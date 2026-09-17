"""Gera o ``.ico`` do executável do Windows a partir do PNG do aplicativo.

    python packaging/make_icon.py [destino]

O PyInstaller só grava o ícone no .exe a partir de um ``.ico``; com um PNG ele
exige o Pillow, que não é dependência do projeto. Sem ``icon=``, o executável
saía com o ícone padrão do próprio PyInstaller.

O arquivo é gerado no build, e não versionado, para que o ``videomanager.png``
continue sendo a única fonte do desenho. A redução é feita pelo Qt, que já é
dependência. Os tamanhos intermediários existem porque o Explorer e a barra de
tarefas pedem 20, 24 e 40 px em escalas de 125 % e 150 %; sem eles, o Windows
reduz o de 256 na hora e o desenho fica borrado.

Só o de 256 px vai comprimido em PNG. Os menores vão como bitmap clássico
(DIB de 32 bits com máscara): o shell do Windows lê PNG em qualquer tamanho,
mas o GDI+ — usado por atalhos antigos e pelo ``System.Drawing`` — devolvia
ruído colorido para uma entrada PNG pequena.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "src" / "videomanager" / "resources" / "videomanager.png"
DEFAULT_TARGET = REPO_ROOT / "build" / "videomanager.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _canvas(image: QImage, size: int) -> QImage:
    scaled = image.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_ARGB32)
    if scaled.width() == size and scaled.height() == size:
        return scaled
    # Um desenho não quadrado ficaria esticado pelo Windows: centraliza numa
    # tela transparente do tamanho pedido.
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return canvas


def _png_entry(canvas: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not canvas.save(buffer, "PNG"):
        raise RuntimeError(f"Não foi possível codificar o ícone de {canvas.width()} px.")
    buffer.close()
    return bytes(data.data())


def _dib_entry(canvas: QImage) -> bytes:
    """Entrada BMP de um ICO: cabeçalho, pixels BGRA de baixo para cima e máscara.

    A altura no cabeçalho é o dobro por convenção do formato (pixels + máscara).
    ``Format_ARGB32`` já guarda cada pixel como B, G, R, A em memória
    little-endian, que é a ordem do DIB.
    """
    size = canvas.width()
    stride = canvas.bytesPerLine()
    bits = bytes(canvas.constBits())
    rows = [bits[y * stride: y * stride + size * 4] for y in range(size)]
    pixels = b"".join(reversed(rows))
    mask_stride = ((size + 31) // 32) * 4
    mask = bytearray()
    for row in reversed(rows):
        line = bytearray(mask_stride)
        for x in range(size):
            if row[x * 4 + 3] == 0:
                line[x // 8] |= 0x80 >> (x % 8)
        mask += line
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + bytes(mask)


def build_ico(source: Path, target: Path) -> Path:
    image = QImage(str(source))
    if image.isNull():
        raise RuntimeError(f"Não foi possível ler {source}.")
    entries = []
    for size in SIZES:
        canvas = _canvas(image, size)
        entries.append((size, _png_entry(canvas) if size >= 256 else _dib_entry(canvas)))
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory = b""
    payload = b""
    for size, data in entries:
        # 0 no byte de dimensão significa 256 px, pelo formato ICO.
        edge = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + directory + payload)
    return target


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    print(build_ico(SOURCE, target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
