#!/usr/bin/env bash
# setup_local_linux.sh — prepara o ARES-7 num Ubuntu 24.04 de 4 GB de RAM.
# Instala SOMENTE o necessario. Nada de pacotes desnecessarios.
set -e
cd "$(dirname "$0")"

echo "=== ARES-7 SETUP (Ubuntu local) ==="

# 1. Ubuntu?
if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "Sistema: $PRETTY_NAME"
else
  echo "AVISO: nao parece Ubuntu; continuando mesmo assim."
fi

# 2. Python
if ! command -v python3 >/dev/null; then
  echo "Instalando python3..."
  sudo apt update && sudo apt install -y python3 python3-venv python3-tk
fi
python3 --version

# 3. Ferramentas de audio e controle (minimas)
PKGS=""
command -v arecord >/dev/null || PKGS="$PKGS alsa-utils"
command -v wpctl   >/dev/null || PKGS="$PKGS wireplumber"
command -v xdg-open >/dev/null || PKGS="$PKGS xdg-utils"
command -v espeak-ng >/dev/null || PKGS="$PKGS espeak-ng"
command -v playerctl >/dev/null || PKGS="$PKGS playerctl"
command -v brightnessctl >/dev/null || PKGS="$PKGS brightnessctl"
python3 -c "import tkinter" 2>/dev/null || PKGS="$PKGS python3-tk"
if [ -n "$PKGS" ]; then
  echo "Instalando:$PKGS"
  sudo apt update && sudo apt install -y $PKGS
fi

# 4. Ambiente virtual (somente se houver dependencias pip no futuro;
#    o ARES-7 roda 100% com a biblioteca padrao, entao e opcional)
if [ ! -d .venv ]; then
  python3 -m venv .venv 2>/dev/null || echo "venv indisponivel; ok, o ARES-7 nao precisa de pip."
fi

# 5. Pastas
mkdir -p models ~/.ares

# 6. Whisper.cpp
if command -v whisper-cli >/dev/null || [ -n "$ARES7_WHISPER_BIN" ]; then
  echo "Whisper: OK"
else
  echo "AVISO: whisper-cli nao encontrado."
  echo "  Para compilar: git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp && cmake -B build && cmake --build build -j2"
fi
if ls models/ggml-*.bin >/dev/null 2>&1; then
  echo "Modelo Whisper: OK"
else
  echo "AVISO: sem modelo ggml-*.bin em ./models"
  echo "  Sugestao (leve): baixe ggml-tiny.bin ou ggml-base.bin para ./models"
fi

# 7. Piper
if command -v piper >/dev/null; then
  echo "Piper: OK"
else
  echo "AVISO: piper nao encontrado (fallback espeak-ng sera usado)."
fi

# 8. llama.cpp
if command -v llama >/dev/null || command -v llama-server >/dev/null; then
  echo "llama.cpp: OK"
else
  echo "AVISO: llama/llama-server nao encontrado."
  echo "  Para compilar: git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp && cmake -B build && cmake --build build -j2"
fi

# 9. Config
if [ ! -f config.json ]; then
  echo "config.json nao encontrado (o ARES-7 usara os defaults internos)."
fi

# 10. Teste rapido
echo ""
echo "=== Teste rapido ==="
python3 ares.py --status || true

# 11. Launcher
cat > ares-launcher.sh <<'LAUNCH'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec python3 ares.py "$@"
LAUNCH
chmod +x ares-launcher.sh

echo ""
echo "=== SETUP CONCLUIDO ==="
echo "Rode:  ./ares-launcher.sh           (GUI)"
echo "       ./ares-launcher.sh --cli     (terminal)"
echo "       ./ares-launcher.sh --diagnose"
