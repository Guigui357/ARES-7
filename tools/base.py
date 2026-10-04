#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas locais do ARES7.

Cada ferramenta tem: nome, descricao, parametros, funcao, validacao e
nivel de risco ("safe" | "confirm"). O router usa isso para pedir
confirmacao antes de comandos perigosos (desligar, reiniciar...).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    function: Callable[..., str]
    risk: str = "safe"           # "safe" | "confirm"
    params: dict = field(default_factory=dict)

    def run(self, **kwargs) -> str:
        return self.function(**kwargs)
