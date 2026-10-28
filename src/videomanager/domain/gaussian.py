"""Desfoque gaussiano de um plano de pixels, a mesma conta do ``gblur`` do ffmpeg.

A prévia do arrasto borra a região em Python, a cada movimento do mouse, e tem de cair onde o ffmpeg cairá no
quadro final. O ``gblur`` aproxima a gaussiana por um filtro recursivo (Alvarez-Mazorra) aplicado ``steps`` vezes
em cada eixo, com a borda tratada para que um plano constante continue constante; reproduzido aqui passo a passo,
a diferença para o ffmpeg real é de no máximo 1 em 255 (arredondamento de ``float``).

Só serve para telas de trabalho pequenas (``geometry.region_work_size``): é Python puro, ~0,3 ms por canal em
28×16 e ~9 ms em 768×16. Abaixo de 16 px de altura o ``gblur`` do ffmpeg deixa linhas sem filtrar, defeito dele
que esta conta não reproduz.
"""

import math
from collections.abc import Sequence


def gaussian_blur(plane: Sequence[float], width: int, height: int, sigma: float, steps: int) -> list[int]:
    """Borra ``plane`` (``width``×``height``, linha após linha, valores de 0 a 255) e devolve inteiros de 0 a 255."""
    lam = sigma * sigma / (2.0 * steps)
    nu = (1.0 + 2.0 * lam - math.sqrt(1.0 + 4.0 * lam)) / (2.0 * lam)
    boundary = 1.0 / (1.0 - nu)
    # Ganho de um plano constante: ``boundary`` por passada, duas passadas por passo, dois eixos.
    post = (1.0 - nu) ** (4 * steps)

    def smooth(line: list[float]) -> list[float]:
        last = len(line) - 1
        for _ in range(steps):
            line[0] *= boundary
            for i in range(1, last + 1):
                line[i] += nu * line[i - 1]
            line[last] *= boundary
            for i in range(last, 0, -1):
                line[i - 1] += nu * line[i]
        return line

    out = [float(v) for v in plane]
    for y in range(height):
        out[y * width:(y + 1) * width] = smooth(out[y * width:(y + 1) * width])
    for x in range(width):
        out[x::width] = smooth(out[x::width])
    return [min(255, max(0, int(v * post + 0.5))) for v in out]
