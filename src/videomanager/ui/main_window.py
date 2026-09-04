"""Janela principal: três abas de trabalho sobre uma fila só.

**Download** — endereço e destino no topo, qualidade à esquerda, perfis rápidos
à direita —, **Convert**, para arquivos que já estão no disco, e **Editar**, que
recorta vídeo. As três enfileiram no mesmo lugar, e por isso a **fila fica fora
das abas**, embaixo: trocar de aba não esconde o que está em andamento.

A exceção é o editor, onde a fila sai de cena para o vídeo ocupar a janela: ali
não se fica esperando tarefa, se trabalha — e a barra de status continua
contando o que roda (ver :meth:`MainWindow._on_tab_changed`).

As duas linhas do topo da aba de download ("de onde" e "para onde") dividem a
mesma grade: rótulos numa coluna, campos noutra, botões encostados na direita.
É o que faz os dois campos começarem e terminarem exatamente na mesma coluna.
"""

from __future__ import annotations

from pathlib import Path

import yt_dlp
from platformdirs import user_cache_dir
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_DISPLAY_NAME, APP_NAME, __version__
from ..core import hwaccel
from ..core.binaries import FFmpegTools, find_tools
from ..core.job import Job, JobStatus
from ..core.models import FormatMatrix, MediaInfo, Mode, PlaylistInfo
from ..core.selector import (
    AudioRequest,
    VideoRequest,
    build_opts,
    describe_request,
)
from ..core.settings import Settings
from ..workers.engine_worker import EngineUpdateWorker, is_packaged
from ..workers.hwaccel_worker import HardwareProbeWorker
from ..workers.probe_worker import ProbeWorker
from ..workers.queue import JobQueue
from ..workers.runner import WorkerRunner
from . import strings
from .ffmpeg_setup import ensure_ffmpeg
from .panels.convert_panel import ConvertPanel
from .panels.edit_panel import EditPanel
from .panels.media_card import MediaCard
from .panels.profiles_panel import Profile, ProfilesPanel
from .panels.quality_panel import QualityPanel
from .panels.queue_panel import QueuePanel
from .playlist_dialog import PlaylistDialog
from .settings_dialog import SettingsDialog
from .theme import qpalette, stylesheet

# Índices das abas, na ordem em que são criadas.
_TAB_DOWNLOAD = 0
_TAB_CONVERT = 1
_TAB_EDIT = 2
# Sem margem lateral: o conteúdo da aba fica na mesma coluna da fila, que está
# fora das abas. Em cima, só o respiro que separa da barra de abas.
_TAB_MARGINS = (0, 10, 0, 0)
_TAB_SPACING = 10
# Quanto tempo o aviso de "adicionado à fila" fica na barra de status.
_ENQUEUED_MS = 5000

# Espera antes de sondar a placa. A janela aparece primeiro: a sondagem abre
# processos de ffmpeg, e disputá-los com a montagem da tela atrasaria
# justamente o que o usuário está esperando ver.
_PROBE_DELAY_MS = 1500


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._tools: FFmpegTools | None = None
        self._media: MediaInfo | None = None
        self._probe_worker: ProbeWorker | None = None
        self._runner = WorkerRunner()
        # A sondagem da placa é uma vez por execução (ver
        # :meth:`_warm_hardware_probe`).
        self._probed_hardware = False
        self._split_by_user = False
        self._balancing = False
        # Diretório temporário próprio: mantém .part e fragmentos fora da pasta
        # de destino, que só recebe arquivo pronto.
        #
        # Fica no cache do usuário, e **não** em /tmp, pelos mesmos dois motivos
        # que levaram ``ParallelExport`` a fugir de lá. Em muitas distribuições
        # /tmp é tmpfs, ou seja memória: um download de vários GB passaria
        # inteiro pela RAM, que é o recurso que esta aplicação já esgotou uma
        # vez. E "/tmp/videomanager" é um caminho fixo dentro de um diretório em
        # que todo usuário da máquina escreve — quem chegasse antes decidiria o
        # que há lá dentro, ou impediria o download por falta de permissão.
        self._temp_dir = Path(user_cache_dir(APP_NAME, appauthor=False)) / "temp"

        self.setWindowTitle(f"{APP_DISPLAY_NAME} {__version__}")
        # Altura escolhida para caber a aba inteira sem rolagem — barra de abas,
        # cabeçalho e controles — com a fila mostrando quatro linhas. Quem manda
        # na conta é a aba de edição, a mais alta das três: cada pixel a mais
        # aqui vira prévia maior lá (ver :meth:`_balance_panes`), e abaixo disto
        # o editor nasceria com o botão de exportar fora da vista. O teto é a
        # tela de 1080p com barra de tarefas. Em telas mais baixas o painel
        # rola, que é para isso que ele está numa área de rolagem.
        self.resize(1180, 1000)

        self._queue = JobQueue(settings, self)
        self._queue.counts_changed.connect(self._update_status)

        self._build_ui()
        self._build_menu()
        self._update_menu_scope(_TAB_DOWNLOAD)
        self._update_status()
        # Depois de a janela aparecer, e não durante a montagem: o que se ganha
        # é tempo na primeira exportação, e não vale pagá-lo na abertura.
        QTimer.singleShot(_PROBE_DELAY_MS, self._warm_hardware_probe)

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # A fila fica fora das abas, embaixo: todas alimentam a mesma fila, e
        # trocar de aba não pode esconder o que está em andamento — salvo no
        # editor, onde ela dá lugar à prévia (ver :meth:`_on_tab_changed`).
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_download_tab(), strings.TAB_DOWNLOAD)
        self._convert = ConvertPanel(self._settings, self._tools_for_convert)
        self._convert.jobs_ready.connect(self._submit_jobs)
        self._convert.changed.connect(self._balance_panes)
        self._tabs.addTab(self._wrap_tab(self._convert), strings.TAB_CONVERT)
        self._edit = EditPanel(self._settings, self._tools_for_convert)
        self._edit.jobs_ready.connect(self._submit_jobs)
        self._edit.changed.connect(self._balance_panes)
        self._tabs.addTab(self._wrap_tab(self._edit), strings.TAB_EDIT)

        self._vertical = QSplitter(Qt.Orientation.Vertical)
        self._vertical.addWidget(self._tabs)
        self._queue_panel = QueuePanel(self._queue)
        self._vertical.addWidget(self._queue_panel)
        # Os controles têm altura natural — passar disso só deixa espaço vazio.
        # A fila, ao contrário, aproveita cada pixel: é o painel que o usuário
        # fica olhando depois de enfileirar. Por isso a sobra vai toda para
        # baixo, e a divisão é refeita a cada mudança de tamanho enquanto o
        # usuário não assumir o divisor (ver :meth:`_balance_panes`).
        self._vertical.setStretchFactor(0, 0)
        self._vertical.setStretchFactor(1, 1)
        self._vertical.setChildrenCollapsible(False)
        self._vertical.installEventFilter(self)
        self._vertical.splitterMoved.connect(self._on_split_moved)
        # A divisão do editor é diferente da das outras abas (ver
        # :meth:`_balance_panes`), então trocar de aba pede um novo cálculo.
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._vertical, 1)

    def _build_download_tab(self) -> QWidget:
        """Endereço, destino, controles de qualidade e perfis rápidos."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(*_TAB_MARGINS)
        layout.setSpacing(_TAB_SPACING)

        self._header = self._build_header()
        layout.addWidget(self._header)

        self._left_pane = self._build_left_pane()
        self._right_pane = self._build_right_pane()
        self._middle = QSplitter(Qt.Orientation.Horizontal)
        self._middle.addWidget(self._left_pane)
        self._middle.addWidget(self._right_pane)
        self._middle.setStretchFactor(0, 1)
        self._middle.setStretchFactor(1, 0)
        self._middle.setSizes([820, 300])
        self._middle.setChildrenCollapsible(False)
        layout.addWidget(self._wrap_scrollable(self._middle), 1)
        return tab

    @staticmethod
    def _wrap_tab(inner: QWidget) -> QWidget:
        """Dá à aba a mesma margem e a mesma rolagem da outra."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(*_TAB_MARGINS)
        layout.setSpacing(_TAB_SPACING)
        layout.addWidget(MainWindow._wrap_scrollable(inner))
        return tab

    def _on_split_moved(self, *_: int) -> None:
        self._split_by_user = not self._balancing

    def _on_tab_changed(self, index: int) -> None:
        """A fila sai de cena no editor, e a janela inteira vira área de trabalho.

        A regra da fila sempre à vista existe para as duas abas que **produzem**
        tarefas e vão embora: quem manda baixar quer acompanhar. O editor é o
        contrário — é onde se fica, e cada pixel que a fila ocupa lá sai da
        imagem que está sendo cortada.

        Nada se perde: a barra de status continua contando o que está em
        andamento, na fila e concluído, e a fila volta inteira em qualquer outra
        aba, com as tarefas que entraram enquanto ela estava escondida.
        """
        self._queue_panel.setVisible(index != _TAB_EDIT)
        self._balance_panes()
        self._update_menu_scope(index)

    def _tabs_height(self) -> int:
        """Altura pedida pelas abas: a maior de todas, para todas caberem.

        É a mesma para todas de propósito. A fila fica sempre na mesma linha, o
        divisor não pula ao trocar de aba, e nenhuma delas nasce cortada — que
        era o que acontecia quando a altura vinha só da aba de download e a de
        conversão precisava de mais. Quem quiser outra divisão arrasta o
        divisor; a partir daí a escolha é do usuário.

        A aba de edição pede mais que as outras, e é ela quem manda quando cabe:
        o teto continua sendo a altura mínima da fila (ver :meth:`_balance_panes`),
        então em tela baixa ninguém fica sem espaço — o editor é que passa a
        rolar.
        """
        page = self._tabs.widget(_TAB_DOWNLOAD)
        # A barra de abas entra na conta: o que o divisor reparte é o QTabWidget
        # inteiro, não a página. A medida sai da página **visível** — a escondida
        # guarda a geometria de antes do último redimensionamento, e a diferença
        # ia crescendo a cada troca de aba.
        visible = self._tabs.currentWidget()
        chrome = (
            max(0, self._tabs.height() - visible.height()) if visible.height() else 0
        )
        margins = page.layout().contentsMargins()
        inner = margins.top() + margins.bottom()

        controls = max(
            self._pane_height(self._left_pane),
            self._pane_height(self._right_pane),
        )
        download = inner + self._header.sizeHint().height() + _TAB_SPACING + controls
        convert = inner + self._pane_height(self._convert)
        edit = inner + self._pane_height(self._edit)
        return chrome + max(download, convert, edit)

    @staticmethod
    def _pane_height(pane: QWidget) -> int:
        """Altura de que o painel precisa na largura que ele tem agora.

        O ``sizeHint`` de um painel com texto que quebra linha é calculado numa
        largura estreita, e sobra altura: o título do card cabe numa linha só na
        largura real. Perguntar pela largura de agora evita reservar espaço em
        cima que a fila usaria melhor.
        """
        layout = pane.layout()
        if layout is not None and layout.hasHeightForWidth() and pane.width() > 0:
            return layout.heightForWidth(pane.width())
        return pane.sizeHint().height()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        # A geometria de verdade do divisor só existe no primeiro redimensiona-
        # mento — nem no showEvent, nem num timer logo depois dele.
        if watched is self._vertical and event.type() == QEvent.Type.Resize:
            self._balance_panes()
        return super().eventFilter(watched, event)

    def _balance_panes(self) -> None:
        """Dá aos controles a altura que eles pedem e a sobra para a fila.

        O ``QSplitter`` reparte o espaço em proporção ao tamanho corrente de
        cada painel, e não ao que cada um pede: sem esta correção os controles
        nasciam cortados no meio de uma linha, com a fila vazia logo abaixo.
        Quando a janela é baixa demais para os dois, a fila fica com o mínimo
        dela e os controles passam a rolar.

        **Na aba de edição não há divisão**: a fila fica escondida (ver
        :meth:`_on_tab_changed`) e a janela inteira é do editor, onde toda
        altura sobrando vira prévia maior. Nas outras duas, sobra vira espaço
        vazio — os controles têm tamanho natural e param de crescer.

        Vale enquanto o usuário não arrastar o divisor: a partir daí a divisão é
        escolha dele e não se mexe mais.
        """
        if self._split_by_user or self._balancing:
            return
        self._balancing = True
        try:
            # Mostrar ou esconder uma linha (a trilha de áudio, um aviso) só
            # muda a altura pedida quando o pedido de layout é entregue. Sem
            # entregá-lo aqui, mede-se o painel de antes da mudança.
            QApplication.sendPostedEvents(None, int(QEvent.Type.LayoutRequest))
            if not self._queue_panel.isVisible():
                # Fila escondida (aba de edição): não há divisão a fazer, o
                # painel de cima recebe a janela toda.
                self._vertical.setSizes([self._vertical.height(), 0])
                return
            total = self._vertical.height() - self._vertical.handleWidth()
            available = total - self._queue_panel.minimumSizeHint().height()
            top = max(0, min(self._tabs_height(), available))
            self._vertical.setSizes([top, total - top])
        finally:
            self._balancing = False

    @staticmethod
    def _wrap_scrollable(inner: QWidget) -> QScrollArea:
        """Torna roláveis as duas colunas de controles, juntas.

        A soma dos grupos tem altura mínima considerável. Em tela de notebook
        (768 px) isso empurraria a fila para fora da janela — pior: com só uma
        das colunas rolando, a outra sozinha já impedia a janela de encolher.
        Rolando as duas juntas, elas continuam alinhadas entre si e a fila
        continua visível em qualquer tela.
        """
        area = QScrollArea()
        area.setWidget(inner)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    def _build_header(self) -> QWidget:
        """Endereço e destino: duas linhas na mesma grade, tudo alinhado."""
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        # Só a coluna dos campos cresce; rótulos e botões ficam no tamanho deles,
        # nas mesmas colunas nas duas linhas.
        grid.setColumnStretch(1, 1)

        url_label = QLabel(strings.URL_LABEL)
        grid.addWidget(url_label, 0, 0)
        self._url = QLineEdit()
        self._url.setPlaceholderText(strings.URL_PLACEHOLDER)
        self._url.setClearButtonEnabled(True)
        self._url.returnPressed.connect(self._analyze)
        grid.addWidget(self._url, 0, 1)

        self._paste = QPushButton(strings.URL_PASTE_AND_ANALYZE)
        self._paste.clicked.connect(self._paste_and_analyze)
        grid.addWidget(self._paste, 0, 2)

        self._analyze_button = QPushButton(strings.URL_ANALYZE)
        self._analyze_button.setProperty("role", "primary")
        self._analyze_button.setDefault(True)
        self._analyze_button.clicked.connect(self._analyze)
        grid.addWidget(self._analyze_button, 0, 3)

        dest_label = QLabel(strings.DEST_LABEL)
        grid.addWidget(dest_label, 1, 0)
        self._dest = QLineEdit(self._settings.download_dir)
        self._dest.setToolTip(strings.DEST_TOOLTIP)
        self._dest.editingFinished.connect(self._on_dest_edited)
        grid.addWidget(self._dest, 1, 1)

        browse = QPushButton(strings.DEST_BROWSE)
        browse.clicked.connect(self._choose_dest)
        # Logo abaixo de "Colar e analisar", na mesma coluna e com a mesma
        # largura: os dois botões formam uma pilha só, ao lado dos dois campos.
        grid.addWidget(browse, 1, 2)

        return box

    def _build_left_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._card = MediaCard()
        layout.addWidget(self._card)

        self._quality = QualityPanel(self._settings)
        self._quality.changed.connect(self._update_add_button)
        # Trocar de modo ou fazer aparecer um aviso muda a altura do painel; a
        # divisão da janela acompanha, para nada ficar cortado.
        self._quality.changed.connect(self._balance_panes)
        layout.addWidget(self._quality)

        layout.addStretch(1)
        return pane

    def _build_right_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._profiles = ProfilesPanel()
        self._profiles.profile_chosen.connect(self._on_profile)
        layout.addWidget(self._profiles, 1)

        self._add_button = QPushButton(strings.ADD_TO_QUEUE)
        self._add_button.setProperty("role", "primary")
        self._add_button.setEnabled(False)
        self._add_button.setToolTip(strings.ADD_TO_QUEUE_TIP)
        self._add_button.clicked.connect(self._add_current_to_queue)
        layout.addWidget(self._add_button)

        return pane

    def _build_menu(self) -> None:
        self._file_menu = self.menuBar().addMenu(strings.MENU_FILE)
        self._file_menu.aboutToShow.connect(self._on_file_menu_about_to_show)
        self._tools_menu = self.menuBar().addMenu(strings.MENU_TOOLS)
        self._help_menu = self.menuBar().addMenu(strings.MENU_HELP)

        # Ações universais
        self._quit_action = QAction(strings.ACTION_QUIT, self)
        self._quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self._quit_action.triggered.connect(self.close)

        self._settings_action = QAction(strings.ACTION_SETTINGS, self)
        self._settings_action.triggered.connect(self._open_settings)

        self._about_action = QAction(strings.ACTION_ABOUT, self)
        self._about_action.triggered.connect(self._show_about)
        self._help_menu.addAction(self._about_action)

        # Ações da aba Download
        self._open_download_dest = QAction(strings.ACTION_OPEN_DOWNLOAD_DEST, self)
        self._open_download_dest.triggered.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._settings.resolved_download_dir()))
            )
        )
        self._update_engine_action = QAction(strings.ACTION_UPDATE_ENGINE, self)
        self._update_engine_action.triggered.connect(self._update_engine)
        if is_packaged():
            self._update_engine_action.setEnabled(False)
            self._update_engine_action.setToolTip(strings.DIALOG_ENGINE_PACKAGED)

        # Ações da aba Converter
        self._convert_add_action = QAction(strings.ACTION_CONVERT_ADD, self)
        self._convert_add_action.triggered.connect(self._convert._choose_files)

        self._convert_remove_action = QAction(strings.ACTION_CONVERT_REMOVE, self)
        self._convert_remove_action.triggered.connect(self._convert._remove_selected)

        self._convert_clear_action = QAction(strings.ACTION_CONVERT_CLEAR, self)
        self._convert_clear_action.triggered.connect(self._convert.clear_files)

        self._convert_open_dest = QAction(strings.ACTION_OPEN_CONVERT_DEST, self)
        self._convert_open_dest.triggered.connect(self._open_convert_dest)

        # Ações da aba Editar
        self._new_proj_action = QAction(strings.ACTION_NEW_PROJECT, self)
        self._new_proj_action.triggered.connect(self._new_project)

        self._open_proj_action = QAction(strings.ACTION_OPEN_PROJECT, self)
        self._open_proj_action.triggered.connect(self._open_project)

        self._save_proj_action = QAction(strings.ACTION_SAVE_PROJECT, self)
        self._save_proj_action.triggered.connect(self._save_project)

        self._save_as_proj_action = QAction(strings.ACTION_SAVE_PROJECT_AS, self)
        self._save_as_proj_action.triggered.connect(self._save_project_as)

        self._import_media_action = QAction(strings.ACTION_IMPORT_MEDIA, self)
        self._import_media_action.triggered.connect(self._edit.import_media_dialog)

        self._export_action = QAction(strings.ACTION_EXPORT_VIDEO, self)
        self._export_action.triggered.connect(self._edit._open_export_dialog)

    def _on_file_menu_about_to_show(self) -> None:
        if self._tabs.currentIndex() == _TAB_CONVERT:
            self._convert_remove_action.setEnabled(bool(self._convert._list.selectedItems()))
            self._convert_clear_action.setEnabled(bool(self._convert._media))

    def _update_menu_scope(self, index: int) -> None:
        if not hasattr(self, "_file_menu"):
            return

        self._file_menu.clear()
        self._tools_menu.clear()

        # Configurações gerais sempre presentes em Ferramentas
        self._tools_menu.addAction(self._settings_action)

        if index == _TAB_DOWNLOAD:
            # Desativa atalhos de outras abas
            self._convert_add_action.setShortcut(QKeySequence())
            self._new_proj_action.setShortcut(QKeySequence())
            self._open_proj_action.setShortcut(QKeySequence())
            self._save_proj_action.setShortcut(QKeySequence())
            self._save_as_proj_action.setShortcut(QKeySequence())
            self._import_media_action.setShortcut(QKeySequence())
            self._export_action.setShortcut(QKeySequence())

            # Arquivo na aba Download
            self._file_menu.addAction(self._open_download_dest)
            self._file_menu.addSeparator()
            self._file_menu.addAction(self._quit_action)

            # Ferramentas na aba Download (motor de download yt-dlp)
            self._tools_menu.addAction(self._update_engine_action)

        elif index == _TAB_CONVERT:
            # Ativa atalhos de conversão e limpa os de edição
            self._convert_add_action.setShortcut(QKeySequence("Ctrl+O"))
            self._new_proj_action.setShortcut(QKeySequence())
            self._open_proj_action.setShortcut(QKeySequence())
            self._save_proj_action.setShortcut(QKeySequence())
            self._save_as_proj_action.setShortcut(QKeySequence())
            self._import_media_action.setShortcut(QKeySequence())
            self._export_action.setShortcut(QKeySequence())

            # Arquivo na aba Conversão
            self._file_menu.addAction(self._convert_add_action)
            self._file_menu.addAction(self._convert_remove_action)
            self._file_menu.addAction(self._convert_clear_action)
            self._file_menu.addSeparator()
            self._file_menu.addAction(self._convert_open_dest)
            self._file_menu.addSeparator()
            self._file_menu.addAction(self._quit_action)

        elif index == _TAB_EDIT:
            # Limpa atalho de conversão e ativa atalhos de edição
            self._convert_add_action.setShortcut(QKeySequence())
            self._new_proj_action.setShortcut(QKeySequence("Ctrl+N"))
            self._open_proj_action.setShortcut(QKeySequence("Ctrl+O"))
            self._save_proj_action.setShortcut(QKeySequence("Ctrl+S"))
            self._save_as_proj_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
            self._import_media_action.setShortcut(QKeySequence("Ctrl+I"))
            self._export_action.setShortcut(QKeySequence("Ctrl+E"))

            # Arquivo na aba Edição
            self._file_menu.addAction(self._new_proj_action)
            self._file_menu.addAction(self._open_proj_action)
            self._file_menu.addAction(self._save_proj_action)
            self._file_menu.addAction(self._save_as_proj_action)
            self._file_menu.addSeparator()
            self._file_menu.addAction(self._import_media_action)
            self._file_menu.addAction(self._export_action)
            self._file_menu.addSeparator()
            self._file_menu.addAction(self._quit_action)

        self._tools_menu.setToolTipsVisible(True)

    # ------------------------------------------------------------------
    # Primeira execução
    # ------------------------------------------------------------------

    def bootstrap(self) -> None:
        """Garante o ffmpeg. Chamado depois de a janela aparecer."""
        self._tools = ensure_ffmpeg(self)
        self._update_status()

    # ------------------------------------------------------------------
    # Análise
    # ------------------------------------------------------------------

    def _paste_and_analyze(self) -> None:
        clipboard = QGuiApplication.clipboard()
        text = (clipboard.text() if clipboard else "").strip()
        if text:
            self._url.setText(text)
            self._analyze()

    def _analyze(self) -> None:
        if self._probe_worker is not None:
            self._cancel_analyze()
            return
        url = self._url.text().strip()
        if not url:
            return
        self._set_analyzing(True)
        worker = ProbeWorker(url, self._settings)
        self._probe_worker = worker
        worker.signals.finished.connect(self._on_probed)
        worker.signals.failed.connect(self._on_probe_failed)
        self._runner.start(worker, worker.signals.finished, worker.signals.failed)

    def _cancel_analyze(self) -> None:
        if self._probe_worker is not None:
            self._probe_worker.cancel()
            self._probe_worker = None
        self._set_analyzing(False)

    def _set_analyzing(self, busy: bool) -> None:
        self._analyze_button.setText(
            strings.URL_CANCEL if busy else strings.URL_ANALYZE
        )
        self._analyze_button.setToolTip(
            strings.URL_CANCEL_TIP if busy else ""
        )
        self._url.setEnabled(not busy)
        self._paste.setEnabled(not busy)

    def _on_probed(self, result: object) -> None:
        self._probe_worker = None
        self._set_analyzing(False)
        if isinstance(result, PlaylistInfo):
            self._handle_playlist(result)
            return
        if not isinstance(result, MediaInfo):
            return
        self._media = result
        self._card.set_media(result)
        self._quality.set_matrix(result.matrix)
        self._profiles.set_enabled(True)
        self._update_add_button()
        # A análise pode acrescentar a linha de trilha de áudio; a divisão da
        # janela é refeita para o painel continuar inteiro.
        self._balance_panes()

    def _on_probe_failed(self, message: str) -> None:
        self._probe_worker = None
        self._set_analyzing(False)
        QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, message)

    # ------------------------------------------------------------------
    # Enfileiramento
    # ------------------------------------------------------------------

    def _update_add_button(self) -> None:
        self._add_button.setEnabled(self._media is not None)
        if self._media is not None:
            self._add_button.setToolTip("")

    def _on_profile(self, profile: Profile) -> None:
        """Aplica o perfil e enfileira em seguida — um clique só."""
        if self._media is None:
            return
        self._quality.apply_profile(
            mode=profile.mode,
            height=profile.height,
            container=profile.container,
            audio_codec=profile.audio_codec,
            audio_quality=profile.audio_quality,
        )
        self._add_current_to_queue()

    def _add_current_to_queue(self) -> None:
        if self._media is None:
            return
        if not self._require_tools():
            return
        request = self._quality.build_request()
        self._enqueue(self._media, request)

    def _enqueue(self, media: MediaInfo, request: VideoRequest | AudioRequest) -> None:
        # Conferência de verdade, e não ``assert``: sob ``python -O`` o assert
        # some e o que sobraria seria um ``AttributeError`` lá dentro.
        if self._tools is None:
            return
        dest = self._settings.resolved_download_dir()
        opts, plan = build_opts(
            request, media, self._settings, self._tools, dest, self._temp_dir
        )
        job = Job(
            url=media.url,
            title=media.title,
            description=describe_request(request, plan),
            opts=opts,
            warnings=plan.warnings if plan else (),
        )
        self._queue.submit(job)

    def _require_tools(self) -> bool:
        """Bloqueia o enfileiramento sem ffmpeg, explicando o motivo."""
        if self._tools is not None:
            return True
        self._tools = ensure_ffmpeg(self)
        self._update_status()
        # O ffmpeg acabou de aparecer: a sondagem da placa, que na abertura não
        # tinha o que sondar, passa a ter.
        self._warm_hardware_probe()
        return self._tools is not None

    def _warm_hardware_probe(self) -> None:
        """Sonda os encoders de placa em segundo plano, uma vez por execução.

        A sondagem manda codificar um quadro de verdade, e custa de 0,5 s a
        3,4 s nesta máquina — o VAAPI daqui aborta o processo, e um aborto
        demora mais que uma recusa. Esse tempo caía no começo da primeira
        exportação, que é quando o usuário está esperando o resultado. Fazê-la
        aqui não a torna mais barata; muda quem espera por ela.

        Só acontece para quem pediu placa. Com a preferência em software não há
        nada a resolver na exportação, e sondar seria gastar processos por uma
        resposta que ninguém vai consultar — as configurações, que consultam,
        sondam por conta própria e sem travar (ver ``settings_dialog``).
        """
        if self._probed_hardware or self._settings.hardware_encoder == hwaccel.SOFTWARE:
            return
        # ``find_tools`` não provisiona nem abre diálogo: sem ffmpeg à mão,
        # simplesmente não há o que sondar ainda.
        tools = self._tools or find_tools()
        if tools is None:
            return
        self._probed_hardware = True
        worker = HardwareProbeWorker(tools)
        self._runner.start(worker, worker.signals.done)

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def _handle_playlist(self, playlist: PlaylistInfo) -> None:
        if not self._require_tools():
            return
        initial_audio = self._quality.mode is Mode.AUDIO_ONLY
        dialog = PlaylistDialog(playlist, initial_audio=initial_audio, parent=self)
        if dialog.exec() != PlaylistDialog.DialogCode.Accepted:
            return
        entries = dialog.selected_entries()
        if not entries:
            return

        if dialog.is_audio_mode():
            self._quality.set_mode(Mode.AUDIO_ONLY)
        else:
            self._quality.set_mode(Mode.VIDEO)

        # Cada item da playlist tem formatos próprios, então uma escolha por id
        # concreto não valeria para todos. O pedido vai por limite de resolução,
        # que o seletor resolve item a item na hora do download.
        height_limit = None if dialog.is_audio_mode() else dialog.height_limit()
        request = self._quality.build_batch_request(height_limit)
        for entry in entries:
            placeholder = MediaInfo(
                url=entry.url, title=entry.title, matrix=FormatMatrix()
            )
            self._enqueue(placeholder, request)

    # ------------------------------------------------------------------
    # Conversor local
    # ------------------------------------------------------------------

    def _tools_for_convert(self) -> FFmpegTools | None:
        """ffmpeg para a aba de conversão, provisionando na primeira vez.

        A aba é montada junto com a janela, antes de o ffmpeg ser procurado, e
        por isso pergunta por ele só na hora de inspecionar um arquivo.
        """
        self._require_tools()
        return self._tools

    def _submit_jobs(self, jobs: list[Job]) -> None:
        for job in jobs:
            self._queue.submit(job)
        if not jobs:
            return
        # Aviso na barra de status porque na aba de edição a fila está
        # escondida: sem ele, clicar em "Adicionar à fila" não teria resposta
        # nenhuma na tela. O texto sai depois de alguns segundos e a barra volta
        # a mostrar as contagens.
        self.statusBar().showMessage(
            strings.STATUS_ENQUEUED.format(count=len(jobs)), _ENQUEUED_MS
        )
        QTimer.singleShot(_ENQUEUED_MS + 100, self._update_status)

    # ------------------------------------------------------------------
    # Configurações e engine
    # ------------------------------------------------------------------

    def _choose_dest(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, strings.SETTINGS_DEST, self._dest.text() or str(Path.home())
        )
        if chosen:
            self._dest.setText(chosen)
            self._on_dest_edited()

    def _on_dest_edited(self) -> None:
        self._settings.download_dir = self._dest.text().strip() or self._settings.download_dir
        self._save_settings()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        previous_theme = self._settings.theme
        self._settings = dialog.result_settings()
        self._save_settings()
        self._queue.apply_settings(self._settings)
        self._edit.apply_settings(self._settings)
        self._dest.setText(self._settings.download_dir)
        if self._settings.theme != previous_theme:
            app = QApplication.instance()
            if app is not None:
                app.setPalette(qpalette(self._settings.theme))
                app.setStyleSheet(stylesheet(self._settings.theme))
        self._update_status()

    def _update_engine(self) -> None:
        if is_packaged():
            # O item de menu já nasce desligado; esta é a segunda tranca, para o
            # caso de a ação chegar por outro caminho. Ver ``EngineUpdateWorker``:
            # num pacote, o comando abriria uma segunda janela do aplicativo em
            # vez de instalar coisa alguma.
            QMessageBox.information(
                self, strings.DIALOG_ENGINE_TITLE, strings.DIALOG_ENGINE_PACKAGED
            )
            return
        current = yt_dlp.version.__version__
        answer = QMessageBox.question(
            self,
            strings.DIALOG_ENGINE_TITLE,
            strings.DIALOG_ENGINE_BODY.format(current=current),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        dialog = QProgressDialog(strings.DIALOG_ENGINE_RUNNING, "", 0, 0, self)
        dialog.setWindowTitle(strings.DIALOG_ENGINE_TITLE)
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)

        def on_finished(version: str, changed: bool) -> None:
            dialog.reset()
            if changed:
                QMessageBox.information(
                    self, strings.DIALOG_ENGINE_TITLE,
                    strings.DIALOG_ENGINE_DONE.format(version=version),
                )
            else:
                QMessageBox.information(
                    self, strings.DIALOG_ENGINE_TITLE,
                    strings.DIALOG_ENGINE_UPTODATE.format(version=version),
                )

        def on_failed(message: str) -> None:
            dialog.reset()
            QMessageBox.warning(
                self, strings.DIALOG_ENGINE_TITLE,
                strings.DIALOG_ENGINE_FAILED.format(error=message),
            )

        worker = EngineUpdateWorker(current)
        worker.signals.finished.connect(on_finished)
        worker.signals.failed.connect(on_failed)
        self._runner.start(worker, worker.signals.finished, worker.signals.failed)
        dialog.exec()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            strings.ABOUT_TITLE,
            strings.ABOUT_BODY.format(
                version=__version__, ytdlp=yt_dlp.version.__version__
            ),
        )

    # ------------------------------------------------------------------
    # Status e encerramento
    # ------------------------------------------------------------------

    def _update_status(self) -> None:
        active = self._queue.count_by_status(JobStatus.RUNNING, JobStatus.PROCESSING)
        pending = self._queue.count_by_status(JobStatus.PENDING)
        done = self._queue.count_by_status(JobStatus.DONE)
        parts = [strings.STATUS_COUNTS.format(active=active, pending=pending, done=done)]
        if self._tools is not None:
            parts.append(strings.STATUS_FFMPEG.format(source=self._tools.source))
        self.statusBar().showMessage("  |  ".join(parts))

    def _new_project(self) -> None:
        self._tabs.setCurrentIndex(_TAB_EDIT)
        self._edit.new_project()

    def _open_project(self) -> None:
        self._tabs.setCurrentIndex(_TAB_EDIT)
        self._edit.open_project()

    def _save_project(self) -> None:
        self._edit.save_project()

    def _save_project_as(self) -> None:
        self._edit.save_project_as()

    def _open_convert_dest(self) -> None:
        target_dir = self._settings.resolved_download_dir()
        if self._convert._same_folder.isChecked() and self._convert._media:
            target_dir = self._convert._media[0].path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_dir)))

    def closeEvent(self, event) -> None:  # noqa: N802
        """Confirma a saída quando há alterações não salvas ou tarefas em andamento."""
        if hasattr(self, "_edit") and self._edit.has_unsaved_changes:
            answer = QMessageBox.question(
                self,
                strings.PROJECT_MODIFIED_TITLE,
                strings.PROJECT_MODIFIED_BODY,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        unfinished = sum(1 for job in self._queue.jobs if not job.status.is_final)
        if unfinished:
            answer = QMessageBox.question(
                self,
                strings.DIALOG_QUIT_TITLE,
                strings.DIALOG_QUIT_BODY.format(count=unfinished),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        # Encerrar vem **antes** de salvar, e salvar não pode derrubar o
        # encerramento. ``Settings.save`` propaga ``OSError`` de propósito
        # (disco cheio, pasta de configuração somente leitura, perfil em rede
        # fora do ar), e a exceção saindo daqui pulava as duas linhas seguintes
        # — o ``QCloseEvent`` já nasce aceito, então a janela fechava assim
        # mesmo e sobravam ffmpeg órfãos e gravação truncada, exatamente o que
        # estas duas chamadas existem para evitar. Perder a última preferência é
        # incômodo; isso era defeito.
        #
        # A aba de edição tem processos próprios (prévia e mixagem) que a fila
        # não conhece: sem este aviso, eles ficam rodando depois da janela.
        self._edit.shutdown()
        self._queue.shutdown()
        self._save_settings()
        event.accept()

    def _save_settings(self) -> None:
        """Grava as preferências sem deixar uma falha de disco virar defeito.

        Todo lugar que salva passa por aqui: a gravação é secundária em relação
        ao que o usuário estava fazendo, e um ``OSError`` cru dentro de um slot
        do Qt vira traceback sem explicação nenhuma na tela.
        """
        try:
            self._settings.save()
        except OSError as exc:
            self.statusBar().showMessage(
                strings.STATUS_SETTINGS_FAILED.format(error=exc), _ENQUEUED_MS
            )
