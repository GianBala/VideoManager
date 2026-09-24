"""Idioma da interface, para todas as camadas.

Mora no domínio porque é a única camada que todas as outras podem importar — e
por isso usa só a biblioteca padrão. Cada camada registra o próprio catálogo
com :func:`register`, em pares ``CHAVE: ("português", "inglês")``: as duas
línguas lado a lado, para uma frase nova não nascer só numa delas.
"""

from __future__ import annotations

PORTUGUESE = "pt-BR"
ENGLISH = "en"
LANGUAGES = (PORTUGUESE, ENGLISH)

_language = PORTUGUESE
_catalog: dict[str, tuple[str, str]] = {}


def language() -> str:
    return _language


def set_language(code: str) -> None:
    global _language
    if code not in LANGUAGES:
        raise ValueError(f"idioma desconhecido: {code!r}")
    _language = code


def register(table: dict[str, tuple[str, str]]) -> None:
    """Acrescenta um catálogo ao que :func:`t` conhece.

    A mesma chave com outro texto é recusada: dois catálogos disputando um nome
    fariam um deles sumir em silêncio, e a tela mostraria a frase errada.
    """
    for key, pair in table.items():
        if _catalog.get(key, pair) != pair:
            raise ValueError(f"chave repetida em catálogos diferentes: {key}")
    _catalog.update(table)


def t(key: str, /, **params: object) -> str:
    """O texto de ``key`` no idioma de agora, com os parâmetros preenchidos."""
    return _catalog[key][1 if _language == ENGLISH else 0].format(**params)


class Text:
    """Texto guardado que só vira ``str`` quando é mostrado.

    Uma tarefa da fila, um aviso ou uma mensagem de erro nascem num idioma e
    continuam na tela depois da troca. Guardados já traduzidos, ficariam no
    idioma antigo até sumirem; ``str(texto)`` traduz no idioma daquele instante.
    """

    __slots__ = ("key", "params")

    def __init__(self, key: str, /, **params: object) -> None:
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return t(self.key, **self.params)

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)

    def __repr__(self) -> str:
        return f"Text({self.key!r})"


def decimal_separator() -> str:
    return "." if _language == ENGLISH else ","


def decimal(value: float, places: int = 1, *, trim: bool = False, sign: bool = False) -> str:
    """Número com ``places`` casas e o separador decimal do idioma.

    ``trim`` tira os zeros à direita que não dizem nada ("2 MB", não "2,0 MB");
    ``sign`` mostra o sinal também no positivo, como num ajuste de volume.
    """
    text = f"{value:{'+' if sign else ''}.{places}f}"
    if trim and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", decimal_separator())
