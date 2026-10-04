#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VAD / gravador de voz do ARES7.

Fluxo:

    audio/devices.py
            ↓
       resolve_input()
            ↓
       hw:0,0
            ↓
        arecord
            ↓
     48 kHz / 2 canais
            ↓
      detecção de voz
            ↓
      16 kHz / mono WAV
            ↓
         Whisper
"""

from __future__ import annotations

import array
import os
import shutil
import subprocess
import tempfile
import threading
import wave

from core.logs import debug, warn

# Descoberta centralizada dos dispositivos.
from audio.devices import (
    resolve_input,
    describe_devices,
    list_alsa_inputs,
)


TAG = "VAD"


# ----------------------------------------------------------------------
# CONFIGURAÇÃO DE CAPTURA
# ----------------------------------------------------------------------

# Formato REAL usado pelo seu microfone ALC256.
CAPTURE_RATE = 48000
CAPTURE_CHANNELS = 2
SAMPLE_WIDTH = 2  # S16_LE

# Formato entregue ao Whisper.
OUTPUT_RATE = 16000
OUTPUT_CHANNELS = 1

# VAD
DEFAULT_THRESHOLD = 700
DEFAULT_SILENCE_MS = 900
DEFAULT_MAX_SECONDS = 20
DEFAULT_PRE_ROLL_MS = 300
DEFAULT_POST_ROLL_MS = 200
DEFAULT_MIN_SPEECH_MS = 400

# Tamanho dos blocos de análise.
CHUNK_MS = 40


# ----------------------------------------------------------------------
# RMS
# ----------------------------------------------------------------------

def _rms_pcm16_mono(data: bytes) -> float:
    """Calcula RMS de PCM16 mono sem depender de audioop."""

    if not data:
        return 0.0

    usable = len(data) - (len(data) % 2)

    if usable <= 0:
        return 0.0

    samples = array.array("h")

    try:
        samples.frombytes(data[:usable])
    except Exception:
        return 0.0

    if not samples:
        return 0.0

    total = 0.0

    for sample in samples:
        total += sample * sample

    return (total / len(samples)) ** 0.5


def _rms_pcm16_stereo(data: bytes) -> float:
    """Calcula RMS aproximado do áudio estéreo."""

    if not data:
        return 0.0

    usable = len(data) - (len(data) % 4)

    if usable <= 0:
        return 0.0

    samples = array.array("h")

    try:
        samples.frombytes(data[:usable])
    except Exception:
        return 0.0

    if not samples:
        return 0.0

    total = 0.0

    for sample in samples:
        total += sample * sample

    return (total / len(samples)) ** 0.5


# ----------------------------------------------------------------------
# ESTÉREO -> MONO
# ----------------------------------------------------------------------

def _stereo_to_mono(data: bytes) -> bytes:
    """Converte PCM16 estéreo para PCM16 mono."""

    if not data:
        return b""

    usable = len(data) - (len(data) % 4)

    if usable <= 0:
        return b""

    samples = array.array("h")

    try:
        samples.frombytes(data[:usable])
    except Exception:
        return b""

    mono = array.array("h")

    # L, R, L, R...
    for i in range(0, len(samples) - 1, 2):

        left = samples[i]
        right = samples[i + 1]

        value = (left + right) // 2

        # proteção contra overflow
        if value > 32767:
            value = 32767

        elif value < -32768:
            value = -32768

        mono.append(value)

    return mono.tobytes()


# ----------------------------------------------------------------------
# 48 kHz -> 16 kHz
# ----------------------------------------------------------------------

def _resample_48k_to_16k(data: bytes) -> bytes:
    """
    Redução simples de 48 kHz para 16 kHz.

    Como 48000 / 16000 = 3,
    podemos pegar uma amostra a cada 3.
    """

    if not data:
        return b""

    samples = array.array("h")

    usable = len(data) - (len(data) % 2)

    if usable <= 0:
        return b""

    try:
        samples.frombytes(data[:usable])
    except Exception:
        return b""

    output = array.array("h")

    # 48k -> 16k
    output.extend(samples[::3])

    return output.tobytes()


# ----------------------------------------------------------------------
# WAV
# ----------------------------------------------------------------------

def _write_wav(
    path: str,
    pcm: bytes,
    rate: int = OUTPUT_RATE,
    channels: int = OUTPUT_CHANNELS,
):
    """Grava PCM16 em WAV."""

    with wave.open(path, "wb") as wav:

        wav.setnchannels(channels)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(rate)
        wav.writeframes(pcm)


# ----------------------------------------------------------------------
# VAD
# ----------------------------------------------------------------------

class VADRecorder:

    def __init__(
        self,
        audio_cfg=None,
        device_resolver=None,
        threshold: int = DEFAULT_THRESHOLD,
        silence_ms: int = DEFAULT_SILENCE_MS,
        max_seconds: int = DEFAULT_MAX_SECONDS,
        pre_roll_ms: int = DEFAULT_PRE_ROLL_MS,
        post_roll_ms: int = DEFAULT_POST_ROLL_MS,
        min_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
    ):
        self.audio_cfg = audio_cfg

        # Se alguém fornecer um resolver externo, usamos ele.
        # Caso contrário, usamos audio/devices.py.
        self._device_resolver = (
            device_resolver
            if device_resolver is not None
            else self._resolve_device
        )

        self.threshold = threshold
        self.silence_ms = silence_ms
        self.max_seconds = max_seconds
        self.pre_roll_ms = pre_roll_ms
        self.post_roll_ms = post_roll_ms
        self.min_speech_ms = min_speech_ms

        self.stop_event = threading.Event()

    # ------------------------------------------------------------------
    # DEVICE
    # ------------------------------------------------------------------

    def _resolve_device(self) -> str:
        """
        Resolve o dispositivo através de audio/devices.py.

        Configuração aceita:

            auto
            0
            1
            hw:0,0
            plughw:0,0
            nome do dispositivo
        """

        choice = "auto"

        if self.audio_cfg is not None:

            choice = getattr(
                self.audio_cfg,
                "input",
                None,
            )

            if choice is None:

                choice = getattr(
                    self.audio_cfg,
                    "input_device",
                    None,
                )

            if choice is None:

                choice = getattr(
                    self.audio_cfg,
                    "device",
                    None,
                )

        choice = str(choice or "auto")

        device = resolve_input(choice)

        debug(
            TAG,
            f"audio.devices: choice={choice!r} -> "
            f"device={device!r}"
        )

        return device

    # ------------------------------------------------------------------
    # LISTAGEM
    # ------------------------------------------------------------------

    @staticmethod
    def list_devices() -> str:
        """Retorna os dispositivos disponíveis."""

        return describe_devices()

    # ------------------------------------------------------------------
    # STOP
    # ------------------------------------------------------------------

    def stop(self):
        self.stop_event.set()

    # ------------------------------------------------------------------
    # RECORD
    # ------------------------------------------------------------------

    def record_utterance(self) -> str | None:

        self.stop_event.clear()

        # --------------------------------------------------------------
        # Dispositivo vem de audio/devices.py
        # --------------------------------------------------------------

        device = self._device_resolver()

        if not device:
            warn(
                TAG,
                "Nenhum dispositivo de áudio selecionado."
            )
            return None

        # --------------------------------------------------------------
        # Tamanho do bloco
        # --------------------------------------------------------------

        chunk_bytes = int(
            CAPTURE_RATE
            * SAMPLE_WIDTH
            * CAPTURE_CHANNELS
            * CHUNK_MS
            / 1000
        )

        # Para 48k / 2ch / S16:
        #
        # 48000 * 2 * 2 * 0.040 = 7680 bytes
        #

        debug(
            TAG,
            "captura:"
            f" device={device}"
            f" rate={CAPTURE_RATE}"
            f" channels={CAPTURE_CHANNELS}"
            f" format=S16_LE"
            f" chunk={chunk_bytes} bytes"
        )

        # --------------------------------------------------------------
        # arecord
        # --------------------------------------------------------------

        arecord = shutil.which("arecord")

        if not arecord:

            warn(
                TAG,
                "arecord não encontrado."
            )

            return None

        cmd = [
            arecord,
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            str(CAPTURE_RATE),
            "-c",
            str(CAPTURE_CHANNELS),
            "-t",
            "raw",
        ]

        debug(
            TAG,
            "executando: "
            + " ".join(cmd)
        )

        try:

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        except OSError as exc:

            warn(
                TAG,
                f"não foi possível iniciar arecord: {exc}"
            )

            return None

        # --------------------------------------------------------------
        # Buffers
        # --------------------------------------------------------------

        pre_roll_chunks = max(
            1,
            self.pre_roll_ms // CHUNK_MS,
        )

        pre_roll: list[bytes] = []

        speech_audio: list[bytes] = []

        speech_started = False

        speech_ms = 0
        silence_ms = 0
        total_ms = 0

        debug(
            TAG,
            f"aguardando voz "
            f"(threshold={self.threshold}, "
            f"device={device})"
        )

        # --------------------------------------------------------------
        # LOOP
        # --------------------------------------------------------------

        try:

            while not self.stop_event.is_set():

                data = proc.stdout.read(chunk_bytes)

                if not data:
                    break

                total_ms += CHUNK_MS

                # ------------------------------------------------------
                # RMS
                # ------------------------------------------------------

                rms = _rms_pcm16_stereo(data)

                # ------------------------------------------------------
                # DEBUG periódico
                # ------------------------------------------------------

                if total_ms % 400 == 0:

                    debug(
                        TAG,
                        f"RMS={rms:.1f} "
                        f"voz={'SIM' if rms >= self.threshold else 'não'}"
                    )

                # ------------------------------------------------------
                # PRE-ROLL
                # ------------------------------------------------------

                pre_roll.append(data)

                if len(pre_roll) > pre_roll_chunks:
                    pre_roll.pop(0)

                # ------------------------------------------------------
                # VOZ
                # ------------------------------------------------------

                if rms >= self.threshold:

                    if not speech_started:

                        speech_started = True

                        debug(
                            TAG,
                            f"voz detectada "
                            f"(RMS={rms:.1f})"
                        )

                        # Mantém os últimos blocos antes
                        # da detecção da voz.
                        speech_audio.extend(pre_roll)

                    speech_audio.append(data)

                    speech_ms += CHUNK_MS

                    silence_ms = 0

                # ------------------------------------------------------
                # SILÊNCIO DEPOIS DA VOZ
                # ------------------------------------------------------

                elif speech_started:

                    speech_audio.append(data)

                    silence_ms += CHUNK_MS

                    # Terminou após silêncio suficiente.
                    if (
                        speech_ms >= self.min_speech_ms
                        and silence_ms >= self.silence_ms
                    ):

                        debug(
                            TAG,
                            f"fim da fala: "
                            f"{speech_ms} ms de voz, "
                            f"{silence_ms} ms de silêncio"
                        )

                        break

                # ------------------------------------------------------
                # LIMITE MÁXIMO
                # ------------------------------------------------------

                if total_ms >= self.max_seconds * 1000:

                    debug(
                        TAG,
                        "tempo máximo de gravação atingido"
                    )

                    break

        finally:

            # ----------------------------------------------------------
            # encerra arecord
            # ----------------------------------------------------------

            try:
                proc.terminate()
            except Exception:
                pass

            try:
                proc.wait(timeout=1)
            except Exception:

                try:
                    proc.kill()
                except Exception:
                    pass

        # --------------------------------------------------------------
        # Nenhuma voz
        # --------------------------------------------------------------

        if not speech_started or speech_ms < self.min_speech_ms:

            # Tenta descobrir erro do arecord.
            try:
                stderr = proc.stderr.read().decode(
                    "utf-8",
                    errors="replace",
                ).strip()
            except Exception:
                stderr = ""

            if stderr:

                warn(
                    TAG,
                    f"arecord: {stderr}"
                )

            warn(
                TAG,
                "Nenhuma fala detectada "
                "(volume muito baixo ou silêncio)."
            )

            return None

        # --------------------------------------------------------------
        # PCM estéreo capturado
        # --------------------------------------------------------------

        stereo_pcm = b"".join(speech_audio)

        if not stereo_pcm:

            warn(
                TAG,
                "Áudio capturado vazio."
            )

            return None

        # --------------------------------------------------------------
        # ESTÉREO -> MONO
        # --------------------------------------------------------------

        mono_pcm = _stereo_to_mono(
            stereo_pcm
        )

        if not mono_pcm:

            warn(
                TAG,
                "Falha ao converter áudio estéreo para mono."
            )

            return None

        # --------------------------------------------------------------
        # 48k -> 16k
        # --------------------------------------------------------------

        output_pcm = _resample_48k_to_16k(
            mono_pcm
        )

        if not output_pcm:

            warn(
                TAG,
                "Falha ao converter 48 kHz para 16 kHz."
            )

            return None

        # --------------------------------------------------------------
        # WAV temporário
        # --------------------------------------------------------------

        fd, wav_path = tempfile.mkstemp(
            prefix="ares_",
            suffix=".wav",
        )

        os.close(fd)

        try:

            _write_wav(
                wav_path,
                output_pcm,
                OUTPUT_RATE,
                OUTPUT_CHANNELS,
            )

        except Exception as exc:

            warn(
                TAG,
                f"Erro ao salvar WAV: {exc}"
            )

            try:
                os.unlink(wav_path)
            except OSError:
                pass

            return None

        debug(
            TAG,
            f"WAV pronto: {wav_path} "
            f"(16 kHz mono, "
            f"{len(output_pcm)} bytes)"
        )

        return wav_path


# ----------------------------------------------------------------------
# Alias compatibilidade
# ----------------------------------------------------------------------

Recorder = VADRecorder


# ----------------------------------------------------------------------
# TESTE DIRETO
# ----------------------------------------------------------------------

if __name__ == "__main__":

    print()
    print("=== DISPOSITIVOS DE ENTRADA ===")
    print()

    print(describe_devices())

    print()
    print("=== ALSA ===")
    print()

    for i, device in enumerate(list_alsa_inputs()):

        print(
            f"[{i}] "
            f"{device['alsa']} - "
            f"{device['label']}"
        )

    print()
    print("Para testar o VAD:")
    print()

    recorder = VADRecorder()

    wav = recorder.record_utterance()

    if wav:

        print()
        print(f"Gravação salva em: {wav}")

    else:

        print()
        print("Nenhuma fala detectada.")
