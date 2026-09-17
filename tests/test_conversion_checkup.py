"""Checkup da conversão local: defeitos achados na revisão, um teste por achado.

Os de montagem de argumentos são puros. Os marcados ``ffmpeg`` rodam o ffmpeg
de verdade, porque o defeito só existe na execução (decodificação do stderr,
metadados preservados pela capa).
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ConversionError
from videomanager.application.media.conversion_description import describe_target
from videomanager.domain.compatibility import can_copy_audio
from videomanager.domain.compatibility import container_accepts_video
from videomanager.domain.compatibility import needs_scaling
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.media import VideoTarget
from videomanager.infrastructure.ffmpeg.converter import build_audio_args
from videomanager.infrastructure.ffmpeg.converter import build_video_args

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


def _media(*streams: LocalStream, name: str = "entrada.mkv", format_name: str = "matroska,webm") -> LocalMedia:
    return LocalMedia(Path(f"/entrada/{name}"), 60.0, format_name, 10_000_000, tuple(streams))


VIDEO = LocalStream(0, "video", "h264", height=1080, width=1920, fps=30.0)
AUDIO = LocalStream(1, "audio", "aac", sample_rate=48000, channels=2)


def _index(args: list[str], value: str) -> int:
    return args.index(value)


# --- C2: codec escolhido precisa caber no container -------------------------

class TestCodecNoContainer:
    @pytest.mark.parametrize(("container", "codec", "cabe"), [
        ("webm", "h264", False), ("webm", "hevc", False), ("webm", "vp9", True), ("webm", "av1", True),
        ("mp4", "vp9", False), ("mp4", "h264", True), ("mp4", "hevc", True), ("mkv", "h264", True),
        ("mkv", "vp9", True), ("webm", "copy", True),
    ])
    def test_tabela(self, container, codec, cabe) -> None:
        assert container_accepts_video(container, codec) is cabe

    def test_servico_recusa_antes_de_enfileirar(self, tmp_path) -> None:
        from videomanager.application.media.processing import ProcessingService

        class Catalog:
            def writable(self, directory):
                return True

        media = _media(VIDEO, AUDIO)
        service = ProcessingService(Catalog(), outputs=None, rasterizer=None)
        with pytest.raises(ConversionError, match="webm"):
            service.convert(media, VideoTarget(container="webm", video_codec="h264"),
                            same_folder=False, fallback=tmp_path)

    def test_hevc_em_mp4_recebe_tag_hvc1(self) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec="hevc"),
                                Path("/s/x.mp4"), TOOLS)
        assert args[_index(args, "-tag:v") + 1] == "hvc1"

    def test_hevc_copiado_para_mp4_recebe_tag_hvc1(self) -> None:
        hevc = LocalStream(0, "video", "hevc", height=1080, width=1920, fps=30.0)
        args = build_video_args(_media(hevc, AUDIO), VideoTarget(container="mp4"), Path("/s/x.mp4"), TOOLS)
        assert args[_index(args, "-c:v") + 1] == "copy"
        assert args[_index(args, "-tag:v") + 1] == "hvc1"

    def test_h264_nao_recebe_tag(self) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4"), Path("/s/x.mp4"), TOOLS)
        assert "-tag:v" not in args


# --- C4: capa embutida não é trilha de vídeo --------------------------------

class TestCapaNaoEVideo:
    def test_mapeia_so_video_que_nao_e_capa(self) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mkv"), Path("/s/x.mkv"), TOOLS)
        assert args[_index(args, "-map") + 1] == "0:V:0"
        assert "0:v:0" not in args

    def test_audio_com_capa_nao_vira_video(self, tmp_path) -> None:
        from videomanager.application.media.processing import ProcessingService

        class Catalog:
            def writable(self, directory):
                return True

        capa = LocalStream(0, "video", "mjpeg", height=500, width=500, attached_picture=True)
        mp3 = _media(capa, LocalStream(1, "audio", "mp3"), name="musica.mp3", format_name="mp3")
        with pytest.raises(ConversionError, match="vídeo"):
            ProcessingService(Catalog(), outputs=None, rasterizer=None).convert(
                mp3, VideoTarget(container="mp4"), same_folder=False, fallback=tmp_path)


# --- C5: faixas extras ------------------------------------------------------

class TestFaixasExtras:
    def _mkv(self) -> LocalMedia:
        return _media(VIDEO, AUDIO, LocalStream(2, "audio", "ac3"), LocalStream(3, "subtitle", "subrip"),
                      LocalStream(4, "attachment", "ttf"))

    def test_mkv_mantem_audios_legendas_e_anexos(self) -> None:
        args = build_video_args(self._mkv(), VideoTarget(container="mkv"), Path("/s/x.mkv"), TOOLS)
        maps = [args[i + 1] for i, value in enumerate(args) if value == "-map"]
        assert maps == ["0:V:0", "0:a?", "0:s?", "0:t?"]
        assert args[_index(args, "-c:s") + 1] == "copy"

    def test_mp4_avisa_o_que_fica_de_fora(self) -> None:
        texto = describe_target(self._mkv(), VideoTarget(container="mp4"))
        assert "1ª faixa de áudio" in texto and "legendas" in texto

    def test_arquivo_simples_nao_ganha_aviso(self) -> None:
        texto = describe_target(_media(VIDEO, AUDIO), VideoTarget(container="mp4"))
        assert "faixa" not in texto and "legendas" not in texto


# --- C9: vídeo retrato ------------------------------------------------------

class TestRetrato:
    def test_720p_de_retrato_reduz_o_lado_curto(self) -> None:
        retrato = LocalStream(0, "video", "h264", height=1080, width=1920, fps=30.0, rotation=90.0)
        media = _media(retrato, AUDIO)
        target = VideoTarget(container="mp4", height=720)
        assert needs_scaling(media, target)
        args = build_video_args(media, target, Path("/s/x.mp4"), TOOLS)
        assert args[_index(args, "-vf") + 1].startswith("scale=720:-2")

    def test_retrato_ja_no_tamanho_nao_redimensiona(self) -> None:
        retrato = LocalStream(0, "video", "h264", height=720, width=1280, fps=30.0, rotation=-90.0)
        assert not needs_scaling(_media(retrato, AUDIO), VideoTarget(container="mp4", height=720))

    def test_paisagem_continua_pela_altura(self) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", height=720), Path("/s/x.mp4"), TOOLS)
        assert args[_index(args, "-vf") + 1].startswith("scale=-2:720")


# --- C10: WAV ---------------------------------------------------------------

class TestWav:
    def test_pcm_big_endian_nao_e_copiado_para_wav(self) -> None:
        assert not can_copy_audio(_media(LocalStream(0, "audio", "pcm_s16be")), "wav")

    @pytest.mark.parametrize("codec", ["pcm_s24le", "pcm_s32le", "pcm_f32le"])
    def test_origem_de_alta_resolucao_sai_em_24_bits(self, codec) -> None:
        args = build_audio_args(_media(LocalStream(0, "audio", codec)), AudioTarget(codec="wav"),
                                Path("/s/x.wav"), TOOLS)
        assert args[_index(args, "-c:a") + 1] == "pcm_s24le"

    def test_origem_comum_sai_em_16_bits(self) -> None:
        args = build_audio_args(_media(LocalStream(0, "audio", "aac")), AudioTarget(codec="wav"),
                                Path("/s/x.wav"), TOOLS)
        assert args[_index(args, "-c:a") + 1] == "pcm_s16le"


# --- C12: estimativa sem dimensões ------------------------------------------

def test_estimativa_sem_largura_nao_quebra() -> None:
    sem_medidas = LocalStream(0, "video", "h264", height=None, width=None, fps=None)
    assert estimate_convert_size(_media(sem_medidas, AUDIO), VideoTarget(container="mp4", video_codec="h264",
                                                                          height=720)) > 0


# --- C7: pasta sem permissão real -------------------------------------------

def test_pasta_so_e_gravavel_se_um_arquivo_puder_ser_criado(tmp_path, monkeypatch) -> None:
    from videomanager.infrastructure.ffmpeg import catalog
    assert catalog.FFmpegCatalog().writable(tmp_path) is True
    assert not any(tmp_path.iterdir())

    def recusa(*args, **kwargs):
        raise PermissionError("acesso controlado a pastas")

    monkeypatch.setattr(catalog.tempfile, "TemporaryFile", recusa)
    assert catalog.FFmpegCatalog().writable(tmp_path) is False


# --- C13: arquivo segurado por antivírus ou OneDrive ------------------------

def test_entrega_tenta_de_novo_quando_o_destino_esta_ocupado(tmp_path, monkeypatch) -> None:
    from videomanager.infrastructure.storage import outputs
    temporary = tmp_path / "tmp.mp4"
    temporary.write_bytes(b"pronto")
    destination = tmp_path / "saida.mp4"
    destination.write_bytes(b"")
    real_replace = Path.replace
    tentativas = []

    def ocupado(self, target):
        tentativas.append(target)
        if len(tentativas) < 3:
            raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", ocupado)
    monkeypatch.setattr(outputs.time, "sleep", lambda seconds: None)
    outputs.FileOutputStore().commit(temporary, destination)
    assert destination.read_bytes() == b"pronto" and len(tentativas) == 3


# --- C6: configurações novas chegam à aba Converter -------------------------

def test_configuracoes_salvas_chegam_ao_painel_de_conversao(desktop_app, monkeypatch) -> None:
    from dataclasses import replace

    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import (
        build_desktop_runtime, build_download_service, build_editor_service, build_processing_service,
    )
    from videomanager.presentation.qt import main_window as module

    window = module.MainWindow(Preferences(), editor=build_editor_service(), processing=build_processing_service(),
                               downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    novas = replace(Preferences(), hardware_encoder="nvenc")

    class Dialogo:
        DialogCode = module.SettingsDialog.DialogCode

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def result_settings(self):
            return novas

    monkeypatch.setattr(module, "SettingsDialog", Dialogo)
    monkeypatch.setattr(window, "_save_settings", lambda: None)
    try:
        window._open_settings()
        assert window._convert._settings is novas
    finally:
        window.close()


# --- C1 e C3: execução real -------------------------------------------------

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


def _utf8_source(tools: FFmpegTools, tmp_path: Path, seconds: int = 1) -> Path:
    source = tmp_path / "origem.mkv"
    # Por arquivo, e não por -metadata: a linha de comando do Windows tem 32 KB.
    metadata = tmp_path / "meta.txt"
    # "Á" é C3 81 em UTF-8, e 0x81 não tem caractere no cp1252: é esse byte
    # que derrubava a leitura. "ç" e emoji decodificam como lixo, sem erro.
    metadata.write_text(";FFMETADATA1\ntitle=ÁUDIO e ÍNDICE ✓ 😀\n", encoding="utf-8")
    _run(tools, "-f", "lavfi", "-i", f"testsrc2=s=64x36:r=25:d={seconds}", "-i", str(metadata),
         "-map_metadata", "1", "-c:v", "libx264", str(source))
    return source


def _convert_with_extra(tools, tmp_path, monkeypatch, *extra: str):
    from videomanager.infrastructure.ffmpeg import converter as module

    original = module.build_args

    def with_extra(*args, **kwargs):
        built = original(*args, **kwargs)
        return [*built[:-1], *extra, built[-1]]

    monkeypatch.setattr(module, "build_args", with_extra)
    media = module.probe_file(_utf8_source(tools, tmp_path, seconds=8), tools)
    destination = tmp_path / "saida.mkv"
    destination.write_bytes(b"")
    converter = module.Converter(media, VideoTarget(container="mkv"), destination, tools)
    outcome: list[object] = []
    worker = threading.Thread(target=lambda: outcome.append(_capture(converter.run)), daemon=True)
    worker.start()
    worker.join(60)
    if worker.is_alive():
        converter.cancel()
        worker.join(15)
        pytest.fail("a conversão travou: o stderr deixou de ser lido depois do título em UTF-8")
    return outcome[0]


@pytest.mark.ffmpeg
def test_stderr_em_utf8_nao_trava_a_conversao(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    """Com cp1252 a thread do stderr morria no título, o cano enchia com o que
    viesse depois e o ffmpeg parava para sempre, segurando a fila de uma vaga.
    ``-debug_ts`` faz o papel de um arquivo que gera avisos a cada quadro."""
    result = _convert_with_extra(ffmpeg_tools, tmp_path, monkeypatch, "-debug_ts")
    assert isinstance(result, Path) and result.stat().st_size > 0, result


@pytest.mark.ffmpeg
def test_erro_do_ffmpeg_aparece_mesmo_com_titulo_em_utf8(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    """Sem a leitura do stderr, a falha chegava sem o motivo dado pelo ffmpeg."""
    result = _convert_with_extra(ffmpeg_tools, tmp_path, monkeypatch, "-map", "0:9")
    assert isinstance(result, ConversionError), result
    # Com a leitura morta, a "última linha" era o cabeçalho do arquivo de entrada.
    assert "Input #0" not in str(result)
    assert "output" in str(result).lower()


def _capture(call):
    try:
        return call()
    except BaseException as exc:  # noqa: BLE001 - o teste inspeciona o resultado
        return exc


@pytest.mark.ffmpeg
def test_capa_em_mkv_preserva_metadados_e_capitulos(ffmpeg_tools, tmp_path) -> None:
    import json

    from videomanager.infrastructure.ffmpeg.thumbnail import embed_thumbnail

    chapters = tmp_path / "meta.txt"
    chapters.write_text(";FFMETADATA1\ntitle=Meu título\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Um\n",
                        encoding="utf-8")
    video = tmp_path / "video.mkv"
    _run(ffmpeg_tools, "-f", "lavfi", "-i", "testsrc2=s=64x36:r=10:d=2", "-i", str(chapters),
         "-map_metadata", "1", "-map_chapters", "1", "-c:v", "libx264", str(video))
    embed_thumbnail(video, ffmpeg_tools)
    from videomanager.infrastructure.system.binaries import subprocess_kwargs
    probe = subprocess.run([ffmpeg_tools.ffprobe_str, "-v", "error", "-print_format", "json", "-show_format",
                            "-show_chapters", "-show_streams", str(video)], timeout=30, **subprocess_kwargs())
    data = json.loads(probe.stdout)
    assert data["format"]["tags"].get("title") == "Meu título"
    assert len(data["chapters"]) == 1
    # O ffprobe 7 mostra a imagem anexada ao MKV como vídeo com attached_pic.
    assert any(stream.get("codec_type") == "attachment" or (stream.get("disposition") or {}).get("attached_pic")
               for stream in data["streams"])


def test_aba_nao_oferece_codec_que_o_container_recusa(desktop_app) -> None:
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime, build_processing_service
    from videomanager.presentation.qt.panels.convert_panel import ConvertPanel

    panel = ConvertPanel(Preferences(), lambda: None, processing=build_processing_service(),
                         runtime=build_desktop_runtime(audio_enabled=False))
    try:
        codecs = panel._video_codec
        codecs.setCurrentIndex(codecs.findData("h264"))
        panel._container.setCurrentIndex(panel._container.findData("webm"))
        habilitados = {codecs.itemData(i) for i in range(codecs.count()) if codecs.model().item(i).isEnabled()}
        assert habilitados == {"copy", "vp9", "av1"}
        assert codecs.currentData() == "copy"
        panel._container.setCurrentIndex(panel._container.findData("mkv"))
        assert all(codecs.model().item(i).isEnabled() for i in range(codecs.count()))
    finally:
        panel.deleteLater()
