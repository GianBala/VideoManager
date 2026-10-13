"""Linha de arquivo da aba Convert: nome, especificações e o antes → depois do tamanho.

A lista era uma linha de texto por arquivo, "nome · codec WxH · áudio · duração · tamanho → estimado", que o
olho tinha de desmontar. Aqui cada parte tem o seu lugar: o nome em cima, as especificações em selos embaixo,
e à direita o que o arquivo é hoje, o que vai ser e quanto muda — a conta que decide se a conversão vale a pena.

É pintada, como a fila, para a lista continuar sendo um ``QListWidget`` (seleção, Delete, arrastar e soltar,
os testes) e o texto do item continuar existindo para quem o lê sem ver.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from videomanager.application.formatting import DASH, format_duration, format_size
from videomanager.domain.media import LocalMedia
from videomanager.presentation.qt import fonts, icons, strings, theme

ROLE_MEDIA = Qt.ItemDataRole.UserRole
# ``{"size": bytes | None}`` com o tamanho que o arquivo terá (``None`` enquanto a amostra não chega). Item sem
# este dado ainda não foi estimado: a linha mostra só o tamanho de hoje.
ROLE_AFTER = Qt.ItemDataRole.UserRole + 1

_PAD = 10
_TILE = 44
_GAP = 12
_REMOVE = 24
ENTRE_LINHAS = 6
ALTURA = _PAD + _TILE + _PAD

_CODECS = {"h264": "H.264", "hevc": "HEVC", "h265": "H.265", "vp9": "VP9", "vp8": "VP8", "av1": "AV1",
           "aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC", "alac": "ALAC"}


def codec_name(codec: str) -> str:
    return _CODECS.get(codec.lower(), codec.upper())


def chips(media: LocalMedia) -> list[tuple[str, str]]:
    """Os selos da linha, ``(texto, tom)``: especificações do vídeo, do áudio e a duração."""
    selos: list[tuple[str, str]] = []
    if media.video:
        v = media.video
        selos.append((f"{codec_name(v.codec)} · {v.width}×{v.height}" if v.width and v.height
                      else codec_name(v.codec), "dim"))
    if media.audio:
        selos.append((codec_name(media.audio.codec), "dim"))
    elif media.video:
        # Vídeo sem som é a surpresa que a conversão não deve esconder.
        selos.append((strings.CONVERT_NO_AUDIO, "warn"))
    selos.append((format_duration(media.duration), "dim"))
    return selos


def change_percent(media: LocalMedia, after: int | None) -> int | None:
    if not media.size or after is None:
        return None
    return round((after - media.size) * 100 / media.size)


class RowDelegate(QStyledItemDelegate):
    """Pinta os arquivos da lista. O clique no × é da lista (``_DropList``), que o trata antes da seleção."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cores: dict[str, str] = {}
        self._hover = -1
        self._refrescar()
        theme.on_theme_change(self._retheme)

    def _refrescar(self) -> None:
        self._cores = theme.papeis(*theme.atual())

    def _retheme(self) -> None:
        self._refrescar()
        pai = self.parent()
        if pai is not None and hasattr(pai, "viewport"):
            pai.viewport().update()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        if index.data(ROLE_MEDIA) is None:
            return super().sizeHint(option, index)
        return QSize(option.rect.width(), ALTURA + ENTRE_LINHAS)

    @staticmethod
    def remove_rect(largura: int) -> QRect:
        return QRect(largura - _PAD - _REMOVE, (ALTURA - _REMOVE) // 2, _REMOVE, _REMOVE)

    def set_hover(self, row: int) -> bool:
        mudou = row != self._hover
        self._hover = row
        return mudou

    def paint(self, painter: QPainter, option, index) -> None:
        media: LocalMedia | None = index.data(ROLE_MEDIA)
        if media is None:
            super().paint(painter, option, index)
            return
        c = self._cores
        largura = option.rect.width()
        selecionado = bool(option.state & QStyle.StateFlag.State_Selected)
        passando = index.row() == self._hover or bool(option.state & QStyle.StateFlag.State_MouseOver)
        titulo = QFont(option.font)
        titulo.setBold(True)
        pequeno = fonts.resized(option.font, factor=0.9)
        mt, mp = QFontMetrics(titulo), QFontMetrics(pequeno)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(option.rect.topLeft())
        if selecionado or passando:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["raised"]))
            painter.drawRoundedRect(QRectF(0, 0, largura, ALTURA), 10, 10)

        tile = QRect(_PAD, _PAD, _TILE, _TILE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["raised2"]))
        painter.drawRoundedRect(QRectF(tile), 8, 8)
        desenho = icons.nav_edit if media.has_video else icons.music
        lado = 22
        desenho(c["accent"], lado).paint(painter, QRect(tile.x() + (_TILE - lado) // 2, tile.y() + (_TILE - lado) // 2, lado, lado))

        direita = self._pintar_tamanhos(painter, media, index.data(ROLE_AFTER), largura, pequeno, titulo)
        x = _PAD + _TILE + _GAP
        livre = max(40, direita - 16 - x)
        painter.setFont(titulo)
        painter.setPen(QColor(c["text"]))
        painter.drawText(QPoint(x, _PAD + mt.ascent() + 1), mt.elidedText(media.path.name, Qt.TextElideMode.ElideRight, livre))
        self._pintar_selos(painter, media, QRect(x, _PAD + mt.lineSpacing() + 6, livre, mp.height() + 6), pequeno, mp)

        remover = self.remove_rect(largura)
        if passando:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["raised2"]))
            painter.drawRoundedRect(QRectF(remover), 7, 7)
        lado = 14
        icons.close(c["text"] if passando else c["t2"], lado).paint(
            painter, QRect(remover.x() + (_REMOVE - lado) // 2, remover.y() + (_REMOVE - lado) // 2, lado, lado))
        painter.restore()

    def _pintar_selos(self, painter: QPainter, media: LocalMedia, area: QRect, fonte: QFont, metricas: QFontMetrics) -> None:
        c = self._cores
        painter.setFont(fonte)
        x = area.x()
        for texto, tom in chips(media):
            largura = metricas.horizontalAdvance(texto) + 16
            if x + largura > area.right():
                break
            caixa = QRectF(x, area.y(), largura, area.height())
            if tom == "warn":
                fundo = QColor(c["warn"])
                fundo.setAlpha(46)
                cor_texto = c["warn"]
            else:
                fundo = QColor(c["raised2"])
                cor_texto = c["t2"]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fundo)
            painter.drawRoundedRect(caixa, area.height() / 2, area.height() / 2)
            painter.setPen(QColor(cor_texto))
            painter.drawText(QPoint(x + 8, area.y() + (area.height() + metricas.ascent() - metricas.descent()) // 2), texto)
            x += largura + 6

    def _pintar_tamanhos(self, painter: QPainter, media: LocalMedia, depois: dict | None, largura: int, fonte: QFont,
                         forte: QFont) -> int:
        """"antes → depois  +35%", da direita para a esquerda; devolve o x onde o texto começa."""
        c = self._cores
        direita = self.remove_rect(largura).left() - 14
        normal = QFont(forte)
        normal.setBold(False)
        mn, mf = QFontMetrics(normal), QFontMetrics(forte)
        base = (ALTURA + mn.ascent() - mn.descent()) // 2

        def escrever(texto: str, fonte_: QFont, metricas: QFontMetrics, cor: str) -> None:
            nonlocal direita
            direita -= metricas.horizontalAdvance(texto)
            painter.setFont(fonte_)
            painter.setPen(QColor(cor))
            painter.drawText(QPoint(direita, base), texto)

        if depois is None:
            escrever(format_size(media.size), normal, mn, c["t2"])
            return direita
        estimado = depois["size"]
        mudanca = change_percent(media, estimado)
        if mudanca is not None:
            texto = (f"{mudanca:+d}%" if mudanca else "0%").replace("-", "−")
            escrever(texto, forte, mf, c["warn"] if mudanca > 0 else c["ok"] if mudanca < 0 else c["t2"])
            direita -= 8
        alvo = strings.CONVERT_MEASURING if estimado is None else format_size(estimado, estimated=True)
        escrever(alvo, forte, mf, c["text"])
        direita -= 8
        escrever("→", normal, mn, c["t3"])
        direita -= 8
        escrever(format_size(media.size) if media.size else DASH, normal, mn, c["t2"])
        return direita
