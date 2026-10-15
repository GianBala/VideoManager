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

from videomanager.domain import size_model

if TYPE_CHECKING:
    from videomanager.domain.media import AudioTarget
    from videomanager.domain.media import LocalMedia
    from videomanager.domain.media import VideoTarget
    from videomanager.domain.formats import AudioChoice
    from videomanager.domain.formats import FormatMatrix
    from videomanager.domain.formats import Mode
    from videomanager.domain.formats import VideoChoice

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
    if clean_codec == "gif":
        # GIF é comprimido sem prever movimento: o tamanho acompanha pixels por
        # segundo, não a taxa de bits de um codec de vídeo. Medido em
        # exportações reais: 0,27 byte por pixel a 640 px e 0,37 a 1080p (o
        # material com mais detalhe paga mais). O meio-termo erra para mais, que
        # é o lado certo de errar num aviso de tamanho.
        return max(200.0, pixels * safe_fps * 0.3 * 8 / 1000)
    efficiency = _CODEC_EFFICIENCY.get(clean_codec, 1.0)
    q_factor = _QUALITY_FACTOR.get(quality.lower().strip(), 1.0)

    return max(200.0, base_kbps * fps_factor * efficiency * q_factor)


# Quadros de áudio por segundo (AAC a 48 kHz: 1024 amostras por quadro): quantas amostras o container indexa além do vídeo.
_AUDIO_FRAMES_PER_SECOND = 47.0

# Quanto o FLAC, o ALAC e o WAV (que é o próprio PCM) ocupam do PCM de 16 bits, na mediana de áudios de vídeos reais
# (de 0,61 a 1,12 do PCM: depende do conteúdo, e por isso a amostra é quem mede; isto é só o que aparece enquanto ela
# não chega).
_LOSSLESS_SHARE = {"flac": 0.85, "alac": 1.0, "wav": 1.0}


def _lossless_kbps(media: LocalMedia, target: AudioTarget) -> float | None:
    """O bitrate de um áudio sem perda a partir do PCM da própria trilha; ``None`` se não for o caso ou faltar o dado."""
    share = _LOSSLESS_SHARE.get(target.codec)
    stream = media.audio
    if share is None or stream is None or not stream.sample_rate or not stream.channels:
        return None
    return stream.sample_rate * stream.channels * 16 / 1000 * share


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
    video_kbps: int | None = None,
) -> int | None:
    """Estima tamanho de download em bytes para a seleção atual.

    ``video_kbps`` é o bitrate de vídeo pedido (o vídeo é recodificado a ele depois do download): o arquivo sai perto de
    ``kbps × duração``. Uma fonte que já está nesse bitrate, ou abaixo, não é recodificada, e a conta é a de sempre.
    """
    from videomanager.domain.formats import Kind
    from videomanager.domain.formats import Mode

    if mode is Mode.VIDEO:
        if video_choice is None:
            return None

        v_fmt = video_choice.best
        recoded = recode_video_bytes(v_fmt, duration, video_kbps)
        if recoded is not None:
            return recoded + _audio_bytes_beside_recoded_video(matrix, v_fmt, audio_choice, duration)
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


def recode_video_bytes(v_fmt, duration: float | None, video_kbps: int | None) -> int | None:
    """Só o vídeo, recodificado a ``video_kbps``; ``None`` quando não há recodificação a estimar.

    Não há quando nada foi pedido, quando a duração não é conhecida, ou quando a fonte já está no bitrate pedido ou abaixo
    (ver ``infrastructure/ffmpeg/recode.py``: ali o vídeo é mantido).
    """
    if not video_kbps or not duration or duration <= 0:
        return None
    source = _video_only_kbps(v_fmt)
    if source is not None and source <= video_kbps * 1.02:
        return None
    return int(video_kbps * 1000 / 8 * duration)


def _video_only_kbps(v_fmt) -> float | None:
    """O bitrate do vídeo da fonte, sem o áudio que um formato muxado carrega junto."""
    from videomanager.domain.formats import Kind

    if v_fmt.vbr:
        return v_fmt.vbr
    if v_fmt.tbr is None:
        return None
    if v_fmt.kind is Kind.MUXED:
        return max(0.0, v_fmt.tbr - (v_fmt.abr or 0.0))
    return v_fmt.tbr


def _audio_bytes_beside_recoded_video(matrix, v_fmt, audio_choice, duration: float | None) -> int:
    """O áudio que acompanha o vídeo recodificado: copiado, com o tamanho que a fonte dele já tem."""
    from videomanager.domain.formats import Kind

    if v_fmt.kind is Kind.MUXED or not matrix.needs_muxing:
        # O áudio vem junto do vídeo, no bitrate dele; sem o dado, a conta usa o do áudio padrão.
        return int((v_fmt.abr or 128.0) * 1000 / 8 * (duration or 0.0))
    a_fmt = audio_choice.best if audio_choice else (matrix.audio[0].best if matrix.audio else None)
    if a_fmt is None:
        return 0
    if a_fmt.filesize:
        return a_fmt.filesize
    return int((a_fmt.effective_audio_bitrate or 160.0) * 1000 / 8 * (duration or 0.0))


def estimate_profile_size(
    matrix: FormatMatrix,
    mode: Mode,
    *,
    max_height: int | None = None,
    audio_codec: str = "mp3",
    audio_quality: str = "320",
    duration: float | None = None,
) -> int | None:
    """Tamanho estimado de um perfil rápido ("MP4 1080p", "MP3 320k"…) para esta mídia.

    É a mesma conta do rodapé depois de o perfil ser aplicado: o melhor vídeo que respeita o limite de altura e a
    primeira trilha de áudio, ou o áudio no codec e na qualidade do perfil. Por isso o número do cartão e o do rodapé,
    depois do clique, não discordam.
    """
    from videomanager.domain.format_policy import pick_audio, pick_video
    from videomanager.domain.formats import Mode

    audio = pick_audio(matrix)
    if mode is Mode.VIDEO:
        return estimate_download_size(matrix, Mode.VIDEO, pick_video(matrix, max_height=max_height), audio, duration=duration)
    return estimate_download_size(
        matrix, Mode.AUDIO_ONLY, None, audio, audio_codec=audio_codec, audio_quality=audio_quality, duration=duration)


def estimate_convert_size(
    media: LocalMedia,
    target: VideoTarget | AudioTarget,
    video_kbps: float | None = None,
) -> int:
    """Estima tamanho de arquivo resultante da conversão local em bytes.

    ``video_kbps`` é o bitrate medido numa amostra (ver
    ``infrastructure/ffmpeg/sample.py``) — o do vídeo, ou o do áudio quando o alvo
    é só de áudio: quando existe, substitui a conta por pixels, que não enxerga
    o conteúdo.
    """
    from videomanager.domain.media import AudioTarget
    from videomanager.domain.media import VideoTarget
    from videomanager.domain.compatibility import copies_audio
    from videomanager.domain.compatibility import display_size
    from videomanager.domain.compatibility import resolved_audio_codec

    duration = media.duration or 0.0

    if isinstance(target, AudioTarget):
        if copies_audio(media, target):
            # A trilha como está, sem a imagem, a capa nem as legendas que o arquivo carregue: pelo bitrate dela, e não
            # pelo pedido (o nominal anunciava 128 kbps para um AAC de 191 copiado, 34% abaixo do que saía).
            stream = media.audio
            if stream and stream.bitrate and duration > 0:
                return int(stream.bitrate * 1000 / 8 * duration)
            if media.size and not media.has_video:
                return media.size
        if duration > 0:
            if video_kbps is not None:
                # Medido em trechos (``infrastructure/ffmpeg/sample.py``): é o que o encoder grava para este áudio.
                payload = video_kbps * 1000 / 8 * duration
                return int(payload * (1 + size_model.audio_overhead(target.codec)) + size_model.AUDIO_FILE_OVERHEAD)
            a_rate = _lossless_kbps(media, target) or estimate_audio_bitrate(target.codec, target.bitrate)
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
                w = (media.video.width if media.video else None) or 1920
                h = (media.video.height if media.video else None) or 1080
                fps = (media.video.fps if media.video else None) or 30.0
                v_rate = estimate_video_bitrate(w, h, fps, "h264")
                return int(((v_rate + 160.0) * 1000 / 8) * duration * 1.015)
            return 0

        # O ffprobe omite dimensões em alguns arquivos (streams quebrados, HLS);
        # sem o padrão a conta levantava TypeError dentro do plano da aba.
        orig_w = (media.video.width if media.video else None) or 1920
        orig_h = (media.video.height if media.video else None) or 1080
        orig_fps = (media.video.fps if media.video else None) or 30.0

        # A resolução pedida é o lado curto da imagem exibida, como em
        # ``build_video_args``. Pela altura guardada, um retrato 1080×1920 em
        # "720p" entrava na conta como 405×720, e a estimativa saía ~2,4× abaixo.
        target_w, target_h = display_size(media) or (orig_w, orig_h)
        short = min(target_w, target_h)
        if target.height:
            scale = target.height / short
            if target_w < target_h:
                target_w, target_h = target.height, int(target_h * scale)
            else:
                target_w, target_h = int(target_w * scale), target.height

        v_rate = estimate_video_bitrate(target_w, target_h, orig_fps, target.video_codec,
                                        quality=target.quality or "balanced")
        # O áudio recodificado sai no bitrate pedido, não no de origem: numa
        # compressão, 320 kbps viram 64, e a conta pela origem anunciava o
        # arquivo maior do que ele sai.
        if not media.has_audio:
            a_rate = 0.0
        elif resolved_audio_codec(media, target) != "copy":
            a_rate = float(target.audio_bitrate)
        else:
            a_rate = media.audio.bitrate or 160.0

        # Se o original já possui taxa menor, não superestima
        if media.size and duration > 0:
            orig_total_rate = (media.size * 8) / (duration * 1000)
            if (target.height or short) <= short and orig_total_rate > 0:
                v_rate = min(v_rate, orig_total_rate * 1.1)
        if video_kbps is not None:
            v_rate = video_kbps
        if target.guaranteed_kbps:
            v_rate = min(v_rate, target.guaranteed_kbps)

        if duration > 0:
            payload = (v_rate + a_rate) * 1000 / 8 * duration
            if video_kbps is not None:
                # Com o vídeo medido o container é só o que ele grava além dos pacotes (tabelas de amostras, índices):
                # 0,2–0,4% em 1080p, e não o 1,5% fixo da conta por pixels, que sobrava mais de 1% em todo arquivo.
                samples = int(duration * (orig_fps + (_AUDIO_FRAMES_PER_SECOND if media.has_audio else 0.0)))
                return int(payload + size_model.container_overhead_bytes(target.container, samples))
            return int(payload * 1.015)
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
    video_kbps: float | None = None,
    container: str = "mp4",
) -> int:
    """Estima tamanho de exportação da edição em bytes.

    ``video_kbps`` é o bitrate de vídeo medido numa amostra da mídia principal codificada como a exportação a codificaria
    (ver ``infrastructure/ffmpeg/sample.py``): substitui a conta por pixels, que não enxerga o conteúdo.
    """
    if duration <= 0:
        return 0

    if audio_only:
        # O compositor mistura a 48 kHz estéreo: é o PCM de onde partem o WAV e o FLAC.
        pcm = size_model.COMPOSER_PCM_KBPS * _LOSSLESS_SHARE.get(audio_codec.lower().strip(), 0.0)
        a_rate = pcm or estimate_audio_bitrate(audio_codec)
        return int((a_rate * 1000 / 8) * duration)

    if is_fast and source_size and source_duration and source_duration > 0:
        return int((source_size / source_duration) * duration)

    # GIF não tem trilha de áudio para somar.
    a_rate = 0.0 if video_codec.lower().strip() == "gif" else 192.0
    if video_kbps is not None:
        samples = int(duration * (fps + (_AUDIO_FRAMES_PER_SECOND if a_rate else 0.0)))
        return int((video_kbps + a_rate) * 1000 / 8 * duration + size_model.container_overhead_bytes(container, samples))
    v_rate = estimate_video_bitrate(width, height, fps, video_codec, quality=quality)
    return int(((v_rate + a_rate) * 1000 / 8) * duration * 1.015)
