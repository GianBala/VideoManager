"""Contrato de rasterização: o domínio recebe um adaptador sem importar Qt."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .errors import ConversionError
from .project import Clip

_renderer: Callable[[Clip], Path] | None = None


def set_text_renderer(renderer: Callable[[Clip], Path]) -> None:
    """Configura o adaptador ao inicializar a aplicação."""
    global _renderer
    _renderer = renderer


def render_text_to_image(clip: Clip) -> Path:
    """Obtém um recurso imutável para o grafo de composição."""
    if _renderer is None:
        raise ConversionError("O renderizador de textos não foi inicializado.")
    return _renderer(clip)
