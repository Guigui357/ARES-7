#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducao de audio (aplay/paplay/pw-play), sem copias desnecessarias."""
from __future__ import annotations

import shutil
import subprocess

from core.logs import debug, warn

TAG = "AUDIO"


def player_cmd(wav_path: str) -> list[str] | None:
    for name, extra in (("aplay", ["-q"]), ("paplay", []), ("pw-play", [])):
        exe = shutil.which(name)
        if exe:
            return [exe, *extra, wav_path]
    return None


def play(wav_path: str, timeout: int = 120) -> tuple[bool, str]:
    """Toca um WAV. Retorna (ok, erro)."""
    cmd = player_cmd(wav_path)
    if not cmd:
        return False, "Nenhum player (aplay/paplay/pw-play) encontrado."
    debug(TAG, " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"Falha ao tocar audio: {exc!r}"
    if result.returncode != 0:
        warn(TAG, f"{cmd[0]} retornou {result.returncode}")
        return False, f"player retornou {result.returncode}"
    return True, ""
