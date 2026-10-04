#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nucleo do ARES7: orquestra AUDIO -> STT -> ROUTER -> LLM -> TTS.

GUI, CLI, servidor remoto e wake word usam TODOS este nucleo. Quem desenha
a interface define `emit(kind, payload)`:

kinds: state, user_text, user_voice, ares, system, error, mic_level, confirm

Estados: READY | LISTENING | PROCESSING | SPEAKING | ERROR
"""
from __future__ import annotations

import os
import threading
import traceback

from audio.devices import describe_devices
from audio.recorder import Recorder, wav_peak
from audio.vad import VADRecorder
from core.config import Config, ARES7_HOME
from core.context import ContextManager
from core.logs import error as log_error
from core.logs import log
from core.memory import LongTermMemory
from core.router import IntentRouter
from llm.llama import LLMError, LlamaClient
from stt.whisper import WhisperSTT
from tts.piper import TTS
from tools.common import CPU_SAMPLER, read_battery, read_memory, read_temperature

TAG = "CORE"

_CONFIRM_YES = {"sim", "confirmo", "confirma", "pode", "pode sim", "yes", "claro", "ok", "isso"}
_CONFIRM_NO = {"nao", "não", "cancela", "cancelar", "negativo", "no", "deixa", "esquece"}


class Ares7:
    def __init__(self, config: Config | None = None, low_memory: bool = False) -> None:
        self.config = config or Config()
        if low_memory or self.config.get("performance", "low_memory", False):
            self.config.apply_low_memory()
            log(TAG, "modo ULTRA FAST (low memory) ativo")
        elif self.config.get("performance", "auto_low_memory", True):
            if self._ram_available_mb() < int(self.config.get("performance", "low_memory_threshold_mb", 700)):
                self.config.apply_low_memory()
                log(TAG, "RAM baixa detectada -> modo ULTRA FAST automatico")
        self.low_memory = low_memory or self.config.get("performance", "low_memory", False)

        self.home_dir = ARES7_HOME
        self.notes_path = os.path.join(ARES7_HOME, "notas.txt")
        os.makedirs(ARES7_HOME, exist_ok=True)

        self.context = ContextManager(self.config["memory"])
        self.llm = LlamaClient(self.config["llm"])
        self.stt = WhisperSTT(self.config["whisper"])
        self.tts = TTS(self.config["tts"])
        self.recorder = Recorder(self.config["audio"])
        self.vad = VADRecorder(self.config["audio"], self.config["vad"],
                               lambda: self.recorder.device)
        self.router = IntentRouter(self)
        self.memory_enabled = bool(self.config.get("memory", "enabled", True))
        self.memory = LongTermMemory(str(self.config.get("memory", "db_path", "") or "")) \
            if self.memory_enabled else None  # type: ignore[assignment]

        self.busy = threading.Lock()
        self.speak_enabled = True
        self.state = "READY"
        self.emit = lambda kind, payload: None
        self._pending_confirm: tuple[str, object] | None = None
        self._wake_stop = threading.Event()
        self._wake_thread: threading.Thread | None = None

    # ---- memoria / hardware ------------------------------------------------------
    @staticmethod
    def _ram_available_mb() -> float:
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) / 1024.0
        except OSError:
            pass
        return 99999.0

    # ---- helpers -----------------------------------------------------------------
    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", state)

    def speak(self, text: str) -> None:
        if not self.speak_enabled:
            return
        try:
            self.tts.speak(text)
        except Exception as exc:
            log_error("TTS", f"erro inesperado: {exc!r}")

    def run_async(self, func, *args) -> bool:
        """Executa func em thread, uma tarefa por vez."""
        if not self.busy.acquire(blocking=False):
            self.emit("system", "Ocupado. Aguarde a tarefa atual terminar.")
            return False

        def runner() -> None:
            try:
                func(*args)
            except Exception as exc:
                log_error(TAG, traceback.format_exc())
                self.emit("error", f"Erro interno: {exc!r}")
                self.set_state("ERROR")
            finally:
                self.set_state("READY")
                self.busy.release()

        threading.Thread(target=runner, daemon=True).start()
        return True

    def announce(self, text: str) -> None:
        """Fala por iniciativa propria (timer, lembrete)."""
        got = self.busy.acquire(blocking=False)
        try:
            self.emit("ares", text)
            if got:
                self.set_state("SPEAKING")
            self.speak(text)
        finally:
            if got:
                self.set_state("READY")
                self.busy.release()

    # ---- confirmacao de comandos perigosos -----------------------------------------
    def _handle_confirmation(self, text: str) -> bool:
        """Se ha acao perigosa pendente, resolve aqui. Retorna True se consumiu."""
        if not self._pending_confirm:
            return False
        from core.router import normalize_phrase
        norm = normalize_phrase(text)
        question, action = self._pending_confirm
        if norm in _CONFIRM_YES or norm.split()[:1] and norm.split()[0] in _CONFIRM_YES:
            self._pending_confirm = None
            try:
                reply = action()  # type: ignore[operator]
            except Exception as exc:
                reply = f"Falha ao executar: {exc}"
            self.emit("ares", reply)
            if self.speak_enabled:
                self.set_state("SPEAKING")
                self.speak(reply)
            return True
        if norm in _CONFIRM_NO or norm.split()[:1] and norm.split()[0] in _CONFIRM_NO:
            self._pending_confirm = None
            reply = "Ok, cancelado."
            self.emit("ares", reply)
            if self.speak_enabled:
                self.set_state("SPEAKING")
                self.speak(reply)
            return True
        reply = f"Ainda aguardando confirmação: {question} Responda 'sim' ou 'não'."
        self.emit("ares", reply)
        if self.speak_enabled:
            self.set_state("SPEAKING")
            self.speak(reply)
        return True

    # ---- fluxo principal de texto -----------------------------------------------------
    def handle_text(self, text: str, from_voice: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        self.emit("user_voice" if from_voice else "user_text", text)
        self.set_state("PROCESSING")
        if self._handle_confirmation(text):
            return
        # Fast path: comandos locais nunca precisam acordar o LLM.
        result = self.router.try_handle(text)
        if result is not None:
            if result.confirm:
                question, _action = result.confirm
                self._pending_confirm = result.confirm
                self.emit("confirm", question)
                self.emit("ares", question)
                if self.speak_enabled:
                    self.set_state("SPEAKING")
                    self.speak(question)
                return
            reply = result.reply
        else:
            extra = self.memory.context_for(text) if self.memory else ""
            messages = self.context.build_messages(text, extra_system=extra)
            try:
                # Respostas curtas usam menos tokens e terminam mais rápido.
                reply = self.llm.fast_chat(messages) if len(text) <= 120 else self.llm.chat(messages)
            except LLMError as exc:
                self.emit("error", str(exc))
                self.set_state("ERROR")
                return
            self.context.add("user", text)
            self.context.add("assistant", reply)
        self.emit("ares", reply)
        if self.speak_enabled:
            self.set_state("SPEAKING")
            self.speak(reply)

    # ---- fluxo de voz --------------------------------------------------------------------
    def voice_turn(self, use_vad: bool | None = None) -> None:
        use_vad = bool(self.config.get("vad", "enabled", True)) if use_vad is None else use_vad
        self.set_state("LISTENING")
        if use_vad:
            wav_path, error = self.vad.record_utterance(
                on_level=lambda level, active: self.emit("mic_level", (level, active)))
        else:
            seconds = int(self.config.get("audio", "record_seconds", 8))
            self.emit("system", f"Fale agora ({seconds}s)...")
            wav_path, error = self.recorder.record(seconds)
        if error:
            self.emit("error", error)
            self.set_state("ERROR" if "nao encontrado" in error else "READY")
            return
        assert wav_path is not None
        try:
            peak = wav_peak(wav_path)
        except Exception as exc:
            self.emit("error", f"Nao consegui ler o WAV: {exc}")
            self.set_state("READY")
            return
        threshold = int(self.config.get("audio", "low_peak_threshold", 400))
        if peak < threshold:
            self.emit("system", f"Audio muito baixo (peak {peak} < {threshold}). Fale mais perto do microfone.")
        self.set_state("PROCESSING")
        text, error = self.stt.transcribe(wav_path)
        try:
            os.remove(wav_path)
        except OSError:
            pass
        if error:
            self.emit("error", error)
            self.set_state("ERROR")
            return
        if not text:
            self.emit("system", "Nenhuma fala reconhecida.")
            self.set_state("READY")
            return
        self.handle_text(text, from_voice=True)

    # ---- wake word (modo CONTINUOUS) ---------------------------------------------------------
    def start_wake_word(self) -> None:
        word = str(self.config.get("wake_word", "word", "ares")).lower()
        if self._wake_thread and self._wake_thread.is_alive():
            return
        self._wake_stop.clear()

        def loop() -> None:
            self.emit("system", f"Modo CONTINUOUS ativo. Diga '{word.upper()}' para falar.")
            while not self._wake_stop.is_set():
                got = self.busy.acquire(blocking=False)
                if not got:
                    self._wake_stop.wait(0.5)
                    continue
                try:
                    wav_path, error = self.vad.record_utterance()
                    if error or not wav_path:
                        continue
                    text, stt_error = self.stt.transcribe(wav_path)
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
                    if stt_error or not text:
                        continue
                    if word in text.lower():
                        self.emit("system", "Wake word detectada!")
                        self.handle_text(text, from_voice=True)
                finally:
                    self.busy.release()

        self._wake_thread = threading.Thread(target=loop, daemon=True)
        self._wake_thread.start()

    def stop_wake_word(self) -> None:
        self._wake_stop.set()
        self.vad.stop_event.set()

    # ---- status / diagnostico leve --------------------------------------------------------------
    def collect_status(self) -> dict:
        online, model, llm_error = self.llm.probe()
        memory = read_memory()
        return {
            "whisper_bin": self.stt.binary(),
            "whisper_model": self.stt.model(),
            "whisper_ok": self.stt.ready(),
            "llm_online": online,
            "llm_model": model,
            "llm_error": llm_error,
            "piper_ready": self.tts.piper_ready(),
            "tts_fallback": self.tts.fallback_name(),
            "tts_mode": self.tts.mode(),
            "mic_device": self.recorder.device,
            "cpu": CPU_SAMPLER.percent(),
            "ram_used": memory[0] if memory else None,
            "ram_total": memory[1] if memory else None,
            "temp": read_temperature(),
            "battery": read_battery(),
            "low_memory": self.low_memory,
            "state": self.state,
        }

    def reconnect_llm(self) -> str:
        online, model = self.llm.reconnect()
        if online:
            return f"LLM online ({model or 'modelo desconhecido'})."
        return "LLM continua offline. Verifique: llama serve (ou llm.server_bin/server_model no config.json)."

    def list_input_devices(self) -> str:
        return describe_devices()
