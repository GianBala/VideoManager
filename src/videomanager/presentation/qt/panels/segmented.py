"""Botão de um controle segmentado: um ``QRadioButton`` com desenho de pílula, com ícone opcional.

Os modos das abas Download e Converter continuam sendo botões de rádio irmãos — o mesmo grupo exclusivo, os mesmos
sinais, as setas do teclado trocando de modo. Só o desenho muda: sem o círculo, com o ícone e o texto centrados e o
marcado destacado no tom do acento, com um anel fino. O QSS não faz isso (``::indicator`` com largura zero deixa o
círculo desenhado e o texto cortado), então o botão se pinta.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QRadioButton, QSizePolicy, QWidget

from videomanager.presentation.qt import fonts, theme

_PAD_H = 14
_ALTURA = 29
# A versão estreita (atalhos de rotação da aba Propriedades): células de 22 px que dividem a largura por igual.
_ALTURA_COMPACTA = 22
_ICONE = 15
_ENTRE_ICONE_E_TEXTO = 7


def segmented(buttons: list[SegmentButton], parent: QWidget | None = None, *, compact: bool = False) -> QFrame:
    """O contêiner do controle: uma pílula de fundo elevado com 3 px de recuo em volta dos botões."""
    quadro = QFrame(parent)
    quadro.setProperty("role", "segments")
    if compact:
        quadro.setProperty("compact", "true")
    linha = QHBoxLayout(quadro)
    linha.setContentsMargins(3, 3, 3, 3)
    linha.setSpacing(2)
    for botao in buttons:
        # Com estica, o ``QHBoxLayout`` reparte a largura por igual e ignora a dica de cada botão ("0°" e "270°").
        linha.addWidget(botao, 1 if compact else 0)
    return quadro


class SegmentButton(QRadioButton):
    def __init__(self, parent: QWidget | None = None, *, glyph: Callable | None = None, compact: bool = False) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._compact = compact
        if compact:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def _fonte(self) -> QFont:
        fonte = fonts.resized(self.font())
        fonte.setWeight(QFont.Weight.Medium)
        return fonte

    def _largura_do_conteudo(self) -> int:
        texto = QFontMetrics(self._fonte()).horizontalAdvance(self.text())
        return texto + (_ICONE + _ENTRE_ICONE_E_TEXTO if self._glyph is not None else 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._compact:
            return QSize(self._largura_do_conteudo() + 8, _ALTURA_COMPACTA)
        return QSize(self._largura_do_conteudo() + 2 * _PAD_H, _ALTURA)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        cores = theme.papeis(*theme.atual())
        derivadas = theme.derivadas(cores)
        foco = theme.palette(*theme.atual())["focus"]
        marcado = self.isChecked()
        passando = self.underMouse() and self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.5)
        caixa = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        if marcado:
            p.setBrush(QColor(derivadas["seg_on"]))
            p.setPen(QPen(QColor(derivadas["seg_ring"]), 1))
        else:
            p.setBrush(QColor(cores["raised2"]) if passando else Qt.BrushStyle.NoBrush)
            p.setPen(Qt.PenStyle.NoPen)
        if self.hasFocus():
            p.setPen(QPen(QColor(foco), 1.5))
        p.drawRoundedRect(caixa, 8, 8)
        cor = cores["accent"] if marcado else cores["text"] if passando else cores["t2"]
        fonte = self._fonte()
        p.setFont(fonte)
        p.setPen(QColor(cor))
        # Ícone e texto formam um bloco só, centrado no botão.
        largura = self._largura_do_conteudo()
        x = (self.width() - largura) // 2
        if self._glyph is not None:
            self._glyph(cor, _ICONE).paint(p, QRect(x, (self.height() - _ICONE) // 2, _ICONE, _ICONE))
            x += _ICONE + _ENTRE_ICONE_E_TEXTO
        p.drawText(QRect(x, 0, self.width() - x, self.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        p.end()
