#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observador do sistema para a IA Autonoma em modo daemon.

Coleta o estado da maquina periodicamente e transforma em observacoes
acionaveis. O observador nao executa nada: apenas diz o que mudou e o
que poderia ser feito a respeito.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

from core.config import ARES7_HOME
from core.logs import debug
from tools.common import (CPU_SAMPLER, read_battery, read_memory, read_temperature,
                          read_uptime_seconds, run_quiet)

SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


@dataclass
class Observation:
    """Uma condicao observada no sistema, com a acao sugerida (se houver)."""

    key: str
    title: str
    detail: str
    severity: str = "info"          # info | warn | critical
    tool: str = ""                  # ferramenta sugerida
    params: dict = field(default_factory=dict)
    suggestion: str = ""            # o que fazer, em linguagem natural

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "detail": self.detail,
            "severity": self.severity,
            "tool": self.tool,
            "params": dict(self.params),
            "suggestion": self.suggestion,
        }


class Watcher:
    """Coleta observacoes e so devolve as que mudaram desde a ultima checagem."""

    def __init__(self, config=None, core=None) -> None:
        self.config = config
        self.core = core
        self._seen: dict[str, tuple[str, float]] = {}   # key -> (severity, quando)
        self._history: list[Observation] = []
        self._llm_offline_reported = 0.0

    # ---- coleta -------------------------------------------------------------------
    def collect(self) -> list[Observation]:
        """Devolve apenas as observacoes novas ou que mudaram de severidade."""
        found: list[Observation] = []
        for obs in self._all():
            previous = self._seen.get(obs.key)
            now = time.time()
            if previous is None or previous[0] != obs.severity:
                self._seen[obs.key] = (obs.severity, now)
                found.append(obs)
            else:
                self._seen[obs.key] = (obs.severity, previous[1])
        if found:
            self._history.extend(found)
            del self._history[:-50]
        return found

    def _all(self) -> list[Observation]:
        observations: list[Observation] = []
        observations.extend(self._memory())
        observations.extend(self._disk())
        observations.extend(self._battery())
        observations.extend(self._temperature())
        observations.extend(self._cpu())
        observations.extend(self._llm())
        observations.extend(self._pending())
        observations.extend(self._uptime())
        return observations

    # ---- regras -------------------------------------------------------------------
    def _memory(self) -> list[Observation]:
        data = read_memory()
        if not data:
            return []
        used, total = data
        if total <= 0:
            return []
        free_pct = 100.0 * (total - used) / total
        if free_pct < 8:
            return [Observation(
                key="memoria_critica",
                title="Memoria quase esgotada",
                detail=f"Apenas {free_pct:.0f}% de RAM livre ({used / 1024 ** 3:.1f} de "
                       f"{total / 1024 ** 3:.1f} GB em uso).",
                severity="critical",
                tool="reset_context",
                params={},
                suggestion="Limpar o contexto da conversa para liberar memoria.",
            )]
        if free_pct < 15:
            return [Observation(
                key="memoria_baixa",
                title="Memoria baixa",
                detail=f"Apenas {free_pct:.0f}% de RAM livre.",
                severity="warn",
                tool="reset_context",
                params={},
                suggestion="Limpar o contexto da conversa para liberar memoria.",
            )]
        return []

    def _disk(self) -> list[Observation]:
        try:
            usage = shutil.disk_usage("/")
        except OSError:
            return []
        if usage.total <= 0:
            return []
        free_pct = 100.0 * usage.free / usage.total
        if free_pct < 5:
            return [Observation(
                key="disco_critico",
                title="Disco quase cheio",
                detail=f"Sobram {free_pct:.1f}% de espaco em / "
                       f"({usage.free / 1024 ** 3:.1f} GB).",
                severity="critical",
                suggestion="Liberar espaco em disco.",
            )]
        if free_pct < 10:
            return [Observation(
                key="disco_baixo",
                title="Disco com pouco espaco",
                detail=f"Sobram {free_pct:.1f}% de espaco em /.",
                severity="warn",
                suggestion="Liberar espaco em disco.",
            )]
        return []

    def _battery(self) -> list[Observation]:
        raw = read_battery()
        if not raw:
            return []
        match = re.match(r"(\d+)%", raw)
        if not match:
            return []
        level = int(match.group(1))
        if level <= 10:
            return [Observation(
                key="bateria_critica",
                title="Bateria em nivel critico",
                detail=f"Bateria em {level}%.",
                severity="critical",
                suggestion="Conectar o carregador.",
            )]
        if level <= 20:
            return [Observation(
                key="bateria_baixa",
                title="Bateria baixa",
                detail=f"Bateria em {level}%.",
                severity="warn",
                suggestion="Conectar o carregador.",
            )]
        return []

    def _temperature(self) -> list[Observation]:
        temp = read_temperature()
        if temp is None:
            return []
        if temp >= 90:
            return [Observation(
                key="temperatura_critica",
                title="Temperatura muito alta",
                detail=f"{temp:.0f} C no sensor do sistema.",
                severity="critical",
                suggestion="Verificar ventilacao e carga da maquina.",
            )]
        if temp >= 80:
            return [Observation(
                key="temperatura_alta",
                title="Temperatura alta",
                detail=f"{temp:.0f} C no sensor do sistema.",
                severity="warn",
                suggestion="Verificar ventilacao da maquina.",
            )]
        return []

    def _cpu(self) -> list[Observation]:
        cpu = CPU_SAMPLER.percent()
        if cpu is None or cpu < 90:
            return []
        return [Observation(
            key="cpu_alto",
            title="CPU muito ocupada",
            detail=f"Uso de CPU em {cpu:.0f}%.",
            severity="warn",
            tool="process_list",
            params={},
            suggestion="Ver quais processos estao consumindo CPU.",
        )]

    def _llm(self) -> list[Observation]:
        if self.core is None:
            return []
        try:
            online, model, _err = self.core.llm.probe()
        except Exception as exc:  # noqa: BLE001
            debug("WATCHER", f"probe do LLM falhou: {exc!r}")
            return []
        if online:
            return []
        return [Observation(
            key="llm_offline",
            title="Servidor do Qwen offline",
            detail="O llama.cpp nao responde; o planejamento autonomo esta indisponivel.",
            severity="warn",
            tool="reconnect_llm",
            params={},
            suggestion="Tentar subir o servidor llama.cpp novamente.",
        )]

    def _pending(self) -> list[Observation]:
        path = os.path.join(ARES7_HOME, "autonomous_pending.json")
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = handle.read().strip()
        except OSError:
            return []
        if not data:
            return []
        return [Observation(
            key="confirmacao_pendente",
            title="Acao aguardando confirmacao",
            detail="Ha uma acao de risco que o usuario ainda nao confirmou.",
            severity="warn",
            suggestion="Responder 'sim' ou 'nao' para a acao pendente.",
        )]

    def _uptime(self) -> list[Observation]:
        seconds = read_uptime_seconds()
        if seconds is None or seconds < 7 * 24 * 3600:
            return []
        days = seconds // 86400
        return [Observation(
            key="uptime_alto",
            title="Maquina ligada ha muito tempo",
            detail=f"{days} dias sem reiniciar.",
            severity="info",
            suggestion="Reiniciar para liberar recursos, se estiver seguro.",
        )]

    # ---- extras -------------------------------------------------------------------
    def processes_snapshot(self, limit: int = 5) -> str:
        code, out = run_quiet(["ps", "-eo", "comm,%mem", "--sort=-%mem"], timeout=8)
        if code != 0:
            return ""
        lines = out.splitlines()[1: limit + 1]
        return "\n".join(line.strip() for line in lines)

    def zombie_count(self) -> int:
        code, out = run_quiet(["ps", "-eo", "stat"], timeout=8)
        if code != 0:
            return 0
        return sum(1 for line in out.splitlines()[1:] if line.strip().startswith("Z"))

    def thermal_zones(self) -> list[str]:
        return glob.glob("/sys/class/thermal/thermal_zone*/temp")
