#!/usr/bin/env bash
# Gera o pacote para Linux em dist/VideoManager/.
#
# Não há compilação cruzada no PyInstaller: o pacote de Windows precisa ser
# gerado no Windows, com build_windows.ps1.
set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
    echo "venv não encontrado em $VENV. Crie com: python3 -m venv $VENV" >&2
    exit 1
fi

echo "==> instalando dependências"
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -e ".[dev]" pyinstaller

echo "==> testes (um pacote não deve ser gerado sobre suíte vermelha)"
"$PY" -m pytest -q

echo "==> baixando ffmpeg para embutir"
PYTHONPATH=src "$PY" packaging/fetch_binaries.py

echo "==> empacotando"
rm -rf build dist
"$PY" -m PyInstaller --noconfirm --clean packaging/videomanager.spec

echo
echo "pronto: dist/VideoManager/VideoManager"
du -sh dist/VideoManager
