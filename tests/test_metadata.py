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
        assert args[args.index("-attach") + 1] == "/t/cover.jpg"

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
        meta = _meta()
        janela._metadata._install(meta, None)
        janela._metadata._fields["title"].setText("Mudou")
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
