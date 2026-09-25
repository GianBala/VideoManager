"""Troca de idioma na janela inteira: nada esquecido, nada editado, nada rearranjado.

A garantia central: a janela trocada ao vivo mostra os mesmos textos que uma
janela que já nasce no idioma novo. Um texto preso num widget sem ``bind``
aparece aqui como diferença — é o teste que falha quando alguém acrescenta
um botão e esquece da troca. ``scripts/validate_language.py`` faz o mesmo em
mais cenas e confere também a geometria.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import shiboken6
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QMenu, QMenuBar,
                               QTabWidget, QWidget)

from conftest import fixture_formats
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.domain import i18n
from videomanager.domain.formats import MediaInfo
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.infrastructure.yt_dlp.formats import build_matrix
from videomanager.presentation.qt import i18n as idioma
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.main_window import MainWindow

_EDITOR = 2


@pytest.fixture
def janelas(desktop_app, monkeypatch):
    """Fábrica de janelas, todas fechadas no fim sem perguntar nada."""
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    abertas: list[MainWindow] = []

    def abrir() -> MainWindow:
        janela = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                            downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
        janela.show()
        desktop_app.processEvents()
        abertas.append(janela)
        return janela

    yield abrir
    for janela in abertas:
        janela._edit._project_actions.confirm_replace = lambda: True
        janela._edit.shutdown()
        janela.close()


def _foto(pasta: Path) -> MediaRef:
    imagem = QImage(320, 180, QImage.Format.Format_RGBA8888)
    imagem.fill(QColor("orange"))
    caminho = pasta / "foto.png"
    imagem.save(str(caminho))
    return MediaRef(caminho, MediaKind.IMAGE, width=320, height=180)


def _projeto(foto: MediaRef) -> Project:
    texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=3.0), 0.0, 3.0, clip_id=801,
                 overlay_type="text", text_content="Olá")
    filtro = Clip(MediaRef(Path("Filtro_x"), MediaKind.IMAGE, duration=3.0), 3.0, 3.0, clip_id=802,
                  overlay_type="filter", filter_name="sepia")
    a, b = Clip(foto, 0.0, 4.0, clip_id=803), Clip(foto, 4.0, 4.0, clip_id=804)
    transicao = Clip(MediaRef(Path("Transição_x"), MediaKind.IMAGE, duration=1.0), 3.5, 1.0, clip_id=805,
                     overlay_type="transition", transition_name="dissolve",
                     transition_left_id=803, transition_right_id=804)
    return Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(texto, filtro)),
                           Track(TrackKind.VIDEO, clips=(a, transicao, b))), width=640, height=360, fps=30.0)


def _caminho(widget: QWidget, raiz: QWidget) -> str:
    partes = []
    atual = widget
    while atual is not None and atual is not raiz:
        pai = atual.parentWidget()
        irmaos = [c for c in (pai.children() if pai is not None else []) if type(c) is type(atual)]
        partes.append(f"{type(atual).__name__}{irmaos.index(atual)}")
        atual = pai
    return "/".join(reversed(partes))


def _textos(janela: QWidget) -> dict[str, object]:
    """Todo texto que a janela mostra ou guarda para mostrar."""
    saida: dict[str, object] = {}
    for w in janela.findChildren(QWidget):
        # O menu de transbordo da barra é interno do Qt (sem título).
        if not shiboken6.isValid(w) or (isinstance(w, QMenu) and not w.title()
                                        and isinstance(w.parentWidget(), QMenuBar)):
            continue
        caminho = _caminho(w, janela)
        if isinstance(w, (QLabel, QAbstractButton)):
            saida[f"{caminho}.texto"] = w.text()
        if isinstance(w, QGroupBox):
            saida[f"{caminho}.titulo"] = w.title()
        if isinstance(w, QLineEdit):
            saida[f"{caminho}.placeholder"] = w.placeholderText()
        if isinstance(w, QComboBox):
            saida[f"{caminho}.itens"] = [w.itemText(i) for i in range(w.count())]
        if isinstance(w, QTabWidget):
            saida[f"{caminho}.abas"] = [w.tabText(i) for i in range(w.count())]
        if isinstance(w, QMenu):
            saida[f"{caminho}.menu"] = [w.title(), *(a.text() for a in w.actions())]
        saida[f"{caminho}.dica"] = w.toolTip()
    return saida


def _diferencas(a: dict, b: dict) -> list[str]:
    return [f"{chave}: {a.get(chave)!r} × {b.get(chave)!r}"
            for chave in sorted(set(a) | set(b)) if a.get(chave) != b.get(chave)]


def _cena_download(janela: MainWindow) -> None:
    media = MediaInfo(url="https://exemplo/v", title="Vídeo", matrix=build_matrix(fixture_formats("youtube_dash")))
    janela._on_probed(media)


def _cena_editor(janela: MainWindow, foto: MediaRef, escolhido: int, propriedades: bool = False) -> None:
    janela._tabs.setCurrentIndex(_EDITOR)
    janela._edit.install_project(_projeto(foto), None, [foto], {})
    janela._edit._timeline.select(escolhido)
    if propriedades:
        janela._edit._open_properties_tab(escolhido)


@pytest.mark.parametrize("cena", ["download", "texto", "filtro", "transicao", "propriedades"])
def test_janela_trocada_ao_vivo_mostra_o_mesmo_que_a_que_nasce_no_idioma(janelas, pseudo, tmp_path, cena):
    foto = _foto(tmp_path)

    def entrar(janela: MainWindow) -> None:
        if cena == "download":
            _cena_download(janela)
        else:
            escolhido = {"texto": 801, "filtro": 802, "transicao": 805, "propriedades": 803}[cena]
            _cena_editor(janela, foto, escolhido, propriedades=cena == "propriedades")

    ao_vivo = janelas()
    entrar(ao_vivo)
    ao_vivo._edit._end_loading_hint()
    em_portugues = _textos(ao_vivo)
    idioma.apply_language(i18n.ENGLISH)
    do_zero = janelas()
    entrar(do_zero)
    # O aviso de carregamento aparece depois de um prazo, e a janela mais
    # velha pode tê-lo à vista enquanto a nova não: estado de tempo, não de
    # idioma. Sem ffmpeg aqui, nenhum quadro chegaria para tirá-lo.
    for janela in (ao_vivo, do_zero):
        janela._edit._end_loading_hint()
    assert _diferencas(_textos(ao_vivo), _textos(do_zero)) == []
    idioma.apply_language(i18n.PORTUGUESE)
    ao_vivo._edit._end_loading_hint()
    assert _diferencas(_textos(ao_vivo), em_portugues) == []


def test_troca_nao_reescreve_o_bloco_de_texto_escolhido(janelas, pseudo, tmp_path):
    """O campo da aba Texto edita o bloco ao vivo; com o conteúdo igual ao
    texto inicial ("Título"), a troca o tomava por texto de catálogo, e a
    tradução dele virava uma edição do projeto."""
    janela = janelas()
    editor = janela._edit
    texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=3.0), 0.0, 3.0, clip_id=811,
                 overlay_type="text", text_content=strings.EDIT_TEXT_DEFAULT)
    janela._tabs.setCurrentIndex(_EDITOR)
    editor.install_project(Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(texto,)),),
                                   width=640, height=360, fps=30.0), None, [], {})
    editor._timeline.select(811)
    projeto, desfazer = editor._project, len(editor._session.history)
    idioma.apply_language(i18n.ENGLISH)
    assert editor._project is projeto
    assert len(editor._session.history) == desfazer
    assert editor._text_input.text() == "Título"
    assert not editor.has_unsaved_changes


def test_troca_nao_refaz_a_divisao_das_colunas_do_editor(janelas, pseudo, tmp_path):
    """Os textos novos mudam a largura mínima da aba, e o divisor de cima
    refazia a divisão inteira como se a janela tivesse mudado de tamanho: com a
    aba Propriedades aberta, a coluna de Adicionais perdia 47 px — e a volta ao
    português não a devolvia."""
    janela = janelas()
    foto = _foto(tmp_path)
    _cena_editor(janela, foto, 803, propriedades=True)
    divisor = janela._edit._top_splitter
    colunas = divisor.sizes()[:2]
    idioma.apply_language(i18n.ENGLISH)
    idioma.apply_language(i18n.PORTUGUESE)
    assert divisor.sizes()[:2] == colunas


def test_troca_com_o_editor_escondido_tambem_preserva_as_colunas(janelas, pseudo, tmp_path, desktop_app):
    """Aba escondida recebe o redimensionamento só ao aparecer, fora da troca."""
    janela = janelas()
    _cena_editor(janela, _foto(tmp_path), 803, propriedades=True)
    divisor = janela._edit._top_splitter
    colunas = divisor.sizes()[:2]
    janela._tabs.setCurrentIndex(0)
    idioma.apply_language(i18n.ENGLISH)
    idioma.apply_language(i18n.PORTUGUESE)
    janela._tabs.setCurrentIndex(_EDITOR)
    for _ in range(3):
        desktop_app.processEvents()
    assert divisor.sizes()[:2] == colunas


def test_coluna_de_rotulos_volta_a_encolher(desktop_app):
    """A dica do QLabel guarda o mínimo em vigor; o rótulo vazio de uma linha
    sem título segurava a coluna na largura do idioma anterior."""
    rotulos = [QLabel("Codec de vídeo"), QLabel("Formato"), QLabel()]
    idioma.align_label_column(rotulos)
    rotulos[0].setText("Codec")
    idioma.align_label_column(rotulos)
    natural = max(QLabel(texto).sizeHint().width() for texto in ("Codec", "Formato", ""))
    assert [rotulo.minimumWidth() for rotulo in rotulos] == [natural] * 3


def test_itens_trocam_de_texto_sem_mudar_a_escolha_nem_emitir_sinal(desktop_app):
    lista = QComboBox()
    lista.addItem("Automática", None)
    lista.addItem("1080p", 1080)
    lista.setCurrentIndex(0)
    sinais = []
    lista.currentIndexChanged.connect(lambda *_: sinais.append("índice"))
    lista.currentTextChanged.connect(lambda *_: sinais.append("texto"))
    idioma.retext_items(lista, lambda dado: "Automatic" if dado is None else None)
    assert [lista.itemText(i) for i in range(lista.count())] == ["Automatic", "1080p"]
    assert lista.currentIndex() == 0
    assert sinais == []


def test_faixa_sem_altura_continua_escolhida_depois_da_troca(desktop_app):
    """O rótulo de uma faixa sem altura mostra o bitrate com o separador do
    idioma, e era ele o dado da lista: depois da troca a busca não achava mais
    a faixa e o download caía na primeira, em silêncio."""
    from videomanager.presentation.qt.panels.quality_panel import QualityPanel
    matriz = build_matrix([
        {"format_id": "a", "vcodec": "avc1", "acodec": "mp4a", "tbr": 1500.5, "protocol": "m3u8"},
        {"format_id": "b", "vcodec": "vp09", "acodec": "opus", "tbr": 2800.5, "protocol": "m3u8"},
    ])
    painel = QualityPanel(Settings())
    painel.set_matrix(matriz)
    sem_altura = [i for i in range(painel._resolution.count()) if painel._resolution.itemData(i) is not None]
    assert len(sem_altura) == 2
    painel._resolution.setCurrentIndex(sem_altura[-1])
    escolhida = painel.current_video_choice()
    i18n.set_language(i18n.ENGLISH)  # muda o separador decimal do rótulo
    painel._retranslate()
    assert painel.current_video_choice() is escolhida
    assert "." in painel._resolution.itemText(sem_altura[-1])


def test_aba_propriedades_sem_bloco_trocada_ao_vivo_igual_a_nova(desktop_app, pseudo):
    """Solta até ser aberta, a aba ficava fora da comparação da janela inteira."""
    from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget
    ao_vivo = _ClipPropertiesWidget()
    idioma.apply_language(i18n.ENGLISH)
    nova = _ClipPropertiesWidget()
    try:
        assert _diferencas(_textos(ao_vivo), _textos(nova)) == []
    finally:
        ao_vivo.deleteLater()
        nova.deleteLater()
