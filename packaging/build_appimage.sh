#!/usr/bin/env bash
# Gera um AppImage: um arquivo só, executável, que roda sem instalação.
#
# Não reimplementa o empacotamento — envelopa o resultado de build_linux.sh num
# AppDir. Tudo que vale para aquele pacote (bibliotecas, ffmpeg embutido, os
# extratores do yt-dlp) vale aqui, porque é literalmente a mesma pasta.
#
#   ./packaging/build_appimage.sh                  # build completo
#   ./packaging/build_appimage.sh --reuse-dist     # reaproveita dist/ existente
#   VM_FAST_TESTS=0 ./packaging/build_appimage.sh   # suíte completa (com ffmpeg)
#   VM_BUNDLE_FFMPEG=0 ./packaging/build_appimage.sh   # ~290 MB a menos
#
# Sem compilação cruzada: um AppImage x86_64 precisa ser gerado numa máquina
# x86_64. E AppImage é formato de Linux — no Windows continua o build_windows.ps1.
set -euo pipefail

cd "$(dirname "$0")/.."

REUSE_DIST=0
for arg in "$@"; do
    case "$arg" in
        --reuse-dist) REUSE_DIST=1 ;;
        *) echo "argumento desconhecido: $arg" >&2; exit 2 ;;
    esac
done

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"
ARCH="$(uname -m)"
DIST="${VM_DIST_DIR:-dist}"
BUILD="${VM_BUILD_DIR:-build}"
APPDIR="$BUILD/AppDir"

if [ ! -x "$PY" ]; then
    echo "venv não encontrado em $VENV. Crie com: python3 -m venv $VENV" >&2
    exit 1
fi

VERSION="$("$PY" -c 'import re,pathlib; print(re.search(r"__version__ = \"([^\"]+)\"", pathlib.Path("src/videomanager/__init__.py").read_text()).group(1))')"
OUTPUT="$DIST/Video_Manager-${VERSION}-${ARCH}.AppImage"

if [ "$REUSE_DIST" = 1 ] && [ -x "$DIST/VideoManager/VideoManager" ]; then
    echo "==> reaproveitando $DIST/VideoManager"
else
    ./packaging/build_linux.sh
fi

echo "==> montando o AppDir"
# Depois do build_linux.sh, que apaga build/ inteiro.
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/share/icons/hicolor/512x512/apps" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -a "$DIST/VideoManager/." "$APPDIR/usr/bin/"

install -m 755 packaging/appimage/AppRun "$APPDIR/AppRun"

# O .desktop e o ícone precisam estar na raiz do AppDir: é ali que o
# appimagetool os procura para gravar os metadados dentro da imagem. As cópias
# em usr/share são para quando a AppImage é integrada ao menu do sistema.
install -m 644 packaging/appimage/videomanager.desktop "$APPDIR/videomanager.desktop"
install -m 644 packaging/appimage/videomanager.desktop "$APPDIR/usr/share/applications/"
install -m 644 src/videomanager/resources/videomanager.png "$APPDIR/videomanager.png"
install -m 644 src/videomanager/resources/videomanager.png \
        "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
install -m 644 src/videomanager/resources/videomanager.png \
        "$APPDIR/usr/share/icons/hicolor/512x512/apps/"
install -m 644 src/videomanager/resources/videomanager.svg \
        "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
# .DirIcon é o ícone que gerenciadores de arquivo mostram para o próprio
# arquivo .AppImage. Cópia, não link: o link simbólico se perde em algumas
# ferramentas que remontam o AppDir.
cp "$APPDIR/videomanager.png" "$APPDIR/.DirIcon"

# Cache fora de build/, que build_linux.sh apaga a cada execução — senão o
# appimagetool seria rebaixado toda vez.
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/videomanager-packaging"
TOOL="$CACHE/appimagetool-${ARCH}.AppImage"
if [ ! -x "$TOOL" ]; then
    echo "==> baixando appimagetool"
    mkdir -p "$CACHE"
    curl -fL --progress-bar -o "$TOOL.parcial" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x "$TOOL.parcial"
    mv "$TOOL.parcial" "$TOOL"
fi

# O appimagetool é ele próprio um AppImage e precisa de FUSE para se montar.
# Onde não há (contêiner, CI, máquina sem libfuse2), ele sabe se auto-extrair.
if ! "$TOOL" --version >/dev/null 2>&1; then
    echo "==> FUSE indisponível; usando o appimagetool em modo auto-extração"
    export APPIMAGE_EXTRACT_AND_RUN=1
fi

echo "==> gerando o AppImage"
mkdir -p "$DIST"
rm -f "$OUTPUT"
RUNTIME="$CACHE/runtime-${ARCH}"
RUNTIME_ARG=()
if [ ! -f "$RUNTIME" ]; then
    echo "==> baixando runtime type2 para $ARCH"
    mkdir -p "$CACHE"
    if curl -fL --progress-bar -o "$RUNTIME.part" \
        "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-${ARCH}"; then
        mv "$RUNTIME.part" "$RUNTIME"
    else
        rm -f "$RUNTIME.part"
        echo "Falha ao baixar runtime; o cache não foi atualizado." >&2
        exit 1
    fi
fi

if [ -f "$RUNTIME" ]; then
    # Altera uma cópia: o cache continua utilizável por outras execuções.
    cp "$RUNTIME" "$BUILD/runtime-${ARCH}"
    if ! "$PY" packaging/patch_runtime.py "$BUILD/runtime-${ARCH}"; then
        echo "Runtime sem patch: use APPIMAGE_EXTRACT_AND_RUN=1 quando não houver FUSE." >&2
    fi
    RUNTIME_ARG=("--runtime-file" "$BUILD/runtime-${ARCH}")
fi

ARCH="$ARCH" "$TOOL" "${RUNTIME_ARG[@]}" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

echo "==> conferindo que o AppImage abre"
./packaging/smoke_run.sh "$OUTPUT"

echo
echo "pronto: $OUTPUT"
du -h "$OUTPUT"
sha256sum "$OUTPUT" > "$OUTPUT.sha256"
