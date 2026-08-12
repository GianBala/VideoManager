#!/usr/bin/env bash
# Confere que o executável gerado abre de verdade.
#
# Existe porque o modo de falha típico do PyInstaller é silencioso na geração e
# fatal na abertura: um import que o analisador não enxerga produz um pacote
# aparentemente completo que morre no primeiro segundo. Foi exatamente o que
# aconteceu — o pacote saiu sem o PySide6 inteiro e ninguém percebeu.
#
# Uso: smoke_run.sh <executável> [segundos]
set -uo pipefail

exe="${1:?informe o executável}"
seconds="${2:-12}"
log="$(mktemp)"
trap 'rm -f "$log"' EXIT

# offscreen: roda sem servidor gráfico, então isto funciona igual em CI.
QT_QPA_PLATFORM=offscreen "$exe" >"$log" 2>&1 &
pid=$!

waited=0
while [ "$waited" -lt "$seconds" ]; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
    waited=$((waited + 1))
done

if kill -0 "$pid" 2>/dev/null; then
    # Continua de pé depois da janela montada e do bootstrap: é o que queríamos.
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    echo "ok: abriu e continuou rodando por ${seconds}s"
    exit 0
fi

wait "$pid"
code=$?
echo "FALHOU: o executável saiu com código $code antes de ${seconds}s" >&2
echo "--- saída ---" >&2
cat "$log" >&2
exit 1
