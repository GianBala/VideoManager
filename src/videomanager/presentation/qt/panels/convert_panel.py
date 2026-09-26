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
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
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

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.targets import AUDIO_TARGETS
from videomanager.domain.targets import VIDEO_CONTAINERS
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.i18n import Text
from videomanager.domain.compatibility import container_accepts_video
from videomanager.domain.compression import LEVELS
from videomanager.domain.compression import VIDEO_CODECS as COMPRESS_CODECS
from videomanager.domain.compression import compression_target
from videomanager.domain.media import VideoTarget
from videomanager.application.media.conversion_description import describe_target
from videomanager.domain.estimator import estimate_convert_size
from videomanager.application.errors import VideoManagerError
from videomanager.application.formatting import DASH
from videomanager.application.formatting import format_duration
from videomanager.application.formatting import format_size
from videomanager.application.jobs.models import Job
from videomanager.domain.selection import AUDIO_BITRATES
from videomanager.domain.selection import LOSSLESS_AUDIO
from videomanager.application.preferences import Preferences as Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import align_label_column, bind, on_language_change, retext_items
from videomanager.presentation.qt.theme import FIELD_WIDTH
from videomanager.presentation.qt.ports import DesktopRuntimePort
from videomanager.presentation.qt.tasks import WorkerRunner

# Os rótulos que vêm do catálogo são lidos na hora (ver ``_resize_label`` e
# ``_codec_label``): montados no import, ficariam no idioma da abertura.
_RESIZE_OPTIONS = (None, 2160, 1440, 1080, 720, 480, 360)
_VIDEO_CODECS = (("copy", None), ("h264", "H.264"), ("hevc", "HEVC"), ("vp9", "VP9"), ("av1", "AV1"))


def _resize_label(height: int | None) -> str:
    return strings.CONVERT_KEEP if height is None else f"{height}p"


def _codec_label(value: str) -> str | None:
    return strings.CONVERT_COPY_CODEC if value == "copy" else None


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

    delete_requested = Signal()

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

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


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
        *,
        processing,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self.setAcceptDrops(True)
        # O ffmpeg pode ainda não existir quando a aba é montada — ele é
        # provisionado depois de a janela aparecer. Por isso o painel pergunta
        # por ele na hora de usar, em vez de recebê-lo pronto.
        self._ensure_tools = ensure_tools
        self._processing = processing
        self._settings = settings
        self._media: list[LocalMedia] = []
        self._labels: list[QLabel] = []
        self._inspection_token = 0
        self._inspection_worker = None
        self._inspection_paths: list[Path] = []
        self._inspection_pool = QThreadPool(self)
        self._inspection_pool.setMaxThreadCount(1)
        self._inspection_runner = WorkerRunner(self._inspection_pool)
        # A medida dos níveis divide a vaga da inspeção: um ffmpeg por vez da
        # aba, e adicionar arquivos cancela a medida em vez de esperar por ela.
        self._sampling_runner = WorkerRunner(self._inspection_pool)
        self._sampling_token = 0
        self._sampling: set[tuple] = set()
        # Bitrate de vídeo medido por (arquivo, alvo); ``None`` quando a medida
        # falhou e a conta por pixels é o que resta.
        self._samples: dict[tuple, float | None] = {}
        self._tools: FFmpegTools | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Criados antes dos controles de alvo: a montagem deles já chama
        # _update_plan, que mexe nos dois.
        self._start = bind(QPushButton(), "setText", lambda: strings.CONVERT_START)
        self._start.setProperty("role", "primary")
        self._start.clicked.connect(self._start_conversion)
        self._plan = QLabel("")
        self._plan.setProperty("role", "dim")
        self._plan.setWordWrap(True)

        layout.addWidget(self._build_files_group(), 1)
        layout.addWidget(self._build_target_group())
        self._align_label_column()

        actions = QHBoxLayout()
        self._same_folder = bind(QCheckBox(), "setText", lambda: strings.CONVERT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        actions.addWidget(self._same_folder)
        actions.addStretch(1)
        actions.addWidget(self._start)
        layout.addLayout(actions)

        self._update_plan()
        on_language_change(self._retranslate)

    def _retranslate(self) -> None:
        retext_items(self._video_codec, _codec_label)
        retext_items(self._resize, _resize_label)
        retext_items(self._compress_codec, strings.EXPORT_VIDEO_CODECS.get)
        self._align_label_column()
        # O plano, o tamanho estimado e a descrição de cada arquivo levam texto
        # e números do idioma.
        self._update_plan()

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_files_group(self) -> QGroupBox:
        group = bind(QGroupBox(), "setTitle", lambda: strings.CONVERT_FILES_GROUP)
        box = QVBoxLayout(group)
        box.setSpacing(8)

        self._list = _DropList()
        self._list.setMinimumHeight(_LIST_MIN_HEIGHT)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.delete_requested.connect(self._remove_selected)
        box.addWidget(self._list, 1)

        row = QHBoxLayout()
        pick = bind(QPushButton(), "setText", lambda: strings.CONVERT_PICK)
        bind(pick, "setToolTip", lambda: strings.CONVERT_PICK_TIP.format(label=strings.CONVERT_PICK))
        pick.clicked.connect(self._choose_files)
        row.addWidget(pick)
        self._remove = bind(QPushButton(), "setText", lambda: strings.CONVERT_REMOVE)
        bind(self._remove, "setToolTip", lambda: strings.CONVERT_REMOVE_TIP.format(label=strings.CONVERT_REMOVE))
        self._remove.clicked.connect(self._remove_selected)
        self._remove.setEnabled(False)
        row.addWidget(self._remove)
        self._clear_btn = bind(QPushButton(), "setText", lambda: strings.CONVERT_CLEAR)
        self._clear_btn.clicked.connect(self.clear_files)
        self._clear_btn.setEnabled(False)
        row.addWidget(self._clear_btn)
        row.addStretch(1)
        box.addLayout(row)

        self._list.itemSelectionChanged.connect(self._update_remove_button)
        return group

    def _update_remove_button(self) -> None:
        self._remove.setEnabled(bool(self._list.selectedItems()))
        if hasattr(self, "_clear_btn"):
            self._clear_btn.setEnabled(bool(self._media) or self._inspection_worker is not None)

    def _build_target_group(self) -> QGroupBox:
        group = bind(QGroupBox(), "setTitle", lambda: strings.CONVERT_TARGET_GROUP)
        outer = QVBoxLayout(group)
        outer.setSpacing(8)

        modes = QHBoxLayout()
        modes.setContentsMargins(0, 0, 0, 0)
        modes.setSpacing(18)
        self._to_audio = bind(QRadioButton(), "setText", lambda: strings.CONVERT_TO_AUDIO)
        self._to_audio.setChecked(True)
        self._to_audio.toggled.connect(self._on_mode_changed)
        self._to_video = bind(QRadioButton(), "setText", lambda: strings.CONVERT_TO_VIDEO)
        self._to_compress = bind(QRadioButton(), "setText", lambda: strings.CONVERT_TO_COMPRESS)
        # O rádio de áudio não avisa a troca entre vídeo e compressão.
        self._to_compress.toggled.connect(self._on_mode_changed)
        modes.addWidget(self._to_audio)
        modes.addWidget(self._to_video)
        modes.addWidget(self._to_compress)
        modes.addStretch(1)
        outer.addLayout(modes)
        outer.addWidget(self._build_level_table())

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
        self._add_row(form, lambda: strings.LABEL_AUDIO_FORMAT, self._audio_codec)

        self._audio_bitrate = QComboBox()
        for value in AUDIO_BITRATES:
            self._audio_bitrate.addItem(f"{value} kbps", value)
        index = self._audio_bitrate.findData(self._settings.default_audio_quality)
        self._audio_bitrate.setCurrentIndex(max(0, index))
        self._audio_bitrate.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, lambda: strings.LABEL_AUDIO_QUALITY, self._audio_bitrate)

        self._container = QComboBox()
        for value in VIDEO_CONTAINERS:
            self._container.addItem(f".{value}", value)
        self._add_row(form, lambda: strings.LABEL_CONTAINER, self._container)

        self._video_codec = QComboBox()
        for value, label in _VIDEO_CODECS:
            self._video_codec.addItem(label or _codec_label(value), value)
        self._video_codec.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, lambda: strings.LABEL_CODEC, self._video_codec)
        # Conectado depois de o seletor de codec existir: a troca de container
        # decide quais codecs continuam oferecidos.
        self._container.currentIndexChanged.connect(self._on_container_changed)
        self._sync_codec_choices()

        self._resize = QComboBox()
        for value in _RESIZE_OPTIONS:
            self._resize.addItem(_resize_label(value), value)
        self._resize.currentIndexChanged.connect(self._update_plan)
        self._add_row(form, lambda: strings.CONVERT_RESIZE, self._resize)

        self._compress_codec = QComboBox()
        for value in COMPRESS_CODECS:
            self._compress_codec.addItem(strings.EXPORT_VIDEO_CODECS[value], value)
        self._compress_codec.currentIndexChanged.connect(self._on_compress_codec_changed)
        self._add_row(form, lambda: strings.LABEL_CODEC, self._compress_codec)

        for combo in (self._audio_codec, self._audio_bitrate, self._container,
                      self._video_codec, self._resize, self._compress_codec):
            combo.setFixedWidth(FIELD_WIDTH)

        outer.addLayout(form)
        outer.addWidget(self._plan)
        self._form = form
        self._on_mode_changed()
        return group

    def _build_level_table(self) -> QWidget:
        """Os níveis lado a lado com o que cada um custa e rende.

        Uma lista de nomes obrigaria a escolher um nível para descobrir o
        tamanho dele; aqui a troca entre qualidade e tamanho está à vista antes
        de escolher, para os arquivos que estão na lista.
        """
        self._level_table = QWidget()
        self._level_table.setProperty("role", "plain")
        grid = QGridLayout(self._level_table)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        headers = (lambda: strings.CONVERT_LEVEL_HEADER, lambda: strings.CONVERT_QUALITY_HEADER,
                   lambda: strings.CONVERT_SIZE_HEADER)
        for column, text in enumerate(headers):
            header = bind(QLabel(), "setText", text)
            header.setProperty("role", "dim")
            grid.addWidget(header, 0, column, Qt.AlignmentFlag.AlignRight if column == 2 else Qt.AlignmentFlag.AlignLeft)
        # Grupo próprio: os rádios de modo são irmãos no mesmo grupo de tela.
        self._levels = QButtonGroup(self)
        self._level_sizes: list[QLabel] = []
        for row, level in enumerate(LEVELS, start=1):
            button = bind(QRadioButton(), "setText", lambda key=level.key: strings.CONVERT_LEVELS[key])
            self._levels.addButton(button, row - 1)
            grid.addWidget(button, row, 0)
            quality = bind(QLabel(), "setText",
                           lambda level=level: strings.CONVERT_LEVEL_QUALITY[level.key].format(height=level.max_height))
            grid.addWidget(quality, row, 1)
            size = QLabel(DASH)
            grid.addWidget(size, row, 2, Qt.AlignmentFlag.AlignRight)
            self._level_sizes.append(size)
        self._levels.button(1).setChecked(True)  # Equilibrada
        self._levels.idToggled.connect(self._on_level_toggled)
        grid.setColumnStretch(3, 1)
        return self._level_table

    def _on_level_toggled(self, _index: int, checked: bool) -> None:
        if checked:
            self._update_plan()

    def _on_compress_codec_changed(self) -> None:
        # O que estava na fila mede o codec anterior: sairia antes do pedido agora.
        self._cancel_sampling()
        self._update_plan()

    def _on_container_changed(self) -> None:
        self._sync_codec_choices()
        self._update_plan()

    def _sync_codec_choices(self) -> None:
        """Desliga os codecs que o container escolhido não aceita.

        H.264 e HEVC em .webm eram oferecidos e só falhavam na fila, com o erro
        cru do ffmpeg. Se o codec atual deixa de caber, volta para "Copiar", que
        o plano descreve antes de converter — nada é trocado sem aparecer.
        """
        container = self._container.currentData() or "mp4"
        model = self._video_codec.model()
        for index in range(self._video_codec.count()):
            item = model.item(index)
            if item is not None:
                item.setEnabled(container_accepts_video(container, self._video_codec.itemData(index)))
        current = self._video_codec.currentData() or "copy"
        if not container_accepts_video(container, current):
            self._video_codec.setCurrentIndex(self._video_codec.findData("copy"))

    def _add_row(self, form: QFormLayout, text: Callable[[], str], field: QWidget) -> QLabel:
        label = bind(QLabel(), "setText", text)
        self._labels.append(label)
        form.addRow(label, field)
        return label

    def _align_label_column(self) -> None:
        """Uma coluna de rótulos só, como na aba de download.

        As linhas de áudio e as de vídeo se revezam conforme o modo; sem largura
        comum, trocar de modo deslocaria os campos de lado.
        """
        align_label_column(self._labels)

    def _on_mode_changed(self) -> None:
        audio = self._to_audio.isChecked()
        compress = self._to_compress.isChecked()
        for widget in (self._audio_codec, self._audio_bitrate):
            self._set_row_visible(widget, audio)
        for widget in (self._container, self._video_codec, self._resize):
            self._set_row_visible(widget, not audio and not compress)
        self._set_row_visible(self._compress_codec, compress)
        self._level_table.setVisible(compress)
        if not compress:
            self._cancel_sampling()
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
            self, strings.CONVERT_PICK, str(Path.home()), strings.CONVERT_FILE_FILTER,
        )
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        """Inspeciona fora da UI; novos lotes incorporam os caminhos ainda pendentes."""
        tools = self._ensure_tools()
        if tools is None:
            return
        self._tools = tools

        known = {media.path for media in self._media}
        pending = [path for path in dict.fromkeys(self._inspection_paths + paths) if path not in known]
        if not pending:
            return
        self._cancel_inspection()
        self._inspection_paths = pending
        worker = self._runtime.media_worker(self._inspection_token, tools, pending, require_duration=False)
        self._inspection_worker = worker
        worker.signals.finished.connect(self._on_inspected, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_inspection_failed, Qt.ConnectionType.QueuedConnection)
        self._inspection_runner.start(worker, worker.signals.done)
        self._update_remove_button()
        self._update_plan()

    @Slot(int, object)
    def _on_inspected(self, token, result) -> None:
        if token != self._inspection_token:
            return
        self._inspection_worker = None
        self._inspection_paths = []
        known = {media.path for media in self._media}
        for media in result.probed.values():
            if media.path not in known:
                self._media.append(media)
                self._list.addItem(QListWidgetItem(self._describe(media)))
                known.add(media.path)
        if result.rejected:
            QMessageBox.warning(
                self, strings.DIALOG_WARNING_TITLE,
                strings.CONVERT_REJECTED + "\n\n" + "\n".join(result.rejected),
            )
        self._update_remove_button()
        self._update_plan()

    @Slot(int, str)
    def _on_inspection_failed(self, token, message) -> None:
        if token != self._inspection_token:
            return
        self._inspection_worker = None
        self._inspection_paths = []
        self._update_remove_button()
        self._update_plan()
        QMessageBox.warning(self, strings.DIALOG_WARNING_TITLE, message)

    def _cancel_inspection(self) -> None:
        self._inspection_token += 1
        self._inspection_runner.cancel_all()
        self._inspection_worker = None
        self._inspection_paths = []
        self._cancel_sampling()

    def _cancel_sampling(self) -> None:
        self._sampling_token += 1
        self._sampling_runner.cancel_all()
        self._sampling.clear()

    def shutdown(self) -> None:
        self._cancel_inspection()
        self._inspection_pool.waitForDone(2000)

    @staticmethod
    def _describe(media: LocalMedia, after: str | None = None) -> str:
        pieces = [media.path.name]
        if media.video:
            pieces.append(f"{media.video.codec} {media.video.width}x{media.video.height}")
        if media.audio:
            pieces.append(f"{media.audio.codec}")
        pieces.append(format_duration(media.duration))
        size_txt = format_size(media.size)
        if after is not None:
            size_txt = f"{size_txt} → {after}"
        pieces.append(size_txt)
        return "   ·   ".join(pieces)

    def _refresh_list_items(self, targets: list[VideoTarget | AudioTarget]) -> None:
        for idx, (media, target) in enumerate(zip(self._media, targets)):
            item = self._list.item(idx)
            if item:
                estimated = self._estimate(media, target)
                after = strings.CONVERT_MEASURING if estimated is None else format_size(estimated, estimated=True)
                item.setText(self._describe(media, after))

    def _remove_selected(self) -> None:
        self._cancel_sampling()
        for item in self._list.selectedItems():
            row = self._list.row(item)
            self._list.takeItem(row)
            if 0 <= row < len(self._media):
                self._media.pop(row)
        self._update_remove_button()
        self._update_plan()

    def apply_settings(self, settings: Settings) -> None:
        """Adota as preferências recém-salvas pelo diálogo de configurações.

        Sem isto a aba seguia com o objeto antigo: trocar o encoder de placa ou
        a pasta de downloads só valia na conversão depois de reiniciar.
        """
        self._settings = settings
        # A placa escolhida muda o encoder, e com ele o que se mede.
        self._cancel_sampling()
        self._update_plan()

    def clear_files(self) -> None:
        self._clear()

    def _clear(self) -> None:
        self._cancel_inspection()
        self._media.clear()
        self._list.clear()
        self._update_remove_button()
        self._update_plan()

    # ------------------------------------------------------------------
    # Alvo
    # ------------------------------------------------------------------

    def _build_target(self, media: LocalMedia) -> AudioTarget | VideoTarget:
        """O alvo deste arquivo. Na compressão ele depende do arquivo: vídeo
        vira vídeo e áudio vira áudio, na mesma lista."""
        if self._to_compress.isChecked():
            return self._compression_target(media, LEVELS[self._levels.checkedId()])
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
            hardware=self._settings.hardware_encoder,
        )

    def _compression_target(self, media: LocalMedia, level) -> AudioTarget | VideoTarget:
        return compression_target(media, level, self._compress_codec.currentData() or "h264",
                                  self._settings.hardware_encoder)

    @staticmethod
    def _sample_key(media: LocalMedia, target: VideoTarget) -> tuple:
        # Tudo que muda o vídeo codificado, e nada do áudio: Forte e Máxima de
        # um vídeo até 720p gravam a mesma imagem e são medidos uma vez só.
        return (media.path, target.container, target.video_codec, target.quality, target.height, target.hardware)

    def _estimate(self, media: LocalMedia, target: AudioTarget | VideoTarget) -> int | None:
        """Tamanho esperado da saída; ``None`` enquanto a amostra não chega."""
        if not (self._to_compress.isChecked() and isinstance(target, VideoTarget)) or self._tools is None:
            return estimate_convert_size(media, target)
        key = self._sample_key(media, target)
        if key not in self._samples:
            return None
        return estimate_convert_size(media, target, self._samples[key])

    def _request_samples(self) -> None:
        """Enfileira a medida do que falta, começando pelo nível escolhido."""
        if self._tools is None:
            return
        chosen = self._levels.checkedId()
        for level in (LEVELS[chosen], *LEVELS[:chosen], *LEVELS[chosen + 1:]):
            for media in self._media:
                target = self._compression_target(media, level)
                if not isinstance(target, VideoTarget):
                    continue
                key = self._sample_key(media, target)
                if key in self._samples or key in self._sampling:
                    continue
                self._sampling.add(key)
                token = self._sampling_token
                worker = self._runtime.sample_worker(media, target, self._tools)
                worker.signals.finished.connect(partial(self._on_sampled, token, key),
                                                Qt.ConnectionType.QueuedConnection)
                worker.signals.failed.connect(lambda _error, token=token, key=key: self._on_sampled(token, key, None),
                                              Qt.ConnectionType.QueuedConnection)
                self._sampling_runner.start(worker, worker.signals.done)

    def _on_sampled(self, token: int, key: tuple, kbps: float | None) -> None:
        if token != self._sampling_token:
            return
        self._sampling.discard(key)
        self._samples[key] = kbps
        self._update_plan()

    def _update_level_sizes(self) -> None:
        """Tamanho de cada nível para os arquivos da lista, e quanto encolhe."""
        before = sum(m.size for m in self._media) if all(m.size for m in self._media) else None
        for level, label in zip(LEVELS, self._level_sizes):
            sizes = [self._estimate(m, self._compression_target(m, level)) for m in self._media]
            if None in sizes:
                label.setText(strings.CONVERT_MEASURING)
                continue
            after = sum(sizes)
            text = format_size(after, estimated=True) if after else DASH
            if after and before:
                change = round((after - before) * 100 / before)
                text += f"  ({change:+d}%)"
            label.setText(text)

    def _update_plan(self) -> None:
        if self._to_compress.isChecked():
            self._update_level_sizes()
        if self._to_audio.isChecked():
            codec = self._audio_codec.currentData() or "mp3"
            self._audio_bitrate.setEnabled(codec not in LOSSLESS_AUDIO)

        self._start.setEnabled(bool(self._media) and self._inspection_worker is None)
        if self._inspection_worker is not None:
            self._plan.setText(strings.CONVERT_INSPECTING.format(count=len(self._inspection_paths)))
            self._plan.setVisible(True)
            self.changed.emit()
            return
        if not self._media:
            # Escondido, e não só vazio: um rótulo em branco deixava uma faixa
            # de altura sem explicação no meio do grupo.
            self._plan.clear()
            self._plan.setVisible(False)
            self.changed.emit()
            return

        targets = [self._build_target(m) for m in self._media]
        self._refresh_list_items(targets)
        plans = [describe_target(m, t) for m, t in zip(self._media, targets)]
        unique_plans = list(dict.fromkeys(plans))
        estimates = [self._estimate(m, t) for m, t in zip(self._media, targets)]
        total_estimated = None if None in estimates else sum(estimates)
        formatted_size = (strings.CONVERT_MEASURING if total_estimated is None
                          else format_size(total_estimated, estimated=True))
        size_info = strings.CONVERT_ESTIMATED_SIZE.format(size=formatted_size)
        before = sum(m.size for m in self._media) if all(m.size for m in self._media) else None
        if self._to_compress.isChecked() and before and total_estimated:
            template = (strings.CONVERT_COMPRESS_SIZE if total_estimated < before
                        else strings.CONVERT_COMPRESS_SIZE_LARGER)
            size_info = template.format(before=format_size(before), after=formatted_size,
                                        percent=round((before - total_estimated) * 100 / before))
        if self._to_compress.isChecked() and total_estimated:
            # Por arquivo, e não pelo total: é cada tarefa que deixa de gravar o
            # que sai maior, e um lote que encolhe no total pode ter um arquivo
            # baixado da internet que cresce (medido: +24% no nível padrão).
            larger = sum(1 for m, size in zip(self._media, estimates) if m.size and size >= m.size)
            if larger:
                size_info += "\n• " + strings.CONVERT_COMPRESS_NO_GAIN.format(count=larger)

        if len(unique_plans) == 1:
            plan_str = strings.CONVERT_PLAN.format(plan=unique_plans[0])
        else:
            plan_str = strings.CONVERT_PLAN.format(
                plan=strings.CONVERT_PLAN_MIXED.format(plan=unique_plans[0], count=len(self._media))
            )
        self._plan.setText(f"{plan_str}\n• {size_info}")
        self._plan.setVisible(True)
        self.changed.emit()
        if self._to_compress.isChecked():
            self._request_samples()

    # ------------------------------------------------------------------

    def _start_conversion(self) -> None:
        if self._inspection_worker is not None:
            return
        if not self._media:
            QMessageBox.information(
                self, strings.DIALOG_WARNING_TITLE, strings.CONVERT_NO_FILES
            )
            return
        tools = self._ensure_tools()
        if tools is None:
            return

        fallback_dir = self._runtime.download_directory(self._settings)
        use_same_folder = self._same_folder.isChecked()
        compress = self._to_compress.isChecked()

        jobs: list[Job] = []
        skipped: list[str] = []
        fallback_used = False

        for media in self._media:
            target = self._build_target(media)
            try:
                job, used_fallback = self._processing.convert(media, target, same_folder=use_same_folder,
                                                              fallback=fallback_dir, compress=compress)
                # Refeita na exibição: a tarefa fica na fila depois da troca de idioma.
                job.description = Text.of(describe_target, media, target)
                jobs.append(job)
                fallback_used = fallback_used or used_fallback
            except VideoManagerError as exc:
                skipped.append(f"{media.path.name}: {exc}")

        if fallback_used:
            QMessageBox.information(
                self,
                strings.DIALOG_INFO_TITLE,
                strings.CONVERT_FALLBACK.format(folder=fallback_dir),
            )
        if skipped:
            QMessageBox.warning(
                self, strings.DIALOG_WARNING_TITLE,
                strings.CONVERT_SKIPPED + "\n\n" + "\n".join(skipped),
            )
        if jobs:
            self.jobs_ready.emit(jobs)
            # A lista esvazia porque os arquivos foram embora para a fila, que
            # está logo abaixo e continua à vista: sem isso, converter duas
            # vezes seguidas enfileiraria tudo de novo.
            self._clear()
