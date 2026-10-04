#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Memoria local do ARES7.

- Short-term: fica no ContextManager (ultimas mensagens).
- Long-term: SQLite em ~/.ares/memory.db (sem dependencias externas).

IMPORTANTE: a memoria longa NUNCA vai inteira para o prompt. So entram
fatores relevantes recuperados por busca simples por palavras-chave.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading

from core.config import ARES7_HOME
from core.logs import debug

TAG = "MEMORY"


class LongTermMemory:
    def __init__(self, db_path: str = "") -> None:
        self.path = db_path or os.path.join(ARES7_HOME, "memory.db")
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "content TEXT NOT NULL,"
                "created TEXT DEFAULT (datetime('now', 'localtime')))")
            self._conn.commit()
        return self._conn

    # ---- CRUD -----------------------------------------------------------------
    def add(self, content: str) -> int:
        content = re.sub(r"\s+", " ", content).strip()
        with self._lock:
            cur = self._db().execute("INSERT INTO facts (content) VALUES (?)", (content,))
            self._db().commit()
            debug(TAG, f"memoria #{cur.lastrowid} salva")
            return int(cur.lastrowid)

    def remove(self, fact_id: int) -> bool:
        with self._lock:
            cur = self._db().execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self._db().commit()
            return cur.rowcount > 0

    def clear(self) -> int:
        with self._lock:
            cur = self._db().execute("DELETE FROM facts")
            self._db().commit()
            return cur.rowcount

    def list(self, limit: int = 50) -> list[tuple[int, str]]:
        with self._lock:
            rows = self._db().execute(
                "SELECT id, content FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [(int(r[0]), str(r[1])) for r in rows]

    def search(self, query: str, limit: int = 3) -> list[str]:
        """Busca simples por palavras-chave (LIKE); retorna conteudos."""
        words = [w for w in re.findall(r"\w{4,}", query.lower())][:6]
        if not words:
            return []
        clauses = " OR ".join("LOWER(content) LIKE ?" for _ in words)
        params = [f"%{w}%" for w in words]
        with self._lock:
            rows = self._db().execute(
                f"SELECT content FROM facts WHERE {clauses} ORDER BY id DESC LIMIT ?",
                (*params, limit)).fetchall()
        return [str(r[0]) for r in rows]

    def context_for(self, query: str) -> str:
        """Trecho curto para o system prompt (ou vazio). Nunca a base inteira."""
        facts = self.search(query, limit=3)
        if not facts:
            return ""
        joined = " | ".join(f[:80] for f in facts)
        return f"Fatos lembrados: {joined}"[:400]
