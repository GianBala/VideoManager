"""O filtro móvel: qualquer filtro pode agir só num retângulo, como o desfoque de região.

Roda sem Qt nem ffmpeg. O desfoque é sempre um retângulo; os demais filtros começam na tela inteira (como sempre foi) e
só viram retângulo quando o bloco é ``movable``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.constants import REGION_BLUR_DEFAULT_SCALE
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import OverlayType
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import filter_pose
from videomanager.domain.project import pseudo_media

OUTROS = ["pb", "sepia", "inverter", "contraste", "vinheta"]


def _filtro(nome: str, **extra) -> Clip:
    pose = {} if "scale_x" in extra else filter_pose(nome)
    return Clip(pseudo_media(OverlayType.FILTER, nome, 4.0), 0.0, 4.0, overlay_type="filter", filter_name=nome,
                **pose, **extra)


@pytest.mark.parametrize("nome", OUTROS)
def test_filtro_comum_nao_tem_regiao_e_o_movel_tem(nome):
    assert not _filtro(nome).has_region
    assert _filtro(nome, movable=True).has_region
    assert not _filtro(nome, movable=True).is_region_blur


def test_o_desfoque_e_sempre_regiao_e_o_unico_que_borra():
    assert _filtro(REGION_BLUR).has_region and _filtro(REGION_BLUR).is_region_blur
    assert not _filtro("sepia", movable=True).is_region_blur


def test_o_campo_so_vale_para_filtro():
    texto = Clip(pseudo_media(OverlayType.TEXT, "t", 3.0), 0.0, 3.0, overlay_type="text", movable=True)
    assert not texto.has_region and not texto.is_region_blur


@pytest.mark.parametrize("nome", OUTROS)
def test_ligar_o_movel_vira_um_retangulo_pequeno_no_centro(nome):
    movel = _filtro(nome).with_movable(True)
    assert movel.movable and movel.filter_name == nome and movel.has_region
    assert (movel.x, movel.y) == (0.5, 0.5)
    assert (movel.scale_x, movel.scale_y) == (REGION_BLUR_DEFAULT_SCALE, REGION_BLUR_DEFAULT_SCALE)
    # É o mesmo retângulo com que o desfoque nasce.
    assert movel.region_rect(1920, 1080) == _filtro(REGION_BLUR).region_rect(1920, 1080)


@pytest.mark.parametrize("nome", OUTROS)
def test_desligar_o_movel_volta_a_tela_inteira_sem_quadros_chave(nome):
    anim = (Keyframe(0.0, x=0.2, y=0.3, scale_x=0.3, scale_y=0.3), Keyframe(2.0, x=0.7, y=0.6, scale_x=0.3, scale_y=0.3))
    movel = _filtro(nome, movable=True, x=0.25, y=0.7, scale=0.3, scale_x=0.3, scale_y=0.3, keyframes=anim)
    comum = movel.with_movable(False)
    assert not comum.movable and not comum.has_region and comum.keyframes == ()
    assert (comum.x, comum.y, comum.scale_x, comum.scale_y) == (0.5, 0.5, 1.0, 1.0)
    assert comum.filter_name == nome


def test_ligar_ou_desligar_o_que_ja_esta_assim_nao_mexe_no_bloco():
    movel = _filtro("sepia", movable=True, x=0.2, y=0.3, scale=0.4, scale_x=0.4, scale_y=0.4)
    assert movel.with_movable(True) is movel
    comum = _filtro("sepia")
    assert comum.with_movable(False) is comum


def test_o_desfoque_e_o_que_nao_e_filtro_nao_tem_o_que_ligar():
    desfoque = _filtro(REGION_BLUR, x=0.2, y=0.3)
    assert desfoque.with_movable(True) is desfoque and desfoque.with_movable(False) is desfoque
    texto = Clip(pseudo_media(OverlayType.TEXT, "t", 3.0), 0.0, 3.0, overlay_type="text")
    assert texto.with_movable(True) is texto


def test_trocar_o_tipo_de_um_filtro_movel_o_mantem_movel_com_o_mesmo_retangulo():
    movel = _filtro("sepia", movable=True, x=0.2, y=0.3, scale=0.4, scale_x=0.4, scale_y=0.4)
    novo = movel.with_filter("inverter")
    assert novo.filter_name == "inverter" and novo.movable and novo.has_region
    assert (novo.x, novo.y, novo.scale_x, novo.scale_y) == (0.2, 0.3, 0.4, 0.4)


def test_um_filtro_movel_que_vira_desfoque_conserva_o_retangulo_e_o_campo_se_apaga():
    movel = _filtro("sepia", movable=True, x=0.2, y=0.3, scale=0.4, scale_x=0.4, scale_y=0.4)
    desfoque = movel.with_filter(REGION_BLUR)
    assert desfoque.is_region_blur and not desfoque.movable
    assert (desfoque.x, desfoque.y, desfoque.scale_x, desfoque.scale_y) == (0.2, 0.3, 0.4, 0.4)
    # Um filtro de tela cheia que vira desfoque nasce com o tamanho inicial, como sempre.
    assert _filtro("sepia").with_filter(REGION_BLUR).scale_x == REGION_BLUR_DEFAULT_SCALE


def test_o_desfoque_que_vira_outro_filtro_volta_a_tela_inteira_e_nao_movel():
    novo = _filtro(REGION_BLUR, x=0.2, y=0.3).with_filter("sepia")
    assert novo.filter_name == "sepia" and not novo.movable and not novo.has_region
    assert (novo.x, novo.y, novo.scale_x, novo.scale_y) == (0.5, 0.5, 1.0, 1.0)


def test_o_projeto_leva_o_campo_na_troca_de_filtro_e_nao_o_perde():
    movel = _filtro("sepia", movable=True, x=0.2, y=0.3, scale=0.4, scale_x=0.4, scale_y=0.4)
    projeto = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(movel,), name="A"),), width=1280, height=720, fps=30.0)
    depois = projeto.with_filter(movel.clip_id, "pb").find(movel.clip_id)[1]
    assert depois.filter_name == "pb" and depois.movable and (depois.x, depois.scale_y) == (0.2, 0.4)
    desfoque = projeto.with_filter(movel.clip_id, REGION_BLUR).find(movel.clip_id)[1]
    assert desfoque.is_region_blur and not desfoque.movable


def test_o_retangulo_do_movel_prende_dentro_da_tela_como_o_do_desfoque():
    movel = _filtro("sepia").with_movable(True)
    maior = movel.with_region_size(0.5, 0.5)
    assert replace(maior, x=0.99).with_region_size(0.5, 0.5).x == pytest.approx(0.75)
