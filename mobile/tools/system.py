#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas de sistema: info, volume, brilho, energia, screenshot, processos."""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess

from tools.base import Tool
from tools.common import (CPU_SAMPLER, first_executable, launch_detached, read_battery,
                          read_memory, read_temperature, read_uptime_seconds, run_quiet,
                          user_dir)

GB = 1024 ** 3


def system_info() -> str:
    parts = []
    cpu = CPU_SAMPLER.percent()
    if cpu is not None:
        parts.append(f"CPU {cpu:.0f}%")
    memory = read_memory()
    if memory:
        parts.append(f"RAM {memory[0] / GB:.1f}/{memory[1] / GB:.1f} GB")
    temp = read_temperature()
    if temp is not None:
        parts.append(f"temperatura {temp:.0f}°C")
    battery = read_battery()
    if battery:
        parts.append(f"bateria {battery}")
    usage = shutil.disk_usage("/")
    parts.append(f"disco {usage.used / GB:.0f}/{usage.total / GB:.0f} GB")
    return "Sistema: " + ", ".join(parts) + "."


def _volume_report(wpctl: str) -> str:
    code, out = run_quiet([wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"])
    match = re.search(r"([0-9]*\.?[0-9]+)", out)
    if code != 0 or not match:
        return "Volume ajustado."
    text = f"Volume em {round(float(match.group(1)) * 100)} por cento."
    if "MUTED" in out:
        text += " Som mutado."
    return text


def volume(step: str) -> str:
    """step: '5%+', '5%-' (relativo) ou '40%' (absoluto)."""
    wpctl = shutil.which("wpctl")
    if wpctl:
        code, out = run_quiet([wpctl, "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", step])
        if code != 0:
            return f"wpctl falhou: {out}"
        return _volume_report(wpctl)
    amixer = shutil.which("amixer")
    if amixer:
        code, out = run_quiet([amixer, "-q", "sset", "Master", step])
        return "Volume ajustado." if code == 0 else f"amixer falhou: {out}"
    return "Nem wpctl nem amixer encontrados para controlar o volume."


def mute(mode: str) -> str:
    """mode: 'toggle', '1' (mudo), '0' (som ligado)."""
    wpctl = shutil.which("wpctl")
    if wpctl:
        code, out = run_quiet([wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", mode])
        if code != 0:
            return f"wpctl falhou: {out}"
        _, out = run_quiet([wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"])
        return "Som mutado." if "MUTED" in out else "Som reativado."
    amixer = shutil.which("amixer")
    if amixer:
        arg = {"toggle": "toggle", "1": "mute", "0": "unmute"}[mode]
        code, out = run_quiet([amixer, "-q", "sset", "Master", arg])
        return "Estado do mudo alterado." if code == 0 else f"amixer falhou: {out}"
    return "Nem wpctl nem amixer encontrados."


def brightness(step: str) -> str:
    tool = shutil.which("brightnessctl")
    if not tool:
        return "brightnessctl nao encontrado. Instale: sudo apt install brightnessctl"
    code, out = run_quiet([tool, "set", step])
    return "Brilho ajustado." if code == 0 else f"brightnessctl falhou: {out}"


def screenshot() -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = user_dir("PICTURES", "Pictures")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return f"Nao consegui criar {folder}: {exc}"
    path = os.path.join(folder, f"ares_{stamp}.png")
    tool = shutil.which("gnome-screenshot")
    cmd = [tool, "-f", path] if tool else None
    if cmd is None:
        tool = shutil.which("scrot")
        cmd = [tool, path] if tool else None
    if cmd is None:
        return "Nenhum programa de screenshot (gnome-screenshot/scrot) encontrado."
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"Falha ao tirar screenshot: {exc}"
    if result.returncode != 0 or not os.path.isfile(path):
        return f"A captura falhou: {(result.stderr or '').strip() or 'sem detalhes'}"
    return f"Screenshot salva em {path}."


def lock_screen() -> str:
    for exe, args in (("loginctl", ["lock-session"]), ("xdg-screensaver", ["lock"]),
                      ("gnome-screensaver-command", ["-l"])):
        path = shutil.which(exe)
        if path:
            code, out = run_quiet([path, *args])
            return "Bloqueando a tela." if code == 0 else f"Falha ao bloquear: {out}"
    return "Nenhum comando de bloqueio de tela encontrado."


def process_list(limit: int = 8) -> str:
    code, out = run_quiet(["ps", "-eo", "comm,%mem", "--sort=-%mem"], timeout=8)
    if code != 0:
        return f"ps falhou: {out}"
    lines = out.splitlines()[1: limit + 1]
    return "Processos que mais usam memoria:\n" + "\n".join(l.strip() for l in lines)


# ---- energia (exigem confirmacao) --------------------------------------------

def _power(action: str) -> str:
    if shutil.which("systemctl"):
        launch_detached(["systemctl", action])
        return {"poweroff": "Desligando o computador.", "reboot": "Reiniciando o computador.",
                "suspend": "Suspendendo o computador."}.get(action, "Ok.")
    return "systemctl nao encontrado."


def poweroff() -> str:
    return _power("poweroff")


def reboot() -> str:
    return _power("reboot")


def suspend() -> str:
    return _power("suspend")


TOOLS = [
    Tool("system_info", "CPU, RAM, temperatura, bateria e disco", system_info),
    Tool("volume", "Ajusta o volume (ex.: '5%+', '40%')", volume, params={"step": "str"}),
    Tool("mute", "Muta/desmuta o som", mute, params={"mode": "toggle|1|0"}),
    Tool("brightness", "Ajusta o brilho (ex.: '10%+', '50%')", brightness, params={"step": "str"}),
    Tool("screenshot", "Tira uma captura de tela", screenshot),
    Tool("lock_screen", "Bloqueia a tela", lock_screen, risk="confirm"),
    Tool("process_list", "Lista processos que mais usam memoria", process_list),
    Tool("poweroff", "Desliga o computador", poweroff, risk="confirm"),
    Tool("reboot", "Reinicia o computador", reboot, risk="confirm"),
    Tool("suspend", "Suspende o computador", suspend, risk="confirm"),
]
