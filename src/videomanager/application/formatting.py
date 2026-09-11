"""Formatação de números para exibição, em pt-BR (vírgula decimal).

Todas as funções aceitam ``None`` e devolvem ``"—"``. Isso é deliberado: a
maioria dos extratores omite tamanho, bitrate ou duração em algum formato, e a
alternativa comum — exibir ``0`` — mente para o usuário dizendo que o arquivo
não tem tamanho.
"""

from __future__ import annotations

import math

DASH = "—"


def _decimal(value: float, places: int = 1) -> str:
    """Formata com vírgula decimal, sem zero à direita inútil."""
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_size(num_bytes: int | float | None, *, estimated: bool = False) -> str:
    """Tamanho em bytes para texto legível (base 1024)."""
    if num_bytes is None or num_bytes < 0:
        return DASH
    prefix = "~" if estimated else ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            places = 0 if unit == "B" else 1
            return f"{prefix}{_decimal(size, places)} {unit}"
        size /= 1024
    return DASH  # inalcançável, mantido para o verificador de tipos


def format_bitrate(kbps: float | None) -> str:
    """Bitrate recebido em kbps (a unidade que o yt-dlp usa em tbr/vbr/abr)."""
    if kbps is None or kbps <= 0:
        return DASH
    if kbps >= 1000:
        return f"{_decimal(kbps / 1000)} Mbps"
    return f"{_decimal(kbps, 0)} kbps"


def format_speed(bytes_per_second: float | None) -> str:
    if bytes_per_second is None or bytes_per_second <= 0:
        return DASH
    return f"{format_size(bytes_per_second)}/s"


def format_duration(seconds: float | None) -> str:
    """Duração como ``h:mm:ss`` ou ``m:ss``."""
    if seconds is None or seconds < 0:
        return DASH
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return DASH
    return format_duration(seconds)


def format_rate(fps: float | None) -> str:
    """Framerate **exato**, para onde a diferença entre 29,97 e 30 importa.

    Numa lista de formatos, arredondar ajuda: "29,97" só faria procurar a
    diferença. Já na taxa escolhida para a exportação os dois valores produzem
    arquivos diferentes, e a lista não pode oferecer um mostrando o outro.
    """
    if fps is None or fps <= 0:
        return DASH
    return _decimal(fps, 2)


def format_aspect_ratio(width: int | None, height: int | None) -> str:
    """Nome da proporção de aspecto (ex.: '16:9', '4:3', '9:16', '1:1', '21:9')."""
    if not width or not height or width <= 0 or height <= 0:
        return ""
    ratio = width / height
    if abs(ratio - 16 / 9) < 0.04:
        return "16:9"
    if abs(ratio - 4 / 3) < 0.04:
        return "4:3"
    if abs(ratio - 9 / 16) < 0.04:
        return "9:16"
    if abs(ratio - 1.0) < 0.04:
        return "1:1"
    if abs(ratio - 21 / 9) < 0.08 or abs(ratio - 64 / 27) < 0.08:
        return "21:9"
    g = math.gcd(width, height)
    rw, rh = width // g, height // g
    if rw < 100 and rh < 100:
        return f"{rw}:{rh}"
    return f"{ratio:.2f}:1"
