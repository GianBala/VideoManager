"""Aba Metadados: o comando do remux, a cópia gravada e medida, a aba e a janela.

A cópia é conferida pelo que ela tem, e não pela ausência de erro: tags lidas de
volta, pacotes de cada trilha idênticos aos da origem (md5) e o original intacto.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ConversionError, JobCancelled
from videomanager.domain.metadata import CoverInfo
from videomanager.domain.metadata import FileMetadata
from videomanager.domain.metadata import MetadataEdit
from videomanager.domain.metadata import TrackInfo
from videomanager.domain.metadata import unchanged_edit
from videomanager.infrastructure.ffmpeg.metadata import metadata_args
from videomanager.infrastructure.ffmpeg.metadata import verify_copy

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


def _meta(nome="a.mp4", tags=(("title", "Antigo"), ("ARTIST", "Fulano")), cover=None,
          streams=(("video", "h264"), ("audio", "aac")), formato="mov,mp4") -> FileMetadata:
    tracks = tuple(TrackInfo(i, kind, codec, "", "und") for i, (kind, codec) in enumerate(streams)
                   if kind != "attachment" and not (cover and cover.index == i))
    return FileMetadata(Path(f"/origem/{nome}"), formato, 10.0, tags, tracks, cover, streams)


def _pares(args: list[str], opcao: str) -> list[str]:
    return [args[i + 1] for i, valor in enumerate(args) if valor == opcao]


# --- Comando -------------------------------------------------------------------

class TestComando:
    def test_so_as_diferencas_vao_para_o_comando(self) -> None:
        meta = _meta()
        edicao = replace(unchanged_edit(meta), tags=(("title", "Novo"), ("artist", "Fulano"), ("album", "Disco")))
        args = metadata_args(meta, edicao, Path("/s/x.mp4"), TOOLS)
        assert _pares(args, "-metadata") == ["title=Novo", "album=Disco"]
        assert args[args.index("-map") + 1] == "0" and "-c" in args and args[args.index("-c") + 1] == "copy"

    def test_campo_apagado_sai_com_valor_vazio_na_caixa_da_origem(self) -> None:
        # O MKV guarda ARTIST; gravar "artist" criaria outro campo em vez de apagar.
        meta = _meta(tags=(("title", "T"), ("ARTIST", "Fulano")))
        args = metadata_args(meta, replace(unchanged_edit(meta), tags=(("title", "T"), ("artist", ""))),
                             Path("/s/x.mkv"), TOOLS)
        assert _pares(args, "-metadata") == ["ARTIST="]

    def test_campo_novo_vazio_nao_entra(self) -> None:
        meta = _meta()
        edicao = replace(unchanged_edit(meta), tags=(*unchanged_edit(meta).tags, ("album", "")))
        assert _pares(metadata_args(meta, edicao, Path("/s/x"), TOOLS), "-metadata") == []

    def test_ogg_grava_as_tags_na_trilha(self) -> None:
        meta = _meta("a.opus", streams=(("audio", "opus"),), formato="ogg")
        args = metadata_args(meta, replace(unchanged_edit(meta), tags=(("title", "X"),)), Path("/s/x.opus"), TOOLS)
        assert "-metadata" not in args and "title=X" in _pares(args, "-metadata:s:a:0")

    def test_titulo_da_trilha_no_mp4_vai_para_o_handler_name(self) -> None:
        meta = _meta()
        edicao = replace(unchanged_edit(meta), tracks=((0, "", "und"), (1, "Dublado", "por")))
        args = metadata_args(meta, edicao, Path("/s/x.mp4"), TOOLS)
        assert _pares(args, "-metadata:s:1") == ["handler_name=Dublado", "language=por"]

    def test_trocar_capa_do_mp3_tira_a_antiga_e_marca_a_nova(self) -> None:
        meta = _meta("a.mp3", tags=(), cover=CoverInfo(1, "picture", "image/jpeg"),
                     streams=(("audio", "mp3"), ("video", "mjpeg")), formato="mp3")
        args = metadata_args(meta, replace(unchanged_edit(meta), cover_image=Path("/c.png")), Path("/s/x.mp3"), TOOLS)
        assert _pares(args, "-map") == ["0", "-0:1", "1"]
        # A imagem nova é a trilha 1 da saída: a antiga saiu, e a de áudio fica na 0.
        assert args[args.index("-disposition:1") + 1] == "attached_pic"
        assert _pares(args, "-metadata:s:1") == ["title=Album cover", "comment=Cover (front)"]
        assert args[args.index("-id3v2_version") + 1] == "3"

    def test_indice_da_trilha_acompanha_a_capa_removida(self) -> None:
        meta = _meta(cover=CoverInfo(0, "picture", "image/png"),
                     streams=(("video", "png"), ("video", "h264"), ("audio", "aac")))
        edicao = replace(unchanged_edit(meta), remove_cover=True,
                         tracks=((1, "", "und"), (2, "", "por")))
        args = metadata_args(meta, edicao, Path("/s/x.mp4"), TOOLS)
        assert _pares(args, "-metadata:s:1") == ["language=por"]  # a 2 da origem vira a 1

    def test_capa_do_mkv_mantida_sai_e_volta_anexada(self) -> None:
        # Num remux simples ela voltava como trilha de vídeo de um quadro (medido).
        meta = _meta("a.mkv", tags=(), cover=CoverInfo(2, "picture", "image/jpeg"),
                     streams=(("video", "h264"), ("audio", "aac"), ("video", "mjpeg"), ("attachment", "ttf")),
                     formato="matroska,webm")
        args = metadata_args(meta, unchanged_edit(meta), Path("/s/x.mkv"), TOOLS, attach=Path("/t/cover.jpg"))
        assert "-0:2" in _pares(args, "-map")
        # Já há um anexo (a fonte): a capa é o segundo.
        assert _pares(args, "-metadata:s:t:1") == ["mimetype=image/jpeg", "filename=cover.jpg"]
        # Pelo Path, e não por texto: no Windows ele vira "\t\cover.jpg".
        assert args[args.index("-attach") + 1] == str(Path("/t/cover.jpg"))

    def test_mp4_sai_com_indice_no_comeco(self) -> None:
        assert "+faststart" in metadata_args(_meta(), unchanged_edit(_meta()), Path("/s/x.mp4"), TOOLS)


class TestConferencia:
    def test_copia_com_outras_trilhas_e_recusada(self) -> None:
        meta = _meta()
        copia = replace(meta, streams=(("video", "h264"),))
        with pytest.raises(ConversionError):
            verify_copy(meta, unchanged_edit(meta), copia)

    def test_diz_o_que_o_formato_nao_guardou(self) -> None:
        meta = _meta()
        edicao = replace(unchanged_edit(meta), tags=(("title", "Novo"), ("ARTIST", "Fulano"), ("meu_campo", "x")),
                         tracks=((0, "", "und"), (1, "Dublado", "und")))
        copia = replace(meta, tags=(("title", "Novo"), ("artist", "Fulano")))
        faltas = [str(item) for item in verify_copy(meta, edicao, copia)]
        assert faltas == ["meu_campo", "título da trilha 2"]

    def test_idioma_apagado_vira_und_no_mp4_e_nao_e_falta(self) -> None:
        meta = replace(_meta(), tracks=(TrackInfo(0, "video", "h264", "", "eng"), TrackInfo(1, "audio", "aac")))
        edicao = replace(unchanged_edit(meta), tracks=((0, "", ""), (1, "", "")))
        copia = replace(meta, tracks=(TrackInfo(0, "video", "h264", "", "und"), TrackInfo(1, "audio", "aac")))
        assert verify_copy(meta, edicao, copia) == ()


# --- Gravação de verdade ---------------------------------------------------------

@pytest.fixture
def ffmpeg_tools():
    from videomanager.infrastructure.system.binaries import find_tools
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")
    return tools


def _run(tools: FFmpegTools, *args: str) -> None:
    from videomanager.infrastructure.system.binaries import subprocess_kwargs
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args], check=True, timeout=60,
                   **subprocess_kwargs())


_RECEITAS = {
    "mp4": ["-f", "lavfi", "-i", "testsrc2=s=160x120:r=10:d=1", "-f", "lavfi", "-i", "sine=d=1",
            "-c:v", "libx264", "-c:a", "aac"],
    "mkv": ["-f", "lavfi", "-i", "testsrc2=s=160x120:r=10:d=1", "-f", "lavfi", "-i", "sine=d=1",
            "-c:v", "libx264", "-c:a", "aac"],
    "webm": ["-f", "lavfi", "-i", "testsrc2=s=160x120:r=10:d=1", "-f", "lavfi", "-i", "sine=d=1",
             "-c:v", "libvpx-vp9", "-c:a", "libopus"],
    "mp3": ["-f", "lavfi", "-i", "sine=d=1", "-c:a", "libmp3lame"],
    "m4a": ["-f", "lavfi", "-i", "sine=d=1", "-c:a", "aac"],
    "flac": ["-f", "lavfi", "-i", "sine=d=1", "-c:a", "flac"],
    "opus": ["-f", "lavfi", "-i", "sine=d=1", "-c:a", "libopus"],
    "ogg": ["-f", "lavfi", "-i", "sine=d=1", "-c:a", "libvorbis"],
    "wav": ["-f", "lavfi", "-i", "sine=d=1"],
}
# O que cada formato não guarda, medido: a lista que a aba mostra tem de bater.
_NAO_GUARDA = {
    "mp4": ["meu_campo"], "m4a": ["meu_campo"], "mkv": [], "webm": [], "opus": [], "ogg": [],
    "mp3": ["título da trilha 1", "idioma da trilha 1"],
    "flac": ["título da trilha 1", "idioma da trilha 1"],
    "wav": ["meu_campo", "título da trilha 1", "idioma da trilha 1"],
}


def _md5_das_trilhas(tools: FFmpegTools, path: Path, meta: FileMetadata) -> list[str]:
    from videomanager.infrastructure.system.binaries import subprocess_kwargs
    kwargs = subprocess_kwargs()
    kwargs["stdout"] = subprocess.PIPE
    resultado = []
    for index in range(len(meta.streams)):
        if meta.cover and index == meta.cover.index:
            continue
        saida = subprocess.run([tools.ffmpeg_str, "-v", "error", "-i", str(path), "-map", f"0:{index}",
                                "-c", "copy", "-f", "md5", "-"], timeout=60, **kwargs)
        resultado.append(saida.stdout.decode().strip())
    return resultado


def _salvar(tools: FFmpegTools, meta: FileMetadata, edicao: MetadataEdit, pasta: Path):
    from videomanager.infrastructure.ffmpeg.metadata import save_metadata
    from videomanager.infrastructure.system.process import ProcessControl
    return save_metadata(meta, edicao, tools, ProcessControl(), pasta)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("formato", sorted(_RECEITAS))
def test_copia_leva_as_tags_e_os_mesmos_pacotes(ffmpeg_tools, tmp_path, formato) -> None:
    from videomanager.infrastructure.ffmpeg.metadata import read_metadata

    origem = tmp_path / f"origem.{formato}"
    _run(ffmpeg_tools, *_RECEITAS[formato], "-metadata", "comment=apagar", str(origem))
    antes = hashlib.sha256(origem.read_bytes()).hexdigest()
    meta = read_metadata(origem, ffmpeg_tools)
    base = unchanged_edit(meta)
    tags = dict(base.tags)
    tags.update(title="Título ç", artist="Artista", meu_campo="livre")
    tags = {key: ("" if key.lower() == "comment" else value) for key, value in tags.items()}
    trilhas = tuple((i, "Dublado" if n == 0 else t, "por" if n == 0 else lang)
                    for n, (i, t, lang) in enumerate(base.tracks))
    salvo = _salvar(ffmpeg_tools, meta, MetadataEdit(tuple(tags.items()), trilhas), tmp_path)

    assert salvo.path == tmp_path / f"origem (metadados).{formato}"
    copia = read_metadata(salvo.path, ffmpeg_tools)
    gravadas = {key.lower(): value for key, value in copia.tags}
    assert (gravadas["title"], gravadas["artist"]) == ("Título ç", "Artista")
    assert "comment" not in gravadas
    assert [str(item) for item in salvo.not_saved] == _NAO_GUARDA[formato]
    assert _md5_das_trilhas(ffmpeg_tools, salvo.path, copia) == _md5_das_trilhas(ffmpeg_tools, origem, meta)
    assert copia.duration == pytest.approx(meta.duration, abs=0.1)
    assert hashlib.sha256(origem.read_bytes()).hexdigest() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([origem.name, salvo.path.name])


def _capa(tools: FFmpegTools, pasta: Path, nome: str, cor: str) -> Path:
    imagem = pasta / nome
    _run(tools, "-f", "lavfi", "-i", f"color=c={cor}:s=64x64:d=1", "-frames:v", "1", str(imagem))
    return imagem


@pytest.mark.ffmpeg
@pytest.mark.parametrize("formato", ["mp4", "m4a", "mp3", "flac", "mkv"])
def test_capa_entra_troca_e_sai(ffmpeg_tools, tmp_path, formato) -> None:
    from videomanager.infrastructure.ffmpeg.metadata import cover_bytes, read_metadata

    origem = tmp_path / f"origem.{formato}"
    _run(ffmpeg_tools, *_RECEITAS[formato], str(origem))
    vermelha, azul = _capa(ffmpeg_tools, tmp_path, "vermelha.jpg", "red"), _capa(ffmpeg_tools, tmp_path, "azul.png", "blue")
    meta = read_metadata(origem, ffmpeg_tools)
    trilhas_da_origem = [kind for kind, _ in meta.streams]

    com_capa = read_metadata(_salvar(ffmpeg_tools, meta, replace(unchanged_edit(meta), cover_image=vermelha),
                                     tmp_path).path, ffmpeg_tools)
    assert cover_bytes(com_capa, ffmpeg_tools) == vermelha.read_bytes()
    # Mantida numa edição de tags, a capa continua capa, idêntica (no MKV ela
    # voltava como trilha de vídeo de um quadro).
    mantida = read_metadata(_salvar(ffmpeg_tools, com_capa, replace(unchanged_edit(com_capa), tags=(("title", "X"),)),
                                    tmp_path).path, ffmpeg_tools)
    assert cover_bytes(mantida, ffmpeg_tools) == vermelha.read_bytes()
    assert [kind for i, (kind, _) in enumerate(mantida.streams) if i != mantida.cover.index] == trilhas_da_origem
    trocada = read_metadata(_salvar(ffmpeg_tools, mantida, replace(unchanged_edit(mantida), cover_image=azul),
                                    tmp_path).path, ffmpeg_tools)
    assert cover_bytes(trocada, ffmpeg_tools) == azul.read_bytes()
    sem = _salvar(ffmpeg_tools, trocada, replace(unchanged_edit(trocada), remove_cover=True), tmp_path)
    sem_capa = read_metadata(sem.path, ffmpeg_tools)
    assert sem_capa.cover is None and [kind for kind, _ in sem_capa.streams] == trilhas_da_origem
    assert sem.not_saved == ()


@pytest.mark.ffmpeg
def test_anexo_webp_do_mkv_e_capa_mantida_e_removivel(ffmpeg_tools, tmp_path) -> None:
    """Os MKV baixados do YouTube trazem a capa como anexo WebP, que o ffmpeg não
    expõe como imagem."""
    from videomanager.infrastructure.ffmpeg.metadata import cover_bytes, read_metadata

    webp = tmp_path / "capa.webp"
    _run(ffmpeg_tools, "-f", "lavfi", "-i", "color=c=green:s=64x64:d=1", "-frames:v", "1", "-c:v", "libwebp", str(webp))
    origem = tmp_path / "baixado.mkv"
    _run(ffmpeg_tools, *_RECEITAS["mkv"], "-attach", str(webp), "-metadata:s:t:0", "mimetype=image/webp",
         "-metadata:s:t:0", "filename=cover.webp", str(origem))
    meta = read_metadata(origem, ffmpeg_tools)
    assert meta.cover is not None and meta.cover.stream == "attachment"
    mantida = read_metadata(_salvar(ffmpeg_tools, meta, replace(unchanged_edit(meta), tags=(("title", "X"),)),
                                    tmp_path).path, ffmpeg_tools)
    assert cover_bytes(mantida, ffmpeg_tools) == webp.read_bytes()
    removida = read_metadata(_salvar(ffmpeg_tools, meta, replace(unchanged_edit(meta), remove_cover=True),
                                     tmp_path).path, ffmpeg_tools)
    assert removida.cover is None


@pytest.mark.ffmpeg
def test_gravacao_cancelada_nao_deixa_nada(ffmpeg_tools, tmp_path) -> None:
    from videomanager.infrastructure.ffmpeg.metadata import read_metadata, save_metadata
    from videomanager.infrastructure.system.process import ProcessControl

    origem = tmp_path / "origem.mkv"
    _run(ffmpeg_tools, *_RECEITAS["mkv"], str(origem))
    meta = read_metadata(origem, ffmpeg_tools)
    control = ProcessControl()
    control.cancel()
    with pytest.raises(JobCancelled):
        save_metadata(meta, unchanged_edit(meta), ffmpeg_tools, control, tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [origem.name]


@pytest.mark.ffmpeg
def test_sem_permissao_na_pasta_a_copia_vai_para_os_downloads(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    from videomanager.infrastructure.ffmpeg import metadata as modulo

    origem = tmp_path / "origem.mp3"
    _run(ffmpeg_tools, *_RECEITAS["mp3"], str(origem))
    meta = modulo.read_metadata(origem, ffmpeg_tools)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(modulo.FFmpegCatalog, "writable", lambda self, pasta: pasta != tmp_path)
    salvo = _salvar(ffmpeg_tools, meta, unchanged_edit(meta), downloads)
    assert salvo.fallback_used and salvo.path.parent == downloads


# --- Aba e janela -------------------------------------------------------------------

@pytest.fixture
def painel(desktop_app, ffmpeg_tools):
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime
    from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel

    panel = MetadataPanel(Preferences(), lambda: ffmpeg_tools, runtime=build_desktop_runtime(audio_enabled=False))
    yield panel
    panel.shutdown()
    panel.deleteLater()


@pytest.mark.ffmpeg
def test_aba_abre_edita_e_salva_a_copia(painel, ffmpeg_tools, tmp_path, wait_until, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox
    from videomanager.infrastructure.ffmpeg.metadata import read_metadata

    origem = tmp_path / "musica.mp3"
    _run(ffmpeg_tools, *_RECEITAS["mp3"], "-metadata", "title=Antigo", "-metadata", "meu_campo=x", str(origem))
    painel.open_file(origem)
    wait_until(lambda: painel._meta is not None, timeout=20)
    assert painel._fields["title"].text() == "Antigo" and not painel.has_unsaved_changes
    assert [painel._others.item(r, 0).text() for r in range(painel._others.rowCount())] == ["meu_campo"]

    painel._fields["title"].setText("Novo")
    painel._fields["artist"].setText("Artista")
    painel._others.selectRow(0)
    painel._remove_others()
    assert painel.has_unsaved_changes and painel._discard.isEnabled()
    perguntas = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: perguntas.append(a) or QMessageBox.StandardButton.Cancel)
    assert not painel.confirm_discard() and len(perguntas) == 1

    painel.save()
    assert not painel._save.isEnabled()  # não salva duas vezes ao mesmo tempo
    wait_until(lambda: painel._saved is not None, timeout=30)
    copia = read_metadata(painel._saved.path, ffmpeg_tools)
    gravadas = {key.lower(): value for key, value in copia.tags}
    assert (gravadas["title"], gravadas["artist"]) == ("Novo", "Artista") and "meu_campo" not in gravadas
    assert painel._saved.path.name in painel._result.text() and painel._reveal.isVisibleTo(painel)
    # A cópia guardou o que se pediu: fechar não pergunta mais nada.
    assert not painel.has_unsaved_changes and painel.confirm_discard() and len(perguntas) == 1
    assert painel._runner.active == 0


def test_janela_tem_a_aba_com_menu_e_sem_fila(desktop_app, monkeypatch) -> None:
    from PySide6.QtGui import QKeySequence
    from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                        build_processing_service)
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt import strings
    from videomanager.presentation.qt.main_window import _TAB_CONVERT, _TAB_EDIT, _TAB_METADATA, MainWindow

    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    janela = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    try:
        janela.show()
        assert janela._tabs.tabText(_TAB_METADATA) == strings.TAB_METADATA
        janela._tabs.setCurrentIndex(_TAB_METADATA)
        acoes = [a.text() for a in janela._file_menu.actions() if not a.isSeparator()]
        assert acoes == [strings.ACTION_META_OPEN, strings.ACTION_META_SAVE, strings.ACTION_QUIT]
        assert janela._meta_open_action.shortcut() == QKeySequence("Ctrl+O")
        assert janela._meta_save_action.shortcut() == QKeySequence("Ctrl+S")
        # Um atalho, uma ação: os das outras abas desligam aqui, e vice-versa.
        assert janela._convert_add_action.shortcut().isEmpty() and janela._save_proj_action.shortcut().isEmpty()
        assert not janela._queue_panel.isVisible()
        for aba in (_TAB_CONVERT, _TAB_EDIT):
            janela._tabs.setCurrentIndex(aba)
            assert janela._meta_open_action.shortcut().isEmpty() and janela._meta_save_action.shortcut().isEmpty()
        janela._tabs.setCurrentIndex(_TAB_CONVERT)
        assert janela._queue_panel.isVisible()
    finally:
        janela._edit.shutdown()
        janela._convert.shutdown()
        janela._metadata.shutdown()
        janela.deleteLater()


def test_fechar_com_metadados_nao_salvos_pergunta(desktop_app, monkeypatch) -> None:
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                        build_processing_service)
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.main_window import MainWindow

    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    janela = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    try:
        painel = janela._metadata_panel()
        painel._install(_meta(), None)
        painel._fields["title"].setText("Mudou")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
        evento = QCloseEvent()
        janela.closeEvent(evento)
        assert not evento.isAccepted()
    finally:
        janela._edit.shutdown()
        janela._convert.shutdown()
        janela._metadata.shutdown()
        janela.deleteLater()


def test_tabela_nao_pede_o_palpite_fixo_de_192px(desktop_app) -> None:
    from videomanager.presentation.qt.panels.metadata_panel import _Table
    tabela = _Table(2)
    try:
        assert tabela.sizeHint().height() == tabela.minimumHeight() < 192
    finally:
        tabela.deleteLater()


# --- Alça que amplia os campos de várias linhas ----------------------------------

_LINHAS = "\n".join(f"linha {n} da descrição" for n in range(30))

def _frase(tabela, larguras: float = 3.4) -> str:
    """Um texto de ``larguras`` vezes a largura da coluna de valor, na fonte que a tabela tem.

    Com 3,4 larguras ele ocupa 4 linhas na coluna de agora e 3 numa coluna 50% mais larga,
    em qualquer fonte e abaixo do teto de 8 linhas. Um texto de tamanho fixo ocupava 8 na
    DejaVu da CI — o teto —, e o teste que esperava ver a linha encolher falhava.
    """
    unidade = "uma frase comprida que quebra conforme a largura "
    disponivel = tabela.horizontalHeader().sectionSize(1) - 12  # o preenchimento da célula
    return unidade * max(1, round(larguras * disponivel / tabela.fontMetrics().horizontalAdvance(unidade)))


_SINOPSE = ("Primeiro parágrafo da sinopse, longo o bastante para passar da largura da coluna de valor e quebrar.\n"
            "Segundo parágrafo.\nTerceiro parágrafo.")


@pytest.fixture
def painel_visivel(desktop_app):
    """Painel de verdade, aberto e com um arquivo: a alça só existe com o layout feito."""
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime
    from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel

    painel = MetadataPanel(Preferences(), lambda: TOOLS, runtime=build_desktop_runtime(audio_enabled=False))
    painel.resize(1000, 900)
    painel.show()
    desktop_app.processEvents()
    painel._install(_meta(tags=(("title", "T"), ("comment", "um\ndois"), ("description", _LINHAS),
                                ("synopsis", _SINOPSE), ("purl", "https://exemplo.com/video"))), None)
    _assentar(desktop_app)
    yield painel
    painel.shutdown()
    painel.deleteLater()


def _assentar(app) -> None:
    """Deixa o layout terminar: cada contêiner aninhado pede o seguinte numa volta do laço."""
    for _ in range(10):
        app.processEvents()


def _arrastar(alca, dy: int) -> None:
    """Aperta no meio da alça, move ``dy`` px na vertical e solta — eventos reais."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    inicio = QPoint(alca.width() // 2, alca.height() // 2)
    QTest.mousePress(alca, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio)
    QTest.mouseMove(alca, inicio + QPoint(0, dy))
    QTest.mouseRelease(alca, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio + QPoint(0, dy))


def test_so_os_campos_de_varias_linhas_tem_alca(painel_visivel) -> None:
    from PySide6.QtWidgets import QPlainTextEdit
    from videomanager.presentation.qt.panels.metadata_panel import _MULTILINE

    assert set(painel_visivel._grips) == set(_MULTILINE)
    assert all(isinstance(painel_visivel._fields[chave], QPlainTextEdit) for chave in _MULTILINE)


def test_arrastar_a_alca_amplia_so_o_campo_dela(painel_visivel, desktop_app) -> None:
    campos, alcas = painel_visivel._fields, painel_visivel._grips
    descricao, comentario = campos["description"].height(), campos["comment"].height()
    _arrastar(alcas["description"], 120)
    _assentar(desktop_app)
    assert campos["description"].height() == descricao + 120
    assert campos["comment"].height() == comentario  # o irmão não se mexe
    # A alça fica colada ao campo, na largura dele, e o rótulo continua no topo da linha:
    topo = lambda w: w.mapTo(painel_visivel, w.rect().topLeft())  # noqa: E731
    assert topo(alcas["description"]).y() == topo(campos["description"]).y() + campos["description"].height()
    assert alcas["description"].width() == campos["description"].width()
    rotulo = painel_visivel._labels[list(campos).index("description")]
    assert topo(rotulo).y() == topo(campos["description"]).y()

    _arrastar(alcas["comment"], 40)
    _assentar(desktop_app)
    assert campos["comment"].height() == comentario + 40 and campos["description"].height() == descricao + 120


def test_o_campo_nao_encolhe_abaixo_do_tamanho_de_nascenca_e_o_clique_duplo_o_restaura(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    campo, alca = painel_visivel._fields["description"], painel_visivel._grips["description"]
    base = campo.height()
    _arrastar(alca, -60)
    assert campo.height() == base  # o piso é a altura de nascença
    _arrastar(alca, 90)
    assert campo.height() == base + 90
    QTest.mouseDClick(alca, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      QPoint(alca.width() // 2, alca.height() // 2))
    assert campo.height() == base


def test_ampliar_o_campo_nao_conta_como_alteracao_nem_mexe_no_texto(painel_visivel) -> None:
    antes = painel_visivel.current_edit()
    assert not painel_visivel.has_unsaved_changes
    _arrastar(painel_visivel._grips["description"], 100)
    assert painel_visivel.current_edit() == antes and not painel_visivel.has_unsaved_changes
    assert painel_visivel._fields["description"].toPlainText() == _LINHAS


def test_o_tamanho_escolhido_vale_para_o_proximo_arquivo_e_para_descartar(painel_visivel) -> None:
    campo = painel_visivel._fields["description"]
    base = campo.height()
    _arrastar(painel_visivel._grips["description"], 70)
    painel_visivel._install(_meta(nome="b.mp4", tags=(("description", "outra"),)), None)
    assert campo.height() == base + 70
    painel_visivel._fields["description"].setPlainText("mexido")
    painel_visivel._discard_changes()
    assert campo.height() == base + 70 and campo.toPlainText() == "outra"


@pytest.mark.parametrize("tema", ["dark", "light"])
def test_a_alca_nao_pinta_fundo_proprio(painel_visivel, desktop_app, tema) -> None:
    """Sem ``role=plain`` o contêiner herda o fundo da janela e pinta um retângulo
    escuro sobre a superfície do grupo: a cor tem de ser a do grupo."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor
    from videomanager.presentation.qt.theme import palette, stylesheet

    anterior = desktop_app.styleSheet()
    desktop_app.setStyleSheet(stylesheet(tema))
    try:
        _assentar(desktop_app)
        imagem = painel_visivel.grab().toImage()
        alca = painel_visivel._grips["description"]
        canto = alca.mapTo(painel_visivel, QPoint(2, 1))
        assert imagem.pixelColor(canto) == QColor(palette(tema)["surface"])
    finally:
        desktop_app.setStyleSheet(anterior)


def test_a_alca_nao_entra_na_ordem_do_tab(painel_visivel) -> None:
    """Os campos usam ``setTabChangesFocus``: uma parada de foco a mais entre o
    comentário e a descrição prenderia quem navega pelo teclado numa alça sem teclado."""
    from PySide6.QtCore import Qt

    assert all(alca.focusPolicy() == Qt.FocusPolicy.NoFocus for alca in painel_visivel._grips.values())


def test_a_dica_da_alca_segue_o_idioma(painel_visivel) -> None:
    from videomanager.presentation.qt import i18n, strings

    alca = painel_visivel._grips["description"]
    em_portugues = alca.toolTip()
    assert em_portugues == strings.META_GROW_TIP and em_portugues
    i18n.apply_language("en")
    assert alca.toolTip() == strings.META_GROW_TIP != em_portugues


# --- Tabela "Outros campos": colunas, linhas e altura ------------------------------

def _mouse(widget, de, para) -> None:
    """Aperta em ``de``, move até ``para`` e solta, no widget dado — eventos reais."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, de)
    QTest.mouseMove(widget, para)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, para)


def _arrastar_divisao(tabela, dx: int) -> None:
    """Arrasta a divisão entre as duas colunas pelo cabeçalho."""
    from PySide6.QtCore import QPoint

    cabecalho = tabela.horizontalHeader()
    x = cabecalho.sectionViewportPosition(0) + cabecalho.sectionSize(0) - 1
    y = cabecalho.height() // 2
    _mouse(cabecalho.viewport(), QPoint(x, y), QPoint(x + dx, y))


def _alca_da_linha(tabela, linha: int):
    """Ponto da alça, no pé da linha, na área visível da tabela."""
    from PySide6.QtCore import QPoint

    return QPoint(tabela.viewport().width() // 2, tabela.rowViewportPosition(linha) + tabela.rowHeight(linha) - 3)


def _arrastar_alca_da_linha(tabela, linha: int, dy: int) -> None:
    ponto = _alca_da_linha(tabela, linha)
    _mouse(tabela.viewport(), ponto, type(ponto)(ponto.x(), ponto.y() + dy))


def _linha_do_campo(tabela, nome: str) -> int:
    return next(r for r in range(tabela.rowCount()) if tabela.item(r, 0).text() == nome)


def _larguras(tabela) -> tuple[int, int]:
    cabecalho = tabela.horizontalHeader()
    return cabecalho.sectionSize(0), cabecalho.sectionSize(1)


def test_a_divisao_das_colunas_segue_a_largura_ate_alguem_arrastar(painel_visivel, desktop_app) -> None:
    tabela = painel_visivel._others
    primeira, segunda = _larguras(tabela)
    assert abs(primeira - segunda) <= 1  # nascem metade e metade, como antes
    painel_visivel.resize(800, 900)
    _assentar(desktop_app)
    primeira, segunda = _larguras(tabela)
    assert abs(primeira - segunda) <= 1  # e continuam assim quando a janela muda

    _arrastar_divisao(tabela, 50)
    _assentar(desktop_app)
    escolhida = _larguras(tabela)[0]
    assert escolhida == primeira + 50 and not tabela._split_free
    painel_visivel.resize(1000, 900)
    _assentar(desktop_app)
    assert _larguras(tabela)[0] == escolhida  # depois de arrastar, a escolha é do usuário


def test_a_coluna_nunca_fica_menor_que_o_minimo(painel_visivel, desktop_app) -> None:
    from videomanager.presentation.qt.panels.metadata_panel import _MIN_COLUMN

    tabela = painel_visivel._others
    # Até perto da borda esquerda do cabeçalho: o Qt ignora posição negativa.
    _arrastar_divisao(tabela, -(_larguras(tabela)[0] - 5))
    _assentar(desktop_app)
    assert _larguras(tabela)[0] == _MIN_COLUMN


def test_a_tabela_de_outros_campos_mantem_o_visual_de_sempre(painel_visivel) -> None:
    tabela = painel_visivel._others
    assert not tabela.verticalHeader().isVisible()  # sem coluna de números nem quadrado no canto
    assert tabela.wordWrap()


def test_a_linha_se_adapta_ao_texto_sem_reticencias(painel_visivel) -> None:
    """Texto de várias linhas numa linha de 30 px era cortado com ``…`` no fim da
    primeira, por mais larga que fosse a coluna."""
    tabela = painel_visivel._others
    padrao = tabela.verticalHeader().defaultSectionSize()
    sinopse, purl = _linha_do_campo(tabela, "synopsis"), _linha_do_campo(tabela, "purl")
    assert tabela.rowHeight(purl) == padrao  # uma linha de texto: nada muda
    assert tabela.rowHeight(sinopse) > padrao  # várias linhas: a linha cresce
    assert tabela.sizeHintForRow(sinopse) <= tabela.rowHeight(sinopse)  # e cabe o texto todo


def test_alargar_a_coluna_reduz_a_linha_que_se_adapta(painel_visivel, desktop_app) -> None:
    tabela = painel_visivel._others
    painel_visivel._install(_meta(tags=(("longa", _frase(tabela)),)), None)
    _assentar(desktop_app)
    estreita = tabela.rowHeight(0)
    assert tabela.sizeHintForRow(0) <= estreita
    _arrastar_divisao(tabela, -120)  # o valor ganha 120 px
    _assentar(desktop_app)
    larga = tabela.rowHeight(0)
    assert larga < estreita and tabela.sizeHintForRow(0) <= larga  # menos linhas, e o texto continua cabendo
    _arrastar_divisao(tabela, 120)  # e volta a ficar apertado
    _assentar(desktop_app)
    assert tabela.rowHeight(0) == estreita


def test_o_ajuste_automatico_tem_teto_e_a_alca_vai_alem(painel_visivel, desktop_app) -> None:
    from videomanager.presentation.qt.panels.metadata_panel import _AUTO_ROW_LINES

    tabela = painel_visivel._others
    painel_visivel._install(_meta(tags=(("longa", "\n".join(f"linha {n}" for n in range(60))),)), None)
    _assentar(desktop_app)
    padrao = tabela.verticalHeader().defaultSectionSize()
    teto = padrao + (_AUTO_ROW_LINES - 1) * tabela.fontMetrics().lineSpacing()
    assert tabela.rowHeight(0) == teto < tabela.sizeHintForRow(0)  # 60 linhas não empurram a aba
    _arrastar_alca_da_linha(tabela, 0, 300)
    _assentar(desktop_app)
    assert tabela.rowHeight(0) == teto + 300  # a alça não tem teto


def test_a_alca_da_linha_a_amplia_e_a_escolha_do_usuario_prevalece(painel_visivel, desktop_app) -> None:
    tabela = painel_visivel._others
    padrao = tabela.verticalHeader().defaultSectionSize()
    purl, sinopse = _linha_do_campo(tabela, "purl"), _linha_do_campo(tabela, "synopsis")
    _arrastar_alca_da_linha(tabela, purl, 70)
    _assentar(desktop_app)
    assert tabela.rowHeight(purl) == padrao + 70 and tabela._is_manual(purl)
    assert not tabela._is_manual(sinopse)  # só a linha arrastada
    escolhida = tabela.rowHeight(purl)
    _arrastar_divisao(tabela, 40)  # mudar a largura reajusta as outras, e não a que o usuário ajustou
    _assentar(desktop_app)
    assert tabela.rowHeight(purl) == escolhida
    _arrastar_alca_da_linha(tabela, purl, -500)  # o piso é a altura de nascença
    _assentar(desktop_app)
    assert tabela.rowHeight(purl) == padrao


def test_clique_duplo_na_alca_devolve_o_ajuste_automatico(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tabela = painel_visivel._others
    painel_visivel._install(_meta(tags=(("longa", _frase(tabela)),)), None)
    _assentar(desktop_app)
    automatica = tabela.rowHeight(0)
    _arrastar_alca_da_linha(tabela, 0, 90)
    _assentar(desktop_app)
    assert tabela.rowHeight(0) == automatica + 90 and tabela._is_manual(0)
    QTest.mouseDClick(tabela.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      _alca_da_linha(tabela, 0))
    _assentar(desktop_app)
    assert tabela.rowHeight(0) == automatica and not tabela._is_manual(0)
    _arrastar_divisao(tabela, -120)  # voltou a se adaptar à largura
    _assentar(desktop_app)
    assert tabela.rowHeight(0) < automatica


def test_a_alca_da_linha_nao_seleciona_nem_abre_editor(painel_visivel, desktop_app) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    tabela = painel_visivel._others
    tabela.clearSelection()
    _arrastar_alca_da_linha(tabela, _linha_do_campo(tabela, "purl"), 20)
    _assentar(desktop_app)
    assert not tabela.selectedIndexes()
    assert tabela.state() != QAbstractItemView.State.EditingState


def test_o_cursor_muda_sobre_a_alca_da_linha_e_volta_fora_dela(painel_visivel, desktop_app) -> None:
    """Pelo sistema de janelas, que é por onde o mouse de verdade chega: o movimento
    sem botão apertado só existe aí."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    tabela, viewport = painel_visivel._others, painel_visivel._others.viewport()
    janela = painel_visivel.windowHandle()
    sobre = viewport.mapTo(painel_visivel, _alca_da_linha(tabela, 0))
    fora = viewport.mapTo(painel_visivel, QPoint(viewport.width() // 2, tabela.rowViewportPosition(0) + 8))
    QTest.mouseMove(janela, sobre)
    _assentar(desktop_app)
    assert viewport.cursor().shape() == Qt.CursorShape.SizeVerCursor
    QTest.mouseMove(janela, fora)
    _assentar(desktop_app)
    assert viewport.cursor().shape() != Qt.CursorShape.SizeVerCursor


def test_a_alca_de_cada_linha_e_desenhada(painel_visivel, desktop_app) -> None:
    """O traço no pé da linha tem de aparecer: é o que diz onde arrastar."""
    tabela = painel_visivel._others
    tabela.clearSelection()
    _assentar(desktop_app)
    imagem = tabela.grab().toImage()
    y = tabela.viewport().y() + tabela.rowViewportPosition(0) + tabela.rowHeight(0) - 6
    x = tabela.viewport().x() + tabela.viewport().width() // 2
    assert imagem.pixelColor(x, y) != imagem.pixelColor(x - 40, y)  # traço x fundo da linha


def test_a_dica_da_alca_da_linha_aparece_sobre_ela_e_segue_o_idioma(painel_visivel, monkeypatch) -> None:
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QApplication
    from videomanager.presentation.qt import i18n, strings
    from videomanager.presentation.qt.panels import metadata_panel

    mostradas: list[str] = []

    class DicaFalsa:  # o QToolTip de verdade guarda o texto antigo por 300 ms depois de escondido
        @staticmethod
        def showText(_posicao, texto, _widget=None) -> None:  # noqa: N802
            mostradas.append(texto)

    monkeypatch.setattr(metadata_panel, "QToolTip", DicaFalsa)
    tabela = painel_visivel._others
    viewport = tabela.viewport()

    def pedir_dica(ponto: QPoint) -> None:
        QApplication.sendEvent(viewport, QHelpEvent(QEvent.Type.ToolTip, ponto, viewport.mapToGlobal(ponto)))

    sobre = _alca_da_linha(tabela, 0)
    fora = QPoint(viewport.width() // 2, tabela.rowViewportPosition(0) + 8)
    pedir_dica(fora)
    assert mostradas == []  # fora da faixa da alça não há dica
    pedir_dica(sobre)
    assert mostradas == [strings.META_ROW_TIP]
    i18n.apply_language("en")
    pedir_dica(sobre)
    assert mostradas[-1] == strings.META_ROW_TIP != mostradas[0]


def test_a_tabela_acompanha_o_que_a_adaptacao_das_linhas_acrescenta(painel_visivel, desktop_app) -> None:
    """Mede o que a tabela **pede** (``sizeHint``): a sobra da coluna ela sempre recebeu, e
    é o layout que a reparte."""
    from videomanager.presentation.qt.panels.metadata_panel import _AUTO_ROW_LINES

    tabela = painel_visivel._others
    base = tabela._base_min
    # Só linhas de uma linha de texto: a tabela pede o que sempre pediu.
    painel_visivel._install(_meta(tags=(("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5"))), None)
    _assentar(desktop_app)
    assert tabela.sizeHint().height() == base
    # Uma sinopse de várias linhas: a tabela passa a pedir mais, e a linha ajustada cabe na área visível.
    painel_visivel._install(_meta(tags=(("synopsis", _SINOPSE),)), None)
    _assentar(desktop_app)
    assert tabela.sizeHint().height() > base and tabela.viewport().height() >= tabela.rowHeight(0)
    # Sessenta linhas: o pedido tem teto, e a alça da tabela vai além dele.
    painel_visivel._install(_meta(tags=(("longa", "\n".join(f"linha {n}" for n in range(60))),)), None)
    _assentar(desktop_app)
    teto = base + (_AUTO_ROW_LINES - 1) * tabela.fontMetrics().lineSpacing()
    assert tabela.sizeHint().height() == teto
    antes = tabela.height()
    _arrastar(painel_visivel._others_grip, 50)
    _assentar(desktop_app)
    assert tabela.height() == antes + 50 and tabela.sizeHint().height() == antes + 50


def test_linha_mais_alta_que_a_tabela_rola_por_pixel(desktop_app) -> None:
    """Numa tabela espremida (janela baixa) uma linha ajustada ao texto passa da área
    visível; por item, o meio dela não se alcançaria."""
    from PySide6.QtWidgets import QAbstractItemView, QTableWidgetItem
    from videomanager.presentation.qt.panels.metadata_panel import _Table

    tabela = _Table(2, adjustable=True)
    try:
        for linha, valor in enumerate(("curto", "\n".join(f"linha {n}" for n in range(60)), "curto")):
            tabela.insertRow(linha)
            tabela.setItem(linha, 0, QTableWidgetItem(f"campo{linha}"))
            tabela.setItem(linha, 1, QTableWidgetItem(valor))
        tabela.setFixedSize(400, 126)  # o piso de nascença: 90 px de área visível
        tabela.show()
        _assentar(desktop_app)
        assert tabela.rowHeight(1) > tabela.viewport().height()  # a premissa: a linha passa da área visível
        assert tabela.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
        barra = tabela.verticalScrollBar()
        assert barra.maximum() > 50  # por item seria 2 (uma linha por passo)
        topo = tabela.rowViewportPosition(1)
        barra.setValue(barra.value() + 20)
        assert tabela.rowViewportPosition(1) == topo - 20  # anda 20 px, e não a linha inteira
    finally:
        tabela.close()
        tabela.deleteLater()


def test_ajustar_colunas_linhas_e_tabela_nao_conta_como_alteracao(painel_visivel, desktop_app) -> None:
    tabela = painel_visivel._others
    antes = painel_visivel.current_edit()
    _arrastar_divisao(tabela, 30)
    _arrastar_alca_da_linha(tabela, 0, 40)
    _arrastar(painel_visivel._others_grip, 50)
    _assentar(desktop_app)
    assert painel_visivel.current_edit() == antes and not painel_visivel.has_unsaved_changes


def test_editar_o_valor_de_uma_linha_reajusta_a_altura_dela(painel_visivel, desktop_app) -> None:
    tabela = painel_visivel._others
    purl = _linha_do_campo(tabela, "purl")
    padrao = tabela.verticalHeader().defaultSectionSize()
    assert tabela.rowHeight(purl) == padrao
    tabela.item(purl, 1).setText("um\ndois\ntrês\nquatro")
    _assentar(desktop_app)
    assert tabela.rowHeight(purl) > padrao and tabela.sizeHintForRow(purl) <= tabela.rowHeight(purl)
    tabela.item(purl, 1).setText("curto")
    _assentar(desktop_app)
    assert tabela.rowHeight(purl) == padrao


def test_clicar_numa_celula_seleciona_a_linha_e_remover_campo_a_apaga(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tabela = painel_visivel._others
    antes = tabela.rowCount()
    linha = _linha_do_campo(tabela, "purl")
    celula = tabela.visualRect(tabela.model().index(linha, 0))
    QTest.mouseClick(tabela.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     celula.center() - type(celula.center())(0, 4))  # longe da faixa da alça
    assert {i.row() for i in tabela.selectedIndexes()} == {linha}
    painel_visivel._remove_others()
    assert tabela.rowCount() == antes - 1 and painel_visivel.has_unsaved_changes
    assert "purl" not in {tabela.item(r, 0).text() for r in range(tabela.rowCount())}


def test_as_linhas_voltam_ao_ajuste_automatico_em_outro_arquivo_e_a_divisao_fica(painel_visivel, desktop_app) -> None:
    tabela = painel_visivel._others
    _arrastar_alca_da_linha(tabela, 0, 60)
    _arrastar_divisao(tabela, 40)
    _assentar(desktop_app)
    divisao = _larguras(tabela)[0]
    painel_visivel._install(_meta(nome="b.mp4", tags=(("synopsis", _SINOPSE), ("purl", "x"))), None)
    _assentar(desktop_app)
    assert not any(tabela._is_manual(r) for r in range(tabela.rowCount()))
    assert tabela.sizeHintForRow(0) <= tabela.rowHeight(0)
    assert _larguras(tabela)[0] == divisao


def test_a_alca_da_tabela_a_amplia_e_o_clique_duplo_a_restaura(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    tabela, alca = painel_visivel._others, painel_visivel._others_grip
    base, campos = tabela.height(), {k: f.height() for k, f in painel_visivel._fields.items()}
    _arrastar(alca, 80)
    _assentar(desktop_app)
    assert tabela.height() == base + 80
    # A alça fica colada à tabela, e os campos de texto não são afetados:
    topo = lambda w: w.mapTo(painel_visivel, w.rect().topLeft())  # noqa: E731
    assert topo(alca).y() == topo(tabela).y() + tabela.height() and alca.width() == tabela.width()
    assert {k: f.height() for k, f in painel_visivel._fields.items()} == campos
    _arrastar(alca, -500)
    _assentar(desktop_app)
    assert tabela.height() == base  # o piso é a altura de nascença
    _arrastar(alca, 60)
    QTest.mouseDClick(alca, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      QPoint(alca.width() // 2, alca.height() // 2))
    _assentar(desktop_app)
    assert tabela.height() == base


def test_a_tabela_de_trilhas_continua_como_era(painel_visivel) -> None:
    from PySide6.QtWidgets import QHeaderView
    from videomanager.presentation.qt.panels.metadata_panel import _TITLE, _Header

    trilhas = painel_visivel._tracks
    cabecalho = trilhas.horizontalHeader()
    assert not trilhas._adjustable and not trilhas.verticalHeader().isVisible()
    assert not isinstance(cabecalho, _Header)
    assert cabecalho.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert cabecalho.sectionResizeMode(_TITLE) == QHeaderView.ResizeMode.Stretch


def test_as_dicas_do_cabecalho_e_da_alca_da_tabela_seguem_o_idioma(painel_visivel) -> None:
    from videomanager.presentation.qt import i18n, strings

    pecas = {
        "colunas": (painel_visivel._others.horizontalHeader(), "META_COLUMN_TIP"),
        "alça": (painel_visivel._others_grip, "META_GROW_TABLE_TIP"),
    }
    antes = {nome: widget.toolTip() for nome, (widget, _) in pecas.items()}
    assert all(antes[nome] == getattr(strings, chave) and antes[nome] for nome, (_, chave) in pecas.items())
    i18n.apply_language("en")
    for nome, (widget, chave) in pecas.items():
        assert widget.toolTip() == getattr(strings, chave) != antes[nome]


def test_a_linha_aberta_continua_com_a_alca_a_vista_e_se_fecha(painel_visivel, desktop_app) -> None:
    """Aberta além do que a tabela mostrava, a linha levava a alça do pé para fora da área
    visível — bem sobre a alça da tabela, logo abaixo — e não se fechava mais."""
    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "purl")
    antes, pedido = tabela.rowHeight(linha), tabela.sizeHint().height()
    _arrastar_alca_da_linha(tabela, linha, 300)  # muito além do teto do ajuste automático
    _assentar(desktop_app)
    assert tabela.rowHeight(linha) == antes + 300
    alca = _alca_da_linha(tabela, linha)
    assert 0 <= alca.y() < tabela.viewport().height()  # a alça de fechar está à vista
    _arrastar_alca_da_linha(tabela, linha, -300)  # fecha arrastando para cima
    _assentar(desktop_app)
    assert tabela.rowHeight(linha) == antes and tabela.sizeHint().height() == pedido  # e a tabela acompanha de volta


def test_arrastar_a_linha_de_volta_ao_ajuste_automatico_a_devolve_ao_automatico(painel_visivel, desktop_app) -> None:
    """Fechada de volta ao que o ajuste daria, a linha não fica presa como "manual": senão
    o piso da tabela continuava segurando uma altura que ninguém mais pediu."""
    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "synopsis")
    piso = tabela.minimumHeight()
    _arrastar_alca_da_linha(tabela, linha, 120)
    _assentar(desktop_app)
    assert tabela._is_manual(linha) and tabela.minimumHeight() > piso
    _arrastar_alca_da_linha(tabela, linha, -120)  # de volta, exatamente
    _assentar(desktop_app)
    assert not tabela._is_manual(linha) and tabela.minimumHeight() == piso
    assert tabela.rowHeight(linha) == tabela._auto_height(linha)  # e é de novo a altura do texto


def test_o_retorno_ao_automatico_nao_depende_de_a_altura_de_agora_ser_igual_a_de_antes(painel_visivel, desktop_app) -> None:
    """A altura automática depende da largura do texto, que muda com a barra de rolagem e com
    a fonte: na CI ela diferia da de antes do arrasto, e a linha de volta ao lugar ficava presa
    como manual. Reproduzido aqui forçando a diferença, sem depender da fonte."""
    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "synopsis")
    antes = tabela.rowHeight(linha)
    _arrastar_alca_da_linha(tabela, linha, 120)
    _assentar(desktop_app)
    original = tabela._auto_height
    tabela._auto_height = lambda row: original(row) + 14  # uma linha de texto a mais, como com outra largura
    try:
        _arrastar_alca_da_linha(tabela, linha, -120)
        _assentar(desktop_app)
        assert not tabela._is_manual(linha)  # encaixou na altura que a linha tinha ao começar o arrasto
    finally:
        del tabela._auto_height
    assert antes > 0


def test_a_linha_encaixa_no_automatico_com_uma_folga_de_alguns_pixels(painel_visivel, desktop_app) -> None:
    from videomanager.presentation.qt.panels.metadata_panel import _SNAP

    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "synopsis")
    _arrastar_alca_da_linha(tabela, linha, 100)
    _assentar(desktop_app)
    _arrastar_alca_da_linha(tabela, linha, -100 + _SNAP)  # a poucos pixels da altura automática
    _assentar(desktop_app)
    assert not tabela._is_manual(linha)
    _arrastar_alca_da_linha(tabela, linha, 100)
    _assentar(desktop_app)
    _arrastar_alca_da_linha(tabela, linha, -100 + _SNAP + 10)  # além da folga: o usuário quis aquela altura
    _assentar(desktop_app)
    assert tabela._is_manual(linha)


def test_fechar_a_linha_para_menos_que_o_automatico_a_mantem_manual(painel_visivel, desktop_app) -> None:
    """Quem fecha a sinopse até 30 px quer vê-la fechada: ela fica como o usuário a deixou."""
    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "synopsis")
    padrao = tabela.verticalHeader().defaultSectionSize()
    _arrastar_alca_da_linha(tabela, linha, -500)
    _assentar(desktop_app)
    assert tabela.rowHeight(linha) == padrao and tabela._is_manual(linha)
    _arrastar_divisao(tabela, 40)  # a largura muda e a linha fechada continua fechada
    _assentar(desktop_app)
    assert tabela.rowHeight(linha) == padrao


def test_a_linha_aberta_tambem_se_fecha_com_o_clique_duplo(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "purl")
    antes = tabela.rowHeight(linha)
    _arrastar_alca_da_linha(tabela, linha, 300)
    _assentar(desktop_app)
    QTest.mouseDClick(tabela.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      _alca_da_linha(tabela, linha))
    _assentar(desktop_app)
    assert tabela.rowHeight(linha) == antes and not tabela._is_manual(linha)


# --- Editor do valor, na tabela "Outros campos" -----------------------------------------

def _abrir_editor(tabela, linha: int, coluna: int, app):
    tabela.setCurrentCell(linha, coluna)
    tabela.editItem(tabela.item(linha, coluna))
    _assentar(app)
    # Pelo índice, e não procurando um filho: o editor fechado só some num deleteLater, que fora do laço não sai.
    return tabela.indexWidget(tabela.model().index(linha, coluna))


def test_o_editor_do_valor_e_um_campo_de_varias_linhas_como_o_da_aba_tags(painel_visivel, desktop_app) -> None:
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "synopsis")
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    assert type(editor) is type(painel_visivel._fields["description"]) is QPlainTextEdit  # o mesmo campo da aba Tags
    assert editor.tabChangesFocus() and editor.toPlainText() == _SINOPSE  # o texto, com as quebras
    assert editor.height() > tabela.rowHeight(linha) or editor.height() >= 3 * editor.fontMetrics().lineSpacing()
    # Mostra o texto todo sem rolar, e fica dentro da área visível da tabela:
    assert editor.verticalScrollBar().maximum() == 0
    assert tabela.viewport().rect().contains(editor.geometry())
    # A coluna do nome continua com o editor de uma linha.
    assert isinstance(_abrir_editor(tabela, linha, 0, desktop_app), QLineEdit)


@pytest.mark.parametrize("tema", ["dark", "light"])
def test_o_editor_mostra_o_texto_todo_sem_rolar_com_o_tema(painel_visivel, desktop_app, tema) -> None:
    """Com o tema a fonte e a folga do campo são outras, e em certas larguras o texto fica
    no limite entre 4 e 5 linhas: o editor nascia com a barra de rolagem, que estreitava o
    texto e o mantinha rolado. Varre as larguras da janela, e não uma só."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from videomanager.presentation.qt.theme import stylesheet

    texto = ("Primeiro parágrafo da sinopse, longo o bastante para quebrar na coluna de valor.\n"
             "Segundo parágrafo.\nTerceiro parágrafo da sinopse.")
    anterior = desktop_app.styleSheet()
    desktop_app.setStyleSheet(stylesheet(tema))
    try:
        _assentar(desktop_app)
        painel_visivel._install(_meta(tags=(("synopsis", texto),)), None)
        tabela = painel_visivel._others
        for largura in range(760, 1500, 37):
            painel_visivel.resize(largura, 900)
            _assentar(desktop_app)
            editor = _abrir_editor(tabela, 0, 1, desktop_app)
            # Rolar só é aceitável quando o editor já ocupa toda a área visível da tabela.
            assert (editor.verticalScrollBar().maximum() == 0 or editor.height() >= tabela.viewport().height()), \
                f"barra de rolagem à toa com a janela em {largura} px"
            assert editor.verticalScrollBar().value() == 0
            assert tabela.viewport().rect().contains(editor.geometry())
            QTest.keyClick(editor, Qt.Key.Key_Escape)
            _assentar(desktop_app)
    finally:
        desktop_app.setStyleSheet(anterior)


def test_o_editor_de_um_texto_muito_longo_tem_teto_e_rola(painel_visivel, desktop_app) -> None:
    from videomanager.presentation.qt.panels.metadata_panel import (
        _EDITOR_CHROME_H, _EDITOR_MAX_LINES, _EDITOR_SPARE_LINES)

    tabela = painel_visivel._others
    painel_visivel._install(_meta(tags=(("longa", "\n".join(f"linha {n}" for n in range(60))),)), None)
    _assentar(desktop_app)
    editor = _abrir_editor(tabela, 0, 1, desktop_app)
    esperado = ((_EDITOR_MAX_LINES + _EDITOR_SPARE_LINES) * editor.fontMetrics().lineSpacing()
                + 2 * editor.document().documentMargin() + _EDITOR_CHROME_H)
    assert editor.height() == int(esperado)
    assert editor.verticalScrollBar().maximum() > 0  # e o resto se alcança rolando
    assert editor.verticalScrollBar().value() == 0  # abre no começo do texto, como o campo da aba Tags


def test_enter_quebra_a_linha_e_ctrl_enter_confirma(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "purl")
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    editor.selectAll()
    QTest.keyClicks(editor, "primeira")
    QTest.keyClick(editor, Qt.Key.Key_Return)  # no campo de várias linhas, o Enter quebra a linha
    QTest.keyClicks(editor, "segunda")
    assert editor.toPlainText() == "primeira\nsegunda"
    assert tabela.item(linha, 1).text() != "primeira\nsegunda"  # ainda não confirmou
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    _assentar(desktop_app)
    assert tabela.item(linha, 1).text() == "primeira\nsegunda"
    assert tabela.indexWidget(tabela.model().index(linha, 1)) is None  # o editor fechou
    assert painel_visivel.has_unsaved_changes
    assert ("purl", "primeira\nsegunda") in painel_visivel.current_edit().tags
    assert tabela.sizeHintForRow(linha) <= tabela.rowHeight(linha)  # a linha já se ajustou às duas linhas


def test_esc_desfaz_e_tab_confirma_o_editor_do_valor(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "purl")
    original = tabela.item(linha, 1).text()
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    QTest.keyClicks(editor, "XYZ")
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    _assentar(desktop_app)
    assert tabela.item(linha, 1).text() == original and not painel_visivel.has_unsaved_changes

    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    editor.selectAll()
    QTest.keyClicks(editor, "novo")
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    _assentar(desktop_app)
    assert tabela.item(linha, 1).text() == "novo" and painel_visivel.has_unsaved_changes


def test_clicar_fora_confirma_o_editor_do_valor(painel_visivel, desktop_app) -> None:
    from PySide6.QtTest import QTest

    painel_visivel.activateWindow()
    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "purl")
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    editor.selectAll()
    QTest.keyClicks(editor, "fora")
    painel_visivel._fields["title"].setFocus()  # o foco sai do editor, como num clique em outro campo
    _assentar(desktop_app)
    assert tabela.item(linha, 1).text() == "fora"


def test_abrir_o_editor_e_confirmar_sem_digitar_nao_altera_o_valor(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tabela = painel_visivel._others
    linha = _linha_do_campo(tabela, "synopsis")
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    _assentar(desktop_app)
    assert tabela.item(linha, 1).text() == _SINOPSE and not painel_visivel.has_unsaved_changes


def test_campo_novo_pelo_teclado_chega_ao_valor_de_varias_linhas(painel_visivel, desktop_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    tabela = painel_visivel._others
    painel_visivel._add_other()  # abre o editor do nome da linha nova
    _assentar(desktop_app)
    nome = tabela.indexWidget(tabela.model().index(tabela.rowCount() - 1, 0))
    assert isinstance(nome, QLineEdit)
    QTest.keyClicks(nome, "novo_campo")
    QTest.keyClick(nome, Qt.Key.Key_Return)  # no nome, uma linha só: o Enter confirma
    _assentar(desktop_app)
    linha = tabela.rowCount() - 1
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    QTest.keyClicks(editor, "um")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QTest.keyClicks(editor, "dois")
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    _assentar(desktop_app)
    assert ("novo_campo", "um\ndois") in painel_visivel.current_edit().tags


@pytest.mark.ffmpeg
def test_valor_de_varias_linhas_editado_na_tabela_chega_a_copia_e_o_original_fica(painel, ffmpeg_tools, tmp_path,
                                                                                    wait_until, desktop_app) -> None:
    """Medido no arquivo gravado, e não pela ausência de erro: a tag de várias linhas
    editada pelo editor da tabela volta do ffprobe igual, e o original não muda."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from videomanager.infrastructure.ffmpeg.metadata import read_metadata

    origem = tmp_path / "video.mkv"
    _run(ffmpeg_tools, *_RECEITAS["mkv"], "-metadata", "meu_campo=antigo", str(origem))
    antes = origem.read_bytes()
    painel.open_file(origem)
    wait_until(lambda: painel._meta is not None, timeout=20)
    painel.resize(1000, 900)
    painel.show()
    _assentar(desktop_app)
    tabela = painel._others
    linha = next(r for r in range(tabela.rowCount()) if tabela.item(r, 0).text().lower() == "meu_campo")  # o MKV põe em maiúsculas
    editor = _abrir_editor(tabela, linha, 1, desktop_app)
    editor.selectAll()
    QTest.keyClicks(editor, "primeira linha")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QTest.keyClicks(editor, "segunda linha")
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    _assentar(desktop_app)
    painel.save()
    wait_until(lambda: painel._saved is not None, timeout=30)
    gravadas = {chave.lower(): valor for chave, valor in read_metadata(painel._saved.path, ffmpeg_tools).tags}
    assert gravadas["meu_campo"] == "primeira linha\nsegunda linha"
    assert origem.read_bytes() == antes  # o original nunca é alterado


def test_cancelar_o_worker_de_gravacao_nao_deixa_arquivo(desktop_app, tmp_path) -> None:
    """``WorkerRunner.cancel_all`` chama ``cancel`` do worker: tem de chegar ao
    processo e devolver a reserva, senão fica um arquivo vazio com o nome da cópia."""
    from videomanager.bootstrap import build_desktop_runtime

    worker = build_desktop_runtime(audio_enabled=False).metadata_writer(_meta(), unchanged_edit(_meta()), TOOLS,
                                                                        tmp_path)
    falhas = []
    worker.signals.failed.connect(falhas.append)
    worker.cancel()
    worker.run()
    assert len(falhas) == 1 and isinstance(falhas[0], JobCancelled)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.ffmpeg
def test_abrir_e_salvar_sem_mexer_nao_altera_campo_nenhum(painel, ffmpeg_tools, tmp_path, wait_until) -> None:
    """Valor com quebra de linha ou espaço no fim volta como está: aparado na aba,
    ele seria regravado alterado sem o usuário ter tocado nele."""
    from videomanager.infrastructure.ffmpeg.metadata import metadata_args

    origem = tmp_path / "video.mkv"
    _run(ffmpeg_tools, *_RECEITAS["mkv"], "-metadata", "description=linha 1\nlinha 2\n",
         "-metadata", "title=Com espaço ", "-metadata", "meu_campo= x ", str(origem))
    painel.open_file(origem)
    wait_until(lambda: painel._meta is not None, timeout=20)
    assert "\n" in painel._fields["description"].toPlainText()
    args = metadata_args(painel._meta, painel.current_edit(), tmp_path / "saida.mkv", ffmpeg_tools)
    assert [a for a in args if a.startswith("-metadata")] == []


def test_troca_de_idioma_refaz_o_que_as_celulas_da_tabela_mostram(desktop_app) -> None:
    """Célula de tabela não passa por ``bind``: o tipo da trilha e a dica do
    idioma ficavam no idioma da abertura do arquivo."""
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime
    from videomanager.presentation.qt import i18n, strings
    from videomanager.presentation.qt.panels.metadata_panel import _LANGUAGE, MetadataPanel

    painel = MetadataPanel(Preferences(), lambda: TOOLS, runtime=build_desktop_runtime(audio_enabled=False))
    try:
        painel._install(_meta(), None)
        i18n.apply_language("en")
        assert painel._tracks.item(1, 1).text() == strings.META_TRACK_KINDS["audio"] == "Audio"
        assert painel._tracks.item(1, _LANGUAGE).toolTip() == strings.META_LANGUAGE_TIP
        assert painel._tracks.horizontalHeaderItem(1).text() == "Type"
    finally:
        painel.shutdown()
        painel.deleteLater()


def _mp3_vbr_sem_xing(tools: FFmpegTools, pasta: Path) -> Path:
    """Silêncio e depois ruído, sem o cabeçalho Xing: sem ele, o ffprobe estima
    a duração pelo bitrate do começo, que é o do silêncio."""
    origem = pasta / "vbr.mp3"
    _run(tools, "-f", "lavfi", "-i", "anoisesrc=d=12:a=0.5", "-af", "volume='if(lt(t,6),0,1)':eval=frame",
         "-c:a", "libmp3lame", "-q:a", "4", "-write_xing", "0", str(origem))
    return origem


@pytest.mark.ffmpeg
def test_mp3_vbr_sem_cabecalho_xing_e_salvo(ffmpeg_tools, tmp_path) -> None:
    """A cópia ganha o cabeçalho e passa a dizer a duração real: a diferença de
    duração não é diferença de conteúdo (medido num rip real: 18,80 s estimados
    contra 20,04 s), e a cópia correta era recusada."""
    from videomanager.infrastructure.ffmpeg.metadata import read_metadata

    origem = _mp3_vbr_sem_xing(ffmpeg_tools, tmp_path)
    meta = read_metadata(origem, ffmpeg_tools)
    salvo = _salvar(ffmpeg_tools, meta, replace(unchanged_edit(meta), tags=(("title", "X"),)), tmp_path)
    copia = read_metadata(salvo.path, ffmpeg_tools)
    assert abs(copia.duration - meta.duration) > 1  # o cenário é o de verdade
    assert _md5_das_trilhas(ffmpeg_tools, salvo.path, copia) == _md5_das_trilhas(ffmpeg_tools, origem, meta)


@pytest.mark.ffmpeg
def test_duracao_diferente_com_outros_pacotes_continua_recusada(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    from videomanager.infrastructure.ffmpeg import metadata as modulo

    origem = _mp3_vbr_sem_xing(ffmpeg_tools, tmp_path)
    meta = modulo.read_metadata(origem, ffmpeg_tools)
    contagens = iter([[100], [99]])
    monkeypatch.setattr(modulo, "_packet_counts", lambda *a, **k: next(contagens))
    with pytest.raises(ConversionError, match="mesmas trilhas"):
        _salvar(ffmpeg_tools, meta, unchanged_edit(meta), tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [origem.name]


def test_digitar_nao_decodifica_a_capa_de_novo(desktop_app, monkeypatch) -> None:
    """Decodificar e reduzir a capa a cada tecla custava 59 ms por tecla com uma
    capa de 3000×3000 (medido): a imagem só se refaz quando a capa muda."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QPixmap
    from PySide6.QtTest import QTest
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime
    from videomanager.presentation.qt.panels import metadata_panel as modulo

    decodificacoes = []

    class Contada(QPixmap):
        def loadFromData(self, *args, **kwargs):  # noqa: N802
            decodificacoes.append("bytes")
            return super().loadFromData(*args, **kwargs)

        def load(self, *args, **kwargs):
            decodificacoes.append("arquivo")
            return super().load(*args, **kwargs)

    monkeypatch.setattr(modulo, "QPixmap", Contada)
    painel = modulo.MetadataPanel(Preferences(), lambda: TOOLS, runtime=build_desktop_runtime(audio_enabled=False))
    try:
        capa = QPixmap(8, 8)
        capa.fill()
        dados = QByteArray()
        buffer = QBuffer(dados)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        capa.save(buffer, "PNG")
        meta = _meta("a.mp3", tags=(("title", "T"),), cover=CoverInfo(1, "picture", "image/png"),
                     streams=(("audio", "mp3"), ("video", "png")), formato="mp3")
        painel._install(meta, bytes(dados))
        antes = len(decodificacoes)
        QTest.keyClicks(painel._fields["title"], "novo titulo")  # o QTest só mapeia ASCII
        assert len(decodificacoes) == antes, decodificacoes
        assert not painel._cover_view.pixmap().isNull()
        painel._clear_cover()
        assert painel._cover_view.pixmap().isNull()
    finally:
        painel.shutdown()
        painel.deleteLater()


def _janela(monkeypatch):
    from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                        build_processing_service)
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.main_window import MainWindow

    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    return MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                      downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))


def test_painel_de_metadados_nasce_na_primeira_visita(desktop_app, monkeypatch) -> None:
    """Montado com a janela, ele somava ~55 ms à abertura e ~6 ms a toda troca de
    idioma (medido), para quem nunca abre a aba."""
    from videomanager.presentation.qt.main_window import _TAB_EDIT, _TAB_METADATA
    from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel

    janela = _janela(monkeypatch)
    try:
        assert janela.findChildren(MetadataPanel) == []
        janela._tabs.setCurrentIndex(_TAB_EDIT)
        assert janela.findChildren(MetadataPanel) == []
        janela._tabs.setCurrentIndex(_TAB_METADATA)
        paineis = janela.findChildren(MetadataPanel)
        assert len(paineis) == 1 and paineis[0].isVisibleTo(janela._tabs.widget(_TAB_METADATA))
        janela._tabs.setCurrentIndex(_TAB_EDIT)
        janela._tabs.setCurrentIndex(_TAB_METADATA)
        assert janela.findChildren(MetadataPanel) == paineis  # uma vez só
    finally:
        janela._edit.shutdown()
        janela._convert.shutdown()
        if janela._metadata is not None:
            janela._metadata.shutdown()
        janela.deleteLater()


def test_fechar_sem_visitar_a_aba_nao_cria_o_painel(desktop_app, monkeypatch) -> None:
    from PySide6.QtGui import QCloseEvent
    from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel

    janela = _janela(monkeypatch)
    try:
        evento = QCloseEvent()
        janela.closeEvent(evento)
        assert evento.isAccepted() and janela.findChildren(MetadataPanel) == []
    finally:
        janela.deleteLater()
