"""Elegibilidade de corte direto e interpolação, sem comandos do backend."""
from videomanager.domain.project import Project
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.timing import Segment
from videomanager.domain.timing import CutMode
from videomanager.domain.timing import TrimTarget

def simple_trim(project: Project) -> tuple[Segment, ...] | None:
    """Se o projeto é só um recorte de um arquivo, devolve os trechos dele.

    Existe para preservar o corte sem recodificar (ver ``infrastructure/ffmpeg/trimmer.py``)
    depois que o editor virou multipista: enquanto ninguém acrescentou uma
    segunda mídia, mexeu no volume ou mudou um bloco de lugar, cortar continua
    sendo instantâneo e sem perda. Basta uma dessas coisas para a resposta ser
    ``None`` e a exportação passar a compor.
    """
    project = project.for_export()
    clips = project.clips
    if not clips:
        return None
    first = clips[0].media
    if any(clip.media.path != first.path for clip in clips):
        return None
    if any(clip.muted or abs(clip.gain_db) >= 0.05 for clip in clips):
        return None
    # Um bloco de "separar áudio" é só o som do arquivo, e copiar os dados
    # levaria a imagem junto: o que se pediu na tela deixaria de ser o que sai.
    if any(clip.audio_only or clip.detached for clip in clips):
        return None
    if first.kind is MediaKind.IMAGE:
        return None
    # Copiar os dados entrega a imagem como ela está no arquivo: uma tela pedida
    # em outro tamanho ou outra taxa seria simplesmente ignorada, e o arquivo
    # sairia diferente do que a tela do editor anuncia.
    if first.width and first.height and (
        (project.width, project.height) != (first.width, first.height)
    ):
        return None
    if first.fps and abs(project.fps - first.fps) > 0.01:
        return None
    if len(project.video_tracks) > 1 and sum(
        1 for track in project.video_tracks if track.clips
    ) > 1:
        return None
    if any(clip.is_additional for clip in clips) or any(track.clips for track in project.additional_tracks):
        return None
    if any(
        abs(clip.x - 0.5) >= 0.001
        or abs(clip.y - 0.5) >= 0.001
        or abs(getattr(clip, "scale_x", clip.scale) - 1.0) >= 0.001
        or abs(getattr(clip, "scale_y", clip.scale) - 1.0) >= 0.001
        or abs(clip.rotation) >= 0.1
        or clip.chromakey_enabled
        for clip in clips
    ):
        return None
    if any(not track.visible for track in project.tracks if track.clips):
        return None
    if any(track.muted for track in project.tracks if track.clips):
        return None

    ordered = sorted(clips, key=lambda clip: clip.start)
    # O recorte simples é a mídia na ordem original: se os blocos foram
    # embaralhados no tempo, quem monta é o compositor.
    if any(
        later.in_point < earlier.in_point
        for earlier, later in zip(ordered, ordered[1:])
    ):
        return None
    return tuple(Segment(clip.in_point, clip.out_point) for clip in ordered)


def as_trim_target(
    project: Project, container: str, mode: CutMode, anchor: float | None
) -> TrimTarget | None:
    segments = simple_trim(project)
    if segments is None:
        return None
    return TrimTarget(
        segments=segments, container=container, mode=mode, anchor=anchor
    )


def _interpolated_clips(project: Project) -> list[Clip]:
    """Os blocos que teriam quadros inventados nesta edição.

    Uma regra só, usada para oferecer a opção e para dizer o que ela vai custar:
    duas contas para a mesma decisão acabam discordando, e aqui a que discordasse
    anunciaria uma memória que não é a pedida.
    """
    return [
        clip
        for track in project.video_tracks
        if track.visible
        for clip in track.clips
        if clip.has_image and clip.media.fps and clip.media.fps < project.fps - 0.01
    ]


def can_interpolate(project: Project) -> bool:
    """Se há bloco abaixo da taxa da tela — o único caso com o que interpolar."""
    return bool(_interpolated_clips(project))
