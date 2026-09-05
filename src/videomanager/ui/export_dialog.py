"""Diálogo de configurações de exportação do editor de vídeo.

Reúne todas as escolhas de saída (resolução, taxa de quadros, interpolação,
corte rápido sem recodificação e pasta de destino) em uma janela modal dedicada,
liberando espaço para a visualização das trilhas na tela principal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
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

from ..core.binaries import FFmpegTools
from ..core.composer import (
    Composition,
    can_interpolate,
    describe_export,
    interpolation_bytes,
    simple_trim,
)
from ..core.converter import LocalMedia, output_path, probe_file
from ..core import hwaccel
from ..core.estimator import estimate_export_size
from ..core.errors import VideoManagerError
from ..core.humanize import format_rate, format_size
from ..core.job import Job, JobKind
from ..core.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    auto_canvas,
)
from ..core.settings import Settings
from ..core.trimmer import (
    CutMode,
    TrimTarget,
    format_span,
    format_timecode,
    frame_step,
    keyframe_at_or_before,
)
from . import strings

_CANVAS_PRESETS: tuple[tuple[int, int], ...] = (
    (3840, 2160),  # 4K UHD
    (2560, 1440),  # 2K QHD
    (1920, 1080),  # Full HD 16:9
    (1280, 720),   # HD 16:9
    (854, 480),    # SD
    (1080, 1920),  # Vertical Full HD 9:16 (TikTok / Reels / Shorts)
    (720, 1280),   # Vertical HD 9:16
    (1080, 1080),  # Quadrado 1:1
)

_RATE_PRESETS: tuple[float, ...] = (24.0, 25.0, 30.0, 50.0, 60.0)

_CONTAINER_PRESETS: tuple[tuple[str, str], ...] = (
    ("MP4 (.mp4)", "mp4"),
    ("MKV (.mkv)", "mkv"),
    ("WebM (.webm)", "webm"),
    ("QuickTime (.mov)", "mov"),
)

_VIDEO_CODEC_PRESETS: tuple[tuple[str, str], ...] = (
    ("H.264 / AVC (padrão universal)", "h264"),
    ("HEVC / H.265 (alta eficiência)", "hevc"),
    ("AV1 (alta compressão)", "av1"),
    ("VP9 (web)", "vp9"),
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.EXPORT_DIALOG_TITLE)
        self.setMinimumWidth(580)
        self.setModal(True)

        self._project = project
        self._settings = settings
        self._pool = pool
        self._probed = probed
        self._keyframes = keyframes
        self._ensure_tools = ensure_tools
        self._canvas_choice = initial_canvas
        self._rate_choice = initial_rate

        self._container_choice: str = self._default_container(project)
        self._codec_choice: str | None = None
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

        # Formato de áudio (visível no modo somente áudio)
        self._audio_format_label = QLabel(strings.EXPORT_AUDIO_FORMAT)
        self._audio_format_box = QComboBox()
        self._audio_format_box.setToolTip(strings.EXPORT_AUDIO_FORMAT_TIP)
        self._audio_format_box.currentIndexChanged.connect(self._on_audio_format_changed)
        self._form.addRow(self._audio_format_label, self._audio_format_box)

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

        self._dest_edit = QLineEdit(str(self._settings.resolved_download_dir()))
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setEnabled(False)
        folder_row.addWidget(self._dest_edit, 1)

        self._pick_folder_button = QPushButton(strings.EXPORT_DESTINATION_PICK)
        self._pick_folder_button.setEnabled(False)
        self._pick_folder_button.clicked.connect(self._choose_destination_folder)
        folder_row.addWidget(self._pick_folder_button)
        dest_box.addLayout(folder_row)

        main_init = self._main_clip(self._project)
        source_init = main_init.media.path if main_init else (self._project.clips[0].media.path if self._project.clips else None)
        default_stem = f"{source_init.stem}_editado" if source_init else "video_editado"

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
        # Opções de tela
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
        for w, h in [*ordered, *_CANVAS_PRESETS]:
            if (w, h) in seen:
                continue
            seen.add((w, h))
            options_canvas.append(
                (strings.EDIT_CANVAS_SIZE.format(width=w, height=h), (w, h))
            )
        for label, val in options_canvas:
            self._canvas_box.addItem(label, val)

        idx_c = _index_of(self._canvas_box, self._canvas_choice)
        self._canvas_box.setCurrentIndex(max(0, idx_c))

        # Opções de taxa
        self._rate_box.clear()
        options_rate: list[tuple[str, float | None]] = [
            (strings.EDIT_CANVAS_RATE_AUTO, None)
        ]
        rates = {round(ref.fps, 3) for ref in self._pool if ref.has_video and ref.fps}
        for r in sorted(rates | set(_RATE_PRESETS)):
            options_rate.append((strings.EDIT_CANVAS_FPS.format(fps=format_rate(r)), r))
        for label, val in options_rate:
            self._rate_box.addItem(label, val)

        idx_r = _index_of(self._rate_box, self._rate_choice)
        self._rate_box.setCurrentIndex(max(0, idx_r))

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
            self._canvas_label, self._canvas_box,
            self._rate_label, self._rate_box,
            self._advanced_widget,
        ):
            widget.setVisible(not audio_only)
        # Campos de áudio — mostrar apenas no modo somente-áudio
        self._audio_format_label.setVisible(audio_only)
        self._audio_format_box.setVisible(audio_only)

    @staticmethod
    def _default_container(project: Project) -> str:
        """Determina o container padrão a partir da mídia principal do projeto."""
        for track in reversed(project.video_tracks):
            if track.clips:
                clip = track.sorted_clips()[0]
                ext = clip.media.path.suffix.lstrip(".").lower()
                if ext in ("mp4", "mkv", "webm", "mov"):
                    return ext
                return "mp4"
        return "mp4"

    def _effective_project(self) -> Project:
        material = auto_canvas(self._project)
        w, h = self._canvas_choice or (material.width, material.height)
        fps = self._rate_choice or material.fps
        return replace(self._project, width=w, height=h, fps=fps)

    def _on_canvas_changed(self, index: int) -> None:
        if index < 0:
            return
        self._canvas_choice = self._canvas_box.itemData(index)
        self.chosen_canvas = self._canvas_choice
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
        self._update_plan()

    def _on_video_codec_changed(self, index: int) -> None:
        if index < 0:
            return
        self._codec_choice = self._video_codec_box.itemData(index)
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
        initial = self._dest_edit.text() or str(self._settings.resolved_download_dir())
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
        segments = simple_trim(proj)
        return bool(segments) and len(segments) == 1

    def _trim_target(self, proj: Project) -> TrimTarget | None:
        segments = simple_trim(proj)
        if not segments or len(segments) != 1:
            return None
        clip = proj.clips[0]
        anchor = keyframe_at_or_before(self._keyframes, segments[0].start)
        return TrimTarget(
            segments=segments,
            container=clip.media.path.suffix.lstrip(".").lower() or "mp4",
            mode=CutMode.FAST,
            anchor=anchor,
            hardware=self._settings.hardware_encoder,
        )

    def _main_clip(self, proj: Project) -> Clip | None:
        for track in reversed(proj.video_tracks):
            if track.visible and track.clips:
                return track.sorted_clips()[0]
        clips = [c for t in proj.tracks if t.visible for c in t.clips]
        return clips[0] if clips else None

    def _container(self, proj: Project) -> str:
        video = self._main_clip(proj)
        if video is None or not video.media.has_video:
            return "m4a"
        suffix = video.media.path.suffix.lstrip(".").lower()
        return "mp4" if not suffix or video.media.kind is MediaKind.IMAGE else suffix

    def _update_plan(self) -> None:
        proj = self._effective_project()
        audio_only = self._audio_only_check.isChecked()

        can_fast = self._fast_available(proj) and not audio_only
        self._fast.setEnabled(can_fast)
        if not can_fast and self._fast.isChecked():
            self._fast.setChecked(False)

        can_interp = can_interpolate(proj) and not audio_only
        self._interpolate.setEnabled(can_interp)
        if not can_interp and self._interpolate.isChecked():
            self._interpolate.setChecked(False)

        # Atualiza o texto do item "Automática" em tela e taxa
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
            codec_family = self._codec_choice or hwaccel.family_for(container)
            plan = describe_export(
                proj,
                container,
                self._settings.hardware_encoder,
                interpolating,
                family=codec_family,
            )
            warning = ""
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
        source = main.media.path if main else (proj.clips[0].media.path if proj.clips else None)
        local = self._probed.get(source) if source else None
        source_size = local.size if local else None
        source_dur = local.duration if local else None

        export_duration = target.output_duration if (is_fast and target) else proj.export_duration
        codec_family = self._codec_choice or hwaccel.family_for(self._container_choice or "mp4")

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

        main = self._main_clip(proj)
        source = main.media.path if main else proj.clips[0].media.path
        local = self._probed.get(source)
        if local is None:
            try:
                local = probe_file(source, tools)
            except VideoManagerError as exc:
                QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, str(exc))
                return

        audio_only = self._audio_only_check.isChecked()
        can_fast = self._fast_available(proj) and not audio_only
        is_fast = self._fast.isChecked() and can_fast
        interpolating = self._interpolate.isChecked() and can_interpolate(proj) and not audio_only

        if is_fast:
            target = self._trim_target(proj)
        elif audio_only:
            audio_fmt = self._audio_format_choice or "mp3"
            target = Composition(
                proj,
                container=audio_fmt,
                hardware=self._settings.hardware_encoder,
                interpolate=False,
                audio_only=True,
                audio_codec=audio_fmt,
            )
        else:
            container = self._container_choice or "mp4"
            codec_family = self._codec_choice or hwaccel.family_for(container)
            target = Composition(
                proj,
                container=container,
                family=codec_family,
                hardware=self._settings.hardware_encoder,
                interpolate=interpolating,
            )

        if target is None:
            return

        dest_dir: Path | None = None
        if not self._same_folder.isChecked():
            dir_str = self._dest_edit.text().strip()
            dest_dir = Path(dir_str) if dir_str else self._settings.resolved_download_dir()

        suffix = strings.EDIT_SUFFIX_ONE if is_fast else strings.EDIT_SUFFIX_EDIT
        custom_name = self._filename_edit.text().strip() if hasattr(self, "_filename_edit") else ""
        ext_suffix = f".{target.extension.lower()}"
        if custom_name.lower().endswith(ext_suffix):
            custom_name = custom_name[:-len(ext_suffix)].strip()
        try:
            destination = output_path(source, target, dest_dir, suffix, custom_stem=custom_name or None)
        except VideoManagerError as exc:
            QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, str(exc))
            return

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
            )

        self.created_job = Job(
            url=str(source),
            title=destination.name,
            description=description,
            kind=JobKind.TRIM,
            opts={
                "media": local,
                "target": target,
                "destination": destination,
                "tools": tools,
            },
            warnings=(self._warning.text(),) if self._warning.text() else (),
        )

        self.accept()
