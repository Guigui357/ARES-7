#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STT via whisper.cpp.

- localiza o binario automaticamente (whisper-cli, whisper-cpp, main, etc.)
- localiza o modelo ggml-*.bin em pastas comuns (sem caminho hardcoded)
- caminho configuravel via config.json ou ARES7_WHISPER_BIN / ARES7_WHISPER_MODEL
- timeout, logs claros e sem travamentos
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

from core.logs import debug, log

TAG = "STT"

BINARY_CANDIDATES = ("whisper-cli", "whisper-cpp", "whisper", "main", "whisper_main")
MODEL_PATTERNS = ("ggml-tiny*.bin", "ggml-base*.bin", "ggml-small*.bin", "ggml-*.bin")


def _search_dirs() -> list[str]:
    from core.config import HOME, ARES7_HOME, PROJECT_DIR
    return [
        os.path.join(PROJECT_DIR, "models"),
        os.path.join(ARES7_HOME, "models"),
        os.path.join(HOME, "models"),
        os.path.join(HOME, ".cache", "whisper"),
        os.path.join(HOME, ".local", "share", "whisper.cpp"),
        "/usr/local/share/whisper.cpp",
        "/opt/whisper.cpp/models",
    ]


def find_binary(configured: str = "") -> str | None:
    if configured:
        resolved = shutil.which(configured) or (configured if os.path.isfile(configured) else None)
        return resolved
    for name in BINARY_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def find_model(configured: str = "") -> str | None:
    if configured and os.path.isfile(configured):
        return configured
    if configured:
        # talvez seja so o nome do arquivo
        for directory in _search_dirs():
            candidate = os.path.join(directory, configured)
            if os.path.isfile(candidate):
                return candidate
    for directory in _search_dirs():
        for pattern in MODEL_PATTERNS:
            matches = sorted(glob.glob(os.path.join(directory, "**", pattern), recursive=True))
            if matches:
                return matches[0]  # tiny primeiro (menor)
    return None


def clean_transcript(raw: str) -> str:
    """Remove marcacoes como [BLANK_AUDIO] e (musica) e junta as linhas."""
    no_marks = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", raw)
    return re.sub(r"\s+", " ", no_marks).strip()


class WhisperSTT:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def binary(self) -> str | None:
        return find_binary(str(self.cfg.get("binary", "")))

    def model(self) -> str | None:
        return find_model(str(self.cfg.get("model", "")))

    def ready(self) -> bool:
        return self.binary() is not None and self.model() is not None

    def transcribe(self, wav_path: str) -> tuple[str, str | None]:
        """Retorna (texto, erro). Se erro != None, texto e vazio."""
        cli = self.binary()
        if not cli:
            return "", ("whisper-cli nao encontrado. Compile o whisper.cpp "
                        "ou aponte 'whisper.binary' no config.json.")
        model = self.model()
        if not model:
            return "", ("Modelo do Whisper nao encontrado. Baixe ggml-tiny.bin "
                        "para ./models ou aponte 'whisper.model' no config.json.")
        if not os.path.isfile(wav_path):
            return "", f"Arquivo de audio nao encontrado: {wav_path}"
        threads = max(1, min(int(self.cfg.get("threads", 2)), os.cpu_count() or 2))
        timeout = int(self.cfg.get("timeout", 120))
        cmd = [cli, "-m", model, "-f", wav_path, "-nt", "-t", str(threads)]
        lang = str(self.cfg.get("lang", "") or "")
        if lang:
            cmd += ["-l", lang]
        debug(TAG, " ".join(cmd))
        log(TAG, "Whisper processando...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return "", f"whisper-cli excedeu {timeout}s."
        except OSError as exc:
            return "", f"Falha ao executar whisper-cli: {exc}"
        if result.returncode != 0:
            tail = (result.stderr or "").strip()[-600:]
            return "", f"whisper-cli falhou (codigo {result.returncode}):\n{tail}"
        text = clean_transcript(result.stdout)
        log(TAG, f'"{text}"' if text else "(sem fala reconhecida)")
        return text, None
