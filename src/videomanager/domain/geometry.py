"""Dimensões de imagens na composição."""

def image_base_size(
    media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    """Tamanho base de uma imagem ajustada proporcionalmente ao canvas do projeto."""
    w = media_w or 400
    h = media_h or 300
    fit_ratio = min(1.0, canvas_w / max(1, w), canvas_h / max(1, h))
    base_w = max(2, int(round(w * fit_ratio / 2.0) * 2))
    base_h = max(2, int(round(h * fit_ratio / 2.0) * 2))
    return base_w, base_h
