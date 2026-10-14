"""Inventário dos controles e das ações do aplicativo, para provar que uma reorganização não perdeu nada.

    PYTHONPATH=src python scripts/inventario_controles.py > /tmp/inv-antes.json
    PYTHONPATH=src python scripts/inventario_controles.py > /tmp/inv-depois.json
    python scripts/inventario_controles.py --comparar /tmp/inv-antes.json /tmp/inv-depois.json \\
        [--relocacoes relocacoes.json]

Uma reorganização visual move botões e campos de lugar, e o que a suíte verde não vê é o
controle que **sumiu** ou que mudou de nome: nenhum teste que não o procure levanta exceção.
O inventário percorre as quatro abas, os menus de cada aba e a janela de Configurações, e
grava cada controle com uma chave estável:

- o **nome do atributo** que o guarda (``MainWindow._url``, ``_ClipPropertiesWidget._spin_gain``),
  quando existe — é o nome que os testes e os scripts de validação usam, então renomeá-lo
  quebra os dois sem aviso;
- senão, a classe e o rótulo (texto, nome acessível, dica ou texto de exemplo), normalizados
  (sem ``&``, sem o ``+`` e o ``✓`` que hoje vão dentro do texto dos botões, sem pontuação final).

A comparação falha (código 1) se um controle do antes não está no depois e não consta em
``--relocacoes``: um JSON ``{"chave antiga": "chave nova"}``, ou ``{"chave antiga": {"removido":
"motivo"}}`` para o que sai de propósito. A chave nova precisa existir no depois.

Um processo só, perfil temporário, plataforma offscreen: nada toca nas preferências de quem roda.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

_VERSAO = 1


def _normalizar(texto: str) -> str:
    texto = (texto or "").split("\n")[0].replace("&", "")
    texto = re.sub(r"^[^\w]+", "", texto)
    texto = re.sub(r"[\s:….]+$", "", texto)
    return re.sub(r"\s+", " ", texto).casefold()


def _rotulo(widget) -> str:
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit

    texto = widget.text() if hasattr(widget, "text") and callable(widget.text) else ""
    if not texto and isinstance(widget, QComboBox):
        texto = "|".join(widget.itemText(i) for i in range(min(widget.count(), 3)))
    if not texto and isinstance(widget, (QLineEdit, QPlainTextEdit)):
        texto = widget.placeholderText()
    return _normalizar(texto or widget.accessibleName() or widget.toolTip())


def _mapa_de_atributos(raizes) -> dict[int, str]:
    """id(widget) -> ``Classe._atributo``, varrendo todo widget da árvore e os soltos."""
    from PySide6.QtWidgets import QWidget

    mapa: dict[int, str] = {}
    visitados: set[int] = set()
    fila = list(raizes)
    for raiz in list(fila):
        fila.extend(raiz.findChildren(QWidget))
    for dono in fila:
        if id(dono) in visitados:
            continue
        visitados.add(id(dono))
        for nome, valor in vars(dono).items():
            if isinstance(valor, QWidget) and id(valor) not in mapa and nome.startswith("_"):
                mapa[id(valor)] = f"{type(dono).__name__}.{nome}"
    return mapa


def _controles(escopo: str, pagina, mapa: dict[int, str]) -> list[dict]:
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
                                   QComboBox, QLineEdit, QPlainTextEdit, QScrollBar, QTabBar, QTextEdit)

    tipos = (QAbstractButton, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QAbstractSlider,
             QAbstractItemView, QTabBar)
    achados, repetidas = [], Counter()
    from PySide6.QtWidgets import QWidget

    for widget in (w for w in pagina.findChildren(QWidget) if isinstance(w, tipos)):
        if isinstance(widget, QScrollBar) or not widget.isVisibleTo(pagina) and not isinstance(widget, QTabBar):
            continue
        if isinstance(widget, QTabBar):
            for indice in range(widget.count()):
                achados.append({"escopo": escopo, "chave": f"{escopo}|aba:{_normalizar(widget.tabText(indice))}",
                                "classe": "QTabBar", "rotulo": _normalizar(widget.tabText(indice)), "papel": "",
                                "habilitado": widget.isTabEnabled(indice)})
            continue
        atributo = mapa.get(id(widget))
        base = f"{escopo}|{atributo}" if atributo else f"{escopo}|{type(widget).__name__}:{_rotulo(widget)}"
        repetidas[base] += 1
        chave = base if repetidas[base] == 1 else f"{base}#{repetidas[base]}"
        achados.append({"escopo": escopo, "chave": chave, "classe": type(widget).__name__, "rotulo": _rotulo(widget),
                        "papel": str(widget.property("role") or ""), "habilitado": widget.isEnabled()})
    return achados


def _menus(escopo: str, janela) -> list[dict]:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    achados = []
    # ``findChildren`` devolve os objetos que já existem; ``QAction.menu()`` passaria a posse do
    # submenu a um objeto novo, que o apagaria ao sair de cena (CLAUDE.md) e quebraria a janela.
    for menu in janela.menuBar().findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
        nome_do_menu = _normalizar(menu.title())
        for acao in menu.actions():
            if acao.isSeparator() or not acao.text():
                continue
            achados.append({"escopo": escopo, "chave": f"{escopo}|menu:{nome_do_menu}|{_normalizar(acao.text())}",
                            "classe": "QAction", "rotulo": _normalizar(acao.text()),
                            "atalho": acao.shortcut().toString(), "habilitado": acao.isEnabled()})
    return achados


def inventariar() -> dict:
    """O inventário, com o perfil temporário apagado no fim (a pasta ficava em ``/tmp`` a cada execução)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    perfil = Path(tempfile.mkdtemp(prefix="vm-inventario-"))
    try:
        return _inventariar(perfil)
    finally:
        shutil.rmtree(perfil, ignore_errors=True)


def _inventariar(perfil: Path) -> dict:
    from videomanager.infrastructure.storage import settings as armazenamento

    armazenamento.config_dir = lambda: perfil
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTabWidget

    from videomanager.app import build_app
    from videomanager.presentation.qt.settings_dialog import SettingsDialog

    app, janela = build_app([], audio_enabled=False)
    janela.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    janela.resize(1280, 1000)
    janela.show()
    for _ in range(40):
        app.processEvents()

    controles: list[dict] = []
    nomes = ("download", "convert", "editar", "metadados")
    abas = janela._tabs
    for indice, nome in enumerate(nomes):
        abas.setCurrentIndex(indice)
        for _ in range(10):
            app.processEvents()
        if nome == "metadados":
            janela._metadata_panel()
            for _ in range(10):
                app.processEvents()
        raizes = [janela, janela._edit, janela._queue_panel, janela._convert, janela._metadata_panel()
                  if nome == "metadados" else janela._convert]
        mapa = _mapa_de_atributos(raizes + [janela._edit._properties_widget])
        pagina = abas.widget(indice)
        controles += _controles(nome, pagina, mapa)
        controles += _menus(nome, janela)
    # Propriedades nasce solta (só entra na janela quando um bloco abre a aba): inventário à parte.
    mapa_prop = _mapa_de_atributos([janela._edit._properties_widget])
    controles += _controles("editar:propriedades", janela._edit._properties_widget, mapa_prop)
    # O painel do seletor de tela só abre ao clique e é uma janela própria: inventário à parte, como o das Propriedades.
    # Só existe da barra nova em diante: sem a guarda o script não rodava na árvore anterior, e a linha de base do
    # inventário dependia de um arquivo guardado à parte.
    if hasattr(janela._edit, "_canvas_popup"):
        controles += _controles("editar:tela", janela._edit._canvas_popup, _mapa_de_atributos([janela._edit]))
    # Fila: vive fora das abas.
    controles += _controles("fila", janela._queue_panel, _mapa_de_atributos([janela._queue_panel]))

    dialogo = SettingsDialog(janela._settings, janela, runtime=janela._runtime)
    dialogo.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialogo.show()
    for _ in range(20):
        app.processEvents()
    mapa_dialogo = _mapa_de_atributos([dialogo])
    guias = dialogo.findChild(QTabWidget)
    for indice in range(guias.count()):
        guias.setCurrentIndex(indice)
        for _ in range(5):
            app.processEvents()
        controles += _controles(f"ajustes:{_normalizar(guias.tabText(indice))}", guias.widget(indice), mapa_dialogo)

    chaves = Counter(c["chave"] for c in controles)
    repetidas = [k for k, n in chaves.items() if n > 1]
    # Fecha o que abriu antes de o perfil ser apagado: uma gravação tardia de preferências o recriaria.
    dialogo.close()
    janela._edit.shutdown()
    janela._edit._project_actions.confirm_replace = lambda: True
    janela.close()
    return {"versao": _VERSAO, "controles": controles, "chaves_repetidas": repetidas}


def comparar(caminho_antes: str, caminho_depois: str, caminho_relocacoes: str | None) -> int:
    antes = {c["chave"]: c for c in json.loads(Path(caminho_antes).read_text(encoding="utf-8"))["controles"]}
    depois = {c["chave"]: c for c in json.loads(Path(caminho_depois).read_text(encoding="utf-8"))["controles"]}
    relocacoes = json.loads(Path(caminho_relocacoes).read_text(encoding="utf-8")) if caminho_relocacoes else {}
    perdidos, relocados_invalidos, removidos = [], [], []
    for chave in antes:
        if chave in depois:
            continue
        destino = relocacoes.get(chave)
        if destino is None:
            perdidos.append(chave)
        elif isinstance(destino, dict):
            removidos.append((chave, destino.get("removido", "?")))
        elif destino not in depois:
            relocados_invalidos.append((chave, destino))
    novos = [c for c in depois if c not in antes]
    print(f"antes: {len(antes)} controles · depois: {len(depois)} · novos: {len(novos)} · "
          f"relocados: {sum(1 for c in antes if c not in depois and isinstance(relocacoes.get(c), str))} · "
          f"removidos de propósito: {len(removidos)}")
    for titulo, itens in (("PERDIDOS (sem relocação)", perdidos),
                          ("RELOCAÇÃO COM DESTINO INEXISTENTE", relocados_invalidos)):
        if itens:
            print(f"\n{titulo}: {len(itens)}")
            for item in itens:
                print("  -", item if isinstance(item, str) else f"{item[0]}  ->  {item[1]}")
    if removidos:
        print(f"\nREMOVIDOS DE PROPÓSITO: {len(removidos)}")
        for chave, motivo in removidos:
            print(f"  - {chave}: {motivo}")
    return 1 if perdidos or relocados_invalidos else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--comparar", nargs=2, metavar=("ANTES", "DEPOIS"))
    parser.add_argument("--relocacoes", metavar="JSON")
    args = parser.parse_args()
    if args.comparar:
        return comparar(args.comparar[0], args.comparar[1], args.relocacoes)
    json.dump(inventariar(), sys.stdout, ensure_ascii=False, indent=1, sort_keys=False)
    sys.stdout.write("\n")
    sys.stdout.flush()
    os._exit(0)  # o encerramento normal do Qt fica preso em threads de fundo


if __name__ == "__main__":
    raise SystemExit(main())
