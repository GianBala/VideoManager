"""O filtro de cor de um filtro móvel na prévia do arrasto: o retângulo do quadro que a prévia monta passa pela conta do
domínio (``domain.color_filters``), a mesma do ffmpeg, a cada movimento.

O filtro age sobre tudo que está abaixo dele, inclusive o item que a mão está movendo, então não vem numa imagem pronta.
Mesmo desenho de ``region_blur.blur_region``: recorta, converte para bytes, aplica e cola no lugar.
"""

from PySide6.QtGui import QImage
from PySide6.QtGui import QPainter

from videomanager.domain.color_filters import apply_color_filter

# Bytes na ordem R, G, B, X em qualquer máquina, sem preenchimento no fim da linha.
_RGBX = QImage.Format.Format_RGBX8888


def filter_region(image: QImage, left: int, top: int, width: int, height: int, name: str) -> None:
    """Aplica o filtro de cor ``name`` ao retângulo de ``image``, no lugar. O que cai fora da imagem é ignorado."""
    right, bottom = min(image.width(), left + width), min(image.height(), top + height)
    left, top = max(0, left), max(0, top)
    width, height = right - left, bottom - top
    if width < 1 or height < 1:
        return
    crop = image.copy(left, top, width, height).convertToFormat(_RGBX)
    pixels = apply_color_filter(name, bytes(crop.constBits()))
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(left, top, QImage(pixels, width, height, width * 4, _RGBX))
    painter.end()
