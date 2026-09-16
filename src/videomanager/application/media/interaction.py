"""Planos imutáveis para manipulação imediata de um objeto em um instante."""
from dataclasses import dataclass, replace

from ...domain.project import Clip, Project, TrackKind


@dataclass(frozen=True)
class InteractionPlan:
    background: Project
    foreground: Project
    source: Project
    clip_id: int
    seconds: float


def interaction_plan(project: Project, clip_id: int, seconds: float) -> InteractionPlan | None:
    """Separa a pilha sem tentar decompor filtros que dependem do objeto móvel."""
    if any(c.start <= seconds < c.end for c in project.transition_contexts()):
        return None
    ordered = [c for t in reversed(project.tracks)
               if t.visible and t.kind is not TrackKind.AUDIO
               for c in t.sorted_clips() if c.contains(seconds) and c.has_image and not c.audio_only]
    selected = next((i for i, c in enumerate(ordered) if c.clip_id == clip_id), None)
    if selected is None:
        return None
    clip = ordered[selected]
    if clip.overlay_type in ('filter', 'transition'):
        return None
    if any(c.overlay_type in ('filter', 'transition') for c in ordered[selected + 1:]):
        return None

    def subset(clips: list[Clip]) -> Project:
        ids = {c.clip_id for c in clips}
        return replace(project, tracks=tuple(replace(t, clips=tuple(c for c in t.clips if c.clip_id in ids))
                                              for t in project.tracks))

    # Retirar somente a pose torna o plano estável ao longo do gesto. Tempo,
    # origem, chroma, texto e todas as demais camadas continuam fazendo parte dele.
    source = subset([clip]).with_updated_clip(clip_id, x=.5, y=.5, scale=1.,
                    scale_x=1., scale_y=1., rotation=0., opacity=1., keyframes=())
    return InteractionPlan(subset(ordered[:selected]), subset(ordered[selected + 1:]),
                           source, clip_id, seconds)
