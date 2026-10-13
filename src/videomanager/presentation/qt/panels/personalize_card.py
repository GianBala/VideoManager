"""Seção que se recolhe: o cabeçalho (seta, título, dica) e o conteúdo, que só se esconde.

O conteúdo é escondido e não destruído: um widget escondido continua guardando o que o usuário escolheu
(a lista de taxa que zerava a escolha de projetos NTSC reabertos foi o defeito que ensinou isso), então
recolher a seção e abri-la de novo devolve cada campo como estava, e "Adicionar à fila" com ela recolhida usa
o que está nos campos.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from videomanager.presentation.qt import icons, strings, theme
from videomanager.presentation.qt.i18n import bind


class PersonalizeCard(QFrame):
    """"Personalizar": o ajuste fino da qualidade, atrás de um cabeçalho que abre e fecha."""

    toggled = Signal(bool)

    def __init__(self, body: QWidget, parent: QWidget | None = None, *, expanded: bool = True) -> None:
        super().__init__(parent)
        self.setProperty("role", "section")
        self._body = body
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._toggle = QToolButton()
        self._toggle.setProperty("role", "section-header")
        self._toggle.setProperty("tight", "true")
        self._toggle.setCheckable(True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setIconSize(QSize(16, 16))
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        bind(self._toggle, "setText", lambda: strings.PERSONALIZE_TITLE)
        self._toggle.toggled.connect(self._on_toggled)
        header.addWidget(self._toggle)
        hint = bind(QLabel(), "setText", lambda: strings.PERSONALIZE_HINT)
        hint.setProperty("role", "hint")
        header.addWidget(hint, 1)
        # O seletor de modo (vídeo/áudio) é do corpo, mas se mostra aqui, à direita do título.
        modos = getattr(body, "mode_selector", None)
        if modos is not None:
            header.addWidget(modos)
        layout.addLayout(header)
        layout.addWidget(body)

        theme.on_theme_change(self._retheme)
        self._toggle.setChecked(expanded)
        self._on_toggled(expanded)

    @property
    def expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._retheme()
        self.toggled.emit(expanded)

    def _retheme(self) -> None:
        desenho = icons.chevron_down if self._toggle.isChecked() else icons.chevron_right
        self._toggle.setIcon(desenho(theme.papeis(*theme.atual())["text"]))
