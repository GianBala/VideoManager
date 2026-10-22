"""Diálogo de configurações de exportação do editor de vídeo.

Reúne todas as escolhas de saída (resolução, taxa de quadros, interpolação,
corte rápido sem recodificação e pasta de destino) em uma janela modal dedicada,
liberando espaço para a visualização das trilhas na tela principal.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.export_policy import MIN_FFMPEG_FOR_FILTER_IN_TRANSITION
from videomanager.domain.export_policy import can_interpolate
from videomanager.domain.export_policy import region_blur_in_affecting_transition
from videomanager.application.media.export_description import describe_export
from videomanager.domain.render_cost import interpolation_bytes
from videomanager.domain.export_policy import reference_clip
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import VideoTarget
from videomanager.domain.size_model import needs_sample
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
from videomanager.application.preferences import Preferences as Settings
from videomanager.domain.timing import CutMode
from videomanager.domain.timing import TrimTarget
from videomanager.domain.timing import format_span
from videomanager.domain.timing import format_timecode
from videomanager.domain.timing import frame_step
from videomanager.domain.timing import keyframe_at_or_before
from videomanager.domain.i18n import Text
from videomanager.presentation.qt import icons, strings, theme
from videomanager.presentation.qt.panels.edit_widgets import index_of
from videomanager.application.editor.canvas import CANVAS_PRESETS, aspect_of, canvas_for_aspect, output_canvas
from videomanager.presentation.qt.ports import DesktopRuntimePort
from videomanager.presentation.qt.tasks import WorkerRunner

RATE_PRESETS: tuple[float, ...] = (24.0, 25.0, 30.0, 50.0, 60.0)

# Taxas usuais de GIF. São baixas de propósito: cada quadro do GIF é uma imagem
# inteira, então dobrar a taxa dobra o arquivo. Todas dividem 100 sem sobra, que
# é como o formato guarda a duração de cada quadro (centésimos de segundo).
_GIF_RATE_PRESETS: tuple[float, ...] = (10.0, 12.5, 20.0, 25.0)

# Tela e taxa de um GIF em "Automática". Sair na tela do projeto é o que fazia
# o arquivo explodir: medido numa edição de 4 s, 14,9 MB em 1080p a 30 q/s
# contra 1,1 MB com estes limites — e 46 MB contra 3,6 MB quando a origem é
# outro GIF. Escolher tela ou taxa na mão continua valendo.
_GIF_MAX_EDGE = 640
_GIF_MAX_RATE = 15.0

def _quality_presets() -> tuple[tuple[str, str], ...]:
    # Função, e não constante: os rótulos montados no import ficariam no
    # idioma da abertura.
    return (
        (strings.EXPORT_QUALITY_BALANCED, hwaccel.QUALITY_BALANCED),
        (strings.EXPORT_QUALITY_HIGH, hwaccel.QUALITY_HIGH),
        (strings.EXPORT_QUALITY_ECONOMY, hwaccel.QUALITY_ECONOMY),
    )


def canvas_options(pool: list[MediaRef], aspect_choice: str | None,
                   canvas_choice: tuple[int, int] | None) -> list[tuple[str, tuple[int, int] | None]]:
    """Automática, a tela em vigor, os tamanhos do material e os formatos comuns.

    Os tamanhos das mídias importadas vêm antes dos formatos comuns porque são
    os únicos que não custam nada: qualquer outro obriga a redimensionar todo
    bloco. A tela em vigor entra mesmo fora das duas listas — projeto reaberto,
    slideshow —: sem ela a lista mostrava "Automática" enquanto a saída usava
    a tela escolhida, e voltar ao automático de verdade não era possível.
    Uma lista só para o painel e para esta janela.
    """
    sizes = sorted(((ref.width, ref.height) for ref in pool if ref.has_video and ref.width and ref.height),
                   key=lambda size: -size[0] * size[1])
    options: list[tuple[str, tuple[int, int] | None]] = [(strings.EDIT_CANVAS_AUTO, None)]
    seen: set[tuple[int, int]] = set()
    for width, height in ([canvas_choice] if canvas_choice else []) + [*sizes, *CANVAS_PRESETS]:
        aspect = format_aspect_ratio(width, height)
        if (width, height) in seen or (aspect_choice and aspect != aspect_choice):
            continue
        seen.add((width, height))
        label = (f"{aspect} · {width} × {height}" if aspect and not aspect_choice
                 else strings.EDIT_CANVAS_SIZE.format(width=width, height=height))
        options.append((label, (width, height)))
    return options


def rate_options(pool: list[MediaRef], rate_choice: float | None,
                 extra: tuple[float, ...] = ()) -> list[tuple[str, float | None]]:
    """Automática, a taxa em vigor, as taxas do material e as usuais.

    A taxa em vigor entra com o valor exato (24000/1001, não 23,976) e toma o
    lugar da gêmea arredondada do acervo: com as duas, a lista mostrava o
    mesmo rótulo duas vezes.
    """
    rates = {round(ref.fps, 3) for ref in pool if ref.has_video and ref.fps} | set(RATE_PRESETS) | set(extra)
    if rate_choice:
        rates = {rate for rate in rates if abs(rate - rate_choice) > 1e-3} | {rate_choice}
    return [(strings.EDIT_CANVAS_RATE_AUTO, None)] + [
        (strings.EDIT_CANVAS_FPS.format(fps=format_rate(rate)), rate) for rate in sorted(rates)]


def _fast_plan(target: TrimTarget) -> str:
    return strings.EDIT_PLAN_FAST.format(
        container=target.container, duration=format_span(target.output_duration)
    )


def _drift_text(target: TrimTarget, fps: float) -> str:
    if target.anchor is None:
        return ""
    if target.drift < frame_step(fps):
        return strings.EDIT_DRIFT_NONE
    return strings.EDIT_DRIFT.format(
        time=format_timecode(target.anchor), delta=format_span(target.drift)
    )


def _export_warning(container: str, project: Project, interpolating: bool) -> str:
    if interpolating:
        return strings.EDIT_INTERPOLATE_WARN.format(memory=format_size(interpolation_bytes(project)))
    return strings.EXPORT_GIF_NOTE if container == "gif" else ""


def _blur_transition_note(version: int) -> str:
    return strings.EXPORT_BLUR_TRANSITION_WARN.format(version=version)


def _gif_canvas(width: int, height: int) -> tuple[int, int]:
    """Tela de um GIF em "Automática": o maior lado vai a 640 px, no máximo."""
    maior = max(width, height)
    if maior <= _GIF_MAX_EDGE:
        return width, height
    fator = _GIF_MAX_EDGE / maior
    return max(2, int(width * fator) // 2 * 2), max(2, int(height * fator) // 2 * 2)


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
        self.setMinimumWidth(760)
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

        # Bitrate de vídeo medido por (mídia principal, como a exportação a codificaria); ``None`` quando a medida falhou
        # e a conta por pixels é o que resta. Uma vaga só: cada escolha da janela pede a medida da sua.
        self._samples: dict[tuple, float | None] = {}
        self._sampling: set[tuple] = set()
        self._sampling_token = 0
        self._sampling_pool = QThreadPool(self)
        self._sampling_pool.setMaxThreadCount(1)
        self._sampling_runner = WorkerRunner(self._sampling_pool)

        self._build_ui()
        self._sync_presets()
        self._update_plan()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        """Uma seção em cartão: título e o corpo, onde entram os campos."""
        card = QFrame()
        card.setProperty("role", "section")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 16)
        box.setSpacing(10)
        heading = QLabel(title)
        heading.setProperty("role", "section-title")
        box.addWidget(heading)
        return card, box

    def _field(self, label: QLabel, widget: QWidget) -> QWidget:
        """O rótulo em cima e o campo embaixo, numa célula que some quando os dois somem.

        A visibilidade continua sendo a do rótulo e a do campo (as regras de ``_apply_*_visibility`` não
        mudaram); a célula só acompanha, para não deixar um vão de altura onde o campo saiu.
        """
        cell = QWidget()
        cell.setProperty("role", "plain")
        column = QVBoxLayout(cell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        label.setProperty("role", "dim")
        column.addWidget(label)
        column.addWidget(widget)
        self._cells.append((cell, label, widget))
        return cell

    @staticmethod
    def _callout_icon(drawing, role: str) -> QLabel:
        """O ícone à esquerda de um destaque (informação, aviso), no papel do tema que dá o tom do destaque."""
        label = QLabel()
        label.setProperty("role", "plain")
        label.setFixedSize(20, 20)
        label.setPixmap(drawing(theme.papeis(*theme.atual())[role], 20).pixmap(20, 20))
        return label

    def _sync_cells(self) -> None:
        for cell, label, widget in self._cells:
            cell.setVisible(not label.isHidden() or not widget.isHidden())

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self._cells: list[tuple[QWidget, QLabel, QWidget]] = []

        # 1. Resumo da edição
        summary_group, summary_box = self._card(strings.EXPORT_SUMMARY_GROUP)
        summary_box.setSpacing(6)
        # Três pastilhas, e não uma linha: a duração (com o valor em negrito), as trilhas e os blocos.
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for text in (
            strings.EXPORT_SUMMARY_DURATION.format(duration=format_span(self._project.export_duration)),
            strings.EXPORT_SUMMARY_TRACKS.format(tracks=len(self._project.tracks)),
            strings.EXPORT_SUMMARY_CLIPS.format(clips=len(self._project.clips)),
        ):
            chip = QLabel(text)
            chip.setProperty("role", "chip")
            chip.setTextFormat(Qt.TextFormat.RichText)
            chips.addWidget(chip)
        chips.addStretch(1)
        summary_box.addLayout(chips)
        layout.addWidget(summary_group)

        # 2. Configurações de saída
        settings_group, settings_box = self._card(strings.EXPORT_SETTINGS_GROUP)

        # Checkbox Exportar Somente Áudio
        self._audio_only_check = QCheckBox(strings.EXPORT_MODE_AUDIO_ONLY)
        self._audio_only_check.setToolTip(strings.EXPORT_MODE_AUDIO_ONLY_TIP)
        self._audio_only_check.toggled.connect(self._on_audio_only_toggled)
        settings_box.addWidget(self._audio_only_check)

        # Formato de vídeo (container)
        self._container_label = QLabel(strings.EXPORT_CONTAINER)
        self._container_box = QComboBox()
        self._container_box.setToolTip(strings.EXPORT_CONTAINER_TIP)
        self._container_box.currentIndexChanged.connect(self._on_container_changed)

        # Codec de vídeo
        self._video_codec_label = QLabel(strings.EXPORT_VIDEO_CODEC)
        self._video_codec_box = QComboBox()
        self._video_codec_box.setToolTip(strings.EXPORT_VIDEO_CODEC_TIP)
        self._video_codec_box.currentIndexChanged.connect(self._on_video_codec_changed)

        # Qualidade de vídeo
        self._quality_label = QLabel(strings.EXPORT_QUALITY)
        self._quality_box = QComboBox()
        self._quality_box.setToolTip(strings.EXPORT_QUALITY_TIP)
        self._quality_box.currentIndexChanged.connect(self._on_quality_changed)

        # Formato de áudio (visível no modo somente áudio)
        self._audio_format_label = QLabel(strings.EXPORT_AUDIO_FORMAT)
        self._audio_format_box = QComboBox()
        self._audio_format_box.setToolTip(strings.EXPORT_AUDIO_FORMAT_TIP)
        self._audio_format_box.currentIndexChanged.connect(self._on_audio_format_changed)

        # Proporção
        self._aspect_label = QLabel(strings.EXPORT_ASPECT)
        self._aspect_box = QComboBox()
        self._aspect_box.setToolTip(strings.EXPORT_ASPECT_TIP)
        self._aspect_box.currentIndexChanged.connect(self._on_aspect_changed)

        # Resolução / Tela
        self._canvas_label = QLabel(strings.EDIT_CANVAS)
        self._canvas_box = QComboBox()
        self._canvas_box.setToolTip(strings.EDIT_CANVAS_TIP)
        self._canvas_box.currentIndexChanged.connect(self._on_canvas_changed)

        # Taxa de quadros
        self._rate_label = QLabel(strings.EDIT_CANVAS_RATE)
        self._rate_box = QComboBox()
        self._rate_box.setToolTip(strings.EDIT_CANVAS_RATE_TIP)
        self._rate_box.currentIndexChanged.connect(self._on_rate_changed)

        # Opções avançadas
        self._advanced_widget = QWidget()
        self._advanced_widget.setProperty("role", "plain")
        advanced_box = QHBoxLayout(self._advanced_widget)
        advanced_box.setContentsMargins(0, 0, 0, 0)
        advanced_box.setSpacing(18)

        self._fast = QCheckBox(strings.EDIT_MODE_FAST)
        self._fast.setToolTip(strings.EDIT_MODE_TIP)
        self._fast.toggled.connect(self._on_option_toggled)
        advanced_box.addWidget(self._fast)

        self._interpolate = QCheckBox(strings.EDIT_INTERPOLATE)
        self._interpolate.setToolTip(strings.EDIT_INTERPOLATE_TIP)
        self._interpolate.toggled.connect(self._on_option_toggled)
        advanced_box.addWidget(self._interpolate)
        advanced_box.addStretch(1)

        # Os campos em grade de duas colunas, como em exportar.png. Os de uma linha só (qualidade, formato de
        # áudio) ocupam as duas; o que sai de cena (o codec no GIF, tudo de vídeo no só-áudio) deixa a célula
        # vazia e a linha some.
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._field(self._container_label, self._container_box), 0, 0)
        grid.addWidget(self._field(self._video_codec_label, self._video_codec_box), 0, 1)
        grid.addWidget(self._field(self._audio_format_label, self._audio_format_box), 1, 0, 1, 2)
        grid.addWidget(self._field(self._quality_label, self._quality_box), 2, 0, 1, 2)
        grid.addWidget(self._field(self._aspect_label, self._aspect_box), 3, 0)
        grid.addWidget(self._field(self._canvas_label, self._canvas_box), 3, 1)
        grid.addWidget(self._field(self._rate_label, self._rate_box), 4, 0)
        grid.addWidget(self._advanced_widget, 5, 0, 1, 2)
        settings_box.addLayout(grid)
        layout.addWidget(settings_group)

        # O tamanho estimado sobe para o rodapé, junto da ação (como no Download e no Converter).
        self._size_label = QLabel("—")
        self._size_label.setProperty("role", "result-size")

        # 3. Destino do arquivo
        dest_group, dest_box = self._card(strings.EXPORT_DESTINATION_GROUP)

        self._same_folder = QCheckBox(strings.EDIT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        self._same_folder.toggled.connect(self._on_same_folder_toggled)
        dest_box.addWidget(self._same_folder)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self._dest_edit = QLineEdit(str(self._runtime.download_directory(self._settings)))
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setEnabled(False)
        folder_row.addWidget(self._dest_edit, 1)

        self._pick_folder_button = QPushButton(strings.EXPORT_DESTINATION_PICK)
        self._pick_folder_button.setEnabled(False)
        self._pick_folder_button.clicked.connect(self._choose_destination_folder)
        folder_row.addWidget(self._pick_folder_button)
        folder_cell = QWidget()
        folder_cell.setProperty("role", "plain")
        folder_column = QVBoxLayout(folder_cell)
        folder_column.setContentsMargins(0, 0, 0, 0)
        folder_column.setSpacing(4)
        folder_label = QLabel(strings.EXPORT_DESTINATION_FOLDER)
        folder_label.setProperty("role", "dim")
        folder_column.addWidget(folder_label)
        folder_column.addLayout(folder_row)
        dest_box.addWidget(folder_cell)

        main_init = self._main_clip(self._project)
        source_init = (
            main_init.media.path
            if (main_init and main_init.media and main_init.media.path.is_file())
            else None
        )
        if source_init:
            default_stem = f"{source_init.stem}{strings.EXPORT_DEFAULT_SUFFIX}"
        elif self._project_path:
            default_stem = f"{self._project_path.stem}{strings.EXPORT_DEFAULT_SUFFIX}"
        else:
            default_stem = strings.EXPORT_DEFAULT_STEM

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._filename_edit = QLineEdit(default_stem)
        self._filename_edit.setPlaceholderText(strings.EXPORT_FILENAME_PLACEHOLDER)
        name_row.addWidget(self._filename_edit, 1)

        self._ext_label = QLabel(".mp4")
        self._ext_label.setProperty("role", "chip")
        name_row.addWidget(self._ext_label)
        name_cell = QWidget()
        name_cell.setProperty("role", "plain")
        name_column = QVBoxLayout(name_cell)
        name_column.setContentsMargins(0, 0, 0, 0)
        name_column.setSpacing(4)
        name_label = QLabel(strings.EXPORT_FILENAME)
        name_label.setProperty("role", "dim")
        name_column.addWidget(name_label)
        name_column.addLayout(name_row)
        dest_box.addWidget(name_cell)

        layout.addWidget(dest_group)

        # 4. Plano e avisos: o plano é o destaque da janela, o aviso tem a moldura âmbar.
        self._plan = QLabel("")
        self._plan.setWordWrap(True)
        plan_box = QFrame()
        plan_box.setProperty("role", "callout")
        plan_row = QHBoxLayout(plan_box)
        plan_row.setContentsMargins(14, 12, 14, 12)
        plan_row.setSpacing(12)
        plan_row.addWidget(self._callout_icon(icons.info, "accent"), 0, Qt.AlignmentFlag.AlignTop)
        plan_column = QVBoxLayout()
        plan_column.setSpacing(4)
        plan_title = QLabel(strings.EXPORT_PLAN_TITLE.upper())
        plan_title.setProperty("role", "callout-title")
        plan_column.addWidget(plan_title)
        plan_column.addWidget(self._plan)
        plan_row.addLayout(plan_column, 1)
        layout.addWidget(plan_box)

        self._warning = QLabel("")
        self._warning.setProperty("role", "warn")
        self._warning.setWordWrap(True)
        self._warning_box = QFrame()
        self._warning_box.setProperty("role", "callout-warn")
        warning_row = QHBoxLayout(self._warning_box)
        warning_row.setContentsMargins(14, 12, 14, 12)
        warning_row.setSpacing(12)
        warning_row.addWidget(self._callout_icon(icons.warn, "warn"), 0, Qt.AlignmentFlag.AlignTop)
        warning_row.addWidget(self._warning, 1)
        self._warning.setVisible(False)
        self._warning_box.setVisible(False)
        layout.addWidget(self._warning_box)

        # 5. Rodapé: o tamanho estimado e a ação
        footer = QFrame()
        footer.setProperty("role", "footer")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(16, 10, 12, 10)
        actions.setSpacing(10)
        size_column = QVBoxLayout()
        size_column.setSpacing(0)
        size_caption = QLabel(strings.EXPORT_ESTIMATED_SIZE)
        size_caption.setProperty("role", "dim")
        size_column.addWidget(size_caption)
        size_column.addWidget(self._size_label)
        actions.addLayout(size_column)
        actions.addStretch(1)

        self._cancel_button = QPushButton(strings.EXPORT_ACTION_CANCEL)
        self._cancel_button.setProperty("role", "ghost")
        self._cancel_button.clicked.connect(self.reject)
        actions.addWidget(self._cancel_button)

        self._enqueue_button = QPushButton(strings.EXPORT_ACTION_ENQUEUE)
        self._enqueue_button.setProperty("role", "primary")
        self._enqueue_button.setIcon(icons.plus(theme.papeis(*theme.atual())["on_fill"], 16))
        self._enqueue_button.setIconSize(QSize(16, 16))
        self._enqueue_button.setProperty("emphasis", "large")
        self._enqueue_button.setDefault(True)
        self._enqueue_button.clicked.connect(self._on_enqueue)
        actions.addWidget(self._enqueue_button)

        layout.addWidget(footer)

        # Piso de altura de cada campo, o que ele pede de verdade (com o preenchimento do estilo). Sem isso o layout
        # os comprime até o mínimo do Qt quando um aviso entra embaixo (o GIF), cortando o texto ao meio em vez de a
        # janela crescer: ela só cresce até o mínimo do layout, e o mínimo de um combo não inclui o preenchimento.
        for campo in (self._container_box, self._video_codec_box, self._quality_box, self._audio_format_box,
                      self._aspect_box, self._canvas_box, self._rate_box, self._dest_edit, self._filename_edit):
            campo.ensurePolished()
            campo.setMinimumHeight(campo.sizeHint().height())

    # ------------------------------------------------------------------
    # Preenchimento e sincronização
    # ------------------------------------------------------------------

    def _sync_presets(self) -> None:
        """Preenche as opções de tela, taxa, container, codec e formato de áudio."""
        # Opções de proporção
        self._aspect_box.blockSignals(True)
        self._aspect_box.clear()
        aspect_options = [(strings.EXPORT_ASPECT_AUTO, None)] + [
            (label, value) for value, label in strings.EXPORT_ASPECTS.items()
        ]
        for label, val in aspect_options:
            self._aspect_box.addItem(label, val)
        idx_a = index_of(self._aspect_box, self._aspect_choice)
        self._aspect_box.setCurrentIndex(max(0, idx_a))
        self._aspect_box.blockSignals(False)

        # Opções de tela
        self._sync_canvas_box()

    def _sync_canvas_box(self) -> None:
        self._canvas_box.blockSignals(True)
        self._canvas_box.clear()
        for label, val in canvas_options(self._pool, self._aspect_choice, self._canvas_choice):
            self._canvas_box.addItem(label, val)

        idx_c = index_of(self._canvas_box, self._canvas_choice)
        self._canvas_box.setCurrentIndex(max(0, idx_c))
        self._canvas_box.blockSignals(False)

        # Opções de taxa
        self._fill_rates()

        # Container de vídeo
        self._container_box.blockSignals(True)
        self._container_box.clear()
        for val, label in strings.EXPORT_CONTAINERS.items():
            self._container_box.addItem(label, val)
        idx_ct = index_of(self._container_box, self._container_choice)
        self._container_box.setCurrentIndex(max(0, idx_ct))
        self._container_box.blockSignals(False)

        # Codec de vídeo (filtrado pelo container)
        self._sync_codecs()

        # Qualidade de vídeo
        self._quality_box.blockSignals(True)
        self._quality_box.clear()
        for label, val in _quality_presets():
            self._quality_box.addItem(label, val)
        idx_q = index_of(self._quality_box, self._quality_choice)
        self._quality_box.setCurrentIndex(max(0, idx_q))
        self._quality_box.blockSignals(False)

        # Formato de áudio (somente áudio)
        self._audio_format_box.blockSignals(True)
        self._audio_format_box.clear()
        for val, label in strings.EXPORT_AUDIO_FORMATS.items():
            self._audio_format_box.addItem(label, val)
        idx_af = index_of(self._audio_format_box, self._audio_format_choice)
        self._audio_format_box.setCurrentIndex(max(0, idx_af))
        self._audio_format_box.blockSignals(False)

        # Visibilidade inicial
        self._apply_audio_only_visibility()

    def _fill_rates(self) -> None:
        """Repopula as taxas — o GIF traz as dele, mais baixas."""
        self._rate_box.blockSignals(True)
        self._rate_box.clear()
        extra = _GIF_RATE_PRESETS if self._container_choice == "gif" else ()
        for label, val in rate_options(self._pool, self._rate_choice, extra):
            self._rate_box.addItem(label, val)
        idx_r = index_of(self._rate_box, self._rate_choice)
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
        self._sync_cells()

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
        for val, label in strings.EXPORT_VIDEO_CODECS.items():
            if val in allowed:
                self._video_codec_box.addItem(label, val)
        # Tenta restaurar o codec anterior; se não couber, pega o primeiro
        idx_vc = index_of(self._video_codec_box, self._codec_choice)
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
        self._apply_container_visibility()  # sincroniza as células ao fim

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
        return self._output_project(self._canvas_choice, self._rate_choice)

    def _output_project(self, canvas: tuple[int, int] | None, rate: float | None) -> Project:
        """O projeto na tela e na taxa de saída para uma escolha — ``None`` é a automática.

        Separada de ``_effective_project`` para os itens "Automática" poderem perguntar o que
        a escolha automática produz **sem** a escolha em vigor (``_update_plan``).
        """
        w, h, fps = output_canvas(self._project, canvas, rate)
        if self._container_choice == "gif" and not self._audio_only_check.isChecked():
            if canvas is None:
                w, h = _gif_canvas(w, h)
            if rate is None:
                fps = min(fps, _GIF_MAX_RATE)
        return self._project.with_output_canvas(w, h, fps)

    def _on_aspect_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._aspect_choice = self._aspect_box.itemData(index)
        self._canvas_choice = canvas_for_aspect(self._aspect_choice, self._canvas_choice)
        self.chosen_canvas = self._canvas_choice
        self._sync_canvas_box()
        self._update_plan()

    def _on_canvas_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._canvas_choice = self._canvas_box.itemData(index)
        self.chosen_canvas = self._canvas_choice
        if self._canvas_choice is not None:
            new_aspect = aspect_of(self._canvas_choice)
            if new_aspect != self._aspect_choice:
                self._aspect_choice = new_aspect
                idx_a = index_of(self._aspect_box, self._aspect_choice)
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
        return reference_clip(proj, lambda clip: clip.media.path.is_file())

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
        # A opção desligada diz por quê: uma caixa cinza sem explicação parece
        # defeito, e o motivo — a edição não é um recorte, nenhum bloco está
        # abaixo da taxa — não é visível daqui.
        if self._container_choice == "gif" and not audio_only:
            self._fast.setToolTip(strings.EXPORT_GIF_NO_FAST)
        else:
            self._fast.setToolTip(strings.EDIT_MODE_TIP if can_fast else strings.EDIT_FAST_UNAVAILABLE)
        self._interpolate.setToolTip(strings.EDIT_INTERPOLATE_TIP if can_interp else strings.EDIT_INTERPOLATE_OFF)

        # Atualiza o texto do item "Automática" em proporção, tela e taxa. Com o que a escolha
        # automática produz, e não com o projeto efetivo: este já traz a tela e a taxa
        # escolhidas, e "Automática" passava a anunciar a escolha (60 q/s, 9:16...) até ser
        # ela mesma a selecionada.
        auto = self._output_project(None, None)
        if self._aspect_box.count() > 0 and self._aspect_box.itemData(0) is None:
            proj_aspect = format_aspect_ratio(auto.width, auto.height)
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
                + strings.EDIT_CANVAS_SIZE.format(width=auto.width, height=auto.height)
                + ")",
            )
        self._rate_box.setItemText(
            0,
            f"{strings.EDIT_CANVAS_RATE_AUTO}  ("
            + strings.EDIT_CANVAS_FPS.format(fps=format_rate(auto.fps))
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
            self._container_box.setCurrentIndex(index_of(self._container_box, self._container_choice))
            self._video_codec_box.setCurrentIndex(index_of(self._video_codec_box, self._codec_choice))
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
                plan = _fast_plan(target)
                warning = _drift_text(target, proj.fps)
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
            warning = _export_warning(container, proj, interpolating)

        if hasattr(self, "_ext_label"):
            self._ext_label.setText(f".{container}")

        self._plan.setText(plan)
        self._warning.setText(warning)
        self._warning.setVisible(bool(warning))
        self._warning_box.setVisible(bool(warning))

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

        if is_fast and target:
            export_duration = target.output_duration
        elif self._container_choice == "gif" and not audio_only:
            export_duration = proj.video_duration
        else:
            export_duration = proj.export_duration
        codec_family = ("gif" if self._container_choice == "gif"
                        else self._codec_choice or hwaccel.family_for(self._container_choice or "mp4"))

        container = self._container_choice or "mp4"
        measured, pending = self._measured_video_kbps(proj, container, codec_family, audio_only, is_fast)
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
            video_kbps=measured,
            container=container,
        )
        self._size_label.setText(strings.CONVERT_MEASURING if pending else format_size(est_bytes, estimated=True))

    def _measured_video_kbps(self, proj: Project, container: str, family: str, audio_only: bool,
                             is_fast: bool) -> tuple[float | None, bool]:
        """``(bitrate, medindo)``: o da mídia principal codificada como a exportação a codificaria.

        A conta por pixels errava de −66% a +1500% porque não enxerga o conteúdo; a medida pede uns segundos e chega em
        segundo plano. Só a mídia principal é medida: com várias fontes é o que a exportação mais vai gastar, e o
        restante segue a mesma taxa. Cópia, só áudio e GIF não recodificam vídeo de taxa a medir.
        """
        if audio_only or is_fast or family == "gif":
            self._cancel_sampling()
            return None, False
        main = self._main_clip(proj)
        local = self._probed.get(main.media.path) if main else None
        target = VideoTarget(
            container=container, video_codec=family, height=min(proj.width, proj.height), fps=proj.fps,
            quality=self._quality_choice or hwaccel.QUALITY_BALANCED, hardware=self._settings.hardware_encoder,
        )
        if local is None or not needs_sample(local, target):
            self._cancel_sampling()
            return None, False
        key = (local.path, container, family, target.quality, target.height, target.fps, target.hardware)
        if key in self._samples:
            return self._samples[key], False
        # Trocar de opção em sequência não espera a medida de cada passo: a que a escolha atual dispensa sai.
        if any(pedida != key for pedida in self._sampling):
            self._cancel_sampling()
        if key not in self._sampling:
            # Só aqui, quando vai mesmo medir: ``_ensure_tools`` pode abrir a caixa "Baixar o ffmpeg?", e esta conta
            # roda a cada troca de opção da janela (e na montagem dela).
            tools = self._ensure_tools() if self._ensure_tools else None
            if tools is None:
                return None, False
            self._sampling.add(key)
            token = self._sampling_token
            worker = self._runtime.sample_worker(local, target, tools)
            worker.signals.finished.connect(partial(self._on_sampled, token, key), Qt.ConnectionType.QueuedConnection)
            worker.signals.failed.connect(lambda _error, token=token, key=key: self._on_sampled(token, key, None),
                                          Qt.ConnectionType.QueuedConnection)
            self._sampling_runner.start(worker, worker.signals.done)
        return None, True

    def _on_sampled(self, token: int, key: tuple, kbps: float | None) -> None:
        if token != self._sampling_token:
            return
        self._sampling.discard(key)
        self._samples[key] = kbps
        self._update_plan()

    def _cancel_sampling(self) -> None:
        if not self._sampling:
            return
        self._sampling_token += 1
        self._sampling_runner.cancel_all()
        self._sampling.clear()

    def done(self, result: int) -> None:
        # Fechar a janela interrompe o ffmpeg da medida: o destrutor do pool esperaria o prazo dele.
        self._cancel_sampling()
        super().done(result)

    # ------------------------------------------------------------------
    # Enfileirar
    # ------------------------------------------------------------------

    def _blur_transition_warning(self, project: Project, tools: FFmpegTools) -> tuple[Text, ...]:
        """Avisa quando o ffmpeg em uso perde o desfoque numa transição que afeta os adicionais.

        A versão só se consulta (um processo, guardado por caminho) quando o projeto tem essa combinação.
        """
        if not region_blur_in_affecting_transition(project):
            return ()
        version = self._runtime.ffmpeg_major_version(tools)
        if version is None or version >= MIN_FFMPEG_FOR_FILTER_IN_TRANSITION:
            return ()
        return (Text.of(_blur_transition_note, version),)

    def _on_enqueue(self) -> None:
        tools = self._ensure_tools() if self._ensure_tools else None
        if tools is None:
            QMessageBox.warning(
                self, strings.DIALOG_ERROR_TITLE, strings.DIALOG_FFMPEG_UNAVAILABLE
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
        # Descrição e aviso ficam na fila depois de a janela fechar: guardados
        # como texto refeito na exibição, acompanham a troca de idioma — com os
        # mesmos cálculos que a janela acabou de mostrar.
        extra: tuple[Text, ...] = ()
        if is_fast and isinstance(target, TrimTarget):
            description = Text.of(_fast_plan, target)
            warning = Text.of(_drift_text, target, proj.fps)
        elif audio_only:
            description = Text.of(describe_export, proj, target.container, self._settings.hardware_encoder,
                                  False, audio_only=True, audio_codec=target.audio_codec)
            warning = None
        else:
            description = Text.of(describe_export, proj, target.container, self._settings.hardware_encoder,
                                  interpolating, family=target.family,
                                  quality=self._quality_choice or hwaccel.QUALITY_BALANCED)
            warning = Text.of(_export_warning, target.container, proj, interpolating)
            extra = self._blur_transition_warning(proj, tools)

        self.created_job.description = description
        self.created_job.warnings = (*((warning,) if warning is not None and str(warning) else ()), *extra)

        self.accept()
