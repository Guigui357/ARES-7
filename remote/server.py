#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor remoto do ARES7 (HTTP, biblioteca padrao).

CELULAR/OUTRO PC -> HTTP -> ARES7 SERVER -> CORE

- autenticacao por token (header "X-Ares7-Token" ou ?token=)
- NUNCA exponha sem token; para LAN use host 0.0.0.0 + token forte
- serve a interface web estatica de web/
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core.config import ARES7_HOME, PROJECT_DIR, VERSION
from core.logs import log, warn

TAG = "REMOTE"

WEB_DIR = os.path.join(PROJECT_DIR, "web")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
}

def make_handler(ares, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Ares7Remote/1.0"

        def log_message(self, fmt, *args):  # silencia o log padrao
            log(TAG, fmt % args)

        # ---- auth -----------------------------------------------------------------
        def _authorized(self) -> bool:
            # Nunca autoriza requisições se o servidor estiver sem um token válido.
            if not token or token == "troque-este-token":
                return False
            supplied = self.headers.get("X-Ares7-Token", "")
            if hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                return True
            # Mantido por compatibilidade com clientes antigos; prefira o cabeçalho.
            query = parse_qs(urlparse(self.path).query)
            supplied = query.get("token", [""])[0]
            return hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))

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
            if path in (
                "/",
                "/index.html",
                "/app.js",
                "/style.css",
                "/manifest.webmanifest",
                "/sw.js",
                "/icon.svg",
            ):
                self._serve_static(path)
                return
            if not self._authorized():
                self._reject()
                return
            if path == "/api/ping":
                self._json({"ok": True, "name": "ARES-7", "version": VERSION})
            elif path == "/api/status":
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
            elif path == "/api/notes":
                self._json({"notes": self._read_notes()})
            elif path == "/api/memory":
                facts: list[dict] = []
                if getattr(ares, "memory", None):
                    for fact_id, content in ares.memory.list(limit=30):
                        facts.append({"id": fact_id, "content": content})
                self._json({"facts": facts})
            elif path == "/api/daemon":
                self._json(self._daemon_status())
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
                done = threading.Event()

                def capture(kind: str, data) -> None:
                    if kind == "ares":
                        replies.append(str(data))
                    if kind == "state" and data in ("READY", "ERROR"):
                        done.set()

                # Ouvinte dedicado: nao substitui o emit global, entao a GUI
                # e outros consumidores continuam recebendo os eventos.
                ares.add_listener(capture)
                try:
                    started = ares.run_async(ares.handle_text, text, False)
                    if not started:
                        self._json({"error": "O ARES-7 esta ocupado com outra tarefa. "
                                             "Tente de novo em instantes."}, 409)
                        return
                    done.wait(timeout=240)
                finally:
                    ares.remove_listener(capture)
                self._json({"reply": replies[-1] if replies else "", "state": ares.state})
            elif parsed.path == "/api/listen":
                started = ares.run_async(ares.voice_turn)
                self._json({"started": started})
            elif parsed.path == "/api/stop":
                ares.vad.stop_event.set()
                self._json({"stopped": True})
            elif parsed.path == "/api/clear":
                ares.context.reset()
                self._json({"cleared": True})
            elif parsed.path == "/api/reconnect":
                self._json({"message": ares.reconnect_llm()})
            elif parsed.path == "/api/tts":
                ares.speak_enabled = bool(payload.get("enabled", True))
                self._json({"tts": ares.speak_enabled})
            elif parsed.path == "/api/notify":
                msg = str(payload.get("message", "")).strip()
                if msg:
                    ares.emit("system", msg)
                    try:
                        ares.announce(msg)
                    except Exception:
                        pass
                self._json({"ok": True})
            elif parsed.path == "/api/run":
                action = str(payload.get("action", "")).strip()
                params = payload.get("params") or {}
                if not action:
                    self._json({"error": "action vazio"}, 400)
                    return
                try:
                    from core.autonomous import AutonomousAres
                    auto = getattr(ares, "_auto", None) or AutonomousAres(config=None, core=ares)
                    if not hasattr(ares, "_auto"):
                        ares._auto = auto
                    res = auto.run_autonomous(f"execute {action} " + json.dumps(params, ensure_ascii=False), skip_local=True) if False else None
                except Exception:
                    res = None
                # Executa direto via ferramenta
                try:
                    tool = auto.tools.get(action)
                    if tool is None:
                        self._json({"error": "acao desconhecida"}, 404)
                        return
                    result = tool.run(**(params if isinstance(params, dict) else {}))
                    self._json({"ok": True, "result": result})
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"error": "rota desconhecida"}, 404)

        # ---- estaticos ---------------------------------------------------------------------
        def _read_notes(self) -> list[str]:
            """Le as notas salvas pelo ARES-7."""
            try:
                with open(ares.notes_path, "r", encoding="utf-8", errors="replace") as handle:
                    raw = handle.read()
            except OSError:
                return []
            return [line.strip() for line in raw.splitlines() if line.strip()][-30:]

        def _daemon_status(self) -> dict:
            """Estado do daemon: pendencias, ultimas linhas do log e config."""
            pending_path = os.path.join(ARES7_HOME, "autonomous_pending.json")
            pending = None
            if os.path.isfile(pending_path):
                try:
                    with open(pending_path, "r", encoding="utf-8") as handle:
                        pending = json.load(handle)
                except (OSError, ValueError):
                    pending = None

            log_lines: list[str] = []
            log_path = os.path.join(ARES7_HOME, "daemon.log")
            if os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                        log_lines = [line.rstrip() for line in handle if line.strip()][-20:]
                except OSError:
                    log_lines = []

            return {
                "pending": pending,
                "log": log_lines,
                "enabled": bool(ares.config.get("daemon", "enabled", False)),
                "interval": ares.config.get("daemon", "interval", 60),
            }

        def _serve_static(self, path: str) -> None:
            if path == "/":
                path = "/index.html"
            safe = os.path.normpath(path).lstrip("/")
            full = os.path.normpath(os.path.join(WEB_DIR, safe))
            # commonpath (e nao startswith) impede escapar de web/: um irmao
            # chamado "web_backup" comecaria com "web" e passaria na comparacao.
            try:
                inside = os.path.commonpath([WEB_DIR, full]) == WEB_DIR
            except ValueError:
                inside = False
            if not inside or not os.path.isfile(full):
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
        self.token = str(cfg.get("token", "")).strip()
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> bool:
        if not self.token or self.token == "troque-este-token":
            warn(
                TAG,
                "servidor remoto nao iniciado: token vazio ou padrao. "
                "Defina um token forte em remote.token no config.json.",
            )
            return False
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
