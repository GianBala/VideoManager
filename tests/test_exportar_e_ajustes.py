"""Exportar e Configurações reorganizados: seções em cartões, campos em grade e títulos de grupo.

O contrato de visibilidade do diálogo de exportação (``test_exportar_estados``) diz o que aparece em cada estado;
aqui fica o que é do desenho novo e some sem barulho: a célula que deixa um vão onde o campo saiu, a janela que
não cresce quando entra o aviso do GIF (e o texto dos campos sai cortado), o tamanho estimado fora do rodapé.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QLabel, QSpinBox, QTabWidget

from videomanager.application.capabilities import FFmpegTools
from videomanager.bootstrap import build_desktop_runtime
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings, theme
from videomanager.presentation.qt.arrow_spin import ArrowSpinBox
from videomanager.presentation.qt.settings_dialog import SettingsDialog
from videomanager.presentation.qt.theme import apply as aplicar_tema


def _y(widget, ancestral) -> int:
    return widget.mapTo(ancestral, widget.rect().topLeft()).y()


def _x(widget, ancestral) -> int:
    return widget.mapTo(ancestral, widget.rect().topLeft()).x()


@pytest.fixture
def aberto(dialogo_de_exportacao, desktop_app):
    dialogo_de_exportacao.show()
    for _ in range(5):
        desktop_app.processEvents()
    return dialogo_de_exportacao


# -- Exportar -------------------------------------------------------------------------------------------------

def test_formato_e_codec_dividem_a_linha_e_o_rotulo_fica_em_cima(aberto):
    assert _y(aberto._container_box, aberto) == _y(aberto._video_codec_box, aberto)
    assert _x(aberto._container_box, aberto) < _x(aberto._video_codec_box, aberto)
    assert _y(aberto._aspect_box, aberto) == _y(aberto._canvas_box, aberto)
    # Qualidade ocupa a linha inteira, abaixo dos dois.
    assert _y(aberto._quality_box, aberto) > _y(aberto._container_box, aberto)
    assert aberto._quality_box.width() > aberto._container_box.width()
    for rotulo, campo in ((aberto._container_label, aberto._container_box), (aberto._quality_label, aberto._quality_box),
                          (aberto._rate_label, aberto._rate_box)):
        assert _y(rotulo, aberto) < _y(campo, aberto) and _x(rotulo, aberto) == _x(campo, aberto)


def test_o_tamanho_estimado_esta_no_rodape_junto_da_acao(aberto):
    assert aberto._size_label.parent() is aberto._enqueue_button.parent() is aberto._cancel_button.parent()
    assert _y(aberto._size_label, aberto) > _y(aberto._plan, aberto)
    assert aberto._size_label.text() != "—"


def test_so_audio_nao_deixa_vao_onde_estavam_os_campos_de_video(aberto, desktop_app):
    aberto._audio_only_check.setChecked(True)
    for _ in range(3):
        desktop_app.processEvents()
    # O formato de áudio vem logo abaixo da caixa, só com o espaçamento do cartão: as linhas de vídeo que saíram
    # (células vazias) não deixam o espaçamento delas.
    folga = _y(aberto._audio_format_label, aberto) - (_y(aberto._audio_only_check, aberto) + aberto._audio_only_check.height())
    assert folga == 10, folga


def test_a_janela_cresce_com_o_aviso_do_gif_e_nenhum_campo_sai_espremido(aberto, desktop_app):
    aberto._container_box.setCurrentIndex(aberto._container_box.findData("gif"))
    for _ in range(5):
        desktop_app.processEvents()
    assert aberto._warning_box.isVisibleTo(aberto) and aberto._warning.text() == strings.EXPORT_GIF_NOTE
    assert aberto.height() >= aberto.layout().minimumSize().height()
    # No menor tamanho que o layout aceita, os campos ainda têm a altura que o texto pede: o mínimo de um combo
    # não inclui o preenchimento do estilo, e a janela só cresce até o mínimo do layout.
    aberto.resize(aberto.minimumSizeHint())
    for _ in range(5):
        desktop_app.processEvents()
    for campo in aberto.findChildren(QComboBox):
        if campo.isVisibleTo(aberto):
            assert campo.height() >= campo.sizeHint().height(), campo.currentText()


def test_o_aviso_so_aparece_com_texto(aberto):
    assert not aberto._warning_box.isVisibleTo(aberto) and aberto._warning.text() == ""
    aberto._container_box.setCurrentIndex(aberto._container_box.findData("gif"))
    assert aberto._warning_box.isVisibleTo(aberto)
    aberto._container_box.setCurrentIndex(aberto._container_box.findData("mp4"))
    assert not aberto._warning_box.isVisibleTo(aberto)


def test_o_plano_leva_o_titulo_do_destaque_e_nao_o_repete(aberto):
    assert strings.EXPORT_PLAN_TITLE.lower() not in aberto._plan.text().lower()
    titulos = [rotulo.text() for rotulo in aberto.findChildren(QLabel) if rotulo.property("role") == "callout-title"]
    assert titulos == [strings.EXPORT_PLAN_TITLE.upper()]


# -- Configurações --------------------------------------------------------------------------------------------

class _SemFerramentas:
    def __init__(self, runtime):
        self._runtime = runtime

    def __getattr__(self, nome):
        return getattr(self._runtime, nome)

    def find_tools(self):
        return None


@pytest.fixture
def ajustes(desktop_app, tmp_path):
    janela = SettingsDialog(Settings(), runtime=_SemFerramentas(build_desktop_runtime(audio_enabled=False)),
                             tools=FFmpegTools(tmp_path / "ffmpeg", tmp_path / "ffprobe", "empacotado"))
    janela.show()
    for _ in range(3):
        desktop_app.processEvents()
    yield janela
    janela.deleteLater()


def _titulos(pagina) -> list[str]:
    return [r.text() for r in pagina.findChildren(QLabel) if r.property("role") == "group-heading"]


def test_cada_aba_agrupa_os_campos_sob_titulos(ajustes):
    abas = ajustes.findChild(QTabWidget)
    esperado = {
        0: [strings.SETTINGS_GROUP_DOWNLOADS, strings.SETTINGS_GROUP_LANGUAGE, strings.SETTINGS_GROUP_VIDEO],
        1: [strings.SETTINGS_PALETTE],
        2: [strings.SETTINGS_GROUP_SPEED, strings.SETTINGS_GROUP_COOKIES],
        3: [strings.SETTINGS_GROUP_FILE, strings.SETTINGS_GROUP_SUBS],
    }
    for indice, titulos in esperado.items():
        assert _titulos(abas.widget(indice)) == [t.upper() for t in titulos], indice


def _tem_a_cor(campo, cor: QColor) -> bool:
    imagem = campo.grab().toImage()
    return any(abs(imagem.pixelColor(x, y).red() - cor.red()) < 20 and abs(imagem.pixelColor(x, y).green() - cor.green()) < 20
               and abs(imagem.pixelColor(x, y).blue() - cor.blue()) < 20
               for x in range(imagem.width() - 22, imagem.width() - 2) for y in range(imagem.height()))


def test_os_campos_numericos_trazem_as_setas_e_elas_se_pintam(ajustes, desktop_app):
    campos = (ajustes._concurrent, ajustes._fragments, ajustes._rate)
    assert all(isinstance(c, ArrowSpinBox) for c in campos)
    antes = (desktop_app.palette(), desktop_app.styleSheet(), theme.atual())
    try:
        # Com o estilo do app é que o campo perde as setas; sem ele o Qt as desenha sozinho.
        aplicar_tema(desktop_app, "dark", "atual")
        ajustes.findChild(QTabWidget).setCurrentIndex(2)
        for _ in range(3):
            desktop_app.processEvents()
        cor = QColor(theme.papeis("dark", "atual")["t2"])
        assert _tem_a_cor(ajustes._concurrent, cor)
        simples = QSpinBox()
        simples.show()
        for _ in range(3):
            desktop_app.processEvents()
        assert not _tem_a_cor(simples, cor)  # o que o ``ArrowSpinBox`` existe para resolver
        simples.close()
    finally:
        desktop_app.setPalette(antes[0])
        desktop_app.setStyleSheet(antes[1])
        theme._atual = antes[2]


def test_ok_e_a_acao_primaria_e_as_abas_sao_sublinhadas(ajustes):
    from PySide6.QtWidgets import QDialogButtonBox
    caixa = ajustes.findChild(QDialogButtonBox)
    assert caixa.button(QDialogButtonBox.StandardButton.Ok).property("role") == "primary"
    assert ajustes.findChild(QTabWidget).tabBar().property("role") == "underline"
