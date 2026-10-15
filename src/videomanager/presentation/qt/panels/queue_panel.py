"""A fila de tarefas: lista de cartões com progresso, ações e menu de contexto.

O modelo é um ``QAbstractTableModel`` e o desenho é um delegate (:mod:`queue_cards`), em vez de um widget
por tarefa. A diferença importa: o progresso chega várias vezes por segundo por tarefa, e criar/atualizar
widgets reais em cada linha gasta muito mais que desenhar o cartão no delegate.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.formatting import DASH
from videomanager.application.formatting import format_size
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.models import JobStatus
from videomanager.presentation.qt import fonts, icons, strings, theme
from videomanager.presentation.qt.i18n import bind, on_language_change
from videomanager.presentation.qt.panels.queue_cards import REGIOES_CLICAVEIS, TaskDelegate, situacao, velocidade_e_tempo
from videomanager.presentation.qt.ports import DesktopRuntimePort

_COL_TITLE, _COL_OUTPUT, _COL_STATUS, _COL_PROGRESS, _COL_SPEED = range(5)

# Cartões simples que a lista mostra por inteiro antes de precisar rolar. Sem esse piso o divisor cede
# toda a altura ao painel de cima e sobra um cartão e meio.
_MIN_CARDS = 2


def status_text(job):
    if job.status is JobStatus.FAILED and job.error:
        return f"{strings.JOB_STATUS_LABELS['failed']}: {job.error}"
    if job.status.is_active and job.progress:
        return str(job.progress.phase)
    return strings.JOB_STATUS_LABELS[job.status.value]


class QueueModel(QAbstractTableModel):
    """Adapta a lista de tarefas da fila para a tabela."""

    def __init__(self, queue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._jobs: list[Job] = []
        queue.job_added.connect(self._on_added)
        queue.job_changed.connect(self._on_changed)
        on_language_change(self._retranslate)

    def _retranslate(self) -> None:
        # Cabeçalho e células leem o catálogo, e o texto guardado nas tarefas é
        # convertido, na hora de desenhar: basta avisar a tabela.
        last = self.columnCount() - 1
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, last)
        if self._jobs:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._jobs) - 1, last))

    # -- interface do modelo ---------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._jobs)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(strings.QUEUE_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return strings.QUEUE_COLUMNS[section]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job = self._jobs[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.UserRole:
            return job

        if role == Qt.ItemDataRole.DisplayRole:
            if column == _COL_TITLE:
                return job.title
            if column == _COL_OUTPUT:
                return str(job.description)
            if column == _COL_STATUS:
                return status_text(job)
            if column == _COL_PROGRESS:
                return job.percent
            if column == _COL_SPEED:
                return self._speed_text(job)

        if role == Qt.ItemDataRole.AccessibleTextRole and column == _COL_TITLE:
            # O cartão é pintado: o leitor de tela só tem o que o modelo diz dele.
            return f"{job.title}. {situacao(job)}" + (f". {job.error}" if job.error else "")

        if role == Qt.ItemDataRole.ToolTipRole:
            if column == _COL_STATUS and job.error:
                return str(job.error)
            if column == _COL_TITLE:
                return job.url
            if column == _COL_OUTPUT and job.warnings:
                return "\n".join(map(str, job.warnings))

        if role == Qt.ItemDataRole.TextAlignmentRole and column in (_COL_STATUS, _COL_SPEED):
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        return None

    # -- ajuda -------------------------------------------------------------

    @staticmethod
    def _speed_text(job: Job) -> str:
        progress = job.progress
        if job.status is JobStatus.DONE:
            # Número medido uma vez, quando a tarefa terminou (ver
            # ``Job.result_size``): esta função roda a cada repintura de célula.
            return format_size(job.result_size) if job.result_size else DASH
        if progress is None:
            return DASH
        pieces = velocidade_e_tempo(job)
        if not pieces and progress.fragment_count:
            pieces.append(strings.QUEUE_FRAGMENT.format(index=progress.fragment_index or 0,
                                                        count=progress.fragment_count))
        return " · ".join(pieces) or DASH

    def job_at(self, row: int) -> Job | None:
        return self._jobs[row] if 0 <= row < len(self._jobs) else None

    # -- sincronização com a fila -----------------------------------------

    def _on_added(self, job: Job) -> None:
        position = len(self._jobs)
        self.beginInsertRows(QModelIndex(), position, position)
        self._jobs.append(job)
        self.endInsertRows()

    def _on_changed(self, job: Job) -> None:
        try:
            row = self._jobs.index(job)
        except ValueError:
            return
        # Atualiza só a linha alterada: emitir para a tabela inteira redesenharia
        # tudo a cada quadro de progresso.
        self.dataChanged.emit(
            self.index(row, 0), self.index(row, self.columnCount() - 1)
        )

    def reload(self) -> None:
        self.beginResetModel()
        self._jobs = list(self._queue.jobs)
        self.endResetModel()


class QueueView(QListView):
    """A lista de cartões.

    A altura preferida é a mínima que ela aceita: o padrão do Qt para qualquer área de rolagem é um palpite
    fixo (192 px) sem relação com o conteúdo. O divisor reservava esse palpite e tirava a diferença dos
    controles, que apareciam cortados com a fila vazia embaixo. Pedindo o mínimo, a fila ainda cresce com
    a janela — mas só depois que o resto está inteiro.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._delegate = TaskDelegate(self)
        self.setItemDelegate(self._delegate)
        self.setProperty("role", "queue")
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setUniformItemSizes(False)
        # Largura nova, altura nova: o texto quebra por largura, então a lista refaz as medidas ao redimensionar.
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    @property
    def delegate(self) -> TaskDelegate:
        return self._delegate

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def card_at(self, position) -> tuple[Job | None, str, QModelIndex]:
        """A tarefa sob ``position`` (coordenadas da lista), a região do cartão e o índice."""
        index = self.indexAt(position)
        if not index.isValid():
            return None, "", index
        job: Job | None = index.data(Qt.ItemDataRole.UserRole)
        if job is None:
            return None, "", index
        return job, self._delegate.regiao_em(job, self.visualRect(index), position), index

    def dataChanged(self, top_left, bottom_right, roles=()) -> None:  # noqa: N802
        """Só o andamento mudou: repinta a linha, sem pedir a altura de todas as outras de novo.

        A lista refaz o layout inteiro a cada aviso do modelo, e com 200 tarefas isso custava 23 ms por
        aviso de progresso. A altura de um cartão não depende do percentual, então na maioria dos avisos
        basta repintar.
        """
        model = self.model()
        largura = self._delegate.largura()
        jobs = [model.index(row, 0).data(Qt.ItemDataRole.UserRole)
                for row in range(top_left.row(), bottom_right.row() + 1)]
        if largura and all(job is not None and not self._delegate.mudou_a_altura(job, largura, self.font())
                           for job in jobs):
            for row in range(top_left.row(), bottom_right.row() + 1):
                self.viewport().update(self.visualRect(model.index(row, 0)))
            return
        super().dataChanged(top_left, bottom_right, roles)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Depois do ``super``: a barra de rolagem que aparece (ou some) estreita a área sem mexer na lista, e é a
        # largura da área que o delegate usa para quebrar o texto.
        self._delegate.set_largura(self.viewport().width())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        job, region, _ = self.card_at(event.position().toPoint())
        clickable = region in REGIOES_CLICAVEIS
        changed = self._delegate.set_hover(job.job_id if job and clickable else None, region if clickable else "")
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        if changed:
            self.viewport().update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._delegate.set_hover(None):
            self.viewport().update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # O segundo clique rápido num botão do cartão (cancelar, abrir a pasta) não é "abrir o arquivo".
        _, region, _ = self.card_at(event.position().toPoint())
        if region in REGIOES_CLICAVEIS:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.ToolTip:
            return super().viewportEvent(event)
        job, region, index = self.card_at(event.pos())
        tips = {"cancelar": strings.QUEUE_CANCEL, "pasta": strings.QUEUE_OPEN_FOLDER,
                "repetir": strings.QUEUE_RETRY, "detalhes": strings.QUEUE_SHOW_LOG}
        if job is not None and region == "erro":
            text = str(job.error)  # o cartão corta o erro em quatro linhas; o texto inteiro mora aqui
        elif job is not None:
            text = tips.get(region) or self.model().data(index, Qt.ItemDataRole.ToolTipRole)
        else:
            text = None
        if text:
            QToolTip.showText(event.globalPos(), text, self.viewport())
        else:
            QToolTip.hideText()
        event.accept()
        return True

    def paintEvent(self, event) -> None:  # noqa: N802
        """Diz que a fila está vazia, em vez de mostrar um retângulo em branco.

        Uma lista sem nada passa impressão de tela que não carregou.
        """
        super().paintEvent(event)
        model = self.model()
        if model is not None and model.rowCount():
            return
        colors = theme.papeis(*theme.atual())
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.viewport().rect()
        side, gap, line = 56, 12, 20
        tile = QRect(area.center().x() - side // 2, area.center().y() - (side + gap + line) // 2, side, side)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["raised"]))
        painter.drawRoundedRect(QRectF(tile), 16, 16)
        icon = 26
        icons.task_list(colors["t3"], icon).paint(
            painter, QRect(tile.x() + (side - icon) // 2, tile.y() + (side - icon) // 2, icon, icon))
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(QRect(area.x(), tile.bottom() + gap, area.width(), line),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, strings.QUEUE_EMPTY)
        painter.end()


# Largura da gaveta: cabe o cartão com o texto do tempo restante e o botão de cancelar sem quebrar linha.
DRAWER_WIDTH = 344

# (nome, papel de cor, situações que contam) de cada selo do cabeçalho, na ordem em que aparecem.
_CHIPS = (
    ("active", "accent", (JobStatus.RUNNING, JobStatus.PROCESSING), "QUEUE_CHIP_ACTIVE"),
    ("pending", "dim", (JobStatus.PENDING,), "QUEUE_CHIP_PENDING"),
    ("failed", "err", (JobStatus.FAILED,), "QUEUE_CHIP_FAILED"),
    ("cancelled", "dim", (JobStatus.CANCELLED,), "QUEUE_CHIP_CANCELLED"),
)


class QueuePanel(QFrame):
    """A gaveta de tarefas: cabeçalho com a contagem, a lista de cartões, ações em lote e menu de contexto."""

    hide_requested = Signal()

    def __init__(
        self,
        queue,
        parent: QWidget | None = None,
        *,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "drawer")
        # Largura máxima, e não fixa: quem decide se a gaveta cabe é a janela (``MainWindow._apply_drawer``), e o mínimo
        # que ela anuncia depende disso (ver :meth:`set_squeezable`). Esticamento zero no layout da janela, então o
        # conteúdo cede primeiro e ela mantém os 344 px até o conteúdo chegar ao próprio mínimo.
        self.setMaximumWidth(DRAWER_WIDTH)
        self._squeezable = True
        self._runtime = runtime
        self._queue = queue
        self._counts = {name: 0 for name, *_ in _CHIPS}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(14)
        self._layout = layout

        header = QHBoxLayout()
        self._header = header
        header.setSpacing(10)
        self._chips_inline: bool | None = None
        title = bind(QLabel(), "setText", lambda: strings.QUEUE_GROUP)
        title.setProperty("role", "drawer-title")
        header.addWidget(title)
        self._title = title
        header.addStretch(1)
        self._hide_button = QToolButton()
        self._hide_button.setProperty("role", "icon")
        self._hide_button.setIconSize(QSize(18, 18))
        bind(self._hide_button, "setToolTip", lambda: strings.QUEUE_HIDE)
        self._hide_button.clicked.connect(self.hide_requested)
        header.addWidget(self._hide_button)
        layout.addLayout(header)

        # Os selos ficam ao lado do título quando cabem (o protótipo mostra dois ou três por vez); com os quatro à vista
        # (ativas, na fila, falharam, canceladas) não cabem nos 344 px da gaveta, e vão para uma linha própria.
        # ``_place_chips`` decide, a cada mudança de contagem e de idioma.
        self._chip_row = QWidget()
        self._chip_row.setProperty("role", "plain")
        chips = QHBoxLayout(self._chip_row)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)
        self._chips: dict[str, QLabel] = {}
        for name, tone, _statuses, _key in _CHIPS:
            chip = QLabel()
            chip.setProperty("role", "chip")
            chip.setProperty("tone", tone)
            self._chips[name] = chip
            chips.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._chip_row)
        theme.on_theme_change(self._retheme)
        self._retheme()

        self._model = QueueModel(queue, self)
        self._list = QueueView()
        bind(self._list, "setAccessibleName", lambda: strings.QUEUE_GROUP)
        self._list.setModel(self._model)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.doubleClicked.connect(self._open_selected_file)
        self._list.delegate.acionado.connect(self._on_card_action)
        self._fit_min_height()
        # O piso depende da fonte, e a fonte pode ser outra depois da troca de idioma.
        on_language_change(self._fit_min_height)
        layout.addWidget(self._list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._cancel_all = bind(QPushButton(), "setText", lambda: strings.QUEUE_CANCEL_ALL)
        self._cancel_all.setProperty("role", "btn")
        self._cancel_all.clicked.connect(self._confirm_cancel_all)
        actions.addWidget(self._cancel_all, 1)
        # "Limpar encerrados" é o gesto discreto: sem fundo, ao lado do que interrompe o trabalho.
        self._clear = bind(QPushButton(), "setText", lambda: strings.QUEUE_CLEAR_FINISHED)
        self._clear.setProperty("role", "ghost")
        self._clear.clicked.connect(self._clear_finished)
        actions.addWidget(self._clear, 1)
        layout.addLayout(actions)
        queue.job_added.connect(self._sync_state)
        queue.job_changed.connect(self._sync_state)
        on_language_change(self._retext_chips)
        # Os selos nascem com texto (escondidos): o que a troca de idioma reescreve tem de existir antes dela.
        self._retext_chips()
        self._sync_state()

    def _retheme(self) -> None:
        self._hide_button.setIcon(icons.chevron_right(theme.papeis(*theme.atual())["t2"]))

    def _sync_state(self, *_) -> None:
        """Os botões de baixo e os selos do cabeçalho acompanham as tarefas.

        Os botões só ficam à mão quando têm o que fazer (antes respondiam sem fazer nada). Uma passada só pelas
        tarefas, que o progresso chama várias vezes por segundo: os selos só são reescritos quando uma contagem muda.
        """
        counts = {name: 0 for name, *_ in _CHIPS}
        unfinished = finished = False
        for job in self._queue.jobs:
            if job.status.is_final:
                finished = True
            else:
                unfinished = True
            for name, _tone, statuses, _key in _CHIPS:
                if job.status in statuses:
                    counts[name] += 1
        self._cancel_all.setEnabled(unfinished)
        self._clear.setEnabled(finished)
        if counts != self._counts:
            self._counts = counts
            self._retext_chips()

    def _retext_chips(self) -> None:
        for name, _tone, _statuses, key in _CHIPS:
            count = self._counts[name]
            singular, plural = getattr(strings, key)
            self._chips[name].setText((singular if count == 1 else plural).format(count=count))
            self._chips[name].setVisible(count > 0)
        self._chip_row.setVisible(any(self._counts.values()))
        self._place_chips()

    def set_squeezable(self, squeezable: bool) -> None:
        """Se a gaveta pode ceder largura: ``False`` faz o mínimo da janela incluir os 344 px dela.

        À vista por preferência, ela não conta no mínimo da janela — abaixo do limiar a janela a recolhe, em vez de
        ficar presa em 840 px por causa de uma coluna que ninguém pediu naquele momento. Aberta de passagem
        (o item Tarefas numa janela estreita), ela pede o espaço inteiro e a janela cresce até caber.
        """
        if squeezable != self._squeezable:
            self._squeezable = squeezable
            self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(DRAWER_WIDTH, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0 if self._squeezable else DRAWER_WIDTH, super().minimumSizeHint().height())

    def _place_chips(self) -> None:
        """Os selos ao lado do título quando cabem; senão, numa linha própria logo abaixo dele.

        A conta é a das larguras que cada peça pede, e não um número fixo: o texto de um selo muda com a contagem
        ("1 falhou", "12 canceladas") e com o idioma.
        """
        visiveis = [chip for chip in self._chips.values() if not chip.isHidden()]
        if not visiveis:
            return
        pedido = sum(chip.sizeHint().width() for chip in visiveis) + 6 * (len(visiveis) - 1)
        margens = self._layout.contentsMargins()
        livre = (DRAWER_WIDTH - margens.left() - margens.right() - self._title.sizeHint().width()
                 - self._hide_button.sizeHint().width() - 2 * self._header.spacing())
        inline = pedido <= livre
        if inline == self._chips_inline:
            return
        self._chips_inline = inline
        self._header.removeWidget(self._chip_row)
        self._layout.removeWidget(self._chip_row)
        if inline:
            self._header.insertWidget(1, self._chip_row)
        else:
            self._layout.insertWidget(1, self._chip_row)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Só agora o estilo está aplicado e os selos pedem a largura de verdade.
        self._chips_inline = None
        self._place_chips()

    def _on_card_action(self, job: Job, region: str) -> None:
        if region == "cancelar":
            self._queue.cancel(job.job_id)
        elif region == "repetir":
            self._queue.retry(job.job_id)
        elif region == "detalhes":
            self._show_log(job)
        elif region == "pasta":
            self._reveal(job.result_path)

    def _confirm_cancel_all(self) -> None:
        """Confirma antes de cancelar: o botão fica ao lado de "Limpar encerrados".

        Um clique errado interrompia todas as tarefas de uma vez — inclusive uma
        exportação interpolada longa, que "Repetir" recomeça do zero.
        """
        unfinished = sum(1 for job in self._queue.jobs if not job.status.is_final)
        if not unfinished:
            return
        answer = QMessageBox.question(
            self, strings.QUEUE_CANCEL_ALL_TITLE, strings.QUEUE_CANCEL_ALL_BODY.format(count=unfinished),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._queue.cancel_all()

    def _fit_min_height(self) -> None:
        # Piso de dois cartões inteiros, medido pela fonte em uso: um número redondo escrito à mão cortaria
        # o último ao meio em outra fonte, outro tema ou outro idioma.
        card = self._list.delegate.altura_minima(self._list.font())
        self._list.setMinimumHeight(_MIN_CARDS * card + 2 * self._list.frameWidth())

    # ------------------------------------------------------------------

    def _selected_jobs(self) -> list[Job]:
        rows = {index.row() for index in self._list.selectionModel().selectedIndexes()}
        return [job for row in sorted(rows) if (job := self._model.job_at(row))]

    def _clear_finished(self) -> None:
        self._queue.remove_finished()
        self._model.reload()
        self._sync_state()

    def _show_context_menu(self, position) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            return
        job = jobs[0]
        menu = QMenu(self)

        if any(not j.status.is_final for j in jobs):
            action = QAction(strings.QUEUE_CANCEL, menu)
            action.triggered.connect(lambda: [self._queue.cancel(j.job_id) for j in jobs])
            menu.addAction(action)

        if any(j.status in (JobStatus.FAILED, JobStatus.CANCELLED) for j in jobs):
            action = QAction(strings.QUEUE_RETRY, menu)
            action.triggered.connect(lambda: [self._queue.retry(j.job_id) for j in jobs])
            menu.addAction(action)

        if job.result_path and job.result_path.exists():
            menu.addSeparator()
            open_file = QAction(strings.QUEUE_OPEN_FILE, menu)
            open_file.triggered.connect(lambda: self._open_path(job.result_path))
            menu.addAction(open_file)
            open_folder = QAction(strings.QUEUE_OPEN_FOLDER, menu)
            open_folder.triggered.connect(lambda: self._reveal(job.result_path))
            menu.addAction(open_folder)

        if job.error:
            menu.addSeparator()
            copy_error = QAction(strings.QUEUE_COPY_ERROR, menu)
            copy_error.triggered.connect(
                lambda: QApplication.clipboard().setText(str(job.error or ""))
            )
            menu.addAction(copy_error)

        if job.log:
            action = QAction(strings.QUEUE_SHOW_LOG, menu)
            action.triggered.connect(lambda: self._show_log(job))
            menu.addAction(action)

        if not menu.isEmpty():
            menu.exec(self._list.viewport().mapToGlobal(position))

    def _open_selected_file(self) -> None:
        jobs = self._selected_jobs()
        if jobs and jobs[0].result_path:
            self._open_path(jobs[0].result_path)

    @staticmethod
    def _open_path(path: Path | None) -> None:
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _reveal(self, path: Path | None) -> None:
        try:
            self._runtime.reveal_file(path)
        except OSError:
            if path:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _show_log(self, job: Job) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(strings.QUEUE_LOG_TITLE.format(title=job.title[:60]))
        dialog.resize(760, 460)
        box = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        # Monoespaçada: é saída de ferramenta, com colunas e caminhos que só
        # ficam legíveis alinhados.
        text.setFont(fonts.mono())
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        text.setPlainText("\n".join(job.log))
        box.addWidget(text)
        close = QPushButton(strings.QUEUE_LOG_CLOSE)
        close.clicked.connect(dialog.accept)
        box.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()
