"""Seção recolhível da aba Propriedades: cabeçalho com seta e título, e um corpo que só se esconde.

Substitui o ``QGroupBox`` de cada seção sem mexer no que há dentro: o corpo (``body``) é o contêiner onde
os mesmos widgets de antes são postos, e a seção inteira continua sendo o que o painel mostra e esconde
conforme o tipo do bloco. Recolher esconde o corpo e não o destrói: o que o usuário digitou fica lá.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QFrame, QToolButton, QVBoxLayout, QWidget

from videomanager.presentation.qt import icons, theme
from videomanager.presentation.qt.i18n import bind


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
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(6)
        self._header = _Header()
        self._header.setProperty("role", "section-header")
        self._header.setProperty("compact", "true")
        self._header.setCheckable(True)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setIconSize(QSize(14, 14))
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

    def _retheme(self) -> None:
        desenho = icons.chevron_down if self._header.isChecked() else icons.chevron_right
        self._header.setIcon(desenho(theme.papeis(*theme.atual())["text"]))
