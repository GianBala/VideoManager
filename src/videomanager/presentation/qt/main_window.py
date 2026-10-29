"""Janela principal: três abas de trabalho sobre uma fila só.

**Download** — endereço e destino no topo, qualidade à esquerda, perfis rápidos
à direita —, **Converter**, para arquivos que já estão no disco, e **Editar**, que
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

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videomanager import APP_TITLE
from videomanager import ISSUES_URL, RELEASES_URL, __version__, build_commit
from videomanager.application import encoding as hwaccel
from videomanager.application.capabilities import FFmpegTools
from videomanager.application.jobs.requests import DownloadRequest
from videomanager.application.preferences import Preferences
from dataclasses import asdict
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.models import JobStatus
from videomanager.domain.estimator import estimate_profile_size
from videomanager.domain.formats import FormatMatrix
from videomanager.domain.formats import MediaInfo
from videomanager.domain.formats import Mode
from videomanager.domain.formats import PlaylistInfo
from videomanager.domain.selection import AudioRequest
from videomanager.domain.selection import VideoRequest
from videomanager.application.preferences import Preferences as Settings
from videomanager.presentation.qt.tasks import WorkerRunner
from videomanager.application.formatting import DASH
from videomanager.presentation.qt import icons, strings, theme
from videomanager.presentation.qt.accessibility import name_controls
from videomanager.presentation.qt.i18n import apply_language, bind, on_language_change
from videomanager.presentation.qt.ffmpeg_setup import ensure_ffmpeg
from videomanager.presentation.qt.panels.address_bar import AddressBar
from videomanager.presentation.qt.panels.convert_panel import ConvertPanel
from videomanager.presentation.qt.panels.edit_panel import _EDITOR_MARGINS as EDITOR_MARGINS
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.panels.media_card import MediaCard
from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel
from videomanager.presentation.qt.panels.personalize_card import PersonalizeCard
from videomanager.presentation.qt.panels.profiles_panel import PROFILES, Profile
from videomanager.presentation.qt.panels.profiles_panel import ProfilesPanel
from videomanager.presentation.qt.panels.quality_panel import QualityPanel
from videomanager.presentation.qt.panels.queue_panel import DRAWER_WIDTH, QueuePanel
from videomanager.presentation.qt.playlist_dialog import PlaylistDialog
from videomanager.presentation.qt.settings_dialog import SettingsDialog
from videomanager.presentation.qt.nav_rail import LARGURA as LARGURA_DO_MENU, Paginas
from videomanager.presentation.qt.theme import EstiloDaBarraDeMenus
from videomanager.presentation.qt.theme import apply as aplicar_tema
from videomanager.presentation.qt.toast import ToastHost
from videomanager.presentation.qt.ports import DesktopRuntimePort

# Índices das abas, na ordem em que são criadas.
_TAB_DOWNLOAD = 0
_TAB_CONVERT = 1
_TAB_EDIT = 2
# No fim, e não ao lado da aba Converter: scripts de validação e testes situam o
# editor no índice 2, e a aba nova não desloca nenhum deles.
_TAB_METADATA = 3
# Sem margem lateral: o conteúdo da aba fica na mesma coluna da fila, que está
# fora das abas. Em cima, só o respiro que separa da barra de abas.
# Cada página decide a própria margem (a janela não tem mais uma moldura em volta de todas): as que ainda não foram
# redesenhadas mantêm o recuo de sempre (12 px de cada lado e 22 em cima, que eram os 12 da moldura mais 10); as que
# seguem o protótipo usam 28 px nas laterais, 24 em cima e embaixo e 18 entre os blocos.
_TAB_MARGINS = (12, 22, 12, 12)
_TAB_SPACING = 10
_PAGE_MARGINS = (28, 24, 28, 24)
_PAGE_SPACING = 18
# A aba Metadados tem a sua: 20 em cima e 22 embaixo, para o formulário e o rodapé caberem na janela padrão.
_METADATA_MARGINS = (28, 20, 28, 22)
# Quanto tempo o aviso de "adicionado à fila" fica na tela.
_ENQUEUED_MS = 5000

# Espera antes de sondar a placa. A janela aparece primeiro: a sondagem abre
# processos de ffmpeg, e disputá-los com a montagem da tela atrasaria
# justamente o que o usuário está esperando ver.
_PROBE_DELAY_MS = 1500


class _ProbeAttempt(QObject):
    """Recebe sinais na thread da janela e ignora análises já substituídas."""

    def __init__(self, window, worker):
        super().__init__(window)
        self.window = window
        self.worker = worker

    @Slot(object)
    def finished(self, result):
        if self.window._probe_worker is self.worker:
            self.window._on_probed(result)

    @Slot(object)
    def failed(self, message):
        if self.window._probe_worker is self.worker:
            self.window._on_probe_failed(message)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        *,
        editor,
        processing,
        downloads,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__()
        self._runtime = runtime
        self._settings = settings
        self._downloads = downloads
        self._processing = processing
        self._editor_service = editor
        self._tools: FFmpegTools | None = None
        self._media: MediaInfo | None = None
        self._probe_worker: object | None = None
        self._runner = WorkerRunner()
        # A sondagem da placa é uma vez por execução (ver
        # :meth:`_warm_hardware_probe`).
        self._probed_hardware = False
        # Se o usuário quer a gaveta de tarefas à vista. É uma vontade só, de todas as abas (ver :meth:`_apply_drawer`).
        self._drawer_open = True
        # A gaveta aberta numa janela estreita demais para ela (a janela cresce até caber), e o que a janela já mandou ao
        # painel (``None`` até a montagem terminar: os eventos de layout antes disso não contam).
        self._drawer_forced = False
        self._drawer_shown: bool | None = None
        # Filha da janela: um ``QTimer.singleShot`` com método seria entregue depois de a janela ser apagada.
        self._drawer_timer = QTimer(self)
        self._drawer_timer.setSingleShot(True)
        self._drawer_timer.setInterval(0)
        self._drawer_timer.timeout.connect(self._apply_drawer)
        # O estilo da barra de menus (letra de atalho sublinhada só com o Alt apertado). O widget não é dono do estilo e o
        # consulta até o último evento da destruição dele (o QMenuBar pergunta no ChildRemoved): o dono é o QApplication, que
        # sobrevive aos widgets. Só com a referência Python, o estilo era liberado antes e o processo caía no encerramento.
        self._menu_style = EstiloDaBarraDeMenus()
        self._menu_style.setParent(QApplication.instance())
        self.destroyed.connect(self._menu_style.deleteLater)
        self.installEventFilter(self)
        self.setWindowTitle(APP_TITLE)
        # Altura escolhida para caber a aba inteira sem rolagem. Quem manda na
        # conta é a aba de edição, a mais alta das quatro: cada pixel a mais
        # aqui vira prévia maior lá, e abaixo disto o editor nasceria com o
        # botão de exportar fora da vista. O teto é a tela de 1080p com barra de
        # tarefas. Em telas mais baixas o painel rola, que é para isso que ele
        # está numa área de rolagem.
        # 1180 px é o que o conteúdo sempre teve; o menu lateral é largura que não pode sair dele, senão o editor
        # (que pede 1191) nascia com 87 px de rolagem horizontal em vez dos 11 de antes.
        self.resize(1180 + LARGURA_DO_MENU, 1000)

        self._queue = self._runtime.queue(settings, self)
        self._queue.counts_changed.connect(self._update_tasks_badge)

        self._build_ui()
        self._toasts = ToastHost(self)
        self._build_menu()
        self._update_menu_scope(_TAB_DOWNLOAD)
        self._update_tasks_badge()
        on_language_change(self._retranslate)
        name_controls(self)
        # Depois de a janela aparecer, e não durante a montagem: o que se ganha
        # é tempo na primeira exportação, e não vale pagá-lo na abertura.
        QTimer.singleShot(_PROBE_DELAY_MS, self._warm_hardware_probe)

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        # O menu lateral fica à esquerda de tudo; a coluna do conteúdo (abas e fila) é a de sempre.
        moldura = QHBoxLayout(central)
        moldura.setContentsMargins(0, 0, 0, 0)
        moldura.setSpacing(0)
        conteudo = QWidget()
        conteudo.setProperty("role", "plain")
        self._content = conteudo
        root = QVBoxLayout(conteudo)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # As tarefas ficam fora das abas, numa gaveta à direita: todas as abas alimentam a mesma fila, e trocar
        # de aba não pode esconder o que está em andamento (ver :meth:`_apply_drawer`).
        self._tabs = Paginas()
        self._tabs.addTab(self._build_download_tab(), strings.TAB_DOWNLOAD)
        self._convert = ConvertPanel(self._settings, self._tools_for_convert, processing=self._processing, runtime=self._runtime)
        self._convert.jobs_ready.connect(self._submit_jobs)
        self._tabs.addTab(self._wrap_tab(self._convert, page=True), strings.TAB_CONVERT)
        self._edit = EditPanel(self._settings, self._tools_for_convert, editor=self._editor_service, processing=self._processing, runtime=self._runtime)
        self._edit.jobs_ready.connect(self._submit_jobs)
        self._tabs.addTab(self._wrap_tab(self._edit, horizontal=True, margins=EDITOR_MARGINS), strings.TAB_EDIT)
        # A aba nasce vazia e o painel entra na primeira visita: montado com a
        # janela, ele somava ~55 ms à abertura e ~6 ms a toda troca de idioma
        # (medido), para quem nunca abre a aba.
        self._metadata: MetadataPanel | None = None
        self._metadata_page = QWidget()
        self._metadata_page.setLayout(QVBoxLayout())
        self._metadata_page.layout().setContentsMargins(0, 0, 0, 0)
        self._tabs.addTab(self._metadata_page, strings.TAB_METADATA)

        self._queue_panel = QueuePanel(self._queue, runtime=self._runtime)
        self._queue_panel.hide_requested.connect(lambda: self._set_drawer(False))
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, 1)
        # Tarefas e Ajustes não são páginas: o primeiro liga e desliga a gaveta, o segundo abre o diálogo. Moram
        # no pé do menu, longe dos itens que trocam de aba.
        self._nav_tasks = self._tabs.rail.add_toggle(icons.task_list, strings.NAV_TASKS, self._set_drawer)
        self._nav_settings = self._tabs.rail.add_action(icons.nav_settings, strings.NAV_SETTINGS, self._open_settings)
        moldura.addWidget(self._tabs.rail)
        moldura.addWidget(conteudo, 1)
        moldura.addWidget(self._queue_panel)
        self._apply_drawer()
        # Sem foco inicial, o Qt entrega o foco ao primeiro da ordem de Tab — a
        # barra de abas —, e a aba Download abria com a borda de foco, como se
        # Tab já tivesse sido apertado. O foco nasce no widget central, que não
        # desenha nada: tirar a barra de abas do Tab custaria o teclado a quem
        # navega por ele, e clicar num vão da janela devolve o foco para cá.
        central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        central.setFocus()

    def _build_download_tab(self) -> QWidget:
        """Endereço e destino em cima, o que se baixa no meio (rola) e o resultado com a ação embaixo."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(*_PAGE_MARGINS)
        layout.setSpacing(_PAGE_SPACING)

        self._header = self._build_header()
        layout.addWidget(self._header)

        # A coluna do meio é o que rola; o rodapé fica fora dela, à vista, porque é onde está a ação.
        self._middle = QWidget()
        self._middle.setProperty("role", "plain")
        coluna = QVBoxLayout(self._middle)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(_PAGE_SPACING)
        self._card = MediaCard(runtime=self._runtime)
        coluna.addWidget(self._card)
        self._profiles = ProfilesPanel()
        self._profiles.profile_chosen.connect(self._on_profile)
        coluna.addWidget(self._profiles)
        # Recolher o "Personalizar" só esconde os campos: eles guardam o que foi escolhido, e o rodapé continua
        # enfileirando com isso.
        self._quality = QualityPanel(self._settings)
        self._quality.changed.connect(self._update_add_button)
        self._personalize = PersonalizeCard(self._quality)
        coluna.addWidget(self._personalize)
        coluna.addStretch(1)
        layout.addWidget(self._wrap_scrollable(self._middle), 1)
        layout.addWidget(self._build_footer())
        return tab

    def _retheme_header(self) -> None:
        self._dest_icon.setPixmap(icons.folder(theme.papeis(*theme.atual())["t3"], 16).pixmap(16, 16))

    def _retheme_footer(self) -> None:
        self._add_button.setIcon(icons.plus(theme.papeis(*theme.atual())["on_fill"], 18))

    def _build_footer(self) -> QWidget:
        """O resultado do que está escolhido, o tamanho estimado e a ação de enfileirar."""
        footer = QFrame()
        footer.setProperty("role", "footer")
        linha = QHBoxLayout(footer)
        linha.setContentsMargins(16, 12, 12, 12)
        linha.setSpacing(16)

        resultado = QVBoxLayout()
        resultado.setSpacing(2)
        legenda = bind(QLabel(), "setText", lambda: strings.RESULT_LABEL)
        legenda.setProperty("role", "micro")
        resultado.addWidget(legenda)
        self._result_summary = QLabel(DASH)
        self._result_summary.setProperty("role", "result")
        self._result_summary.setWordWrap(True)
        resultado.addWidget(self._result_summary)
        linha.addLayout(resultado, 1)

        tamanho = QHBoxLayout()
        tamanho.setSpacing(6)
        self._result_size = QLabel(DASH)
        self._result_size.setProperty("role", "result-size")
        tamanho.addWidget(self._result_size, 0, Qt.AlignmentFlag.AlignBottom)
        self._result_estimated = bind(QLabel(), "setText", lambda: strings.RESULT_ESTIMATED)
        self._result_estimated.setProperty("role", "dim")
        tamanho.addWidget(self._result_estimated, 0, Qt.AlignmentFlag.AlignBottom)
        linha.addLayout(tamanho)

        self._add_button = bind(QPushButton(), "setText", lambda: strings.ADD_TO_QUEUE)
        self._add_button.setProperty("role", "primary")
        self._add_button.setProperty("emphasis", "large")
        self._add_button.setEnabled(False)
        bind(self._add_button, "setToolTip", lambda: strings.ADD_TO_QUEUE_TIP)
        self._add_button.clicked.connect(self._add_current_to_queue)
        linha.addWidget(self._add_button)
        self._retheme_footer()
        theme.on_theme_change(self._retheme_footer)
        return footer

    @staticmethod
    def _wrap_tab(inner: QWidget, *, horizontal: bool = False, page: bool = False,
                  margins: tuple[int, int, int, int] | None = None) -> QWidget:
        """Dá à aba a mesma margem e a mesma rolagem da outra (``page``: a margem do protótipo, de 28 px)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(*(margins or (_PAGE_MARGINS if page else _TAB_MARGINS)))
        layout.setSpacing(_PAGE_SPACING if page else _TAB_SPACING)
        layout.addWidget(MainWindow._wrap_scrollable(inner, horizontal=horizontal))
        return tab

    def _retranslate(self) -> None:
        for index, text in enumerate((strings.TAB_DOWNLOAD, strings.TAB_CONVERT, strings.TAB_EDIT,
                                      strings.TAB_METADATA)):
            self._tabs.setTabText(index, text)
        self._nav_settings.set_text(strings.NAV_SETTINGS)
        self._nav_tasks.set_text(strings.NAV_TASKS)
        self._update_tasks_badge()
        self._update_footer()
        # Os nomes acessíveis tirados das dicas acompanham as dicas novas.
        name_controls(self)

    def _metadata_panel(self) -> MetadataPanel:
        """O painel da aba Metadados, criado na primeira vez que alguém o pede."""
        if self._metadata is None:
            self._metadata = MetadataPanel(self._settings, self._tools_for_convert, runtime=self._runtime)
            self._metadata_page.layout().addWidget(self._wrap_tab(self._metadata, page=True, margins=_METADATA_MARGINS))
            name_controls(self._metadata)
        return self._metadata

    def _on_tab_changed(self, index: int) -> None:
        # Na aba Metadados o painel nasce na primeira visita.
        if index == _TAB_METADATA:
            self._metadata_panel()
        # Abrir a gaveta numa janela estreita vale para a aba em que se pediu.
        self._drawer_forced = False
        self._apply_drawer()
        self._update_menu_scope(index)

    def _apply_drawer(self) -> None:
        """A gaveta de tarefas à vista, ou não, conforme a vontade do usuário e a largura da janela.

        A gaveta é uma só, e trocar de aba não a mexe: aberta numa aba, continua aberta nas outras, o editor e os
        Metadados incluídos; fechada, continua fechada. Quem baixa ou exporta e vai editar quer acompanhar a tarefa, e
        a gaveta está fora das abas justamente para isso. Houve uma vontade para Download e Converter e outra para o
        editor e os Metadados, e fechar numa não revogava a outra: com as duas abertas, a gaveta reaparecia ao voltar de
        uma aba para a outra, como se abrisse sozinha. Uma vontade só, e quem mexe nela em qualquer aba a muda para todas.

        Numa janela estreita ela também recolhe (ver :meth:`_narrow`), e a vontade do usuário fica como estava: quando
        há largura de novo, a gaveta volta. O contrário seria a janela presa em 840 px por uma coluna que ninguém pediu
        para ver naquele momento. ``_drawer_forced`` é o usuário pedindo a gaveta numa janela estreita demais (o item
        Tarefas, o aviso "Ver tarefas"): ela pede então os 344 px inteiros, e a janela cresce.
        """
        wanted = self._drawer_open and not self._narrow()
        visible = wanted or self._drawer_forced
        self._queue_panel.set_squeezable(not self._drawer_forced)
        if visible == self._drawer_shown:
            return
        self._drawer_shown = visible
        self._queue_panel.setVisible(visible)
        blocked = self._nav_tasks.blockSignals(True)
        self._nav_tasks.setChecked(visible)
        self._nav_tasks.blockSignals(blocked)

    def _narrow(self) -> bool:
        """Se falta largura para a gaveta ao lado do conteúdo: o menu, o mínimo que o conteúdo pede e os 344 px dela.

        O mínimo do conteúdo muda com o que está na tela (analisar um vídeo o alarga em ~100 px), por isso o limiar é
        medido a cada vez e não é um número fixo.
        """
        return self.width() < LARGURA_DO_MENU + self._content.minimumSizeHint().width() + DRAWER_WIDTH

    def _set_drawer(self, open_: bool) -> None:
        self._drawer_open = open_
        self._drawer_forced = open_ and self._narrow()
        self._apply_drawer()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._drawer_shown is not None:
            self._apply_drawer()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        # O mínimo do conteúdo pode mudar sem a janela mudar de tamanho (um vídeo analisado, outro idioma). É um filtro
        # de si mesma, e não um ``event()`` sobrescrito, de propósito: o ``DeferredDelete`` que apaga a janela passa
        # por ``event()``, e o destrutor do ``QThreadPool`` espera os workers lá dentro. Com o override em Python esse
        # ``delete this`` rodava num quadro que segura o GIL, e um worker ainda vivo, que precisa dele para terminar,
        # travava o fechamento para sempre (reproduzido: a janela apagada com um worker dormindo trava, sem o override
        # não). O filtro devolve antes de o evento chegar ao Qt, e o layout só termina de assentar no tique seguinte (um temporizador de 0 ms, que também junta pedidos em sequência).
        if watched is self:
            tipo = event.type()
            if tipo == QEvent.Type.LayoutRequest and self._drawer_shown is not None:
                self._drawer_timer.start()
            elif tipo in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() == Qt.Key.Key_Alt:
                self._set_alt(tipo == QEvent.Type.KeyPress)
            elif tipo == QEvent.Type.WindowDeactivate:
                # Alt+Tab não manda a soltura do Alt a esta janela: sem isto o sublinhado ficava preso.
                self._set_alt(False)
        return False

    def _set_alt(self, apertado: bool) -> None:
        if self._menu_style.alt_apertado != apertado:
            self._menu_style.alt_apertado = apertado
            self.menuBar().update()

    @staticmethod
    def _wrap_scrollable(inner: QWidget, *, horizontal: bool = False) -> QScrollArea:
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
        # O editor tem três colunas: telas estreitas precisam alcançar as laterais.
        area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        return area

    def _build_header(self) -> QWidget:
        """Endereço (uma barra só) e, embaixo, a pasta de destino em linha corrida."""
        box = QWidget()
        box.setProperty("role", "plain")
        coluna = QVBoxLayout(box)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)

        self._address = AddressBar()
        self._url = self._address.edit
        self._url.returnPressed.connect(self._analyze)
        self._paste = self._address.paste
        self._paste.clicked.connect(self._paste_and_analyze)
        self._analyze_button = self._address.analyze
        self._analyze_button.clicked.connect(self._analyze)
        coluna.addWidget(self._address)

        # "Salvar em  /pasta  Alterar": o caminho é texto corrido (o campo é editável, mas sem moldura), e o "Alterar"
        # vem logo depois dele.
        destino = QHBoxLayout()
        destino.setContentsMargins(4, 0, 0, 0)
        destino.setSpacing(8)
        self._dest_icon = QLabel()
        self._dest_icon.setProperty("role", "plain")
        destino.addWidget(self._dest_icon)
        dest_label = bind(QLabel(), "setText", lambda: strings.DEST_LABEL)
        dest_label.setProperty("role", "dim")
        destino.addWidget(dest_label)
        self._dest = bind(QLineEdit(self._settings.download_dir), "setToolTip", lambda: strings.DEST_TOOLTIP)
        self._dest.setProperty("role", "path")
        self._dest.editingFinished.connect(self._on_dest_edited)
        self._dest.textChanged.connect(self._fit_dest)
        destino.addWidget(self._dest, 1000)
        browse = bind(QPushButton(), "setText", lambda: strings.DEST_CHANGE)
        browse.setProperty("role", "link")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._choose_dest)
        destino.addWidget(browse)
        destino.addStretch(1)
        coluna.addLayout(destino)
        self._fit_dest()
        self._retheme_header()
        theme.on_theme_change(self._retheme_header)
        return box

    def _fit_dest(self) -> None:
        """O campo do caminho tem a largura do texto: o "Alterar" fica colado nele, e não na ponta da linha."""
        largura = self._dest.fontMetrics().horizontalAdvance(self._dest.text()) + 6
        self._dest.setMaximumWidth(max(60, largura))

    def _build_menu(self) -> None:
        self._file_menu = bind(self.menuBar().addMenu(""), "setTitle", lambda: strings.MENU_FILE)
        self._file_menu.aboutToShow.connect(self._on_file_menu_about_to_show)
        self._tools_menu = bind(self.menuBar().addMenu(""), "setTitle", lambda: strings.MENU_TOOLS)
        self._help_menu = bind(self.menuBar().addMenu(""), "setTitle", lambda: strings.MENU_HELP)
        self.menuBar().setStyle(self._menu_style)
        # Alt+letra abre o menu e a soltura do Alt vai para o menu aberto: o sublinhado sai quando o menu fecha.
        for menu in (self._file_menu, self._tools_menu, self._help_menu):
            menu.aboutToHide.connect(lambda: self._set_alt(False))

        # Ações universais
        self._quit_action = bind(QAction(self), "setText", lambda: strings.ACTION_QUIT)
        self._quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self._quit_action.triggered.connect(self.close)

        self._settings_action = bind(QAction(self), "setText", lambda: strings.ACTION_SETTINGS)
        self._settings_action.triggered.connect(self._open_settings)

        self._about_action = bind(QAction(self), "setText", lambda: strings.ACTION_ABOUT)
        self._about_action.triggered.connect(self._show_about)
        self._help_menu.addAction(self._about_action)

        # Ações da aba Download
        self._open_download_dest = bind(QAction(self), "setText", lambda: strings.ACTION_OPEN_DOWNLOAD_DEST)
        self._open_download_dest.triggered.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._runtime.download_directory(self._settings)))
            )
        )
        self._update_engine_action = bind(QAction(self), "setText", lambda: strings.ACTION_UPDATE_ENGINE)
        self._update_engine_action.triggered.connect(self._update_engine)
        if self._runtime.is_packaged():
            self._update_engine_action.setEnabled(False)
            bind(self._update_engine_action, "setToolTip",
                 lambda: strings.DIALOG_ENGINE_PACKAGED.format(url=RELEASES_URL))

        # Ações da aba Converter
        self._convert_add_action = bind(QAction(self), "setText", lambda: strings.ACTION_CONVERT_ADD)
        self._convert_add_action.triggered.connect(self._convert._choose_files)

        self._convert_remove_action = bind(QAction(self), "setText", lambda: strings.ACTION_CONVERT_REMOVE)
        self._convert_remove_action.triggered.connect(self._convert._remove_selected)

        self._convert_clear_action = bind(QAction(self), "setText", lambda: strings.ACTION_CONVERT_CLEAR)
        self._convert_clear_action.triggered.connect(self._convert.clear_files)

        self._convert_open_dest = bind(QAction(self), "setText", lambda: strings.ACTION_OPEN_CONVERT_DEST)
        self._convert_open_dest.triggered.connect(self._open_convert_dest)

        # Ações da aba Editar
        self._new_proj_action = bind(QAction(self), "setText", lambda: strings.ACTION_NEW_PROJECT)
        self._new_proj_action.triggered.connect(self._new_project)

        self._open_proj_action = bind(QAction(self), "setText", lambda: strings.ACTION_OPEN_PROJECT)
        self._open_proj_action.triggered.connect(self._open_project)

        self._save_proj_action = bind(QAction(self), "setText", lambda: strings.ACTION_SAVE_PROJECT)
        self._save_proj_action.triggered.connect(self._save_project)

        self._save_as_proj_action = bind(QAction(self), "setText", lambda: strings.ACTION_SAVE_PROJECT_AS)
        self._save_as_proj_action.triggered.connect(self._save_project_as)

        self._import_media_action = bind(QAction(self), "setText", lambda: strings.ACTION_IMPORT_MEDIA)
        self._import_media_action.triggered.connect(self._edit.import_media_dialog)

        self._export_action = bind(QAction(self), "setText", lambda: strings.ACTION_EXPORT_VIDEO)
        self._export_action.triggered.connect(self._edit._open_export_dialog)

        # Ações da aba Metadados
        self._meta_open_action = bind(QAction(self), "setText", lambda: strings.ACTION_META_OPEN)
        self._meta_open_action.triggered.connect(lambda: self._metadata_panel().choose_file())
        self._meta_save_action = bind(QAction(self), "setText", lambda: strings.ACTION_META_SAVE)
        self._meta_save_action.triggered.connect(lambda: self._metadata_panel().save())

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
        # O mesmo atalho vale uma coisa em cada aba (Ctrl+O abre arquivos na
        # Converter, projeto no editor e arquivo nos Metadados): só os da aba atual
        # ficam ligados, senão o Qt acusa atalho ambíguo e nenhum dispara.
        for action in (self._meta_open_action, self._meta_save_action):
            action.setShortcut(QKeySequence())

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

        elif index == _TAB_METADATA:
            for action in (self._convert_add_action, self._new_proj_action, self._open_proj_action,
                           self._save_proj_action, self._save_as_proj_action, self._import_media_action,
                           self._export_action):
                action.setShortcut(QKeySequence())
            self._meta_open_action.setShortcut(QKeySequence("Ctrl+O"))
            self._meta_save_action.setShortcut(QKeySequence("Ctrl+S"))
            self._file_menu.addAction(self._meta_open_action)
            self._file_menu.addAction(self._meta_save_action)
            self._file_menu.addSeparator()
            self._file_menu.addAction(self._quit_action)

        self._tools_menu.setToolTipsVisible(True)

    # ------------------------------------------------------------------
    # Primeira execução
    # ------------------------------------------------------------------

    def bootstrap(self) -> None:
        """Garante o ffmpeg. Chamado depois de a janela aparecer."""
        self._tools = ensure_ffmpeg(self, runtime=self._runtime)

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
        worker = self._runtime.probe_worker(url, self._settings, service=self._downloads)
        self._probe_worker = worker
        attempt = _ProbeAttempt(self, worker)
        worker.signals.finished.connect(attempt.finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(attempt.failed, Qt.ConnectionType.QueuedConnection)
        worker.signals.done.connect(attempt.deleteLater)
        self._runner.start(worker, worker.signals.done)

    def _cancel_analyze(self) -> None:
        if self._probe_worker is not None:
            self._probe_worker.cancel()
            self._probe_worker = None
        self._set_analyzing(False)

    def _set_analyzing(self, busy: bool) -> None:
        bind(self._analyze_button, "setText", lambda: strings.URL_CANCEL if busy else strings.URL_ANALYZE)
        bind(self._analyze_button, "setToolTip", lambda: strings.URL_CANCEL_TIP if busy else "")
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
        self._quality.set_matrix(result.matrix, duration=result.duration)
        self._profiles.set_enabled(True)
        self._profiles.set_estimates([
            estimate_profile_size(result.matrix, p.mode, max_height=p.height, audio_codec=p.audio_codec,
                                  audio_quality=p.audio_quality, duration=result.duration)
            for p in PROFILES])
        self._update_add_button()

    def _on_probe_failed(self, message: object) -> None:
        self._probe_worker = None
        self._set_analyzing(False)
        QMessageBox.warning(self, strings.DIALOG_ERROR_TITLE, str(message))

    # ------------------------------------------------------------------
    # Enfileiramento
    # ------------------------------------------------------------------

    def _update_add_button(self) -> None:
        self._add_button.setEnabled(self._media is not None)
        if self._media is not None:
            self._add_button.setToolTip("")
        self._update_footer()

    def _update_footer(self) -> None:
        """O resultado e o tamanho, lidos do que os campos mostram agora."""
        analyzed = self._media is not None
        self._result_summary.setText(self._quality.summary() if analyzed else DASH)
        self._result_size.setText(self._quality.estimated_size() if analyzed else DASH)

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
        dest = self._runtime.download_directory(self._settings)
        # Temporários fora da pasta de destino, que só recebe arquivo pronto, e
        # no cache do usuário, **não** em /tmp, pelos mesmos dois motivos que
        # levaram ``ParallelExport`` a fugir de lá: /tmp é tmpfs (memória) em
        # muitas distribuições, e um caminho fixo nele fica à mercê de quem
        # chegar antes. A pasta da sessão só nasce no primeiro download.
        payload = DownloadRequest(request, media, dest, self._runtime.download_cache,
                                  Preferences.from_dict(asdict(self._settings)))
        job = self._downloads.prepare(payload)
        self._queue.submit(job)

    def _require_tools(self) -> bool:
        """Bloqueia o enfileiramento sem ffmpeg, explicando o motivo."""
        if self._tools is not None:
            return True
        self._tools = ensure_ffmpeg(self, runtime=self._runtime)
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
        tools = self._tools or self._runtime.find_tools()
        if tools is None:
            return
        self._probed_hardware = True
        worker = self._runtime.hardware_worker(tools)
        self._runner.start(worker, worker.signals.done)

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def _handle_playlist(self, playlist: PlaylistInfo) -> None:
        if not self._require_tools():
            return
        initial_audio = self._quality.mode is Mode.AUDIO_ONLY
        dialog = PlaylistDialog(playlist, initial_audio=initial_audio, parent=self)
        # O diálogo tem a janela por pai: sem o ``deleteLater`` ele ficava escondido para sempre (ver ``EditPanel._exec_menu``).
        try:
            if dialog.exec() != PlaylistDialog.DialogCode.Accepted:
                return
            entries = dialog.selected_entries()
            audio_mode = dialog.is_audio_mode()
            height_limit = None if audio_mode else dialog.height_limit()
        finally:
            dialog.deleteLater()
        if not entries:
            return

        if audio_mode:
            self._quality.set_mode(Mode.AUDIO_ONLY)
        else:
            self._quality.set_mode(Mode.VIDEO)

        # Cada item da playlist tem formatos próprios, então uma escolha por id
        # concreto não valeria para todos. O pedido vai por limite de resolução,
        # que o seletor resolve item a item na hora do download.
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
        # Aviso na tela porque a gaveta pode estar fechada (ou a janela estreita demais para ela): sem ele, clicar em
        # "Adicionar à fila" não teria resposta nenhuma. "Ver tarefas" abre a gaveta onde quer que o usuário esteja.
        self._toasts.mostrar(
            strings.STATUS_ENQUEUED.format(count=len(jobs)), ms=_ENQUEUED_MS,
            acao=(strings.TOAST_VIEW_TASKS, lambda: self._set_drawer(True)),
        )

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
        dialog = SettingsDialog(self._settings, self, runtime=self._runtime, tools=self._tools)
        # Cada abertura deixava ~125 widgets escondidos (4 MiB), todos reestilizados a cada troca de tema e de idioma:
        # 25 aberturas levavam a ida e volta do tema de 1,8 s a 4,7 s. O resultado se lê antes de apagar o diálogo.
        try:
            if dialog.exec() != SettingsDialog.DialogCode.Accepted:
                return
            result = dialog.result_settings()
        finally:
            dialog.deleteLater()
        previous_theme, previous_palette = self._settings.theme, self._settings.palette
        self._settings = result
        self._save_settings()
        self._queue.apply_settings(self._settings)
        self._convert.apply_settings(self._settings)
        self._edit.apply_settings(self._settings)
        if self._metadata is not None:
            self._metadata.apply_settings(self._settings)
        self._dest.setText(self._settings.download_dir)
        if (self._settings.theme, self._settings.palette) != (previous_theme, previous_palette):
            app = QApplication.instance()
            if app is not None:
                aplicar_tema(app, self._settings.theme, self._settings.palette)
        apply_language(self._settings.language)

    def _update_engine(self) -> None:
        if self._runtime.is_packaged():
            # O item de menu já nasce desligado; esta é a segunda tranca, para o
            # caso de a ação chegar por outro caminho. Ver ``EngineUpdateWorker``:
            # num pacote, o comando abriria uma segunda janela do aplicativo em
            # vez de instalar coisa alguma.
            QMessageBox.information(
                self, strings.DIALOG_ENGINE_TITLE, strings.DIALOG_ENGINE_PACKAGED.format(url=RELEASES_URL)
            )
            return
        current = self._runtime.engine_version
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

        worker = self._runtime.engine_worker(current)
        worker.signals.finished.connect(on_finished)
        worker.signals.failed.connect(on_failed)
        self._runner.start(worker, worker.signals.done)
        dialog.exec()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            strings.ABOUT_TITLE,
            strings.ABOUT_BODY.format(
                version=f"{__version__} ({commit})" if (commit := build_commit()) else __version__,
                ytdlp=self._runtime.engine_version,
                releases=RELEASES_URL, issues=ISSUES_URL,
            ),
        )

    # ------------------------------------------------------------------
    # Status e encerramento
    # ------------------------------------------------------------------

    def _update_tasks_badge(self) -> None:
        """O número de tarefas em aberto no item Tarefas, e a contagem completa na dica.

        É o que sobrou da barra de status, que contava as tarefas mas só aparecia nas abas onde a fila já estava
        à vista. O selo vale nas quatro, inclusive no editor e nos Metadados, onde a gaveta está recolhida.
        """
        active = self._queue.count_by_status(JobStatus.RUNNING, JobStatus.PROCESSING)
        pending = self._queue.count_by_status(JobStatus.PENDING)
        done = self._queue.count_by_status(JobStatus.DONE)
        self._nav_tasks.set_selo(active + pending, strings.STATUS_COUNTS.format(active=active, pending=pending, done=done))

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
        target_dir = self._runtime.download_directory(self._settings)
        if self._convert._same_folder.isChecked() and self._convert._media:
            target_dir = self._convert._media[0].path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_dir)))

    def closeEvent(self, event) -> None:  # noqa: N802
        """Confirma a saída quando há alterações não salvas ou tarefas em andamento."""
        if hasattr(self, "_edit") and not self._edit._project_actions.confirm_replace():
            event.ignore()
            return
        if getattr(self, "_metadata", None) is not None and not self._metadata.confirm_discard():
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
        self._convert.shutdown()
        if self._metadata is not None:
            self._metadata.shutdown()
        self._queue.shutdown()
        # Sem a fila, nenhum .part é retomável: a pasta da sessão sai junto.
        self._runtime.close_session()
        self._save_settings()
        event.accept()

    def _save_settings(self) -> None:
        """Grava as preferências sem deixar uma falha de disco virar defeito.

        Todo lugar que salva passa por aqui: a gravação é secundária em relação
        ao que o usuário estava fazendo, e um ``OSError`` cru dentro de um slot
        do Qt vira traceback sem explicação nenhuma na tela.
        """
        try:
            self._runtime.save_settings(self._settings)
        except OSError as exc:
            self._toasts.mostrar(strings.STATUS_SETTINGS_FAILED.format(error=exc), tipo="error", ms=_ENQUEUED_MS)
