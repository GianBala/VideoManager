"""Troca de idioma com a janela aberta: o mecanismo de presentation/qt/i18n.py.

O inglês dos testes do mecanismo é o pseudoidioma do ``conftest`` (cada texto
do catálogo entre ⟦ ⟧), porque o mecanismo não pode depender de uma tradução.
A tradução de verdade se confere no fim, pela forma: os mesmos nomes,
parâmetros e estruturas do português.
"""

from __future__ import annotations

import re
import string

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QWidget

from videomanager.domain import i18n
from videomanager.presentation.qt import i18n as idioma
from videomanager.presentation.qt import strings


class _Dono(QWidget):
    def __init__(self):
        super().__init__()
        self.chamadas = 0
        self.congelada = None

    def refazer(self):
        self.chamadas += 1
        self.congelada = not self.updatesEnabled()


def test_catalogo_e_texto_preso_seguem_a_troca(pseudo):
    rotulo = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    assert rotulo.text() == "Reproduzir"
    idioma.apply_language(i18n.ENGLISH)
    assert strings.EDIT_PLAY == "⟦Reproduzir⟧"
    assert strings.QUEUE_COLUMNS[0] == "⟦Título⟧"
    assert rotulo.text() == "⟦Reproduzir⟧"
    assert i18n.language() == i18n.ENGLISH
    idioma.apply_language(i18n.PORTUGUESE)
    assert rotulo.text() == "Reproduzir"
    assert strings.EDIT_PLAY == "Reproduzir"


def test_origem_com_estado_volta_igual_no_idioma_novo(pseudo):
    contagem = 3
    rotulo = idioma.bind(QLabel(), "setToolTip", lambda: strings.EDIT_MEDIA_COUNT.format(count=contagem))
    idioma.apply_language(i18n.ENGLISH)
    assert rotulo.toolTip() == "⟦3 mídia(s)⟧"


def test_texto_escrito_depois_do_bind_nao_e_apagado(pseudo):
    rotulo = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    rotulo.setText("clip.mp4 · 4,25 s")
    idioma.apply_language(i18n.ENGLISH)
    assert rotulo.text() == "clip.mp4 · 4,25 s"


def test_segundo_bind_substitui_o_primeiro(pseudo):
    botao = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    idioma.bind(botao, "setText", lambda: strings.EDIT_PAUSE)
    idioma.apply_language(i18n.ENGLISH)
    assert botao.text() == "⟦Pausar⟧"


def test_widget_destruido_sai_do_registro(pseudo):
    rotulo = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    rotulo.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    idioma.apply_language(i18n.ENGLISH)
    assert all(obj is not rotulo for obj in list(idioma._bound.keys()))


def test_metodo_roda_na_troca_com_a_janela_congelada(pseudo):
    dono = _Dono()
    dono.show()
    idioma.on_language_change(dono.refazer)
    idioma.apply_language(i18n.ENGLISH)
    assert dono.chamadas == 1
    assert dono.congelada is True
    assert dono.updatesEnabled()
    idioma.apply_language(i18n.ENGLISH)  # mesmo idioma: nada a refazer
    assert dono.chamadas == 1
    dono.close()


def test_metodo_de_dono_destruido_nao_roda(pseudo):
    dono = _Dono()
    idioma.on_language_change(dono.refazer)
    dono.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    idioma.apply_language(i18n.ENGLISH)  # não levanta RuntimeError de objeto C++ apagado


def test_bind_e_on_language_change_recusam_o_que_nao_saberiam_refazer(desktop_app):
    with pytest.raises(ValueError):
        idioma.bind(QLabel(), "setAccessibleName", lambda: strings.EDIT_PLAY)
    with pytest.raises(TypeError):
        idioma.on_language_change(lambda: None)


def test_fila_desenha_o_texto_guardado_no_idioma_do_momento(desktop_app):
    from PySide6.QtCore import QObject, Qt, Signal

    from videomanager.application.events import Progress
    from videomanager.application.jobs.models import Job, JobStatus
    from videomanager.domain.i18n import Text
    from videomanager.presentation.qt.panels.queue_panel import QueueModel

    class Fila(QObject):
        job_added = Signal(object)
        job_changed = Signal(object)

    fila = Fila()
    modelo = QueueModel(fila)
    falhou = Job("a.mp4", "a.mp4", Text("DESC_AUDIO_ONLY"), status=JobStatus.FAILED,
                 error=Text("PROBE_GEO"), warnings=(Text("DESC_NO_SUBTITLES"),))
    baixando = Job("b.mp4", "b.mp4", "—", status=JobStatus.RUNNING,
                   progress=Progress(phase=Text("PHASE_MERGING")))
    fila.job_added.emit(falhou)
    fila.job_added.emit(baixando)

    def celulas():
        exibir, dica = Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole
        return (modelo.data(modelo.index(0, 1), exibir), modelo.data(modelo.index(0, 2), dica),
                modelo.data(modelo.index(0, 1), dica), modelo.data(modelo.index(1, 2), exibir))

    assert celulas() == ("somente áudio", "Esta mídia está bloqueada na sua região.",
                         "legendas não incluídas", "Juntando vídeo e áudio")
    i18n.set_language(i18n.ENGLISH)
    assert celulas() == ("audio only", "This media is blocked in your region.",
                         "subtitles not included", "Merging video and audio")


def test_descricao_e_aviso_da_exportacao_seguem_a_troca(pseudo, tmp_path):
    from pathlib import Path

    from videomanager.application.capabilities import FFmpegTools
    from videomanager.bootstrap import build_desktop_runtime, build_processing_service
    from videomanager.domain.media import LocalMedia, LocalStream
    from videomanager.domain.project import Clip, MediaKind, MediaRef, new_project
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.export_dialog import ExportDialog

    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")
    ref = MediaRef(video, MediaKind.VIDEO, duration=60.0, width=1920, height=1080, fps=30.0, has_audio=True)
    local = LocalMedia(path=video, duration=60.0, format_name="mp4", size=1024,
                       streams=(LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080, fps=30.0),
                                LocalStream(index=1, kind="audio", codec="aac", channels=2)))
    ferramentas = FFmpegTools(ffmpeg=Path("/bin/true"), ffprobe=Path("/bin/true"), source="sistema")
    projeto = new_project().with_clip(0, Clip(ref, 0.0, 30.0))

    def exportar(rapido: bool):
        janela = ExportDialog(project=projeto, settings=Settings(), pool=[ref], probed={ref.path: local},
                              keyframes=(0.0, 5.0), ensure_tools=lambda: ferramentas,
                              processing=build_processing_service(), runtime=build_desktop_runtime())
        janela._fast.setChecked(rapido)
        janela._on_enqueue()
        return janela.created_job

    rapida, composta = exportar(True), exportar(False)
    assert "cópia direta" in str(rapida.description)
    assert str(composta.description).endswith("30,00 s de duração")
    idioma.apply_language(i18n.ENGLISH)
    # A descrição rápida vem do catálogo da interface; a composta, do da aplicação.
    assert str(rapida.description).startswith("⟦")
    assert str(composta.description).endswith("30.00 s long")


def test_quem_mede_o_layout_roda_depois_de_todos_os_textos(pseudo):
    """Medido no meio da troca, o layout tinha parte dos textos trocados, e um
    QSplitter apertado por um mínimo provisório não devolvia a coluna."""
    ordem = []

    class Dono(QWidget):
        def texto(self):
            ordem.append("texto")

        def medida(self):
            ordem.append(("medida", idioma.switching(), not self.updatesEnabled()))

    dono = Dono()
    dono.show()
    idioma.on_language_change(dono.medida, after_layout=True)
    idioma.on_language_change(dono.texto)
    idioma.apply_language(i18n.ENGLISH)
    assert ordem == ["texto", ("medida", True, True)]
    assert not idioma.switching()
    dono.close()


# --- a tradução de verdade ---------------------------------------------------

def _campos(texto):
    return sorted((nome, formato, conversao) for _, nome, formato, conversao in string.Formatter().parse(texto)
                  if nome is not None)


def _mesma_forma(pt, en, onde):
    assert type(pt) is type(en), onde
    if isinstance(pt, dict):
        assert list(pt) == list(en), onde
        for chave in pt:
            _mesma_forma(pt[chave], en[chave], f"{onde}[{chave!r}]")
    elif isinstance(pt, tuple):
        assert len(pt) == len(en), onde
        for i, (a, b) in enumerate(zip(pt, en)):
            _mesma_forma(a, b, f"{onde}[{i}]")
    else:
        # Um parâmetro a menos no inglês levantaria KeyError só nesse idioma.
        assert _campos(pt) == _campos(en), onde
        # A marcação só vale onde as duas línguas a têm, e "&" é tecla de
        # atalho em botão, aba e rótulo de formulário: some da tela.
        assert re.findall(r"<[^>]*>", pt) == re.findall(r"<[^>]*>", en), onde
        assert pt.count("&") == en.count("&"), onde
        # O espaço da ponta faz parte do texto montado (" (corte)").
        assert (pt[:1] == " ", pt[-1:] == " ") == (en[:1] == " ", en[-1:] == " "), onde
        # Ícone e símbolo ("♪", "{width} × {height}") não se traduzem.
        if not re.search(r"[^\W\d_]", re.sub(r"\{[^}]*\}", "", pt)):
            assert en == pt, onde


def test_ingles_tem_os_nomes_parametros_e_estruturas_do_portugues():
    pt, en = idioma._TABLES[i18n.PORTUGUESE], idioma._TABLES[i18n.ENGLISH]
    assert set(pt) ^ set(en) == set()
    # Na mesma ordem, para os dois arquivos se lerem lado a lado.
    assert list(pt) == list(en)
    for nome in pt:
        _mesma_forma(pt[nome], en[nome], nome)


def _textos(valor):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, (tuple, dict)):
        for item in (valor.values() if isinstance(valor, dict) else valor):
            yield from _textos(item)


# Acento do português, ou palavra que o inglês não tem.
_PORTUGUES = re.compile(r"[ãõçáéíóúâêôà]|\b(de|para|com|sem|uma?|os|ao|trilha|bloco|quadro|arquivo)\b",
                        re.IGNORECASE)
# Iguais nas duas línguas de propósito: nome de formato, sigla, palavra que o
# português tomou do inglês. Fora daqui, texto igual é texto que ficou sem
# tradução — o detector acima não reconhece "Copiar".
_IGUAIS = {
    "TAB_DOWNLOAD", "TAB_CONVERT", "LABEL_CONTAINER", "LABEL_AUDIO_QUALITY", "PROFILE_MP4_1080",
    "PROFILE_MP3_320", "STATUS_FFMPEG", "CONVERT_PICK_TIP", "CONVERT_REMOVE_TIP", "EDIT_CHANNELS_MONO",
    "EXPORT_CONTAINERS", "EXPORT_VIDEO_CODECS", "EXPORT_AUDIO_FORMATS", "EXPORT_ASPECTS", "EDIT_PREV_KEY_SHORT",
    "EDIT_NEXT_KEY_SHORT", "EDIT_LOOP", "EDIT_FONT_BOLD", "EDIT_FONT_ITALIC", "EDIT_TRANSITIONS",
    "EDIT_CANVAS_FPS", "PROP_CLIP_ID", "EDIT_SLIDESHOW", "LANGUAGE_NAMES",
}


def test_ingles_sem_resto_de_portugues():
    pt, en = idioma._TABLES[i18n.PORTUGUESE], idioma._TABLES[i18n.ENGLISH]
    restos = []
    for nome in en:
        for original, traduzido in zip(_textos(pt[nome]), _textos(en[nome])):
            if traduzido == original:
                # "Português (Brasil)" fica igual de propósito, e com acento.
                if nome not in _IGUAIS and re.search(r"[^\W\d_]", re.sub(r"\{[^}]*\}", "", original)):
                    restos.append(f"{nome}: {traduzido!r}")
            elif _PORTUGUES.search(traduzido):
                restos.append(f"{nome}: {traduzido!r}")
    assert restos == []


def test_cada_idioma_aparece_no_proprio_nome():
    assert list(strings.LANGUAGE_NAMES) == list(i18n.LANGUAGES)


def test_aviso_de_biblioteca_faltando_sai_no_idioma_das_preferencias():
    """Sai antes de existir janela, e portanto antes de qualquer troca."""
    from videomanager.preflight import format_instructions
    assert format_instructions(["libxcb-cursor0"]).startswith(
        "O Video Manager não pôde abrir: falta biblioteca de sistema")
    i18n.set_language(i18n.ENGLISH)
    texto = format_instructions(["libxcb-cursor0", "libxcb-xkb1"])
    assert texto.startswith("Video Manager could not start: system libraries")
    assert "sudo apt install -y libxcb-cursor0 libxcb-xkb1" in texto


def test_aviso_de_url_nao_reconhecida_aponta_o_menu_do_motor(desktop_app):
    """Dizia "atualizar a engine em Configurações", onde não há como fazer isso."""
    import importlib
    importlib.import_module("videomanager.infrastructure")  # registra o catálogo da camada
    for codigo in i18n.LANGUAGES:
        idioma.apply_language(codigo)
        assert strings.MENU_TOOLS.replace("&", "") in i18n.t("PROBE_UNSUPPORTED")
