"""Texto visível nasce nos catálogos, não dentro de uma tela.

Um literal com palavras posto direto num widget fica no idioma em que foi
escrito depois da troca: "faltam 0:41" aparecia na fila com a interface em
inglês, e nenhum teste de idioma pegava, porque o texto só surgia com uma
tarefa em andamento. Este teste lê o código da apresentação e recusa
literais com letras nas chamadas que põem texto na tela.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_APRESENTACAO = Path(__file__).resolve().parents[2] / "src" / "videomanager" / "presentation"
_POEM_TEXTO = {"setText", "setToolTip", "setWindowTitle", "setPlaceholderText", "addItem", "insertItem",
               "setItemText", "drawText", "setTabText", "setStatusTip", "showMessage", "setTitle",
               "addAction", "addMenu", "information", "warning", "critical", "question"}
# Onde está o texto em cada chamada: nas outras posições vão dado da lista
# (identificador como "dark"), índice ou retângulo.
_POSICAO_DO_TEXTO = {"setItemText": 1, "setTabText": 1, "insertItem": 1}
# Letra de verdade, fora de marcadores de formato ({nome}, %s).
_PALAVRA = re.compile(r"[^\W\d_]{2,}")
# Unidades, iguais nas duas línguas.
_UNIDADE = re.compile(r"^\s*(kbps|fps|dB|ms|px|KB|MB|GB)\s*$")


def _literais(no: ast.AST):
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        yield no.value
    elif isinstance(no, ast.JoinedStr):
        for parte in no.values:
            if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                yield parte.value


def test_nenhum_literal_com_palavras_vai_direto_para_a_tela():
    achados = []
    for arquivo in sorted(_APRESENTACAO.rglob("*.py")):
        if arquivo.name in ("strings.py", "strings_en.py"):
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                    and no.func.attr in _POEM_TEXTO):
                continue
            if no.func.attr == "drawText":
                argumentos = no.args
            else:
                posicao = _POSICAO_DO_TEXTO.get(no.func.attr, 0)
                argumentos = no.args[posicao:posicao + 1]
            for argumento in argumentos:
                for texto in _literais(argumento):
                    sem_formato = re.sub(r"\{[^}]*\}|%[sd]", "", texto)
                    if _PALAVRA.search(sem_formato) and not _UNIDADE.match(sem_formato):
                        achados.append(f"{arquivo.relative_to(_APRESENTACAO)}:{no.lineno}: {texto!r}")
    assert achados == []
