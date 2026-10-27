"""O desfoque da região na prévia do arrasto: a sequência do compositor, feita no Qt a cada movimento.

O compositor recorta o retângulo, reduz a uma tela de trabalho de lado fixo, borra e amplia de volta
(``composer._compose_region_blur``). Aqui é a mesma sequência sobre a imagem que a prévia monta enquanto um
item é arrastado por baixo do desfoque: abrir o ffmpeg a cada movimento é justamente o que o plano rápido evita.
A redução e a ampliação são as do Qt; a gaussiana é a do ``gblur`` (``domain.gaussian``).
"""

from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtGui import QPainter

from videomanager.domain.constants import REGION_BLUR_STEPS
from videomanager.domain.gaussian import gaussian_blur
from videomanager.domain.geometry import region_work_size

# Bytes na ordem R, G, B, X em qualquer máquina, sem preenchimento no fim da linha.
_RGBX = QImage.Format.Format_RGBX8888
_SMOOTH = Qt.TransformationMode.SmoothTransformation
_STRETCH = Qt.AspectRatioMode.IgnoreAspectRatio


@lru_cache(maxsize=4)
def _blurred(pixels: bytes, width: int, height: int) -> QImage:
    """O recorte borrado. Guardado pelos pixels de entrada: arrastar longe da região repete o mesmo recorte."""
    work_w, work_h, sigma = region_work_size(width, height)
    small = QImage(pixels, width, height, width * 4, _RGBX).scaled(work_w, work_h, _STRETCH, _SMOOTH)
    data = bytes(small.convertToFormat(_RGBX).constBits())
    out = bytearray(data)
    for channel in range(3):
        out[channel::4] = bytes(gaussian_blur(data[channel::4], work_w, work_h, sigma, REGION_BLUR_STEPS))
    return QImage(bytes(out), work_w, work_h, work_w * 4, _RGBX).scaled(width, height, _STRETCH, _SMOOTH)


def blur_region(image: QImage, left: int, top: int, width: int, height: int) -> None:
    """Borra o retângulo de ``image`` no lugar. O que cai fora da imagem é ignorado."""
    right, bottom = min(image.width(), left + width), min(image.height(), top + height)
    left, top = max(0, left), max(0, top)
    width, height = right - left, bottom - top
    if width < 2 or height < 2:
        return
    crop = image.copy(left, top, width, height).convertToFormat(_RGBX)
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(left, top, _blurred(bytes(crop.constBits()), width, height))
    painter.end()
