"""Cor escrita direto no código de apresentação: só a que já existe, e nenhuma a mais.

Uma cor literal fora do ``theme.py`` não acompanha a paleta: no tema claro ela fica onde
estava, e a troca de paleta ao vivo a esquece. O editor já tem dezenas delas (a maior parte
na linha do tempo, que se pinta sozinha), e a renovação visual as passa para os papéis do
tema uma a uma.

Este teste é uma catraca. O orçamento abaixo é o que existia quando a renovação começou:
cor nova reprova, e cor removida **também** reprova, até o número ser baixado — assim o
orçamento só diminui e nunca fica folgado. Cor semântica de verdade (o gradiente de cada
filtro, por exemplo) não precisa sair: ela fica no orçamento, de propósito, até ganhar um
lugar próprio no tema.

Só ``ast`` e ``pathlib``: roda também no job da CI que não tem PySide6.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2] / "src" / "videomanager" / "presentation"
_HEX = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b")
_HEX_CURTO = re.compile(r"^#[0-9a-fA-F]{3}$")

# A casa das cores: aqui pode.
_LIVRES = {"qt/theme.py", "qt/paletas.py"}

# Arquivo -> quantas cores literais ele tinha no começo da renovação.
_ORCAMENTO = {
    "qt/fullscreen_preview.py": 2,
    "qt/panels/edit_panel.py": 16,
    "qt/panels/edit_widgets.py": 18,
    "qt/panels/timeline.py": 29,
    "qt/strings.py": 3,
    "qt/strings_en.py": 3,
}


def _contar(arquivo: Path) -> int:
    total = 0
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            total += len(_HEX.findall(no.value)) + (1 if _HEX_CURTO.match(no.value) else 0)
        elif isinstance(no, ast.Call) and getattr(no.func, "id", getattr(no.func, "attr", "")) == "QColor":
            # QColor(r, g, b[, a]) com inteiros literais: a mesma cor fixa, sem o "#".
            if len(no.args) >= 3 and all(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in no.args):
                total += 1
    return total


def test_cores_literais_fora_do_tema_so_diminuem():
    achados = []
    for arquivo in sorted(_RAIZ.rglob("*.py")):
        relativo = arquivo.relative_to(_RAIZ).as_posix()
        if relativo in _LIVRES:
            continue
        obtido, esperado = _contar(arquivo), _ORCAMENTO.get(relativo, 0)
        if obtido > esperado:
            achados.append(f"{relativo}: {obtido} cores literais, o orçamento é {esperado}. "
                           "Use um papel do tema (theme.py) em vez de uma cor escrita à mão.")
        elif obtido < esperado:
            achados.append(f"{relativo}: {obtido} cores literais e o orçamento ainda é {esperado}. "
                           f"Baixe o orçamento para {obtido}.")
    assert not achados, "\n" + "\n".join(achados)


def test_orcamento_so_lista_arquivos_que_existem():
    for relativo in _ORCAMENTO:
        assert (_RAIZ / relativo).is_file(), f"{relativo} saiu do código: tire-o do orçamento"
