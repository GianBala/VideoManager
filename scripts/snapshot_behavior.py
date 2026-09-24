"""Retrato do comportamento observável, para comparar duas versões do código.

    PYTHONPATH=/tmp/vm-base/src python scripts/snapshot_behavior.py > /tmp/vm-antes.json
    PYTHONPATH=src python scripts/snapshot_behavior.py > /tmp/vm-depois.json
    python scripts/snapshot_behavior.py --comparar /tmp/vm-antes.json /tmp/vm-depois.json

O mesmo script roda sobre as duas árvores, e a comparação lista tudo o que mudou.
Toda diferença precisa ser uma mudança pretendida; as outras são regressão. Foi
comparando retratos assim que apareceram as regressões que nenhum teste pegou:
a prévia 32 px mais baixa, as colunas do editor presas no mínimo, a taxa presa
ao reabrir um projeto, a tela da janela de exportação dizendo "Automática".

Seções (cada uma num processo próprio, sem estado vazando entre elas):

- ``comandos``: todos os comandos do compositor (quadro, reprodução, áudio,
  cache da agulha, camadas, exportação, GIF, interpolação) para uma bateria de
  projetos. Qualquer mudança no grafo aparece aqui.
- ``interface``: geometria de cada widget das três abas em quatro larguras,
  com a janela aberta no tamanho padrão e só depois redimensionada — como o
  aplicativo abre de verdade.
- ``atalhos``: que ação cada tecla dispara, com o foco em quatro lugares.
- ``exportacao``: a tarefa criada pela janela de exportação (alvo, descrição,
  avisos) e o estado de todos os campos dela, em dezenas de combinações.
- ``persistencia``: abrir sem marcar alteração, salvar sem editar gravando o
  mesmo arquivo, desfazer, reabrir projetos em várias taxas, escolha de tela
  vinda da janela de exportação.
- ``layout``: controles da barra de transporte sumidos, cortados ou sobrepostos
  em todas as larguras, e o divisor de cima depois de estreitar e alargar.
  Com ``QT_SCALE_FACTOR=1.25`` ou ``1.5`` confere as escalas de tela.

Um nome privado que este script usa e que a mudança renomeia precisa ganhar
alternativa aqui na mesma mudança — senão a seção falha na árvore antiga e a
comparação não diz nada.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SECOES = ("comandos", "interface", "atalhos", "exportacao", "persistencia", "layout")
TAMANHOS = ((1920, 1080), (1680, 1050), (1366, 768), (1280, 720))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _normal(valor):
    """JSON estável: tuplas viram listas, floats arredondados, caminhos pelo nome."""
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return {f.name: _normal(getattr(valor, f.name)) for f in dataclasses.fields(valor)}
    if isinstance(valor, Path):
        return re.sub(r"\(\d+\)", "(n)", valor.name)
    if isinstance(valor, dict):
        return {str(k): _normal(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_normal(v) for v in valor]
    if isinstance(valor, float):
        return round(valor, 6)
    if isinstance(valor, (int, str, bool)) or valor is None:
        return valor
    return re.sub(r" at 0x[0-9a-f]+", "", repr(valor))


def _app():
    """Aplicativo com perfil descartável e sem diálogos modais."""
    perfil = Path(tempfile.mkdtemp(prefix="vm-retrato-"))
    for chave in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        os.environ[chave] = str(perfil / chave)
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    from videomanager.app import build_app
    app, janela = build_app([], audio_enabled=False)
    return app, janela, perfil


def _processar(app, vezes: int = 10) -> None:
    for _ in range(vezes):
        app.processEvents()


def _esperar(app, condicao, prazo: float = 20.0) -> bool:
    import time
    fim = time.monotonic() + prazo
    while not condicao() and time.monotonic() < fim:
        app.processEvents()
        time.sleep(0.01)
    return condicao()


def _geometria(janela, dono) -> dict:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QWidget
    saida = {}
    for nome, obj in vars(dono).items():
        if isinstance(obj, QWidget) and obj is not janela and obj.isVisible():
            p = obj.mapTo(janela, QPoint(0, 0))
            saida[nome] = [p.x(), p.y(), obj.width(), obj.height()]
    return saida


def _midia(pasta: Path, tools) -> dict[str, Path]:
    """Vídeos curtos em taxas diferentes e uma música, gerados uma vez."""
    from videomanager.infrastructure.system.binaries import subprocess_kwargs
    receitas = {
        "r23976.mp4": ("testsrc2=s=640x360:r=24000/1001:d=2", True),
        "r25.mp4": ("testsrc2=s=640x360:r=25:d=2", True),
        "r2997.mp4": ("testsrc2=s=640x360:r=30000/1001:d=2", True),
        "r30.mp4": ("testsrc2=s=640x360:r=30:d=2", True),
        "r60.mp4": ("testsrc2=s=1280x720:r=60:d=2", True),
        "m10.m4a": ("sine=d=10", False),
    }
    for nome, (fonte, video) in receitas.items():
        destino = pasta / nome
        if destino.exists():
            continue
        entrada = ["-f", "lavfi", "-i", fonte]
        if video:
            entrada += ["-f", "lavfi", "-i", "sine=d=2", "-shortest", "-c:v", "libx264",
                        "-preset", "veryfast", "-g", "15", "-c:a", "aac"]
        subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *entrada, str(destino)],
                       check=True, **subprocess_kwargs())
    return {nome: pasta / nome for nome in receitas}


# ---------------------------------------------------------------------------
# Seções
# ---------------------------------------------------------------------------

def secao_comandos(_midia_dir: Path) -> dict:
    from dataclasses import replace
    from videomanager.application.capabilities import FFmpegTools
    from videomanager.application.media.interaction import interaction_plan
    from videomanager.domain.keyframe import Keyframe
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
    from videomanager.infrastructure.ffmpeg import composer

    tools = FFmpegTools(Path("/x/ffmpeg"), Path("/x/ffprobe"), "retrato")
    V = MediaRef(Path("/nao/existe/video.mp4"), MediaKind.VIDEO, duration=12.0, width=1920, height=1080,
                 fps=30.0, has_audio=True, channels=2)
    V2 = MediaRef(Path("/nao/existe/outro.mp4"), MediaKind.VIDEO, duration=8.0, width=1280, height=720,
                  fps=24.0, has_audio=True, channels=1)
    BIG = MediaRef(Path("/nao/existe/4k.mp4"), MediaKind.VIDEO, duration=10.0, width=3840, height=2160,
                   fps=24.0, has_audio=False)
    IMG = MediaRef(Path("/nao/existe/foto.png"), MediaKind.IMAGE, width=800, height=600)
    AUD = MediaRef(Path("/nao/existe/musica.m4a"), MediaKind.AUDIO, duration=20.0, has_audio=True, channels=2)
    TXT = MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=5.0)
    FIL = MediaRef(Path("Filtro_pb"), MediaKind.IMAGE, duration=5.0)
    TRN = MediaRef(Path("Transição_fade"), MediaKind.IMAGE, duration=1.0)
    anim = (Keyframe(0.0, x=0.3, y=0.4, scale_x=0.5, scale_y=0.5, opacity=0.0, easing="ease_out"),
            Keyframe(1.0, x=0.6, y=0.5, scale_x=0.8, scale_y=0.8, rotation=30, opacity=1.0))
    a = Clip(V, 0.0, 5.0, clip_id=1)
    b = Clip(V2, 5.0, 4.0, in_point=1.0, clip_id=2)
    tr = Clip(TRN, 4.5, 1.0, overlay_type="transition", transition_name="dissolve",
              transition_left_id=1, transition_right_id=2, clip_id=3)
    foto = Clip(IMG, 1.0, 4.0, x=0.7, y=0.3, scale=0.6, scale_x=0.6, scale_y=0.6, rotation=15,
                opacity=0.8, keyframes=anim, clip_id=4)
    texto = Clip(TXT, 2.0, 5.0, overlay_type="text", text_content="Olá", keyframes=anim, clip_id=5)
    filtro = Clip(FIL, 3.0, 4.0, overlay_type="filter", filter_name="sepia", clip_id=6)
    chroma = Clip(V2, 0.5, 3.0, chromakey_enabled=True, x=0.4, clip_id=7)
    rapido = Clip(V, 9.0, 2.0, in_point=6.0, speed=2.0, gain_db=-3.0, clip_id=8)
    musica = Clip(AUD, 0.0, 12.0, gain_db=2.0, clip_id=9)
    separado = Clip(V, 0.0, 5.0, audio_only=True, clip_id=10)
    grande = Clip(BIG, 0.0, 6.0, x=0.45, clip_id=11)
    zoom = Keyframe(0.0, scale_x=1.0, scale_y=1.0), Keyframe(4.0, scale_x=1.6, scale_y=1.6)
    assets = {5: Path("/nao/existe/texto.png")}
    video = lambda *clips, tid: Track(TrackKind.VIDEO, clips=clips, track_id=tid)  # noqa: E731
    projetos = {
        "simples": Project(tracks=(video(a, tid=1),), width=1920, height=1080, fps=30.0),
        "montagem": Project(tracks=(
            Track(TrackKind.ADDITIONAL, clips=(texto, filtro), track_id=2), video(foto, tid=3),
            video(chroma, tid=4), video(a, tr, b, rapido, tid=5),
            Track(TrackKind.AUDIO, clips=(musica,), track_id=6),
            Track(TrackKind.AUDIO, clips=(separado,), track_id=7, muted=True),
        ), width=1920, height=1080, fps=30.0),
        "transicao_adicionais": Project(tracks=(
            Track(TrackKind.ADDITIONAL, clips=(texto,), track_id=8),
            video(a, replace(tr, transition_affects_additionals=True), b, tid=9),
        ), width=1280, height=720, fps=24.0),
        "4k_deslocado": Project(tracks=(video(grande, tid=10),), width=1920, height=1080, fps=60.0),
        "4k_ampliado": Project(tracks=(video(replace(grande, scale=2.0, scale_x=2.0, scale_y=2.0), tid=11),),
                               width=1920, height=1080, fps=60.0),
        "4k_zoom_animado": Project(tracks=(video(replace(grande, keyframes=zoom), tid=12),),
                                   width=1920, height=1080, fps=60.0),
        "4k_reduzido": Project(tracks=(video(replace(grande, scale=0.5, scale_x=0.5, scale_y=0.5), tid=13),),
                               width=1920, height=1080, fps=60.0),
        "menor_ampliado": Project(tracks=(video(replace(b, start=0.0, scale=2.0, scale_x=2.0, scale_y=2.0),
                                                tid=14),), width=1920, height=1080, fps=60.0),
        "musica_alem_do_video": Project(tracks=(video(replace(a, duration=3.0), tid=15),
                                                Track(TrackKind.AUDIO, clips=(musica,), track_id=16)),
                                        width=1280, height=720, fps=30.0),
    }

    def seguro(funcao, *args, **kwargs):
        try:
            return funcao(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — a recusa também é comportamento
            return f"ERRO {type(exc).__name__}: {exc}"

    saida = {}
    for nome, projeto in projetos.items():
        cmds = {}
        for t in (0.0, 1.5, 4.8, 5.0, 8.99, 11.0, projeto.duration):
            cmds[f"quadro@{t}"] = seguro(composer.frame_command, projeto, t, (640, 360), tools, text_assets=assets)
            cmds[f"quadro_png@{t}"] = seguro(composer.frame_command, projeto, t, (640, 360), tools,
                                             text_assets=assets, transparent=True, png=True)
            cmds[f"reproducao@{t}"] = seguro(composer.playback_command, projeto, t, (960, 540), tools,
                                             fps=30.0, text_assets=assets)
            cmds[f"audio@{t}"] = seguro(composer.audio_command, projeto, t, tools, text_assets=assets)
            cmds[f"audio_loop@{t}"] = seguro(composer.audio_command, projeto, t, tools, text_assets=assets,
                                             until=projeto.export_duration)
        cmds["agulha"] = seguro(composer.scrub_command, projeto, 0.0, 6.0, (640, 360), tools, fps=30.0,
                                text_assets=assets)
        for clip in projeto.clips:
            for t in (1.5, 3.2):
                plano = interaction_plan(projeto, clip.clip_id, t)
                if plano is not None:
                    cmds[f"camadas{clip.clip_id}@{t}"] = seguro(composer.interaction_commands, plano, (640, 360),
                                                                tools, text_assets=assets)
        destino = Path("/tmp/retrato")
        cmds["exportar_mp4"] = seguro(composer.export_args, projeto, destino.with_suffix(".mp4"), tools,
                                      text_assets=assets)
        cmds["exportar_interpolado"] = seguro(composer.export_args, projeto, destino.with_suffix(".mp4"), tools,
                                              interpolate=True, text_assets=assets)
        cmds["exportar_audio"] = seguro(composer.export_args, projeto, destino.with_suffix(".mp3"), tools,
                                        audio_only=True, audio_codec="mp3", text_assets=assets)
        cmds["exportar_gif"] = seguro(composer.export_args, projeto, destino.with_suffix(".gif"), tools,
                                      container="gif", text_assets=assets)
        saida[nome] = cmds
    return saida


def secao_interface(midia_dir: Path) -> dict:
    from PySide6.QtGui import QColor, QImage
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, new_project
    app, janela, perfil = _app()
    janela.show()
    _processar(app)                      # abre no tamanho padrão, como o aplicativo
    editor = janela._edit
    imagem = QImage(320, 180, QImage.Format.Format_RGBA8888)
    imagem.fill(QColor("lime"))
    caminho = perfil / "quadro.png"
    imagem.save(str(caminho))
    ref = MediaRef(caminho, MediaKind.IMAGE, width=320, height=180)
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(ref, 0, 5), Clip(ref, 5, 5))),),
                      width=640, height=360)
    saida = {}
    for largura, altura in TAMANHOS:
        janela.resize(largura, altura)
        _processar(app)
        for indice, nome in ((0, "download"), (1, "convert")):
            janela._tabs.setCurrentIndex(indice)
            _processar(app)
            medidas = _geometria(janela, janela)
            for dono, obj in list(vars(janela).items()):
                if hasattr(obj, "isVisible") and obj is not editor and obj.isVisible() and vars(obj):
                    medidas.update({f"{dono}.{k}": v for k, v in _geometria(janela, obj).items()})
            saida[f"{nome} {largura}x{altura}"] = medidas
        janela._tabs.setCurrentIndex(2)
        _processar(app)
        vazio = _geometria(janela, editor)
        vazio["divisores"] = [editor._top_splitter.sizes(), editor._split_view.sizes()]
        saida[f"editor vazio {largura}x{altura}"] = vazio
        editor._apply(projeto)
        _processar(app, 20)
        cheio = _geometria(janela, editor)
        cheio["divisores"] = [editor._top_splitter.sizes(), editor._split_view.sizes()]
        cheio["tamanho pedido à prévia"] = list(editor._preview_size())
        saida[f"editor com projeto {largura}x{altura}"] = cheio
        editor.install_project(new_project(), None, [], {})
        _processar(app)
    editor.shutdown()
    return saida


def secao_atalhos(_midia_dir: Path) -> dict:
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit
    from videomanager.presentation.qt.panels.edit_panel import EditPanel
    chamadas: list[str] = []

    def registrar(nome):
        def chamada(self, *args, **kwargs):
            chamadas.append(nome + (repr(args) if args else ""))
            return True
        return chamada

    for nome in ("_toggle_play", "_split_here", "_trim_to_cursor", "_delete_selected", "_copy_clip",
                 "_paste_clip", "_step_frame", "_undo_edit", "_redo_edit", "_toggle_fullscreen",
                 "save_project", "save_project_as", "open_project", "new_project", "_open_export_dialog",
                 "_toggle_collapsed"):
        if hasattr(EditPanel, nome):
            setattr(EditPanel, nome, registrar(nome))
    app, janela, _ = _app()
    janela.show()
    janela._tabs.setCurrentIndex(2)
    _processar(app)
    janela.activateWindow()
    janela.raise_()
    _processar(app)
    editor = janela._edit
    campos = ([c for c in editor.findChildren(QLineEdit) if c.isVisible()]
              + [c for c in editor.findChildren(QPlainTextEdit) if c.isVisible()])
    focos = {"linha do tempo": editor._timeline, "prévia": editor._preview, "biblioteca": editor._media_list}
    if campos:
        focos["campo de texto"] = campos[0]
    teclas = ("Space", "S", "Ctrl+B", "Q", "W", "Del", "Backspace", "Ctrl+C", "Ctrl+V", ",", ".", "Ctrl+Z",
              "Ctrl+Shift+Z", "Ctrl+Y", "F", "F11", "Ctrl+S", "Ctrl+Shift+S", "Ctrl+O", "Ctrl+N", "Ctrl+E",
              "Home", "End", "Left", "Right")
    saida = {}
    for nome_foco, widget in focos.items():
        for tecla in teclas:
            widget.setFocus()
            _processar(app, 3)
            combinacao = QKeySequence(tecla)[0]
            antes = len(chamadas)
            QTest.keyClick(QApplication.focusWidget() or widget, combinacao.key(), combinacao.keyboardModifiers())
            _processar(app, 3)
            saida[f"{nome_foco} | {tecla}"] = chamadas[antes:]
    return saida


def secao_exportacao(midia_dir: Path) -> dict:
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QWidget
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, auto_canvas, media_ref
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools
    from videomanager.presentation.qt.export_dialog import ExportDialog
    app, janela, perfil = _app()
    editor = janela._edit
    tools = find_tools()
    midia = {n: media_ref(probe_file(midia_dir / n, tools)) for n in ("r2997.mp4", "r30.mp4", "r60.mp4", "m10.m4a")}
    probed = {r.path: probe_file(r.path, tools) for r in midia.values()}
    a, b, c, m = midia["r2997.mp4"], midia["r30.mp4"], midia["r60.mp4"], midia["m10.m4a"]
    texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=1.5), 0.2, 1.5, overlay_type="text",
                 text_content="Olá", font_size=48)
    projetos = {
        "um_clipe": Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(a, 0.0, a.duration),)),)),
        "recorte": Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(a, 0.0, 1.0, in_point=0.5),)),)),
        "dois_clipes": Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(b, 0.0, 2.0), Clip(c, 2.0, 2.0))),)),
        "com_texto": Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(texto,)),
                                     Track(TrackKind.VIDEO, clips=(Clip(b, 0.0, 2.0),)))),
        "musica_longa": Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(b, 0.0, 2.0),)),
                                        Track(TrackKind.AUDIO, clips=(Clip(m, 0.0, 5.0),)))),
    }
    destino = perfil / "saida"

    def janela_exportacao(projeto, tela=None, taxa=None):
        dialogo = ExportDialog(processing=editor._processing, project=auto_canvas(projeto), settings=editor._settings,
                               pool=list(midia.values()), probed=probed, keyframes=(), ensure_tools=lambda: tools,
                               initial_canvas=tela, initial_rate=taxa, project_path=None, parent=None,
                               runtime=editor._runtime)
        dialogo._same_folder.setChecked(False)
        dialogo._dest_edit.setText(str(destino))
        return dialogo

    def escolher(caixa, dado):
        for i in range(caixa.count()):
            if caixa.itemData(i) == dado:
                caixa.setCurrentIndex(i)
                return True
        return False

    def tarefa(dialogo):
        dialogo._on_enqueue()
        job = dialogo.created_job
        return None if job is None else {"alvo": type(job.request.target).__name__, "campos": _normal(job.request.target),
                                         "descricao": str(job.description), "avisos": [str(a) for a in job.warnings],
                                         "devolvida": _normal([dialogo.chosen_canvas, dialogo.chosen_rate])}

    saida = {}
    modos = (("mp4", False, False, False, None), ("mkv", False, False, False, None),
             ("mov", False, False, False, None), ("gif", False, False, False, None),
             ("mp4", True, False, False, None), ("mp4", False, True, False, 60.0),
             (None, False, False, True, None))
    for nome, projeto in projetos.items():
        for recipiente, rapido, interpolar, so_audio, taxa in modos:
            dialogo = janela_exportacao(projeto, taxa=taxa)
            chave = f"tarefa {nome} | {recipiente} rápido={rapido} interpolar={interpolar} só_áudio={so_audio} taxa={taxa}"
            if so_audio:
                dialogo._audio_only_check.setChecked(True)
            if recipiente:
                escolher(dialogo._container_box, recipiente)
            if rapido and not dialogo._fast.isEnabled():
                saida[chave] = "rápido indisponível"
            elif interpolar and not dialogo._interpolate.isEnabled():
                saida[chave] = "interpolar indisponível"
            else:
                dialogo._fast.setChecked(rapido)
                dialogo._interpolate.setChecked(interpolar)
                saida[chave] = tarefa(dialogo)
            dialogo.deleteLater()
    explicitas = (("720p_25", (1280, 720), 25.0, ()), ("vertical", (1080, 1920), None, ()),
                  ("fora_das_listas", (1000, 562), None, ()), ("ntsc_exata", None, 30000 / 1001, ()),
                  ("troca_proporcao", None, None, (("aspect", "9:16"),)),
                  ("troca_tela", None, None, (("canvas", (1280, 720)),)),
                  ("troca_taxa", None, None, (("rate", 50.0),)),
                  ("explicita_depois_auto", (1280, 720), 25.0, (("canvas", None), ("rate", None))))
    dois = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(a, 0.0, 2.0), Clip(c, 2.0, 2.0))),))
    for nome, tela, taxa, acoes in explicitas:
        dialogo = janela_exportacao(dois, tela, taxa)
        caixas = {"aspect": getattr(dialogo, "_aspect_box", None), "canvas": dialogo._canvas_box,
                  "rate": dialogo._rate_box}
        for qual, dado in acoes:
            if caixas[qual] is not None:
                escolher(caixas[qual], dado)
        resultado = tarefa(dialogo)
        saida[f"escolha explícita {nome}"] = {"tarefa": resultado, "tela_mostrada": dialogo._canvas_box.currentText(),
                                              "taxa_mostrada": dialogo._rate_box.currentText()}
        dialogo.deleteLater()
    for nome in ("um_clipe", "musica_longa"):
        for recipiente in ("mp4", "mkv", "webm", "mov", "gif"):
            for so_audio in (False, True):
                dialogo = janela_exportacao(projetos[nome])
                dialogo.show()
                escolher(dialogo._container_box, recipiente)
                dialogo._audio_only_check.setChecked(so_audio)
                app.processEvents()
                campos = {}
                for campo, obj in vars(dialogo).items():
                    if isinstance(obj, QWidget):
                        info = {"visivel": obj.isVisibleTo(dialogo), "habilitado": obj.isEnabled(), "dica": obj.toolTip()}
                        if isinstance(obj, (QAbstractButton, QLabel, QLineEdit)):
                            info["texto"] = re.sub(r"/[^ ]*vm-retrato-[^ ]*", "<perfil>", obj.text())
                        if isinstance(obj, QAbstractButton) and obj.isCheckable():
                            info["marcado"] = obj.isChecked()
                        if isinstance(obj, QComboBox):
                            info["itens"] = [obj.itemText(i) for i in range(obj.count())]
                        campos[campo] = info
                saida[f"campos {nome} | {recipiente} | só_áudio={so_audio}"] = campos
                dialogo.close()
                dialogo.deleteLater()
    editor.shutdown()
    return saida


def secao_persistencia(midia_dir: Path) -> dict:
    from PySide6.QtWidgets import QDialog
    from videomanager.domain.keyframe import Keyframe
    from videomanager.domain.project import Clip, Project, Track, TrackKind, auto_canvas, media_ref, new_project
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools
    import videomanager.presentation.qt.panels.edit_panel as modulo_painel
    app, janela, perfil = _app()
    editor = janela._edit
    tools = find_tools()
    ref = lambda nome: media_ref(probe_file(midia_dir / nome, tools))  # noqa: E731
    r60 = ref("r60.mp4")
    saida = {}

    def reabrir(projeto, pool, nome):
        arquivo = perfil / f"{nome}.vmp"
        editor.install_project(projeto, None, pool, {})
        _processar(app)
        foto = editor.editor.session.snapshot()
        editor.editor.write_snapshot(foto, arquivo)
        editor.editor.accept_saved(foto, arquivo)
        original = arquivo.read_bytes()
        # Sai de um projeto sem caminho: o accept_saved já gravou o caminho, e
        # esperar por ele sem isso terminaria antes de a abertura acontecer.
        editor.install_project(new_project(), None, [], {})
        editor.open_project(arquivo)
        _esperar(app, lambda: editor.project_path == arquivo and not editor._project.is_empty)
        _processar(app, 30)
        return arquivo, original

    def estado():
        return _normal({"escolha_tela": editor._canvas_choice, "escolha_taxa": editor._rate_choice,
                        "tela": [editor._project.width, editor._project.height], "taxa": editor._project.fps})

    for nome in ("r23976.mp4", "r25.mp4", "r2997.mp4", "r30.mp4"):
        video = ref(nome)
        arquivo, original = reabrir(Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0.0, 2.0),)),)),
                                    [video], nome)
        linha = {"alterado_ao_abrir": editor.has_unsaved_changes, "reaberto": estado()}
        foto = editor.editor.session.snapshot()
        editor.editor.write_snapshot(foto, arquivo)
        linha["salvar_sem_editar_grava_igual"] = arquivo.read_bytes() == original
        editor._pool.append(r60)
        editor._insert_media_ref(r60)
        _processar(app)
        linha["depois_de_60fps"] = estado()
        editor._undo_edit()
        _processar(app)
        linha["desfeito"] = estado()
        saida[f"reabrir {nome}"] = linha

    animacao = (Keyframe(0.0, opacity=0.0), Keyframe(0.5, opacity=1.0), Keyframe(1.5, opacity=1.0),
                Keyframe(2.0, opacity=0.0))
    video = ref("r2997.mp4")
    editor.install_project(auto_canvas(Project(tracks=(Track(TrackKind.VIDEO, clips=(
        Clip(video, 0.0, 2.0, keyframes=animacao),)),))), None, [video], {})
    _processar(app)
    antes = editor._project
    editor._timeline.select(editor._project.clips[0].clip_id)
    editor._on_speed(2.0)
    saida["velocidade 2x"] = _normal({"duracao": editor._project.clips[0].duration,
                                      "quadros_chave": [k.time_offset for k in editor._project.clips[0].keyframes]})
    editor._speed_session = -1
    editor._undo_edit()
    saida["desfazer velocidade volta igual"] = editor._project == antes

    class Janela:
        def __init__(self, *args, **kwargs):
            self.created_job, self.chosen_canvas, self.chosen_rate = None, (1080, 1920), None

        def exec(self):
            self.created_job = object()
            return QDialog.DialogCode.Accepted

    original_dialogo = modulo_painel.ExportDialog
    modulo_painel.ExportDialog = Janela
    try:
        indice = next(i for i in range(editor._aspect_box.count()) if editor._aspect_box.itemData(i) == "16:9")
        editor._aspect_box.setCurrentIndex(indice)
        _processar(app)
        editor.jobs_ready.disconnect()
        editor._open_export_dialog()
        _processar(app)
        saida["tela vertical escolhida na exportação"] = _normal({
            "proporcao": editor._aspect_choice, "tela": editor._canvas_choice,
            "lista": editor._canvas_box.currentText(), "projeto": [editor._project.width, editor._project.height]})
    finally:
        modulo_painel.ExportDialog = original_dialogo
    editor.shutdown()
    return saida


def secao_layout(_midia_dir: Path) -> dict:
    from PySide6.QtCore import QPoint, QRect
    app, janela, _ = _app()
    janela.show()
    _processar(app)
    editor = janela._edit
    divisor = editor._top_splitter
    saida = {}
    # O grab() da janela dispõe a aba escondida na largura do momento: as
    # colunas não podem ficar presas no que cederam ali.
    janela.resize(1280, 900)
    janela._tabs.setCurrentIndex(1)
    _processar(app)
    janela.grab()
    janela.resize(1920, 1200)
    janela._tabs.setCurrentIndex(2)
    _processar(app)
    saida["divisor depois da aba escondida"] = divisor.sizes()
    janela.resize(1280, 900)
    _processar(app)
    janela.resize(1920, 1200)
    _processar(app)
    saida["divisor 1920 → 1280 → 1920"] = divisor.sizes()
    controles = list(dict.fromkeys([*editor._buttons, editor._time_label, editor._frame_label, editor._loop,
                                    editor._mute, editor._volume, editor._play_button]))
    problemas = []
    escala = float(os.environ.get("QT_SCALE_FACTOR", "1") or 1)
    for largura in range(janela.minimumSizeHint().width(), int(1920 / escala) + 1, 23):
        janela.resize(largura, 900)
        _processar(app, 3)
        areas = []
        for c in controles:
            if not c.isVisible():
                problemas.append([largura, "invisível", type(c).__name__])
                continue
            area = QRect(c.mapTo(editor, QPoint(0, 0)), c.size())
            if area.left() < 0 or area.right() > editor.width():
                problemas.append([largura, "fora da aba", type(c).__name__])
            if not c.parentWidget().rect().contains(QRect(c.pos(), c.size())):
                problemas.append([largura, "cortado pelo contêiner", type(c).__name__])
            areas.append(area)
        for i, area in enumerate(areas):
            if any(area.intersects(outra) for outra in areas[i + 1:]):
                problemas.append([largura, "controles sobrepostos"])
    saida["barra de transporte: problemas"] = problemas
    editor.shutdown()
    return saida


EXECUTORES = {"comandos": secao_comandos, "interface": secao_interface, "atalhos": secao_atalhos,
              "exportacao": secao_exportacao, "persistencia": secao_persistencia, "layout": secao_layout}


# ---------------------------------------------------------------------------
# Comparação
# ---------------------------------------------------------------------------

def _primeira_diferenca(a, b, caminho=""):
    if type(a) is not type(b):
        return caminho, a, b
    if isinstance(a, dict):
        for chave in sorted(set(a) | set(b), key=str):
            if a.get(chave) != b.get(chave):
                return _primeira_diferenca(a.get(chave), b.get(chave), f"{caminho}/{chave}")
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{caminho}[{len(a)}→{len(b)} itens]", a[:3], b[:3]
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _primeira_diferenca(x, y, f"{caminho}[{i}]")
    return caminho, a, b


def comparar(antes: Path, depois: Path, limite: int) -> int:
    a, b = json.loads(antes.read_text(encoding="utf-8")), json.loads(depois.read_text(encoding="utf-8"))
    total = 0
    for secao in sorted(set(a) | set(b)):
        sa, sb = a.get(secao, {}), b.get(secao, {})
        if not isinstance(sa, dict) or not isinstance(sb, dict):
            iguais = sa == sb
            print(f"== {secao}: {'igual' if iguais else f'DIFERENTE ({str(sa)[:120]} → {str(sb)[:120]})'}")
            total += 0 if iguais else 1
            continue
        chaves = sorted(set(sa) | set(sb), key=str)
        diferentes = [k for k in chaves if sa.get(k) != sb.get(k)]
        total += len(diferentes)
        print(f"== {secao}: {len(chaves)} itens, {len(diferentes)} diferente(s)")
        for chave in diferentes[:limite]:
            caminho, x, y = _primeira_diferenca(sa.get(chave), sb.get(chave), str(chave))
            print(f"   {caminho}\n      antes:  {str(x)[:160]}\n      depois: {str(y)[:160]}")
        if len(diferentes) > limite:
            print(f"   … e mais {len(diferentes) - limite} (use --limite)")
    print(f"\n{total} diferença(s). Cada uma precisa ser uma mudança pretendida.")
    return 1 if total else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--comparar", nargs=2, type=Path, metavar=("ANTES", "DEPOIS"))
    parser.add_argument("--limite", type=int, default=15, help="diferenças mostradas por seção")
    parser.add_argument("--secoes", nargs="+", choices=SECOES, default=list(SECOES))
    parser.add_argument("--secao", choices=SECOES, help=argparse.SUPPRESS)
    parser.add_argument("--midia", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.comparar:
        return comparar(*args.comparar, args.limite)
    if args.secao:
        print(json.dumps(_normal(EXECUTORES[args.secao](args.midia)), ensure_ascii=False))
        return 0
    from videomanager.infrastructure.system.binaries import find_tools
    tools = find_tools()
    if tools is None:
        print("ffmpeg não encontrado: o retrato precisa dele para gerar as mídias de teste.", file=sys.stderr)
        return 2
    midia_dir = Path(tempfile.mkdtemp(prefix="vm-retrato-midia-"))
    _midia(midia_dir, tools)
    retrato = {}
    for secao in args.secoes:
        # Um processo por seção: janela, timers e threads de uma não chegam na outra.
        feito = subprocess.run([sys.executable, __file__, "--secao", secao, "--midia", str(midia_dir)],
                               capture_output=True, text=True, timeout=900, env=os.environ.copy())
        try:
            retrato[secao] = json.loads(feito.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            retrato[secao] = {"ERRO": (feito.stderr or "sem saída").strip().splitlines()[-5:]}
        print(f"{secao}: {'ok' if 'ERRO' not in retrato[secao] else 'falhou'}", file=sys.stderr)
    print(json.dumps(retrato, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
