#!/usr/bin/env bash
# ==============================================================================
# Script de Automação de Geração de AppImage - Video Manager
# ==============================================================================
# Constrói o pacote completo de ponta a ponta:
# 1. Validação do ambiente (Linux, arquitetura, Python 3.10+)
# 2. Criação/ativação do venv (.venv)
# 3. Instalação das dependências de runtime e compilação
# 4. Execução da suíte de testes com pytest
# 5. Download dos binários oficiais de ffmpeg e ffprobe
# 6. Compilação com PyInstaller via packaging/videomanager.spec
# 7. Montagem do AppDir e obtenção do appimagetool
# 8. Empacotamento do AppImage final
# 9. Verificação de fumaça (smoke run offscreen) e cálculo de SHA-256
#
# Uso:
#   ./scripts/generate_appimage.sh [opções]
#
# Opções:
#   --skip-tests        Pula a execução do pytest
#   --skip-deps         Pula atualização/instalação de dependências do pip
#   --no-bundle-ffmpeg  Não embute o ffmpeg (~290 MB a menos)
#   --reuse-dist        Reaproveita a compilação prévia em dist/VideoManager
#   --help, -h          Exibe esta mensagem de ajuda
# ==============================================================================

set -euo pipefail

# Garante execução a partir da raiz do repositório
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SKIP_TESTS=0
SKIP_DEPS=0
BUNDLE_FFMPEG="${VM_BUNDLE_FFMPEG:-1}"
REUSE_DIST=0

for arg in "$@"; do
    case "$arg" in
        --skip-tests)
            SKIP_TESTS=1
            ;;
        --skip-deps)
            SKIP_DEPS=1
            ;;
        --no-bundle-ffmpeg)
            BUNDLE_FFMPEG=0
            ;;
        --reuse-dist)
            REUSE_DIST=1
            ;;
        --help|-h)
            sed -n '2,24p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Erro: argumento desconhecido '$arg'" >&2
            echo "Consulte './scripts/generate_appimage.sh --help' para opções disponíveis." >&2
            exit 2
            ;;
    esac
done

echo "========================================================================"
echo "  Gerador Automatizado de AppImage - Video Manager"
echo "========================================================================"

# --- 1. Verificação do Sistema Operacional e Arquitetura ---------------------
if [ "$(uname -s)" != "Linux" ]; then
    echo "Erro: AppImage só pode ser gerado no Linux." >&2
    exit 1
fi

ARCH="$(uname -m)"
echo "--> Arquitetura detectada: $ARCH"

if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "aarch64" ]; then
    echo "Aviso: arquitetura $ARCH pode não ter suporte oficial para todos os binários." >&2
fi

# --- 2. Verificação do Python e Ambiente Virtual ----------------------------
VENV="${VENV:-.venv}"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
    echo "--> Ambiente virtual não encontrado em $VENV. Criando..."
    if command -v python3 >/dev/null 2>&1; then
        SYSTEM_PY="python3"
    else
        echo "Erro: python3 não encontrado no sistema." >&2
        exit 1
    fi

    # Confere versão do Python (mínimo 3.10)
    PY_VER="$("$SYSTEM_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    PY_MAJOR="$("$SYSTEM_PY" -c 'import sys; print(sys.version_info.major)')"
    PY_MINOR="$("$SYSTEM_PY" -c 'import sys; print(sys.version_info.minor)')"

    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
        echo "Erro: Python 3.10 ou superior é necessário (versão atual: $PY_VER)." >&2
        exit 1
    fi

    "$SYSTEM_PY" -m venv "$VENV"
    echo "--> Ambiente virtual criado em $VENV (Python $PY_VER)."
fi

VERSION="$("$PY" -c 'import re,pathlib; print(re.search(r"__version__ = \"([^\"]+)\"", pathlib.Path("src/videomanager/__init__.py").read_text()).group(1))')"
echo "--> Versão do aplicativo: $VERSION"

# --- 3. Dependências --------------------------------------------------------
if [ "$SKIP_DEPS" = 1 ]; then
    echo "--> Pulando instalação de dependências (--skip-deps ativo)."
else
    echo "--> Atualizando pip e instalando dependências de desenvolvimento e empacotamento..."
    "$PY" -m pip install -q --upgrade pip
    "$PY" -m pip install -q -e ".[dev]" pyinstaller
fi

# --- 4. Testes Automatizados ------------------------------------------------
if [ "$SKIP_TESTS" = 1 ]; then
    echo "--> Pulando testes automatizados (--skip-tests ativo)."
else
    echo "--> Executando testes com pytest..."
    if ! "$PY" -m pytest -q; then
        echo "Erro: a suíte de testes falhou! Corrija os testes antes de gerar o pacote." >&2
        exit 1
    fi
    echo "--> Todos os testes passaram com sucesso."
fi

# --- 5. Binários do FFmpeg --------------------------------------------------
if [ "$BUNDLE_FFMPEG" = "0" ]; then
    echo "--> ffmpeg NÃO será embutido (BUNDLE_FFMPEG=0)."
else
    echo "--> Verificando/baixando binários do ffmpeg e ffprobe..."
    PYTHONPATH=src "$PY" packaging/fetch_binaries.py
fi

# --- 6. Compilação com PyInstaller ------------------------------------------
if [ "$REUSE_DIST" = 1 ] && [ -x dist/VideoManager/VideoManager ]; then
    echo "--> Reaproveitando compilação existente em dist/VideoManager (--reuse-dist ativo)."
else
    echo "--> Compilando binário via PyInstaller (packaging/videomanager.spec)..."
    rm -rf build dist/VideoManager
    "$PY" -m PyInstaller --noconfirm --clean packaging/videomanager.spec
fi

# Valida executável intermediário
if [ ! -x dist/VideoManager/VideoManager ]; then
    echo "Erro: falha na compilação do PyInstaller. 'dist/VideoManager/VideoManager' não foi encontrado." >&2
    exit 1
fi

# --- 7. Montagem do AppDir ---------------------------------------------------
APPDIR="build/AppDir"
echo "--> Montando a estrutura do AppDir em $APPDIR..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -a dist/VideoManager/. "$APPDIR/usr/bin/"

install -m 755 packaging/appimage/AppRun "$APPDIR/AppRun"
install -m 644 packaging/appimage/videomanager.desktop "$APPDIR/videomanager.desktop"
install -m 644 packaging/appimage/videomanager.desktop "$APPDIR/usr/share/applications/"
install -m 644 src/videomanager/resources/videomanager.png "$APPDIR/videomanager.png"
install -m 644 src/videomanager/resources/videomanager.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
install -m 644 src/videomanager/resources/videomanager.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
cp "$APPDIR/videomanager.png" "$APPDIR/.DirIcon"

# --- 8. Obtenção do appimagetool e runtime -----------------------------------
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/videomanager-packaging"
TOOL="$CACHE_DIR/appimagetool-${ARCH}.AppImage"
RUNTIME="$CACHE_DIR/runtime-${ARCH}"

if [ ! -x "$TOOL" ]; then
    echo "--> Baixando appimagetool oficial para $ARCH..."
    mkdir -p "$CACHE_DIR"
    curl -fL --progress-bar -o "$TOOL.part" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x "$TOOL.part"
    mv "$TOOL.part" "$TOOL"
fi

if [ ! -f "$RUNTIME" ]; then
    echo "--> Baixando runtime type2 oficial para $ARCH..."
    mkdir -p "$CACHE_DIR"
    curl -fL --progress-bar -o "$RUNTIME.part" \
        "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-${ARCH}" || true
    if [ -f "$RUNTIME.part" ]; then
        mv "$RUNTIME.part" "$RUNTIME"
    fi
fi

if [ -f "$RUNTIME" ]; then
    "$PY" packaging/patch_runtime.py "$RUNTIME" >/dev/null 2>&1 || true
fi

# Se FUSE não estiver disponível (ex: container ou sistema sem libfuse2),
# o appimagetool pode se auto-extrair
if ! "$TOOL" --version >/dev/null 2>&1; then
    echo "--> FUSE indisponível no host; ativando extração automática do appimagetool..."
    export APPIMAGE_EXTRACT_AND_RUN=1
fi

# --- 9. Empacotamento do AppImage --------------------------------------------
OUTPUT_APPIMAGE="dist/Video_Manager-${VERSION}-${ARCH}.AppImage"
echo "--> Gerando pacote final: $OUTPUT_APPIMAGE..."
mkdir -p dist
rm -f "$OUTPUT_APPIMAGE"

RUNTIME_ARG=()
if [ -f "$RUNTIME" ]; then
    RUNTIME_ARG=("--runtime-file" "$RUNTIME")
fi

ARCH="$ARCH" "$TOOL" "${RUNTIME_ARG[@]}" "$APPDIR" "$OUTPUT_APPIMAGE"
chmod +x "$OUTPUT_APPIMAGE"
"$PY" packaging/patch_runtime.py "$OUTPUT_APPIMAGE" >/dev/null 2>&1 || true

# --- 10. Verificação e Checksum ----------------------------------------------
echo "--> Executando teste de fumaça (smoke run offscreen)..."
if [ -x packaging/smoke_run.sh ]; then
    ./packaging/smoke_run.sh "$OUTPUT_APPIMAGE"
else
    echo "Aviso: packaging/smoke_run.sh não encontrado para teste de fumaça."
fi

echo "--> Calculando checksum SHA-256..."
SHA256_FILE="${OUTPUT_APPIMAGE}.sha256"
(cd dist && sha256sum "$(basename "$OUTPUT_APPIMAGE")") > "$SHA256_FILE"

echo
echo "========================================================================"
echo "  Sucesso! AppImage gerado com êxito."
echo "========================================================================"
echo "Arquivo:  $OUTPUT_APPIMAGE"
echo "Tamanho:  $(du -h "$OUTPUT_APPIMAGE" | cut -f1)"
echo "SHA-256:  $(cat "$SHA256_FILE" | cut -d' ' -f1)"
echo "Checksum: $SHA256_FILE"
echo "========================================================================"
