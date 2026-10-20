#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Motor de IA Autonoma do ARES-7.

Recebe uma solicitacao em linguagem natural, detecta a intencao, valida se
e possivel executar (dependencias, permissoes, recursos) e executa em zero
rodadas ou uma mensagem.

Fluxo:
    Entrada -> Detecao de intencao -> Validacao de pre-requisitos -> Executacao -> Resultado
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from core.config import ARES7_HOME, Config
from core.context import ContextManager
from core.logs import log, warn
from core.memory import LongTermMemory
from core.router import IntentRouter
from llm.llama import LlamaClient
from tools import apps as t_apps
from tools import files as t_files
from tools import media as t_media
from tools import network as t_network
from tools import screen as t_screen
from tools import system as t_sys
from tools.base import Tool
from tts.piper import TTS

TAG = "AUTONOMOUS"

_CONFIRM_YES = {"sim", "confirmo", "confirma", "pode", "pode sim", "yes", "claro", "ok", "isso"}
_CONFIRM_NO = {"nao", "cancela", "cancelar", "negativo", "no", "deixa", "esquece"}

# Dependencias externas por ferramenta.
# Cada ferramenta mapeia grupos de alternativas: dentro de um grupo basta UM
# binario presente; todos os grupos precisam ser satisfeitos.
# Se faltar dependencia, a acao e rejeitada na validacao (antes de executar).
_TOOL_REQUIREMENTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "volume": (("wpctl", "amixer"),),
    "brightness": (("brightnessctl",),),
    "screenshot": (("gnome-screenshot", "scrot"),),
    "media": (("playerctl",),),
    "open_url": (("xdg-open",),),
    "open_site": (("xdg-open",),),
    "open_folder": (("xdg-open",),),
    "web_search": (("xdg-open",),),
    "lock_screen": (("loginctl", "xdg-screensaver", "gnome-screensaver-command"),),
    "mouse_move": (("xdotool", "python3"),),
    "mouse_click": (("xdotool", "python3"),),
    "mouse_scroll": (("xdotool", "python3"),),
    "type_text": (("xdotool", "python3"),),
    "key_press": (("xdotool", "python3"),),
    "focus_window": (("wmctrl", "xdotool"),),
}

# Parametros realmente obrigatorios de cada ferramenta.
_TOOL_REQUIRED: dict[str, tuple[str, ...]] = {
    "volume": ("step",),
    "brightness": ("step",),
    "mute": ("mode",),
    "media": ("action",),
    "open_app": ("name",),
    "open_site": ("name",),
    "open_url": ("url",),
    "web_search": ("query",),
    "file_search": ("name",),
}

# Ferramentas registradas para execucao autônoma
_AUTONOMOUS_TOOLS: dict[str, Tool] = {}


def _file_search_anywhere(name: str, base: str = "") -> str:
    """Busca o arquivo na home e tambem no diretorio do projeto."""
    found = t_files.file_search(name, base)
    if not found.startswith("Nenhum arquivo"):
        return found
    from core.config import PROJECT_DIR
    if base:
        return found
    return t_files.file_search(name, PROJECT_DIR)


def _register_tools(ares_instance: "AutonomousAres") -> dict[str, Tool]:
    """Registra ferramentas locais disponiveis para execução autônoma."""
    global _AUTONOMOUS_TOOLS
        _AUTONOMOUS_TOOLS = {
            "system_info": Tool("system_info", "CPU, RAM, temperatura, bateria e disco", t_sys.system_info),
            "process_list": Tool("process_list", "Lista processos que mais usam memoria", t_sys.process_list),
            "network_info": Tool("network_info", "IP local e conectividade", t_network.network_info),
            "volume": Tool("volume", "Ajusta o volume (ex.: '40%', '5%+')", t_sys.volume, params={"step": "str"}),
            "mute": Tool("mute", "Muta/desmuta o som (toggle|1|0)", t_sys.mute, params={"mode": "str"}),
            "brightness": Tool("brightness", "Ajusta o brilho (ex.: '10%+', '50%')", t_sys.brightness, params={"step": "str"}),
            "screenshot": Tool("screenshot", "Tira uma captura de tela", t_sys.screenshot),
            "media": Tool("media", "Controla musica (play-pause/next/previous/stop)", t_media.media,
                          params={"action": "str"}),
            "list_dir": Tool("list_dir", "Lista o conteudo de uma pasta", t_files.list_dir, params={"path": "str"}),
            "file_search": Tool("file_search", "Procura arquivos por nome", _file_search_anywhere,
                                params={"name": "str", "base": "str"}),
            "open_folder": Tool("open_folder", "Abre uma pasta (DOWNLOAD, DOCUMENTS...)", t_files.open_folder,
                                params={"kind": "str"}),
            "open_app": Tool("open_app", "Abre um aplicativo pelo nome", t_apps.open_app, params={"name": "str"}),
            "open_site": Tool("open_site", "Abre um site conhecido", t_apps.open_site, params={"name": "str"}),
            "open_url": Tool("open_url", "Abre uma URL", t_apps.open_url, params={"url": "str", "label": "str"}),
            "web_search": Tool("web_search", "Pesquisa na web (google/youtube/wikipedia/maps)", t_apps.web_search,
                               params={"query": "str", "engine": "str"}),
            # Controle de tela
            "mouse_move": Tool("mouse_move", "Move o mouse", t_screen.mouse_move, params={"x": "int", "y": "int", "duration": "float"}, risk="confirm"),
            "mouse_click": Tool("mouse_click", "Clica com mouse", t_screen.mouse_click, params={"button": "str", "clicks": "int", "x": "int", "y": "int"}, risk="confirm"),
            "mouse_scroll": Tool("mouse_scroll", "Rola a tela", t_screen.mouse_scroll, params={"amount": "int"}, risk="confirm"),
            "type_text": Tool("type_text", "Digita texto", t_screen.type_text, params={"text": "str", "delay": "float"}, risk="confirm"),
            "key_press": Tool("key_press", "Envia atalho", t_screen.key_press, params={"keys": "str"}, risk="confirm"),
            "focus_window": Tool("focus_window", "Foca janela", t_screen.focus_window, params={"name": "str"}, risk="confirm"),
            # Ferramentas internas
            "notify": Tool("notify", "Avisa o usuario sobre o que aconteceu", ares_instance._notify,
                           params={"message": "str"}),
            "reset_context": Tool("reset_context", "Limpa o historico da conversa para liberar memoria",
                                  ares_instance._reset_context),
            "reconnect_llm": Tool("reconnect_llm", "Tenta subir/reconectar o servidor llama.cpp",
                                  ares_instance._reconnect_llm),
            # Acoes de risco
            "lock_screen": Tool("lock_screen", "Bloqueia a tela", t_sys.lock_screen, risk="confirm"),
            "poweroff": Tool("poweroff", "Desliga o computador", t_sys.poweroff, risk="confirm"),
            "reboot": Tool("reboot", "Reinicia o computador", t_sys.reboot, risk="confirm"),
            "suspend": Tool("suspend", "Suspende o computador", t_sys.suspend, risk="confirm"),
            "close_app": Tool("close_app", "Fecha um aplicativo pelo nome", t_apps.close_app, risk="confirm",
                              params={"name": "str"}),
        }
    return _AUTONOMOUS_TOOLS


class AutonomousAres:
    """IA Autonoma: detecta intencao, valida e executa em zero rodadas.

    Pode ser usada de duas formas:
    - autonome (CLI): cria o proprio nucleo minimo (router, memoria, LLM);
    - integrada: recebe o nucleo do Ares7 e planeja o que o router local
      nao resolveu, validando antes de executar.
    """

    def __init__(self, config: Config | None = None, core=None) -> None:
        self.core = core
        if core is None:
            self._config = config or Config()
            self._llm = LlamaClient(self._config["llm"])
            self._context = ContextManager(self._config["memory"])
            self._memory_enabled = bool(self._config.get("memory", "enabled", True))
            self._memory = (
                LongTermMemory(str(self._config.get("memory", "db_path", "") or ""))
                if self._memory_enabled
                else None
            )
            self._home_dir = ARES7_HOME
            self._notes_path = os.path.join(ARES7_HOME, "notas.txt")
            self._router = IntentRouter(self)
        self.tools = _register_tools(self)
        self._speak_enabled = True
        self._tts: TTS | None = None
        self._pending_confirm: tuple[str, Any] | None = None
        self._pending_state: dict[str, Any] | None = None
        self._auto_confirm = False
        self._load_pending()

    # ---- acesso ao nucleo (integrado) ou ao nucleo proprio (autonomo) --------------
    # Quando ha um core (Ares7), os atributos sao delegados dinamicamente: assim
    # recarregar o LLM ou a memoria no core vale imediatamente para o motor.
    @property
    def config(self):
        return self.core.config if self.core is not None else self._config

    @property
    def llm(self):
        return self.core.llm if self.core is not None else self._llm

    @llm.setter
    def llm(self, value) -> None:
        if self.core is not None:
            self.core.llm = value
        else:
            self._llm = value

    @property
    def context(self):
        return self.core.context if self.core is not None else self._context

    @property
    def memory(self):
        return self.core.memory if self.core is not None else self._memory

    @property
    def memory_enabled(self) -> bool:
        return self.core.memory_enabled if self.core is not None else self._memory_enabled

    @property
    def home_dir(self) -> str:
        return self.core.home_dir if self.core is not None else self._home_dir

    @property
    def notes_path(self) -> str:
        return self.core.notes_path if self.core is not None else self._notes_path

    @property
    def router(self):
        return self.core.router if self.core is not None else self._router

    # ---- fluxo principal autonomo ------------------------------------------------
    def has_pending(self) -> bool:
        """True se ha uma acao de risco esperando confirmacao."""
        return self._pending_confirm is not None

    def _enabled(self) -> bool:
        return bool(self.config.get("autonomous", "enabled", True))

    def _confirm_required(self) -> bool:
        return bool(self.config.get("autonomous", "confirm_required", True))

    def _llm_planning(self) -> bool:
        return bool(self.config.get("autonomous", "llm_planning", True))

    def run_autonomous(self, request: str, skip_local: bool = False) -> str:
        """Detecta o que o usuario quer fazer, valida e executa. Retorna o resultado.

        skip_local=True: nao tenta as regras locais (quando o chamador ja as
        executou) e vai direto ao planejamento autonomo.
        """
        request = (request or "").strip()
        if not request:
            return "Diga o que voce quer que eu faca."
        log(TAG, f"requisicao autonoma: {request}")

        # 0. Ha uma acao de risco aguardando confirmacao?
        if self._pending_confirm is not None and self.is_confirmation_answer(request):
            return self._resolve_confirmation(request)

        # 1. Fast path: regras locais (nunca acordam o LLM)
        if not skip_local:
            result = self.router.try_handle(request)
            if result is not None:
                if result.confirm:
                    question, action = result.confirm
                    if self._auto_confirm or not self._confirm_required():
                        # Confirmacao ja concedida (ou desativada): executa direto.
                        self._auto_confirm = False
                        try:
                            reply = action()
                        except Exception as exc:
                            reply = f"Falha ao executar: {exc}"
                        self._speak_reply(reply)
                        return reply
                    self._pending_confirm = (question, action)
                    self._pending_state = {"mode": "request", "text": request, "question": question}
                    self._save_pending()
                    return (f"{question}\n"
                            "Responda 'sim' para executar ou 'nao' para cancelar.")
                return result.reply

        # 2. LLM planeja os passos (uma unica chamada: acoes + resposta)
        if self._llm_planning():
            plan = self._plan_with_llm(request)
            if plan is not None:
                actions = plan.get("actions") or []
                if actions:
                    return self._execute_plan(actions, request)
                reply = (plan.get("reply") or "").strip()
                if reply:
                    self.context.add("user", request)
                    self.context.add("assistant", reply)
                    self._speak_reply(reply)
                    return reply

        # 3. LLM offline: tenta responder localmente (memoria/llm indisponivel)
        reply = self._chat(request)
        if reply:
            return reply

        # 4. Falha: nao foi possivel planejar nem responder
        return (
            "Nao consegui entender ou executar essa solicitacao. "
            "Tente: 'verifique o sistema', 'anote comprar pao', "
            "'abra o navegador', 'quanto eh 2+2', 'captura de tela'."
        )

    # ---- confirmacao de acoes de risco --------------------------------------------
    @staticmethod
    def is_confirmation_answer(text: str) -> bool:
        """Diz se o texto e uma resposta de confirmacao ('sim'/'nao')."""
        from core.router import normalize_phrase

        norm = normalize_phrase(text)
        if not norm:
            return False
        first = norm.split()[0]
        return norm in _CONFIRM_YES or norm in _CONFIRM_NO or first in _CONFIRM_YES or first in _CONFIRM_NO

    def _state_path(self) -> str:
        return os.path.join(ARES7_HOME, "autonomous_pending.json")

    def _save_pending(self) -> None:
        """Guarda a acao pendente para sobreviver entre invocacoes do CLI."""
        state = self._pending_state
        try:
            os.makedirs(ARES7_HOME, exist_ok=True)
            if state is None:
                path = self._state_path()
                if os.path.isfile(path):
                    os.remove(path)
                return
            with open(self._state_path(), "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False)
        except OSError as exc:
            log(TAG, f"nao consegui salvar a acao pendente: {exc!r}")

    def _load_pending(self) -> None:
        """Restaura a acao pendente de uma invocacao anterior."""
        path = self._state_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(state, dict):
            return
        mode = state.get("mode")
        if mode == "request":
            self._pending_state = state
            self._pending_confirm = (str(state.get("question", "Confirmar?")),
                                     self._make_request_action(str(state.get("text", ""))))
        elif mode == "step":
            self._pending_state = state
            self._pending_confirm = (str(state.get("question", "Confirmar?")),
                                     self._make_step_action(state.get("tool", ""), state.get("params", {})))

    def _make_request_action(self, text: str):
        """Acao que reexecuta a requisicao original com confirmacao automatica."""
        def action() -> str:
            self._auto_confirm = True
            try:
                return self.run_autonomous(text)
            finally:
                self._auto_confirm = False
        return action

    def _make_step_action(self, tool_name: str, params: dict):
        """Acao que executa um passo de plano aprovado."""
        def action() -> str:
            return self._run_step({"tool": tool_name, "params": params})
        return action

    def _resolve_confirmation(self, answer: str) -> str:
        """Resolve a confirmacao pendente a partir da resposta do usuario."""
        from core.router import normalize_phrase

        question, action = self._pending_confirm  # type: ignore[misc]
        norm = normalize_phrase(answer)
        first = norm.split()[0] if norm.split() else ""

        if norm in _CONFIRM_YES or first in _CONFIRM_YES:
            self._pending_confirm = None
            self._pending_state = None
            self._save_pending()
            try:
                reply = action()  # type: ignore[operator]
            except Exception as exc:
                reply = f"Falha ao executar: {exc}"
            self._speak_reply(reply)
            return reply

        if norm in _CONFIRM_NO or first in _CONFIRM_NO:
            self._pending_confirm = None
            self._pending_state = None
            self._save_pending()
            reply = "Ok, cancelado."
            self._speak_reply(reply)
            return reply

        return (f"Ainda aguardando confirmacao: {question}\n"
                "Responda 'sim' para executar ou 'nao' para cancelar.")

    # ---- resposta conversacional do LLM --------------------------------------------
    def _chat(self, request: str) -> str:
        """Usa o LLM para responder quando nao ha acao local a executar."""
        try:
            online, _model, _err = self.llm.probe()
            if not online:
                online, _model = self.llm.ensure_online()
            if not online:
                return ""
            extra = self.memory.context_for(request) if self.memory else ""
            messages = self.context.build_messages(request, extra_system=extra)
            reply = self.llm.chat(messages)
            self.context.add("user", request)
            self.context.add("assistant", reply)
            self._speak_reply(reply)
            return reply
        except Exception as exc:
            warn(TAG, f"falha na conversa com o LLM: {exc!r}")
            return ""

    # ---- planejamento com LLM ----------------------------------------------------
    def _plan_with_llm(self, request: str) -> dict[str, Any] | None:
        """Uma unica chamada de LLM: devolve as acoes a executar e a resposta final.

        Retorna {"actions": [...], "reply": "..."} ou None se o LLM estiver offline.
        """
        try:
            online, _model, _err = self.llm.probe()
            if not online:
                online, _model = self.llm.ensure_online()
            if not online:
                return None

            tool_list = "\n".join(
                f"- {name}: {t.description}" for name, t in self.tools.items()
            )
            param_list = "\n".join(
                f"  {name}: {', '.join(sorted(t.params)) or '(sem parametros)'}"
                for name, t in self.tools.items()
            )

            system = (
                "Voce e o ARES-7, uma IA autonoma local que roda offline.\n"
                "Usuario pediu: \"{request}\"\n\n"
                "Ferramentas disponiveis:\n{tools}\n\n"
                "Parametros de cada ferramenta:\n{params}\n\n"
                "Responda APENAS com JSON, no formato:\n"
                '{{"actions": [{{"tool": "nome_da_ferramenta", "params": {{...}}}}], '
                '"reply": "resposta curta em portugues"}}\n\n'
                "Regras:\n"
                "- Se o pedido pode ser resolvido por uma ferramenta, coloque a acao em "
                '"actions" e deixe "reply" vazio.\n'
                "- Se o pedido e apenas conversa (pergunta, conversa, texto), deixe "
                '"actions" vazio e responda em "reply" (1-3 frases).\n'
                "- Use apenas nomes de ferramenta da lista. Nao invente parametros.\n"
                "- Nao escreva nada fora do JSON."
            ).format(request=request, tools=tool_list, params=param_list)

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": request},
            ]
            reply = self.llm.chat(messages)
            return self._parse_plan(reply)
        except Exception as exc:
            warn(TAG, f"falha no planejamento LLM: {exc!r}")
            return None

    def _parse_plan(self, raw: str) -> dict[str, Any] | None:
        """Le a resposta do LLM e extrai acoes + reply."""
        text = (raw or "").strip()
        if not text:
            return None
        # Remove cercas de codigo markdown, se houver.
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

        # 1) A resposta inteira e JSON?
        try:
            return self._normalize_plan(json.loads(text))
        except ValueError:
            pass

        # 2) Ha um objeto ou lista embutido no texto?
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, text, re.DOTALL)
            if not match:
                continue
            try:
                data = json.loads(match.group(0))
            except ValueError:
                continue
            plan = self._normalize_plan(data)
            if plan is not None:
                return plan

        return {"actions": [], "reply": text}

    @staticmethod
    def _normalize_plan(data: Any) -> dict[str, Any] | None:
        """Normaliza a resposta do LLM no formato {actions, reply}."""
        if isinstance(data, list):
            return {"actions": [p for p in data if isinstance(p, dict)], "reply": ""}
        if not isinstance(data, dict):
            return None
        if "actions" not in data and "reply" not in data:
            # Objeto que nao tem a forma de um plano: nao serve.
            return None
        actions = data.get("actions")
        if not isinstance(actions, list):
            actions = []
        reply = data.get("reply")
        return {
            "actions": [a for a in actions if isinstance(a, dict)],
            "reply": reply if isinstance(reply, str) else "",
        }

    # ---- execucao de plano -------------------------------------------------------
    def _execute_plan(self, plan: list[dict[str, Any]], original_request: str) -> str:
        """Executa cada acao do plano em sequencia, validando antes."""
        results: list[str] = []
        max_steps = int(self.config.get("autonomous", "max_steps", 10) or 10)
        pending: list[dict[str, Any]] = []

        for step_idx, step in enumerate(plan[:max_steps], 1):
            tool_name = str(step.get("tool", ""))
            params = step.get("params", {}) or {}
            if not isinstance(params, dict):
                params = {}

            if tool_name not in self.tools:
                results.append(f"Passo {step_idx}: ferramenta '{tool_name}' nao encontrada.")
                continue

            tool = self.tools[tool_name]

            # Validacao de pre-requisitos (antes de executar)
            validation = self._validate(tool_name, params)
            if not validation["ok"]:
                if validation.get("needs_confirm"):
                    # Acao de risco: guarda e pede confirmacao (uma unica mensagem).
                    pending.append(step)
                    continue
                results.append(f"Passo {step_idx}: {validation['reason']}")
                continue

            # Execucao
            try:
                reply = tool.run(**params)
                results.append(f"Passo {step_idx}: {reply}")
            except TypeError as exc:
                results.append(f"Passo {step_idx}: parametros invalidos para '{tool_name}': {exc}")
            except Exception as exc:
                results.append(f"Passo {step_idx}: falha ao executar '{tool_name}': {exc}")

        if pending:
            step = pending[0]
            tool_name = str(step.get("tool", ""))
            params = step.get("params", {}) or {}
            question = f"Confirmar '{tool_name}' ({json.dumps(params, ensure_ascii=False)})?"
            self._pending_confirm = (question, self._make_step_action(tool_name, params))
            self._pending_state = {"mode": "step", "tool": tool_name, "params": params,
                                   "question": question}
            self._save_pending()
            results.append(question)
            results.append("Responda 'sim' para executar ou 'nao' para cancelar.")

        if not results:
            return "Nenhuma acao foi executada."

        output = "\n".join(results)
        self._speak_reply(output)
        return output

    def _run_step(self, step: dict[str, Any]) -> str:
        """Executa um passo isolado (usado na confirmacao)."""
        tool_name = str(step.get("tool", ""))
        params = step.get("params", {}) or {}
        tool = self.tools.get(tool_name)
        if tool is None:
            return f"Ferramenta '{tool_name}' nao encontrada."
        try:
            return tool.run(**params)
        except Exception as exc:
            return f"Falha ao executar '{tool_name}': {exc}"

    # ---- validacao de pre-requisitos --------------------------------------------
    def _validate(self, tool_name: str, params: dict) -> dict[str, object]:
        """Verifica se a ferramenta pode ser executada com os parametros dados."""
        tool = self.tools[tool_name]

        # Acoes de risco exigem confirmacao (nao sao zero rodadas)
        if getattr(tool, "risk", "") == "confirm" and not self._auto_confirm and self._confirm_required():
            return {
                "ok": False,
                "reason": f"'{tool_name}' requer confirmacao do usuario.",
                "needs_confirm": True,
            }

        # Parametros obrigatorios (verificados antes das dependencias: sao mais especificos)
        for required in _TOOL_REQUIRED.get(tool_name, ()):
            if not str(params.get(required, "")).strip():
                return {
                    "ok": False,
                    "reason": f"Falta o parametro '{required}' para '{tool_name}'.",
                }

        if tool_name == "volume":
            step = str(params.get("step", ""))
            if not any(ch.isdigit() for ch in step):
                return {"ok": False, "reason": f"Valor de volume invalido: '{step}'."}
            if not re.fullmatch(r"\d{1,3}%?[-+]?", step):
                return {"ok": False, "reason": f"Valor de volume invalido: '{step}' (use '40%' ou '5%+')."}

        if tool_name == "brightness":
            step = str(params.get("step", ""))
            if not re.fullmatch(r"\d{1,3}%?[-+]?", step):
                return {"ok": False, "reason": f"Valor de brilho invalido: '{step}' (use '50%' ou '10%+')."}

        if tool_name == "mute":
            mode = str(params.get("mode", "")).lower()
            if mode not in ("toggle", "1", "0"):
                return {"ok": False, "reason": f"Modo de mudo invalido: '{mode}' (use toggle, 1 ou 0)."}

        if tool_name == "media":
            action = str(params.get("action", "")).lower()
            if action not in ("play-pause", "next", "previous", "stop"):
                return {"ok": False, "reason": f"Acao de midia invalida: '{action}'."}

        if tool_name == "open_app":
            name = str(params.get("name", "")).lower()
            known = {key for keys, _l, _c in t_apps.APPS for key in keys}
            if name and name not in known and not shutil.which(name):
                return {"ok": False, "reason": f"Nao encontrei o aplicativo '{name}' instalado."}

        if tool_name == "open_site":
            name = str(params.get("name", "")).lower()
            if name not in t_apps.SITES:
                return {"ok": False, "reason": f"Site desconhecido: '{name}'."}

        if tool_name == "open_url":
            url = str(params.get("url", ""))
            if not re.match(r"^https?://", url):
                return {"ok": False, "reason": f"URL invalida: '{url}' (deve começar com http:// ou https://)."}

        if tool_name == "file_search":
            base = str(params.get("base", "")).strip()
            if base and not os.path.isdir(os.path.expanduser(base)):
                return {"ok": False, "reason": f"Pasta nao encontrada: '{base}'."}

        if tool_name == "list_dir":
            path = str(params.get("path", "")).strip()
            if path and not os.path.isdir(os.path.expanduser(path)):
                return {"ok": False, "reason": f"Pasta nao encontrada: '{path}'."}

        # Dependencias externas: checadas por ultimo (os erros de parametro
        # e de semantica sao mais especificos e uteis para o usuario).
        for group in _TOOL_REQUIREMENTS.get(tool_name, ()):
            if not any(shutil.which(binary) for binary in group):
                return {
                    "ok": False,
                    "reason": (f"'{tool_name}' precisa de um destes: {', '.join(group)} — "
                               f"nenhum esta instalado."),
                }

        return {"ok": True, "reason": "", "needs_confirm": False}

    # ---- ferramentas internas -------------------------------------------------------
    def _notify(self, message: str = "") -> str:
        """Avisa o usuario. No daemon, a mensagem ja vai para o log/stdout."""
        text = str(message).strip()
        if not text:
            return "Aviso sem mensagem."
        self._speak_reply(text)
        return text

    def _reset_context(self) -> str:
        """Limpa o historico da conversa (libera memoria do LLM)."""
        self.context.reset()
        return "Contexto da conversa limpo."

    def _reconnect_llm(self) -> str:
        """Tenta (re)conectar o servidor llama.cpp."""
        online, model = self.llm.reconnect()
        if online:
            return f"Servidor llama.cpp online ({model or 'modelo desconhecido'})."
        return "Servidor llama.cpp continua offline."

    # ---- fala ---------------------------------------------------------------------
    @property
    def speak_enabled(self) -> bool:
        if self.core is not None:
            return bool(self.core.speak_enabled)
        return self._speak_enabled

    @speak_enabled.setter
    def speak_enabled(self, value: bool) -> None:
        self._speak_enabled = value

    def speak(self, text: str) -> None:
        if not self.speak_enabled:
            return
        if self.core is not None:
            # Nucleo integrado: usa o TTS do proprio ARES7 (respeita --text/--no-tts).
            self.core.speak(text)
            return
        try:
            if self._tts is None:
                self._tts = TTS(self.config["tts"])
            self._tts.speak(text)
        except Exception as exc:
            log(TAG, f"erro TTS: {exc!r}")

    def _speak_reply(self, text: str) -> None:
        """Emite a resposta e fala (se a voz estiver ligada)."""
        if self.core is not None:
            # No modo integrado quem emite e fala e o nucleo (evita duplicar).
            return
        self.emit("ares", text)
        self.speak(text)

    def announce(self, text: str) -> None:
        """Fala por iniciativa propria (timer, lembrete)."""
        if self.core is not None:
            self.core.announce(text)
            return
        self._speak_reply(text)

    def emit(self, kind: str, payload: Any) -> None:
        if self.core is not None:
            self.core.emit(kind, payload)
            return
        log(TAG, f"[{kind}] {payload}")


def run_autonomous_cli(request: str, config_path: str | None = None) -> int:
    """Ponto de entrada para execução autônoma via CLI."""
    config = Config(config_path)
    ares = AutonomousAres(config)
    ares.speak_enabled = False
    result = ares.run_autonomous(request)
    print(result)
    return 0