"""O texto de exemplo de um campo vazio aparece inteiro.

O Qt corta o texto de exemplo (``placeholderText``) no fim do campo e põe reticências: "Opcional: caminho para coo…" era o
que o campo do arquivo de cookies mostrava em português, e nenhum erro dizia isso. O ``validate_language --cortes`` só aponta
o que corta em inglês e não corta em português, então um corte nos dois idiomas passava. Aqui a medida é a do texto contra a
largura útil do campo, em cada guia das Configurações e nos dois idiomas.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QApplication, QLineEdit, QStyle, QStyleOptionFrame, QTabWidget)

from test_exportar_e_ajustes import _SemFerramentas
from videomanager.application.capabilities import FFmpegTools
from videomanager.bootstrap import build_desktop_runtime
from videomanager.domain import i18n
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.settings_dialog import SettingsDialog


def _largura_util(campo: QLineEdit) -> int:
    opcao = QStyleOptionFrame()
    opcao.initFrom(campo)
    opcao.rect = campo.rect()
    opcao.lineWidth = 1
    return campo.style().subElementRect(QStyle.SubElement.SE_LineEditContents, opcao, campo).width()


def _assentar() -> None:
    for _ in range(6):
        QApplication.processEvents()


@pytest.mark.parametrize("idioma", [i18n.PORTUGUESE, i18n.ENGLISH])
def test_o_texto_de_exemplo_dos_campos_das_configuracoes_cabe_inteiro(tema_do_app, idioma):
    apply_language(idioma)
    janela = SettingsDialog(Settings(), runtime=_SemFerramentas(build_desktop_runtime(audio_enabled=False)),
                            tools=FFmpegTools(Path("/opt/vm/ffmpeg"), Path("/opt/vm/ffprobe"), "empacotado"))
    try:
        janela.show()
        _assentar()
        guias = janela.findChild(QTabWidget)
        cortados, conferidos = [], 0
        for indice in range(guias.count()):
            guias.setCurrentIndex(indice)
            _assentar()
            for campo in guias.widget(indice).findChildren(QLineEdit):
                if not campo.isVisibleTo(janela) or campo.text() or not campo.placeholderText():
                    continue
                conferidos += 1
                largura = QFontMetrics(campo.font()).horizontalAdvance(campo.placeholderText())
                if largura > _largura_util(campo):
                    cortados.append(f"{campo.placeholderText()!r}: {largura} px num campo de {_largura_util(campo)} px")
        assert conferidos >= 1
        assert not cortados, cortados
    finally:
        janela.close()
        janela.deleteLater()
        apply_language(i18n.PORTUGUESE)
