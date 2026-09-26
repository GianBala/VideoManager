"""Descritores de mídia e pedidos de conversão sem dependência de ffprobe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from videomanager.domain.constants import IMAGE_CODECS

_AUDIO_EXTENSIONS = {
    "mp3": "mp3",
    "aac": "m4a",
    "m4a": "m4a",
    "opus": "opus",
    "vorbis": "ogg",
    "ogg": "ogg",
    "flac": "flac",
    "alac": "m4a",
    "wav": "wav",
}


_LOSSLESS = {"flac", "alac", "wav"}


@dataclass(frozen=True)
class LocalStream:
    index: int
    kind: str  # "video" | "audio" | "subtitle" | outro
    codec: str
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    # Proporção do pixel (``sample_aspect_ratio``). Quase toda mídia atual tem
    # pixel quadrado e traz 1, mas rip de DVD e filmadora antiga guardam a
    # imagem espremida — 720×480 para exibir em 16:9 — e só este número diz
    # isso. Sem ele, a imagem sai achatada e nada falha. ``None`` quando o
    # arquivo não informa, que o ffmpeg trata como 1.
    sar: float | None = None
    bitrate: float | None = None  # kbps
    sample_rate: int | None = None
    channels: int | None = None
    language: str | None = None
    rotation: float = 0.0
    attached_picture: bool = False
    # Duração da própria trilha, quando o arquivo informa. Pode ser menor que a
    # do container: o AAC costuma sobrar alguns quadros além do vídeo.
    duration: float | None = None


@dataclass(frozen=True)
class LocalMedia:
    """Um arquivo local já inspecionado pelo ffprobe."""

    path: Path
    duration: float | None
    format_name: str
    size: int | None
    streams: tuple[LocalStream, ...]

    @property
    def video(self) -> LocalStream | None:
        return next((s for s in self.streams if s.kind == "video"), None)

    @property
    def audio(self) -> LocalStream | None:
        return next((s for s in self.streams if s.kind == "audio"), None)

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def is_image(self) -> bool:
        """Codec de imagem em contêiner estático; MJPEG em AVI é temporal."""
        formats = set(self.format_name.lower().split(','))
        static = any(name in ('image2', 'image2pipe') or name.endswith('_pipe') for name in formats)
        return bool(self.video and self.video.codec.lower() in IMAGE_CODECS and static and not self.has_audio)

    @property
    def video_is_cover(self) -> bool:
        """Mantém descritores antigos de arquivos de áudio sem disposition."""
        return bool(self.video and (self.video.attached_picture or (
            self.has_audio and self.video.codec.lower() in IMAGE_CODECS
            and self.path.suffix.lower().lstrip('.') in {'mp3', 'flac', 'm4a', 'ogg', 'opus', 'wav', 'aac'}
        )))


@dataclass(frozen=True)
class AudioTarget:
    """Pedido de conversão para áudio."""

    codec: str = "mp3"
    bitrate: str = "192"
    # A compressão pede o mesmo codec com bitrate menor: sem isto a cópia
    # direta (``copies_audio``) devolvia o arquivo intacto, do mesmo tamanho.
    reencode: bool = False

    @property
    def extension(self) -> str:
        return _AUDIO_EXTENSIONS.get(self.codec, self.codec)

    @property
    def is_lossless(self) -> bool:
        return self.codec in _LOSSLESS


@dataclass(frozen=True)
class VideoTarget:
    """Pedido de conversão para vídeo.

    ``video_codec="copy"`` troca só o container: rápido e sem perda. É o padrão
    por isso mesmo.
    """

    container: str = "mp4"
    video_codec: str = "copy"
    audio_codec: str = "copy"
    audio_bitrate: str = "192"
    height: int | None = None
    fps: float | None = None
    crf: int = 20
    # Nível do encoder ("high", "balanced", "economy"), usado pela compressão.
    # Com ele, o número de qualidade sai da tabela de cada encoder — software e
    # placa —, porque o mesmo CRF não quer dizer a mesma coisa no x264 e no AV1.
    # ``None`` mantém o ``crf`` acima, que é o da conversão comum.
    quality: str | None = None
    hardware: str = "software"
    # Teto do bitrate de vídeo (kbps) sobre o nível de qualidade: o encoder
    # mira o nível e não passa disto (ver ``domain/compression.py``).
    max_kbps: int | None = None

    @property
    def guaranteed_kbps(self) -> int | None:
        """O teto que o encoder cumpre: o VBV do x264 e do x265.

        O SVT-AV1 trata o dele como alvo — medido num conteúdo difícil, até 38%
        acima, e passando mais quanto mais longo o arquivo —, e a placa, com
        quantização fixa, não tem teto. Só este número pode virar promessa.
        """
        if self.max_kbps and self.hardware == "software" and self.video_codec in ("h264", "hevc"):
            return self.max_kbps
        return None

    @property
    def extension(self) -> str:
        return self.container
