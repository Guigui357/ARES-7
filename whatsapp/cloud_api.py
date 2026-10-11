#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integração oficial WhatsApp Cloud API para o ARES-7 (stdlib only)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from core.logs import log, warn

TAG = "WHATSAPP"
MAX_BODY = 1_000_000


class WhatsAppCloudAPI:
    """Webhook Meta + envio de texto. Segredos vêm da configuração/ambiente."""

    def __init__(self, ares, cfg: dict) -> None:
        self.ares = ares
        self.cfg = cfg
        self.host = str(cfg.get("host", "127.0.0.1"))
        self.port = int(cfg.get("port", 8766))
        self.verify_token = str(cfg.get("verify_token", ""))
        self.app_secret = str(cfg.get("app_secret", ""))
        self.access_token = str(cfg.get("access_token", ""))
        self.phone_number_id = str(cfg.get("phone_number_id", ""))
        self.api_version = str(cfg.get("api_version", "v23.0"))
        self.allowed_senders = {self._digits(x) for x in cfg.get("allowed_senders", []) if self._digits(x)}
        self._httpd: ThreadingHTTPServer | None = None
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._seen_lock = threading.Lock()

    @staticmethod
    def _digits(value: object) -> str:
        return "".join(ch for ch in str(value) if ch.isdigit())

    def _ready(self) -> bool:
        missing = [name for name, value in (
            ("verify_token", self.verify_token), ("app_secret", self.app_secret),
            ("access_token", self.access_token), ("phone_number_id", self.phone_number_id),
        ) if not value]
        if missing:
            warn(TAG, "configuração incompleta; faltando: " + ", ".join(missing))
            return False
        if not self.allowed_senders:
            warn(TAG, "allowed_senders está vazio; nenhuma mensagem poderá executar comandos.")
        return True

    def start(self) -> bool:
        if not self._ready():
            return False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ARES7WhatsApp/1.0"

            def log_message(self, fmt, *args):
                log(TAG, fmt % args)

            def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/webhook":
                    self._send(404, b"not found")
                    return
                q = parse_qs(parsed.query)
                mode = q.get("hub.mode", [""])[0]
                token = q.get("hub.verify_token", [""])[0]
                challenge = q.get("hub.challenge", [""])[0]
                if mode == "subscribe" and hmac.compare_digest(token, owner.verify_token) and challenge:
                    self._send(200, challenge.encode())
                else:
                    self._send(403, b"forbidden")

            def do_POST(self):
                if urlparse(self.path).path != "/webhook":
                    self._send(404, b"not found")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = MAX_BODY + 1
                if length <= 0 or length > MAX_BODY:
                    self._send(413 if length > MAX_BODY else 400, b"invalid body")
                    return
                raw = self.rfile.read(length)
                signature = self.headers.get("X-Hub-Signature-256", "")
                expected = "sha256=" + hmac.new(owner.app_secret.encode(), raw, hashlib.sha256).hexdigest()
                if not signature or not hmac.compare_digest(signature, expected):
                    self._send(401, b"invalid signature")
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send(400, b"invalid json")
                    return
                # ACK rápido: processamento e chamadas à API ocorrem em background.
                self._send(200, b"EVENT_RECEIVED")
                threading.Thread(target=owner._handle_event, args=(payload,), daemon=True).start()

        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
            log(TAG, f"webhook ativo em http://{self.host}:{self.port}/webhook")
            return True
        except OSError as exc:
            warn(TAG, f"não foi possível abrir {self.host}:{self.port}: {exc}")
            return False

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def _handle_event(self, payload: dict) -> None:
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                if change.get("field") != "messages":
                    continue
                for message in value.get("messages", []) or []:
                    if message.get("type") != "text":
                        continue
                    message_id = str(message.get("id", ""))
                    sender = self._digits(message.get("from", ""))
                    text = str((message.get("text") or {}).get("body", "")).strip()
                    if not message_id or not sender or not text or not self._remember_once(message_id):
                        continue
                    if sender not in self.allowed_senders:
                        warn(TAG, f"mensagem ignorada de remetente não autorizado: {sender}")
                        continue
                    reply = self._ask_ares(text)
                    if reply:
                        try:
                            self.send_text(sender, reply[:4000])
                        except Exception as exc:
                            warn(TAG, f"falha ao responder no WhatsApp: {exc}")

    def _remember_once(self, message_id: str) -> bool:
        with self._seen_lock:
            if message_id in self._seen:
                return False
            self._seen.add(message_id)
            self._seen_order.append(message_id)
            if len(self._seen_order) > 2000:
                self._seen.discard(self._seen_order.popleft())
            return True

    def _ask_ares(self, text: str) -> str:
        # Não disputa o núcleo com uma tarefa local já em andamento.
        if not self.ares.busy.acquire(blocking=False):
            return "Estou ocupado com outra tarefa. Tente novamente em alguns instantes."
        old_emit = self.ares.emit
        old_speak = self.ares.speak_enabled
        replies: list[str] = []

        def capture(kind: str, data):
            old_emit(kind, data)
            if kind == "ares":
                replies.append(str(data))

        try:
            self.ares.emit = capture
            self.ares.speak_enabled = False
            self.ares.handle_text(text, from_voice=False)
            return replies[-1] if replies else "Não consegui gerar uma resposta."
        except Exception as exc:
            warn(TAG, f"erro no núcleo ARES-7: {exc!r}")
            return "O ARES-7 encontrou um erro ao processar a mensagem."
        finally:
            self.ares.emit = old_emit
            self.ares.speak_enabled = old_speak
            self.ares.busy.release()

    def send_text(self, recipient: str, text: str) -> dict:
        if not self.access_token or not self.phone_number_id:
            raise RuntimeError("Configure access_token e phone_number_id.")
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        body = json.dumps({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._digits(recipient),
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }).encode("utf-8")
        request = Request(url, data=body, headers={
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }, method="POST")
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", errors="replace")
            raise RuntimeError(f"Meta Graph API HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"não foi possível acessar a Meta Graph API: {exc}") from exc
