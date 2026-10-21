"""A região do desfoque: uma conta só para o compositor e para a prévia.

Roda sem Qt nem ffmpeg. Que a expressão do ffmpeg caia no mesmo pixel que estas
funções é conferido com o ffmpeg de verdade em ``tests/test_regiao_do_desfoque_export.py``.
"""

from __future__ import annotations

import pytest

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.constants import REGION_BLUR_DEFAULT_SCALE
from videomanager.domain.constants import REGION_MIN_SCALE
from videomanager.domain.geometry import region_origin
from videomanager.domain.geometry import region_origin_expr
from videomanager.domain.geometry import region_size
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import OverlayType
from videomanager.domain.project import filter_pose
from videomanager.domain.project import pseudo_media


def _filtro(nome: str = REGION_BLUR, **extra) -> Clip:
    media = pseudo_media(OverlayType.FILTER, nome, 3.0)
    pose = filter_pose(nome) if "scale_x" not in extra else {}
    return Clip(media, 0.0, 3.0, overlay_type="filter", filter_name=nome, **pose, **extra)


# -- tamanho -----------------------------------------------------------------

@pytest.mark.parametrize("escala, tela, esperado", [
    (1.0, 1920, 1920),
    (0.3, 1920, 576),
    (0.3, 1080, 324),
    (0.5, 641, 320),        # tela ímpar: o par de baixo, nunca passa dela
    (REGION_MIN_SCALE / 100, 1920, 2),   # nunca menos que 2 px
    (5.0, 1920, 1920),      # nunca maior que a tela
])
def test_o_tamanho_e_par_e_cabe_na_tela(escala, tela, esperado):
    w, _ = region_size(escala, escala, tela, 1080)
    assert w == esperado
    assert w % 2 == 0 and 2 <= w <= tela


def test_largura_e_altura_sao_independentes():
    assert region_size(0.5, 0.1, 1280, 720) == (640, 72)


# -- posição -----------------------------------------------------------------

@pytest.mark.parametrize("cx, cy", [(-0.3, 0.5), (1.3, 0.5), (0.5, -0.3), (0.5, 1.3), (0.4003, 0.3991), (0.5017, 0.7)])
def test_a_posicao_e_par_e_a_regiao_nunca_sai_da_tela(cx, cy):
    w, h, tela_w, tela_h = 320, 240, 1920, 1080
    left, top = region_origin(cx, cy, w, h, tela_w, tela_h)
    assert left % 2 == 0 and top % 2 == 0
    assert 0 <= left <= tela_w - w and 0 <= top <= tela_h - h


def test_o_canto_arredonda_a_metade_para_longe_do_zero():
    # 0,25 · 64 − 14/2 = 9; metade de 9 é 4,5 — o round do ffmpeg dá 5 (canto 10), o do Python daria 4 (canto 8).
    assert region_origin(0.25, 0.5, 14, 14, 64, 64)[0] == 10


def test_a_regiao_do_tamanho_da_tela_fica_no_canto():
    assert region_origin(0.9, 0.1, 1920, 1080, 1920, 1080) == (0, 0)


def test_a_expressao_do_ffmpeg_e_a_conta_com_o_centro_em_t():
    expr = region_origin_expr("0.2+0.15*t", 1920, 320)
    assert expr == "2*round(max(0,min(1600,(0.2+0.15*t)*1920-320/2))/2)"


def test_o_limite_da_expressao_e_par_com_tela_impar():
    # Com 641 − 320 = 321 o limite ímpar deixaria o canto passar dele; o limite é o par de baixo.
    assert "min(320," in region_origin_expr("0.5", 641, 320)


# -- o bloco -----------------------------------------------------------------

def test_so_o_desfoque_tem_regiao():
    assert _filtro().has_region
    for nome in ("pb", "sepia", "contraste", "vinheta", "inverter"):
        assert not _filtro(nome).has_region
    texto = Clip(pseudo_media(OverlayType.TEXT, "x", 3.0), 0.0, 3.0, overlay_type="text", filter_name=REGION_BLUR)
    assert not texto.has_region      # o nome do filtro não basta: tem de ser um bloco de filtro


def test_o_desfoque_nasce_pequeno_e_os_outros_em_tela_cheia():
    assert _filtro().scale_x == REGION_BLUR_DEFAULT_SCALE
    assert _filtro("sepia").scale_x == 1.0
    assert filter_pose("desfoque")["scale"] == filter_pose("desfoque")["scale_y"]


def test_um_filtro_antigo_continua_em_tela_cheia():
    sepia = _filtro("sepia")
    assert sepia.region_rect(1280, 720) == (0, 0, 1280, 720)


def test_a_regiao_segue_a_posicao_dos_quadros_chave_e_nao_o_tamanho():
    base = _filtro(x=0.25, y=0.5, scale_x=0.2, scale_y=0.2, scale=0.2)
    animado = base.with_region_size(0.2, 0.2)
    animado = Clip(**{**animado.__dict__, "keyframes": (
        Keyframe(0.0, x=0.25, y=0.5, scale_x=0.2, scale_y=0.2),
        Keyframe(2.0, x=0.75, y=0.5, scale_x=0.2, scale_y=0.2),
    )})
    inicio = animado.region_rect(1920, 1080, 0.0)
    meio = animado.region_rect(1920, 1080, 1.0)
    fim = animado.region_rect(1920, 1080, 2.0)
    assert inicio[0] < meio[0] < fim[0]
    assert meio[0] == pytest.approx(0.5 * 1920 - 384 / 2, abs=2)
    assert inicio[2:] == meio[2:] == fim[2:] == (384, 216)


def test_redimensionar_muda_todos_os_quadros_chave_e_nao_toca_na_posicao():
    clip = _filtro(keyframes=(
        Keyframe(0.0, x=0.2, y=0.3, scale_x=0.3, scale_y=0.3),
        Keyframe(2.0, x=0.8, y=0.6, scale_x=0.3, scale_y=0.3),
    ))
    novo = clip.with_region_size(0.5, 0.25)
    assert (novo.scale_x, novo.scale_y) == (0.5, 0.25)
    assert [(k.scale_x, k.scale_y) for k in novo.keyframes] == [(0.5, 0.25), (0.5, 0.25)]
    assert [(k.x, k.y) for k in novo.keyframes] == [(0.2, 0.3), (0.8, 0.6)]
    assert (novo.x, novo.y) == (clip.x, clip.y)


def test_o_tamanho_pedido_e_limitado_ao_que_a_regiao_aceita():
    novo = _filtro().with_region_size(0.0, 7.0)
    assert (novo.scale_x, novo.scale_y) == (REGION_MIN_SCALE, 1.0)


def test_trocar_um_filtro_comum_por_desfoque_da_o_tamanho_inicial():
    sepia = _filtro("sepia")
    novo = sepia.with_filter(REGION_BLUR)
    assert novo.has_region and novo.scale_x == novo.scale_y == REGION_BLUR_DEFAULT_SCALE
    assert novo.clip_id == sepia.clip_id


def test_trocar_o_desfoque_por_outro_filtro_devolve_a_pose_padrao():
    movido = _filtro(x=0.2, y=0.8, keyframes=(Keyframe(0.0, x=0.2, y=0.8, scale_x=0.3, scale_y=0.3),))
    novo = movido.with_filter("sepia")
    assert not novo.has_region
    assert (novo.x, novo.y, novo.scale_x, novo.scale_y, novo.keyframes) == (0.5, 0.5, 1.0, 1.0, ())


def test_trocar_o_desfoque_por_ele_mesmo_nao_mexe_na_pose():
    movido = _filtro(x=0.2, y=0.8, scale_x=0.4, scale_y=0.4, scale=0.4)
    assert movido.with_filter(REGION_BLUR) == movido


def test_trocar_entre_filtros_comuns_so_muda_o_nome():
    novo = _filtro("sepia").with_filter("pb")
    assert novo.filter_name == "pb" and novo.scale_x == 1.0
