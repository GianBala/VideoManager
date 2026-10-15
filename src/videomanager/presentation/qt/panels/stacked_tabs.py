"""Abas com o ícone sobre o texto, do tamanho da largura da coluna.

A barra de abas dos adicionais tinha o ícone ao lado do texto, apertado para caber em 400 px, e um título "Adicionais"
em cima. No protótipo as quatro abas (Texto, Filtros, Transições, Propriedades) dividem a coluna em partes iguais, cada
uma com o ícone em cima e o nome embaixo, e a marcada leva o acento no texto e um sublinhado na base da aba.

É uma ``QTabBar`` de verdade (teclado, ``setCurrentIndex``, ``tabText``, ``tabIcon``, ``tabRect``, o sinal de troca): só
o desenho e a medida são próprios — o QSS não coloca o ícone acima do texto.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from videomanager.presentation.qt import fonts, theme

_ALTURA = 58
_ICONE = 20
_ENTRE = 5
_RESPIRO = 10


class StackedTabBar(QTabBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Transparente: o fundo global dos widgets (a página) pintaria um retângulo escuro sobre o cartão da coluna.
        self.setProperty("role", "plain")
        self.setDrawBase(False)
        self.setExpanding(True)
        self.setUsesScrollButtons(False)
        self.setIconSize(QSize(_ICONE, _ICONE))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def _fonte(self) -> QFont:
        fonte = fonts.resized(self.font(), delta=-1)
        fonte.setWeight(QFont.Weight.Medium)
        return fonte

    def _minimo(self, indice: int) -> int:
        return QFontMetrics(self._fonte()).horizontalAdvance(self.tabText(indice)) + 2 * _RESPIRO

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802
        # Partes iguais da largura que a barra tem; o piso é o que o texto pede. A soma dos pisos é a dica da barra.
        quantas = max(1, self.count())
        return QSize(max(self._minimo(index), self.width() // quantas), _ALTURA)

    def minimumTabSizeHint(self, index: int) -> QSize:  # noqa: N802
        return QSize(self._minimo(index), _ALTURA)

    def sizeHint(self) -> QSize:  # noqa: N802
        # A soma dos pisos e nada mais. Pedir a largura do pai fazia a coluna pedir a largura que já tinha: a dica da
        # coluna de Adicionais saltava de 520 para 616–644 px e o divisor deixava de caber a prévia em 1920 px. Quem
        # estica a barra de ponta a ponta é o ``documentMode`` do ``StackedTabs``.
        return QSize(sum(self._minimo(i) for i in range(self.count())), _ALTURA)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802
        cores = theme.papeis(*theme.atual())
        foco = theme.palette(*theme.atual())["focus"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # O fio da base, de ponta a ponta; o sublinhado da marcada passa por cima dele.
        p.setPen(QPen(self._cor(cores["raised2"]), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        fonte = self._fonte()
        metricas = QFontMetrics(fonte)
        for indice in range(self.count()):
            caixa = self.tabRect(indice)
            marcada = indice == self.currentIndex()
            cor = cores["accent"] if marcada else cores["t2"]
            icone: QIcon = self.tabIcon(indice)
            if not icone.isNull():
                estado = QIcon.State.On if marcada else QIcon.State.Off
                p.drawPixmap(QRect(caixa.center().x() - _ICONE // 2, caixa.top() + 10, _ICONE, _ICONE),
                             icone.pixmap(QSize(_ICONE, _ICONE), QIcon.Mode.Normal, estado))
            p.setFont(fonte)
            p.setPen(self._cor(cor))
            texto = metricas.elidedText(self.tabText(indice), Qt.TextElideMode.ElideRight, caixa.width() - 2 * 4)
            p.drawText(QRect(caixa.left(), caixa.top() + 10 + _ICONE + _ENTRE, caixa.width(), metricas.height() + 2),
                       int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), texto)
            if marcada:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._cor(cores["accent"]))
                p.drawRect(QRect(caixa.left(), self.height() - 2, caixa.width(), 2))
            if self.hasFocus() and marcada:
                p.setPen(QPen(self._cor(foco), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRect(caixa.left() + 3, caixa.top() + 3, caixa.width() - 6, caixa.height() - 8), 6, 6)
        p.end()

    @staticmethod
    def _cor(texto: str):
        from PySide6.QtGui import QColor
        return QColor(texto)


class StackedTabs(QTabWidget):
    """Um ``QTabWidget`` com a barra de ``StackedTabBar``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabBar(StackedTabBar())
        # No modo documento o ``QTabWidget`` dá à barra a largura inteira dele, qualquer que seja a dica da barra.
        self.setDocumentMode(True)
