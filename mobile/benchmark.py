#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python3 ares.py --benchmark

Mede: inicializacao, captura, Whisper, Qwen (tokens/s), TTS, RAM e CPU.
Objetivo: otimizar o caminho critico do pipeline de voz.
"""
from __future__ import annotations

import os
import time

from core.assistant import Ares7
from core.config import Config


def _ram_mb() -> float:
    try:
        with open("/proc/self/statm", encoding="utf-8") as fh:
            pages = int(fh.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024
    except (OSError, ValueError, IndexError):
        return 0.0


def run(config: Config, low_memory: bool = False) -> int:
    print("ARES7 PERFORMANCE\n(medindo; cada etapa sem hardware/modelo e marcada como SKIP)\n")
    t0 = time.time()
    ares = Ares7(config, low_memory=low_memory)
    ares.speak_enabled = True
    t_boot = time.time() - t0
    results: list[tuple[str, str]] = [("Inicializacao", f"{t_boot:.2f}s")]

    # captura (2s)
    t = time.time()
    wav_path, err = ares.recorder.record(2)
    if err:
        results.append(("Captura 2s", f"SKIP ({err})"))
        wav_path = None
    else:
        results.append(("Captura 2s", f"{time.time() - t:.2f}s"))

    # whisper
    if wav_path:
        t = time.time()
        text, stt_err = ares.stt.transcribe(wav_path)
        if stt_err:
            results.append(("STT Whisper", f"SKIP ({stt_err.splitlines()[0]})"))
        else:
            elapsed = time.time() - t
            results.append(("STT Whisper", f"{elapsed:.2f}s para '{text[:40]}'"))
        try:
            os.remove(wav_path)
        except OSError:
            pass
    else:
        results.append(("STT Whisper", "SKIP (sem audio)"))

    # qwen
    online, *_ = ares.llm.probe()
    if not online:
        online, _ = ares.llm.ensure_online(wait_seconds=20)
    if online:
        t = time.time()
        try:
            reply = ares.llm.chat(ares.context.build_messages("Diga apenas: pronto."))
            elapsed = time.time() - t
            approx_tokens = max(1, len(reply) // 4)
            results.append(("LLM Qwen", f"{elapsed:.2f}s (~{approx_tokens / elapsed:.1f} tok/s)"))
        except Exception as exc:
            results.append(("LLM Qwen", f"SKIP ({exc})"))
    else:
        results.append(("LLM Qwen", "SKIP (servidor offline)"))

    # tts
    if ares.tts.piper_ready():
        t = time.time()
        ares.tts.speak("Teste de sintese de voz do Ares7.")
        results.append(("TTS Piper", f"{time.time() - t:.2f}s"))
    else:
        results.append(("TTS Piper", f"SKIP (fallback: {ares.tts.fallback_name()})"))

    results.append(("RAM do processo", f"{_ram_mb():.0f} MB"))
    st = ares.collect_status()
    results.append(("CPU", f"{st['cpu']:.0f}%" if st["cpu"] is not None else "N/D"))

    print("=" * 50)
    print(" ARES7 PERFORMANCE")
    print("=" * 50)
    for name, value in results:
        print(f"{name:16} {value}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run(Config()))
