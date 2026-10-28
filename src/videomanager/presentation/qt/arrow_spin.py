"""Campo numérico com as setas de aumentar e diminuir à vista.

Sob a folha de estilo do app o ``QSpinBox`` perde o desenho nativo dos botões e fica com dois retângulos em
branco no canto: o usuário vê um campo que parece não ter controle nenhum. O QSS só desenha seta com uma imagem
(``image: url(...)``), e o pacote não leva imagens nem QtSvg — então o campo pinta as setas por cima, nos
retângulos que o próprio estilo diz serem os botões, na cor do tema.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSpinBox, QStyle, QStyleOptionSpinBox

from videomanager.presentation.qt import theme


class ArrowSpinBox(QSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        theme.on_theme_change(self._retheme)
        self.lineEdit().installEventFilter(self)

    def _retheme(self) -> None:
        self.update()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self.lineEdit() and event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self._restore_inset()
        return super().eventFilter(obj, event)

    def _restore_inset(self) -> None:
        """Devolve ao número o afastamento da borda que o QSS manda e o Qt 6.12 deixou de aplicar.

        No 6.11 o campo de dentro nascia a ``SPIN_EDIT_INSET`` px de cada lado (borda e preenchimento da regra de campos);
        no 6.12 ele começa em x = 0 e sobra o mesmo dos dois lados: o número colava na borda arredondada e o Windows da
        CI, que instala o PySide6 mais novo, o entregava assim. Só age se o estilo não afastou, então nada dobra nas
        versões em que ele afasta.
        """
        edit, inset = self.lineEdit(), theme.SPIN_EDIT_INSET
        if edit.x() < inset and edit.width() > 2 * inset:
            edit.setGeometry(edit.x() + inset, edit.y(), edit.width() - 2 * inset, edit.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        opcao = QStyleOptionSpinBox()
        self.initStyleOption(opcao)
        cor = QColor(theme.papeis(*theme.atual())["t2" if self.isEnabled() else "t3"])
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(QPen(cor, 1.5))
        for parte, sentido in ((QStyle.SubControl.SC_SpinBoxUp, -1), (QStyle.SubControl.SC_SpinBoxDown, 1)):
            caixa = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opcao, parte, self)
            centro = QPointF(caixa.center())
            largura, altura = 3.2, 1.8
            pintor.drawPolyline(QPolygonF([
                QPointF(centro.x() - largura, centro.y() - sentido * altura),
                QPointF(centro.x(), centro.y() + sentido * altura),
                QPointF(centro.x() + largura, centro.y() - sentido * altura),
            ]))
        pintor.end()
