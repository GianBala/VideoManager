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

import math

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


# ---------------------------------------------------------------------------
# Tarefas
# ---------------------------------------------------------------------------

def upload(color: str, size: int = _NAV) -> QIcon:
    """Exportação: a seta de baixar, de cabeça para cima."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawLine(QPointF(12 * u, 19 * u), QPointF(12 * u, 8.5 * u))
        p.drawPolyline(QPolygonF([QPointF(7.5 * u, 12.8 * u), QPointF(12 * u, 8.3 * u), QPointF(16.5 * u, 12.8 * u)]))
        p.drawLine(QPointF(5 * u, 5 * u), QPointF(19 * u, 5 * u))
    return _nav(color, size, desenho)


def sync(color: str, size: int = _NAV) -> QIcon:
    """Processamento: duas setas em volta, uma para cada metade do círculo."""
    def desenho(p: QPainter, u: float) -> None:
        caixa = QRectF(5 * u, 5 * u, 14 * u, 14 * u)
        p.drawArc(caixa, 20 * 16, 140 * 16)
        p.drawArc(caixa, 200 * 16, 140 * 16)
        p.drawPolyline(QPolygonF([QPointF(15.2 * u, 3.8 * u), QPointF(18.6 * u, 7.0 * u), QPointF(14.6 * u, 8.4 * u)]))
        p.drawPolyline(QPolygonF([QPointF(8.8 * u, 20.2 * u), QPointF(5.4 * u, 17.0 * u), QPointF(9.4 * u, 15.6 * u)]))
    return _nav(color, size, desenho)


def clock(color: str, size: int = _NAV) -> QIcon:
    """Na fila: relógio."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawEllipse(QPointF(12 * u, 12 * u), 7.5 * u, 7.5 * u)
        p.drawPolyline(QPolygonF([QPointF(12 * u, 7.8 * u), QPointF(12 * u, 12 * u), QPointF(15 * u, 13.8 * u)]))
    return _nav(color, size, desenho)


def folder(color: str, size: int = _NAV) -> QIcon:
    """Abrir a pasta do arquivo."""
    def desenho(p: QPainter, u: float) -> None:
        pasta = QPainterPath(QPointF(4 * u, 8 * u))
        pasta.lineTo(QPointF(4 * u, 17 * u))
        pasta.quadTo(QPointF(4 * u, 18.5 * u), QPointF(5.5 * u, 18.5 * u))
        pasta.lineTo(QPointF(18.5 * u, 18.5 * u))
        pasta.quadTo(QPointF(20 * u, 18.5 * u), QPointF(20 * u, 17 * u))
        pasta.lineTo(QPointF(20 * u, 9.5 * u))
        pasta.quadTo(QPointF(20 * u, 8 * u), QPointF(18.5 * u, 8 * u))
        pasta.lineTo(QPointF(11.5 * u, 8 * u))
        pasta.lineTo(QPointF(9.8 * u, 5.8 * u))
        pasta.lineTo(QPointF(5.5 * u, 5.8 * u))
        pasta.quadTo(QPointF(4 * u, 5.8 * u), QPointF(4 * u, 7.3 * u))
        p.drawPath(pasta)
    return _nav(color, size, desenho)


def screen(color: str, size: int = _NAV) -> QIcon:
    """A tela do projeto: o monitor, só o contorno."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(4.5 * u, 6 * u, 15 * u, 10.5 * u), 2 * u, 2 * u)
        p.drawLine(QPointF(9.5 * u, 19 * u), QPointF(14.5 * u, 19 * u))
    return _nav(color, size, desenho)


def image(color: str, size: int = _NAV) -> QIcon:
    """Imagem: a moldura com o sol e a montanha."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(4.5 * u, 5.5 * u, 15 * u, 13 * u), 2.4 * u, 2.4 * u)
        p.drawEllipse(QPointF(9.2 * u, 10 * u), 1.5 * u, 1.5 * u)
        p.drawPolyline(QPolygonF([QPointF(5 * u, 17 * u), QPointF(10 * u, 12.6 * u), QPointF(13.2 * u, 15.4 * u),
                                  QPointF(15.2 * u, 13.6 * u), QPointF(19 * u, 17 * u)]))
    return _nav(color, size, desenho)


def info(color: str, size: int = _NAV) -> QIcon:
    """Aviso informativo: o círculo com o "i"."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawEllipse(QPointF(12 * u, 12 * u), 8.2 * u, 8.2 * u)
        p.drawLine(QPointF(12 * u, 11 * u), QPointF(12 * u, 16.4 * u))
        p.drawPoint(QPointF(12 * u, 7.9 * u))
    return _nav(color, size, desenho)


def compress(color: str, size: int = _NAV) -> QIcon:
    """Comprimir: duas setas de pontas opostas que se encontram no meio."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawPolyline(QPolygonF([QPointF(5 * u, 9.6 * u), QPointF(9.6 * u, 9.6 * u), QPointF(9.6 * u, 5 * u)]))
        p.drawLine(QPointF(9.6 * u, 9.6 * u), QPointF(4.4 * u, 4.4 * u))
        p.drawPolyline(QPolygonF([QPointF(19 * u, 14.4 * u), QPointF(14.4 * u, 14.4 * u), QPointF(14.4 * u, 19 * u)]))
        p.drawLine(QPointF(14.4 * u, 14.4 * u), QPointF(19.6 * u, 19.6 * u))
    return _nav(color, size, desenho)


def clipboard(color: str, size: int = _NAV) -> QIcon:
    """Colar: a prancheta, com a presilha de cima."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(6 * u, 5.5 * u, 12 * u, 14.5 * u), 2.2 * u, 2.2 * u)
        p.drawRoundedRect(QRectF(9 * u, 3.5 * u, 6 * u, 3.8 * u), 1.4 * u, 1.4 * u)
    return _nav(color, size, desenho)


def task_list(color: str, size: int = _NAV) -> QIcon:
    """A fila vazia: três linhas com marcador."""
    def desenho(p: QPainter, u: float) -> None:
        for y in (7, 12, 17):
            p.drawPoint(QPointF(5.5 * u, y * u))
            p.drawLine(QPointF(9 * u, y * u), QPointF(19 * u, y * u))
    return _nav(color, size, desenho)


# ---------------------------------------------------------------------------
# Barra superior do editor
# ---------------------------------------------------------------------------

def file_plus(color: str, size: int = _NAV) -> QIcon:
    """Novo projeto: a folha com a ponta dobrada e um mais."""
    def desenho(p: QPainter, u: float) -> None:
        folha = QPainterPath(QPointF(13.5 * u, 3.8 * u))
        folha.lineTo(QPointF(7 * u, 3.8 * u))
        folha.quadTo(QPointF(5.3 * u, 3.8 * u), QPointF(5.3 * u, 5.5 * u))
        folha.lineTo(QPointF(5.3 * u, 18.5 * u))
        folha.quadTo(QPointF(5.3 * u, 20.2 * u), QPointF(7 * u, 20.2 * u))
        folha.lineTo(QPointF(17 * u, 20.2 * u))
        folha.quadTo(QPointF(18.7 * u, 20.2 * u), QPointF(18.7 * u, 18.5 * u))
        folha.lineTo(QPointF(18.7 * u, 9 * u))
        folha.lineTo(QPointF(13.5 * u, 3.8 * u))
        folha.lineTo(QPointF(13.5 * u, 9 * u))
        folha.lineTo(QPointF(18.7 * u, 9 * u))
        p.drawPath(folha)
        p.drawLine(QPointF(12 * u, 12.6 * u), QPointF(12 * u, 17.2 * u))
        p.drawLine(QPointF(9.7 * u, 14.9 * u), QPointF(14.3 * u, 14.9 * u))
    return _nav(color, size, desenho)


def save(color: str, size: int = _NAV) -> QIcon:
    """Salvar: o disquete, com a aba de cima e a etiqueta de baixo."""
    def desenho(p: QPainter, u: float) -> None:
        corpo = QPainterPath(QPointF(6.8 * u, 4.5 * u))
        corpo.lineTo(QPointF(15.8 * u, 4.5 * u))
        corpo.lineTo(QPointF(19.5 * u, 8.2 * u))
        corpo.lineTo(QPointF(19.5 * u, 17.7 * u))
        corpo.quadTo(QPointF(19.5 * u, 19.5 * u), QPointF(17.7 * u, 19.5 * u))
        corpo.lineTo(QPointF(6.8 * u, 19.5 * u))
        corpo.quadTo(QPointF(4.5 * u, 19.5 * u), QPointF(4.5 * u, 17.2 * u))
        corpo.lineTo(QPointF(4.5 * u, 6.8 * u))
        corpo.quadTo(QPointF(4.5 * u, 4.5 * u), QPointF(6.8 * u, 4.5 * u))
        p.drawPath(corpo)
        p.drawPolyline(QPolygonF([QPointF(8 * u, 4.6 * u), QPointF(8 * u, 8.6 * u), QPointF(14.5 * u, 8.6 * u), QPointF(14.5 * u, 4.6 * u)]))
        p.drawPolyline(QPolygonF([QPointF(8 * u, 19.4 * u), QPointF(8 * u, 13.8 * u), QPointF(16 * u, 13.8 * u), QPointF(16 * u, 19.4 * u)]))
    return _nav(color, size, desenho)


def _painel(color: str, size: int, divisao: float) -> QIcon:
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(4.5 * u, 5 * u, 15 * u, 14 * u), 2.2 * u, 2.2 * u)
        p.drawLine(QPointF(4.7 * u, divisao * u), QPointF(19.3 * u, divisao * u))
    return _nav(color, size, desenho)


def preview_collapse(color: str, size: int = _NAV) -> QIcon:
    """Retrair a prévia: o quadro e, embaixo, a faixa que passa a ocupar a janela."""
    return _painel(color, size, 10)


def preview_expand(color: str, size: int = _NAV) -> QIcon:
    """Expandir a prévia: a divisão desce, a imagem volta a crescer."""
    return _painel(color, size, 15)


def fullscreen(color: str, size: int = _NAV) -> QIcon:
    """Tela cheia: os quatro cantos."""
    def desenho(p: QPainter, u: float) -> None:
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            x, y = (4.8 if sx > 0 else 19.2), (4.8 if sy > 0 else 19.2)
            p.drawPolyline(QPolygonF([QPointF(x * u, (y + 4.2 * sy) * u), QPointF(x * u, y * u), QPointF((x + 4.2 * sx) * u, y * u)]))
    return _nav(color, size, desenho)


def chevron_right(color: str, size: int = _SIZE) -> QIcon:
    """Recolher a gaveta, que fica à direita."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, _STROKE * 1.1))
    u = size / 18.0
    painter.drawPolyline(QPolygonF([QPointF(6.8 * u, 3.8 * u), QPointF(12.0 * u, 9.0 * u), QPointF(6.8 * u, 14.2 * u)]))
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Aba Download
# ---------------------------------------------------------------------------

def link(color: str, size: int = _NAV) -> QIcon:
    """O campo do endereço: dois elos de corrente."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawArc(QRectF(4 * u, 10 * u, 9 * u, 6 * u), 50 * 16, 260 * 16)
        p.drawArc(QRectF(11 * u, 8 * u, 9 * u, 6 * u), 230 * 16, 260 * 16)
        p.drawLine(QPointF(9 * u, 12 * u), QPointF(15 * u, 12 * u))
    return _nav(color, size, desenho)


def star(color: str, size: int = _NAV) -> QIcon:
    """Máxima qualidade."""
    def desenho(p: QPainter, u: float) -> None:
        pontos = []
        for i in range(10):
            raio = 8 * u if i % 2 == 0 else 3.6 * u
            angulo = -math.pi / 2 + i * math.pi / 5
            pontos.append(QPointF(12 * u + raio * math.cos(angulo), 12.4 * u + raio * math.sin(angulo)))
        p.drawPolygon(QPolygonF(pontos))
    return _nav(color, size, desenho)


def music(color: str, size: int = _NAV) -> QIcon:
    """Só o áudio: nota musical."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawLine(QPointF(10 * u, 17 * u), QPointF(10 * u, 6 * u))
        p.drawLine(QPointF(10 * u, 6 * u), QPointF(18 * u, 4.5 * u))
        p.drawLine(QPointF(18 * u, 4.5 * u), QPointF(18 * u, 15 * u))
        p.drawEllipse(QPointF(7.6 * u, 17 * u), 2.4 * u, 2.4 * u)
        p.drawEllipse(QPointF(15.6 * u, 15 * u), 2.4 * u, 2.4 * u)
    return _nav(color, size, desenho)


def waveform(color: str, size: int = _NAV) -> QIcon:
    """Áudio original, sem perda: barras de onda."""
    def desenho(p: QPainter, u: float) -> None:
        for x, meia in ((6, 2.5), (9, 5), (12, 8), (15, 5), (18, 2.5)):
            p.drawLine(QPointF(x * u, (12 - meia) * u), QPointF(x * u, (12 + meia) * u))
    return _nav(color, size, desenho)


def chevron_down(color: str, size: int = _SIZE) -> QIcon:
    """Seção aberta."""
    pixmap, painter = _canvas(size)
    painter.setPen(_pen(color, _STROKE * 1.1))
    u = size / 18.0
    painter.drawPolyline(QPolygonF([QPointF(3.8 * u, 6.8 * u), QPointF(9.0 * u, 12.0 * u), QPointF(14.2 * u, 6.8 * u)]))
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Espécies de bloco da linha do tempo
# ---------------------------------------------------------------------------

def type_text(color: str, size: int = _NAV) -> QIcon:
    """Bloco de texto: a letra T."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawLine(QPointF(6 * u, 6.5 * u), QPointF(18 * u, 6.5 * u))
        p.drawLine(QPointF(12 * u, 6.5 * u), QPointF(12 * u, 18.5 * u))
        p.drawLine(QPointF(9.5 * u, 18.5 * u), QPointF(14.5 * u, 18.5 * u))
    return _nav(color, size, desenho)


def type_filter(color: str, size: int = _NAV) -> QIcon:
    """Bloco de filtro: dois círculos que se sobrepõem."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawEllipse(QPointF(9.5 * u, 12 * u), 5.5 * u, 5.5 * u)
        p.drawEllipse(QPointF(14.5 * u, 12 * u), 5.5 * u, 5.5 * u)
    return _nav(color, size, desenho)


def type_image(color: str, size: int = _NAV) -> QIcon:
    """Bloco de imagem: moldura com o sol e a montanha."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(4.5 * u, 5.5 * u, 15 * u, 13 * u), 2 * u, 2 * u)
        p.drawEllipse(QPointF(9.2 * u, 10 * u), 1.6 * u, 1.6 * u)
        p.drawPolyline(QPolygonF([QPointF(5 * u, 17 * u), QPointF(10.5 * u, 12.5 * u), QPointF(14 * u, 15.5 * u),
                                  QPointF(16.5 * u, 13.5 * u), QPointF(19 * u, 16.5 * u)]))
    return _nav(color, size, desenho)


# ---------------------------------------------------------------------------
# Opções de filtro e de transição (aba Adicionais do editor)
# ---------------------------------------------------------------------------

def half_circle(color: str, size: int = _NAV) -> QIcon:
    """Preto e branco: círculo metade cheio."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawEllipse(QPointF(12 * u, 12 * u), 7 * u, 7 * u)
        caminho = QPainterPath(QPointF(12 * u, 5 * u))
        caminho.arcTo(QRectF(5 * u, 5 * u, 14 * u, 14 * u), 90, 180)
        caminho.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(caminho)
    return _nav(color, size, desenho)


def cup(color: str, size: int = _NAV) -> QIcon:
    """Sépia: xícara de café."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(5 * u, 9 * u, 11 * u, 8 * u), 2 * u, 2 * u)
        p.drawArc(QRectF(13 * u, 10.5 * u, 6 * u, 5 * u), -90 * 16, 180 * 16)
        p.drawLine(QPointF(9 * u, 5 * u), QPointF(9 * u, 7 * u))
        p.drawLine(QPointF(12 * u, 5 * u), QPointF(12 * u, 7 * u))
    return _nav(color, size, desenho)


def bolt(color: str, size: int = _NAV) -> QIcon:
    """Alto contraste: raio."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawPolygon(QPolygonF([QPointF(13.5 * u, 4 * u), QPointF(6.5 * u, 13 * u), QPointF(12 * u, 13 * u),
                                 QPointF(10.5 * u, 20 * u), QPointF(17.5 * u, 11 * u), QPointF(12 * u, 11 * u)]))
    return _nav(color, size, desenho)


def target(color: str, size: int = _NAV) -> QIcon:
    """Vinheta: círculos concêntricos."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawEllipse(QPointF(12 * u, 12 * u), 8 * u, 8 * u)
        p.drawEllipse(QPointF(12 * u, 12 * u), 4.2 * u, 4.2 * u)
    return _nav(color, size, desenho)


def dashed_circle(color: str, size: int = _NAV) -> QIcon:
    """Fade: círculo tracejado."""
    def desenho(p: QPainter, u: float) -> None:
        caneta = p.pen()
        caneta.setStyle(Qt.PenStyle.DotLine)
        p.setPen(caneta)
        p.drawEllipse(QPointF(12 * u, 12 * u), 7.5 * u, 7.5 * u)
    return _nav(color, size, desenho)


def square_filled(color: str, size: int = _NAV) -> QIcon:
    """Fade para preto: quadrado cheio."""
    def desenho(p: QPainter, u: float) -> None:
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(5.5 * u, 5.5 * u, 13 * u, 13 * u), 2.5 * u, 2.5 * u)
    return _nav(color, size, desenho)


def square_outline(color: str, size: int = _NAV) -> QIcon:
    """Fade para branco: quadrado vazado."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(5.5 * u, 5.5 * u, 13 * u, 13 * u), 2.5 * u, 2.5 * u)
    return _nav(color, size, desenho)


def _wipe(color: str, size: int, para_esquerda: bool) -> QIcon:
    def desenho(p: QPainter, u: float) -> None:
        p.drawRoundedRect(QRectF(4.5 * u, 5.5 * u, 15 * u, 13 * u), 2 * u, 2 * u)
        x = 9.5 if para_esquerda else 14.5
        p.drawLine(QPointF(x * u, 5.5 * u), QPointF(x * u, 18.5 * u))
        sentido = -1 if para_esquerda else 1
        meio = 14.5 if para_esquerda else 9.5
        p.drawPolyline(QPolygonF([QPointF((meio - sentido * 1.6) * u, 9.5 * u), QPointF((meio + sentido * 1.2) * u, 12 * u),
                                  QPointF((meio - sentido * 1.6) * u, 14.5 * u)]))
    return _nav(color, size, desenho)


def wipe_left(color: str, size: int = _NAV) -> QIcon:
    return _wipe(color, size, True)


def wipe_right(color: str, size: int = _NAV) -> QIcon:
    return _wipe(color, size, False)


def _slide(color: str, size: int, para_esquerda: bool) -> QIcon:
    def desenho(p: QPainter, u: float) -> None:
        borda = 5.5 if para_esquerda else 18.5
        p.drawLine(QPointF(borda * u, 5.5 * u), QPointF(borda * u, 18.5 * u))
        sentido = 1 if para_esquerda else -1
        ponta = 9.5 if para_esquerda else 14.5
        p.drawLine(QPointF(ponta * u, 12 * u), QPointF((ponta + sentido * 8) * u, 12 * u))
        p.drawPolyline(QPolygonF([QPointF((ponta + sentido * 3.2) * u, 8.6 * u), QPointF(ponta * u, 12 * u),
                                  QPointF((ponta + sentido * 3.2) * u, 15.4 * u)]))
    return _nav(color, size, desenho)


def slide_left(color: str, size: int = _NAV) -> QIcon:
    return _slide(color, size, True)


def slide_right(color: str, size: int = _NAV) -> QIcon:
    return _slide(color, size, False)


def loop(color: str, size: int = _NAV) -> QIcon:
    """Reproduzir em loop: duas setas que se perseguem."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawPolyline(QPolygonF([QPointF(4 * u, 11 * u), QPointF(4 * u, 8 * u), QPointF(20 * u, 8 * u)]))
        p.drawPolyline(QPolygonF([QPointF(17 * u, 5 * u), QPointF(20 * u, 8 * u), QPointF(17 * u, 11 * u)]))
        p.drawPolyline(QPolygonF([QPointF(20 * u, 13 * u), QPointF(20 * u, 16 * u), QPointF(4 * u, 16 * u)]))
        p.drawPolyline(QPolygonF([QPointF(7 * u, 13 * u), QPointF(4 * u, 16 * u), QPointF(7 * u, 19 * u)]))
    return _nav(color, size, desenho)


def magnet(color: str, size: int = _NAV) -> QIcon:
    """Alinhamento magnético: o ímã em U, com as pontas."""
    def desenho(p: QPainter, u: float) -> None:
        caminho = QPainterPath()
        caminho.moveTo(7 * u, 4 * u)
        caminho.lineTo(7 * u, 12 * u)
        caminho.arcTo(QRectF(7 * u, 7 * u, 10 * u, 10 * u), 180, 180)
        caminho.lineTo(17 * u, 4 * u)
        p.drawPath(caminho)
        p.drawLine(QPointF(5 * u, 4 * u), QPointF(9 * u, 4 * u))
        p.drawLine(QPointF(15 * u, 4 * u), QPointF(19 * u, 4 * u))
    return _nav(color, size, desenho)


def volume(color: str, size: int = _NAV, muted: bool = False) -> QIcon:
    """Som da prévia: o alto-falante com as ondas, ou com o X quando está mudo."""
    def desenho(p: QPainter, u: float) -> None:
        p.drawPolygon(QPolygonF([QPointF(4 * u, 10 * u), QPointF(8 * u, 10 * u), QPointF(13 * u, 6 * u),
                                 QPointF(13 * u, 18 * u), QPointF(8 * u, 14 * u), QPointF(4 * u, 14 * u)]))
        if muted:
            p.drawLine(QPointF(16.5 * u, 9.5 * u), QPointF(21.5 * u, 14.5 * u))
            p.drawLine(QPointF(21.5 * u, 9.5 * u), QPointF(16.5 * u, 14.5 * u))
        else:
            p.drawArc(QRectF(10 * u, 8 * u, 8 * u, 8 * u), -50 * 16, 100 * 16)
            p.drawArc(QRectF(8 * u, 5 * u, 14 * u, 14 * u), -50 * 16, 100 * 16)
    return _nav(color, size, desenho)


def _keyframe_step(color: str, size: int, previous: bool) -> QIcon:
    def desenho(p: QPainter, u: float) -> None:
        x = 6.5 if previous else 17.5
        sentido = 1 if previous else -1
        p.drawLine(QPointF(x * u, 6 * u), QPointF(x * u, 18 * u))
        p.drawPolyline(QPolygonF([QPointF((x + sentido * 9) * u, 7 * u), QPointF((x + sentido * 3.5) * u, 12 * u),
                                  QPointF((x + sentido * 9) * u, 17 * u)]))
    return _nav(color, size, desenho)


def keyframe_prev(color: str, size: int = _NAV) -> QIcon:
    """Quadro-chave anterior: a barra e o ângulo que aponta para trás."""
    return _keyframe_step(color, size, True)


def keyframe_next(color: str, size: int = _NAV) -> QIcon:
    return _keyframe_step(color, size, False)


def diamond(color: str, size: int = _NAV, filled: bool = False) -> QIcon:
    """O quadro-chave do cursor: losango vazado onde não há ponto, cheio onde há."""
    def desenho(p: QPainter, u: float) -> None:
        if filled:
            p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(12 * u, 5 * u), QPointF(19 * u, 12 * u), QPointF(12 * u, 19 * u),
                                 QPointF(5 * u, 12 * u)]))
    return _nav(color, size, desenho)


# Qual desenho acompanha cada opção, por identificador gravado no projeto.
FILTER_ICONS = {"pb": half_circle, "sepia": cup, "contraste": bolt, "vinheta": target, "inverter": nav_convert}
TRANSITION_ICONS = {
    "fade": dashed_circle, "fadeblack": square_filled, "fadewhite": square_outline, "dissolve": type_filter,
    "wipeleft": wipe_left, "wiperight": wipe_right, "slideleft": slide_left, "slideright": slide_right,
}


# Qual desenho acompanha cada espécie de bloco: a linha do tempo e o cabeçalho da aba Propriedades usam o mesmo.
TYPE_ICONS = {
    "video": nav_edit, "audio": music, "text": type_text, "image": type_image, "filter": type_filter,
    "transition": nav_convert,
}
