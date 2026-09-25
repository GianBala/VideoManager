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
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from videomanager.domain import i18n
from videomanager.presentation.qt import strings, strings_en

T = TypeVar("T")


def _table(module) -> dict[str, object]:
    return {name: value for name, value in vars(module).items() if name.isupper()}


# O português é fotografado no import, antes de qualquer troca: é o que
# strings.py traz, e a troca de volta precisa dele depois de o módulo ter
# recebido os valores do inglês.
_TABLES: dict[str, dict[str, object]] = {i18n.PORTUGUESE: _table(strings), i18n.ENGLISH: _table(strings_en)}
_current = i18n.PORTUGUESE
_switching = False

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
_after_layout: list[weakref.WeakMethod] = []


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


def release(obj: object, setter: str) -> None:
    """Tira ``setter`` de ``obj`` do registro: o texto ali passou a ser dado.

    Para o campo que mostra o conteúdo do usuário no lugar de um texto
    inicial. Sem isso, um conteúdo igual ao texto inicial seria tomado por ele
    e reescrito na troca — e num campo que edita o projeto ao vivo, a troca de
    idioma viraria uma edição.
    """
    setters = _bound.get(obj)
    if setters is not None:
        setters.pop(setter, None)


def on_language_change(callback: Callable[[], None], *, after_layout: bool = False) -> None:
    """Chama o método ``callback`` a cada troca, enquanto o dono existir.

    Para o texto que depende de estado e já tem quem o recalcule (contadores,
    planos, listas montadas conforme a mídia). Só método: uma função solta
    prenderia o dono para sempre no registro.

    ``after_layout`` é para quem mede o layout (divisões, colunas): roda depois
    de os layouts assentarem com todos os textos novos. Medido no meio da
    troca, o layout tinha parte dos textos trocados — e um ``QSplitter`` que
    aperta uma coluna para caber um mínimo provisório não a devolve depois.
    """
    (_after_layout if after_layout else _callbacks).append(weakref.WeakMethod(callback))


def retext_items(combo: QComboBox, text: Callable[[object], str | None]) -> None:
    """Reescreve o texto de cada item de ``combo`` a partir do dado dele.

    ``text`` devolve o texto novo, ou ``None`` para deixar o item como está
    (um nome de codec, uma resolução). O dado e a seleção não mudam — é por
    eles que o resto do código se guia —, e os sinais ficam bloqueados para a
    troca não se passar por uma escolha do usuário.
    """
    blocked = combo.blockSignals(True)
    try:
        for index in range(combo.count()):
            new = text(combo.itemData(index))
            if new is not None and new != combo.itemText(index):
                combo.setItemText(index, new)
    finally:
        combo.blockSignals(blocked)


def align_label_column(labels: list[QLabel]) -> None:
    """Dá a todos os rótulos a largura do maior, medida no texto de agora.

    A dica de tamanho do QLabel guarda o mínimo em vigor quando foi calculada,
    e mudar o mínimo depois não a invalida (medido: 300 px continuavam 300 px
    com o mínimo zerado). Remedida depois de uma troca de idioma, a coluna do
    texto mais longo nunca encolhia. Zerar o mínimo e reescrever o texto faz
    cada rótulo medir de novo só o conteúdo — passando por um texto diferente,
    porque reescrever o mesmo não faz nada, e o rótulo vazio de uma linha sem
    título segurava a coluna larga.
    """
    for label in labels:
        label.setMinimumWidth(0)
        text = label.text()
        label.setText(text + " ")
        label.setText(text)
    width = max((label.sizeHint().width() for label in labels), default=0)
    for label in labels:
        label.setMinimumWidth(width)


def switching() -> bool:
    """Se uma troca de idioma está em andamento.

    Para quem reage a mudança de tamanho: um texto mais curto ou mais longo
    muda a largura de um painel, e isso não é o usuário redimensionando a
    janela — não pode desfazer o arranjo que ele montou.
    """
    return _switching


def apply_language(code: str) -> None:
    """Passa a interface inteira para ``code``, sem pintar nada pela metade."""
    global _current, _switching
    if code == _current:
        i18n.set_language(code)
        return
    table = _TABLES[code]
    # Sem isso, cada texto trocado pediria uma pintura, e a janela mostraria
    # por um instante metade num idioma e metade no outro.
    frozen = [window for window in QApplication.topLevelWidgets() if window.updatesEnabled()]
    for window in frozen:
        window.setUpdatesEnabled(False)
    _switching = True
    try:
        i18n.set_language(code)
        for name, value in table.items():
            setattr(strings, name, value)
        _current = code
        _reapply()
        # As medidas que dependem do texto (larguras, quebras de linha) ficam
        # prontas antes da primeira pintura, e não um quadro depois dela.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        _call(_after_layout)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    finally:
        _switching = False
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
    _call(_callbacks)


def _call(callbacks: list[weakref.WeakMethod]) -> None:
    for ref in list(callbacks):
        method = ref()
        if method is None or not shiboken6.isValid(method.__self__):
            callbacks.remove(ref)
            continue
        method()
