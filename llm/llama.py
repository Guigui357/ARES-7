#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cliente llama.cpp (llama serve / llama-server) com:

- deteccao automatica do servidor e do endpoint certo:
  NAO assumimos que base_url + "/v1" existe; testamos /v1/models e /completion
  e escolhemos o modo (openai | legacy) que responder.
- auto-start do servidor ("llama serve" ou "llama-server") quando configurado;
- reconnect sob demanda;
- somente biblioteca padrao (urllib), sem dependencias pesadas.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

from core.logs import debug, log, warn

TAG = "LLM"


class LLMError(Exception):
    """kind: connection | timeout | http | json | choices | other."""

    def __init__(self, message: str, kind: str = "other", status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class LlamaClient:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.model_id: str | None = str(cfg.get("model", "") or "") or None
        self.api_mode: str = str(cfg.get("api_mode", "auto"))  # auto|openai|legacy
        self._server_proc: subprocess.Popen | None = None

    # ---- endereco ------------------------------------------------------------
    @property
    def base_url(self) -> str:
        host = str(self.cfg.get("host", "127.0.0.1"))
        port = int(self.cfg.get("port", 8080))
        if host.startswith("http"):
            return host.rstrip("/")
        return f"http://{host}:{port}"

    # ---- HTTP de baixo nivel --------------------------------------------------
    def _http(self, method: str, path: str, payload: dict | None, timeout: float) -> str:
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = "(corpo ilegivel)"
            message = f"LLM HTTP {exc.code} em {method} {url}\n{body}"
            if exc.code == 400 and re.search(r"context|n_ctx|ctx", body, re.IGNORECASE):
                message += ("\nDica: contexto estourado. Reduza memory.max_tokens_budget "
                            "ou suba o servidor com contexto maior (-c).")
            raise LLMError(message, kind="http", status=exc.code) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ConnectionRefusedError):
                raise LLMError(f"Conexao recusada em {self.base_url} (servidor offline)", kind="connection") from exc
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise LLMError(f"Timeout ao conectar em {url}", kind="timeout") from exc
            raise LLMError(f"Erro de rede em {url}: {reason!r}", kind="connection") from exc
        except TimeoutError as exc:
            raise LLMError(f"Timeout aguardando {url}", kind="timeout") from exc
        except (ConnectionError, OSError) as exc:
            raise LLMError(f"Erro de E/S em {url}: {exc!r}", kind="connection") from exc

    # ---- descoberta de endpoint ----------------------------------------------
    def _detect_api_mode(self) -> str:
        """Descobre se o servidor fala OpenAI (/v1/...) ou legado (/completion)."""
        if self.api_mode in ("openai", "legacy"):
            return self.api_mode
        try:
            self._http("GET", "/v1/models", None, 4)
            self.api_mode = "openai"
            debug(TAG, "endpoint detectado: OpenAI-compatible (/v1)")
        except LLMError as exc:
            if exc.kind == "http":
                try:
                    self._http("GET", "/health", None, 4)
                    self.api_mode = "legacy"
                    debug(TAG, "endpoint detectado: legado (/completion)")
                except LLMError:
                    self.api_mode = "openai"  # padrao mais comum hoje
            else:
                raise
        return self.api_mode

    @staticmethod
    def _model_from_body(body: str) -> str | None:
        try:
            data = json.loads(body)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        items = data.get("data") or data.get("models") or []
        if items and isinstance(items[0], dict):
            for key in ("id", "model", "name"):
                value = items[0].get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(data.get("default_generation_settings"), dict):
            return "llama.cpp"
        return None

    def discover_model(self) -> str | None:
        if self.model_id:
            return self.model_id
        try:
            body = self._http("GET", "/v1/models", None, 5)
        except LLMError:
            return None
        self.model_id = self._model_from_body(body)
        return self.model_id

    # ---- status / autostart / reconnect --------------------------------------
    def probe(self) -> tuple[bool, str | None, str | None]:
        """(online, modelo, erro). Erro HTTP ainda conta como servidor vivo."""
        for path in ("/v1/models", "/health"):
            try:
                body = self._http("GET", path, None, 3)
                model = self._model_from_body(body) or self.model_id
                if model:
                    self.model_id = model
                return True, model, None
            except LLMError as exc:
                if exc.kind == "http":
                    return True, None, str(exc)
        return False, None, "servidor offline"

    def _find_server_cmd(self) -> list[str] | None:
        """Monta o comando de auto-start do servidor llama.cpp."""
        model = str(self.cfg.get("server_model", "") or "")
        if not model:
            return None
        binary = str(self.cfg.get("server_bin", "") or "")
        candidates = [binary] if binary else []
        candidates += ["llama-server", "llama", "server"]
        exe = None
        for name in candidates:
            if not name:
                continue
            exe = shutil.which(name) or (name if os.path.isfile(name) else None)
            if exe:
                break
        if not exe:
            return None
        base = os.path.basename(exe)
        if base == "llama":  # comando moderno: llama serve
            cmd = [exe, "serve", "-m", model]
        else:
            cmd = [exe, "-m", model]
        cmd += ["--host", str(self.cfg.get("host", "127.0.0.1")),
                "--port", str(self.cfg.get("port", 8080)),
                "-c", str(self.cfg.get("server_ctx", 2048)),
                "-t", str(self.cfg.get("server_threads", 2))]
        return cmd

    def ensure_online(self, wait_seconds: float = 45.0) -> tuple[bool, str | None]:
        """Garante servidor online; se autostart estiver ativo, tenta subir um."""
        online, model, _ = self.probe()
        if online:
            return True, model
        if not self.cfg.get("autostart", True):
            return False, None
        if self._server_proc is not None and self._server_proc.poll() is None:
            pass  # ja estamos subindo
        else:
            cmd = self._find_server_cmd()
            if not cmd:
                warn(TAG, "autostart sem servidor/modelo configurado (llm.server_bin / llm.server_model)")
                return False, None
            log(TAG, "subindo servidor llama.cpp: " + " ".join(cmd))
            try:
                self._server_proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                warn(TAG, f"falha ao iniciar servidor: {exc!r}")
                return False, None
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            online, model, _ = self.probe()
            if online:
                log(TAG, "servidor llama.cpp online")
                return True, model
            if self._server_proc and self._server_proc.poll() is not None:
                return False, None  # processo morreu
            time.sleep(1.0)
        return False, None

    def reconnect(self) -> tuple[bool, str | None]:
        """Forca nova deteccao (botao RECONNECT da GUI)."""
        self.model_id = str(self.cfg.get("model", "") or "") or None
        if self.api_mode != "auto":
            pass
        else:
            self.api_mode = "auto"
        return self.ensure_online(wait_seconds=8)

    # ---- chat ------------------------------------------------------------------
    def _parse_openai_reply(self, body: str) -> str:
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON invalido do llama.cpp: {exc}\n{body[:500]}", kind="json") from exc
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices or not isinstance(choices, list):
            raise LLMError(f"Resposta sem choices.\n{body[:500]}", kind="choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            content = first.get("text") if isinstance(first.get("text"), str) else ""
        if not content.strip():
            raise LLMError(f"Resposta vazia.\n{body[:500]}", kind="choices")
        return content.strip()

    def chat(self, messages: list[dict]) -> str:
        """Envia mensagens ja montadas (ContextManager) e retorna a resposta."""
        online, _model, _err = self.probe()
        if not online:
            online, _model = self.ensure_online()
        if not online:
            raise LLMError("Servidor llama.cpp offline e nao foi possivel iniciar.", kind="connection")
        mode = self._detect_api_mode()
        timeout = float(self.cfg.get("timeout", 180))
        if mode == "legacy":
            prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant:"
            payload = {"prompt": prompt,
                       "n_predict": int(self.cfg.get("max_tokens", 256)),
                       "temperature": float(self.cfg.get("temperature", 0.7))}
            log(TAG, "Qwen request (legacy /completion)")
            body = self._http("POST", "/completion", payload, timeout)
            try:
                content = json.loads(body).get("content", "")
            except ValueError as exc:
                raise LLMError(f"JSON invalido: {exc}", kind="json") from exc
            if not str(content).strip():
                raise LLMError("Resposta vazia do /completion.", kind="choices")
            return str(content).strip()
        payload: dict = {
            "messages": messages,
            "temperature": float(self.cfg.get("temperature", 0.7)),
            "max_tokens": int(self.cfg.get("max_tokens", 256)),
            "stream": False,
        }
        model = self.discover_model()
        if model:
            payload["model"] = model
        log(TAG, "Qwen request (/v1/chat/completions)")
        try:
            body = self._http("POST", "/v1/chat/completions", payload, timeout)
        except LLMError as exc:
            if exc.status == 404:
                # este servidor nao fala OpenAI; muda para o legado e tenta de novo
                warn(TAG, "/v1/chat/completions retornou 404; usando /completion")
                self.api_mode = "legacy"
                return self.chat(messages)
            raise
        reply = self._parse_openai_reply(body)
        log(TAG, "resposta recebida")
        return reply
