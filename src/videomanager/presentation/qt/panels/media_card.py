"""Card com miniatura e dados da mídia analisada."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.formatting import DASH
from videomanager.application.formatting import format_duration
from videomanager.domain.formats import MediaInfo
from videomanager.presentation.qt.tasks import WorkerRunner
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.ports import DesktopRuntimePort

# 16:9, do tamanho de um selo: o card divide a altura da janela com os controles
# e com a fila, e uma miniatura maior só empurraria os dois para fora da vista.
_THUMB_WIDTH = 128
_THUMB_HEIGHT = 72


class MediaCard(QFrame):
    """Mostra miniatura, título, autor, duração e origem da mídia."""

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

        # Painel de superfície, como os grupos de baixo (ver o QSS de
        # ``QFrame#mediaCard``). As margens do layout ficam no padrão do estilo,
        # que é o mesmo que os QGroupBox usam — é o que põe a miniatura na mesma
        # coluna em que começam os rótulos dos controles.
        self.setObjectName("mediaCard")
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_WIDTH, _THUMB_HEIGHT)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(
            "border-radius: 6px; background: rgba(128,128,128,0.15);"
        )
        self._thumb.setProperty("role", "dim")
        layout.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(3)

        self._title = QLabel(strings.CARD_EMPTY)
        self._title.setProperty("role", "title")
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info.addWidget(self._title)

        self._meta = QLabel("")
        self._meta.setProperty("role", "dim")
        self._meta.setWordWrap(True)
        info.addWidget(self._meta)

        self._extra = QLabel("")
        self._extra.setProperty("role", "dim")
        self._extra.setWordWrap(True)
        info.addWidget(self._extra)

        info.addStretch(1)
        layout.addLayout(info, 1)

        self.clear()

    # ------------------------------------------------------------------

    def clear(self) -> None:
        self._pending_thumb_url = ""
        self._title.setText(strings.CARD_EMPTY)
        self._title.setProperty("role", "dim")
        self._meta.clear()
        self._extra.clear()
        self._thumb.setPixmap(QPixmap())
        self._thumb.setText(strings.CARD_NO_THUMB)

    def set_media(self, media: MediaInfo) -> None:
        self._title.setText(media.title)
        self._title.setProperty("role", "title")
        self._title.style().unpolish(self._title)
        self._title.style().polish(self._title)

        # DASH é o "não informado" do humanize: numa transmissão ao vivo, que não
        # tem duração, a linha ficava com um travessão solto entre os pontos.
        # A duração é formatada aqui: o domínio não conhece a apresentação, e o
        # antigo ``MediaInfo.duration_label`` saiu dele na migração — o cartão
        # continuava a lê-lo e a análise terminava sem mostrar nada.
        pieces = [
            piece
            for piece in (media.uploader, format_duration(media.duration), media.extractor)
            if piece and piece != DASH
        ]
        if media.is_live:
            pieces.insert(0, strings.CARD_LIVE)
        self._meta.setText(" · ".join(pieces))

        extras: list[str] = []
        if media.subtitles:
            extras.append(strings.CARD_SUBTITLES.format(count=len(media.subtitles)))
        if media.matrix.drm_blocked:
            extras.append(
                f"{len(media.matrix.drm_blocked)} formato(s) bloqueado(s) por DRM"
            )
        self._extra.setText(" · ".join(extras))

        self._thumb.setPixmap(QPixmap())
        self._thumb.setText(strings.CARD_NO_THUMB)
        self._pending_thumb_url = media.thumbnail_url
        if media.thumbnail_url:
            worker = self._runtime.thumbnail_worker(media.thumbnail_url)
            url = media.thumbnail_url
            worker.signals.loaded.connect(lambda data, u=url: self._apply_thumb(u, data))
            self._runner.start(worker, worker.signals.loaded, worker.signals.done)

    def _apply_thumb(self, url: str, data: bytes) -> None:
        # Descarta a imagem se ela não é da mídia exibida agora.
        if url != self._pending_thumb_url:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self._thumb.setText("")
        self._thumb.setPixmap(
            pixmap.scaled(
                _THUMB_WIDTH,
                _THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
