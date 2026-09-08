"""Casos de uso do ciclo de vida: I/O separado da instalação de resultados."""
from pathlib import Path

from videomanager.application.editor.media import MediaResult
from videomanager.application.editor.session import EditorSession
from videomanager.application.editor.session import SessionSnapshot
from videomanager.application.ports.rendering import TextRasterizer
from videomanager.application.ports.rendering import collect_text_assets
from videomanager.application.ports.editor import ProjectRepository


class EditorService:
    def __init__(self, repository: ProjectRepository, session: EditorSession | None = None, rasterizer: TextRasterizer | None = None):
        self.rasterizer = rasterizer
        self.repository = repository
        self.session = session or EditorSession()

    def write_snapshot(self, snapshot: SessionSnapshot, path: Path) -> None:
        """Executado na fila serial de I/O; não modifica a sessão."""
        self.repository.save(snapshot.project, path)

    def accept_saved(self, snapshot: SessionSnapshot, path: Path) -> bool:
        return self.session.mark_saved(snapshot, path)

    def accept_opened(self, expected: SessionSnapshot, result: MediaResult, path: Path) -> bool:
        if result.project is None or not self.session.is_current(expected):
            return False
        self.session.reset(result.project, path)
        return True

    def text_assets(self, project):
        return collect_text_assets(project, self.rasterizer)
