"""O desfoque de região na aba Filtros: a opção, o bloco que nasce e a troca de tipo de um bloco existente."""

from __future__ import annotations

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.constants import REGION_BLUR_DEFAULT_SCALE
from videomanager.domain.project import OverlayType
from videomanager.presentation.qt import strings
from videomanager.presentation.qt import strings_en


def _filtros(painel):
    return [c for t in painel._project.additional_tracks for c in t.clips if c.overlay_type is OverlayType.FILTER]


def test_o_desfoque_e_a_ultima_opcao_da_aba(painel_de_edicao):
    painel = painel_de_edicao
    assert painel._filter_specs[-1] == REGION_BLUR
    assert painel._filter_buttons[-1].text() == strings.EDIT_FILTER_BLUR
    assert not painel._filter_buttons[-1].icon().isNull()


def test_o_catalogo_nos_dois_idiomas_traz_a_opcao_e_a_dica():
    for catalogo, nome in ((strings, "Desfoque"), (strings_en, "Blur")):
        assert catalogo.EDIT_FILTERS[REGION_BLUR][1] == catalogo.EDIT_FILTER_BLUR == nome
        assert catalogo.EDIT_BLUR_HINT


def test_inserir_o_desfoque_cria_um_bloco_pequeno_e_ja_selecionado(painel_de_edicao):
    painel = painel_de_edicao
    painel._select_filter(REGION_BLUR)
    painel._insert_filter_clip(REGION_BLUR)
    (bloco,) = _filtros(painel)
    assert bloco.has_region and bloco.filter_name == REGION_BLUR
    assert (bloco.scale_x, bloco.scale_y) == (REGION_BLUR_DEFAULT_SCALE, REGION_BLUR_DEFAULT_SCALE)
    assert (bloco.x, bloco.y) == (0.5, 0.5)
    assert painel._timeline.selected_clip.clip_id == bloco.clip_id


def test_os_outros_filtros_continuam_nascendo_em_tela_cheia(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip("sepia")
    (bloco,) = _filtros(painel)
    assert not bloco.has_region and (bloco.scale_x, bloco.scale_y) == (1.0, 1.0)


def test_a_dica_so_aparece_com_o_desfoque_marcado(painel_de_edicao):
    painel = painel_de_edicao
    assert painel._blur_hint.isHidden()                     # abre em Preto e Branco
    painel._select_filter(REGION_BLUR)
    assert not painel._blur_hint.isHidden() and painel._blur_hint.text() == strings.EDIT_BLUR_HINT
    painel._select_filter("sepia")
    assert painel._blur_hint.isHidden()


def test_selecionar_um_bloco_de_desfoque_mostra_a_dica_e_um_de_sepia_a_esconde(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip(REGION_BLUR)
    (desfoque,) = _filtros(painel)
    painel._insert_filter_clip("sepia")
    sepia = next(c for c in _filtros(painel) if c.filter_name == "sepia")
    painel._sync_extras_controls(desfoque)
    assert not painel._blur_hint.isHidden() and painel._selected_filter_name == REGION_BLUR
    painel._sync_extras_controls(sepia)
    assert painel._blur_hint.isHidden()


def test_trocar_o_tipo_de_um_bloco_ajusta_a_pose_e_o_desfazer_a_devolve(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip("sepia")
    (sepia,) = _filtros(painel)
    antes = painel._project

    painel._select_filter(REGION_BLUR)                       # com o bloco de sépia selecionado
    (bloco,) = _filtros(painel)
    assert bloco.clip_id == sepia.clip_id and bloco.has_region
    assert (bloco.scale_x, bloco.scale_y) == (REGION_BLUR_DEFAULT_SCALE, REGION_BLUR_DEFAULT_SCALE)

    painel._select_filter("pb")                              # e de volta: a região some do bloco
    (volta,) = _filtros(painel)
    assert not volta.has_region and (volta.x, volta.y, volta.scale_x, volta.scale_y) == (0.5, 0.5, 1.0, 1.0)

    painel._undo_edit()
    painel._undo_edit()
    assert painel._project == antes


def test_o_botao_de_atualizar_tambem_ajusta_a_pose(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip("pb")
    painel._selected_filter_name = REGION_BLUR
    painel._handle_apply_or_update_filter()
    (bloco,) = _filtros(painel)
    assert bloco.has_region and (bloco.scale_x, bloco.scale_y) == (REGION_BLUR_DEFAULT_SCALE, REGION_BLUR_DEFAULT_SCALE)
