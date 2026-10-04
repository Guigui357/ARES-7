#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas de arquivos: buscar, ler, criar, listar diretorios."""
from __future__ import annotations

import os

from tools.base import Tool
from tools.common import launch_detached, user_dir

HOME = os.path.expanduser("~")


def list_dir(path: str = "") -> str:
    path = os.path.expanduser(path) if path else HOME
    if not os.path.isdir(path):
        return f"Pasta nao encontrada: {path}"
    try:
        entries = sorted(os.listdir(path))[:30]
    except OSError as exc:
        return f"Nao consegui listar {path}: {exc}"
    if not entries:
        return f"{path} esta vazia."
    return f"Conteudo de {path}:\n" + "\n".join(entries)


def open_file(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"Arquivo nao encontrado: {path}"
    import shutil
    opener = shutil.which("xdg-open")
    if not opener:
        return "xdg-open nao encontrado. Instale: sudo apt install xdg-utils"
    launch_detached([opener, path])
    return f"Abrindo {path}."


def open_folder(kind: str = "HOME") -> str:
    mapping = {
        "DOWNLOAD": ("DOWNLOAD", "Downloads"), "DOCUMENTS": ("DOCUMENTS", "Documents"),
        "PICTURES": ("PICTURES", "Pictures"), "MUSIC": ("MUSIC", "Music"),
        "VIDEOS": ("VIDEOS", "Videos"), "DESKTOP": ("DESKTOP", "Desktop"),
    }
    if kind.upper() in mapping:
        xdg_kind, fallback = mapping[kind.upper()]
        path = user_dir(xdg_kind, fallback)
    else:
        path = HOME
    if not os.path.isdir(path):
        return f"A pasta nao existe: {path}"
    import shutil
    opener = shutil.which("xdg-open")
    if not opener:
        return "xdg-open nao encontrado. Instale: sudo apt install xdg-utils"
    launch_detached([opener, path])
    return f"Abrindo a pasta {path}."


def file_search(name: str, base: str = "") -> str:
    """Busca arquivo por nome (substrings, sem case) a partir de `base` (default: ~)."""
    base = os.path.expanduser(base) if base else HOME
    needle = name.lower()
    hits: list[str] = []
    skipped = {".cache", ".config/google-chrome", "snap", ".mozilla", "node_modules"}
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skipped and not d.startswith(".git")]
            for fname in files:
                if needle in fname.lower():
                    hits.append(os.path.join(root, fname))
                    if len(hits) >= 10:
                        break
            if len(hits) >= 10:
                break
    except OSError:
        pass
    if not hits:
        return f"Nenhum arquivo parecido com '{name}' em {base}."
    return f"Encontrei {len(hits)}:\n" + "\n".join(hits)


def file_read(path: str, max_chars: int = 1500) -> str:
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"Arquivo nao encontrado: {path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(max_chars + 1)
    except OSError as exc:
        return f"Nao consegui ler {path}: {exc}"
    if len(content) > max_chars:
        content = content[:max_chars] + "\n… (cortado)"
    return content


def file_write(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        return f"Nao consegui escrever {path}: {exc}"
    return f"Arquivo salvo em {path}."


TOOLS = [
    Tool("list_dir", "Lista o conteudo de uma pasta", list_dir, params={"path": "str"}),
    Tool("open_file", "Abre um arquivo com o app padrao", open_file, params={"path": "str"}),
    Tool("open_folder", "Abre uma pasta (Downloads, Documentos...)", open_folder, params={"kind": "str"}),
    Tool("file_search", "Procura arquivos por nome", file_search, params={"name": "str", "base": "str"}),
    Tool("file_read", "Le o inicio de um arquivo de texto", file_read, params={"path": "str"}),
    Tool("file_write", "Cria um arquivo de texto", file_write, risk="confirm",
         params={"path": "str", "content": "str"}),
]
