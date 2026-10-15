"""Quadros e geometria da prévia, sem decodificação nem objetos Qt."""
from dataclasses import dataclass
import math

# Teto da taxa da prévia. Abaixo dele a reprodução usa **a taxa do próprio
# projeto**: pedir ao ffmpeg a mesma taxa da origem faz o filtro ``fps`` não ter
# o que duplicar nem descartar, e o movimento na tela é o do arquivo. Uma taxa
# fixa mais baixa — havia 15 aqui — deixa a imagem visivelmente aos trancos num
# vídeo de 30 ou 60 fps.
#
# O teto existe para material acima de 60 fps, onde o ganho é imperceptível e o
# custo não é: cada quadro é uma imagem crua atravessando um cano. Medido nesta
# máquina, 1920×1080 a 60 fps sustenta 355 MB/s sem atrasar.
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


def reduced_fit(
    media_width: int | None,
    media_height: int | None,
    canvas_width: int,
    canvas_height: int,
    full_width: int,
    full_height: int,
) -> tuple[int, int]:
    """Tamanho do vídeo na tela reduzida da prévia, encaixado como na tela de verdade.

    A tela da prévia é a do projeto com cada lado levado ao par de baixo, e por
    isso nem sempre tem a proporção dela: 1920×1080 na caixa 596×508 vira
    592×334. Encaixar por pixels nessa tela deixava 1 px preto em cima e embaixo
    (2 px nas laterais, conforme a janela) de um vídeo que preenche a tela do
    projeto, e a moldura da prévia ficava a um fio da imagem. Aqui o encaixe é
    feito na tela de verdade, onde ele é exato, e só então reduzido eixo a eixo:
    quem preenche uma tela preenche a outra.

    Arredonda para o par mais próximo, e não para baixo, para o ruído do ponto
    flutuante (591,99999) não custar 2 px; como os lados da tela são pares, o
    resultado nunca passa dela. Sem redução é a regra de sempre (``fit_size``).
    """
    if (canvas_width, canvas_height) == (full_width, full_height):
        return fit_size(media_width, media_height, canvas_width, canvas_height)
    width = media_width or 16
    height = media_height or 9
    scale = min(full_width / width, full_height / height)
    return (
        max(2, int(width * scale * canvas_width / full_width / 2 + 0.5) * 2),
        max(2, int(height * scale * canvas_height / full_height / 2 + 0.5) * 2),
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
