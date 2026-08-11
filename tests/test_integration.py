"""Testes de ponta a ponta, com rede e ffmpeg de verdade.

Fora da execução padrão (marcados ``network``), porque dependem de conexão, de
mídias que podem sair do ar e de extratores que mudam. Rode com::

    pytest -m network

Estes testes verificam o que nenhum teste offline consegue: que o arquivo
produzido tem de fato as trilhas, os codecs e o bitrate pedidos. A conferência é
feita com ffprobe sobre a saída — não pela ausência de exceção, que é justamente
como um download de vídeo mudo passaria despercebido.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from videomanager.core import binaries
from videomanager.core.converter import (
    AudioTarget,
    Converter,
    can_copy_audio,
    output_path,
    probe_file,
)
from videomanager.core.downloader import Downloader
from videomanager.core.format_matrix import pick_audio, pick_video
from videomanager.core.probe import probe
from videomanager.core.selector import AudioRequest, VideoRequest, build_opts
from videomanager.core.settings import Settings

pytestmark = pytest.mark.network

# Fluxo HLS com trilhas de áudio separadas: exige mesclagem, que é o caminho em
# que um erro produz vídeo mudo em vez de falhar.
HLS_URL = (
    "https://devstreaming-cdn.apple.com/videos/streaming/examples/"
    "img_bipbop_adv_example_fmp4/master.m3u8"
)
# Áudio de domínio público (NASA), curto.
AUDIO_URL = "https://soundcloud.com/nasa/apollo-11-eagle-has-landed"


@pytest.fixture(scope="module")
def tools():
    found = binaries.find_tools()
    if found is None:
        pytest.skip("ffmpeg não disponível; rode a aplicação uma vez para provisioná-lo")
    return found


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Miniatura desligada: exige requisição extra e não é o objeto do teste.
    return Settings(download_dir=str(tmp_path), embed_thumbnail=False)


def ffprobe_streams(path: Path, tools) -> tuple[dict, list[dict]]:
    output = subprocess.run(
        [tools.ffprobe_str, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(output)
    return data["format"], data["streams"]


def stream_of(streams: list[dict], kind: str) -> dict | None:
    return next((s for s in streams if s.get("codec_type") == kind), None)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def test_hls_com_trilhas_separadas_sai_com_audio(tools, settings, tmp_path: Path) -> None:
    """O arquivo final precisa ter **vídeo e áudio**.

    Regressão do bug mais grave que a suíte pegou: as faixas de áudio deste
    manifesto declaram ``vcodec: "none"`` e omitem ``acodec``. Quando eram
    descartadas, o download terminava com sucesso e produzia um vídeo mudo —
    falha silenciosa, do tipo que só se descobre ao abrir o arquivo.
    """
    info = probe(HLS_URL, settings)
    assert info.matrix.audio, "as faixas de áudio precisam ser reconhecidas"

    request = VideoRequest(
        video=pick_video(info.matrix, max_height=480),
        audio=pick_audio(info.matrix),
        container="mp4",
    )
    opts, _plan = build_opts(request, info, settings, tools, tmp_path, tmp_path / "t")
    result = Downloader(opts).run(HLS_URL)

    assert result.path is not None and result.path.exists()
    container, streams = ffprobe_streams(result.path, tools)
    kinds = {s["codec_type"] for s in streams}
    assert kinds == {"video", "audio"}, f"esperado vídeo+áudio, obtido {kinds}"

    video = stream_of(streams, "video")
    assert video is not None
    assert video["codec_name"] == "h264"
    assert int(video["height"]) <= 480, "o limite de resolução deve ser respeitado"
    assert "mp4" in container["format_name"]


def test_audio_recodificado_atinge_o_bitrate_pedido(tools, settings, tmp_path: Path) -> None:
    """Quando os codecs diferem, o bitrate escolhido tem de valer de fato."""
    info = probe(AUDIO_URL, settings)
    aac = next((c for c in info.matrix.audio if c.family == "AAC"), None)
    if aac is None:
        pytest.skip("a fonte não oferece trilha AAC")

    opts, _ = build_opts(
        AudioRequest(audio=aac, codec="mp3", quality="320"),
        info, settings, tools, tmp_path, tmp_path / "t",
    )
    result = Downloader(opts).run(AUDIO_URL)

    assert result.path is not None and result.path.exists()
    _container, streams = ffprobe_streams(result.path, tools)
    audio = stream_of(streams, "audio")
    assert audio is not None
    assert audio["codec_name"] == "mp3"
    assert 300 <= int(audio["bit_rate"]) // 1000 <= 340


def test_metadados_gravados_no_mp3(tools, settings, tmp_path: Path) -> None:
    info = probe(AUDIO_URL, settings)
    opts, _ = build_opts(
        AudioRequest(audio=pick_audio(info.matrix), codec="mp3", quality="192"),
        info, settings, tools, tmp_path, tmp_path / "t",
    )
    result = Downloader(opts).run(AUDIO_URL)
    container, _streams = ffprobe_streams(result.path, tools)
    assert container.get("tags", {}).get("title"), "sem título, o arquivo aparece sem nome nos players"


def test_parciais_nao_vazam_para_a_pasta_de_destino(tools, settings, tmp_path: Path) -> None:
    destino = tmp_path / "final"
    destino.mkdir()
    info = probe(AUDIO_URL, settings)
    opts, _ = build_opts(
        AudioRequest(audio=pick_audio(info.matrix), codec="mp3"),
        info, settings, tools, destino, tmp_path / "temp",
    )
    Downloader(opts).run(AUDIO_URL)
    restos = [p.name for p in destino.iterdir() if p.suffix in (".part", ".ytdl")]
    assert not restos, f"sobras na pasta final: {restos}"


def test_cancelamento_interrompe_e_nao_deixa_arquivo(tools, settings, tmp_path: Path) -> None:
    """Cancelar tem de parar o download e não deixar arquivo final."""
    from videomanager.core.errors import JobCancelled

    info = probe(HLS_URL, settings)
    opts, _ = build_opts(
        VideoRequest(video=pick_video(info.matrix), audio=pick_audio(info.matrix)),
        info, settings, tools, tmp_path, tmp_path / "t",
    )
    downloader = Downloader(opts)
    # Cancela no primeiro relatório de progresso.
    downloader._on_progress = lambda _p: downloader.cancel()  # noqa: SLF001

    with pytest.raises(JobCancelled):
        downloader.run(HLS_URL)
    finais = [p for p in tmp_path.iterdir() if p.is_file() and p.suffix in (".mp4", ".mkv")]
    assert not finais, "cancelar não deve deixar arquivo final"


# ---------------------------------------------------------------------------
# Conversão local
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def arquivo_local(tools, tmp_path_factory) -> Path:
    """Baixa uma vez um arquivo pequeno para servir de origem nas conversões."""
    pasta = tmp_path_factory.mktemp("origem")
    settings = Settings(download_dir=str(pasta), embed_thumbnail=False)
    info = probe(AUDIO_URL, settings)
    opts, _ = build_opts(
        AudioRequest(audio=pick_audio(info.matrix), codec="best"),
        info, settings, tools, pasta, pasta / "t",
    )
    result = Downloader(opts).run(AUDIO_URL)
    assert result.path is not None
    return result.path


def test_copia_direta_preserva_o_bitrate_exato(tools, arquivo_local: Path, tmp_path: Path) -> None:
    """Cópia direta não pode alterar o áudio em nada."""
    media = probe_file(arquivo_local, tools)
    codec_alvo = "mp3" if media.audio and media.audio.codec == "mp3" else "m4a"
    if not can_copy_audio(media, codec_alvo):
        pytest.skip("a origem não permite cópia direta neste formato")

    original = media.audio.bitrate
    destino = output_path(arquivo_local, AudioTarget(codec=codec_alvo), tmp_path)
    saida = Converter(media, AudioTarget(codec=codec_alvo), destino, tools).run()

    convertido = probe_file(saida, tools)
    assert convertido.audio is not None and original is not None
    assert convertido.audio.codec == media.audio.codec
    assert abs(convertido.audio.bitrate - original) < 1.0


def test_conversao_para_mp3_reporta_progresso(tools, arquivo_local: Path, tmp_path: Path) -> None:
    """O progresso vem do ``-progress pipe:1``, não de raspar o stderr."""
    media = probe_file(arquivo_local, tools)
    target = AudioTarget(codec="flac")  # difere da origem, então recodifica
    destino = output_path(arquivo_local, target, tmp_path)

    percentuais: list[float] = []
    Converter(
        media, target, destino, tools,
        on_progress=lambda p: percentuais.append(p.percent) if p.percent else None,
    ).run()

    assert destino.exists()
    assert percentuais, "nenhum progresso reportado"
    assert percentuais == sorted(percentuais), "o progresso não pode andar para trás"


def test_arquivo_de_saida_nunca_sobrescreve_a_origem(tools, arquivo_local: Path) -> None:
    media = probe_file(arquivo_local, tools)
    codec = media.audio.codec if media.audio else "mp3"
    alvo = "mp3" if codec == "mp3" else "m4a"
    destino = output_path(arquivo_local, AudioTarget(codec=alvo), arquivo_local.parent)
    assert destino.resolve() != arquivo_local.resolve()
