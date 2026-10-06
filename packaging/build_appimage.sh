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

# Versões fixas, conferidas pelo SHA-256 que o GitHub publica para cada arquivo.
# O canal "continuous" muda sem aviso, e as duas ferramentas montam o binário
# que o usuário executa: o que entra no pacote tem de ser o que foi conferido.
# Trocar de versão é trocar os resumos junto.
APPIMAGETOOL_VERSION="1.9.1"
RUNTIME_VERSION="20251108"
case "$ARCH" in
    x86_64)
        APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
        RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d" ;;
    aarch64)
        APPIMAGETOOL_SHA256="f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158"
        RUNTIME_SHA256="00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444" ;;
    *) echo "arquitetura sem ferramentas conferidas: $ARCH" >&2; exit 1 ;;
esac

# Baixa para o cache só se ainda não estiver lá, e confere o resumo sempre: um
# cache adulterado é tão ruim quanto um download adulterado.
baixar_conferido() {  # destino url sha256
    if [ ! -f "$1" ]; then
        mkdir -p "$CACHE"
        curl -fL --progress-bar -o "$1.parcial" "$2"
        mv "$1.parcial" "$1"
    fi
    if ! echo "$3  $1" | sha256sum -c --quiet -; then
        echo "SHA-256 não confere: $1 (apague-o do cache para baixar de novo)" >&2
        exit 1
    fi
}

TOOL="$CACHE/appimagetool-${APPIMAGETOOL_VERSION}-${ARCH}.AppImage"
echo "==> appimagetool $APPIMAGETOOL_VERSION"
baixar_conferido "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-${ARCH}.AppImage" \
    "$APPIMAGETOOL_SHA256"
chmod +x "$TOOL"

# O appimagetool é ele próprio um AppImage e precisa de FUSE para se montar.
# Onde não há (contêiner, CI, máquina sem libfuse2), ele sabe se auto-extrair.
if ! "$TOOL" --version >/dev/null 2>&1; then
    echo "==> FUSE indisponível; usando o appimagetool em modo auto-extração"
    export APPIMAGE_EXTRACT_AND_RUN=1
fi

echo "==> gerando o AppImage"
mkdir -p "$DIST"
rm -f "$OUTPUT"
RUNTIME="$CACHE/runtime-${RUNTIME_VERSION}-${ARCH}"
echo "==> runtime type2 $RUNTIME_VERSION"
baixar_conferido "$RUNTIME" \
    "https://github.com/AppImage/type2-runtime/releases/download/${RUNTIME_VERSION}/runtime-${ARCH}" \
    "$RUNTIME_SHA256"

# Altera uma cópia: o cache continua utilizável por outras execuções.
cp "$RUNTIME" "$BUILD/runtime-${ARCH}"
if ! "$PY" packaging/patch_runtime.py "$BUILD/runtime-${ARCH}"; then
    echo "Runtime sem patch: use APPIMAGE_EXTRACT_AND_RUN=1 quando não houver FUSE." >&2
fi
RUNTIME_ARG=("--runtime-file" "$BUILD/runtime-${ARCH}")

ARCH="$ARCH" "$TOOL" "${RUNTIME_ARG[@]}" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

echo "==> conferindo que o AppImage abre"
./packaging/smoke_run.sh "$OUTPUT"

echo
echo "pronto: $OUTPUT"
du -h "$OUTPUT"
# Só o nome do arquivo, sem a pasta: com "dist/" no caminho o `sha256sum -c`
# só confere a partir da raiz do repositório, e não depois de o par ser movido
# ou baixado.
(cd "$DIST" && sha256sum "$(basename "$OUTPUT")") > "$OUTPUT.sha256"
