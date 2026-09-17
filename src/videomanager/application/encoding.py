"""Preferências e nomes públicos de codificação; não seleciona dispositivos."""

SOFTWARE = "software"


AUTO = "auto"


QUALITY_BALANCED = "balanced"


QUALITY_HIGH = "high"


QUALITY_ECONOMY = "economy"


DEFAULT_QUALITY = QUALITY_BALANCED


QUALITY_LABELS: dict[str, str] = {
    QUALITY_BALANCED: "qualidade equilibrada",
    QUALITY_HIGH: "alta qualidade",
    QUALITY_ECONOMY: "qualidade econômica",
}


def quality_label(quality: str) -> str:
    return QUALITY_LABELS.get(quality, quality)


FAMILY_NAMES = {"h264": "H.264", "hevc": "HEVC", "vp9": "VP9", "av1": "AV1", "gif": "GIF"}


def family_for(container: str) -> str:
    """Família de codec que combina com o container de saída."""
    if container == "gif":
        return "gif"
    return "vp9" if container == "webm" else "h264"


def family_label(family: str) -> str:
    return FAMILY_NAMES.get(family, family.upper())


CHOICES: tuple[tuple[str, str], ...] = (
    (SOFTWARE, "Software (melhor compressão)"),
    (AUTO, "Automático (usa a placa)"),
    ("nvenc", "NVIDIA (NVENC)"),
    ("qsv", "Intel (Quick Sync)"),
    ("amf", "AMD (AMF)"),
    ("vaapi", "VAAPI (Linux)"),
)
