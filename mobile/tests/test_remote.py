#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do servidor remoto e do modelo de ouvintes de eventos.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.assistant import Ares7  # noqa: E402
from core.config import VERSION, Config  # noqa: E402

TOKEN = "token-de-teste-123456"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakeAres:
    """Nucleo minimo para exercitar o servidor HTTP."""

    def __init__(self) -> None:
        self.state = "READY"
        self.speak_enabled = True
        self.busy_forever = False
        self.events: list[tuple[str, object]] = []
        self.config = Config()
        self.notes_path = "/tmp/ares7-test-notas.txt"
        self.memory = None
        self.vad = type("V", (), {"stop_event": threading.Event()})()
        self.context = type("C", (), {"reset": lambda self: None})()

    # --- eventos (modelo de ouvintes) ---
    def add_listener(self, listener) -> None:
        if listener not in self.events:
            self.events.append(listener)

    def remove_listener(self, listener) -> None:
        if listener in self.events:
            self.events.remove(listener)

    def emit(self, kind: str, payload=None) -> None:
        for listener in list(self.events):
            listener(kind, payload)

    # --- acoes do servidor ---
    def collect_status(self) -> dict:
        return {"cpu": 3.5, "ram_used": 2 * 1024 ** 3, "ram_total": 8 * 1024 ** 3,
                "temp": 45.0, "battery": "", "whisper_ok": True, "llm_online": True,
                "llm_model": "qwen2.5-3b", "piper_ready": True, "tts_mode": "piper",
                "tts_fallback": "nenhum TTS instalado", "mic_device": "default",
                "low_memory": False}

    def list_input_devices(self) -> str:
        return "default"

    def run_async(self, func, *args) -> bool:
        if self.busy_forever:
            return False
        def runner():
            func(*args)
        threading.Thread(target=runner, daemon=True).start()
        return True

    def handle_text(self, text: str, from_voice: bool = False) -> None:
        self.emit("user_text", text)
        self.emit("ares", f"recebido: {text}")
        self.set_state("READY")

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", state)

    def voice_turn(self) -> None:
        self.emit("state", "LISTENING")

    def reconnect_llm(self) -> str:
        return "llama.cpp online"


class TestServidorRemoto(unittest.TestCase):
    """Roda o servidor HTTP de verdade numa porta livre."""

    @classmethod
    def setUpClass(cls) -> None:
        from remote.server import RemoteServer
        cls.ares = FakeAres()
        cls.server = RemoteServer(cls.ares, {"host": "127.0.0.1", "port": free_port(),
                                             "token": TOKEN})
        assert cls.server.start(), "nao consegui subir o servidor"
        cls.base = f"http://127.0.0.1:{cls.server.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def get(self, path: str, token: str = TOKEN) -> tuple[int, str]:
        req = urllib.request.Request(self.base + path)
        if token:
            req.add_header("X-Ares7-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def post(self, path: str, payload: dict | None = None, token: str = TOKEN) -> tuple[int, str]:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-Ares7-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    # --- autenticacao ---
    def test_sem_token_responde_401(self):
        status, _ = self.get("/api/status", token="")
        self.assertEqual(status, 401)

    def test_token_errado_responde_401(self):
        status, _ = self.get("/api/status", token="errado")
        self.assertEqual(status, 401)

    def test_token_certo_responde_200(self):
        status, _ = self.get("/api/status")
        self.assertEqual(status, 200)

    # --- rotas ---
    def test_ping_traz_a_versao_do_codigo(self):
        status, body = self.get("/api/ping")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["version"], VERSION)

    def test_status(self):
        status, body = self.get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("cpu", data)
        self.assertIn("ram_total_gb", data)

    def test_notes(self):
        status, body = self.get("/api/notes")
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body)["notes"], list)

    def test_memory(self):
        status, body = self.get("/api/memory")
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body)["facts"], list)

    def test_daemon(self):
        status, body = self.get("/api/daemon")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("pending", data)
        self.assertIn("log", data)
        self.assertIn("enabled", data)

    def test_rota_desconhecida_404(self):
        status, _ = self.get("/api/nao-existe")
        self.assertEqual(status, 404)

    # --- chat ---
    def test_chat_devolve_a_resposta(self):
        status, body = self.post("/api/chat", {"text": "ola"})
        self.assertEqual(status, 200)
        self.assertIn("recebido: ola", json.loads(body)["reply"])

    def test_chat_vazio_400(self):
        status, _ = self.post("/api/chat", {"text": "   "})
        self.assertEqual(status, 400)

    def test_chat_ocupado_responde_409(self):
        # Com o nucleo ocupado, o servidor precisa avisar em vez de devolver
        # uma resposta vazia sem explicacao.
        self.ares.busy_forever = True
        try:
            status, body = self.post("/api/chat", {"text": "ola"})
            self.assertEqual(status, 409)
            self.assertIn("ocupado", json.loads(body)["error"].lower())
        finally:
            self.ares.busy_forever = False

    def test_chat_nao_engole_os_eventos_de_outros_ouvintes(self):
        # O bug antigo: o servidor substituia ares.emit e os outros
        # consumidores (GUI) perdiam os eventos.
        other: list[tuple[str, object]] = []
        self.ares.add_listener(lambda k, p: other.append((k, p)))
        try:
            self.post("/api/chat", {"text": "ping"})
        finally:
            self.ares.events = [e for e in self.ares.events
                                if getattr(e, "__name__", "") != "<lambda>"]
        self.assertTrue(any(kind == "ares" for kind, _ in other),
                        "o ouvinte externo nao recebeu o evento")

    # --- estaticos ---
    def test_serve_a_interface(self):
        status, body = self.get("/", token="")
        self.assertEqual(status, 200)
        self.assertIn("ARES-7", body)

    def test_arquivo_estatico(self):
        status, body = self.get("/style.css", token="")
        self.assertEqual(status, 200)
        self.assertIn("aurora", body)

    def test_nao_serve_arquivo_fora_de_web(self):
        # Tentativas de escapar de web/ nao podem servir arquivo nenhum.
        for path in ("/../core/config.py", "/../../etc/passwd", "/./../ares.py"):
            status, body = self.get(path, token="")
            self.assertNotIn("DEFAULT_CONFIG", body)
            self.assertNotIn("root:", body)
            self.assertIn(status, (401, 404))


class TestModeloDeOuvintes(unittest.TestCase):
    """O nucleo entrega o evento para todos os ouvintes, sem se atropelar."""

    def setUp(self) -> None:
        config = Config()
        config.set("llm", "autostart", False)
        self.ares = Ares7(config)

    def test_varios_ouvintes_recebem(self):
        a: list = []
        b: list = []
        self.ares.add_listener(lambda k, p: a.append(k))
        self.ares.add_listener(lambda k, p: b.append(k))
        self.ares.emit("system", "oi")
        self.assertEqual(a, ["system"])
        self.assertEqual(b, ["system"])

    def test_ouvinte_removido_para_de_receber(self):
        got: list = []
        listener = lambda k, p: got.append(k)  # noqa: E731
        self.ares.add_listener(listener)
        self.ares.emit("system", "1")
        self.ares.remove_listener(listener)
        self.ares.emit("system", "2")
        self.assertEqual(got, ["system"])

    def test_ouvinte_que_quebra_nao_derruba_os_outros(self):
        got: list = []

        def ruim(_k, _p):
            raise RuntimeError("falhou")

        self.ares.add_listener(ruim)
        self.ares.add_listener(lambda k, p: got.append(k))
        self.ares.emit("system", "oi")
        self.assertEqual(got, ["system"])

    def test_registrar_duas_vezes_nao_duplica(self):
        got: list = []
        listener = lambda k, p: got.append(k)  # noqa: E731
        self.ares.add_listener(listener)
        self.ares.add_listener(listener)
        self.ares.emit("system", "oi")
        self.assertEqual(got, ["system"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
