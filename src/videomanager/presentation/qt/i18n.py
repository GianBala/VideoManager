"""Troca de idioma da interface com a janela aberta.

Recriar a janela custaria perto de um segundo e perderia o que está na tela —
projeto, seleção, reprodução, rolagens. A troca reescreve só os textos: os
valores do módulo :mod:`strings` passam a ser os do idioma novo, e todo texto
guardado num widget é refeito pela origem registrada com :func:`bind`. O que
lê ``strings`` na hora (menus montados ao abrir, modelos, pintura) já sai
certo sem registro nenhum.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TypeVar

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from videomanager.domain import i18n
from videomanager.presentation.qt import strings

T = TypeVar("T")


def _table(module) -> dict[str, object]:
    return {name: value for name, value in vars(module).items() if name.isupper()}


# Fotografado no import, antes de qualquer troca: é o que strings.py traz.
_TABLES: dict[str, dict[str, object]] = {i18n.PORTUGUESE: _table(strings)}
_current = i18n.PORTUGUESE

# De onde cada setter lê o texto de volta, para saber se alguém o trocou depois.
_GETTERS = {
    "setText": "text",
    "setToolTip": "toolTip",
    "setPlaceholderText": "placeholderText",
    "setWindowTitle": "windowTitle",
    "setTitle": "title",
    "setStatusTip": "statusTip",
}

# objeto → {setter: (origem, texto aplicado)}. Referência fraca: o registro não
# segura widget nenhum, e o que é destruído sai daqui sozinho.
_bound: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_callbacks: list[weakref.WeakMethod] = []


def bind(obj: T, setter: str, source: Callable[[], str]) -> T:
    """Aplica ``source()`` com ``setter`` agora e de novo a cada troca de idioma.

    ``source`` lê ``strings`` na hora em que é chamada; o que ela capturar do
    estado de agora (um nome, uma contagem) volta igual, só que no idioma novo.
    Um segundo ``bind`` no mesmo objeto e setter substitui o primeiro.
    """
    if setter not in _GETTERS:
        raise ValueError(f"setter sem leitura correspondente: {setter}")
    text = source()
    getattr(obj, setter)(text)
    _bound.setdefault(obj, {})[setter] = (source, text)
    return obj


def on_language_change(callback: Callable[[], None]) -> None:
    """Chama o método ``callback`` a cada troca, enquanto o dono existir.

    Para o texto que depende de estado e já tem quem o recalcule (contadores,
    planos, listas montadas conforme a mídia). Só método: uma função solta
    prenderia o dono para sempre no registro.
    """
    _callbacks.append(weakref.WeakMethod(callback))


def apply_language(code: str) -> None:
    """Passa a interface inteira para ``code``, sem pintar nada pela metade."""
    global _current
    if code == _current:
        i18n.set_language(code)
        return
    table = _TABLES[code]
    # Sem isso, cada texto trocado pediria uma pintura, e a janela mostraria
    # por um instante metade num idioma e metade no outro.
    frozen = [window for window in QApplication.topLevelWidgets() if window.updatesEnabled()]
    for window in frozen:
        window.setUpdatesEnabled(False)
    try:
        i18n.set_language(code)
        for name, value in table.items():
            setattr(strings, name, value)
        _current = code
        _reapply()
        # As medidas que dependem do texto (larguras, quebras de linha) ficam
        # prontas antes da primeira pintura, e não um quadro depois dela.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    finally:
        for window in frozen:
            window.setUpdatesEnabled(True)


def _reapply() -> None:
    for obj, setters in list(_bound.items()):
        if not shiboken6.isValid(obj):
            del _bound[obj]
            continue
        for setter, (source, shown) in list(setters.items()):
            # Outro texto escrito depois do bind: quem o escreveu é o dono
            # agora, e refazer a origem antiga apagaria o que ele mostrou.
            if getattr(obj, _GETTERS[setter])() != shown:
                del setters[setter]
                continue
            text = source()
            getattr(obj, setter)(text)
            setters[setter] = (source, text)
    for ref in list(_callbacks):
        method = ref()
        if method is None or not shiboken6.isValid(method.__self__):
            _callbacks.remove(ref)
            continue
        method()
