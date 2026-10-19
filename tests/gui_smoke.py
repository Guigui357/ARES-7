#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sobe a GUI do ARES-7 em display virtual e tira um screenshot.

    xvfb-run -a -s "-screen 0 1280x800x24" python3 tests/gui_smoke.py [saida.png]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.assistant import Ares7
from core.config import Config


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kilo/gui.png"
    config = Config()
    config.set("llm", "autostart", False)
    ares = Ares7(config)
    ares.speak_enabled = False

    from gui.app import Ares7GUI

    gui = Ares7GUI(ares)
    gui.root.update()

    # Simula o que o nucleo faria: estado pronto, uma nota e uma confirmacao.
    gui._dispatch("state", "READY")
    gui._dispatch("user_text", "verifique o sistema")
    gui._dispatch("ares", "Sistema: CPU 12%, RAM 1.4/8.2 GB, disco 59/144 GB.")
    gui._dispatch("confirm", "Tem certeza que deseja desligar o computador?")
    gui.root.update()
    # Dispara alguns quadros da animacao do nucleo para o screenshot.
    for _ in range(12):
        gui._draw_core()
    gui.root.update()

    def capture() -> None:
        gui.root.update()
        try:
            from PIL import ImageGrab  # type: ignore
            ImageGrab.grab(xdisplay=os.environ.get("DISPLAY")).save(out)
            print("screenshot:", out)
        except Exception as exc:
            print("sem PIL para o screenshot:", exc)
        gui.root.destroy()

    gui.root.after(700, capture)
    gui.root.mainloop()
    print("GUI subiu sem erro (ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
