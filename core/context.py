#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gerenciador de contexto: a cura para o erro "6418 tokens exceeds available 2048".

- estimativa de tokens (~3.5 chars/token em PT-BR, com margem)
- teto de tokens para system + historico + mensagem atual
- historico limitado a N mensagens recentes
- compactacao: mensagens antigas viram um resumo curto de 1 linha
- truncamento inteligente da mensagem do usuario
- limpeza automatica
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = (
    "Você é ARES7, um assistente local que roda offline.\n"
    "Responda em português, de forma curta e direta (1-3 frases), "
    "a menos que o usuário peça detalhes."
)

CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN) + 4)


def truncate_text(text: str, max_tokens: int) -> str:
    """Corta o texto no fim de uma frase, sem passar do teto de tokens."""
    if estimate_tokens(text) <= max_tokens:
        return text
    limit = int(max_tokens * CHARS_PER_TOKEN)
    cut = text[:limit]
    sentence_end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("\n"))
    if sentence_end > limit // 2:
        cut = cut[: sentence_end + 1]
    return cut.rstrip() + "…"


class ContextManager:
    def __init__(self, cfg: dict) -> None:
        self.max_messages = int(cfg.get("max_messages", 8))
        self.budget = int(cfg.get("max_tokens_budget", 1200))
        self.history: list[dict] = []   # [{"role": "user"/"assistant", "content": str}]
        self.summary = ""               # resumo das mensagens antigas

    # ---- historico ----------------------------------------------------------
    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        self._compact_if_needed()

    def _compact_if_needed(self) -> None:
        """Quando o historico cresce, as metades mais antigas viram resumo."""
        while len(self.history) > self.max_messages * 2:
            old = self.history[: len(self.history) // 2]
            self.history = self.history[len(self.history) // 2:]
            facts = []
            for msg in old:
                content = re.sub(r"\s+", " ", msg["content"]).strip()
                facts.append(content[:80])
            joined = "; ".join(facts)
            self.summary = truncate_text(joined, 120)
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)

    def reset(self) -> None:
        self.history = []
        self.summary = ""

    # ---- montagem do prompt --------------------------------------------------
    def build_messages(self, user_text: str, extra_system: str = "") -> list[dict]:
        """Monta a lista de mensagens cabendo no orcamento de tokens."""
        system = SYSTEM_PROMPT
        if extra_system:
            system += "\n" + truncate_text(extra_system, 120)
        if self.summary:
            system += f"\nContexto anterior (resumo): {self.summary}"
        budget = self.budget - estimate_tokens(system) - estimate_tokens(user_text) - 20
        user_text = truncate_text(user_text, max(64, self.budget // 2))
        messages: list[dict] = [{"role": "system", "content": system}]
        recent: list[dict] = []
        for msg in reversed(self.history[-self.max_messages:]):
            cost = estimate_tokens(msg["content"])
            if cost > budget:
                break
            recent.insert(0, msg)
            budget -= cost
        messages.extend(recent)
        messages.append({"role": "user", "content": user_text})
        return messages
