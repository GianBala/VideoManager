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
mesmo grafo do ffmpeg que exporta o arquivo (ver ``core/composer``), então
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
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.binaries import FFmpegTools
from ...core.composer import (
    Composition,
    audio_command,
    can_interpolate,
    describe_export,
    frame_command,
    interpolation_bytes,
    playback_command,
    simple_trim,
)
from ...core.converter import LocalMedia, output_path, probe_file
from ...core.errors import VideoManagerError
from ...core.humanize import format_rate, format_size
from ...core.job import Job, JobKind
from ...core.preview import fit_size, preview_fps
from ...core.project import (
    MAX_GAIN_DB,
    MIN_GAIN_DB,
    Clip,
    MediaKind,
    MediaRef,
    Project,
    TrackKind,
    accepts,
    auto_canvas,
    media_ref,
    new_project,
    next_clip_id,
)
from ...core.settings import Settings
from ...core.trimmer import (
    MIN_SEGMENT,
    CutMode,
    TrimTarget,
    format_span,
    format_timecode,
    frame_index,
    frame_step,
    keyframe_after,
    keyframe_at_or_before,
    parse_timecode,
)
from ...workers.preview_worker import (
    FilmstripWorker,
    FrameWorker,
    KeyframeWorker,
    PlaybackWorker,
    WaveformWorker,
)
from ...workers.runner import WorkerRunner
from .. import icons, strings
from ..audio_preview import AudioPreview
from ..fullscreen_preview import FullscreenPreview
from ..theme import palette
from .timeline import (
    AUDIO_TRACK_HEIGHT,
    FILM_CELL_WIDTH,
    VIDEO_TRACK_HEIGHT,
    Timeline,
    image_from_frame,
    pixmap_from_frame,
)

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
    (3840, 2160), (2560, 1440), (1920, 1080), (1280, 720), (854, 480),
    (1080, 1920), (720, 1280), (1080, 1080),
)
_RATE_PRESETS = (24.0, 25.0, 30.0, 50.0, 60.0)

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


def _wrapping_label(role: str) -> QLabel:
    """Rótulo que quebra linha **e** cobra do layout a altura que isso exige.

    Um ``QLabel`` com ``wordWrap`` sabe calcular a própria altura, mas o layout
    só pergunta quando a política de tamanho declara que a altura depende da
    largura. Sem a declaração, o texto do plano quebrava em duas linhas e a
    caixa continuava dimensionada para uma: a segunda linha — e o aviso logo
    abaixo — nasciam cortados pela borda da janela.
    """
    label = QLabel("")
    label.setProperty("role", role)
    label.setWordWrap(True)
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


def _index_of(box: QComboBox, value: object) -> int:
    """Posição do item que guarda este dado, ou -1.

    Não é o ``findData`` do Qt: ele compara os dados como ``QVariant``, e dois
    pares ``(1280, 720)`` iguais em Python não são o mesmo objeto — a busca
    devolvia -1 e a escolha de tela simplesmente não acontecia, enquanto a de
    taxa (um número) funcionava. Aqui a comparação é a do Python.
    """
    return next((i for i in range(box.count()) if box.itemData(i) == value), -1)


class _Preview(QLabel):
    """Tela da prévia: mantém o quadro centralizado e o fundo preto."""

    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(_PREVIEW_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: #000000; border-radius: 8px;")
        self.setText(strings.EDIT_EMPTY)
        self.setProperty("role", "dim")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, self.minimumHeight())

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()


class EditPanel(QWidget):
    """Monta um projeto de várias trilhas e entrega a exportação para a fila."""

    jobs_ready = Signal(list)  # list[Job]
    changed = Signal()

    def __init__(
        self,
        settings: Settings,
        ensure_tools: Callable[[], FFmpegTools | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
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

        self._project = new_project()
        self._pool: list[MediaRef] = []
        self._probed: dict[Path, LocalMedia] = {}
        self._history: list[Project] = []
        self._future: list[Project] = []
        self._clipboard: Clip | None = None
        self._keyframes: tuple[float, ...] = ()
        self._keyframe_source: Path | None = None
        # Tela pedida, ou ``None`` para seguir o material. Mora aqui, e não no
        # projeto, porque é preferência de saída e não parte da montagem — ver
        # :meth:`_sync_canvas`.
        self._canvas_choice: tuple[int, int] | None = None
        self._rate_choice: float | None = None

        self._tokens = itertools.count(1)
        self._frame_token = 0
        self._play_token = 0
        self._strip_tokens: dict[int, int] = {}
        self._strip_workers: dict[int, FilmstripWorker] = {}
        self._frame_busy = False
        self._wanted: float | None = None
        self._rendered: float | None = None
        self._playing = False
        self._playback: PlaybackWorker | None = None
        self._fullscreen: FullscreenPreview | None = None
        self._syncing = False
        self._shown_frame = 0.0
        self._resynced_at = 0.0
        self._resume_wanted = False
        self._collapsed = False
        # Bloco cujo volume está sendo ajustado agora: enquanto for o mesmo, os
        # passos entram num desfazer só (ver :meth:`_on_gain`).
        self._gain_session = -1

        self._audio = AudioPreview(self)
        self._audio.stopped.connect(self._stop_playback)
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

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addWidget(self._build_source_row())

        # Divisor arrastável entre a imagem e as trilhas, em vez de uma divisão
        # fixa: quanto de cada uma se quer à vista muda a cada momento da
        # edição — enquadrando um corte, a imagem; montando a sequência, as
        # trilhas. O botão de retrair continua existindo como atalho para o
        # extremo mais pedido.
        self._split_view = QSplitter(Qt.Orientation.Vertical)
        self._split_view.setChildrenCollapsible(False)
        self._player_box = self._build_player()
        self._split_view.addWidget(self._player_box)
        self._timeline_box = self._build_timeline_area()
        self._split_view.addWidget(self._timeline_box)
        self._split_view.setStretchFactor(0, 1)
        self._split_view.setStretchFactor(1, 0)
        self._layout.addWidget(self._split_view, 1)

        self._layout.addWidget(self._build_export_row())

    def _build_source_row(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._import = QPushButton(strings.EDIT_IMPORT)
        self._import.setToolTip(strings.EDIT_IMPORT_TIP)
        self._import.clicked.connect(self._choose_files)
        row.addWidget(self._import)

        self._pool_box = QComboBox()
        self._pool_box.setMinimumWidth(260)
        self._pool_box.setToolTip(strings.EDIT_POOL_TIP)
        row.addWidget(self._pool_box, 1)

        self._insert = QPushButton(strings.EDIT_INSERT)
        self._insert.setToolTip(strings.EDIT_INSERT_TIP)
        self._insert.clicked.connect(self._insert_selected_media)
        row.addWidget(self._insert)

        self._collapse = QPushButton(strings.EDIT_COLLAPSE)
        self._collapse.setToolTip(strings.EDIT_COLLAPSE_TIP)
        self._collapse.clicked.connect(self._toggle_collapsed)
        row.addWidget(self._collapse)

        self._fullscreen_button = QPushButton(strings.EDIT_FULLSCREEN)
        self._fullscreen_button.setToolTip(strings.EDIT_FULLSCREEN_TIP)
        self._fullscreen_button.clicked.connect(self._toggle_fullscreen)
        row.addWidget(self._fullscreen_button)
        return box

    def _build_player(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self._preview = _Preview()
        self._preview.double_clicked.connect(self._toggle_fullscreen)
        column.addWidget(self._preview, 1)
        column.addWidget(self._build_transport())
        return box

    def _build_transport(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._time_label = QLabel(
            strings.EDIT_POSITION.format(
                current=format_timecode(0), total=format_timecode(0)
            )
        )
        self._time_label.setFont(mono)
        self._frame_label = QLabel("")
        self._frame_label.setFont(mono)
        self._frame_label.setProperty("role", "dim")
        row.addWidget(self._time_label)
        row.addWidget(self._frame_label)
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
            button.setFixedWidth(56)
            button.clicked.connect(slot)
            row.addWidget(button)
            self._buttons.append(button)
        self._play_button = self._buttons[3]
        self._play_button.setProperty("role", "primary")

        row.addStretch(1)
        self._prev_key = QPushButton(strings.EDIT_PREV_KEY_SHORT)
        self._prev_key.setToolTip(strings.EDIT_PREV_KEY)
        self._prev_key.clicked.connect(lambda: self._jump_keyframe(-1))
        self._next_key = QPushButton(strings.EDIT_NEXT_KEY_SHORT)
        self._next_key.setToolTip(strings.EDIT_NEXT_KEY)
        self._next_key.clicked.connect(lambda: self._jump_keyframe(+1))
        row.addWidget(self._prev_key)
        row.addWidget(self._next_key)
        self._buttons += [self._prev_key, self._next_key]

        row.addSpacing(12)
        row.addWidget(self._build_volume())
        return box

    def _build_volume(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._mute = QPushButton()
        self._mute.setCheckable(True)
        self._mute.setChecked(self._settings.preview_muted)
        self._mute.setFixedWidth(46)
        self._mute.toggled.connect(self._on_mute)
        row.addWidget(self._mute)

        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(self._settings.preview_volume)
        self._volume.setFixedWidth(110)
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
        self._timeline.edit_started.connect(self._remember)
        self._timeline.edit_finished.connect(self._on_edit_finished)
        self._timeline.clip_moved.connect(self._on_clip_moved)
        self._timeline.clip_resized.connect(self._on_clip_resized)
        self._timeline.clip_selected.connect(self._on_clip_selected)
        self._timeline.track_mute_clicked.connect(self._toggle_track_mute)
        self._timeline.menu_requested.connect(self._show_menu)
        self._timeline.view_changed.connect(self._on_view_changed)
        self._timeline_area.setWidget(self._timeline)
        column.addWidget(self._timeline_area)

        self._scroll = QScrollBar(Qt.Orientation.Horizontal)
        self._scroll.valueChanged.connect(self._on_scrollbar)
        column.addWidget(self._scroll)

        column.addLayout(self._build_clip_row())
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

        row.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setProperty("role", "dim")
        row.addWidget(self._count_label)
        row.addStretch(1)
        hint = QLabel(strings.EDIT_MENU_HINT)
        hint.setProperty("role", "dim")
        row.addWidget(hint)
        row.addSpacing(10)

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

    def _build_clip_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._start_field = self._timecode_field()
        self._end_field = self._timecode_field()
        self._start_field.editingFinished.connect(lambda: self._apply_field("inicio"))
        self._end_field.editingFinished.connect(lambda: self._apply_field("fim"))

        row.addWidget(QLabel(strings.EDIT_CLIP_START))
        row.addWidget(self._start_field)
        row.addWidget(QLabel(strings.EDIT_CLIP_END))
        row.addWidget(self._end_field)
        row.addSpacing(10)

        row.addWidget(QLabel(strings.EDIT_GAIN))
        self._gain = QDoubleSpinBox()
        self._gain.setRange(MIN_GAIN_DB, MAX_GAIN_DB)
        self._gain.setSingleStep(0.5)
        self._gain.setDecimals(1)
        self._gain.setSuffix(" dB")
        self._gain.setFixedWidth(96)
        self._gain.setToolTip(strings.EDIT_GAIN_TIP)
        self._gain.valueChanged.connect(self._on_gain)
        self._gain.editingFinished.connect(self._end_gain_session)
        row.addWidget(self._gain)

        self._clip_mute = QCheckBox(strings.EDIT_CLIP_MUTE)
        self._clip_mute.setToolTip(strings.EDIT_CLIP_MUTE_TIP)
        self._clip_mute.toggled.connect(self._on_clip_mute)
        row.addWidget(self._clip_mute)

        row.addSpacing(10)
        self._clip_label = QLabel(strings.EDIT_CLIP_NONE)
        self._clip_label.setProperty("role", "dim")
        row.addWidget(self._clip_label, 1)
        return row

    @staticmethod
    def _timecode_field() -> QLineEdit:
        field = QLineEdit()
        field.setToolTip(strings.EDIT_FIELD_TIP)
        field.setFixedWidth(110)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return field

    def _build_export_row(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        # Altura natural, nunca espremida: sem isto o layout repartia a falta de
        # espaço entre a prévia e esta caixa, e o aviso da última linha nascia
        # cortado pela borda da janela. Aqui quem cede pixels é a prévia — ela é
        # a única coisa da aba que rende com espaço sobrando.
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        choices = QHBoxLayout()
        choices.setContentsMargins(0, 0, 0, 0)
        choices.setSpacing(14)
        choices.addWidget(QLabel(strings.EDIT_CUT_LABEL))
        self._fast = QCheckBox(strings.EDIT_MODE_FAST)
        self._fast.setToolTip(strings.EDIT_MODE_TIP)
        self._fast.toggled.connect(self._on_mode_changed)
        choices.addWidget(self._fast)
        choices.addStretch(1)
        column.addLayout(choices)

        # A tela fica numa linha própria, logo acima do texto que anuncia o
        # resultado: é lendo "1920×1080 · 30 fps" que se descobre querer outra
        # coisa. Espremer isto na linha do corte passava da largura da janela.
        canvas = QHBoxLayout()
        canvas.setContentsMargins(0, 0, 0, 0)
        canvas.setSpacing(8)
        canvas.addWidget(QLabel(strings.EDIT_CANVAS))
        self._canvas_box = QComboBox()
        self._canvas_box.setToolTip(strings.EDIT_CANVAS_TIP)
        self._canvas_box.setMinimumWidth(210)
        self._canvas_box.currentIndexChanged.connect(self._on_canvas_choice)
        canvas.addWidget(self._canvas_box)
        canvas.addSpacing(10)
        canvas.addWidget(QLabel(strings.EDIT_CANVAS_RATE))
        self._rate_box = QComboBox()
        self._rate_box.setToolTip(strings.EDIT_CANVAS_RATE_TIP)
        self._rate_box.setMinimumWidth(130)
        self._rate_box.currentIndexChanged.connect(self._on_rate_choice)
        canvas.addWidget(self._rate_box)
        canvas.addSpacing(10)
        self._interpolate = QCheckBox(strings.EDIT_INTERPOLATE)
        self._interpolate.toggled.connect(self._on_mode_changed)
        canvas.addWidget(self._interpolate)
        canvas.addStretch(1)
        column.addLayout(canvas)

        # O plano e o aviso ocupam a largura inteira, em linhas próprias. Ao
        # lado do botão eles ficavam numa coluna de 732 px e quebravam em duas
        # linhas — e a altura dessa quebra não atravessa uma linha horizontal
        # (``heightForWidth`` para no ``QHBoxLayout``), então a caixa continuava
        # dimensionada para uma linha e a última nascia cortada. Com a largura
        # toda, o texto cabe numa linha e a conta fecha sozinha.
        self._plan = _wrapping_label("dim")
        column.addWidget(self._plan)
        self._warning = _wrapping_label("warn")
        self._warning.setVisible(False)
        column.addWidget(self._warning)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch(1)

        self._same_folder = QCheckBox(strings.EDIT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        actions.addWidget(self._same_folder)
        self._export = QPushButton(strings.EDIT_EXPORT)
        self._export.setProperty("role", "primary")
        self._export.clicked.connect(self._enqueue)
        actions.addWidget(self._export)
        column.addLayout(actions)
        return box

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
            ("Ctrl+C", self._copy_clip),
            ("Ctrl+V", self._paste_clip),
            (",", lambda: self._step_frame(-1)),
            (".", lambda: self._step_frame(+1)),
            ("Ctrl+Z", self._undo_edit),
            ("Ctrl+Shift+Z", self._redo_edit),
            ("Ctrl+Y", self._redo_edit),
            ("F", self._toggle_fullscreen),
            ("F11", self._toggle_fullscreen),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda slot=slot: self._dispatch(slot))

    def _dispatch(self, slot: Callable[[], None]) -> None:
        """Filtra os atalhos de uma tecla antes de deixá-los agir.

        Sem a primeira guarda, digitar um timecode dispararia as ações letra a
        letra. A segunda existe porque a janela de tela cheia é filha deste
        painel e o alcance do atalho a acompanha: sem ela, um Espaço lá seria
        contado duas vezes.
        """
        # Campo de texto, número ou lista: todos usam teclas que também são
        # atalhos daqui — o espaço abre a lista de mídias, as letras entram no
        # timecode.
        if isinstance(
            QApplication.focusWidget(), (QLineEdit, QDoubleSpinBox, QComboBox)
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
        return not self._project.is_empty

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

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, strings.EDIT_IMPORT, str(Path.home()), strings.EDIT_FILE_FILTER
        )
        if paths:
            self.import_files([Path(p) for p in paths], insert=True)

    def import_files(self, paths: list[Path], *, insert: bool = False) -> None:
        """Inspeciona os arquivos, guarda no acervo e opcionalmente insere."""
        tools = self._ensure_tools()
        if tools is None:
            return

        rejected: list[str] = []
        added: list[MediaRef] = []
        for path in paths:
            if any(ref.path == path for ref in self._pool):
                added.append(next(r for r in self._pool if r.path == path))
                continue
            try:
                local = probe_file(path, tools)
            except VideoManagerError as exc:
                rejected.append(f"{path.name}: {exc}")
                continue
            reference = media_ref(local)
            if reference.kind is not MediaKind.IMAGE and not reference.duration:
                rejected.append(f"{path.name}: não informa duração")
                continue
            self._probed[path] = local
            self._pool.append(reference)
            added.append(reference)

        if rejected:
            QMessageBox.warning(
                self,
                strings.DIALOG_WARNING_TITLE,
                strings.EDIT_IMPORT_REJECTED + "\n\n" + "\n".join(rejected),
            )
        if not added:
            return

        self._refresh_pool()
        self._refresh_canvas_controls()
        self._pool_box.setCurrentIndex(self._pool.index(added[-1]))
        if insert:
            self._remember()
            for reference in added:
                self._place(reference)
            self._after_edit(refit=True)

    def _refresh_pool(self) -> None:
        self._syncing = True
        try:
            current = self._pool_box.currentIndex()
            self._pool_box.clear()
            for reference in self._pool:
                self._pool_box.addItem(reference.label)
            self._pool_box.setCurrentIndex(min(max(0, current), len(self._pool) - 1))
        finally:
            self._syncing = False

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
            kind = TrackKind.VIDEO if reference.has_video else TrackKind.AUDIO
            self._project = self._project.with_track(kind)
            index = self._project.track_index(
                self._project.tracks[0 if kind is TrackKind.VIDEO else -1].track_id
            )
        self._project = self._project.with_clip(index, clip)
        self._timeline.select(clip.clip_id)

    def _free_track(self, clip: Clip) -> int | None:
        for index, track in enumerate(self._project.tracks):
            if not accepts(track.kind, clip):
                continue
            floor, ceiling = track.free_range(clip.start)
            if floor <= clip.start and clip.end <= ceiling:
                return index
        return None

    def _insert_selected_media(self) -> None:
        index = self._pool_box.currentIndex()
        if not 0 <= index < len(self._pool):
            return
        self._remember()
        self._place(self._pool[index])
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
            self._act(menu, f"{strings.EDIT_SPLIT}  (S)", self._split_here,
                      enabled=clip.contains(self._position))
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
            self._act(menu, f"{strings.EDIT_COPY}  (Ctrl+C)", self._copy_clip)
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
        self._act(menu, strings.EDIT_ADD_VIDEO_TRACK_FULL,
                  lambda: self._add_track(TrackKind.VIDEO))
        self._act(menu, strings.EDIT_ADD_AUDIO_TRACK_FULL,
                  lambda: self._add_track(TrackKind.AUDIO))
        return menu

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
        self._history.append(self._project)
        self._future.clear()
        del self._history[:-60]

    def _apply(self, project: Project, *, refit: bool = False) -> None:
        self._project = project
        self._after_edit(refit=refit)

    def _after_edit(self, *, refit: bool = False) -> None:
        self._sync_canvas()
        self._timeline.set_project(self._project, refit=refit)
        self._refresh_clip_fields()
        self._refresh_controls()
        self._view_timer.start()
        self._request_frame(force=True)
        if self._playing:
            # A composição mudou com a reprodução em andamento, e o que está
            # saindo é a composição de antes: o grafo do ffmpeg foi montado na
            # hora em que o fluxo abriu (ver :meth:`_restart_stream`).
            self._live_timer.start()
        self.changed.emit()

    def _on_clip_moved(self, clip_id: int, track_index: int, start: float) -> None:
        self._project = self._project.moved(clip_id, track_index, start)
        self._timeline.set_project(self._project)

    def _on_clip_resized(self, clip_id: int, edge: str, seconds: float) -> None:
        self._project = self._project.resized(clip_id, edge, seconds)
        self._timeline.set_project(self._project)

    def _on_edit_finished(self) -> None:
        self._after_edit()

    def _toggle_track_mute(self, index: int) -> None:
        self._remember()
        track = self._project.tracks[index]
        self._apply(self._project.with_track_muted(index, not track.muted))

    def _add_track(self, kind: TrackKind) -> None:
        self._remember()
        self._apply(self._project.with_track(kind))

    def _split_here(self) -> None:
        position = self._position
        clip = next(
            (c for c in self._project.clips if c.contains(position)), None
        )
        selected = self._timeline.selected_clip
        if selected is not None and selected.contains(position):
            clip = selected
        if clip is None:
            return
        self._remember()
        self._apply(self._project.split(clip.clip_id, position))

    def _delete_selected(self) -> None:
        clip = self._timeline.selected_clip
        if clip is None:
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
        if clip is None or not clip.contains(self._position):
            return False
        if edge == "inicio":
            return (
                self._position > clip.start
                and clip.end - self._position >= MIN_SEGMENT
            )
        return self._position - clip.start >= MIN_SEGMENT

    def _detach_audio(self) -> None:
        clip = self._timeline.selected_clip
        if clip is None or not clip.media.has_audio:
            return
        self._remember()
        self._apply(self._project.detached_audio(clip.clip_id))

    def _copy_clip(self) -> None:
        clip = self._timeline.selected_clip
        if clip is not None:
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
            # Pelo bloco, não pela mídia dele: um bloco de "separar áudio" vem
            # de um arquivo com imagem, e pela mídia a cópia de um som ia parar
            # numa trilha de vídeo, recolando o vídeo inteiro.
            kind = TrackKind.VIDEO if pasted.has_image else TrackKind.AUDIO
            project = self._project.with_track(kind)
            index = 0 if kind is TrackKind.VIDEO else len(project.tracks) - 1
            self._project = project
        self._project = self._project.with_clip(index, pasted)
        self._timeline.select(pasted.clip_id)
        self._after_edit()

    def _undo_edit(self) -> None:
        if not self._history:
            return
        self._future.append(self._project)
        self._apply(self._history.pop())

    def _redo_edit(self) -> None:
        if not self._future:
            return
        self._history.append(self._project)
        self._apply(self._future.pop())

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

    def _apply_field(self, edge: str) -> None:
        clip = self._timeline.selected_clip
        if clip is None:
            return
        field = self._start_field if edge == "inicio" else self._end_field
        value = parse_timecode(field.text())
        if value is None:
            self._refresh_clip_fields()
            return
        self._remember()
        self._apply(self._project.resized(clip.clip_id, edge, value))

    def _on_clip_selected(self, _clip_id: int) -> None:
        self._end_gain_session()
        self._refresh_clip_fields()
        # Trocar de bloco troca o que os controles alcançam — volume e mudo se
        # desligam num bloco sem som ajustável. Antes isto pegava carona no fim
        # do arrasto; agora que um clique simples não conta como edição (ver
        # ``timeline._DRAG_SLACK``), a seleção precisa avisar por conta própria.
        self._refresh_controls()

    def _refresh_clip_fields(self) -> None:
        clip = self._timeline.selected_clip
        self._syncing = True
        try:
            self._start_field.setText(format_timecode(clip.start) if clip else "")
            self._end_field.setText(format_timecode(clip.end) if clip else "")
            self._gain.setValue(clip.gain_db if clip else 0.0)
            self._clip_mute.setChecked(bool(clip and clip.muted))
        finally:
            self._syncing = False

        if clip is None:
            self._clip_label.setText(strings.EDIT_CLIP_NONE)
            return
        info = strings.EDIT_CLIP_INFO.format(
            name=clip.media.name, duration=format_span(clip.duration)
        )
        if clip.detached:
            info = f"{info} · {strings.EDIT_CLIP_DETACHED}"
        self._clip_label.setText(info)

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
        self._project = replace(self._project, width=width, height=height, fps=fps)

    def _on_canvas_choice(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._canvas_choice = self._canvas_box.itemData(index)
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
        for width, height in [*ordered, *_CANVAS_PRESETS]:
            if (width, height) in seen:
                continue
            seen.add((width, height))
            options.append(
                (strings.EDIT_CANVAS_SIZE.format(width=width, height=height),
                 (width, height))
            )
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
        area = self._fullscreen.size() if self._on_fullscreen else self._preview.size()
        ceiling = _FULLSCREEN_MAX_WIDTH if self._on_fullscreen else _PREVIEW_MAX_WIDTH
        return fit_size(
            self._project.width,
            self._project.height,
            min(ceiling, max(160, area.width())),
            max(120, area.height()),
        )

    def _request_frame(self, *, force: bool = False) -> None:
        if self._project.is_empty or self._playing:
            return
        self._wanted = self._position
        if force:
            self._rendered = None
        if self._frame_busy:
            return
        self._start_frame()

    def _start_frame(self) -> None:
        tools = self._ensure_tools()
        if tools is None or self._wanted is None:
            return
        self._frame_busy = True
        self._rendered = self._wanted
        self._frame_token = next(self._tokens)
        size = self._preview_size()
        worker = FrameWorker(
            frame_command(self._project, self._wanted, size, tools),
            size,
            self._wanted,
            self._frame_token,
        )
        worker.signals.frame.connect(self._on_frame)
        worker.signals.done.connect(self._on_frame_done)
        self._runner.start(worker, worker.signals.done)

    def _on_frame_done(self) -> None:
        self._frame_busy = False
        if self._wanted is not None and self._wanted != self._rendered:
            self._start_frame()

    def _on_frame(self, token: int, frame: object) -> None:
        if token not in (self._frame_token, self._play_token):
            return
        self._show_frame(frame)
        if token != self._play_token or not self._playing:
            return
        self._shown_frame = frame.seconds
        if not self._audio.playing:
            self._timeline.set_position(frame.seconds)
            self._update_time_labels()

    def _show_frame(self, frame: object) -> None:
        pixmap = pixmap_from_frame(frame.data, frame.width, frame.height)
        if self._on_fullscreen:
            self._fullscreen.set_frame(pixmap)
            return
        area = self._preview.size()
        if pixmap.width() > area.width() or pixmap.height() > area.height():
            pixmap = pixmap.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._preview.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
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
                if clip.end < start or clip.start > end:
                    continue
                if not self._strip_is_stale(clip, track.kind):
                    continue
                if track.kind is TrackKind.VIDEO:
                    self._request_thumbs(clip, tools)
                elif clip.media.has_audio:
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
        if clip.is_image:
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
        if clip.is_image:
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
        worker = FilmstripWorker(
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
        self._background.start(worker, worker.signals.done)
        self._strip_workers[clip.clip_id] = worker

    def _cancel_strip(self, clip_id: int) -> None:
        """Interrompe a geração anterior de miniaturas deste bloco.

        O token já descartaria as imagens atrasadas, mas o ffmpeg continuaria
        gerando cada uma delas: aproximar três vezes seguidas deixaria três
        gerações disputando a fila de trabalho.
        """
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
        token = next(self._tokens)
        self._strip_tokens[clip.clip_id] = token
        begin, finish = self._strip_window(clip)
        width = int(min(_WAVE_MAX_WIDTH, max(80, self._clip_pixels(clip))))
        worker = WaveformWorker(
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
        self._background.start(worker, worker.signals.done)

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
            clip is not None and clip.contains(self._position)
        )
        self._trim_left_button.setEnabled(self._can_trim(clip, "inicio"))
        self._trim_right_button.setEnabled(self._can_trim(clip, "fim"))
        self._delete_button.setEnabled(clip is not None)

    def _on_scrub(self, seconds: float) -> None:
        self._stop_playback()
        self._request_frame()
        self._update_time_labels()
        self._refresh_clip_actions()

    def _seek_to(self, seconds: float) -> None:
        if self._project.is_empty:
            return
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
        if direction < 0:
            target = keyframe_at_or_before(
                self._keyframes, self._position - frame_step(self._fps)
            )
        else:
            target = keyframe_after(self._keyframes, self._position)
        if target is not None:
            self._seek_to(target)

    def _update_time_labels(self) -> None:
        self._time_label.setText(
            strings.EDIT_POSITION.format(
                current=format_timecode(self._position),
                total=format_timecode(self._duration),
            )
        )
        self._frame_label.setText(
            strings.EDIT_FRAME_NUMBER.format(index=frame_index(self._position, self._fps))
        )
        self._sync_fullscreen()

    def _lock_readouts(self) -> None:
        """Fixa a largura dos números pelo maior valor deste projeto.

        Em tipo proporcional o "1" é mais estreito que o "8": sem largura fixa,
        a barra de transporte inteira treme a cada quadro.
        """
        biggest = format_timecode(self._duration)
        text = strings.EDIT_POSITION.format(current=biggest, total=biggest)
        self._time_label.setFixedWidth(
            QFontMetrics(self._time_label.font()).horizontalAdvance(text) + 6
        )
        frames = strings.EDIT_FRAME_NUMBER.format(
            index=frame_index(self._duration, self._fps)
        )
        self._frame_label.setFixedWidth(
            QFontMetrics(self._frame_label.font()).horizontalAdvance(frames) + 6
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
            self._settings.save()
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
        if seconds >= self._duration - frame_step(self._fps):
            seconds = 0.0
            self._timeline.set_position(0.0)

        self._playing = True
        self._refresh_play_button()
        self._open_stream(seconds)
        self._tick.start()

    def _open_stream(self, seconds: float) -> None:
        """Abre imagem e som da composição corrente, a partir de ``seconds``."""
        tools = self._ensure_tools()
        if tools is None:
            return
        self._live_timer.stop()
        self._start_frames(seconds)
        command = audio_command(self._project, seconds, tools)
        if command is not None and self._audio.available:
            self._audio.start(command, seconds)
        else:
            # A composição pode ter ficado sem som — uma trilha calada, o último
            # bloco audível apagado. Sem parar, o que já estava no processo
            # continuaria tocando depois de silenciado na tela.
            self._audio.stop()

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

    def _start_frames(self, seconds: float) -> None:
        tools = self._ensure_tools()
        if tools is None or not self._has_video:
            return
        if self._playback is not None:
            self._playback.cancel()
        self._shown_frame = seconds
        self._play_token = next(self._tokens)
        size = self._preview_size()
        fps = preview_fps(self._fps)
        worker = PlaybackWorker(
            playback_command(self._project, seconds, size, tools, fps=fps),
            seconds,
            size,
            self._play_token,
            fps=fps,
        )
        worker.signals.frame.connect(self._on_frame)
        worker.signals.done.connect(
            lambda token=self._play_token: self._on_playback_done(token)
        )
        self._runner.start(worker, worker.signals.done)
        self._playback = worker

    def _on_tick(self) -> None:
        if not self._playing:
            return
        if self._audio.playing:
            position = self._audio.position
            self._timeline.set_position(position)
            self._update_time_labels()
            drift = abs(self._shown_frame - position)
            if (
                self._has_video
                and drift > _MAX_DRIFT
                and position - self._resynced_at > _RESYNC_COOLDOWN
            ):
                self._resynced_at = position
                self._start_frames(position)
        if self._position >= self._duration - 1e-3:
            self._stop_playback()

    def _on_playback_done(self, token: int) -> None:
        """O fluxo de quadros acabou: sem som, é ele quem diz que terminou."""
        if token != self._play_token or not self._playing or self._audio.playing:
            return
        self._stop_playback()

    def _stop_playback(self) -> None:
        self._tick.stop()
        self._live_timer.stop()
        self._audio.stop()
        if self._playback is not None:
            self._playback.cancel()
            self._playback = None
        if self._playing:
            self._playing = False
            self._play_token = 0
            self._request_frame(force=True)
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

        self._fullscreen.set_audio(
            self._has_sound, self._volume.value(), self._mute.isChecked()
        )
        self._fullscreen.showFullScreen()
        self._fullscreen.activateWindow()
        self._fullscreen.setFocus()
        self._sync_fullscreen()
        self._restart_frames()

    def _restart_frames(self) -> None:
        if self._playing:
            self._start_frames(self._position)
        else:
            self._request_frame(force=True)

    def _sync_fullscreen(self) -> None:
        if self._on_fullscreen:
            self._fullscreen.set_state(self._position, self._duration, self._playing)

    # ------------------------------------------------------------------
    # Zoom e rolagem
    # ------------------------------------------------------------------

    def _zoom(self, factor: float) -> None:
        self._timeline.zoom(factor, self._position)

    def _sync_scrollbar(self) -> None:
        start, end = self._timeline.view
        span = end - start
        self._syncing = True
        try:
            self._scroll.setPageStep(int(span * 1000))
            self._scroll.setRange(0, max(0, int((self._duration - span) * 1000)))
            self._scroll.setValue(int(start * 1000))
            self._scroll.setEnabled(span < self._duration)
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
        anchor = keyframe_at_or_before(self._keyframes, segments[0].start)
        return TrimTarget(
            segments=segments,
            container=clip.media.path.suffix.lstrip(".").lower() or "mp4",
            mode=CutMode.FAST,
            anchor=anchor,
            hardware=self._settings.hardware_encoder,
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
        fast = self._fast.isChecked() and self._fast_available()
        if self._project.is_empty:
            self._plan.setText("")
            self._warning.setVisible(False)
            self._export.setEnabled(False)
            return

        if fast:
            target = self._trim_target()
            plan = strings.EDIT_PLAN_FAST.format(
                container=target.container,
                duration=format_span(target.output_duration),
            )
            self._warning.setText(self._drift_text(target))
        else:
            plan = describe_export(
                self._project,
                self._container(),
                self._settings.hardware_encoder,
                self._interpolating,
            )
            self._warning.setText(self._compose_warning())
        self._plan.setText(strings.EDIT_PLAN.format(plan=plan))
        self._warning.setVisible(bool(self._warning.text()))
        self._export.setEnabled(True)

    @property
    def _interpolating(self) -> bool:
        """Se a exportação vai inventar os quadros que faltam.

        A caixa marcada não basta: ela fica desligada quando não há bloco abaixo
        da taxa da tela, e uma caixa desligada não manda em nada.
        """
        return self._interpolate.isChecked() and can_interpolate(self._project)

    def _compose_warning(self) -> str:
        """O que precisa ser dito antes de a exportação entrar na fila."""
        if self._interpolating:
            # A memória entra no aviso porque é o número que decide se dá para
            # exportar: ela sai da tela escolhida, que está no controle logo
            # acima, e uma máquina que não a tem não fica lenta — ela cai.
            return strings.EDIT_INTERPOLATE_WARN.format(
                memory=format_size(interpolation_bytes(self._project))
            )
        if self._fast.isChecked() and not self._fast_available():
            return strings.EDIT_FAST_UNAVAILABLE
        return ""

    def _drift_text(self, target: TrimTarget) -> str:
        if target.anchor is None:
            return ""
        if target.drift < frame_step(self._fps):
            return strings.EDIT_DRIFT_NONE
        return strings.EDIT_DRIFT.format(
            time=format_timecode(target.anchor), delta=format_span(target.drift)
        )

    def _enqueue(self) -> None:
        tools = self._ensure_tools()
        if tools is None:
            return
        if self._project.is_empty:
            QMessageBox.information(
                self, strings.DIALOG_WARNING_TITLE, strings.EDIT_NO_CLIPS
            )
            return

        main = self._main_clip()
        source = main.media.path if main else self._project.clips[0].media.path
        local = self._probed.get(source)
        if local is None:
            try:
                local = probe_file(source, tools)
            except VideoManagerError as exc:
                QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, str(exc))
                return

        fast = self._fast.isChecked() and self._fast_available()
        target = self._trim_target() if fast else Composition(
            self._project,
            self._container(),
            self._settings.hardware_encoder,
            self._interpolating,
        )
        dest_dir = (
            None if self._same_folder.isChecked() else self._settings.resolved_download_dir()
        )
        destination = output_path(
            source,
            target,
            dest_dir,
            strings.EDIT_SUFFIX_ONE if fast else strings.EDIT_SUFFIX_EDIT,
        )
        job = Job(
            url=str(source),
            title=destination.name,
            description=(
                strings.EDIT_PLAN_FAST.format(
                    container=target.container,
                    duration=format_span(target.output_duration),
                )
                if fast
                else describe_export(
                    self._project,
                    self._container(),
                    self._settings.hardware_encoder,
                    self._interpolating,
                )
            ),
            kind=JobKind.TRIM,
            opts={
                "media": local,
                "target": target,
                "destination": destination,
                "tools": tools,
            },
            warnings=(self._warning.text(),) if self._warning.text() else (),
        )
        self.jobs_ready.emit([job])

    # ------------------------------------------------------------------
    # Sincronização geral
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Encerra o que a aba deixou rodando fora do processo.

        A prévia mantém até dois ffmpeg vivos — o fluxo de quadros e o da
        mixagem —, e eles não morrem só porque a janela fechou: ficariam
        consumindo CPU até perceberem o cano fechado. Fechar a janela é o
        último momento em que alguém pode mandá-los parar.
        """
        self._stop_playback()
        for clip_id in list(self._strip_workers):
            self._cancel_strip(clip_id)
        if self._fullscreen is not None:
            self._fullscreen.close()

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
        self._insert.setEnabled(bool(self._pool))
        for field in (self._start_field, self._end_field):
            field.setEnabled(clip is not None)
        # Volume e mudo só onde há som para ajustar. Num bloco cujo áudio foi
        # separado eles ficam desligados de propósito: o som agora é o do outro
        # bloco, e é lá que ele se ajusta — oferecer o controle aqui seria
        # oferecer um botão que não faz nada.
        adjustable = clip is not None and clip.can_adjust_sound
        self._gain.setEnabled(adjustable)
        self._clip_mute.setEnabled(adjustable)
        tip = (
            strings.EDIT_GAIN_DETACHED
            if clip is not None and clip.detached
            else strings.EDIT_GAIN_TIP
        )
        self._gain.setToolTip(tip)
        self._clip_mute.setToolTip(
            tip if clip is not None and clip.detached else strings.EDIT_CLIP_MUTE_TIP
        )

        self._refresh_clip_actions()

        for button in (self._prev_key, self._next_key):
            button.setEnabled(bool(self._keyframes) and self._fast_available())
        self._refresh_play_button()
        for widget in (self._mute, self._volume):
            widget.setEnabled(self._audio.available)
        self._fullscreen_button.setEnabled(self._has_video)
        self._collapse.setEnabled(True)

        self._fast.setEnabled(self._fast_available())
        if not self._fast_available() and self._fast.isChecked():
            self._fast.setChecked(False)

        # Interpolar só faz sentido com bloco abaixo da taxa da tela. Desmarcar
        # junto com o desligamento é o que impede uma caixa cinza e marcada
        # continuar mandando na exportação.
        interpolavel = can_interpolate(self._project)
        self._interpolate.setEnabled(interpolavel)
        self._interpolate.setToolTip(
            strings.EDIT_INTERPOLATE_TIP if interpolavel else strings.EDIT_INTERPOLATE_OFF
        )
        if not interpolavel and self._interpolate.isChecked():
            self._interpolate.setChecked(False)

        self._count_label.setText(
            strings.EDIT_TRACK_COUNT.format(
                tracks=len(self._project.tracks),
                clips=len(self._project.clips),
                duration=format_span(self._duration),
            )
            if loaded
            else ""
        )
        self._refresh_canvas_controls()
        self._lock_readouts()
        self._update_time_labels()
        self._sync_scrollbar()
        self._refresh_plan()
        self._scan_keyframes()

    def _scan_keyframes(self) -> None:
        """Mapeia os keyframes da mídia única, quando ainda houver uma só.

        Só o corte rápido usa isso, e ele só existe enquanto a edição for um
        recorte de um arquivo — daí o mapeamento não acontecer numa montagem com
        várias mídias, onde não teria uso.
        """
        if not self._fast_available():
            return
        source = self._project.clips[0].media.path
        if source == self._keyframe_source:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        self._keyframe_source = source
        worker = KeyframeWorker(source, tools)
        worker.signals.keyframes.connect(self._on_keyframes)
        self._background.start(worker, worker.signals.done)

    def _on_keyframes(self, times: object) -> None:
        self._keyframes = tuple(times) if isinstance(times, tuple) else ()
        for button in (self._prev_key, self._next_key):
            button.setEnabled(bool(self._keyframes) and self._fast_available())
        self._refresh_plan()

