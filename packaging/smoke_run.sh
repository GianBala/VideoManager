#!/usr/bin/env bash
# Exige a conclusão do diagnóstico interno, não apenas um processo ainda vivo.
# Uso: smoke_run.sh <executável> [prazo em segundos]
set -uo pipefail

exe="${1:?informe o executável}"
seconds="${2:-30}"
log="$(mktemp)"
profile="$(mktemp -d)"
pid=""
cleanup() {
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
    rm -f "$log"
    rm -rf "$profile"
}
trap cleanup EXIT

QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME="$profile/config" \
XDG_DATA_HOME="$profile/data" XDG_CACHE_HOME="$profile/cache" \
"$exe" --smoke-test >"$log" 2>&1 &
pid=$!
waited=0
while [ "$waited" -lt "$seconds" ]; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
    waited=$((waited + 1))
done

if kill -0 "$pid" 2>/dev/null; then
    echo "FALHOU: diagnóstico não terminou em ${seconds}s" >&2
    cat "$log" >&2
    exit 1
fi

wait "$pid"
code=$?
pid=""
if [ "$code" -eq 0 ] && grep -q '^VM_SMOKE_OK:' "$log"; then
    grep '^VM_SMOKE_OK:' "$log"
    exit 0
fi
echo "FALHOU: diagnóstico saiu com código $code" >&2
cat "$log" >&2
exit 1
