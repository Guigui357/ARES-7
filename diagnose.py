#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python3 ares.py --diagnose

Verifica Python, RAM, CPU, ALSA, PipeWire/PulseAudio, microfones, Whisper,
modelo Whisper, llama.cpp, Qwen, endpoint, Piper, modelo Piper, speaker,
permissoes, portas e dependencias. Termina com um relatorio PASS/WARN/FAIL
e instrucoes de correcao.
"""
from __future__ import annotations

import os
import shutil
import socket
import sys

from audio.devices import list_alsa_inputs, list_pipewire_inputs
from core.config import Config
from llm.llama import LlamaClient
from stt.whisper import find_binary as find_whisper, find_model as find_whisper_model
from tts.piper import find_piper_binary, find_piper_model

RESULTS: list[tuple[str, str, str]] = []  # (status, item, detalhe/correcao)


def check(status: str, item: str, detail: str = "") -> None:
    RESULTS.append((status, item, detail))


def run(config: Config, low_memory: bool = False) -> int:
    print("Executando diagnóstico...\n")

    # Python
    v = sys.version_info
    check("PASS" if v >= (3, 10) else "FAIL", "Python",
          f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 10) else " — precisa >= 3.10"))

    # RAM
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            mem = {l.split(":")[0]: int(l.split()[1]) for l in fh if ":" in l}
        total_mb = mem.get("MemTotal", 0) / 1024
        avail_mb = mem.get("MemAvailable", 0) / 1024
        status = "PASS" if avail_mb > 700 else "WARN"
        check(status, "RAM", f"{avail_mb:.0f} MB livres de {total_mb:.0f} MB"
              + ("" if status == "PASS" else " — use --low-memory"))
    except OSError:
        check("WARN", "RAM", "nao consegui ler /proc/meminfo")

    # CPU
    check("PASS", "CPU", f"{os.cpu_count() or '?'} nucleos")

    # ALSA / PipeWire / PulseAudio
    check("PASS" if shutil.which("arecord") else "FAIL", "ALSA (arecord)",
          "" if shutil.which("arecord") else "sudo apt install alsa-utils")
    pipewire = shutil.which("wpctl")
    pactl = shutil.which("pactl")
    check("PASS" if (pipewire or pactl) else "WARN", "PipeWire/PulseAudio",
          "wpctl/pactl presentes" if (pipewire or pactl) else "sem wpctl/pactl — controle de volume limitado")

    # microfones
    alsa_in = list_alsa_inputs()
    pw_in = list_pipewire_inputs()
    if alsa_in:
        detail = "; ".join(f"{d['alsa']} ({d['label']})" for d in alsa_in)
        check("PASS", "Microfones (ALSA)", detail)
    elif pw_in:
        check("PASS", "Microfones (PipeWire)", "; ".join(s["label"] for s in pw_in))
    else:
        check("FAIL", "Microfones", "nenhum encontrado — verifique `arecord -l` e o mixer do ALSA")

    # Whisper
    wbin = find_whisper(str(config.get("whisper", "binary", "")))
    wmodel = find_whisper_model(str(config.get("whisper", "model", "")))
    check("PASS" if wbin else "FAIL", "Whisper binario",
          wbin or "compile o whisper.cpp ou aponte whisper.binary no config.json")
    check("PASS" if wmodel else "FAIL", "Whisper modelo",
          wmodel or "baixe ggml-tiny.bin para ./models ou aponte whisper.model no config.json")

    # llama.cpp / Qwen / endpoint
    llm = LlamaClient(config["llm"])
    online, model, err = llm.probe()
    if online:
        check("PASS", "llama.cpp endpoint", llm.base_url)
        check("PASS" if model else "WARN", "Qwen (modelo)", model or "servidor vivo, mas /models nao listou modelo")
    else:
        srv_bin = shutil.which(str(config.get("llm", "server_bin", "") or "llama-server")) or shutil.which("llama")
        check("FAIL", "llama.cpp endpoint", f"{llm.base_url} offline — inicie `llama serve` ou configure autostart")
        check("PASS" if srv_bin else "WARN", "llama.cpp binario",
              srv_bin or "llama-server/llama nao encontrado no PATH (necessario para autostart)")

    # porta do remoto
    port = int(config.get("remote", "port", 8765))
    sock = socket.socket()
    sock.settimeout(1)
    busy = sock.connect_ex(("127.0.0.1", port)) == 0
    sock.close()
    check("PASS" if not busy else "WARN", f"Porta {port} (remoto)",
          "livre" if not busy else "ocupada — outro servico ja usa essa porta")

    # Piper
    pbin = find_piper_binary(str(config.get("tts", "binary", "")))
    pmodel = find_piper_model(str(config.get("tts", "model", "")))
    check("PASS" if pbin else "WARN", "Piper binario",
          pbin or "nao encontrado — fallback (espeak-ng) sera usado")
    check("PASS" if pmodel else "WARN", "Piper modelo",
          pmodel or "nenhum .onnx com .json em ./models — baixe uma voz pt_BR")
    if not pbin or not pmodel:
        fb = shutil.which("espeak-ng") or shutil.which("espeak") or shutil.which("spd-say")
        check("PASS" if fb else "WARN", "TTS fallback", fb or "nenhum — instale: sudo apt install espeak-ng")

    # speaker
    player = shutil.which("aplay") or shutil.which("paplay") or shutil.which("pw-play")
    check("PASS" if player else "WARN", "Saida de som", player or "sem aplay/paplay/pw-play")

    # tkinter
    try:
        import tkinter  # noqa: F401
        check("PASS", "Tkinter (GUI)", "")
    except Exception as exc:
        check("WARN", "Tkinter (GUI)", f"{exc} — sudo apt install python3-tk")

    # relatorio
    fails = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    warns = sum(1 for s, _, _ in RESULTS if s == "WARN")
    print("=" * 60)
    print(" ARES7 DIAGNOSTIC REPORT")
    print("=" * 60)
    for status, item, detail in RESULTS:
        line = f"[{status:4}] {item}"
        if detail:
            line += f": {detail}"
        print(line)
    print("-" * 60)
    print(f"Resumo: {len(RESULTS) - fails - warns} PASS, {warns} WARN, {fails} FAIL")
    if fails:
        print("Corrija os itens FAIL acima e rode novamente.")
    elif warns:
        print("Tudo essencial OK. WARNs indicam recursos em fallback.")
    else:
        print("Tudo pronto. Bom uso!")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run(Config()))
