"""Rasterização Qt de texto em recursos imutáveis, isolados por processo."""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication,
                          QImage, QPainter, QPainterPath, QPen)

from videomanager.application.errors import ConversionError
from videomanager.domain.project import Clip

class QtTextRasterizer:
    """Cache por instância; vive enquanto seus consumidores e tarefas viverem."""
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: tempfile.TemporaryDirectory | None = None

    def render(self, clip: Clip) -> Path:
        """Reutiliza conteúdo idêntico sem sobrescrever recursos de outra versão."""
        fields = (clip.text_content, clip.font_family, clip.font_size, clip.font_bold,
                  clip.font_italic, clip.text_color, clip.stroke_color, clip.stroke_width)
        key = hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()
        with self._lock:
            if self._cache is None:
                self._cache = tempfile.TemporaryDirectory(prefix="videomanager-text-")
            path = Path(self._cache.name) / f"{key}.png"
            if path.is_file():
                return path
            if QGuiApplication.instance() is None:
                raise ConversionError("A aplicação gráfica precisa estar inicializada para preparar textos.")
            return _render(clip, path)


def _render(clip: Clip, out_path: Path) -> Path:
    font = QFont(clip.font_family or "Sans Serif", clip.font_size or 36)
    font.setBold(clip.font_bold)
    font.setItalic(clip.font_italic)

    text = clip.text_content or "Texto"
    metrics = QFontMetrics(font)
    stroke_w = max(0, clip.stroke_width)
    pad = 20 + stroke_w

    lines = text.splitlines() if text else ["Texto"]
    line_spacing = metrics.lineSpacing()
    total_text_h = (len(lines) - 1) * line_spacing + metrics.ascent() + metrics.descent()
    max_tw = max((metrics.horizontalAdvance(l) for l in lines), default=100)

    w = max(40, ((max_tw + pad * 2 + 3) // 4) * 4)
    h = max(40, ((total_text_h + pad * 2 + 3) // 4) * 4)

    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    start_y = (h - total_text_h) / 2 + metrics.ascent()
    path = QPainterPath()
    for i, line in enumerate(lines):
        tw = metrics.horizontalAdvance(line)
        lx = (w - tw) / 2
        ly = start_y + i * line_spacing
        path.addText(lx, ly, font, line)

    if stroke_w > 0:
        pen = QPen(
            QColor(clip.stroke_color or "#000000"),
            stroke_w * 2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.strokePath(path, pen)

    painter.fillPath(path, QBrush(QColor(clip.text_color or "#ffffff")))
    painter.end()

    # Publica somente a imagem completa. Cada conteúdo tem nome próprio e vive
    # até a saída do processo, inclusive enquanto workers ainda o consomem.
    temporary = out_path.with_suffix(".tmp.png")
    try:
        if not img.save(str(temporary), "PNG"):
            raise ConversionError("Não foi possível preparar a imagem do texto.")
        temporary.replace(out_path)
    finally:
        temporary.unlink(missing_ok=True)
    return out_path

__all__ = [
    'ConversionError',
    'Clip',
]
