"""Os filtros de cor do compositor (Sépia, P&B, Inverter, Contraste) como conta sobre os bytes de um quadro.

A prévia do arrasto aplica o filtro de um filtro **móvel** ao retângulo dele no quadro que monta a cada movimento do
mouse (``presentation.qt.panels.region_filter``): o filtro age sobre tudo que está abaixo dele, inclusive o item que a
mão está movendo, então não cabe numa imagem pronta. Aqui está a mesma conta que o ffmpeg faz (``hue=s=0``,
``colorchannelmixer``, ``negate``, ``eq=contrast=1.5``), medida contra ele em ``tests/test_cores_contra_o_ffmpeg.py``:
Inverter exato, P&B a 1 em 255, Sépia a 2, Contraste a 4.

Sem NumPy e sem laço por pixel: a conta usa o que o Python faz em C — fatiar com passo, ``bytes.translate`` (tabela de
256 entradas) e a soma de inteiros enormes, em que cada pixel ocupa uma "pista" de 32 (ou 16) bits e a soma de uma pista
não vaza para a vizinha. O corte em 0 e 255 sai dos bytes de excesso da pista. Em 200 mil pixels, ~10 ms.
"""

from functools import lru_cache

from videomanager.domain.constants import COLOR_FILTERS

# Os números do compositor (``composer._COLOR_FILTER_EXPRESSIONS``; um teste confere que são os mesmos).
SEPIA_MATRIX = ((.393, .769, .189), (.349, .686, .168), (.272, .534, .131))
# O ``hue=s=0`` do ffmpeg passa por YCbCr e mantém só o Y: os pesos da BT.601 (medido: 1 em 255 de diferença).
LUMA = (.299, .587, .114)
CONTRAST = 1.5

_EXCESS = bytes(0 if i == 0 else 255 for i in range(256))      # byte de excesso > 0 → satura em 255
_INVERT = bytes(255 - i for i in range(256))
_KEEP_IN_RANGE = bytes(255 if i == 1 else 0 for i in range(256))   # faixa de contraste: byte alto 1 = dentro de 0..255
_OVER_RANGE = bytes(255 if i >= 2 else 0 for i in range(256))      # byte alto 2 ou mais = passou de 255 (0 = abaixo de 0)


def _fixed(weights: tuple[float, ...]) -> tuple[int, ...]:
    """Pesos em 1/256: o produto ``plano * peso`` cabe em 16 bits e a soma de três, numa pista de 32."""
    return tuple(round(w * 256) for w in weights)


@lru_cache(maxsize=None)
def _product_tables(weight: int) -> tuple[bytes, bytes]:
    """O byte baixo e o byte alto de ``valor * peso`` para cada valor de 0 a 255."""
    return bytes((c * weight) & 255 for c in range(256)), bytes((c * weight) >> 8 for c in range(256))


def _lanes(size: int, *placed: tuple[int, bytes]) -> int:
    """Um inteiro com uma pista de ``size`` bytes por pixel, e cada plano posto no byte da pista que o par diz."""
    buffer = bytearray(size * len(placed[0][1]))
    for offset, plane in placed:
        buffer[offset::size] = plane
    return int.from_bytes(buffer, "little")


def _weighted_sum(planes: tuple[bytes, bytes, bytes], weights: tuple[int, int, int]) -> tuple[bytes, bytes]:
    """``(Σ plano·peso + 128) >> 8`` de cada pixel, como (byte baixo, byte de excesso): o excesso é o que passou de 255."""
    n = len(planes[0])
    total = int.from_bytes(b"\x80\x00\x00\x00" * n, "little")                  # 0,5 em 8.8: arredonda para o mais próximo
    for plane, weight in zip(planes, weights):
        low, high = _product_tables(weight)
        total += _lanes(4, (0, plane.translate(low)), (1, plane.translate(high)))
    result = total.to_bytes(4 * n, "little")
    return result[1::4], result[2::4]


def _saturate(low: bytes, excess: bytes) -> bytes:
    n = len(low)
    return (int.from_bytes(low, "little") | int.from_bytes(excess.translate(_EXCESS), "little")).to_bytes(n, "little")


@lru_cache(maxsize=None)
def _contrast_tables() -> tuple[bytes, bytes]:
    """O deslocamento que o ``eq`` soma a cada canal, por luma Y (0 a 255), mais 256 para ficar positivo: byte baixo e alto.

    O ``eq`` age só no Y do YCbCr (faixa limitada, 16 a 235), e a conversão de volta soma essa diferença aos três
    canais. Medido contra o ffmpeg: até 4 em 255; por canal (``1,5·(x−128)+128``) seria até 89.
    """
    values = []
    for y in range(256):
        limited = 16 + 219 * y / 255
        shifted = min(255.0, max(0.0, CONTRAST * (limited - 128) + 128))
        values.append(round((shifted - limited) * 255 / 219) + 256)
    return bytes(v & 255 for v in values), bytes(v >> 8 for v in values)


def _contrast(r: bytes, g: bytes, b: bytes) -> tuple[bytes, bytes, bytes]:
    n = len(r)
    luma, _ = _weighted_sum((r, g, b), _fixed(LUMA))
    low, high = _contrast_tables()
    shift = _lanes(2, (0, luma.translate(low)), (1, luma.translate(high)))
    out = []
    for plane in (r, g, b):
        total = (_lanes(2, (0, plane)) + shift).to_bytes(2 * n, "little")
        value, band = total[0::2], total[1::2]
        keep = int.from_bytes(band.translate(_KEEP_IN_RANGE), "little")
        over = int.from_bytes(band.translate(_OVER_RANGE), "little")
        out.append(((int.from_bytes(value, "little") & keep) | over).to_bytes(n, "little"))
    return out[0], out[1], out[2]


def apply_color_filter(name: str, pixels: bytes) -> bytes:
    """O filtro ``name`` (um de ``COLOR_FILTERS``) aplicado a ``pixels``: R, G, B e X de cada pixel, como a
    ``QImage.Format_RGBX8888`` os guarda. O byte X passa como veio."""
    if name not in COLOR_FILTERS:
        raise ValueError(f"filtro de cor desconhecido: {name!r}")
    if len(pixels) % 4:
        raise ValueError("os pixels vêm de quatro em quatro bytes")
    r, g, b = pixels[0::4], pixels[1::4], pixels[2::4]
    if name == "inverter":
        out = (r.translate(_INVERT), g.translate(_INVERT), b.translate(_INVERT))
    elif name == "pb":
        gray = _saturate(*_weighted_sum((r, g, b), _fixed(LUMA)))
        out = (gray, gray, gray)
    elif name == "sepia":
        out = tuple(_saturate(*_weighted_sum((r, g, b), _fixed(row))) for row in SEPIA_MATRIX)
    else:
        out = _contrast(r, g, b)
    result = bytearray(len(pixels))
    result[0::4], result[1::4], result[2::4], result[3::4] = out[0], out[1], out[2], pixels[3::4]
    return bytes(result)
