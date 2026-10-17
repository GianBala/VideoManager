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

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
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
from videomanager.domain.compression import compression_ceiling
from videomanager.domain.compression import VIDEO_CODECS as COMPRESS_CODECS
from videomanager.domain.compression import compression_target
from videomanager.domain.media import VideoTarget
from videomanager.application.media.conversion_description import describe_target
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.size_model import needs_sample
from videomanager.application.errors import VideoManagerError
from videomanager.application.formatting import DASH
from videomanager.application.formatting import format_duration
from videomanager.application.formatting import format_size
from videomanager.application.jobs.models import Job
from videomanager.domain.selection import AUDIO_BITRATES
from videomanager.domain.selection import LOSSLESS_AUDIO
from videomanager.application.preferences import Preferences as Settings
from videomanager.presentation.qt import icons, strings, theme
from videomanager.presentation.qt.panels import convert_rows
from videomanager.presentation.qt.panels.fields import captioned, make_grid
from videomanager.presentation.qt.panels.segmented import SegmentButton, segmented
from videomanager.presentation.qt.i18n import bind, on_language_change, retext_items
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


# Altura da lista de arquivos vazia (o convite tracejado) e quantas linhas ela mostra antes de rolar. A lista tem a altura
# dos arquivos que tem — o protótipo não deixa um vão em branco entre ela e o cartão de baixo —, e o padrão do Qt para áreas de
# rolagem (192 px) é um palpite fixo, sem relação com esta lista.
_LIST_MIN_HEIGHT = 120
_LIST_MAX_ROWS = 6
# O espaço entre os blocos da aba, o mesmo da aba Download.
_SPACING = 18


class _DropList(QListWidget):
    """Lista de arquivos que diz o que fazer quando está vazia.

    O mesmo tratamento da fila, na outra aba: uma área grande e em branco
    parece tela que não carregou, e o convite a arrastar arquivos precisa estar
    onde os arquivos são soltos — com a moldura tracejada, que é o que diz "solte aqui".
    """

    delete_requested = Signal()
    #: O × de uma linha foi clicado (pressionado e solto nele).
    remove_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pressed_remove = -1
        self.setProperty("role", "files")
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.rows = convert_rows.RowDelegate(self)
        self.setItemDelegate(self.rows)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def _remove_row_at(self, position) -> int:
        """A linha cujo × está em ``position``, ou -1."""
        item = self.itemAt(position)
        if item is None or item.data(convert_rows.ROLE_MEDIA) is None:
            return -1
        rect = self.visualItemRect(item)
        return self.row(item) if self.rows.remove_rect(rect.width()).contains(position - rect.topLeft()) else -1

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # O × não é um clique na linha: não pode mudar a seleção que o usuário montou.
        self._pressed_remove = self._remove_row_at(event.position().toPoint())
        if self._pressed_remove >= 0 and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        pressed, self._pressed_remove = self._pressed_remove, -1
        if pressed >= 0 and event.button() == Qt.MouseButton.LeftButton:
            if self._remove_row_at(event.position().toPoint()) == pressed:
                self.remove_requested.emit(pressed)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        item = self.itemAt(event.position().toPoint())
        row = self.row(item) if item is not None else -1
        if self.rows.set_hover(row):
            self.viewport().update()
        over_remove = self._remove_row_at(event.position().toPoint()) >= 0
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over_remove else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.rows.set_hover(-1):
            self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count():
            return
        cores = theme.papeis(*theme.atual())
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.viewport().rect().adjusted(1, 1, -1, -1)
        pen = QPen(QColor(cores["t3"]), 1.2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(area), 12, 12)
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(area, Qt.AlignmentFlag.AlignCenter, strings.CONVERT_DROP_HINT)
        painter.end()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _DropHint(QPushButton):
    """"Solte mais arquivos aqui ou escolha no computador", numa moldura tracejada sob a lista de arquivos.

    É um botão de verdade (Tab, Enter e Espaço abrem o seletor, como o "Adicionar arquivos"); soltar arquivos nele é
    soltar na aba, que já aceita o arraste em qualquer ponto. Só aparece com arquivos na lista: vazia, é a própria lista
    que desenha o convite.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "plain")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        bind(self, "setAccessibleName", lambda: f"{strings.CONVERT_DROP_MORE} {strings.CONVERT_DROP_BROWSE}")
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        cores = theme.papeis(*theme.atual())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        quente = self.underMouse() or self.hasFocus()
        area = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        painter.setPen(QPen(QColor(cores["accent"] if quente else cores["t3"]), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(area, 10, 10)
        fonte = painter.font()
        metricas = painter.fontMetrics()
        resto, link = strings.CONVERT_DROP_MORE, strings.CONVERT_DROP_BROWSE
        icone = 16
        largura = icone + 8 + metricas.horizontalAdvance(resto) + 4 + metricas.horizontalAdvance(link)
        x = int((self.width() - largura) / 2)
        icons.nav_download(cores["t2"], icone).paint(painter, QRect(x, (self.height() - icone) // 2, icone, icone))
        x += icone + 8
        base = (self.height() + metricas.ascent() - metricas.descent()) // 2
        painter.setFont(fonte)
        painter.setPen(QColor(cores["t2"]))
        painter.drawText(x, base, resto)
        painter.setPen(QColor(cores["accent"]))
        painter.drawText(x + metricas.horizontalAdvance(resto) + 4, base, link)
        painter.end()


class ConvertPanel(QWidget):
    """Escolhe arquivos e o alvo, e entrega as tarefas prontas para a fila."""

    jobs_ready = Signal(list)  # list[Job]

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
        # Bitrate medido por (arquivo, alvo) — o do vídeo, ou o do áudio numa
        # conversão só de som; ``None`` quando a medida falhou e a conta por
        # pixels é o que resta.
        self._samples: dict[tuple, float | None] = {}
        self._tools: FFmpegTools | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_SPACING)

        # Criados antes dos controles de alvo: a montagem deles já chama
        # _update_plan, que mexe nos dois.
        self._start = bind(QPushButton(), "setText", self._start_text)
        self._start.setProperty("role", "primary")
        self._start.clicked.connect(self._start_conversion)
        self._plan = QLabel("")
        self._plan.setWordWrap(True)
        self._estimate_label = QLabel(DASH)
        self._estimate_label.setProperty("role", "result-size")
        # O resumo "O que vai acontecer" é um destaque: moldura própria, com o título em cima.
        self._plan_box = QFrame()
        self._plan_box.setProperty("role", "callout")
        # O ícone de informação à esquerda e, ao lado dele, o título pequeno e o texto do plano.
        linha_plano = QHBoxLayout(self._plan_box)
        linha_plano.setContentsMargins(16, 12, 16, 12)
        linha_plano.setSpacing(12)
        self._plan_icon = QLabel()
        self._plan_icon.setProperty("role", "plain")
        linha_plano.addWidget(self._plan_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        caixa = QVBoxLayout()
        caixa.setSpacing(2)
        titulo = bind(QLabel(), "setText", lambda: strings.CONVERT_PLAN_TITLE.upper())
        titulo.setProperty("role", "callout-title")
        caixa.addWidget(titulo)
        self._plan.setProperty("role", "plan")
        caixa.addWidget(self._plan)
        linha_plano.addLayout(caixa, 1)
        self._plan_box.setVisible(False)

        layout.addWidget(self._build_files_group())
        layout.addWidget(self._build_target_group())
        layout.addStretch(1)
        layout.addWidget(self._build_footer())

        self._retheme()
        theme.on_theme_change(self._retheme)
        self._update_plan()
        on_language_change(self._retranslate)

    def _retranslate(self) -> None:
        retext_items(self._video_codec, _codec_label)
        retext_items(self._resize, _resize_label)
        retext_items(self._compress_codec, strings.EXPORT_VIDEO_CODECS.get)
        self._update_files_chip()
        # O plano, o tamanho estimado e a descrição de cada arquivo levam texto
        # e números do idioma.
        self._update_plan()

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_files_group(self) -> QFrame:
        group = QFrame()
        group.setProperty("role", "section")
        box = QVBoxLayout(group)
        box.setContentsMargins(18, 16, 18, 18)
        box.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(8)
        title = bind(QLabel(), "setText", lambda: strings.CONVERT_FILES_GROUP)
        title.setProperty("role", "section-title")
        row.addWidget(title)
        self._files_chip = QLabel()
        self._files_chip.setProperty("role", "chip")
        self._files_chip.setVisible(False)
        row.addWidget(self._files_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        self._pick = bind(QPushButton(), "setText", lambda: strings.CONVERT_PICK)
        self._pick.setProperty("role", "btn")
        bind(self._pick, "setToolTip", lambda: strings.CONVERT_PICK_TIP.format(label=strings.CONVERT_PICK))
        self._pick.clicked.connect(self._choose_files)
        row.addWidget(self._pick)
        # Os dois gestos de limpar são discretos (sem fundo). "Remover selecionados" só aparece quando há seleção: o
        # × de cada linha e a tecla Delete fazem o mesmo, e um botão sempre apagado era ruído.
        self._remove = bind(QPushButton(), "setText", lambda: strings.CONVERT_REMOVE)
        self._remove.setProperty("role", "ghost")
        bind(self._remove, "setToolTip", lambda: strings.CONVERT_REMOVE_TIP.format(label=strings.CONVERT_REMOVE))
        self._remove.clicked.connect(self._remove_selected)
        self._remove.setEnabled(False)
        self._remove.setVisible(False)
        row.addWidget(self._remove)
        self._clear_btn = bind(QPushButton(), "setText", lambda: strings.CONVERT_CLEAR)
        self._clear_btn.setProperty("role", "ghost")
        self._clear_btn.clicked.connect(self.clear_files)
        self._clear_btn.setEnabled(False)
        row.addWidget(self._clear_btn)
        box.addLayout(row)

        self._list = _DropList()
        bind(self._list, "setAccessibleName", lambda: strings.CONVERT_FILES_GROUP)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.delete_requested.connect(self._remove_selected)
        self._list.remove_requested.connect(self._remove_row)
        box.addWidget(self._list)
        self._fit_list()
        # A altura acompanha os arquivos: entra ou sai linha, e a lista refaz a conta.
        for sinal in (self._list.model().rowsInserted, self._list.model().rowsRemoved, self._list.model().modelReset):
            sinal.connect(self._fit_list)

        self._drop_hint = _DropHint()
        self._drop_hint.clicked.connect(self._choose_files)
        # Vazia, é a própria lista que desenha o convite: o de baixo só entra com arquivos (``_fit_list``).
        self._drop_hint.setVisible(False)
        box.addWidget(self._drop_hint)

        self._list.itemSelectionChanged.connect(self._update_remove_button)
        return group

    def _fit_list(self, *_) -> None:
        """A lista tem a altura das linhas que tem (até ``_LIST_MAX_ROWS``, depois rola); vazia, a do convite."""
        linhas = self._list.count()
        if linhas == 0:
            self._list.setFixedHeight(_LIST_MIN_HEIGHT)
        else:
            passo = convert_rows.ALTURA + convert_rows.ENTRE_LINHAS
            self._list.setFixedHeight(min(linhas, _LIST_MAX_ROWS) * passo)
        if hasattr(self, "_drop_hint"):
            self._drop_hint.setVisible(linhas > 0)

    def _build_footer(self) -> QWidget:
        """Onde salvar, quanto deve sair e a ação."""
        footer = QFrame()
        footer.setProperty("role", "footer")
        linha = QHBoxLayout(footer)
        linha.setContentsMargins(20, 12, 12, 12)
        linha.setSpacing(16)
        self._same_folder = bind(QCheckBox(), "setText", lambda: strings.CONVERT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        linha.addWidget(self._same_folder)
        linha.addStretch(1)
        linha.addWidget(self._estimate_label, 0, Qt.AlignmentFlag.AlignBottom)
        estimated = bind(QLabel(), "setText", lambda: strings.CONVERT_ESTIMATED)
        estimated.setProperty("role", "hint")
        linha.addWidget(estimated, 0, Qt.AlignmentFlag.AlignBottom)
        self._start.setProperty("emphasis", "large")
        linha.addWidget(self._start)
        return footer

    def _update_remove_button(self) -> None:
        selecionados = bool(self._list.selectedItems())
        self._remove.setEnabled(selecionados)
        self._remove.setVisible(selecionados)
        if hasattr(self, "_clear_btn"):
            self._clear_btn.setEnabled(bool(self._media) or self._inspection_worker is not None)
            self._update_files_chip()

    def _update_files_chip(self) -> None:
        """"3 arquivos · 472 KB" ao lado do título: o que está na lista, de relance."""
        count = len(self._media)
        self._files_chip.setVisible(count > 0)
        if count:
            singular, plural = strings.CONVERT_FILES_COUNT
            size = format_size(sum(m.size or 0 for m in self._media))
            self._files_chip.setText((singular if count == 1 else plural).format(count=count, size=size))

    def _build_target_group(self) -> QFrame:
        group = QFrame()
        group.setProperty("role", "section")
        outer = QVBoxLayout(group)
        outer.setContentsMargins(18, 16, 18, 18)
        outer.setSpacing(12)
        title = bind(QLabel(), "setText", lambda: strings.CONVERT_TARGET_GROUP)
        title.setProperty("role", "section-title")
        outer.addWidget(title)

        # Os três modos num controle segmentado, com ícone. Continuam sendo três botões de rádio irmãos (o mesmo grupo
        # exclusivo, os mesmos sinais): muda o desenho, não o comportamento nem o teclado (setas trocam de modo).
        self._to_audio = bind(SegmentButton(glyph=icons.music), "setText", lambda: strings.CONVERT_TO_AUDIO)
        self._to_audio.setChecked(True)
        self._to_audio.toggled.connect(self._on_mode_changed)
        self._to_video = bind(SegmentButton(glyph=icons.nav_edit), "setText", lambda: strings.CONVERT_TO_VIDEO)
        self._to_compress = bind(SegmentButton(glyph=icons.compress), "setText", lambda: strings.CONVERT_TO_COMPRESS)
        # O rádio de áudio não avisa a troca entre vídeo e compressão.
        self._to_compress.toggled.connect(self._on_mode_changed)
        segmentos = segmented([self._to_audio, self._to_video, self._to_compress])
        bind(segmentos, "setAccessibleName", lambda: strings.CONVERT_TARGET_GROUP)
        linha_modos = QHBoxLayout()
        linha_modos.addWidget(segmentos)
        linha_modos.addStretch(1)
        outer.addLayout(linha_modos)
        outer.addWidget(self._build_level_table())

        # Campos em grade, com a legenda em cima. Cada modo usa as mesmas colunas; os blocos dos outros modos ficam
        # escondidos (``_set_row_visible``) e não ocupam lugar.
        self._blocks: dict[QWidget, QWidget] = {}
        grade = make_grid()

        def campo(legenda, widget: QWidget, linha: int, coluna: int) -> None:
            bloco = captioned(legenda, widget)
            self._blocks[widget] = bloco
            grade.addWidget(bloco, linha, coluna)

        self._audio_codec = QComboBox()
        for codec in AUDIO_TARGETS:
            self._audio_codec.addItem(codec.upper(), codec)
        index = self._audio_codec.findData(self._settings.default_audio_format)
        self._audio_codec.setCurrentIndex(max(0, index))
        self._audio_codec.currentIndexChanged.connect(self._update_plan)
        campo(lambda: strings.LABEL_AUDIO_FORMAT, self._audio_codec, 0, 0)

        self._audio_bitrate = QComboBox()
        for value in AUDIO_BITRATES:
            self._audio_bitrate.addItem(f"{value} kbps", value)
        index = self._audio_bitrate.findData(self._settings.default_audio_quality)
        self._audio_bitrate.setCurrentIndex(max(0, index))
        self._audio_bitrate.currentIndexChanged.connect(self._update_plan)
        campo(lambda: strings.LABEL_AUDIO_QUALITY, self._audio_bitrate, 0, 1)

        self._container = QComboBox()
        for value in VIDEO_CONTAINERS:
            self._container.addItem(f".{value}", value)
        campo(lambda: strings.LABEL_CONTAINER, self._container, 0, 0)

        self._video_codec = QComboBox()
        for value, label in _VIDEO_CODECS:
            self._video_codec.addItem(label or _codec_label(value), value)
        self._video_codec.currentIndexChanged.connect(self._update_plan)
        campo(lambda: strings.LABEL_CODEC, self._video_codec, 0, 1)
        # Conectado depois de o seletor de codec existir: a troca de container
        # decide quais codecs continuam oferecidos.
        self._container.currentIndexChanged.connect(self._on_container_changed)
        self._sync_codec_choices()

        self._resize = QComboBox()
        for value in _RESIZE_OPTIONS:
            self._resize.addItem(_resize_label(value), value)
        self._resize.currentIndexChanged.connect(self._update_plan)
        campo(lambda: strings.CONVERT_RESIZE, self._resize, 0, 2)

        self._compress_codec = QComboBox()
        for value in COMPRESS_CODECS:
            self._compress_codec.addItem(strings.EXPORT_VIDEO_CODECS[value], value)
        self._compress_codec.currentIndexChanged.connect(self._on_compress_codec_changed)
        campo(lambda: strings.LABEL_CODEC, self._compress_codec, 0, 0)

        outer.addLayout(grade)
        outer.addWidget(self._plan_box)
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
                   lambda: strings.CONVERT_SIZE_HEADER, lambda: strings.CONVERT_CEILING_HEADER)
        for column, text in enumerate(headers):
            header = bind(QLabel(), "setText", text)
            header.setProperty("role", "dim")
            grid.addWidget(header, 0, column, Qt.AlignmentFlag.AlignRight if column >= 2 else Qt.AlignmentFlag.AlignLeft)
        # Grupo próprio: os rádios de modo são irmãos no mesmo grupo de tela.
        self._levels = QButtonGroup(self)
        self._level_sizes: list[QLabel] = []
        self._level_ceilings: list[QLabel] = []
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
            ceiling = QLabel(DASH)
            grid.addWidget(ceiling, row, 3, Qt.AlignmentFlag.AlignRight)
            self._level_ceilings.append(ceiling)
        self._levels.button(1).setChecked(True)  # Equilibrada
        self._levels.idToggled.connect(self._on_level_toggled)
        grid.setColumnStretch(4, 1)
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
        """Mostra ou esconde o campo e a legenda dele (o bloco inteiro)."""
        widget.setVisible(visible)
        self._blocks[widget].setVisible(visible)

    def _start_text(self) -> str:
        """"Converter" sem arquivos e "Converter 3 arquivos" com eles: o botão diz o que vai ser feito."""
        count = len(self._media)
        if not count:
            return strings.CONVERT_START
        singular, plural = strings.CONVERT_START_COUNT
        return (singular if count == 1 else plural).format(count=count)

    def _retheme(self) -> None:
        cores = theme.papeis(*theme.atual())
        self._pick.setIcon(icons.plus(cores["t2"], 18))
        self._start.setIcon(icons.sync(cores["on_fill"], 18))
        self._plan_icon.setPixmap(icons.info(cores["accent"], 20).pixmap(20, 20))

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
                item = QListWidgetItem(self._describe(media))
                item.setData(convert_rows.ROLE_MEDIA, media)
                self._list.addItem(item)
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
                skipped = not self._applies(media, target)
                estimated, approximate = self._estimate_with_quality(media, target)
                after = DASH if skipped else (
                    strings.CONVERT_MEASURING if estimated is None else format_size(estimated, estimated=True))
                item.setText(self._describe(media, after))
                after = {"size": estimated, "approximate": approximate, "skipped": skipped}
                if not skipped and self._tools is not None and not needs_sample(media, target):
                    after["exact"] = True  # copiar, MP3 e WAV: sai por conta, sem o erro de uma medida
                item.setData(convert_rows.ROLE_AFTER, after)

    def _remove_selected(self) -> None:
        self._remove_rows([self._list.row(item) for item in self._list.selectedItems()])

    def _remove_row(self, row: int) -> None:
        """O × da linha: tira só ela, mesmo que outras estejam selecionadas."""
        self._remove_rows([row])

    def _remove_rows(self, rows: list[int]) -> None:
        self._cancel_sampling()
        # De trás para frente: tirar uma linha desloca as de baixo.
        for row in sorted(set(rows), reverse=True):
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
    def _sample_key(media: LocalMedia, target: VideoTarget | AudioTarget) -> tuple:
        # Tudo que muda o que o encoder grava, e nada do que não muda: no áudio, só o codec e o bitrate; no vídeo, o teto
        # também, porque Forte e Máxima de um vídeo até 720p gravam a mesma imagem mas com tetos diferentes, e uma
        # medida feita sob o teto de uma não vale para a outra.
        if isinstance(target, AudioTarget):
            return (media.path, "audio", target.codec, target.bitrate)
        return (media.path, target.container, target.video_codec, target.quality, target.crf, target.height, target.fps,
                target.hardware, target.max_kbps)

    @staticmethod
    def _applies(media: LocalMedia, target: AudioTarget | VideoTarget) -> bool:
        """Se a conversão grava algo para este arquivo: sem a trilha que o alvo pede ela o ignora (``ProcessingService``)."""
        if isinstance(target, AudioTarget):
            return media.has_audio
        return media.has_video and not media.video_is_cover

    def _estimate_with_quality(self, media: LocalMedia, target: AudioTarget | VideoTarget) -> tuple[int | None, bool]:
        """``(tamanho, aproximado)``: ``None`` enquanto a amostra não chega; aproximado quando ela falhou.

        O que recodifica é medido em trechos, na hora de escolher e não só ao comprimir: a conta por pixels não enxerga
        o conteúdo e errou de −66% a +1500% (anunciava que o arquivo cresceria quando ele encolhia). Ela só aparece
        quando a medida não foi possível, e marcada como aproximada.
        """
        if not self._applies(media, target):
            return 0, False  # o arquivo é ignorado na conversão: não grava nada, e a conta por pixels inventaria um tamanho
        if self._tools is None or not needs_sample(media, target):
            return estimate_convert_size(media, target), False
        key = self._sample_key(media, target)
        if key not in self._samples:
            return None, False
        measured = self._samples[key]
        return estimate_convert_size(media, target, measured), measured is None

    def _estimate(self, media: LocalMedia, target: AudioTarget | VideoTarget) -> int | None:
        return self._estimate_with_quality(media, target)[0]

    def _wanted_samples(self) -> dict[tuple, tuple[LocalMedia, VideoTarget | AudioTarget]]:
        """O que a tela precisa medir agora, na ordem em que vale a pena: o que está escolhido primeiro."""
        if self._to_compress.isChecked():
            chosen = self._levels.checkedId()
            pairs = [(media, self._compression_target(media, level))
                     for level in (LEVELS[chosen], *LEVELS[:chosen], *LEVELS[chosen + 1:])
                     for media in self._media]
        else:
            pairs = [(media, self._build_target(media)) for media in self._media]
        wanted: dict[tuple, tuple[LocalMedia, VideoTarget | AudioTarget]] = {}
        for media, target in pairs:
            if needs_sample(media, target):
                wanted.setdefault(self._sample_key(media, target), (media, target))
        return wanted

    def _request_samples(self) -> None:
        """Enfileira a medida do que falta, e abandona a que a escolha atual dispensa."""
        if self._tools is None:
            return
        wanted = self._wanted_samples()
        # Quem troca de codec ou de resolução em sequência não espera a medida de cada passo intermediário: o que está
        # no ar e já não é pedido sai, e a vaga (uma só da aba) vai para o que está escolhido.
        if any(key not in wanted for key in self._sampling):
            self._cancel_sampling()
        for key, (media, target) in wanted.items():
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
        for level, label, ceiling in zip(LEVELS, self._level_sizes, self._level_ceilings):
            targets = [self._compression_target(m, level) for m in self._media]
            # O teto não depende da amostra: aparece na hora. Um arquivo sem teto
            # (na placa, ou sem bitrate de origem) deixa o lote sem garantia.
            limits = [compression_ceiling(m, t) for m, t in zip(self._media, targets)]
            ceiling.setText(strings.CONVERT_CEILING.format(size=format_size(sum(limits)))
                            if limits and None not in limits else DASH)
            sizes = [self._estimate(m, t) for m, t in zip(self._media, targets)]
            if None in sizes:
                label.setText(strings.CONVERT_MEASURING)
                continue
            after = sum(sizes)
            text = format_size(after, estimated=True) if after else DASH
            if after and before:
                change = round((after - before) * 100 / before)
                text += f"  ({change:+d}%)"
            label.setText(text)

    def _set_plan_visible(self, visible: bool) -> None:
        self._plan.setVisible(visible)
        self._plan_box.setVisible(visible)

    def _update_plan(self) -> None:
        if self._to_compress.isChecked():
            self._update_level_sizes()
        if self._to_audio.isChecked():
            codec = self._audio_codec.currentData() or "mp3"
            self._audio_bitrate.setEnabled(codec not in LOSSLESS_AUDIO)

        self._start.setEnabled(bool(self._media) and self._inspection_worker is None)
        bind(self._start, "setText", self._start_text)
        if self._inspection_worker is not None:
            self._plan.setText(strings.CONVERT_INSPECTING.format(count=len(self._inspection_paths)))
            self._set_plan_visible(True)
            self._estimate_label.setText(DASH)
            return
        if not self._media:
            # Escondido, e não só vazio: um rótulo em branco deixava uma faixa
            # de altura sem explicação no meio do grupo.
            self._plan.clear()
            self._set_plan_visible(False)
            self._estimate_label.setText(DASH)
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
        if total_estimated and any(self._estimate_with_quality(m, t)[1] for m, t in zip(self._media, targets)):
            size_info += "\n• " + strings.CONVERT_SIZE_APPROXIMATE
        if self._to_compress.isChecked() and total_estimated:
            # Por arquivo, e não pelo total: é cada tarefa que deixa de gravar o
            # que sai maior, e um lote que encolhe no total pode ter um arquivo
            # baixado da internet que cresce (medido: +24% no nível padrão).
            larger = sum(1 for m, size in zip(self._media, estimates) if m.size and size >= m.size)
            if larger:
                size_info += "\n• " + strings.CONVERT_COMPRESS_NO_GAIN.format(count=larger)

        if len(unique_plans) == 1:
            plan_str = unique_plans[0]
        else:
            plan_str = strings.CONVERT_PLAN_MIXED.format(plan=unique_plans[0], count=len(self._media))
        self._plan.setText(f"{plan_str}\n• {size_info}")
        self._set_plan_visible(True)
        self._estimate_label.setText(formatted_size)
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
