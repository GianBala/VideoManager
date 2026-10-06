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

# Um pacote com número de versão sai de um commit: com alteração local, o
# "3.1" do Sobre não diria o que o usuário roda. VM_ALLOW_DIRTY=1 gera assim
# mesmo, e o commit gravado leva o sufixo -dirty.
if [ -n "$(git status --porcelain)" ] && [ "${VM_ALLOW_DIRTY:-0}" != "1" ]; then
    echo "árvore com alterações não commitadas; commite ou use VM_ALLOW_DIRTY=1" >&2
    git status --short >&2
    exit 1
fi

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
# Cache de fontes do usuário isolado: um ~/.cache/fontconfig regravado por um
# fontconfig mais novo que o do sistema derruba o Qt com SIGSEGV no meio da
# suíte (FcCharSetHasChar), e o build parava aqui sem empacotar nada. O cache do
# sistema (/var/cache/fontconfig) continua valendo.
FONT_CACHE="$(mktemp -d)"
trap 'rm -rf "$FONT_CACHE"' EXIT
if [ "${VM_FAST_TESTS:-1}" = "1" ]; then
    echo "    modo rápido: testes de integração com ffmpeg ficam para a CI"
    XDG_CACHE_HOME="$FONT_CACHE" "$PY" -m pytest -q -m "not ffmpeg and not network"
else
    XDG_CACHE_HOME="$FONT_CACHE" "$PY" -m pytest -q
fi

if [ "${VM_BUNDLE_FFMPEG:-1}" = "0" ]; then
    echo "==> ffmpeg NÃO será embutido (VM_BUNDLE_FFMPEG=0)"
else
    echo "==> baixando ffmpeg para embutir"
    PYTHONPATH=src "$PY" packaging/fetch_binaries.py
fi

echo "==> empacotando"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$BUILD" packaging/videomanager.spec

echo "==> conferindo as licenças no pacote"
# Sem elas o pacote redistribui ffmpeg (GPL) e Qt (LGPL) fora dos termos das
# próprias licenças; ver THIRD_PARTY_NOTICES.md.
for texto in LICENSE THIRD_PARTY_NOTICES.md LGPL-3.0.txt Deno-MIT.txt python/LICENSE.txt mutagen/COPYING; do
    if [ ! -f "$DIST/VideoManager/_internal/licenses/$texto" ]; then
        echo "falta licenses/$texto no pacote" >&2
        exit 1
    fi
done

echo "==> conferindo que o pacote abre"
./packaging/smoke_run.sh "$DIST/VideoManager/VideoManager"

echo
echo "pronto: $DIST/VideoManager/VideoManager"
du -sh "$DIST/VideoManager"
