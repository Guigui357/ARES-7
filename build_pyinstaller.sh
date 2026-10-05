#!/usr/bin/env bash
# build_pyinstaller.sh — gera o ARES-7 com PyInstaller.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== ARES-7 PyInstaller ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: python3 não encontrado."
  exit 1
fi

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller não encontrado. Instalando..."
  python3 -m pip install --user pyinstaller
fi

python3 -m PyInstaller --clean --noconfirm ARES-7.spec

echo ""
echo "=== BUILD CONCLUÍDO ==="
echo "Executável: dist/ARES-7/ARES-7"
echo "Teste: ./dist/ARES-7/ARES-7 --version"
echo ""
echo "O config.json fica ao lado do executável e pode ser editado."
echo "Whisper, llama.cpp/Qwen, Piper e modelos continuam externos."
