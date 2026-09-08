#!/usr/bin/env bash
# Gera o pacote para Linux em dist/VideoManager/.
#
# Não há compilação cruzada no PyInstaller: o pacote de Windows precisa ser
# gerado no Windows, com build_windows.ps1.
set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"
DIST="${VM_DIST_DIR:-dist}"
BUILD="${VM_BUILD_DIR:-build}"

if [ ! -x "$PY" ]; then
    echo "venv não encontrado em $VENV. Crie com: python3 -m venv $VENV" >&2
    exit 1
fi

if [ "${SKIP_DEPS:-0}" != "1" ]; then
    echo "==> instalando dependências"
    "$PY" -m pip install -q --upgrade pip
    "$PY" -m pip install -q -e ".[dev]" pyinstaller
fi

echo "==> testes (um pacote não deve ser gerado sobre suíte vermelha)"
if [ "${VM_FAST_TESTS:-0}" = "1" ]; then
    echo "    modo rápido: testes de integração com ffmpeg ficam para a CI"
    "$PY" -m pytest -q -m "not ffmpeg and not network"
else
    "$PY" -m pytest -q
fi

if [ "${VM_BUNDLE_FFMPEG:-1}" = "0" ]; then
    echo "==> ffmpeg NÃO será embutido (VM_BUNDLE_FFMPEG=0)"
else
    echo "==> baixando ffmpeg para embutir"
    PYTHONPATH=src "$PY" packaging/fetch_binaries.py
fi

echo "==> empacotando"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$BUILD" packaging/videomanager.spec

echo "==> conferindo que o pacote abre"
./packaging/smoke_run.sh "$DIST/VideoManager/VideoManager"

echo
echo "pronto: $DIST/VideoManager/VideoManager"
du -sh "$DIST/VideoManager"
