"""Textos da camada de aplicação nos dois idiomas (ver :mod:`videomanager.domain.i18n`)."""

from videomanager.domain.i18n import register

register({
    # --- erros -------------------------------------------------------------------
    "ERROR_URL_EMPTY": ("Informe uma URL.", "Enter a URL."),
    "ERROR_MEDIA_NO_DURATION": ("A mídia não informa duração.", "The media doesn't report its duration."),
    "ERROR_PROJECT_EMPTY": ("O projeto não tem clipes para exportar.", "The project has no clips to export."),
    # Completam o nome do arquivo na lista de recusados da aba Convert.
    "ERROR_NO_VIDEO_TRACK": ("não tem trilha de vídeo", "has no video track"),
    "ERROR_NO_AUDIO_TRACK": ("não tem trilha de áudio", "has no audio track"),
    "ERROR_CODEC_NOT_IN_CONTAINER": ("{codec} não cabe em .{container}", "{codec} doesn't fit in .{container}"),

    # --- codificação ---------------------------------------------------------------
    "QUALITY_BALANCED": ("qualidade equilibrada", "balanced quality"),
    "QUALITY_HIGH": ("alta qualidade", "high quality"),
    "QUALITY_ECONOMY": ("qualidade econômica", "economy quality"),
    "ENCODER_SOFTWARE": ("Software (melhor compressão)", "Software (best compression)"),
    "ENCODER_AUTO": ("Automático (usa a placa)", "Automatic (uses the GPU)"),

    # --- descrição do que a tarefa vai fazer -----------------------------------------
    "DESC_AUDIO_COPY": ("{codec} · cópia direta (sem recodificar)", "{codec} · direct copy (no re-encode)"),
    "DESC_AUDIO_LOSSLESS": ("{codec} · sem perda", "{codec} · lossless"),
    "DESC_VIDEO_COPY": ("vídeo copiado (sem recodificar)", "video copied (no re-encode)"),
    "DESC_REENCODE": ("recodifica em {codec}", "re-encodes to {codec}"),
    "DESC_GPU": ("placa de vídeo, se disponível", "GPU, if available"),
    "DESC_GPU_SHORT": (" (placa, se disponível)", " (GPU, if available)"),
    "DESC_AUDIO_TO": ("áudio em {codec}", "audio to {codec}"),
    "DESC_FIRST_AUDIO_ONLY": ("somente a 1ª faixa de áudio", "first audio track only"),
    "DESC_NO_SUBTITLES": ("legendas não incluídas", "subtitles not included"),
    "DESC_AUDIO_ONLY": ("somente áudio", "audio only"),
    "DESC_SEGMENTS_JOINED": ("{count} trechos unidos", "{count} segments joined"),
    "DESC_DIRECT_COPY": ("cópia direta (sem recodificar)", "direct copy (no re-encode)"),
    "DESC_EXACT_CUT": ("corte exato · recodifica em {codec}", "exact cut · re-encodes to {codec}"),
    "DESC_DURATION": ("{duration} de duração", "{duration} long"),
    "DESC_EXPORT_AUDIO": (".{container} (Áudio · {codec})", ".{container} (Audio · {codec})"),
    "DESC_EXPORT_GIF": (".gif (GIF · 256 cores · sem som)", ".gif (GIF · 256 colors · no sound)"),
    "DESC_AUDIO_CLIPS": ("{count} bloco(s) de áudio", "{count} audio clip(s)"),
    "DESC_IMAGE_CLIPS": ("{count} bloco(s) de imagem", "{count} image clip(s)"),
    "DESC_AUDIO_COUNT": ("{count} de áudio", "{count} audio"),
    "DESC_INTERPOLATED": ("movimento interpolado (lento)", "motion interpolated (slow)"),
    "DESC_DOWNLOAD_AUDIO_BEST": ("Áudio · original (sem perda)", "Audio · original (lossless)"),
    "DESC_DOWNLOAD_AUDIO": ("Áudio · {codec}", "Audio · {codec}"),
    "DESC_DOWNLOAD_AUDIO_RATE": ("Áudio · {codec} {quality} kbps", "Audio · {codec} {quality} kbps"),
    "DESC_UP_TO": ("até {height}p", "up to {height}p"),
    "DESC_EXTRACTED_FROM": ("extraído do vídeo {source}", "extracted from the {source} video"),

    # --- avisos da negociação de container -----------------------------------------
    "POLICY_VIDEO_SWAP": (
        "{family} não cabe em .{container}: usando {alternative} em {resolution} (sem recodificar).",
        "{family} doesn't fit in .{container}: using {alternative} at {resolution} (no re-encode).",
    ),
    "POLICY_VIDEO_MKV": (
        "{family} não cabe em .{container} e não há alternativa compatível nesta mídia. Salvando em "
        ".mkv, que aceita qualquer codec — sem recodificar nem perder qualidade.",
        "{family} doesn't fit in .{container} and this media has no compatible alternative. Saving "
        "as .mkv, which accepts any codec — no re-encoding and no quality loss.",
    ),
    "POLICY_VIDEO_RISKY": (
        "{family} em .{container} gera arquivo válido, mas alguns aparelhos e TVs não reproduzem. "
        ".mkv ou H.264 são mais seguros.",
        "{family} in .{container} makes a valid file, but some devices and TVs can't play it. "
        ".mkv or H.264 are safer.",
    ),
    "POLICY_AUDIO_SWAP": (
        "Trilha {family} não cabe em .{container}: usando {alternative} {bitrate} (sem recodificar).",
        "{family} audio doesn't fit in .{container}: using {alternative} {bitrate} (no re-encode).",
    ),
    "POLICY_AUDIO_MKV": (
        "A única trilha de áudio é {family}, incompatível com .{container}. Salvando em .mkv para "
        "preservar o áudio original.",
        "The only audio track is {family}, which .{container} can't hold. Saving as .mkv to keep "
        "the original audio.",
    ),
    "POLICY_AUDIO_RISKY": (
        "Trilha {alternative} {bitrate} escolhida em vez de {family}: {family} em .{container} tem "
        "suporte irregular nos players. A troca é sem recodificar.",
        "{alternative} {bitrate} audio chosen instead of {family}: {family} in .{container} has "
        "patchy player support. The swap involves no re-encoding.",
    ),
    "POLICY_AUDIO_BITRATE": (
        "A melhor trilha desta mídia tem {source}. Gerar um {codec} de {requested} kbps só aumenta o "
        "arquivo, sem recuperar qualidade — a compressão original é irreversível. Considere "
        "“Original (sem perda)” ou um valor próximo de {source}.",
        "The best track in this media is {source}. Making a {codec} at {requested} kbps only grows "
        "the file without recovering quality — the original compression can't be undone. Consider "
        "“Original (lossless)” or a value close to {source}.",
    ),
})
