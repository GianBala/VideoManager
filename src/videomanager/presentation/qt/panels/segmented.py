"""Botão de um controle segmentado: um ``QRadioButton`` com desenho de pílula.

Os três modos da aba Convert continuam sendo botões de rádio irmãos — o mesmo grupo exclusivo, os mesmos sinais,
as setas do teclado trocando de modo. Só o desenho muda: sem o círculo, com o texto centrado e o marcado
destacado no tom do acento. O QSS não faz isso (``::indicator`` com largura zero deixa o círculo desenhado e o
texto cortado), então o botão se pinta.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QRadioButton, QWidget

from videomanager.presentation.qt import theme

_PAD_H = 16
_ALTURA = 32


class SegmentButton(QRadioButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def _fonte(self) -> QFont:
        fonte = QFont(self.font())
        fonte.setBold(True)
        return fonte

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(QFontMetrics(self._fonte()).horizontalAdvance(self.text()) + 2 * _PAD_H, _ALTURA)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        cores = theme.papeis(*theme.atual())
        foco = theme.palette(*theme.atual())["focus"]
        marcado = self.isChecked()
        passando = self.underMouse() and self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.5)
        caixa = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        if marcado:
            fundo = QColor(cores["accent"])
            fundo.setAlpha(41)
            p.setBrush(fundo)
            p.setPen(QPen(QColor(cores["accent"]), 1))
        else:
            p.setBrush(QColor(cores["raised2"]) if passando else Qt.BrushStyle.NoBrush)
            p.setPen(Qt.PenStyle.NoPen)
        if self.hasFocus():
            p.setPen(QPen(QColor(foco), 1.5))
        p.drawRoundedRect(caixa, 8, 8)
        p.setFont(self._fonte())
        p.setPen(QColor(cores["accent"] if marcado else cores["text"] if passando else cores["t2"]))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()
