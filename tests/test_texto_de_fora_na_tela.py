"""Título e nome de arquivo vêm de fora (do site, do disco, do que o usuário digitou) e aparecem como vieram.

Um ``QLabel`` sem formato definido usa ``AutoText``: o texto com uma tag conhecida é lido como HTML, e "Aula <b>1</b>" saía em
negrito, "x <font color=red>…" perdia as marcas e "<br>" quebrava a linha e mudava a altura do cartão. Nenhum erro, nenhuma
exceção: só um título diferente do que o site mandou.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from videomanager.domain.formats import FormatMatrix, MediaInfo
from videomanager.domain.project import Clip, MediaKind, MediaRef

TITULO = "Aula <b>especial</b><br>parte <i>2</i>"
pytestmark = pytest.mark.usefixtures("desktop_app")


def _puro(texto: str, fonte_de: QLabel) -> QLabel:
    """O mesmo texto num rótulo de texto puro: o que o cartão deve medir."""
    referencia = QLabel()
    referencia.setTextFormat(Qt.TextFormat.PlainText)
    referencia.setFont(fonte_de.font())
    referencia.setWordWrap(fonte_de.wordWrap())
    referencia.setText(texto)
    return referencia


def test_o_titulo_e_o_autor_da_midia_aparecem_como_vieram():
    from videomanager.presentation.qt.panels.media_card import MediaCard

    cartao = MediaCard(runtime=object())
    cartao.set_media(MediaInfo(url="u", title=TITULO, matrix=FormatMatrix(), uploader="Canal <b>X</b><br>Y", extractor="site"))
    for rotulo, texto in ((cartao._title, TITULO), (cartao._meta, "Canal <b>X</b><br>Y · site")):
        assert rotulo.textFormat() is Qt.TextFormat.PlainText
        assert rotulo.text() == texto
        assert rotulo.sizeHint() == _puro(texto, rotulo).sizeHint(), "o rótulo mede o texto como HTML"
    cartao.deleteLater()


def test_o_nome_do_arquivo_e_o_lendo_dos_metadados_aparecem_como_vieram():
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime
    from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel

    painel = MetadataPanel(Preferences(), lambda: None, runtime=build_desktop_runtime(audio_enabled=False))
    try:
        assert painel._file_name.textFormat() is Qt.TextFormat.PlainText
        painel._loading = Path("/musicas/a<b>x<br>c.mp3")
        painel._refresh()
        assert painel._info.textFormat() is Qt.TextFormat.PlainText
        assert "a<b>x<br>c.mp3" in painel._info.text()
        assert painel._info.sizeHint() == _puro(painel._info.text(), painel._info).sizeHint()
    finally:
        painel._loading = None
        painel.shutdown()
        painel.deleteLater()


def test_o_nome_do_bloco_nas_propriedades_aparece_como_veio():
    from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget

    widget = _ClipPropertiesWidget()
    bloco = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=3.0), 0.0, 3.0, overlay_type="text",
                 text_content="x <b>y</b><br>z")
    widget.load_clip(bloco, 1920, 1080)
    assert widget._title_lbl.textFormat() is Qt.TextFormat.PlainText
    assert "<b>y</b><br>z" in widget._title_lbl.text()
    assert widget._title_lbl.sizeHint() == _puro(widget._title_lbl.text(), widget._title_lbl).sizeHint()
    widget.deleteLater()
