"""Regras de compatibilidade de streams e containers."""
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import VideoTarget

_EQUIVALENT_SOURCE_CODECS = {
    "mp3": {"mp3"},
    "aac": {"aac"},
    "m4a": {"aac"},
    "opus": {"opus"},
    "vorbis": {"vorbis"},
    "ogg": {"vorbis"},
    "flac": {"flac"},
    "alac": {"alac"},
    # Só o que o muxer WAV grava como está: PCM big-endian (comum em AIFF e
    # MOV) é recusado por ele, e "copiar" terminava em erro do ffmpeg.
    "wav": {"pcm_s16le", "pcm_u8"},
}


_CONTAINER_VIDEO_OK: dict[str, set[str] | None] = {
    "mp4": {"h264", "hevc", "av1", "mpeg4"},
    "mkv": None,
    "webm": {"vp8", "vp9", "av1"},
}


_CONTAINER_AUDIO_OK: dict[str, set[str] | None] = {
    "mp4": {"aac", "mp3", "alac", "ac3", "eac3"},
    "mkv": None,
    "webm": {"opus", "vorbis"},
}


_CONTAINER_VIDEO_FALLBACK = {"mp4": "h264", "mkv": "h264", "webm": "vp9"}


_CONTAINER_AUDIO_FALLBACK = {"mp4": "aac", "mkv": "aac", "webm": "opus"}


def can_copy_audio(media: LocalMedia, codec: str) -> bool:
    """Se o áudio pode ser copiado em vez de recodificado.

    Vale quando o codec de origem já é o pedido: aí a conversão é só troca de
    container, feita em segundos e sem perda.
    """
    stream = media.audio
    if stream is None or codec == "copy":
        return codec == "copy" and stream is not None
    return stream.codec.lower() in _EQUIVALENT_SOURCE_CODECS.get(codec, set())


def display_size(media: LocalMedia) -> tuple[int, int] | None:
    """Largura e altura **como o vídeo aparece**, já considerando a rotação.

    O ffmpeg aplica a rotação dos metadados antes dos filtros, então é nesta
    orientação que o redimensionamento trabalha.
    """
    stream = media.video
    if stream is None or not stream.width or not stream.height:
        return None
    if round(abs(stream.rotation)) % 180 == 90:
        return stream.height, stream.width
    return stream.width, stream.height


def is_portrait(media: LocalMedia) -> bool:
    size = display_size(media)
    return bool(size and size[1] > size[0])


def needs_scaling(media: LocalMedia, target: VideoTarget) -> bool:
    """Se a resolução pedida exige redimensionar.

    "720p" é o lado **curto**: num vídeo retrato ele é a largura. Comparar só a
    altura armazenada fazia um retrato 1080×1920 virar 405×720 — e um vídeo
    gravado de lado, com rotação nos metadados, nunca era reconhecido.
    """
    size = display_size(media)
    if not target.height or size is None:
        return bool(target.height and media.video and media.video.height != target.height)
    return min(size) != target.height


def container_accepts_video(container: str, codec: str) -> bool:
    """Se um codec **escolhido** pelo usuário cabe no container.

    Diferente da cópia, que cai no codec natural do container, uma escolha
    explícita incompatível não pode ser trocada em silêncio: a interface deixa
    de oferecê-la e o serviço a recusa antes de enfileirar.
    """
    return codec == "copy" or _container_accepts(_CONTAINER_VIDEO_OK, container, codec)


def _container_accepts(table: dict[str, set[str] | None], container: str, codec: str) -> bool:
    allowed = table.get(container, None)
    return allowed is None or codec.lower() in allowed


def needs_video_reencode(media: LocalMedia, target: VideoTarget) -> bool:
    """Se a conversão vai ter de recodificar o vídeo.

    Existe para que :func:`build_video_args` e :func:`describe_target` decidam
    pela mesma regra. Quando essa decisão estava duplicada, a interface anunciava
    "vídeo copiado" numa conversão que recodificava — porque redimensionar ou
    mudar o framerate torna a cópia impossível, independentemente do que o
    usuário pediu.
    """
    if target.video_codec != "copy":
        return True
    if needs_scaling(media, target) or target.fps:
        return True
    # Copiar só é possível se o container de destino aceitar o codec de origem.
    stream = media.video
    return stream is not None and not _container_accepts(
        _CONTAINER_VIDEO_OK, target.container, stream.codec
    )


def needs_audio_reencode(media: LocalMedia, target: VideoTarget) -> bool:
    """Mesma pergunta, para a trilha de áudio de uma conversão de vídeo."""
    if not media.has_audio:
        return False
    if target.audio_codec != "copy":
        return True
    stream = media.audio
    return stream is not None and not _container_accepts(
        _CONTAINER_AUDIO_OK, target.container, stream.codec
    )


def resolved_video_codec(media: LocalMedia, target: VideoTarget) -> str:
    """Codec de vídeo que a conversão vai realmente produzir."""
    if not needs_video_reencode(media, target):
        return "copy"
    if target.video_codec != "copy":
        return target.video_codec
    # O usuário pediu cópia, mas ela não cabe: escolhe o codec natural do
    # container em vez de falhar.
    stream = media.video
    if stream is not None and _container_accepts(
        _CONTAINER_VIDEO_OK, target.container, stream.codec
    ):
        return "h264" if target.container != "webm" else "vp9"
    return _CONTAINER_VIDEO_FALLBACK.get(target.container, "h264")


def resolved_audio_codec(media: LocalMedia, target: VideoTarget) -> str:
    """Codec de áudio que a conversão vai realmente produzir."""
    if not needs_audio_reencode(media, target):
        return "copy"
    if target.audio_codec != "copy":
        return target.audio_codec
    return _CONTAINER_AUDIO_FALLBACK.get(target.container, "aac")
