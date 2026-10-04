#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ferramentas de aplicativos e sites."""
from __future__ import annotations

import shutil
import urllib.parse

from tools.base import Tool
from tools.common import first_executable, launch_detached, run_quiet

SITES = {
    "youtube": ("https://www.youtube.com", "o YouTube"),
    "github": ("https://github.com", "o GitHub"),
    "gmail": ("https://mail.google.com", "o Gmail"),
    "google": ("https://www.google.com", "o Google"),
    "maps": ("https://www.google.com/maps", "o Google Maps"),
    "mapas": ("https://www.google.com/maps", "o Google Maps"),
    "wikipedia": ("https://pt.wikipedia.org", "a Wikipédia"),
    "spotify": ("https://open.spotify.com", "o Spotify"),
    "whatsapp": ("https://web.whatsapp.com", "o WhatsApp Web"),
    "drive": ("https://drive.google.com", "o Google Drive"),
    "linkedin": ("https://www.linkedin.com", "o LinkedIn"),
    "netflix": ("https://www.netflix.com", "a Netflix"),
}

APPS = [
    ({"terminal", "console"}, "o terminal",
     ["gnome-terminal", "x-terminal-emulator", "konsole", "xfce4-terminal", "xterm"]),
    ({"calculadora"}, "a calculadora", ["gnome-calculator", "kcalc", "galculator", "mate-calc"]),
    ({"arquivos", "explorador", "nautilus", "nemo", "thunar"}, "o gerenciador de arquivos",
     ["nautilus", "nemo", "thunar", "dolphin", "pcmanfm"]),
    ({"configuracoes", "configuracao", "ajustes", "settings"}, "as configurações",
     ["gnome-control-center", "systemsettings", "xfce4-settings-manager"]),
    ({"editor", "gedit", "bloco"}, "o editor de texto",
     ["gnome-text-editor", "gedit", "kate", "mousepad", "xed"]),
    ({"monitor", "tarefas"}, "o monitor do sistema",
     ["gnome-system-monitor", "ksysguard", "xfce4-taskmanager"]),
    ({"firefox"}, "o Firefox", ["firefox"]),
    ({"chrome", "chromium"}, "o Chrome", ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]),
    ({"brave"}, "o Brave", ["brave-browser", "brave"]),
]

SEARCH_ENGINES = {
    "google": ("https://www.google.com/search?q=", "Google"),
    "youtube": ("https://www.youtube.com/results?search_query=", "YouTube"),
    "wikipedia": ("https://pt.wikipedia.org/w/index.php?search=", "Wikipédia"),
    "maps": ("https://www.google.com/maps/search/", "Google Maps"),
    "mapas": ("https://www.google.com/maps/search/", "Google Maps"),
}


def _opener() -> str | None:
    return shutil.which("xdg-open")


def open_url(url: str, label: str = "o site") -> str:
    opener = _opener()
    if not opener:
        return "xdg-open nao encontrado. Instale: sudo apt install xdg-utils"
    launch_detached([opener, url])
    return f"Abrindo {label}."


def open_site(name: str) -> str:
    entry = SITES.get(name.lower())
    if not entry:
        return f"Site desconhecido: {name}. Conheço: {', '.join(sorted(SITES))}."
    return open_url(entry[0], entry[1])


def open_app(name: str) -> str:
    low = name.lower()
    for keys, label, candidates in APPS:
        if low in keys or any(low.startswith(k) or k.startswith(low) for k in keys):
            exe = first_executable(candidates)
            if not exe:
                return f"Nao encontrei {label} instalado."
            launch_detached([exe])
            return f"Abrindo {label}."
    exe = shutil.which(low)
    if exe:
        launch_detached([exe])
        return f"Abrindo {low}."
    return f"Nao encontrei o aplicativo '{name}'."


def close_app(name: str) -> str:
    code, out = run_quiet(["pkill", "-f", "-i", name], timeout=8)
    if code == 0:
        return f"Fechando {name}."
    return f"Nao encontrei '{name}' em execucao ({out or 'sem processo'})."


def web_search(query: str, engine: str = "google") -> str:
    base, label = SEARCH_ENGINES.get(engine.lower(), SEARCH_ENGINES["google"])
    return open_url(base + urllib.parse.quote_plus(query), f"a pesquisa no {label}")


TOOLS = [
    Tool("open_app", "Abre um aplicativo pelo nome", open_app, params={"name": "str"}),
    Tool("close_app", "Fecha um aplicativo pelo nome", close_app, risk="confirm", params={"name": "str"}),
    Tool("open_site", "Abre um site conhecido", open_site, params={"name": "str"}),
    Tool("web_search", "Pesquisa na web (google/youtube/wikipedia/maps)", web_search,
         params={"query": "str", "engine": "str"}),
]
