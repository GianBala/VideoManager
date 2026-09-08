"""Descrição da conversão a partir das regras de compatibilidade."""
from videomanager.application import encoding as hwaccel
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.composition import Composition
from videomanager.domain.timing import TrimTarget
from videomanager.domain.compatibility import can_copy_audio
from videomanager.domain.compatibility import resolved_video_codec
from videomanager.domain.compatibility import resolved_audio_codec
from videomanager.application.jobs.requests import ConversionTarget
from videomanager.application.media.export_description import describe_export
from videomanager.application.media.trim_description import describe_trim

def describe_target(media: LocalMedia, target: ConversionTarget) -> str:
    """Resumo do que a conversão vai fazer, para exibir antes de começar."""
    if isinstance(target, Composition):
        return describe_export(
            target.project,
            target.container,
            target.hardware,
            target.interpolate,
            family=target.family,
            audio_only=target.audio_only,
            audio_codec=target.audio_codec,
            quality=target.quality,
        )
    if isinstance(target, TrimTarget):
        return describe_trim(media, target)
    if isinstance(target, AudioTarget):
        if can_copy_audio(media, target.codec):
            return f"{target.codec.upper()} · cópia direta (sem recodificar)"
        if target.is_lossless:
            return f"{target.codec.upper()} · sem perda"
        return f"{target.codec.upper()} · {target.bitrate} kbps"

    parts = [f".{target.container}"]
    codec = resolved_video_codec(media, target)
    if codec == "copy":
        parts.append("vídeo copiado (sem recodificar)")
    else:
        parts.append(f"recodifica em {codec.upper()}")
        if target.hardware != hwaccel.SOFTWARE and codec in ("h264", "hevc"):
            parts.append("placa de vídeo, se disponível")
    audio_codec = resolved_audio_codec(media, target)
    if media.has_audio and audio_codec != "copy":
        # Só se diz quando há custo: "áudio copiado" seria ruído em toda linha.
        parts.append(f"áudio em {audio_codec.upper()}")
    if target.height:
        parts.append(f"{target.height}p")
    if target.fps:
        parts.append(f"{target.fps:g} fps")
    return " · ".join(parts)
