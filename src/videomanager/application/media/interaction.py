"""Planos imutáveis para manipulação imediata de um objeto em um instante."""
from dataclasses import dataclass, replace

from ...domain.project import Clip, OverlayType, Project, TrackKind


@dataclass(frozen=True)
class InteractionPlan:
    background: Project
    foreground: Project
    source: Project
    clip_id: int
    seconds: float
    # Se o gesto precisa da imagem do fundo desfocado como quarta camada. É a
    # opção ligada, e não "aparece agora": a pose muda durante o arrasto.
    blur: bool = False
    # Os desfoques de região **acima** do item, de baixo para cima, cada um com o que vem depois dele até o
    # próximo. O desfoque borra o que o item móvel desenha, então não cabe numa imagem pronta: a prévia o refaz
    # a cada movimento. ``foreground`` é só o que está entre o item e o primeiro desfoque.
    stages: tuple[tuple[Clip, Project], ...] = ()


def interaction_plan(project: Project, clip_id: int, seconds: float) -> InteractionPlan | None:
    """Separa a pilha sem tentar decompor filtros que dependem do objeto móvel.

    Filtro de tela inteira ou transição acima do item mudam o resultado de tudo que está abaixo e não têm como ser
    refeitos a cada movimento: sem plano. O desfoque de região também depende do item, mas é só um recorte, e a
    prévia sabe refazê-lo (``stages``).
    """
    if any(c.start <= seconds < c.end for c in project.transition_contexts()):
        return None
    ordered = [c for t in reversed(project.tracks)
               if t.visible and t.kind is not TrackKind.AUDIO
               for c in t.sorted_clips() if c.contains(seconds) and c.has_image and not c.audio_only]
    selected = next((i for i, c in enumerate(ordered) if c.clip_id == clip_id), None)
    if selected is None:
        return None
    clip = ordered[selected]
    if clip.overlay_type in (OverlayType.FILTER, OverlayType.TRANSITION):
        return None
    above = ordered[selected + 1:]
    if any(c.overlay_type is OverlayType.TRANSITION or (c.overlay_type is OverlayType.FILTER and not c.has_region)
           for c in above):
        return None

    def subset(clips: list[Clip]) -> Project:
        ids = {c.clip_id for c in clips}
        return replace(project, tracks=tuple(replace(t, clips=tuple(c for c in t.clips if c.clip_id in ids))
                                              for t in project.tracks))

    # Retirar somente a pose torna o plano estável ao longo do gesto. Tempo,
    # origem, chroma, texto e todas as demais camadas continuam fazendo parte dele.
    source = subset([clip]).with_updated_clip(clip_id, x=.5, y=.5, scale=1.,
                    scale_x=1., scale_y=1., rotation=0., opacity=1., keyframes=())
    head: list[Clip] = []
    regions: list[tuple[Clip, list[Clip]]] = []
    for c in above:
        if c.has_region:
            regions.append((c, []))
        else:
            (regions[-1][1] if regions else head).append(c)
    return InteractionPlan(subset(ordered[:selected]), subset(head), source, clip_id, seconds,
                           blur=clip.has_blur_background,
                           stages=tuple((region, subset(items)) for region, items in regions))
