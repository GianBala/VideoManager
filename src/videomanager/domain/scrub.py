"""O que aparece num quadro, para reaproveitar quadros já compostos.

Arrastar a agulha pede um quadro a cada movimento, e compor um quadro custa um
ffmpeg inteiro — perto de 100 ms só para abrir o processo no Windows. A prévia
guarda quadros já compostos em baixa resolução; para saber se um deles ainda
vale depois de uma edição, compara a **assinatura** do instante: a tela e os
blocos visíveis que entram na composição daquele instante, na ordem da pilha.

Os modelos são imutáveis e uma edição preserva os objetos que não mudaram, então
comparar assinaturas de trechos intocados é quase só comparar identidades.
"""

from __future__ import annotations

from videomanager.domain.project import Project, TrackKind

Signature = tuple


def _transition_windows(project: Project) -> list[tuple[float, float]]:
    return [(context.start, context.end) for context in project.transition_contexts()]


def _signature(project: Project, seconds: float, windows: list[tuple[float, float]]) -> Signature:
    low = high = seconds
    for start, end in windows:
        # Uma transição usa quadros dos dois lados do corte durante a janela
        # inteira: qualquer bloco que cruze a janela entra na assinatura.
        if start <= seconds < end:
            low, high = min(low, start), max(high, end)
    layers = []
    for track in project.tracks:
        if track.kind is TrackKind.AUDIO or not track.visible:
            continue
        if low == high:
            active = tuple(clip for clip in track.clips if clip.start <= seconds < clip.end)
        else:
            active = tuple(clip for clip in track.clips if clip.start < high and clip.end > low)
        if active:
            layers.append(active)
    return (project.width, project.height, project.fps,
            project.text_reference_width, project.text_reference_height, tuple(layers))


def render_signature(project: Project, seconds: float) -> Signature:
    """Assinatura do quadro composto em ``seconds``.

    Duas assinaturas iguais significam o mesmo quadro: mesmos blocos, com as
    mesmas propriedades e quadros-chave, na mesma ordem de camadas, na mesma
    tela. Trilhas de áudio e ocultas não entram — não mudam a imagem.
    """
    return _signature(project, seconds, _transition_windows(project))


def signature_segments(project: Project, start: float, end: float) -> list[tuple[float, float, Signature]]:
    """Trechos de ``[start, end)`` em que a assinatura não muda.

    A assinatura só muda nas pontas dos blocos e nas bordas das janelas de
    transição. Calcular por trecho, e não por quadro, é o que torna barato
    conferir milhares de quadros guardados depois de cada edição.
    """
    if end <= start:
        return []
    windows = _transition_windows(project)
    edges = {start, end}
    for track in project.tracks:
        if track.kind is TrackKind.AUDIO or not track.visible:
            continue
        for clip in track.clips:
            edges.update((clip.start, clip.end))
    for window_start, window_end in windows:
        edges.update((window_start, window_end))
    ordered = sorted(edge for edge in edges if start <= edge <= end)
    return [(a, b, _signature(project, a, windows)) for a, b in zip(ordered, ordered[1:]) if b > a]


def signature_at(segments: list[tuple[float, float, Signature]], seconds: float) -> Signature | None:
    """Assinatura de ``seconds`` dentro de trechos já calculados."""
    low, high = 0, len(segments) - 1
    while low <= high:
        middle = (low + high) // 2
        start, end, signature = segments[middle]
        if seconds < start:
            high = middle - 1
        elif seconds >= end:
            low = middle + 1
        else:
            return signature
    return None
