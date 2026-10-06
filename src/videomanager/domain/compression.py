"""Níveis de compressão da aba Convert: quanto de qualidade cada um troca por tamanho.

A compressão não é um alvo novo. Cada arquivo vira o ``VideoTarget`` ou o
``AudioTarget`` de sempre, e por isso descrição, estimativa, reserva de saída e
execução seguem os caminhos da conversão comum — o que a aba anuncia é o que o
ffmpeg recebe.

Três regras valem para todos os níveis. **Nada é ampliado**: o teto de
resolução só entra quando o lado curto passa dele, porque "720p" num vídeo 480p
recodificaria para um arquivo maior e pior. **Nada é recodificado para ficar
igual**: um áudio que já está abaixo do teto é copiado, e não comprimido de novo
no mesmo bitrate, que só perderia qualidade. **O vídeo tem teto de bitrate**,
uma fração do da origem: o CRF sozinho mira a qualidade e deixa o tamanho
livre, e recodificar material já comprimido o aumentava (medido, no nível
Equilibrada: +10% numa abertura de anime, +20% num gameplay em H.264, +37% em
AV1). Com o teto — CRF limitado, a qualidade do nível até onde ele deixa — o
x264 e o x265 não passam dele, e onde o conteúdo comprime bem (uma tela parada
do OBS) o arquivo sai idêntico ao do CRF sozinho. O SVT-AV1 só o trata como
alvo: reduz o crescimento (medido: de 337% para 108% do original), sem garantir.
"""

from __future__ import annotations

from dataclasses import dataclass

from videomanager.domain.compatibility import display_size
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import VideoTarget


@dataclass(frozen=True)
class CompressionLevel:
    key: str
    # Nível da tabela de cada encoder (``encoder_quality``), a mesma da exportação.
    quality: str
    audio_kbps: int
    # Teto do vídeo, em fração do bitrate de vídeo da origem: a redução mínima
    # que o nível garante. Custou pouca qualidade onde limitou (SSIM de 0,003 a
    # 0,010 abaixo do CRF sozinho, que nesses casos saía maior que o original).
    max_share: float
    max_height: int | None = None


LEVELS = (
    CompressionLevel("light", "high", 192, 0.85),
    CompressionLevel("balanced", "balanced", 128, 0.70),
    CompressionLevel("strong", "economy", 96, 0.50),
    CompressionLevel("max", "economy", 64, 0.35, max_height=720),
)
VIDEO_CODECS = ("h264", "hevc", "av1")

# Codecs com perda que o aplicativo grava: o áudio comprimido fica no formato em
# que chegou. O resto (FLAC, WAV, WMA…) vai para AAC, que toca em qualquer lugar.
_AUDIO_KEEP = {"mp3": "mp3", "aac": "m4a", "opus": "opus", "vorbis": "vorbis"}


# Folga do que se garante sobre a conta pelo teto: contêiner, capa embutida e o
# AAC, que é de bitrate médio (saiu até 3,7% acima do pedido).
_CEILING_SLACK = 1.05
# O VBV começa com o buffer cheio e pode gastá-lo além do teto: um excesso fixo,
# que não cresce com a duração. Medido com o buffer de 1 s (``bitrate_cap``):
# no máximo 0,45 s de teto a mais, em 6, 20 e 60 s, no x264 e no x265.
_VBV_SECONDS = 1.0


def source_video_kbps(media: LocalMedia) -> float | None:
    """Bitrate do vídeo de origem: o da trilha, ou o do arquivo menos o áudio.

    O MKV não informa bitrate por trilha. Sem o do áudio, a conta pelo arquivo o
    inclui, e o teto sai mais alto — mais fraco, nunca errado para baixo.
    """
    if media.video and media.video.bitrate:
        return media.video.bitrate
    if not (media.size and media.duration):
        return None
    audio = sum(stream.bitrate or 0.0 for stream in media.streams if stream.kind == "audio")
    total = media.size * 8 / 1000 / media.duration - audio
    return total if total > 0 else None


def compression_ceiling(media: LocalMedia, target: VideoTarget | AudioTarget) -> int | None:
    """O maior tamanho que a saída pode ter, ou ``None`` quando nada o limita."""
    if isinstance(target, AudioTarget):
        return int(estimate_convert_size(media, target) * _CEILING_SLACK)
    cap = target.guaranteed_kbps
    if not cap:
        return None
    return int((estimate_convert_size(media, target, cap) + cap * 1000 / 8 * _VBV_SECONDS) * _CEILING_SLACK)


def compression_target(
    media: LocalMedia, chosen: CompressionLevel, codec: str, hardware: str
) -> VideoTarget | AudioTarget:
    source_kbps = media.audio.bitrate if media.audio else None
    # Abaixo do teto não há o que ganhar recodificando o áudio.
    keeps_audio = bool(source_kbps and source_kbps <= chosen.audio_kbps)
    if media.has_video and not media.video_is_cover and not media.is_image:
        size = display_size(media)
        shrink = chosen.max_height if size and chosen.max_height and min(size) > chosen.max_height else None
        video_kbps = source_video_kbps(media)
        # Na placa (H.264 e HEVC) o controle de taxa é quantização fixa, que não
        # aceita teto. O AV1 é sempre software: recebe o teto, que o encoder
        # trata como alvo, sem promessa (ver ``VideoTarget.guaranteed_kbps``).
        capped = hardware == "software" or codec not in ("h264", "hevc")
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
            max_kbps=int(video_kbps * chosen.max_share) if video_kbps and capped else None,
        )
    source = media.audio.codec.lower() if media.audio else ""
    return AudioTarget(
        codec=_AUDIO_KEEP.get(source, "m4a"),
        bitrate=str(chosen.audio_kbps if not keeps_audio else int(source_kbps)),
        reencode=not keeps_audio,
    )
