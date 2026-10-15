"""Amostra de cor das abas Texto e Propriedades: um quadrado arredondado com o anel do acento quando é a escolhida.

No protótipo a escolhida leva um anel de 2 px do acento **afastado** da cor por 2 px de ar, e é isso que o QSS não faz
(a borda de um botão cola na cor dele). A amostra se pinta, e a cor é dado do bloco: só a borda e o anel vêm do tema,
que é o que faz a troca de paleta alcançá-la.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from videomanager.presentation.qt import theme

# O ar em volta da cor, onde mora o anel de quem está escolhido: 2 px de anel e 1 de folga (medido no protótipo: a cor
# de 24 px tem o anel a 29 px de ponta a ponta, e as amostras andam de 32 em 32).
_ARO = 3


class Swatch(QPushButton):
    def __init__(self, color: str, *, width: int = 24, height: int | None = None, radius: int = 8, ring: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._width = width
        self._height = width if height is None else height
        self._radius = radius
        self._ring = _ARO if ring else 0
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.sizeHint())
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._width + 2 * self._ring, self._height + 2 * self._ring)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.update()

    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        cores = theme.papeis(*theme.atual())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        miolo = QRectF(self._ring, self._ring, self._width, self._height)
        p.setBrush(QColor(self._color))
        # A borda fina separa do fundo a cor que se confunde com ele (o preto, o azul-marinho).
        p.setPen(QPen(QColor(cores["raised2"]), 1))
        p.drawRoundedRect(miolo.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        if self._selected and self._ring:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(cores["accent"]), 2))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), self._radius + 2, self._radius + 2)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.palette(*theme.atual())["focus"]), 1.5))
            p.drawRoundedRect(QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5), self._radius + 2, self._radius + 2)
        p.end()
