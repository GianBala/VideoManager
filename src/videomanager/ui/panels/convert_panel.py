"""Conversão de arquivos que o usuário já tem no disco.

Aceita arrastar-e-soltar e vários arquivos de uma vez. Antes de converter, mostra
o que vai acontecer com cada um — em especial se haverá cópia direta ou
recodificação, que é a diferença entre um segundo e vários minutos.

Vive numa aba ao lado da de download, e não num diálogo modal: as duas alimentam
a mesma fila, e enfileirar uma conversão não deve impedir de acompanhar o que já
está baixando.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...core.binaries import FFmpegTools
from ...core.converter import (
    AUDIO_TARGETS,
    VIDEO_CONTAINERS,
    AudioTarget,
    LocalMedia,
    VideoTarget,
    describe_target,
    output_path,
    probe_file,
)
from ...core.errors import VideoManagerError
from ...core.humanize import format_duration, format_size
from ...core.job import Job, JobKind
from ...core.selector import AUDIO_BITRATES, LOSSLESS_AUDIO
from ...core.settings import Settings
from .. import strings
from ..theme import FIELD_WIDTH

_RESIZE_OPTIONS = ((None, strings.CONVERT_KEEP), (2160, "2160p"), (1440, "1440p"),
                   (1080, "1080p"), (720, "720p"), (480, "480p"), (360, "360p"))
_VIDEO_CODECS = (("copy", "Copiar (sem recodificar)"), ("h264", "H.264"),
                 ("hevc", "HEVC"), ("vp9", "VP9"), ("av1", "AV1"))


# Altura mínima da lista de arquivos: cabem quatro linhas, e ela cresce com o
# espaço que sobrar. O padrão do Qt para áreas de rolagem (192 px) é um palpite
# fixo, sem relação com esta lista, e sozinho já estourava a altura da aba.
_LIST_MIN_HEIGHT = 120


class _DropList(QListWidget):
    """Lista de arquivos que diz o que fazer quando está vazia.

    O mesmo tratamento da fila, na outra aba: uma área grande e em branco
    parece tela que não carregou, e o convite a arrastar arquivos precisa estar
    onde os arquivos são soltos.
    """

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count():
            return
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            self.viewport().rect(),
            Qt.AlignmentFlag.AlignCenter,
            strings.CONVERT_DROP_HINT,
        )
        painter.end()


class ConvertPanel(QWidget):
    """Escolhe arquivos e o alvo, e entrega as tarefas prontas para a fila."""

    jobs_ready = Signal(list)  # list[Job]
    # Emitido quando o painel muda de tamanho preferido — o plano aparece, as
    # linhas do modo vídeo entram no lugar das de áudio. A janela redivide o
    # espaço para o painel não ficar cortado.
    changed = Signal()

    def __init__(
        self,
        settings: Settings,
        ensure_tools: Callable[[], FFmpegTools | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        # O ffmpeg pode ainda não existir quando a aba é montada — ele é
        # provisionado depois de a janela aparecer. Por isso o painel pergunta
        # por ele na hora de usar, em vez de recebê-lo pronto.
        self._ensure_tools = ensure_tools
        self._settings = settings
        self._media: list[LocalMedia] = []
        self._labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Criados antes dos controles de alvo: a montagem deles já chama
        # _update_plan, que mexe nos dois.
        self._start = QPushButton(strings.CONVERT_START)
        self._start.setProperty("role", "primary")
        self._start.clicked.connect(self._start_conversion)
        self._plan = QLabel("")
        self._plan.setProperty("role", "dim")
        self._plan.setWordWrap(True)

        layout.addWidget(self._build_files_group(), 1)
        layout.addWidget(self._build_target_group())
        self._align_label_column()

        actions = QHBoxLayout()
        self._same_folder = QCheckBox(strings.CONVERT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        actions.addWidget(self._same_folder)
        actions.addStretch(1)
        actions.addWidget(self._start)
        layout.addLayout(actions)

        self._update_plan()

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_files_group(self) -> QGroupBox:
        group = QGroupBox(strings.CONVERT_FILES_GROUP)
        box = QVBoxLayout(group)
        box.setSpacing(8)

        self._list = _DropList()
        self._list.setMinimumHeight(_LIST_MIN_HEIGHT)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        box.addWidget(self._list, 1)

        row = QHBoxLayout()
        pick = QPushButton(strings.CONVERT_PICK)
        pick.clicked.connect(self._choose_files)
        row.addWidget(pick)
        self._remove = QPushButton(strings.CONVERT_REMOVE)
        self._remove.clicked.connect(self._remove_selected)
        self._remove.setEnabled(False)
        row.addWidget(self._remove)
        row.addStretch(1)
        box.addLayout(row)

        self._list.itemSelectionChanged.connect(self._update_remove_button)
        return group

    def _update_remove_button(self) -> None:
        """"Remover selecionados" sem seleção não faz nada; fica desabilitado."""
        self._remove.setEnabled(bool(self._list.selectedItems()))

    def _build_target_group(self) -> QGroupBox:
        group = QGroupBox(strings.CONVERT_TARGET_GROUP)
        outer = QVBoxLayout(group)
        outer.setSpacing(8)

        modes = QHBoxLayout()
        modes.setContentsMargins(0, 0, 0, 0)
        modes.setSpacing(18)
        self._to_audio = QRadioButton(strings.CONVERT_TO_AUDIO)
        self._to_audio.setChecked(True)
        self._to_audio.toggled.connect(self._on_mode_changed)
        self._to_video = QRadioButton(strings.CONVERT_TO_VIDEO)
        modes.addWidget(self._to_audio)
        modes.addWidget(self._to_video)
        modes.addStretch(1)
        outer.addLayout(modes)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self._audio_codec = QComboBox()
        for codec in AUDIO_TARGETS:
            self._audio_codec.addItem(codec.upper(), codec)
        index = self._audio_codec.findData(self._settings.default_audio_format)
        self._audio_codec.setCurrentIndex(max(0, index))
        self._audio_codec.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, strings.LABEL_AUDIO_FORMAT, self._audio_codec)

        self._audio_bitrate = QComboBox()
        for value in AUDIO_BITRATES:
            self._audio_bitrate.addItem(f"{value} kbps", value)
        index = self._audio_bitrate.findData(self._settings.default_audio_quality)
        self._audio_bitrate.setCurrentIndex(max(0, index))
        self._audio_bitrate.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, strings.LABEL_AUDIO_QUALITY, self._audio_bitrate)

        self._container = QComboBox()
        for value in VIDEO_CONTAINERS:
            self._container.addItem(f".{value}", value)
        self._container.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, strings.LABEL_CONTAINER, self._container)

        self._video_codec = QComboBox()
        for value, label in _VIDEO_CODECS:
            self._video_codec.addItem(label, value)
        self._video_codec.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, strings.LABEL_CODEC, self._video_codec)

        self._resize = QComboBox()
        for value, label in _RESIZE_OPTIONS:
            self._resize.addItem(label, value)
        self._resize.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, strings.CONVERT_RESIZE, self._resize)

        for combo in (self._audio_codec, self._audio_bitrate, self._container,
                      self._video_codec, self._resize):
            combo.setFixedWidth(FIELD_WIDTH)

        outer.addLayout(form)
        outer.addWidget(self._plan)
        self._form = form
        self._on_mode_changed()
        return group

    def _add_row(self, form: QFormLayout, text: str, field: QWidget) -> QLabel:
        label = QLabel(text)
        self._labels.append(label)
        form.addRow(label, field)
        return label

    def _align_label_column(self) -> None:
        """Uma coluna de rótulos só, como na aba de download.

        As linhas de áudio e as de vídeo se revezam conforme o modo; sem largura
        comum, trocar de modo deslocaria os campos de lado.
        """
        width = max(label.sizeHint().width() for label in self._labels)
        for label in self._labels:
            label.setMinimumWidth(width)

    def _on_mode_changed(self) -> None:
        audio = self._to_audio.isChecked()
        for widget in (self._audio_codec, self._audio_bitrate):
            self._set_row_visible(widget, audio)
        for widget in (self._container, self._video_codec, self._resize):
            self._set_row_visible(widget, not audio)
        self._update_plan()

    def _set_row_visible(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self._form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    # ------------------------------------------------------------------
    # Arquivos
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.add_files(paths)
            event.acceptProposedAction()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, strings.CONVERT_PICK, str(Path.home()),
            "Mídia (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts "
            "*.mp3 *.m4a *.aac *.opus *.ogg *.flac *.wav *.wma);;Todos (*)",
        )
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        """Inspeciona e adiciona arquivos, ignorando o que não for mídia."""
        tools = self._ensure_tools()
        if tools is None:
            return

        rejected: list[str] = []
        for path in paths:
            if any(m.path == path for m in self._media):
                continue
            try:
                media = probe_file(path, tools)
            except VideoManagerError as exc:
                rejected.append(f"{path.name}: {exc}")
                continue
            self._media.append(media)
            self._list.addItem(QListWidgetItem(self._describe(media)))

        if rejected:
            QMessageBox.warning(
                self, strings.DIALOG_WARNING_TITLE,
                "Estes arquivos foram ignorados:\n\n" + "\n".join(rejected),
            )
        self._update_plan()

    @staticmethod
    def _describe(media: LocalMedia) -> str:
        pieces = [media.path.name]
        if media.video:
            pieces.append(f"{media.video.codec} {media.video.width}x{media.video.height}")
        if media.audio:
            pieces.append(f"{media.audio.codec}")
        pieces.append(format_duration(media.duration))
        pieces.append(format_size(media.size))
        return "   ·   ".join(pieces)

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            row = self._list.row(item)
            self._list.takeItem(row)
            if 0 <= row < len(self._media):
                self._media.pop(row)
        self._update_plan()

    def _clear(self) -> None:
        self._media.clear()
        self._list.clear()
        self._update_plan()

    # ------------------------------------------------------------------
    # Alvo
    # ------------------------------------------------------------------

    def _build_target(self) -> AudioTarget | VideoTarget:
        if self._to_audio.isChecked():
            codec = self._audio_codec.currentData() or "mp3"
            return AudioTarget(
                codec=codec,
                bitrate=self._audio_bitrate.currentData() or "192",
            )
        return VideoTarget(
            container=self._container.currentData() or "mp4",
            video_codec=self._video_codec.currentData() or "copy",
            audio_codec="copy",
            height=self._resize.currentData(),
        )

    def _update_plan(self) -> None:
        if self._to_audio.isChecked():
            codec = self._audio_codec.currentData() or "mp3"
            self._audio_bitrate.setEnabled(codec not in LOSSLESS_AUDIO)

        self._start.setEnabled(bool(self._media))
        if not self._media:
            # Escondido, e não só vazio: um rótulo em branco deixava uma faixa
            # de altura sem explicação no meio do grupo.
            self._plan.clear()
            self._plan.setVisible(False)
            self.changed.emit()
            return

        target = self._build_target()
        # Descreve pelo primeiro arquivo: descrever todos poluiria a tela, e o
        # que interessa — copiar ou recodificar — é quase sempre igual no lote.
        self._plan.setText(
            strings.CONVERT_PLAN.format(plan=describe_target(self._media[0], target))
        )
        self._plan.setVisible(True)
        self.changed.emit()

    # ------------------------------------------------------------------

    def _start_conversion(self) -> None:
        if not self._media:
            QMessageBox.information(
                self, strings.DIALOG_WARNING_TITLE, strings.CONVERT_NO_FILES
            )
            return
        tools = self._ensure_tools()
        if tools is None:
            return

        target = self._build_target()
        dest_dir = None if self._same_folder.isChecked() else self._settings.resolved_download_dir()

        jobs: list[Job] = []
        skipped: list[str] = []
        for media in self._media:
            # Um arquivo só de áudio não pode virar vídeo: avisar aqui é melhor
            # que deixar a tarefa falhar na fila.
            if isinstance(target, VideoTarget) and not media.has_video:
                skipped.append(f"{media.path.name}: não tem trilha de vídeo")
                continue
            if isinstance(target, AudioTarget) and not media.has_audio:
                skipped.append(f"{media.path.name}: não tem trilha de áudio")
                continue
            try:
                # Reserva o nome de saída no ato (ver ``converter.output_path``).
                # Pasta sem permissão de escrita falha aqui, com o nome do
                # arquivo à vista, em vez de sete minutos depois dentro da fila.
                destination = output_path(media.path, target, dest_dir)
            except VideoManagerError as exc:
                skipped.append(f"{media.path.name}: {exc}")
                continue
            jobs.append(
                Job(
                    url=str(media.path),
                    title=media.path.name,
                    description=describe_target(media, target),
                    kind=JobKind.CONVERT,
                    opts={
                        "media": media,
                        "target": target,
                        "destination": destination,
                        "tools": tools,
                    },
                )
            )

        if skipped:
            QMessageBox.warning(
                self, strings.DIALOG_WARNING_TITLE,
                "Ignorados:\n\n" + "\n".join(skipped),
            )
        if jobs:
            self.jobs_ready.emit(jobs)
            # A lista esvazia porque os arquivos foram embora para a fila, que
            # está logo abaixo e continua à vista: sem isso, converter duas
            # vezes seguidas enfileiraria tudo de novo.
            self._clear()
