"""Paletas de cores: estrutura, contraste e a promessa de que "atual" não mudou nada.

O contraste é verificado aqui, e não só lido num documento: a renovação visual oferece seis
paletas em escuro e claro, e uma cor ajustada sem refazer a conta é um defeito que nenhuma
tela mostra — o texto continua aparecendo, só deixa de ser legível para parte de quem o lê.
O critério é o do projeto: 4,5 : 1 para texto, em todas as superfícies onde ele aparece.
"""

from __future__ import annotations

import pytest

from videomanager.presentation.qt import paletas
from videomanager.presentation.qt.theme import palette, qpalette, stylesheet

# As chaves antigas do tema, como eram antes da renovação (cópia do dicionário que existia em
# ``theme.py``). A paleta "atual" tem de reproduzi-las exatamente: o aplicativo de hoje não pode
# mudar de cor porque o tema ganhou papéis novos.
_ANTES = {
    "dark": {
        "bg": "#1e2128", "surface": "#272b34", "surface_alt": "#2f3440", "border": "#3a404e",
        "text": "#e6e8ec", "text_dim": "#9aa3b2", "accent": "#4c8bf5", "accent_hover": "#6ba0f7",
        "accent_text": "#ffffff", "accent_fill": "#3170dc", "accent_fill_hover": "#2b64c8",
        "accent_fg": "#6ba0f7", "live": "#c0392f", "ok": "#3fb950", "warn": "#d99b28",
        "error": "#e5534b", "track": "#353b47", "focus": "#ffffff",
    },
    "light": {
        "bg": "#f4f5f7", "surface": "#ffffff", "surface_alt": "#eceef2", "border": "#d3d7de",
        "text": "#1d2128", "text_dim": "#616b7a", "accent": "#2f6fd0", "accent_hover": "#3f80e0",
        "accent_text": "#ffffff", "accent_fill": "#2860b8", "accent_fill_hover": "#255aad",
        "accent_fg": "#2f6fd0", "live": "#cf222e", "ok": "#1a7f37", "warn": "#8f6000",
        "error": "#cf222e", "track": "#dfe3e9", "focus": "#000000",
    },
}

_COMBINACOES = [(nome, modo) for nome in paletas.nomes() for modo in paletas.MODOS]


def _rgb(cor: str) -> tuple[int, int, int]:
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def _luminancia(cor: str | tuple[int, int, int]) -> float:
    def canal(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in (_rgb(cor) if isinstance(cor, str) else cor))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b) -> float:
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


def _sobre(frente: str, fundo: str, opacidade: float) -> tuple[int, int, int]:
    """A cor de ``frente`` com a opacidade dada sobre ``fundo``, como o QSS compõe."""
    f, g = _rgb(frente), _rgb(fundo)
    return tuple(round(f[i] * opacidade + g[i] * (1 - opacidade)) for i in range(3))


def test_as_seis_paletas_estao_registradas_na_ordem():
    assert paletas.nomes() == ("atual", "grafite", "estudio", "mare", "aurora", "cinema")
    assert paletas.PADRAO == "atual"


@pytest.mark.parametrize("nome, modo", _COMBINACOES)
def test_toda_paleta_tem_todos_os_papeis_em_hexadecimal(nome, modo):
    papeis = paletas.papeis(nome, modo)
    assert set(papeis) == set(paletas.PAPEIS)
    for papel, cor in papeis.items():
        assert len(cor) == 7 and cor.startswith("#"), f"{nome}/{modo}/{papel}: {cor!r}"
        int(cor[1:], 16)


@pytest.mark.parametrize("modo", paletas.MODOS)
def test_atual_reproduz_as_cores_de_antes_chave_a_chave(modo):
    assert paletas.legado("atual", modo) == _ANTES[modo]
    assert palette(modo) == _ANTES[modo]


@pytest.mark.parametrize("nome, modo", _COMBINACOES)
def test_texto_acento_botao_e_estados_tem_4_5_para_1(nome, modo):
    p = paletas.papeis(nome, modo)
    superficies = {s: p[s] for s in ("canvas", "panel", "card", "raised")}
    selo_do_acento = _sobre(p["soft"], p["card"], 0.15)
    falhas = []
    for papel in ("text", "t2", "t3", "accent", "ok", "warn", "err"):
        for superficie, cor in superficies.items():
            if (r := _contraste(p[papel], cor)) < 4.5:
                falhas.append(f"{papel} sobre {superficie}: {r:.2f}")
    if (r := _contraste(p["accent"], selo_do_acento)) < 4.5:
        falhas.append(f"accent sobre o selo do acento: {r:.2f}")
    for papel in ("ok", "warn", "err"):
        if (r := _contraste(p[papel], _sobre(p[papel], p["card"], 0.15))) < 4.5:
            falhas.append(f"{papel} sobre o próprio selo: {r:.2f}")
    for fundo in ("fill_a", "fill_b"):
        if (r := _contraste(p["on_fill"], p[fundo])) < 4.5:
            falhas.append(f"texto do botão sobre {fundo}: {r:.2f}")
    assert not falhas, f"{nome}/{modo}: " + "; ".join(falhas)


@pytest.mark.parametrize("nome, modo", _COMBINACOES)
def test_a_previa_e_escura_nos_dois_modos(nome, modo):
    # Quem edita vídeo olha a imagem sobre fundo escuro, no tema claro também.
    assert _luminancia(paletas.papeis(nome, modo)["screen"]) < 0.02


@pytest.mark.parametrize("nome, modo", _COMBINACOES)
def test_estilo_e_paleta_do_qt_montam_em_todas_as_combinacoes(desktop_app, nome, modo):
    assert stylesheet(modo, nome)
    assert qpalette(modo, nome).window().color().name() == paletas.legado(nome, modo)["bg"]


def test_nome_desconhecido_volta_ao_padrao():
    assert paletas.papeis("nao-existe", "dark") == paletas.papeis("atual", "dark")
    assert palette("dark", "nao-existe") == palette("dark")
    assert not paletas.existe("nao-existe") and paletas.existe("aurora")


def test_modo_desconhecido_volta_ao_escuro():
    assert paletas.papeis("grafite", "qualquer") == paletas.papeis("grafite", "dark")
