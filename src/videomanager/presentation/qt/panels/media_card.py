"""O cartão da mídia analisada: miniatura com a duração, título, origem e o que a mídia oferece.

No protótipo o cartão é a prova de que a análise deu certo, e por isso diz mais do que o nome: a miniatura grande
com o selo da duração, o autor e a origem numa linha, e os três selos que respondem "vale a pena?" — a maior
resolução, a maior taxa de quadros e os codecs disponíveis. Os selos saem da matriz de formatos, a mesma que alimenta
os campos de "Personalizar", e por isso nunca prometem o que a mídia não tem.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from videomanager.application.formatting import DASH, format_duration
from videomanager.domain.format_policy import available_families, available_fps, available_heights
from videomanager.domain.formats import FormatMatrix, MediaInfo
from videomanager.presentation.qt import fonts, strings, theme
from videomanager.presentation.qt.i18n import bind, on_language_change
from videomanager.presentation.qt.ports import DesktopRuntimePort
from videomanager.presentation.qt.tasks import WorkerRunner

# 16:9, o tamanho do protótipo: a miniatura é o que dá ao cartão o peso de "resultado da análise".
_THUMB_WIDTH = 216
_THUMB_HEIGHT = 122
_THUMB_RADIUS = 10


def chips(matrix: FormatMatrix) -> list[tuple[str, str]]:
    """Os selos do cartão, ``(texto, tom)``: o teto de resolução, o de taxa e os codecs, só os que a mídia tem."""
    selos: list[tuple[str, str]] = []
    alturas = available_heights(matrix)
    if alturas:
        selos.append((strings.CARD_CHIP_UP_TO.format(height=alturas[0]), "accent"))
    taxas = available_fps(matrix)
    if taxas:
        selos.append((strings.EDIT_CANVAS_FPS.format(fps=taxas[0]), "dim"))
    familias = available_families(matrix)
    if familias:
        selos.append((" · ".join(familias), "dim"))
    return selos


class _Thumb(QWidget):
    """A miniatura com os cantos arredondados e o selo da duração; sem imagem, o espaço reservado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_THUMB_WIDTH, _THUMB_HEIGHT)
        self._pixmap: QPixmap | None = None
        self._badge = ""
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None

    def set_badge(self, text: str) -> None:
        self._badge = text
        self.update()

    def badge(self) -> str:
        return self._badge

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_THUMB_WIDTH, _THUMB_HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802
        cores = theme.papeis(*theme.atual())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        corpo = QRectF(self.rect())
        recorte = QPainterPath()
        recorte.addRoundedRect(corpo, _THUMB_RADIUS, _THUMB_RADIUS)
        p.setClipPath(recorte)
        if self._pixmap is not None:
            # Preenche o quadro inteiro, cortando o que sobra: uma faixa preta de cada lado faria o selo da duração
            # flutuar fora da imagem.
            escalada = self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - escalada.width()) // 2, (self.height() - escalada.height()) // 2, escalada)
        else:
            p.fillRect(corpo, QColor(cores["raised2"]))
            p.setPen(QColor(cores["t3"]))
            p.drawText(corpo, int(Qt.AlignmentFlag.AlignCenter), strings.CARD_NO_THUMB)
        if self._badge:
            p.setClipping(False)
            fonte = fonts.resized(self.font(), delta=-1)
            fonte.setBold(True)
            p.setFont(fonte)
            largura = QFontMetrics(fonte).horizontalAdvance(self._badge) + 16
            selo = QRectF(self.width() - 8 - largura, self.height() - 8 - 22, largura, 22)
            p.setPen(Qt.PenStyle.NoPen)
            # Sobre a imagem, e não sobre o tema: o fundo é o preto da prévia, translúcido, e o texto é branco em
            # qualquer paleta (um papel de texto escuro sumiria sobre a miniatura).
            fundo = QColor(cores["screen"])
            fundo.setAlpha(178)
            p.setBrush(fundo)
            p.drawRoundedRect(selo, 6, 6)
            p.setPen(Qt.GlobalColor.white)
            p.drawText(selo, int(Qt.AlignmentFlag.AlignCenter), self._badge)
        p.end()


class MediaCard(QFrame):
    """Miniatura, título, autor e origem, e os selos do que a mídia oferece."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._runner = WorkerRunner()
        # Guarda a URL do pedido em voo: miniaturas de análises antigas podem
        # chegar depois de o usuário já ter analisado outra coisa.
        self._pending_thumb_url = ""

        self.setObjectName("mediaCard")
        self.setProperty("role", "media-card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(18)

        self._thumb = _Thumb()
        layout.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignTop)

        # O texto fica no meio da altura da miniatura, e não colado no topo.
        info = QVBoxLayout()
        info.setSpacing(6)
        info.addStretch(1)

        # O título e o autor vêm do site: texto puro, e não HTML. Com o formato automático do QLabel, "Aula <b>1</b>" saía em
        # negrito e "<br>" quebrava a linha do cartão.
        self._title = QLabel()
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setProperty("role", "media-title")
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info.addWidget(self._title)

        self._meta = QLabel("")
        self._meta.setTextFormat(Qt.TextFormat.PlainText)
        self._meta.setProperty("role", "media-meta")
        self._meta.setWordWrap(True)
        info.addWidget(self._meta)

        self._chips = QHBoxLayout()
        self._chips.setContentsMargins(0, 6, 0, 0)
        self._chips.setSpacing(6)
        info.addLayout(self._chips)
        self._media: MediaInfo | None = None

        self._extra = QLabel("")
        self._extra.setProperty("role", "dim")
        self._extra.setWordWrap(True)
        info.addWidget(self._extra)

        info.addStretch(1)
        layout.addLayout(info, 1)

        self.clear()
        on_language_change(self._retranslate)

    # ------------------------------------------------------------------

    def _set_chips(self, selos: list[tuple[str, str]]) -> None:
        while self._chips.count():
            item = self._chips.takeAt(0)
            selo = item.widget()
            if selo is not None:
                # Sem ``setParent(None)`` o selo velho continua filho do cartão, e à vista, até o próximo laço de
                # eventos entregar o ``deleteLater``: por um instante os selos do idioma anterior e os do novo
                # apareciam juntos.
                selo.setParent(None)
                selo.deleteLater()
        for texto, tom in selos:
            selo = QLabel(texto)
            selo.setProperty("role", "chip")
            selo.setProperty("tone", tom)
            self._chips.addWidget(selo)
        self._chips.addStretch(1)

    def clear(self) -> None:
        self._pending_thumb_url = ""
        self._media = None
        self._title.setProperty("role", "media-empty")
        self._repolish(self._title)
        bind(self._title, "setText", lambda: strings.CARD_EMPTY)
        self._meta.clear()
        self._extra.clear()
        self._set_chips([])
        self._thumb.set_pixmap(None)
        self._thumb.set_badge("")

    def set_media(self, media: MediaInfo) -> None:
        self._title.setText(media.title)
        self._title.setProperty("role", "media-title")
        self._repolish(self._title)

        # DASH é o "não informado" do humanize: numa transmissão ao vivo, que não tem duração, a linha ficava com um
        # travessão solto entre os pontos. A duração é formatada aqui: o domínio não conhece a apresentação.
        pieces = [piece for piece in (media.uploader, media.extractor) if piece and piece != DASH]
        subtitles, blocked = len(media.subtitles), len(media.matrix.drm_blocked)

        def meta() -> str:
            return " · ".join(pieces)

        def extras() -> str:
            parts = []
            if subtitles:
                parts.append(strings.CARD_SUBTITLES.format(count=subtitles))
            if blocked:
                parts.append(strings.CARD_DRM.format(count=blocked))
            return " · ".join(parts)

        bind(self._meta, "setText", meta)
        bind(self._extra, "setText", extras)
        self._media = media
        self._show_facts(media)

        self._thumb.set_pixmap(None)
        self._pending_thumb_url = media.thumbnail_url
        if media.thumbnail_url:
            worker = self._runtime.thumbnail_worker(media.thumbnail_url)
            url = media.thumbnail_url
            worker.signals.loaded.connect(lambda data, u=url: self._apply_thumb(u, data))
            self._runner.start(worker, worker.signals.loaded, worker.signals.done)

    def _show_facts(self, media: MediaInfo) -> None:
        """O que a mídia oferece (selos) e o selo da miniatura: a duração, ou o aviso numa transmissão ao vivo."""
        self._set_chips(chips(media.matrix))
        duration = format_duration(media.duration)
        self._thumb.set_badge(strings.CARD_LIVE_BADGE if media.is_live else (duration if duration != DASH else ""))

    def _retranslate(self) -> None:
        """Os selos e o aviso "ao vivo" são montados na hora, no idioma de então: na troca, refaz com o de agora."""
        if self._media is not None:
            self._show_facts(self._media)
        self._thumb.update()

    def _apply_thumb(self, url: str, data: bytes) -> None:
        # Descarta a imagem se ela não é da mídia exibida agora.
        if url != self._pending_thumb_url:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self._thumb.set_pixmap(pixmap)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
