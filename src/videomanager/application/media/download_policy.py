"""Negocia containers sem recodificação e descreve os avisos ao usuário."""
from dataclasses import dataclass
from videomanager.domain.formats import FormatMatrix
from videomanager.domain.formats import VideoChoice
from videomanager.domain.formats import AudioChoice
from videomanager.domain.selection import CONTAINER_AUTO
from videomanager.domain.selection import Request
from videomanager.domain.selection import AudioRequest
from videomanager.domain.selection import LOSSLESS_AUDIO
from videomanager.application.formatting import format_bitrate
from videomanager.application.format_labels import resolution_label

_MP4_MUXABLE_VIDEO = {"H.264", "HEVC", "AV1", "VP9", "MPEG-4", "Dolby Vision"}


_MP4_MUXABLE_AUDIO = {"AAC", "MP3", "AC-3", "E-AC-3", "ALAC", "Opus", "FLAC"}


_MP4_SAFE_VIDEO = {"H.264", "HEVC", "AV1"}


_MP4_SAFE_AUDIO = {"AAC", "MP3", "AC-3", "E-AC-3"}


_WEBM_MUXABLE_VIDEO = {"VP8", "VP9", "AV1"}


_WEBM_MUXABLE_AUDIO = {"Opus", "Vorbis"}


@dataclass(frozen=True)
class ContainerPlan:
    """Resultado da negociação entre o container pedido e os codecs disponíveis."""

    container: str
    video: VideoChoice | None
    audio: AudioChoice | None
    warnings: tuple[str, ...] = ()

    @property
    def merge_output_format(self) -> str | None:
        """Valor para ``merge_output_format``; ``None`` deixa o yt-dlp decidir."""
        return None if self.container == CONTAINER_AUTO else self.container


def _first_compatible_audio(matrix: FormatMatrix, allowed: set[str]) -> AudioChoice | None:
    for choice in matrix.audio:
        if choice.family in allowed:
            return choice
    return None


def _first_compatible_video(
    matrix: FormatMatrix, allowed: set[str], height: int | None
) -> VideoChoice | None:
    """Melhor vídeo compatível, priorizando manter a resolução escolhida."""
    if height is not None:
        for choice in matrix.video:
            if choice.family in allowed and choice.height == height:
                return choice
    for choice in matrix.video:
        if choice.family in allowed:
            return choice
    return None


def plan_container(
    matrix: FormatMatrix,
    video: VideoChoice | None,
    audio: AudioChoice | None,
    container: str,
) -> ContainerPlan:
    """Concilia o container pedido com os codecs realmente disponíveis.

    A ordem de preferência ao resolver um conflito é sempre: trocar de stream
    (sem perda, mesma qualidade) → trocar de container (sem perda, arquivo
    diferente do pedido) → e nunca recodificar.
    """
    warnings: list[str] = []

    if container == CONTAINER_AUTO or container == "mkv":
        # MKV aceita tudo, e no modo automático o próprio yt-dlp escolhe um
        # container compatível. Nada a negociar.
        return ContainerPlan(container, video, audio, ())

    muxable_video, muxable_audio, safe_video, safe_audio = {
        "mp4": (_MP4_MUXABLE_VIDEO, _MP4_MUXABLE_AUDIO, _MP4_SAFE_VIDEO, _MP4_SAFE_AUDIO),
        "webm": (
            _WEBM_MUXABLE_VIDEO,
            _WEBM_MUXABLE_AUDIO,
            _WEBM_MUXABLE_VIDEO,
            _WEBM_MUXABLE_AUDIO,
        ),
    }[container]

    # --- vídeo ---
    if video and video.family and video.family not in muxable_video:
        alternative = _first_compatible_video(matrix, safe_video, video.height)
        if alternative:
            warnings.append(
                f"{video.family} não cabe em .{container}: usando "
                f"{alternative.family} em {resolution_label(alternative)} "
                "(sem recodificar)."
            )
            video = alternative
        else:
            warnings.append(
                f"{video.family} não cabe em .{container} e não há alternativa "
                "compatível nesta mídia. Salvando em .mkv, que aceita qualquer "
                "codec — sem recodificar nem perder qualidade."
            )
            return ContainerPlan("mkv", video, audio, tuple(warnings))
    elif video and video.family and video.family not in safe_video:
        warnings.append(
            f"{video.family} em .{container} gera arquivo válido, mas alguns "
            "aparelhos e TVs não reproduzem. .mkv ou H.264 são mais seguros."
        )

    # --- áudio ---
    if audio and audio.family and audio.family not in muxable_audio:
        alternative = _first_compatible_audio(matrix, safe_audio)
        if alternative:
            warnings.append(
                f"Trilha {audio.family} não cabe em .{container}: usando "
                f"{alternative.family} {format_bitrate(alternative.bitrate)} "
                "(sem recodificar)."
            )
            audio = alternative
        else:
            warnings.append(
                f"A única trilha de áudio é {audio.family}, incompatível com "
                f".{container}. Salvando em .mkv para preservar o áudio original."
            )
            return ContainerPlan("mkv", video, audio, tuple(warnings))
    elif audio and audio.family and audio.family not in safe_audio:
        alternative = _first_compatible_audio(matrix, safe_audio)
        if alternative:
            warnings.append(
                f"Trilha {alternative.family} "
                f"{format_bitrate(alternative.bitrate)} escolhida em vez de "
                f"{audio.family}: {audio.family} em .{container} tem suporte "
                "irregular nos players. A troca é sem recodificar."
            )
            audio = alternative

    return ContainerPlan(container, video, audio, tuple(warnings))


def audio_quality_warning(matrix: FormatMatrix, codec: str, quality: str) -> str | None:
    """Avisa quando o bitrate pedido excede o que a fonte realmente tem.

    Transcodificar um Opus de 128 kbps para um MP3 de 320 kbps não recupera
    nada: o arquivo triplica de tamanho e a qualidade continua sendo a do
    original — na prática, um pouco pior, porque é uma segunda compressão com
    perda. O usuário merece saber disso antes, não depois.
    """
    if codec in LOSSLESS_AUDIO or codec == "best":
        return None
    try:
        requested = float(quality)
    except (TypeError, ValueError):
        return None

    source = matrix.best_audio_bitrate
    if source and requested > source * 1.1:
        return (
            f"A melhor trilha desta mídia tem {format_bitrate(source)}. "
            f"Gerar um {codec.upper()} de {int(requested)} kbps só aumenta o "
            "arquivo, sem recuperar qualidade — a compressão original é "
            "irreversível. Considere “Original (sem perda)” ou um valor próximo "
            f"de {format_bitrate(source)}."
        )
    return None


def describe_request(request: Request, plan: ContainerPlan | None) -> str:
    """Resumo curto do que será baixado, para a coluna de destino na fila."""
    if isinstance(request, AudioRequest):
        if request.codec == "best":
            return "Áudio · original (sem perda)"
        if request.codec in LOSSLESS_AUDIO:
            return f"Áudio · {request.codec.upper()}"
        return f"Áudio · {request.codec.upper()} {request.quality} kbps"

    parts: list[str] = []
    choice = plan.video if plan else request.video
    if choice is not None:
        parts.append(resolution_label(choice))
        if choice.family:
            parts.append(choice.family)
    elif request.max_height:
        parts.append(f"até {request.max_height}p")
    container = plan.container if plan else request.container
    parts.append(".mkv" if container == CONTAINER_AUTO else f".{container}")
    return " · ".join(parts)

