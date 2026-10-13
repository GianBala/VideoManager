"""Ícones da barra da linha do tempo, desenhados à mão.

Existe porque as duas alternativas óbvias foram tentadas e não servem.

**Glifos de texto** — o caminho que ↶, ↷, − e + já usam — quebram para estes
dois: "✂" sai fino e minúsculo ao lado dos outros, e não há caractere de lixeira
fora do bloco de emoji. "🗑" é emoji: o sistema o desenha colorido, num tamanho
próprio, e ele fica visivelmente de outra família no meio da barra.

**Ícones do tema do sistema** (``QStyle.SP_TrashIcon``) mudam de desenho e de
cor a cada ambiente, e não existe equivalente para tesoura — os dois botões
sairiam de estilos diferentes um do outro.

Desenhar resolve os três problemas de uma vez: mesma espessura de traço dos
outros símbolos, cor vinda do tema (ver ``presentation/qt/theme.py``) e nenhuma dependência de
fonte ou de QtSvg, que não está no pacote. É o mesmo caminho que a linha do tempo
já toma ao se pintar sozinha.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# Lado do ícone, em pixels lógicos. Os botões da barra têm 40 px de largura;
# 18 deixa respiro suficiente para a borda do botão não encostar no desenho.
_SIZE = 18
_STROKE = 1.6


def _canvas(size: int) -> tuple[QPixmap, QPainter]:
    """Pixmap transparente e um painter já com antialiasing."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def _pen(color: str, width: float = _STROKE) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def scissors(color: str, size: int = _SIZE) -> QIcon:
    """Tesoura: duas lâminas cruzadas e dois anéis."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color))
    u = size / 18.0  # tudo abaixo é medido no desenho de 18 px

    # As lâminas cruzam acima dos anéis, como numa tesoura fechada.
    painter.drawLine(QPointF(4.5 * u, 13.0 * u), QPointF(14.0 * u, 3.0 * u))
    painter.drawLine(QPointF(13.5 * u, 13.0 * u), QPointF(4.0 * u, 3.0 * u))

    painter.setBrush(Qt.BrushStyle.NoBrush)
    raio = 2.1 * u
    painter.drawEllipse(QPointF(5.0 * u, 14.6 * u), raio, raio)
    painter.drawEllipse(QPointF(13.0 * u, 14.6 * u), raio, raio)
    painter.end()
    return QIcon(pixmap)


def _trim(color: str, size: int, keep_right: bool) -> QIcon:
    """Aparar até o cursor: o lado que fica é cheio, o que sai é contorno.

    Os dois lados aparecem de propósito. Só o lado que fica não diria de qual
    ponta se está falando — e a diferença entre estes dois botões é exatamente
    essa. A linha no meio é o cursor, que é o que decide onde o corte cai.
    """
    pixmap, painter = _canvas(size)
    u = size / 18.0
    topo, base = 3.6 * u, 14.4 * u
    corte = 9.0 * u
    folga = 1.6 * u  # respiro dos dois lados da linha do cursor

    fora = QRectF(1.4 * u, topo, corte - folga - 1.4 * u, base - topo)
    dentro = QRectF(corte + folga, topo, 16.6 * u - corte - folga, base - topo)
    if not keep_right:
        fora, dentro = dentro, fora

    # O que sai: contorno tracejado e apagado. O tracejado é o que diz "isto vai
    # embora" mesmo em quem olha o botão pela primeira vez; só apagar deixava os
    # dois ícones parecidos demais um com o outro.
    caneta = _pen(color, _STROKE * 0.9)
    caneta.setStyle(Qt.PenStyle.DotLine)
    painter.setPen(caneta)
    painter.setOpacity(0.5)
    painter.drawRect(fora)

    # O que fica: cheio.
    painter.setOpacity(1.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRect(dentro)

    # O cursor, mais alto que os blocos — é assim que ele aparece na linha do
    # tempo, atravessando as trilhas.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_pen(color, _STROKE * 1.15))
    painter.drawLine(QPointF(corte, 1.6 * u), QPointF(corte, 16.4 * u))
    painter.end()
    return QIcon(pixmap)


def trim_left(color: str, size: int = _SIZE) -> QIcon:
    """Apagar à esquerda: sai o que está antes do cursor."""
    return _trim(color, size, keep_right=True)


def trim_right(color: str, size: int = _SIZE) -> QIcon:
    """Apagar à direita: sai o que está depois do cursor."""
    return _trim(color, size, keep_right=False)


def trash(color: str, size: int = _SIZE) -> QIcon:
    """Lixeira: tampa, alça e corpo levemente afunilado, com duas ranhuras."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color))
    u = size / 18.0

    # Tampa e alça.
    painter.drawLine(QPointF(3.0 * u, 5.0 * u), QPointF(15.0 * u, 5.0 * u))
    painter.drawLine(QPointF(7.0 * u, 5.0 * u), QPointF(7.0 * u, 3.0 * u))
    painter.drawLine(QPointF(7.0 * u, 3.0 * u), QPointF(11.0 * u, 3.0 * u))
    painter.drawLine(QPointF(11.0 * u, 3.0 * u), QPointF(11.0 * u, 5.0 * u))

    # Corpo: as laterais fecham para baixo, que é o que faz um retângulo
    # parecer uma lixeira em vez de uma caixa.
    painter.drawLine(QPointF(4.6 * u, 5.0 * u), QPointF(5.6 * u, 15.2 * u))
    painter.drawLine(QPointF(13.4 * u, 5.0 * u), QPointF(12.4 * u, 15.2 * u))
    painter.drawLine(QPointF(5.6 * u, 15.2 * u), QPointF(12.4 * u, 15.2 * u))

    # Ranhuras, mais finas que o contorno para não competirem com ele.
    painter.setPen(_pen(color, _STROKE * 0.75))
    painter.drawLine(QPointF(7.6 * u, 7.4 * u), QPointF(7.9 * u, 13.0 * u))
    painter.drawLine(QPointF(10.4 * u, 7.4 * u), QPointF(10.1 * u, 13.0 * u))
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Transporte, desfazer e zoom
#
# Eram texto (▶ ❚❚ ◀◀ ↶ ↷ − +) e dependiam de uma fonte com símbolos: onde ela falta (o Qt do
# Windows sem a fonte de símbolos) cada um saía como um quadrado. Desenhados, saem iguais em
# qualquer sistema e na cor do tema. Todos no mesmo desenho de 18 px e no mesmo traço dos de cima.
# ---------------------------------------------------------------------------


def _preenchido(painter: QPainter, color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))


def _triangulo(painter: QPainter, u: float, tip_x: float, base_x: float, meio_y: float = 9.0, meia_altura: float = 5.0) -> None:
    """Triângulo apontando de ``base_x`` para ``tip_x`` (esquerda ou direita), em unidades de 18 px."""
    painter.drawPolygon(QPolygonF([
        QPointF(base_x * u, (meio_y - meia_altura) * u),
        QPointF(tip_x * u, meio_y * u),
        QPointF(base_x * u, (meio_y + meia_altura) * u),
    ]))


def _barra(painter: QPainter, u: float, x: float, largura: float = 1.9) -> None:
    painter.drawRoundedRect(QRectF(x * u, 4.0 * u, largura * u, 10.0 * u), 0.7 * u, 0.7 * u)


def play(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _triangulo(painter, u, 14.2, 5.2, meia_altura=5.6)
    painter.end()
    return QIcon(pixmap)


def pause(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    for x in (4.8, 10.4):
        painter.drawRoundedRect(QRectF(x * u, 3.8 * u, 2.9 * u, 10.4 * u), 0.9 * u, 0.9 * u)
    painter.end()
    return QIcon(pixmap)


def to_start(color: str, size: int = _SIZE) -> QIcon:
    """Ir ao início: uma barra e um triângulo para a esquerda."""
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _barra(painter, u, 3.4)
    _triangulo(painter, u, 6.6, 14.6)
    painter.end()
    return QIcon(pixmap)


def to_end(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _barra(painter, u, 12.7)
    _triangulo(painter, u, 11.4, 3.4)
    painter.end()
    return QIcon(pixmap)


def rewind(color: str, size: int = _SIZE) -> QIcon:
    """Voltar: dois triângulos para a esquerda."""
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _triangulo(painter, u, 2.6, 9.4, meia_altura=4.6)
    _triangulo(painter, u, 8.6, 15.4, meia_altura=4.6)
    painter.end()
    return QIcon(pixmap)


def fast_forward(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _triangulo(painter, u, 9.4, 2.6, meia_altura=4.6)
    _triangulo(painter, u, 15.4, 8.6, meia_altura=4.6)
    painter.end()
    return QIcon(pixmap)


def frame_back(color: str, size: int = _SIZE) -> QIcon:
    """Quadro anterior: um triângulo para a esquerda e a barra do quadro."""
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _triangulo(painter, u, 4.2, 11.4)
    _barra(painter, u, 12.6)
    painter.end()
    return QIcon(pixmap)


def frame_forward(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    u = size / 18.0
    _preenchido(painter, color)
    _barra(painter, u, 3.5)
    _triangulo(painter, u, 13.8, 6.6)
    painter.end()
    return QIcon(pixmap)


def _volta(color: str, size: int, espelhar: bool) -> QIcon:
    """Seta curva de desfazer; refazer é a mesma, espelhada."""
    pixmap, painter = _canvas(size)
    u = size / 18.0
    if espelhar:
        painter.translate(size, 0)
        painter.scale(-1, 1)
    painter.setPen(_pen(color))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    curva = QPainterPath(QPointF(4.4 * u, 7.0 * u))
    curva.cubicTo(QPointF(6.6 * u, 3.4 * u), QPointF(13.4 * u, 3.6 * u), QPointF(14.0 * u, 9.2 * u))
    curva.cubicTo(QPointF(14.4 * u, 12.6 * u), QPointF(11.8 * u, 14.4 * u), QPointF(8.6 * u, 14.2 * u))
    painter.drawPath(curva)
    ponta = QPainterPath(QPointF(4.2 * u, 3.4 * u))
    ponta.lineTo(QPointF(4.4 * u, 7.2 * u))
    ponta.lineTo(QPointF(8.2 * u, 6.8 * u))
    painter.drawPath(ponta)
    painter.end()
    return QIcon(pixmap)


def undo(color: str, size: int = _SIZE) -> QIcon:
    return _volta(color, size, espelhar=False)


def redo(color: str, size: int = _SIZE) -> QIcon:
    return _volta(color, size, espelhar=True)


def plus(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color))
    u = size / 18.0
    painter.drawLine(QPointF(4.0 * u, 9.0 * u), QPointF(14.0 * u, 9.0 * u))
    painter.drawLine(QPointF(9.0 * u, 4.0 * u), QPointF(9.0 * u, 14.0 * u))
    painter.end()
    return QIcon(pixmap)


def minus(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color))
    u = size / 18.0
    painter.drawLine(QPointF(4.0 * u, 9.0 * u), QPointF(14.0 * u, 9.0 * u))
    painter.end()
    return QIcon(pixmap)


def check(color: str, size: int = _SIZE) -> QIcon:
    """Confirmação: o tique."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, _STROKE * 1.15))
    u = size / 18.0
    painter.drawPolyline(QPolygonF([QPointF(3.8 * u, 9.6 * u), QPointF(7.4 * u, 13.2 * u), QPointF(14.4 * u, 5.4 * u)]))
    painter.end()
    return QIcon(pixmap)


def warn(color: str, size: int = _SIZE) -> QIcon:
    """Aviso: triângulo com ponto de exclamação."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    u = size / 18.0
    painter.drawPolygon(QPolygonF([QPointF(9.0 * u, 2.8 * u), QPointF(15.8 * u, 14.6 * u), QPointF(2.2 * u, 14.6 * u)]))
    painter.drawLine(QPointF(9.0 * u, 7.0 * u), QPointF(9.0 * u, 10.4 * u))
    painter.drawPoint(QPointF(9.0 * u, 12.5 * u))
    painter.end()
    return QIcon(pixmap)


def close(color: str, size: int = _SIZE) -> QIcon:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color))
    u = size / 18.0
    painter.drawLine(QPointF(4.6 * u, 4.6 * u), QPointF(13.4 * u, 13.4 * u))
    painter.drawLine(QPointF(13.4 * u, 4.6 * u), QPointF(4.6 * u, 13.4 * u))
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Menu lateral
# ---------------------------------------------------------------------------

_NAV = 22


def _nav(color: str, size: int, desenho) -> QIcon:
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, 1.7))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    desenho(painter, size / 24.0)
    painter.end()
    return QIcon(pixmap)


def nav_download(color: str, size: int = _NAV) -> QIcon:
    def desenho(p: QPainter, u: float) -> None:
        p.drawLine(QPointF(12 * u, 4 * u), QPointF(12 * u, 14.5 * u))
        p.drawPolyline(QPolygonF([QPointF(7.5 * u, 10.2 * u), QPointF(12 * u, 14.7 * u), QPointF(16.5 * u, 10.2 * u)]))
        p.drawPolyline(QPolygonF([QPointF(5 * u, 18.5 * u), QPointF(19 * u, 18.5 * u)]))
    return _nav(color, size, desenho)


def nav_convert(color: str, size: int = _NAV) -> QIcon:
    def desenho(p: QPainter, u: float) -> None:
        p.drawLine(QPointF(5 * u, 8 * u), QPointF(18 * u, 8 * u))
        p.drawPolyline(QPolygonF([QPointF(14.8 * u, 4.8 * u), QPointF(18 * u, 8 * u), QPointF(14.8 * u, 11.2 * u)]))
        p.drawLine(QPointF(19 * u, 16 * u), QPointF(6 * u, 16 * u))
        p.drawPolyline(QPolygonF([QPointF(9.2 * u, 12.8 * u), QPointF(6 * u, 16 * u), QPointF(9.2 * u, 19.2 * u)]))
    return _nav(color, size, desenho)


def nav_edit(color: str, size: int = _NAV) -> QIcon:
    """Fita de filme: moldura, duas divisões e os furos das bordas."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(4 * u, 5 * u, 16 * u, 14 * u), 2 * u, 2 * u)
        p.drawLine(QPointF(8.5 * u, 5 * u), QPointF(8.5 * u, 19 * u))
        p.drawLine(QPointF(15.5 * u, 5 * u), QPointF(15.5 * u, 19 * u))
        for y in (9.5, 14.5):
            p.drawLine(QPointF(4 * u, y * u), QPointF(8.5 * u, y * u))
            p.drawLine(QPointF(15.5 * u, y * u), QPointF(20 * u, y * u))
    return _nav(color, size, desenho)


def nav_metadata(color: str, size: int = _NAV) -> QIcon:
    """Etiqueta: o contorno em losango alongado e o furo."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawPolygon(QPolygonF([QPointF(4.5 * u, 4.5 * u), QPointF(12.5 * u, 4.5 * u), QPointF(19.5 * u, 11.5 * u),
                                 QPointF(12.5 * u, 19.5 * u), QPointF(4.5 * u, 11.5 * u)]))
        p.drawPoint(QPointF(8.3 * u, 8.3 * u))
    return _nav(color, size, desenho)


def nav_settings(color: str, size: int = _NAV) -> QIcon:
    """Dois controles deslizantes."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawLine(QPointF(5 * u, 8 * u), QPointF(19 * u, 8 * u))
        p.drawLine(QPointF(5 * u, 16 * u), QPointF(19 * u, 16 * u))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(9 * u, 8 * u), 2.2 * u, 2.2 * u)
        p.drawEllipse(QPointF(15 * u, 16 * u), 2.2 * u, 2.2 * u)
    return _nav(color, size, desenho)


def two_states(desenho, normal: str, marcado: str, size: int = _NAV) -> QIcon:
    """Um ícone com uma cor em repouso e outra quando o botão está marcado."""
    icone = QIcon()
    icone.addPixmap(desenho(normal, size).pixmap(size, size), QIcon.Mode.Normal, QIcon.State.Off)
    icone.addPixmap(desenho(marcado, size).pixmap(size, size), QIcon.Mode.Normal, QIcon.State.On)
    return icone
