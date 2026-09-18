"""Quando o último quadro de um arquivo entra na tela.

A taxa declarada não descreve o fim de um arquivo. Um GIF guarda a duração de
cada quadro em centésimos de segundo e pode segurar o último por segundos: um
de 128 quadros que declara 30 q/s começa o último em 4,23 s, e não em 4,2667 s
como a grade sugere. Sem saber onde ele começa de verdade, a prévia buscava um
instante depois do fim de tudo e não achava quadro nenhum — a tela ficava preta
justamente com a agulha parada no fim do vídeo.

Os tempos vêm do próprio arquivo, por ``ffprobe``, e ficam guardados por
arquivo (caminho, tamanho e data): é uma leitura por mídia, não por quadro.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import subprocess_kwargs

# Quanto do fim do arquivo é lido à procura do último quadro. Cobre com folga a
# pausa final de um GIF; ler o arquivo inteiro seria caro num vídeo longo.
_TAIL_SECONDS = 8.0
# Acima disto, um arquivo sem índice (GIF) não é lido do começo: a leitura
# custaria mais que o quadro que se quer mostrar.
_FULL_READ_LIMIT = 64 * 1024 * 1024

_cache: dict[tuple[str, int, int], float | None] = {}


def last_frame_start(path: Path, duration: float, tools: FFmpegTools) -> float | None:
    """Instante em que o último quadro do arquivo começa, ou ``None``.

    ``None`` quando não dá para ler (arquivo grande demais sem índice, formato
    que não informa tempos, ffprobe indisponível): quem chama volta a estimar
    pela taxa declarada.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    key = (str(path), info.st_size, int(info.st_mtime))
    if key in _cache:
        return _cache[key]
    found = _probe(path, duration, tools, info.st_size)
    _cache[key] = found
    return found


def _probe(path: Path, duration: float, tools: FFmpegTools, size: int) -> float | None:
    start = max(0.0, duration - _TAIL_SECONDS) if duration > 0 else 0.0
    times = _packet_times(path, tools, start if start > 0 else None)
    if not times and start > 0 and size <= _FULL_READ_LIMIT:
        # Formato sem índice (o GIF é o caso): a busca não leva a lugar nenhum e
        # a leitura começa do zero. Só vale para arquivo pequeno.
        times = _packet_times(path, tools, None)
    return max(times) if times else None


def _packet_times(path: Path, tools: FFmpegTools, start: float | None) -> list[float]:
    command = [
        tools.ffprobe_str, "-v", "error", "-select_streams", "v",
        "-show_entries", "packet=pts_time", "-of", "csv=p=0",
    ]
    if start is not None:
        command += ["-read_intervals", f"{start:.3f}%+{_TAIL_SECONDS + 1:.3f}"]
    command.append(str(path))
    try:
        result = subprocess.run(command, timeout=30, check=False, **subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        return []
    saida = (result.stdout or b"").decode("utf-8", "replace")
    times = []
    for linha in saida.splitlines():
        try:
            times.append(float(linha.strip().rstrip(",")))
        except ValueError:
            continue
    return times
