#!/usr/bin/env bash
# build_pyinstaller.sh — gera o ARES-7 com PyInstaller.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== ARES-7 PyInstaller ==="

PYTHON="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif [ ! -d ".venv" ]; then
  echo "Criando ambiente virtual de build..."
  python3 -m venv .venv
  PYTHON=".venv/bin/python"
fi

if ! "$PYTHON" -m PyInstaller --version >/dev/null 2>&1; then
  echo "Instalando PyInstaller no ambiente virtual..."
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install pyinstaller
fi

"$PYTHON" -m PyInstaller --clean --noconfirm ARES-7.spec

echo ""
echo "=== BUILD CONCLUÍDO ==="
echo "Executável: dist/ARES-7/ARES-7"
echo "Teste: ./dist/ARES-7/ARES-7 --version"
echo ""
echo "O config.json fica ao lado do executável e pode ser editado."
echo "Whisper, llama.cpp/Qwen, Piper e modelos continuam externos."
