#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descoberta de dispositivos de entrada de áudio.

Lista dispositivos ALSA reais usando `arecord -l`.
Também pode listar fontes PipeWire/Pulse.

Exemplo:
    [0] hw:0,0 - HDA Intel PCH - ALC256 Analog

O dispositivo ALSA retornado é `hw:X,Y`, sem plughw.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from core.logs import debug, warn

TAG = "AUDIO"


def _run(cmd: list[str], timeout: int = 6) -> str:
    """Executa um comando e retorna stdout + stderr."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        debug(TAG, f"{cmd[0]} falhou: {exc!r}")
        return ""

    return (result.stdout or "") + (result.stderr or "")


# ----------------------------------------------------------------------
# ALSA
# ----------------------------------------------------------------------

def list_alsa_inputs() -> list[dict]:
    """Lista dispositivos reais de captura ALSA via `arecord -l`.

    Funciona tanto com saída do arecord em inglês quanto em português.

    Retorna:
        [
            {
                "card": 0,
                "device": 0,
                "alsa": "hw:0,0",
                "plughw": "plughw:0,0",
                "label": "HDA Intel PCH - ALC256 Analog"
            }
        ]
    """

    arecord = shutil.which("arecord")

    if not arecord:
        warn(TAG, "arecord não encontrado")
        return []

    out = _run([arecord, "-l"])

    devices: list[dict] = []

    # Português:
    #
    # placa 0: PCH [HDA Intel PCH], dispositivo 0: ALC256 Analog [ALC256 Analog]
    #
    # Inglês:
    #
    # card 0: PCH [HDA Intel PCH], device 0: ALC256 Analog [ALC256 Analog]
    #
    pattern = re.compile(
        r"(?:card|placa)\s+(\d+):\s*"
        r"([^\[]+)\[([^\]]+)\],\s*"
        r"(?:device|dispositivo)\s+(\d+):\s*"
        r"([^\[]+)\[([^\]]+)\]",
        re.IGNORECASE,
    )

    for line in out.splitlines():

        match = pattern.search(line)

        if not match:
            continue

        (
            card,
            _card_id,
            card_name,
            device,
            _device_id,
            device_name,
        ) = match.groups()

        card = int(card)
        device = int(device)

        label = (
            f"{card_name.strip()} - "
            f"{device_name.strip()}"
        )

        entry = {
            "card": card,
            "device": device,

            # Dispositivo ALSA REAL.
            "alsa": f"hw:{card},{device}",

            # Alternativa, se algum componente precisar.
            "plughw": f"plughw:{card},{device}",

            "label": label,
        }

        devices.append(entry)

    if devices:

        debug(
            TAG,
            f"ALSA: encontrados {len(devices)} dispositivo(s)"
        )

        for i, device in enumerate(devices):

            debug(
                TAG,
                f"ALSA [{i}] "
                f"{device['alsa']} - "
                f"{device['label']}"
            )

    else:

        warn(
            TAG,
            "Nenhum dispositivo ALSA de captura encontrado"
        )

        # Útil para diagnóstico.
        debug(
            TAG,
            f"Saída de 'arecord -l':\n{out}"
        )

    return devices


# ----------------------------------------------------------------------
# PipeWire / PulseAudio
# ----------------------------------------------------------------------

def list_pipewire_inputs() -> list[dict]:
    """Lista fontes de entrada PipeWire/Pulse."""

    sources: list[dict] = []

    # --------------------------------------------------------------
    # pactl
    # --------------------------------------------------------------

    pactl = shutil.which("pactl")

    if pactl:
        out = _run(
            [pactl, "list", "short", "sources"]
        )

        for line in out.splitlines():

            parts = line.split("\t")

            if len(parts) < 2:
                continue

            name = parts[1].strip()

            # Monitor é saída, não microfone.
            if name.endswith(".monitor"):
                continue

            sources.append({
                "name": name,
                "label": name,
            })

        if sources:
            return sources

    # --------------------------------------------------------------
    # wpctl
    # --------------------------------------------------------------

    wpctl = shutil.which("wpctl")

    if wpctl:

        out = _run(
            [wpctl, "status"]
        )

        in_sources = False

        for line in out.splitlines():

            stripped = line.strip()

            if "Sources:" in stripped:
                in_sources = True
                continue

            if not in_sources:
                continue

            if any(
                x in stripped
                for x in (
                    "Sinks:",
                    "Filters:",
                    "Streams:",
                )
            ):
                break

            match = re.search(
                r"(\d+)\.\s+(.+?)(?:\s+\[vol.*)?$",
                stripped,
            )

            if not match:
                continue

            name = match.group(2).strip()

            sources.append({
                "name": name,
                "label": name,
            })

    return sources


# ----------------------------------------------------------------------
# Lista unificada
# ----------------------------------------------------------------------

def list_input_devices() -> list[dict]:
    """Lista dispositivos de entrada.

    Prioridade:

        1. ALSA
        2. PipeWire/Pulse

    ALSA retorna `hw:X,Y`.
    """

    devices: list[dict] = []

    alsa_devices = list_alsa_inputs()

    for d in alsa_devices:

        devices.append({
            "id": d["alsa"],
            "backend": "alsa",
            "label": d["label"],
            "alsa": d["alsa"],
            "plughw": d["plughw"],
            "card": d["card"],
            "device": d["device"],
        })

    # Só usa PipeWire se ALSA não encontrou nada.
    if not devices:

        for source in list_pipewire_inputs():

            devices.append({
                "id": source["name"],
                "backend": "pipewire",
                "label": source["label"],
                "alsa": "default",
                "plughw": "default",
            })

    return devices


# ----------------------------------------------------------------------
# Resolver
# ----------------------------------------------------------------------

def resolve_input(choice: str) -> str:
    """Converte uma escolha em um dispositivo ALSA.

    Exemplos:

        auto
        0
        1
        hw:0,0
        plughw:0,0
        default
        ALC256
    """

    choice = (choice or "").strip()

    devices = list_alsa_inputs()

    # --------------------------------------------------------------
    # AUTO
    # --------------------------------------------------------------

    if choice in ("", "auto"):

        if devices:

            selected = devices[0]

            debug(
                TAG,
                f"entrada auto -> "
                f"{selected['alsa']} "
                f"({selected['label']})"
            )

            return selected["alsa"]

        warn(
            TAG,
            "Nenhum dispositivo ALSA de captura; "
            "usando 'default'"
        )

        return "default"

    # --------------------------------------------------------------
    # DEVICE ALSA/PipeWire explícito
    # --------------------------------------------------------------

    if choice.startswith(
        (
            "hw:",
            "plughw:",
            "default",
            "pulse",
            "pipewire",
        )
    ):
        return choice

    # --------------------------------------------------------------
    # ÍNDICE
    # --------------------------------------------------------------

    if choice.isdigit():

        index = int(choice)

        if 0 <= index < len(devices):

            selected = devices[index]

            debug(
                TAG,
                f"entrada [{index}] -> "
                f"{selected['alsa']} "
                f"({selected['label']})"
            )

            return selected["alsa"]

        warn(
            TAG,
            f"Índice de microfone {index} "
            f"fora da lista ({len(devices)})"
        )

        return (
            devices[0]["alsa"]
            if devices
            else "default"
        )

    # --------------------------------------------------------------
    # NOME PARCIAL
    # --------------------------------------------------------------

    low = choice.lower()

    for device in devices:

        if low in device["label"].lower():

            debug(
                TAG,
                f"entrada '{choice}' -> "
                f"{device['alsa']} "
                f"({device['label']})"
            )

            return device["alsa"]

    # --------------------------------------------------------------
    # NÃO ENCONTRADO
    # --------------------------------------------------------------

    warn(
        TAG,
        f"Microfone {choice!r} não encontrado; "
        "usando auto"
    )

    return (
        devices[0]["alsa"]
        if devices
        else "default"
    )


# ----------------------------------------------------------------------
# Descrição para GUI/CLI
# ----------------------------------------------------------------------

def describe_devices() -> str:
    """Gera uma lista legível dos dispositivos."""

    devices = list_input_devices()

    if not devices:
        return (
            "Nenhum dispositivo de entrada encontrado "
            "(arecord/pactl/wpctl)."
        )

    lines = [
        "INPUT DEVICES",
        "",
    ]

    for index, device in enumerate(devices):

        if device["backend"] == "alsa":

            lines.append(
                f"[{index}] "
                f"{device['alsa']} - "
                f"{device['label']}"
            )

        else:

            lines.append(
                f"[{index}] "
                f"{device['label']} "
                f"(pipewire: {device['id']})"
            )

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Teste direto
# ----------------------------------------------------------------------

if __name__ == "__main__":

    print()
    print(describe_devices())
    print()

    devices = list_alsa_inputs()

    if devices:

        print("Dispositivos ALSA encontrados:")

        for i, device in enumerate(devices):

            print(
                f"  [{i}] "
                f"{device['alsa']}  "
                f"{device['label']}"
            )

        print()
        print(
            "Exemplo de teste:"
        )

        print(
            f"  arecord -D {devices[0]['alsa']} "
            "-f S16_LE -r 48000 -c 2 -d 5 /tmp/test.wav"
        )

    else:

        print(
            "Nenhum dispositivo ALSA disponível."
        )
