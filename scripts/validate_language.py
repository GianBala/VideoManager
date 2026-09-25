"""Confere a troca de idioma: ao vivo igual a do zero, nada esquecido, sem pintura no meio.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python scripts/validate_language.py [--modo M] [--cena NOME]

Para cada cena (as três abas vazias e com conteúdo, a fila com tarefas, o
editor com bloco de vídeo, texto, filtro e transição selecionados, a aba
Propriedades, a tela cheia) monta duas janelas no mesmo processo:

- **A** abre em português, entra na cena, e troca para o inglês ao vivo;
- **B** nasce depois dessa troca, já em inglês, e entra na mesma cena.

A troca de volta leva as duas ao português ao vivo. Compara-se o texto de cada
widget (texto, dica, placeholder, título, abas, itens de lista, células e
cabeçalhos de tabela, campos numéricos como aparecem, menus e ações, e o texto
pintado à mão, como o da linha do tempo) e a geometria de cada widget visível:

- inglês ao vivo (A) contra inglês do zero (B): diferença é texto que a troca
  esqueceu ou medida que ela não refez;
- português de volta (A e B) contra o português do começo (A): diferença é
  estado que a ida e a volta não devolveram.

Três modos, porque texto de outra largura muda o layout por razões legítimas:

- ``pseudo`` (padrão): cada texto de catálogo entre « ». Compara texto, e lista
  todo texto visível com letras e sem as marcas — texto que não passa pelo
  catálogo. Geometria só na ida e volta da mesma janela;
- ``identidade``: o "inglês" é o próprio português. Nenhum texto muda de
  largura, então qualquer diferença de geometria é da mecânica da troca;
- ``ingles``: a tradução de verdade. Lista todo texto visível com cara de
  português (acento, ou palavra que o inglês não tem): o que a tradução
  esqueceu, ou o que outra camada compôs sem catálogo.

Diálogos e menus de contexto, que se montam ao abrir e já nascem no idioma do
momento, passam no fim pela busca de texto do modo.

Mede ainda, por cena, o tempo da troca, as pinturas durante ela (têm de ser
zero) e os efeitos colaterais: desfazer, alteração não salva, pedido de quadro,
reprodução, aba e bloco escolhidos, workers da prévia. Sai com código 1 se
houver qualquer diferença ou efeito.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RAIZ = Path(__file__).resolve().parents[1]

# Texto que não é frase: número, tempo, tamanho, nome de arquivo, codec, sigla.
_UNIDADE = r"(px|pt|s|dB|fps|kbps|Mbps|KB|MB|GB|B|p|x|ms|min)"
_DADO = re.compile(
    rf"""^(
        [\W\d_]*                                   # só símbolos e números
      | .*\.(mp4|mkv|webm|mov|m4a|mp3|png|jpg|vmp|json|wav|flac|ogg|opus|gif|avi)\b.*   # arquivo
      | [\d.,:\s×x%/+\-−]*{_UNIDADE}?([\s·/]+[\d.,:\s×x%/+\-−]+{_UNIDADE}?)*   # medida
      | (H\.264|HEVC|H\.265|AV1|VP9|VP8|AAC|ALAC|MP3|FLAC|WAV|Opus|Vorbis|MKV|MP4|WEBM|GIF|MOV|PNG)(\W.*)?
      | https?://\S+
      | (/|~/|[A-Za-z]:\\)\S.*                     # caminho
    )$""",
    re.VERBOSE | re.IGNORECASE,
)
# Listas cujo conteúdo é dado do sistema, e não texto do aplicativo.
_LISTAS_DE_DADO = ("_FontSelectorWidget",)
# O que as próprias cenas trazem: título e autor da mídia analisada, nome das
# tarefas, das trilhas e dos itens da playlist, conteúdo do texto, faixas de
# áudio (bitrate · codec · tamanho). E nomes próprios, que nenhuma língua
# traduz: navegadores de onde ler cookies, placas de vídeo, códigos de idioma.
_DADOS_DA_CENA = re.compile(
    r"^(Big Buck Bunny.*|Blender( · .*)?|Vídeo [AB]|Olá|Trilha da câmera|\d+\. Item \d+.*"
    r"|\d+ kbps · \w+ · [\d.,]+ \w?B"
    r"|Brave|Chrome|Chromium|Edge|Firefox|Opera|Safari|Vivaldi|Whale"
    r"|NVIDIA \(NVENC\)|Intel \(Quick Sync\)|AMD \(AMF\)|VAAPI \(Linux\)"
    r"|[a-z]{2}(-[A-Z]{2})?(, [a-z]{2}(-[A-Z]{2})?)*)$"
)


# Marcas do pseudoidioma, latinas para não trazer uma fonte de reserva com
# outra altura de linha ("⟦ ⟧" faziam o cabeçalho da fila crescer 5 px). Nem
# marcas invisíveis deixam a largura intacta (U+2060 tira 1 px de alguns
# botões), por isso a geometria da troca se confere no modo identidade.
ABRE, FECHA = "«", "»"


def _pseudo(valor):
    if isinstance(valor, str):
        return f"{ABRE}{valor}{FECHA}" if valor else valor
    if isinstance(valor, tuple):
        return tuple(_pseudo(v) for v in valor)
    if isinstance(valor, dict):
        return {chave: _pseudo(v) for chave, v in valor.items()}
    return valor


def _instalar(modo: str) -> None:
    """Troca o inglês pelo pseudoidioma ou pelo próprio português (identidade)."""
    import importlib

    from videomanager.domain import i18n
    from videomanager.presentation.qt import i18n as idioma
    if modo == "ingles":
        return
    for camada in ("videomanager.application", "videomanager.infrastructure"):
        importlib.import_module(camada)
    transformar = _pseudo if modo == "pseudo" else (lambda valor: valor)
    idioma._TABLES[i18n.ENGLISH] = {nome: transformar(v) for nome, v in idioma._TABLES[i18n.PORTUGUESE].items()}
    for chave, (pt, _) in list(i18n._catalog.items()):
        i18n._catalog[chave] = (pt, transformar(pt))


# ---------------------------------------------------------------------------
# Janela e recursos
# ---------------------------------------------------------------------------

def _processar(app, ms: int = 60) -> None:
    fim = time.perf_counter() + ms / 1000
    while time.perf_counter() < fim:
        app.processEvents()
        time.sleep(0.005)


def _esperar(app, condicao, prazo: float = 20.0) -> bool:
    fim = time.perf_counter() + prazo
    while not condicao() and time.perf_counter() < fim:
        app.processEvents()
        time.sleep(0.01)
    return condicao()


def _janela(app):
    from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                        build_processing_service)
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.main_window import MainWindow
    janela = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    janela.show()
    _processar(app, 150)
    return janela


def _fechar(app, janela) -> None:
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    fullscreen = getattr(janela._edit, "_fullscreen", None)
    if fullscreen is not None:
        fullscreen.close()
    janela._edit._project_actions.confirm_replace = lambda: True
    janela.close()
    _processar(app, 100)
    janela.deleteLater()
    # Fora do exec() o deleteLater não é entregue sozinho: sem isto as janelas
    # das cenas anteriores continuavam vivas, no registro da troca.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    _processar(app, 50)


def _recursos(pasta: Path) -> dict:
    """Mídia sintética (gerada uma vez) e as peças de cada cena."""
    from videomanager.domain.formats import MediaInfo
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    from videomanager.infrastructure.yt_dlp.formats import build_matrix

    tools = find_tools()
    if tools is None:
        raise SystemExit("ffmpeg não encontrado.")
    receitas = {
        "clipe.mp4": ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
                      "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"],
        "outro.mp4": ["-f", "lavfi", "-i", "mandelbrot=s=640x360:r=30", "-t", "4", "-c:v", "libx264",
                      "-preset", "veryfast"],
        "musica.m4a": ["-f", "lavfi", "-i", "sine=d=6", "-c:a", "aac"],
        "foto.png": ["-f", "lavfi", "-i", "color=c=orange:s=800x600", "-frames:v", "1"],
    }
    for nome, args in receitas.items():
        if not (pasta / nome).exists():
            subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args, str(pasta / nome)],
                           check=True, **subprocess_kwargs())
    locais = {nome: probe_file(pasta / nome, tools) for nome in receitas}
    refs = {nome: media_ref(local) for nome, local in locais.items()}
    a = Clip(refs["clipe.mp4"], 0.0, 4.0, clip_id=901)
    b = Clip(refs["outro.mp4"], 4.0, 4.0, clip_id=902)
    transicao = Clip(MediaRef(Path("Transição_x"), MediaKind.IMAGE, duration=1.0), 3.5, 1.0, clip_id=903,
                     overlay_type="transition", transition_name="dissolve",
                     transition_left_id=901, transition_right_id=902)
    texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=3.0), 0.5, 3.0, clip_id=904,
                 overlay_type="text", text_content="Olá")
    filtro = Clip(MediaRef(Path("Filtro_x"), MediaKind.IMAGE, duration=3.0), 4.5, 3.0, clip_id=905,
                  overlay_type="filter", filter_name="sepia")
    foto = Clip(refs["foto.png"], 1.0, 3.0, clip_id=906, scale=0.5, scale_x=0.5, scale_y=0.5)
    musica = Clip(refs["musica.m4a"], 0.0, 6.0, clip_id=907, gain_db=-3.5)
    projeto = Project(tracks=(
        Track(TrackKind.ADDITIONAL, clips=(texto, filtro), name="Adicionais 1"),
        Track(TrackKind.VIDEO, clips=(foto,), name="Vídeo 2"),
        Track(TrackKind.VIDEO, clips=(a, transicao, b), name="Vídeo 1"),
        Track(TrackKind.AUDIO, clips=(musica,), name="Trilha da câmera"),
    ), width=1280, height=720, fps=30.0)

    import json as _json
    bruto = _json.loads((RAIZ / "tests" / "fixtures" / "youtube_dash.json").read_text(encoding="utf-8"))
    midia = MediaInfo(url="https://exemplo/video", title=str(bruto.get("title") or "video"),
                      matrix=build_matrix(bruto.get("formats") or []), duration=bruto.get("duration"),
                      uploader=str(bruto.get("uploader") or ""))
    return {"pasta": pasta, "projeto": projeto, "pool": list(refs.values()), "probed": {l.path: l for l in locais.values()},
            "midia": midia, "arquivos": [pasta / "clipe.mp4", pasta / "musica.m4a"]}


def _tarefas():
    from videomanager.application.events import Progress
    from videomanager.application.jobs.models import Job, JobKind, JobStatus
    from videomanager.domain.i18n import Text
    return [
        Job("https://exemplo/a", "Vídeo A", Text("DESC_DOWNLOAD_AUDIO_BEST"), status=JobStatus.FAILED,
            error=Text("PROBE_GEO"), warnings=(Text("DESC_NO_SUBTITLES"),)),
        Job("https://exemplo/b", "Vídeo B", Text("DESC_UP_TO", height=720), status=JobStatus.RUNNING,
            progress=Progress(phase=Text("PHASE_MERGING"), percent=40.0)),
        Job("/x/c.mp4", "c.mp4", Text("DESC_AUDIO_ONLY"), kind=JobKind.CONVERT, status=JobStatus.DONE),
        Job("/x/d.mp4", "d.mp4", Text("DESC_DIRECT_COPY"), kind=JobKind.TRIM, status=JobStatus.PENDING),
    ]


# ---------------------------------------------------------------------------
# Cenas
# ---------------------------------------------------------------------------

def _aba(janela, indice: int) -> None:
    janela._tabs.setCurrentIndex(indice)


def _editor(app, janela, r, selecionar: int | None = 901) -> None:
    _aba(janela, 2)
    editor = janela._edit
    editor.install_project(r["projeto"], None, r["pool"], dict(r["probed"]))
    _processar(app, 250)
    if selecionar is not None:
        editor._timeline.select(selecionar)
        _processar(app, 150)


def _convert(app, janela, r, video: bool = False) -> None:
    _aba(janela, 1)
    painel = janela._convert
    painel.add_files(list(r["arquivos"]))
    _esperar(app, lambda: len(painel._media) == len(r["arquivos"]), 30)
    if video:
        painel._to_video.setChecked(True)
    _processar(app, 120)


CENAS = {
    "download_vazio": lambda app, j, r: _aba(j, 0),
    "download_video": lambda app, j, r: (_aba(j, 0), j._on_probed(r["midia"])),
    "download_audio": lambda app, j, r: (_aba(j, 0), j._on_probed(r["midia"]), j._quality._radio_audio.setChecked(True)),
    "fila": lambda app, j, r: (_aba(j, 0), [j._queue.job_added.emit(t) for t in _tarefas()]),
    "convert_vazio": lambda app, j, r: _aba(j, 1),
    "convert_audio": lambda app, j, r: _convert(app, j, r),
    "convert_video": lambda app, j, r: _convert(app, j, r, video=True),
    "editor_vazio": lambda app, j, r: _aba(j, 2),
    "editor_video": lambda app, j, r: _editor(app, j, r, 901),
    "editor_audio": lambda app, j, r: _editor(app, j, r, 907),
    "editor_texto": lambda app, j, r: _editor(app, j, r, 904),
    "editor_filtro": lambda app, j, r: _editor(app, j, r, 905),
    "editor_transicao": lambda app, j, r: _editor(app, j, r, 903),
    "editor_propriedades": lambda app, j, r: (_editor(app, j, r, 906), j._edit._open_properties_tab(906)),
    "tela_cheia": lambda app, j, r: (_editor(app, j, r, 901), j._edit._toggle_fullscreen()),
}


# ---------------------------------------------------------------------------
# Retrato
# ---------------------------------------------------------------------------

def _caminho(widget, raiz) -> str:
    partes = []
    atual = widget
    while atual is not None and atual is not raiz:
        pai = atual.parentWidget()
        if atual.objectName():
            partes.append(f"{type(atual).__name__}:{atual.objectName()}")
        else:
            irmaos = [c for c in (pai.children() if pai is not None else []) if type(c) is type(atual)]
            partes.append(f"{type(atual).__name__}{irmaos.index(atual) if atual in irmaos else '?'}")
        atual = pai
    return "/".join(reversed(partes)) or type(raiz).__name__


def _acoes(prefixo: str, acoes, saida: dict) -> None:
    """Texto, dica e atalho de cada ação.

    Sem ``QAction.menu()``: no PySide6 ele passa a posse do submenu ao objeto
    Python devolvido, e o menu da janela era apagado quando esse objeto saía de
    cena. Os menus entram no retrato como widgets filhos da barra.
    """
    from PySide6.QtGui import QKeySequence
    for i, acao in enumerate(acoes):
        if acao.isSeparator():
            continue
        saida[f"{prefixo}[{i}]"] = [acao.text(),
                                    acao.toolTip() if acao.toolTip() != acao.text().replace("&", "") else ""]
        # O nome da tecla ("Exit", "Space") é texto do próprio Qt, traduzido por
        # ele: entra na comparação, mas não na busca por texto sem catálogo.
        atalho = acao.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        if atalho:
            saida[f"{prefixo}[{i}].atalho"] = atalho


def _textos_do_widget(w) -> list[tuple[str, object]]:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox, QDialogButtonBox, QDoubleSpinBox,
                                   QGroupBox, QLabel, QLineEdit, QListWidget, QMenu, QPlainTextEdit, QSpinBox,
                                   QStatusBar, QTableView, QTabWidget, QTextEdit)
    saida: list[tuple[str, object]] = []
    if isinstance(w, QLabel):
        saida.append(("texto", w.text()))
    if isinstance(w, QAbstractButton):
        # OK e Cancelar de uma caixa de botões padrão são texto do próprio Qt,
        # traduzido por ele: entram na comparação com outro nome.
        caixa = w.parentWidget()
        padrao = (isinstance(caixa, QDialogButtonBox)
                  and caixa.standardButton(w) != QDialogButtonBox.StandardButton.NoButton)
        saida.append(("texto_qt" if padrao else "texto", w.text()))
    if isinstance(w, QGroupBox):
        saida.append(("titulo", w.title()))
    if isinstance(w, QLineEdit) and not isinstance(w.parentWidget(), QAbstractSpinBox):
        saida.append(("placeholder", w.placeholderText()))
        saida.append(("texto", w.text()))
    if isinstance(w, (QTextEdit, QPlainTextEdit)):
        saida.append(("placeholder", w.placeholderText()))
    if isinstance(w, QComboBox):
        saida.append(("itens", [w.itemText(i) for i in range(w.count())]))
        saida.append(("atual", w.currentIndex()))
    if isinstance(w, QTabWidget):
        saida.append(("abas", [[w.tabText(i), w.tabToolTip(i)] for i in range(w.count())]))
    if isinstance(w, QAbstractSpinBox):
        saida.append(("exibido", w.text()))
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        saida.append(("sufixo", [w.prefix(), w.suffix(), w.specialValueText()]))
    if isinstance(w, QListWidget):
        saida.append(("lista", [[w.item(i).text(), w.item(i).toolTip()] for i in range(w.count())]))
    if isinstance(w, QTableView) and w.model() is not None:
        modelo = w.model()
        saida.append(("cabecalho", [modelo.headerData(c, Qt.Orientation.Horizontal) for c in range(modelo.columnCount())]))
        for linha in range(modelo.rowCount()):
            for coluna in range(modelo.columnCount()):
                indice = modelo.index(linha, coluna)
                valores = [modelo.data(indice, papel) for papel in (Qt.ItemDataRole.DisplayRole,
                                                                     Qt.ItemDataRole.ToolTipRole)]
                saida.append((f"celula{linha},{coluna}", [None if v is None else str(v) for v in valores]))
    if isinstance(w, QStatusBar):
        saida.append(("mensagem", w.currentMessage()))
    if isinstance(w, QMenu):
        saida.append(("titulo", w.title()))
    saida.append(("dica", w.toolTip()))
    if w.statusTip():
        saida.append(("status", w.statusTip()))
    if w.isWindow():
        saida.append(("janela", w.windowTitle()))
    return [(prop, valor) for prop, valor in saida if valor not in ("", [], None)]


def _pintados(raiz) -> dict[str, list[str]]:
    """Texto desenhado à mão, que não mora em widget nenhum.

    A linha do tempo pinta nomes de trilha, rótulos e marcas dos blocos; a fila
    e as listas vazias pintam o convite. Só se enxerga pelo ``drawText`` que o
    ``paintEvent`` escrito em Python chama.
    """
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QWidget

    def pinta_a_mao(w) -> bool:
        return any("paintEvent" in vars(c) for c in type(w).__mro__ if c.__module__.startswith("videomanager"))

    original = QPainter.drawText
    vistos: list[str] = []

    def gravar(painter, *args):
        vistos.extend(a for a in args if isinstance(a, str))
        return original(painter, *args)

    saida = {}
    QPainter.drawText = gravar
    try:
        for w in [raiz, *raiz.findChildren(QWidget)]:
            if w.isVisible() and pinta_a_mao(w):
                vistos.clear()
                w.grab()
                if vistos:
                    saida[_caminho(w, raiz)] = list(vistos)
    finally:
        QPainter.drawText = original
    return saida


def _retrato(janela, extras=()) -> dict:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu, QMenuBar, QWidget
    textos: dict[str, object] = {}
    geometria: dict[str, list[int]] = {}
    import shiboken6
    for raiz in (janela, *[e for e in extras if e is not None]):
        nome = type(raiz).__name__
        # Menus montados na hora de abrir ficam na lista de filhos até o Qt
        # apagá-los de vez; o objeto Python sobrevive ao C++. O menu de
        # transbordo da barra (sem título) é interno do Qt e só aparece se ela
        # não couber.
        for w in [raiz, *(c for c in raiz.findChildren(QWidget) if shiboken6.isValid(c)
                          and not (isinstance(c, QMenu) and not c.title()
                                   and isinstance(c.parentWidget(), QMenuBar)))]:
            caminho = f"{nome}/{_caminho(w, raiz)}"
            for prop, valor in _textos_do_widget(w):
                textos[f"{caminho}.{prop}"] = valor
            _acoes(f"{caminho}.acao", w.actions(), textos)
            if w.isVisible():
                p = w.mapTo(raiz, QPoint(0, 0))
                geometria[caminho] = [p.x(), p.y(), w.width(), w.height()]
        for caminho, pintado in _pintados(raiz).items():
            textos[f"{nome}/{caminho}.pintado"] = pintado
    return {"textos": textos, "geometria": geometria}


def _diferencas(a: dict, b: dict, secoes=("textos", "geometria")) -> list[str]:
    saida = []
    for secao in secoes:
        for chave in sorted(set(a[secao]) | set(b[secao])):
            va, vb = a[secao].get(chave, "∅"), b[secao].get(chave, "∅")
            if va != vb:
                saida.append(f"{secao}: {chave}\n      ao vivo: {va}\n      do zero: {vb}")
    return saida


def _suspeitos(retrato: dict, suspeito, ignorar: tuple[str, ...]) -> list[str]:
    achados = []

    def varrer(chave, valor):
        if isinstance(valor, (list, tuple)):
            for item in valor:
                varrer(chave, item)
        elif isinstance(valor, str):
            # Ícone ou símbolo na ponta ("🔊 0,0 dB", "🔤 Olá") não faz de um
            # número uma frase, nem de um dado um texto.
            bruto = valor.replace("&", "").strip()
            limpo = re.sub(rf"^[^\w{ABRE}]+|[^\w{FECHA})]+$", "", bruto)
            if any(_DADO.match(x) or _DADOS_DA_CENA.match(x) for x in (bruto, limpo)):
                return
            if suspeito(limpo):
                achados.append(f"{chave}: {limpo[:110]!r}")

    for chave, valor in retrato["textos"].items():
        if chave.endswith(ignorar) or any(lista in chave for lista in _LISTAS_DE_DADO):
            continue
        varrer(chave, valor)
    return sorted(set(achados))


def _sem_marca(retrato: dict) -> list[str]:
    """Texto com letras e sem as marcas num retrato em pseudoidioma."""
    return _suspeitos(
        retrato,
        lambda limpo: ABRE not in limpo and re.search(r"[^\W\d_]{2,}", limpo),
        (".atual", ".janela", ".atalho", ".texto_qt"),
    )


def _textos(valor):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, (tuple, dict)):
        for item in (valor.values() if isinstance(valor, dict) else valor):
            yield from _textos(item)


@functools.cache
def _portugues() -> re.Pattern:
    """Acento, palavra curta do português, ou palavra que só o português dos catálogos usa.

    O vocabulário sai dos catálogos, e não de uma lista escrita à mão: uma
    lista não reconhecia "Desfazer" nem o plural de "trilha". Fotografado na
    primeira chamada, com as tabelas de verdade.
    """
    from videomanager.domain import i18n
    from videomanager.presentation.qt import i18n as idioma

    def palavras(textos):
        return {p.lower() for texto in textos for p in re.findall(r"[^\W\d_]{4,}", re.sub(r"\{[^}]*\}", "", texto))}

    so_pt = (palavras([*_textos(idioma._TABLES[i18n.PORTUGUESE]), *(pt for pt, _ in i18n._catalog.values())])
             - palavras([*_textos(idioma._TABLES[i18n.ENGLISH]), *(en for _, en in i18n._catalog.values())]))
    return re.compile(rf"[ãõçáéíóúâêôà]|\b(de|com|sem|uma?|os|ao|{'|'.join(sorted(so_pt))})\b", re.IGNORECASE)


# Dado das cenas no meio de um texto maior: nome de arquivo ("clipe.mp4" numa
# dica), conteúdo digitado ("Olá · 3.00 s"), nome de tarefa e de trilha não se
# traduzem.
_DADO_EMBUTIDO = re.compile(
    r"\S*\.(mp4|mkv|webm|mov|m4a|mp3|png|jpg|vmp|json|wav|flac|ogg|opus|gif|avi)\b|\bOlá\b|\bVídeo [AB]\b"
    r"|\bTrilha da câmera\b",
    re.IGNORECASE,
)


def _em_portugues(retrato: dict) -> list[str]:
    """Texto com cara de português num retrato em inglês, títulos e teclas inclusive."""
    return _suspeitos(retrato, lambda limpo: _portugues().search(_DADO_EMBUTIDO.sub("", limpo)), (".atual",))


_DETECTORES = {"pseudo": _sem_marca, "ingles": _em_portugues}


# ---------------------------------------------------------------------------
# Troca medida
# ---------------------------------------------------------------------------

def _estado(janela) -> dict:
    editor = janela._edit
    return {"desfazer": len(editor._session.history), "refazer": len(editor._session.future),
            "alterado": editor.has_unsaved_changes, "workers": editor._runner.active + editor._background.active,
            "projeto": id(editor._project), "pedido_de_quadro": editor._frame_token,
            "reproducao": editor._play_token, "aba_adicionais": editor._extras_tabs.currentIndex(),
            "selecionado": editor._timeline.selected}


def _trocar(app, codigo: str, janela=None) -> dict:
    from PySide6.QtCore import QEvent, QObject

    from videomanager.presentation.qt.i18n import apply_language

    class Pinturas(QObject):
        def __init__(self):
            super().__init__()
            self.durante = 0

        def eventFilter(self, _obj, evento):  # noqa: N802
            if evento.type() == QEvent.Type.Paint:
                self.durante += 1
            return False

    contador = Pinturas()
    app.installEventFilter(contador)
    # O estado é lido colado na troca, sem processar eventos no meio: um
    # worker agendado antes dela e que começa depois não é efeito dela.
    antes = _estado(janela) if janela is not None else {}
    inicio = time.perf_counter()
    apply_language(codigo)
    fim_troca = time.perf_counter()
    depois = _estado(janela) if janela is not None else {}
    app.removeEventFilter(contador)
    app.processEvents()
    fim_assentar = time.perf_counter()
    return {"troca_ms": round((fim_troca - inicio) * 1000, 2), "ate_pintar_ms": round((fim_assentar - inicio) * 1000, 2),
            "pinturas_durante": contador.durante,
            "efeitos": {k: (antes[k], depois[k]) for k in antes if antes[k] != depois[k]}}


def rodar_cena(app, nome: str, r: dict, modo: str) -> dict:
    from videomanager.domain import i18n

    entrar = CENAS[nome]
    extras = (lambda j: (j._edit._fullscreen,)) if nome == "tela_cheia" else (lambda j: ())
    a = _janela(app)
    entrar(app, a, r)
    _processar(app, 200)
    pt_inicio = _retrato(a, extras(a))
    ida = _trocar(app, i18n.ENGLISH, a)
    _processar(app, 200)
    en_vivo = _retrato(a, extras(a))

    b = _janela(app)
    entrar(app, b, r)
    _processar(app, 200)
    en_zero = _retrato(b, extras(b))

    volta = _trocar(app, i18n.PORTUGUESE, a)
    _processar(app, 200)
    pt_volta_a = _retrato(a, extras(a))
    pt_volta_b = _retrato(b, extras(b))
    _fechar(app, a)
    _fechar(app, b)
    efeitos = {**ida["efeitos"], **{f"volta.{k}": v for k, v in volta["efeitos"].items()}}
    # Janelas diferentes só se comparam por geometria quando os textos não
    # mudam de largura (identidade): com texto de outro tamanho, a divisão das
    # colunas depende da história de cada janela, e não é defeito divergir. A
    # ida e volta na mesma janela, essa sim, tem de devolver tudo.
    entre_janelas = ("textos", "geometria") if modo == "identidade" else ("textos",)
    detector = _DETECTORES.get(modo)
    return {
        "ida": ida, "volta": volta, "efeitos": efeitos,
        "ingles_vivo_x_zero": _diferencas(en_vivo, en_zero, entre_janelas),
        "portugues_volta_x_inicio": _diferencas(pt_volta_a, pt_inicio),
        "portugues_de_b_x_inicio": _diferencas(pt_volta_b, pt_inicio, entre_janelas),
        "sem_traducao": detector(en_vivo) + [f"(do zero) {x}" for x in detector(en_zero)] if detector else [],
    }


def _sob_demanda(app, r) -> dict:
    """Retrato do que só se monta ao abrir: diálogos e menus de contexto.

    Nascem no idioma do momento e são modais — a troca de idioma nunca os
    pega abertos —, então não há troca a conferir, só o texto: fora do
    catálogo (pseudoidioma) ou com cara de português (inglês).
    """
    from PySide6.QtWidgets import QMenu

    from videomanager.domain.formats import PlaylistEntry, PlaylistInfo
    from videomanager.presentation.qt.export_dialog import ExportDialog
    from videomanager.presentation.qt.playlist_dialog import PlaylistDialog
    from videomanager.presentation.qt.settings_dialog import SettingsDialog

    janela = _janela(app)
    _editor(app, janela, r, 901)
    editor = janela._edit
    lista = editor._media_list
    itens = tuple(PlaylistEntry(f"https://exemplo/{i}", f"Item {i}", i) for i in range(1, 4))
    raizes = {
        "configuracoes": SettingsDialog(janela._settings, janela, runtime=janela._runtime),
        "exportacao": ExportDialog(project=editor._project, settings=editor._settings, pool=editor._pool,
                                   probed=editor._probed, parent=editor, processing=editor._processing,
                                   runtime=editor._runtime),
        "playlist": PlaylistDialog(PlaylistInfo("https://exemplo/lista", "Playlist X", itens), parent=janela),
        "menu_do_bloco": editor.build_menu("clip", 2, 901),
        "menu_do_texto": editor.build_menu("clip", 0, 904),
        "menu_da_trilha": editor.build_menu("track", 3, -1),
        "menu_do_acervo": editor.build_media_menu(lista.visualItemRect(lista.item(0)).center()),
    }
    for raiz in raizes.values():
        if not isinstance(raiz, QMenu):
            raiz.show()
    _processar(app, 200)
    textos = {}
    for nome, raiz in raizes.items():
        textos.update({f"{nome}:{chave}": valor for chave, valor in _retrato(raiz)["textos"].items()})
        raiz.close()
        raiz.deleteLater()
    _fechar(app, janela)
    return {"textos": textos}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modo", choices=("pseudo", "identidade", "ingles"), default="pseudo",
                        help="pseudo: textos marcados, confere texto e o que ficou sem catálogo; "
                             "identidade: inglês igual ao português, confere a geometria da própria troca; "
                             "ingles: a tradução de verdade, e o que ficou com cara de português")
    parser.add_argument("--cena", action="append", choices=sorted(CENAS), help="só estas cenas")
    parser.add_argument("--limite", type=int, default=12, help="diferenças mostradas por grupo")
    parser.add_argument("--json", type=Path, help="grava o resultado completo")
    args = parser.parse_args()

    perfil = Path(tempfile.mkdtemp(prefix="vm-idioma-"))
    for chave in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        os.environ[chave] = str(perfil / chave)
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    from videomanager.app import build_app
    app, primeira = build_app([], audio_enabled=False)
    primeira.close()
    primeira.deleteLater()
    _instalar(args.modo)
    recursos = _recursos(perfil)

    resultado = {}
    problemas = 0
    for nome in args.cena or list(CENAS):
        cena = rodar_cena(app, nome, recursos, args.modo)
        resultado[nome] = cena
        grupos = [g for g in ("ingles_vivo_x_zero", "portugues_volta_x_inicio", "portugues_de_b_x_inicio")
                  if cena[g]]
        sem = cena["sem_traducao"]
        problemas += sum(len(cena[g]) for g in grupos) + len(sem) + len(cena["efeitos"])
        problemas += cena["ida"]["pinturas_durante"] + cena["volta"]["pinturas_durante"]
        print(f"== {nome}: troca {cena['ida']['troca_ms']} ms (até pintar {cena['ida']['ate_pintar_ms']} ms), "
              f"volta {cena['volta']['troca_ms']} ms, pinturas durante {cena['ida']['pinturas_durante']}"
              f"/{cena['volta']['pinturas_durante']}, efeitos {cena['efeitos'] or 'nenhum'}")
        for grupo in grupos:
            print(f"   {grupo}: {len(cena[grupo])}")
            for linha in cena[grupo][:args.limite]:
                print(f"      {linha}")
        if sem:
            print(f"   sem tradução: {len(sem)}")
            for linha in sem[:args.limite]:
                print(f"      {linha}")
    detector = _DETECTORES.get(args.modo)
    if detector is not None and not args.cena:
        from videomanager.domain import i18n
        from videomanager.presentation.qt.i18n import apply_language
        apply_language(i18n.ENGLISH)
        sob_demanda = detector(_sob_demanda(app, recursos))
        apply_language(i18n.PORTUGUESE)
        problemas += len(sob_demanda)
        resultado["sob_demanda"] = sob_demanda
        print(f"== diálogos e menus: {len(sob_demanda)} texto(s) sem tradução")
        for linha in sob_demanda[:args.limite]:
            print(f"      {linha}")
    tempos = [c["ida"]["troca_ms"] for n, c in resultado.items() if n in CENAS]
    tempos += [c["volta"]["troca_ms"] for n, c in resultado.items() if n in CENAS]
    print(f"\ntroca: mediana {statistics.median(tempos):.1f} ms, máximo {max(tempos):.1f} ms")
    print(f"{problemas} problema(s).")
    if args.json:
        args.json.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
