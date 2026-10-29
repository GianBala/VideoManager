"""O que se abre e se fecha não fica vivo e escondido.

Menus e diálogos nascem com o painel ou a janela por pai: o Python solta a referência quando a função acaba, mas o Qt
mantém o filho vivo até o pai morrer. Medido no uso repetido do editor: cada clique direito deixava ~18 objetos e cada
abertura das Configurações ~125 widgets (4 MiB), e a ida e volta do tema ia de 1,8 s a 4,7 s depois de 25 aberturas, porque
tudo que está escondido também é reestilizado. Estes testes contam os widgets que sobram depois de N usos.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QDialog



def _widgets_vivos() -> int:
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(3):
        QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return len(QApplication.allWidgets())


def _fechar_o_popup_logo() -> None:
    """``QMenu.exec`` não se substitui no PySide6 (ver o CLAUDE.md): o menu abre de verdade e um temporizador o fecha."""
    def fechar() -> None:
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
    QTimer.singleShot(40, fechar)


def test_cada_clique_direito_no_editor_nao_deixa_um_menu_vivo(tema_do_app, painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    painel.resize(1200, 900)
    painel.show()
    QApplication.processEvents()

    def usar_menus() -> int:
        usos = 0
        for bloco in list(blocos_de_edicao.values())[:3]:
            _fechar_o_popup_logo()
            painel._show_menu("clip", 0, bloco.clip_id, QPoint(5, 5))
            usos += 1
        _fechar_o_popup_logo()
        painel._show_save_menu(QPoint(1, 1))
        _fechar_o_popup_logo()
        painel._show_media_context_menu(QPoint(1, 1))
        return usos + 2

    usar_menus()
    antes = _widgets_vivos()
    menus = sum(usar_menus() for _ in range(4))
    depois = _widgets_vivos()
    assert depois - antes <= 0, f"{depois - antes} widgets a mais depois de {menus} menus"


def test_a_janela_de_exportar_tambem_e_apagada_ao_fechar(tema_do_app, painel_de_edicao, blocos_de_edicao, monkeypatch):
    import videomanager.presentation.qt.panels.edit_panel as modulo

    class Falso(QDialog):
        created_job, chosen_canvas, chosen_rate = None, None, None

        def __init__(self, *args, parent=None, **kwargs):
            super().__init__(parent)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(modulo, "ExportDialog", Falso)
    painel_de_edicao._open_export_dialog()
    antes = _widgets_vivos()
    for _ in range(6):
        painel_de_edicao._open_export_dialog()
    assert _widgets_vivos() - antes <= 0

