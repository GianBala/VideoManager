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
outros símbolos, cor vinda do tema (ver ``ui/theme.py``) e nenhuma dependência de
fonte ou de QtSvg, que não está no pacote. É o mesmo caminho que a linha do tempo
já toma ao se pintar sozinha.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

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
