"""Diálogo de configurações de exportação do editor de vídeo.

Reúne todas as escolhas de saída (resolução, taxa de quadros, interpolação,
corte rápido sem recodificação e pasta de destino) em uma janela modal dedicada,
liberando espaço para a visualização das trilhas na tela principal.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.export_policy import can_interpolate
from videomanager.application.media.export_description import describe_export
from videomanager.domain.render_cost import interpolation_bytes
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.media import LocalMedia
from videomanager.application import encoding as hwaccel
from videomanager.domain.estimator import estimate_export_size
from videomanager.application.errors import VideoManagerError
from videomanager.application.formatting import format_aspect_ratio, format_rate
from videomanager.application.formatting import format_size
from videomanager.application.media.processing import ExportOptions
from videomanager.application.jobs.models import Job
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import auto_canvas
from videomanager.application.preferences import Preferences as Settings
from videomanager.domain.timing import CutMode
from videomanager.domain.timing import TrimTarget
from videomanager.domain.timing import format_span
from videomanager.domain.timing import format_timecode
from videomanager.domain.timing import frame_step
from videomanager.domain.timing import keyframe_at_or_before
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.ports import DesktopRuntimePort

_CANVAS_PRESETS: tuple[tuple[int, int], ...] = (
    (3840, 2160),  # 4K UHD 16:9
    (2560, 1440),  # 2K QHD 16:9
    (1920, 1080),  # Full HD 16:9
    (1280, 720),   # HD 16:9
    (854, 480),    # SD 16:9
    (1080, 1920),  # Vertical Full HD 9:16 (TikTok / Reels / Shorts)
    (720, 1280),   # Vertical HD 9:16
    (1440, 1080),  # 4:3 Full HD
    (960, 720),    # 4:3 HD
    (640, 480),    # 4:3 SD
    (1080, 1080),  # Quadrado 1:1
    (720, 720),    # Quadrado 1:1
    (2560, 1080),  # Ultrawide 21:9
)

_RATE_PRESETS: tuple[float, ...] = (24.0, 25.0, 30.0, 50.0, 60.0)

# Taxas usuais de GIF. São baixas de propósito: cada quadro do GIF é uma imagem
# inteira, então dobrar a taxa dobra o arquivo. Todas dividem 100 sem sobra, que
# é como o formato guarda a duração de cada quadro (centésimos de segundo).
_GIF_RATE_PRESETS: tuple[float, ...] = (10.0, 12.5, 20.0, 25.0)

_CONTAINER_PRESETS: tuple[tuple[str, str], ...] = (
    ("MP4 (.mp4)", "mp4"),
    ("MKV (.mkv)", "mkv"),
    ("WebM (.webm)", "webm"),
    ("QuickTime (.mov)", "mov"),
    ("GIF animado (.gif)", "gif"),
)

_VIDEO_CODEC_PRESETS: tuple[tuple[str, str], ...] = (
    ("H.264 / AVC (padrão universal)", "h264"),
    ("HEVC / H.265 (alta eficiência)", "hevc"),
    ("AV1 (alta compressão)", "av1"),
    ("VP9 (web)", "vp9"),
)

_QUALITY_PRESETS: tuple[tuple[str, str], ...] = (
    (strings.EXPORT_QUALITY_BALANCED, hwaccel.QUALITY_BALANCED),
    (strings.EXPORT_QUALITY_HIGH, hwaccel.QUALITY_HIGH),
    (strings.EXPORT_QUALITY_ECONOMY, hwaccel.QUALITY_ECONOMY),
)

_AUDIO_FORMAT_PRESETS: tuple[tuple[str, str], ...] = (
    ("MP3 (.mp3 - 192 kbps)", "mp3"),
    ("AAC / M4A (.m4a - 192 kbps)", "m4a"),
    ("FLAC (.flac - sem perdas)", "flac"),
    ("WAV (.wav - PCM sem perdas)", "wav"),
    ("Opus (.opus - 128 kbps)", "opus"),
    ("OGG Vorbis (.ogg)", "ogg"),
)


def _index_of(box: QComboBox, value: object) -> int:
    """Retorna o índice do item com o dado associado, ou -1."""
    return next((i for i in range(box.count()) if box.itemData(i) == value), -1)


class ExportDialog(QDialog):
    """Janela modal para configurar e enfileirar a exportação da edição."""

    def __init__(
        self,
        project: Project,
        settings: Settings,
        pool: list[MediaRef],
        probed: dict[Path, LocalMedia],
        keyframes: tuple[float, ...] = (),
        ensure_tools: Callable[[], FFmpegTools | None] | None = None,
        initial_canvas: tuple[int, int] | None = None,
        initial_rate: float | None = None,
        project_path: Path | None = None,
        parent: QWidget | None = None,
        *,
        processing,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self.setWindowTitle(strings.EXPORT_DIALOG_TITLE)
        self.setMinimumWidth(580)
        self.setModal(True)

        self._processing = processing
        self._project = project.for_export()
        self._settings = settings
        self._pool = pool
        self._probed = probed
        self._keyframes = keyframes
        self._ensure_tools = ensure_tools
        self._canvas_choice = initial_canvas
        self._aspect_choice = (
            format_aspect_ratio(*initial_canvas) if initial_canvas else None
        )
        self._rate_choice = initial_rate
        self._project_path = project_path
        self._syncing = False

        self._container_choice: str = self._default_container(self._project)
        self._codec_choice: str | None = None
        self._quality_choice: str = getattr(self._settings, "default_export_quality", hwaccel.QUALITY_BALANCED)
        self._audio_format_choice: str = "mp3"

        self.created_job: Job | None = None
        self.chosen_canvas = initial_canvas
        self.chosen_rate = initial_rate

        self._build_ui()
        self._sync_presets()
        self._update_plan()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. Resumo da edição
        summary_group = QGroupBox(strings.EXPORT_SUMMARY_GROUP)
        summary_box = QVBoxLayout(summary_group)
        summary_box.setSpacing(4)
        summary_text = (
            f"Duração total: <b>{format_span(self._project.export_duration)}</b> · "
            f"{len(self._project.tracks)} trilha(s) · {len(self._project.clips)} bloco(s)"
        )
        summary_label = QLabel(summary_text)
        summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_box.addWidget(summary_label)
        layout.addWidget(summary_group)

        # 2. Configurações de saída
        settings_group = QGroupBox(strings.EXPORT_SETTINGS_GROUP)
        self._form = QFormLayout(settings_group)
        self._form.setSpacing(8)

        # Checkbox Exportar Somente Áudio
        self._audio_only_check = QCheckBox(strings.EXPORT_MODE_AUDIO_ONLY)
        self._audio_only_check.setToolTip(strings.EXPORT_MODE_AUDIO_ONLY_TIP)
        self._audio_only_check.toggled.connect(self._on_audio_only_toggled)
        self._form.addRow("", self._audio_only_check)

        # Formato de vídeo (container)
        self._container_label = QLabel(strings.EXPORT_CONTAINER)
        self._container_box = QComboBox()
        self._container_box.setToolTip(strings.EXPORT_CONTAINER_TIP)
        self._container_box.currentIndexChanged.connect(self._on_container_changed)
        self._form.addRow(self._container_label, self._container_box)

        # Codec de vídeo
        self._video_codec_label = QLabel(strings.EXPORT_VIDEO_CODEC)
        self._video_codec_box = QComboBox()
        self._video_codec_box.setToolTip(strings.EXPORT_VIDEO_CODEC_TIP)
        self._video_codec_box.currentIndexChanged.connect(self._on_video_codec_changed)
        self._form.addRow(self._video_codec_label, self._video_codec_box)

        # Qualidade de vídeo
        self._quality_label = QLabel(strings.EXPORT_QUALITY)
        self._quality_box = QComboBox()
        self._quality_box.setToolTip(strings.EXPORT_QUALITY_TIP)
        self._quality_box.currentIndexChanged.connect(self._on_quality_changed)
        self._form.addRow(self._quality_label, self._quality_box)

        # Formato de áudio (visível no modo somente áudio)
        self._audio_format_label = QLabel(strings.EXPORT_AUDIO_FORMAT)
        self._audio_format_box = QComboBox()
        self._audio_format_box.setToolTip(strings.EXPORT_AUDIO_FORMAT_TIP)
        self._audio_format_box.currentIndexChanged.connect(self._on_audio_format_changed)
        self._form.addRow(self._audio_format_label, self._audio_format_box)

        # Proporção
        self._aspect_label = QLabel(strings.EXPORT_ASPECT)
        self._aspect_box = QComboBox()
        self._aspect_box.setToolTip(strings.EXPORT_ASPECT_TIP)
        self._aspect_box.currentIndexChanged.connect(self._on_aspect_changed)
        self._form.addRow(self._aspect_label, self._aspect_box)

        # Resolução / Tela
        self._canvas_label = QLabel(strings.EDIT_CANVAS)
        self._canvas_box = QComboBox()
        self._canvas_box.setToolTip(strings.EDIT_CANVAS_TIP)
        self._canvas_box.currentIndexChanged.connect(self._on_canvas_changed)
        self._form.addRow(self._canvas_label, self._canvas_box)

        # Taxa de quadros
        self._rate_label = QLabel(strings.EDIT_CANVAS_RATE)
        self._rate_box = QComboBox()
        self._rate_box.setToolTip(strings.EDIT_CANVAS_RATE_TIP)
        self._rate_box.currentIndexChanged.connect(self._on_rate_changed)
        self._form.addRow(self._rate_label, self._rate_box)

        # Opções avançadas
        self._advanced_widget = QWidget()
        advanced_box = QVBoxLayout(self._advanced_widget)
        advanced_box.setContentsMargins(0, 0, 0, 0)
        advanced_box.setSpacing(6)

        self._fast = QCheckBox(strings.EDIT_MODE_FAST)
        self._fast.setToolTip(strings.EDIT_MODE_TIP)
        self._fast.toggled.connect(self._on_option_toggled)
        advanced_box.addWidget(self._fast)

        self._interpolate = QCheckBox(strings.EDIT_INTERPOLATE)
        self._interpolate.setToolTip(strings.EDIT_INTERPOLATE_TIP)
        self._interpolate.toggled.connect(self._on_option_toggled)
        advanced_box.addWidget(self._interpolate)

        self._form.addRow("", self._advanced_widget)

        self._size_label = QLabel("—")
        self._size_label.setProperty("role", "dim")
        self._form.addRow(strings.EXPORT_ESTIMATED_SIZE, self._size_label)

        layout.addWidget(settings_group)

        # 3. Destino do arquivo
        dest_group = QGroupBox(strings.EXPORT_DESTINATION_GROUP)
        dest_box = QVBoxLayout(dest_group)
        dest_box.setSpacing(8)

        self._same_folder = QCheckBox(strings.EDIT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        self._same_folder.toggled.connect(self._on_same_folder_toggled)
        dest_box.addWidget(self._same_folder)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_label = QLabel(strings.EXPORT_DESTINATION_FOLDER)
        folder_row.addWidget(folder_label)

        self._dest_edit = QLineEdit(str(self._runtime.download_directory(self._settings)))
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setEnabled(False)
        folder_row.addWidget(self._dest_edit, 1)

        self._pick_folder_button = QPushButton(strings.EXPORT_DESTINATION_PICK)
        self._pick_folder_button.setEnabled(False)
        self._pick_folder_button.clicked.connect(self._choose_destination_folder)
        folder_row.addWidget(self._pick_folder_button)
        dest_box.addLayout(folder_row)

        main_init = self._main_clip(self._project)
        source_init = (
            main_init.media.path
            if (main_init and main_init.media and main_init.media.path.is_file())
            else None
        )
        if source_init:
            default_stem = f"{source_init.stem}_editado"
        elif self._project_path:
            default_stem = f"{self._project_path.stem}_editado"
        else:
            default_stem = "video_editado"

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = QLabel("Nome do arquivo:")
        name_row.addWidget(name_label)

        self._filename_edit = QLineEdit(default_stem)
        self._filename_edit.setPlaceholderText("Nome do arquivo (sem extensão)")
        name_row.addWidget(self._filename_edit, 1)

        self._ext_label = QLabel(".mp4")
        self._ext_label.setProperty("role", "dim")
        name_row.addWidget(self._ext_label)
        dest_box.addLayout(name_row)

        layout.addWidget(dest_group)

        # 4. Plano e avisos
        self._plan = QLabel("")
        self._plan.setProperty("role", "dim")
        self._plan.setWordWrap(True)
        layout.addWidget(self._plan)

        self._warning = QLabel("")
        self._warning.setProperty("role", "warn")
        self._warning.setWordWrap(True)
        self._warning.setVisible(False)
        layout.addWidget(self._warning)

        # 5. Botões de ação
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)

        self._cancel_button = QPushButton(strings.EXPORT_ACTION_CANCEL)
        self._cancel_button.clicked.connect(self.reject)
        actions.addWidget(self._cancel_button)

        self._enqueue_button = QPushButton(strings.EXPORT_ACTION_ENQUEUE)
        self._enqueue_button.setProperty("role", "primary")
        self._enqueue_button.setDefault(True)
        self._enqueue_button.clicked.connect(self._on_enqueue)
        actions.addWidget(self._enqueue_button)

        layout.addLayout(actions)

    # ------------------------------------------------------------------
    # Preenchimento e sincronização
    # ------------------------------------------------------------------

    def _sync_presets(self) -> None:
        """Preenche as opções de tela, taxa, container, codec e formato de áudio."""
        # Opções de proporção
        self._aspect_box.blockSignals(True)
        self._aspect_box.clear()
        aspect_options = [
            (strings.EXPORT_ASPECT_AUTO, None),
            ("16:9 (Widescreen)", "16:9"),
            ("4:3 (Tradicional)", "4:3"),
            ("9:16 (Vertical / Shorts / Reels)", "9:16"),
            ("1:1 (Quadrado)", "1:1"),
            ("21:9 (Ultrawide)", "21:9"),
        ]
        for label, val in aspect_options:
            self._aspect_box.addItem(label, val)
        idx_a = _index_of(self._aspect_box, self._aspect_choice)
        self._aspect_box.setCurrentIndex(max(0, idx_a))
        self._aspect_box.blockSignals(False)

        # Opções de tela
        self._sync_canvas_box()

    def _sync_canvas_box(self) -> None:
        self._canvas_box.blockSignals(True)
        self._canvas_box.clear()
        options_canvas: list[tuple[str, tuple[int, int] | None]] = [
            (strings.EDIT_CANVAS_AUTO, None)
        ]
        seen: set[tuple[int, int]] = set()
        sizes = [
            (ref.width, ref.height)
            for ref in self._pool
            if ref.has_video and ref.width and ref.height
        ]
        ordered = sorted(sizes, key=lambda s: -s[0] * s[1])
        all_candidates = [*ordered, *_CANVAS_PRESETS]
        if self._aspect_choice:
            filtered = [
                (w, h)
                for (w, h) in all_candidates
                if format_aspect_ratio(w, h) == self._aspect_choice
            ]
        else:
            filtered = all_candidates

        for w, h in filtered:
            if (w, h) in seen:
                continue
            seen.add((w, h))
            aspect = format_aspect_ratio(w, h)
            label = (
                f"{aspect} · {w} × {h}"
                if aspect and not self._aspect_choice
                else strings.EDIT_CANVAS_SIZE.format(width=w, height=h)
            )
            options_canvas.append((label, (w, h)))
        for label, val in options_canvas:
            self._canvas_box.addItem(label, val)

        idx_c = _index_of(self._canvas_box, self._canvas_choice)
        self._canvas_box.setCurrentIndex(max(0, idx_c))
        self._canvas_box.blockSignals(False)

        # Opções de taxa
        self._fill_rates()

        # Container de vídeo
        self._container_box.blockSignals(True)
        self._container_box.clear()
        for label, val in _CONTAINER_PRESETS:
            self._container_box.addItem(label, val)
        idx_ct = _index_of(self._container_box, self._container_choice)
        self._container_box.setCurrentIndex(max(0, idx_ct))
        self._container_box.blockSignals(False)

        # Codec de vídeo (filtrado pelo container)
        self._sync_codecs()

        # Qualidade de vídeo
        self._quality_box.blockSignals(True)
        self._quality_box.clear()
        for label, val in _QUALITY_PRESETS:
            self._quality_box.addItem(label, val)
        idx_q = _index_of(self._quality_box, self._quality_choice)
        self._quality_box.setCurrentIndex(max(0, idx_q))
        self._quality_box.blockSignals(False)

        # Formato de áudio (somente áudio)
        self._audio_format_box.blockSignals(True)
        self._audio_format_box.clear()
        for label, val in _AUDIO_FORMAT_PRESETS:
            self._audio_format_box.addItem(label, val)
        idx_af = _index_of(self._audio_format_box, self._audio_format_choice)
        self._audio_format_box.setCurrentIndex(max(0, idx_af))
        self._audio_format_box.blockSignals(False)

        # Visibilidade inicial
        self._apply_audio_only_visibility()

    def _fill_rates(self) -> None:
        """Repopula as taxas — o GIF traz as dele, mais baixas."""
        self._rate_box.blockSignals(True)
        self._rate_box.clear()
        options_rate: list[tuple[str, float | None]] = [
            (strings.EDIT_CANVAS_RATE_AUTO, None)
        ]
        rates = {round(ref.fps, 3) for ref in self._pool if ref.has_video and ref.fps}
        presets = set(_RATE_PRESETS)
        if self._container_choice == "gif":
            presets |= set(_GIF_RATE_PRESETS)
        for r in sorted(rates | presets):
            options_rate.append((strings.EDIT_CANVAS_FPS.format(fps=format_rate(r)), r))
        for label, val in options_rate:
            self._rate_box.addItem(label, val)
        idx_r = _index_of(self._rate_box, self._rate_choice)
        self._rate_box.setCurrentIndex(max(0, idx_r))
        self._rate_box.blockSignals(False)

    def _apply_container_visibility(self) -> None:
        """GIF não tem codec, qualidade nem cópia dos dados da origem."""
        gif = self._container_choice == "gif" and not self._audio_only_check.isChecked()
        for widget in (self._video_codec_label, self._video_codec_box,
                       self._quality_label, self._quality_box):
            widget.setVisible(not gif and not self._audio_only_check.isChecked())
        if gif and self._fast.isChecked():
            self._fast.setChecked(False)
        self._fast.setToolTip(strings.EXPORT_GIF_NO_FAST if gif else strings.EDIT_MODE_TIP)

    def _sync_codecs(self) -> None:
        """Repopula o combo de codecs conforme o container selecionado."""
        container = self._container_box.currentData() or "mp4"
        # WebM suporta apenas VP9 e AV1
        if container == "webm":
            allowed = {"vp9", "av1"}
        else:
            allowed = {"h264", "hevc", "av1", "vp9"}

        self._video_codec_box.blockSignals(True)
        self._video_codec_box.clear()
        for label, val in _VIDEO_CODEC_PRESETS:
            if val in allowed:
                self._video_codec_box.addItem(label, val)
        # Tenta restaurar o codec anterior; se não couber, pega o primeiro
        idx_vc = _index_of(self._video_codec_box, self._codec_choice)
        if idx_vc < 0:
            idx_vc = 0
            self._codec_choice = self._video_codec_box.itemData(0) if self._video_codec_box.count() else None
        self._video_codec_box.setCurrentIndex(idx_vc)
        self._video_codec_box.blockSignals(False)

    def _apply_audio_only_visibility(self) -> None:
        """Mostra/oculta campos conforme o modo somente-áudio."""
        audio_only = self._audio_only_check.isChecked()
        # Campos de vídeo — ocultar no modo somente-áudio
        for widget in (
            self._container_label, self._container_box,
            self._video_codec_label, self._video_codec_box,
            self._quality_label, self._quality_box,
            self._aspect_label, self._aspect_box,
            self._canvas_label, self._canvas_box,
            self._rate_label, self._rate_box,
            self._advanced_widget,
        ):
            widget.setVisible(not audio_only)
        # Campos de áudio — mostrar apenas no modo somente-áudio
        self._audio_format_label.setVisible(audio_only)
        self._audio_format_box.setVisible(audio_only)
        self._apply_container_visibility()

    @staticmethod
    def _default_container(project: Project) -> str:
        """Determina o container padrão a partir da mídia principal do projeto."""
        for track in reversed(project.video_tracks):
            clips = [c for c in track.sorted_clips() if not c.is_image and not c.is_transition]
            if track.visible and clips:
                clip = clips[0]
                ext = clip.media.path.suffix.lstrip(".").lower()
                if ext in ("mp4", "mkv", "webm", "mov"):
                    return ext
                return "mp4"
        return "mp4"

    def _effective_project(self) -> Project:
        material = auto_canvas(self._project)
        w, h = self._canvas_choice or (material.width, material.height)
        fps = self._rate_choice or material.fps
        return self._project.with_output_canvas(w, h, fps)

    def _on_aspect_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._aspect_choice = self._aspect_box.itemData(index)
        if self._aspect_choice is None:
            self._canvas_choice = None
        else:
            cur_aspect = (
                format_aspect_ratio(*self._canvas_choice)
                if self._canvas_choice
                else None
            )
            if cur_aspect != self._aspect_choice:
                for w, h in _CANVAS_PRESETS:
                    if format_aspect_ratio(w, h) == self._aspect_choice:
                        self._canvas_choice = (w, h)
                        break
        self.chosen_canvas = self._canvas_choice
        self._sync_canvas_box()
        self._update_plan()

    def _on_canvas_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._canvas_choice = self._canvas_box.itemData(index)
        self.chosen_canvas = self._canvas_choice
        if self._canvas_choice is not None:
            new_aspect = format_aspect_ratio(*self._canvas_choice)
            if new_aspect != self._aspect_choice:
                self._aspect_choice = new_aspect
                idx_a = _index_of(self._aspect_box, self._aspect_choice)
                self._aspect_box.blockSignals(True)
                self._aspect_box.setCurrentIndex(max(0, idx_a))
                self._aspect_box.blockSignals(False)
        else:
            if self._aspect_choice is not None:
                self._aspect_choice = None
                self._aspect_box.blockSignals(True)
                self._aspect_box.setCurrentIndex(0)
                self._aspect_box.blockSignals(False)
        self._update_plan()

    def _on_rate_changed(self, index: int) -> None:
        if index < 0:
            return
        self._rate_choice = self._rate_box.itemData(index)
        self.chosen_rate = self._rate_choice
        self._update_plan()

    def _on_audio_only_toggled(self, checked: bool) -> None:
        self._apply_audio_only_visibility()
        self._update_plan()

    def _on_container_changed(self, index: int) -> None:
        if index < 0:
            return
        self._container_choice = self._container_box.itemData(index)
        self._sync_codecs()
        self._fill_rates()
        self._apply_container_visibility()
        self._update_plan()

    def _on_video_codec_changed(self, index: int) -> None:
        if index < 0:
            return
        self._codec_choice = self._video_codec_box.itemData(index)
        self._update_plan()

    def _on_quality_changed(self, index: int) -> None:
        if index < 0:
            return
        self._quality_choice = self._quality_box.itemData(index) or hwaccel.QUALITY_BALANCED
        self._update_plan()

    def _on_audio_format_changed(self, index: int) -> None:
        if index < 0:
            return
        self._audio_format_choice = self._audio_format_box.itemData(index)
        self._update_plan()

    def _on_option_toggled(self) -> None:
        self._update_plan()

    def _on_same_folder_toggled(self, checked: bool) -> None:
        self._dest_edit.setEnabled(not checked)
        self._pick_folder_button.setEnabled(not checked)
        self._update_plan()

    def _choose_destination_folder(self) -> None:
        initial = self._dest_edit.text() or str(self._runtime.download_directory(self._settings))
        chosen = QFileDialog.getExistingDirectory(
            self, strings.EXPORT_DESTINATION_PICK_TITLE, initial
        )
        if chosen:
            self._dest_edit.setText(chosen)
            self._update_plan()

    # ------------------------------------------------------------------
    # Estado e plano de exportação
    # ------------------------------------------------------------------

    def _fast_available(self, proj: Project) -> bool:
        """Corte rápido só é possível para um único recorte de um único arquivo."""
        # Se a tela ou a taxa pedida forem diferentes da do arquivo de origem,
        # é necessário recompor / recodificar.
        if self._canvas_choice is not None or self._rate_choice is not None:
            return False
        main = self._main_clip(proj)
        if not main or main.is_additional or not (main.media and main.media.path.is_file()):
            return False
        segments = simple_trim(proj)
        return bool(segments) and len(segments) == 1

    def _trim_target(self, proj: Project) -> TrimTarget | None:
        segments = simple_trim(proj)
        if not segments or len(segments) != 1:
            return None
        clip = self._main_clip(proj) or proj.clips[0]
        anchor = keyframe_at_or_before(self._keyframes, segments[0].start)
        return TrimTarget(
            segments=segments,
            container=clip.media.path.suffix.lstrip(".").lower() or "mp4",
            mode=CutMode.FAST,
            anchor=anchor,
            hardware=self._settings.hardware_encoder,
            copy_metadata=False,
        )

    def _main_clip(self, proj: Project) -> Clip | None:
        # Primeiro um vídeo da trilha mais baixa; foto só na falta de vídeo.
        for skip_images in (True, False):
            for track in reversed(proj.video_tracks):
                if track.visible and track.clips:
                    for clip in track.sorted_clips():
                        if skip_images and clip.is_image:
                            continue
                        if clip.overlay_type not in ("text", "filter", "transition") and clip.media and clip.media.path.is_file():
                            return clip
        for t in proj.tracks:
            if t.visible:
                for c in t.clips:
                    if c.overlay_type not in ("text", "filter", "transition") and c.media and c.media.path.is_file():
                        return c
        clips = [c for t in proj.tracks if t.visible for c in t.clips if c.overlay_type not in ("text", "filter", "transition")]
        if clips:
            return clips[0]
        all_visible = [c for t in proj.tracks if t.visible for c in t.clips]
        return all_visible[0] if all_visible else None

    def _container(self, proj: Project) -> str:
        video = self._main_clip(proj)
        if video is None or not video.media.has_video:
            return "m4a"
        suffix = video.media.path.suffix.lstrip(".").lower()
        return "mp4" if not suffix or video.media.kind is MediaKind.IMAGE else suffix

    def _update_plan(self) -> None:
        proj = self._effective_project()
        audio_only = self._audio_only_check.isChecked()

        # Copiar os dados como estão produziria o vídeo da origem, não um GIF.
        can_fast = (self._fast_available(proj) and not audio_only
                    and self._container_choice != "gif")
        self._fast.setEnabled(can_fast)
        if not can_fast and self._fast.isChecked():
            self._fast.setChecked(False)

        can_interp = can_interpolate(proj) and not audio_only
        self._interpolate.setEnabled(can_interp)
        if not can_interp and self._interpolate.isChecked():
            self._interpolate.setChecked(False)

        # Atualiza o texto do item "Automática" em proporção, tela e taxa
        if self._aspect_box.count() > 0 and self._aspect_box.itemData(0) is None:
            proj_aspect = format_aspect_ratio(proj.width, proj.height)
            self._aspect_box.setItemText(
                0,
                f"{strings.EXPORT_ASPECT_AUTO}  ({proj_aspect})"
                if proj_aspect
                else strings.EXPORT_ASPECT_AUTO,
            )
        if self._canvas_box.count() > 0 and self._canvas_box.itemData(0) is None:
            self._canvas_box.setItemText(
                0,
                f"{strings.EDIT_CANVAS_AUTO}  ("
                + strings.EDIT_CANVAS_SIZE.format(width=proj.width, height=proj.height)
                + ")",
            )
        self._rate_box.setItemText(
            0,
            f"{strings.EDIT_CANVAS_RATE_AUTO}  ("
            + strings.EDIT_CANVAS_FPS.format(fps=format_rate(proj.fps))
            + ")",
        )

        is_fast = self._fast.isChecked() and can_fast
        interpolating = self._interpolate.isChecked() and can_interp
        target: TrimTarget | None = None
        container = self._container_choice or "mp4"

        self._quality_box.setEnabled(not is_fast)
        if is_fast:
            self._quality_box.setToolTip(strings.EDIT_MODE_TIP)
        else:
            self._quality_box.setToolTip(strings.EXPORT_QUALITY_TIP)

        # As escolhas de recodificação são guardadas para a volta ao modo
        # exato; durante a cópia os controles anunciam a origem real.
        for box in (self._container_box, self._video_codec_box):
            box.setEnabled(not is_fast)
        self._container_box.blockSignals(True)
        self._video_codec_box.blockSignals(True)
        for box in (self._container_box, self._video_codec_box):
            for index in reversed(range(box.count())):
                if box.itemData(index) == 'source-copy':
                    box.removeItem(index)
        if is_fast:
            source_clip = self._main_clip(proj)
            source_container = self._container(proj)
            local = self._probed.get(source_clip.media.path) if source_clip else None
            codec = local.video.codec if local and local.video else strings.EXPORT_SOURCE_CODEC
            self._container_box.addItem(source_container.upper(), 'source-copy')
            self._video_codec_box.addItem(strings.EXPORT_COPY_CODEC.format(codec=codec), 'source-copy')
            self._container_box.setCurrentIndex(self._container_box.count() - 1)
            self._video_codec_box.setCurrentIndex(self._video_codec_box.count() - 1)
        else:
            self._container_box.setCurrentIndex(_index_of(self._container_box, self._container_choice))
            self._video_codec_box.setCurrentIndex(_index_of(self._video_codec_box, self._codec_choice))
        self._container_box.blockSignals(False)
        self._video_codec_box.blockSignals(False)

        if audio_only:
            container = self._audio_format_choice or "mp3"
            plan = describe_export(
                proj,
                container,
                self._settings.hardware_encoder,
                False,
                audio_only=True,
                audio_codec=container,
            )
            warning = ""
        elif is_fast:
            target = self._trim_target(proj)
            if target:
                container = target.container
                plan = strings.EDIT_PLAN_FAST.format(
                    container=target.container,
                    duration=format_span(target.output_duration),
                )
                warning = self._drift_text(target, proj.fps)
            else:
                plan = ""
                warning = ""
        else:
            container = self._container_choice or "mp4"
            codec_family = ("gif" if container == "gif"
                            else self._codec_choice or hwaccel.family_for(container))
            plan = describe_export(
                proj,
                container,
                self._settings.hardware_encoder,
                interpolating,
                family=codec_family,
                quality=self._quality_choice or hwaccel.QUALITY_BALANCED,
            )
            warning = strings.EXPORT_GIF_NOTE if container == "gif" else ""
            if interpolating:
                warning = strings.EDIT_INTERPOLATE_WARN.format(
                    memory=format_size(interpolation_bytes(proj))
                )

        if hasattr(self, "_ext_label"):
            self._ext_label.setText(f".{container}")

        self._plan.setText(strings.EDIT_PLAN.format(plan=plan))
        self._warning.setText(warning)
        self._warning.setVisible(bool(warning))

        # Calcula estimativa de tamanho do arquivo exportado
        main = self._main_clip(proj)
        source = (
            main.media.path
            if (main and main.media and main.media.path.is_file())
            else (proj.clips[0].media.path if proj.clips else None)
        )
        local = self._probed.get(source) if source else None
        source_size = getattr(local, "size", None)
        source_dur = getattr(local, "duration", None)

        export_duration = target.output_duration if (is_fast and target) else proj.export_duration
        codec_family = ("gif" if self._container_choice == "gif"
                        else self._codec_choice or hwaccel.family_for(self._container_choice or "mp4"))

        est_bytes = estimate_export_size(
            duration=export_duration,
            width=proj.width,
            height=proj.height,
            fps=proj.fps,
            video_codec=codec_family,
            audio_only=audio_only,
            audio_codec=self._audio_format_choice or "mp3",
            is_fast=is_fast,
            source_size=source_size,
            source_duration=source_dur,
            quality=self._quality_choice or hwaccel.QUALITY_BALANCED,
        )
        self._size_label.setText(format_size(est_bytes, estimated=True))

    def _drift_text(self, target: TrimTarget, fps: float) -> str:
        if target.anchor is None:
            return ""
        if target.drift < frame_step(fps):
            return strings.EDIT_DRIFT_NONE
        return strings.EDIT_DRIFT.format(
            time=format_timecode(target.anchor), delta=format_span(target.drift)
        )

    # ------------------------------------------------------------------
    # Enfileirar
    # ------------------------------------------------------------------

    def _on_enqueue(self) -> None:
        tools = self._ensure_tools() if self._ensure_tools else None
        if tools is None:
            QMessageBox.warning(
                self, strings.DIALOG_ERROR_TITLE, "FFmpeg não disponível."
            )
            return

        proj = self._effective_project()
        if proj.is_empty:
            QMessageBox.information(
                self, strings.DIALOG_WARNING_TITLE, strings.EDIT_NO_CLIPS
            )
            return

        audio_only = self._audio_only_check.isChecked()
        gif = (self._container_choice == "gif") and not audio_only
        options = ExportOptions(
            container=self._container_choice or "mp4",
            family=None if gif else self._codec_choice,
            quality=self._quality_choice or "balanced", hardware=self._settings.hardware_encoder,
            interpolate=self._interpolate.isChecked(), audio_only=audio_only,
            audio_codec=self._audio_format_choice or "mp3", fast=self._fast.isChecked(),
            canvas_explicit=self._canvas_choice is not None or self._rate_choice is not None,
            keyframes=self._keyframes, same_folder=self._same_folder.isChecked(),
            directory=Path(self._dest_edit.text().strip()) if self._dest_edit.text().strip() else None,
            custom_name=self._filename_edit.text(), fast_suffix=strings.EDIT_SUFFIX_ONE,
            export_suffix=strings.EDIT_SUFFIX_EDIT,
        )
        try:
            self.created_job = self._processing.export(
                proj, options, fallback=self._runtime.download_directory(self._settings),
                project_path=self._project_path, probed=self._probed,
            )
        except VideoManagerError as exc:
            QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, str(exc))
            return
        target = self.created_job.request.target
        is_fast = isinstance(target, TrimTarget)
        interpolating = getattr(target, "interpolate", False)
        if not is_fast and not audio_only:
            self._settings.default_export_quality = self._quality_choice
        if is_fast and isinstance(target, TrimTarget):
            description = strings.EDIT_PLAN_FAST.format(
                container=target.container,
                duration=format_span(target.output_duration),
            )
        elif audio_only:
            description = describe_export(
                proj,
                target.container,
                self._settings.hardware_encoder,
                False,
                audio_only=True,
                audio_codec=target.audio_codec,
            )
        else:
            description = describe_export(
                proj,
                target.container,
                self._settings.hardware_encoder,
                interpolating,
                family=target.family,
                quality=self._quality_choice or hwaccel.QUALITY_BALANCED,
            )

        self.created_job.description = description
        self.created_job.warnings = (self._warning.text(),) if self._warning.text() else ()

        self.accept()
