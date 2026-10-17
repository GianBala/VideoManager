"""O texto que cai sobre o plano da prévia se lê em qualquer paleta e modo (``FRT-001``).

O plano ``screen`` é escuro nos dois modos. O estado vazio da prévia ("Importe vídeos…") e o aviso sobre o quadro
("Carregando quadro…") usavam o texto discreto do tema, escuro no modo claro: 2,3 a 2,4 : 1 sobre o plano. Aqui o texto é pintado
pelo QSS de verdade e medido na imagem, e não pelo token.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

from videomanager.presentation.qt import paletas, theme
from videomanager.presentation.qt.panels.edit_widgets import _Preview


def _luminancia(cor: QColor) -> float:
    canal = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(cor.red()) + 0.7152 * canal(cor.green()) + 0.0722 * canal(cor.blue())


def _contraste(a: QColor, b: QColor) -> float:
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


def _melhor_contraste(widget, fundo_em: tuple[int, int]) -> float:
    imagem = widget.grab().toImage()
    fundo = imagem.pixelColor(*fundo_em)
    return max(_contraste(imagem.pixelColor(x, y), fundo) for y in range(imagem.height()) for x in range(imagem.width()))


@pytest.mark.parametrize("modo", ["dark", "light"])
@pytest.mark.parametrize("nome", paletas.nomes())
def test_o_estado_vazio_da_previa_se_le(tema_do_app, nome, modo):
    theme.apply(tema_do_app, modo, nome)
    previa = _Preview()
    previa.resize(520, 160)
    previa.show()
    for _ in range(3):
        tema_do_app.processEvents()
    try:
        assert previa.property("role") == "screen-dim"
        # No canto de cima à esquerda, onde há só o plano da prévia.
        melhor = _melhor_contraste(previa, (30, 8))
        assert melhor >= 4.5, f"{nome}/{modo}: o estado vazio da prévia tem {melhor:.2f} : 1"
    finally:
        previa.close()
        previa.deleteLater()


@pytest.mark.parametrize("modo", ["dark", "light"])
@pytest.mark.parametrize("nome", paletas.nomes())
def test_o_aviso_sobre_o_quadro_se_le(tema_do_app, nome, modo):
    theme.apply(tema_do_app, modo, nome)
    aviso = QLabel("Carregando quadro…")
    aviso.setProperty("role", "overlay-note")
    aviso.show()
    for _ in range(3):
        tema_do_app.processEvents()
    try:
        melhor = _melhor_contraste(aviso, (3, 3))
        assert melhor >= 4.5, f"{nome}/{modo}: o aviso sobre o quadro tem {melhor:.2f} : 1"
    finally:
        aviso.close()
        aviso.deleteLater()
