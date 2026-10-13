"""As paletas de cores do aplicativo, cada uma em escuro (``dark``) e claro (``light``).

São seis: ``atual`` (as cores de antes da renovação visual), ``grafite``, ``estudio``,
``mare``, ``aurora`` e ``cinema``. Os valores passaram pela verificação de contraste (WCAG
2.x): texto, acento, botão primário e estados a 4,5 : 1 ou mais sobre as quatro superfícies,
inclusive o selo (a cor do estado a 15% sobre o cartão). ``tests/test_paletas.py`` refaz a conta.

**Papéis, não cores.** Cada paleta diz *para que* serve cada cor:

=============  ======================================================================
canvas         fundo da janela, entre os cartões
panel          menu lateral, gaveta de tarefas, barras
card           seções e blocos de conteúdo
raised         campos e botões
raised2        passar o mouse, trilho de barras e de controles deslizantes
text           texto principal
t2, t3         texto secundário; dicas e rótulos
accent         destaque em texto e ícone
soft           o acento em cor sólida, de onde saem o selo e a seleção (a 16% de opacidade)
fill_a, fill_b botão primário (gradiente de um para o outro); ``on_fill`` é o texto dele
ok, warn, err  estados
screen         fundo da prévia, escuro nos dois modos
=============  ======================================================================

**Dois acessores, de propósito.** :func:`papeis` devolve os papéis acima. :func:`legado`
devolve as **chaves antigas** (``bg``, ``surface``, ``surface_alt``, ``border``, ``text_dim``,
``accent_fill``...) que o QSS e os painéis que pintam à mão ainda leem, derivadas dos papéis. Não
dá para fundir os dois num dicionário só: ``accent``, ``ok`` e ``warn`` existem nos dois com
valores diferentes na paleta ``atual``. A camada antiga some quando nenhum código a ler mais.

**``atual`` reproduz as cores de antes, sem tirar nem pôr**, nas chaves antigas (``_legado``
guarda só o que difere da derivação). Já os papéis ``accent``, ``ok``, ``warn`` e ``err`` dela
são o mínimo mais claro (no escuro) ou mais escuro (no claro) que atinge 4,5 : 1 nos contextos
que só o layout novo tem: um vermelho de erro sobre uma superfície elevada media 3,26 : 1. É o
único desvio de "manter as cores de hoje".
"""

from __future__ import annotations

from videomanager.domain.appearance import DEFAULT_PALETTE, THEMES

PADRAO = DEFAULT_PALETTE
MODOS = THEMES
PAPEIS = ("canvas", "panel", "card", "raised", "raised2", "text", "t2", "t3", "accent", "soft",
          "fill_a", "fill_b", "on_fill", "ok", "warn", "err", "screen")

_PALETAS: dict[str, dict[str, dict[str, str]]] = {
    "atual": dict(
        dark=dict(
            canvas="#1e2128", panel="#1e2128", card="#272b34", raised="#2f3440",
            raised2="#3a404e", text="#e6e8ec", t2="#9aa3b2", t3="#9aa3b2",
            accent="#6ea2f7", soft="#4c8bf5", fill_a="#3170dc", fill_b="#3170dc",
            on_fill="#ffffff", ok="#4bbd5a", warn="#d99b28", err="#ee8c86",
            screen="#0f1115",
            _legado=dict(accent="#4c8bf5", accent_hover="#6ba0f7", accent_fg="#6ba0f7", accent_fill_hover="#2b64c8", ok="#3fb950", warn="#d99b28", error="#e5534b", track="#353b47"),
        ),
        light=dict(
            canvas="#f4f5f7", panel="#f4f5f7", card="#ffffff", raised="#eceef2",
            raised2="#d3d7de", text="#1d2128", t2="#616b7a", t3="#616b7a",
            accent="#2c67c1", soft="#2f6fd0", fill_a="#2860b8", fill_b="#2860b8",
            on_fill="#ffffff", ok="#187734", warn="#8e5f00", err="#c5202c",
            screen="#0f1115",
            _legado=dict(accent="#2f6fd0", accent_hover="#3f80e0", accent_fg="#2f6fd0", accent_fill_hover="#255aad", ok="#1a7f37", warn="#8f6000", error="#cf222e", track="#dfe3e9"),
        ),
    ),
    "grafite": dict(
        dark=dict(
            canvas="#0f1216", panel="#161a20", card="#1d222a", raised="#252b35",
            raised2="#2d3440", text="#eef0f4", t2="#aab2c0", t3="#98a2b2",
            accent="#7ba3ff", soft="#5b8def", fill_a="#2f6bd8", fill_b="#5a4fd6",
            on_fill="#ffffff", ok="#4cc38a", warn="#e3a53a", err="#f5857b",
            screen="#090b0e"
        ),
        light=dict(
            canvas="#e8ebf0", panel="#f3f5f8", card="#ffffff", raised="#eef1f5",
            raised2="#e2e7ee", text="#161a20", t2="#465061", t3="#5a6576",
            accent="#2459c6", soft="#2f6bd8", fill_a="#2f6bd8", fill_b="#5a4fd6",
            on_fill="#ffffff", ok="#146c34", warn="#8a5a00", err="#b9231b",
            screen="#090b0e"
        ),
    ),
    "estudio": dict(
        dark=dict(
            canvas="#0c0c0d", panel="#131314", card="#1a1a1c", raised="#242427",
            raised2="#2e2e32", text="#f2f2f3", t2="#b1b1b8", t3="#9b9ba3",
            accent="#f2f2f3", soft="#ffffff", fill_a="#f4f4f5", fill_b="#d4d4d8",
            on_fill="#101012", ok="#4cc38a", warn="#e3a53a", err="#f5857b",
            screen="#08080a"
        ),
        light=dict(
            canvas="#e9e9eb", panel="#f4f4f5", card="#ffffff", raised="#efeff1",
            raised2="#e4e4e7", text="#18181b", t2="#4a4a52", t3="#5c5c66",
            accent="#18181b", soft="#18181b", fill_a="#2e2e33", fill_b="#18181b",
            on_fill="#ffffff", ok="#146c34", warn="#8a5a00", err="#b9231b",
            screen="#08080a"
        ),
    ),
    "mare": dict(
        dark=dict(
            canvas="#070d17", panel="#0c1524", card="#121d30", raised="#1a2842",
            raised2="#22344f", text="#e8f0fa", t2="#a7b8cf", t3="#90a3bc",
            accent="#3cc8e0", soft="#22b8d8", fill_a="#0e7490", fill_b="#2563eb",
            on_fill="#ffffff", ok="#4cc38a", warn="#e3a53a", err="#f5857b",
            screen="#05090f"
        ),
        light=dict(
            canvas="#e3edf4", panel="#eff5f9", card="#ffffff", raised="#e9f0f6",
            raised2="#dce6ef", text="#0d1b2c", t2="#3f566c", t3="#566b80",
            accent="#0a6c86", soft="#0e7490", fill_a="#0e7490", fill_b="#2563eb",
            on_fill="#ffffff", ok="#146c34", warn="#8a5a00", err="#b9231b",
            screen="#05090f"
        ),
    ),
    "aurora": dict(
        dark=dict(
            canvas="#0d0b14", panel="#14111d", card="#1b1727", raised="#262034",
            raised2="#302a42", text="#f1eefa", t2="#b9b1d0", t3="#a39bbd",
            accent="#b79cff", soft="#9b7bff", fill_a="#6d3fe0", fill_b="#c026d3",
            on_fill="#ffffff", ok="#4cc38a", warn="#e3a53a", err="#f5857b",
            screen="#0a0810"
        ),
        light=dict(
            canvas="#ece8f6", panel="#f6f3fb", card="#ffffff", raised="#f0ecf8",
            raised2="#e5dff2", text="#1a1426", t2="#50466a", t3="#62587c",
            accent="#6b3fd4", soft="#6d3fe0", fill_a="#6d3fe0", fill_b="#c026d3",
            on_fill="#ffffff", ok="#146c34", warn="#8a5a00", err="#b9231b",
            screen="#0a0810"
        ),
    ),
    "cinema": dict(
        dark=dict(
            canvas="#100e0c", panel="#171411", card="#1f1b17", raised="#2a2520",
            raised2="#342e28", text="#f4f0ea", t2="#bab0a3", t3="#a3998c",
            accent="#f5a742", soft="#f5a742", fill_a="#f5a524", fill_b="#ea7d12",
            on_fill="#1b1204", ok="#5cc98e", warn="#f2d14b", err="#f5857b",
            screen="#0b0a09"
        ),
        light=dict(
            canvas="#ece7df", panel="#f6f2ec", card="#fffdfa", raised="#f1ece4",
            raised2="#e6dfd4", text="#1f1a14", t2="#55493c", t3="#685c4e",
            accent="#8c5200", soft="#d98a1f", fill_a="#f5a524", fill_b="#ea7d12",
            on_fill="#1b1204", ok="#146c34", warn="#7a6200", err="#b9231b",
            screen="#0b0a09"
        ),
    ),

}


def nomes() -> tuple[str, ...]:
    """Os identificadores das paletas, na ordem em que aparecem para o usuário."""
    return tuple(_PALETAS)


def existe(nome: str) -> bool:
    return nome in _PALETAS


def _cores(nome: str, modo: str) -> dict[str, str]:
    # Nome ou modo desconhecido volta ao padrão: um arquivo de preferências editado à mão, ou
    # gravado por uma versão futura, não pode impedir o aplicativo de abrir.
    paleta = _PALETAS.get(nome) or _PALETAS[PADRAO]
    return paleta["light" if modo == "light" else "dark"]


def papeis(nome: str = PADRAO, modo: str = "dark") -> dict[str, str]:
    """Os papéis de cor de uma paleta, num dicionário novo a cada chamada."""
    return {chave: valor for chave, valor in _cores(nome, modo).items() if not chave.startswith("_")}


def legado(nome: str = PADRAO, modo: str = "dark") -> dict[str, str]:
    """As chaves antigas do tema, derivadas dos papéis; ``atual`` as reproduz como eram."""
    cores = _cores(nome, modo)
    p = papeis(nome, modo)
    escuro = modo != "light"
    chaves = {
        "bg": p["canvas"], "surface": p["card"], "surface_alt": p["raised"], "border": p["raised2"],
        "text": p["text"], "text_dim": p["t2"],
        # Preenchimento que leva texto branco (botão primário, seleções) e destaque usado como
        # texto são chaves separadas: o mesmo azul não serve aos dois. Com um só papel, o texto do
        # botão primário ficava em 3,32 : 1 e a aba selecionada em 4,27 : 1 (referência: 4,5 : 1).
        "accent": p["accent"], "accent_hover": p["accent"], "accent_fg": p["accent"],
        "accent_text": p["on_fill"], "accent_fill": p["fill_a"], "accent_fill_hover": p["fill_b"],
        # Fundo do selo "ao vivo": o vermelho de erro deixava o texto branco em 3,7 : 1.
        "live": "#c0392f" if escuro else "#cf222e",
        "ok": p["ok"], "warn": p["warn"], "error": p["err"], "track": p["raised2"],
        # Borda de foco do teclado: pelo menos 3 : 1 contra a borda sem foco e contra o
        # preenchimento do botão primário.
        "focus": "#ffffff" if escuro else "#000000",
    }
    chaves.update(cores.get("_legado", {}))
    return chaves
