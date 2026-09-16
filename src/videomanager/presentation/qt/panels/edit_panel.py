"""A aba de edição: prévia em cima, linha do tempo multipista embaixo.

A disposição e os gestos são os que os editores de consumo (CapCut, Filmora)
tornaram padrão, porque é o vocabulário que quem vai usar já tem: **importar
mídia, largar na linha do tempo, arrastar os blocos, dividir no cursor, apagar o
que não serve e exportar**. O que está nas trilhas é o que vai ser exportado.

Quatro decisões próprias desta tela:

**O projeto é imutável e o painel é o dono dele.** A linha do tempo só desenha e
avisa a intenção ("este bloco foi solto ali"); quem aplica é aqui, guardando o
estado anterior numa pilha. Desfazer é trocar o projeto pelo anterior — não há
o que reverter passo a passo.

**A prévia é a composição de verdade.** O quadro parado e a reprodução saem do
mesmo grafo do ffmpeg que exporta o arquivo (ver ``infrastructure/ffmpeg/composer``), então
trilha sobreposta, vão preto, volume em decibéis e mudo aparecem na tela como
vão aparecer no resultado. O som é a mixagem, pelo mesmo motivo.

**Um pedido de quadro por vez.** Arrastar o cursor gera dezenas de pedidos por
segundo, e atender todos encheria a fila de trabalho com imagens que ninguém vai
ver. Guardamos só o último e o disparamos quando o anterior volta.

**Enquanto toca, o relógio é o áudio.** O ouvido percebe um engasgo de vinte
milissegundos e o olho não percebe um quadro repetido; com a imagem seguindo o
som, um computador que não dá conta perde quadros e continua no tempo certo.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFontDatabase,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QTabBar,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.media.preview import PreviewFrameInbox, PreviewResultKey
from videomanager.application.media.interaction import interaction_plan
from videomanager.domain.project import slideshow_canvas
from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.media import LocalMedia
from videomanager.application.editor.service import EditorService
from videomanager.application.formatting import format_aspect_ratio, format_rate
from videomanager.domain.preview import fit_size
from videomanager.domain.preview import preview_fps
from videomanager.domain.project import IMAGE_DURATION
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import TrackKind
from videomanager.domain.project import accepts
from videomanager.domain.project import auto_canvas
from videomanager.domain.project import next_clip_id
from videomanager.application.preferences import Preferences as Settings
from videomanager.domain.constants import MIN_SEGMENT
from videomanager.domain.constants import MIN_TRANSITION_DURATION
from videomanager.domain.timing import CutMode
from videomanager.domain.timing import TrimTarget
from videomanager.domain.timing import format_span
from videomanager.domain.timing import format_timecode
from videomanager.domain.timing import frame_index
from videomanager.domain.timing import frame_step
from videomanager.domain.timing import keyframe_after
from videomanager.domain.timing import keyframe_at_or_before
from videomanager.presentation.qt.tasks import WorkerRunner
from videomanager.presentation.qt import icons
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.editor_project import EditorProject
from videomanager.presentation.qt.export_dialog import ExportDialog
from videomanager.presentation.qt.fullscreen_preview import FullscreenPreview
from videomanager.presentation.qt.theme import palette
from videomanager.presentation.qt.panels.timeline import AUDIO_TRACK_HEIGHT
from videomanager.presentation.qt.panels.timeline import FILM_CELL_WIDTH
from videomanager.presentation.qt.panels.timeline import VIDEO_TRACK_HEIGHT
from videomanager.presentation.qt.panels.timeline import Timeline
from videomanager.presentation.qt.panels.timeline import image_from_frame
from videomanager.presentation.qt.panels.timeline import pixmap_from_frame

from videomanager.presentation.qt.panels.edit_widgets import _index_of as _index_of
from videomanager.presentation.qt.panels.edit_widgets import _VolumePopup as _VolumePopup
from videomanager.presentation.qt.panels.edit_widgets import _SpeedPopup as _SpeedPopup
from videomanager.presentation.qt.panels.edit_widgets import _Preview as _Preview
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget as _ClipPropertiesWidget
from videomanager.presentation.qt.panels.edit_widgets import _MediaListWidget as _MediaListWidget
from videomanager.presentation.qt.panels.edit_widgets import _FontSelectorWidget as _FontSelectorWidget
from videomanager.presentation.qt.ports import DesktopRuntimePort

# Altura mínima da prévia, e a altura dela quando retraída. A prévia é o único
# painel que estica: tudo o mais tem altura natural, e o que sobrar de janela
# vira imagem maior.
_PREVIEW_MIN_HEIGHT = 160
_PREVIEW_COLLAPSED = 92
_PREVIEW_MAX_WIDTH = 1280
_FULLSCREEN_MAX_WIDTH = 1920

_VIEW_SETTLE_MS = 220
_RESIZE_SETTLE_MS = 200
# Espera antes de refazer o fluxo depois de uma alteração feita com o vídeo
# tocando. Um arrasto de volume avisa a cada meio decibel: sem a espera, cada
# passo abriria um ffmpeg novo.
_LIVE_RESTART_MS = 200
# Espera antes de gravar as preferências de som, para um arrasto de volume não
# escrever o arquivo de configuração dezenas de vezes.
_PREFS_SAVE_MS = 900
_ZOOM_FACTOR = 1.6
_TICK_MS = 40
_MAX_DRIFT = 0.35
_RESYNC_COOLDOWN = 1.5

# Miniaturas por bloco. O teto existe porque um bloco largo não fica mais
# compreensível com quarenta imagens do que com doze, e cada uma é uma chamada
# ao ffmpeg.
_MAX_THUMBS = 12
_WAVE_MAX_WIDTH = 1200

# Piso da área de trilhas: régua, uma trilha de vídeo e uma de áudio inteiras.
# Sem ele o layout espreme a linha do tempo até sobrar só a régua, porque é a
# prévia que tem política de esticar e ela não abre mão sozinha.
_TIMELINE_MIN_HEIGHT = 150

# Telas oferecidas além das que o próprio material traz. São os formatos que os
# aparelhos e os sites esperam — não uma tabela de tudo que existe.
_CANVAS_PRESETS = (
    (3840, 2160), (2560, 1440), (1920, 1080), (1280, 720), (854, 480),  # 16:9
    (1080, 1920), (720, 1280),  # 9:16
    (1440, 1080), (960, 720), (640, 480),  # 4:3
    (1080, 1080), (720, 720),  # 1:1
    (2560, 1080),  # 21:9
)
_RATE_PRESETS = (24.0, 25.0, 30.0, 50.0, 60.0)

# Piso das duas listas de saída, com folga. Quem paga um piso apertado é o
# item "Automática" — o texto mais longo das duas listas, e justamente o que
# diz em que tela e em que taxa a edição está. Medido com a fonte da
# aplicação, que o QSS fixa em 10pt: "Automática · segue o material
# (3840 × 2160)" pede 299 px e "Automática (29,97 fps)" pede 172, já com os
# 38 px de moldura e seta do Fusion. Os valores anteriores, 210 e 130,
# cortavam os dois. ``AdjustToContents``, logo abaixo, cobre o que passar
# disto — uma taxa de três dígitos, um tamanho de tela maior.
_CANVAS_BOX_WIDTH = 300
_RATE_BOX_WIDTH = 210

# Vagas de ffmpeg da aba (ver o construtor). Números pequenos e de propósito: o
# que limita aqui não é o processador, é a memória — cada worker decodifica
# vídeo, e o material que se edita costuma ser o mais pesado que a máquina tem.
_LIVE_WORKERS = 2        # o quadro parado e a reprodução, que nunca esperam
_BACKGROUND_WORKERS = 2  # tira, onda e keyframes, que podem esperar

# Respiro entre os botões que agem sobre a edição inteira (desfazer, refazer) e
# os que agem sobre o bloco selecionado (dividir, excluir). Sem ele os quatro se
# leem como um grupo só, e o usuário procura em "desfazer" o alvo que "excluir"
# tem. É mais que o espaçamento normal da barra, que é 6.
_TOOL_GROUP_GAP = 22
# Distância entre o volume do bloco e o grupo de zoom, na outra ponta da barra.
_VOLUME_ZOOM_GAP = 72

# Em quantos passos uma seta da barra de navegação atravessa a janela visível.
# Dez dá um passo curto o bastante para ajustar e longo o bastante para andar.
_SCROLL_STEPS = 10


def _bounded_pool(parent: QObject, threads: int) -> QThreadPool:
    """Uma fila própria, com teto — nunca a global.

    ``QThreadPool.globalInstance()`` dimensiona por núcleo, o que é a conta certa
    para trabalho que ocupa um núcleo e a errada para trabalho que abre um
    processo de ffmpeg: ali cada vaga custa a memória de um decodificador
    inteiro, e as vagas todas juntas custam mais do que a máquina tem.
    """
    pool = QThreadPool(parent)
    pool.setMaxThreadCount(threads)
    return pool


class EditPanel(QWidget):
    """Monta um projeto de várias trilhas e entrega a exportação para a fila."""

    jobs_ready = Signal(list)  # list[Job]
    changed = Signal()

    @property
    def desktop_runtime(self):
        return self._runtime

    @property
    def current_project(self):
        return self._project

    @property
    def project_path(self):
        return self._project_path

    @property
    def media_references(self):
        return tuple(self._pool)

    def ensure_tools(self):
        return self._ensure_tools()

    def stop_playback(self):
        self._stop_playback()

    def refresh_project_label(self):
        self._update_project_label()

    def accept_import(self, result, *, insert=False):
        self._probed.update(result.probed)
        for ref in result.references:
            self._pool_thumbnails.pop(ref.path, None)
            self._pool_tokens.pop(ref.path, None)
        existing = {ref.path for ref in self._pool}
        self._pool.extend(ref for ref in result.references if ref.path not in existing)
        self._refresh_pool()
        if result.references:
            self._media_list.setCurrentRow(self._pool.index(result.references[-1]))
            if insert:
                self._remember()
                for reference in result.references:
                    self._place(reference)
                self._after_edit(refit=True)

    def install_project(self, project, path, references, probed, *, reset=True):
        self._generation += 1
        self._end_edit_groups()
        self._stop_playback()
        self._cancel_primed_playback()
        self._background.cancel_all()
        self._runner.cancel_all()
        self._frame_token = next(self._tokens)
        self._strip_tokens.clear()
        for clip_id in list(self._strip_workers):
            self._cancel_strip(clip_id)
        if reset:
            self._session.reset(project, path)
        self._pool = list(references)
        self._pool_thumbnails.clear()
        self._pool_tokens.clear()
        self._probed = dict(probed)
        self._canvas_choice = (project.width, project.height) if path else None
        self._aspect_choice = format_aspect_ratio(project.width, project.height) if path else None
        self._rate_choice = project.fps if path else None
        self._keyframes = ()
        self._keyframe_source = None
        self._keyframe_token = next(self._tokens)
        self._clipboard = None
        self._refresh_pool()
        self._after_edit(refit=True)
        self._session.mark_saved()
        self._timeline.fit()
        self._update_project_label()

    @property
    def _project(self) -> Project:
        return self._session.project

    @_project.setter
    def _project(self, project: Project) -> None:
        self._session.replace_current(project)

    @property
    def _project_path(self) -> Path | None:
        return self._session.path

    @_project_path.setter
    def _project_path(self, path: Path | None) -> None:
        self._session.set_path(path)

    def __init__(
        self,
        settings: Settings,
        ensure_tools: Callable[[], FFmpegTools | None],
        parent: QWidget | None = None,
        *,
        editor: EditorService,
        processing,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self.setAcceptDrops(True)
        self._settings = settings
        self._ensure_tools = ensure_tools
        # Duas filas, e nenhuma delas é a global. Todo worker daqui abre um
        # ffmpeg, e a global tem uma vaga por núcleo — 20 nesta máquina. Uma
        # linha do tempo com quatro blocos disparava quatro tiras e quatro ondas
        # de uma vez: **oito ffmpeg**, ~900 MB cada, todos decodificando o mesmo
        # material que ninguém ainda pediu para ver. Foi o que, somado a uma
        # exportação, esgotou a memória da máquina e derrubou a sessão.
        #
        # A separação existe porque as duas esperas são diferentes. Quadro e
        # reprodução respondem ao usuário e não podem ficar atrás de trabalho de
        # fundo numa fila só — duas vagas, que é exatamente o que eles usam (um
        # quadro por vez, uma reprodução por vez). Tira, onda e keyframes são de
        # fundo, aparecem preenchendo e podem esperar.
        self._runner = WorkerRunner(_bounded_pool(self, _LIVE_WORKERS))
        self._background = WorkerRunner(_bounded_pool(self, _BACKGROUND_WORKERS))
        self._colors = palette(settings.theme)

        self._processing = processing
        self.editor = editor
        self._session = editor.session
        self._pool: list[MediaRef] = []
        self._probed: dict[Path, LocalMedia] = {}
        self._clipboard: Clip | None = None
        self._keyframes: tuple[float, ...] = ()
        self._keyframe_source: Path | None = None
        self._keyframe_token = 0
        self._keyframe_worker = None
        # Tela pedida, ou ``None`` para seguir o material. Mora aqui, e não no
        # projeto, porque é preferência de saída e não parte da montagem — ver
        # :meth:`_sync_canvas`.
        self._canvas_choice: tuple[int, int] | None = None
        self._aspect_choice: str | None = None
        self._rate_choice: float | None = None

        self._tokens = itertools.count(1)
        self._frame_token = 0
        self._play_token = 0
        self._strip_tokens: dict[int, int] = {}
        self._strip_workers: dict[int, object] = {}
        self._wave_requests: dict[int, tuple] = {}
        self._pool_tokens: dict[Path, int] = {}
        self._frame_busy = False
        self._frame_job_token = 0
        self._frame_key = None
        self._presented_key = None
        self._frame_error_token = 0
        self._generation = 0
        self._closed = False
        self._wanted: float | None = None
        self._rendered: float | None = None
        # O instante sozinho não identifica um quadro: duas versões diferentes
        # da edição podem pedir exatamente o mesmo ponto da linha do tempo. A
        # revisão impede que o resultado anterior ao redimensionamento de uma
        # transição seja aceito como se pertencesse ao projeto mais recente.
        self._frame_revision = 0
        self._playing = False
        self._playback: object | None = None
        # O worker preparado mantém o primeiro quadro no cano enquanto a
        # prévia está pausada. Assim o clique em play só abre uma comporta; não
        # precisa montar naquele momento o grafo mais caro de uma transição.
        self._primed_playback: object | None = None
        self._primed_key: tuple[object, ...] | None = None
        self._primed_token = 0
        self._primed_ready = False
        # Quando ainda não houve tempo de preparar o vídeo, o áudio espera o
        # primeiro quadro. Começar o som durante a abertura do FFmpeg deixaria
        # a imagem atrasada justamente no caminho de contingência.
        self._pending_audio: tuple[object, float, object, object] | None = None
        self._fullscreen: FullscreenPreview | None = None
        self._syncing = False
        self._shown_frame = 0.0
        self._clock_position = 0.0
        self._clock_started: float | None = None
        self._resynced_at = 0.0
        self._resume_wanted = False
        self._collapsed = False
        self._gain_session = -1
        self._speed_session = -1
        self._overlay_drag_session = -1
        self._interaction_context = None
        self._interaction_worker = None
        self._interaction_token = 0
        self._properties_session = -1
        self._typing_session = -1
        self._pool_thumbnails: dict[Path, QIcon] = {}
        self._selected_filter_name = "pb"
        self._project_path: Path | None = None
        self._session.mark_saved()

        self._project_actions = EditorProject(self)
        self._audio = self._runtime.audio_output(self)
        self._audio.stopped.connect(self._on_audio_stopped)
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._on_tick)

        self._view_timer = QTimer(self)
        self._view_timer.setSingleShot(True)
        self._view_timer.setInterval(_VIEW_SETTLE_MS)
        self._view_timer.timeout.connect(self._refresh_backdrop)

        self._prefs_timer = QTimer(self)
        self._prefs_timer.setSingleShot(True)
        self._prefs_timer.setInterval(_PREFS_SAVE_MS)
        self._prefs_timer.timeout.connect(self._save_audio_prefs)

        self._properties_session_timer = QTimer(self)
        self._properties_session_timer.setSingleShot(True)
        self._properties_session_timer.setInterval(400)
        self._properties_session_timer.timeout.connect(self._end_properties_session)

        self._typing_timer = QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.setInterval(1200)
        self._typing_timer.timeout.connect(self._end_typing_session)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_SETTLE_MS)
        self._resize_timer.timeout.connect(lambda: self._request_frame(force=True))

        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(_LIVE_RESTART_MS)
        self._live_timer.timeout.connect(self._restart_stream)

        self._build_ui()
        self._install_shortcuts()
        self._refresh_all()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addWidget(self._build_top_bar())

        # Divisor vertical principal: metade superior (mídia + monitor) e
        # metade inferior (linha do tempo).
        self._split_view = QSplitter(Qt.Orientation.Vertical)
        self._split_view.setChildrenCollapsible(False)

        # Divisor horizontal superior (estilo CapCut): biblioteca de mídias à
        # esquerda e monitor de vídeo com controles de transporte à direita.
        self._top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._top_splitter.setChildrenCollapsible(False)

        self._media_box = self._build_media_box()
        self._top_splitter.addWidget(self._media_box)

        self._extras_box = self._build_extras_box()
        self._top_splitter.addWidget(self._extras_box)

        self._player_box = self._build_player()
        self._top_splitter.addWidget(self._player_box)

        self._top_splitter.setStretchFactor(0, 0)
        self._top_splitter.setStretchFactor(1, 0)
        self._top_splitter.setStretchFactor(2, 1)
        self._top_splitter.splitterMoved.connect(self._on_splitter_moved)

        self._split_view.addWidget(self._top_splitter)

        self._timeline_box = self._build_timeline_area()
        self._split_view.addWidget(self._timeline_box)

        self._split_view.setStretchFactor(0, 1)
        self._split_view.setStretchFactor(1, 1)
        self._split_view.splitterMoved.connect(self._on_splitter_moved)

        self._layout.addWidget(self._split_view, 1)

    def _build_top_bar(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._new_btn = QPushButton(strings.EDIT_NEW_BUTTON)
        self._new_btn.setToolTip(f"{strings.ACTION_NEW_PROJECT} (Ctrl+N)")
        self._new_btn.clicked.connect(self.new_project)
        row.addWidget(self._new_btn)

        self._open_btn = QPushButton(strings.EDIT_OPEN_BUTTON)
        self._open_btn.setToolTip(f"{strings.ACTION_OPEN_PROJECT} (Ctrl+O)")
        self._open_btn.clicked.connect(lambda: self.open_project())
        row.addWidget(self._open_btn)

        self._save_btn = QPushButton(strings.EDIT_SAVE_BUTTON)
        self._save_btn.setToolTip(f"{strings.ACTION_SAVE_PROJECT} (Ctrl+S)")
        self._save_btn.clicked.connect(self.save_project)
        row.addWidget(self._save_btn)

        self._save_as_btn = QPushButton(strings.EDIT_SAVE_AS_BUTTON)
        self._save_as_btn.setToolTip(f"{strings.ACTION_SAVE_PROJECT_AS} (Ctrl+Shift+S)")
        self._save_as_btn.clicked.connect(self.save_project_as)
        row.addWidget(self._save_as_btn)

        row.addSpacing(6)
        self._project_label = QLabel("")
        self._project_label.setProperty("role", "dim")
        row.addWidget(self._project_label)
        self._update_project_label()

        row.addStretch(1)

        self._slideshow_button = QPushButton(strings.EDIT_SLIDESHOW)
        self._slideshow_button.setToolTip(strings.EDIT_SLIDESHOW_TIP)
        self._slideshow_button.clicked.connect(self._apply_slideshow_canvas)
        row.addWidget(self._slideshow_button)

        aspect_label = QLabel(strings.EDIT_CANVAS_ASPECT)
        aspect_label.setProperty("role", "dim")
        row.addWidget(aspect_label)

        self._aspect_box = QComboBox()
        self._aspect_box.setToolTip(strings.EDIT_CANVAS_ASPECT_TIP)
        self._aspect_box.currentIndexChanged.connect(self._on_aspect_choice)
        row.addWidget(self._aspect_box)

        canvas_label = QLabel(strings.EDIT_CANVAS)
        canvas_label.setProperty("role", "dim")
        row.addWidget(canvas_label)

        self._canvas_box = QComboBox()
        self._canvas_box.setToolTip(strings.EDIT_CANVAS_TIP)
        self._canvas_box.currentIndexChanged.connect(self._on_canvas_choice)
        row.addWidget(self._canvas_box)

        self._rate_box = QComboBox()
        self._rate_box.setToolTip(strings.EDIT_CANVAS_RATE_TIP)
        self._rate_box.currentIndexChanged.connect(self._on_rate_choice)

        row.addSpacing(6)

        self._collapse = QPushButton(strings.EDIT_COLLAPSE)
        self._collapse.setToolTip(strings.EDIT_COLLAPSE_TIP)
        self._collapse.clicked.connect(self._toggle_collapsed)
        row.addWidget(self._collapse)

        self._fullscreen_button = QPushButton(strings.EDIT_FULLSCREEN)
        self._fullscreen_button.setToolTip(strings.EDIT_FULLSCREEN_TIP)
        self._fullscreen_button.clicked.connect(self._toggle_fullscreen)
        row.addWidget(self._fullscreen_button)

        self._export_button = QPushButton(strings.EDIT_EXPORT_BUTTON)
        self._export_button.setProperty("role", "primary")
        self._export_button.setToolTip(strings.EDIT_EXPORT_BUTTON_TIP)
        self._export_button.clicked.connect(self._open_export_dialog)
        row.addWidget(self._export_button)

        return box

    def _update_project_label(self) -> None:
        if not hasattr(self, "_project_label"):
            return
        name = self._project_path.name if self._project_path else strings.EDIT_UNTITLED
        dirty = " *" if self.has_unsaved_changes else ""
        self._project_label.setText(strings.EDIT_PROJECT_STATUS.format(name=name, dirty=dirty))
        self._project_label.setToolTip(strings.EDIT_PROJECT_V2_TIP)

    def _build_media_box(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        box.setMinimumWidth(260)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        title = QLabel(strings.EDIT_MEDIA_POOL_TITLE)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)

        self._pool_count_label = QLabel("")
        self._pool_count_label.setProperty("role", "dim")
        header.addWidget(self._pool_count_label)
        header.addStretch(1)

        self._import = QPushButton("+ Importar")
        self._import.setToolTip(strings.EDIT_IMPORT_TIP)
        self._import.clicked.connect(self._choose_files)
        header.addWidget(self._import)
        layout.addLayout(header)

        self._media_list = _MediaListWidget()
        self._media_list.setToolTip(strings.EDIT_POOL_TIP)
        self._media_list.itemDoubleClicked.connect(lambda _: self._insert_selected_media())
        self._media_list.itemSelectionChanged.connect(self._on_media_selection_changed)
        self._media_list.delete_requested.connect(self._delete_selected_media)
        self._media_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._media_list.customContextMenuRequested.connect(self._show_media_context_menu)
        self._media_list.files_dropped.connect(lambda paths: self.import_files(paths, insert=False))
        layout.addWidget(self._media_list, 1)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(6)

        self._clear_unused_btn = QPushButton("🧹 Limpar não usados")
        self._clear_unused_btn.setToolTip(strings.EDIT_CLEAR_UNUSED_TIP)
        self._clear_unused_btn.clicked.connect(self._clear_unused_media)
        bottom_row.addWidget(self._clear_unused_btn)

        bottom_row.addStretch(1)

        self._insert = QPushButton(strings.EDIT_INSERT)
        self._insert.setToolTip(strings.EDIT_INSERT_TIP)
        self._insert.clicked.connect(self._insert_selected_media)
        self._insert.setEnabled(False)
        bottom_row.addWidget(self._insert)
        layout.addLayout(bottom_row)

        return box

    def _build_extras_box(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        box.setMinimumWidth(260)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title = QLabel(strings.EDIT_EXTRAS_TITLE)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        self._extras_tabs = QTabWidget()
        self._extras_tabs.addTab(self._build_text_tab(), strings.EDIT_TAB_TEXT)
        self._extras_tabs.addTab(self._build_filters_tab(), strings.EDIT_TAB_FILTERS)
        self._extras_tabs.addTab(self._build_transitions_tab(), strings.EDIT_TAB_TRANSITIONS)
        self._extras_tabs.setTabsClosable(False)
        self._properties_widget = _ClipPropertiesWidget()
        self._properties_widget.property_changed.connect(self._on_properties_changed)
        self._properties_widget.animation_scope_changed.connect(
            lambda enabled: setattr(self._preview, "_whole_animation", enabled))
        self._properties_widget.close_requested.connect(self._close_properties_tab)
        self._properties_widget.seek_requested.connect(self._seek_to)
        layout.addWidget(self._extras_tabs, 1)

        return box

    def _update_extras_tab_close_buttons(self) -> None:
        pass

    def _on_extras_tab_close_requested(self, index: int) -> None:
        if self._extras_tabs.widget(index) is self._properties_widget:
            self._extras_tabs.removeTab(index)

    def _close_properties_tab(self) -> None:
        idx = self._extras_tabs.indexOf(self._properties_widget)
        if idx >= 0:
            self._extras_tabs.removeTab(idx)

    def _build_text_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)

        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText(strings.EDIT_TEXT_PLACEHOLDER)
        self._text_input.setText("Título")
        self._text_input.textChanged.connect(lambda _: self._on_text_input_changed())
        layout.addWidget(self._text_input)

        self._font_selector = _FontSelectorWidget("Sans Serif")
        self._font_selector.font_changed.connect(lambda _: self._on_text_style_changed())
        layout.addWidget(self._font_selector)

        row_size = QHBoxLayout()
        row_size.setSpacing(6)
        lbl_size = QLabel("Tamanho:")
        row_size.addWidget(lbl_size)

        btn_dec = QPushButton("-")
        btn_dec.setProperty("role", "spin-tool")
        btn_dec.setFixedSize(30, 28)
        btn_dec.setToolTip("Diminuir tamanho da fonte (1 pt)")
        btn_dec.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 16px; color: #ffffff; background: #2a2a32; border: 1px solid #555; border-radius: 4px; padding: 0px; margin: 0px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; text-align: center; } "
            "QPushButton:hover { background: #383844; border-color: #777; color: #ffffff; } "
            "QPushButton:pressed { background: #0284c7; color: #ffffff; }"
        )
        btn_dec.clicked.connect(lambda: self._font_size_spin.setValue(max(8, self._font_size_spin.value() - 1)))
        row_size.addWidget(btn_dec)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 200)
        self._font_size_spin.setValue(48)
        self._font_size_spin.setSingleStep(1)
        self._font_size_spin.setSuffix(" pt")
        self._font_size_spin.setFixedHeight(28)
        self._font_size_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._font_size_spin.setStyleSheet(
            "QSpinBox { background: #1e1e26; border: 1px solid #444; border-radius: 4px; color: #ffffff; padding: 2px 8px; font-size: 13px; } "
            "QSpinBox:focus { border: 1px solid #0284c7; } "
            "QSpinBox::up-button, QSpinBox::down-button { width: 0px; height: 0px; border: none; }"
        )
        self._font_size_spin.valueChanged.connect(lambda _: self._on_text_style_changed())
        row_size.addWidget(self._font_size_spin, 1)

        btn_inc = QPushButton("+")
        btn_inc.setProperty("role", "spin-tool")
        btn_inc.setFixedSize(30, 28)
        btn_inc.setToolTip("Aumentar tamanho da fonte (1 pt)")
        btn_inc.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 16px; color: #ffffff; background: #2a2a32; border: 1px solid #555; border-radius: 4px; padding: 0px; margin: 0px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; text-align: center; } "
            "QPushButton:hover { background: #383844; border-color: #777; color: #ffffff; } "
            "QPushButton:pressed { background: #0284c7; color: #ffffff; }"
        )
        btn_inc.clicked.connect(lambda: self._font_size_spin.setValue(min(200, self._font_size_spin.value() + 1)))
        row_size.addWidget(btn_inc)
        layout.addLayout(row_size)

        size_presets = QHBoxLayout()
        size_presets.setSpacing(4)
        for sz in (18, 24, 36, 48, 64, 72):
            btn_sz = QPushButton(f"{sz}")
            btn_sz.setFixedHeight(24)
            btn_sz.setToolTip(f"Definir tamanho para {sz} pt")
            btn_sz.setStyleSheet(
                "QPushButton { font-size: 11px; font-weight: 500; color: #ddd; background: #2a2a32; border: 1px solid #444; border-radius: 3px; padding: 2px 4px; } "
                "QPushButton:hover { background: #383844; border-color: #666; color: #fff; } "
                "QPushButton:pressed { background: #0284c7; color: #fff; }"
            )
            btn_sz.clicked.connect(lambda _, s=sz: self._font_size_spin.setValue(s))
            size_presets.addWidget(btn_sz)
        layout.addLayout(size_presets)

        row_style = QHBoxLayout()
        row_style.setSpacing(4)
        self._bold_btn = QPushButton("B")
        self._bold_btn.setCheckable(True)
        b_font = self._bold_btn.font()
        b_font.setBold(True)
        self._bold_btn.setFont(b_font)
        self._bold_btn.setFixedWidth(36)
        self._bold_btn.toggled.connect(lambda _: self._on_text_style_changed())
        row_style.addWidget(self._bold_btn)

        self._italic_btn = QPushButton("I")
        self._italic_btn.setCheckable(True)
        i_font = self._italic_btn.font()
        i_font.setItalic(True)
        self._italic_btn.setFont(i_font)
        self._italic_btn.setFixedWidth(36)
        self._italic_btn.toggled.connect(lambda _: self._on_text_style_changed())
        row_style.addWidget(self._italic_btn)

        row_style.addStretch(1)
        self._text_color = "#ffffff"
        self._color_indicator = QPushButton()
        self._color_indicator.setFixedSize(28, 28)
        self._color_indicator.setStyleSheet(
            f"background: {self._text_color}; border: 1px solid #666; border-radius: 4px;"
        )
        self._color_indicator.setToolTip("Escolher cor personalizada")
        self._color_indicator.clicked.connect(self._choose_text_color)
        row_style.addWidget(self._color_indicator)
        layout.addLayout(row_style)

        # Paleta rápida
        pal_row = QHBoxLayout()
        pal_row.setSpacing(4)
        for c in ("#ffffff", "#ffeb3b", "#f44336", "#00e5ff", "#00e676", "#e040fb"):
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(f"background: {c}; border: 1px solid #444; border-radius: 3px;")
            btn.clicked.connect(lambda _, col=c: self._set_text_color(col))
            pal_row.addWidget(btn)
        pal_row.addStretch(1)
        layout.addLayout(pal_row)

        # Seção de Contorno
        layout.addSpacing(6)
        row_stroke = QHBoxLayout()
        row_stroke.setSpacing(6)

        self._stroke_checkbox = QCheckBox("Contorno:")
        self._stroke_checkbox.setToolTip("Ativar ou desativar contorno no texto")
        self._stroke_checkbox.toggled.connect(self._on_stroke_toggled)
        row_stroke.addWidget(self._stroke_checkbox)

        self._stroke_spin = QSpinBox()
        self._stroke_spin.setRange(1, 30)
        self._stroke_spin.setValue(3)
        self._stroke_spin.setSingleStep(1)
        self._stroke_spin.setSuffix(" px")
        self._stroke_spin.setFixedHeight(28)
        self._stroke_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._stroke_spin.setStyleSheet(
            "QSpinBox { background: #1e1e26; border: 1px solid #444; border-radius: 4px; color: #ffffff; padding: 2px 8px; font-size: 13px; } "
            "QSpinBox:focus { border: 1px solid #0284c7; } "
            "QSpinBox::up-button, QSpinBox::down-button { width: 0px; height: 0px; border: none; }"
        )
        self._stroke_spin.setToolTip("Grossura do contorno em pixels")
        self._stroke_spin.setEnabled(False)
        self._stroke_spin.valueChanged.connect(lambda _: self._on_text_style_changed())
        row_stroke.addWidget(self._stroke_spin, 1)

        self._stroke_color = "#000000"
        self._stroke_color_indicator = QPushButton()
        self._stroke_color_indicator.setFixedSize(28, 28)
        self._stroke_color_indicator.setStyleSheet(
            f"background: {self._stroke_color}; border: 1px solid #666; border-radius: 4px;"
        )
        self._stroke_color_indicator.setToolTip("Escolher cor do contorno")
        self._stroke_color_indicator.setEnabled(False)
        self._stroke_color_indicator.clicked.connect(self._choose_stroke_color)
        row_stroke.addWidget(self._stroke_color_indicator)
        layout.addLayout(row_stroke)

        stroke_pal_row = QHBoxLayout()
        stroke_pal_row.setSpacing(4)
        for c in ("#000000", "#ffffff", "#1e293b", "#e11d48", "#facc15", "#0284c7"):
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(f"background: {c}; border: 1px solid #444; border-radius: 3px;")
            btn.clicked.connect(lambda _, col=c: self._set_stroke_color(col))
            stroke_pal_row.addWidget(btn)
        stroke_pal_row.addStretch(1)
        layout.addLayout(stroke_pal_row)

        layout.addStretch(1)

        self._insert_text_btn = QPushButton(strings.EDIT_INSERT_TEXT)
        self._insert_text_btn.setProperty("role", "primary")
        self._insert_text_btn.clicked.connect(self._handle_insert_or_update_text)
        layout.addWidget(self._insert_text_btn)

        self._insert_new_text_btn = QPushButton(strings.EDIT_INSERT_NEW_TEXT)
        self._insert_new_text_btn.clicked.connect(self._insert_text_clip)
        self._insert_new_text_btn.setVisible(False)
        layout.addWidget(self._insert_new_text_btn)

        return tab

    def _choose_text_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._text_color), self, "Cor do Texto")
        if col.isValid():
            self._set_text_color(col.name())

    def _set_text_color(self, color_hex: str) -> None:
        self._text_color = color_hex
        self._color_indicator.setStyleSheet(
            f"background: {color_hex}; border: 1px solid #666; border-radius: 4px;"
        )
        self._on_text_style_changed()

    def _choose_stroke_color(self) -> None:
        col = QColorDialog.getColor(QColor(self._stroke_color), self, "Cor do Contorno")
        if col.isValid():
            self._set_stroke_color(col.name())

    def _set_stroke_color(self, color_hex: str) -> None:
        self._stroke_color = color_hex
        self._stroke_color_indicator.setStyleSheet(
            f"background: {color_hex}; border: 1px solid #666; border-radius: 4px;"
        )
        if not self._stroke_checkbox.isChecked():
            self._stroke_checkbox.setChecked(True)
        else:
            self._on_text_style_changed()

    def _on_stroke_toggled(self, checked: bool) -> None:
        self._stroke_spin.setEnabled(checked)
        self._stroke_color_indicator.setEnabled(checked)
        self._on_text_style_changed()

    def _build_filters_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Escolha um efeito visual:"))

        self._filter_specs = (
            ("pb", "🎬 " + strings.EDIT_FILTER_BW),
            ("sepia", "☕ " + strings.EDIT_FILTER_SEPIA),
            ("contraste", "⚡ " + strings.EDIT_FILTER_CONTRAST),
            ("vinheta", "🎯 " + strings.EDIT_FILTER_VIGNETTE),
            ("inverter", "🔄 " + strings.EDIT_FILTER_INVERT),
        )

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_buttons: list[QPushButton] = []
        for fid, flabel in self._filter_specs:
            btn = QPushButton(flabel)
            btn.setCheckable(True)
            btn.setChecked(fid == self._selected_filter_name)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px 10px; border-radius: 4px; border: 1px solid #444; background: #2a2a32; color: #fff; font-size: 12px; }"
                "QPushButton:hover { background: #353540; border-color: #666; }"
                "QPushButton:checked { background: #2a2a32; border: 2px solid #38bdf8; font-weight: bold; color: #ffffff; }"
                "QPushButton:checked:hover { background: #32323c; border: 2px solid #38bdf8; }"
            )
            self._filter_group.addButton(btn)
            btn.clicked.connect(lambda _, f=fid: self._select_filter(f))
            layout.addWidget(btn)
            self._filter_buttons.append(btn)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duração:"))
        self._filter_dur = QDoubleSpinBox()
        self._filter_dur.setRange(0.5, 3600.0)
        self._filter_dur.setValue(IMAGE_DURATION)
        self._filter_dur.setSingleStep(0.5)
        self._filter_dur.setSuffix(" s")
        self._filter_dur.valueChanged.connect(self._on_filter_dur_changed)
        dur_row.addWidget(self._filter_dur)
        layout.addLayout(dur_row)

        layout.addStretch(1)

        self._apply_filter_btn = QPushButton(strings.EDIT_APPLY_FILTER)
        self._apply_filter_btn.setProperty("role", "primary")
        self._apply_filter_btn.clicked.connect(self._handle_apply_or_update_filter)
        layout.addWidget(self._apply_filter_btn)

        self._insert_new_filter_btn = QPushButton(strings.EDIT_INSERT_NEW_FILTER)
        self._insert_new_filter_btn.clicked.connect(lambda: self._insert_filter_clip(self._selected_filter_name))
        self._insert_new_filter_btn.setVisible(False)
        layout.addWidget(self._insert_new_filter_btn)

        return tab

    def _select_filter(self, filter_name: str) -> None:
        self._selected_filter_name = filter_name
        for i, (fid, _) in enumerate(self._filter_specs):
            if i < len(self._filter_buttons):
                self._filter_buttons[i].setChecked(fid == filter_name)
        clip = self._timeline.selected_clip
        if not self._syncing and clip is not None and clip.overlay_type == "filter":
            self._remember()
            self._apply(self._project.with_updated_clip(clip.clip_id, filter_name=filter_name))

    def _on_filter_dur_changed(self, dur: float) -> None:
        clip = self._timeline.selected_clip
        if not self._syncing and clip is not None and clip.overlay_type == "filter":
            self._remember()
            self._apply(self._project.with_updated_clip(clip.clip_id, duration=dur))

    def _handle_apply_or_update_filter(self) -> None:
        clip = self._timeline.selected_clip
        if clip is not None and clip.overlay_type == "filter":
            self._remember()
            self._apply(
                self._project.with_updated_clip(
                    clip.clip_id,
                    filter_name=self._selected_filter_name,
                    duration=self._filter_dur.value(),
                )
            )
        else:
            self._insert_filter_clip(self._selected_filter_name)

    def _on_text_input_changed(self) -> None:
        clip = self._timeline.selected_clip
        if self._syncing or clip is None or clip.overlay_type != "text":
            return
        new_text = self._text_input.text()
        if clip.text_content == new_text:
            return
        if self._typing_session != clip.clip_id:
            self._end_edit_groups()
            self._session.begin_edit()
            self._typing_session = clip.clip_id
        self._apply(self._project.with_updated_clip(clip.clip_id, text_content=new_text))
        self._typing_timer.start()

    def _on_text_style_changed(self) -> None:
        clip = self._timeline.selected_clip
        if self._syncing or clip is None or clip.overlay_type != "text":
            return
        family = self._font_selector.current_family()
        size = self._font_size_spin.value()
        bold = self._bold_btn.isChecked()
        italic = self._italic_btn.isChecked()
        color = self._text_color
        stroke_color = self._stroke_color
        stroke_width = self._stroke_spin.value() if self._stroke_checkbox.isChecked() else 0
        self._remember()
        self._apply(
            self._project.with_updated_clip(
                clip.clip_id,
                font_family=family,
                font_size=size,
                font_bold=bold,
                font_italic=italic,
                text_color=color,
                stroke_color=stroke_color,
                stroke_width=stroke_width,
            )
        )

    def _handle_insert_or_update_text(self) -> None:
        clip = self._timeline.selected_clip
        if clip is not None and clip.overlay_type == "text":
            self._update_selected_text_clip()
        else:
            self._insert_text_clip()

    def _update_selected_text_clip(self) -> None:
        clip = self._timeline.selected_clip
        if clip is None or clip.overlay_type != "text":
            return
        text = self._text_input.text().strip() or "Texto"
        family = self._font_selector.current_family()
        size = self._font_size_spin.value()
        bold = self._bold_btn.isChecked()
        italic = self._italic_btn.isChecked()
        color = self._text_color
        stroke_color = self._stroke_color
        stroke_width = self._stroke_spin.value() if self._stroke_checkbox.isChecked() else 0
        self._remember()
        self._apply(
            self._project.with_updated_clip(
                clip.clip_id,
                text_content=text,
                font_family=family,
                font_size=size,
                font_bold=bold,
                font_italic=italic,
                text_color=color,
                stroke_color=stroke_color,
                stroke_width=stroke_width,
            )
        )

    def _insert_text_clip(self) -> None:
        text = self._text_input.text().strip() or "Texto"
        font_family = self._font_selector.current_family()
        font_size = self._font_size_spin.value()
        bold = self._bold_btn.isChecked()
        italic = self._italic_btn.isChecked()
        color = self._text_color
        stroke_color = self._stroke_color
        stroke_width = self._stroke_spin.value() if self._stroke_checkbox.isChecked() else 0

        ref = MediaRef(
            path=Path(f"Texto_{text[:15]}"),
            kind=MediaKind.IMAGE,
            duration=IMAGE_DURATION,
        )
        clip = Clip(
            media=ref,
            start=max(0.0, self._position),
            duration=IMAGE_DURATION,
            overlay_type="text",
            text_content=text,
            font_family=font_family,
            font_size=font_size,
            font_bold=bold,
            font_italic=italic,
            text_color=color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            x=0.5,
            y=0.5,
            scale=1.0,
            rotation=0.0,
        )
        self._place_clip(clip)

    def _insert_filter_clip(self, filter_name: str | None = None) -> None:
        fname = filter_name or self._selected_filter_name
        label = next((lbl for fid, lbl in self._filter_specs if fid == fname), fname)
        duration = self._filter_dur.value()

        ref = MediaRef(
            path=Path(f"Filtro_{label}"),
            kind=MediaKind.IMAGE,
            duration=duration,
        )
        clip = Clip(
            media=ref,
            start=max(0.0, self._position),
            duration=duration,
            overlay_type="filter",
            filter_name=fname,
        )
        self._place_clip(clip)

    def _build_transitions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Escolha uma transição de vídeo:"))

        self._trans_specs = (
            ("fade", "🌑 Fade"),
            ("fadeblack", "⬛ Fade para Preto"),
            ("fadewhite", "⬜ Fade para Branco"),
            ("dissolve", "🎬 Dissolve"),
            ("wipeleft", "◀ Wipe para Esquerda"),
            ("wiperight", "▶ Wipe para Direita"),
            ("slideleft", "◀ Slide para Esquerda"),
            ("slideright", "▶ Slide para Direita"),
        )
        self._selected_trans_name = "fade"

        self._trans_group = QButtonGroup(self)
        self._trans_group.setExclusive(True)
        self._trans_buttons: list[QPushButton] = []
        for tid, tlabel in self._trans_specs:
            btn = QPushButton(tlabel)
            btn.setCheckable(True)
            btn.setChecked(tid == self._selected_trans_name)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px 10px; border-radius: 4px; border: 1px solid #444; background: #2a2a32; color: #fff; font-size: 12px; }"
                "QPushButton:hover { background: #353540; border-color: #666; }"
                "QPushButton:checked { background: #2a2a32; border: 2px solid #fbbf24; font-weight: bold; color: #ffffff; }"
                "QPushButton:checked:hover { background: #32323c; border: 2px solid #fbbf24; }"
            )
            self._trans_group.addButton(btn)
            btn.clicked.connect(lambda _, t=tid: self._select_transition(t))
            layout.addWidget(btn)
            self._trans_buttons.append(btn)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duração:"))
        self._trans_dur = QDoubleSpinBox()
        self._trans_dur.setRange(MIN_TRANSITION_DURATION, 5.0)
        self._trans_dur.setValue(1.0)
        self._trans_dur.setSingleStep(0.1)
        self._trans_dur.setSuffix(" s")
        self._trans_dur.valueChanged.connect(self._on_transition_dur_changed)
        dur_row.addWidget(self._trans_dur)
        layout.addLayout(dur_row)

        self._trans_affect_additionals = QCheckBox(
            strings.EDIT_TRANSITION_AFFECT_ADDITIONALS
        )
        self._trans_affect_additionals.setToolTip(
            strings.EDIT_TRANSITION_AFFECT_ADDITIONALS_TIP
        )
        self._trans_affect_additionals.toggled.connect(
            self._on_transition_affect_additionals_changed
        )
        layout.addWidget(self._trans_affect_additionals)

        hint = QLabel(strings.EDIT_TRANSITION_TRACK_HINT)
        hint.setWordWrap(True)
        hint.setProperty("role", "dim")
        hint.setStyleSheet("font-size: 11px; color: #94a3b8;")
        layout.addWidget(hint)

        layout.addStretch(1)

        self._apply_trans_btn = QPushButton("+ Inserir Transição")
        self._apply_trans_btn.setProperty("role", "primary")
        self._apply_trans_btn.clicked.connect(self._handle_apply_or_update_transition)
        layout.addWidget(self._apply_trans_btn)

        self._insert_new_trans_btn = QPushButton("+ Inserir como Nova Transição")
        self._insert_new_trans_btn.clicked.connect(lambda: self._insert_transition_clip(self._selected_trans_name))
        self._insert_new_trans_btn.setVisible(False)
        layout.addWidget(self._insert_new_trans_btn)

        return tab

    def _select_transition(self, trans_name: str) -> None:
        self._selected_trans_name = trans_name
        for i, (tid, _) in enumerate(self._trans_specs):
            if i < len(self._trans_buttons):
                self._trans_buttons[i].setChecked(tid == trans_name)
        clip = self._timeline.selected_clip
        if not self._syncing and clip is not None and clip.overlay_type == "transition":
            self._remember()
            self._apply(self._project.with_updated_clip(clip.clip_id, transition_name=trans_name))

    def _on_transition_dur_changed(self, dur: float) -> None:
        clip = self._timeline.selected_clip
        if not self._syncing and clip is not None and clip.overlay_type == "transition":
            dur = min(dur, self._transition_max_duration(clip))
            if abs(self._trans_dur.value() - dur) > 1e-6:
                self._trans_dur.blockSignals(True)
                self._trans_dur.setValue(dur)
                self._trans_dur.blockSignals(False)
            self._remember()
            self._apply(self._project.with_updated_clip(clip.clip_id, duration=dur))

    def _on_transition_affect_additionals_changed(self, checked: bool) -> None:
        clip = self._timeline.selected_clip
        if not self._syncing and clip is not None and clip.is_transition:
            self._remember()
            self._apply(
                self._project.with_updated_clip(
                    clip.clip_id,
                    transition_affects_additionals=checked,
                )
            )

    def _transition_max_duration(self, marker: Clip) -> float:
        """Maior duração que permanece contida nos dois lados do corte."""
        context = self._project.transition_context(marker)
        if context is None:
            return marker.duration
        return max(
            MIN_TRANSITION_DURATION,
            min(5.0, context.left.duration, context.right.duration),
        )

    def _handle_apply_or_update_transition(self) -> None:
        clip = self._timeline.selected_clip
        if clip is not None and clip.overlay_type == "transition":
            self._remember()
            duration = min(self._trans_dur.value(), self._transition_max_duration(clip))
            self._apply(
                self._project.with_updated_clip(
                    clip.clip_id,
                    transition_name=self._selected_trans_name,
                    duration=duration,
                    transition_affects_additionals=(
                        self._trans_affect_additionals.isChecked()
                    ),
                )
            )
        else:
            self._insert_transition_clip(self._selected_trans_name)

    def _find_nearest_video_cut(
        self, current_pos: float
    ) -> tuple[int, Clip, Clip, float] | None:
        """Corte do clipe selecionado ou, sem seleção aplicável, o mais próximo.

        A identidade do clipe é o escopo, não o instante. Assim, duas trilhas
        com cortes perfeitamente alinhados continuam selecionáveis sem depender
        da ordem interna em que aparecem no projeto.
        """
        cuts: list[tuple[int, Clip, Clip, float]] = []
        for index, track in enumerate(self._project.tracks):
            if track.kind != TrackKind.VIDEO:
                continue
            ordered = sorted(
                (clip for clip in track.clips if not clip.is_transition),
                key=lambda clip: clip.start,
            )
            for left, right in zip(ordered, ordered[1:]):
                if abs(left.end - right.start) <= 1e-4:
                    cuts.append((index, left, right, left.end))

        if not cuts:
            return None

        selected = self._timeline.selected_clip
        if selected is not None and not selected.is_transition:
            found = self._project.find(selected.clip_id)
            if found is not None and self._project.tracks[found[0]].kind is TrackKind.VIDEO:
                selected_cuts = [
                    cut
                    for cut in cuts
                    if selected.clip_id in (cut[1].clip_id, cut[2].clip_id)
                ]
                # Uma seleção explícita nunca cai silenciosamente em outra
                # trilha. Se o clipe não toca um corte, a UI mostra o aviso de
                # que são necessários dois blocos encostados.
                if not selected_cuts:
                    return None
                cuts = selected_cuts
        return min(cuts, key=lambda item: abs(item[3] - current_pos))

    def _insert_transition_clip(self, trans_name: str | None = None) -> None:
        tname = trans_name or getattr(self, "_selected_trans_name", "fade")
        label = next((lbl for tid, lbl in getattr(self, "_trans_specs", ()) if tid == tname), tname)
        duration = self._trans_dur.value() if hasattr(self, "_trans_dur") else 1.0

        edit = self._find_nearest_video_cut(self._position)
        if edit is None:
            QMessageBox.information(
                self,
                strings.DIALOG_WARNING_TITLE,
                strings.EDIT_TRANSITION_NEEDS_CUT,
            )
            return
        video_index, left, right, cut = edit
        duration = min(duration, left.duration, right.duration)
        start = max(0.0, cut - duration / 2.0)

        ref = MediaRef(
            path=Path(f"Transição_{label}"),
            kind=MediaKind.IMAGE,
            duration=duration,
        )
        # Como nos editores profissionais, um ponto de edição tem no máximo
        # uma transição. Inserir outra naquele corte substitui seus ajustes.
        existing = next(
            (
                marker
                for marker in self._project.clips
                if marker.is_transition
                and marker.transition_left_id == left.clip_id
                and marker.transition_right_id == right.clip_id
            ),
            None,
        )
        if existing is not None:
            self._remember()
            self._project = self._project.with_updated_clip(
                existing.clip_id,
                transition_name=tname,
                duration=duration,
                transition_affects_additionals=(
                    self._trans_affect_additionals.isChecked()
                ),
            )
            self._timeline.select(existing.clip_id)
            self._after_edit()
            return
        clip = Clip(
            media=ref,
            start=start,
            duration=duration,
            overlay_type="transition",
            transition_name=tname,
            transition_left_id=left.clip_id,
            transition_right_id=right.clip_id,
            transition_affects_additionals=(
                self._trans_affect_additionals.isChecked()
            ),
        )
        # Transições pertencem à sequência de vídeo, no próprio corte. Elas
        # não são overlays de Adicionais: podem ocupar o mesmo intervalo dos
        # dois clipes que conectam.
        self._remember()
        self._project = self._project.with_clip(video_index, clip)
        self._timeline.select(clip.clip_id)
        self._after_edit()

    def _sync_extras_controls(self, clip: Clip | None) -> None:
        if hasattr(self, "_properties_widget") and self._extras_tabs.indexOf(self._properties_widget) >= 0:
            if clip is not None:
                self._properties_widget.set_playhead_position(self._position)
                self._properties_widget.load_clip(clip, self._project.width, self._project.height, fps=self._project.fps, text_ratio=self._project.text_ratio)
            elif (
                self._properties_widget._clip_id >= 0
                and self._project.find(self._properties_widget._clip_id) is None
            ):
                self._properties_widget.clear()
            if self._extras_tabs.currentWidget() is self._properties_widget:
                return

        if clip is not None and clip.overlay_type == "text":
            self._extras_tabs.setCurrentIndex(0)
            if self._text_input.text() != clip.text_content:
                self._text_input.setText(clip.text_content)
            self._font_selector.set_family(clip.font_family or "Sans Serif")
            self._font_size_spin.setValue(clip.font_size or 48)
            self._bold_btn.setChecked(bool(clip.font_bold))
            self._italic_btn.setChecked(bool(clip.font_italic))
            self._text_color = clip.text_color or "#ffffff"
            self._color_indicator.setStyleSheet(
                f"background: {self._text_color}; border: 1px solid #666; border-radius: 4px;"
            )
            has_stroke = (clip.stroke_width or 0) > 0
            self._stroke_checkbox.setChecked(has_stroke)
            self._stroke_spin.setValue(clip.stroke_width if has_stroke else 3)
            self._stroke_spin.setEnabled(has_stroke)
            self._stroke_color = clip.stroke_color or "#000000"
            self._stroke_color_indicator.setStyleSheet(
                f"background: {self._stroke_color}; border: 1px solid #666; border-radius: 4px;"
            )
            self._stroke_color_indicator.setEnabled(has_stroke)
            self._insert_text_btn.setText(strings.EDIT_UPDATE_TEXT)
            self._insert_new_text_btn.setVisible(True)
            self._apply_filter_btn.setText(strings.EDIT_APPLY_FILTER)
            self._insert_new_filter_btn.setVisible(False)
            if hasattr(self, "_apply_trans_btn"):
                self._apply_trans_btn.setText("+ Inserir Transição")
                self._insert_new_trans_btn.setVisible(False)
        elif clip is not None and clip.overlay_type == "filter":
            self._extras_tabs.setCurrentIndex(1)
            fname = clip.filter_name or "pb"
            self._selected_filter_name = fname
            for i, (fid, _) in enumerate(self._filter_specs):
                if i < len(self._filter_buttons):
                    self._filter_buttons[i].setChecked(fid == fname)
            self._filter_dur.setValue(clip.duration)
            self._apply_filter_btn.setText(strings.EDIT_UPDATE_FILTER)
            self._insert_new_filter_btn.setVisible(True)
            self._insert_text_btn.setText(strings.EDIT_INSERT_TEXT)
            self._insert_new_text_btn.setVisible(False)
            if hasattr(self, "_apply_trans_btn"):
                self._apply_trans_btn.setText("+ Inserir Transição")
                self._insert_new_trans_btn.setVisible(False)
        elif clip is not None and clip.overlay_type == "transition":
            self._extras_tabs.setCurrentIndex(2)
            tname = clip.transition_name or "fade"
            self._selected_trans_name = tname
            for i, (tid, _) in enumerate(getattr(self, "_trans_specs", ())):
                if i < len(self._trans_buttons):
                    self._trans_buttons[i].setChecked(tid == tname)
            self._trans_dur.setValue(clip.duration)
            self._trans_affect_additionals.setChecked(
                clip.transition_affects_additionals
            )
            if hasattr(self, "_apply_trans_btn"):
                self._apply_trans_btn.setText("✓ Atualizar Transição Selecionada")
                self._insert_new_trans_btn.setVisible(True)
            self._insert_text_btn.setText(strings.EDIT_INSERT_TEXT)
            self._insert_new_text_btn.setVisible(False)
            self._apply_filter_btn.setText(strings.EDIT_APPLY_FILTER)
            self._insert_new_filter_btn.setVisible(False)
        else:
            self._insert_text_btn.setText(strings.EDIT_INSERT_TEXT)
            self._insert_new_text_btn.setVisible(False)
            self._apply_filter_btn.setText(strings.EDIT_APPLY_FILTER)
            self._insert_new_filter_btn.setVisible(False)
            if hasattr(self, "_apply_trans_btn"):
                self._apply_trans_btn.setText("+ Inserir Transição")
                self._insert_new_trans_btn.setVisible(False)

    def _build_player(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        box.setMinimumWidth(1040)
        column = QVBoxLayout(box)
        column.setContentsMargins(4, 0, 0, 0)
        column.setSpacing(6)

        # Moldura com respiro para comportar vídeos com proporções diferentes
        self._preview_frame = QWidget()
        self._preview_frame.setProperty("role", "plain")
        frame_layout = QVBoxLayout(self._preview_frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)

        self._preview = _Preview(rasterizer=self.editor.rasterizer)
        self._preview.set_snap_enabled(self._settings.preview_snap)
        self._preview.double_clicked.connect(self._toggle_fullscreen)
        self._preview.play_toggle_requested.connect(self._toggle_play)
        self._preview.overlay_transformed.connect(self._on_overlay_transformed)
        self._preview.overlay_transform_finished.connect(self._on_overlay_transform_finished)
        self._preview.overlay_transform_cancelled.connect(self._on_overlay_transform_cancelled)
        self._preview.clicked_outside.connect(lambda: self._timeline.select(-1))
        self._preview.clip_selected.connect(lambda cid: self._timeline.select(cid))
        frame_layout.addWidget(self._preview)

        column.addWidget(self._preview_frame, 1)
        column.addWidget(self._build_transport())
        column.addWidget(self._loading_label)
        return box

    def _build_transport(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        box.setMinimumWidth(1040)
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 4, 4, 0)
        row.setSpacing(6)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._time_label = QLabel(
            strings.EDIT_POSITION.format(
                current=format_timecode(0, milliseconds=False),
                total=format_timecode(0, milliseconds=False),
            )
        )
        self._time_label.setFont(mono)
        self._frame_label = QLabel("")
        self._frame_label.setFont(mono)
        self._frame_label.setProperty("role", "dim")
        self._loading_label = QLabel("")
        self._loading_label.setProperty("role", "dim")
        self._loading_label.setWordWrap(True)
        # Reservar espaço evita redimensionar a prévia a cada resultado do worker.
        self._loading_label.setFixedHeight(self._loading_label.fontMetrics().lineSpacing() * 2)

        readouts = QWidget()
        readouts.setProperty("role", "plain")
        readouts_layout = QHBoxLayout(readouts)
        readouts_layout.setContentsMargins(0, 0, 0, 0)
        readouts_layout.setSpacing(12)
        readouts_layout.addWidget(self._time_label)
        readouts_layout.addWidget(self._frame_label)
        row.addWidget(readouts)

        row.addStretch(1)

        self._buttons: list[QPushButton] = []
        specs = (
            ("|◀◀", strings.EDIT_TO_START, lambda: self._seek_to(0.0)),
            ("◀◀", strings.EDIT_BACK, lambda: self._nudge(-1.0)),
            ("◀|", f"{strings.EDIT_PREV_FRAME}  (,)", lambda: self._step_frame(-1)),
            ("▶", f"{strings.EDIT_PLAY}  (Espaço)", self._toggle_play),
            ("|▶", f"{strings.EDIT_NEXT_FRAME}  (.)", lambda: self._step_frame(+1)),
            ("▶▶", strings.EDIT_FORWARD, lambda: self._nudge(+1.0)),
            ("▶▶|", strings.EDIT_TO_END, lambda: self._seek_to(self._duration)),
        )
        for text, tip, slot in specs:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setProperty("role", "transport")
            button.setFixedWidth(38)
            button.setFixedHeight(32)
            button.clicked.connect(slot)
            row.addWidget(button)
            self._buttons.append(button)
        self._play_button = self._buttons[3]
        self._play_button.setFixedWidth(48)
        self._play_button.setFixedHeight(32)
        self._play_button.setProperty("role", "primary")

        row.addStretch(1)

        self._prev_key = QPushButton(strings.EDIT_PREV_KEY_SHORT)
        self._prev_key.setToolTip(strings.EDIT_PREV_KEY)
        self._prev_key.setProperty("role", "transport")
        self._prev_key.setFixedHeight(32)
        self._prev_key.clicked.connect(lambda: self._jump_keyframe(-1))

        self._next_key = QPushButton(strings.EDIT_NEXT_KEY_SHORT)
        self._next_key.setToolTip(strings.EDIT_NEXT_KEY)
        self._next_key.setProperty("role", "transport")
        self._next_key.setFixedHeight(32)
        self._next_key.clicked.connect(lambda: self._jump_keyframe(+1))

        row.addWidget(self._prev_key)
        row.addWidget(self._next_key)
        self._buttons += [self._prev_key, self._next_key]

        row.addSpacing(6)
        self._loop = QCheckBox(strings.EDIT_LOOP)
        self._loop.setToolTip(strings.EDIT_LOOP_TIP)
        self._loop.setChecked(False)
        row.addWidget(self._loop)

        row.addSpacing(6)
        self._snap_btn = QPushButton(strings.EDIT_SNAP)
        self._snap_btn.setToolTip(strings.EDIT_SNAP_TIP)
        self._snap_btn.setCheckable(True)
        self._snap_btn.setChecked(self._settings.preview_snap)
        self._snap_btn.setProperty("role", "transport")
        self._snap_btn.setFixedWidth(38)
        self._snap_btn.setFixedHeight(32)
        self._snap_btn.toggled.connect(self._on_snap_toggled)
        row.addWidget(self._snap_btn)
        self._buttons.append(self._snap_btn)

        row.addSpacing(6)
        row.addWidget(self._build_volume())
        return box

    def _on_snap_toggled(self, checked: bool) -> None:
        self._preview.set_snap_enabled(checked)
        self._settings.preview_snap = checked
        self._runtime.save_settings(self._settings)

    def _build_volume(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._mute = QPushButton()
        self._mute.setCheckable(True)
        self._mute.setChecked(self._settings.preview_muted)
        self._mute.setProperty("role", "transport")
        self._mute.setFixedWidth(36)
        self._mute.setFixedHeight(32)
        self._mute.toggled.connect(self._on_mute)
        row.addWidget(self._mute)

        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(self._settings.preview_volume)
        self._volume.setMinimumWidth(60)
        self._volume.setMaximumWidth(90)
        self._volume.setFixedHeight(32)
        self._volume.setToolTip(strings.EDIT_VOLUME)
        self._volume.valueChanged.connect(self._on_volume)
        row.addWidget(self._volume)
        self._refresh_volume_label()
        return box

    def _build_timeline_area(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        column.addLayout(self._build_toolbar())

        # A linha do tempo cresce com o número de trilhas, e a partir de certo
        # ponto ela empurraria a exportação para fora da vista. Numa área de
        # rolagem, ela para de crescer e passa a rolar — como em qualquer editor
        # com mais trilhas do que tela.
        self._timeline_area = QScrollArea()
        self._timeline_area.setWidgetResizable(True)
        self._timeline_area.setFrameShape(QScrollArea.Shape.NoFrame)
        # Sem teto: quem decide quanto das trilhas fica à vista é o divisor. O
        # piso garante uma trilha de cada espécie inteira.
        self._timeline_area.setMinimumHeight(_TIMELINE_MIN_HEIGHT)
        self._timeline_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._timeline = Timeline(self._colors)
        self._timeline.setToolTip(strings.EDIT_TIMELINE_HINT)
        self._timeline.scrubbed.connect(self._on_scrub)
        self._timeline.edit_started.connect(self._begin_timeline_edit)
        self._timeline.edit_finished.connect(self._on_edit_finished)
        self._timeline.edit_cancelled.connect(self._on_edit_cancelled)
        self._timeline.clip_moved.connect(self._on_clip_moved)
        self._timeline.clip_resized.connect(self._on_clip_resized)
        self._timeline.clip_selected.connect(self._on_clip_selected)
        self._timeline.track_mute_clicked.connect(self._toggle_track_mute)
        self._timeline.track_visibility_clicked.connect(self._toggle_track_visibility)
        self._timeline.track_reordered.connect(self._on_track_reordered)
        self._timeline.menu_requested.connect(self._show_menu)
        self._timeline.view_changed.connect(self._on_view_changed)
        self._timeline_area.setWidget(self._timeline)
        bar = self._timeline_area.verticalScrollBar()
        self._timeline.vertical_scroll_requested.connect(lambda delta: bar.setValue(round(bar.value() + delta)))
        column.addWidget(self._timeline_area)

        self._scroll = QScrollBar(Qt.Orientation.Horizontal)
        self._scroll.valueChanged.connect(self._on_scrollbar)
        column.addWidget(self._scroll)

        return box

    def _build_toolbar(self) -> QHBoxLayout:
        """Barra curta de propósito.

        Copiar, colar, separar áudio e criar trilha moram no **botão direito**
        sobre o que elas afetam — é onde se procura por elas depois de já ter o
        bloco na mão, e cada uma que sai daqui é uma coisa a menos entre a
        imagem e a linha do tempo.

        As quatro que ficam aqui são a exceção, e por frequência: dividir,
        apagar à esquerda, apagar à direita e excluir se repetem dezenas de vezes
        ao montar uma sequência, e abrir um menu para cada uma custa mais que o
        espaço de quatro botões. Continuam no menu também — o atalho não
        substitui o lugar onde elas se procuram.

        Elas ficam **afastadas** de desfazer e refazer porque não são a mesma
        coisa: desfazer age sobre a edição inteira e está sempre disponível;
        estas agem sobre o bloco selecionado e se desligam sem ele. Coladas,
        pareceriam seis botões do mesmo grupo.

        A ordem é a do corte: a tesoura divide, as duas do meio apagam um lado,
        a lixeira apaga tudo — da menor consequência para a maior.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._undo = self._tool(row, "↶", "Ctrl+Z", self._undo_edit, strings.EDIT_UNDO, 40)
        self._redo = self._tool(
            row, "↷", "Ctrl+Shift+Z", self._redo_edit, strings.EDIT_REDO, 40
        )

        row.addSpacing(_TOOL_GROUP_GAP)
        # Ícone e não texto: a barra inteira é de símbolos (↶ ↷ − +), e "Excluir
        # bloco" por extenso ao lado deles teria o dobro da largura de tudo que
        # está ali. O que diz o nome é a dica, como nos outros.
        self._split_button = self._tool(
            row, "", "S", self._split_here, strings.EDIT_SPLIT, 40
        )
        self._split_button.setIcon(icons.scissors(self._colors["text"]))
        self._trim_left_button = self._tool(
            row, "", "Q", lambda: self._trim_to_cursor("inicio"),
            strings.EDIT_TRIM_LEFT, 40,
        )
        self._trim_left_button.setIcon(icons.trim_left(self._colors["text"]))
        # Dica maior que a dos outros três: tesoura e lixeira se explicam
        # sozinhas, "apagar à esquerda" não diz de onde nem até onde.
        self._trim_left_button.setToolTip(
            f"{strings.EDIT_TRIM_LEFT}  (Q)\n{strings.EDIT_TRIM_LEFT_TIP}"
        )
        self._trim_right_button = self._tool(
            row, "", "W", lambda: self._trim_to_cursor("fim"),
            strings.EDIT_TRIM_RIGHT, 40,
        )
        self._trim_right_button.setIcon(icons.trim_right(self._colors["text"]))
        self._trim_right_button.setToolTip(
            f"{strings.EDIT_TRIM_RIGHT}  (W)\n{strings.EDIT_TRIM_RIGHT_TIP}"
        )
        self._delete_button = self._tool(
            row, "", "Del", self._delete_selected, strings.EDIT_DELETE, 40
        )
        self._delete_button.setIcon(icons.trash(self._colors["text"]))

        row.addSpacing(_TOOL_GROUP_GAP)
        self._add_video_button = QPushButton(strings.EDIT_ADD_VIDEO_TRACK)
        self._add_video_button.setToolTip(strings.EDIT_ADD_VIDEO_TRACK_FULL)
        self._add_video_button.clicked.connect(lambda: self._add_track(TrackKind.VIDEO))
        row.addWidget(self._add_video_button)

        self._add_audio_button = QPushButton(strings.EDIT_ADD_AUDIO_TRACK)
        self._add_audio_button.setToolTip(strings.EDIT_ADD_AUDIO_TRACK_FULL)
        self._add_audio_button.clicked.connect(lambda: self._add_track(TrackKind.AUDIO))
        row.addWidget(self._add_audio_button)

        self._add_additional_button = QPushButton(strings.EDIT_ADD_ADDITIONAL_TRACK)
        self._add_additional_button.setToolTip(strings.EDIT_ADD_ADDITIONAL_TRACK_FULL)
        self._add_additional_button.clicked.connect(lambda: self._add_track(TrackKind.ADDITIONAL))
        row.addWidget(self._add_additional_button)

        row.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setProperty("role", "dim")
        row.addWidget(self._count_label)
        # O bloco escolhido tinha uma faixa só para ele, com dois campos de
        # timecode e o nome do arquivo. Os campos saíram — as pontas se
        # ajustam pelas alças, pelos botões de apagar e pela tesoura, todos
        # no cursor — e o nome fica aqui, sem custar altura nenhuma.
        row.addSpacing(10)
        self._clip_label = QLabel(strings.EDIT_CLIP_NONE)
        self._clip_label.setProperty("role", "dim")
        row.addWidget(self._clip_label)
        row.addStretch(1)

        # Ajustes do bloco: botões suspensos compactos para volume e velocidade
        self._volume_btn = QPushButton("🔊 0,0 dB")
        self._volume_btn.setToolTip(strings.EDIT_GAIN_TIP)
        self._volume_btn.clicked.connect(self._show_volume_popup)
        row.addWidget(self._volume_btn)

        row.addSpacing(4)
        self._speed_btn = QPushButton("⚡ 1,0x")
        self._speed_btn.setToolTip(strings.EDIT_SPEED_TIP)
        self._speed_btn.clicked.connect(self._show_speed_popup)
        row.addWidget(self._speed_btn)
        # Folga larga: o volume é do bloco escolhido, o zoom é da vista. Encostar
        # um no outro faria a barra terminar num amontoado de coisas sem relação.
        row.addSpacing(_VOLUME_ZOOM_GAP)

        for text, tip, slot in (
            ("−", strings.EDIT_ZOOM_OUT, lambda: self._zoom(1 / _ZOOM_FACTOR)),
            ("+", strings.EDIT_ZOOM_IN, lambda: self._zoom(_ZOOM_FACTOR)),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setFixedWidth(40)
            button.clicked.connect(slot)
            row.addWidget(button)
        fit = QPushButton(strings.EDIT_ZOOM_FIT)
        fit.setToolTip(strings.EDIT_ZOOM_FIT_TIP)
        # Por lambda: a barra é montada antes da linha do tempo existir.
        fit.clicked.connect(lambda: self._timeline.fit())
        row.addWidget(fit)
        return row

    @staticmethod
    def _tool(
        row: QHBoxLayout,
        text: str,
        shortcut: str,
        slot: Callable[[], None],
        tip: str = "",
        width: int = 0,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(f"{tip or text}  ({shortcut})" if shortcut else (tip or text))
        if width:
            button.setFixedWidth(width)
        button.clicked.connect(slot)
        row.addWidget(button)
        return button

    def _open_export_dialog(self) -> None:
        if self._project.is_empty:
            QMessageBox.information(
                self, strings.DIALOG_WARNING_TITLE, strings.EDIT_NO_CLIPS
            )
            return

        dialog = ExportDialog(
            processing=self._processing,
            project=self._project,
            settings=self._settings,
            pool=self._pool,
            probed=self._probed,
            keyframes=self._keyframes_for(self._main_clip()),
            ensure_tools=self._ensure_tools,
            initial_canvas=self._canvas_choice,
            initial_rate=self._rate_choice,
            project_path=self._project_path,
            parent=self,
         runtime=self._runtime)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_job:
            if (
                dialog.chosen_canvas != self._canvas_choice
                or dialog.chosen_rate != self._rate_choice
            ):
                self._canvas_choice = dialog.chosen_canvas
                self._rate_choice = dialog.chosen_rate
                self._sync_canvas()
                self._after_edit()
            self.jobs_ready.emit([dialog.created_job])

    def _enqueue(self) -> None:
        self._open_export_dialog()

    def _install_shortcuts(self) -> None:
        """Atalhos do editor, com o alcance do painel.

        As setas ficam de fora: elas pertencem à linha do tempo, que só as
        recebe quando tem o foco. Um atalho de janela para elas roubaria as
        setas de todo campo de texto da aba.
        """
        for keys, slot in (
            ("Space", self._toggle_play),
            ("S", self._split_here),
            ("Ctrl+B", self._split_here),
            # Q e W são as teclas de aparar até o cursor nos editores que quem
            # usa isto já conhece.
            ("Q", lambda: self._trim_to_cursor("inicio")),
            ("W", lambda: self._trim_to_cursor("fim")),
            ("Del", self._delete_selected),
            ("Backspace", self._delete_selected),
            ("Ctrl+C", self._copy_clip),
            ("Ctrl+V", self._paste_clip),
            (",", lambda: self._step_frame(-1)),
            (".", lambda: self._step_frame(+1)),
            ("Ctrl+Z", self._undo_edit),
            ("Ctrl+Shift+Z", self._redo_edit),
            ("Ctrl+Y", self._redo_edit),
            ("Ctrl+S", lambda: self.save_project()),
            ("Ctrl+Shift+S", lambda: self.save_project_as()),
            ("Ctrl+O", lambda: self.open_project()),
            ("Ctrl+N", lambda: self.new_project()),
            ("Ctrl+E", self._open_export_dialog),
            ("F", self._toggle_fullscreen),
            ("F11", self._toggle_fullscreen),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            global_command = keys in {"Ctrl+S", "Ctrl+Shift+S", "Ctrl+O", "Ctrl+N", "Ctrl+E", "F11"}
            shortcut.activated.connect(lambda slot=slot, allowed=global_command: self._dispatch(slot, allow_in_field=allowed))

    def _dispatch(self, slot: Callable[[], None], *, allow_in_field: bool = False) -> None:
        """Filtra os atalhos de uma tecla antes de deixá-los agir.

        Sem a primeira guarda, digitar um timecode dispararia as ações letra a
        letra. A segunda existe porque a janela de tela cheia é filha deste
        painel e o alcance do atalho a acompanha: sem ela, um Espaço lá seria
        contado duas vezes.
        """
        # Campo de texto, número ou lista: todos usam teclas que também são
        # atalhos daqui — o espaço abre a lista de mídias, as letras entram no
        # timecode.
        if not allow_in_field and isinstance(
            QApplication.focusWidget(),
            (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit),
        ):
            return
        if self._on_fullscreen:
            return
        slot()

    # ------------------------------------------------------------------
    # Estado derivado
    # ------------------------------------------------------------------

    @property
    def _duration(self) -> float:
        return self._project.duration

    @property
    def _fps(self) -> float:
        return self._project.fps

    @property
    def _position(self) -> float:
        return self._timeline.position

    @property
    def _has_video(self) -> bool:
        return self._project.has_video

    @property
    def _has_sound(self) -> bool:
        return self._project.has_sound and self._audio.available

    @property
    def _playable(self) -> bool:
        return self._has_video or self._has_sound

    @property
    def _on_fullscreen(self) -> bool:
        return self._fullscreen is not None and self._fullscreen.isVisible()

    # ------------------------------------------------------------------
    # Importação
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()
        ]
        if paths:
            self.import_files(paths, insert=True)
            event.acceptProposedAction()

    def import_media_dialog(self) -> None:
        self._choose_files()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, strings.EDIT_IMPORT, str(Path.home()), strings.EDIT_FILE_FILTER
        )
        if paths:
            self.import_files([Path(p) for p in paths], insert=True)

    def import_files(self, paths: list[Path], *, insert: bool = False) -> None:
        self._project_actions.import_files(paths, insert=insert)

    def _create_thumbnail_for(self, reference: MediaRef) -> QIcon:
        if reference.path in self._pool_thumbnails:
            return self._pool_thumbnails[reference.path]

        card = QPixmap(96, 54)
        card.fill(QColor(28, 28, 34))
        p = QPainter(card)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(60, 60, 70))
        p.drawRect(0, 0, 95, 53)
        font = p.font()
        font.setPointSize(16)
        p.setFont(font)
        sym = (
            "🎬"
            if reference.kind is MediaKind.VIDEO
            else ("🎵" if reference.kind is MediaKind.AUDIO else "🖼️")
        )
        p.drawText(card.rect(), Qt.AlignmentFlag.AlignCenter, sym)
        p.end()
        icon = QIcon(card)
        self._pool_thumbnails[reference.path] = icon

        if reference.kind in (MediaKind.VIDEO, MediaKind.IMAGE):
            tools = self._ensure_tools()
            if tools is not None:
                token = next(self._tokens)
                self._pool_tokens[reference.path] = token
                worker = self._runtime.filmstrip_worker(
                    reference.path, 0.0, 0.0, 1, (96, 54), tools, token
                )
                worker.signals.strip.connect(
                    lambda tok, idx, frame, ref=reference: self._on_pool_thumb_ready(ref, frame, token=tok)
                )
                self._background.start(worker, worker.signals.done)

        return icon

    def _on_pool_thumb_ready(self, reference: MediaRef, frame: object, *, token: int | None = None) -> None:
        if self._closed or (token is not None and self._pool_tokens.get(reference.path) != token):
            return
        try:
            data = getattr(frame, "data", None)
            w = getattr(frame, "width", 96)
            h = getattr(frame, "height", 54)
            if data:
                img = image_from_frame(data, w, h)
                card = QPixmap(96, 54)
                card.fill(QColor(24, 24, 28))
                scaled = img.scaled(
                    96,
                    54,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                p = QPainter(card)
                p.drawImage((96 - scaled.width()) // 2, (54 - scaled.height()) // 2, scaled)
                p.end()
                icon = QIcon(card)
                self._pool_thumbnails[reference.path] = icon
                for i in range(self._media_list.count()):
                    item = self._media_list.item(i)
                    ref = item.data(Qt.ItemDataRole.UserRole)
                    if ref and ref.path == reference.path:
                        item.setIcon(icon)
        except Exception:
            pass

    def _refresh_pool(self) -> None:
        self._syncing = True
        try:
            current_row = self._media_list.currentRow()
            self._media_list.clear()
            for reference in self._pool:
                duration_str = format_span(reference.natural_duration)
                if reference.has_video and reference.width and reference.height:
                    specs = f"{duration_str} · {reference.width}×{reference.height}"
                    if reference.fps:
                        specs += f" · {format_rate(reference.fps)} fps"
                elif reference.kind is MediaKind.AUDIO:
                    ch = reference.channels or 2
                    ch_str = "estéreo" if ch == 2 else ("mono" if ch == 1 else f"{ch} canais")
                    specs = f"{duration_str} · {ch_str}"
                else:
                    specs = duration_str

                item = QListWidgetItem(reference.name)
                item.setIcon(self._create_thumbnail_for(reference))
                item.setData(Qt.ItemDataRole.UserRole, reference)
                item.setToolTip(
                    f"{reference.name}\n{reference.path}\n"
                    f"{reference.kind.value.capitalize()} · {specs}"
                )
                self._media_list.addItem(item)

            if self._pool:
                new_row = min(max(0, current_row), len(self._pool) - 1)
                self._media_list.setCurrentRow(new_row)

            count = len(self._pool)
            self._pool_count_label.setText(
                strings.EDIT_MEDIA_COUNT.format(count=count) if count else ""
            )
            self._insert.setEnabled(bool(self._pool) and self._media_list.currentRow() >= 0)
        finally:
            self._syncing = False

    def _on_media_selection_changed(self) -> None:
        has_sel = self._media_list.currentRow() >= 0
        self._insert.setEnabled(has_sel)

    def _delete_selected_media(self) -> None:
        items = self._media_list.selectedItems()
        if not items:
            item = self._media_list.currentItem()
            if item is not None:
                items = [item]
        if not items:
            return
        for item in items:
            ref = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(ref, MediaRef):
                self._remove_media_ref(ref)

    def _show_media_context_menu(self, pos: QPoint) -> None:
        item = self._media_list.itemAt(pos)
        if item is not None and not item.isSelected():
            self._media_list.setCurrentItem(item)
        menu = QMenu(self)
        if item is not None:
            ref = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(ref, MediaRef):
                insert_action = menu.addAction(strings.EDIT_MEDIA_INSERT)
                insert_action.triggered.connect(lambda: self._insert_media_ref(ref))

                remove_action = menu.addAction(strings.EDIT_MEDIA_REMOVE)
                remove_action.triggered.connect(lambda: self._remove_media_ref(ref))
                menu.addSeparator()

        clear_unused_action = menu.addAction(strings.EDIT_CLEAR_UNUSED)
        clear_unused_action.triggered.connect(self._clear_unused_media)

        menu.exec(self._media_list.mapToGlobal(pos))

    def _insert_media_ref(self, reference: MediaRef) -> None:
        self._remember()
        self._place(reference)
        self._after_edit()

    def _remove_media_ref(self, reference: MediaRef) -> None:
        used_clips = [
            c for c in self._project.clips if c.media.path == reference.path
        ]
        if used_clips:
            QMessageBox.warning(
                self,
                strings.EDIT_MEDIA_IN_USE_TITLE,
                strings.EDIT_MEDIA_IN_USE_MSG.format(
                    name=reference.name, count=len(used_clips)
                ),
            )
            return

        if reference in self._pool:
            self._pool.remove(reference)
        self._pool_thumbnails.pop(reference.path, None)
        self._probed.pop(reference.path, None)
        self._refresh_pool()
        self._refresh_controls()

    def _clear_unused_media(self) -> None:
        used_paths = {c.media.path for c in self._project.clips if c.media.path}
        to_remove = [ref for ref in self._pool if ref.path not in used_paths]
        if not to_remove:
            return
        for ref in to_remove:
            self._pool.remove(ref)
            self._pool_thumbnails.pop(ref.path, None)
            self._probed.pop(ref.path, None)
        self._refresh_pool()
        self._refresh_controls()

    def _place(self, reference: MediaRef, at: float | None = None) -> None:
        """Coloca a mídia numa trilha compatível, a partir do instante dado.

        Procura a primeira trilha em que o bloco caiba inteiro; se não houver
        nenhuma, cria uma trilha nova em vez de empurrar o que já está lá — o
        que o usuário montou não se mexe sozinho.

        A tela do projeto não é decidida aqui: quem decide é :meth:`_sync_canvas`,
        depois de o bloco entrar, e olhando a edição inteira. Enquanto era o
        primeiro arquivo importado que mandava, a ordem de importação decidia a
        qualidade de tudo — e não havia como mudar de ideia.
        """
        clip = Clip(
            media=reference,
            start=max(0.0, self._position if at is None else at),
            duration=reference.natural_duration,
        )
        index = self._free_track(clip)
        if index is None:
            kind = (
                TrackKind.ADDITIONAL
                if clip.is_additional
                else (TrackKind.VIDEO if reference.has_video else TrackKind.AUDIO)
            )
            self._project = self._project.with_track(kind)
            index = self._free_track(clip)
            if index is None:
                index = len(self._project.tracks) - 1
        self._project = self._project.with_clip(index, clip)
        self._timeline.select(clip.clip_id)

    def _place_clip(self, clip: Clip) -> None:
        self._remember()
        index = self._free_track(clip)
        if index is None:
            kind = (
                TrackKind.ADDITIONAL
                if clip.is_additional
                else TrackKind.VIDEO
                if clip.is_transition or clip.has_image
                else TrackKind.AUDIO
            )
            self._project = self._project.with_track(kind)
            index = self._free_track(clip)
            if index is None:
                index = len(self._project.tracks) - 1
        self._project = self._project.with_clip(index, clip)
        self._timeline.select(clip.clip_id)
        self._after_edit()

    def _free_track(self, clip: Clip) -> int | None:
        for index, track in enumerate(self._project.tracks):
            if not accepts(track.kind, clip):
                continue
            if ((clip.has_image or clip.has_sound) and not track.visible) or (clip.has_sound and track.muted):
                continue
            floor, ceiling = track.free_range(clip.start)
            if floor <= clip.start and clip.end <= ceiling:
                return index
        return None

    def _insert_selected_media(self) -> None:
        row = self._media_list.currentRow()
        if not 0 <= row < len(self._pool):
            return
        self._remember()
        self._place(self._pool[row])
        self._after_edit()

    # ------------------------------------------------------------------
    # Menu do botão direito
    # ------------------------------------------------------------------

    def _show_menu(self, kind: str, track_index: int, clip_id: int, position) -> None:
        self.build_menu(kind, track_index, clip_id).exec(position)

    def build_menu(self, kind: str, track_index: int, clip_id: int) -> QMenu:
        """Monta o menu com o que faz sentido para o que foi clicado.

        Um menu que oferece "separar áudio" sobre um bloco sem som, ou "excluir
        trilha" sobre o vazio, obriga a ler tudo para descobrir o que serve —
        aqui cada item só aparece quando tem o que fazer.

        Montar e exibir são separados de propósito: abrir o menu inicia um laço
        de eventos próprio, e o que se quer conferir é a lista de opções, não o
        laço.
        """
        menu = QMenu(self)
        found = self._project.find(clip_id) if clip_id >= 0 else None
        clip = found[1] if found else None

        if clip is not None:
            self._act(
                menu,
                strings.EDIT_PROPERTIES,
                lambda: self._open_properties_tab(clip.clip_id),
                tip=strings.EDIT_PROPERTIES_TIP,
            )
            menu.addSeparator()
            self._act(menu, f"{strings.EDIT_SPLIT}  (S)", self._split_here,
                      enabled=not clip.is_transition and clip.contains(self._position))
            self._act(
                menu, f"{strings.EDIT_TRIM_LEFT}  (Q)",
                lambda: self._trim_to_cursor("inicio"),
                enabled=self._can_trim(clip, "inicio"),
                tip=strings.EDIT_TRIM_LEFT_TIP,
            )
            self._act(
                menu, f"{strings.EDIT_TRIM_RIGHT}  (W)",
                lambda: self._trim_to_cursor("fim"),
                enabled=self._can_trim(clip, "fim"),
                tip=strings.EDIT_TRIM_RIGHT_TIP,
            )
            self._act(
                menu,
                f"{strings.EDIT_COPY}  (Ctrl+C)",
                self._copy_clip,
                enabled=not clip.is_transition,
            )
            self._act(menu, f"{strings.EDIT_DELETE}  (Del)", self._delete_selected)
            menu.addSeparator()
            if clip.media.has_audio and clip.media.kind is not MediaKind.AUDIO:
                self._act(
                    menu, strings.EDIT_DETACH, self._detach_audio,
                    enabled=not clip.detached, tip=strings.EDIT_DETACH_TIP,
                )
            if clip.can_adjust_sound:
                self._act(
                    menu,
                    strings.EDIT_CLIP_UNMUTE if clip.muted else strings.EDIT_CLIP_MUTE,
                    lambda: self._on_clip_mute(not clip.muted),
                )

        if clip is None and self._clipboard is not None:
            self._act(menu, f"{strings.EDIT_PASTE}  (Ctrl+V)", self._paste_clip)

        if track_index >= 0:
            menu.addSeparator()
            track = self._project.tracks[track_index]
            if track.kind in (TrackKind.VIDEO, TrackKind.ADDITIONAL):
                self._act(
                    menu,
                    strings.EDIT_TRACK_HIDE if track.visible else strings.EDIT_TRACK_SHOW,
                    lambda: self._toggle_track_visibility(track_index),
                )
            if track.kind is not TrackKind.ADDITIONAL:
                self._act(
                    menu,
                    strings.EDIT_TRACK_UNMUTE if track.muted else strings.EDIT_TRACK_MUTE,
                    lambda: self._toggle_track_mute(track_index),
                )
            self._act(
                menu,
                strings.EDIT_DELETE_TRACK.format(name=track.name),
                lambda: self._remove_track(track_index),
                tip=strings.EDIT_DELETE_TRACK_TIP,
            )

        menu.addSeparator()
        self._act(menu, strings.EDIT_ADD_ADDITIONAL_TRACK_FULL,
                  lambda: self._add_track(TrackKind.ADDITIONAL))
        self._act(menu, strings.EDIT_ADD_VIDEO_TRACK_FULL,
                  lambda: self._add_track(TrackKind.VIDEO))
        self._act(menu, strings.EDIT_ADD_AUDIO_TRACK_FULL,
                  lambda: self._add_track(TrackKind.AUDIO))
        return menu

    def _open_properties_tab(self, clip_id: int) -> None:
        found = self._project.find(clip_id) if clip_id >= 0 else None
        if found is None:
            return
        _, clip = found
        self._timeline.select(clip_id)
        if not clip.contains(self._position):
            self._seek_to(clip.start)
        if self._extras_tabs.indexOf(self._properties_widget) < 0:
            self._extras_tabs.addTab(self._properties_widget, strings.EDIT_TAB_PROPERTIES)
            self._update_extras_tab_close_buttons()
        self._properties_widget.set_playhead_position(self._position)
        self._properties_widget.load_clip(clip, self._project.width, self._project.height, fps=self._project.fps, text_ratio=self._project.text_ratio)
        self._extras_tabs.setCurrentWidget(self._properties_widget)
        sizes = self._top_splitter.sizes()
        if len(sizes) >= 3 and sizes[1] < 340:
            diff = 340 - sizes[1]
            sizes[1] = 340
            sizes[2] = max(200, sizes[2] - diff)
            self._top_splitter.setSizes(sizes)

    def _end_properties_session(self) -> None:
        self._properties_session = -1
        self._properties_session_timer.stop()

    def _end_typing_session(self) -> None:
        if self._typing_session < 0:
            return
        self._typing_timer.stop()
        self._typing_session = -1
        self._session.commit_edit()

    def commit_pending_edits(self) -> None:
        self._end_edit_groups()
        self._session.commit_edit()

    def _end_edit_groups(self) -> None:
        self._end_typing_session()
        self._end_properties_session()
        self._end_gain_session()
        self._end_speed_session()
        if self._overlay_drag_session >= 0:
            self._session.commit_edit()
            self._overlay_drag_session = -1
            self._preview.end_transform()
            self._request_frame(force=True)

    def _begin_timeline_edit(self) -> None:
        self._end_edit_groups()
        self._session.begin_edit()

    def _on_properties_changed(self, clip_id: int, changes: dict) -> None:
        if self._syncing:
            return
        found = self._project.find(clip_id) if clip_id >= 0 else None
        if found is None:
            return
        if self._properties_session != clip_id:
            self._remember()
            self._properties_session = clip_id
        self._properties_session_timer.start()
        self._project = self._project.with_updated_clip(clip_id, **changes)
        found_after = self._project.find(clip_id)
        if not found_after:
            return
        track_idx, updated_clip = found_after

        self._sync_canvas()

        # Garante que o clipe permaneça ou torne a ser selecionado na timeline
        if self._timeline.selected != clip_id:
            self._timeline.select(clip_id)
        else:
            self._timeline.set_project(self._project, refit=False)

        # A duração de uma transição pode ser limitada pelas duas pontas do
        # corte. Recarregar devolve ao campo o valor realmente aceito pelo
        # domínio, em vez de deixar na tela um número que não será renderizado.
        if (
            updated_clip.is_transition
            and self._properties_widget._clip_id == clip_id
        ):
            self._properties_widget.load_clip(
                updated_clip,
                self._project.width,
                self._project.height,
                fps=self._project.fps,
                text_ratio=self._project.text_ratio,
            )

        track_visible = self._project.tracks[track_idx].visible
        self._preview.set_active_clip(
            updated_clip, self._project.width, self._project.height, visible=track_visible
        )
        self._preview.update()
        self._update_preview_overlay_clips()

        # Atualiza a renderização de vídeo no preview em tempo real
        self._request_frame(force=True)
        self.changed.emit()

    @staticmethod
    def _act(
        menu: QMenu,
        text: str,
        slot: Callable[[], None],
        *,
        enabled: bool = True,
        tip: str = "",
    ) -> None:
        action = menu.addAction(text)
        action.setEnabled(enabled)
        if tip:
            action.setToolTip(tip)
        action.triggered.connect(slot)

    def _remove_track(self, track_index: int) -> None:
        """Apaga a trilha. Com blocos dentro, pergunta antes."""
        if not 0 <= track_index < len(self._project.tracks):
            return
        track = self._project.tracks[track_index]
        if track.clips:
            answer = QMessageBox.question(
                self,
                strings.EDIT_DELETE_TRACK_TITLE,
                strings.EDIT_DELETE_TRACK_BODY.format(
                    name=track.name, count=len(track.clips)
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._remember()
        self._apply(self._project.without_track(track_index))

    # ------------------------------------------------------------------
    # Edição
    # ------------------------------------------------------------------

    def _remember(self) -> None:
        self._end_edit_groups()
        self._session.remember()

    def _apply(self, project: Project, *, refit: bool = False) -> None:
        self._project = project
        self._after_edit(refit=refit)

    def _after_edit(self, *, refit: bool = False) -> None:
        self._sync_canvas()
        self._timeline.set_project(self._project, refit=refit)
        self._refresh_clip_fields()
        self._refresh_controls()
        self._view_timer.start()
        if self._project.is_empty:
            self._preview.clear_frame()
        else:
            self._request_frame(force=True)
        if self._playing:
            # A composição mudou com a reprodução em andamento, e o que está
            # saindo é a composição de antes: o grafo do ffmpeg foi montado na
            # hora em que o fluxo abriu (ver :meth:`_restart_stream`).
            self._live_timer.start()
        self._update_preview_overlay_clips()
        self._update_project_label()
        self.changed.emit()

    def _on_clip_moved(self, clip_id: int, track_index: int, start: float) -> None:
        self._project = self._session.edit_origin.moved(clip_id, track_index, start)
        self._timeline.set_project(self._project)
        self._update_project_label()
        self._update_preview_overlay_clips()
        self._request_frame(force=True)

    def _on_clip_resized(self, clip_id: int, edge: str, seconds: float) -> None:
        self._project = self._session.edit_origin.resized(clip_id, edge, seconds)
        self._timeline.set_project(self._project)
        self._update_project_label()
        self._update_preview_overlay_clips()
        self._request_frame(force=True)

    def _on_edit_finished(self) -> None:
        self._session.commit_edit()
        self._after_edit()

    def _on_edit_cancelled(self) -> None:
        self._session.cancel_edit()
        self._end_edit_groups()
        self._after_edit()

    def _toggle_track_mute(self, index: int) -> None:
        self._remember()
        track = self._project.tracks[index]
        self._apply(self._project.with_track_muted(index, not track.muted))
        if self._playing:
            self._live_timer.stop()
            self._restart_stream()

    def _toggle_track_visibility(self, index: int) -> None:
        self._remember()
        track = self._project.tracks[index]
        self._apply(self._project.with_track_visible(index, not track.visible))
        active = self._timeline.selected_clip
        if active is not None:
            found = self._project.find(active.clip_id)
            if found is not None and found[0] == index:
                self._preview.set_active_clip(
                    active, self._project.width, self._project.height, visible=self._project.tracks[index].visible
                )
        if self._playing:
            self._live_timer.stop()
            self._restart_stream()
        else:
            self._request_frame(force=True)

    def _on_track_reordered(self, from_index: int, to_index: int) -> None:
        if not self._session.editing:
            self._remember()
        self._apply(self._project.reordered_track(from_index, to_index))
        if self._playing:
            self._live_timer.stop()
            self._restart_stream()

    def _add_track(self, kind: TrackKind) -> None:
        self._remember()
        self._apply(self._project.with_track(kind))

    def _split_here(self) -> None:
        position = self._position
        clip = next(
            (c for c in self._project.clips if c.contains(position)), None
        )
        selected = self._timeline.selected_clip
        if selected is not None:
            clip = selected
        if clip is None or clip.is_transition or not clip.contains(position):
            return
        if min(position - clip.start, clip.end - position) < MIN_SEGMENT:
            return
        self._remember()
        self._apply(self._project.split(clip.clip_id, position))

    def _delete_selected(self) -> None:
        focused = QApplication.focusWidget()
        if self._media_list.hasFocus() or (focused is not None and self._media_list.isAncestorOf(focused)):
            self._delete_selected_media()
            return
        clip = self._timeline.selected_clip
        if clip is None:
            if not self._timeline.hasFocus() and (self._media_list.selectedItems() or self._media_list.currentRow() >= 0):
                self._delete_selected_media()
                return
            return
        self._remember()
        self._apply(self._project.without_clip(clip.clip_id))

    def _trim_to_cursor(self, edge: str) -> None:
        """Apaga o que está de um lado do cursor, dentro do bloco selecionado.

        É o mesmo que arrastar aquela ponta até o cursor — e é literalmente a
        mesma operação do modelo (``Project.resized``), então o ponto de origem
        acompanha, os vizinhos são respeitados e o desfazer funciona igual.
        Existe como botão porque mirar a ponta com o mouse exige aproximar até
        o quadro, e o cursor já está no lugar exato.
        """
        clip = self._timeline.selected_clip
        if not self._can_trim(clip, edge):
            return
        self._remember()
        self._apply(self._project.resized(clip.clip_id, edge, self._position))

    def _can_trim(self, clip: Clip | None, edge: str) -> bool:
        """Se há o que apagar daquele lado, e se sobra bloco depois.

        Sobrar menos que o mínimo não é aparar, é apagar o bloco por um caminho
        que não diz isso — para apagar existe a lixeira ao lado.
        """
        if clip is None or clip.is_transition or not clip.contains(self._position):
            return False
        if edge == "inicio":
            return (
                self._position > clip.start
                and clip.end - self._position >= MIN_SEGMENT
            )
        return self._position - clip.start >= MIN_SEGMENT

    def _detach_audio(self) -> None:
        clip = self._timeline.selected_clip
        if clip is None or clip.media is None or not clip.media.has_audio:
            return
        self._remember()
        self._apply(self._project.detached_audio(clip.clip_id))

    def _copy_clip(self) -> None:
        clip = self._timeline.selected_clip
        if clip is not None and not clip.is_transition:
            self._clipboard = clip
            self._refresh_controls()

    def _paste_clip(self) -> None:
        """Cola no cursor, numa trilha que aceite e onde caiba."""
        if self._clipboard is None:
            return
        self._remember()
        pasted = replace(
            self._clipboard, start=self._position, clip_id=next_clip_id()
        )
        index = self._free_track(pasted)
        if index is None:
            kind = (
                TrackKind.ADDITIONAL
                if pasted.is_additional
                else TrackKind.VIDEO
                if pasted.is_transition or pasted.has_image
                else TrackKind.AUDIO
            )
            project = self._project.with_track(kind)
            self._project = project
            index = self._free_track(pasted)
            if index is None:
                index = len(project.tracks) - 1
        self._project = self._project.with_clip(index, pasted)
        self._timeline.select(pasted.clip_id)
        self._after_edit()

    def _undo_edit(self) -> None:
        self._end_edit_groups()
        if self._session.undo():
            self._after_edit()

    def _redo_edit(self) -> None:
        self._end_edit_groups()
        if self._session.redo():
            self._after_edit()

    # -- propriedades do bloco -------------------------------------------

    def _on_gain(self, value: float) -> None:
        """Aplica o volume ao bloco, agrupando o arrasto num passo de desfazer.

        Um ``QDoubleSpinBox`` avisa a cada passo de meio decibel: sem o
        agrupamento, ajustar de 0 a −6 dB enfileiraria doze desfazeres, e voltar
        atrás exigiria doze Ctrl+Z para desfazer uma decisão só.
        """
        clip = self._timeline.selected_clip
        if self._syncing or clip is None or abs(clip.gain_db - value) < 0.01:
            return
        if self._gain_session != clip.clip_id:
            self._remember()
            self._gain_session = clip.clip_id
        self._apply(self._project.with_updated_clip(clip.clip_id, gain_db=value))

    def _end_gain_session(self) -> None:
        """Fecha o agrupamento: o próximo ajuste vira um desfazer novo."""
        self._gain_session = -1

    def _on_clip_mute(self, muted: bool) -> None:
        clip = self._timeline.selected_clip
        if self._syncing or clip is None or clip.muted == muted:
            return
        self._remember()
        self._apply(self._project.with_updated_clip(clip.clip_id, muted=muted))

    def _on_clip_selected(self, _clip_id: int) -> None:
        self._end_edit_groups()
        self._refresh_clip_fields()
        # Trocar de bloco troca o que os controles alcançam — volume e mudo se
        # desligam num bloco sem som ajustável. Antes isto pegava carona no fim
        # do arrasto; agora que um clique simples não conta como edição (ver
        # ``timeline._DRAG_SLACK``), a seleção precisa avisar por conta própria.
        self._refresh_controls()
        # Selecionar muda as alças, não os pixels da composição.
        if self._interaction_context != self._interaction_key():
            self._invalidate_interaction()
        self._prepare_interaction()
        if not self._preview.has_frame:
            self._request_frame()

    def _show_volume_popup(self) -> None:
        clip = self._timeline.selected_clip
        if clip is None:
            return
        popup = _VolumePopup(clip.gain_db, parent=self)
        popup.gain_changed.connect(self._on_gain)
        popup.finished.connect(self._end_gain_session)
        pos = self._volume_btn.mapToGlobal(QPoint(0, self._volume_btn.height() + 2))
        popup.move(pos)
        popup.show()

    def _show_speed_popup(self) -> None:
        clip = self._timeline.selected_clip
        if clip is None:
            return
        popup = _SpeedPopup(clip.speed, parent=self)
        def apply_speed(value):
            self._on_speed(value)
            updated = self._project.find(clip.clip_id)
            if updated is not None:
                popup._spin.blockSignals(True)
                popup._spin.setValue(updated[1].speed)
                popup._spin.blockSignals(False)
        popup.speed_changed.connect(apply_speed)
        popup.finished.connect(self._end_speed_session)
        pos = self._speed_btn.mapToGlobal(QPoint(0, self._speed_btn.height() + 2))
        popup.move(pos)
        popup.show()

    def _on_speed(self, value: float) -> None:
        clip = self._timeline.selected_clip
        if self._syncing or clip is None or abs(clip.speed - value) < 0.01:
            return
        found = self._project.find(clip.clip_id)
        if found is None:
            return
        track_idx, _ = found
        track = self._project.tracks[track_idx]
        other_clips = [c for c in track.clips if c.clip_id != clip.clip_id and not c.is_transition]
        ceiling = float("inf")
        for c in other_clips:
            if c.start >= clip.start and c.start < ceiling:
                ceiling = c.start

        source_span = clip.duration * clip.speed
        target_duration = source_span / max(0.1, value)
        new_duration = max(MIN_SEGMENT, target_duration)
        if clip.start + new_duration > ceiling + 1e-9:
            QMessageBox.warning(self, strings.DIALOG_WARNING_TITLE, strings.EDIT_SPEED_COLLISION)
            return
        if self._speed_session != clip.clip_id:
            self._remember()
            self._speed_session = clip.clip_id

        self._apply(
            self._project.with_updated_clip(clip.clip_id, speed=value, duration=new_duration)
        )
        self._refresh_clip_fields()
        self._refresh_controls()

    def _end_speed_session(self) -> None:
        self._speed_session = -1

    def _on_overlay_transformed(
        self, clip_id: int, x: float, y: float, scale: float, rotation: float
    ) -> None:
        if self._syncing:
            return
        if self._overlay_drag_session != clip_id:
            self._end_edit_groups()
            self._session.begin_edit()
            self._overlay_drag_session = clip_id
        active = self._preview._active_clip
        sx = getattr(active, "scale_x", scale) if active else scale
        sy = getattr(active, "scale_y", scale) if active else scale
        if active is not None and active.has_keyframes:
            self._project = self._project.with_updated_clip(
                clip_id,
                keyframes=active.keyframes,
                x=x,
                y=y,
                scale=scale,
                scale_x=sx,
                scale_y=sy,
                rotation=rotation,
            )
            self._preview.set_active_clip(
                active, self._project.width, self._project.height
            )
        else:
            self._project = self._project.with_updated_clip(
                clip_id, x=x, y=y, scale=scale, scale_x=sx, scale_y=sy, rotation=rotation
            )
        if (
            hasattr(self, "_properties_widget")
            and self._extras_tabs.indexOf(self._properties_widget) >= 0
            and self._properties_widget._clip_id == clip_id
        ):
            self._properties_widget.update_transform_fields(x, y, sx, sy, rotation)
        self._timeline.set_project(self._project, refit=False)
        self._request_frame(force=True)
        self.changed.emit()

    def _on_overlay_transform_finished(self, clip_id: int) -> None:
        self._session.commit_edit()
        self._overlay_drag_session = -1
        self._after_edit()
        if (
            hasattr(self, "_properties_widget")
            and self._extras_tabs.indexOf(self._properties_widget) >= 0
            and self._properties_widget._clip_id == clip_id
        ):
            found = self._project.find(clip_id)
            if found is not None:
                self._properties_widget.load_clip(found[1], self._project.width, self._project.height, fps=self._project.fps, text_ratio=self._project.text_ratio)

    def _on_overlay_transform_cancelled(self, clip_id: int) -> None:
        self._preview._interaction_visible = False
        if self._overlay_drag_session == clip_id:
            self._on_edit_cancelled()

    def _refresh_clip_fields(self) -> None:
        clip = self._timeline.selected_clip
        self._syncing = True
        try:
            if clip is not None:
                self._volume_btn.setText(f"🔊 {clip.gain_db:+.1f} dB".replace(".", ","))
                self._speed_btn.setText(f"⚡ {clip.speed:.1f}x".replace(".", ","))
            else:
                self._volume_btn.setText("🔊 0,0 dB")
                self._speed_btn.setText("⚡ 1,0x")
            self._sync_extras_controls(clip)
        finally:
            self._syncing = False

        if clip is None:
            self._clip_label.setText(strings.EDIT_CLIP_NONE)
            self._preview.set_active_clip(None, self._project.width, self._project.height)
            self._update_preview_overlay_clips()
            return

        found = self._project.find(clip.clip_id) if clip is not None else None
        track_visible = True
        if found is not None:
            t_idx, _ = found
            track_visible = self._project.tracks[t_idx].visible

        self._preview.set_active_clip(clip, self._project.width, self._project.height, visible=track_visible)
        info = strings.EDIT_CLIP_INFO.format(
            name=clip.media.name if clip.media else (clip.text_content or clip.overlay_type), duration=format_span(clip.duration)
        )
        if clip.detached:
            info = f"{info} · {strings.EDIT_CLIP_DETACHED}"
        if abs(clip.speed - 1.0) >= 0.01:
            info = f"{info} · {clip.speed:.1f}x"
        self._clip_label.setText(info)
        self._update_preview_overlay_clips()

    def _update_preview_overlay_clips(self) -> None:
        # A prévia mostra o quadro composto pelo ffmpeg, e não uma reprodução
        # própria das camadas: o que chega aqui são as alças e o que pode ser
        # selecionado, nunca pixels recortados da imagem final.
        self._preview._fps = self._project.fps
        self._preview._text_ratio = self._project.text_ratio
        if self._on_fullscreen or self._playing:
            self._preview.set_overlay_clips(())
            return
        self._preview._selectable_clips = tuple(
            c for t in reversed(self._project.tracks) if t.visible
            for c in sorted(t.clips, key=lambda c: (c.start, c.clip_id))
            if t.kind is not TrackKind.AUDIO and c.has_image and not c.audio_only
            and c.overlay_type not in ("filter", "transition")
            and c.contains(self._preview._position)
            and c.transform_at(self._preview._position - c.start).opacity > 0
        )
        visual_tracks = [
            t
            for t in self._project.tracks
            if t.visible and t.kind is TrackKind.ADDITIONAL
        ]
        clips = tuple(
            c
            for t in reversed(visual_tracks)
            for c in t.clips
            if c.overlay_type != "filter"
            and not c.is_transition
            and not c.audio_only
            and (c.overlay_type in ("image", "text") or c.is_image)
            and c.contains(self._position)
            and not c.chromakey_enabled
        )
        self._preview.set_overlay_clips(clips)

    # ------------------------------------------------------------------
    # Tela do projeto
    # ------------------------------------------------------------------

    def _sync_canvas(self) -> None:
        """Põe a tela do projeto de acordo com o que está escolhido.

        A escolha é **do painel, não do projeto**: ela é uma preferência de
        saída, como "corte rápido", e não uma alteração da montagem. Por isso
        não entra na pilha de desfazer — um Ctrl+Z que devolvesse a tela antiga
        sem mexer no controle deixaria os dois discordando na tela seguinte.

        As duas metades são independentes: dá para fixar o tamanho e deixar a
        taxa seguir o material, ou o contrário.
        """
        material = auto_canvas(self._project)
        width, height = self._canvas_choice or (material.width, material.height)
        fps = self._rate_choice or material.fps
        if (self._project.width, self._project.height, self._project.fps) == (
            width, height, fps
        ):
            return
        self._project = self._project.with_output_canvas(width, height, fps)

    def _apply_slideshow_canvas(self) -> None:
        suggestion = slideshow_canvas(self._project)
        if suggestion is None:
            return
        self._canvas_choice = suggestion
        self._aspect_choice = format_aspect_ratio(*suggestion)
        self._after_edit()

    def _aspect_options(self) -> list[tuple[str, str | None]]:
        options = [
            (strings.EDIT_CANVAS_ASPECT_AUTO, None),
            ("16:9", "16:9"),
            ("4:3", "4:3"),
            ("9:16", "9:16"),
            ("1:1", "1:1"),
            ("21:9", "21:9"),
        ]
        if self._aspect_choice and all(value != self._aspect_choice for _, value in options):
            options.append((self._aspect_choice, self._aspect_choice))
        return options

    def _on_aspect_choice(self, index: int) -> None:
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
        self._after_edit()

    def _on_canvas_choice(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._canvas_choice = self._canvas_box.itemData(index)
        if self._canvas_choice is not None:
            self._aspect_choice = format_aspect_ratio(*self._canvas_choice)
        else:
            self._aspect_choice = None
        self._after_edit()

    def _on_rate_choice(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._rate_choice = self._rate_box.itemData(index)
        self._after_edit()

    def _canvas_options(self) -> list[tuple[str, object]]:
        """Automática, os tamanhos do próprio material e os formatos comuns.

        Os tamanhos das mídias importadas vêm primeiro porque são os únicos que
        não custam nada: qualquer outro obriga a redimensionar todo bloco.
        """
        options: list[tuple[str, object]] = [(strings.EDIT_CANVAS_AUTO, None)]
        seen: set[tuple[int, int]] = set()
        sizes = [
            (ref.width, ref.height)
            for ref in self._pool
            if ref.has_video and ref.width and ref.height
        ]
        ordered = sorted(sizes, key=lambda size: -size[0] * size[1])
        # Projetos reabertos e o slideshow podem usar tamanhos que não estão
        # no acervo nem nos presets. A reconstrução do controle deve conservá-los.
        all_candidates = ([self._canvas_choice] if self._canvas_choice else []) + [*ordered, *_CANVAS_PRESETS]
        if self._aspect_choice:
            filtered = [
                (w, h)
                for (w, h) in all_candidates
                if format_aspect_ratio(w, h) == self._aspect_choice
            ]
        else:
            filtered = all_candidates

        for width, height in filtered:
            if (width, height) in seen:
                continue
            seen.add((width, height))
            aspect = format_aspect_ratio(width, height)
            label = (
                f"{aspect} · {width} × {height}"
                if aspect and not self._aspect_choice
                else strings.EDIT_CANVAS_SIZE.format(width=width, height=height)
            )
            options.append((label, (width, height)))
        return options

    def _rate_options(self) -> list[tuple[str, object]]:
        options: list[tuple[str, object]] = [(strings.EDIT_CANVAS_RATE_AUTO, None)]
        rates = {
            round(ref.fps, 3) for ref in self._pool if ref.has_video and ref.fps
        }
        for rate in sorted(rates | set(_RATE_PRESETS)):
            options.append((strings.EDIT_CANVAS_FPS.format(fps=format_rate(rate)), rate))
        return options

    def _refresh_canvas_controls(self) -> None:
        """Reconstrói as listas só quando elas mudam de conteúdo.

        Refazer a lista a cada alteração da edição fecharia o menu na cara de
        quem estivesse com ele aberto.
        """
        self._syncing = True
        try:
            aspect_opts = self._aspect_options()
            if [self._aspect_box.itemData(i) for i in range(self._aspect_box.count())] != [
                data for _, data in aspect_opts
            ]:
                self._aspect_box.clear()
                for label, data in aspect_opts:
                    self._aspect_box.addItem(label, data)
            idx_a = _index_of(self._aspect_box, self._aspect_choice)
            self._aspect_box.setCurrentIndex(max(0, idx_a))

            for box, options, choice in (
                (self._canvas_box, self._canvas_options(), self._canvas_choice),
                (self._rate_box, self._rate_options(), self._rate_choice),
            ):
                # Comparação só pelos dados: o texto do primeiro item é
                # reescrito no fim daqui com a tela que a escolha produziu.
                if [box.itemData(i) for i in range(box.count())] != [
                    data for _, data in options
                ]:
                    box.clear()
                    for label, data in options:
                        box.addItem(label, data)
                index = _index_of(box, choice)
                if index < 0 and choice is not None:
                    # A escolha sumiu da lista: volta ao automático de verdade,
                    # em vez de a lista dizer "Automática" e a exportação sair
                    # com a tela antiga.
                    self._canvas_choice, self._rate_choice = (
                        (None, self._rate_choice)
                        if box is self._canvas_box
                        else (self._canvas_choice, None)
                    )
                box.setCurrentIndex(max(0, index))
        finally:
            self._syncing = False

        # O que a escolha automática produziu fica à vista mesmo sem abrir a
        # lista: sem isso, "Automática" não diz em que tela a edição está.
        proj_aspect = format_aspect_ratio(self._project.width, self._project.height)
        self._aspect_box.setItemText(
            0,
            f"{strings.EDIT_CANVAS_ASPECT_AUTO}  ({proj_aspect})"
            if proj_aspect
            else strings.EDIT_CANVAS_ASPECT_AUTO,
        )
        self._canvas_box.setItemText(
            0,
            f"{strings.EDIT_CANVAS_AUTO}  ("
            + strings.EDIT_CANVAS_SIZE.format(
                width=self._project.width, height=self._project.height
            )
            + ")",
        )
        self._rate_box.setItemText(
            0,
            f"{strings.EDIT_CANVAS_RATE_AUTO}  ("
            + strings.EDIT_CANVAS_FPS.format(fps=format_rate(self._project.fps))
            + ")",
        )

    # ------------------------------------------------------------------
    # Prévia
    # ------------------------------------------------------------------

    def _preview_size(self) -> tuple[int, int]:
        """Tamanho a pedir ao ffmpeg para a superfície que está à frente.

        O mesmo tamanho para o quadro parado e para a reprodução: pedir menor e
        ampliar na exibição — o que se fazia em tela cheia — devolve uma imagem
        borrada, que se lê como perda de qualidade do vídeo e não como escolha
        da prévia. Medido: 1920×1080 a 60 fps atravessa o cano sem atrasar.
        """
        if self._on_fullscreen:
            area = self._fullscreen.size()
            if area.width() <= 640 or area.height() <= 480:
                screen = self._fullscreen.screen() or QApplication.primaryScreen()
                if screen is not None:
                    area = screen.geometry().size()
            ceiling = max(_FULLSCREEN_MAX_WIDTH, area.width())
            return fit_size(
                self._project.width,
                self._project.height,
                min(ceiling, max(160, area.width())),
                max(120, area.height()),
            )
        area = self._preview.size()
        ceiling = _PREVIEW_MAX_WIDTH
        return fit_size(
            self._project.width,
            self._project.height,
            min(ceiling, max(160, area.width())),
            max(120, area.height()),
        )

    def _interaction_key(self):
        clip = self._preview._active_clip
        if self._closed or self._playing or self._on_fullscreen or clip is None:
            return None
        plan = interaction_plan(self._project, clip.clip_id, self._position)
        return (self._generation, self._preview_size(), plan) if plan else None

    def _invalidate_interaction(self) -> None:
        self._interaction_context = None
        self._interaction_token = next(self._tokens)
        self._preview.set_interaction_layers(None)
        if self._interaction_worker is not None:
            self._interaction_worker.cancel()

    def _prepare_interaction(self) -> None:
        key = self._interaction_key()
        if key is None or key == self._interaction_context:
            return
        if self._interaction_worker is not None:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        self._interaction_context = key
        self._interaction_token = next(self._tokens)
        plan = key[2]
        worker = self._runtime.interaction_worker(plan, key[1], tools, self._interaction_token,
                                                  text_assets=self.editor.text_assets(self._project))
        self._interaction_worker = worker
        worker.signals.frame.connect(self._on_interaction_ready)
        worker.signals.done.connect(self._on_interaction_done)
        self._runner.start(worker, worker.signals.done)

    def _on_interaction_done(self) -> None:
        self._interaction_worker = None
        if not self._closed and self._interaction_context != self._interaction_key():
            self._prepare_interaction()

    def _on_interaction_ready(self, token: int, images: object) -> None:
        if (self._closed or token != self._interaction_token
                or self._interaction_context != self._interaction_key()):
            return
        layers = tuple(QPixmap.fromImage(QImage.fromData(data)) for data in images)
        if len(layers) == 3 and all(not p.isNull() for p in layers):
            self._preview.set_interaction_layers(layers)

    def _request_frame(self, *, force: bool = False) -> None:
        if self._closed or self._project.is_empty:
            return
        if self._interaction_context is not None and self._interaction_context != self._interaction_key():
            self._invalidate_interaction()
        if self._playing:
            if force:
                self._loading_label.setText(strings.EDIT_LOADING_FRAME)
                if not self._live_timer.isActive():
                    self._live_timer.start()
            return
        self._cancel_primed_playback()
        changed = self._wanted != self._position
        self._wanted = self._position
        if force:
            self._frame_revision += 1
            self._rendered = None
        if force or changed:
            self._frame_token = next(self._tokens)
        if self._overlay_drag_session >= 0 and self._preview.begin_interaction():
            self._loading_label.setText("")
            return
        self._loading_label.setText(strings.EDIT_LOADING_FRAME)
        if self._frame_busy:
            return
        self._start_frame()

    def _start_frame(self) -> None:
        tools = self._ensure_tools()
        if tools is None or self._wanted is None:
            return
        self._frame_busy = True
        if hasattr(self, "_loading_label") and not self._preview.has_frame:
            self._loading_label.setText(strings.EDIT_LOADING_FRAME)
            self._preview.setText(strings.EDIT_LOADING_FRAME)
        self._rendered = self._wanted
        revision = self._frame_revision
        self._frame_token = next(self._tokens)
        size = self._preview_size()

        proj = self._project
        key = PreviewResultKey(self._frame_token, self._generation, revision,
                               self._wanted, size, self._project.fps)
        self._frame_key = key
        self._frame_job_token = key.token
        self._frame_error_token = 0

        worker = self._runtime.frame_worker(
            proj, self._wanted, size, tools, self._frame_token,
            text_assets=self.editor.text_assets(proj),
        )
        worker.signals.frame.connect(self._on_frame)
        if hasattr(worker.signals, "failed"):
            worker.signals.failed.connect(self._on_preview_failed)
        worker.signals.done.connect(
            lambda key=key: self._on_frame_done(key.revision, key.token)
        )
        self._runner.start(worker, worker.signals.done)

    def _on_frame_done(self, revision: int, token: int | None = None) -> None:
        if self._closed or (token is not None and token != self._frame_job_token):
            return
        self._frame_busy = False
        self._frame_job_token = 0
        if self._overlay_drag_session >= 0 and self._preview._interaction_visible:
            return
        if self._playing or self._project.is_empty:
            return
        current = (revision == self._frame_revision
                   and (token is None or token == self._frame_token)
                   and (self._frame_key is None or self._frame_key.size == self._preview_size())
                   and (self._wanted is None or self._wanted == self._rendered))
        if self._wanted is not None and not current:
            self._start_frame()
        elif current and self._frame_error_token != token:
            self._prime_playback()

    def _on_preview_failed(self, token: int, message: str) -> None:
        if self._closed or token not in (self._frame_token, self._play_token):
            return
        self._frame_error_token = token
        if token == self._play_token and self._playing:
            self._stop_playback()
        self._loading_label.setText(message)

    def _on_frame(self, token: int, frame: object) -> None:
        if isinstance(frame, PreviewFrameInbox):
            frame = frame.take()
        if self._closed or frame is None:
            return
        if self._overlay_drag_session >= 0 and self._preview._interaction_visible:
            return
        current = True
        if token == self._play_token and self._playing:
            current = getattr(self, "_playback_project", self._project) is self._project
        else:
            key = self._frame_key
            if key is None:
                if token != self._frame_token:
                    return
            else:
                if (self._playing or key.token != token or key.generation != self._generation
                        or key.seconds != self._wanted or key.size != self._preview_size()):
                    return
                current = token == self._frame_token and key.revision == self._frame_revision
                editing = (self._session.editing or self._overlay_drag_session >= 0
                           or self._properties_session >= 0 or self._typing_session >= 0)
                if not current and not editing:
                    return
                # Durante um gesto, apresentar snapshots completos em ordem
                # evita esperar a mão parar. A indicação de atualização só
                # desaparece quando chega a revisão final, nunca num seek antigo.
                if (self._presented_key is not None and self._presented_key.generation == key.generation
                        and self._presented_key.revision > key.revision):
                    return
                self._presented_key = key
        self._loading_label.setText("" if current else strings.EDIT_LOADING_FRAME)
        self._shown_frame = frame.seconds
        self._preview.set_position(frame.seconds)
        self._show_frame(frame)
        if current:
            self._prepare_interaction()
        if token == self._play_token and self._playing and self._clock_started is None:
            self._clock_position = frame.seconds
            self._clock_started = time.monotonic()

    def _show_frame(self, frame: object) -> None:
        pixmap = pixmap_from_frame(frame.data, frame.width, frame.height)
        if self._on_fullscreen:
            self._fullscreen.set_frame(pixmap)
            return
        self._preview.set_frame_pixmap(pixmap)
        self._update_preview_overlay_clips()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._preview.update()
        if not self._project.is_empty:
            self._resize_timer.start()
            self._view_timer.start()

    def _on_splitter_moved(self, pos: int, index: int) -> None:
        self._preview.update()
        if not self._project.is_empty:
            self._resize_timer.start()
            self._view_timer.start()

    def _toggle_collapsed(self) -> None:
        """Retrai a prévia para a linha do tempo ficar com a janela.

        Em vez de esconder a imagem, ela encolhe: durante um trabalho de
        montagem o que se olha é a trilha, mas perder a referência do que está
        no cursor atrapalharia mais do que ajuda.
        """
        self._collapsed = not self._collapsed
        self._preview.setMinimumHeight(
            _PREVIEW_COLLAPSED if self._collapsed else _PREVIEW_MIN_HEIGHT
        )
        total = sum(self._split_view.sizes())
        if self._collapsed:
            # Recolhe a imagem ao mínimo e passa **todo** o resto às trilhas.
            top = self._player_box.minimumSizeHint().height()
            self._split_view.setSizes([top, max(0, total - top)])
        else:
            self._split_view.setSizes([total // 2, total - total // 2])
        self._collapse.setText(
            strings.EDIT_EXPAND if self._collapsed else strings.EDIT_COLLAPSE
        )
        self._preview.update()
        self._resize_timer.start()
        self.changed.emit()

    # ------------------------------------------------------------------
    # Miniaturas e onda, por bloco
    # ------------------------------------------------------------------

    def _on_view_changed(self) -> None:
        self._sync_scrollbar()
        self._view_timer.start()

    def _refresh_backdrop(self) -> None:
        """Pede as imagens dos blocos visíveis que ainda não servem.

        Cada bloco tem as suas: a tira sai da mídia dele, no trecho dele. Um
        bloco fora da vista não é gerado — numa edição longa, isso é a diferença
        entre uma dúzia de chamadas ao ffmpeg e centenas.

        Refaz também quando o bloco foi cortado (o trecho de origem mudou) ou
        quando ele cresceu bastante na tela: aproximar sem refazer deixaria as
        mesmas poucas miniaturas esticadas, cada vez mais borradas.
        """
        tools = self._ensure_tools()
        if tools is None:
            return
        start, end = self._timeline.view
        for track in self._project.tracks:
            for clip in track.clips:
                # O marcador usa uma referência sintética. Agora que vive na
                # trilha de vídeo, não pode cair no caminho que tenta extrair
                # miniaturas de cada mídia: isso abria um ffmpeg inútil para
                # "Transição_..." e disputava a pool justamente ao dar play.
                if clip.is_transition:
                    continue
                if clip.end < start or clip.start > end:
                    continue
                if not self._strip_is_stale(clip, track.kind):
                    continue
                if track.kind is TrackKind.VIDEO or clip.is_image or clip.overlay_type == "image":
                    self._request_thumbs(clip, tools)
                elif clip.media is not None and clip.media.has_audio:
                    self._request_wave(clip, tools)

    def _strip_window(self, clip: Clip) -> tuple[float, float]:
        """Trecho de origem que precisa de imagem: só o pedaço à vista.

        Um bloco de duas horas com doze miniaturas espalhadas por ele não diz
        nada quando se aproxima em dez segundos. Gerando só o que está na tela,
        as mesmas doze imagens cobrem o que se está olhando — e um bloco longo
        fora da vista deixa de custar qualquer coisa.
        """
        start, end = self._timeline.view
        begin = max(clip.start, start)
        finish = min(clip.end, end)
        if finish <= begin:
            return clip.in_point, clip.out_point
        return clip.source_time(begin), clip.source_time(finish)

    def _strip_is_stale(self, clip: Clip, kind: TrackKind) -> bool:
        current = self._timeline.strip_range(clip.clip_id)
        if current is None:
            return True
        if clip.is_image or clip.overlay_type == "image":
            return False

        begin, finish = self._strip_window(clip)
        tolerance = max(0.05, (finish - begin) * 0.02)
        if begin < current[0] - tolerance or finish > current[1] + tolerance:
            return True  # a vista saiu do que já foi gerado
        if kind is not TrackKind.VIDEO:
            return False
        # Refaz quando o trecho à vista couber no dobro do detalhe atual: sem
        # esse passo grosso, cada movimento da roda do mouse geraria imagens que
        # o movimento seguinte descartaria.
        coberto = max(1e-6, current[1] - current[0])
        return (finish - begin) * 2 <= coberto

    def _thumb_count(self, clip: Clip) -> int:
        if clip.is_image or clip.overlay_type == "image":
            return 1
        return max(1, min(_MAX_THUMBS, round(self._clip_pixels(clip) / FILM_CELL_WIDTH)))

    def _clip_pixels(self, clip: Clip) -> float:
        """Largura em pixels da parte do bloco que está à vista."""
        start, end = self._timeline.view
        span = max(1e-6, end - start)
        visivel = max(0.0, min(clip.end, end) - max(clip.start, start))
        return max(1.0, visivel / span * max(1, self._timeline.width() - 120))

    def _request_thumbs(self, clip: Clip, tools: FFmpegTools) -> None:
        # Uma imagem não tem trecho de origem para percorrer: uma miniatura só,
        # esticada por todo o bloco. Sem isso a tira cobriria uma fatia mínima
        # dele e o resto ficaria em branco.
        begin, finish = self._strip_window(clip)
        count = self._thumb_count(clip)
        token = next(self._tokens)
        self._cancel_strip(clip.clip_id)
        self._strip_tokens[clip.clip_id] = token
        self._timeline.set_strip(clip.clip_id, begin, finish, count)
        worker = self._runtime.filmstrip_worker(
            clip.media.path,
            begin,
            begin if clip.is_image else finish,
            count,
            (FILM_CELL_WIDTH, VIDEO_TRACK_HEIGHT - 14),
            tools,
            token,
        )
        worker.signals.strip.connect(
            lambda tok, index, frame, cid=clip.clip_id: self._on_thumb(
                tok, cid, index, frame
            )
        )
        self._strip_workers[clip.clip_id] = worker
        worker.signals.done.connect(lambda cid=clip.clip_id, tok=token: self._on_strip_done(cid, tok))
        self._background.start(worker, worker.signals.done)

    def _cancel_strip(self, clip_id: int) -> None:
        """Interrompe a geração anterior de miniaturas deste bloco.

        O token já descartaria as imagens atrasadas, mas o ffmpeg continuaria
        gerando cada uma delas: aproximar três vezes seguidas deixaria três
        gerações disputando a fila de trabalho.
        """
        self._wave_requests.pop(clip_id, None)
        worker = self._strip_workers.pop(clip_id, None)
        if worker is not None:
            worker.cancel()

    def _on_thumb(self, token: int, clip_id: int, index: int, frame: object) -> None:
        if self._strip_tokens.get(clip_id) != token:
            return
        # O quadro carrega o instante de origem que ele mostra, e é por ele que
        # a linha do tempo guarda a imagem: a posição na tira muda de
        # significado a cada zoom, o instante não (ver ``timeline._Strip``).
        self._timeline.set_thumb(
            clip_id,
            frame.seconds,
            image_from_frame(frame.data, frame.width, frame.height),
        )

    def _request_wave(self, clip: Clip, tools: FFmpegTools) -> None:
        begin, finish = self._strip_window(clip)
        width = int(min(_WAVE_MAX_WIDTH, max(80, self._clip_pixels(clip))))
        key = (self._generation, clip.media.path, begin, finish, width, self._colors["accent"])
        if self._wave_requests.get(clip.clip_id) == key:
            return
        self._cancel_strip(clip.clip_id)
        token = next(self._tokens)
        self._strip_tokens[clip.clip_id] = token
        self._wave_requests[clip.clip_id] = key
        worker = self._runtime.waveform_worker(
            clip.media.path,
            begin,
            max(0.05, finish - begin),
            (width, AUDIO_TRACK_HEIGHT - 14),
            self._colors["accent"],
            tools,
            token,
        )
        worker.signals.waveform.connect(
            lambda tok, png, c=clip.clip_id, a=begin, b=finish: self._on_wave(
                tok, c, a, b, png
            )
        )
        self._strip_workers[clip.clip_id] = worker
        worker.signals.done.connect(lambda cid=clip.clip_id, tok=token: self._on_strip_done(cid, tok))
        self._background.start(worker, worker.signals.done)

    def _on_strip_done(self, clip_id: int, token: int) -> None:
        if self._strip_tokens.get(clip_id) != token:
            return
        self._strip_workers.pop(clip_id, None)
        self._wave_requests.pop(clip_id, None)

    def _on_wave(
        self, token: int, clip_id: int, begin: float, finish: float, png: bytes
    ) -> None:
        if self._strip_tokens.get(clip_id) != token:
            return
        image = QImage()
        if image.loadFromData(png, "PNG"):
            self._timeline.set_wave(clip_id, begin, finish, image)

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------

    def _refresh_clip_actions(self) -> None:
        """Estado dos atalhos que dependem do bloco **e do cursor**.

        Separado de :meth:`_refresh_controls` porque o cursor anda a cada
        movimento do mouse: refazer a barra inteira a cada passo custaria muito
        mais do que estes dois botões valem. Eles seguem exatamente o que o menu
        do botão direito oferece — dividir só onde o cursor está dentro do bloco,
        excluir só com bloco escolhido —, porque um botão que não faz nada é pior
        que botão nenhum.
        """
        clip = self._timeline.selected_clip
        self._split_button.setEnabled(
            clip is not None
            and not clip.is_transition
            and clip.contains(self._position)
        )
        self._trim_left_button.setEnabled(self._can_trim(clip, "inicio"))
        self._trim_right_button.setEnabled(self._can_trim(clip, "fim"))
        self._delete_button.setEnabled(clip is not None)

    def _on_scrub(self, seconds: float) -> None:
        self._stop_playback()
        self._timeline.set_position(seconds)
        self._request_frame()
        self._update_time_labels()
        self._refresh_clip_actions()

    def _seek_to(self, seconds: float) -> None:
        if self._project.is_empty:
            return
        self._end_edit_groups()
        self._stop_playback()
        self._timeline.set_position(seconds)
        self._request_frame()
        self._update_time_labels()
        self._refresh_clip_actions()

    def _scrub_to(self, seconds: float) -> None:
        self._resume_wanted = self._resume_wanted or self._playing
        self._seek_to(seconds)

    def _resume_after_scrub(self) -> None:
        if self._resume_wanted:
            self._resume_wanted = False
            self._start_playback(self._position)

    def _nudge(self, seconds: float) -> None:
        self._seek_to(self._position + seconds)

    def _step_frame(self, direction: int) -> None:
        self._seek_to(self._position + direction * frame_step(self._fps))

    def _jump_keyframe(self, direction: int) -> None:
        from videomanager.domain.timing import timeline_time
        clip = self._keyframe_clip()
        if clip is None:
            return
        times = tuple(timeline_time(t, clip.start, clip.in_point, clip.speed)
                      for t in self._keyframes_for(clip)
                      if clip.in_point <= t < clip.out_point)
        if direction < 0:
            target = keyframe_at_or_before(
                times, self._position - frame_step(self._fps)
            )
        else:
            target = keyframe_after(times, self._position)
        if target is not None:
            self._seek_to(target)

    def _update_time_labels(self) -> None:
        curr = format_timecode(self._position, milliseconds=False)
        visible_dur = self._project.export_duration if hasattr(self, "_project") else self._duration
        tot = format_timecode(visible_dur, milliseconds=False)
        self._time_label.setText(
            strings.EDIT_POSITION.format(current=curr, total=tot)
        )
        self._time_label.setToolTip(
            f"{format_timecode(self._position)}  /  {format_timecode(visible_dur)}"
        )
        self._frame_label.setText(
            strings.EDIT_FRAME_NUMBER.format(index=frame_index(self._position, self._fps))
        )
        self._update_preview_overlay_clips()
        if hasattr(self, "_properties_widget"):
            self._properties_widget.set_playhead_position(self._position)
        self._sync_fullscreen()

    def _lock_readouts(self) -> None:
        """Fixa a largura dos números pelo maior valor deste projeto.

        Em tipo proporcional o "1" é mais estreito que o "8": sem largura fixa,
        a barra de transporte inteira treme a cada quadro.
        """
        visible_dur = self._project.export_duration if hasattr(self, "_project") else self._duration
        biggest = format_timecode(max(visible_dur, 3600.0), milliseconds=False)
        text = strings.EDIT_POSITION.format(current=biggest, total=biggest)
        self._time_label.setFixedWidth(
            QFontMetrics(self._time_label.font()).horizontalAdvance(text) + 12
        )
        max_idx = max(99999, frame_index(visible_dur, self._fps))
        frames = strings.EDIT_FRAME_NUMBER.format(index=max_idx)
        self._frame_label.setFixedWidth(
            QFontMetrics(self._frame_label.font()).horizontalAdvance(frames) + 12
        )

    # ------------------------------------------------------------------
    # Som e reprodução
    # ------------------------------------------------------------------

    def _on_volume(self, value: int) -> None:
        self._audio.set_volume(value)
        self._settings.preview_volume = value
        self._refresh_volume_label()
        self._schedule_prefs_save()

    def _on_mute(self, muted: bool) -> None:
        self._audio.set_muted(muted)
        self._settings.preview_muted = muted
        self._refresh_volume_label()
        self._schedule_prefs_save()

    def _refresh_volume_label(self) -> None:
        silent = self._mute.isChecked() or self._volume.value() == 0
        self._mute.setText(strings.EDIT_MUTED if silent else strings.EDIT_SOUND)
        self._mute.setToolTip(
            strings.EDIT_UNMUTE if self._mute.isChecked() else strings.EDIT_MUTE
        )

    def _schedule_prefs_save(self) -> None:
        """Grava as preferências depois que o ajuste parar.

        O volume muda a cada pixel de arrasto — e em dois lugares, aqui e na
        tela cheia. Gravar em cada passo escreveria o arquivo dezenas de vezes
        por segundo; esperar o controle parar grava uma vez só, e continua
        gravando mesmo quando o ajuste veio da outra tela.
        """
        self._prefs_timer.start()

    def _save_audio_prefs(self) -> None:
        try:
            self._runtime.save_settings(self._settings)
        except OSError:
            # Perder a preferência de volume é um incômodo; interromper a
            # edição por causa dela seria um defeito.
            pass

    def _toggle_play(self) -> None:
        if not self._playable:
            return
        if self._playing:
            self._stop_playback()
            return
        self._start_playback(self._position)

    def _start_playback(self, seconds: float) -> None:
        tools = self._ensure_tools()
        if tools is None or self._project.is_empty:
            return
        self._end_edit_groups()
        self._invalidate_interaction()
        if seconds >= self._duration - frame_step(self._fps):
            seconds = 0.0
            self._timeline.set_position(0.0)

        # Um pedido de quadro parado pode ter terminado na worker thread e seu
        # sinal ainda estar na fila da interface. Ele não pode cobrir o primeiro
        # quadro do play quando essa fila for processada.
        self._frame_token = next(self._tokens)
        self._playing = True
        self._preview.set_playing(True)
        self._refresh_play_button()
        self._open_stream(seconds)
        self._tick.start()

    def _open_stream(self, seconds: float) -> None:
        """Abre imagem e som da composição corrente, a partir de ``seconds``."""
        tools = self._ensure_tools()
        if tools is None:
            return
        self._live_timer.stop()
        self._playback_project = self._project
        self._pending_audio = None
        self._clock_position = seconds
        self._clock_started = None
        started = self._start_frames(seconds)
        text_assets = self.editor.text_assets(self._project)
        if started is None or started[1]:
            self._clock_started = time.monotonic()
            self._runtime.play_audio(
                self._audio,
                self._project,
                seconds,
                tools,
                text_assets=text_assets,
            )
        else:
            # O caminho sem pré-carga continua correto: som e relógio só
            # começam quando a imagem também pode começar, sem salto inicial.
            self._audio.stop()
            self._pending_audio = (self._project, seconds, tools, text_assets)

    def _restart_stream(self) -> None:
        """Refaz o fluxo com a composição nova, sem sair da reprodução.

        O volume em decibéis, o mudo e a posição dos blocos entram no **grafo do
        ffmpeg**, e o grafo é montado na hora em que o fluxo abre: mexer neles
        com o vídeo tocando não muda o que já está saindo do processo. Sem isto
        era preciso pausar e voltar para ouvir o próprio ajuste — justamente na
        hora em que ele menos serve, porque o que se quer é comparar.
        """
        if not self._playing:
            return
        position = self._position
        if position >= self._duration - frame_step(self._fps):
            self._stop_playback()
            return
        self._open_stream(position)

    def _playback_key(
        self, seconds: float, size: tuple[int, int], fps: float
    ) -> tuple[object, ...]:
        return (id(self._project), round(seconds, 9), size, fps)

    def _cancel_primed_playback(self) -> None:
        worker = self._primed_playback
        self._primed_playback = None
        self._primed_key = None
        self._primed_token = 0
        self._primed_ready = False
        if worker is not None:
            worker.cancel()

    def _prime_playback(self) -> None:
        """Prepara o primeiro quadro enquanto a interface está pausada."""
        if self._closed or self._playing or self._project.is_empty or not self._has_video:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        seconds = self._position
        size = self._preview_size()
        fps = preview_fps(self._fps)
        key = self._playback_key(seconds, size, fps)
        if self._primed_playback is not None and self._primed_key == key:
            return
        self._cancel_primed_playback()
        token = next(self._tokens)
        worker = self._runtime.playback_worker(
            self._project,
            seconds,
            size,
            tools,
            token,
            fps=fps,
            text_assets=self.editor.text_assets(self._project),
            autostart=False,
        )
        worker.signals.frame.connect(self._on_frame)
        worker.signals.primed.connect(self._on_playback_primed)
        if hasattr(worker.signals, "failed"):
            worker.signals.failed.connect(self._on_preview_failed)
        worker.signals.done.connect(
            lambda token=token: self._on_playback_worker_done(token)
        )
        self._primed_playback = worker
        self._primed_key = key
        self._primed_token = token
        self._primed_ready = False
        self._runner.start(worker, worker.signals.done)

    def _on_playback_primed(self, token: int) -> None:
        if token == self._primed_token:
            self._primed_ready = True
        if token != self._play_token or not self._playing:
            return
        pending = self._pending_audio
        if pending is None:
            return
        self._pending_audio = None
        project, seconds, tools, text_assets = pending
        self._clock_position = seconds
        self._clock_started = time.monotonic()
        self._runtime.play_audio(
            self._audio,
            project,
            seconds,
            tools,
            text_assets=text_assets,
        )

    def _on_playback_worker_done(self, token: int) -> None:
        if token == self._primed_token:
            self._primed_playback = None
            self._primed_key = None
            self._primed_token = 0
            self._primed_ready = False
        self._on_playback_done(token)

    def _start_frames(self, seconds: float) -> tuple[int, bool] | None:
        tools = self._ensure_tools()
        if tools is None or not self._has_video:
            return None
        if self._playback is not None:
            self._playback.cancel()
        size = self._preview_size()
        fps = preview_fps(self._fps)
        key = self._playback_key(seconds, size, fps)
        if self._primed_playback is not None and self._primed_key == key:
            worker = self._primed_playback
            token = self._primed_token
            ready = self._primed_ready
            self._primed_playback = None
            self._primed_key = None
            self._primed_token = 0
            self._primed_ready = False
            self._play_token = token
            self._playback = worker
            worker.start_playback()
            return token, ready

        self._cancel_primed_playback()
        self._play_token = next(self._tokens)
        worker = self._runtime.playback_worker(
            self._project, seconds, size, tools, self._play_token, fps=fps,
            text_assets=self.editor.text_assets(self._project),
        )
        worker.signals.frame.connect(self._on_frame)
        worker.signals.primed.connect(self._on_playback_primed)
        if hasattr(worker.signals, "failed"):
            worker.signals.failed.connect(self._on_preview_failed)
        worker.signals.done.connect(
            lambda token=self._play_token: self._on_playback_worker_done(token)
        )
        self._runner.start(worker, worker.signals.done)
        self._playback = worker
        return self._play_token, False

    def _loop_playback(self) -> None:
        self._tick.stop()
        self._live_timer.stop()
        self._audio.stop()
        if self._playback is not None:
            self._playback.cancel()
            self._playback = None
        self._play_token = 0
        self._timeline.set_position(0.0)
        self._update_time_labels()
        self._start_playback(0.0)

    def _on_audio_stopped(self) -> None:
        if not self._playing:
            return
        # O término do som não encerra imagens, vãos ou trilhas mais longas.
        self._clock_position = max(self._position, self._audio.position)
        self._clock_started = time.monotonic()
        self._on_tick()

    def _on_tick(self) -> None:
        if not self._playing:
            return
        now = time.monotonic()
        position = self._position
        if self._audio.playing:
            position = self._audio.position
            self._clock_position, self._clock_started = position, now
            drift = abs(self._shown_frame - position)
            if (self._has_video and drift > _MAX_DRIFT
                    and position - self._resynced_at > _RESYNC_COOLDOWN):
                self._resynced_at = position
                self._start_frames(position)
        elif self._clock_started is not None:
            position = self._clock_position + now - self._clock_started
        self._timeline.set_position(min(self._duration, position))
        self._update_time_labels()
        # Duração é da saída: velocidade de outro clipe não encurta este fim.
        if self._duration > 0 and position >= self._duration - 1e-8:
            if self._loop.isChecked():
                self._loop_playback()
            else:
                self._stop_playback()

    def _on_playback_done(self, token: int) -> None:
        if token != self._play_token or not self._playing:
            return
        self._playback = None
        # O último frame ainda ocupa um intervalo. O relógio conclui esse
        # intervalo e o eventual trecho de áudio posterior ao vídeo.
        self._on_tick()

    def _stop_playback(self) -> None:
        # A imagem pode estar alguns quadros à frente da última atualização do
        # cursor (que chega pelo relógio do áudio a cada 40 ms). Guardar o ponto
        # visível antes de desmontar os fluxos impede o próximo play de reabrir
        # num instante anterior e parecer que o vídeo voltou.
        visible_position = self._shown_frame if self._has_video else self._position
        self._tick.stop()
        self._live_timer.stop()
        self._pending_audio = None
        self._clock_started = None
        self._audio.stop()
        if self._playback is not None:
            self._playback.cancel()
            self._playback = None
        self._preview.set_playing(False)
        if self._playing:
            self._playing = False
            self._play_token = 0
            self._timeline.set_position(visible_position, follow=False)
            self._update_time_labels()
            has_overlays = any(
                t.visible and t.kind is TrackKind.ADDITIONAL and any(
                    c.overlay_type != "filter"
                    and (c.overlay_type in ("image", "text") or c.is_image)
                    and c.contains(visible_position)
                    and not c.chromakey_enabled
                    for c in t.clips
                )
                for t in self._project.tracks
            )
            self._frame_revision += 1
            self._frame_token = next(self._tokens)
            if has_overlays:
                self._rendered = None
                self._request_frame(force=True)
            else:
                self._wanted = None
                self._rendered = visible_position
                self._prime_playback()
            self._update_preview_overlay_clips()
            self._prepare_interaction()
        self._refresh_play_button()

    def _refresh_play_button(self) -> None:
        self._play_button.setEnabled(self._playable)
        self._play_button.setText("❚❚" if self._playing else "▶")
        if not self._playable:
            self._play_button.setToolTip(strings.EDIT_NO_PLAYBACK)
            return
        label = strings.EDIT_PAUSE if self._playing else strings.EDIT_PLAY
        self._play_button.setToolTip(f"{label}  (Espaço)")

    # ------------------------------------------------------------------
    # Tela cheia
    # ------------------------------------------------------------------

    def _toggle_fullscreen(self) -> None:
        self._end_edit_groups()
        if self._on_fullscreen:
            self._fullscreen.close()
            return
        if not self._has_video:
            return
        if self._fullscreen is None:
            self._fullscreen = FullscreenPreview(self)
            self._fullscreen.play_toggled.connect(self._toggle_play)
            self._fullscreen.stepped.connect(self._step_frame)
            self._fullscreen.seeked.connect(self._scrub_to)
            self._fullscreen.seek_finished.connect(self._resume_after_scrub)
            self._fullscreen.volume_changed.connect(self._volume.setValue)
            self._fullscreen.mute_toggled.connect(self._mute.setChecked)
            self._fullscreen.closed.connect(self._restart_frames)
            self._fullscreen.resized.connect(self._on_fullscreen_resized)

        self._fullscreen.set_audio(
            self._has_sound, self._volume.value(), self._mute.isChecked()
        )
        self._fullscreen.showFullScreen()
        self._fullscreen.activateWindow()
        self._fullscreen.setFocus()
        self._sync_fullscreen()
        self._restart_frames()

    def _on_fullscreen_resized(self, size: QSize) -> None:
        if self._on_fullscreen:
            self._restart_frames()

    def _restart_frames(self) -> None:
        if self._playing:
            self._start_frames(self._position)
        else:
            self._request_frame(force=True)

    def _sync_fullscreen(self) -> None:
        if self._on_fullscreen:
            dur = self._project.export_duration if hasattr(self, "_project") else self._duration
            self._fullscreen.set_state(self._position, dur, self._playing)

    # ------------------------------------------------------------------
    # Zoom e rolagem
    # ------------------------------------------------------------------

    def _zoom(self, factor: float) -> None:
        self._timeline.zoom(factor, self._position)

    def _sync_scrollbar(self) -> None:
        """Põe a barra de navegação de acordo com a janela visível.

        Duas coisas aqui já foram defeito, e as duas apareciam só com zoom.

        **O limite é o da própria linha do tempo** (``max_view_start``), e não
        "o conteúdo encostado na borda direita". A roda do mouse podia levar a
        vista mais para a direita do que a barra alcançava — medido com zoom de
        6,6×, 0,9 s a mais —, e o vazio depois do último bloco, que é onde se
        solta um bloco para o fim, não tinha como ser alcançado por ela.

        **O passo simples é uma fatia da janela**, e não o padrão do Qt. A escala
        é em milissegundos, então o passo padrão (1) movia a vista **um
        milissegundo** por clique de seta ou de roda: a barra parecia travada.
        """
        start, end = self._timeline.view
        span = end - start
        ceiling = self._timeline.max_view_start(span)
        self._syncing = True
        try:
            self._scroll.setPageStep(round(span * 1000))
            self._scroll.setSingleStep(max(1, round(span * 1000 / _SCROLL_STEPS)))
            # Arredondar, e não truncar: truncando, o último milissegundo da
            # edição ficava fora do alcance da barra.
            self._scroll.setRange(0, max(0, round(ceiling * 1000)))
            self._scroll.setValue(round(start * 1000))
            self._scroll.setEnabled(ceiling > 0)
        finally:
            self._syncing = False

    def _on_scrollbar(self, value: int) -> None:
        if self._syncing:
            return
        start, end = self._timeline.view
        self._timeline.set_view(value / 1000, value / 1000 + (end - start))

    # ------------------------------------------------------------------
    # Exportação
    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        self._timeline.update()
        self._refresh_plan()
        # O aviso aparece e some com a escolha, e com ele a altura preferida do
        # painel: sem avisar, a linha de baixo nasce cortada (ver
        # ``MainWindow._balance_panes``).
        self.changed.emit()

    def _fast_available(self) -> bool:
        """O corte sem recodificar só sobrevive enquanto a edição for um recorte.

        Um arquivo, blocos na ordem, nenhum volume mexido, nada sobreposto: é o
        caso em que copiar os dados ainda produz o resultado pedido. Qualquer
        montagem além disso precisa de composição, e composição recodifica.
        """
        segments = simple_trim(self._project)
        return bool(segments) and len(segments) == 1

    def _trim_target(self) -> TrimTarget | None:
        segments = simple_trim(self._project)
        if not segments or len(segments) != 1:
            return None
        clip = self._project.clips[0]
        anchor = keyframe_at_or_before(self._keyframes_for(clip), segments[0].start)
        return TrimTarget(
            segments=segments,
            container=clip.media.path.suffix.lstrip(".").lower() or "mp4",
            mode=CutMode.FAST,
            anchor=anchor,
            hardware=self._settings.hardware_encoder,
            copy_metadata=False,
        )

    def _main_clip(self) -> Clip | None:
        """O bloco que dá nome e formato à saída.

        É o primeiro da trilha de vídeo **mais baixa** — a principal, onde fica
        o material de base. Pegar o primeiro bloco de qualquer trilha faria uma
        montagem inteira herdar o nome de uma foto sobreposta.
        """
        for track in reversed(self._project.video_tracks):
            if track.clips:
                return track.sorted_clips()[0]
        clips = self._project.clips
        return clips[0] if clips else None

    def _container(self) -> str:
        video = self._main_clip()
        if video is None or not video.media.has_video:
            return "m4a"
        suffix = video.media.path.suffix.lstrip(".").lower()
        # Uma imagem não dá container de saída: um projeto que começa por foto
        # sai em mp4, que é o que qualquer aparelho abre.
        return "mp4" if not suffix or video.media.kind is MediaKind.IMAGE else suffix

    def _refresh_plan(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Sincronização geral
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Encerra o que a aba deixou rodando fora do processo.

        A prévia mantém até dois ffmpeg vivos — o fluxo de quadros e o da
        mixagem —, e eles não morrem só porque a janela fechou: ficariam
        consumindo CPU até perceberem o cano fechado. Fechar a janela é o
        último momento em que alguém pode mandá-los parar.

        **O trabalho de fundo entra na conta.** O destrutor do ``QThreadPool``
        chama ``waitForDone()`` sem prazo, e onda e keyframes esperam ffmpeg de
        120 s e 180 s: enquanto eles não eram cancelados aqui, fechar a janela
        logo depois de importar um arquivo longo deixava o processo pendurado
        até o prazo acabar, sem janela e sem explicação.
        """
        self._closed = True
        self.commit_pending_edits()
        self._stop_playback()
        self._cancel_primed_playback()
        for clip_id in list(self._strip_workers):
            self._cancel_strip(clip_id)
        self._project_actions.cancel_pending()
        self._background.cancel_all()
        self._runner.cancel_all()
        if self._fullscreen is not None:
            self._fullscreen.close()
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.FocusOut and obj is getattr(self, "_text_input", None):
            self._end_typing_session()
        if event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                if hasattr(self, "_timeline") and self._timeline.selected_clip is not None:
                    if isinstance(obj, QWidget) and (obj == self or self.isAncestorOf(obj)):
                        # Se o clique for na área das trilhas, não desseleciona
                        if (
                            obj == self._timeline
                            or self._timeline.isAncestorOf(obj)
                            or (hasattr(self, "_timeline_area") and (obj == self._timeline_area or self._timeline_area.isAncestorOf(obj)))
                        ):
                            return super().eventFilter(obj, event)

                        # Se for no monitor de prévia, a própria _Preview gerencia
                        if hasattr(self, "_preview") and obj == self._preview:
                            return super().eventFilter(obj, event)

                        # Se o clique for no painel lateral de ferramentas / propriedades, não desseleciona
                        if (
                            (hasattr(self, "_extras_tabs") and (obj == self._extras_tabs or self._extras_tabs.isAncestorOf(obj)))
                            or (hasattr(self, "_extras_box") and (obj == self._extras_box or self._extras_box.isAncestorOf(obj)))
                        ):
                            return super().eventFilter(obj, event)

                        # Se for um controle interativo de propriedades (botão, spinbox, tab, input, slider, etc.)
                        if isinstance(obj, (QAbstractButton, QAbstractSpinBox, QLineEdit, QComboBox, QSlider, QTabBar)):
                            return super().eventFilter(obj, event)

                        # Clique fora das trilhas e de controles interativos: desseleciona
                        self._timeline.select(-1)
        return super().eventFilter(obj, event)

    def apply_settings(self, settings: Settings) -> None:
        """Adota as preferências recém-salvas pelo diálogo de configurações."""
        self._settings = settings
        self._audio.set_volume(settings.preview_volume)
        self._audio.set_muted(settings.preview_muted)
        self._volume.setValue(settings.preview_volume)
        self._mute.setChecked(settings.preview_muted)

    def _refresh_all(self) -> None:
        self._timeline.set_project(self._project)
        self._refresh_controls()
        self._refresh_clip_fields()

    def _refresh_controls(self) -> None:
        loaded = not self._project.is_empty
        clip = self._timeline.selected_clip
        for widget in (*self._buttons, self._scroll):
            widget.setEnabled(loaded)
        self._insert.setEnabled(bool(self._pool) and self._media_list.currentRow() >= 0)
        self._export_button.setEnabled(loaded)
        # Volume só onde há som para ajustar. Num bloco cujo áudio foi
        # separado ele fica desligado de propósito: o som agora é o do outro
        # bloco, e é lá que ele se ajusta — oferecer o controle aqui seria
        # oferecer um botão que não faz nada. O mudo saiu da barra e vive no
        # menu do botão direito, que só o oferece quando ele tem o que calar.
        adjustable = clip is not None and clip.can_adjust_sound
        self._volume_btn.setEnabled(adjustable)
        self._volume_btn.setToolTip(
            strings.EDIT_GAIN_DETACHED
            if clip is not None and clip.detached
            else strings.EDIT_GAIN_TIP
        )
        self._speed_btn.setEnabled(clip is not None and clip.overlay_type != "filter")
        self._speed_btn.setToolTip(strings.EDIT_SPEED_TIP)

        self._refresh_clip_actions()

        for button in (self._prev_key, self._next_key):
            button.setEnabled(bool(self._keyframes_for(self._keyframe_clip())))
        self._refresh_play_button()
        for widget in (self._mute, self._volume):
            widget.setEnabled(self._audio.available)
        self._fullscreen_button.setEnabled(self._has_video)
        self._collapse.setEnabled(True)

        self._count_label.setText(
            strings.EDIT_TRACK_COUNT.format(
                tracks=len(self._project.tracks),
                clips=len(self._project.clips),
                duration=format_span(self._duration),
            )
            if loaded
            else ""
        )
        self._slideshow_button.setEnabled(slideshow_canvas(self._project) is not None)
        self._refresh_canvas_controls()
        self._lock_readouts()
        self._update_time_labels()
        self._sync_scrollbar()
        self._scan_keyframes()

    def _keyframes_for(self, clip: Clip | None) -> tuple[float, ...]:
        return self._keyframes if clip and clip.media and clip.media.path == self._keyframe_source else ()

    def _keyframe_clip(self) -> Clip | None:
        clip = self._timeline.selected_clip or self._main_clip()
        return clip if clip and clip.media and clip.media.kind is MediaKind.VIDEO and not clip.is_transition else None

    def _scan_keyframes(self) -> None:
        """Mapeia os keyframes da mídia única, quando ainda houver uma só.

        Só o corte rápido usa isso, e ele só existe enquanto a edição for um
        recorte de um arquivo — daí o mapeamento não acontecer numa montagem com
        várias mídias, onde não teria uso.
        """
        clip = self._keyframe_clip()
        source = clip.media.path if clip else None
        if source == self._keyframe_source:
            return
        if self._keyframe_worker is not None:
            self._keyframe_worker.cancel()
            self._keyframe_worker = None
        self._keyframe_token = next(self._tokens)
        self._keyframes = ()
        self._keyframe_source = source
        for button in (self._prev_key, self._next_key):
            button.setEnabled(False)
        if source is None:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        worker = self._runtime.keyframe_worker(source, tools)
        self._keyframe_worker = worker
        token = self._keyframe_token
        worker.signals.keyframes.connect(lambda times, s=source, t=token: self._on_keyframes(times, s, t))
        self._background.start(worker, worker.signals.done)

    def _on_keyframes(self, times: object, source: Path, token: int) -> None:
        if source != self._keyframe_source or token != self._keyframe_token:
            return
        self._keyframe_worker = None
        self._keyframes = tuple(times) if isinstance(times, tuple) else ()
        for button in (self._prev_key, self._next_key):
            button.setEnabled(bool(self._keyframes_for(self._keyframe_clip())))

    # ------------------------------------------------------------------
    # Projeto (Salvar e Carregar)
    # ------------------------------------------------------------------

    @property
    def has_unsaved_changes(self) -> bool:
        return self._session.has_changes

    def new_project(self) -> bool:
        return self._project_actions.new()

    def save_project(self) -> bool:
        self._session.commit_edit()
        self._end_edit_groups()
        return self._project_actions.save()

    def save_project_as(self) -> bool:
        self._session.commit_edit()
        self._end_edit_groups()
        return self._project_actions.save(choose_path=True)

    def open_project(self, path: Path | None = None) -> bool:
        return self._project_actions.open(path)
