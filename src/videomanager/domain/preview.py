"""Quadros e geometria da prévia, sem decodificação nem objetos Qt."""
from dataclasses import dataclass
import math

MAX_PREVIEW_FPS = 60


def preview_fps(project_fps: float | None) -> float:
    """Taxa da reprodução de prévia para um projeto."""
    if not project_fps or not math.isfinite(project_fps) or project_fps <= 0:
        return 30
    return max(1, min(MAX_PREVIEW_FPS, project_fps))


BYTES_PER_PIXEL = 3  # rgb24


@dataclass(frozen=True)
class RawFrame:
    """Um quadro em rgb24, pronto para virar ``QImage`` sem conversão."""

    data: bytes
    width: int
    height: int
    seconds: float = 0.0

    @property
    def is_complete(self) -> bool:
        return len(self.data) == self.width * self.height * BYTES_PER_PIXEL


def fit_size(
    source_width: int | None,
    source_height: int | None,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """Tamanho de exibição que cabe na área, preservando a proporção.

    Sempre par: escaladores e codificadores de vídeo trabalham em blocos de dois
    pixels e recusam dimensões ímpares.
    """
    width = source_width or 16
    height = source_height or 9
    scale = min(max_width / width, max_height / height)
    return (
        max(2, int(width * scale) // 2 * 2),
        max(2, int(height * scale) // 2 * 2),
    )


def filmstrip_times(start: float, end: float, count: int) -> tuple[float, ...]:
    """Instantes das miniaturas que cobrem um trecho da linha do tempo.

    Cada miniatura representa uma fatia, e o instante escolhido é o **meio** da
    fatia: pegar o começo faria a primeira miniatura ser sempre o primeiro
    quadro do arquivo, que costuma ser preto.
    """
    if count <= 0:
        return ()
    if end <= start:
        # Trecho de duração zero — uma imagem, que só tem o instante zero.
        # Devolver a fatia média de um intervalo vazio pediria ao ffmpeg um
        # quadro depois do fim do arquivo, e ele não devolveria nada.
        return (start,)
    step = (end - start) / count
    return tuple(start + step * (index + 0.5) for index in range(count))
