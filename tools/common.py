#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers compartilhados pelas ferramentas (leitura de /proc, subprocess...)."""
from __future__ import annotations

import glob
import os
import re
import shutil
import socket
import subprocess
import threading
import time


def read_text_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return None


def run_quiet(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or result.stderr or "").strip()


def launch_detached(cmd: list[str]) -> None:
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def first_executable(candidates: list[str]) -> str | None:
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return None


class CpuSampler:
    """Uso de CPU via /proc/stat, sem bibliotecas externas."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prev: tuple[int, int] | None = None

    @staticmethod
    def _read() -> tuple[int, int]:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            line = handle.readline()
        parts = [int(x) for x in line.split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        return idle, sum(parts[:8])

    def percent(self) -> float | None:
        with self._lock:
            try:
                if self._prev is None:
                    self._prev = self._read()
                    time.sleep(0.15)
                current = self._read()
            except (OSError, ValueError, IndexError):
                return None
            prev_idle, prev_total = self._prev
            idle, total = current
            self._prev = current
            delta_total = total - prev_total
            if delta_total <= 0:
                return None
            usage = 100.0 * (1.0 - (idle - prev_idle) / delta_total)
            return max(0.0, min(100.0, usage))


CPU_SAMPLER = CpuSampler()


def read_memory() -> tuple[int, int] | None:
    raw = read_text_file("/proc/meminfo")
    if not raw:
        return None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        match = re.match(r"^(\w+):\s+(\d+)\s*kB", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return total - available, total


def read_temperature() -> float | None:
    temps: list[float] = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        raw = read_text_file(path)
        if raw is None:
            continue
        try:
            value = int(raw) / 1000.0
        except ValueError:
            continue
        if -20.0 < value < 150.0:
            temps.append(value)
    return max(temps) if temps else None


def read_battery() -> str | None:
    for base in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        capacity = read_text_file(os.path.join(base, "capacity"))
        if capacity is None:
            continue
        status = read_text_file(os.path.join(base, "status")) or ""
        return f"{capacity}% ({status})" if status else f"{capacity}%"
    return None


def read_uptime_seconds() -> int | None:
    raw = read_text_file("/proc/uptime")
    if not raw:
        return None
    try:
        return int(float(raw.split()[0]))
    except (ValueError, IndexError):
        return None


def local_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def user_dir(kind: str, fallback_name: str) -> str:
    """Pasta do usuario via xdg-user-dir, com fallback em ~/<nome>."""
    xdg = shutil.which("xdg-user-dir")
    if xdg:
        code, out = run_quiet([xdg, kind], timeout=5)
        if code == 0 and out:
            return out.splitlines()[0].strip()
    return os.path.join(os.path.expanduser("~"), fallback_name)
