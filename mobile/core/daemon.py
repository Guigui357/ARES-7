#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IA Autonoma em modo daemon: observa, decide e age sem esperar mensagem.

Diferente do modo de requisicao (onde o usuario pergunta e o ARES responde),
o daemon nao espera nada: ele roda, observa o estado da maquina, decide o que
fazer e executa sozinho. So fala quando ha algo que vale a pena dizer.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from core.autonomous import AutonomousAres
from core.config import ARES7_HOME, Config
from core.logs import log, warn
from core.watcher import Observation, Watcher

TAG = "DAEMON"

_SEVERITY_EMOJI = {"info": "i", "warn": "!", "critical": "!!"}


class AutonomousDaemon:
    """Loop autonomo: observa -> decide -> executa -> registra."""

    def __init__(self, config: Config | None = None, core=None) -> None:
        self.config = config or (core.config if core is not None else Config())
        self.core = core
        self.engine = AutonomousAres(config=self.config, core=core)
        self.watcher = Watcher(self.config, core=core)
        self.log_path = os.path.join(ARES7_HOME, "daemon.log")
        self.interval = max(5, int(self.config.get("daemon", "interval", 60) or 60))
        self.cooldown = max(0, int(self.config.get("daemon", "report_cooldown", 900) or 0))
        self.auto_actions = bool(self.config.get("daemon", "auto_actions", True))
        self.llm_decisions = bool(self.config.get("daemon", "llm_decisions", True))
        self.verbose = bool(self.config.get("daemon", "verbose", False))
        self._last_action: dict[str, float] = {}
        self._stop = threading.Event()
        self._history: list[dict[str, Any]] = []

    # ---- ciclo --------------------------------------------------------------------
    def tick(self) -> list[str]:
        """Executa um ciclo: observa, decide e age. Devolve as mensagens geradas."""
        messages: list[str] = []
        observations = self.watcher.collect()
        if not observations:
            if self.verbose:
                self._say("nada a fazer: estado estavel")
            return messages

        for obs in observations:
            for message in self._handle(obs):
                messages.append(message)
                self._record({"ts": time.time(), "message": message, "key": obs.key,
                              "severity": obs.severity})
        return messages

    def run_forever(self) -> None:
        """Roda o ciclo periodicamente ate ser interrompido (Ctrl+C)."""
        abertura = (f"IA Autonoma ativa. Observando a cada {self.interval}s. "
                    "Ctrl+C para parar.")
        self._record({"ts": time.time(), "message": abertura})
        self._say(abertura)
        while not self._stop.is_set():
            started = time.time()
            try:
                for message in self.tick():
                    self._say(message)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                warn(TAG, f"erro no ciclo do daemon: {exc!r}")
            elapsed = time.time() - started
            self._stop.wait(max(1.0, self.interval - elapsed))
        self._record({"ts": time.time(), "message": "IA Autonoma encerrada."})
        self._say("IA Autonoma encerrada.")

    def stop(self) -> None:
        self._stop.set()

    # ---- decisao ------------------------------------------------------------------
    def _handle(self, obs: Observation) -> list[str]:
        """Trata uma observacao: decide, executa e reporta."""
        if not self._cooldown_ok(obs.key):
            return []

        if self.llm_decisions and self.core is not None:
            actions = self._ask_llm(obs)
            if actions is not None:
                return self._run_actions(actions, obs)

        if self.auto_actions and obs.tool:
            return self._run_actions(
                [{"tool": obs.tool, "params": dict(obs.params)}], obs)

        return [self._format(obs, "Nenhuma acao automatica possivel.")]

    def _ask_llm(self, obs: Observation) -> list[dict] | None:
        """Pede ao LLM o que fazer com a observacao (uma chamada)."""
        try:
            online, _model, _err = self.engine.llm.probe()
        except Exception as exc:  # noqa: BLE001
            warn(TAG, f"probe do LLM falhou: {exc!r}")
            return None
        if not online:
            return None
        request = (
            f"Observacao do sistema: {obs.title}. {obs.detail}\n"
            f"Sugestao: {obs.suggestion or 'avalie a situacao'}.\n"
            "Decida o que fazer agora usando as ferramentas disponiveis. "
            "Se nada for necessario, responda apenas com {\"actions\": [], \"reply\": \"\"}."
        )
        try:
            plan = self.engine._plan_with_llm(request)
        except Exception as exc:  # noqa: BLE001
            warn(TAG, f"decisao do LLM falhou: {exc!r}")
            return None
        if not plan:
            return None
        actions = plan.get("actions") or []
        reply = (plan.get("reply") or "").strip()
        if not actions:
            if reply:
                return [{"tool": "notify", "params": {"message": reply}}]
            return []
        return actions

    def _run_actions(self, actions: list[dict], obs: Observation) -> list[str]:
        """Executa as acoes decididas, validando cada uma antes."""
        messages: list[str] = []
        for action in actions:
            tool_name = str(action.get("tool", ""))
            params = action.get("params", {}) or {}
            if not isinstance(params, dict):
                params = {}
            if tool_name not in self.engine.tools:
                messages.append(self._format(obs, f"ferramenta '{tool_name}' desconhecida"))
                continue
            validation = self.engine._validate(tool_name, params)
            if not validation["ok"]:
                if validation.get("needs_confirm"):
                    messages.append(self._format(
                        obs, f"'{tool_name}' precisa de confirmacao; deixei anotado."))
                    self._queue_for_confirmation(tool_name, params, obs)
                    continue
                messages.append(self._format(obs, str(validation["reason"])))
                continue
            try:
                result = self.engine._run_step({"tool": tool_name, "params": params})
            except Exception as exc:  # noqa: BLE001
                result = f"falha ao executar '{tool_name}': {exc}"
            messages.append(self._format(obs, result))
            self._last_action[obs.key] = time.time()
        return messages

    def _queue_for_confirmation(self, tool_name: str, params: dict, obs: Observation) -> None:
        """Guarda a acao de risco para o usuario confirmar depois."""
        state = {
            "mode": "step",
            "tool": tool_name,
            "params": params,
            "question": f"Confirmar '{tool_name}'? (detectado pelo daemon: {obs.title})",
        }
        try:
            os.makedirs(ARES7_HOME, exist_ok=True)
            with open(os.path.join(ARES7_HOME, "autonomous_pending.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False)
        except OSError as exc:
            warn(TAG, f"nao consegui registrar a acao pendente: {exc!r}")

    def _cooldown_ok(self, key: str) -> bool:
        """Evita repetir a mesma acao em pouco tempo."""
        if self.cooldown <= 0:
            return True
        last = self._last_action.get(key)
        if last is None:
            return True
        return (time.time() - last) >= self.cooldown

    # ---- registro -------------------------------------------------------------------
    def _format(self, obs: Observation, outcome: str) -> str:
        tag = _SEVERITY_EMOJI.get(obs.severity, "i")
        return f"[{tag}] {obs.title}: {obs.detail} -> {outcome}"

    def _say(self, message: str) -> None:
        """Mostra a mensagem na tela (o registro ja foi feito em tick())."""
        print(message, flush=True)

    def _record(self, entry: dict[str, Any]) -> None:
        self._history.append(entry)
        del self._history[:-200]
        if not self.config.get("daemon", "log", True):
            return
        try:
            os.makedirs(ARES7_HOME, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as handle:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                handle.write(f"{stamp} {entry.get('message', '')}\n")
        except OSError as exc:
            warn(TAG, f"nao consegui escrever no log do daemon: {exc!r}")

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)


def run_daemon(config_path: str | None = None, once: bool = False,
               core=None) -> int:
    """Ponto de entrada do modo daemon."""
    config = Config(config_path)
    daemon = AutonomousDaemon(config=config, core=core)
    if once:
        for message in daemon.tick():
            daemon._say(message)
        return 0
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        print("Encerrado.", flush=True)
    return 0
