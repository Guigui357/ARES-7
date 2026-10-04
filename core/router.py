#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roteador de intencoes (INTENT ROUTER).

USER INPUT -> conversation | system command | application control |
file operation | media | network | memory | LLM (fallback)

Regras em linguagem natural PT-BR. Nada de eval/shell arbitrario sem
confirmacao. Comandos de risco ("confirm") passam pelo Core, que pergunta
"Tem certeza?" antes de executar.
"""
from __future__ import annotations

import ast
import datetime
import math
import operator
import re
import threading
import unicodedata

from core.logs import log
from tools import apps as t_apps
from tools import files as t_files
from tools import media as t_media
from tools import network as t_network
from tools import system as t_sys
from tools.common import (CPU_SAMPLER, local_ip, read_battery, read_memory,
                          read_temperature, read_uptime_seconds, run_quiet)

TAG = "ROUTER"

# ============================================================================
# Texto: normalizacao, numeros por extenso, calculadora segura
# ============================================================================

STOPWORDS = frozenset({
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "no", "na", "nos", "nas", "para", "pra", "pro", "por", "favor", "ares", "ei", "ola", "oi",
    "pode", "poderia", "podia", "consegue", "queria", "quero", "gostaria", "preciso", "precisa",
    "voce", "vc", "me", "meu", "minha", "meus", "minhas", "ai", "agora", "ja", "so", "e",
    "ele", "ela", "la", "em", "ao", "aos", "isso", "esse", "essa", "aquele", "mim", "tu",
})
EXPLAIN_RE = re.compile(r"^(?:porque|por que|explique|explica|ensine|ensina|o que (?:e|significa|sao)|para que|quem)\b")
_PHRASE_PREFIXES = ("ares ", "ei ", "ola ", "oi ", "e ai ", "por favor ", "entao ", "agora ")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_phrase(text: str) -> str:
    t = strip_accents(text.lower())
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    changed = True
    while changed:
        changed = False
        for prefix in _PHRASE_PREFIXES:
            if t.startswith(prefix):
                t = t[len(prefix):]
                changed = True
    return t


_NUM_UNITS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}
_NUM_TENS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
}
_SMALL_UNITS = [w for w, v in _NUM_UNITS.items() if 0 < v < 10]
NUMBER_WORDS_RE = (
    r"(?:(?:" + "|".join(_NUM_TENS) + r")(?:\s+e\s+(?:" + "|".join(_SMALL_UNITS) + r"))?"
    r"|cem|" + "|".join(sorted(_NUM_UNITS, key=len, reverse=True)) + r")"
)


def parse_number(token: str) -> float:
    t = token.strip().lower()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
        return float(t.replace(",", "."))
    if t == "cem":
        return 100.0
    total = 0
    for part in re.split(r"\s+e\s+", t):
        if part in _NUM_TENS:
            total += _NUM_TENS[part]
        elif part in _NUM_UNITS:
            total += _NUM_UNITS[part]
        else:
            raise ValueError(f"numero desconhecido: {token}")
    return float(total)


def convert_number_words(text: str, keep_articles: bool = False) -> str:
    def repl(match: "re.Match[str]") -> str:
        word = match.group(0)
        if keep_articles and word.lower() in ("um", "uma"):
            return word
        try:
            return str(int(parse_number(word)))
        except ValueError:
            return word
    return re.sub(r"\b" + NUMBER_WORDS_RE + r"\b", repl, text, flags=re.IGNORECASE)


_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_calc(expression: str) -> float | int:
    """Calculadora segura baseada em AST: so numeros e + - * / // % ** ( )."""
    if len(expression) > 80:
        raise ValueError("Expressao longa demais.")
    if not re.fullmatch(r"[0-9+\-*/().%\s]+", expression):
        raise ValueError("Use apenas numeros e + - * / % ( ).")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError("Expressao invalida.") from exc

    def evaluate(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Expoente grande demais.")
            return _BIN_OPS[type(node.op)](left, right)
        raise ValueError("Expressao invalida.")

    try:
        return evaluate(tree)
    except ZeroDivisionError as exc:
        raise ValueError("Divisao por zero.") from exc
    except (OverflowError, RecursionError, MemoryError) as exc:
        raise ValueError("Resultado grande demais.") from exc


def format_number(value: float | int) -> str:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


def format_duration(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hora" if hours == 1 else f"{hours} horas")
    if minutes:
        parts.append(f"{minutes} minuto" if minutes == 1 else f"{minutes} minutos")
    if secs or not parts:
        parts.append(f"{secs} segundo" if secs == 1 else f"{secs} segundos")
    return " e ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " e " + parts[-1]


# ============================================================================
# Regex de intencoes
# ============================================================================

DURATION_RE = re.compile(
    r"(?P<n>\d+(?:[.,]\d+)?|" + NUMBER_WORDS_RE + r")\s*"
    r"(?P<u>horas?|hrs?|h|minutos?|mins?|m|segundos?|segs?|s)\b",
    re.IGNORECASE,
)
NOTE_RE = re.compile(
    r"^\s*(?:ares[\s,]+)?(?:por favor[\s,]+)?(?:(?:pode|poderia|consegue|vai)\s+)?"
    r"(?:anot(?:e|a|ar)|registr(?:e|a|ar)|(?:salv|tom|adicion|cri)(?:e|ar|a)\s+(?:uma\s+)?nota|nova\s+nota)"
    r"\b(?:\s+(?:que|isso|aqui))?\s*[:,\-]?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
MEM_ADD_RE = re.compile(
    r"^\s*(?:ares[\s,]+)?(?:por favor[\s,]+)?(?:lembre(?:\s*[-\s]se)?|lembra|guarde|memorize|grave)"
    r"\s+(?:que|de|isso)?\s*[:,\-]?\s*(?P<fact>.+)$",
    re.IGNORECASE | re.DOTALL,
)
MEM_DEL_RE = re.compile(
    r"(?:esquec\w*|apagu?\w*|remov\w*|delet\w*)\s+(?:a\s+)?memoria\s*(?:numero|n|#)?\s*(\d+)",
    re.IGNORECASE,
)
SEARCH_RE = re.compile(
    r"^\s*(?:ares[\s,]+)?(?:por favor[\s,]+)?(?:(?:pode|poderia|consegue|vai)\s+)?"
    r"(?:pesquis(?:e|a|ar)|busc(?:a|ar)|busque|procur(?:e|a|ar))\s+(?:por\s+|sobre\s+)?"
    r"(?P<query>.+?)(?:\s+(?:no|na|pelo|pela|do|em)\s+(?P<engine>youtube|google|wikipedia|wikip[eé]dia|maps|mapas))?"
    r"\s*[.!?]*\s*$",
    re.IGNORECASE | re.DOTALL,
)
CALC_RE = re.compile(
    r"^\s*(?:ares[\s,]+)?(?:por favor[\s,]+)?(?:(?:pode|poderia|consegue)\s+)?"
    r"(?P<verb>calcul(?:ar|e|a)\b|quanto\s+(?:[eé]|eh|d[aá]|fica|vale|seria)|resultado\s+d[eo]|conta\s+d[eo])"
    r"\s*(?:d[eo]\s+)?(?P<expr>.+)$",
    re.IGNORECASE | re.DOTALL,
)
BARE_MATH_RE = re.compile(r"[\d\s+\-*/().,^%x×÷]+")

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]

HELP_TEXT = (
    "Fale do seu jeito. Eu entendo:\n"
    "• Abrir: navegador, YouTube, GitHub, terminal, arquivos, pastas, configurações\n"
    "• Pesquisar: \"pesquisa gatos no youtube\"\n"
    "• Sistema: hora, data, bateria, CPU, memória, temperatura, disco, IP, status\n"
    "• Controle: screenshot, volume, mutar, brilho, música, bloquear/desligar/reiniciar (com confirmação)\n"
    "• Calcular: \"quanto é 15 por cento de 200\", \"calcula 2+2\"\n"
    "• Tempo: \"timer de 5 minutos\", \"me lembra de beber água em 10 minutos\"\n"
    "• Notas: \"anota comprar pão\", \"mostra minhas notas\"\n"
    "• Memória: \"lembra que meu projeto se chama X\", \"o que você lembra?\", \"esquece a memória 3\"\n"
    "• \"limpa a conversa\" zera o histórico. O resto eu pergunto ao Qwen."
)


class Utterance:
    """Frase do usuario ja normalizada, para casar intencoes."""

    def __init__(self, raw: str) -> None:
        self.raw = raw.strip()
        self.norm = normalize_phrase(raw)
        self.words = self.norm.split()
        self.wset = set(self.words)
        self.tokens = [w for w in self.words if w not in STOPWORDS]
        self.tset = set(self.tokens)
        self.explain = bool(EXPLAIN_RE.match(self.norm)) or bool(
            self.wset & {"diferenca", "significa", "funciona"})
        self.howto = self.explain or self.norm.startswith("como ")

    def has(self, *words: str) -> bool:
        return any(w in self.tset for w in words)

    def stem(self, *stems: str) -> bool:
        return any(tok.startswith(s) for tok in self.tokens for s in stems)

    def short(self, limit: int) -> bool:
        return len(self.words) <= limit


# ============================================================================
# Resultado de uma intencao
# ============================================================================

class IntentResult:
    """Resposta de uma regra: texto pronto, ou acao pendente de confirmacao."""

    def __init__(self, reply: str, confirm: tuple[str, object] | None = None) -> None:
        self.reply = reply
        self.confirm = confirm  # (pergunta, callable_que_executa)


class IntentRouter:
    """Tenta resolver localmente; retorna None para cair no LLM."""

    def __init__(self, ares) -> None:
        self.ares = ares
        self._timers: list[threading.Event] = []
        self._timers_lock = threading.Lock()
        self._rules = [
            self._intent_memory_add,
            self._intent_memory_query,
            self._intent_memory_del,
            self._intent_memory_list,
            self._intent_note_add,
            self._intent_notes_read,
            self._intent_search,
            self._intent_power,
            self._intent_timer_cancel,
            self._intent_timer,
            self._intent_calc,
            self._intent_help,
            self._intent_clear,
            self._intent_media,
            self._intent_lock,
            self._intent_screenshot,
            self._intent_brightness,
            self._intent_audio,
            self._intent_run_command,
            self._intent_file_ops,
            self._intent_open_url,
            self._intent_open,
            self._intent_info,
        ]

    def try_handle(self, text: str) -> IntentResult | None:
        ut = Utterance(text)
        if not ut.words:
            return None
        try:
            for rule in self._rules:
                result = rule(ut)
                if result is not None:
                    log(TAG, f"intencao local: {rule.__name__}")
                    return result
        except Exception as exc:
            log(TAG, f"erro em regra: {exc!r}")
            return IntentResult(f"Erro ao executar o comando: {exc}")
        return None

    # ---- memoria de longo prazo ------------------------------------------------
    def _intent_memory_add(self, ut: Utterance) -> IntentResult | None:
        if ut.explain or not self.ares.memory_enabled:
            return None
        match = MEM_ADD_RE.match(ut.raw)
        if not match:
            return None
        fact = match.group("fact").strip(" .")
        if len(fact) < 4:
            return IntentResult("O que devo lembrar? Exemplo: lembra que meu projeto se chama X")
        self.ares.memory.add(fact)
        return IntentResult(f"Guardei na memória: {fact}")

    def _intent_memory_query(self, ut: Utterance) -> IntentResult | None:
        if not self.ares.memory_enabled or not ut.short(12):
            return None
        if not ut.has("lembra", "lembra-se", "memoria", "memorias"):
            return None
        if not (ut.stem("o que", "que") or ut.has("sobre", "que") or "que" in ut.wset):
            return None
        if ut.has("memoria", "memorias") and len(ut.tokens) <= 3:
            return None  # "lista as memorias" cai na regra de listagem
        facts = self.ares.memory.search(ut.norm, limit=3)
        if facts:
            return IntentResult("Lembro disso: " + " | ".join(facts))
        return IntentResult("Não tenho nada sobre isso na memória.")

    def _intent_memory_del(self, ut: Utterance) -> IntentResult | None:
        if not self.ares.memory_enabled:
            return None
        match = MEM_DEL_RE.search(ut.raw)
        if not match:
            return None
        fact_id = int(match.group(1))
        if self.ares.memory.remove(fact_id):
            return IntentResult(f"Memória {fact_id} apagada.")
        return IntentResult(f"Não encontrei a memória {fact_id}.")

    def _intent_memory_list(self, ut: Utterance) -> IntentResult | None:
        if not self.ares.memory_enabled or not ut.short(8):
            return None
        if not ut.has("memoria", "memorias"):
            return None
        if not (ut.stem("list", "mostr", "ver", "quais", "abr") or ut.has("minhas", "todas")):
            return None
        facts = self.ares.memory.list(limit=10)
        if not facts:
            return IntentResult("A memória está vazia.")
        lines = [f"#{fid} {content}" for fid, content in facts]
        return IntentResult("Memórias:\n" + "\n".join(lines))

    # ---- notas ------------------------------------------------------------------
    def _intent_note_add(self, ut: Utterance) -> IntentResult | None:
        if ut.explain:
            return None
        match = NOTE_RE.match(ut.raw)
        if not match:
            return None
        note = match.group(1).strip()
        if not note:
            return IntentResult("O que devo anotar? Exemplo: anota comprar pão")
        try:
            import os
            os.makedirs(self.ares.home_dir, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(self.ares.notes_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] {note}\n")
        except OSError as exc:
            return IntentResult(f"Não consegui salvar a nota: {exc}")
        return IntentResult(f"Anotado: {note}")

    def _intent_notes_read(self, ut: Utterance) -> IntentResult | None:
        if ut.explain or not ut.has("notas", "anotacoes", "anotei") or not ut.short(8):
            return None
        if not (ut.stem("le", "lei", "mostr", "list", "ver", "abr", "quais", "fal") or "minhas" in ut.wset):
            return None
        try:
            with open(self.ares.notes_path, "r", encoding="utf-8", errors="replace") as handle:
                raw = handle.read().strip()
        except OSError:
            raw = ""
        if not raw:
            return IntentResult("Você ainda não tem notas.")
        last = raw.splitlines()[-5:]
        return IntentResult("Suas últimas notas:\n" + "\n".join(last))

    # ---- pesquisa na web ----------------------------------------------------------
    def _intent_search(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(20):
            return None
        match = SEARCH_RE.match(ut.raw)
        if not match:
            return None
        query = match.group("query").strip(" .!?")
        if not query:
            return None
        engine_key = strip_accents((match.group("engine") or "google").lower())
        return IntentResult(t_apps.web_search(query, engine_key))

    # ---- energia (confirmacao) ------------------------------------------------------
    def _intent_power(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(10):
            return None
        actions = [
            (("deslig",), ("computador", "pc", "notebook", "sistema", "maquina", "tudo"),
             "desligar o computador", t_sys.poweroff),
            (("reinici", "reboot"), ("computador", "pc", "notebook", "sistema", "maquina"),
             "reiniciar o computador", t_sys.reboot),
            (("suspend", "hibern"), ("computador", "pc", "notebook", "sistema", "maquina"),
             "suspender o computador", t_sys.suspend),
        ]
        for stems, subjects, label, func in actions:
            if ut.stem(*stems) and (ut.has(*subjects) or ut.tset <= set(stems)):
                return IntentResult(
                    "",
                    confirm=(f"Tem certeza que deseja {label}?",
                             lambda f=func, l=label: f()))
        return None

    # ---- timers ----------------------------------------------------------------------
    @staticmethod
    def _parse_duration(text: str) -> int:
        total = 0.0
        for match in DURATION_RE.finditer(text):
            try:
                amount = parse_number(match.group("n"))
            except ValueError:
                continue
            unit = match.group("u").lower()
            if unit.startswith("h"):
                total += amount * 3600
            elif unit.startswith("m"):
                total += amount * 60
            else:
                total += amount
        low = strip_accents(text.lower())
        if re.search(r"\bmeia\s+hora\b", low) and not re.search(r"\bhoras?\s+e\s+meia\b", low):
            total += 1800
        if re.search(r"\bhoras?\s+e\s+meia\b", low):
            total += 1800
        if re.search(r"\bminutos?\s+e\s+meio\b", low):
            total += 30
        return int(total)

    def _intent_timer_cancel(self, ut: Utterance) -> IntentResult | None:
        if not ut.stem("timer", "temporiz", "alarm", "cronomet", "lembret"):
            return None
        if not ut.stem("cancel", "par", "desativ", "apag", "desfaz", "esquec"):
            return None
        with self._timers_lock:
            active = [e for e in self._timers if not e.is_set()]
            for event in self._timers:
                event.set()
            self._timers = []
        if not active:
            return IntentResult("Não há nenhum timer ativo.")
        return IntentResult("Timer cancelado." if len(active) == 1 else f"{len(active)} timers cancelados.")

    def _intent_timer(self, ut: Utterance) -> IntentResult | None:
        if ut.explain or not ut.short(24):
            return None
        keywords = ("timer", "temporiz", "cronomet", "alarm", "desperta", "avis", "lembr", "contagem")
        if not ut.stem(*keywords):
            return None
        raw = ut.raw
        seconds = self._parse_duration(raw)
        if seconds <= 0:
            bare = re.search(r"\b(?:timer|temporizador|cronometro|cronômetro)\s+(?:de\s+)?(\d+)\s*$", raw, re.IGNORECASE)
            if not bare:
                return None
            seconds = int(bare.group(1))
        if seconds < 1 or seconds > 86400:
            return IntentResult("O timer precisa ficar entre 1 segundo e 24 horas.")
        message = self._extract_reminder(raw)
        label = format_duration(seconds)
        event = threading.Event()
        with self._timers_lock:
            self._timers = [e for e in self._timers if not e.is_set()]
            self._timers.append(event)
        threading.Thread(target=self._timer_worker, args=(seconds, label, message, event), daemon=True).start()
        if message:
            return IntentResult(f"Combinado. Aviso em {label}: {message}.")
        return IntentResult(f"Timer de {label} iniciado.")

    @staticmethod
    def _extract_reminder(raw: str) -> str:
        rest = DURATION_RE.sub(" ", raw)
        rest = re.sub(r"\b(?:meia\s+hora|horas?\s+e\s+meia|minutos?\s+e\s+meio)\b", " ", rest, flags=re.IGNORECASE)
        match = re.search(r"(?:lembr\w*|avis\w*)\s+(?:me\s+)?(?:de\s+|que\s+|para\s+|pra\s+|sobre\s+)?(.*)$",
                          rest, re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        message = match.group(1)
        connectors = r"(?:daqui\s+a|dentro\s+de|depois\s+de|em|de|e|por\s+favor|ares)"
        for _ in range(4):
            message = message.strip(" .,!?;:\n")
            message = re.sub(r"^" + connectors + r"\s+", "", message, flags=re.IGNORECASE)
            message = re.sub(r"\s+" + connectors + r"$", "", message, flags=re.IGNORECASE)
        message = re.sub(r"\s+", " ", message).strip(" .,!?;:")
        if re.fullmatch(connectors, message, flags=re.IGNORECASE) or len(message) < 3:
            return ""
        return message

    def _timer_worker(self, seconds: int, label: str, message: str, event: threading.Event) -> None:
        if event.wait(seconds):
            return
        if message:
            self.ares.announce(f"Lembrete: {message}.")
        else:
            self.ares.announce(f"Timer de {label} finalizado.")

    # ---- calculadora ----------------------------------------------------------------
    @staticmethod
    def _prepare_expression(text: str) -> str:
        expr = text
        expr = re.sub(r"(?<=\d),(?=\d)", ".", expr)
        expr = re.sub(r"\bao\s+quadrado\b", "**2", expr)
        expr = re.sub(r"\bao\s+cubo\b", "**3", expr)
        expr = re.sub(r"\belevado\s+a\s*", "**", expr)
        expr = re.sub(r"\bmais\b", "+", expr)
        expr = re.sub(r"\bmenos\b", "-", expr)
        expr = re.sub(r"\b(?:vezes|multiplicado\s+por)\b", "*", expr)
        expr = re.sub(r"\bdividido(?:\s+por)?\b", "/", expr)
        expr = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", expr)
        expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
        expr = re.sub(r"\s*\*\*\s*", "**", expr)
        return expr.strip().rstrip(" .!?=")

    def _intent_calc(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(30):
            return None
        match = CALC_RE.match(ut.raw)
        strict = False
        if match:
            expr_raw = match.group("expr")
            strict = match.group("verb").lower().startswith("calcul")
        else:
            candidate = ut.raw.strip().rstrip("=?! ")
            if (BARE_MATH_RE.fullmatch(candidate) and re.search(r"\d", candidate)
                    and re.search(r"[+\-*/^%x×÷]", candidate)):
                expr_raw = candidate
            elif re.search(r"por\s*cento\s+d[eo]|raiz\s+(?:quadrada\s+)?d[eo]", ut.norm):
                expr_raw = ut.raw
            else:
                return None
        text = convert_number_words(strip_accents(expr_raw.lower()))

        percent = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:por\s*cento|%)\s*d[eo]\s*(\d+(?:[.,]\d+)?)", text)
        if percent:
            p = parse_number(percent.group(1))
            v = parse_number(percent.group(2))
            return IntentResult(f"{format_number(p)}% de {format_number(v)} = {format_number(p * v / 100.0)}")
        root = re.search(r"raiz\s+(?:quadrada\s+)?d[eo]\s*(\d+(?:[.,]\d+)?)", text)
        if root:
            n = parse_number(root.group(1))
            return IntentResult(f"A raiz quadrada de {format_number(n)} é {format_number(math.sqrt(n))}")

        expr = self._prepare_expression(text)
        if not expr:
            return IntentResult("Informe uma expressão, por exemplo: calcula 2+2") if strict else None
        try:
            value = safe_calc(expr)
        except ValueError as exc:
            return IntentResult(f"Não consegui calcular: {exc}") if strict else None
        return IntentResult(f"{expr} = {format_number(value)}")

    # ---- ajuda / historico -------------------------------------------------------------
    def _intent_help(self, ut: Utterance) -> IntentResult | None:
        if not ut.short(8):
            return None
        if ut.has("ajuda", "comandos", "help"):
            return IntentResult(HELP_TEXT)
        if "voce" in ut.wset and ut.has("fazer", "sabe", "consegue") and ("o" in ut.wset or "que" in ut.wset):
            return IntentResult(HELP_TEXT)
        return None

    def _intent_clear(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(8):
            return None
        if ut.has("memoria", "memorias") and ut.stem("limp", "apag", "zer", "esquec"):
            if self.ares.memory_enabled:
                count = self.ares.memory.clear()
                return IntentResult(f"Memória apagada ({count} itens removidos).")
        if ut.has("conversa", "historico", "contexto") and ut.stem("limp", "esquec", "apag", "reset", "reinici", "zer"):
            self.ares.context.reset()
            return IntentResult("Conversa limpa. Começamos do zero.")
        return None

    # ---- midia / bloqueio ------------------------------------------------------------------
    def _intent_media(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(10):
            return None
        subject = ut.has("musica", "musicas", "faixa", "video", "player", "spotify", "reproducao")
        action = None
        if ut.stem("paus", "retom") and (subject or ut.tokens in (["pausar"], ["pause"], ["pausa"])):
            action = "play-pause"
        elif ut.tset == {"play"} or ut.tset == {"pause"}:
            action = "play-pause"
        elif ut.stem("prox", "pul", "avanc", "skip") and subject:
            action = "next"
        elif subject and (ut.has("anterior", "voltar", "volta", "volte") or ut.stem("anteri")):
            action = "previous"
        elif ut.tset == {"proxima"} or ut.tset == {"proximo"} or ut.tset == {"anterior"}:
            action = "previous" if ut.has("anterior") else "next"
        if action is None:
            return None
        return IntentResult(t_media.media(action))

    def _intent_lock(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(8):
            return None
        if not (ut.stem("bloque", "tranc") and ut.has("tela", "computador", "pc", "sessao", "notebook")):
            return None
        return IntentResult("", confirm=("Tem certeza que deseja bloquear a tela?",
                                         t_sys.lock_screen))

    # ---- screenshot ---------------------------------------------------------------------------
    def _intent_screenshot(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(10):
            return None
        wanted = (ut.has("screenshot", "screenshots", "print", "prints", "printscreen")
                  or (ut.has("captura", "capturar", "foto") and ut.has("tela", "monitor"))
                  or ut.tset == {"captura"})
        if not wanted:
            return None
        return IntentResult(t_sys.screenshot())

    # ---- volume / mudo / brilho ------------------------------------------------------------------
    def _intent_audio(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(12):
            return None
        norm = ut.norm
        volume_word = ut.has("volume", "som", "audio", "volumes")
        if (re.search(r"\b(?:desmut\w*|reativ\w*|unmute)\b", norm)
                or re.search(r"\b(?:ligar|liga|ligue|volta|volte|voltar|ativar|ative|ativa|tirar|tira)\s+(?:o\s+)?(?:som|mudo)\b", norm)):
            return IntentResult(t_sys.mute("0"))
        if ut.stem("mut", "silenc") or ut.has("mute") or "sem som" in norm:
            return IntentResult(t_sys.mute("toggle"))
        if volume_word:
            converted = convert_number_words(norm, keep_articles=True)
            level = re.search(r"\b(\d{1,3})\b", converted)
            if level:
                return IntentResult(t_sys.volume(f"{min(100, int(level.group(1)))}%"))
            if ut.has("maximo", "maxima"):
                return IntentResult(t_sys.volume("100%"))
            if ut.has("minimo", "minima"):
                return IntentResult(t_sys.volume("0%"))
            if ut.has("metade"):
                return IntentResult(t_sys.volume("50%"))
        quick = ut.short(4) and ut.has("mais", "menos")
        if volume_word or quick:
            if ut.stem("diminu", "abaix", "baix", "reduz", "menos", "menor"):
                return IntentResult(t_sys.volume("5%-"))
            if ut.stem("aument", "sub", "elev", "mais", "maior", "alto", "alta") or ut.has("sobe"):
                return IntentResult(t_sys.volume("5%+"))
        return None

    def _intent_brightness(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(10) or not ut.has("brilho"):
            return None
        level = re.search(r"\b(\d{1,3})\b", convert_number_words(ut.norm, keep_articles=True))
        if level:
            step = f"{min(100, int(level.group(1)))}%"
        elif ut.stem("diminu", "abaix", "baix", "reduz", "menos", "menor", "escur"):
            step = "10%-"
        elif ut.stem("aument", "sub", "elev", "mais", "maior", "alto", "alta", "clare"):
            step = "10%+"
        else:
            return None
        return IntentResult(t_sys.brightness(step))

    # ---- executar comando de shell (perigoso -> confirmacao) ---------------------------------------
    def _intent_run_command(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(14):
            return None
        match = re.match(r"^(?:ares[\s,]+)?(?:por favor[\s,]+)?"
                         r"(?:execut[ae]|rode|rodar)\s+(?:o\s+comando\s+)?[:\"]?(?P<cmd>.+?)[\"]?\s*$",
                         ut.raw, re.IGNORECASE | re.DOTALL)
        if not match or not ut.stem("execut", "rod"):
            return None
        cmd = match.group("cmd").strip()
        if not cmd or len(cmd) > 200:
            return IntentResult("Comando vazio ou longo demais.")
        dangerous = re.search(r"\b(rm|mkfs|dd|shutdown|reboot|poweroff|chmod|chown|sudo)\b", cmd)
        if dangerous:
            return None  # comandos destrutivos nao passam nem com confirmacao
        def _run(c: str = cmd) -> str:
            code, out = run_quiet(["/bin/sh", "-c", c], timeout=30)
            out = out[:400] or "(sem saída)"
            return f"Comando terminou ({code}):\n{out}"
        return IntentResult("", confirm=(f"Executar o comando \"{cmd}\"?", _run))

    # ---- arquivos ------------------------------------------------------------------------------------
    def _intent_file_ops(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(16):
            return None
        if ut.stem("procur", "busc", "encontr", "ach") and ut.has("arquivo", "arquivos", "pasta"):
            match = re.search(r"(?:arquivo|pasta)s?\s+(?:chamad[ao]\s+|nomead[ao]\s+)?[\"']?([\w.\- ]+?)[\"']?\s*$",
                              ut.norm)
            if match:
                return IntentResult(t_files.file_search(match.group(1).strip()))
        if ut.stem("list", "mostr") and ut.has("pasta", "diretorio", "arquivos") and ut.short(8):
            return IntentResult(t_files.list_dir())
        return None

    # ---- abrir URL direta -------------------------------------------------------------------------------
    def _intent_open_url(self, ut: Utterance) -> IntentResult | None:
        if ut.howto:
            return None
        match = re.search(r"(?:abrir|abra|acessar|acesse|ir para|entrar em)\s+((?:https?://)?(?:www\.)?[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?)", ut.raw, re.IGNORECASE)
        if not match:
            return None
        url = match.group(1)
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        return IntentResult(t_apps.open_url(url, "o endereço solicitado"))

    # ---- abrir sites, apps e pastas ---------------------------------------------------------------------
    def _intent_open(self, ut: Utterance) -> IntentResult | None:
        if ut.howto or not ut.short(14):
            return None
        wants_open = (ut.stem("abr", "inici", "execut", "lanc", "chama", "rod", "mostr", "acess", "entr", "ligu")
                      or ut.has("ir", "va", "vai", "ver"))
        wants_close = ut.stem("fech", "encer", "termin", "mat")
        bare = len(ut.tokens) <= 2
        if wants_close:
            for keys, label, _candidates in t_apps.APPS:
                if ut.tset & keys:
                    return IntentResult("", confirm=(f"Fechar {label}?",
                                                     lambda k=next(iter(keys)): t_apps.close_app(k)))
            return None
        if not (wants_open or bare):
            return None
        folders = ({"downloads", "download", "baixados"}, {"documentos", "documento"},
                   {"imagens", "fotos", "figuras"}, {"musicas"}, {"videos"}, {"desktop", "trabalho"})
        folder_kinds = ["DOWNLOAD", "DOCUMENTS", "PICTURES", "MUSIC", "VIDEOS", "DESKTOP"]
        for keys, kind in zip(folders, folder_kinds):
            if ut.has(*keys) and (ut.has("pasta", "diretorio") or wants_open):
                return IntentResult(t_files.open_folder(kind))
        for name in t_apps.SITES:
            if name in ut.tset:
                return IntentResult(t_apps.open_site(name))
        for keys, label, _candidates in t_apps.APPS:
            if ut.tset & keys:
                return IntentResult(t_apps.open_app(next(iter(keys))))
        if ut.has("navegador", "browser", "internet", "web") and wants_open:
            return IntentResult(t_apps.open_url("https://www.google.com", "o navegador"))
        return None

    # ---- informacoes do sistema ----------------------------------------------------------------------------
    def _intent_info(self, ut: Utterance) -> IntentResult | None:
        if ut.explain or not ut.short(9):
            return None
        wset = ut.wset
        if ut.has("hora", "horas") and (wset & {"que", "qual", "quantas", "sao", "agora", "atual", "certa"}
                                        or ut.tokens in (["hora"], ["horas"])):
            return IntentResult(self._time_reply())
        if (ut.has("data") and (wset & {"qual", "hoje", "atual"})) or (
                ut.has("dia") and (wset & {"hoje", "estamos", "semana"})) or ut.tokens == ["data"]:
            return IntentResult(self._date_reply())
        if ut.has("bateria", "carga", "baterias"):
            battery = read_battery()
            return IntentResult(f"Bateria em {battery}." if battery else "Não detectei bateria neste computador.")
        if ut.has("temperatura", "temperaturas", "esquentando", "superaquecimento"):
            temp = read_temperature()
            if temp is None:
                return IntentResult("Não consegui ler a temperatura do computador.")
            weather = wset & {"clima", "previsao", "chover", "chuva", "fora", "rua", "cidade", "tempo"}
            prefix = "Não tenho previsão do tempo offline. " if weather else ""
            return IntentResult(f"{prefix}A temperatura do computador é {temp:.0f} graus.")
        if ut.has("cpu", "processador"):
            cpu = CPU_SAMPLER.percent()
            return IntentResult(f"CPU em {cpu:.0f} por cento." if cpu is not None else "Não consegui ler o uso da CPU.")
        if ut.has("ram", "memoria"):
            memory = read_memory()
            if not memory:
                return IntentResult("Não consegui ler a memória.")
            gb = 1024 ** 3
            return IntentResult(f"Memória: {memory[0] / gb:.1f} de {memory[1] / gb:.1f} gigabytes em uso.")
        if ut.has("disco", "armazenamento", "hd", "ssd") or (ut.has("espaco") and ut.has("livre", "disco")):
            import shutil
            usage = shutil.disk_usage("/")
            gb = 1024 ** 3
            pct = 100.0 * usage.used / usage.total
            return IntentResult(f"Disco: {usage.used / gb:.0f} de {usage.total / gb:.0f} gigabytes usados, {pct:.0f} por cento.")
        if ut.has("ip") and (wset & {"meu", "qual", "endereco", "local"}):
            ip = local_ip()
            return IntentResult(f"Seu IP local é {ip}." if ip else "Não detectei conexão de rede.")
        if ut.has("uptime") or (ut.has("ligado") and ut.has("tempo", "quanto")):
            seconds = read_uptime_seconds()
            if seconds is None:
                return IntentResult("Não consegui ler o tempo ligado.")
            return IntentResult(f"O computador está ligado há {format_duration(seconds)}.")
        if ut.has("processos", "processo") and ut.stem("list", "mostr", "quais", "ver"):
            return IntentResult(t_sys.process_list())
        if (ut.has("status", "diagnostico")
                or ut.tokens == ["sistema"]
                or (ut.has("sistema", "computador", "maquina", "notebook")
                    and wset & {"como", "esta", "estado", "uso", "situacao"})):
            return IntentResult(t_sys.system_info())
        if ut.has("rede", "internet", "conexao") and wset & {"como", "esta", "status", "testar", "teste"}:
            return IntentResult(t_network.network_info())
        return None

    # ---- respostas de data/hora ---------------------------------------------------------------------------------
    @staticmethod
    def _time_reply() -> str:
        now = datetime.datetime.now()
        h, m = now.hour, now.minute
        if h == 0:
            base = "É meia-noite"
        elif h == 12 and m == 0:
            return "É meio-dia."
        elif h == 1:
            base = "É 1 hora"
        else:
            base = f"São {h} horas"
        if m:
            base += f" e {m} minuto" + ("" if m == 1 else "s")
        return base + "."

    @staticmethod
    def _date_reply() -> str:
        now = datetime.datetime.now()
        return f"Hoje é {WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]} de {now.year}."
