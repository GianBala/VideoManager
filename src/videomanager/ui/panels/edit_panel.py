"""A aba de edição: prévia em cima, linha do tempo embaixo, fila logo abaixo.

A disposição e os gestos são os que os editores de consumo (CapCut, Filmora)
tornaram padrão, porque é o vocabulário que quem vai usar já tem: **posicionar o
cursor, dividir com a tesoura, apagar o que não serve, arrastar as pontas** —
e o que sobrou na trilha é o que será exportado. Não há campo escondido: o
formulário de tempos ao lado edita o mesmo trecho que está selecionado na
trilha, nos dois sentidos.

Três decisões próprias desta tela:

**Um pedido de quadro por vez.** Arrastar o cursor gera dezenas de pedidos por
segundo, e atender todos encheria a fila de trabalho com imagens que ninguém vai
ver. Guardamos só o último pedido e o disparamos quando o anterior volta — o que
mantém a resposta imediata e o custo constante, independentemente da velocidade
do arrasto.

**A reprodução atravessa os cortes.** Ao chegar ao fim de um trecho, a prévia
salta para o começo do seguinte, pulando o que foi apagado. É o que transforma o
botão de reprodução numa conferência do resultado, e não do arquivo de origem.

**A imagem vem do ffmpeg e o som vem do Qt, e quem manda no tempo é o som.** As
duas exigências são opostas: a imagem precisa ser o quadro exato do corte (ver
``core/preview``), o som precisa sair contínuo. Enquanto toca, o relógio é o
áudio — o ouvido percebe um engasgo de vinte milissegundos e não percebe um
quadro repetido —, e a imagem se corrige contra ele quando os dois se afastam
demais. Sem som disponível (arquivo sem trilha, pacote sem o módulo de
multimídia), o fluxo de quadros volta a ser o próprio relógio e a prévia toca
muda, como antes.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
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
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...core.binaries import FFmpegTools
from ...core.converter import LocalMedia, output_path, probe_file
from ...core.errors import VideoManagerError
from ...core.humanize import format_size
from ...core.job import Job, JobKind
from ...core.preview import fit_size
from ...core.settings import Settings
from ...core.trimmer import (
    CutMode,
    Segment,
    TrimTarget,
    describe_trim,
    format_span,
    format_timecode,
    frame_index,
    frame_step,
    has_real_video,
    keyframe_after,
    keyframe_at_or_before,
    parse_timecode,
    seek_time,
)
from ...workers.preview_worker import (
    FilmstripWorker,
    FrameWorker,
    KeyframeWorker,
    PlaybackWorker,
    WaveformWorker,
)
from ...workers.runner import WorkerRunner
from .. import strings
from ..audio_preview import AudioPreview
from ..fullscreen_preview import FullscreenPreview
from ..theme import palette
from .timeline import (
    FILM_CELL_WIDTH,
    FILM_HEIGHT,
    WAVE_HEIGHT,
    Timeline,
    image_from_frame,
    pixmap_from_frame,
)

# Altura mínima da prévia. Baixa de propósito: a aba divide a janela com a fila,
# e a prévia é o que mais cresce quando sobra espaço (ver a política de tamanho
# do rótulo). Quem quiser uma tela maior arrasta o divisor.
_PREVIEW_MIN_HEIGHT = 160
# Teto do que se pede ao ffmpeg. Decodificar em 4K para exibir em 600 px de
# largura gastaria tempo em pixels que a tela não mostra. O valor cobre uma
# janela maximizada em 1080p sem nunca ser ele o limite — quem manda no tamanho
# é a altura disponível, senão sobraria tarja preta dos lados de propósito.
_PREVIEW_MAX_WIDTH = 1280
# Tetos da tela cheia: o quadro parado vem em resolução de tela, a reprodução
# vem menor e é ampliada na exibição (ver :meth:`EditPanel._preview_size`).
_FULLSCREEN_MAX_WIDTH = 1920
_FULLSCREEN_PLAYING_WIDTH = 1280

# Espera antes de refazer miniaturas e onda depois de mexer no zoom. Um zoom é
# uma sequência de passos da roda do mouse; sem a pausa, cada passo dispararia
# uma geração inteira que o passo seguinte descartaria.
_VIEW_SETTLE_MS = 220
# Mesma ideia para o redimensionamento da janela, que chega em rajada.
_RESIZE_SETTLE_MS = 200

_ZOOM_FACTOR = 1.6

# Passo do relógio da reprodução. 40 ms move o cursor de forma contínua ao olho
# sem custar nada: cada tique é uma leitura de posição e um repintar.
_TICK_MS = 40
# Diferença entre a imagem e o som a partir da qual vale recomeçar o fluxo de
# quadros. Meio quadro ninguém nota; um terço de segundo é dublagem ruim.
_MAX_DRIFT = 0.35
# Intervalo mínimo entre duas correções, para uma máquina lenta não ficar
# reiniciando o ffmpeg em looping e piorar justamente o que tenta corrigir.
_RESYNC_COOLDOWN = 1.5


class _Preview(QLabel):
    """Tela da prévia: mantém o quadro centralizado e o fundo preto.

    ``QLabel`` com pixmap escalado, e não um widget desenhado à mão, porque o
    quadro já chega no tamanho certo — o escalonamento aqui só cuida da fração
    de segundo entre redimensionar a janela e o quadro novo chegar.
    """

    # Duplo clique abre a tela cheia, como em qualquer player.
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
        return QSize(480, _PREVIEW_MIN_HEIGHT)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()


class EditPanel(QWidget):
    """Abre um vídeo, recorta trechos dele e entrega as tarefas para a fila."""

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
        self._runner = WorkerRunner()
        self._colors = palette(settings.theme)

        self._media: LocalMedia | None = None
        self._keyframes: tuple[float, ...] = ()
        self._history: list[tuple[Segment, ...]] = []
        self._future: list[tuple[Segment, ...]] = []

        # Pedidos de imagem em voo. O contador é global às três espécies de
        # pedido: um número que nunca se repete é o bastante para descartar o
        # que chegou tarde, e evita três contadores para a mesma finalidade.
        self._tokens = itertools.count(1)
        self._frame_token = 0
        self._strip_token = 0
        self._wave_token = 0
        self._play_token = 0
        self._frame_busy = False
        self._wanted: float | None = None
        self._rendered: float | None = None
        self._playing = False
        self._playback: PlaybackWorker | None = None
        self._strip_worker: FilmstripWorker | None = None
        # Criada na primeira vez que for pedida: quem só recorta sem ampliar
        # nunca paga por ela.
        self._fullscreen: FullscreenPreview | None = None
        self._syncing = False
        self._shown_frame = 0.0
        self._resynced_at = 0.0
        self._resume_wanted = False

        # O som sai pelo Qt e a imagem pelo ffmpeg; quem manda no tempo é o som
        # (ver ui/audio_preview.py). O tique lê o relógio do áudio e arrasta a
        # tela atrás dele.
        self._audio = AudioPreview(self)
        self._audio.set_volume(settings.preview_volume)
        self._audio.set_muted(settings.preview_muted)
        self._audio.stopped.connect(self._stop_playback)
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._on_audio_tick)

        self._view_timer = QTimer(self)
        self._view_timer.setSingleShot(True)
        self._view_timer.setInterval(_VIEW_SETTLE_MS)
        self._view_timer.timeout.connect(self._refresh_backdrop)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_SETTLE_MS)
        self._resize_timer.timeout.connect(lambda: self._request_frame(force=True))

        self._build_ui()
        self._install_shortcuts()
        self._update_controls()

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_source_row())
        # Só a prévia estica: tudo o mais na aba tem altura natural, e o que
        # sobrar de janela vira imagem maior.
        layout.addWidget(self._build_player(), 1)
        layout.addWidget(self._build_timeline_group())
        layout.addWidget(self._build_export_row())

    def _build_source_row(self) -> QWidget:
        box = QWidget()
        box.setProperty("role", "plain")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._open = QPushButton(strings.EDIT_OPEN)
        self._open.clicked.connect(self._choose_file)
        row.addWidget(self._open)

        self._file_label = QLabel(strings.EDIT_NO_FILE)
        self._file_label.setProperty("role", "dim")
        row.addWidget(self._file_label, 1)

        # A tela cheia mora aqui, e não na barra de transporte: lá os botões já
        # ocupam a largura toda, e esta linha tem espaço sobrando.
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

        # Números em fonte monoespaçada: num tipo proporcional o "1" é mais
        # estreito que o "8", e o cronômetro se mexe sozinho a cada quadro.
        # A largura fixa (ver :meth:`_lock_readouts`) resolve a outra metade do
        # problema — o texto crescendo empurrava a fileira de botões inteira.
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

        # Setas simples, e não os símbolos de transporte do Unicode (⏮ ⏪): estes
        # últimos têm apresentação de emoji em boa parte dos sistemas e saem
        # coloridos no meio de uma barra de botões monocromática.
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
            # Largura para os três símbolos de "|◀◀" caberem sem corte: com 46
            # px o Qt encurtava o rótulo e o botão de início ficava igual ao de
            # voltar um segundo.
            button.setFixedWidth(56)
            button.clicked.connect(slot)
            row.addWidget(button)
            self._buttons.append(button)
        # O botão do meio é o de reprodução: guardado para trocar o ícone.
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
        """Mudo e volume, ajustáveis com a reprodução em andamento."""
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
        # Enquanto arrasta, só o som muda; a preferência é gravada ao soltar,
        # senão cada pixel do arrasto escreveria o arquivo de configuração.
        self._volume.valueChanged.connect(self._on_volume)
        self._volume.sliderReleased.connect(self._save_audio_prefs)
        row.addWidget(self._volume)
        self._refresh_volume_label()
        return box

    def _build_timeline_group(self) -> QWidget:
        """A linha do tempo e seus controles, sem moldura de grupo.

        A moldura custaria quase 60 px de recuo interno — que aqui saem direto
        da altura da prévia, o painel que o usuário fica olhando. E ela não
        agrupa nada: a própria trilha, desenhada, já é a fronteira visual.
        """
        group = QWidget()
        group.setProperty("role", "plain")
        column = QVBoxLayout(group)
        column.setSpacing(6)
        column.setContentsMargins(0, 0, 0, 0)

        column.addLayout(self._build_toolbar())

        self._timeline = Timeline(self._colors)
        self._timeline.setToolTip(strings.EDIT_TIMELINE_HINT)
        self._timeline.scrubbed.connect(self._on_scrub)
        self._timeline.edit_started.connect(self._remember)
        self._timeline.clips_edited.connect(self._on_clips_edited)
        self._timeline.selection_changed.connect(lambda _: self._sync_clip_fields())
        self._timeline.view_changed.connect(self._on_view_changed)
        column.addWidget(self._timeline)

        self._scroll = QScrollBar(Qt.Orientation.Horizontal)
        self._scroll.valueChanged.connect(self._on_scrollbar)
        column.addWidget(self._scroll)

        column.addLayout(self._build_clip_fields())
        return group

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        # Sem ícone: a aplicação inteira é de texto, e um par de emojis aqui
        # seria a única coisa colorida da janela.
        self._split = QPushButton(strings.EDIT_SPLIT)
        self._split.setToolTip(f"{strings.EDIT_SPLIT} (S)")
        self._split.clicked.connect(self._split_here)
        row.addWidget(self._split)

        self._delete = QPushButton(strings.EDIT_DELETE)
        self._delete.setToolTip(f"{strings.EDIT_DELETE} (Del)")
        self._delete.clicked.connect(self._delete_selected)
        row.addWidget(self._delete)

        self._undo = QPushButton("↶")
        self._undo.setToolTip(f"{strings.EDIT_UNDO} (Ctrl+Z)")
        self._undo.setFixedWidth(40)
        self._undo.clicked.connect(self._undo_edit)
        row.addWidget(self._undo)

        self._redo = QPushButton("↷")
        self._redo.setToolTip(f"{strings.EDIT_REDO} (Ctrl+Shift+Z)")
        self._redo.setFixedWidth(40)
        self._redo.clicked.connect(self._redo_edit)
        row.addWidget(self._redo)

        row.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setProperty("role", "dim")
        row.addWidget(self._count_label)
        row.addStretch(1)

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
        fit.clicked.connect(lambda: self._timeline.set_view(0.0, self._duration))
        row.addWidget(fit)
        return row

    def _build_clip_fields(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._start_field = self._timecode_field(strings.EDIT_FIELD_TIP)
        self._end_field = self._timecode_field(strings.EDIT_FIELD_TIP)
        self._start_field.editingFinished.connect(lambda: self._apply_field("inicio"))
        self._end_field.editingFinished.connect(lambda: self._apply_field("fim"))

        mark_start = QPushButton(strings.EDIT_MARK_HERE.format(key="I"))
        mark_start.setToolTip(strings.EDIT_MARK_START)
        mark_start.clicked.connect(lambda: self._mark("inicio"))
        mark_end = QPushButton(strings.EDIT_MARK_HERE.format(key="O"))
        mark_end.setToolTip(strings.EDIT_MARK_END)
        mark_end.clicked.connect(lambda: self._mark("fim"))

        row.addWidget(QLabel(strings.EDIT_CLIP_START))
        row.addWidget(self._start_field)
        row.addWidget(mark_start)
        row.addSpacing(10)
        row.addWidget(QLabel(strings.EDIT_CLIP_END))
        row.addWidget(self._end_field)
        row.addWidget(mark_end)
        row.addSpacing(10)

        self._duration_label = QLabel(strings.EDIT_CLIP_NONE)
        self._duration_label.setProperty("role", "dim")
        row.addWidget(self._duration_label, 1)
        self._mark_buttons = [mark_start, mark_end]
        return row

    @staticmethod
    def _timecode_field(tip: str) -> QLineEdit:
        field = QLineEdit()
        field.setToolTip(tip)
        # Largura de "0:00:00,000" com folga: o campo é de tamanho fixo porque
        # o conteúdo dele também é.
        field.setFixedWidth(110)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return field

    def _build_export_row(self) -> QWidget:
        """A faixa de exportação, sem moldura de grupo.

        Fora de um ``QGroupBox`` de propósito: a moldura custaria quase 60 px de
        recuo interno numa aba que já disputa altura com a fila, e o que ela
        agruparia são duas linhas que se explicam sozinhas — como o botão de
        adicionar à fila da aba de download, que também vive solto.
        """
        group = QWidget()
        group.setProperty("role", "plain")
        column = QVBoxLayout(group)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        choices = QHBoxLayout()
        choices.setContentsMargins(0, 0, 0, 0)
        choices.setSpacing(14)
        choices.addWidget(QLabel(strings.EDIT_EXPORT_LABEL))
        self._join = QRadioButton(strings.EDIT_OUTPUT_JOIN)
        self._join.setChecked(True)
        self._each = QRadioButton(strings.EDIT_OUTPUT_EACH)
        choices.addWidget(self._join)
        choices.addWidget(self._each)
        choices.addSpacing(16)
        choices.addWidget(QLabel(strings.EDIT_CUT_LABEL))

        self._exact = QRadioButton(strings.EDIT_MODE_EXACT)
        self._exact.setChecked(True)
        self._exact.setToolTip(strings.EDIT_MODE_TIP)
        self._fast = QRadioButton(strings.EDIT_MODE_FAST)
        self._fast.setToolTip(strings.EDIT_MODE_TIP)
        choices.addWidget(self._exact)
        choices.addWidget(self._fast)
        choices.addStretch(1)
        column.addLayout(choices)

        # Dois grupos declarados, e não a exclusão automática do Qt: ela vale
        # entre irmãos do mesmo pai, e como as quatro opções dividem a mesma
        # linha, escolher "corte rápido" desmarcava "um vídeo só".
        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self._join)
        self._output_group.addButton(self._each)
        self._output_group.buttonToggled.connect(self._update_plan)

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._exact)
        self._mode_group.addButton(self._fast)
        # Conectado ao grupo, e não a um dos botões: o ``toggled`` do que era
        # marcado chega antes de o outro se marcar, e ler o estado ali dentro
        # devolveria o modo de antes.
        self._mode_group.buttonToggled.connect(self._on_mode_changed)

        # Plano e aviso à esquerda, ação à direita, na mesma linha: são três
        # linhas de altura numa aba que já disputa cada pixel com a fila.
        actions = QHBoxLayout()
        actions.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self._plan = QLabel("")
        self._plan.setProperty("role", "dim")
        self._plan.setWordWrap(True)
        texts.addWidget(self._plan)
        self._warning = QLabel("")
        self._warning.setProperty("role", "warn")
        self._warning.setWordWrap(True)
        self._warning.setVisible(False)
        texts.addWidget(self._warning)
        actions.addLayout(texts, 1)

        self._same_folder = QCheckBox(strings.EDIT_SAME_FOLDER)
        self._same_folder.setChecked(True)
        actions.addWidget(self._same_folder)
        self._export = QPushButton(strings.EDIT_EXPORT)
        self._export.setProperty("role", "primary")
        self._export.clicked.connect(self._enqueue)
        actions.addWidget(self._export)
        column.addLayout(actions)
        return group

    def _install_shortcuts(self) -> None:
        """Atalhos de teclado do editor, com o alcance do painel.

        As setas ficam de fora: elas pertencem à linha do tempo, que só as
        recebe quando tem o foco (ver ``Timeline.keyPressEvent``). Um atalho de
        janela para elas roubaria as setas de todo campo de texto da aba.
        """
        for keys, slot in (
            ("Space", self._toggle_play),
            ("S", self._split_here),
            ("Ctrl+B", self._split_here),
            ("Del", self._delete_selected),
            ("I", lambda: self._mark("inicio")),
            ("O", lambda: self._mark("fim")),
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
        letra — "S" dividiria o trecho no meio da digitação de "0:00:15".

        A segunda existe porque a janela de tela cheia é filha deste painel, e o
        alcance do atalho a acompanha: sem ela, um Espaço lá seria contado duas
        vezes, aqui e no player.
        """
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return
        if self._on_fullscreen:
            return
        slot()

    # ------------------------------------------------------------------
    # Abertura do arquivo
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()
        ]
        if paths:
            self.open_file(paths[0])
            event.acceptProposedAction()

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, strings.EDIT_OPEN, str(Path.home()), strings.EDIT_FILE_FILTER
        )
        if path:
            self.open_file(Path(path))

    def apply_settings(self, settings: Settings) -> None:
        """Adota as preferências recém-salvas pelo diálogo de configurações.

        O diálogo devolve um objeto novo, e sem esta troca o painel continuaria
        gravando por cima dele o estado antigo ao mexer no volume — desfazendo o
        que o usuário acabou de configurar noutra tela.
        """
        self._settings = settings
        self._audio.set_volume(settings.preview_volume)
        self._audio.set_muted(settings.preview_muted)
        self._volume.setValue(settings.preview_volume)
        self._mute.setChecked(settings.preview_muted)

    def open_file(self, path: Path) -> None:
        tools = self._ensure_tools()
        if tools is None:
            return
        try:
            media = probe_file(path, tools)
        except VideoManagerError as exc:
            QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, str(exc))
            return
        if not media.duration:
            QMessageBox.warning(
                self,
                strings.DIALOG_ERROR_TITLE,
                f"“{path.name}” não informa duração e não pode ser recortado.",
            )
            return

        self._stop_playback()
        self._media = media
        self._audio.load(path)
        self._keyframes = ()
        self._history.clear()
        self._future.clear()
        self._file_label.setText(self._describe_file(media))
        self._timeline.load(media.duration, self._fps)
        self._timeline.set_keyframes(())
        # Um arquivo só de áudio não tem quadro para mostrar; quem serve de guia
        # é a forma de onda embaixo da trilha, e a tela diz isso em vez de ficar
        # preta sem explicação.
        self._preview.setText("" if self._has_video else strings.EDIT_AUDIO_ONLY)
        self._request_frame(force=True)
        # A tira e a onda saem pelo temporizador que ``Timeline.load`` já
        # disparou ao anunciar a janela visível nova.
        self._scan_keyframes()
        self._update_controls()
        self.changed.emit()

    @staticmethod
    def _describe_file(media: LocalMedia) -> str:
        pieces = [media.path.name]
        video = media.video
        if video is not None and video.width and video.height:
            pieces.append(f"{video.width}×{video.height}")
        if video is not None and video.fps:
            pieces.append(f"{video.fps:.6g} fps")
        pieces.append(format_timecode(media.duration, milliseconds=False))
        pieces.append(format_size(media.size))
        return "   ·   ".join(pieces)

    def _scan_keyframes(self) -> None:
        if self._media is None:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        worker = KeyframeWorker(self._media.path, tools)
        worker.signals.keyframes.connect(self._on_keyframes)
        self._runner.start(worker, worker.signals.done)

    def _on_keyframes(self, times: object) -> None:
        self._keyframes = tuple(times) if isinstance(times, tuple) else ()
        self._timeline.set_keyframes(self._keyframes)
        for button in (self._prev_key, self._next_key):
            button.setEnabled(bool(self._keyframes))
        self._update_plan()

    # ------------------------------------------------------------------
    # Estado derivado
    # ------------------------------------------------------------------

    @property
    def _duration(self) -> float:
        return self._media.duration or 0.0 if self._media else 0.0

    @property
    def _fps(self) -> float | None:
        video = self._media.video if self._media else None
        return video.fps if video else None

    @property
    def _has_video(self) -> bool:
        return self._media is not None and has_real_video(self._media)

    @property
    def _position(self) -> float:
        return self._timeline.position

    # ------------------------------------------------------------------
    # Prévia
    # ------------------------------------------------------------------

    @property
    def _on_fullscreen(self) -> bool:
        return self._fullscreen is not None and self._fullscreen.isVisible()

    def _preview_size(self, *, playing: bool = False) -> tuple[int, int]:
        """Tamanho a pedir ao ffmpeg para a superfície que está à frente.

        Em tela cheia, a reprodução usa um teto menor que o quadro parado. É a
        mesma troca que os editores fazem com arquivos de prova: decodificar em
        resolução cheia trinta vezes por segundo custa muito mais do que se
        ganha numa imagem em movimento, e ao pausar o quadro exato vem inteiro.
        """
        video = self._media.video if self._media else None
        area = self._fullscreen.size() if self._on_fullscreen else self._preview.size()
        if self._on_fullscreen:
            teto = _FULLSCREEN_PLAYING_WIDTH if playing else _FULLSCREEN_MAX_WIDTH
        else:
            teto = _PREVIEW_MAX_WIDTH
        return fit_size(
            video.width if video else None,
            video.height if video else None,
            min(teto, max(160, area.width())),
            max(120, area.height()),
        )

    def _request_frame(self, *, force: bool = False) -> None:
        """Pede o quadro do cursor, no máximo um por vez (ver o topo do módulo)."""
        if self._media is None or self._playing or not self._has_video:
            return
        self._wanted = self._position
        if force:
            self._rendered = None
        if self._frame_busy:
            return
        self._start_frame()

    def _start_frame(self) -> None:
        tools = self._ensure_tools()
        if tools is None or self._media is None or self._wanted is None:
            return
        self._frame_busy = True
        self._rendered = self._wanted
        self._frame_token = next(self._tokens)
        worker = FrameWorker(
            self._media.path,
            seek_time(self._wanted, self._fps),
            self._preview_size(),
            tools,
            self._frame_token,
        )
        worker.signals.frame.connect(self._on_frame)
        worker.signals.done.connect(self._on_frame_done)
        self._runner.start(worker, worker.signals.done)

    def _on_frame_done(self) -> None:
        self._frame_busy = False
        # O cursor pode ter andado enquanto o quadro era gerado: aí o pedido
        # seguinte sai agora, já com a posição atual.
        if self._wanted is not None and self._wanted != self._rendered:
            self._start_frame()

    def _on_frame(self, token: int, frame: object) -> None:
        if token not in (self._frame_token, self._play_token):
            return  # quadro de um pedido que já não interessa
        self._show_frame(frame)
        if token != self._play_token or not self._playing:
            return
        self._shown_frame = frame.seconds
        # Sem som, o fluxo de quadros é o único relógio que existe e é ele quem
        # move o cursor. Com som, quem move é o tique do áudio — deixar os dois
        # mexendo faria o cursor tremer entre dois tempos ligeiramente
        # diferentes.
        if not self._has_sound:
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
        if self._media is not None:
            self._resize_timer.start()
            self._view_timer.start()

    # ------------------------------------------------------------------
    # Miniaturas e forma de onda
    # ------------------------------------------------------------------

    def _on_view_changed(self) -> None:
        self._sync_scrollbar()
        self._view_timer.start()

    def _refresh_backdrop(self) -> None:
        """Refaz a tira de miniaturas e a onda para o trecho visível."""
        tools = self._ensure_tools()
        if self._media is None or tools is None:
            return
        width = max(200, self._timeline.width())
        start, end = self._timeline.view

        # A capa embutida de um MP3 conta como trilha de vídeo para o ffprobe;
        # gerar uma tira dela repetiria a mesma imagem quarenta vezes.
        if self._has_video:
            if self._strip_worker is not None:
                self._strip_worker.cancel()
            count = max(1, min(40, round(width / FILM_CELL_WIDTH)))
            self._strip_token = next(self._tokens)
            self._timeline.set_strip(start, end, count)
            worker = FilmstripWorker(
                self._media.path,
                start,
                end,
                count,
                (FILM_CELL_WIDTH, FILM_HEIGHT),
                tools,
                self._strip_token,
            )
            worker.signals.strip.connect(self._on_strip)
            self._runner.start(worker, worker.signals.done)
            self._strip_worker = worker

        if self._media.has_audio:
            self._wave_token = next(self._tokens)
            worker_wave = WaveformWorker(
                self._media.path,
                start,
                end - start,
                (width, WAVE_HEIGHT),
                self._colors["accent"],
                tools,
                self._wave_token,
            )
            worker_wave.signals.waveform.connect(
                lambda token, png, a=start, b=end: self._on_waveform(token, png, a, b)
            )
            self._runner.start(worker_wave, worker_wave.signals.done)

    def _on_strip(self, token: int, index: int, frame: object) -> None:
        if token != self._strip_token:
            return
        self._timeline.set_strip_image(
            index, image_from_frame(frame.data, frame.width, frame.height)
        )

    def _on_waveform(self, token: int, png: bytes, start: float, end: float) -> None:
        if token != self._wave_token:
            return
        image = QImage()
        if image.loadFromData(png, "PNG"):
            self._timeline.set_waveform(image, start, end)

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------

    def _on_scrub(self, seconds: float) -> None:
        self._stop_playback()
        self._request_frame()
        self._update_time_labels()

    def _seek_to(self, seconds: float) -> None:
        if self._media is None:
            return
        self._stop_playback()
        self._timeline.set_position(seconds)
        # O som acompanha o cursor mesmo parado: sem isto, o play seguinte
        # começaria pedindo ao player para saltar, e o primeiro instante sairia
        # do lugar errado.
        self._audio.seek(self._position)
        self._request_frame()
        self._update_time_labels()

    def _scrub_to(self, seconds: float) -> None:
        """Arrasto da barra de posição da tela cheia.

        Diferente dos botões de pular quadro ou segundo: ali parar é o
        esperado, aqui o vídeo deve continuar de onde a barra foi solta — é o
        que qualquer player faz.
        """
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
            # Um quadro atrás do cursor, senão "anterior" devolveria o keyframe
            # em que já estamos e o botão não faria nada.
            target = keyframe_at_or_before(
                self._keyframes, self._position - frame_step(self._fps)
            )
        else:
            target = keyframe_after(self._keyframes, self._position)
        if target is not None:
            self._seek_to(target)

    def _lock_readouts(self) -> None:
        """Fixa a largura dos números pelo maior valor que este arquivo terá.

        Medido no arquivo aberto, e não num gabarito de duas horas: um vídeo de
        um minuto não precisa reservar espaço para a casa das horas, e esse
        espaço faz falta para os botões na mesma linha.
        """
        biggest = format_timecode(self._duration)
        text = strings.EDIT_POSITION.format(current=biggest, total=biggest)
        self._time_label.setFixedWidth(
            QFontMetrics(self._time_label.font()).horizontalAdvance(text) + 6
        )

        frames = (
            strings.EDIT_FRAME_NUMBER.format(
                index=frame_index(self._duration, self._fps)
            )
            if self._fps
            else ""
        )
        self._frame_label.setFixedWidth(
            QFontMetrics(self._frame_label.font()).horizontalAdvance(frames) + 6
        )

    def _update_time_labels(self) -> None:
        self._time_label.setText(
            strings.EDIT_POSITION.format(
                current=format_timecode(self._position),
                total=format_timecode(self._duration),
            )
        )
        self._frame_label.setText(
            strings.EDIT_FRAME_NUMBER.format(
                index=frame_index(self._position, self._fps)
            )
            if self._fps
            else ""
        )
        self._sync_fullscreen()

    # ------------------------------------------------------------------
    # Tela cheia
    # ------------------------------------------------------------------

    def _toggle_fullscreen(self) -> None:
        if self._on_fullscreen:
            self._fullscreen.close()
            return
        if self._media is None or not self._has_video:
            return

        if self._fullscreen is None:
            self._fullscreen = FullscreenPreview(self)
            self._fullscreen.play_toggled.connect(self._toggle_play)
            self._fullscreen.stepped.connect(self._step_frame)
            self._fullscreen.seeked.connect(self._scrub_to)
            self._fullscreen.seek_finished.connect(self._resume_after_scrub)
            self._fullscreen.volume_changed.connect(self._volume.setValue)
            self._fullscreen.mute_toggled.connect(self._mute.setChecked)
            self._fullscreen.closed.connect(self._on_fullscreen_closed)

        self._fullscreen.set_audio(
            self._has_sound, self._volume.value(), self._mute.isChecked()
        )
        self._fullscreen.showFullScreen()
        self._fullscreen.activateWindow()
        self._fullscreen.setFocus()
        self._sync_fullscreen()
        # A superfície mudou de tamanho: o que está na tela veio pequeno demais
        # e é pedido de novo, agora na resolução da tela.
        self._restart_frames()

    def _on_fullscreen_closed(self) -> None:
        """Volta a desenhar no painel, no tamanho dele."""
        self._restart_frames()

    def _restart_frames(self) -> None:
        """Refaz a imagem para a superfície atual, tocando ou parada."""
        if self._playing:
            clip = self._clip_at(self._position)
            self._start_frames(self._position, clip.end if clip else self._duration)
        else:
            self._request_frame(force=True)

    def _sync_fullscreen(self) -> None:
        if self._on_fullscreen:
            self._fullscreen.set_state(self._position, self._duration, self._playing)

    # ------------------------------------------------------------------
    # Som
    # ------------------------------------------------------------------

    @property
    def _has_sound(self) -> bool:
        return (
            self._media is not None
            and self._media.has_audio
            and self._audio.available
        )

    def _on_volume(self, value: int) -> None:
        self._audio.set_volume(value)
        self._settings.preview_volume = value
        self._refresh_volume_label()

    def _on_mute(self, muted: bool) -> None:
        self._audio.set_muted(muted)
        self._settings.preview_muted = muted
        self._refresh_volume_label()
        self._save_audio_prefs()

    def _refresh_volume_label(self) -> None:
        silent = self._mute.isChecked() or self._volume.value() == 0
        self._mute.setText(strings.EDIT_MUTED if silent else strings.EDIT_SOUND)
        self._mute.setToolTip(
            strings.EDIT_UNMUTE if self._mute.isChecked() else strings.EDIT_MUTE
        )

    def _save_audio_prefs(self) -> None:
        try:
            self._settings.save()
        except OSError:
            # Perder a preferência de volume é um incômodo; interromper a edição
            # por causa dela seria um defeito.
            pass

    # ------------------------------------------------------------------
    # Reprodução
    # ------------------------------------------------------------------

    @property
    def _playable(self) -> bool:
        """Um arquivo só de áudio também se reproduz: o que anda é o cursor."""
        return self._media is not None and (self._has_video or self._has_sound)

    def _toggle_play(self) -> None:
        if not self._playable:
            return
        if self._playing:
            self._stop_playback()
            return
        self._start_playback(self._position)

    def _start_playback(self, seconds: float) -> None:
        if self._media is None:
            return
        clips = self._timeline.clips
        if not clips:
            return
        # No fim do arquivo, reproduzir recomeça do primeiro trecho — é o que
        # todo player faz, e o que permite reconferir o corte sem voltar à mão.
        if seconds >= self._duration - frame_step(self._fps):
            seconds = clips[0].start
        clip = self._clip_at(seconds)
        if clip is None:
            # Cursor num vão: o que foi apagado não se reproduz, então a prévia
            # começa no trecho seguinte.
            clip = next((item for item in clips if item.start >= seconds), None)
            if clip is None:
                return
            seconds = clip.start
            self._timeline.set_position(seconds)

        self._playing = True
        self._refresh_play_button()
        self._start_frames(seconds, clip.end)
        if self._has_sound:
            self._audio.play(seconds)
            self._tick.start()

    def _start_frames(self, seconds: float, until: float) -> None:
        """Abre o fluxo de quadros a partir de um instante."""
        tools = self._ensure_tools()
        if tools is None or self._media is None or not self._has_video:
            return
        if self._playback is not None:
            self._playback.cancel()
        self._shown_frame = seconds
        self._play_token = next(self._tokens)
        worker = PlaybackWorker(
            self._media.path,
            seconds,
            self._preview_size(playing=True),
            tools,
            self._play_token,
            stop_at=until,
        )
        worker.signals.frame.connect(self._on_frame)
        worker.signals.done.connect(
            lambda token=self._play_token: self._on_playback_done(token)
        )
        self._runner.start(worker, worker.signals.done)
        self._playback = worker

    def _on_audio_tick(self) -> None:
        """O relógio do som arrasta o cursor, o trecho e a imagem atrás dele.

        Enquanto há som, é ele quem diz onde a reprodução está: o ouvido percebe
        um engasgo de vinte milissegundos no áudio, e não percebe um quadro
        repetido na imagem. Com a tela seguindo o som, um computador que não dá
        conta de decodificar em tempo real perde quadros — e continua tocando no
        tempo certo, que é o comportamento de qualquer player.
        """
        if not self._playing or not self._has_sound:
            return
        position = self._audio.position
        self._timeline.set_position(position)
        self._update_time_labels()

        clip = self._clip_at(position)
        if clip is None or position >= clip.end:
            self._advance_clip(position)
            return

        # A imagem se corrige contra o som quando os dois se afastam demais.
        drift = abs(self._shown_frame - position)
        agora = self._audio.position
        if (
            self._has_video
            and drift > _MAX_DRIFT
            and agora - self._resynced_at > _RESYNC_COOLDOWN
        ):
            self._resynced_at = agora
            self._start_frames(position, clip.end)

    def _advance_clip(self, position: float) -> None:
        """Salta o que foi apagado e segue no trecho seguinte."""
        following = next(
            (clip for clip in self._timeline.clips if clip.start > position), None
        )
        if following is None:
            self._stop_playback()
            return
        self._timeline.set_position(following.start)
        if self._has_sound:
            self._audio.seek(following.start)
            self._start_frames(following.start, following.end)
        else:
            self._start_playback(following.start)

    def _on_playback_done(self, token: int) -> None:
        """O fluxo de quadros acabou.

        Sem som, é este o sinal de que o trecho terminou — o fluxo é o único
        relógio que existe. Com som, quem decide a passagem de trecho é o tique
        do áudio, e aqui não há nada a fazer: os quadros acabaram porque o
        trecho está no fim, ou porque uma correção de sincronia trocou o fluxo.
        """
        if token != self._play_token or not self._playing or self._has_sound:
            return
        self._advance_clip(self._position)

    def _stop_playback(self) -> None:
        self._tick.stop()
        self._audio.pause()
        if self._playback is not None:
            self._playback.cancel()
            self._playback = None
        if self._playing:
            self._playing = False
            self._play_token = 0
            # O quadro parado é pedido de novo: o último quadro do fluxo é o de
            # onde a reprodução parou, mas em tamanho e instante aproximados.
            self._request_frame(force=True)
        self._refresh_play_button()

    def _refresh_play_button(self) -> None:
        """Ícone e dica do botão central, que muda de papel conforme o estado."""
        self._play_button.setEnabled(self._playable)
        self._play_button.setText("❚❚" if self._playing else "▶")
        if not self._playable:
            self._play_button.setToolTip(strings.EDIT_NO_PLAYBACK)
            return
        label = strings.EDIT_PAUSE if self._playing else strings.EDIT_PLAY
        self._play_button.setToolTip(f"{label}  (Espaço)")

    # ------------------------------------------------------------------
    # Edição dos trechos
    # ------------------------------------------------------------------

    def _clip_at(self, seconds: float) -> Segment | None:
        return next(
            (clip for clip in self._timeline.clips if clip.contains(seconds)), None
        )

    def _remember(self) -> None:
        """Guarda o estado atual para o desfazer."""
        self._history.append(self._timeline.clips)
        self._future.clear()
        del self._history[:-50]

    def _split_here(self) -> None:
        """A tesoura: divide no cursor o trecho que estiver embaixo dele."""
        clips = self._timeline.clips
        position = self._position
        index = next(
            (i for i, clip in enumerate(clips) if clip.contains(position)), -1
        )
        if index < 0:
            return
        pieces = clips[index].split_at(position)
        if len(pieces) == 1:
            return  # cursor colado na ponta: não há o que dividir
        self._remember()
        self._timeline.set_clips(
            clips[:index] + pieces + clips[index + 1:], selected=index + 1
        )
        self._after_edit()

    def _delete_selected(self) -> None:
        clips = self._timeline.clips
        index = self._timeline.selected
        if not 0 <= index < len(clips):
            return
        self._remember()
        self._timeline.set_clips(
            clips[:index] + clips[index + 1:], selected=min(index, len(clips) - 2)
        )
        self._after_edit()

    def _undo_edit(self) -> None:
        if not self._history:
            return
        self._future.append(self._timeline.clips)
        self._timeline.set_clips(self._history.pop())
        self._after_edit()

    def _redo_edit(self) -> None:
        if not self._future:
            return
        self._history.append(self._timeline.clips)
        self._timeline.set_clips(self._future.pop())
        self._after_edit()

    def _on_clips_edited(self) -> None:
        self._after_edit()
        self._request_frame(force=True)

    def _after_edit(self) -> None:
        self._sync_clip_fields()
        self._update_controls()

    def _mark(self, edge: str) -> None:
        """Move a ponta do trecho selecionado para o cursor (teclas I e O)."""
        self._move_edge(edge, self._position)

    def _apply_field(self, edge: str) -> None:
        """Aplica o timecode digitado à ponta correspondente."""
        field = self._start_field if edge == "inicio" else self._end_field
        value = parse_timecode(field.text())
        if value is None:
            self._sync_clip_fields()  # devolve o valor válido de antes
            return
        self._move_edge(edge, min(max(0.0, value), self._duration))

    def _move_edge(self, edge: str, seconds: float) -> None:
        """Caminho único das duas formas de mover uma ponta sem arrastar.

        Quem decide até onde a ponta pode ir é a linha do tempo, que é dona dos
        trechos e conhece os vizinhos — a mesma regra do arrasto da alça.
        """
        if self._timeline.selected_clip is None:
            return
        self._remember()
        if not self._timeline.set_edge(self._timeline.selected, edge, seconds):
            self._history.pop()
            return
        self._after_edit()

    def _sync_clip_fields(self) -> None:
        clip = self._timeline.selected_clip
        self._start_field.setText(format_timecode(clip.start) if clip else "")
        self._end_field.setText(format_timecode(clip.end) if clip else "")
        self._duration_label.setText(
            format_span(clip.duration) if clip else strings.EDIT_CLIP_NONE
        )

    # ------------------------------------------------------------------
    # Zoom e barra de rolagem
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
            # Sem trecho escondido não há o que rolar: a barra fica desabilitada
            # em vez de sumir, para a linha do tempo não pular de altura.
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
        fast = self._fast.isChecked()
        self._timeline.set_show_keyframes(fast)
        # Juntar trechos exige recodificar: no modo rápido a opção sai de cena
        # em vez de falhar depois, já com a tarefa na fila.
        allowed = not fast or len(self._timeline.clips) < 2
        self._join.setEnabled(allowed)
        if not allowed and self._join.isChecked():
            self._each.setChecked(True)
        self._update_plan()

    def _current_target(self, segments: tuple[Segment, ...]) -> TrimTarget:
        mode = CutMode.FAST if self._fast.isChecked() else CutMode.EXACT
        anchor = (
            keyframe_at_or_before(self._keyframes, segments[0].start)
            if mode is CutMode.FAST and segments
            else None
        )
        return TrimTarget(
            segments=segments,
            container=self._container(),
            mode=mode,
            anchor=anchor,
        )

    def _container(self) -> str:
        """O recorte preserva o formato da origem.

        Trocar de container é o trabalho da aba de conversão, e misturá-lo aqui
        traria de volta a pergunta que o recorte não precisa fazer: o codec de
        origem cabe no formato novo?
        """
        suffix = self._media.path.suffix.lstrip(".").lower() if self._media else "mp4"
        return suffix or "mp4"

    def _export_targets(self) -> list[tuple[TrimTarget, str]]:
        """Os pedidos a enfileirar, com o sufixo do nome de cada arquivo."""
        clips = self._timeline.clips
        if not clips:
            return []
        # Com um trecho só as duas opções dão no mesmo: um arquivo, sem junção.
        joining = self._join.isChecked() and self._join.isEnabled()
        if joining or len(clips) == 1:
            return [(self._current_target(clips), strings.EDIT_SUFFIX_ONE)]
        return [
            (
                self._current_target((clip,)),
                strings.EDIT_SUFFIX_MANY.format(index=number),
            )
            for number, clip in enumerate(clips, start=1)
        ]

    def _update_plan(self) -> None:
        targets = self._export_targets()
        if self._media is None or not targets:
            self._plan.setText("")
            self._warning.setVisible(False)
            self._export.setEnabled(False)
            self.changed.emit()
            return

        first = targets[0][0]
        plan = describe_trim(self._media, first)
        if len(targets) > 1:
            plan = f"{len(targets)} arquivos · {plan}"
        self._plan.setText(strings.EDIT_PLAN.format(plan=plan))

        self._warning.setText(self._warning_text(first))
        self._warning.setVisible(bool(self._warning.text()))
        self._export.setEnabled(True)
        self.changed.emit()

    def _warning_text(self, target: TrimTarget) -> str:
        if target.mode is not CutMode.FAST:
            return ""
        if len(self._timeline.clips) > 1:
            return strings.EDIT_JOIN_NEEDS_REENCODE
        if target.anchor is None:
            return ""
        if target.drift < frame_step(self._fps):
            return strings.EDIT_DRIFT_NONE
        return strings.EDIT_DRIFT.format(
            time=format_timecode(target.anchor), delta=format_span(target.drift)
        )

    def _update_controls(self) -> None:
        loaded = self._media is not None
        clips = self._timeline.clips
        for widget in (
            *self._buttons,
            *self._mark_buttons,
            self._split,
            self._delete,
            self._start_field,
            self._end_field,
            self._timeline,
            self._scroll,
        ):
            widget.setEnabled(loaded)
        if loaded:
            for button in (self._prev_key, self._next_key):
                button.setEnabled(bool(self._keyframes))
        self._refresh_play_button()
        # O controle de volume some de cena quando não há som para controlar —
        # arquivo sem trilha de áudio, ou pacote sem o módulo de multimídia.
        for widget in (self._mute, self._volume):
            widget.setEnabled(self._has_sound)
        # Sem imagem não há o que ampliar.
        self._fullscreen_button.setEnabled(loaded and self._has_video)
        if self._on_fullscreen:
            self._fullscreen.set_audio(
                self._has_sound, self._volume.value(), self._mute.isChecked()
            )
        self._undo.setEnabled(bool(self._history))
        self._redo.setEnabled(bool(self._future))
        self._delete.setEnabled(loaded and len(clips) > 1)
        self._count_label.setText(
            strings.EDIT_CLIP_COUNT.format(
                count=len(clips),
                duration=format_span(sum(clip.duration for clip in clips)),
            )
            if loaded
            else ""
        )
        self._open.setText(strings.EDIT_REPLACE if loaded else strings.EDIT_OPEN)
        self._lock_readouts()
        self._update_time_labels()
        self._sync_clip_fields()
        self._sync_scrollbar()
        self._on_mode_changed()

    def _enqueue(self) -> None:
        if self._media is None:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        targets = self._export_targets()
        if not targets:
            QMessageBox.information(
                self, strings.DIALOG_WARNING_TITLE, strings.EDIT_NO_CLIPS
            )
            return

        dest_dir = (
            None
            if self._same_folder.isChecked()
            else self._settings.resolved_download_dir()
        )
        jobs: list[Job] = []
        for target, suffix in targets:
            destination = output_path(self._media.path, target, dest_dir, suffix)
            jobs.append(
                Job(
                    url=str(self._media.path),
                    title=destination.name,
                    description=describe_trim(self._media, target),
                    kind=JobKind.TRIM,
                    opts={
                        "media": self._media,
                        "target": target,
                        "destination": destination,
                        "tools": tools,
                    },
                    warnings=(self._warning.text(),) if self._warning.text() else (),
                )
            )
        self.jobs_ready.emit(jobs)
