"""Contrato do editor: o que a aba Propriedades e as abas de Adicionais mostram por tipo de bloco.

A reorganização visual do editor move e reestiliza esses controles, e nada na suíte
verde enxerga um controle que sumiu: uma seção que deixa de aparecer num tipo de bloco
não levanta exceção. Este arquivo fixa o comportamento **de hoje** — quais das sete
seções cada tipo mostra, e como as três abas de Adicionais reagem a um bloco do próprio
tipo selecionado —, para que a mudança só passe se ele continuar igual.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.domain.project import MediaKind, MediaRef
from videomanager.presentation.qt import strings

# Atributo do ``_ClipPropertiesWidget`` -> nome da seção, na ordem em que aparecem na tela.
_SECOES = {
    "_transform_group": "transformacao",
    "_speed_group": "velocidade",
    "_volume_group": "volume",
    "_animation_group": "animacao",
    "_chromakey_group": "chroma",
    "_blur_group": "desfoque",
    "_transition_group": "transicao",
}

# O que cada tipo mostra hoje. A matriz de ``docs/propostas-visuais/editor-propriedades.png``
# foi lida destas observações e das condições de ``load_clip``.
_ESPERADO = {
    "video com som": {"transformacao", "velocidade", "volume", "animacao", "chroma", "desfoque"},
    "video sem som": {"transformacao", "velocidade", "animacao", "chroma", "desfoque"},
    "imagem": {"transformacao", "animacao", "chroma", "desfoque"},
    "audio": {"velocidade", "volume", "animacao"},
    "texto": {"transformacao", "animacao"},
    "filtro": set(),
    "transicao": {"transicao"},
}


def _midia(nome: str, tipo: MediaKind, duracao: float = 6.0, **extra) -> MediaRef:
    return MediaRef(Path(nome), tipo, duration=duracao, width=1280, height=720, fps=30.0, **extra)


@pytest.fixture
def painel(painel_de_edicao):
    return painel_de_edicao


@pytest.fixture
def blocos(blocos_de_edicao):
    """Um bloco de cada tipo, num projeto só, aplicado ao painel."""
    return blocos_de_edicao


def _secoes_visiveis(painel) -> set[str]:
    propriedades = painel._properties_widget
    return {nome for atributo, nome in _SECOES.items() if getattr(propriedades, atributo).isVisibleTo(propriedades)}


@pytest.mark.parametrize("tipo", list(_ESPERADO))
def test_cada_tipo_de_bloco_mostra_as_secoes_de_hoje(painel, blocos, tipo):
    clip = blocos[tipo]
    painel._timeline.select(clip.clip_id)
    painel._open_properties_tab(clip.clip_id)
    assert _secoes_visiveis(painel) == _ESPERADO[tipo]


def test_as_sete_secoes_existem_e_nenhuma_tipo_mostra_todas():
    # Guarda contra a matriz virar tautologia: as sete seções do app estão todas nela, e
    # cada uma aparece em pelo menos um tipo.
    assert set(_SECOES.values()) == set().union(*_ESPERADO.values())


# Aba de Adicionais que abre sozinha, e texto do botão principal, para um bloco do próprio tipo.
_EDICAO = {
    "texto": (0, "_insert_text_btn", "EDIT_UPDATE_TEXT", "_insert_new_text_btn"),
    "filtro": (1, "_apply_filter_btn", "EDIT_UPDATE_FILTER", "_insert_new_filter_btn"),
    "transicao": (2, "_apply_trans_btn", "EDIT_UPDATE_TRANSITION", "_insert_new_trans_btn"),
}


@pytest.mark.parametrize("tipo", list(_EDICAO))
def test_bloco_selecionado_abre_a_aba_do_tipo_e_vira_atualizar(painel, blocos, tipo):
    aba, principal, texto_do_catalogo, secundario = _EDICAO[tipo]
    painel._sync_extras_controls(blocos[tipo])
    assert painel._extras_tabs.currentIndex() == aba
    assert getattr(painel, principal).text() == getattr(strings, texto_do_catalogo)
    assert getattr(painel, secundario).isVisibleTo(painel._extras_tabs)
    # O segundo botão é só da aba do tipo: nas outras ele some.
    for outro, (_, _, _, botao) in _EDICAO.items():
        if outro != tipo:
            assert not getattr(painel, botao).isVisibleTo(painel._extras_tabs)


def test_sem_bloco_selecionado_os_botoes_voltam_a_inserir(painel, blocos):
    painel._sync_extras_controls(blocos["texto"])
    painel._sync_extras_controls(None)
    assert painel._insert_text_btn.text() == strings.EDIT_INSERT_TEXT
    assert painel._apply_filter_btn.text() == strings.EDIT_APPLY_FILTER
    assert painel._apply_trans_btn.text() == strings.EDIT_INSERT_TRANSITION
    for botao in ("_insert_new_text_btn", "_insert_new_filter_btn", "_insert_new_trans_btn"):
        assert not getattr(painel, botao).isVisibleTo(painel._extras_tabs)


def test_bloco_de_texto_carrega_seus_valores_no_formulario(painel, blocos):
    painel._sync_extras_controls(blocos["texto"])
    assert painel._text_input.text() == "Video Manager"
    assert painel._font_size_spin.value() == 110
