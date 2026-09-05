"""Modelos e cálculos para estimativa de tamanho de arquivo (MB/GB).

Calibra taxas de bits típicas de compressão de vídeo e áudio com base em:
- Resolução e contagem de pixels (curva BPP - Bits Per Pixel)
- Taxa de quadros (FPS)
- Eficiência do codec (H.264, HEVC, AV1, VP9)
- Bitrate de áudio e formatos com/sem perda
- Streams originais para cópia direta sem recodificação
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .converter import AudioTarget, LocalMedia, VideoTarget
    from .models import AudioChoice, FormatMatrix, Mode, VideoChoice

# Eficiência relativa de compressão de vídeo (base H.264 = 1.0)
_CODEC_EFFICIENCY: dict[str, float] = {
    "h264": 1.0,
    "avc": 1.0,
    "libx264": 1.0,
    "hevc": 0.60,
    "h265": 0.60,
    "libx265": 0.60,
    "vp9": 0.65,
    "libvpx-vp9": 0.65,
    "av1": 0.50,
    "libsvtav1": 0.50,
}

# Fator multiplicador de taxa de bits por nível de qualidade (base: balanced / CRF 23 = 1.0)
_QUALITY_FACTOR: dict[str, float] = {
    "high": 1.75,      # ~CRF 18: ~75% maior bitrate
    "balanced": 1.0,   # ~CRF 23: baseline (~4500 kbps para 1080p30)
    "economy": 0.55,   # ~CRF 28: ~45% menor bitrate
}

# Bitrate de áudio padrão (kbps) para formatos conhecidos
_AUDIO_STANDARD_BITRATES: dict[str, float] = {
    "mp3": 192.0,
    "aac": 192.0,
    "m4a": 192.0,
    "opus": 128.0,
    "vorbis": 160.0,
    "ogg": 160.0,
    "flac": 800.0,
    "alac": 800.0,
    "wav": 1411.2,  # 44.1 kHz, 16-bit, estéreo
}


def estimate_video_bitrate(
    width: int | None,
    height: int | None,
    fps: float = 30.0,
    codec: str = "h264",
    quality: str = "balanced",
) -> float:
    """Calcula estimativa de taxa de bits de vídeo em kbps para CRF médio.

    Usa relação de escala espacial (área de pixels com expoente 0.75,
    que modela a redundância espacial em resoluções maiores) e temporal
    (raiz quadrada do framerate).
    """
    if width and height:
        pixels = width * height
    elif height:
        pixels = int(height * (height * 16 / 9))
    elif width:
        pixels = int(width * (width * 9 / 16))
    else:
        pixels = 1920 * 1080

    # 1080p a 30 fps em H.264 tem referência típica de ~4500 kbps (CRF 22/23)
    base_kbps = 4500.0 * ((pixels / 2_073_600) ** 0.75)

    safe_fps = max(1.0, fps or 30.0)
    fps_factor = (safe_fps / 30.0) ** 0.5

    clean_codec = codec.lower().strip()
    efficiency = _CODEC_EFFICIENCY.get(clean_codec, 1.0)
    q_factor = _QUALITY_FACTOR.get(quality.lower().strip(), 1.0)

    return max(200.0, base_kbps * fps_factor * efficiency * q_factor)


def estimate_audio_bitrate(
    codec: str,
    quality_or_bitrate: str | float | None = None,
) -> float:
    """Retorna a taxa de bits estimada de áudio em kbps."""
    clean_codec = codec.lower().strip()
    if quality_or_bitrate is not None:
        try:
            val = float(quality_or_bitrate)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    return _AUDIO_STANDARD_BITRATES.get(clean_codec, 192.0)


def estimate_download_size(
    matrix: FormatMatrix,
    mode: Mode,
    video_choice: VideoChoice | None,
    audio_choice: AudioChoice | None,
    audio_codec: str = "mp3",
    audio_quality: str = "192",
    duration: float | None = None,
) -> int | None:
    """Estima tamanho de download em bytes para a seleção atual."""
    from .models import Kind, Mode

    if mode is Mode.VIDEO:
        if video_choice is None:
            return None

        v_fmt = video_choice.best
        v_bytes = v_fmt.filesize
        if v_bytes is None and duration and duration > 0:
            bitrate = v_fmt.effective_video_bitrate
            if bitrate and bitrate > 0:
                v_bytes = int((bitrate * 1000 / 8) * duration)
            else:
                v_rate = estimate_video_bitrate(
                    v_fmt.width, v_fmt.height, v_fmt.fps or 30.0, v_fmt.video_family or "h264"
                )
                v_bytes = int((v_rate * 1000 / 8) * duration)

        if v_fmt.kind is Kind.MUXED or not matrix.needs_muxing:
            return v_bytes

        # Áudio separado
        a_fmt = audio_choice.best if audio_choice else (matrix.audio[0].best if matrix.audio else None)
        a_bytes = None
        if a_fmt is not None:
            a_bytes = a_fmt.filesize
            if a_bytes is None and duration and duration > 0:
                a_rate = a_fmt.effective_audio_bitrate or 160.0
                a_bytes = int((a_rate * 1000 / 8) * duration)

        if v_bytes is not None and a_bytes is not None:
            return v_bytes + a_bytes
        if v_bytes is not None:
            return v_bytes
        return a_bytes

    # Mode.AUDIO_ONLY
    a_fmt = audio_choice.best if audio_choice else (matrix.audio[0].best if matrix.audio else None)

    if audio_codec == "best":
        if a_fmt and a_fmt.filesize:
            return a_fmt.filesize
        if a_fmt and a_fmt.effective_audio_bitrate and duration and duration > 0:
            return int((a_fmt.effective_audio_bitrate * 1000 / 8) * duration)
        if duration and duration > 0:
            return int((192.0 * 1000 / 8) * duration)
        return None

    if duration and duration > 0:
        bitrate = estimate_audio_bitrate(audio_codec, audio_quality)
        return int((bitrate * 1000 / 8) * duration)

    if a_fmt and a_fmt.filesize:
        return a_fmt.filesize

    return None


def estimate_convert_size(
    media: LocalMedia,
    target: VideoTarget | AudioTarget,
) -> int:
    """Estima tamanho de arquivo resultante da conversão local em bytes."""
    from .converter import AudioTarget, VideoTarget, can_copy_audio

    duration = media.duration or 0.0

    if isinstance(target, AudioTarget):
        if media.size and not media.has_video and can_copy_audio(media, target.codec):
            return media.size
        if duration > 0:
            a_rate = estimate_audio_bitrate(target.codec, target.bitrate)
            return int((a_rate * 1000 / 8) * duration)
        if media.size:
            # Fração de áudio típica de arquivos com vídeo
            return int(media.size * (0.15 if media.has_video else 1.0))
        return 0

    if isinstance(target, VideoTarget):
        if target.video_codec == "copy" and target.height is None:
            if media.size:
                return media.size
            if duration > 0:
                w = media.video.width if media.video else 1920
                h = media.video.height if media.video else 1080
                fps = media.video.fps if media.video else 30.0
                v_rate = estimate_video_bitrate(w, h, fps, "h264")
                return int(((v_rate + 160.0) * 1000 / 8) * duration * 1.015)
            return 0

        orig_w = media.video.width if media.video else 1920
        orig_h = media.video.height if media.video else 1080
        orig_fps = media.video.fps if media.video else 30.0

        if target.height and orig_h:
            target_h = target.height
            target_w = int(orig_w * (target_h / orig_h))
        else:
            target_w = orig_w
            target_h = orig_h

        v_rate = estimate_video_bitrate(target_w, target_h, orig_fps, target.video_codec)
        a_rate = (media.audio.bitrate if (media.audio and media.audio.bitrate) else 160.0)

        # Se o original já possui taxa menor, não superestima
        if media.size and duration > 0:
            orig_total_rate = (media.size * 8) / (duration * 1000)
            if target_h <= orig_h and orig_total_rate > 0:
                v_rate = min(v_rate, orig_total_rate * 1.1)

        if duration > 0:
            return int(((v_rate + a_rate) * 1000 / 8) * duration * 1.015)
        if media.size:
            ratio = ((target_w * target_h) / max(1, orig_w * orig_h)) ** 0.75
            return int(media.size * ratio)

    return 0


def estimate_export_size(
    duration: float,
    width: int,
    height: int,
    fps: float,
    video_codec: str,
    audio_only: bool = False,
    audio_codec: str = "mp3",
    is_fast: bool = False,
    source_size: int | None = None,
    source_duration: float | None = None,
    quality: str = "balanced",
) -> int:
    """Estima tamanho de exportação da edição em bytes."""
    if duration <= 0:
        return 0

    if audio_only:
        a_rate = estimate_audio_bitrate(audio_codec)
        return int((a_rate * 1000 / 8) * duration)

    if is_fast and source_size and source_duration and source_duration > 0:
        return int((source_size / source_duration) * duration)

    v_rate = estimate_video_bitrate(width, height, fps, video_codec, quality=quality)
    a_rate = 192.0  # exportação de vídeo compõe áudio padrão a ~192 kbps
    return int(((v_rate + a_rate) * 1000 / 8) * duration * 1.015)
