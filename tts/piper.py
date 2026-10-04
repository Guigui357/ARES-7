#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TTS: Piper primeiro; fallback (espeak-ng/espeak/spd-say) se o Piper falhar.

Logs explicitos: [TTS] Piper iniciado / [TTS] Piper indisponivel / fallback.
Deteccao: binario no PATH ou caminho configurado; pacote python `piper`;
modelo .onnx (+ .onnx.json) em pastas comuns ou caminho configurado.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from audio.player import play
from core.logs import log, warn

TAG = "TTS"

MODEL_PATTERNS = ("*pt_BR*.onnx", "*pt*.onnx", "*.onnx")


def _search_dirs() -> list[str]:
    from core.config import HOME, ARES7_HOME, PROJECT_DIR
    return [
        os.path.join(PROJECT_DIR, "models"),
        os.path.join(ARES7_HOME, "models"),
        os.path.join(ARES7_HOME, "voices"),
        os.path.join(HOME, ".local", "share", "piper", "voices"),
        "/usr/local/share/piper/voices",
    ]


def clean_for_tts(text: str, max_chars: int) -> str:
    t = re.sub(r"[*_#`>]+", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0]
    return t


def find_piper_binary(configured: str = "") -> str | None:
    if configured:
        return shutil.which(configured) or (configured if os.path.isfile(configured) else None)
    return shutil.which("piper")


def find_piper_model(configured: str = "") -> str | None:
    if configured and os.path.isfile(configured):
        return configured
    if configured:
        for directory in _search_dirs():
            candidate = os.path.join(directory, configured)
            if os.path.isfile(candidate):
                return candidate
    for directory in _search_dirs():
        for pattern in MODEL_PATTERNS:
            matches = sorted(glob.glob(os.path.join(directory, "**", pattern), recursive=True))
            for match in matches:
                if os.path.isfile(match + ".json"):
                    return match
    return None


class TTS:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()

    # ---- deteccao -------------------------------------------------------------
    def piper_binary(self) -> str | None:
        return find_piper_binary(str(self.cfg.get("binary", "")))

    def piper_model(self) -> str | None:
        return find_piper_model(str(self.cfg.get("model", "")))

    def piper_ready(self) -> bool:
        if str(self.cfg.get("engine", "piper")) != "piper":
            return False
        binary = self.piper_binary()
        if not binary:
            return False
        model = self.piper_model()
        return bool(model and os.path.isfile(model + ".json"))

    def mode(self) -> str:
        return "Piper" if self.piper_ready() else "fallback"

    @staticmethod
    def fallback_name() -> str:
        for name in ("espeak-ng", "espeak", "spd-say"):
            if shutil.which(name):
                return name
        return "nenhum TTS instalado"

    # ---- sintese ----------------------------------------------------------------
    def _speak_piper(self, text: str) -> bool:
        binary = self.piper_binary()
        model = self.piper_model()
        if not binary or not model:
            log(TAG, "Piper indisponivel")
            return False
        fd, wav_path = tempfile.mkstemp(prefix="ares_tts_", suffix=".wav")
        os.close(fd)
        try:
            log(TAG, "Piper sintetizando")
            result = subprocess.run(
                [binary, "--model", model, "--output_file", wav_path],
                input=text.encode("utf-8"), capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as exc:
            warn(TAG, f"Piper falhou: {exc!r}")
            return False
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace").strip()[-400:]
            warn(TAG, f"Piper retornou {result.returncode}: {err}")
            return False
        log(TAG, "Piper reproduzindo")
        ok, error = play(wav_path)
        try:
            os.remove(wav_path)
        except OSError:
            pass
        if not ok:
            warn(TAG, f"reproducao falhou: {error}")
        return ok

    def _speak_fallback(self, text: str) -> None:
        name = self.fallback_name()
        log(TAG, f"fallback utilizado: {name}")
        try:
            if name in ("espeak-ng", "espeak"):
                subprocess.run([shutil.which(name) or name, "-v", "pt-br", "--stdin"],
                               input=text, text=True, capture_output=True, timeout=120)
                return
            if name == "spd-say":
                subprocess.run(["spd-say", "-l", "pt", "-w", "--", text],
                               capture_output=True, timeout=120)
                return
        except (subprocess.TimeoutExpired, OSError) as exc:
            warn(TAG, f"fallback falhou: {exc!r}")
            return
        warn(TAG, "Nenhum TTS disponivel. Instale: sudo apt install espeak-ng")

    def speak(self, text: str) -> None:
        text = clean_for_tts(text, int(self.cfg.get("max_chars", 600)))
        if not text:
            return
        with self._lock:  # nunca dois Piper ao mesmo tempo
            engine = str(self.cfg.get("engine", "piper"))
            if engine == "piper" and self.piper_ready() and self._speak_piper(text):
                return
            self._speak_fallback(text)
