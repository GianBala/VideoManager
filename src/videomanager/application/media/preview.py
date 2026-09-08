"""Pedidos de prévia independentes de comandos e da representação gráfica."""
from dataclasses import dataclass
from pathlib import Path
from ...domain.project import Project
from ...domain.preview import preview_fps


@dataclass(frozen=True)
class PreviewRequest:
    project: Project
    seconds: float
    size: tuple[int, int]
    token: int
    fps: int
    text_assets: tuple[tuple[int, Path], ...] = ()


def prepare_preview(
    project,
    seconds,
    size,
    token,
    *,
    fps = None,
    text_assets = None,
):
    if min(size) <= 0:
        raise ValueError('A prévia precisa de dimensões positivas.')
    return PreviewRequest(project, max(0.0, seconds), size, token,
                          preview_fps(fps or project.fps), tuple((text_assets or {}).items()))
