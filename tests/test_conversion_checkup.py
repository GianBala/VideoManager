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


# --- Compressão ---------------------------------------------------------------

class TestCompressao:
    @pytest.mark.parametrize(("codec", "encoder"), [
        ("h264", "libx264"), ("hevc", "libx265"), ("vp9", "libvpx-vp9"), ("av1", "libsvtav1")])
    @pytest.mark.parametrize("nivel", ["high", "balanced", "economy"])
    def test_nivel_usa_a_tabela_do_encoder(self, codec, encoder, nivel) -> None:
        from videomanager.infrastructure.ffmpeg.hardware import encoder_quality
        container = "webm" if codec == "vp9" else "mp4"
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container=container, video_codec=codec,
                                                                  quality=nivel), Path("/s/x"), TOOLS)
        inicio = _index(args, "-c:v")
        esperado = ["-c:v", encoder, *encoder_quality(encoder, nivel)]
        assert args[inicio:inicio + len(esperado)] == esperado
        assert args.count("-crf") == 1 and args.count("-pix_fmt") <= 1

    def test_sem_nivel_o_comando_e_o_da_conversao_comum(self) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec="h264"),
                                Path("/s/x"), TOOLS)
        inicio = _index(args, "-c:v")
        assert args[inicio:inicio + 8] == ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                                           "-preset", "medium"]

    @pytest.mark.parametrize(("nivel", "esperado"), [(None, "balanced"), ("economy", "economy")])
    def test_nivel_chega_a_placa(self, monkeypatch, nivel, esperado) -> None:
        from videomanager.infrastructure.ffmpeg import hardware
        pedidos = []

        def resolve(family, preference, tools, quality=hardware.DEFAULT_QUALITY):
            pedidos.append(quality)
            return hardware.software_encoder(family)

        monkeypatch.setattr(hardware, "resolve", resolve)
        build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec="h264",
                                                           hardware="nvenc", quality=nivel), Path("/s/x"), TOOLS)
        assert pedidos == [esperado]

    def test_nivel_aparece_no_plano(self) -> None:
        texto = describe_target(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec="h264",
                                                                  quality="economy"))
        assert "qualidade econômica" in texto

    def test_audio_recomprimido_no_mesmo_codec_nao_e_copiado(self) -> None:
        mp3 = _media(LocalStream(0, "audio", "mp3", bitrate=320.0), name="a.mp3", format_name="mp3")
        alvo = AudioTarget(codec="mp3", bitrate="128", reencode=True)
        args = build_audio_args(mp3, alvo, Path("/s/x.mp3"), TOOLS)
        assert args[_index(args, "-c:a") + 1] == "libmp3lame"
        assert args[_index(args, "-b:a") + 1] == "128k"
        assert "cópia" not in describe_target(mp3, alvo)
        assert estimate_convert_size(mp3, alvo) == int(128 * 1000 / 8 * 60.0)

    def test_mesmo_codec_sem_recomprimir_continua_copiado(self) -> None:
        mp3 = _media(LocalStream(0, "audio", "mp3", bitrate=320.0), name="a.mp3", format_name="mp3")
        args = build_audio_args(mp3, AudioTarget(codec="mp3", bitrate="128"), Path("/s/x.mp3"), TOOLS)
        assert args[_index(args, "-c:a") + 1] == "copy"

    def test_saida_comprimida_leva_sufixo_e_teto(self, tmp_path) -> None:
        from videomanager.bootstrap import build_processing_service
        origem = tmp_path / "video.mp4"
        origem.write_bytes(b"x")
        media = LocalMedia(origem, 60.0, "mov,mp4", 1, (VIDEO, AUDIO))
        job, _ = build_processing_service().convert(media, VideoTarget(container="mp4", video_codec="h264"),
                                                    same_folder=True, fallback=tmp_path, compress=True)
        assert job.request.destination == tmp_path / "video (comprimido).mp4"
        assert job.request.max_bytes == 1


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


def test_mensagem_do_trecho_aponta_a_causa_e_nao_a_estatistica() -> None:
    """O ffmpeg despeja estatística no fim, mesmo quando morre.

    Um trecho que falhou aparecia na tela como "CPB properties: bitrate
    max/min/avg: 0/0/0", que não diz nada a quem lê.
    """
    from collections import deque

    from videomanager.infrastructure.ffmpeg.parallel import _last_line

    cauda = deque([
        "[libvpx-vp9 @ 000] Invalid argument",
        "[out#0/webm @ 000] video:0KiB audio:0KiB",
        "[libvpx-vp9 @ 000] CPB properties: bitrate max/min/avg: 0/0/0 buffer size: 0 vbv_delay: N/A",
    ])
    assert "Invalid argument" in _last_line(cauda)

    sem_marca = deque(["[out#0/webm @ 000] video:0KiB audio:0KiB", "  ",
                       "[libvpx-vp9 @ 000] CPB properties: bitrate max/min/avg: 0/0/0"])
    resposta = _last_line(sem_marca)
    assert "CPB properties" in resposta and "video:0KiB" in resposta
    assert str(_last_line(deque())) == "sem detalhes do ffmpeg"


# --- Compressão de verdade ----------------------------------------------------

def _medir(tools: FFmpegTools, path: Path) -> dict:
    import json

    from videomanager.infrastructure.system.binaries import subprocess_kwargs
    kwargs = subprocess_kwargs()
    kwargs["stdout"] = subprocess.PIPE
    probe = subprocess.run([tools.ffprobe_str, "-v", "error", "-of", "json", "-show_format", "-show_streams",
                            str(path)], timeout=30, text=True, **kwargs)
    data = json.loads(probe.stdout)
    streams = {stream["codec_type"]: stream for stream in reversed(data["streams"])}
    return {"tamanho": int(data["format"]["size"]), "duracao": float(data["format"]["duration"]), **streams}


def _comprimir(tools: FFmpegTools, origem: Path, nivel, pasta: Path, codec: str = "h264",
               max_bytes: int | None = None) -> tuple[Path, object]:
    from videomanager.bootstrap import build_processing_service
    from videomanager.domain.compression import compression_target
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file

    media = probe_file(origem, tools)
    alvo = compression_target(media, nivel, codec, "software")
    job, _ = build_processing_service().convert(media, alvo, same_folder=False, fallback=pasta, compress=True)
    request = job.request
    return Converter(media, alvo, request.destination, tools, lease=request.lease,
                     max_bytes=max_bytes or request.max_bytes).run(), alvo


@pytest.mark.ffmpeg
def test_cada_nivel_de_compressao_entrega_arquivo_menor_e_inteiro(ffmpeg_tools, tmp_path) -> None:
    """Medido na saída: menor a cada nível, menor que a origem, sem perder
    duração nem trilha, e com o teto de resolução e de áudio de cada nível."""
    from videomanager.domain.compression import LEVELS

    origem = tmp_path / "origem.mp4"
    # Bitrate alto de propósito, como o de uma câmera: é o que a compressão encolhe.
    _run(ffmpeg_tools, "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=2", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=2", "-ac", "2", "-c:v", "libx264", "-crf", "10",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", str(origem))
    antes = _medir(ffmpeg_tools, origem)
    medidas = [_medir(ffmpeg_tools, _comprimir(ffmpeg_tools, origem, nivel, tmp_path)[0]) for nivel in LEVELS]

    tamanhos = [medida["tamanho"] for medida in medidas]
    assert tamanhos == sorted(tamanhos, reverse=True) and len(set(tamanhos)) == 4, tamanhos
    assert tamanhos[0] < antes["tamanho"]
    # Na mesma resolução, só o nível do encoder separa os três primeiros: o
    # áudio sozinho já faria os tamanhos caírem.
    video = [int(medida["video"]["bit_rate"]) for medida in medidas[:3]]
    assert video[0] > video[1] * 1.2 and video[1] > video[2] * 1.2, video
    for nivel, medida in zip(LEVELS, medidas):
        assert medida["duracao"] == pytest.approx(antes["duracao"], abs=0.1)
        assert medida["video"]["codec_name"] == "h264" and medida["audio"]["codec_name"] == "aac"
        assert medida["video"]["height"] == (nivel.max_height or 1080)
        assert int(medida["audio"]["bit_rate"]) / 1000 == pytest.approx(nivel.audio_kbps, rel=0.2)


@pytest.mark.ffmpeg
def test_mp3_comprimido_e_recodificado_e_nao_copiado(ffmpeg_tools, tmp_path) -> None:
    from videomanager.domain.compression import LEVELS

    origem = tmp_path / "musica.mp3"
    _run(ffmpeg_tools, "-f", "lavfi", "-i", "sine=frequency=330:duration=4", "-ac", "2",
         "-c:a", "libmp3lame", "-b:a", "320k", str(origem))
    saida, alvo = _comprimir(ffmpeg_tools, origem, LEVELS[1], tmp_path)
    medida = _medir(ffmpeg_tools, saida)
    assert (saida.suffix, alvo.bitrate) == (".mp3", "128")
    assert int(medida["audio"]["bit_rate"]) / 1000 == pytest.approx(128, rel=0.05)
    assert medida["tamanho"] < origem.stat().st_size / 2


def test_aba_comprime_video_e_audio_da_mesma_lista(desktop_app, tmp_path) -> None:
    import re
    from types import SimpleNamespace

    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime, build_processing_service
    from videomanager.presentation.qt.panels.convert_panel import ConvertPanel

    video = tmp_path / "video.mov"
    musica = tmp_path / "musica.flac"
    for path in (video, musica):
        path.write_bytes(b"x")
    midias = [
        LocalMedia(video, 60.0, "mov,mp4", 150_000_000,
                   (VIDEO, LocalStream(1, "audio", "aac", bitrate=256.0))),
        LocalMedia(musica, 180.0, "flac", 20_000_000, (LocalStream(0, "audio", "flac", bitrate=900.0),)),
    ]
    panel = ConvertPanel(Preferences(), lambda: TOOLS, processing=build_processing_service(),
                         runtime=build_desktop_runtime(audio_enabled=False))
    try:
        panel._on_inspected(panel._inspection_token,
                            SimpleNamespace(probed={m.path: m for m in midias}, rejected=[]))
        assert not panel._level_table.isVisibleTo(panel)
        panel._to_compress.setChecked(True)
        assert panel._level_table.isVisibleTo(panel) and panel._compress_codec.isVisibleTo(panel)
        assert not panel._container.isVisibleTo(panel) and not panel._audio_codec.isVisibleTo(panel)
        reducoes = [int(re.search(r"\(([+-]\d+)%\)", rotulo.text()).group(1)) for rotulo in panel._level_sizes]
        assert reducoes == sorted(reducoes, reverse=True) and reducoes[-1] < 0, reducoes
        assert "menor" in panel._plan.text()

        panel._compress_codec.setCurrentIndex(panel._compress_codec.findData("hevc"))
        enfileiradas = []
        panel.jobs_ready.connect(enfileiradas.extend)
        panel._start_conversion()
        alvos = {job.request.destination.name: job.request.target for job in enfileiradas}
        assert alvos == {
            # Sem bitrate da trilha: 150 MB em 60 s são 20000 kbps, menos 256 do
            # áudio, e o teto da Equilibrada é 70% disso.
            "video (comprimido).mp4": VideoTarget(container="mp4", video_codec="hevc", audio_codec="aac",
                                                  audio_bitrate="128", quality="balanced", max_kbps=13820),
            "musica (comprimido).m4a": AudioTarget(codec="m4a", bitrate="128", reencode=True),
        }

        panel._to_video.setChecked(True)
        assert not panel._level_table.isVisibleTo(panel) and panel._container.isVisibleTo(panel)
    finally:
        panel.shutdown()
        panel.deleteLater()


# --- Amostra do tamanho comprimido -------------------------------------------

def test_amostra_espalha_trechos_de_8s_ou_usa_o_arquivo_inteiro() -> None:
    from videomanager.infrastructure.ffmpeg.sample import sample_windows
    assert sample_windows(0) == []
    assert sample_windows(20.0) == [(0.0, 20.0)]
    trechos = sample_windows(120.0)
    assert [inicio + duracao / 2 for inicio, duracao in trechos] == [30.0, 60.0, 90.0]
    assert {duracao for _, duracao in trechos} == {8.0}


def _fonte_sintetica(tools: FFmpegTools, pasta: Path, segundos: int, crf: str) -> Path:
    origem = pasta / f"origem-{crf}.mp4"
    _run(tools, "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d={segundos}", "-f", "lavfi",
         "-i", f"sine=duration={segundos}", "-ac", "2", "-c:v", "libx264", "-crf", crf, "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(origem))
    return origem


@pytest.mark.ffmpeg
def test_amostra_mede_o_bitrate_da_codificacao_completa(ffmpeg_tools, tmp_path) -> None:
    from dataclasses import replace

    from videomanager.domain.compression import LEVELS, compression_target
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.ffmpeg.sample import sample_video_kbps
    from videomanager.infrastructure.system.process import ProcessControl

    media = probe_file(_fonte_sintetica(ffmpeg_tools, tmp_path, 40, "10"), ffmpeg_tools)
    alvo = compression_target(media, LEVELS[1], "h264", "software")
    medido = sample_video_kbps(media, alvo, ffmpeg_tools, ProcessControl())
    so_video = replace(media, streams=tuple(s for s in media.streams if s.kind == "video"))
    completo = tmp_path / "completo.mp4"
    ProcessControl().run(build_video_args(so_video, alvo, completo, ffmpeg_tools), timeout=120)
    real = completo.stat().st_size * 8 / 1000 / media.duration
    assert medido == pytest.approx(real, rel=0.15)


@pytest.mark.ffmpeg
def test_amostra_cancelada_para_e_nao_deixa_temporario(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    import tempfile
    import time

    from videomanager.application.errors import JobCancelled
    from videomanager.domain.compression import LEVELS, compression_target
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.ffmpeg.sample import sample_video_kbps
    from videomanager.infrastructure.system.process import ProcessControl

    media = probe_file(_fonte_sintetica(ffmpeg_tools, tmp_path, 60, "10"), ffmpeg_tools)
    temporarios = tmp_path / "tmp"
    temporarios.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporarios))
    control = ProcessControl()
    threading.Timer(0.3, control.cancel).start()
    inicio = time.monotonic()
    with pytest.raises(JobCancelled):
        sample_video_kbps(media, compression_target(media, LEVELS[0], "hevc", "software"), ffmpeg_tools, control)
    assert time.monotonic() - inicio < 5
    assert list(temporarios.iterdir()) == []


@pytest.mark.ffmpeg
def test_compressao_que_nao_encolhe_nao_e_gravada(ffmpeg_tools, tmp_path) -> None:
    """A recusa é a rede de quem não tem teto (a placa, e o AV1, que o trata
    como alvo): um limite que nenhuma saída cumpre a faz aparecer."""
    from videomanager.domain.compression import LEVELS

    origem = _fonte_sintetica(ffmpeg_tools, tmp_path, 3, "20")
    saidas = tmp_path / "saidas"
    with pytest.raises(ConversionError, match="não ficou menor que o original"):
        _comprimir(ffmpeg_tools, origem, LEVELS[0], saidas, max_bytes=1000)
    assert list(saidas.iterdir()) == []


def _ja_comprimida(tools: FFmpegTools, pasta: Path, segundos: int) -> Path:
    """Como um vídeo baixado da internet: encoder lento, bitrate baixo, e o CRF
    do nível Leve o triplicaria (medido: 298% no x264, 271% no x265)."""
    origem = pasta / "baixado.mp4"
    _run(tools, "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d={segundos}", "-f", "lavfi",
         "-i", f"sine=duration={segundos}", "-ac", "2", "-c:v", "libx264", "-crf", "30", "-preset", "veryslow",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(origem))
    return origem


@pytest.mark.ffmpeg
@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_teto_garante_o_tamanho_de_material_ja_comprimido(ffmpeg_tools, tmp_path, codec) -> None:
    from dataclasses import replace

    from videomanager.domain.compression import LEVELS, compression_ceiling
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file

    origem = _ja_comprimida(ffmpeg_tools, tmp_path, 20)
    media = probe_file(origem, ffmpeg_tools)
    saida, alvo = _comprimir(ffmpeg_tools, origem, LEVELS[0], tmp_path / "com", codec)
    assert saida.stat().st_size <= compression_ceiling(media, alvo) < origem.stat().st_size
    # Sem o teto, o mesmo nível cresceria: é o que o teto evita, e não o acaso.
    livre = tmp_path / f"livre.{alvo.extension}"
    Converter(media, replace(alvo, max_kbps=None), livre, ffmpeg_tools).run()
    assert livre.stat().st_size > origem.stat().st_size


@pytest.mark.ffmpeg
def test_teto_do_av1_reduz_o_crescimento_sem_garantir(ffmpeg_tools, tmp_path) -> None:
    from dataclasses import replace

    from videomanager.domain.compression import LEVELS, compression_ceiling
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file

    if "libsvtav1" not in subprocess.run([ffmpeg_tools.ffmpeg_str, "-hide_banner", "-encoders"],
                                         capture_output=True, text=True, timeout=30).stdout:
        pytest.skip("ffmpeg sem SVT-AV1")
    origem = _ja_comprimida(ffmpeg_tools, tmp_path, 6)
    media = probe_file(origem, ffmpeg_tools)
    from videomanager.domain.compression import compression_target
    alvo = compression_target(media, LEVELS[0], "av1", "software")
    assert compression_ceiling(media, alvo) is None  # a tabela não promete
    com, livre = tmp_path / "com.mp4", tmp_path / "livre.mp4"
    Converter(media, alvo, com, ffmpeg_tools).run()
    Converter(media, replace(alvo, max_kbps=None), livre, ffmpeg_tools).run()
    assert com.stat().st_size < livre.stat().st_size / 2


class _AmostrasFalsas:
    """O runtime de verdade, com a medida trocada por uma que só termina quando liberada."""

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self.pedidos: list[tuple] = []
        self.liberar = threading.Event()

    def __getattr__(self, nome):
        return getattr(self._runtime, nome)

    def sample_worker(self, media, target, tools):
        from videomanager.infrastructure.qt.workers.function_worker import FunctionWorker
        from videomanager.infrastructure.system.process import ProcessControl

        control = ProcessControl()
        self.pedidos.append((media.path.name, target.video_codec, target.quality, target.height))

        def medir():
            while not self.liberar.wait(0.005):
                control.check()
            control.check()
            return {"high": 4000.0, "balanced": 2000.0, "economy": 1000.0}[target.quality] / (2 if target.height else 1)

        return FunctionWorker(medir, control.cancel)


@pytest.mark.parametrize("placa", ["software", "nvenc"])
def test_tabela_espera_a_amostra_e_descarta_a_medida_velha(desktop_app, wait_until, tmp_path, placa) -> None:
    import re
    from types import SimpleNamespace

    from videomanager.application.formatting import DASH, format_size
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime, build_processing_service
    from videomanager.domain.compression import LEVELS, compression_target
    from videomanager.presentation.qt import strings
    from videomanager.presentation.qt.panels.convert_panel import ConvertPanel

    runtime = _AmostrasFalsas(build_desktop_runtime(audio_enabled=False))
    video = LocalMedia(tmp_path / "video.mp4", 60.0, "mov,mp4", 150_000_000,
                       (VIDEO, LocalStream(1, "audio", "aac", bitrate=256.0)))
    pequeno = LocalMedia(tmp_path / "pequeno.mp4", 60.0, "mov,mp4", 40_000_000,
                         (LocalStream(0, "video", "h264", height=720, width=1280, fps=30.0),))
    musica = LocalMedia(tmp_path / "musica.flac", 180.0, "flac", 20_000_000,
                        (LocalStream(0, "audio", "flac", bitrate=900.0),))
    # 1 MB por minuto: já mais comprimido do que qualquer nível entrega.
    baixado = LocalMedia(tmp_path / "baixado.mp4", 60.0, "mov,mp4", 1_000_000, (VIDEO,))
    panel = ConvertPanel(Preferences(hardware_encoder=placa), lambda: TOOLS, processing=build_processing_service(),
                         runtime=runtime)
    try:
        panel._tools = TOOLS
        panel._on_inspected(panel._inspection_token, SimpleNamespace(
            probed={m.path: m for m in (video, pequeno, musica, baixado)}, rejected=[]))
        assert runtime.pedidos == []  # fora da compressão não se mede nada
        panel._to_compress.setChecked(True)

        # O nível escolhido primeiro; o 720p grava a mesma imagem em Forte e
        # Máxima, e é medido uma vez; o áudio não é medido.
        assert runtime.pedidos[:3] == [("video.mp4", "h264", "balanced", None),
                                       ("pequeno.mp4", "h264", "balanced", None),
                                       ("baixado.mp4", "h264", "balanced", None)]
        assert len(runtime.pedidos) == 11 and not any(p[0] == "musica.flac" for p in runtime.pedidos)
        assert all(rotulo.text() == strings.CONVERT_MEASURING for rotulo in panel._level_sizes)
        # O teto não espera a amostra; na placa não há teto, e o lote fica sem garantia.
        garantias = [rotulo.text() for rotulo in panel._level_ceilings]
        if placa == "software":
            assert all(texto.startswith(strings.CONVERT_CEILING.format(size="")) for texto in garantias), garantias
        else:
            assert garantias == [DASH] * 4
        assert strings.CONVERT_MEASURING in panel._plan.text()

        # Trocar o codec cancela o que estava sendo medido para o anterior.
        antigo = panel._sampling_token
        panel._compress_codec.setCurrentIndex(panel._compress_codec.findData("hevc"))
        assert panel._sampling_token != antigo and runtime.pedidos[11][1] == "hevc"
        runtime.liberar.set()
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        assert {chave[2] for chave in panel._samples} == {"hevc"}

        # Uma resposta de antes da troca não entra.
        panel._on_sampled(antigo, ("velha",), 1.0)
        assert ("velha",) not in panel._samples

        esperado = sum(estimate_convert_size(m, alvo, {"high": 4000.0, "balanced": 2000.0}.get(alvo.quality))
                       if isinstance(alvo, VideoTarget) else estimate_convert_size(m, alvo)
                       for m in (video, pequeno, musica, baixado)
                       for alvo in [compression_target(m, LEVELS[1], "hevc", placa)])
        assert panel._level_sizes[1].text().startswith(format_size(esperado, estimated=True))
        reducoes = [int(re.search(r"\(([+-]\d+)%\)", rotulo.text()).group(1)) for rotulo in panel._level_sizes]
        assert reducoes == sorted(reducoes, reverse=True), reducoes
        # O lote encolhe no total. Com teto, o arquivo baixado encolhe também;
        # na placa, sem teto, ele cresceria, e é avisado.
        aviso = strings.CONVERT_COMPRESS_NO_GAIN.format(count=1)
        assert (aviso in panel._plan.text()) is (placa == "nvenc")
        assert "menor)" in panel._plan.text()
    finally:
        panel.shutdown()
        panel.deleteLater()
    assert panel._sampling_runner.active == 0


@pytest.mark.parametrize(("disponivel", "mede"), [
    (None, False),                  # não saber é não medir
    (2_700_000_000, False),         # uma conversão 4K rodando ao lado
    (7_500_000_000, True),          # a máquina ociosa
])
def test_amostra_4k_so_roda_com_memoria_para_ela(monkeypatch, disponivel, mede) -> None:
    from videomanager.application.errors import ConversionError as Falha
    from videomanager.infrastructure.ffmpeg import sample

    monkeypatch.setattr(sample, "available_bytes", lambda: disponivel)
    uhd = _media(LocalStream(0, "video", "h264", width=3840, height=2160, fps=30.0), AUDIO)
    assert sample.fits_in_memory(uhd) is mede
    if not mede:
        rodou = []
        monkeypatch.setattr(sample.ProcessControl, "run", lambda *a, **k: rodou.append(a))
        with pytest.raises(Falha):
            sample.sample_video_kbps(uhd, VideoTarget(container="mp4", video_codec="h264", quality="balanced"),
                                     TOOLS, sample.ProcessControl())
        assert rodou == []


class TestTetoNoComando:
    @pytest.mark.parametrize(("codec", "esperado"), [
        ("h264", ["-maxrate", "7000k", "-bufsize", "7000k"]),
        ("hevc", ["-maxrate", "7000k", "-bufsize", "7000k"]),
        ("av1", ["-svtav1-params", "mbr=7000"]),
    ])
    def test_teto_por_encoder(self, codec, esperado) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec=codec,
                                                                  quality="balanced", max_kbps=7000),
                                Path("/s/x"), TOOLS)
        inicio = args.index(esperado[0])
        assert args[inicio:inicio + len(esperado)] == esperado

    def test_sem_teto_nada_muda(self) -> None:
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec="h264",
                                                                  quality="balanced"), Path("/s/x"), TOOLS)
        assert "-maxrate" not in args and "-svtav1-params" not in args

    def test_placa_nao_recebe_teto(self, monkeypatch) -> None:
        from dataclasses import replace

        from videomanager.infrastructure.ffmpeg import hardware
        placa = replace(hardware.software_encoder("h264"), name="h264_nvenc", quality=("-rc", "constqp"))
        monkeypatch.setattr(hardware, "resolve", lambda *a, **k: placa)
        args = build_video_args(_media(VIDEO, AUDIO), VideoTarget(container="mp4", video_codec="h264",
                                                                  hardware="nvenc", quality="balanced",
                                                                  max_kbps=7000), Path("/s/x"), TOOLS)
        assert "-maxrate" not in args


def test_audio_abaixo_do_teto_sai_da_fila_com_o_motivo(tmp_path) -> None:
    from videomanager.bootstrap import build_processing_service
    from videomanager.domain.compression import LEVELS, compression_target

    origem = tmp_path / "musica.mp3"
    origem.write_bytes(b"x")
    mp3 = LocalMedia(origem, 60.0, "mp3", 720_000, (LocalStream(0, "audio", "mp3", bitrate=96.0),))
    alvo = compression_target(mp3, LEVELS[1], "h264", "software")
    with pytest.raises(ConversionError, match="96 kbps"):
        build_processing_service().convert(mp3, alvo, same_folder=True, fallback=tmp_path, compress=True)
    assert list(tmp_path.iterdir()) == [origem]  # nada reservado
    # Fora da compressão, a mesma cópia continua sendo um pedido legítimo.
    build_processing_service().convert(mp3, alvo, same_folder=True, fallback=tmp_path)
