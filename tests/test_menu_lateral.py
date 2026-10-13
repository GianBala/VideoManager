"""Menu lateral: a navegação entre as abas, que antes era uma barra de abas no topo.

``MainWindow._tabs`` virou um ``QStackedWidget`` com a API de um ``QTabWidget``, e os testes e os
scripts de validação continuam escolhendo página por ``setCurrentIndex``. O que a suíte antiga não
via, e este arquivo fixa, é a outra metade: o item do menu acompanha a página (e vice-versa), o
texto troca de idioma sem perder a seleção, e os ícones seguem a paleta.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from test_theme_contrast import contraste
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import paletas, strings, theme
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.main_window import (_TAB_CONVERT, _TAB_DOWNLOAD, _TAB_EDIT, _TAB_METADATA,
                                                      MainWindow)
from videomanager.presentation.qt.nav_rail import LARGURA
from videomanager.presentation.qt.settings_dialog import SettingsDialog
from videomanager.presentation.qt.theme import apply as aplicar_tema


@pytest.fixture
def janela(desktop_app, monkeypatch):
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    antes = (desktop_app.palette(), desktop_app.styleSheet(), theme.atual())
    w = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                   downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    w.show()
    for _ in range(5):
        desktop_app.processEvents()
    yield w
    w._edit._project_actions.confirm_replace = lambda: True
    w._edit.shutdown()
    w.close()
    desktop_app.setPalette(antes[0])
    desktop_app.setStyleSheet(antes[1])
    theme._atual = antes[2]


def _textos(menu) -> list[str]:
    return [menu.text(i) for i in range(menu.count())]


def test_o_menu_lista_as_abas_na_ordem_dos_indices(janela):
    menu = janela._tabs.tabBar()
    assert (_TAB_DOWNLOAD, _TAB_CONVERT, _TAB_EDIT, _TAB_METADATA) == (0, 1, 2, 3)
    assert _textos(menu) == [strings.TAB_DOWNLOAD, strings.TAB_CONVERT, strings.TAB_EDIT, strings.TAB_METADATA]
    assert janela._tabs.count() == 4


def test_clicar_no_item_troca_a_pagina(janela):
    for indice in (_TAB_EDIT, _TAB_METADATA, _TAB_CONVERT, _TAB_DOWNLOAD):
        janela._tabs.tabBar()._itens[indice].click()
        assert janela._tabs.currentIndex() == indice
        assert janela._tabs.currentWidget() is janela._tabs.widget(indice)


def test_trocar_a_pagina_por_codigo_marca_o_item(janela):
    # É o caminho de "Abrir no editor", de atalhos e de todos os testes: o menu não pode ficar para trás.
    menu = janela._tabs.tabBar()
    for indice in (_TAB_EDIT, _TAB_METADATA, _TAB_DOWNLOAD):
        janela._tabs.setCurrentIndex(indice)
        assert menu.current() == indice
        assert [item.isChecked() for item in menu._itens] == [i == indice for i in range(4)]


def test_ajustes_abre_o_dialogo_sem_trocar_de_aba(janela, monkeypatch):
    abertos = []
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: abertos.append(self) or SettingsDialog.DialogCode.Rejected)
    janela._tabs.setCurrentIndex(_TAB_CONVERT)
    janela._nav_settings.click()
    assert len(abertos) == 1
    assert janela._tabs.currentIndex() == _TAB_CONVERT
    assert not janela._nav_settings.isChecked()


def test_a_troca_de_idioma_retraduz_o_menu_e_mantem_a_selecao(janela):
    menu = janela._tabs.tabBar()
    janela._tabs.setCurrentIndex(_TAB_EDIT)
    apply_language("en")
    assert _textos(menu) == ["Download", "Convert", "Edit", "Metadata"]
    assert janela._nav_settings.text() == strings.NAV_SETTINGS == "Settings"
    assert menu.current() == _TAB_EDIT and janela._tabs.currentIndex() == _TAB_EDIT
    assert menu._itens[_TAB_EDIT].accessibleName() == "Edit"


@pytest.mark.parametrize("idioma", ["pt-BR", "en"])
def test_o_texto_de_cada_item_cabe_na_largura_do_menu(janela, desktop_app, idioma):
    # O menu tem largura fixa: um rótulo mais largo que o item seria cortado nas duas pontas, e "Metadados" é o
    # maior. As bordas (3 px à esquerda, 1 px à direita) existem sempre, então entram na conta.
    apply_language(idioma)
    for _ in range(3):
        desktop_app.processEvents()
    menu = janela._tabs.tabBar()
    for item in (*menu._itens, *menu._acoes):
        assert item.fontMetrics().horizontalAdvance(item.text()) + 4 <= item.width(), item.text()


def _cor_do_traco(item, estado) -> str:
    """Cor do pixel mais opaco do ícone: o traço, sem o anti-serrilhado das bordas."""
    imagem: QImage = item.icon().pixmap(22, 22, item.icon().Mode.Normal, estado).toImage()
    melhor = max(((imagem.pixelColor(x, y).alpha(), x, y) for x in range(22) for y in range(22)))
    return imagem.pixelColor(melhor[1], melhor[2]).name()


def test_os_icones_seguem_a_paleta(janela, desktop_app):
    item = janela._tabs.tabBar()._itens[_TAB_EDIT]
    for modo, paleta in (("dark", "estudio"), ("light", "mare"), ("dark", "atual")):
        aplicar_tema(desktop_app, modo, paleta)
        cores = theme.papeis(modo, paleta)
        assert _cor_do_traco(item, item.icon().State.Off) == cores["t2"].lower()
        assert _cor_do_traco(item, item.icon().State.On) == cores["accent"].lower()


def test_o_menu_cabe_no_tamanho_padrao_sem_roubar_largura_do_conteudo(janela):
    # O conteúdo sempre teve 1180 px; o menu entra por fora, senão o editor (que pede 1191) rolaria 76 px a mais.
    assert janela.width() == 1180 + LARGURA
    assert janela._tabs.tabBar().width() == LARGURA


def test_tab_chega_ao_menu_e_as_setas_trocam_de_item(janela, desktop_app):
    menu = janela._tabs.tabBar()
    assert not menu.hasFocus()
    QTest.keyClick(desktop_app.focusWidget(), Qt.Key.Key_Tab)
    desktop_app.processEvents()
    assert menu.hasFocus()
    foco = desktop_app.focusWidget()
    assert foco is menu._itens[_TAB_DOWNLOAD]
    QTest.keyClick(foco, Qt.Key.Key_Down)
    desktop_app.processEvents()
    assert janela._tabs.currentIndex() == _TAB_CONVERT
    assert desktop_app.focusWidget() is menu._itens[_TAB_CONVERT]


@pytest.mark.parametrize("nome", paletas.nomes())
@pytest.mark.parametrize("modo", ["dark", "light"])
def test_o_foco_do_teclado_se_ve_no_item_marcado_e_no_desmarcado(janela, desktop_app, modo, nome):
    # O foco é a única pista de onde o teclado está; num item de fundo transparente ele só existe se a borda mudar.
    aplicar_tema(desktop_app, modo, nome)
    janela.activateWindow()
    menu = janela._tabs.tabBar()
    fracos = []
    for indice in (_TAB_DOWNLOAD, _TAB_METADATA):  # um marcado e um que não é
        janela._tabs.setCurrentIndex(_TAB_DOWNLOAD)
        item = menu._itens[indice]
        janela._nav_settings.setFocus()
        for _ in range(3):
            desktop_app.processEvents()
        # Pelo menu, e não pelo item: o fundo do item é transparente, e a captura dele sairia sem a cor do menu.
        antes = menu.grab(item.geometry()).toImage()
        item.setFocus(Qt.FocusReason.TabFocusReason)
        for _ in range(3):
            desktop_app.processEvents()
        assert item.hasFocus(), indice
        depois = menu.grab(item.geometry()).toImage()
        melhor = max((contraste(antes.pixel(x, y), depois.pixel(x, y)) for y in range(antes.height())
                      for x in range(antes.width()) if antes.pixel(x, y) != depois.pixel(x, y)), default=1.0)
        if melhor < 3.0:
            fracos.append(f"{item.text()}: {melhor:.2f}:1")
    assert not fracos, fracos


def test_tab_visita_so_o_item_marcado_e_depois_tarefas_e_ajustes(janela, desktop_app):
    # Como num grupo de rádio: setas dentro do menu, Tab para fora dele. Quatro paradas para chegar ao conteúdo
    # seriam quatro Tab a mais em toda volta pela janela.
    menu = janela._tabs.tabBar()
    janela._tabs.setCurrentIndex(_TAB_EDIT)
    QTest.keyClick(desktop_app.focusWidget(), Qt.Key.Key_Tab)
    desktop_app.processEvents()
    assert desktop_app.focusWidget() is menu._itens[_TAB_EDIT]
    for esperado in (janela._nav_tasks, janela._nav_settings):
        QTest.keyClick(desktop_app.focusWidget(), Qt.Key.Key_Tab)
        desktop_app.processEvents()
        assert desktop_app.focusWidget() is esperado
