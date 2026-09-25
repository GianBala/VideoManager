"""Preferências e nomes públicos de codificação; não seleciona dispositivos."""

from videomanager.domain.i18n import t

SOFTWARE = "software"


AUTO = "auto"


QUALITY_BALANCED = "balanced"


QUALITY_HIGH = "high"


QUALITY_ECONOMY = "economy"


DEFAULT_QUALITY = QUALITY_BALANCED


_QUALITY_KEYS = {
    QUALITY_BALANCED: "QUALITY_BALANCED",
    QUALITY_HIGH: "QUALITY_HIGH",
    QUALITY_ECONOMY: "QUALITY_ECONOMY",
}


def quality_label(quality: str) -> str:
    return t(_QUALITY_KEYS[quality]) if quality in _QUALITY_KEYS else quality


FAMILY_NAMES = {"h264": "H.264", "hevc": "HEVC", "vp9": "VP9", "av1": "AV1", "gif": "GIF"}


def family_for(container: str) -> str:
    """Família de codec que combina com o container de saída."""
    if container == "gif":
        return "gif"
    return "vp9" if container == "webm" else "h264"


def family_label(family: str) -> str:
    return FAMILY_NAMES.get(family, family.upper())


def choices() -> tuple[tuple[str, str], ...]:
    """As opções de encoder com o rótulo no idioma de agora — por isso função, e
    não constante: uma tupla montada no import ficaria no idioma da abertura."""
    return (
        (SOFTWARE, t("ENCODER_SOFTWARE")),
        (AUTO, t("ENCODER_AUTO")),
        ("nvenc", "NVIDIA (NVENC)"),
        ("qsv", "Intel (Quick Sync)"),
        ("amf", "AMD (AMF)"),
        ("vaapi", "VAAPI (Linux)"),
    )
