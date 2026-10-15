"""A barra de endereço da aba Download: o campo, o limpar e as duas ações num quadro só.

Eram três peças soltas — o campo, "Colar e analisar" e "Analisar" — lado a lado, cada uma com a sua borda. No
protótipo é um quadro só, com o anel de foco em volta de tudo e "Analisar" encaixado na ponta: o olho lê "aqui se
cola o endereço" e não "um campo e dois botões".

O campo (``edit``) continua sendo um ``QLineEdit`` de verdade — o foco, o Enter, o nome acessível, o ``setEnabled``
durante a análise —, e as duas ações são os botões de sempre. Só a moldura é nova.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QWidget

from videomanager.presentation.qt import icons, strings, theme
from videomanager.presentation.qt.i18n import bind


class AddressBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "address-bar")
        self.setProperty("focused", "false")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 7, 7, 7)
        row.setSpacing(10)

        self.link = QLabel()
        self.link.setProperty("role", "plain")
        self.link.setFixedSize(18, 18)
        row.addWidget(self.link)

        # Sem rótulo: o campo diz o que espera, e o nome acessível mantém "Endereço" para o leitor de tela.
        self.edit = bind(QLineEdit(), "setPlaceholderText", lambda: strings.URL_PLACEHOLDER)
        bind(self.edit, "setAccessibleName", lambda: strings.URL_LABEL)
        self.edit.setProperty("role", "address-edit")
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)

        self.clear_button = QToolButton()
        self.clear_button.setProperty("role", "icon")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind(self.clear_button, "setToolTip", lambda: strings.URL_CLEAR)
        bind(self.clear_button, "setAccessibleName", lambda: strings.URL_CLEAR)
        self.clear_button.clicked.connect(self._clear)
        row.addWidget(self.clear_button)

        self.paste = bind(QPushButton(), "setText", lambda: strings.URL_PASTE_AND_ANALYZE)
        self.paste.setProperty("role", "ghost")
        self.paste.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.paste)

        self.analyze = bind(QPushButton(), "setText", lambda: strings.URL_ANALYZE)
        self.analyze.setProperty("role", "primary")
        self.analyze.setProperty("emphasis", "field")
        self.analyze.setDefault(True)
        row.addWidget(self.analyze)

        self.edit.textChanged.connect(self._sync_clear)
        self._sync_clear()
        theme.on_theme_change(self._retheme)
        self._retheme()

    def _clear(self) -> None:
        self.edit.clear()
        self.edit.setFocus()

    def _sync_clear(self) -> None:
        # Escondido sem texto: o botão só tem o que fazer quando há o que limpar, e o espaço dele volta ao campo.
        self.clear_button.setVisible(bool(self.edit.text()))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # O anel de foco é do quadro inteiro, e não só do campo de dentro (o QSS não tem "foco em algum filho").
        if obj is self.edit and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", "true" if event.type() == QEvent.Type.FocusIn else "false")
            self.style().unpolish(self)
            self.style().polish(self)
            self._paint_link()
        return super().eventFilter(obj, event)

    def _paint_link(self) -> None:
        """O elo vai para o acento enquanto a barra tem o foco, como o anel dela."""
        cores = theme.papeis(*theme.atual())
        cor = cores["accent"] if self.property("focused") == "true" else cores["t3"]
        self.link.setPixmap(icons.link(cor, 18).pixmap(18, 18))

    def _retheme(self) -> None:
        cores = theme.papeis(*theme.atual())
        self._paint_link()
        self.clear_button.setIcon(icons.close(cores["t3"], 14))
        self.paste.setIcon(icons.clipboard(cores["t2"], 18))
