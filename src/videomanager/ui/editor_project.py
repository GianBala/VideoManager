"""Coordenação de arquivos, acervo e leitura assíncrona do projeto de edição."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Qt, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from ..core.errors import ProjectError
from ..core.project import new_project
from ..core.project_io import save_project
from ..workers.media_worker import MediaResult, MediaWorker
from ..workers.runner import WorkerRunner
from . import strings


class EditorProject(QObject):
    """Mantém I/O e ciclo de vida fora do painel e descarta respostas obsoletas."""

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self.panel = panel
        pool = QThreadPool(self)
        pool.setMaxThreadCount(1)
        self.runner = WorkerRunner(pool)
        self.worker: MediaWorker | None = None
        self.dialog: QProgressDialog | None = None
        self.token = 0
        self.path: Path | None = None
        self.insert = False
        self.expected = None

    @property
    def busy(self) -> bool:
        return self.worker is not None

    def confirm_replace(self) -> bool:
        p = self.panel
        if not p.has_unsaved_changes:
            return True
        answer = QMessageBox.question(
            p, strings.PROJECT_MODIFIED_TITLE, strings.PROJECT_MODIFIED_BODY,
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def _close_progress(self) -> None:
        if self.dialog is not None:
            self.dialog.reset()
            self.dialog.deleteLater()
            self.dialog = None

    def cancel_pending(self) -> None:
        self.token += 1
        self.runner.cancel_all()
        self.worker = None
        self._close_progress()

    def new(self) -> bool:
        if not self.confirm_replace():
            return False
        self.cancel_pending()
        self._install(new_project(), None, [], {})
        return True

    def save(self, *, choose_path: bool = False) -> bool:
        p = self.panel
        path = p._project_path
        if choose_path or path is None:
            chosen, _ = QFileDialog.getSaveFileName(
                p, strings.EDIT_SAVE_PROJECT, str(path or Path.home() / "projeto.vmp"),
                strings.EDIT_PROJECT_FILTER,
            )
            if not chosen:
                return False
            path = Path(chosen)
        try:
            save_project(p._project, path)
        except ProjectError as exc:
            QMessageBox.warning(p, strings.DIALOG_ERROR_TITLE, str(exc))
            return False
        p._project_path = path
        p._session.mark_saved()
        p._update_project_label()
        return True

    def open(self, path: Path | None = None) -> bool:
        """Retorna quando o pedido foi aceito; a edição muda somente ao concluir."""
        if not self.confirm_replace():
            return False
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(
                self.panel, strings.EDIT_OPEN_PROJECT, str(Path.home()), strings.EDIT_PROJECT_FILTER,
            )
            if not chosen:
                return False
            path = Path(chosen)
        self._start([], project_path=path)
        return True

    def import_files(self, paths: list[Path], *, insert: bool = False) -> None:
        if paths:
            self._start(paths, insert=insert)

    def _start(self, paths, *, project_path=None, insert=False) -> None:
        p = self.panel
        tools = p._ensure_tools()
        if tools is None and project_path is None:
            return
        self.cancel_pending()
        p._stop_playback()
        self.path, self.insert, self.expected = project_path, insert, p._project
        worker = MediaWorker(self.token, tools, paths, project_path=project_path,
                             known={ref.path: ref for ref in p._pool})
        self.worker = worker
        self.dialog = QProgressDialog(strings.EDIT_READING_MEDIA, strings.EDIT_READ_CANCEL, 0, 0, p)
        self.dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.canceled.connect(self.cancel_pending)
        self.dialog.show()
        worker.signals.progress.connect(self._progress)
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        worker.signals.cancelled.connect(self._cancelled)
        self.runner.start(worker, worker.signals.done)

    @Slot(int, int, int)
    def _progress(self, token, completed, total) -> None:
        if token == self.token and self.dialog is not None:
            self.dialog.setRange(0, total)
            self.dialog.setValue(completed)

    @Slot(int)
    def _cancelled(self, token) -> None:
        if token == self.token:
            self.worker = None
            self._close_progress()

    @Slot(int, str)
    def _failed(self, token, message) -> None:
        if token == self.token:
            self._cancelled(token)
            QMessageBox.warning(self.panel, strings.DIALOG_ERROR_TITLE, message)

    @Slot(int, object)
    def _finished(self, token, result: MediaResult) -> None:
        if token != self.token:
            return
        self._cancelled(token)
        p = self.panel
        if result.project is not None:
            if p._project != self.expected:
                QMessageBox.warning(p, strings.DIALOG_WARNING_TITLE, strings.EDIT_LOAD_CHANGED)
                return
            self._install(result.project, self.path, result.references, result.probed)
            if result.missing:
                names = "\n".join(f"• {path.name} ({path})" for path in result.missing)
                QMessageBox.warning(p, strings.DIALOG_WARNING_TITLE,
                                    strings.EDIT_MISSING_MEDIA.format(files=names))
        else:
            p._probed.update(result.probed)
            existing = {ref.path for ref in p._pool}
            p._pool.extend(ref for ref in result.references if ref.path not in existing)
            p._refresh_pool()
            if result.references:
                p._media_list.setCurrentRow(p._pool.index(result.references[-1]))
                if self.insert:
                    p._remember()
                    for reference in result.references:
                        p._place(reference)
                    p._after_edit(refit=True)
            if result.rejected:
                QMessageBox.warning(p, strings.DIALOG_WARNING_TITLE,
                                    strings.EDIT_IMPORT_REJECTED + "\n\n" + "\n".join(result.rejected))

    def _install(self, project, path, references, probed) -> None:
        p = self.panel
        p._stop_playback()
        p._background.cancel_all()
        p._runner.cancel_all()
        p._frame_token = next(p._tokens)
        p._strip_tokens.clear()
        for clip_id in list(p._strip_workers):
            p._cancel_strip(clip_id)
        p._session.reset(project, path)
        p._pool = list(references)
        p._pool_thumbnails.clear()
        p._probed = dict(probed)
        p._canvas_choice = (project.width, project.height) if path else None
        p._rate_choice = project.fps if path else None
        p._keyframes = ()
        p._keyframe_source = None
        p._clipboard = None
        p._refresh_pool()
        p._after_edit(refit=True)
        p._session.mark_saved()
        p._timeline.fit()
        p._update_project_label()
