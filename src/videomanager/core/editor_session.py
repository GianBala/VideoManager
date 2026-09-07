"""Estado da edição, histórico e ponto salvo, sem dependência de interface."""

from pathlib import Path

from .project import Project, new_project


class EditorSession:
    """Compara conteúdo com o ponto salvo, inclusive após apagar tudo ou desfazer."""

    def __init__(self) -> None:
        self.project = new_project()
        self.path: Path | None = None
        self.saved = self.project
        self.history: list[Project] = []
        self.future: list[Project] = []

    @property
    def has_changes(self) -> bool:
        return self.project != self.saved

    def mark_saved(self) -> None:
        self.saved = self.project

    def reset(self, project: Project, path: Path | None = None) -> None:
        self.project = project
        self.path = path
        self.history.clear()
        self.future.clear()
        self.mark_saved()

    def remember(self) -> None:
        self.history.append(self.project)
        del self.history[:-60]
        self.future.clear()

    def undo(self) -> bool:
        if not self.history:
            return False
        self.future.append(self.project)
        self.project = self.history.pop()
        return True

    def redo(self) -> bool:
        if not self.future:
            return False
        self.history.append(self.project)
        self.project = self.future.pop()
        return True
