"""Planos imutáveis para manipulação imediata de um objeto em um instante."""
from dataclasses import dataclass, replace

from ...domain.constants import COLOR_FILTERS, OFFSET_COLOR_FILTERS, VIGNETTE_FILTER
from ...domain.project import Clip, OverlayType, Project, TrackKind


@dataclass(frozen=True)
class InteractionPlan:
    background: Project
    foreground: Project
    # O item arrastado, sozinho e sem pose. ``None`` quando o que se arrasta é a própria região de um desfoque: ela não
    # tem textura, é só o retângulo que a prévia borra no que está abaixo.
    source: Project | None
    clip_id: int
    seconds: float
    # Se o gesto precisa da imagem do fundo desfocado como quarta camada. É a
    # opção ligada, e não "aparece agora": a pose muda durante o arrasto.
    blur: bool = False
    # O que a prévia refaz a cada movimento, acima do item, de baixo para cima, cada um com o que vem depois dele até o
    # próximo: o desfoque de região (borra o que o item móvel desenha) e a vinheta (escurece por posição na tela, e o
    # item muda de posição). Não cabem numa imagem pronta. ``foreground`` é só o que está entre o item e o primeiro.
    stages: tuple[tuple[Clip, Project], ...] = ()
    # Os filtros de cor acima do item (Sépia, P&B, Inverter, Contraste): já estão aplicados em ``background`` e em
    # cada trecho, e aqui ficam para a textura do item (e o fundo desfocado dele) sair filtrada também.
    filters: tuple[Clip, ...] = ()
    # Quando o que se arrasta é um filtro de cor móvel: o que está abaixo dele **com o filtro na tela inteira**. A região
    # é a parte desta imagem que a prévia mostra no retângulo da mão (o filtro é afim: o recorte do filtro aplicado ao
    # quadro todo é o filtro aplicado ao recorte).
    filtered: Project | None = None

    @property
    def base_layers(self) -> int:
        """Quantas imagens vêm antes das dos trechos: fundo e frente (região, mais a filtrada se o filtro é de cor), ou
        a textura e o fundo desfocado (item)."""
        if self.source is None:
            return 3 if self.filtered is not None else 2
        return 4 if self.blur else 3


def interaction_plan(project: Project, clip_id: int, seconds: float) -> InteractionPlan | None:
    """Separa a pilha sem tentar decompor filtros que dependem do objeto móvel.

    Transição acima do item muda tudo que está abaixo e não tem como ser refeita a cada movimento: sem plano. Os
    filtros de tela inteira acima do item têm três destinos:

    * os de cor (Sépia, P&B, Inverter, Contraste) são afins, e filtrar a soma é filtrar cada camada e somar: entram já
      aplicados nas imagens prontas (``background`` e os trechos) e na textura (``filters``);
    * o desfoque de região e a vinheta são refeitos pela prévia a cada movimento (``stages``);
    * uma combinação em que a ordem muda o resultado e a prévia não sabe reproduzir (vinheta abaixo de Inverter ou de
      Contraste, que têm termo constante) fica sem plano, e o quadro vem do ffmpeg como sempre veio.

    Quando o item arrastado é o próprio desfoque, o que está abaixo dele vem pronto e a prévia borra a região na pose
    da mão (``source`` é ``None``). O mesmo vale para um filtro móvel: o de cor traz também o fundo já filtrado
    (``filtered``), de onde a prévia recorta o retângulo da mão, e a vinheta é calculada no retângulo ao pintar. Um
    filtro móvel **acima** do que se arrasta fica sem plano: refazê-lo a cada movimento pede o filtro em cada imagem
    do gesto.
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
    if clip.overlay_type is OverlayType.TRANSITION or (clip.overlay_type is OverlayType.FILTER and not clip.has_region):
        return None
    if clip.has_region and not clip.is_region_blur and clip.filter_name not in (*COLOR_FILTERS, VIGNETTE_FILTER):
        return None            # filtro móvel que o plano não conhece: o quadro vem do ffmpeg
    above = ordered[selected + 1:]

    def is_color(c: Clip) -> bool:
        return c.overlay_type is OverlayType.FILTER and not c.has_region and c.filter_name in COLOR_FILTERS

    def is_vignette(c: Clip) -> bool:
        return c.overlay_type is OverlayType.FILTER and not c.has_region and c.filter_name == VIGNETTE_FILTER

    for c in above:
        if c.overlay_type is OverlayType.TRANSITION:
            return None
        if c.overlay_type is OverlayType.FILTER and not (c.is_region_blur or is_color(c) or is_vignette(c)):
            # Um filtro móvel que não borra aplica a cor dele só num retângulo: refazê-lo a cada movimento pede o
            # filtro na própria imagem do gesto, e a prévia não o faz. Nome que esta lista não conhece, idem.
            return None
    # A vinheta que se arrasta (móvel) não está em ``above``, mas é a primeira da pilha: tudo que há acima dela vem depois.
    first_vignette = -1 if clip.has_region and clip.filter_name == VIGNETTE_FILTER else next(
        (i for i, c in enumerate(above) if is_vignette(c)), None)
    if first_vignette is not None and any(c.filter_name in OFFSET_COLOR_FILTERS for c in above[first_vignette + 1:]
                                          if is_color(c)):
        return None

    def subset(clips: list[Clip], of: Project = project) -> Project:
        ids = {c.clip_id for c in clips}
        return replace(of, tracks=tuple(replace(t, clips=tuple(c for c in t.clips if c.clip_id in ids))
                                        for t in of.tracks))

    colors = [c for c in above if is_color(c)]
    # A posição na pilha é por ``clip_id``: dois blocos iguais em tudo menos na identidade (o mesmo filtro aplicado duas
    # vezes) são iguais para o ``==`` do bloco, e ``list.index`` devolveria sempre o primeiro.
    position = {c.clip_id: i for i, c in enumerate(above)}

    def with_filters(items: list[Clip]) -> list[Clip]:
        """Os itens de um trecho e os filtros de cor que agem sobre eles: os que estão acima do primeiro item."""
        if not items:
            return items
        first = position[items[0].clip_id]
        return [*items, *(c for c in colors if position[c.clip_id] > first)]

    # Retirar somente a pose torna o plano estável ao longo do gesto. Tempo,
    # origem, chroma, texto e todas as demais camadas continuam fazendo parte dele.
    source = None if clip.has_region else subset([clip]).with_updated_clip(
        clip_id, x=.5, y=.5, scale=1., scale_x=1., scale_y=1., rotation=0., opacity=1., keyframes=())
    head: list[Clip] = []
    stages: list[tuple[Clip, list[Clip]]] = []
    for c in above:
        if c.is_region_blur or is_vignette(c):
            stages.append((c, []))
        elif not is_color(c):
            (stages[-1][1] if stages else head).append(c)
    filtered = None
    if clip.has_region and clip.filter_name in COLOR_FILTERS:
        # O mesmo bloco na tela inteira, no mesmo lugar da pilha: o compositor aplica o filtro a tudo que está abaixo.
        everywhere = project.with_updated_clip(clip_id, movable=False, x=.5, y=.5, scale=1., scale_x=1., scale_y=1.,
                                               keyframes=())
        filtered = subset([*ordered[:selected], clip, *colors], everywhere)
    return InteractionPlan(subset([*ordered[:selected], *colors]), subset(with_filters(head)), source, clip_id, seconds,
                           blur=False if clip.has_region else clip.has_blur_background,
                           stages=tuple((stage, subset(with_filters(items))) for stage, items in stages),
                           filters=tuple(colors), filtered=filtered)
