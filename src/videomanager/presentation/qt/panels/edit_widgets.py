"""Widgets visuais do editor: prévia, propriedades, acervo e controles de fonte."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal

from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)

from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videomanager.domain.geometry import image_base_size
from videomanager.domain.constants import MIN_TRANSITION_DURATION

from videomanager.domain.preview import fit_size

from videomanager.domain.keyframe import ClipTransform
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.keyframe import create_preset_keyframes
from videomanager.presentation.qt.fonts import ensure_application_fonts
from videomanager.domain.project import MAX_GAIN_DB
from videomanager.domain.project import MIN_GAIN_DB
from videomanager.domain.project import Clip

from videomanager.presentation.qt import strings

_PREVIEW_MIN_HEIGHT = 160


def _index_of(box: QComboBox, value: object) -> int:
    """Posição do item que guarda este dado, ou -1.

    Não é o ``findData`` do Qt: ele compara os dados como ``QVariant``, e dois
    pares ``(1280, 720)`` iguais em Python não são o mesmo objeto — a busca
    devolvia -1 e a escolha de tela simplesmente não acontecia, enquanto a de
    taxa (um número) funcionava. Aqui a comparação é a do Python.
    """
    return next((i for i in range(box.count()) if box.itemData(i) == value), -1)


class _VolumePopup(QDialog):
    """Aba suspensa para ajuste de volume / ganho do bloco."""

    gain_changed = Signal(float)
    finished = Signal()

    def __init__(self, initial_gain: float, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumWidth(280)
        self.setStyleSheet(
            "QDialog { background: #222228; border: 1px solid #444450; border-radius: 8px; }"
            " QLabel { color: #f0f0f0; }"
            " QPushButton { background: #32323e; border: 1px solid #444454; border-radius: 4px; color: #fff; padding: 3px 6px; font-size: 11px; }"
            " QPushButton:hover { background: #424252; border-color: #666678; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel(strings.EDIT_VOLUME_POPUP_TITLE)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        spin_row = QHBoxLayout()
        self._spin = QDoubleSpinBox()
        self._spin.setRange(MIN_GAIN_DB, MAX_GAIN_DB)
        self._spin.setSingleStep(0.5)
        self._spin.setDecimals(1)
        self._spin.setSuffix(" dB")
        self._spin.setValue(initial_gain)
        self._spin.setFixedWidth(110)
        spin_row.addWidget(self._spin)
        layout.addLayout(spin_row)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for label, db in (("-6 dB", -6.0), ("0 dB", 0.0), ("+3 dB", 3.0), ("+6 dB", 6.0)):
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setMinimumWidth(50)
            btn.clicked.connect(lambda _, v=db: self._spin.setValue(v))
            presets.addWidget(btn)
        layout.addLayout(presets)

        self._spin.valueChanged.connect(self.gain_changed.emit)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.finished.emit()
        super().closeEvent(event)


class _SpeedPopup(QDialog):
    """Aba suspensa para ajuste de velocidade do bloco."""

    speed_changed = Signal(float)
    finished = Signal()

    def __init__(self, initial_speed: float, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumWidth(320)
        self.setStyleSheet(
            "QDialog { background: #222228; border: 1px solid #444450; border-radius: 8px; }"
            " QLabel { color: #f0f0f0; }"
            " QPushButton { background: #32323e; border: 1px solid #444454; border-radius: 4px; color: #fff; padding: 3px 6px; font-size: 11px; }"
            " QPushButton:hover { background: #424252; border-color: #666678; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel(strings.EDIT_SPEED_POPUP_TITLE)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        spin_row = QHBoxLayout()
        self._spin = QDoubleSpinBox()
        self._spin.setRange(0.1, 10.0)
        self._spin.setSingleStep(0.1)
        self._spin.setDecimals(1)
        self._spin.setSuffix("x")
        self._spin.setValue(initial_speed)
        self._spin.setFixedWidth(110)
        spin_row.addWidget(self._spin)
        layout.addLayout(spin_row)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for label, spd in (("0.5x", 0.5), ("1.0x", 1.0), ("1.5x", 1.5), ("2.0x", 2.0), ("4.0x", 4.0)):
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setMinimumWidth(48)
            btn.clicked.connect(lambda _, v=spd: self._spin.setValue(v))
            presets.addWidget(btn)
        layout.addLayout(presets)

        self._spin.valueChanged.connect(self.speed_changed.emit)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.finished.emit()
        super().closeEvent(event)


class _Preview(QLabel):
    """Tela da prévia: mantém o quadro centralizado, o fundo preto e suporte a transformações."""

    double_clicked = Signal()
    play_toggle_requested = Signal()
    overlay_transformed = Signal(int, float, float, float, float)
    overlay_transform_finished = Signal(int)
    clicked_outside = Signal()
    clip_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, rasterizer=None) -> None:
        super().__init__(parent)
        self._rasterizer = rasterizer
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(_PREVIEW_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: #141418; border-radius: 8px;")
        self.setText(strings.EDIT_EMPTY)
        self.setProperty("role", "dim")
        self._pixmap: QPixmap | None = None

        self._active_clip: Clip | None = None
        self._overlay_clips: tuple[Clip, ...] = ()
        self._proj_w: int = 1920
        self._proj_h: int = 1080
        self._position: float = 0.0
        self._drag_mode: str | None = None
        self._drag_clip_id: int = -1
        self._drag_start_pos = QPoint()
        self._drag_init_x: float = 0.5
        self._drag_init_y: float = 0.5
        self._drag_init_scale: float = 1.0
        self._drag_init_rot: float = 0.0
        self._drag_init_dist: float = 1.0
        self._drag_init_angle: float = 0.0
        self._drag_opp_x: float = 0.0
        self._drag_opp_y: float = 0.0
        self._drag_sx: float = 1.0
        self._drag_sy: float = 1.0
        self._drag_w0: float = 1.0
        self._drag_h0: float = 1.0
        self._clip_pixmaps: dict[Path, QPixmap] = {}
        self._text_pixmaps: dict[tuple, QPixmap] = {}
        self._clip_filters: dict[int, tuple[str, ...]] = {}
        self._filtered_pixmaps: dict[tuple, QPixmap] = {}
        self._is_playing: bool = False
        self._clip_visible: bool = True
        self._snap_enabled: bool = True
        self._snap_guide_x: float | None = None
        self._snap_guide_y: float | None = None
        self._snap_guide_rot: float | None = None
        self._drag_video_pixmap: QPixmap | None = None
        self._drag_base_pixmap: QPixmap | None = None
        self.setMouseTracking(True)

    def set_snap_enabled(self, enabled: bool) -> None:
        self._snap_enabled = bool(enabled)
        if not self._snap_enabled:
            self._snap_guide_x = None
            self._snap_guide_y = None
            self._snap_guide_rot = None
        self.update()

    def set_playing(self, playing: bool) -> None:
        if playing:
            self._drag_mode = None
            self._drag_clip_id = -1
            self._drag_video_pixmap = None
            self._drag_base_pixmap = None
            self._snap_guide_x = None
            self._snap_guide_y = None
            self._snap_guide_rot = None
        self._is_playing = playing
        self.update()

    def _apply_filters_to_pixmap(
        self, pix: QPixmap, filter_names: tuple[str, ...]
    ) -> QPixmap:
        if not filter_names or pix.isNull():
            return pix
        img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        for fname in filter_names:
            if fname == "pb":
                gray = img.convertToFormat(QImage.Format.Format_Grayscale8)
                res = gray.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                if img.hasAlphaChannel():
                    p = QPainter(res)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                    p.drawImage(0, 0, img)
                    p.end()
                img = res
            elif fname == "sepia":
                gray = img.convertToFormat(QImage.Format.Format_Grayscale8)
                res = gray.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                p = QPainter(res)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                p.fillRect(res.rect(), QColor(255, 220, 180))
                if img.hasAlphaChannel():
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                    p.drawImage(0, 0, img)
                p.end()
                img = res
            elif fname == "inverter":
                res = img.copy()
                res.invertPixels(QImage.InvertMode.InvertRgb)
                img = res
            elif fname == "contraste":
                res = img.copy()
                p = QPainter(res)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
                p.drawImage(0, 0, img)
                if img.hasAlphaChannel():
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                    p.drawImage(0, 0, img)
                p.end()
                img = res
            elif fname == "vinheta":
                res = img.copy()
                center = QPointF(res.width() / 2.0, res.height() / 2.0)
                radius = math.hypot(res.width() / 2.0, res.height() / 2.0)
                grad = QRadialGradient(center, radius)
                grad.setColorAt(0.0, QColor(0, 0, 0, 0))
                grad.setColorAt(0.5, QColor(0, 0, 0, 40))
                grad.setColorAt(1.0, QColor(0, 0, 0, 180))
                p = QPainter(res)
                p.fillRect(res.rect(), grad)
                if img.hasAlphaChannel():
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                    p.drawImage(0, 0, img)
                p.end()
                img = res
        return QPixmap.fromImage(img)

    def _get_clip_pixmap(
        self, clip: Clip, filters: tuple[str, ...] = ()
    ) -> QPixmap | None:
        base_pix: QPixmap | None = None
        cache_id = None
        if clip.overlay_type == "text":
            key = (
                clip.clip_id,
                clip.text_content,
                clip.font_family,
                clip.font_size,
                clip.font_bold,
                clip.font_italic,
                clip.text_color,
                clip.stroke_color,
                clip.stroke_width,
            )
            pix = self._text_pixmaps.get(key)
            if pix is not None and not pix.isNull():
                base_pix = pix
            else:
                try:
                    if len(self._text_pixmaps) > 60:
                        self._text_pixmaps.clear()
                    txt_path = self._rasterizer.render(clip)
                    pix = QPixmap(str(txt_path))
                    if not pix.isNull():
                        self._text_pixmaps[key] = pix
                    base_pix = pix
                except Exception:
                    base_pix = None
            cache_id = key
        elif clip.media is not None and clip.media.path:
            path = clip.media.path
            pix = self._clip_pixmaps.get(path)
            if pix is None and path.exists():
                pix = QPixmap(str(path))
                if not pix.isNull():
                    self._clip_pixmaps[path] = pix
            base_pix = pix
            cache_id = path
        else:
            return None

        if base_pix is None or base_pix.isNull():
            return None

        if not filters:
            return base_pix

        filter_key = (cache_id, filters)
        filtered = self._filtered_pixmaps.get(filter_key)
        if filtered is not None and not filtered.isNull():
            return filtered

        if len(self._filtered_pixmaps) > 60:
            self._filtered_pixmaps.clear()

        applied = self._apply_filters_to_pixmap(base_pix, filters)
        self._filtered_pixmaps[filter_key] = applied
        return applied

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, self.minimumHeight())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.double_clicked.emit()

    @property
    def has_frame(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def set_frame_pixmap(self, pixmap: QPixmap) -> None:
        if not self._drag_mode:
            self._drag_video_pixmap = None
            self._drag_base_pixmap = None
        self._pixmap = pixmap
        if not pixmap.isNull():
            self.setText("")
        self.update()

    def clear_frame(self) -> None:
        self._pixmap = None
        self._drag_video_pixmap = None
        self._drag_base_pixmap = None
        self._overlay_clips = ()
        self._clip_filters = {}
        self._snap_guide_x = None
        self._snap_guide_y = None
        self._snap_guide_rot = None
        self.setText(strings.EDIT_EMPTY)
        self.update()

    def set_overlay_clips(
        self,
        clips: Sequence[Clip],
        clip_filters: dict[int, tuple[str, ...]] | None = None,
    ) -> None:
        self._overlay_clips = tuple(clips)
        self._clip_filters = dict(clip_filters) if clip_filters else {}
        self.update()

    def setPixmap(self, pixmap: QPixmap) -> None:  # noqa: N802
        self.set_frame_pixmap(pixmap)

    def set_active_clip(self, clip: Clip | None, proj_w: int, proj_h: int, visible: bool = True) -> None:
        if clip is None or self._active_clip is None or clip.clip_id != self._active_clip.clip_id:
            if not self._drag_mode:
                self._drag_video_pixmap = None
                self._drag_base_pixmap = None
        self._active_clip = clip
        self._proj_w = max(1, proj_w)
        self._proj_h = max(1, proj_h)
        self._clip_visible = visible
        self._snap_guide_x = None
        self._snap_guide_y = None
        self._snap_guide_rot = None
        self.update()

    def set_position(self, pos: float) -> None:
        if abs(pos - self._position) > 0.001 and not self._drag_mode:
            self._drag_video_pixmap = None
            self._drag_base_pixmap = None
        self._position = pos
        self.update()

    def _video_rect(self) -> QRect:
        if self._pixmap is not None and not self._pixmap.isNull():
            pw, ph = self._pixmap.width(), self._pixmap.height()
        else:
            pw, ph = self._proj_w, self._proj_h
        target_w, target_h = fit_size(pw, ph, self.width(), self.height())
        x = (self.width() - target_w) // 2
        y = (self.height() - target_h) // 2
        return QRect(x, y, target_w, target_h)

    def _image_overlay_geometry(
        self, clip: Clip, transform: ClipTransform, vrect: QRect
    ) -> tuple[float, float, float, float]:
        """Repete a grade de pixels usada pelo ``overlay`` do FFmpeg.

        O quadro pausado desenha Adicionais no Qt para que possam ser movidos
        sem esperar uma nova renderização. Durante o play, porém, o FFmpeg os
        compõe sobre um canvas YUV 4:2:0: largura, altura e coordenadas do
        ``overlay`` acabam alinhadas em blocos de dois pixels. Desenhar aqui
        com os valores fracionários fazia a imagem saltar um ou dois pixels
        assim que a reprodução assumia a tela.
        """
        if self._pixmap is not None and not self._pixmap.isNull():
            output_w, output_h = self._pixmap.width(), self._pixmap.height()
        else:
            output_w, output_h = self._proj_w, self._proj_h

        # É a mesma redução de canvas de ``composer._preview_project``. Para
        # telas pequenas o compositor trabalha no tamanho original e só amplia
        # o resultado no último filtro, por isso não basta usar ``vrect``.
        compose_w, compose_h = fit_size(
            self._proj_w,
            self._proj_h,
            min(self._proj_w, output_w),
            min(self._proj_h, output_h),
        )
        media_w = clip.media.width if clip.media is not None else None
        media_h = clip.media.height if clip.media is not None else None
        canonical_w, canonical_h = image_base_size(
            media_w, media_h, self._proj_w, self._proj_h
        )
        base_w = max(
            2,
            int(round(canonical_w * compose_w / self._proj_w / 2.0) * 2),
        )
        base_h = max(
            2,
            int(round(canonical_h * compose_h / self._proj_h / 2.0) * 2),
        )

        base_sx = max(0.05, clip.scale_x)
        base_sy = max(0.05, clip.scale_y)
        animated_scale = clip.has_keyframes and (
            any(
                abs(k.scale_x - base_sx) > 0.01
                or abs(k.scale_y - base_sy) > 0.01
                for k in clip.keyframes
            )
            or any(
                abs(clip.keyframes[i].scale_x - clip.keyframes[i + 1].scale_x)
                > 0.01
                or abs(clip.keyframes[i].scale_y - clip.keyframes[i + 1].scale_y)
                > 0.01
                for i in range(len(clip.keyframes) - 1)
            )
        )
        if animated_scale:
            # O filtro com ``eval=frame`` usa ``trunc``; o caminho estático usa
            # ``round`` ao montar o comando.
            item_w = max(2, int(base_w * max(0.05, transform.scale_x) / 2.0) * 2)
            item_h = max(2, int(base_h * max(0.05, transform.scale_y) / 2.0) * 2)
        else:
            item_w = max(
                2,
                int(round(base_w * max(0.05, transform.scale_x) / 2.0) * 2),
            )
            item_h = max(
                2,
                int(round(base_h * max(0.05, transform.scale_y) / 2.0) * 2),
            )

        # O filtro overlay do FFmpeg avalia a expressão com round(), correspondendo a
        # round-half-away-from-zero em C (math.floor(v + 0.5) para valores não negativos).
        x = float(f"{transform.x:.6f}")
        y = float(f"{transform.y:.6f}")
        raw_left = x * compose_w - item_w / 2.0
        raw_top = y * compose_h - item_h / 2.0
        left = math.floor(raw_left + 0.5) if raw_left >= 0 else math.ceil(raw_left - 0.5)
        top = math.floor(raw_top + 0.5) if raw_top >= 0 else math.ceil(raw_top - 0.5)
        scale_x = vrect.width() / max(1.0, float(compose_w))
        scale_y = vrect.height() / max(1.0, float(compose_h))
        return (
            vrect.x() + (left + item_w / 2.0) * scale_x,
            vrect.y() + (top + item_h / 2.0) * scale_y,
            item_w * scale_x,
            item_h * scale_y,
        )

    def _clip_geometry(self, clip: Clip) -> tuple[float, float, float, float] | None:
        vrect = self._video_rect()
        if vrect.width() <= 0 or vrect.height() <= 0:
            return None
        t_offset = max(0.0, self._position - clip.start)
        transform = clip.transform_at(t_offset)
        if clip.overlay_type == "image" or clip.is_image:
            return self._image_overlay_geometry(clip, transform, vrect)
        cx = vrect.x() + transform.x * vrect.width()
        cy = vrect.y() + transform.y * vrect.height()
        sx = max(0.05, transform.scale_x)
        sy = max(0.05, transform.scale_y)

        if clip.overlay_type == "text":
            ensure_application_fonts()
            font = QFont(clip.font_family or "Sans Serif", clip.font_size or 36)
            font.setBold(clip.font_bold)
            font.setItalic(clip.font_italic)
            fm = QFontMetrics(font)
            text = clip.text_content or "Texto"
            stroke_w = max(0, clip.stroke_width)
            pad = 20 + stroke_w
            lines = text.splitlines() if text else ["Texto"]
            line_spacing = fm.lineSpacing()
            total_text_h = (len(lines) - 1) * line_spacing + fm.ascent() + fm.descent()
            max_tw = max((fm.horizontalAdvance(l) for l in lines), default=100)
            full_w = max(40, ((max_tw + pad * 2 + 3) // 4) * 4)
            full_h = max(40, ((total_text_h + pad * 2 + 3) // 4) * 4)
            preview_scale = vrect.width() / max(1.0, float(self._proj_w))
            w = max(20.0, full_w * preview_scale * sx)
            h = max(20.0, full_h * preview_scale * sy)
            return (cx, cy, w, h)

        if clip.has_image and not clip.audio_only and clip.media is not None:
            mw = clip.media.width or self._proj_w
            mh = clip.media.height or self._proj_h
            base_w, base_h = fit_size(mw, mh, self._proj_w, self._proj_h)
            preview_scale = vrect.width() / max(1.0, float(self._proj_w))
            w = max(20.0, base_w * preview_scale * sx)
            h = max(20.0, base_h * preview_scale * sy)
            return (cx, cy, w, h)

        return None

    def _hit_test_clip(
        self, clip: Clip, pos: QPoint
    ) -> tuple[str | None, tuple[float, float, float, float] | None]:
        if (
            clip is None
            or clip.overlay_type == "filter"
            or not clip.contains(self._position)
        ):
            return None, None

        geom = self._clip_geometry(clip)
        if geom is None:
            return None, None
        t_offset = max(0.0, self._position - clip.start)
        transform = clip.transform_at(t_offset)
        cx, cy, w, h = geom
        dx = pos.x() - cx
        dy = pos.y() - cy
        rad = -math.radians(transform.rotation)
        lx = dx * math.cos(rad) - dy * math.sin(rad)
        ly = dx * math.sin(rad) + dy * math.cos(rad)

        is_active = (
            self._active_clip is not None and clip.clip_id == self._active_clip.clip_id
        )
        if is_active:
            # 1. Alça de rotação (topo em y = -h/2 - 24)
            rot_handle_y = -h / 2.0 - 24.0
            if math.hypot(lx, ly - rot_handle_y) <= 14.0:
                return "rotate", geom

            # 2. Alças de escala nos 4 cantos
            corners = (
                ("scale_tl", -w / 2, -h / 2),
                ("scale_tr", w / 2, -h / 2),
                ("scale_br", w / 2, h / 2),
                ("scale_bl", -w / 2, h / 2),
            )
            for mode_name, hx, hy in corners:
                if math.hypot(lx - hx, ly - hy) <= 12.0:
                    return mode_name, geom

        # 3. Corpo (mover)
        if abs(lx) <= w / 2.0 and abs(ly) <= h / 2.0:
            return "move", geom

        return None, geom

    def _hit_test(self, pos: QPoint) -> tuple[str | None, tuple[float, float, float, float] | None]:
        if not self._clip_visible or self._active_clip is None or self._is_playing:
            return None, None
        return self._hit_test_clip(self._active_clip, pos)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_playing:
                self.play_toggle_requested.emit()
                event.accept()
                return
            if self._active_clip is not None:
                mode, geom = self._hit_test(pos)
                if mode and geom:
                    if (
                        mode == "move"
                        and not (self._active_clip.overlay_type in ("image", "text") or self._active_clip.is_image)
                    ):
                        for ov_clip in reversed(self._overlay_clips):
                            if ov_clip.clip_id == self._active_clip.clip_id:
                                continue
                            mode_ov, geom_ov = self._hit_test_clip(ov_clip, pos)
                            if mode_ov and geom_ov:
                                self.clip_selected.emit(ov_clip.clip_id)
                                event.accept()
                                return

                    t_offset = max(0.0, self._position - self._active_clip.start)
                    transform = self._active_clip.transform_at(t_offset)
                    cx, cy, w, h = geom
                    self._drag_mode = mode
                    self._drag_clip_id = self._active_clip.clip_id
                    self._drag_start_pos = pos
                    self._drag_init_x = transform.x
                    self._drag_init_y = transform.y
                    self._drag_init_scale = (transform.scale_x + transform.scale_y) / 2.0
                    self._drag_init_scale_x = transform.scale_x
                    self._drag_init_scale_y = transform.scale_y
                    self._drag_init_rot = transform.rotation
                    self._drag_init_opacity = transform.opacity
                    self._drag_init_time_offset = t_offset
                    self._drag_init_keyframes = self._active_clip.keyframes if self._active_clip.has_keyframes else ()
                    self._drag_init_dist = max(10.0, math.hypot(pos.x() - cx, pos.y() - cy))
                    self._drag_init_angle = math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))

                    # Captura visual imediata para feedback a 60 fps ao arrastar clipe visual
                    is_video_clip = (
                        self._active_clip.media is not None
                        and self._active_clip.media.has_video
                        and not self._active_clip.is_image
                        and not self._active_clip.audio_only
                        and self._active_clip.overlay_type not in ("text", "filter", "transition")
                    )
                    vrect = self._video_rect()
                    if (
                        is_video_clip
                        and self._pixmap is not None
                        and not self._pixmap.isNull()
                        and vrect.width() > 0
                        and vrect.height() > 0
                    ):
                        if self._drag_video_pixmap is None or self._drag_video_pixmap.isNull():
                            sx_pix = self._pixmap.width() / float(vrect.width())
                            sy_pix = self._pixmap.height() / float(vrect.height())
                            rel_cx = (cx - vrect.x()) * sx_pix
                            rel_cy = (cy - vrect.y()) * sy_pix
                            pix_w = max(1.0, w * sx_pix)
                            pix_h = max(1.0, h * sy_pix)
                            rot = transform.rotation

                            # Extrai a região do clipe desrotacionada para ser desenhada dinamicamente sob o cursor
                            extracted = QPixmap(int(round(pix_w)), int(round(pix_h)))
                            extracted.fill(Qt.GlobalColor.transparent)
                            p_ext = QPainter(extracted)
                            p_ext.setRenderHint(QPainter.RenderHint.Antialiasing)
                            p_ext.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                            p_ext.translate(pix_w / 2.0, pix_h / 2.0)
                            p_ext.rotate(-rot)
                            p_ext.translate(-rel_cx, -rel_cy)
                            p_ext.drawPixmap(0, 0, self._pixmap)
                            p_ext.end()
                            self._drag_video_pixmap = extracted

                            # Prepara a imagem base mascarando a posição inicial com preto absoluto
                            base = self._pixmap.copy()
                            p_base = QPainter(base)
                            p_base.setRenderHint(QPainter.RenderHint.Antialiasing)
                            p_base.translate(rel_cx, rel_cy)
                            p_base.rotate(rot)
                            p_base.fillRect(
                                QRectF(-pix_w / 2.0 - 0.5, -pix_h / 2.0 - 0.5, pix_w + 1.0, pix_h + 1.0),
                                Qt.GlobalColor.black,
                            )
                            p_base.end()
                            self._drag_base_pixmap = base
                    else:
                        self._drag_video_pixmap = None
                        self._drag_base_pixmap = None

                    if mode.startswith("scale_"):
                        if mode == "scale_tl":
                            sx, sy = -1.0, -1.0
                        elif mode == "scale_tr":
                            sx, sy = 1.0, -1.0
                        elif mode == "scale_br":
                            sx, sy = 1.0, 1.0
                        else:  # scale_bl
                            sx, sy = -1.0, 1.0

                        self._drag_sx = sx
                        self._drag_sy = sy
                        self._drag_w0 = max(1.0, w)
                        self._drag_h0 = max(1.0, h)

                        ox_local = -sx * (w / 2.0)
                        oy_local = -sy * (h / 2.0)
                        theta_rad = math.radians(transform.rotation)
                        cos_t = math.cos(theta_rad)
                        sin_t = math.sin(theta_rad)

                        self._drag_opp_x = cx + ox_local * cos_t - oy_local * sin_t
                        self._drag_opp_y = cy + ox_local * sin_t + oy_local * cos_t

                    event.accept()
                    return

            # Se não atingiu o clipe ativo, verifica itens sobrepostos (de cima para baixo)
            for ov_clip in reversed(self._overlay_clips):
                if self._active_clip is not None and ov_clip.clip_id == self._active_clip.clip_id:
                    continue
                mode_ov, geom_ov = self._hit_test_clip(ov_clip, pos)
                if mode_ov and geom_ov:
                    self.clip_selected.emit(ov_clip.clip_id)
                    event.accept()
                    return

            self.clicked_outside.emit()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._drag_mode and self._active_clip is not None:
            vrect = self._video_rect()
            geom = self._clip_geometry(self._active_clip)
            if not geom or vrect.width() <= 0 or vrect.height() <= 0:
                return

            cx, cy, w, h = geom
            new_x = self._drag_init_x
            new_y = self._drag_init_y
            new_scale = self._drag_init_scale
            new_scale_x = getattr(self, "_drag_init_scale_x", self._drag_init_scale)
            new_scale_y = getattr(self, "_drag_init_scale_y", self._drag_init_scale)
            new_rot = self._drag_init_rot

            if self._drag_mode == "move":
                dx = pos.x() - self._drag_start_pos.x()
                dy = pos.y() - self._drag_start_pos.y()
                raw_cx = vrect.x() + (self._drag_init_x + dx / vrect.width()) * vrect.width()
                raw_cy = vrect.y() + (self._drag_init_y + dy / vrect.height()) * vrect.height()

                final_cx = raw_cx
                final_cy = raw_cy
                self._snap_guide_x = None
                self._snap_guide_y = None

                if self._snap_enabled:
                    theta_rad = math.radians(self._drag_init_rot)
                    hw_proj = (w / 2.0) * abs(math.cos(theta_rad)) + (h / 2.0) * abs(math.sin(theta_rad))
                    hh_proj = (w / 2.0) * abs(math.sin(theta_rad)) + (h / 2.0) * abs(math.cos(theta_rad))

                    vx_left = float(vrect.x())
                    vx_right = float(vrect.x() + vrect.width())
                    vx_center = float(vrect.center().x())

                    vy_top = float(vrect.y())
                    vy_bottom = float(vrect.y() + vrect.height())
                    vy_center = float(vrect.center().y())

                    threshold = 14.0

                    snaps_x = [
                        (abs(vx_left - (raw_cx - hw_proj)), vx_left + hw_proj, vx_left),
                        (abs(vx_right - (raw_cx + hw_proj)), vx_right - hw_proj, vx_right),
                        (abs(vx_center - raw_cx), vx_center, vx_center),
                    ]
                    best_dist_x, best_cx, gx = min(snaps_x, key=lambda s: s[0])
                    if best_dist_x <= threshold:
                        final_cx = best_cx
                        self._snap_guide_x = gx

                    snaps_y = [
                        (abs(vy_top - (raw_cy - hh_proj)), vy_top + hh_proj, vy_top),
                        (abs(vy_bottom - (raw_cy + hh_proj)), vy_bottom - hh_proj, vy_bottom),
                        (abs(vy_center - raw_cy), vy_center, vy_center),
                    ]
                    best_dist_y, best_cy, gy = min(snaps_y, key=lambda s: s[0])
                    if best_dist_y <= threshold:
                        final_cy = best_cy
                        self._snap_guide_y = gy

                new_x = (final_cx - vrect.x()) / max(1.0, vrect.width())
                new_y = (final_cy - vrect.y()) / max(1.0, vrect.height())
            elif self._drag_mode.startswith("scale_"):
                vx = pos.x() - self._drag_opp_x
                vy = pos.y() - self._drag_opp_y

                theta_rad = math.radians(self._drag_init_rot)
                cos_t = math.cos(theta_rad)
                sin_t = math.sin(theta_rad)
                vlx = vx * cos_t + vy * sin_t
                vly = -vx * sin_t + vy * cos_t

                w_proj = self._drag_sx * vlx
                h_proj = self._drag_sy * vly
                w0 = self._drag_w0
                h0 = self._drag_h0
                diag_sq = w0 * w0 + h0 * h0
                raw_factor = (w_proj * w0 + h_proj * h0) / max(1.0, diag_sq)

                self._snap_guide_x = None
                self._snap_guide_y = None
                factor = raw_factor

                if self._snap_enabled:
                    hw0_proj = (w0 / 2.0) * abs(cos_t) + (h0 / 2.0) * abs(sin_t)
                    hh0_proj = (w0 / 2.0) * abs(sin_t) + (h0 / 2.0) * abs(cos_t)
                    dcx = (self._drag_sx * w0 / 2.0) * cos_t - (self._drag_sy * h0 / 2.0) * sin_t
                    dcy = (self._drag_sx * w0 / 2.0) * sin_t + (self._drag_sy * h0 / 2.0) * cos_t

                    vx_left = float(vrect.x())
                    vx_right = float(vrect.x() + vrect.width())
                    vx_center = float(vrect.x() + vrect.width() / 2.0)
                    vy_top = float(vrect.y())
                    vy_bottom = float(vrect.y() + vrect.height())
                    vy_center = float(vrect.y() + vrect.height() / 2.0)

                    threshold = 14.0
                    candidates: list[tuple[float, float, float | None, float | None]] = []

                    # 1. Borda X móvel (direita se sx > 0, esquerda se sx < 0)
                    kx_edge = dcx + (hw0_proj if self._drag_sx > 0 else -hw0_proj)
                    if abs(kx_edge) > 0.001:
                        targets_x = (vx_right, vx_center) if self._drag_sx > 0 else (vx_left, vx_center)
                        for target_x in targets_x:
                            cur_pos = self._drag_opp_x + raw_factor * kx_edge
                            dist = abs(cur_pos - target_x)
                            cand_factor = (target_x - self._drag_opp_x) / kx_edge
                            if dist <= threshold and cand_factor > 0.02:
                                candidates.append((dist, cand_factor, target_x, None))

                    # 2. Borda Y móvel (inferior se sy > 0, superior se sy < 0)
                    ky_edge = dcy + (hh0_proj if self._drag_sy > 0 else -hh0_proj)
                    if abs(ky_edge) > 0.001:
                        targets_y = (vy_bottom, vy_center) if self._drag_sy > 0 else (vy_top, vy_center)
                        for target_y in targets_y:
                            cur_pos = self._drag_opp_y + raw_factor * ky_edge
                            dist = abs(cur_pos - target_y)
                            cand_factor = (target_y - self._drag_opp_y) / ky_edge
                            if dist <= threshold and cand_factor > 0.02:
                                candidates.append((dist, cand_factor, None, target_y))

                    if candidates:
                        best_dist, best_factor, gx, gy = min(candidates, key=lambda c: c[0])
                        factor = best_factor
                        self._snap_guide_x = gx
                        self._snap_guide_y = gy

                        # Verifica se com esse factor a outra borda também alinha
                        if gx is not None and gy is None and abs(ky_edge) > 0.001:
                            targets_y = (vy_bottom, vy_center) if self._drag_sy > 0 else (vy_top, vy_center)
                            for ty in targets_y:
                                pos_y = self._drag_opp_y + factor * ky_edge
                                if abs(pos_y - ty) <= 2.0:
                                    self._snap_guide_y = ty
                                    break
                        elif gy is not None and gx is None and abs(kx_edge) > 0.001:
                            targets_x = (vx_right, vx_center) if self._drag_sx > 0 else (vx_left, vx_center)
                            for tx in targets_x:
                                pos_x = self._drag_opp_x + factor * kx_edge
                                if abs(pos_x - tx) <= 2.0:
                                    self._snap_guide_x = tx
                                    break

                min_scale = 0.05
                max_scale = 10.0
                new_scale = max(min_scale, min(max_scale, self._drag_init_scale * factor))
                new_scale_x = max(min_scale, min(max_scale, getattr(self, "_drag_init_scale_x", self._drag_init_scale) * factor))
                new_scale_y = max(min_scale, min(max_scale, getattr(self, "_drag_init_scale_y", self._drag_init_scale) * factor))
                actual_ratio = new_scale / max(0.001, self._drag_init_scale)

                new_w = w0 * actual_ratio
                new_h = h0 * actual_ratio

                cnx_local = self._drag_sx * (new_w / 2.0)
                cny_local = self._drag_sy * (new_h / 2.0)
                new_cx = self._drag_opp_x + cnx_local * cos_t - cny_local * sin_t
                new_cy = self._drag_opp_y + cnx_local * sin_t + cny_local * cos_t

                new_x = (new_cx - vrect.x()) / max(1.0, vrect.width())
                new_y = (new_cy - vrect.y()) / max(1.0, vrect.height())
            elif self._drag_mode == "rotate":
                cur_angle = math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))
                delta_angle = cur_angle - self._drag_init_angle
                raw_rot = (self._drag_init_rot + delta_angle) % 360.0
                new_rot = raw_rot
                self._snap_guide_rot = None

                if self._snap_enabled:
                    cardinals = (0.0, 90.0, 180.0, 270.0, 360.0)
                    best_diff = 999.0
                    best_target = raw_rot
                    for target in cardinals:
                        diff = (raw_rot - target + 180.0) % 360.0 - 180.0
                        if abs(diff) < abs(best_diff):
                            best_diff = diff
                            best_target = target % 360.0

                    if abs(best_diff) <= 4.0:
                        new_rot = best_target
                        self._snap_guide_rot = best_target

            if self._active_clip.has_keyframes and getattr(self, "_drag_init_keyframes", None):
                init_kfs = self._drag_init_keyframes
                t_offset = getattr(
                    self,
                    "_drag_init_time_offset",
                    max(0.0, min(self._active_clip.duration, self._position - self._active_clip.start)),
                )
                nearest = None
                for k in init_kfs:
                    if abs(k.time_offset - t_offset) <= 0.08:
                        nearest = k
                        break

                if nearest is not None:
                    target_time = nearest.time_offset
                    target_easing = nearest.easing
                    target_opacity = nearest.opacity

                    target_kf = Keyframe(
                        time_offset=target_time,
                        x=new_x,
                        y=new_y,
                        scale_x=new_scale_x,
                        scale_y=new_scale_y,
                        rotation=new_rot,
                        opacity=target_opacity,
                        easing=target_easing,
                    )
                    new_kfs = tuple(
                        sorted(
                            [k for k in init_kfs if abs(k.time_offset - target_time) >= 1e-4] + [target_kf],
                            key=lambda k: k.time_offset,
                        )
                    )
                else:
                    if self._drag_mode.startswith("scale_"):
                        dx_norm = new_x - self._drag_init_x
                        dy_norm = new_y - self._drag_init_y
                        first_k = init_kfs[0]
                        uniform_scale = all(
                            abs(k.scale_x - first_k.scale_x) < 0.005 and abs(k.scale_y - first_k.scale_y) < 0.005
                            for k in init_kfs
                        )
                        ratio_x = new_scale_x / max(0.001, getattr(self, "_drag_init_scale_x", self._drag_init_scale))
                        ratio_y = new_scale_y / max(0.001, getattr(self, "_drag_init_scale_y", self._drag_init_scale))
                        if uniform_scale:
                            new_kfs = tuple(
                                replace(k, x=k.x + dx_norm, y=k.y + dy_norm, scale_x=new_scale_x, scale_y=new_scale_y)
                                for k in init_kfs
                            )
                        else:
                            new_kfs = tuple(
                                replace(
                                    k,
                                    x=k.x + dx_norm,
                                    y=k.y + dy_norm,
                                    scale_x=max(0.05, min(10.0, k.scale_x * ratio_x)),
                                    scale_y=max(0.05, min(10.0, k.scale_y * ratio_y)),
                                )
                                for k in init_kfs
                            )
                    else:
                        target_time = t_offset
                        target_opacity = getattr(self, "_drag_init_opacity", 1.0)
                        target_kf = Keyframe(
                            time_offset=target_time,
                            x=new_x,
                            y=new_y,
                            scale_x=new_scale_x,
                            scale_y=new_scale_y,
                            rotation=new_rot,
                            opacity=target_opacity,
                            easing="linear",
                        )
                        new_kfs = tuple(
                            sorted(
                                [k for k in init_kfs if abs(k.time_offset - target_time) >= 1e-4] + [target_kf],
                                key=lambda k: k.time_offset,
                            )
                        )

                self._active_clip = replace(
                    self._active_clip,
                    keyframes=new_kfs,
                    x=new_x,
                    y=new_y,
                    scale=new_scale,
                    scale_x=new_scale_x,
                    scale_y=new_scale_y,
                    rotation=new_rot,
                )
            else:
                self._active_clip = replace(
                    self._active_clip,
                    x=new_x,
                    y=new_y,
                    scale=new_scale,
                    scale_x=new_scale_x,
                    scale_y=new_scale_y,
                    rotation=new_rot,
                )
            self.overlay_transformed.emit(self._drag_clip_id, new_x, new_y, new_scale, new_rot)
            self.update()
            event.accept()
            return

        mode, _ = self._hit_test(pos)
        if mode == "rotate":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif mode in ("scale_tl", "scale_br"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif mode in ("scale_tr", "scale_bl"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif mode == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._snap_guide_x = None
        self._snap_guide_y = None
        self._snap_guide_rot = None
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            clip_id = self._drag_clip_id
            self._drag_mode = None
            self._drag_clip_id = -1
            self._drag_init_keyframes = None
            self.overlay_transform_finished.emit(clip_id)
            self.update()
            event.accept()
            return
        self.update()
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if (self._pixmap is None or self._pixmap.isNull()) and self.text():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. Área total do monitor (pasteboard/área de trabalho cinza-escura suave)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        painter.fillPath(path, QColor("#141418"))
        painter.setClipPath(path)

        target = self._video_rect()

        # 2. Canvas efetivo do vídeo (preto absoluto onde o vídeo é exibido)
        painter.fillRect(target, Qt.GlobalColor.black)
        bg_pix = (
            self._drag_base_pixmap
            if (self._drag_base_pixmap is not None and not self._drag_base_pixmap.isNull())
            else self._pixmap
        )
        if bg_pix is not None and not bg_pix.isNull():
            painter.drawPixmap(target, bg_pix)

        clip = self._active_clip
        has_active = (
            self._clip_visible
            and not self._is_playing
            and clip is not None
            and clip.has_image
            and not clip.audio_only
            and clip.overlay_type not in ("filter", "transition")
            and clip.contains(self._position)
        )

        # 3. Desenho de clipe de vídeo ativo sendo arrastado sob o cursor
        if (
            has_active
            and clip.media is not None
            and clip.media.has_video
            and not clip.is_image
            and not clip.audio_only
            and clip.overlay_type not in ("text", "filter", "transition")
        ):
            if (
                self._drag_video_pixmap is not None
                and not self._drag_video_pixmap.isNull()
            ):
                geom = self._clip_geometry(clip)
                if geom:
                    t_offset = max(0.0, self._position - clip.start)
                    transform = clip.transform_at(t_offset)
                    cx, cy, w, h = geom
                    painter.save()
                    painter.setOpacity(1.0)
                    painter.translate(cx, cy)
                    painter.rotate(transform.rotation)
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    painter.drawPixmap(
                        QRectF(-w / 2.0, -h / 2.0, w, h),
                        self._drag_video_pixmap,
                        QRectF(self._drag_video_pixmap.rect()),
                    )
                    painter.restore()
            elif self._drag_mode is not None:
                geom = self._clip_geometry(clip)
                if geom:
                    t_offset = max(0.0, self._position - clip.start)
                    transform = clip.transform_at(t_offset)
                    cx, cy, w, h = geom
                    painter.save()
                    painter.translate(cx, cy)
                    painter.rotate(transform.rotation)
                    painter.fillRect(QRectF(-w / 2, -h / 2, w, h), QColor(0, 229, 255, 35))
                    painter.restore()

        # 4. Desenho de sobreposições de adicionais (imagens e textos) por cima do vídeo
        if not self._is_playing:
            clips_to_draw: list[Clip] = list(self._overlay_clips)
            if (
                has_active
                and (clip.overlay_type in ("image", "text") or clip.is_image)
                and clip.clip_id not in [c.clip_id for c in clips_to_draw]
            ):
                clips_to_draw.append(clip)

            for ov_clip in clips_to_draw:
                draw_clip = (
                    clip
                    if (has_active and clip.clip_id == ov_clip.clip_id)
                    else ov_clip
                )
                if draw_clip.overlay_type == "image" or draw_clip.is_image:
                    vrect = self._video_rect()
                    t_offset = max(0.0, self._position - draw_clip.start)
                    transform = draw_clip.transform_at(t_offset)
                    geom = self._image_overlay_geometry(draw_clip, transform, vrect)
                else:
                    geom = self._clip_geometry(draw_clip)
                if not geom:
                    continue
                t_offset = max(0.0, self._position - draw_clip.start)
                transform = draw_clip.transform_at(t_offset)
                cx, cy, w, h = geom
                painter.save()
                painter.setOpacity(transform.opacity)
                painter.translate(cx, cy)
                painter.rotate(transform.rotation)

                if draw_clip.overlay_type in ("image", "text") or draw_clip.is_image:
                    filters = self._clip_filters.get(draw_clip.clip_id, ())
                    img_pix = self._get_clip_pixmap(draw_clip, filters=filters)
                    if img_pix and not img_pix.isNull():
                        painter.save()
                        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        painter.drawPixmap(
                            QRectF(-w / 2.0, -h / 2.0, w, h),
                            img_pix,
                            QRectF(img_pix.rect()),
                        )
                        painter.restore()
                    elif draw_clip.overlay_type == "text":
                        painter.save()
                        scale_factor = target.width() / max(1.0, float(self._proj_w))
                        px_size = max(8, int(draw_clip.font_size * scale_factor * draw_clip.scale))
                        f = QFont(draw_clip.font_family or "Sans Serif", px_size)
                        f.setBold(draw_clip.font_bold)
                        f.setItalic(draw_clip.font_italic)
                        painter.setFont(f)
                        painter.setPen(QColor(draw_clip.text_color or "#ffffff"))
                        painter.drawText(
                            QRectF(-w / 2, -h / 2, w, h),
                            Qt.AlignmentFlag.AlignCenter,
                            draw_clip.text_content or "Texto",
                        )
                        painter.restore()
                painter.restore()

        # 5. Máscara de delimitação e atenuação (dimming) fora da região efetiva do vídeo
        outside_path = QPainterPath()
        outside_path.addRect(QRectF(self.rect()))
        target_path = QPainterPath()
        target_path.addRect(QRectF(target))
        dim_path = outside_path.subtracted(target_path)
        painter.fillPath(dim_path, QColor(10, 10, 14, 175))

        # 5. Moldura de destaque da região efetiva do vídeo
        border_pen = QPen(
            QColor("#00e5ff") if has_active else QColor("#444452"),
            1.5 if has_active else 1.0,
            Qt.PenStyle.SolidLine,
        )
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(target))

        # Linhas guias de alinhamento magnético (Snapping)
        if self._snap_guide_x is not None or self._snap_guide_y is not None:
            painter.save()
            guide_pen = QPen(QColor("#00e5ff"), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            if self._snap_guide_x is not None:
                gx = self._snap_guide_x
                painter.drawLine(QPointF(gx, target.top()), QPointF(gx, target.bottom()))
            if self._snap_guide_y is not None:
                gy = self._snap_guide_y
                painter.drawLine(QPointF(target.left(), gy), QPointF(target.right(), gy))
            painter.restore()

        # 6. Alças de controle e Bounding Box no topo de tudo
        if has_active:
            t_offset = max(0.0, self._position - clip.start)
            transform = clip.transform_at(t_offset)
            if clip.overlay_type == "image" or clip.is_image:
                vrect = self._video_rect()
                geom = self._image_overlay_geometry(clip, transform, vrect)
            else:
                geom = self._clip_geometry(clip)
            if geom:
                cx, cy, w, h = geom
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(transform.rotation)

                pen = QPen(QColor("#00e5ff"), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(-w / 2, -h / 2, w, h))

                painter.setPen(QPen(QColor("#00e5ff"), 1.5, Qt.PenStyle.SolidLine))
                painter.drawLine(QPointF(0, -h / 2), QPointF(0, -h / 2 - 24))
                painter.setBrush(QColor("#00e5ff"))
                painter.drawEllipse(QPointF(0, -h / 2 - 24), 5, 5)

                if self._snap_guide_rot is not None:
                    painter.save()
                    f_rot = QFont("Sans Serif", 9)
                    f_rot.setBold(True)
                    painter.setFont(f_rot)
                    painter.setPen(QColor("#00e5ff"))
                    painter.drawText(
                        QRectF(-30, -h / 2 - 46, 60, 20),
                        Qt.AlignmentFlag.AlignCenter,
                        f"{int(self._snap_guide_rot)}°",
                    )
                    painter.restore()

                painter.setPen(QPen(QColor("#000000"), 1.0))
                painter.setBrush(QColor("#ffffff"))
                for hx, hy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
                    painter.drawRect(QRectF(hx - 4, hy - 4, 8, 8))

                painter.restore()

        painter.end()


class _ClipPropertiesWidget(QWidget):
    """Aba de propriedades do clipe com visualização e edição numérica precisa."""

    property_changed = Signal(int, dict)  # clip_id, dict de alterações
    seek_requested = Signal(float)  # timestamp para navegação do cursor
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "plain")
        self._clip_id: int = -1
        self._clip: Clip | None = None
        self._proj_w: int = 1920
        self._proj_h: int = 1080
        self._base_w: float = 1920.0
        self._base_h: float = 1080.0
        self._aspect_ratio: float = 16.0 / 9.0
        self._updating: bool = False
        self._last_w: int = 100
        self._last_h: int = 100
        self._last_x: float = 0.5
        self._last_y: float = 0.5
        self._last_rot: float = 0.0
        self._playhead_pos: float = 0.0

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(self._scroll)

        self._container = QWidget()
        self._container.setProperty("role", "plain")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(8)
        self._scroll.setWidget(self._container)

        self._build_ui()

    def _build_ui(self) -> None:
        # Header com título e botão fechar
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._title_lbl = QLabel("Propriedades")
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title_lbl.setMinimumWidth(0)
        f_title = self._title_lbl.font()
        f_title.setBold(True)
        f_title.setPointSize(f_title.pointSize() + 1)
        self._title_lbl.setFont(f_title)
        header.addWidget(self._title_lbl, 1)

        btn_close = QPushButton("✕")
        btn_close.setToolTip("Fechar aba de propriedades")
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Ubuntu', sans-serif; font-size: 14px; font-weight: bold; border-radius: 4px; padding: 0px; margin: 0px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; text-align: center; } "
            "QPushButton:hover { background: #e11d48; color: #ffffff; } "
            "QPushButton:pressed { background: #be123c; color: #ffffff; }"
        )
        btn_close.clicked.connect(self.close_requested.emit)
        header.addWidget(btn_close, 0)
        self._layout.addLayout(header)

        self._lbl_clip_type = QLabel("")
        self._lbl_clip_type.setProperty("role", "dim")
        self._layout.addWidget(self._lbl_clip_type)

        # Grupo Transformação (Posição, Tamanho, Travar proporção, Escala, Rotação)
        self._transform_group = QGroupBox("Transformação")
        grid = QGridLayout(self._transform_group)
        grid.setContentsMargins(6, 8, 6, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        lbl_x = QLabel("Posição X:")
        self._spin_x = QSpinBox()
        self._spin_x.setRange(-10000, 10000)
        self._spin_x.setSuffix(" px")
        self._spin_x.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin_x.valueChanged.connect(self._on_x_changed)

        lbl_y = QLabel("Posição Y:")
        self._spin_y = QSpinBox()
        self._spin_y.setRange(-10000, 10000)
        self._spin_y.setSuffix(" px")
        self._spin_y.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin_y.valueChanged.connect(self._on_y_changed)

        lbl_w = QLabel("Largura:")
        self._spin_w = QSpinBox()
        self._spin_w.setRange(1, 20000)
        self._spin_w.setSuffix(" px")
        self._spin_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin_w.valueChanged.connect(self._on_w_changed)

        lbl_h = QLabel("Altura:")
        self._spin_h = QSpinBox()
        self._spin_h.setRange(1, 20000)
        self._spin_h.setSuffix(" px")
        self._spin_h.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin_h.valueChanged.connect(self._on_h_changed)

        # Alinhamento no eixo X das 4 coordenadas
        grid.addWidget(lbl_x, 0, 0)
        grid.addWidget(self._spin_x, 0, 1)

        grid.addWidget(lbl_y, 1, 0)
        grid.addWidget(self._spin_y, 1, 1)

        grid.addWidget(lbl_w, 2, 0)
        grid.addWidget(self._spin_w, 2, 1)

        grid.addWidget(lbl_h, 3, 0)
        grid.addWidget(self._spin_h, 3, 1)

        # Trava de proporção
        self._chk_lock_ratio = QCheckBox("Travar proporção")
        self._chk_lock_ratio.setChecked(True)
        self._chk_lock_ratio.toggled.connect(self._on_lock_ratio_toggled)
        grid.addWidget(self._chk_lock_ratio, 4, 0, 1, 2)

        # Escala
        lbl_scale = QLabel("Escala:")
        self._spin_scale = QDoubleSpinBox()
        self._spin_scale.setRange(0.05, 10.00)
        self._spin_scale.setSingleStep(0.05)
        self._spin_scale.setDecimals(2)
        self._spin_scale.setSuffix("x")
        self._spin_scale.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin_scale.valueChanged.connect(self._on_scale_changed)
        grid.addWidget(lbl_scale, 5, 0)
        grid.addWidget(self._spin_scale, 5, 1)

        # Rotação
        lbl_rot = QLabel("Rotação:")
        self._spin_rot = QDoubleSpinBox()
        self._spin_rot.setRange(0.0, 360.0)
        self._spin_rot.setSingleStep(1.0)
        self._spin_rot.setDecimals(1)
        self._spin_rot.setSuffix("°")
        self._spin_rot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin_rot.valueChanged.connect(self._on_rot_changed)
        grid.addWidget(lbl_rot, 6, 0)
        grid.addWidget(self._spin_rot, 6, 1)

        # Presets de Rotação
        row_presets = QHBoxLayout()
        row_presets.setSpacing(4)
        for ang in (0.0, 90.0, 180.0, 270.0):
            btn_ang = QPushButton(f"{int(ang)}°")
            btn_ang.setProperty("role", "transport")
            btn_ang.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn_ang.setFixedHeight(24)
            btn_ang.clicked.connect(lambda _, a=ang: self._set_preset_rotation(a))
            row_presets.addWidget(btn_ang)
        grid.addLayout(row_presets, 7, 0, 1, 2)

        # Opacidade
        lbl_opacity = QLabel(strings.EDIT_OPACITY)
        self._slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self._slider_opacity.setRange(0, 100)
        self._slider_opacity.setValue(100)
        self._slider_opacity.valueChanged.connect(self._on_opacity_slider_changed)

        self._spin_opacity = QSpinBox()
        self._spin_opacity.setRange(0, 100)
        self._spin_opacity.setValue(100)
        self._spin_opacity.setSuffix("%")
        self._spin_opacity.setFixedWidth(64)
        self._spin_opacity.valueChanged.connect(self._on_opacity_spin_changed)

        row_op = QHBoxLayout()
        row_op.setSpacing(6)
        row_op.addWidget(self._slider_opacity, 1)
        row_op.addWidget(self._spin_opacity)
        grid.addWidget(lbl_opacity, 8, 0)
        grid.addLayout(row_op, 8, 1)

        self._layout.addWidget(self._transform_group)

        # Grupo Animação / Quadros-chave
        self._animation_group = QGroupBox(strings.EDIT_KEYFRAME_TITLE)
        anim_layout = QVBoxLayout(self._animation_group)
        anim_layout.setContentsMargins(6, 8, 6, 6)
        anim_layout.setSpacing(6)

        # Barra de navegação e adição de quadros-chave
        row_kf = QHBoxLayout()
        row_kf.setSpacing(4)

        self._btn_kf_prev = QPushButton("◀")
        self._btn_kf_prev.setToolTip(strings.EDIT_KEYFRAME_PREV)
        self._btn_kf_prev.setProperty("role", "transport")
        self._btn_kf_prev.setFixedSize(28, 26)
        self._btn_kf_prev.clicked.connect(self._on_prev_keyframe)
        row_kf.addWidget(self._btn_kf_prev)

        self._btn_kf_toggle = QPushButton("◇")
        self._btn_kf_toggle.setToolTip(strings.EDIT_KEYFRAME_TOGGLE)
        self._btn_kf_toggle.setFixedSize(32, 26)
        self._btn_kf_toggle.clicked.connect(self._on_toggle_keyframe)
        row_kf.addWidget(self._btn_kf_toggle)

        self._btn_kf_next = QPushButton("▶")
        self._btn_kf_next.setToolTip(strings.EDIT_KEYFRAME_NEXT)
        self._btn_kf_next.setProperty("role", "transport")
        self._btn_kf_next.setFixedSize(28, 26)
        self._btn_kf_next.clicked.connect(self._on_next_keyframe)
        row_kf.addWidget(self._btn_kf_next)

        self._lbl_kf_status = QLabel("Sem quadros-chave")
        self._lbl_kf_status.setProperty("role", "dim")
        row_kf.addWidget(self._lbl_kf_status, 1)

        anim_layout.addLayout(row_kf)

        # Curva de Interpolação (Easing)
        row_easing = QHBoxLayout()
        row_easing.setSpacing(6)
        row_easing.addWidget(QLabel(strings.EDIT_KEYFRAME_EASING))
        self._combo_easing = QComboBox()
        self._combo_easing.addItem("Linear (Constante)", "linear")
        self._combo_easing.addItem("Suave ao Entrar (Ease In)", "ease_in")
        self._combo_easing.addItem("Suave ao Sair (Ease Out)", "ease_out")
        self._combo_easing.addItem("Suave Completo (Ease In-Out)", "ease_in_out")
        self._combo_easing.addItem("Degrau (Hold)", "hold")
        self._combo_easing.currentIndexChanged.connect(self._on_easing_changed)
        row_easing.addWidget(self._combo_easing, 1)
        anim_layout.addLayout(row_easing)

        # Presets de Efeitos Rápidos
        row_presets_anim = QHBoxLayout()
        row_presets_anim.setSpacing(6)
        row_presets_anim.addWidget(QLabel("Efeito Rápido:"))
        self._combo_presets = QComboBox()
        self._combo_presets.addItem("— Selecionar preset —", "")
        self._combo_presets.addItem(strings.EDIT_PRESET_SLIDE_UP, "slide_up")
        self._combo_presets.addItem(strings.EDIT_PRESET_SLIDE_DOWN, "slide_down")
        self._combo_presets.addItem(strings.EDIT_PRESET_SLIDE_LEFT, "slide_left")
        self._combo_presets.addItem(strings.EDIT_PRESET_SLIDE_RIGHT, "slide_right")
        self._combo_presets.addItem(strings.EDIT_PRESET_FADE_IN, "fade_in")
        self._combo_presets.addItem(strings.EDIT_PRESET_ZOOM_IN, "zoom_in")
        self._combo_presets.addItem(strings.EDIT_PRESET_SPIN_IN, "spin_in")
        self._combo_presets.addItem(strings.EDIT_PRESET_CLEAR, "clear")
        self._combo_presets.currentIndexChanged.connect(self._on_preset_selected)
        row_presets_anim.addWidget(self._combo_presets, 1)
        anim_layout.addLayout(row_presets_anim)

        self._layout.addWidget(self._animation_group)

        # Grupo Chroma Key (Fundo Verde)
        self._chromakey_group = QGroupBox("Fundo Verde (Chroma Key)")
        ck_layout = QVBoxLayout(self._chromakey_group)
        ck_layout.setContentsMargins(6, 8, 6, 6)
        ck_layout.setSpacing(6)

        self._chk_chroma = QCheckBox("Ativar remoção de fundo verde")
        self._chk_chroma.toggled.connect(self._on_chroma_toggled)
        ck_layout.addWidget(self._chk_chroma)

        row_color = QHBoxLayout()
        row_color.setSpacing(6)
        row_color.addWidget(QLabel("Cor a remover:"))
        self._btn_chroma_color = QPushButton()
        self._btn_chroma_color.setFixedSize(40, 22)
        self._btn_chroma_color.setToolTip("Clique para escolher a cor a ser removida")
        self._btn_chroma_color.clicked.connect(self._choose_chroma_color)
        row_color.addWidget(self._btn_chroma_color)
        row_color.addStretch(1)

        for hex_col, c_tip in (
            ("#00FF00", "Verde Padrão"),
            ("#00B140", "Verde Studio"),
            ("#0000FF", "Azul"),
        ):
            btn_preset = QPushButton()
            btn_preset.setFixedSize(22, 22)
            btn_preset.setToolTip(f"{c_tip} ({hex_col})")
            btn_preset.setStyleSheet(
                f"QPushButton {{ background: {hex_col}; border: 1px solid #555; border-radius: 3px; }} "
                f"QPushButton:hover {{ border: 2px solid #fff; }}"
            )
            btn_preset.clicked.connect(lambda _, c=hex_col: self._set_chroma_color(c))
            row_color.addWidget(btn_preset)
        ck_layout.addLayout(row_color)

        row_sim = QHBoxLayout()
        row_sim.setSpacing(6)
        row_sim.addWidget(QLabel("Tolerância:"))
        self._slider_similarity = QSlider(Qt.Orientation.Horizontal)
        self._slider_similarity.setRange(1, 100)
        self._slider_similarity.setValue(25)
        self._slider_similarity.valueChanged.connect(self._on_similarity_slider_changed)
        row_sim.addWidget(self._slider_similarity, 1)

        self._spin_similarity = QSpinBox()
        self._spin_similarity.setRange(1, 100)
        self._spin_similarity.setValue(25)
        self._spin_similarity.setSuffix("%")
        self._spin_similarity.setFixedWidth(64)
        self._spin_similarity.valueChanged.connect(self._on_similarity_spin_changed)
        row_sim.addWidget(self._spin_similarity)
        ck_layout.addLayout(row_sim)

        row_blend = QHBoxLayout()
        row_blend.setSpacing(6)
        row_blend.addWidget(QLabel("Suavização:"))
        self._slider_blend = QSlider(Qt.Orientation.Horizontal)
        self._slider_blend.setRange(0, 100)
        self._slider_blend.setValue(10)
        self._slider_blend.valueChanged.connect(self._on_blend_slider_changed)
        row_blend.addWidget(self._slider_blend, 1)

        self._spin_blend = QSpinBox()
        self._spin_blend.setRange(0, 100)
        self._spin_blend.setValue(10)
        self._spin_blend.setSuffix("%")
        self._spin_blend.setFixedWidth(64)
        self._spin_blend.valueChanged.connect(self._on_blend_spin_changed)
        row_blend.addWidget(self._spin_blend)
        ck_layout.addLayout(row_blend)

        self._layout.addWidget(self._chromakey_group)

        # Grupo Transição (quando um clipe de transição é selecionado)
        self._transition_group = QGroupBox("Transição de Vídeo")
        t_layout = QVBoxLayout(self._transition_group)
        t_layout.setContentsMargins(6, 8, 6, 6)
        t_layout.setSpacing(6)

        t_layout.addWidget(QLabel("Efeito:"))
        self._combo_trans_type = QComboBox()
        self._combo_trans_type.addItem("🌑 Fade", "fade")
        self._combo_trans_type.addItem("⬛ Fade para Preto", "fadeblack")
        self._combo_trans_type.addItem("⬜ Fade para Branco", "fadewhite")
        self._combo_trans_type.addItem("🎬 Dissolve", "dissolve")
        self._combo_trans_type.addItem("◀ Wipe para Esquerda", "wipeleft")
        self._combo_trans_type.addItem("▶ Wipe para Direita", "wiperight")
        self._combo_trans_type.addItem("◀ Slide para Esquerda", "slideleft")
        self._combo_trans_type.addItem("▶ Slide para Direita", "slideright")
        self._combo_trans_type.currentIndexChanged.connect(self._on_trans_type_changed)
        t_layout.addWidget(self._combo_trans_type)

        dur_row = QHBoxLayout()
        dur_row.setSpacing(6)
        dur_row.addWidget(QLabel("Duração:"))
        self._spin_trans_dur = QDoubleSpinBox()
        self._spin_trans_dur.setRange(MIN_TRANSITION_DURATION, 5.0)
        self._spin_trans_dur.setSingleStep(0.1)
        self._spin_trans_dur.setValue(1.0)
        self._spin_trans_dur.setSuffix(" s")
        self._spin_trans_dur.valueChanged.connect(self._on_trans_dur_changed)
        dur_row.addWidget(self._spin_trans_dur, 1)
        t_layout.addLayout(dur_row)

        self._chk_trans_additionals = QCheckBox(
            strings.EDIT_TRANSITION_AFFECT_ADDITIONALS
        )
        self._chk_trans_additionals.setToolTip(
            strings.EDIT_TRANSITION_AFFECT_ADDITIONALS_TIP
        )
        self._chk_trans_additionals.toggled.connect(
            self._on_trans_additionals_toggled
        )
        t_layout.addWidget(self._chk_trans_additionals)

        self._layout.addWidget(self._transition_group)
        self._layout.addStretch(1)

    def clear(self) -> None:
        self._clip_id = -1
        self._clip = None
        self._title_lbl.setText("Propriedades")
        self._title_lbl.setToolTip("")
        self._lbl_clip_type.setText(strings.EDIT_CLIP_NONE)
        self._transform_group.setVisible(False)
        self._animation_group.setVisible(False)
        self._chromakey_group.setVisible(False)
        self._transition_group.setVisible(False)

    def load_clip(self, clip: Clip, proj_w: int, proj_h: int) -> None:
        self._updating = True
        try:
            self._clip_id = clip.clip_id
            self._clip = clip
            self._proj_w = max(1, proj_w)
            self._proj_h = max(1, proj_h)

            if clip.overlay_type == "transition":
                t_labels = {
                    "fade": "Fade",
                    "fadeblack": "Fade para Preto",
                    "fadewhite": "Fade para Branco",
                    "dissolve": "Dissolve",
                    "wipeleft": "Wipe para Esquerda",
                    "wiperight": "Wipe para Direita",
                    "slideleft": "Slide para Esquerda",
                    "slideright": "Slide para Direita",
                }
                tname = clip.transition_name or "fade"
                name = f"Transição: {t_labels.get(tname, tname)}"
            else:
                name = clip.media.name if clip.media else (clip.text_content or clip.overlay_type.title())

            display_name = name if len(name) <= 32 else f"{name[:29]}..."
            self._title_lbl.setText(f"Propriedades: {display_name}")
            self._title_lbl.setToolTip(f"Propriedades: {name}")
            self._lbl_clip_type.setText(f"ID #{clip.clip_id} · {clip.overlay_type.title() if clip.overlay_type != 'none' else 'Mídia'}")

            # Calcular base_w e base_h
            if clip.overlay_type == "text":
                font = QFont(clip.font_family or "Sans Serif", clip.font_size or 36)
                font.setBold(clip.font_bold)
                font.setItalic(clip.font_italic)
                fm = QFontMetrics(font)
                text = clip.text_content or "Texto"
                stroke_w = max(0, clip.stroke_width)
                pad = 20 + stroke_w
                lines = text.splitlines() if text else ["Texto"]
                line_spacing = fm.lineSpacing()
                total_text_h = (len(lines) - 1) * line_spacing + fm.ascent() + fm.descent()
                max_tw = max((fm.horizontalAdvance(l) for l in lines), default=100)
                self._base_w = float(max(40, ((max_tw + pad * 2 + 3) // 4) * 4))
                self._base_h = float(max(40, ((total_text_h + pad * 2 + 3) // 4) * 4))
            elif clip.overlay_type == "image" or clip.is_image:
                if clip.media is not None:
                    bw, bh = image_base_size(clip.media.width, clip.media.height, self._proj_w, self._proj_h)
                    self._base_w, self._base_h = float(bw), float(bh)
                else:
                    self._base_w, self._base_h = 400.0, 300.0
            elif clip.media is not None and clip.media.has_video:
                mw = clip.media.width or self._proj_w
                mh = clip.media.height or self._proj_h
                bw, bh = fit_size(mw, mh, self._proj_w, self._proj_h)
                self._base_w, self._base_h = float(bw), float(bh)
            else:
                self._base_w = float(self._proj_w)
                self._base_h = float(self._proj_h)

            sx = getattr(clip, "scale_x", clip.scale)
            sy = getattr(clip, "scale_y", clip.scale)
            cur_w = max(1, round(self._base_w * sx))
            cur_h = max(1, round(self._base_h * sy))
            self._aspect_ratio = max(0.001, cur_w / max(1.0, float(cur_h)))

            is_trans = clip.overlay_type == "transition"
            has_image_media = bool(clip.media and (clip.media.has_video or clip.is_image))
            can_chroma = has_image_media and clip.overlay_type not in ("text", "filter", "transition")

            can_animate = not is_trans and (clip.has_image or clip.is_additional)
            self._transform_group.setVisible(can_animate)
            self._animation_group.setVisible(can_animate)
            self._chromakey_group.setVisible(can_chroma)
            self._transition_group.setVisible(is_trans)

            if is_trans:
                idx = self._combo_trans_type.findData(clip.transition_name or "fade")
                if idx >= 0:
                    self._combo_trans_type.setCurrentIndex(idx)
                self._spin_trans_dur.setValue(clip.duration)
                self._chk_trans_additionals.setChecked(
                    clip.transition_affects_additionals
                )

            if can_chroma:
                self._chk_chroma.setChecked(clip.chromakey_enabled)
                self._set_chroma_color(clip.chromakey_color or "#00FF00")
                sim_pct = int(round(clip.chromakey_similarity * 100))
                blend_pct = int(round(clip.chromakey_blend * 100))
                self._spin_similarity.setValue(max(1, min(100, sim_pct)))
                self._spin_blend.setValue(max(0, min(100, blend_pct)))
                self._enable_chroma_controls(clip.chromakey_enabled)

            if can_animate:
                px = round(clip.x * self._proj_w)
                py = round(clip.y * self._proj_h)
                self._spin_x.setValue(px)
                self._spin_y.setValue(py)
                self._spin_w.setValue(cur_w)
                self._spin_h.setValue(cur_h)
                self._spin_scale.setValue((sx + sy) / 2.0)
                self._spin_rot.setValue(clip.rotation % 360.0)
                op_pct = int(round(clip.opacity * 100))
                self._slider_opacity.setValue(op_pct)
                self._spin_opacity.setValue(op_pct)
                self._refresh_keyframe_controls()

            self._last_w = cur_w
            self._last_h = cur_h
            self._last_x = clip.x
            self._last_y = clip.y
            self._last_rot = clip.rotation
        finally:
            self._updating = False

    def _on_chroma_toggled(self, checked: bool) -> None:
        self._enable_chroma_controls(checked)
        if self._updating or self._clip_id < 0:
            return
        self.property_changed.emit(self._clip_id, {"chromakey_enabled": checked})

    def _enable_chroma_controls(self, enabled: bool) -> None:
        self._btn_chroma_color.setEnabled(enabled)
        self._slider_similarity.setEnabled(enabled)
        self._spin_similarity.setEnabled(enabled)
        self._slider_blend.setEnabled(enabled)
        self._spin_blend.setEnabled(enabled)

    def _choose_chroma_color(self) -> None:
        cur_col = QColor(getattr(self, "_current_chroma_color", "#00FF00"))
        chosen = QColorDialog.getColor(cur_col, self, "Escolher cor para remover")
        if chosen.isValid():
            self._set_chroma_color(chosen.name().upper())

    def _set_chroma_color(self, hex_color: str) -> None:
        self._current_chroma_color = hex_color
        self._btn_chroma_color.setStyleSheet(
            f"QPushButton {{ background: {hex_color}; border: 1px solid #888; border-radius: 4px; }} "
            f"QPushButton:hover {{ border: 1px solid #fff; }}"
        )
        if self._updating or self._clip_id < 0:
            return
        self.property_changed.emit(self._clip_id, {"chromakey_color": hex_color})

    def _on_similarity_slider_changed(self, val: int) -> None:
        if self._spin_similarity.value() != val:
            self._spin_similarity.setValue(val)

    def _on_similarity_spin_changed(self, val: int) -> None:
        if self._slider_similarity.value() != val:
            self._slider_similarity.setValue(val)
        if self._updating or self._clip_id < 0:
            return
        self.property_changed.emit(self._clip_id, {"chromakey_similarity": val / 100.0})

    def _on_blend_slider_changed(self, val: int) -> None:
        if self._spin_blend.value() != val:
            self._spin_blend.setValue(val)

    def _on_blend_spin_changed(self, val: int) -> None:
        if self._slider_blend.value() != val:
            self._slider_blend.setValue(val)
        if self._updating or self._clip_id < 0:
            return
        self.property_changed.emit(self._clip_id, {"chromakey_blend": val / 100.0})

    def _on_trans_type_changed(self, index: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        data = self._combo_trans_type.itemData(index)
        if data:
            self.property_changed.emit(self._clip_id, {"transition_name": data})

    def _on_trans_dur_changed(self, val: float) -> None:
        if self._updating or self._clip_id < 0:
            return
        self.property_changed.emit(self._clip_id, {"duration": val})

    def _on_trans_additionals_toggled(self, checked: bool) -> None:
        if self._updating or self._clip_id < 0:
            return
        self.property_changed.emit(
            self._clip_id,
            {"transition_affects_additionals": checked},
        )

    def set_playhead_position(self, pos: float) -> None:
        self._playhead_pos = pos
        self._refresh_keyframe_controls()

    def _refresh_keyframe_controls(self) -> None:
        if self._clip is None or not hasattr(self, "_animation_group"):
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        current_kf = self._clip.nearest_keyframe(t_offset, tolerance=0.08)

        if current_kf is not None:
            self._btn_kf_toggle.setText("◆")
            self._btn_kf_toggle.setToolTip(strings.EDIT_KEYFRAME_REMOVE)
            self._btn_kf_toggle.setStyleSheet(
                "QPushButton { background: #2563eb; color: #ffffff; border: 1px solid #60a5fa; border-radius: 4px; font-weight: bold; font-size: 14px; }"
                " QPushButton:hover { background: #1d4ed8; }"
            )
            idx = self._combo_easing.findData(current_kf.easing)
            if idx >= 0 and self._combo_easing.currentIndex() != idx:
                self._updating = True
                try:
                    self._combo_easing.setCurrentIndex(idx)
                finally:
                    self._updating = False
        else:
            self._btn_kf_toggle.setText("◇")
            self._btn_kf_toggle.setToolTip(strings.EDIT_KEYFRAME_ADD)
            self._btn_kf_toggle.setStyleSheet(
                "QPushButton { background: #2a2a35; color: #e4e4e7; border: 1px solid #444455; border-radius: 4px; font-weight: bold; font-size: 14px; }"
                " QPushButton:hover { background: #3f3f4e; border-color: #71717a; }"
            )

        count = len(self._clip.keyframes)
        if count > 0:
            self._lbl_kf_status.setText(f"{count} quadro(s)-chave")
            has_prev = any(k.time_offset < t_offset - 0.05 for k in self._clip.keyframes)
            has_next = any(k.time_offset > t_offset + 0.05 for k in self._clip.keyframes)
            self._btn_kf_prev.setEnabled(has_prev)
            self._btn_kf_next.setEnabled(has_next)

            # Sincroniza campos numéricos com o estado interpolado no instante do cursor
            self._updating = True
            try:
                cur_t = self._clip.transform_at(t_offset)
                cur_w = max(1, round(self._base_w * cur_t.scale_x))
                cur_h = max(1, round(self._base_h * cur_t.scale_y))
                if hasattr(self, "_spin_x"):
                    self._spin_x.setValue(round(cur_t.x * self._proj_w))
                if hasattr(self, "_spin_y"):
                    self._spin_y.setValue(round(cur_t.y * self._proj_h))
                if hasattr(self, "_spin_w"):
                    self._spin_w.setValue(cur_w)
                if hasattr(self, "_spin_h"):
                    self._spin_h.setValue(cur_h)
                if hasattr(self, "_spin_scale"):
                    self._spin_scale.setValue((cur_t.scale_x + cur_t.scale_y) / 2.0)
                if hasattr(self, "_spin_rot"):
                    self._spin_rot.setValue(cur_t.rotation % 360.0)
                if hasattr(self, "_slider_opacity") and hasattr(self, "_spin_opacity"):
                    op_pct = int(round(cur_t.opacity * 100))
                    self._slider_opacity.setValue(op_pct)
                    self._spin_opacity.setValue(op_pct)
                self._last_w = cur_w
                self._last_h = cur_h
                self._last_x = cur_t.x
                self._last_y = cur_t.y
                self._last_rot = cur_t.rotation
            finally:
                self._updating = False
        else:
            self._lbl_kf_status.setText("Sem quadros-chave")
            self._btn_kf_prev.setEnabled(False)
            self._btn_kf_next.setEnabled(False)

    def _on_opacity_slider_changed(self, val: int) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._spin_opacity.setValue(val)
        finally:
            self._updating = False
        self._emit_opacity_change(val / 100.0)

    def _on_opacity_spin_changed(self, val: int) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._slider_opacity.setValue(val)
        finally:
            self._updating = False
        self._emit_opacity_change(val / 100.0)

    def _emit_opacity_change(self, opacity: float) -> None:
        if self._clip_id < 0 or self._clip is None:
            return
        if self._clip.has_keyframes:
            t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
            nearest = self._clip.nearest_keyframe(t_offset, tolerance=0.08)
            if nearest:
                updated_kf = replace(nearest, opacity=opacity)
            else:
                cur_t = self._clip.transform_at(t_offset)
                updated_kf = Keyframe(
                    time_offset=t_offset,
                    x=cur_t.x,
                    y=cur_t.y,
                    scale_x=cur_t.scale_x,
                    scale_y=cur_t.scale_y,
                    rotation=cur_t.rotation,
                    opacity=opacity,
                    easing="linear",
                )
            updated_clip = self._clip.with_keyframe(updated_kf)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": updated_clip.keyframes, "opacity": opacity})
            self._refresh_keyframe_controls()
        else:
            self.property_changed.emit(self._clip_id, {"opacity": opacity})

    def _on_prev_keyframe(self) -> None:
        if self._clip is None or not self._clip.keyframes:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        prev_kfs = [k for k in self._clip.keyframes if k.time_offset < t_offset - 0.05]
        if prev_kfs:
            target_kf = max(prev_kfs, key=lambda k: k.time_offset)
            self.seek_requested.emit(self._clip.start + target_kf.time_offset)

    def _on_next_keyframe(self) -> None:
        if self._clip is None or not self._clip.keyframes:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        next_kfs = [k for k in self._clip.keyframes if k.time_offset > t_offset + 0.05]
        if next_kfs:
            target_kf = min(next_kfs, key=lambda k: k.time_offset)
            self.seek_requested.emit(self._clip.start + target_kf.time_offset)

    def _on_toggle_keyframe(self) -> None:
        if self._clip is None or self._clip_id < 0:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        nearest = self._clip.nearest_keyframe(t_offset, tolerance=0.08)
        if nearest is not None:
            updated_clip = self._clip.without_keyframe(t_offset, tolerance=0.08)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": updated_clip.keyframes})
            self._refresh_keyframe_controls()
        else:
            cur_t = self._clip.transform_at(t_offset)
            easing = self._combo_easing.currentData() or "linear"
            new_kf = Keyframe(
                time_offset=t_offset,
                x=cur_t.x,
                y=cur_t.y,
                scale_x=cur_t.scale_x,
                scale_y=cur_t.scale_y,
                rotation=cur_t.rotation,
                opacity=cur_t.opacity,
                easing=easing,
            )
            updated_clip = self._clip.with_keyframe(new_kf)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": updated_clip.keyframes})
            self._refresh_keyframe_controls()

    def _on_easing_changed(self, index: int) -> None:
        if self._updating or self._clip is None or self._clip_id < 0:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        nearest = self._clip.nearest_keyframe(t_offset, tolerance=0.08)
        if nearest is not None:
            new_easing = self._combo_easing.itemData(index) or "linear"
            updated_kf = replace(nearest, easing=new_easing)
            updated_clip = self._clip.with_keyframe(updated_kf)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": updated_clip.keyframes})

    def _on_preset_selected(self, index: int) -> None:
        if self._updating or self._clip is None or self._clip_id < 0:
            return
        preset = self._combo_presets.itemData(index)
        if not preset:
            return
        if preset == "clear":
            updated_clip = replace(self._clip, keyframes=())
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": ()})
        else:
            kfs = create_preset_keyframes(preset, self._clip.base_transform, duration=0.6)
            updated_clip = replace(self._clip, keyframes=kfs)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": kfs})
        self._updating = True
        try:
            self._combo_presets.setCurrentIndex(0)
        finally:
            self._updating = False
        self._refresh_keyframe_controls()

    def _emit_property_change(self, changes: dict) -> None:
        if self._clip_id < 0 or self._clip is None:
            return
        if self._clip.has_keyframes:
            t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
            nearest = self._clip.nearest_keyframe(t_offset, tolerance=0.08)
            cur_t = self._clip.transform_at(t_offset)
            new_x = float(changes.get("x", cur_t.x))
            new_y = float(changes.get("y", cur_t.y))
            new_sx = float(changes.get("scale_x", cur_t.scale_x))
            new_sy = float(changes.get("scale_y", cur_t.scale_y))
            new_rot = float(changes.get("rotation", cur_t.rotation))

            is_scale_change = "scale" in changes or "scale_x" in changes or "scale_y" in changes

            if is_scale_change and not nearest:
                first_k = self._clip.keyframes[0]
                uniform_scale = len(self._clip.keyframes) > 1 and all(
                    abs(k.scale_x - first_k.scale_x) < 0.005 and abs(k.scale_y - first_k.scale_y) < 0.005
                    for k in self._clip.keyframes
                )
                if uniform_scale or len(self._clip.keyframes) > 1:
                    factor_x = new_sx / max(0.001, cur_t.scale_x)
                    factor_y = new_sy / max(0.001, cur_t.scale_y)
                    dx_norm = new_x - cur_t.x
                    dy_norm = new_y - cur_t.y
                    new_kfs = tuple(
                        replace(
                            k,
                            x=k.x + dx_norm,
                            y=k.y + dy_norm,
                            scale_x=new_sx if uniform_scale else max(0.05, min(10.0, k.scale_x * factor_x)),
                            scale_y=new_sy if uniform_scale else max(0.05, min(10.0, k.scale_y * factor_y)),
                        )
                        for k in self._clip.keyframes
                    )
                    updated_clip = replace(
                        self._clip,
                        keyframes=new_kfs,
                        scale=changes.get("scale", (new_sx + new_sy) / 2.0),
                        scale_x=new_sx,
                        scale_y=new_sy,
                        x=new_x,
                        y=new_y,
                    )
                else:
                    target_time = t_offset
                    easing = self._combo_easing.currentData() or "linear"
                    new_kf = Keyframe(
                        time_offset=target_time,
                        x=new_x,
                        y=new_y,
                        scale_x=new_sx,
                        scale_y=new_sy,
                        rotation=new_rot,
                        opacity=float(changes.get("opacity", cur_t.opacity)),
                        easing=easing,
                    )
                    updated_clip = self._clip.with_keyframe(new_kf)
                    updated_clip = replace(
                        updated_clip,
                        scale=changes.get("scale", (new_sx + new_sy) / 2.0),
                        scale_x=new_sx,
                        scale_y=new_sy,
                        x=new_x,
                        y=new_y,
                        rotation=new_rot,
                    )
            else:
                target_time = nearest.time_offset if nearest is not None else t_offset
                easing = nearest.easing if nearest is not None else (self._combo_easing.currentData() or "linear")
                base_kf = nearest.transform if nearest is not None else cur_t

                new_kf = Keyframe(
                    time_offset=target_time,
                    x=float(changes.get("x", base_kf.x)),
                    y=float(changes.get("y", base_kf.y)),
                    scale_x=float(changes.get("scale_x", base_kf.scale_x)),
                    scale_y=float(changes.get("scale_y", base_kf.scale_y)),
                    rotation=float(changes.get("rotation", base_kf.rotation)),
                    opacity=float(changes.get("opacity", base_kf.opacity)),
                    easing=easing,
                )
                updated_clip = self._clip.with_keyframe(new_kf)
                updated_clip = replace(
                    updated_clip,
                    scale=changes.get("scale", (new_sx + new_sy) / 2.0),
                    scale_x=new_sx,
                    scale_y=new_sy,
                    x=new_x,
                    y=new_y,
                    rotation=new_rot,
                )

            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": updated_clip.keyframes, **changes})
            self._refresh_keyframe_controls()
        else:
            updated_dict = {
                k: v for k, v in changes.items() if hasattr(self._clip, k)
            }
            if updated_dict:
                self._clip = replace(self._clip, **updated_dict)
            self.property_changed.emit(self._clip_id, changes)

    def update_transform_fields(
        self, x: float, y: float, scale_x: float, scale_y: float | None = None, rotation: float = 0.0
    ) -> None:
        """Atualiza campos de transformação durante manipulação interativa no canvas."""
        if self._updating:
            return
        if scale_y is None:
            scale_y = scale_x
        self._updating = True
        try:
            px = round(x * self._proj_w)
            py = round(y * self._proj_h)
            cur_w = max(1, round(self._base_w * scale_x))
            cur_h = max(1, round(self._base_h * scale_y))
            self._spin_x.setValue(px)
            self._spin_y.setValue(py)
            self._spin_w.setValue(cur_w)
            self._spin_h.setValue(cur_h)
            self._spin_scale.setValue((scale_x + scale_y) / 2.0)
            self._spin_rot.setValue(rotation % 360.0)
            self._last_w = cur_w
            self._last_h = cur_h
            self._last_x = x
            self._last_y = y
            self._last_rot = rotation
        finally:
            self._updating = False

    def _calc_anchor_shift(self, new_w: int, new_h: int) -> tuple[float, float]:
        """Calcula o novo centro (new_x, new_y) normalizado para que a expansão ocorra

        exclusivamente para a DIREITA e para CIMA, mantendo o canto inferior esquerdo
        (bottom-left) rigorosamente fixo.
        """
        old_w = getattr(self, "_last_w", self._spin_w.value())
        old_h = getattr(self, "_last_h", self._spin_h.value())
        old_x = getattr(self, "_last_x", self._spin_x.value() / max(1.0, float(self._proj_w)))
        old_y = getattr(self, "_last_y", self._spin_y.value() / max(1.0, float(self._proj_h)))
        rot = getattr(self, "_last_rot", self._spin_rot.value())

        dw = float(new_w - old_w)
        dh = float(new_h - old_h)

        theta_rad = math.radians(rot)
        cos_t = math.cos(theta_rad)
        sin_t = math.sin(theta_rad)

        old_cx_px = old_x * float(self._proj_w)
        old_cy_px = old_y * float(self._proj_h)

        new_cx_px = old_cx_px + (dw / 2.0) * cos_t + (dh / 2.0) * sin_t
        new_cy_px = old_cy_px + (dw / 2.0) * sin_t - (dh / 2.0) * cos_t

        new_x = new_cx_px / max(1.0, float(self._proj_w))
        new_y = new_cy_px / max(1.0, float(self._proj_h))
        return new_x, new_y

    def _on_x_changed(self, val: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        new_x = val / max(1.0, float(self._proj_w))
        self._last_x = new_x
        self._emit_property_change({"x": new_x})

    def _on_y_changed(self, val: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        new_y = val / max(1.0, float(self._proj_h))
        self._last_y = new_y
        self._emit_property_change({"y": new_y})

    def _on_lock_ratio_toggled(self, checked: bool) -> None:
        if checked:
            cur_w = self._spin_w.value()
            cur_h = self._spin_h.value()
            self._aspect_ratio = max(0.001, cur_w / max(1.0, float(cur_h)))

    def _on_scale_changed(self, val: float) -> None:
        if self._updating or self._clip_id < 0:
            return
        self._updating = True
        try:
            if self._chk_lock_ratio.isChecked():
                new_w = max(1, round(self._base_w * val))
                new_h = max(1, round(self._base_h * val))
                new_sx = val
                new_sy = val
            else:
                cur_sx = self._spin_w.value() / max(1.0, self._base_w)
                cur_sy = self._spin_h.value() / max(1.0, self._base_h)
                avg = max(0.001, (cur_sx + cur_sy) / 2.0)
                factor = val / avg
                new_sx = max(0.05, min(10.0, cur_sx * factor))
                new_sy = max(0.05, min(10.0, cur_sy * factor))
                new_w = max(1, round(self._base_w * new_sx))
                new_h = max(1, round(self._base_h * new_sy))

            new_x, new_y = self._calc_anchor_shift(new_w, new_h)
            self._spin_w.setValue(new_w)
            self._spin_h.setValue(new_h)
            self._spin_x.setValue(round(new_x * self._proj_w))
            self._spin_y.setValue(round(new_y * self._proj_h))

            self._last_w = new_w
            self._last_h = new_h
            self._last_x = new_x
            self._last_y = new_y

            changes = {
                "x": new_x,
                "y": new_y,
                "scale": val,
                "scale_x": new_sx,
                "scale_y": new_sy,
            }
        finally:
            self._updating = False
        self._emit_property_change(changes)

    def _on_w_changed(self, val: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        new_scale_x = max(0.05, min(10.0, val / max(1.0, self._base_w)))
        self._updating = True
        try:
            if self._chk_lock_ratio.isChecked():
                new_h = max(1, round(val / max(0.001, self._aspect_ratio)))
                new_scale_y = max(0.05, min(10.0, new_h / max(1.0, self._base_h)))
                self._spin_h.setValue(new_h)
                avg_scale = (new_scale_x + new_scale_y) / 2.0
                self._spin_scale.setValue(avg_scale)
            else:
                new_h = getattr(self, "_last_h", self._spin_h.value())
                cur_sy = self._spin_h.value() / max(1.0, self._base_h)
                new_scale_y = cur_sy
                avg_scale = (new_scale_x + cur_sy) / 2.0
                self._spin_scale.setValue(avg_scale)

            new_x, new_y = self._calc_anchor_shift(val, new_h)
            self._spin_x.setValue(round(new_x * self._proj_w))
            self._spin_y.setValue(round(new_y * self._proj_h))

            self._last_w = val
            self._last_h = new_h
            self._last_x = new_x
            self._last_y = new_y

            if self._chk_lock_ratio.isChecked():
                changes = {
                    "x": new_x,
                    "y": new_y,
                    "scale": avg_scale,
                    "scale_x": new_scale_x,
                    "scale_y": new_scale_y,
                }
            else:
                changes = {
                    "x": new_x,
                    "y": new_y,
                    "scale": avg_scale,
                    "scale_x": new_scale_x,
                }
        finally:
            self._updating = False
        self._emit_property_change(changes)

    def _on_h_changed(self, val: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        new_scale_y = max(0.05, min(10.0, val / max(1.0, self._base_h)))
        self._updating = True
        try:
            if self._chk_lock_ratio.isChecked():
                new_w = max(1, round(val * self._aspect_ratio))
                new_scale_x = max(0.05, min(10.0, new_w / max(1.0, self._base_w)))
                self._spin_w.setValue(new_w)
                avg_scale = (new_scale_x + new_scale_y) / 2.0
                self._spin_scale.setValue(avg_scale)
            else:
                new_w = getattr(self, "_last_w", self._spin_w.value())
                cur_sx = self._spin_w.value() / max(1.0, self._base_w)
                new_scale_x = cur_sx
                avg_scale = (cur_sx + new_scale_y) / 2.0
                self._spin_scale.setValue(avg_scale)

            new_x, new_y = self._calc_anchor_shift(new_w, val)
            self._spin_x.setValue(round(new_x * self._proj_w))
            self._spin_y.setValue(round(new_y * self._proj_h))

            self._last_w = new_w
            self._last_h = val
            self._last_x = new_x
            self._last_y = new_y

            if self._chk_lock_ratio.isChecked():
                changes = {
                    "x": new_x,
                    "y": new_y,
                    "scale": avg_scale,
                    "scale_x": new_scale_x,
                    "scale_y": new_scale_y,
                }
            else:
                changes = {
                    "x": new_x,
                    "y": new_y,
                    "scale": avg_scale,
                    "scale_y": new_scale_y,
                }
        finally:
            self._updating = False
        self._emit_property_change(changes)

    def _on_rot_changed(self, val: float) -> None:
        if self._updating or self._clip_id < 0:
            return
        self._last_rot = val % 360.0
        self._emit_property_change({"rotation": self._last_rot})

    def _set_preset_rotation(self, angle: float) -> None:
        self._spin_rot.setValue(angle)


class _MediaListWidget(QListWidget):
    """Lista de mídias importadas do projeto em grade de cartões com miniaturas."""

    files_dropped = Signal(list)  # list[Path]
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(96, 54))
        self.setGridSize(QSize(116, 92))
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count():
            return
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            self.viewport().rect(),
            Qt.AlignmentFlag.AlignCenter,
            strings.EDIT_MEDIA_EMPTY,
        )
        painter.end()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


_POPULAR_FONTS = [
    "Arial",
    "Calibri",
    "Comic Sans MS",
    "Courier New",
    "DejaVu Sans",
    "DejaVu Sans Mono",
    "DejaVu Serif",
    "Georgia",
    "Helvetica",
    "Impact",
    "Inter",
    "Liberation Sans",
    "Monospace",
    "Rapier Zero",
    "Rapier Zero Hollow",
    "Roboto",
    "Sans Serif",
    "Serif",
    "Times New Roman",
    "Trebuchet MS",
    "Ubuntu",
    "Verdana",
]


class _FontSelectorWidget(QWidget):
    """Seletor de fonte expansível com lista retrátil, busca e prévia tipográfica."""

    font_changed = Signal(str)

    def __init__(self, initial_family: str = "Sans Serif", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from videomanager.presentation.qt.fonts import ensure_application_fonts

        ensure_application_fonts()
        self._current_family = initial_family
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._toggle_btn = QPushButton(f"🔤 {initial_family}  ▾")
        self._toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 5px 8px; border: 1px solid #444; border-radius: 4px; background: #2a2a32; color: #fff; } "
            "QPushButton:hover { background: #353540; border-color: #666; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_list)
        layout.addWidget(self._toggle_btn)

        self._list_container = QFrame()
        self._list_container.setStyleSheet(
            "QFrame { background: #22222a; border: 1px solid #444450; border-radius: 4px; }"
        )
        self._list_container.setVisible(False)
        c_layout = QVBoxLayout(self._list_container)
        c_layout.setContentsMargins(4, 4, 4, 4)
        c_layout.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Buscar fonte...")
        self._search_input.setStyleSheet(
            "QLineEdit { background: #1a1a22; border: 1px solid #444; border-radius: 3px; padding: 4px 6px; color: #fff; font-size: 11px; }"
        )
        self._search_input.textChanged.connect(self._filter_fonts)
        c_layout.addWidget(self._search_input)

        self._font_list = QListWidget()
        self._font_list.setFixedHeight(140)
        self._font_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; color: #eee; } "
            "QListWidget::item { padding: 4px 6px; border-radius: 3px; } "
            "QListWidget::item:selected { background: #0284c7; color: #fff; } "
            "QListWidget::item:hover { background: #2f2f3c; }"
        )

        seen: set[str] = set()
        all_families: list[str] = []
        for fam in _POPULAR_FONTS:
            k = fam.lower()
            if k not in seen:
                seen.add(k)
                all_families.append(fam)

        for fam in QFontDatabase.families():
            if not fam.startswith("."):
                k = fam.lower()
                if k not in seen:
                    seen.add(k)
                    all_families.append(fam)

        all_families.sort(key=lambda s: s.lower())

        for fam in all_families:
            item = QListWidgetItem(fam)
            self._font_list.addItem(item)
            if fam.lower() == initial_family.lower():
                item.setSelected(True)

        self._font_list.itemClicked.connect(self._on_item_clicked)
        c_layout.addWidget(self._font_list)
        layout.addWidget(self._list_container)

    def _filter_fonts(self, query: str) -> None:
        q = query.strip().lower()
        for i in range(self._font_list.count()):
            item = self._font_list.item(i)
            item.setHidden(bool(q and q not in item.text().lower()))

    def _toggle_list(self) -> None:
        self._expanded = not self._expanded
        self._list_container.setVisible(self._expanded)
        arrow = "▴" if self._expanded else "▾"
        self._toggle_btn.setText(f"🔤 {self._current_family}  {arrow}")
        if self._expanded:
            self._search_input.clear()
            self._search_input.setFocus()
            items = self._font_list.findItems(self._current_family, Qt.MatchFlag.MatchExactly)
            if items:
                self._font_list.scrollToItem(items[0])

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.set_family(item.text())
        self._toggle_list()
        self.font_changed.emit(self._current_family)

    def current_family(self) -> str:
        return self._current_family

    def set_family(self, family: str) -> None:
        self._current_family = family
        arrow = "▴" if self._expanded else "▾"
        self._toggle_btn.setText(f"🔤 {family}  {arrow}")
        items = self._font_list.findItems(family, Qt.MatchFlag.MatchExactly)
        if items:
            self._font_list.setCurrentItem(items[0])
        else:
            for i in range(self._font_list.count()):
                it = self._font_list.item(i)
                if it.text().lower() == family.lower():
                    self._font_list.setCurrentItem(it)
                    break
