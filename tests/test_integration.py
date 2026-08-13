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


# ---------------------------------------------------------------------------
# Edição multipista
#
# Estes não tocam a rede — precisam só do ffmpeg —, mas moram aqui porque
# compartilham a regra que dá sentido ao arquivo: **conferir o resultado com o
# ffprobe, e não a ausência de exceção**. Foi assim que se descobriu que a
# mixagem tirava 3 dB do material mono sem ninguém pedir; um teste que apenas
# executasse a exportação teria passado.
# ---------------------------------------------------------------------------


def gerar_video(path: Path, tools, *, duracao: float = 4.0, canais: int = 2) -> Path:
    layout = "stereo" if canais == 2 else "mono"
    subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30:duration={duracao}",
         "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={duracao}:sample_rate=48000",
         "-af", f"aformat=channel_layouts={layout}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True,
    )
    return path


def volume_medio(path: Path, tools) -> float:
    saida = subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-nostdin", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    linha = next(l for l in saida.splitlines() if "mean_volume:" in l)
    return float(linha.split("mean_volume:")[1].split("dB")[0])


class TestExportacaoDaEdicao:
    def test_ganho_em_decibeis_sai_exato_no_arquivo(self, tmp_path: Path, tools) -> None:
        """0 dB tem de significar "não mexe", e -6 dB tem de ser -6 dB.

        A conversão de layout do ffmpeg normaliza a potência e tira 3 dB de
        material mono. O defeito não levanta erro, não aparece na duração e não
        aparece em nenhuma tela: só medindo.
        """
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        for canais in (1, 2):
            origem = gerar_video(tmp_path / f"fonte{canais}.mp4", tools, canais=canais)
            projeto = new_project(media_ref(probe_file(origem, tools)))
            alvo = projeto.clips[0]

            neutro = tmp_path / f"neutro{canais}.mp4"
            Converter(probe_file(origem, tools), Composition(projeto, "mp4"),
                      neutro, tools).run()
            assert volume_medio(neutro, tools) == pytest.approx(
                volume_medio(origem, tools), abs=0.6
            ), f"0 dB alterou o som ({canais} canal/canais)"

            baixado = tmp_path / f"baixo{canais}.mp4"
            Converter(
                probe_file(origem, tools),
                Composition(projeto.with_updated_clip(alvo.clip_id, gain_db=-6.0), "mp4"),
                baixado, tools,
            ).run()
            assert volume_medio(baixado, tools) == pytest.approx(
                volume_medio(neutro, tools) - 6.0, abs=0.6
            ), f"-6 dB não saiu -6 dB ({canais} canal/canais)"

    def test_bloco_mudo_e_trilha_muda_nao_chegam_ao_arquivo(
        self, tmp_path: Path, tools
    ) -> None:
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        origem = gerar_video(tmp_path / "fonte.mp4", tools)
        projeto = new_project(media_ref(probe_file(origem, tools)))
        calado = projeto.with_updated_clip(projeto.clips[0].clip_id, muted=True)

        saida = tmp_path / "mudo.mp4"
        Converter(probe_file(origem, tools), Composition(calado, "mp4"), saida, tools).run()
        _, streams = ffprobe_streams(saida, tools)
        assert stream_of(streams, "video") is not None, "a imagem continua"
        assert stream_of(streams, "audio") is None, "o som calado não foi gravado"

    def test_montagem_de_duas_trilhas_tem_a_duracao_da_mais_longa(
        self, tmp_path: Path, tools
    ) -> None:
        from videomanager.core.composer import Composition
        from videomanager.core.project import Clip, media_ref, new_project
        from videomanager.core.converter import Converter, probe_file

        curto = gerar_video(tmp_path / "curto.mp4", tools, duracao=3.0)
        longo = gerar_video(tmp_path / "longo.mp4", tools, duracao=6.0)
        projeto = new_project(media_ref(probe_file(curto, tools)))
        som = media_ref(probe_file(longo, tools))
        # O áudio do segundo arquivo entra numa trilha própria, começando aos 2 s.
        projeto = projeto.with_clip(
            len(projeto.tracks) - 1,
            Clip(media=som, start=2.0, duration=6.0),
        )

        saida = tmp_path / "montagem.mp4"
        Converter(probe_file(curto, tools), Composition(projeto, "mp4"), saida, tools).run()
        formato, streams = ffprobe_streams(saida, tools)
        assert float(formato["duration"]) == pytest.approx(8.0, abs=0.2)
        assert stream_of(streams, "audio") is not None

    def test_previa_de_audio_sai_na_taxa_que_a_placa_espera(
        self, tmp_path: Path, tools
    ) -> None:
        """O contrato entre o compositor e a saída de som.

        A prévia toca PCM cru: se a taxa, o número de canais ou o formato
        mudarem de um lado sem o outro, o som toca acelerado ou lento em vez de
        falhar — foi exatamente esse o defeito relatado (som ao dobro).
        """
        from videomanager.core.composer import CHANNELS, SAMPLE_RATE, audio_command
        from videomanager.core.converter import probe_file
        from videomanager.core.project import media_ref, new_project

        origem = gerar_video(tmp_path / "fonte.mp4", tools, duracao=3.0)
        projeto = new_project(media_ref(probe_file(origem, tools)))
        pcm = subprocess.run(
            audio_command(projeto, 0.0, tools), capture_output=True
        ).stdout
        esperado = projeto.duration * SAMPLE_RATE * CHANNELS * 2  # s16le
        assert len(pcm) == pytest.approx(esperado, rel=0.02)


class TestCodificacaoPorPlaca:
    """A placa precisa **obedecer** ao número de qualidade, não só aceitar o argumento.

    Um encoder de placa que recebe o número sem o controle de taxa o descarta em
    silêncio e grava no bitrate padrão dele. Não há erro, não há aviso, o arquivo
    existe e a duração confere — só a imagem é pior. Nenhum teste offline alcança
    isso: é preciso codificar de verdade e comparar.
    """

    def _fonte_exigente(self, tmp_path: Path, tools) -> Path:
        """Ruído a 1080p: o material que mais expõe um bitrate baixo demais.

        Vídeo comum disfarça o defeito — o encoder tem folga de sobra para uma
        cena parada. É preciso um quadro que não se deixe comprimir para que a
        diferença entre "obedeceu ao pedido" e "gravou no padrão dele" apareça.
        """
        origem = tmp_path / "ruido.mp4"
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y",
             "-f", "lavfi", "-i", "nullsrc=s=1920x1080:r=30:d=3",
             "-vf", "geq=random(1)*255:128:128",
             "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(origem)],
            check=True, capture_output=True,
        )
        return origem

    def _fidelidade(self, origem: Path, saida: Path, tools) -> float:
        """SSIM médio da saída contra a origem. 1,0 é idêntico."""
        texto = subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-nostdin", "-i", str(saida),
             "-i", str(origem), "-lavfi", "ssim", "-f", "null", "-"],
            capture_output=True, text=True,
        ).stderr
        linha = next(l for l in texto.splitlines() if "All:" in l)
        return float(linha.split("All:")[1].split()[0])

    def _codificar(self, origem: Path, saida: Path, tools, args: list[str]) -> float:
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-i", str(origem),
             *args, "-an", str(saida)],
            check=True, capture_output=True,
        )
        return self._fidelidade(origem, saida, tools)

    def test_a_placa_nao_sai_pior_que_o_software(self, tmp_path: Path, tools) -> None:
        """Escolher a placa troca tempo por tamanho de arquivo — nunca por imagem.

        Com os argumentos anteriores (``-cq`` sem controle de taxa) esta mesma
        fonte saía com SSIM 0,482 contra 0,998 do software: metade da imagem
        perdida, sem erro nenhum, sem aviso, com a duração correta. É o defeito
        que este teste existe para não deixar voltar.
        """
        from videomanager.core import hwaccel

        if "nvenc" not in hwaccel.available(tools):
            pytest.skip("nenhuma placa NVIDIA responde nesta máquina")

        origem = self._fonte_exigente(tmp_path, tools)
        placa = self._codificar(
            origem, tmp_path / "placa.mp4", tools,
            hwaccel.encode_args("h264", "nvenc", tools),
        )
        software = self._codificar(
            origem, tmp_path / "software.mp4", tools,
            hwaccel.encode_args("h264", hwaccel.SOFTWARE, tools),
        )
        # Comparar com o software, e não com um número fixo, é o que mantém o
        # teste válido quando o material de teste ou a build do ffmpeg mudarem.
        assert placa >= software - 0.03, (
            f"a placa entregou SSIM {placa:.4f} contra {software:.4f} do software: "
            "o número de qualidade não está chegando ao encoder"
        )
