"""Toda chave de texto usada no código existe no catálogo e recebe os parâmetros do texto.

Uma chave errada ou um parâmetro a menos só quebra na hora de exibir a
mensagem — quase sempre num caminho de erro, que teste nenhum percorre. A
conferência é pelo código-fonte, sem executar nada além do registro dos
catálogos, que só usa a biblioteca padrão.
"""
import ast
import importlib
import re
import string
from pathlib import Path

from videomanager.domain import i18n

ROOT = Path(__file__).resolve().parents[2] / "src" / "videomanager"

# Importar a camada registra o catálogo dela; o preflight registra o seu.
for _modulo in ("videomanager.application", "videomanager.infrastructure", "videomanager.preflight"):
    importlib.import_module(_modulo)

# Tabelas que guardam chaves para as chamadas com chave calculada
# (t(_KIND_KEYS[kind]), Text(_PHASES.get(...))).
_TABELA_DE_CHAVES = re.compile(r"_[A-Z_]*(KEYS|PHASES?|PHASE_LABELS)$")
_CHAVE = re.compile(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)+")


def _campos(texto: str) -> set[str]:
    return {nome.split(".")[0].split("[")[0] for _, nome, _, _ in string.Formatter().parse(texto) if nome}


def _chamada_de_texto(no: ast.Call) -> str | None:
    """Nome da função (t, Text ou variants) quando a chamada é do núcleo de idioma."""
    if isinstance(no.func, ast.Name) and no.func.id in ("t", "Text", "variants"):
        return no.func.id
    if (isinstance(no.func, ast.Attribute) and no.func.attr in ("t", "variants")
            and isinstance(no.func.value, ast.Name) and no.func.value.id == "i18n"):
        return no.func.attr
    return None


def test_chaves_usadas_existem_e_recebem_os_parametros_do_texto():
    problemas, conferidas = [], 0
    for arquivo in sorted(ROOT.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Assign) and any(isinstance(alvo, ast.Name) and _TABELA_DE_CHAVES.match(alvo.id)
                                                  for alvo in no.targets):
                for folha in ast.walk(no.value):
                    if isinstance(folha, ast.Constant) and isinstance(folha.value, str) \
                            and _CHAVE.fullmatch(folha.value) and folha.value not in i18n._catalog:
                        problemas.append(f"{arquivo.relative_to(ROOT)}:{no.lineno}: chave inexistente {folha.value}")
                continue
            if not isinstance(no, ast.Call) or not no.args:
                continue
            funcao = _chamada_de_texto(no)
            chave = no.args[0]
            if funcao is None or not (isinstance(chave, ast.Constant) and isinstance(chave.value, str)):
                continue
            conferidas += 1
            lugar = f"{arquivo.relative_to(ROOT)}:{no.lineno}"
            if chave.value not in i18n._catalog:
                problemas.append(f"{lugar}: chave inexistente {chave.value}")
                continue
            if funcao == "variants" or any(k.arg is None for k in no.keywords):
                continue
            dados = {k.arg for k in no.keywords}
            for texto in i18n.variants(chave.value):
                if _campos(texto) - dados:
                    problemas.append(f"{lugar}: {chave.value} sem {sorted(_campos(texto) - dados)}")
    assert conferidas > 150
    assert problemas == []
