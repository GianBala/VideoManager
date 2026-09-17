"""Coordenação de arquivos, acervo e leitura assíncrona do projeto de edição."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Qt, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from videomanager.domain.project import new_project
from videomanager.application.editor.media import MediaResult
from videomanager.presentation.qt.tasks import WorkerRunner
from videomanager.presentation.qt import strings


class _SaveProgress(QProgressDialog):
    """A conclusão vem do worker; Escape e fechar não abandonam a gravação."""
    def reject(self):
        pass

    def closeEvent(self, event):
        event.ignore()

    def finish(self, accepted):
        self.done(1 if accepted else 0)


class EditorProject(QObject):
    """Mantém I/O e ciclo de vida fora do painel e descarta respostas obsoletas."""

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self._runtime = panel.desktop_runtime
        self.panel = panel
        pool = QThreadPool(self)
        pool.setMaxThreadCount(1)
        self.runner = WorkerRunner(pool)
        self.worker: object | None = None
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
        p.commit_pending_edits()
        path = p.project_path
        if choose_path or path is None:
            chosen, _ = QFileDialog.getSaveFileName(
                p, strings.EDIT_SAVE_PROJECT, str(path or Path.home() / "projeto.vmp"),
                strings.EDIT_PROJECT_FILTER,
            )
            if not chosen:
                return False
            path = Path(chosen)
        snapshot = p.editor.session.snapshot()
        dialog = _SaveProgress(strings.EDIT_SAVING_PROJECT, "", 0, 0, p)
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        outcome = []
        worker = self._runtime.function_worker(lambda: p.editor.write_snapshot(snapshot, path))
        def finished(_):
            outcome.append(None)
            dialog.finish(True)
        def failed(error):
            outcome.append(error)
            dialog.finish(False)
        worker.signals.finished.connect(finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(failed, Qt.ConnectionType.QueuedConnection)
        self.runner.start(worker, worker.signals.done)
        dialog.exec()
        dialog.deleteLater()
        if not outcome or outcome[0] is not None:
            if outcome:
                QMessageBox.warning(p, strings.DIALOG_ERROR_TITLE, str(outcome[0]))
            return False
        accepted = p.editor.accept_saved(snapshot, path)
        p.refresh_project_label()
        return accepted

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

    def import_files(self, paths: list[Path], *, insert: bool = False, placement=None) -> None:
        if paths:
            self._start(paths, insert=insert, placement=placement)

    def _start(self, paths, *, project_path=None, insert=False, placement=None) -> None:
        p = self.panel
        tools = p.ensure_tools()
        if tools is None and project_path is None:
            return
        self.cancel_pending()
        p.stop_playback()
        self.path, self.insert, self.expected = project_path, insert, p.editor.session.snapshot()
        # Destino de arquivos soltos na linha do tempo: (trilha, posição da
        # trilha nova, instante). Aplicado quando a leitura termina.
        self.placement = placement
        worker = self._runtime.media_worker(self.token, tools, paths, project_path=project_path,
                             known={ref.path: ref for ref in p.media_references})
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
            if not p.editor.accept_opened(self.expected, result, self.path):
                QMessageBox.warning(p, strings.DIALOG_WARNING_TITLE, strings.EDIT_LOAD_CHANGED)
                return
            p.install_project(result.project, self.path, result.references, result.probed, reset=False)
            if result.missing:
                names = "\n".join(f"• {path.name} ({path})" for path in result.missing)
                QMessageBox.warning(p, strings.DIALOG_WARNING_TITLE,
                                    strings.EDIT_MISSING_MEDIA.format(files=names))
        else:
            p.accept_import(result, insert=self.insert, placement=self.placement)
            if result.rejected:
                QMessageBox.warning(p, strings.DIALOG_WARNING_TITLE,
                                    strings.EDIT_IMPORT_REJECTED + "\n\n" + "\n".join(result.rejected))

    def _install(self, project, path, references, probed) -> None:
        self.panel.install_project(project, path, references, probed)
