#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas de midia (playerctl)."""
from __future__ import annotations

import shutil

from tools.base import Tool
from tools.common import run_quiet


def media(action: str) -> str:
    """action: play-pause | next | previous | stop."""
    playerctl = shutil.which("playerctl")
    if not playerctl:
        return "playerctl nao encontrado. Instale: sudo apt install playerctl"
    code, out = run_quiet([playerctl, action])
    if code != 0:
        return f"Nenhum player respondeu: {out or 'sem player ativo'}"
    return {"play-pause": "Ok, alternei entre tocar e pausar.",
            "next": "Proxima faixa.", "previous": "Faixa anterior.",
            "stop": "Reproducao parada."}.get(action, "Ok.")


TOOLS = [
    Tool("media", "Controla musica (play-pause/next/previous/stop)", media, params={"action": "str"}),
]
