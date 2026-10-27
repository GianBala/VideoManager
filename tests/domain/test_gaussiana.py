"""A gaussiana da prévia do arrasto: propriedades da conta, sem ffmpeg nem Qt."""

import pytest

from videomanager.domain.constants import REGION_BLUR_STEPS
from videomanager.domain.gaussian import gaussian_blur


def _borrar(plano, w, h, sigma=0.35 * 16):
    return gaussian_blur(plano, w, h, sigma, REGION_BLUR_STEPS)


def test_um_plano_constante_continua_constante():
    assert _borrar([77] * (28 * 16), 28, 16) == [77] * (28 * 16)
    assert _borrar([255] * (16 * 16), 16, 16) == [255] * (16 * 16)
    assert _borrar([0] * (16 * 40), 16, 40) == [0] * (16 * 40)


def test_o_impulso_se_espalha_simetrico_e_sem_ganho():
    w = h = 33
    plano = [0] * (w * h)
    plano[(h // 2) * w + w // 2] = 255
    saida = _borrar(plano, w, h, sigma=3.0)
    # Uma gaussiana: o pico fica no centro e cada quadrante é o espelho do outro.
    assert max(saida) == saida[(h // 2) * w + w // 2] < 255
    for y in range(h):
        for x in range(w):
            assert abs(saida[y * w + x] - saida[y * w + (w - 1 - x)]) <= 1
            assert abs(saida[y * w + x] - saida[(h - 1 - y) * w + x]) <= 1
    # A massa que não saiu pela borda é a do impulso (arredondar cada pixel para inteiro cabe em uma margem).
    assert sum(saida) == pytest.approx(255, abs=255 * 0.06)


def test_borra_mais_com_sigma_maior():
    w, h = 28, 16
    plano = [255 if x < w // 2 else 0 for _ in range(h) for x in range(w)]
    fraco, forte = _borrar(plano, w, h, sigma=1.0), _borrar(plano, w, h, sigma=5.6)
    meio = (h // 2) * w
    degrau_fraco = abs(fraco[meio + w // 2 - 1] - fraco[meio + w // 2])
    degrau_forte = abs(forte[meio + w // 2 - 1] - forte[meio + w // 2])
    assert degrau_forte < degrau_fraco
