"""Proprietário da edição, histórico e snapshots de persistência."""
from dataclasses import dataclass
from pathlib import Path

from videomanager.domain.project import Project
from videomanager.domain.project import new_project


@dataclass(frozen=True)
class SessionSnapshot:
    generation: int
    revision: int
    project: Project
    path: Path | None


class EditorSession:
    """Mutações serializadas pelo controller; workers recebem apenas snapshots."""
    def __init__(self) -> None:
        self._project = new_project()
        self._path: Path | None = None
        self._saved = self._project
        self._history: list[Project] = []
        self._future: list[Project] = []
        self._generation = 0
        self._revision = 0

    @property
    def project(self) -> Project:
        return self._project

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def history(self) -> tuple[Project, ...]:
        return tuple(self._history)

    @property
    def future(self) -> tuple[Project, ...]:
        return tuple(self._future)

    @property
    def has_changes(self) -> bool:
        return self.project != self._saved

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(self._generation, self._revision, self.project, self.path)

    def is_current(self, snapshot: SessionSnapshot) -> bool:
        return (snapshot.generation, snapshot.revision) == (self._generation, self._revision)

    def replace_current(self, project: Project) -> None:
        # A igualdade de conteúdo ignora IDs; seleção e histórico precisam
        # receber também um documento igual com identidades diferentes.
        if project is not self._project:
            self._project = project
            self._revision += 1

    def set_path(self, path: Path | None) -> None:
        self._path = path

    def mark_saved(self, snapshot: SessionSnapshot | None = None, path: Path | None = None) -> bool:
        if snapshot is not None and snapshot.generation != self._generation:
            return False
        self._saved = snapshot.project if snapshot is not None else self.project
        if path is not None:
            self._path = path
        return True

    def reset(self, project: Project, path: Path | None = None) -> None:
        self._generation += 1
        self._revision += 1
        self._project = project
        self._path = path
        self._history.clear()
        self._future.clear()
        self.mark_saved()

    def remember(self) -> None:
        self._history.append(self.project)
        del self._history[:-60]
        self._future.clear()

    def undo(self) -> bool:
        if not self._history:
            return False
        self._future.append(self.project)
        self.replace_current(self._history.pop())
        return True

    def redo(self) -> bool:
        if not self._future:
            return False
        self._history.append(self.project)
        self.replace_current(self._future.pop())
        return True
