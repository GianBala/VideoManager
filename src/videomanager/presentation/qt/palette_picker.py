"""Seletor de paleta da aba Tema: seis cartões exclusivos, cada um com uma miniatura na própria paleta.

A miniatura é **desenhada** com ``QPainter`` a partir dos papéis da paleta (fundo, painel, cartões,
botão primário, texto, selo de estado), e não é uma captura de tela: existe nos dois modos, segue a
paleta se um valor mudar e não pesa no pacote. O cartão em si usa as cores do tema em vigor
(``QPushButton[role="palette"]``, em ``theme.py``); só a miniatura mostra a paleta que ele representa.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from videomanager.domain.appearance import DEFAULT_PALETTE, PALETTES
from videomanager.presentation.qt import paletas, strings, theme

_COLUNAS = 3
_ALTURA_MINIATURA = 78


def _sem_mouse(widget: QWidget) -> None:
    """O clique tem de chegar ao cartão, e não parar no rótulo ou na miniatura que o cobrem."""
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class _Miniatura(QWidget):
    """Uma janela em miniatura: menu lateral, dois cartões, um campo, o botão primário e um selo."""

    def __init__(self, nome: str, modo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nome, self._modo = nome, modo
        self.setFixedHeight(_ALTURA_MINIATURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _sem_mouse(self)

    def set_mode(self, modo: str) -> None:
        self._modo = modo
        self.update()

    def paintEvent(self, _event) -> None:
        cores = paletas.papeis(self._nome, self._modo)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # O contorno vem do tema da aplicação, para a miniatura se destacar do cartão em qualquer paleta.
        contorno = QColor(self.palette().color(QPalette.ColorRole.Text))
        contorno.setAlpha(70)
        moldura = QPainterPath()
        moldura.addRoundedRect(area, 7, 7)
        pintor.fillPath(moldura, QColor(cores["canvas"]))
        pintor.save()
        pintor.setClipPath(moldura)
        largura, altura = area.width(), area.height()
        pintor.fillRect(QRectF(area.left(), area.top(), largura * 0.2, altura), QColor(cores["panel"]))
        pintor.setPen(Qt.PenStyle.NoPen)
        degrade = QLinearGradient(area.topLeft(), area.topRight())
        degrade.setColorAt(0, QColor(cores["fill_a"]))
        degrade.setColorAt(1, QColor(cores["fill_b"]))
        pintor.setBrush(degrade)
        pintor.drawRoundedRect(QRectF(area.left() + largura * 0.06, area.top() + 8, 11, 11), 3, 3)
        for deslocamento, cor in ((24, cores["accent"]), (32, cores["t3"]), (40, cores["t3"])):
            pintor.setBrush(QColor(cor))
            pintor.drawRoundedRect(QRectF(area.left() + largura * 0.06, area.top() + deslocamento, 11, 3), 1.5, 1.5)
        esquerda, largura_conteudo = area.left() + largura * 0.25, largura * 0.69
        for topo, alto in ((9, 21), (35, 30)):
            pintor.setBrush(QColor(cores["card"]))
            pintor.drawRoundedRect(QRectF(esquerda, area.top() + topo, largura_conteudo, alto), 5, 5)
            pintor.setBrush(QColor(cores["text"]))
            pintor.drawRoundedRect(QRectF(esquerda + 6, area.top() + topo + 6, largura_conteudo * 0.5, 3.5), 1.7, 1.7)
            pintor.setBrush(QColor(cores["t2"]))
            pintor.drawRoundedRect(QRectF(esquerda + 6, area.top() + topo + 13, largura_conteudo * 0.78, 3), 1.5, 1.5)
        pintor.setBrush(QColor(cores["raised"]))
        pintor.drawRoundedRect(QRectF(esquerda + 6, area.top() + 53, largura_conteudo * 0.48, 8), 3, 3)
        botao = QLinearGradient(esquerda, 0, esquerda + largura_conteudo, 0)
        botao.setColorAt(0, QColor(cores["fill_a"]))
        botao.setColorAt(1, QColor(cores["fill_b"]))
        pintor.setBrush(botao)
        pintor.drawRoundedRect(QRectF(esquerda + largura_conteudo * 0.62, area.top() + 52, largura_conteudo * 0.32, 10), 4, 4)
        pintor.setBrush(QColor(cores["ok"]))
        pintor.drawRoundedRect(QRectF(esquerda, area.top() + altura - 11, 18, 5), 2.5, 2.5)
        pintor.restore()
        pintor.setPen(contorno)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(moldura)
        # O visto do cartão marcado, no acento do tema da aplicação, no canto de cima à direita da miniatura.
        cartao = self.parent()
        if cartao is not None and getattr(cartao, "isChecked", lambda: False)():
            da_aplicacao = theme.papeis(*theme.atual())
            centro = QPointF(area.right() - 14, area.top() + 14)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(QColor(da_aplicacao["accent"]))
            pintor.drawEllipse(centro, 10.5, 10.5)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            caneta = QPen(QColor(da_aplicacao["canvas"]), 2.0)
            caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
            caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pintor.setPen(caneta)
            pintor.drawPolyline(QPolygonF([QPointF(centro.x() - 4.2, centro.y() + 0.2), QPointF(centro.x() - 1.2, centro.y() + 3.2),
                                           QPointF(centro.x() + 4.4, centro.y() - 3.0)]))


class _Cartao(QPushButton):
    """A miniatura, o nome e uma linha da paleta, num botão que se marca."""

    def __init__(self, nome: str, modo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.nome = nome
        self.setCheckable(True)
        self.setProperty("role", "palette")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Um QPushButton pede altura fixa; sem isto, o cartão de linha quebrada ficava mais alto que os
        # da mesma fileira, e a grade desalinhava.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        coluna = QVBoxLayout(self)
        # 2 px de borda + 6 de respiro: a margem é do layout, e não do QSS, que não alcança o que
        # um layout posto direto no botão ocupa.
        coluna.setContentsMargins(8, 8, 8, 8)
        coluna.setSpacing(4)
        self.miniatura = _Miniatura(nome, modo, self)
        coluna.addWidget(self.miniatura)
        # O visto é pintado pela miniatura (que cobre o cartão): ela se repinta quando o cartão é marcado ou desmarcado.
        self.toggled.connect(lambda _marcado: self.miniatura.update())
        titulo = QLabel(strings.PALETTE_NAMES[nome])
        fonte = titulo.font()
        fonte.setBold(True)
        titulo.setFont(fonte)
        linha = QLabel(strings.PALETTE_TAGLINES[nome])
        linha.setProperty("role", "dim")
        linha.setWordWrap(True)
        # Duas linhas reservadas: a altura de um rótulo que quebra depende da largura, e o cartão pede a do texto numa linha
        # só. Com a janela mais estreita, "Cinza neutro, sem cor de marca" passava a quebrar, o cartão ficava baixo para ele
        # e o nome da paleta se sobrepunha à miniatura.
        linha.setMinimumHeight(2 * linha.fontMetrics().lineSpacing())
        linha.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for rotulo in (titulo, linha):
            _sem_mouse(rotulo)
            coluna.addWidget(rotulo)
        coluna.addStretch(1)
        # Quem usa leitor de tela ouve o nome; a linha vai na dica.
        self.setAccessibleName(strings.PALETTE_NAMES[nome])
        self.setToolTip(f"{strings.PALETTE_NAMES[nome]}. {strings.PALETTE_TAGLINES[nome]}")

    def sizeHint(self):
        # Um QPushButton sem texto pede o mínimo do estilo, e não o do que há dentro dele.
        hint = self.layout().sizeHint()
        return hint.expandedTo(self.layout().minimumSize())

    def minimumSizeHint(self):
        return self.layout().minimumSize()


class SeletorDePaleta(QWidget):
    """Seis cartões exclusivos; ``palette()`` diz o marcado e ``changed`` avisa a troca."""

    changed = Signal(str)

    def __init__(self, atual: str, modo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "plain")
        grade = QGridLayout(self)
        grade.setContentsMargins(0, 0, 0, 0)
        grade.setSpacing(10)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._cartoes: dict[str, _Cartao] = {}
        for indice, nome in enumerate(PALETTES):
            cartao = _Cartao(nome, modo, self)
            self._grupo.addButton(cartao)
            self._cartoes[nome] = cartao
            grade.addWidget(cartao, indice // _COLUNAS, indice % _COLUNAS)
            cartao.toggled.connect(lambda marcado, n=nome: self.changed.emit(n) if marcado else None)
        for coluna in range(_COLUNAS):
            grade.setColumnStretch(coluna, 1)
        self._cartoes[atual if atual in self._cartoes else DEFAULT_PALETTE].setChecked(True)

    def palette(self) -> str:
        return next((nome for nome, cartao in self._cartoes.items() if cartao.isChecked()), DEFAULT_PALETTE)

    def set_palette(self, nome: str) -> None:
        if nome in self._cartoes:
            self._cartoes[nome].setChecked(True)

    def set_mode(self, modo: str) -> None:
        """Repinta as seis miniaturas no modo escolhido."""
        for cartao in self._cartoes.values():
            cartao.miniatura.set_mode(modo)
