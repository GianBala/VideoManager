"""Exportar e Configurações como no protótipo: pastilhas no resumo, rótulos sem dois-pontos, ícones nos destaques, "Cancelar" à
esquerda de "OK", o modo do tema em dois botões segmentados, o visto no cartão da paleta e o ffmpeg num destaque.

O que uma troca de desenho perde em silêncio: o valor que o controle escondido guarda e deixa de seguir o botão, o cartão de
paleta de altura menor que o texto (o nome sobre a miniatura), a ordem dos botões que muda de um sistema para outro.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFrame, QLabel, QStyle, QTabWidget

from test_exportar_e_ajustes import _SemFerramentas
from videomanager.application.capabilities import FFmpegTools
from videomanager.bootstrap import build_desktop_runtime
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import fonts, strings, theme
from videomanager.presentation.qt.panels.segmented import SegmentButton
from videomanager.presentation.qt.settings_dialog import SettingsDialog
from videomanager.presentation.qt.theme import EstiloDaAplicacao


@pytest.fixture
def estilo_do_app(desktop_app):
    """O estilo do aplicativo (``EstiloDaAplicacao``, que o ``build_app`` instala) enquanto o teste dura."""
    desktop_app.setStyle(EstiloDaAplicacao())
    yield desktop_app
    desktop_app.setStyle("Fusion")


@pytest.fixture
def exportar(tema_do_app, dialogo_de_exportacao):
    dialogo_de_exportacao.show()
    for _ in range(5):
        QApplication.processEvents()
    return dialogo_de_exportacao


@pytest.fixture
def ajustes(tema_do_app, estilo_do_app):
    janela = SettingsDialog(Settings(), runtime=_SemFerramentas(build_desktop_runtime(audio_enabled=False)),
                            tools=FFmpegTools(Path("/opt/vm/ffmpeg"), Path("/opt/vm/ffprobe"), "empacotado"))
    janela.show()
    for _ in range(4):
        QApplication.processEvents()
    yield janela
    janela.deleteLater()


# -- Exportar -------------------------------------------------------------------------------------------------

def test_o_resumo_sao_tres_pastilhas_com_o_valor_da_duracao_em_negrito(exportar):
    # (a extensão ao lado do nome do arquivo também é uma pastilha, e não é do resumo)
    pastilhas = [r for r in exportar.findChildren(QLabel) if r.property("role") == "chip" and r is not exportar._ext_label]
    textos = [p.text() for p in pastilhas]
    assert len(pastilhas) == 3
    assert textos[0].startswith("Duração total <b>") and textos[0].endswith("</b>")
    assert textos[1] == strings.EXPORT_SUMMARY_TRACKS.format(tracks=len(exportar._project.tracks))
    assert textos[2] == strings.EXPORT_SUMMARY_CLIPS.format(clips=len(exportar._project.clips))
    assert all(p.textFormat() == Qt.TextFormat.RichText for p in pastilhas)
    # Lado a lado, na mesma linha.
    assert len({p.mapTo(exportar, p.rect().center()).y() for p in pastilhas}) == 1


def test_os_rotulos_dos_campos_ficam_sem_dois_pontos(exportar):
    rotulos = [r.text() for r in exportar.findChildren(QLabel) if r.text()]
    assert not [t for t in rotulos if t.rstrip().endswith(":")], rotulos
    assert strings.EXPORT_ASPECT in rotulos and strings.EDIT_CANVAS in rotulos and strings.EDIT_CANVAS_RATE in rotulos


def test_o_destaque_do_plano_tem_o_icone_de_informacao_e_o_aviso_o_de_atencao(exportar):
    cores = theme.papeis("dark", "grafite")
    plano = exportar._plan.parentWidget()
    assert plano.property("role") == "callout"
    icone = next(f for f in plano.findChildren(QLabel) if f.pixmap() is not None and not f.pixmap().isNull())
    assert (icone.width(), icone.height()) == (20, 20)
    imagem = icone.pixmap().toImage()
    acento = QColor(cores["accent"])
    assert any(abs(imagem.pixelColor(x, y).red() - acento.red()) < 12 and imagem.pixelColor(x, y).alpha() > 200
               for x in range(20) for y in range(20)), "o ícone de informação leva o acento"
    # O aviso (GIF) leva o ícone no âmbar.
    exportar._container_box.setCurrentIndex(exportar._container_box.findData("gif"))
    QApplication.processEvents()
    aviso = exportar._warning.parentWidget()
    assert aviso.property("role") == "callout-warn" and aviso.isVisibleTo(exportar)
    icone = next(f for f in aviso.findChildren(QLabel) if f.pixmap() is not None and not f.pixmap().isNull())
    alerta = QColor(cores["warn"])
    imagem = icone.pixmap().toImage()
    assert any(abs(imagem.pixelColor(x, y).red() - alerta.red()) < 12 and imagem.pixelColor(x, y).alpha() > 200
               for x in range(20) for y in range(20)), "o ícone de aviso leva o âmbar"


def test_o_rodape_tem_cancelar_sem_fundo_e_a_acao_com_o_mais(exportar):
    assert exportar._cancel_button.property("role") == "ghost"
    assert exportar._enqueue_button.property("role") == "primary" and not exportar._enqueue_button.icon().isNull()
    assert (exportar._cancel_button.mapTo(exportar, exportar._cancel_button.rect().topLeft()).x()
            < exportar._enqueue_button.mapTo(exportar, exportar._enqueue_button.rect().topLeft()).x())


# -- Configurações --------------------------------------------------------------------------------------------

def test_cancelar_fica_a_esquerda_de_ok_e_os_dois_tem_38_px_em_qualquer_caixa_de_botoes(ajustes, desktop_app):
    caixa = ajustes.findChild(QDialogButtonBox)
    ok, cancelar = (caixa.button(QDialogButtonBox.StandardButton.Ok), caixa.button(QDialogButtonBox.StandardButton.Cancel))
    assert cancelar.x() < ok.x()
    assert ok.height() == cancelar.height() == 38 and ok.property("role") == "primary"
    # É a regra do estilo, e não desta janela: qualquer caixa de botões vem na mesma ordem.
    assert desktop_app.style().styleHint(QStyle.StyleHint.SH_DialogButtonLayout) == QDialogButtonBox.ButtonLayout.GnomeLayout.value
    outra = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    outra.show()
    QApplication.processEvents()
    assert (outra.button(QDialogButtonBox.StandardButton.Cancel).x() < outra.button(QDialogButtonBox.StandardButton.Ok).x())
    outra.deleteLater()


def test_o_modo_do_tema_e_um_controle_segmentado_ligado_a_lista_escondida(ajustes):
    abas = ajustes.findChild(QTabWidget)
    pagina = abas.widget(1)
    assert pagina.isAncestorOf(ajustes._theme) and ajustes._theme.isHidden()
    botoes = pagina.findChildren(SegmentButton)
    assert [b.text() for b in botoes] == [strings.THEME_DARK, strings.THEME_LIGHT]
    escuro, claro = botoes
    assert escuro.isChecked() and not claro.isChecked() and ajustes._theme.currentData() == "dark"
    # Clicar no botão manda na lista (que o resultado e a miniatura das paletas leem)…
    QTest.mouseClick(claro, Qt.MouseButton.LeftButton)
    assert ajustes._theme.currentData() == "light" and ajustes.result_settings().theme == "light"
    assert all(c.miniatura._modo == "light" for c in ajustes._palette_picker._cartoes.values())
    # … e trocar pela lista marca o botão certo.
    ajustes._theme.setCurrentIndex(ajustes._theme.findData("dark"))
    assert escuro.isChecked() and not claro.isChecked()


def test_o_visto_marca_so_o_cartao_da_paleta_escolhida_e_acompanha_a_troca(ajustes):
    cores = theme.papeis("dark", "grafite")
    acento = QColor(cores["accent"])
    cartoes = ajustes._palette_picker._cartoes

    def com_visto(cartao) -> bool:
        imagem = cartao.miniatura.grab().toImage()
        # O disco de 21 px no acento: um ponto fora do visto (no meio do disco, acima dele) já é o acento.
        ponto = imagem.pixelColor(imagem.width() - 14, 6)
        return abs(ponto.red() - acento.red()) + abs(ponto.green() - acento.green()) + abs(ponto.blue() - acento.blue()) < 40

    marcado = ajustes._palette_picker.palette()
    assert [n for n, c in cartoes.items() if com_visto(c)] == [marcado]
    outro = next(n for n in cartoes if n != marcado)
    cartoes[outro].click()
    QApplication.processEvents()
    assert [n for n, c in cartoes.items() if com_visto(c)] == [outro]


def test_o_cartao_de_paleta_guarda_duas_linhas_para_a_frase_e_o_nome_nao_cobre_a_miniatura(ajustes):
    ajustes.findChild(QTabWidget).setCurrentIndex(1)
    QApplication.processEvents()
    for cartao in ajustes._palette_picker._cartoes.values():
        titulo = cartao.layout().itemAt(1).widget()
        frase = cartao.layout().itemAt(2).widget()
        assert titulo.geometry().top() >= cartao.miniatura.geometry().bottom()
        assert frase.geometry().top() >= titulo.geometry().bottom() - 2
        assert frase.height() >= 2 * frase.fontMetrics().lineSpacing()
        assert frase.geometry().bottom() <= cartao.height()


def test_o_ffmpeg_e_um_destaque_com_a_origem_numa_pastilha_e_o_caminho_em_mono(ajustes):
    destaque = ajustes._ffmpeg_source.parentWidget()
    assert destaque.property("role") == "callout" and ajustes._ffmpeg_path.parentWidget() is destaque
    assert ajustes._ffmpeg_source.property("role") == "chip" and ajustes._ffmpeg_source.property("tone") == "accent"
    assert ajustes._ffmpeg_path.font().family() == fonts.mono(12).family()
    assert ajustes._ffmpeg_source.mapTo(destaque, ajustes._ffmpeg_source.rect().topLeft()).x() < \
        ajustes._ffmpeg_note.mapTo(destaque, ajustes._ffmpeg_note.rect().topLeft()).x()


def test_as_paginas_tem_margem_de_24_e_os_campos_de_texto_36_mais_a_borda(ajustes):
    margens = ajustes.layout().contentsMargins()
    assert (margens.left(), margens.right()) == (24, 24)
    for campo in (ajustes._dest, ajustes._language, ajustes._encoder):
        assert campo.property("role") == "field" and campo.height() == 38
    assert ajustes.findChild(QTabWidget).tabBar().property("role") == "underline"
    assert not [f for f in ajustes.findChildren(QFrame) if f.property("role") == "callout" and f.height() < 40]
