"""Toda regra de QSS de um ``role`` tem quem a aplique.

Uma renovação visual troca os widgets e deixa para trás as regras deles: ``spin-tool`` (07403e8), ``transport`` (bed24d6) e
``note`` (fefa97b) ficaram no ``theme.py`` por ~25 linhas depois de o código parar de aplicá-las, e o QSS é reaplicado à
aplicação inteira a cada troca de paleta. O teste lê os ``[role="…"]`` do QSS e exige que o nome apareça como literal no código
da apresentação (``setProperty("role", …)``, tabelas de papel, variáveis): regra órfã reprova.

Só ``ast``, ``re`` e ``pathlib``: roda também no job da CI que não tem PySide6.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2] / "src" / "videomanager" / "presentation"
_ARQUIVOS_DO_TEMA = {"theme.py", "paletas.py"}


def _literais_do_codigo() -> set[str]:
    achados: set[str] = set()
    for arquivo in _RAIZ.rglob("*.py"):
        if arquivo.name in _ARQUIVOS_DO_TEMA:
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Constant) and isinstance(no.value, str):
                achados.add(no.value)
    return achados


def test_nenhuma_regra_de_qss_de_papel_ficou_sem_quem_a_aplique():
    folha = (_RAIZ / "qt" / "theme.py").read_text(encoding="utf-8")
    papeis = set(re.findall(r'\[role="([\w-]+)"\]', folha))
    assert len(papeis) > 50, "o QSS mudou de forma: o teste não está lendo os papéis"
    orfaos = sorted(papel for papel in papeis if papel not in _literais_do_codigo())
    assert orfaos == [], f"regras de QSS sem quem as aplique: {orfaos}"
