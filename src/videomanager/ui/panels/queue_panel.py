"""A fila de tarefas: tabela com progresso, ações e menu de contexto.

Usa ``QAbstractTableModel`` com um delegate de barra de progresso, em vez de
``QTableWidget`` com um widget por célula. A diferença importa: o progresso chega
várias vezes por segundo por tarefa, e criar/atualizar um ``QProgressBar`` real em
cada célula gasta muito mais que desenhar a barra no delegate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFontDatabase,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.humanize import DASH, format_eta, format_size, format_speed
from ...core.job import Job, JobStatus
from ...workers.queue import JobQueue
from .. import strings

_COL_TITLE, _COL_OUTPUT, _COL_STATUS, _COL_PROGRESS, _COL_SPEED = range(5)

# Linhas que a fila mostra por inteiro antes de precisar rolar. Sem esse piso o
# divisor cede toda a altura ao painel de cima e sobra uma linha e meia.
_MIN_ROWS = 4


class QueueModel(QAbstractTableModel):
    """Adapta a lista de tarefas da fila para a tabela."""

    def __init__(self, queue: JobQueue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._jobs: list[Job] = []
        queue.job_added.connect(self._on_added)
        queue.job_changed.connect(self._on_changed)

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
                return job.description
            if column == _COL_STATUS:
                return job.status_text
            if column == _COL_PROGRESS:
                return job.percent
            if column == _COL_SPEED:
                return self._speed_text(job)

        if role == Qt.ItemDataRole.ToolTipRole:
            if column == _COL_STATUS and job.error:
                return job.error
            if column == _COL_TITLE:
                return job.url
            if column == _COL_OUTPUT and job.warnings:
                return "\n".join(job.warnings)

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
        pieces: list[str] = []
        if progress.speed:
            pieces.append(format_speed(progress.speed))
        if progress.eta:
            pieces.append(f"faltam {format_eta(progress.eta)}")
        if not pieces and progress.fragment_count:
            pieces.append(f"parte {progress.fragment_index or 0}/{progress.fragment_count}")
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


class ProgressDelegate(QStyledItemDelegate):
    """Desenha a barra de progresso da coluna de andamento."""

    def paint(self, painter, option, index) -> None:
        percent = index.data(Qt.ItemDataRole.DisplayRole)
        job: Job | None = index.data(Qt.ItemDataRole.UserRole)

        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(4, 5, -4, -5)
        # A folha de estilo não alcança o que o delegate desenha; quem responde
        # pelas cores aqui é a paleta da aplicação (ver ui/theme.qpalette).
        bar.palette = option.palette
        bar.minimum = 0
        bar.textVisible = True
        bar.textAlignment = Qt.AlignmentFlag.AlignCenter

        if job is not None and job.status is JobStatus.DONE:
            bar.maximum, bar.progress, bar.text = 100, 100, "100%"
        elif job is not None and job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            bar.maximum, bar.progress = 100, 0
            bar.text = job.status.value
        elif job is not None and job.status is JobStatus.PENDING:
            # Barra vazia, não animada: a animação sugere trabalho em curso, e
            # uma tarefa esperando vaga na fila ainda não começou nada.
            bar.maximum, bar.progress = 100, 0
            bar.text = job.status.value
        elif percent is None:
            # Barra contínua: acontece em HLS sem tamanho total e durante o
            # pós-processamento, quando não há percentual honesto a mostrar.
            bar.maximum, bar.progress, bar.text = 0, 0, "…"
        else:
            bar.maximum, bar.progress = 100, int(percent)
            bar.text = f"{percent:.0f}%"

        QApplication.style().drawControl(
            QStyle.ControlElement.CE_ProgressBar, bar, painter
        )


class _QueueTable(QTableView):
    """Tabela cuja altura preferida é a mínima que ela aceita.

    O padrão do Qt para qualquer área de rolagem é um palpite fixo (192 px) que
    não tem relação com esta tabela. O divisor reservava esse palpite e tirava a
    diferença dos controles, que apareciam cortados com a fila vazia embaixo.
    Pedindo o mínimo, a fila ainda cresce com a janela — mas só depois que o
    resto está inteiro.
    """

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), self.minimumHeight())

    def paintEvent(self, event) -> None:  # noqa: N802
        """Diz que a fila está vazia, em vez de mostrar um retângulo em branco.

        Uma tabela só com cabeçalho e um vazio embaixo passa impressão de tela
        que não carregou.
        """
        super().paintEvent(event)
        model = self.model()
        if model is not None and model.rowCount():
            return
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, strings.QUEUE_EMPTY
        )
        painter.end()


class QueuePanel(QGroupBox):
    """A fila, com barra de ações e menu de contexto."""

    def __init__(self, queue: JobQueue, parent: QWidget | None = None) -> None:
        super().__init__(strings.QUEUE_GROUP, parent)
        self._queue = queue

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._model = QueueModel(queue, self)
        self._table = _QueueTable()
        self._table.setModel(self._model)
        self._table.setItemDelegateForColumn(_COL_PROGRESS, ProgressDelegate(self._table))
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.doubleClicked.connect(self._open_selected_file)

        header = self._table.horizontalHeader()
        # O padrão do Qt centraliza o título da coluna, mas o conteúdo das
        # células é alinhado à esquerda: sem isto, cabeçalho e dados ficam em
        # colunas visualmente diferentes.
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(_COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for column in (_COL_OUTPUT, _COL_STATUS, _COL_PROGRESS, _COL_SPEED):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(_COL_OUTPUT, 190)
        self._table.setColumnWidth(_COL_STATUS, 170)
        self._table.setColumnWidth(_COL_PROGRESS, 120)
        self._table.setColumnWidth(_COL_SPEED, 150)
        # Piso de quatro linhas inteiras, medido nas métricas reais do cabeçalho
        # e das linhas: um número redondo escrito à mão cortava a última linha
        # ao meio, e cortaria outra quantidade em cada tema ou fonte.
        self._table.setMinimumHeight(
            header.sizeHint().height()
            + _MIN_ROWS * self._table.verticalHeader().defaultSectionSize()
            + 2 * self._table.frameWidth()
        )
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._cancel_all = QPushButton(strings.QUEUE_CANCEL_ALL)
        self._cancel_all.clicked.connect(queue.cancel_all)
        actions.addWidget(self._cancel_all)
        self._clear = QPushButton(strings.QUEUE_CLEAR_FINISHED)
        self._clear.clicked.connect(self._clear_finished)
        actions.addWidget(self._clear)
        layout.addLayout(actions)

    # ------------------------------------------------------------------

    def _selected_jobs(self) -> list[Job]:
        rows = {index.row() for index in self._table.selectionModel().selectedRows()}
        return [job for row in sorted(rows) if (job := self._model.job_at(row))]

    def _clear_finished(self) -> None:
        self._queue.remove_finished()
        self._model.reload()

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
                lambda: QApplication.clipboard().setText(job.error or "")
            )
            menu.addAction(copy_error)

        if job.log:
            action = QAction(strings.QUEUE_SHOW_LOG, menu)
            action.triggered.connect(lambda: self._show_log(job))
            menu.addAction(action)

        if not menu.isEmpty():
            menu.exec(self._table.viewport().mapToGlobal(position))

    def _open_selected_file(self) -> None:
        jobs = self._selected_jobs()
        if jobs and jobs[0].result_path:
            self._open_path(jobs[0].result_path)

    @staticmethod
    def _open_path(path: Path | None) -> None:
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @staticmethod
    def _reveal(path: Path | None) -> None:
        """Abre o gerenciador de arquivos com o arquivo selecionado.

        Cada sistema tem sua forma; quando nenhuma serve, abrir a pasta já
        resolve o que o usuário quer.
        """
        if not path or not path.exists():
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
                return
            # Linux: o padrão do freedesktop entende o arquivo e seleciona-o nos
            # gerenciadores que suportam; os demais abrem a pasta.
            subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError:
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
        text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        text.setPlainText("\n".join(job.log))
        box.addWidget(text)
        close = QPushButton("Fechar")
        close.clicked.connect(dialog.accept)
        box.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()
