#!/usr/bin/env bash
# Cria um ambiente Python NOVO, com as dependências na versão mais nova que o pyproject admite, e o audita.
#
#   ./packaging/prepare_env.sh <pasta-do-venv>
#
# Existe porque o AppImage saía do `.venv` de quem desenvolve, com o que estivesse instalado nele: o da 4.2 levou
# urllib3 2.7.0, certifi 2026.07.22 (ainda confiava numa raiz de CA com chaves comprometidas), brotli 1.2.0 (escrita fora do
# limite no decodificador) e um yt-dlp de 12 semanas, enquanto o `.exe` da mesma versão, gerado pela CI num ambiente criado do
# zero, saiu com urllib3 2.8.0, certifi 2026.10.23 e yt-dlp 2026.10.26. Os dois pacotes passam a sair do mesmo tipo de ambiente.
#
# A auditoria (`pip-audit`) roda de um ambiente à parte, para as dependências dela não entrarem na conta, e **recusa** o que
# tiver aviso conhecido. Um aviso aceito de propósito vai em `packaging/pip-audit-ignore.txt` (um identificador por linha, com
# o motivo depois), nunca em silêncio. VM_AUDIT=0 pula a auditoria (só para quem precisa de um pacote de teste).
set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${1:?uso: prepare_env.sh <pasta-do-venv>}"
PYTHON="${PYTHON:-python3}"

echo "==> ambiente novo em $VENV"
rm -rf "$VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -e ".[dev]" pyinstaller

if [ "${VM_AUDIT:-1}" != "1" ]; then
    echo "==> auditoria de dependências PULADA (VM_AUDIT=0)"
    exit 0
fi

echo "==> auditoria de dependências (pip-audit)"
AUDITOR="$(mktemp -d)"
trap 'rm -rf "$AUDITOR"' EXIT
"$PYTHON" -m venv "$AUDITOR"
"$AUDITOR/bin/python" -m pip install -q pip-audit
IGNORAR=()
if [ -f packaging/pip-audit-ignore.txt ]; then
    while read -r id _; do
        case "$id" in ""|\#*) ;; *) IGNORAR+=(--ignore-vuln "$id") ;; esac
    done < packaging/pip-audit-ignore.txt
fi
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
"$AUDITOR/bin/pip-audit" --path "$SITE" --progress-spinner off "${IGNORAR[@]+"${IGNORAR[@]}"}"
echo "==> nenhuma vulnerabilidade conhecida nas dependências"
