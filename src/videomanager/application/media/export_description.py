"""Descrição do plano de exportação, independente dos argumentos do encoder."""
from videomanager.application import encoding as hwaccel
from videomanager.domain.project import Project
from videomanager.domain.timing import format_span
from videomanager.domain.export_policy import can_interpolate

def describe_export(
    project: Project,
    container: str,
    hardware: str = hwaccel.SOFTWARE,
    interpolate: bool = False,
    family: str | None = None,
    audio_only: bool = False,
    audio_codec: str | None = None,
    quality: str = hwaccel.DEFAULT_QUALITY,
) -> str:
    """Resumo do que a exportação vai produzir."""
    project = project.for_export()
    audios = sum(len(track.clips) for track in project.audio_tracks)
    if audio_only:
        codec_name = (audio_codec or container).upper()
        parts = [f".{container} (Áudio · {codec_name})"]
        audible_count = len(project.audible_clips)
        if audible_count:
            parts.append(f"{audible_count} bloco(s) de áudio")
        parts.append(f"{format_span(project.audible_duration)} de duração")
        return " · ".join(parts)

    videos = sum(len(track.clips) for track in project.video_tracks)
    if container == "gif":
        # GIF não guarda som: dizer isso aqui evita a surpresa no arquivo.
        parts = [".gif (GIF · 256 cores · sem som)"]
        if videos:
            parts.append(f"{videos} bloco(s) de imagem")
        parts.append(f"{project.width}×{project.height} · {project.fps:g} fps")
        parts.append(f"{format_span(project.video_duration)} de duração")
        return " · ".join(parts)
    codec_family = family or hwaccel.family_for(container)
    parts = [f".{container} ({hwaccel.family_label(codec_family)})"]
    if videos:
        parts.append(f"{videos} bloco(s) de imagem")
    if audios:
        parts.append(f"{audios} de áudio")
    if project.has_video:
        parts.append(f"{project.width}×{project.height} · {project.fps:g} fps")
    if quality != hwaccel.DEFAULT_QUALITY:
        parts.append(hwaccel.quality_label(quality))
    if interpolate and can_interpolate(project):
        parts.append("movimento interpolado (lento)")
    if hardware != hwaccel.SOFTWARE:
        parts.append("placa de vídeo, se disponível")
    parts.append(f"{format_span(project.export_duration)} de duração")
    return " · ".join(parts)
