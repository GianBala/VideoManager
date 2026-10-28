"""A conta dos filtros de cor sobre bytes, sem ffmpeg nem Qt (a comparação com o ffmpeg está em ``test_cores_contra_o_ffmpeg``).

A referência é escrita pixel a pixel, com a mesma aritmética inteira: a implementação em bytes e inteiros enormes tem de
dar **exatamente** o mesmo, inclusive nos cantos do cubo de cor, onde a soma passa de 255 ou o deslocamento sai de 0.
"""

import random

import pytest

from videomanager.domain.color_filters import CONTRAST
from videomanager.domain.color_filters import LUMA
from videomanager.domain.color_filters import SEPIA_MATRIX
from videomanager.domain.color_filters import apply_color_filter

FILTROS = ("inverter", "pb", "sepia", "contraste")


def _fixo(pesos) -> tuple[int, ...]:
    return tuple(round(p * 256) for p in pesos)


def _ponderado(pesos, r: int, g: int, b: int) -> int:
    return min(255, (sum(p * c for p, c in zip(_fixo(pesos), (r, g, b))) + 128) >> 8)


def _referencia(nome: str, r: int, g: int, b: int) -> tuple[int, int, int]:
    if nome == "inverter":
        return 255 - r, 255 - g, 255 - b
    if nome == "pb":
        y = _ponderado(LUMA, r, g, b)
        return y, y, y
    if nome == "sepia":
        return tuple(_ponderado(linha, r, g, b) for linha in SEPIA_MATRIX)
    luma = _ponderado(LUMA, r, g, b)
    limitada = 16 + 219 * luma / 255
    deslocada = min(255.0, max(0.0, CONTRAST * (limitada - 128) + 128))
    delta = round((deslocada - limitada) * 255 / 219)
    return tuple(min(255, max(0, c + delta)) for c in (r, g, b))


def _pixels(n: int, semente: int = 5) -> bytes:
    acaso = random.Random(semente)
    cantos = [bytes((r, g, b, 255)) for r in (0, 255) for g in (0, 255) for b in (0, 255)]
    return b"".join(cantos) + bytes(acaso.randrange(256) for _ in range(4 * n))


@pytest.mark.parametrize("nome", FILTROS)
def test_cada_filtro_da_exatamente_a_conta_pixel_a_pixel(nome):
    entrada = _pixels(3000)
    saida = apply_color_filter(nome, entrada)
    esperado = bytearray(entrada)
    for i in range(0, len(entrada), 4):
        esperado[i:i + 3] = bytes(_referencia(nome, entrada[i], entrada[i + 1], entrada[i + 2]))
    assert saida == bytes(esperado)


@pytest.mark.parametrize("nome", FILTROS)
def test_o_quarto_byte_de_cada_pixel_passa_como_veio_e_o_tamanho_nao_muda(nome):
    entrada = bytes(range(256)) * 4
    saida = apply_color_filter(nome, entrada)
    assert len(saida) == len(entrada) and saida[3::4] == entrada[3::4]


def test_inverter_duas_vezes_devolve_o_quadro():
    entrada = _pixels(500)
    assert apply_color_filter("inverter", apply_color_filter("inverter", entrada)) == entrada


def test_pb_deixa_os_tres_canais_iguais_e_o_cinza_continua_cinza():
    saida = apply_color_filter("pb", _pixels(500))
    assert saida[0::4] == saida[1::4] == saida[2::4]
    cinzas = bytes(v for c in range(0, 256, 5) for v in (c, c, c, 255))
    assert apply_color_filter("pb", cinzas)[0::4] == cinzas[0::4]


def test_o_sepia_corta_em_255_e_o_contraste_em_0_e_255():
    # Branco: as duas primeiras linhas da matriz passam de 1 e cortam em 255; a terceira dá 0,94 (240, com pesos de 1/256).
    assert apply_color_filter("sepia", bytes((255, 255, 255, 255)))[:3] == bytes((255, 255, 240))
    preto, branco = apply_color_filter("contraste", bytes((0, 0, 0, 255))), apply_color_filter("contraste", bytes((255, 255, 255, 255)))
    assert preto[:3] == bytes((0, 0, 0)) and branco[:3] == bytes((255, 255, 255))


def test_o_contraste_afasta_os_tons_do_meio_cinza():
    escuro, claro = apply_color_filter("contraste", bytes((90, 90, 90, 255)))[0], apply_color_filter("contraste", bytes((170, 170, 170, 255)))[0]
    assert escuro < 90 and claro > 170


def test_sem_pixels_nao_ha_o_que_fazer():
    assert apply_color_filter("sepia", b"") == b""


def test_nome_desconhecido_e_tamanho_quebrado_sao_recusados():
    with pytest.raises(ValueError):
        apply_color_filter("vinheta", bytes(8))
    with pytest.raises(ValueError):
        apply_color_filter("pb", bytes(7))
