"""Seletor único da tela do projeto, na barra superior do editor.

A barra tinha o botão Slideshow, a lista de proporção e a de tamanho, cada uma com o seu rótulo — quase metade da
largura para uma escolha que se faz uma vez por projeto. Aqui ficam um botão que **resume** o resultado ("Tela
automática · 16:9 · 1280 × 720 · 30 fps", que é o que se lê para saber se é preciso mexer) e um painel que abre
sob ele com os mesmos controles de antes.

Os controles são os do ``EditPanel``, só reparentados para dentro do painel: sinais, ``_sync_canvas`` e o fato de
a escolha não entrar no desfazer ficam onde estavam.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QFrame, QToolButton, QVBoxLayout, QWidget

from videomanager.presentation.qt import icons, theme

_CHEVRON = 14
# Espaço à direita do texto: a seta pintada e o respiro (o ``padding`` do QSS tem o mesmo número).
_RESERVE = 34


class CanvasPopup(QFrame):
    """O painel que abre sob o seletor: uma coluna de controles, que quem o monta preenche em ``column``."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setProperty("role", "popover")
        # Sem repetir o clique que fecha o painel: clicar no seletor com ele aberto só o fecha, em vez de fechar e,
        # no mesmo gesto, abrir de novo.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(14, 12, 14, 14)
        self.column.setSpacing(8)


class CanvasSelector(QToolButton):
    def __init__(self, popup: CanvasPopup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "selector")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._popup = popup
        self._summary = ""
        self._chevron = icons.chevron_down(theme.papeis(*theme.atual())["t2"], _CHEVRON)
        theme.on_theme_change(self._retheme)
        self.clicked.connect(self.show_popup)

    @property
    def popup(self) -> CanvasPopup:
        return self._popup

    def summary(self) -> str:
        """O texto inteiro, mesmo quando o botão está estreito demais para mostrá-lo."""
        return self._summary

    def set_summary(self, text: str) -> None:
        if text == self._summary:
            return
        self._summary = text
        self.setToolTip(text)
        self._elide()
        self.updateGeometry()

    def show_popup(self) -> None:
        """Abre o painel colado à borda direita do botão, que fica no canto da janela."""
        self._popup.adjustSize()
        largura = max(self._popup.width(), self.width())
        self._popup.resize(largura, self._popup.height())
        canto = self.mapToGlobal(QPoint(self.width(), self.height() + 4))
        self._popup.move(canto.x() - largura, canto.y())
        self._popup.show()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # O texto se corta com reticências quando falta largura: o piso é de um pedaço legível, e não do texto
        # inteiro, que empurraria o botão Exportar para fora da janela estreita.
        return QSize(150, super().sizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        cheio = QFontMetrics(self.font()).horizontalAdvance(self._summary) + _RESERVE + 14
        return QSize(max(base.width(), cheio), base.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._elide()

    def _elide(self) -> None:
        # Escondido, o botão não refaz layout e a largura dele é a de antes: cortar com ela deixaria o texto novo
        # pela metade até alguém voltar à aba. O corte é feito ao aparecer (``showEvent``) e a cada redimensionamento.
        livre = max(0, self.width() - _RESERVE - 14)
        texto = (QFontMetrics(self.font()).elidedText(self._summary, Qt.TextElideMode.ElideRight, livre)
                 if self.isVisible() else self._summary)
        if texto != self.text():
            self.setText(texto)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        lado = _CHEVRON
        self._chevron.paint(painter, QRect(self.width() - 12 - lado, (self.height() - lado) // 2, lado, lado))
        painter.end()

    def _retheme(self) -> None:
        self._chevron = icons.chevron_down(theme.papeis(*theme.atual())["t2"], _CHEVRON)
        self.update()
