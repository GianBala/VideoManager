"""Colunas de Mídia e de Adicionais: ícones desenhados no lugar dos símbolos de texto.

O ``+`` e o ``✓`` que faziam parte do texto dos botões e os emojis das opções de filtro e transição viraram
ícones desenhados, e o catálogo perdeu esses prefixos. O que isso pode errar sem exceção: o botão que mostra o
ícone de "inserir" quando devia mostrar o de "atualizar", a opção marcada que não muda de cor, o ícone que não
acompanha a troca de tema, o prefixo que volta ao catálogo em um dos idiomas.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMessageBox

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings, strings_en, theme
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.theme import apply as aplicar_tema

_BOTOES = {
    "texto": ("_insert_text_btn", "_insert_new_text_btn", "EDIT_INSERT_TEXT", "EDIT_UPDATE_TEXT"),
    "filtro": ("_apply_filter_btn", "_insert_new_filter_btn", "EDIT_APPLY_FILTER", "EDIT_UPDATE_FILTER"),
    "transicao": ("_apply_trans_btn", "_insert_new_trans_btn", "EDIT_INSERT_TRANSITION", "EDIT_UPDATE_TRANSITION"),
}


@pytest.fixture
def painel(desktop_app, monkeypatch):
    antes = (desktop_app.palette(), desktop_app.styleSheet(), theme.atual())
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    instancia = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    yield instancia
    instancia.shutdown()
    desktop_app.setPalette(antes[0])
    desktop_app.setStyleSheet(antes[1])
    theme._atual = antes[2]


@pytest.fixture
def blocos(painel):
    video = MediaRef(Path("a.mp4"), MediaKind.VIDEO, duration=6.0, width=1280, height=720, fps=30.0, has_audio=True)
    esquerda, direita = Clip(video, 0.0, 6.0), Clip(video, 6.0, 6.0)
    texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=5.0), 0.5, 5.0, overlay_type="text",
                 text_content="Olá")
    filtro = Clip(MediaRef(Path("Filtro_x"), MediaKind.IMAGE, duration=3.0), 6.0, 6.0, overlay_type="filter",
                  filter_name="vinheta")
    transicao = Clip(MediaRef(Path("Transicao"), MediaKind.IMAGE, duration=1.0), 5.5, 1.0, overlay_type="transition",
                     transition_name="dissolve", transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id)
    painel._apply(Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(texto, filtro), name="Adicionais 1"),
                                  Track(TrackKind.VIDEO, clips=(esquerda, transicao, direita), name="Vídeo 1")),
                          width=1280, height=720, fps=30.0))
    return {"texto": texto, "filtro": filtro, "transicao": transicao}


def _pixmap(icone: QIcon, estado: QIcon.State = QIcon.State.Off):
    return icone.pixmap(18, 18, QIcon.Mode.Normal, estado).toImage()


def test_o_catalogo_nao_traz_mais_o_simbolo_no_texto_dos_botoes():
    for nome in (*(n for _, _, a, b in _BOTOES.values() for n in (a, b)), "EDIT_INSERT_NEW_TEXT", "EDIT_INSERT_NEW_FILTER",
                 "EDIT_INSERT_NEW_TRANSITION", "EDIT_IMPORT_BUTTON", "EDIT_CLEAR_UNUSED_BUTTON"):
        for catalogo in (strings, strings_en):
            texto = getattr(catalogo, nome)
            assert texto == texto.lstrip("+✓🧹 "), (nome, texto)


def test_as_opcoes_de_filtro_e_transicao_so_levam_o_nome_e_o_icone_muda_com_a_marca(painel):
    for botoes, tabela in ((painel._filter_buttons, strings.EDIT_FILTERS), (painel._trans_buttons, strings.EDIT_TRANSITIONS)):
        assert [b.text() for b in botoes] == [nome for _emoji, nome in tabela.values()]
        for botao in botoes:
            assert not botao.icon().isNull()
            assert _pixmap(botao.icon(), QIcon.State.Off) != _pixmap(botao.icon(), QIcon.State.On)
    # Cada opção tem o desenho dela: nenhuma repete o ícone de outra.
    for botoes in (painel._filter_buttons, painel._trans_buttons):
        imagens = [_pixmap(b.icon(), QIcon.State.On).constBits().tobytes() for b in botoes]
        assert len(set(imagens)) == len(imagens)


@pytest.mark.parametrize("tipo", list(_BOTOES))
def test_o_botao_principal_troca_de_ícone_com_o_texto_quando_o_bloco_e_do_tipo(painel, blocos, tipo):
    principal, secundario, inserir, atualizar = _BOTOES[tipo]
    botao = getattr(painel, principal)
    painel._sync_extras_controls(None)
    assert botao.text() == getattr(strings, inserir) and not botao.icon().isNull()
    inserindo = _pixmap(botao.icon())
    painel._sync_extras_controls(blocos[tipo])
    assert botao.text() == getattr(strings, atualizar)
    assert _pixmap(botao.icon()) != inserindo  # o "+" virou o "✓"
    assert getattr(painel, secundario).isVisibleTo(painel._extras_tabs) and not getattr(painel, secundario).icon().isNull()
    painel._sync_extras_controls(None)
    assert _pixmap(botao.icon()) == inserindo


def test_as_abas_trazem_icone_e_a_de_propriedades_tambem(painel, blocos):
    abas = painel._extras_tabs
    assert all(not abas.tabIcon(i).isNull() for i in range(abas.count()))
    imagens = {abas.tabIcon(i).pixmap(16, 16).toImage().constBits().tobytes() for i in range(abas.count())}
    assert len(imagens) == abas.count()
    painel._timeline.select(blocos["texto"].clip_id)
    painel._open_properties_tab(blocos["texto"].clip_id)
    indice = abas.indexOf(painel._properties_widget)
    assert indice == 3 and not abas.tabIcon(indice).isNull()


def test_os_icones_seguem_a_troca_de_paleta(painel, desktop_app):
    # O botão principal leva a cor do texto sobre o preenchimento, que é a mesma nos dois modos: compara-se o secundário.
    opcao, principal, aba = painel._filter_buttons[0], painel._insert_new_text_btn, 0
    antes = (_pixmap(opcao.icon(), QIcon.State.On), _pixmap(principal.icon()), painel._extras_tabs.tabIcon(aba).pixmap(16, 16).toImage())
    aplicar_tema(desktop_app, "light", "mare")
    depois = (_pixmap(opcao.icon(), QIcon.State.On), _pixmap(principal.icon()), painel._extras_tabs.tabIcon(aba).pixmap(16, 16).toImage())
    assert all(a != d for a, d in zip(antes, depois))


def test_a_coluna_de_midia_tem_a_acao_em_largura_inteira_e_a_saida_discreta(painel):
    assert painel._insert.property("role") != "ghost" and painel._clear_unused_btn.property("role") == "ghost"
    assert painel._insert.width() >= painel._media_list.width() - 2 or not painel._insert.isVisible()
    assert painel._pool_count_label.property("role") == "chip"
    assert not painel._import.icon().isNull() and not painel._insert.icon().isNull()
