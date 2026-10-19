#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas de rede."""
from __future__ import annotations

from tools.base import Tool
from tools.common import local_ip, run_quiet


def network_info() -> str:
    parts = []
    ip = local_ip()
    parts.append(f"IP local: {ip}" if ip else "Sem conexao de rede detectada")
    code, _out = run_quiet(["ping", "-c", "1", "-W", "2", "8.8.8.8"], timeout=5)
    parts.append("internet: OK" if code == 0 else "internet: sem resposta ao ping")
    return ". ".join(parts) + "."


TOOLS = [
    Tool("network_info", "IP local e conectividade", network_info),
]
