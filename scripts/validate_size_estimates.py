"""Mede o erro do tamanho estimado contra a codificação de verdade.

    PYTHONPATH=src python scripts/validate_size_estimates.py MIDIA [MIDIA...] [--casos convert,compress,audio]
        [--recorte 60] [--cache estimativas.json] [--detalhe]

Para cada mídia e cada caso (uma conversão comum, um nível de compressão, um alvo de áudio) monta o mesmo alvo que a aba
Converter monta, codifica **de verdade** com o mesmo comando (``build_args``) e compara o tamanho que saiu com o que o
aplicativo anunciaria:

- ``formula``: a conta de ``estimate_convert_size`` sem amostra, que é o que a aba mostra enquanto nada foi medido e o que
  o editor e o download usam;
- ``amostra``: a conta com o bitrate medido em trechos (``sample_kbps``, vídeo e áudio), que a aba usa em todo o que
  recodifica.

O erro é ``(estimado − real) / real``: positivo é o aplicativo prometendo um arquivo **maior** do que saiu. O que decide a
confiança é a mediana do erro absoluto e o pior caso, e o viés: um estimador que erra sempre para o mesmo lado engana
(aviso de que o arquivo cresce quando ele encolheu).

Mídia mais longa que ``--recorte`` segundos é cortada (``-c copy``) a partir de 30% da duração, e o caso inteiro é medido
sobre o recorte (``--recorte 0`` mede o arquivo inteiro, que é o que decide se a amostra extrapola bem). O que se codifica e o que se estima são sempre o mesmo trecho. A verdade e as amostras ficam no
``--cache`` (chave: tamanho e data do arquivo, nunca o nome): repetir com outra conta de estimativa não recodifica nada.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.compression import LEVELS, compression_target
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.size_model import needs_sample
from videomanager.domain.media import AudioTarget, LocalMedia, VideoTarget
from videomanager.infrastructure.ffmpeg import sample
from videomanager.infrastructure.ffmpeg.converter import build_args, probe_file
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.infrastructure.system.process import ProcessControl

RAIZ = Path(__file__).resolve().parents[1]
# Muda quando o desenho da amostra muda: o cache de uma medida antiga não vale para a nova.
AMOSTRA = "v2"
FERRAMENTAS = FFmpegTools(RAIZ / "vendor/linux64/ffmpeg", RAIZ / "vendor/linux64/ffprobe", "empacotado")


def _assinatura(path: Path) -> str:
    estado = path.stat()
    return hashlib.sha1(f"{estado.st_size}:{int(estado.st_mtime)}".encode()).hexdigest()[:10]


def recortar(path: Path, recorte: float, pasta: Path) -> Path:
    """Os ``recorte`` segundos a partir de 30% da duração, sem recodificar; o arquivo inteiro se for curto."""
    media = probe_file(path, FERRAMENTAS)
    if recorte <= 0 or not media.duration or media.duration <= recorte * 1.2:
        return path
    inicio = media.duration * 0.30
    saida = pasta / f"recorte-{_assinatura(path)}{path.suffix}"
    if not saida.exists():
        comando = [str(FERRAMENTAS.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-y", "-ss", f"{inicio:.3f}",
                   "-t", f"{recorte:.3f}", "-i", str(path), "-map", "0:V:0", "-map", "0:a:0?", "-c", "copy", str(saida)]
        subprocess.run(comando, check=True, **subprocess_kwargs())
    return saida


def casos(media: LocalMedia, quais: set[str]) -> list[tuple[str, VideoTarget | AudioTarget]]:
    lista: list[tuple[str, VideoTarget | AudioTarget]] = []
    if media.has_video:
        altura = media.video.height or 0 if media.video else 0
        if "convert" in quais:
            lista += [("convert h264 crf20", VideoTarget(container="mp4", video_codec="h264")),
                      ("convert hevc crf20", VideoTarget(container="mkv", video_codec="hevc"))]
            if altura > 720:
                lista.append(("convert h264 720p", VideoTarget(container="mp4", video_codec="h264", height=720)))
        if "convert-h264" in quais:
            lista.append(("convert h264 crf20", VideoTarget(container="mp4", video_codec="h264")))
        if "convert-lento" in quais:
            lista += [("convert vp9", VideoTarget(container="webm", video_codec="vp9")),
                      ("convert av1", VideoTarget(container="mp4", video_codec="av1"))]
        niveis = {c.split(":")[1] for c in quais if c.startswith("compress:")}
        if "compress" in quais or niveis:
            for nivel in LEVELS:
                if niveis and nivel.key not in niveis:
                    continue
                alvo = compression_target(media, nivel, "h264", "software")
                if isinstance(alvo, VideoTarget):
                    lista.append((f"compress {nivel.key}", alvo))
    if "audio" in quais and media.has_audio:
        lista += [("audio mp3 192", AudioTarget(codec="mp3", bitrate="192")),
                  ("audio aac 128", AudioTarget(codec="m4a", bitrate="128")),
                  ("audio aac 128 recod.", AudioTarget(codec="m4a", bitrate="128", reencode=True)),
                  ("audio opus 128", AudioTarget(codec="opus", bitrate="128")),
                  ("audio flac", AudioTarget(codec="flac", bitrate="0"))]
    return lista


def tamanho_real(media: LocalMedia, alvo, pasta: Path) -> tuple[int, float]:
    saida = pasta / f"saida.{alvo.extension if isinstance(alvo, VideoTarget) else alvo.codec}"
    saida.unlink(missing_ok=True)
    comando = build_args(media, alvo, saida, FERRAMENTAS)
    inicio = time.monotonic()
    resultado = subprocess.run(comando, **subprocess_kwargs())
    if resultado.returncode != 0 or not saida.is_file():
        raise RuntimeError(resultado.stderr.decode(errors="replace")[-400:])
    return saida.stat().st_size, time.monotonic() - inicio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("midias", nargs="+", type=Path)
    parser.add_argument("--casos", default="convert,compress,audio")
    parser.add_argument("--recorte", type=float, default=60.0)
    parser.add_argument("--cache", type=Path, default=Path("estimativas.json"))
    parser.add_argument("--detalhe", action="store_true")
    parser.add_argument("--so-resumo", action="store_true", help="não codifica nada novo: usa só o que está no cache")
    argumentos = parser.parse_args()
    quais = set(argumentos.casos.split(","))
    cache = json.loads(argumentos.cache.read_text()) if argumentos.cache.exists() else {}
    erros: dict[str, dict[str, list[float]]] = {}
    falsos: dict[str, dict[str, int]] = {}  # estimou arquivo maior que a origem e saiu menor: o aviso que engana
    linhas = []
    segundos_amostra: list[tuple[float, float]] = []
    with tempfile.TemporaryDirectory(prefix="vm-estimativas-") as temporaria:
        pasta = Path(temporaria)
        for indice, original in enumerate(argumentos.midias, 1):
            assinatura = _assinatura(original) + f"@{argumentos.recorte:g}"  # do arquivo de origem: o recorte é refeito a cada execução
            path = recortar(original, argumentos.recorte, pasta)
            media = probe_file(path, FERRAMENTAS)
            for rotulo, alvo in casos(media, quais):
                chave = f"{assinatura}|{rotulo}"
                registro = cache.setdefault(chave, {})
                if "real" not in registro:
                    if argumentos.so_resumo:
                        continue
                    try:
                        registro["real"], registro["segundos"] = tamanho_real(media, alvo, pasta)
                    except RuntimeError as erro:
                        print(f"V{indice} {rotulo}: falhou ({erro})", file=sys.stderr)
                        continue
                    argumentos.cache.write_text(json.dumps(cache, indent=1))
                real = registro["real"]
                estimativas = {"formula": estimate_convert_size(media, alvo)}
                if needs_sample(media, alvo):
                    chave_amostra = f"kbps-amostra|{AMOSTRA}"
                    if chave_amostra not in registro and not argumentos.so_resumo:
                        try:
                            inicio_amostra = time.monotonic()
                            registro[chave_amostra] = sample.sample_kbps(media, alvo, FERRAMENTAS, ProcessControl())
                            registro[chave_amostra + "|segundos"] = time.monotonic() - inicio_amostra
                        except Exception as erro:  # noqa: BLE001 - o harness relata e segue
                            registro[chave_amostra] = None
                            print(f"V{indice} {rotulo}: amostra falhou ({erro})", file=sys.stderr)
                        argumentos.cache.write_text(json.dumps(cache, indent=1))
                    if registro.get(chave_amostra):
                        estimativas["amostra"] = estimate_convert_size(media, alvo, registro[chave_amostra])
                        segundos_amostra.append((registro.get(chave_amostra + "|segundos", 0.0), registro["segundos"]))
                for metodo, estimado in estimativas.items():
                    erro = (estimado - real) / real * 100
                    erros.setdefault(rotulo, {}).setdefault(metodo, []).append(erro)
                    if media.size and estimado > media.size and real < media.size:
                        falsos.setdefault(rotulo, {}).setdefault(metodo, 0)
                        falsos[rotulo][metodo] += 1
                    linhas.append((f"V{indice}", rotulo, metodo, real, estimado, erro))
    if argumentos.detalhe:
        print(f"{'mídia':5s} {'caso':20s} {'método':8s} {'real MB':>9s} {'estim. MB':>9s} {'erro %':>8s}")
        for v, rotulo, metodo, real, estimado, erro in linhas:
            print(f"{v:5s} {rotulo:20s} {metodo:8s} {real / 1e6:9.2f} {estimado / 1e6:9.2f} {erro:+8.1f}")
    print(f"\n{'caso':20s} {'método':8s} {'n':>3s} {'|erro| mediano':>15s} {'p90 |erro|':>11s} {'pior':>8s} {'viés':>8s} "
          f"{'disse crescer, encolheu':>24s}")
    total: dict[str, list[float]] = {}
    for rotulo in sorted(erros):
        for metodo, valores in erros[rotulo].items():
            absolutos = sorted(abs(v) for v in valores)
            p90 = absolutos[min(len(absolutos) - 1, int(len(absolutos) * 0.9))]
            print(f"{rotulo:20s} {metodo:8s} {len(valores):3d} {statistics.median(absolutos):14.1f}% {p90:10.1f}% "
                  f"{max(valores, key=abs):+7.0f}% {statistics.mean(valores):+7.1f}% "
                  f"{falsos.get(rotulo, {}).get(metodo, 0):>23d}")
            total.setdefault(metodo, []).extend(valores)
    medidos = [m for m, _ in segundos_amostra if m]
    if medidos:
        print(f"\ntempo da amostra: mediana {statistics.median(medidos):.1f} s, máximo {max(medidos):.1f} s "
              f"(a conversão inteira levou {statistics.median(c for _, c in segundos_amostra):.1f} s na mediana)")
    print()
    for metodo, valores in total.items():
        absolutos = sorted(abs(v) for v in valores)
        print(f"TODOS {metodo:8s} n={len(valores):3d} |erro| mediano {statistics.median(absolutos):5.1f}%  "
              f"p90 {absolutos[min(len(absolutos) - 1, int(len(absolutos) * 0.9))]:5.1f}%  pior {max(valores, key=abs):+6.0f}%  "
              f"viés {statistics.mean(valores):+6.1f}%  disse crescer e encolheu: {sum(f.get(metodo, 0) for f in falsos.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
