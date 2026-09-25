"""Textos do domínio nos dois idiomas (ver :mod:`videomanager.domain.i18n`)."""

from videomanager.domain.i18n import register

register({
    # Espécie da trilha, que também começa o nome-padrão ("Vídeo 2").
    "TRACK_VIDEO": ("Vídeo", "Video"),
    "TRACK_AUDIO": ("Áudio", "Audio"),
    "TRACK_ADDITIONAL": ("Adicionais", "Overlays"),
    "CLIP_DETACHED": ("áudio separado", "audio detached"),
    "CLIP_MUTED": ("mudo", "muted"),
})
