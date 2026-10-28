"""A vinheta do ffmpeg (``vignette=PI/4``) como conta: quanto cada pixel de um quadro é escurecido.

O filtro multiplica o pixel por um fator que só depende da distância dele ao centro do quadro (medido: a razão é a
mesma em branco, cinza, vermelho e azul), então a prévia do arrasto escurece o quadro do gesto multiplicando-o por esta
máscara, sem abrir o ffmpeg. O fator é ``cos(π/4 · distância / metade da diagonal)⁴``, com o centro em
``(largura / 2, altura / 2)``; comparada com a máscara que o ffmpeg desenha, a diferença é de no máximo 1 em 255.
"""

import math

_ANGLE = math.pi / 4


def mask_size(width: int, height: int, step: int = 1) -> tuple[int, int]:
    """O tamanho da grade que :func:`vignette_factors` devolve para um quadro ``width``×``height`` com amostra ``step``."""
    return -(-width // step), -(-height // step)


def vignette_factors(width: int, height: int, step: int = 1) -> bytes:
    """O fator de cada pixel de um quadro ``width``×``height`` (255 = não escurece), linha após linha.

    Com ``step`` > 1 devolve uma grade menor, um valor por bloco de ``step``×``step`` pixels e calculado no centro do
    bloco (``mask_size`` diz o tamanho): a prévia a amplia ao pintar, porque o fator é uma curva suave e o quadro
    inteiro de 320×180 passa de 14 ms para 1 ms.
    """
    reach = math.hypot(width / 2, height / 2)
    scale = _ANGLE / reach
    grid_w, grid_h = mask_size(width, height, step)
    middle = (step - 1) / 2
    columns = [(j * step + middle - width / 2) ** 2 for j in range(grid_w)]
    out = bytearray()
    for i in range(grid_h):
        row = (i * step + middle - height / 2) ** 2
        out += bytes(round(255 * math.cos(min(scale * math.sqrt(column + row), math.pi / 2)) ** 4)
                     for column in columns)
    return bytes(out)
