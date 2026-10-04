#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logs claros do ARES7: [TAG] mensagem, com nivel --debug opcional."""
from __future__ import annotations

import datetime
import sys
import threading

DEBUG = False
_lock = threading.Lock()


def set_debug(enabled: bool) -> None:
    global DEBUG
    DEBUG = enabled


def _emit(level: str, tag: str, message: str) -> None:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    with _lock:
        print(f"{stamp} [{level}][{tag}] {message}", file=sys.stderr, flush=True)


def log(tag: str, message: str) -> None:
    _emit("LOG", tag, message)


def info(tag: str, message: str) -> None:
    _emit("INFO", tag, message)


def warn(tag: str, message: str) -> None:
    _emit("WARN", tag, message)


def error(tag: str, message: str) -> None:
    _emit("ERROR", tag, message)


def debug(tag: str, message: str) -> None:
    if DEBUG:
        _emit("DEBUG", tag, message)
