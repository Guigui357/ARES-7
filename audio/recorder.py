#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gravacao de audio via arecord, com device configuravel/auto-detectado."""
from __future__ import annotations

import array
import os
import shutil
import subprocess
import sys
import tempfile
import wave

from audio.devices import resolve_input
from core.logs import debug, log, warn

TAG = "AUDIO"


def wav_peak(path: str) -> int:
    """Maior amplitude absoluta (0..32768) de um WAV PCM de 16 bits."""
    with wave.open(path, "rb") as wav_file:
        if wav_file.getsampwidth() != 2:
            raise ValueError(f"WAV com {wav_file.getsampwidth() * 8} bits (esperado 16)")
        frames = wav_file.readframes(wav_file.getnframes())
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0
    return max(max(samples), -min(samples))


class Recorder:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._device: str | None = None

    @property
    def device(self) -> str:
        if self._device is None:
            self._device = resolve_input(str(self.cfg.get("input", "auto")))
        return self._device

    def refresh_device(self) -> str:
        """Re-resolve o dispositivo (troca de microfone, hotplug etc.)."""
        self._device = None
        return self.device

    def record(self, seconds: int | None = None, path: str | None = None) -> tuple[str | None, str | None]:
        """Grava `seconds` segundos. Retorna (caminho_wav, erro)."""
        seconds = seconds or int(self.cfg.get("record_seconds", 8))
        rate = int(self.cfg.get("sample_rate", 16000))
        arecord = shutil.which("arecord")
        if not arecord:
            return None, "arecord nao encontrado. Instale: sudo apt install alsa-utils"
        if path is None:
            fd, path = tempfile.mkstemp(prefix="ares_", suffix=".wav")
            os.close(fd)
        device = self.device
        cmd = [arecord, "-q", "-D", device, "-f", "S16_LE",
               "-r", str(rate), "-c", "1", "-d", str(seconds), path]
        debug(TAG, " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 10)
        except subprocess.TimeoutExpired:
            return None, "arecord excedeu o tempo limite."
        except OSError as exc:
            return None, f"Falha ao executar arecord: {exc}"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            # tenta uma vez com "default" caso o device escolhido falhe
            if device != "default":
                warn(TAG, f"arecord falhou em {device}; tentando 'default'")
                self._device = "default"
                return self.record(seconds, path)
            return None, f"arecord falhou (codigo {result.returncode}) em {device}: {detail}"
        if not os.path.isfile(path) or os.path.getsize(path) < 100:
            return None, f"arecord terminou, mas {path} esta vazio ou nao existe."
        log(TAG, f"gravado {seconds}s em {device} -> {path}")
        return path, None
