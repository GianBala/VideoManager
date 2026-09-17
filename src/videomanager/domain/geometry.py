"""Dimensões de imagens na composição."""


def _image_size(media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int,
                *, enlarge: bool) -> tuple[int, int]:
    w = media_w or 400
    h = media_h or 300
    fit_ratio = min(canvas_w / max(1, w), canvas_h / max(1, h))
    if not enlarge:
        fit_ratio = min(1.0, fit_ratio)
    base_w = max(2, int(round(w * fit_ratio / 2.0) * 2))
    base_h = max(2, int(round(h * fit_ratio / 2.0) * 2))
    return base_w, base_h


def image_base_size(
    media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    """Tamanho base de uma imagem: ajustada à tela, como um vídeo.

    Imagem é parte da trilha de vídeo, e como nos editores de referência ela
    ocupa a tela — ampliada ou reduzida, sem deformar. Escala, posição e
    animação partem deste tamanho. Compositor, prévia e propriedades usam esta
    mesma função, e é isso que mantém os três de acordo.
    """
    return _image_size(media_w, media_h, canvas_w, canvas_h, enlarge=True)


def natural_image_size(
    media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    """Regra anterior ao formato 3: tamanho natural, reduzida só se não coubesse.

    Existe apenas para migrar projetos antigos sem mudar a aparência deles.
    """
    return _image_size(media_w, media_h, canvas_w, canvas_h, enlarge=False)
