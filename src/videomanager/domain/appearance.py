"""Identificadores da aparência: os modos e as paletas de cor.

Só os nomes. As cores de cada paleta moram na apresentação (``presentation/qt/paletas.py``);
os nomes ficam aqui porque a preferência salva em disco precisa validá-los, e as camadas de
aplicação e de infraestrutura não importam a apresentação. ``tests/test_paletas.py`` confere
que as duas listas nunca divergem.
"""

from __future__ import annotations

# Modo do tema, na ordem em que aparece na tela.
THEMES = ("dark", "light")

# Paletas, na ordem em que aparecem na tela. ``atual`` são as cores de antes da renovação visual, e ``grafite`` (a do protótipo) é a padrão.
PALETTES = ("atual", "grafite", "estudio", "mare", "aurora", "cinema")
DEFAULT_PALETTE = "grafite"
