"""Menu lateral: a navegação entre as abas, que deixou de ser uma barra de abas no topo.

Quatro abas pediam uma faixa inteira de altura só para quatro rótulos; o editor, que é onde a altura
vale mais, é justamente a aba que mais sofria com isso. Na lateral a navegação custa largura, que as
telas largas têm de sobra.

``Paginas`` é um ``QStackedWidget`` com a API de um ``QTabWidget`` (``addTab``, ``setTabText``,
``tabBar``…): os testes e os scripts de validação falam com ``MainWindow._tabs`` desse jeito, e o
menu lateral é só outra forma de escolher a página.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from videomanager.presentation.qt import icons, theme

LARGURA = 80
_ICONES = (icons.nav_download, icons.nav_convert, icons.nav_edit, icons.nav_metadata)


class _Item(QToolButton):
    def __init__(self, desenho, texto: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._desenho = desenho
        self.setProperty("role", "rail-item")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(22, 22))
        self.setFixedWidth(LARGURA - 10)
        # Só Tab alcança o item (clicar não deixa o anel de foco no que se acabou de abrir), e quem decide quais
        # entram na ordem é o menu: ver ``NavRail._sincronizar_foco``.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._selo = 0
        self.set_text(texto)
        self.repintar()

    def set_text(self, texto: str) -> None:
        self.setText(texto)
        self.setAccessibleName(texto)
        self.setToolTip(texto)

    def set_selo(self, contagem: int, dica: str = "") -> None:
        """O número de coisas pendentes no canto do ícone; zero some. ``dica`` diz o que o número conta."""
        self._selo = contagem
        if dica:
            self.setToolTip(dica)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._selo <= 0:
            return
        cores = theme.papeis(*theme.atual())
        texto = str(self._selo) if self._selo < 10 else "9+"
        fonte = QFont(self.font())
        fonte.setBold(True)
        fonte.setPixelSize(10)
        diametro = 16
        # No canto de cima e à direita do ícone, que fica no meio da largura do item.
        caixa = QRectF(self.width() / 2 + 3, 3, diametro + (4 if len(texto) > 1 else 0), diametro)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        degrade = QLinearGradient(caixa.topLeft(), caixa.bottomRight())
        degrade.setColorAt(0, QColor(cores["fill_a"]))
        degrade.setColorAt(1, QColor(cores["fill_b"]))
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(degrade)
        pintor.drawRoundedRect(caixa, diametro / 2, diametro / 2)
        pintor.setFont(fonte)
        pintor.setPen(QColor(cores["on_fill"]))
        pintor.drawText(caixa, Qt.AlignmentFlag.AlignCenter, texto)
        pintor.end()

    def repintar(self) -> None:
        cores = theme.papeis(*theme.atual())
        self.setIcon(icons.two_states(self._desenho, cores["t2"], cores["accent"]))


class NavRail(QWidget):
    """Itens exclusivos, como um grupo de rádio: setas navegam, e só o marcado entra na ordem de Tab."""

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "rail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(LARGURA)
        self._itens: list[_Item] = []
        self._acoes: list[_Item] = []
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(5, 14, 5, 14)
        coluna.setSpacing(4)
        coluna.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        marca = QLabel()
        marca.setProperty("role", "plain")
        icone = QApplication.windowIcon()
        if not icone.isNull():
            marca.setPixmap(icone.pixmap(QSize(38, 38)))
        marca.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        coluna.addWidget(marca)
        coluna.addSpacing(12)
        self._topo = coluna
        coluna.addStretch(1)
        theme.on_theme_change(self._retheme)

    def add_item(self, desenho, texto: str) -> int:
        item = _Item(desenho, texto, self)
        item.setCheckable(True)
        item.setAutoExclusive(True)
        indice = len(self._itens)
        item.toggled.connect(lambda marcado, i=indice: self._on_toggled(i, marcado))
        # Depois da marca e do espaço, antes da mola que separa os itens das ações do pé.
        self._topo.insertWidget(2 + len(self._itens), item)
        self._itens.append(item)
        return indice

    def _on_toggled(self, indice: int, marcado: bool) -> None:
        if marcado:
            self._sincronizar_foco()
            self.currentChanged.emit(indice)

    def _sincronizar_foco(self) -> None:
        """Como num grupo de rádio: Tab para no item marcado e segue adiante; entre os itens, as setas.

        O ``autoExclusive`` do Qt só pula os desmarcados quando o foco já está dentro do grupo, e quem entra de
        fora parava em todos: quatro Tab a mais em cada volta pela janela.
        """
        for item in self._itens:
            item.setFocusPolicy(Qt.FocusPolicy.TabFocus if item.isChecked() else Qt.FocusPolicy.NoFocus)

    def add_action(self, desenho, texto: str, chamada: Callable[[], None]) -> _Item:
        """Item que não marca nada: abre algo (as configurações), no pé do menu."""
        item = _Item(desenho, texto, self)
        item.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        item.clicked.connect(lambda _marcado=False: chamada())
        self._topo.addWidget(item)
        self._acoes.append(item)
        return item

    def add_toggle(self, desenho, texto: str, chamada: Callable[[bool], None]) -> _Item:
        """Item que liga e desliga algo (a gaveta de tarefas), sem fazer parte do grupo das páginas."""
        item = _Item(desenho, texto, self)
        item.setCheckable(True)
        item.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        item.toggled.connect(chamada)
        self._topo.addWidget(item)
        self._acoes.append(item)
        return item

    def count(self) -> int:
        return len(self._itens)

    def set_text(self, indice: int, texto: str) -> None:
        self._itens[indice].set_text(texto)

    def text(self, indice: int) -> str:
        return self._itens[indice].text()

    def current(self) -> int:
        return next((i for i, item in enumerate(self._itens) if item.isChecked()), -1)

    def set_current(self, indice: int) -> None:
        if 0 <= indice < len(self._itens) and not self._itens[indice].isChecked():
            self._itens[indice].setChecked(True)

    def hasFocus(self) -> bool:  # noqa: N802 - sobrepõe o método do Qt
        """Alguma das teclas do menu tem o foco: é o que "a barra de navegação tem foco" quer dizer."""
        return any(item.hasFocus() for item in (*self._itens, *self._acoes)) or super().hasFocus()

    def _retheme(self) -> None:
        for item in (*self._itens, *self._acoes):
            item.repintar()


class Paginas(QStackedWidget):
    """As páginas, com a API de ``QTabWidget`` que o resto do código e os testes usam."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rail = NavRail()
        self.rail.currentChanged.connect(self.setCurrentIndex)
        self.currentChanged.connect(self.rail.set_current)

    def addTab(self, pagina: QWidget, texto: str) -> int:  # noqa: N802
        self.addWidget(pagina)
        indice = self.rail.add_item(_ICONES[min(self.count(), len(_ICONES)) - 1], texto)
        if self.count() == 1:
            self.rail.set_current(0)
        return indice

    def setTabText(self, indice: int, texto: str) -> None:  # noqa: N802
        self.rail.set_text(indice, texto)

    def tabText(self, indice: int) -> str:  # noqa: N802
        return self.rail.text(indice)

    def tabBar(self) -> NavRail:  # noqa: N802
        return self.rail

    def setCurrentWidget(self, pagina: QWidget) -> None:  # noqa: N802
        self.setCurrentIndex(self.indexOf(pagina))
