#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas para controle de tela: mouse, teclado, janela."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

from tools.base import Tool
from tools.common import run_quiet


def _has(*bins: str) -> bool:
    return any(shutil.which(b) for b in bins)


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout or res.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)


def mouse_move(x: int, y: int, duration: float = 0.0) -> str:
    """Move o cursor para (x,y)."""
    x = int(x)
    y = int(y)
    # Prefer xdotool
    if shutil.which("xdotool"):
        if duration and duration > 0:
            _run(["xdotool", "mousemove", "--delay", str(int(duration * 1000)), str(x), str(y)])
        else:
            _run(["xdotool", "mousemove", str(x), str(y)])
        return f"Cursor movido para ({x}, {y})."
    # ydotool (Wayland) limitado, mas tenta
    if shutil.which("ydotool"):
        return "ydotool tem suporte limitado a mover cursor. Use xdotool em X11/Wayland com XWayland ou instale xdotool."
    # pyautogui fallback
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.moveTo(x, y, duration=float(duration or 0.2))
        return f"Cursor movido para ({x}, {y})."
    except Exception as e:
        return f"Sem forma de mover mouse. Instale xdotool ou pyautogui. Erro: {e}"


def mouse_click(button: str = "left", clicks: int = 1, x: Optional[int] = None, y: Optional[int] = None) -> str:
    """Clica com mouse. button: left/right/middle."""
    b = (button or "left").lower()
    clicks = max(1, int(clicks))
    if x is not None and y is not None:
        mouse_move(x, y)
    if shutil.which("xdotool"):
        btn = {"left": "1", "right": "3", "middle": "2"}.get(b, "1")
        _run(["xdotool", "click", "--repeat", str(clicks), btn])
        return f"Clique {b} x{clicks} realizado."
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        if b == "right":
            pyautogui.rightClick(clicks=clicks)
        elif b == "middle":
            pyautogui.middleClick(clicks=clicks)
        else:
            pyautogui.click(clicks=clicks)
        return f"Clique {b} x{clicks} realizado."
    except Exception as e:
        return f"Sem forma de clicar. Instale xdotool ou pyautogui. Erro: {e}"


def mouse_scroll(amount: int = 120) -> str:
    """Scroll vertical. positivo = pra cima, negativo = pra baixo (varia por ambiente)."""
    amount = int(amount)
    if shutil.which("xdotool"):
        if amount >= 0:
            _run(["xdotool", "click", "4"] * (amount // 120 if amount >= 120 else max(1, amount // 10)))
        else:
            _run(["xdotool", "click", "5"] * (abs(amount) // 120 if abs(amount) >= 120 else max(1, abs(amount) // 10)))
        return f"Scroll {'+' if amount >= 0 else ''}{amount} aplicado."
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.scroll(amount)
        return f"Scroll {amount} aplicado."
    except Exception as e:
        return f"Sem forma de scroll. Instale xdotool ou pyautogui. Erro: {e}"


def type_text(text: str, delay: float = 0.01) -> str:
    """Digita texto no campo ativo."""
    if not text:
        return "Texto vazio."
    if shutil.which("xdotool"):
        # xdotool type escapa melhor sem shell
        _run(["xdotool", "type", "--delay", str(int(delay * 1000)), text])
        return f"Digitado {len(text)} caracteres."
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.write(text, interval=float(delay))
        return f"Digitado {len(text)} caracteres."
    except Exception as e:
        return f"Sem forma de digitar. Instale xdotool ou pyautogui. Erro: {e}"


def key_press(keys: str) -> str:
    """Pressiona combinação de teclas. Ex: 'alt+tab', 'ctrl+shift+t', 'Return', 'super+d'"""
    if not keys:
        return "Teclas vazias."
    if shutil.which("xdotool"):
        _run(["xdotool", "key", keys.replace(" ", "")])
        return f"Teclas '{keys}' pressionadas."
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        # pyautogui usa + como separador
        pyautogui.hotkey(*[k.strip() for k in keys.split("+")])
        return f"Atalho '{keys}' pressionado."
    except Exception as e:
        return f"Sem forma de enviar teclas. Instale xdotool ou pyautogui. Erro: {e}"


def active_window() -> str:
    """Mostra janela ativa."""
    if shutil.which("xdotool"):
        c, out = _run(["xdotool", "getactivewindow", "getwindowname"])
        if c == 0 and out:
            return f"Janela ativa: {out}"
    if shutil.which("wmctrl"):
        c, out = _run(["wmctrl", "-a", ":ACTIVE:"])
        c2, out2 = _run(["wmctrl", "-lx"])
        if c2 == 0:
            # tenta achar ativa
            for line in out2.splitlines():
                if "* " in line or line.strip():
                    pass
        return "Use xdotool/wmctrl para detalhes da janela."
    return "Sem ferramentas para identificar janela ativa (xdotool/wmctrl)."


def focus_window(name: str) -> str:
    """Foca janela pelo nome/parcial."""
    if not name:
        return "Nome da janela vazio."
    if shutil.which("wmctrl"):
        c, out = _run(["wmctrl", "-a", name])
        if c == 0:
            return f"Focando janela com '{name}'."
        return f"Não consegui focar: {out}"
    if shutil.which("xdotool"):
        c, out = _run(["xdotool", "search", "--name", name, "windowactivate", "--sync"])
        if c == 0:
            return f"Focando janela com '{name}'."
        return f"Não consegui focar: {out}"
    return "Instale wmctrl ou xdotool para focar janelas."


TOOLS = [
    Tool("mouse_move", "Move o mouse para (x,y)", mouse_move, params={"x": "int", "y": "int", "duration": "float"}),
    Tool("mouse_click", "Clica (left/right/middle)", mouse_click, params={"button": "str", "clicks": "int", "x": "int", "y": "int"}, risk="confirm"),
    Tool("mouse_scroll", "Rola a tela", mouse_scroll, params={"amount": "int"}, risk="confirm"),
    Tool("type_text", "Digita texto no campo ativo", type_text, params={"text": "str", "delay": "float"}, risk="confirm"),
    Tool("key_press", "Envia atalho de teclas", key_press, params={"keys": "str"}, risk="confirm"),
    Tool("active_window", "Mostra janela ativa", active_window),
    Tool("focus_window", "Foca janela pelo nome", focus_window, params={"name": "str"}, risk="confirm"),
]
