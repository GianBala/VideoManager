"""Recursos de texto entregues ao backend como dados, sem tipos Qt."""
from pathlib import Path
from typing import Protocol
from videomanager.domain.project import Clip
from videomanager.domain.project import Project


class TextRasterizer(Protocol):
    def render(self, clip: Clip) -> Path: ...


def collect_text_assets(project: Project, rasterizer: TextRasterizer | None) -> dict[int, Path]:
    clips = [clip for clip in project.clips if clip.overlay_type == 'text']
    if clips and rasterizer is None:
        raise ValueError('O renderizador de textos não foi fornecido.')
    return {clip.clip_id: rasterizer.render(clip) for clip in clips}
