"""A caixa "Filtro móvel" da aba Propriedades: liga o retângulo do filtro e libera o que hoje só o desfoque tem."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.constants import REGION_BLUR_DEFAULT_SCALE
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import OverlayType
from videomanager.domain.project import filter_pose
from videomanager.domain.project import pseudo_media
from videomanager.presentation.qt import strings
from videomanager.presentation.qt import strings_en
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget

pytestmark = pytest.mark.usefixtures("desktop_app")

OUTROS = ["pb", "sepia", "inverter", "contraste", "vinheta"]


def _filtro(nome: str, **extra) -> Clip:
    pose = {} if "scale_x" in extra else filter_pose(nome)
    return Clip(pseudo_media(OverlayType.FILTER, nome, 4.0), 0.0, 4.0, overlay_type="filter", filter_name=nome,
                **pose, **extra)


def _propriedades(clip: Clip, agulha: float = 1.0) -> tuple[_ClipPropertiesWidget, list[dict]]:
    widget = _ClipPropertiesWidget()
    emitidos: list[dict] = []
    widget.property_changed.connect(lambda _cid, mudancas: emitidos.append(mudancas))
    widget.load_clip(clip, 1920, 1080)
    widget.set_playhead_position(agulha)
    return widget, emitidos


def _visivel(widget: _ClipPropertiesWidget, controle) -> bool:
    """``isVisibleTo``: a janela não está na tela, então ``isVisible`` é sempre falso."""
    return controle.isVisibleTo(widget)


@pytest.mark.parametrize("nome", OUTROS)
def test_um_filtro_comum_mostra_a_caixa_desligada_e_nenhuma_pose(nome):
    widget, _ = _propriedades(_filtro(nome))
    assert _visivel(widget, widget._filter_group) and _visivel(widget, widget._chk_movable)
    assert not widget._chk_movable.isChecked()
    for grupo in (widget._transform_group, widget._animation_group):
        assert not _visivel(widget, grupo)


@pytest.mark.parametrize("nome", OUTROS)
def test_ligada_a_caixa_libera_posicao_tamanho_e_animacao(nome):
    widget, _ = _propriedades(_filtro(nome, movable=True, x=0.4, y=0.6, scale=0.3, scale_x=0.3, scale_y=0.3))
    assert widget._chk_movable.isChecked()
    for grupo in (widget._filter_group, widget._transform_group, widget._animation_group):
        assert _visivel(widget, grupo)
    for nome_do_controle in ("_spin_x", "_spin_y", "_spin_w", "_spin_h"):
        assert _visivel(widget, getattr(widget, nome_do_controle)), nome_do_controle
    # O que um recorte não tem (como no desfoque): opacidade, rotação e a trava de proporção.
    for nome_do_controle in ("_slider_opacity", "_spin_opacity", "_slider_rot", "_spin_rot", "_rotation_presets_box",
                             "_chk_lock_ratio"):
        assert not _visivel(widget, getattr(widget, nome_do_controle)), nome_do_controle
    assert widget._spin_x.value() == round(0.4 * 1920) and widget._spin_w.value() == round(1920 * 0.3)


def test_o_desfoque_nao_tem_a_caixa_porque_e_sempre_um_retangulo():
    widget, _ = _propriedades(_filtro(REGION_BLUR))
    assert not _visivel(widget, widget._filter_group)
    assert _visivel(widget, widget._transform_group) and _visivel(widget, widget._animation_group)


def test_o_que_nao_e_filtro_nao_tem_a_caixa():
    imagem = Clip(MediaRef(Path("a.png"), MediaKind.IMAGE, width=100, height=100), 0.0, 4.0, overlay_type="image")
    texto = Clip(pseudo_media(OverlayType.TEXT, "t", 4.0), 0.0, 4.0, overlay_type="text", text_content="Oi")
    for clip in (imagem, texto):
        widget, _ = _propriedades(clip)
        assert not _visivel(widget, widget._filter_group)


def test_ligar_a_caixa_emite_o_retangulo_inicial_no_centro_e_sem_quadros_chave():
    widget, emitidos = _propriedades(_filtro("sepia"))
    widget._chk_movable.setChecked(True)
    (mudancas,) = emitidos
    assert mudancas == {"movable": True, "x": 0.5, "y": 0.5, "scale": REGION_BLUR_DEFAULT_SCALE,
                        "scale_x": REGION_BLUR_DEFAULT_SCALE, "scale_y": REGION_BLUR_DEFAULT_SCALE, "keyframes": ()}


def test_desligar_a_caixa_emite_a_tela_inteira():
    widget, emitidos = _propriedades(_filtro("pb", movable=True, x=0.2, y=0.8, scale=0.4, scale_x=0.4, scale_y=0.4))
    widget._chk_movable.setChecked(False)
    (mudancas,) = emitidos
    assert mudancas == {"movable": False, "x": 0.5, "y": 0.5, "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0, "keyframes": ()}


def test_carregar_um_bloco_nao_emite_nada_e_nao_marca_a_caixa_de_outro():
    widget, emitidos = _propriedades(_filtro("sepia", movable=True, x=0.4, y=0.6, scale=0.3, scale_x=0.3, scale_y=0.3))
    widget.load_clip(_filtro("pb"), 1920, 1080)
    assert emitidos == [] and not widget._chk_movable.isChecked()
    widget.load_clip(_filtro(REGION_BLUR), 1920, 1080)
    assert emitidos == [] and not widget._chk_movable.isChecked()      # o desfoque não herda a marca do bloco anterior


def test_os_dois_catalogos_trazem_os_textos_da_caixa():
    for catalogo in (strings, strings_en):
        assert catalogo.PROP_FILTER and catalogo.PROP_FILTER_MOVABLE and catalogo.PROP_FILTER_MOVABLE_NOTE
    assert strings.PROP_FILTER_MOVABLE != strings_en.PROP_FILTER_MOVABLE


# -- pelo painel inteiro ------------------------------------------------------------------------

def _filtros(painel):
    return [c for t in painel._project.additional_tracks for c in t.clips if c.overlay_type is OverlayType.FILTER]


def test_ligar_a_caixa_pelo_painel_vira_retangulo_no_projeto_na_previa_e_na_aba(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip("sepia")
    (bloco,) = _filtros(painel)
    painel._open_properties_tab(bloco.clip_id)
    widget = painel._properties_widget
    assert _visivel(widget, widget._chk_movable) and not _visivel(widget, widget._transform_group)

    widget._chk_movable.setChecked(True)

    (movel,) = _filtros(painel)
    assert movel.movable and movel.has_region and movel.filter_name == "sepia"
    assert (movel.x, movel.y, movel.scale_x, movel.scale_y) == (0.5, 0.5, REGION_BLUR_DEFAULT_SCALE, REGION_BLUR_DEFAULT_SCALE)
    assert painel._preview._active_clip.has_region                    # a prévia ganha a caixa e as alças
    assert widget._chk_movable.isChecked() and _visivel(widget, widget._transform_group)
    assert widget._spin_w.value() == round(painel._project.width * REGION_BLUR_DEFAULT_SCALE)


def test_desligar_a_caixa_pelo_painel_volta_a_tela_inteira_e_o_desfazer_devolve_o_retangulo(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip("inverter")
    (bloco,) = _filtros(painel)
    painel._open_properties_tab(bloco.clip_id)
    widget = painel._properties_widget
    widget._chk_movable.setChecked(True)
    painel._properties_session_timer.timeout.emit()                    # fecha o agrupamento de edições: o próximo é outro passo
    widget._chk_movable.setChecked(False)

    (comum,) = _filtros(painel)
    assert not comum.movable and not comum.has_region and (comum.scale_x, comum.scale_y) == (1.0, 1.0)
    assert not painel._preview._active_clip.has_region
    assert not _visivel(widget, widget._transform_group) and not widget._chk_movable.isChecked()

    painel._undo_edit()
    (de_volta,) = _filtros(painel)
    assert de_volta.movable and de_volta.has_region


def test_trocar_o_tipo_de_um_filtro_movel_pela_aba_filtros_o_mantem_movel(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip("sepia")
    (bloco,) = _filtros(painel)
    painel._open_properties_tab(bloco.clip_id)
    painel._properties_widget._chk_movable.setChecked(True)
    painel._select_filter("pb")                                         # com o bloco selecionado, troca o tipo dele
    (trocado,) = _filtros(painel)
    assert trocado.filter_name == "pb" and trocado.movable and trocado.has_region
