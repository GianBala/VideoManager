"""Adaptador JSON v1; preserva o protocolo atômico existente durante a migração."""
from pathlib import Path

from videomanager.domain.project import Project
from videomanager.infrastructure.storage import project_json as project_io


class JsonProjectRepository:
    def load(self, path: Path) -> tuple[Project, list[Path]]:
        return project_io.load_project(path)

    def save(self, project: Project, path: Path) -> None:
        project_io.save_project(project, path)

__all__ = [
    'Project',
]
