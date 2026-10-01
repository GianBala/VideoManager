"""Aba Metadados: abrir um arquivo, editar tags, trilhas e capa, e salvar numa cópia.

O original nunca é alterado: cada salvamento grava "nome (metadados).ext" ao
lado dele. A cópia é conferida antes de aparecer (mesmas trilhas, mesmos
pacotes), e o que o formato não guardou é dito na tela — gravado sem erro não
quer dizer guardado (ver ``infrastructure/ffmpeg/metadata.py``).

A fila fica fora desta aba, como no editor: salvar não é tarefa da fila, é o
fim de uma edição que se acompanha aqui mesmo, e o espaço vale mais como
formulário.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import JobCancelled
from videomanager.application.formatting import format_duration
from videomanager.application.preferences import Preferences as Settings
from videomanager.domain.metadata import COMMON_TAGS
from videomanager.domain.metadata import FileMetadata
from videomanager.domain.metadata import MetadataEdit
from videomanager.domain.metadata import SavedCopy
from videomanager.domain.metadata import editable_tags
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import align_label_column, bind, on_language_change
from videomanager.presentation.qt.ports import DesktopRuntimePort
from videomanager.presentation.qt.tasks import WorkerRunner

_COVER_SIZE = 160
# Campos que costumam ter várias linhas (a descrição de um vídeo do YouTube é
# um texto inteiro): numa linha só, as quebras viravam traços na tela.
_MULTILINE = ("comment", "description")
_MULTILINE_ROWS = 3
# Alça de ampliar abaixo desses campos: alta o bastante para acertar com o mouse.
_GRIP_HEIGHT = 8
# Colunas editáveis da tabela de trilhas.
_TITLE, _LANGUAGE = 3, 4
# Linhas visíveis de cada tabela antes de rolar: sem piso próprio o Qt reserva
# 192 px, que não tem relação com o conteúdo.
_TABLE_ROWS = 3


class _Table(QTableWidget):
    """Tabela que pede a altura de ``_TABLE_ROWS`` linhas e cresce com a sobra.

    A dica padrão de uma área de rolagem é um palpite fixo (192 px) sem relação
    com o conteúdo: duas tabelas assim empurravam o botão de salvar para fora
    da janela padrão.
    """

    def __init__(self, columns: int) -> None:
        super().__init__(0, columns)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(self.horizontalHeader().sizeHint().height()
                              + self.verticalHeader().defaultSectionSize() * _TABLE_ROWS + 2 * self.frameWidth())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), self.minimumHeight())


class _Grip(QWidget):
    """Alça sob um campo de texto: arrastar na vertical o amplia, clique duplo o restaura.

    O Qt não tem campo de texto que o usuário redimensione (o ``QSizeGrip`` só
    alcança janelas), e a descrição de um vídeo costuma ter dezenas de linhas
    para três de altura. O campo nunca fica menor que ``base``, a altura de
    nascença, então restaurar é só voltar a ela.

    A posição é medida na tela, e não no widget: a alça anda junto com o campo
    que cresce, e o ponteiro relativo a ela mudaria a cada passo.
    """

    def __init__(self, target: QPlainTextEdit, base: int) -> None:
        super().__init__()
        self._target = target
        self._base = base
        self._press: tuple[int, int] | None = None  # (y na tela, altura do campo) ao apertar
        self._hover = False
        self.setProperty("role", "plain")
        self.setFixedHeight(_GRIP_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def paintEvent(self, _event) -> None:  # noqa: N802
        # Cores do papel do tema, e não fixas: a paleta da aplicação já segue
        # claro e escuro (ver ``theme.qpalette``).
        role = QPalette.ColorRole.Highlight if self._hover or self._press else QPalette.ColorRole.PlaceholderText
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().color(role), 1))
        middle, left, right = self.height() // 2, self.width() // 2 - 12, self.width() // 2 + 12
        for y in (middle - 1, middle + 1):
            painter.drawLine(left, y, right, y)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = (int(event.globalPosition().y()), self._target.height())
            self.update()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:  # soltou fora e o release se perdeu
            self._press = None
            self.update()
            return
        start, height = self._press
        self._target.setFixedHeight(max(self._base, height + int(event.globalPosition().y()) - start))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._target.setFixedHeight(self._base)


class MetadataPanel(QWidget):
    def __init__(
        self,
        settings: Settings,
        ensure_tools: Callable[[], FFmpegTools | None],
        parent: QWidget | None = None,
        *,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._ensure_tools = ensure_tools
        self._runtime = runtime
        self._meta: FileMetadata | None = None
        self._cover: bytes | None = None
        self._new_cover: Path | None = None
        self._remove_cover = False
        self._cover_pixmap: QPixmap | None = None
        self._baseline: MetadataEdit | None = None
        self._loading: Path | None = None
        self._saving = None
        self._saved: SavedCopy | None = None
        self._cancelled = False
        self._token = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._runner = WorkerRunner(self._pool)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_file_group())
        # Duas colunas: as tags têm linhas curtas e muitas; capa, campos livres
        # e trilhas cabem ao lado, e tudo aparece sem rolar na janela padrão.
        middle = QHBoxLayout()
        middle.setSpacing(10)
        middle.addWidget(self._build_tags_group(), 1, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_cover_group())
        right.addWidget(self._build_others_group())
        right.addWidget(self._build_tracks_group())
        middle.addLayout(right, 1)
        layout.addLayout(middle)

        # Em linha própria: texto que quebra ao lado de botões nasce cortado.
        self._result = QLabel()
        self._result.setProperty("role", "dim")
        self._result.setWordWrap(True)
        self._result.setVisible(False)
        layout.addWidget(self._result)
        actions = QHBoxLayout()
        self._reveal = bind(QPushButton(), "setText", lambda: strings.META_REVEAL)
        self._reveal.clicked.connect(lambda: self._saved and self._runtime.reveal_file(self._saved.path))
        self._reveal.setVisible(False)
        actions.addWidget(self._reveal)
        actions.addStretch(1)
        self._discard = bind(QPushButton(), "setText", lambda: strings.META_DISCARD)
        self._discard.clicked.connect(self._discard_changes)
        actions.addWidget(self._discard)
        self._cancel = bind(QPushButton(), "setText", lambda: strings.META_CANCEL)
        self._cancel.clicked.connect(self._runner.cancel_all)
        self._cancel.setVisible(False)
        actions.addWidget(self._cancel)
        self._save = bind(QPushButton(), "setText", lambda: strings.META_SAVE)
        bind(self._save, "setToolTip", lambda: strings.META_SAVE_TIP.format(label=strings.META_SAVE))
        self._save.setProperty("role", "primary")
        self._save.clicked.connect(self.save)
        actions.addWidget(self._save)
        layout.addLayout(actions)
        layout.addStretch(1)

        # Também põe os cabeçalhos das tabelas, que não passam por ``bind``.
        self._retranslate()
        on_language_change(self._retranslate)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_file_group(self) -> QGroupBox:
        group = bind(QGroupBox(), "setTitle", lambda: strings.META_FILE_GROUP)
        row = QHBoxLayout(group)
        pick = bind(QPushButton(), "setText", lambda: strings.META_OPEN)
        bind(pick, "setToolTip", lambda: strings.META_OPEN_TIP.format(label=strings.META_OPEN))
        pick.clicked.connect(self.choose_file)
        row.addWidget(pick)
        self._info = QLabel()
        self._info.setProperty("role", "dim")
        row.addWidget(self._info, 1)
        return group

    def _build_tags_group(self) -> QGroupBox:
        self._tags_group = bind(QGroupBox(), "setTitle", lambda: strings.META_TAGS_GROUP)
        box = QVBoxLayout(self._tags_group)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self._fields: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._grips: dict[str, _Grip] = {}
        self._labels: list[QLabel] = []
        for key in COMMON_TAGS:
            label = bind(QLabel(), "setText", lambda key=key: strings.META_FIELDS[key])
            if key in _MULTILINE:
                field = QPlainTextEdit()
                field.setTabChangesFocus(True)
                lines = field.fontMetrics().lineSpacing() * _MULTILINE_ROWS
                base = lines + 2 * field.frameWidth() + 8
                field.setFixedHeight(base)
                field.textChanged.connect(self._refresh)
                # ``plain``: sem ele o contêiner herda o fundo da janela e pinta
                # um retângulo escuro sobre a superfície do grupo.
                row = QWidget()
                row.setProperty("role", "plain")
                column = QVBoxLayout(row)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(0)
                column.addWidget(field)
                self._grips[key] = bind(_Grip(field, base), "setToolTip", lambda: strings.META_GROW_TIP)
                column.addWidget(self._grips[key])
            else:
                field = row = QLineEdit()
                field.textEdited.connect(self._refresh)
            self._fields[key] = field
            self._labels.append(label)
            form.addRow(label, row)
        align_label_column(self._labels)
        box.addLayout(form)
        return self._tags_group

    def _build_others_group(self) -> QGroupBox:
        self._others_group = bind(QGroupBox(), "setTitle", lambda: strings.META_OTHER_FIELDS)
        box = QVBoxLayout(self._others_group)
        self._others = _Table(2)
        self._others.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._others.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._others.itemChanged.connect(self._refresh)
        box.addWidget(self._others)
        buttons = QHBoxLayout()
        self._add_field = bind(QPushButton(), "setText", lambda: strings.META_ADD_FIELD)
        self._add_field.clicked.connect(self._add_other)
        self._remove_field = bind(QPushButton(), "setText", lambda: strings.META_REMOVE_FIELD)
        self._remove_field.clicked.connect(self._remove_others)
        buttons.addWidget(self._add_field)
        buttons.addWidget(self._remove_field)
        buttons.addStretch(1)
        box.addLayout(buttons)
        return self._others_group

    def _build_cover_group(self) -> QGroupBox:
        self._cover_group = bind(QGroupBox(), "setTitle", lambda: strings.META_COVER_GROUP)
        box = QHBoxLayout(self._cover_group)
        self._cover_view = QLabel()
        self._cover_view.setFixedSize(_COVER_SIZE, _COVER_SIZE)
        self._cover_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_view.setWordWrap(True)
        self._cover_view.setProperty("role", "dim")
        box.addWidget(self._cover_view)
        buttons = QVBoxLayout()
        self._change_cover = bind(QPushButton(), "setText", lambda: strings.META_COVER_CHANGE)
        self._change_cover.clicked.connect(self._choose_cover)
        self._drop_cover = bind(QPushButton(), "setText", lambda: strings.META_COVER_REMOVE)
        self._drop_cover.clicked.connect(self._clear_cover)
        buttons.addWidget(self._change_cover)
        buttons.addWidget(self._drop_cover)
        buttons.addStretch(1)
        box.addLayout(buttons)
        box.addStretch(1)
        return self._cover_group

    def _build_tracks_group(self) -> QGroupBox:
        self._tracks_group = bind(QGroupBox(), "setTitle", lambda: strings.META_TRACKS_GROUP)
        box = QVBoxLayout(self._tracks_group)
        self._tracks = _Table(len(strings.META_TRACK_HEADERS))
        header = self._tracks.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_TITLE, QHeaderView.ResizeMode.Stretch)
        self._tracks.itemChanged.connect(self._refresh)
        box.addWidget(self._tracks)
        self._tracks_note = bind(QLabel(), "setText", lambda: strings.META_TRACKS_ON_FILE)
        self._tracks_note.setProperty("role", "dim")
        self._tracks_note.setWordWrap(True)
        self._tracks_note.setVisible(False)
        box.addWidget(self._tracks_note)
        return self._tracks_group

    def _retranslate(self) -> None:
        align_label_column(self._labels)
        self._others.setHorizontalHeaderLabels([strings.META_FIELD_HEADER, strings.META_VALUE_HEADER])
        self._tracks.setHorizontalHeaderLabels(list(strings.META_TRACK_HEADERS))
        blocked = self._tracks.blockSignals(True)
        # Célula não passa por ``bind``: o tipo e a dica do idioma são refeitos aqui.
        for row in range(self._tracks.rowCount()):
            kind = self._tracks.item(row, 1)
            kind.setText(strings.META_TRACK_KINDS.get(kind.data(Qt.ItemDataRole.UserRole), kind.data(Qt.ItemDataRole.UserRole)))
            self._tracks.item(row, _LANGUAGE).setToolTip(strings.META_LANGUAGE_TIP)
        self._tracks.blockSignals(blocked)
        self._refresh()

    # ------------------------------------------------------------------
    # Abrir
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.open_file(paths[0])

    def choose_file(self) -> None:
        start = str(self._meta.path.parent if self._meta else Path.home())
        path, _ = QFileDialog.getOpenFileName(self, strings.META_OPEN, start, strings.META_FILE_FILTER)
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        if self._saving is not None or not self.confirm_discard():
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        self._token += 1
        self._runner.cancel_all()
        token = self._token
        self._loading = path
        worker = self._runtime.metadata_reader(path, tools)
        worker.signals.finished.connect(lambda result: self._on_loaded(token, result),
                                        Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(lambda error: self._on_load_failed(token, error),
                                      Qt.ConnectionType.QueuedConnection)
        self._runner.start(worker, worker.signals.done)
        self._refresh()

    def _on_loaded(self, token: int, result) -> None:
        if token != self._token:
            return
        self._loading = None
        self._install(*result)

    def _on_load_failed(self, token: int, error) -> None:
        if token != self._token:
            return
        self._loading = None
        self._refresh()
        if not isinstance(error, JobCancelled):
            QMessageBox.warning(self, strings.DIALOG_WARNING_TITLE, str(error))

    def _install(self, meta: FileMetadata, cover: bytes | None) -> None:
        self._meta, self._cover = meta, cover
        self._new_cover, self._remove_cover = None, False
        self._update_cover_pixmap()
        self._saved, self._cancelled = None, False
        tags = dict((key.lower(), (key, value)) for key, value in editable_tags(meta))
        for key, field in self._fields.items():
            value = tags.pop(key, ("", ""))[1]
            if isinstance(field, QPlainTextEdit):
                blocked = field.blockSignals(True)
                field.setPlainText(value)
                field.blockSignals(blocked)
            else:
                field.setText(value)
        blocked = self._others.blockSignals(True)
        self._others.setRowCount(0)
        for key, value in tags.values():
            self._append_other(key, value)
        self._others.blockSignals(blocked)

        blocked = self._tracks.blockSignals(True)
        self._tracks.setRowCount(0)
        for number, track in enumerate(meta.tracks, start=1):
            row = self._tracks.rowCount()
            self._tracks.insertRow(row)
            cells = (str(number), strings.META_TRACK_KINDS.get(track.kind, track.kind), track.codec,
                     track.title, track.language)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                editable = column in (_TITLE, _LANGUAGE) and not meta.tags_on_stream
                if not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, track.index)
                if column == 1:
                    item.setData(Qt.ItemDataRole.UserRole, track.kind)
                if column == _LANGUAGE:
                    item.setToolTip(strings.META_LANGUAGE_TIP)
                self._tracks.setItem(row, column, item)
        self._tracks.blockSignals(blocked)
        self._baseline = self.current_edit()
        self._refresh()

    # ------------------------------------------------------------------
    # Editar
    # ------------------------------------------------------------------

    def _append_other(self, key: str = "", value: str = "") -> int:
        row = self._others.rowCount()
        self._others.insertRow(row)
        self._others.setItem(row, 0, QTableWidgetItem(key))
        self._others.setItem(row, 1, QTableWidgetItem(value))
        return row

    def _add_other(self) -> None:
        row = self._append_other()
        self._others.setCurrentCell(row, 0)
        self._others.editItem(self._others.item(row, 0))
        self._refresh()

    def _remove_others(self) -> None:
        for row in sorted({index.row() for index in self._others.selectedIndexes()}, reverse=True):
            self._others.removeRow(row)
        self._refresh()

    def _choose_cover(self) -> None:
        start = str(self._meta.path.parent if self._meta else Path.home())
        path, _ = QFileDialog.getOpenFileName(self, strings.META_COVER_CHANGE, start, strings.META_COVER_FILTER)
        if path:
            self._new_cover, self._remove_cover = Path(path), False
            self._update_cover_pixmap()
            self._refresh()

    def _clear_cover(self) -> None:
        self._new_cover, self._remove_cover = None, True
        self._update_cover_pixmap()
        self._refresh()

    def _discard_changes(self) -> None:
        if self._meta is not None:
            self._install(self._meta, self._cover)

    def current_edit(self) -> MetadataEdit | None:
        if self._meta is None:
            return None
        # Os valores vão como estão: tirar espaço ou quebra de linha do fim
        # regravaria alterado um campo que o usuário nem tocou.
        tags = [(key, field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text())
                for key, field in self._fields.items()]
        for row in range(self._others.rowCount()):
            key, value = self._others.item(row, 0), self._others.item(row, 1)
            if key is not None and key.text().strip():
                tags.append((key.text().strip(), value.text() if value is not None else ""))
        tracks = tuple(
            (self._tracks.item(row, 0).data(Qt.ItemDataRole.UserRole), self._tracks.item(row, _TITLE).text(),
             self._tracks.item(row, _LANGUAGE).text())
            for row in range(self._tracks.rowCount())
        )
        return MetadataEdit(tuple(tags), tracks, self._new_cover, self._remove_cover)

    @property
    def has_unsaved_changes(self) -> bool:
        return self._meta is not None and self.current_edit() != self._baseline

    def confirm_discard(self) -> bool:
        if not self.has_unsaved_changes:
            return True
        answer = QMessageBox.question(
            self, strings.META_MODIFIED_TITLE, strings.META_MODIFIED_BODY.format(name=self._meta.path.name),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    # ------------------------------------------------------------------
    # Salvar
    # ------------------------------------------------------------------

    def save(self) -> None:
        edit = self.current_edit()
        if edit is None or self._saving is not None or self._loading is not None:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        worker = self._runtime.metadata_writer(self._meta, edit, tools,
                                               self._runtime.download_directory(self._settings))
        self._saving = worker
        self._saved, self._cancelled = None, False
        worker.signals.finished.connect(lambda saved: self._on_saved(edit, saved), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_save_failed, Qt.ConnectionType.QueuedConnection)
        self._runner.start(worker, worker.signals.done)
        self._refresh()

    def _on_saved(self, edit: MetadataEdit, saved: SavedCopy) -> None:
        self._saving = None
        self._saved = saved
        # A cópia guardou o que se pediu: não há mais o que perder ao fechar.
        self._baseline = edit
        self._refresh()

    def _on_save_failed(self, error) -> None:
        self._saving = None
        self._refresh()
        if isinstance(error, JobCancelled):
            self._cancelled = True
            self._refresh()
            return
        QMessageBox.warning(self, strings.DIALOG_WARNING_TITLE, str(error))

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings

    def shutdown(self) -> None:
        self._token += 1
        self._runner.cancel_all()
        self._pool.waitForDone(2000)

    # ------------------------------------------------------------------
    # Estado na tela
    # ------------------------------------------------------------------

    def _refresh(self, *_args) -> None:
        meta, busy = self._meta, self._saving is not None or self._loading is not None
        if self._loading is not None:
            self._info.setText(strings.META_LOADING.format(name=self._loading.name))
        elif meta is None:
            self._info.setText(strings.META_DROP_HINT)
        else:
            self._info.setText(strings.META_FILE_INFO.format(
                name=meta.path.name, format=meta.extension.upper(), duration=format_duration(meta.duration)))
        for widget in (self._tags_group, self._others_group, self._tracks_group, self._cover_group):
            widget.setEnabled(meta is not None and not busy)
        self._tracks_note.setVisible(bool(meta and meta.tags_on_stream))
        self._remove_field.setEnabled(self._others.rowCount() > 0)
        self._save.setEnabled(meta is not None and not busy)
        self._discard.setEnabled(self.has_unsaved_changes and not busy)
        self._cancel.setVisible(self._saving is not None)
        self._refresh_cover()
        self._refresh_result()

    def _update_cover_pixmap(self) -> None:
        """Decodifica e reduz a capa uma vez por troca de capa.

        Feito no ``_refresh``, que roda a cada tecla, custava 59 ms por tecla
        com uma capa de 3000×3000 (medido) — e, com capa nova, lia o arquivo
        do disco a cada vez.
        """
        pixmap = QPixmap()
        if self._new_cover is not None:
            pixmap.load(str(self._new_cover))
        elif self._cover and not self._remove_cover:
            pixmap.loadFromData(self._cover)
        self._cover_pixmap = None if pixmap.isNull() else pixmap.scaled(
            _COVER_SIZE, _COVER_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def _refresh_cover(self) -> None:
        meta = self._meta
        accepts = bool(meta and meta.accepts_cover)
        self._change_cover.setEnabled(accepts)
        self._drop_cover.setEnabled(accepts and (bool(self._cover) or self._new_cover is not None)
                                    and not self._remove_cover)
        if self._cover_pixmap is not None:
            self._cover_view.setPixmap(self._cover_pixmap)
            return
        self._cover_view.setPixmap(QPixmap())
        if meta is not None and not accepts:
            self._cover_view.setText(strings.META_COVER_UNSUPPORTED)
        elif self._remove_cover:
            self._cover_view.setText(strings.META_COVER_REMOVED)
        else:
            self._cover_view.setText(strings.META_COVER_NONE)

    def _refresh_result(self) -> None:
        saved = self._saved
        if self._saving is not None:
            text = strings.META_SAVING
        elif self._cancelled:
            text = strings.META_CANCELLED
        elif saved is None:
            text = ""
        else:
            template = strings.META_SAVED_FALLBACK if saved.fallback_used else strings.META_SAVED
            text = template.format(name=saved.path.name)
            if saved.not_saved:
                text += "\n" + strings.META_NOT_SAVED.format(fields=", ".join(str(item) for item in saved.not_saved))
        self._result.setText(text)
        self._result.setVisible(bool(text))
        self._reveal.setVisible(saved is not None)
