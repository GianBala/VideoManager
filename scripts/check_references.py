"""Procura referências a nomes que não existem — o que o pyflakes não enxerga.

    PYTHONPATH=src python scripts/check_references.py

Duas varreduras sobre src/, tests/, scripts/ e packaging/:

- todo ``from videomanager… import X`` e todo ``módulo.atributo`` de um módulo do
  pacote precisa existir. Um nome removido ou renomeado não dá erro nenhum até a
  linha rodar;
- todo ``self.atributo`` lido numa classe do pacote precisa ser definido nela ou
  nas bases, inclusive por atribuição no ``__init__`` de uma base.

Foi assim que apareceu o ``strings.EDIT_MEDIA_INSERT``, que nunca existiu: o menu
da biblioteca de mídias levantava AttributeError ao abrir, e nenhum teste abria
o menu. Sai com código 1 quando acha alguma coisa.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import textwrap
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RAIZ = Path(__file__).resolve().parents[1]
PASTAS = ("src", "tests", "scripts", "packaging")


def _modulo(nome: str):
    try:
        return importlib.import_module(nome)
    except Exception:  # noqa: BLE001 — o import quebrado já é o achado
        return None


def referencias_de_modulo(arquivos: list[Path]) -> list[str]:
    achados = []
    for caminho in arquivos:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"), str(caminho))
        apelidos: dict[str, set[str]] = {}
        for no in ast.walk(arvore):
            if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("videomanager"):
                mod = _modulo(no.module)
                if mod is None:
                    achados.append(f"{caminho}:{no.lineno}: não importa {no.module}")
                    continue
                for nome in no.names:
                    if nome.name == "*":
                        continue
                    if not hasattr(mod, nome.name) and _modulo(f"{no.module}.{nome.name}") is None:
                        achados.append(f"{caminho}:{no.lineno}: {no.module} não tem {nome.name}")
                        continue
                    valor = getattr(mod, nome.name, None) or _modulo(f"{no.module}.{nome.name}")
                    if inspect.ismodule(valor):
                        apelidos.setdefault(nome.asname or nome.name, set()).add(valor.__name__)
            elif isinstance(no, ast.Import):
                for nome in no.names:
                    if nome.name.startswith("videomanager") and nome.asname:
                        if _modulo(nome.name) is None:
                            achados.append(f"{caminho}:{no.lineno}: não importa {nome.name}")
                        else:
                            apelidos.setdefault(nome.asname, set()).add(nome.name)
        # Um apelido ligado a módulos diferentes no mesmo arquivo não diz qual
        # deles uma linha usa; conferir daria falso positivo.
        unicos = {nome: _modulo(next(iter(mods))) for nome, mods in apelidos.items() if len(mods) == 1}
        for no in ast.walk(arvore):
            if (isinstance(no, ast.Attribute) and isinstance(no.ctx, ast.Load)
                    and isinstance(no.value, ast.Name) and no.value.id in unicos):
                mod = unicos[no.value.id]
                if mod is not None and not hasattr(mod, no.attr) and _modulo(f"{mod.__name__}.{no.attr}") is None:
                    achados.append(f"{caminho}:{no.lineno}: {mod.__name__} não tem {no.attr}")
    return achados


def _atribuidos_em(classe: type) -> set[str]:
    """``self.x = …`` escritos no código da classe (vale para bases de fora do pacote)."""
    try:
        arvore = ast.parse(textwrap.dedent(inspect.getsource(classe)))
    except (OSError, TypeError, SyntaxError):
        return set()
    return {no.attr for no in ast.walk(arvore)
            if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name)
            and no.value.id == "self" and isinstance(no.ctx, ast.Store)}


def atributos_de_instancia(raiz: Path) -> list[str]:
    achados = []
    for caminho in sorted((raiz / "src" / "videomanager").rglob("*.py")):
        nome_modulo = ".".join(caminho.relative_to(raiz / "src").with_suffix("").parts)
        mod = _modulo(nome_modulo)
        if mod is None:
            achados.append(f"{caminho}: não importa")
            continue
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            classe = getattr(mod, no.name, None) if isinstance(no, ast.ClassDef) else None
            if not inspect.isclass(classe):
                continue
            definidos = set(dir(classe))
            for base in classe.__mro__:
                definidos |= set(getattr(base, "__annotations__", {}))
                definidos |= set(getattr(base, "__dataclass_fields__", {}))
                definidos |= set(getattr(base, "__slots__", ()) or ())
                if base is not classe and base is not object:
                    definidos |= _atribuidos_em(base)
            usa_setattr = any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "setattr"
                              for n in ast.walk(no))
            for sub in ast.walk(no):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"):
                    if isinstance(sub.ctx, (ast.Store, ast.Del)):
                        definidos.add(sub.attr)
            if usa_setattr:
                continue
            for sub in ast.walk(no):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self" and isinstance(sub.ctx, ast.Load)
                        and sub.attr not in definidos):
                    achados.append(f"{caminho}:{sub.lineno}: {no.name} lê self.{sub.attr}, que não é definido")
    return sorted(set(achados))


def main() -> int:
    sys.path.insert(0, str(RAIZ / "src"))
    arquivos = [p for pasta in PASTAS for p in sorted((RAIZ / pasta).rglob("*.py"))
                if "__pycache__" not in p.parts]
    achados = referencias_de_modulo(arquivos) + atributos_de_instancia(RAIZ)
    for linha in achados:
        print(linha)
    print(f"{len(arquivos)} arquivos conferidos; {len(achados)} referência(s) sem destino.")
    return 1 if achados else 0


if __name__ == "__main__":
    raise SystemExit(main())
