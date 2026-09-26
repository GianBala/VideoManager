"""Níveis de compressão da aba Convert: quanto de qualidade cada um troca por tamanho.

A compressão não é um alvo novo. Cada arquivo vira o ``VideoTarget`` ou o
``AudioTarget`` de sempre, e por isso descrição, estimativa, reserva de saída e
execução seguem os caminhos da conversão comum — o que a aba anuncia é o que o
ffmpeg recebe.

Duas regras valem para todos os níveis. **Nada é ampliado**: o teto de
resolução só entra quando o lado curto passa dele, porque "720p" num vídeo 480p
recodificaria para um arquivo maior e pior. **Nada é recodificado para ficar
igual**: um áudio que já está abaixo do teto é copiado, e não comprimido de novo
no mesmo bitrate, que só perderia qualidade.
"""

from __future__ import annotations

from dataclasses import dataclass

from videomanager.domain.compatibility import display_size
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import VideoTarget


@dataclass(frozen=True)
class CompressionLevel:
    key: str
    # Nível da tabela de cada encoder (``encoder_quality``), a mesma da exportação.
    quality: str
    audio_kbps: int
    max_height: int | None = None


LEVELS = (
    CompressionLevel("light", "high", 192),
    CompressionLevel("balanced", "balanced", 128),
    CompressionLevel("strong", "economy", 96),
    CompressionLevel("max", "economy", 64, max_height=720),
)
VIDEO_CODECS = ("h264", "hevc", "av1")

# Codecs com perda que o aplicativo grava: o áudio comprimido fica no formato em
# que chegou. O resto (FLAC, WAV, WMA…) vai para AAC, que toca em qualquer lugar.
_AUDIO_KEEP = {"mp3": "mp3", "aac": "m4a", "opus": "opus", "vorbis": "vorbis"}


def compression_target(
    media: LocalMedia, chosen: CompressionLevel, codec: str, hardware: str
) -> VideoTarget | AudioTarget:
    source_kbps = media.audio.bitrate if media.audio else None
    # Abaixo do teto não há o que ganhar recodificando o áudio.
    keeps_audio = bool(source_kbps and source_kbps <= chosen.audio_kbps)
    if media.has_video and not media.video_is_cover and not media.is_image:
        size = display_size(media)
        shrink = chosen.max_height if size and chosen.max_height and min(size) > chosen.max_height else None
        return VideoTarget(
            # Só o MKV guarda todas as faixas de áudio e as legendas; o resto sai
            # em MP4, que abre em qualquer aparelho.
            container="mkv" if media.path.suffix.lower() == ".mkv" else "mp4",
            video_codec=codec,
            audio_codec="copy" if keeps_audio else "aac",
            audio_bitrate=str(chosen.audio_kbps),
            height=shrink,
            quality=chosen.quality,
            hardware=hardware,
        )
    source = media.audio.codec.lower() if media.audio else ""
    return AudioTarget(
        codec=_AUDIO_KEEP.get(source, "m4a"),
        bitrate=str(chosen.audio_kbps if not keeps_audio else int(source_kbps)),
        reencode=not keeps_audio,
    )
