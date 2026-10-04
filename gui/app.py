#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI Tkinter leve (HUD). Mostra estado, texto reconhecido, respostas,
CPU/RAM, modelo carregado, dispositivo de entrada e botoes:
MICROFONE, TEST MICROPHONE e RECONNECT.
"""
from __future__ import annotations

import datetime
import math
import queue
import re
import threading
import traceback

try:
    import tkinter as tk
    TK_IMPORT_ERROR = None
except Exception as _tk_exc:
    tk = None  # type: ignore[assignment]
    TK_IMPORT_ERROR = _tk_exc

from core.logs import error as log_error

BG = "#02060d"
PANEL = "#06101c"
PANEL2 = "#0a1a2c"
BORDER = "#0f3552"
CYAN = "#00e5ff"
TEXT = "#cfe6f7"
DIM = "#4f7089"
GREEN = "#00ffa3"
RED = "#ff3366"
AMBER = "#ffb300"
USER_COLOR = "#6db3ff"
MONO = "DejaVu Sans Mono"
SANS = "DejaVu Sans"

STATE_COLORS = {
    "READY": CYAN, "LISTENING": RED, "PROCESSING": AMBER,
    "SPEAKING": GREEN, "ERROR": RED,
}
STATE_SUBTITLES = {
    "READY": "AGUARDANDO COMANDO", "LISTENING": "CAPTANDO ÁUDIO",
    "PROCESSING": "PROCESSANDO", "SPEAKING": "TRANSMITINDO RESPOSTA",
    "ERROR": "ERRO",
}
STATS_INTERVAL = 5.0


def hex_to_rgb(color: str) -> list[float]:
    return [float(int(color[i:i + 2], 16)) for i in (1, 3, 5)]


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def blend(fg: str, bg: str, alpha: float) -> str:
    alpha = max(0.0, min(1.0, alpha))
    f = hex_to_rgb(fg)
    b = hex_to_rgb(bg)
    return rgb_to_hex([b[k] + (f[k] - b[k]) * alpha for k in range(3)])


class Ares7GUI:
    PLACEHOLDER = "Digite uma mensagem ou comando..."
    CORE_HEIGHT = 200

    def __init__(self, ares) -> None:
        self.ares = ares
        self.events: queue.Queue = queue.Queue()
        self.state = "READY"
        self.phase = 0.0
        self.color_rgb = hex_to_rgb(CYAN)
        self.closing = False
        self.boot_done = False
        self.placeholder_active = False
        self.stats: dict | None = None
        self.online_text = "CONECTANDO"
        self.online_color = AMBER
        self.stop_event = threading.Event()
        self.dots: dict[str, "tk.Label"] = {}
        self.mic_level = 0.0

        self.root = tk.Tk()
        self.root.title("ARES7 LOCAL")

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        win_w = min(1100, screen_w - 50)
        win_h = min(720, screen_h - 50)

        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(760, 560)
        self.root.resizable(True, True)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tts_var = tk.BooleanVar(value=ares.speak_enabled)

        self._build_header()
        self._build_core()
        self._build_chat()
        self._build_input()
        self._build_statusbar()

        ares.emit = lambda kind, payload: self.events.put((kind, payload))

    # ---- construcao --------------------------------------------------------------
    def _build_header(self) -> None:
        self.header = tk.Canvas(self.root, height=52, bg=BG, highlightthickness=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda _e: self._draw_header())

    def _draw_header(self) -> None:
        h = self.header
        h.delete("all")
        width = max(h.winfo_width(), 300)
        height = 58
        segments = 70
        for i in range(segments):
            alpha = 0.08 + 0.85 * (1.0 - i / segments) ** 1.6
            x0 = width * i / segments
            h.create_line(x0, height - 2, x0 + width / segments + 1, height - 2,
                          fill=blend(CYAN, BG, alpha), width=2)
        h.create_text(23, 22, text="A R E S - 7", anchor="w", fill=blend(CYAN, BG, 0.28),
                      font=(SANS, 19, "bold"))
        h.create_text(21, 21, text="A R E S - 7", anchor="w", fill=CYAN, font=(SANS, 19, "bold"))
        h.create_text(23, 40, text="NÚCLEO LOCAL  //  WHISPER · QWEN · PIPER", anchor="w",
                      fill=DIM, font=(MONO, 8))
        col = self.online_color
        x1, x0 = width - 18, width - 168
        h.create_polygon(x0 + 10, 12, x1, 12, x1, 33, x1 - 10, 36, x0, 36, x0, 21,
                         outline=blend(col, BG, 0.85), fill=blend(col, BG, 0.1), width=1)
        h.create_text((x0 + x1) / 2, 23, text=f"● {self.online_text}", fill=col, font=(MONO, 11, "bold"))

    def _build_core(self) -> None:
        self.canvas = tk.Canvas(self.root, height=self.CORE_HEIGHT, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _e: self._draw_static())

    def _add_corners(self, parent, color: str) -> None:
        size = 16
        shapes = (
            ({"x": 0, "y": 0}, [(1, size - 1, 1, 1), (1, 1, size - 1, 1)]),
            ({"relx": 1.0, "x": -size, "y": 0}, [(0, 1, size - 2, 1), (size - 2, 1, size - 2, size - 1)]),
            ({"rely": 1.0, "y": -size, "x": 0}, [(1, 0, 1, size - 2), (1, size - 2, size - 1, size - 2)]),
            ({"relx": 1.0, "x": -size, "rely": 1.0, "y": -size},
             [(0, size - 2, size - 2, size - 2), (size - 2, size - 2, size - 2, 0)]),
        )
        for place, lines in shapes:
            corner = tk.Canvas(parent, width=size, height=size, bg=BG, highlightthickness=0)
            for x0, y0, x1, y1 in lines:
                corner.create_line(x0, y0, x1, y1, fill=color, width=2)
            corner.place(**place)

    def _build_chat(self) -> None:
        self.chat_frame = tk.Frame(self.root, bg=BG)

        self.chat_frame.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=(4, 4)
        )

        self.chat_frame.pack_propagate(False)

        self.chat = tk.Text(
            self.chat_frame,
            bg=PANEL,
            fg=TEXT,
            wrap="word",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            padx=12,
            pady=8,
            font=(MONO, 10),
            state="disabled",
            insertbackground=CYAN,
            spacing1=1,
            spacing3=1,
            cursor="arrow",
            height=1,
        )

        scrollbar = tk.Scrollbar(
            self.chat_frame,
            command=self.chat.yview,
            bg=PANEL,
            troughcolor=BG,
            activebackground=BORDER,
            bd=0,
            width=8,
            highlightthickness=0
        )

        self.chat.configure(
            yscrollcommand=scrollbar.set
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.chat.pack(
            side="left",
            fill="both",
            expand=True
        )

        self.chat.tag_configure(
            "who_user",
            foreground=USER_COLOR,
            font=(MONO, 9, "bold"),
            spacing1=5
        )

        self.chat.tag_configure(
            "who_ares",
            foreground=CYAN,
            font=(MONO, 9, "bold"),
            spacing1=5
        )

        self.chat.tag_configure(
            "stamp",
            foreground=DIM,
            font=(MONO, 8)
        )

        self.chat.tag_configure(
            "msg_user",
            foreground="#e6f1ff",
            lmargin1=12,
            lmargin2=12
        )

        self.chat.tag_configure(
            "msg_ares",
            foreground=TEXT,
            lmargin1=12,
            lmargin2=12
        )

        self.chat.tag_configure(
            "system",
            foreground=DIM,
            font=(MONO, 9),
            lmargin1=4,
            lmargin2=4
        )

        self.chat.tag_configure(
            "ok",
            foreground=GREEN,
            font=(MONO, 9)
        )

        self.chat.tag_configure(
            "warn",
            foreground=AMBER,
            font=(MONO, 9)
        )

        self.chat.tag_configure(
            "error",
            foreground=RED,
            font=(MONO, 9),
            lmargin1=12,
            lmargin2=12
        )

        self._add_corners(
            self.chat_frame,
            CYAN
        )

    def _build_input(self) -> None:
        # Linha principal
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=12, pady=(0, 3))

        tk.Label(
            row,
            text="❯",
            bg=BG,
            fg=CYAN,
            font=(MONO, 14, "bold")
        ).pack(side="left", padx=(2, 7))

        self.entry = tk.Entry(
            row,
            bg=PANEL,
            fg=TEXT,
            insertbackground=CYAN,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
            font=(MONO, 11)
        )

        self.entry.pack(
            side="left",
            fill="x",
            expand=True,
            ipady=5
        )

        self.entry.bind("<Return>", self.on_send)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

        self._show_placeholder()

        self.mic_button = self._make_button(
            row, "🎤 MIC", self.on_mic, RED, 7
        )
        self.mic_button.pack(side="left", padx=(7, 0), ipady=2)

        self.send_button = self._make_button(
            row, "SEND", self.on_send, CYAN, 7
        )
        self.send_button.pack(side="left", padx=(5, 0), ipady=2)

        # Segunda linha
        row2 = tk.Frame(self.root, bg=BG)
        row2.pack(fill="x", padx=12, pady=(0, 5))

        self.test_button = self._make_button(
            row2,
            "TEST MICROPHONE",
            self.on_test_mic,
            AMBER,
            16
        )
        self.test_button.pack(side="left", ipady=1)

        self.reconnect_button = self._make_button(
            row2,
            "RECONNECT",
            self.on_reconnect,
            GREEN,
            10
        )
        self.reconnect_button.pack(
            side="left",
            padx=(5, 0),
            ipady=1
        )

        self.devices_button = self._make_button(
            row2,
            "INPUT DEVICES",
            self.on_devices,
            DIM,
            14
        )
        self.devices_button.pack(
            side="left",
            padx=(5, 0),
            ipady=1
        )

    def _make_button(self, parent, text, command, color, width):
        button = tk.Button(
            parent, text=text, command=command, bg=PANEL, fg=color,
            activebackground=PANEL2, activeforeground=color, disabledforeground=DIM,
            relief="flat", bd=0, highlightthickness=1, highlightbackground=blend(color, BG, 0.45),
            font=(MONO, 10, "bold"), width=width, cursor="hand2")

        def on_enter(_e) -> None:
            if str(button["state"]) == "normal":
                button.config(bg=PANEL2, highlightbackground=color)

        def on_leave(_e) -> None:
            button.config(bg=PANEL, highlightbackground=blend(color, BG, 0.45))

        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)
        return button

    def _build_statusbar(self) -> None:
        tk.Frame(
            self.root,
            bg=BORDER,
            height=1
        ).pack(fill="x")

        bar = tk.Frame(
            self.root,
            bg=PANEL,
            height=28
        )
        bar.pack(fill="x")
        bar.pack_propagate(False)

        font = (MONO, 8)

        for key, label in (
            ("mic", "MIC"),
            ("whisper", "WHISPER"),
            ("llama", "QWEN"),
            ("piper", "PIPER"),
        ):
            tk.Label(
                bar,
                text=label,
                bg=PANEL,
                fg=DIM,
                font=font
            ).pack(
                side="left",
                padx=(9, 2)
            )

            dot = tk.Label(
                bar,
                text="●",
                bg=PANEL,
                fg=AMBER,
                font=font
            )
            dot.pack(side="left")

            self.dots[key] = dot

        self.stats_label = tk.Label(
            bar,
            text="CPU --  RAM --  --  BAT --",
            bg=PANEL,
            fg=DIM,
            font=font
        )
        self.stats_label.pack(
            side="left",
            padx=10
        )

        tk.Checkbutton(
            bar,
            text="TTS",
            variable=self.tts_var,
            command=self._toggle_tts,
            bg=PANEL,
            fg=DIM,
            selectcolor=BG,
            activebackground=PANEL,
            activeforeground=TEXT,
            bd=0,
            highlightthickness=0,
            font=font,
        ).pack(
            side="right",
            padx=9
        )

    # ---- placeholder ---------------------------------------------------------------
    def _show_placeholder(self) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, self.PLACEHOLDER)
        self.entry.config(fg=DIM)
        self.placeholder_active = True

    def _on_focus_in(self, _event=None) -> None:
        if self.placeholder_active:
            self.entry.delete(0, "end")
            self.entry.config(fg=TEXT)
            self.placeholder_active = False

    def _on_focus_out(self, _event=None) -> None:
        if not self.entry.get().strip():
            self._show_placeholder()

    # ---- acoes -----------------------------------------------------------------------
    def _toggle_tts(self) -> None:
        self.ares.speak_enabled = bool(self.tts_var.get())

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.mic_button, self.send_button, self.test_button):
            b.config(state=state)

    def on_send(self, _event=None) -> None:
        if self.placeholder_active:
            return
        text = self.entry.get().strip()
        if not text:
            return
        if self.ares.run_async(self.ares.handle_text, text, False):
            self.entry.delete(0, "end")

    def on_mic(self) -> None:
        """Inicia/para a escuta. Em modo VAD, um segundo clique interrompe."""
        if self.ares.state == "LISTENING":
            self.ares.vad.stop_event.set()
            return
        self.ares.run_async(self.ares.voice_turn)

    def on_test_mic(self) -> None:
        """Grava 3s, mede amplitude, informa se o microfone esta recebendo audio."""
        def _test() -> None:
            self.events.put(("system", "Testando microfone: fale algo por 3 segundos..."))
            wav_path, error = self.ares.recorder.record(3)
            if error:
                self.events.put(("error", f"TEST MIC falhou: {error}"))
                return
            from audio.recorder import wav_peak
            try:
                peak = wav_peak(wav_path)
            except Exception as exc:
                self.events.put(("error", f"TEST MIC: nao consegui ler o WAV: {exc}"))
                return
            import os
            try:
                os.remove(wav_path)
            except OSError:
                pass
            threshold = int(self.ares.config.get("audio", "low_peak_threshold", 400))
            if peak >= threshold:
                self.events.put(("ok", f"TEST MIC: microfone OK (amplitude {peak}, device {self.ares.recorder.device})"))
            else:
                self.events.put(("warn", f"TEST MIC: audio muito baixo (amplitude {peak} < {threshold}). "
                                         "Verifique o dispositivo em INPUT DEVICES."))

        threading.Thread(target=_test, daemon=True).start()

    def on_reconnect(self) -> None:
        def _rec() -> None:
            self.events.put(("system", "Tentando reconectar ao llama.cpp..."))
            message = self.ares.reconnect_llm()
            self.events.put(("ok" if "online" in message else "warn", message))
        threading.Thread(target=_rec, daemon=True).start()

    def on_devices(self) -> None:
        def _list() -> None:
            self.events.put(("system", self.ares.list_input_devices()))
        threading.Thread(target=_list, daemon=True).start()

    def on_close(self) -> None:
        self.closing = True
        self.stop_event.set()
        self.ares.stop_wake_word()
        self.root.destroy()

    # ---- chat -------------------------------------------------------------------------
    def append(self, kind: str, text: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.chat.config(state="normal")
        if kind == "user":
            self.chat.insert("end", "❯ VOCÊ", "who_user")
            self.chat.insert("end", f"  {stamp}\n", "stamp")
            self.chat.insert("end", text + "\n\n", "msg_user")
        elif kind == "ares":
            self.chat.insert("end", "◆ ARES7", "who_ares")
            self.chat.insert("end", f"  {stamp}\n", "stamp")
            self.chat.insert("end", text + "\n\n", "msg_ares")
        elif kind in ("system", "ok", "warn"):
            prefix = {"system": "// ", "ok": "[ OK ] ", "warn": "[ -- ] "}[kind]
            self.chat.insert("end", prefix + text + "\n", kind)
        else:
            self.chat.insert("end", "✖ " + text + "\n\n", "error")
        total_lines = int(self.chat.index("end-1c").split(".")[0])
        if total_lines > 600:
            self.chat.delete("1.0", f"{total_lines - 500}.0")
        self.chat.config(state="disabled")
        self.chat.see("end")

    # ---- fila de eventos -----------------------------------------------------------------
    def _pump(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._dispatch(kind, payload)
            except Exception:
                log_error("GUI", traceback.format_exc())
        if not self.closing:
            self.root.after(60, self._pump)

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "state":
            self.state = payload
            self._set_busy(payload not in ("READY", "ERROR"))
        elif kind in ("user_text", "user_voice"):
            self.append("user", payload)
        elif kind == "ares":
            self.append("ares", payload)
        elif kind in ("system", "ok", "warn"):
            self.append(kind, payload)
        elif kind == "confirm":
            self.append("warn", "CONFIRMAÇÃO NECESSÁRIA: " + str(payload))
        elif kind == "error":
            self.append("error", payload)
            log_error("GUI", str(payload))
        elif kind == "mic_level":
            level, _active = payload
            self.mic_level = min(1.0, level / 8000.0)
        elif kind == "stats":
            self._apply_stats(payload)

    def _apply_stats(self, st: dict) -> None:
        self.stats = st
        self.dots["whisper"].config(fg=GREEN if st["whisper_ok"] else RED)
        self.dots["llama"].config(fg=GREEN if st["llm_online"] else RED)
        self.dots["mic"].config(fg=GREEN if st.get("mic_device") else RED)
        if st["piper_ready"]:
            piper_color = GREEN
        elif st["tts_fallback"] != "nenhum TTS instalado":
            piper_color = AMBER
        else:
            piper_color = RED
        self.dots["piper"].config(fg=piper_color)
        new_text, new_color = ("ONLINE", GREEN) if st["llm_online"] else ("OFFLINE", RED)
        if (new_text, new_color) != (self.online_text, self.online_color):
            self.online_text, self.online_color = new_text, new_color
            self._draw_header()
        gb = 1024 ** 3
        cpu = f"{st['cpu']:.0f}%" if st["cpu"] is not None else "--"
        ram = f"{st['ram_used'] / gb:.1f}/{st['ram_total'] / gb:.1f}G" if st["ram_total"] else "--"
        temp = f"{st['temp']:.0f}°C" if st["temp"] is not None else "--"
        battery = st["battery"].split(" ")[0] if st["battery"] else "--"
        self.stats_label.config(text=f"CPU {cpu}  RAM {ram}  {temp}  BAT {battery}")
        if not self.boot_done:
            self.boot_done = True
            self._report_boot(st)

    def _report_boot(self, st: dict) -> None:
        self.append("ok" if st["whisper_ok"] else "warn",
                    "WHISPER  " + (f"pronto ({st['whisper_model']})" if st["whisper_ok"]
                                    else "verifique whisper-cli e o modelo"))
        self.append("ok" if st.get("mic_device") else "warn",
                    "MIC      " + str(st.get("mic_device") or "nenhum dispositivo encontrado"))
        self.append("ok" if st["llm_online"] else "warn",
                    "QWEN     " + (f"online ({st['llm_model']})" if st["llm_online"] and st["llm_model"]
                                    else "online" if st["llm_online"] else "offline - RECONNECT ou llama serve"))
        self.append("ok" if st["piper_ready"] else "warn",
                    "PIPER    " + ("voz neural ativa" if st["piper_ready"] else f"fallback ({st['tts_fallback']})"))
        if st.get("low_memory"):
            self.append("warn", "MODO ULTRA FAST ativo (pouca RAM): contexto e threads reduzidos.")
        self.append("system", "Diga \"ajuda\" para ver os comandos.")

    def _stats_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.events.put(("stats", self.ares.collect_status()))
            except Exception:
                log_error("GUI", traceback.format_exc())
            self.stop_event.wait(STATS_INTERVAL)

    # ---- nucleo animado (HUD) ----------------------------------------------------------
    def _draw_static(self) -> None:
        c = self.canvas
        c.delete("static")
        width = max(c.winfo_width(), 300)
        height = max(c.winfo_height(), 200)
        grid = blend(CYAN, BG, 0.05)
        for x in range(0, width, 36):
            c.create_line(x, 0, x, height, fill=grid, tags="static")
        for y in range(0, height, 36):
            c.create_line(0, y, width, y, fill=grid, tags="static")
        bracket = blend(CYAN, BG, 0.6)
        size = 20
        for x, y, dx, dy in ((8, 8, 1, 1), (width - 8, 8, -1, 1), (8, height - 8, 1, -1), (width - 8, height - 8, -1, -1)):
            c.create_line(x, y + dy * size, x, y, x + dx * size, y, fill=bracket, width=2, tags="static")
        cx, cy = width / 2, height / 2 - 8
        c.create_text(cx, 18, text="ARES7 CORE", fill=DIM, font=(MONO, 9, "bold"), tags="static")
        if width >= 660:
            line = blend(CYAN, BG, 0.28)
            c.create_line(176, cy, cx - 112, cy, fill=line, tags="static")
            c.create_line(cx + 112, cy, width - 176, cy, fill=line, tags="static")
            c.create_oval(cx - 116, cy - 3, cx - 110, cy + 3, outline=line, tags="static")
            c.create_oval(cx + 110, cy - 3, cx + 116, cy + 3, outline=line, tags="static")
        c.tag_lower("static")

    def _telemetry(self, width: int, cy: float) -> None:
        if width < 660:
            return
        c = self.canvas
        st = self.stats or {}
        cpu = st.get("cpu")
        ram_pct = (100.0 * st["ram_used"] / st["ram_total"]) if st.get("ram_total") else None
        temp = st.get("temp")
        battery = None
        if st.get("battery"):
            m = re.match(r"(\d+)", st["battery"])
            battery = float(m.group(1)) if m else None
        gauges = (
            (26, cy - 52, "CPU", cpu, None if cpu is None else f"{cpu:.0f}%", False),
            (26, cy + 4, "RAM", ram_pct, None if ram_pct is None else f"{ram_pct:.0f}%", False),
            (width - 166, cy - 52, "TEMP", None if temp is None else (temp - 30) / 60 * 100,
             None if temp is None else f"{temp:.0f}°C", False),
            (width - 166, cy + 4, "BAT", battery, None if battery is None else f"{battery:.0f}%", True),
        )
        bar_w = 140
        for x, y, label, value, shown, invert in gauges:
            c.create_text(x, y, text=label, anchor="w", fill=DIM, font=(MONO, 9), tags="dyn")
            c.create_text(x + bar_w, y, text=shown if shown else "--", anchor="e", fill=TEXT,
                          font=(MONO, 9, "bold"), tags="dyn")
            c.create_rectangle(x, y + 12, x + bar_w, y + 19, outline=BORDER, tags="dyn")
            if value is not None:
                frac = max(0.0, min(1.0, value / 100.0))
                bad = (1.0 - frac) if invert else frac
                color = GREEN if bad < 0.6 else (AMBER if bad < 0.85 else RED)
                c.create_rectangle(x + 1, y + 13, x + 1 + (bar_w - 2) * frac, y + 18,
                                   fill=color, outline="", tags="dyn")

    def _animate(self) -> None:
        if self.closing:
            return
        self.phase += 1.0
        try:
            self._draw_core()
        except Exception:
            log_error("GUI", traceback.format_exc())
        self.root.after(75 if self.state == "READY" else 40, self._animate)

    def _draw_core(self) -> None:
        c = self.canvas
        c.delete("dyn")
        width = max(c.winfo_width(), 300)
        height = max(c.winfo_height(), 200)
        cx, cy = width / 2, height / 2 - 8
        t = self.phase

        target = hex_to_rgb(STATE_COLORS.get(self.state, CYAN))
        self.color_rgb = [self.color_rgb[i] + (target[i] - self.color_rgb[i]) * 0.18 for i in range(3)]
        color = rgb_to_hex(self.color_rgb)
        dim = blend(color, BG, 0.45)
        faint = blend(color, BG, 0.2)

        def oval(r: float, **kw) -> None:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, tags="dyn", **kw)

        def arc(r: float, start: float, extent: float, **kw) -> None:
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=extent,
                         style="arc", tags="dyn", **kw)

        def ray(angle_deg: float, r1: float, r2: float, **kw) -> None:
            a = math.radians(angle_deg)
            c.create_line(cx + math.cos(a) * r1, cy - math.sin(a) * r1,
                          cx + math.cos(a) * r2, cy - math.sin(a) * r2, tags="dyn", **kw)

        for angle in (0, 90, 180, 270):
            ray(angle, 94, 104, fill=dim, width=2)

        if self.state in ("READY", "ERROR"):
            oval(98, outline=faint, width=1, dash=(1, 6), dashoffset=int(t * 0.6))
            oval(78, outline=dim, width=1)
            arc(70, (t * 1.1) % 360, 70, outline=color, width=3)
            arc(70, (t * 1.1 + 180) % 360, 70, outline=color, width=3)
            oval(52, outline=faint, width=1, dash=(10, 6), dashoffset=-int(t * 0.9))
            r = 24 + 2.5 * math.sin(t * 0.08)
            oval(r, outline=color, width=2, fill=blend(color, BG, 0.16))
            oval(8, fill=color, outline="")
        elif self.state == "LISTENING":
            for i in range(3):
                p = (t * 0.03 + i / 3.0) % 1.0
                oval(26 + p * 72, outline=blend(color, BG, (1.0 - p) * 0.95), width=2)
            oval(98, outline=faint, width=1, dash=(1, 5), dashoffset=int(t * 1.6))
            r0 = 22 + 4 * math.sin(t * 0.45) + self.mic_level * 10
            oval(r0, fill=color, outline="")
            for side in (-1, 1):
                for i in range(10):
                    x = cx + side * (112 + i * 9)
                    amp = abs(math.sin(t * 0.3 + i * 0.8) * math.cos(t * 0.12 + i * 0.4))
                    half = 3 + (amp * 0.4 + self.mic_level * 0.6) * 30
                    c.create_line(x, cy - half, x, cy + half, fill=blend(color, BG, 0.9 - i * 0.07),
                                  width=4, tags="dyn")
        elif self.state == "PROCESSING":
            oval(98, outline=faint, width=1, dash=(2, 5), dashoffset=int(t * 1.4))
            for radius, speed, extent, width_px in ((84, 5, 90, 3), (72, -8, 120, 3), (60, 11, 60, 4), (48, -14, 100, 3)):
                arc(radius, (t * speed) % 360, extent, outline=color, width=width_px)
            for k in range(3):
                ang = math.radians(t * 4.5 + k * 120)
                px, py = cx + math.cos(ang) * 98, cy - math.sin(ang) * 98
                c.create_oval(px - 4, py - 4, px + 4, py + 4, fill=color, outline="", tags="dyn")
            sweep = (t * 7) % 360
            for k in range(5):
                ray(sweep - k * 7, 0, 66, fill=blend(color, BG, 0.85 - k * 0.17), width=2)
            oval(12, outline=color, width=2, fill=blend(color, BG, 0.3))
        else:  # SPEAKING
            oval(98, outline=faint, width=1, dash=(10, 6), dashoffset=-int(t * 1.0))
            for i in range(36):
                amp = abs(math.sin(t * 0.3 + i * 0.7) * math.cos(t * 0.13 + i * 0.35))
                ray(i * 10, 38, 42 + amp * 40, fill=color if i % 2 == 0 else dim, width=3)
            r0 = 24 + 3 * math.sin(t * 0.5)
            oval(r0, fill=blend(color, BG, 0.25), outline=color, width=2)
            oval(8, fill=color, outline="")

        self._telemetry(width, cy)
        c.create_text(cx, height - 30, text=f"◉ {self.state}", fill=color, font=(MONO, 12, "bold"), tags="dyn")
        c.create_text(cx, height - 13, text=STATE_SUBTITLES.get(self.state, ""), fill=dim,
                      font=(MONO, 8), tags="dyn")

    # ---- execucao ------------------------------------------------------------------------
    def run(self) -> None:
        self.append("system", f"Inicializando núcleo...  TTS: {self.ares.tts.mode()}")
        threading.Thread(target=self._stats_worker, daemon=True).start()
        if self.ares.config.get("wake_word", "enabled", False):
            self.ares.start_wake_word()
        self._pump()
        self._animate()
        self.root.mainloop()
