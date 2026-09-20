"""Widgets visuais do editor: prévia, propriedades, acervo e controles de fonte."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal

from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
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
from videomanager.domain.timing import frame_index, last_frame_time
from videomanager.domain.constants import MIN_TRANSITION_DURATION

from videomanager.domain.preview import fit_size

from videomanager.domain.keyframe import ClipTransform
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.keyframe import create_preset_keyframes
from videomanager.presentation.qt.fonts import ensure_application_fonts
from videomanager.domain.project import MAX_GAIN_DB
from videomanager.domain.project import MIN_GAIN_DB
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaRef
from videomanager.presentation.qt.panels.timeline import MEDIA_MIME

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
    overlay_transform_cancelled = Signal(int)
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
        self._interaction_layers: tuple[QPixmap, ...] | None = None
        self._interaction_visible = False

        self._active_clip: Clip | None = None
        self._overlay_clips: tuple[Clip, ...] = ()
        self._selectable_clips: tuple[Clip, ...] | None = None
        self._text_ratio = 1.0
        self._whole_animation = False
        self._drag_init_time_offset = 0.0
        self._proj_w: int = 1920
        self._proj_h: int = 1080
        self._fps = 30.0
        self._position: float = 0.0
        self._drag_mode: str | None = None
        self._drag_clip_id: int = -1
        self._drag_original_clip: Clip | None = None
        self._drag_start_pos = QPoint()
        self._drag_init_x: float = 0.5
        self._drag_init_y: float = 0.5
        self._drag_init_scale: float = 1.0
        self._drag_init_rot: float = 0.0
        self._drag_init_dist: float = 1.0
        self._drag_init_angle: float = 0.0
        self._drag_last_angle: float = 0.0
        self._drag_rotation_delta: float = 0.0
        self._drag_opp_x: float = 0.0
        self._drag_opp_y: float = 0.0
        self._drag_sx: float = 1.0
        self._drag_sy: float = 1.0
        self._drag_w0: float = 1.0
        self._drag_h0: float = 1.0
        self._is_playing: bool = False
        self._clip_visible: bool = True
        self._snap_enabled: bool = True
        self._snap_guide_x: float | None = None
        self._snap_guide_y: float | None = None
        self._snap_guide_rot: float | None = None
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
            self._interaction_visible = False
            self._drag_mode = None
            self._drag_clip_id = -1
            self._snap_guide_x = None
            self._snap_guide_y = None
            self._snap_guide_rot = None
        self._is_playing = playing
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, self.minimumHeight())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.double_clicked.emit()

    @property
    def has_frame(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def set_frame_pixmap(self, pixmap: QPixmap) -> None:
        if not self._drag_mode:
            self._interaction_visible = False
        self._pixmap = pixmap
        if not pixmap.isNull():
            self.setText("")
        self.update()

    def clear_frame(self) -> None:
        self.set_interaction_layers(None)
        self._pixmap = None
        self._overlay_clips = ()
        self._snap_guide_x = None
        self._snap_guide_y = None
        self._snap_guide_rot = None
        self.setText(strings.EDIT_EMPTY)
        self.update()

    def set_interaction_layers(self, layers: tuple[QPixmap, ...] | None) -> None:
        self._interaction_layers = layers
        if layers is None:
            self._interaction_visible = False
        elif self._drag_mode:
            self._interaction_visible = True
        self.update()

    def begin_interaction(self) -> bool:
        if self._interaction_layers is None:
            return False
        self._interaction_visible = True
        self.update()
        return True

    def set_overlay_clips(self, clips: Sequence[Clip]) -> None:
        self._overlay_clips = tuple(clips)
        self.update()

    def setPixmap(self, pixmap: QPixmap) -> None:  # noqa: N802
        self.set_frame_pixmap(pixmap)

    def set_active_clip(self, clip: Clip | None, proj_w: int, proj_h: int, visible: bool = True) -> None:
        if clip is None or self._active_clip is None or clip.clip_id != self._active_clip.clip_id:
            self.set_interaction_layers(None)
        self._active_clip = clip
        self._proj_w = max(1, proj_w)
        self._proj_h = max(1, proj_h)
        self._clip_visible = visible
        if not (self._drag_mode and clip and self._drag_clip_id == clip.clip_id):
            self._snap_guide_x = None
            self._snap_guide_y = None
            self._snap_guide_rot = None
        self.update()

    def set_position(self, pos: float) -> None:
        if abs(pos - self._position) > 0.001:
            self.set_interaction_layers(None)
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

        base_sx = clip.scale_x
        base_sy = clip.scale_y
        animated_scale = clip.has_keyframes and (
            any(
                abs(k.scale_x - base_sx) > 1e-9
                or abs(k.scale_y - base_sy) > 1e-9
                for k in clip.keyframes
            )
            or any(
                abs(clip.keyframes[i].scale_x - clip.keyframes[i + 1].scale_x)
                > 1e-9
                or abs(clip.keyframes[i].scale_y - clip.keyframes[i + 1].scale_y)
                > 1e-9
                for i in range(len(clip.keyframes) - 1)
            )
        )
        if animated_scale:
            # O filtro com ``eval=frame`` usa ``trunc``; o caminho estático usa
            # ``round`` ao montar o comando.
            item_w = max(2, int(base_w * transform.scale_x / 2.0) * 2)
            item_h = max(2, int(base_h * transform.scale_y / 2.0) * 2)
        else:
            item_w = max(
                2,
                int(round(base_w * transform.scale_x / 2.0) * 2),
            )
            item_h = max(
                2,
                int(round(base_h * transform.scale_y / 2.0) * 2),
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
        sx = max(0.05, transform.scale_x)
        sy = max(0.05, transform.scale_y)

        if clip.overlay_type == "text":
            ensure_application_fonts()
            font = QFont(clip.font_family or "Sans Serif", clip.font_size or 36)
            font.setBold(clip.font_bold)
            font.setItalic(clip.font_italic)
            fm = QFontMetrics(font)
            # O conteúdo é o que o rasterizador recebe, sem substituto: com um
            # texto apagado, inventar "Texto" aqui dimensionava a caixa para
            # uma palavra que a exportação não tem.
            text = clip.text_content
            stroke_w = max(0, clip.stroke_width)
            pad = 20 + stroke_w
            lines = text.splitlines() if text else [""]
            line_spacing = fm.lineSpacing()
            total_text_h = (len(lines) - 1) * line_spacing + fm.ascent() + fm.descent()
            max_tw = max((fm.horizontalAdvance(l) for l in lines), default=100)
            full_w = max(40, ((max_tw + pad * 2 + 3) // 4) * 4)
            full_h = max(40, ((total_text_h + pad * 2 + 3) // 4) * 4)
            output_w = self._pixmap.width() if self._pixmap is not None else self._proj_w
            output_h = self._pixmap.height() if self._pixmap is not None else self._proj_h
            compose_w, compose_h = fit_size(self._proj_w, self._proj_h,
                                           min(self._proj_w, output_w), min(self._proj_h, output_h))
            ratio = min(compose_w / self._proj_w, compose_h / self._proj_h) * self._text_ratio
            item_w = max(2, int(full_w * sx * ratio / 2) * 2)
            item_h = max(2, int(full_h * sy * ratio / 2) * 2)
            x = float(f"{transform.x:.6f}") * compose_w - item_w / 2
            y = float(f"{transform.y:.6f}") * compose_h - item_h / 2
            left = math.floor(x+.5) if x >= 0 else math.ceil(x-.5)
            top = math.floor(y+.5) if y >= 0 else math.ceil(y-.5)
            rx, ry = vrect.width()/compose_w, vrect.height()/compose_h
            return (vrect.x()+(left+item_w/2)*rx, vrect.y()+(top+item_h/2)*ry, item_w*rx, item_h*ry)

        if clip.has_image and not clip.audio_only and clip.media is not None:
            mw = clip.media.width or self._proj_w
            mh = clip.media.height or self._proj_h
            output_w = self._pixmap.width() if self._pixmap is not None else self._proj_w
            output_h = self._pixmap.height() if self._pixmap is not None else self._proj_h
            compose_w, compose_h = fit_size(self._proj_w, self._proj_h,
                                           min(self._proj_w, output_w), min(self._proj_h, output_h))
            base_w, base_h = fit_size(mw, mh, compose_w, compose_h)
            animated = any(abs(k.scale_x - clip.scale_x) > 1e-9 or abs(k.scale_y - clip.scale_y) > 1e-9
                           for k in clip.keyframes)
            quantize = int if animated else round
            w, h = max(2, int(quantize(base_w * sx / 2)) * 2), max(2, int(quantize(base_h * sy / 2)) * 2)
            left = float(f'{transform.x:.6f}') * compose_w - w / 2
            top = float(f'{transform.y:.6f}') * compose_h - h / 2
            left = math.floor(left + .5) if left >= 0 else math.ceil(left - .5)
            top = math.floor(top + .5) if top >= 0 else math.ceil(top - .5)
            rx, ry = vrect.width() / compose_w, vrect.height() / compose_h
            return (vrect.x() + (left + w / 2) * rx, vrect.y() + (top + h / 2) * ry, w * rx, h * ry)

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
                    ):
                        for ov_clip in reversed(self._selectable_clips if self._selectable_clips is not None else self._overlay_clips):
                            if ov_clip.clip_id == self._active_clip.clip_id:
                                break
                            mode_ov, geom_ov = self._hit_test_clip(ov_clip, pos)
                            if mode_ov and geom_ov:
                                self.clip_selected.emit(ov_clip.clip_id)
                                event.accept()
                                return

                    t_offset = max(0.0, self._position - self._active_clip.start)
                    transform = self._active_clip.transform_at(t_offset)
                    cx, cy, w, h = geom
                    self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                    self._drag_original_clip = self._active_clip
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
                    self._drag_last_angle = self._drag_init_angle
                    self._drag_rotation_delta = 0.0

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
            for ov_clip in reversed(self._selectable_clips if self._selectable_clips is not None else self._overlay_clips):
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
                sx0 = getattr(self, "_drag_init_scale_x", self._drag_init_scale)
                sy0 = getattr(self, "_drag_init_scale_y", self._drag_init_scale)
                axes = [sx0, sy0]
                if self._whole_animation:
                    axes += [s for k in (self._drag_init_keyframes or ()) for s in (k.scale_x, k.scale_y)]
                bounded = max(max(min_scale / s for s in axes), min(min(max_scale / s for s in axes), factor))
                if bounded != factor:
                    self._snap_guide_x = self._snap_guide_y = None
                new_scale_x, new_scale_y = sx0 * bounded, sy0 * bounded
                new_scale = (new_scale_x + new_scale_y) / 2
                actual_ratio = bounded

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
                delta_angle = (cur_angle - self._drag_last_angle + 180.0) % 360.0 - 180.0
                self._drag_last_angle = cur_angle
                self._drag_rotation_delta += delta_angle
                raw_rot = self._drag_init_rot + self._drag_rotation_delta
                new_rot = raw_rot
                self._snap_guide_rot = None

                if self._snap_enabled:
                    cardinal = round(raw_rot / 90.0) * 90.0
                    if abs(raw_rot - cardinal) <= 4.0:
                        new_rot = cardinal
                        self._snap_guide_rot = cardinal

            original = replace(self._active_clip, keyframes=getattr(self, "_drag_init_keyframes", ()) or ())
            self._active_clip = original.with_edited_transform(
                self._drag_init_time_offset,
                {"x": new_x, "y": new_y, "scale_x": new_scale_x, "scale_y": new_scale_y, "rotation": new_rot},
                fps=self._fps, whole_animation=self._whole_animation)
            pose = self._active_clip.transform_at(self._drag_init_time_offset)
            new_x, new_y, new_rot = pose.x, pose.y, pose.rotation
            new_scale = (pose.scale_x + pose.scale_y) / 2
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

    def end_transform(self) -> None:
        """Encerra a captura lógica quando outro comando confirma o gesto."""
        self._drag_mode, self._drag_clip_id = None, -1
        self._drag_original_clip = self._drag_init_keyframes = None
        self._snap_guide_x = self._snap_guide_y = self._snap_guide_rot = None
        self.update()

    def _cancel_transform(self) -> None:
        if not self._drag_mode:
            return
        self._interaction_visible = False
        clip_id = self._drag_clip_id
        if self._drag_original_clip is not None:
            self._active_clip = self._drag_original_clip
        self._drag_mode, self._drag_clip_id = None, -1
        self._drag_original_clip = self._drag_init_keyframes = None
        self._snap_guide_x = self._snap_guide_y = self._snap_guide_rot = None
        self.overlay_transform_cancelled.emit(clip_id)
        self.update()

    def event(self, event: QEvent) -> bool:
        if (event.type() in (QEvent.Type.UngrabMouse, QEvent.Type.Hide, QEvent.Type.WindowDeactivate)
                and getattr(self, '_drag_mode', None)):
            self._cancel_transform()
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._drag_mode:
            self._cancel_transform()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._snap_guide_x = None
        self._snap_guide_y = None
        self._snap_guide_rot = None
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            clip_id = self._drag_clip_id
            self._drag_mode = None
            self._drag_clip_id = -1
            self._drag_init_keyframes = None
            self._drag_original_clip = None
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
        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(target, self._pixmap)

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

        # Camadas preparadas preservam o fundo descoberto e objetos superiores.
        # A pose acompanha cada evento; só o fechamento espera o quadro canônico.
        if has_active and self._interaction_visible and self._interaction_layers:
            geom = self._clip_geometry(clip)
            if geom:
                background, texture, foreground = self._interaction_layers
                transform = clip.transform_at(max(0., self._position - clip.start))
                cx, cy, w, h = geom
                painter.save()
                painter.setClipRect(target, Qt.ClipOperation.IntersectClip)
                painter.drawPixmap(target, background)
                painter.save()
                painter.setOpacity(transform.opacity)
                painter.translate(cx, cy)
                painter.rotate(transform.rotation)
                painter.drawPixmap(QRectF(-w / 2, -h / 2, w, h), texture, QRectF(texture.rect()))
                painter.restore()
                painter.drawPixmap(target, foreground)
                painter.restore()

        # 3. Máscara de delimitação e atenuação (dimming) fora da região efetiva do vídeo
        outside_path = QPainterPath()
        outside_path.addRect(QRectF(self.rect()))
        target_path = QPainterPath()
        target_path.addRect(QRectF(target))
        dim_path = outside_path.subtracted(target_path)
        painter.fillPath(dim_path, QColor(10, 10, 14, 175))

        # 4. Moldura de destaque da região efetiva do vídeo
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

        # 5. Alças de controle e Bounding Box no topo de tudo
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
    animation_scope_changed = Signal(bool)
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "plain")
        self._clip_id: int = -1
        self._clip: Clip | None = None
        self._proj_w: int = 1920
        self._proj_h: int = 1080
        self._fps = 30.0
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
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        self._whole_animation = QCheckBox(strings.EDIT_ANIMATION_GLOBAL)
        self._whole_animation.setToolTip(strings.EDIT_ANIMATION_GLOBAL_TIP)
        self._whole_animation.toggled.connect(self.animation_scope_changed)
        anim_layout.addWidget(self._whole_animation)

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

    def load_clip(self, clip: Clip, proj_w: int, proj_h: int, fps: float = 30.0, text_ratio: float = 1.0) -> None:
        self._updating = True
        try:
            if self._clip_id != clip.clip_id:
                self._whole_animation.setChecked(False)
            self._clip_id = clip.clip_id
            self._fps = fps if fps > 0 else 30.0
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
                text = clip.text_content
                stroke_w = max(0, clip.stroke_width)
                pad = 20 + stroke_w
                lines = text.splitlines() if text else [""]
                line_spacing = fm.lineSpacing()
                total_text_h = (len(lines) - 1) * line_spacing + fm.ascent() + fm.descent()
                max_tw = max((fm.horizontalAdvance(l) for l in lines), default=100)
                self._base_w = float(max(40, ((max_tw + pad * 2 + 3) // 4) * 4))
                self._base_h = float(max(40, ((total_text_h + pad * 2 + 3) // 4) * 4))
                self._base_w *= text_ratio
                self._base_h *= text_ratio
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

            can_animate = clip.overlay_type not in ("transition", "filter") and (clip.has_image or clip.is_additional)
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

            self._last_w = cur_w
            self._last_h = cur_h
            self._last_x = clip.x
            self._last_y = clip.y
            self._last_rot = clip.rotation

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

    def _keyframe_in_frame(self, offset: float) -> Keyframe | None:
        if self._clip is None:
            return None
        frame = frame_index(self._clip.start + offset, self._fps)
        candidates = [k for k in self._clip.visible_keyframes
                      if frame_index(self._clip.start + k.time_offset, self._fps) == frame]
        return min(candidates, key=lambda k: abs(k.time_offset - offset), default=None)

    def _refresh_keyframe_controls(self, *, refresh_static: bool = False) -> None:
        if self._clip is None or not hasattr(self, "_animation_group"):
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        current_kf = self._keyframe_in_frame(t_offset)

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

        count = len(self._clip.visible_keyframes)
        if self._clip.has_keyframes:
            self._lbl_kf_status.setText(f"{count} quadro(s)-chave")
            has_prev = any(k.time_offset < t_offset - 1e-8 for k in self._clip.visible_keyframes)
            has_next = any(k.time_offset > t_offset + 1e-8 for k in self._clip.visible_keyframes)
            self._btn_kf_prev.setEnabled(has_prev)
            self._btn_kf_next.setEnabled(has_next)
        else:
            self._lbl_kf_status.setText("Sem quadros-chave")
            self._btn_kf_prev.setEnabled(False)
            self._btn_kf_next.setEnabled(False)

        # Sem animação, o cursor não muda a pose. Reescrever os campos a cada
        # tick apagaria digitação parcial e valores de um arrasto em andamento.
        if not self._clip.has_keyframes and not refresh_static:
            return
        # Sincroniza campos numéricos com o estado interpolado no instante do cursor
        was_updating = self._updating
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
            self._updating = was_updating

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
        self._emit_property_change({"opacity": opacity})

    def _on_prev_keyframe(self) -> None:
        if self._clip is None or not self._clip.keyframes:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        prev_kfs = [k for k in self._clip.visible_keyframes if k.time_offset < t_offset - 1e-8]
        if prev_kfs:
            target_kf = max(prev_kfs, key=lambda k: k.time_offset)
            self.seek_requested.emit(self._clip.start + target_kf.time_offset)

    def _on_next_keyframe(self) -> None:
        if self._clip is None or not self._clip.keyframes:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        next_kfs = [k for k in self._clip.visible_keyframes if k.time_offset > t_offset + 1e-8]
        if next_kfs:
            target_kf = min(next_kfs, key=lambda k: k.time_offset)
            self.seek_requested.emit(self._clip.start + target_kf.time_offset)

    def _on_toggle_keyframe(self) -> None:
        if self._clip is None or self._clip_id < 0:
            return
        t_offset = max(0.0, min(self._clip.duration, self._playhead_pos - self._clip.start))
        nearest = self._keyframe_in_frame(t_offset)
        if nearest is not None:
            updated_clip = self._clip.without_keyframe(nearest.time_offset, tolerance=1e-9)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": updated_clip.keyframes})
            self._refresh_keyframe_controls(refresh_static=True)
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
        nearest = self._keyframe_in_frame(t_offset)
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
            end = min(0.6, last_frame_time(self._clip.duration, self._fps))
            kfs = create_preset_keyframes(preset, self._clip.base_transform, duration=end)
            updated_clip = replace(self._clip, keyframes=kfs)
            self._clip = updated_clip
            self.property_changed.emit(self._clip_id, {"keyframes": kfs})
        self._updating = True
        try:
            self._combo_presets.setCurrentIndex(0)
        finally:
            self._updating = False
        self._refresh_keyframe_controls(refresh_static=preset == "clear")

    def _emit_property_change(self, changes: dict) -> None:
        if self._clip_id < 0 or self._clip is None:
            return
        offset = self._playhead_pos - self._clip.start
        updated = self._clip.with_edited_transform(offset, changes, fps=self._fps,
                                                   whole_animation=self._whole_animation.isChecked())
        self._clip = updated
        result = {name: getattr(updated, name) for name in
                  ("x", "y", "scale", "scale_x", "scale_y", "rotation", "opacity", "keyframes")}
        self.property_changed.emit(self._clip_id, result)
        self._refresh_keyframe_controls()

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

    def _current_scales(self) -> tuple[float, float]:
        pose = self._clip.transform_at(max(0, self._playhead_pos - self._clip.start))
        return pose.scale_x, pose.scale_y

    @staticmethod
    def _scaled_axes(sx: float, sy: float, factor: float) -> tuple[float, float]:
        # Limitar o fator, e não cada eixo, conserva a proporção nos extremos.
        factor = max(max(.05 / sx, .05 / sy), min(min(10 / sx, 10 / sy), factor))
        return sx * factor, sy * factor

    def _apply_size(self, sx: float, sy: float) -> None:
        new_w = max(1, round(self._base_w * sx))
        new_h = max(1, round(self._base_h * sy))
        new_x, new_y = self._calc_anchor_shift(new_w, new_h)
        self._updating = True
        try:
            self._spin_w.setValue(new_w)
            self._spin_h.setValue(new_h)
            self._spin_scale.setValue((sx + sy) / 2)
            self._spin_x.setValue(round(new_x * self._proj_w))
            self._spin_y.setValue(round(new_y * self._proj_h))
            self._last_w, self._last_h = new_w, new_h
            self._last_x, self._last_y = new_x, new_y
            self._aspect_ratio = new_w / max(1, new_h)
        finally:
            self._updating = False
        self._emit_property_change({"x": new_x, "y": new_y, "scale": (sx + sy) / 2,
                                    "scale_x": sx, "scale_y": sy})

    def _on_scale_changed(self, val: float) -> None:
        if self._updating or self._clip_id < 0:
            return
        sx, sy = self._current_scales()
        self._apply_size(*self._scaled_axes(sx, sy, val / ((sx + sy) / 2)))

    def _on_w_changed(self, val: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        sx, sy = self._current_scales()
        if self._chk_lock_ratio.isChecked():
            sx, sy = self._scaled_axes(sx, sy, val / (self._base_w * sx))
        else:
            sx = max(.05, min(10, val / self._base_w))
        self._apply_size(sx, sy)

    def _on_h_changed(self, val: int) -> None:
        if self._updating or self._clip_id < 0:
            return
        sx, sy = self._current_scales()
        if self._chk_lock_ratio.isChecked():
            sx, sy = self._scaled_axes(sx, sy, val / (self._base_h * sy))
        else:
            sy = max(.05, min(10, val / self._base_h))
        self._apply_size(sx, sy)

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
        # Arrastar um cartão até a linha do tempo põe a mídia na trilha e no
        # instante escolhidos. A lista só exporta: soltar um cartão nela mesma
        # não reordena nada.
        #
        # **Depois** de ``setMovement``: o Qt desliga ``dragEnabled`` por dentro
        # quando o movimento é estático, e com a ordem inversa o cartão nunca
        # começava a ser arrastado.
        self.setDragEnabled(True)
        self.setDragDropMode(QListView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

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

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [MEDIA_MIME]

    def mimeData(self, items) -> QMimeData:  # noqa: N802
        payload = []
        for item in items:
            reference = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(reference, MediaRef):
                payload.append({"path": str(reference.path), "kind": reference.kind.name,
                                "duration": float(reference.natural_duration)})
        data = QMimeData()
        data.setData(MEDIA_MIME, json.dumps(payload).encode("utf-8"))
        return data

    def supportedDropActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

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
            event.ignore()


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
