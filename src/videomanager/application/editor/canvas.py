"""Tela e proporção da saída: a mesma regra no painel e na janela de exportação.

As duas telas tinham cópias desta lógica (escolher a proporção acha uma tela;
escolher a tela acerta a proporção; "automática" segue o material), e a janela
importava do painel um nome privado para consultar as listas. Cópias de uma
regra de saída acabam discordando — foi o que já fez a janela mostrar
"Automática" com uma tela escolhida.
"""

from __future__ import annotations

from videomanager.application.formatting import format_aspect_ratio
from videomanager.domain.project import Project, auto_canvas

# Telas oferecidas além das que o próprio material traz, no painel e na janela
# de exportação. São os formatos que os aparelhos e os sites esperam — não uma
# tabela de tudo que existe.
CANVAS_PRESETS: tuple[tuple[int, int], ...] = (
    (3840, 2160),  # 4K UHD 16:9
    (2560, 1440),  # 2K QHD 16:9
    (1920, 1080),  # Full HD 16:9
    (1280, 720),   # HD 16:9
    (854, 480),    # SD 16:9
    (1080, 1920),  # Vertical Full HD 9:16 (TikTok / Reels / Shorts)
    (720, 1280),   # Vertical HD 9:16
    (1440, 1080),  # 4:3 Full HD
    (960, 720),    # 4:3 HD
    (640, 480),    # 4:3 SD
    (1080, 1080),  # Quadrado 1:1
    (720, 720),    # Quadrado 1:1
    (2560, 1080),  # Ultrawide 21:9
)


def aspect_of(canvas: tuple[int, int] | None) -> str | None:
    """A proporção de uma tela escolhida; ``None`` é a automática."""
    return format_aspect_ratio(*canvas) if canvas is not None else None


def canvas_for_aspect(aspect: str | None, current: tuple[int, int] | None) -> tuple[int, int] | None:
    """A tela para uma proporção escolhida.

    Mantém a atual se ela já tem essa proporção; senão, a primeira tela da
    lista com ela. ``None`` (automática) devolve a tela automática.
    """
    if aspect is None:
        return None
    if aspect_of(current) == aspect:
        return current
    return next((size for size in CANVAS_PRESETS if format_aspect_ratio(*size) == aspect), current)


def output_canvas(project: Project, canvas: tuple[int, int] | None,
                  rate: float | None) -> tuple[int, int, float]:
    """Tela e taxa da saída: a escolhida, ou a do material em cada metade."""
    material = auto_canvas(project)
    width, height = canvas or (material.width, material.height)
    return width, height, rate or material.fps
