"""Escolhas de download independentes de opções yt-dlp."""
from dataclasses import dataclass
from videomanager.domain.formats import VideoChoice
from videomanager.domain.formats import AudioChoice

CONTAINER_AUTO = "auto"


CONTAINERS = (CONTAINER_AUTO, "mp4", "mkv", "webm")


AUDIO_CODECS = ("best", "mp3", "m4a", "aac", "opus", "vorbis", "flac", "alac", "wav")


LOSSLESS_AUDIO = {"flac", "alac", "wav"}


AUDIO_BITRATES = ("320", "256", "192", "160", "128", "96", "64")

# Bitrate de vídeo pedido no download (kbps): os valores prontos do seletor e os limites do campo livre. Abaixo de 100 kbps
# a imagem deixa de ser vídeo; acima de 100 000 não há fonte da web que justifique.
VIDEO_BITRATE_PRESETS = (500, 1000, 2500, 5000, 8000, 12000)
VIDEO_BITRATE_MIN = 100
VIDEO_BITRATE_MAX = 100_000


@dataclass(frozen=True)
class VideoRequest:
    """Pedido de download de vídeo.

    ``video`` e ``audio`` em ``None`` significam modo automático: em vez de ids
    fixos, o seletor emite filtros por resolução e framerate. É o modo usado
    pelos perfis rápidos e por downloads em lote, onde cada item da playlist tem
    formatos diferentes e ids concretos não valeriam para todos.
    """

    video: VideoChoice | None = None
    audio: AudioChoice | None = None
    container: str = CONTAINER_AUTO
    max_height: int | None = None
    max_fps: int | None = None
    # Bitrate médio do vídeo, em kbps. ``None`` é "igual ao da fonte": o vídeo fica como o site o entrega, sem recodificar.
    # Um número é o consentimento de recodificar: depois do download o vídeo é codificado de novo a esse bitrate.
    video_kbps: int | None = None


@dataclass(frozen=True)
class AudioRequest:
    """Pedido de download somente-áudio."""

    audio: AudioChoice | None = None
    codec: str = "mp3"
    quality: str = "192"


Request = VideoRequest | AudioRequest
