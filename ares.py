#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ARES7 FAST / LOCAL — launcher principal.

Uso:
    python3 ares.py                # GUI (Tkinter)
    python3 ares.py --cli          # terminal
    python3 ares.py --headless     # igual a --cli
    python3 ares.py --cli --voice  # CLI com voz ativa
    python3 ares.py --cli --text   # CLI somente texto (sem voz/TTS)
    python3 ares.py --remote       # sobe tambem o servidor remoto (config: remote)
    python3 ares.py --diagnose     # relatorio de diagnostico
    python3 ares.py --benchmark    # mede desempenho
    python3 ares.py --low-memory   # modo ULTRA FAST
    python3 ares.py --debug        # logs detalhados
    python3 ares.py --wake         # ativa wake word ("ares") modo CONTINUOUS
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config  # noqa: E402
from core.logs import log, set_debug  # noqa: E402

TAG = "MAIN"
VERSION = "1.2.1"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ares.py", description="ARES-7 - assistente de voz 100% local")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cli", "--headless", dest="cli", action="store_true", help="modo terminal (sem GUI)")
    mode.add_argument("--diagnose", action="store_true", help="relatorio de diagnostico completo")
    mode.add_argument("--benchmark", action="store_true", help="mede desempenho do pipeline")
    mode.add_argument("--status", action="store_true", help="estado rapido do sistema")
    parser.add_argument("--voice", action="store_true", help="CLI com botao de voz (/voz)")
    parser.add_argument("--text", action="store_true", help="somente texto (desativa TTS)")
    parser.add_argument("--no-tts", action="store_true", help="nao falar as respostas")
    parser.add_argument("--low-memory", action="store_true", help="modo ULTRA FAST (pouca RAM)")
    parser.add_argument("--remote", action="store_true", help="subir o servidor remoto (remote.*)")
    parser.add_argument("--wake", action="store_true", help="wake word continua ('ares')")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--debug", action="store_true", help="logs detalhados")
    parser.add_argument("--config", default=None, help="caminho alternativo do config.json")
    return parser


def make_ares(args) -> "Ares7":
    from core.assistant import Ares7
    config = Config(args.config)
    if args.wake:
        config.set("wake_word", "enabled", True)
    ares = Ares7(config, low_memory=args.low_memory)
    if args.text or args.no_tts:
        ares.speak_enabled = False
    return ares


def maybe_start_remote(ares, args) -> None:
    if args.remote or ares.config.get("remote", "enabled", False):
        from remote.server import RemoteServer
        ares.remote = RemoteServer(ares, ares.config["remote"])
        ares.remote.start()


def run_status(ares) -> int:
    st = ares.collect_status()
    gb = 1024 ** 3
    print("ARES7 STATUS")
    print("Whisper: " + (f"OK ({st['whisper_bin']})" if st["whisper_bin"] else "MISSING"))
    print("Modelo Whisper: " + (st["whisper_model"] or "MISSING"))
    print("Microfone: " + str(st["mic_device"]))
    print("llama.cpp: " + ("ONLINE" if st["llm_online"] else "OFFLINE") +
          (f" ({st['llm_model']})" if st["llm_model"] else ""))
    print("Piper: " + ("OK" if st["piper_ready"] else f"FALLBACK ({st['tts_fallback']})"))
    print("CPU: " + (f"{st['cpu']:.0f}%" if st["cpu"] is not None else "N/D"))
    if st["ram_total"]:
        print(f"RAM: {st['ram_used'] / gb:.1f} / {st['ram_total'] / gb:.1f} GB")
    print("Temperatura: " + (f"{st['temp']:.1f} C" if st["temp"] is not None else "N/D"))
    print("Bateria: " + (st["battery"] or "N/D"))
    print("Low memory: " + ("SIM" if st["low_memory"] else "nao"))
    print("Contexto LLM: " + str(ares.context.token_budget()) + " tokens")
    return 0


def cli_emit(kind: str, payload) -> None:
    if kind == "user_voice":
        print(f"Você (voz) > {payload}")
    elif kind == "ares":
        print(f"ARES7 > {payload}")
    elif kind == "system":
        print(payload)
    elif kind == "confirm":
        print(f"⚠ CONFIRMAÇÃO: {payload} (responda 'sim' ou 'não')")
    elif kind == "error":
        print(f"[ERRO] {payload}")


def run_cli(ares) -> int:
    ares.emit = cli_emit
    print("=" * 50)
    print(" A R E S - 7   C L I")
    print("=" * 50)
    st = ares.collect_status()
    print("Whisper: " + ("OK" if st["whisper_ok"] else "PROBLEMA (use --diagnose)"))
    print("LLM: " + ("ONLINE" if st["llm_online"] else "OFFLINE"))
    print("TTS: " + st["tts_mode"] + (" (desligado)" if not ares.speak_enabled else ""))
    print("Comandos: /voz /wake /status /dispositivos /limpar /sair — ou fale naturalmente; \"ajuda\" lista tudo")
    if ares.config.get("wake_word", "enabled", False):
        ares.start_wake_word()
    while True:
        try:
            line = input("Você > ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        line = line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in ("/sair", "/exit", "/quit", "sair"):
            break
        if lowered == "/status":
            run_status(ares)
            continue
        if lowered == "/limpar":
            ares.context.reset()
            print("Histórico limpo.")
            continue
        if lowered == "/tts":
            ares.speak_enabled = not ares.speak_enabled
            print("TTS: " + ("ligado" if ares.speak_enabled else "desligado"))
            continue
        if lowered == "/dispositivos":
            print(ares.list_input_devices())
            continue
        if lowered == "/wake":
            ares.start_wake_word()
            continue
        try:
            if lowered == "/voz":
                ares.voice_turn()
            else:
                ares.handle_text(line)
        except KeyboardInterrupt:
            print("\nInterrompido.")
            ares.vad.stop_event.set()
        except Exception as exc:
            log(TAG, f"falha inesperada: {exc!r}")
            print("[ERRO] Falha inesperada (detalhes no log).")
    ares.stop_wake_word()
    print("Até logo.")
    return 0


def run_gui(ares) -> int:
    from gui.app import TK_IMPORT_ERROR, Ares7GUI, tk
    if tk is None:
        print(f"Tkinter indisponível: {TK_IMPORT_ERROR}")
        print("Use: python3 ares.py --cli")
        return 1
    try:
        gui = Ares7GUI(ares)
    except tk.TclError as exc:
        print(f"Não foi possível abrir a janela: {exc}")
        print("Sem ambiente gráfico? Use: python3 ares.py --cli")
        return 1
    gui.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    set_debug(args.debug)

    if args.diagnose:
        import diagnose
        return diagnose.run(Config(args.config), low_memory=args.low_memory)
    if args.benchmark:
        import benchmark
        return benchmark.run(Config(args.config), low_memory=args.low_memory)

    ares = make_ares(args)
    maybe_start_remote(ares, args)
    if args.status:
        return run_status(ares)
    if args.cli:
        return run_cli(ares)
    return run_gui(ares)


if __name__ == "__main__":
    sys.exit(main())
