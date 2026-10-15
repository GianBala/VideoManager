"""Seção recolhível da aba Propriedades: cabeçalho com seta e título, e um corpo que só se esconde.

Substitui o ``QGroupBox`` de cada seção sem mexer no que há dentro: o corpo (``body``) é o contêiner onde
os mesmos widgets de antes são postos, e a seção inteira continua sendo o que o painel mostra e esconde
conforme o tipo do bloco. Recolher esconde o corpo e não o destrói: o que o usuário digitou fica lá.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QToolButton, QVBoxLayout, QWidget

from videomanager.presentation.qt import icons, theme
from videomanager.presentation.qt.i18n import bind


# O fio entre as seções: 15 px de ar acima dele, e 10 entre ele e o cabeçalho. A primeira seção visível não tem fio.
_AR_ACIMA = 15
_AR_ABAIXO = 10
# O ícone tem 3 px de ar à direita da seta: é o que afasta o título dela, que o ``QToolButton`` não deixa regular.
_ICONE = QSize(17, 14)


class _Header(QToolButton):
    def event(self, event: QEvent) -> bool:  # noqa: N802
        # O Espaço é o atalho de reproduzir do editor, de alcance do painel todo: sem recusar a tomada da
        # tecla, o cabeçalho com o foco reproduzia a edição em vez de recolher a seção.
        if event.type() == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Space:
            event.accept()
            return True
        return super().event(event)


class Section(QFrame):
    def __init__(self, title: Callable[[], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "prop-section")
        self._first = False
        self._column = QVBoxLayout(self)
        column = self._column
        column.setSpacing(7)
        self._apply_margins()
        self._header = _Header()
        self._header.setProperty("role", "section-header")
        self._header.setProperty("compact", "true")
        self._header.setCheckable(True)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setIconSize(_ICONE)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        bind(self._header, "setText", title)
        column.addWidget(self._header, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QWidget()
        self.body.setProperty("role", "plain")
        column.addWidget(self.body)
        self._header.toggled.connect(self._on_toggled)
        theme.on_theme_change(self._retheme)
        self._header.setChecked(True)
        self._retheme()

    def title(self) -> str:
        """O título como se lê agora (o ``QGroupBox`` de antes tinha o mesmo método)."""
        return self._header.text()

    @property
    def expanded(self) -> bool:
        return self._header.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._header.setChecked(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self._retheme()

    def set_first(self, first: bool) -> None:
        """A primeira seção visível não leva o fio de cima, e quem decide é o painel, que sabe quais aparecem."""
        if first != self._first:
            self._first = first
            self._apply_margins()
            self.update()

    def _apply_margins(self) -> None:
        self._column.setContentsMargins(0, _AR_ABAIXO if self._first else _AR_ACIMA + 1 + _AR_ABAIXO, 0, 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._first:
            painter = QPainter(self)
            painter.fillRect(0, _AR_ACIMA, self.width(), 1, QColor(theme.papeis(*theme.atual())["raised"]))
            painter.end()

    def _retheme(self) -> None:
        desenho = icons.chevron_down if self._header.isChecked() else icons.chevron_right
        seta = desenho(theme.papeis(*theme.atual())["t2"], _ICONE.height())
        quadro = QPixmap(_ICONE)
        quadro.fill(Qt.GlobalColor.transparent)
        painter = QPainter(quadro)
        seta.paint(painter, QRect(0, 0, _ICONE.height(), _ICONE.height()))
        painter.end()
        self._header.setIcon(QIcon(quadro))
