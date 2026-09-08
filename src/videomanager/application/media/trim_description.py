"""Descrição do recorte e de sua precisão."""
from videomanager.application import encoding as hwaccel
from videomanager.domain.media import LocalMedia
from videomanager.domain.timing import TrimTarget
from videomanager.domain.timing import CutMode
from videomanager.domain.timing import has_real_video
from videomanager.domain.timing import format_span

def describe_trim(media: LocalMedia, target: TrimTarget) -> str:
    """Resumo do que o recorte vai fazer, para exibir antes de começar."""
    video = has_real_video(media)
    parts = [f".{target.container}"]
    if not video:
        parts.append("somente áudio")
    if target.joins:
        parts.append(f"{len(target.segments)} trechos unidos")
    if target.mode is CutMode.FAST:
        parts.append("cópia direta (sem recodificar)")
    else:
        # O codec anunciado é o da trilha que existe: dizer "recodifica em
        # H.264" ao recortar um MP3 descreveria um arquivo que não existe.
        if video:
            family = hwaccel.family_for(target.container)
            nome = hwaccel.family_label(family)
            if target.hardware != hwaccel.SOFTWARE:
                nome += " (placa, se disponível)"
        else:
            nome = {"mp3": "MP3", "webm": "Opus", "ogg": "Vorbis", "oga": "Vorbis", "opus": "Opus",
                    "flac": "FLAC", "wav": "WAV"}.get(target.container, "AAC")
        parts.append(f"corte exato · recodifica em {nome}")
    parts.append(f"{format_span(target.output_duration)} de duração")
    return " · ".join(parts)
