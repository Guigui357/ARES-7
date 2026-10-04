#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Carregamento de configuracao do ARES7.

Ordem de prioridade (maior para menor):
  1. variaveis de ambiente ARES7_*
  2. config.json (na pasta do projeto ou em ~/.ares/config.json)
  3. defaults embutidos abaixo

Nada de caminhos hardcoded: strings vazias significam "auto-detectar".
"""
from __future__ import annotations

import copy
import json
import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
ARES7_HOME = os.path.join(HOME, ".ares")

DEFAULTS: dict = {
    "llm": {
        "host": "127.0.0.1",
        "port": 8080,
        "model": "",            # id do modelo; vazio = descobrir via /models
        "api_mode": "auto",     # auto | openai (/v1/chat/completions) | legacy (/completion)
        "autostart": True,      # tentar subir o servidor se estiver offline
        "server_bin": "",       # ex.: llama-server / llama / caminho completo
        "server_model": "",     # .gguf para o autostart
        "server_ctx": 2048,
        "server_threads": 2,
        "temperature": 0.7,
        "max_tokens": 256,
        "timeout": 180,
    },
    "whisper": {
        "binary": "",           # whisper-cli / whisper-cpp / caminho completo
        "model": "",            # ggml-*.bin; vazio = procurar
        "lang": "pt",           # vazio = deixar o whisper decidir
        "threads": 2,
        "timeout": 120,
    },
    "audio": {
        "input": "auto",        # "auto", indice, nome parcial ou device ALSA (plughw:X,Y)
        "output": "auto",
        "sample_rate": 16000,
        "record_seconds": 8,
        "low_peak_threshold": 400,
    },
    "vad": {
        "enabled": True,
        "threshold": 700,       # RMS 0..32768
        "silence_ms": 900,
        "max_seconds": 20,
        "pre_roll_ms": 300,
        "post_roll_ms": 200,
        "min_speech_ms": 400,
    },
    "wake_word": {
        "enabled": False,
        "word": "ares",
        "mode": "push_to_talk",   # continuous | push_to_talk | manual
    },
    "tts": {
        "engine": "piper",
        "model": "",            # .onnx (+ .onnx.json ao lado)
        "binary": "",           # piper / caminho completo
        "max_chars": 600,
    },
    "memory": {
        "enabled": True,
        "max_messages": 8,          # mensagens recentes enviadas ao LLM
        "max_tokens_budget": 1200,  # teto de tokens do prompt (system+historico+msg)
        "db_path": "",              # vazio = ~/.ares/memory.db
    },
    "performance": {
        "low_memory": False,
        "auto_low_memory": True,
        "low_memory_threshold_mb": 700,
    },
    "remote": {
        "enabled": False,
        "host": "127.0.0.1",    # 0.0.0.0 expoe na LAN (use token!)
        "port": 8765,
        "token": "troque-este-token",
    },
}

# mapeamento de variaveis de ambiente -> (secao, chave, tipo)
ENV_MAP = {
    "ARES7_LLM_HOST": ("llm", "host", str),
    "ARES7_LLM_PORT": ("llm", "port", int),
    "ARES7_LLM_MODEL": ("llm", "model", str),
    "ARES7_LLM_BIN": ("llm", "server_bin", str),
    "ARES7_LLM_GGUF": ("llm", "server_model", str),
    "ARES7_LLM_CTX": ("llm", "server_ctx", int),
    "ARES7_WHISPER_BIN": ("whisper", "binary", str),
    "WHISPER_BIN": ("whisper", "binary", str),
    "ARES7_WHISPER_MODEL": ("whisper", "model", str),
    "WHISPER_MODEL": ("whisper", "model", str),
    "ARES7_WHISPER_LANG": ("whisper", "lang", str),
    "ARES7_PIPER_BIN": ("tts", "binary", str),
    "PIPER_BIN": ("tts", "binary", str),
    "ARES7_PIPER_MODEL": ("tts", "model", str),
    "PIPER_MODEL": ("tts", "model", str),
    "ARES7_AUDIO_INPUT": ("audio", "input", str),
    "ARES7_REMOTE_TOKEN": ("remote", "token", str),
    "ARES7_REMOTE_HOST": ("remote", "host", str),
    "ARES7_REMOTE_PORT": ("remote", "port", int),
    "ARES7_LOW_MEMORY": ("performance", "low_memory", "bool"),
    "AUTO_LOW_MEMORY": ("performance", "auto_low_memory", "bool"),
}


def _find_config_file() -> str | None:
    candidates = [
        os.path.join(PROJECT_DIR, "config.json"),
        os.path.join(ARES7_HOME, "config.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    """Acesso central a configuracao. cfg["llm"]["port"], cfg.get(...), etc."""

    def __init__(self, config_path: str | None = None) -> None:
        self.data = copy.deepcopy(DEFAULTS)
        self.path = config_path or _find_config_file()
        if self.path:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    _deep_merge(self.data, loaded)
            except (OSError, ValueError) as exc:
                print(f"[CONFIG] Falha ao ler {self.path}: {exc} (usando defaults)")
        self._apply_env()

    def _apply_env(self) -> None:
        for env, (section, key, kind) in ENV_MAP.items():
            raw = os.environ.get(env)
            if raw is None or raw == "":
                continue
            try:
                if kind == "bool":
                    value: object = raw.strip().lower() in ("1", "true", "yes", "sim", "on")
                else:
                    value = kind(raw)
            except ValueError:
                print(f"[CONFIG] Valor invalido em {env}={raw!r}; ignorado")
                continue
            self.data[section][key] = value

    # acesso comodo ---------------------------------------------------------
    def __getitem__(self, section: str) -> dict:
        return self.data[section]

    def get(self, section: str, key: str, default=None):
        return self.data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value) -> None:
        self.data.setdefault(section, {})[key] = value

    def apply_low_memory(self) -> None:
        """Reduz parametros para o modo de pouca RAM."""
        self.set("llm", "server_ctx", min(1024, int(self.get("llm", "server_ctx", 2048))))
        self.set("llm", "max_tokens", min(128, int(self.get("llm", "max_tokens", 128))))
        self.set("llm", "server_threads", min(2, int(self.get("llm", "server_threads", 2))))
        self.set("whisper", "threads", min(2, int(self.get("whisper", "threads", 2))))
        self.set("memory", "max_messages", min(4, int(self.get("memory", "max_messages", 8))))
        self.set("memory", "max_tokens_budget", min(700, int(self.get("memory", "max_tokens_budget", 1200))))
        self.set("audio", "record_seconds", min(6, int(self.get("audio", "record_seconds", 8))))
        self.set("vad", "max_seconds", min(12, int(self.get("vad", "max_seconds", 20))))
