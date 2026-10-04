#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor remoto do ARES7 (HTTP, biblioteca padrao).

CELULAR/OUTRO PC -> HTTP -> ARES7 SERVER -> CORE

- autenticacao por token (header "X-Ares7-Token" ou ?token=)
- NUNCA exponha sem token; para LAN use host 0.0.0.0 + token forte
- serve a interface web estatica de web/
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core.config import PROJECT_DIR
from core.logs import log, warn

TAG = "REMOTE"

WEB_DIR = os.path.join(PROJECT_DIR, "web")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
                 ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml"}


def make_handler(ares, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Ares7Remote/1.0"

        def log_message(self, fmt, *args):  # silencia o log padrao
            log(TAG, fmt % args)

        # ---- auth -----------------------------------------------------------------
        def _authorized(self) -> bool:
            if self.headers.get("X-Ares7-Token", "") == token:
                return True
            query = parse_qs(urlparse(self.path).query)
            return query.get("token", [""])[0] == token

        def _reject(self) -> None:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "token invalido ou ausente"}')

        def _json(self, data: dict, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8", errors="replace"))
            except ValueError:
                return {}

        # ---- rotas GET --------------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path.startswith("/app.") or path.startswith("/style"):
                self._serve_static(path)
                return
            if not self._authorized():
                self._reject()
                return
            if path == "/api/status":
                st = ares.collect_status()
                gb = 1024 ** 3
                self._json({
                    "state": ares.state,
                    "cpu": st["cpu"],
                    "ram_used_gb": round(st["ram_used"] / gb, 2) if st["ram_total"] else None,
                    "ram_total_gb": round(st["ram_total"] / gb, 2) if st["ram_total"] else None,
                    "temp": st["temp"],
                    "battery": st["battery"],
                    "whisper": bool(st["whisper_ok"]),
                    "llm": bool(st["llm_online"]),
                    "llm_model": st["llm_model"],
                    "piper": bool(st["piper_ready"]),
                    "tts_mode": st["tts_mode"],
                    "mic": st["mic_device"],
                })
            elif path == "/api/devices":
                self._json({"devices": ares.list_input_devices()})
            else:
                self._json({"error": "rota desconhecida"}, 404)

        # ---- rotas POST ----------------------------------------------------------------
        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized():
                self._reject()
                return
            payload = self._body()
            if parsed.path == "/api/chat":
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._json({"error": "texto vazio"}, 400)
                    return
                replies: list[str] = []
                old_emit = ares.emit
                done = threading.Event()

                def capture(kind: str, data) -> None:
                    old_emit(kind, data)
                    if kind == "ares":
                        replies.append(str(data))
                    if kind == "state" and data in ("READY", "ERROR"):
                        done.set()

                ares.emit = capture
                try:
                    if ares.run_async(ares.handle_text, text, False):
                        done.wait(timeout=240)
                finally:
                    ares.emit = old_emit
                self._json({"reply": replies[-1] if replies else "", "state": ares.state})
            elif parsed.path == "/api/listen":
                started = ares.run_async(ares.voice_turn)
                self._json({"started": started})
            elif parsed.path == "/api/stop":
                ares.vad.stop_event.set()
                self._json({"stopped": True})
            elif parsed.path == "/api/reconnect":
                self._json({"message": ares.reconnect_llm()})
            elif parsed.path == "/api/tts":
                ares.speak_enabled = bool(payload.get("enabled", True))
                self._json({"tts": ares.speak_enabled})
            else:
                self._json({"error": "rota desconhecida"}, 404)

        # ---- estaticos ---------------------------------------------------------------------
        def _serve_static(self, path: str) -> None:
            if path == "/":
                path = "/index.html"
            safe = os.path.normpath(path).lstrip("/")
            full = os.path.join(WEB_DIR, safe)
            if not full.startswith(WEB_DIR) or not os.path.isfile(full):
                self.send_response(404)
                self.end_headers()
                return
            with open(full, "rb") as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1], "text/plain"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class RemoteServer:
    def __init__(self, ares, cfg: dict) -> None:
        self.ares = ares
        self.host = str(cfg.get("host", "127.0.0.1"))
        self.port = int(cfg.get("port", 8765))
        self.token = str(cfg.get("token", ""))
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> bool:
        if not self.token or self.token == "troque-este-token":
            warn(TAG, "token padrao/vazio! Defina remote.token no config.json antes de expor na LAN.")
        handler = make_handler(self.ares, self.token)
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as exc:
            warn(TAG, f"nao foi possivel abrir {self.host}:{self.port}: {exc}")
            return False
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        log(TAG, f"servidor remoto em http://{self.host}:{self.port}")
        return True

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
