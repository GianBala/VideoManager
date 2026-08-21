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
from dataclasses import replace
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


def distintos(path: Path, tools) -> int:
    """Quantas imagens **diferentes** o arquivo tem, e não quantos quadros.

    O ``mpdecimate`` descarta o quadro que repete o anterior. Comparar hashes
    não serviria: a recodificação com perdas faz o quadro repetido não sair byte
    a byte igual, e todos pareceriam distintos.
    """
    saida = subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-i", str(path), "-vf", "mpdecimate",
         "-loglevel", "info", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    return int(saida.split("frame=")[-1].split()[0])


def _rate_of(path: Path, tools) -> tuple[float, int, float]:
    formato, streams = ffprobe_streams(path, tools)
    video = stream_of(streams, "video")
    assert video is not None
    num, den = video["r_frame_rate"].split("/")
    return float(num) / float(den), int(video.get("nb_frames") or 0), float(
        formato["duration"]
    )


def _sar_of(stream: dict) -> float:
    """Proporção do pixel de um stream, como o ffprobe a escreve ("32:27")."""
    texto = str(stream.get("sample_aspect_ratio") or "1:1")
    numerador, _, denominador = texto.partition(":")
    try:
        return float(numerador) / float(denominador)
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0


def brilho_medio(path: Path, tools, at: float) -> float:
    """Luminância média do quadro em ``at``, de 0 (preto) a 255.

    É como se afirma que **não há imagem** num trecho: a ausência de vídeo
    indevido não aparece na duração, nem nos streams, nem em exceção nenhuma.
    """
    quadro = subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-ss", f"{at:.3f}",
         "-i", str(path), "-frames:v", "1", "-vf", "scale=16:16",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    assert quadro, f"não saiu quadro em {at} s"
    return sum(quadro) / len(quadro)


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

    def test_som_separado_nao_leva_a_imagem_junto(self, tmp_path: Path, tools) -> None:
        """Separar o áudio e movê-lo não pode reaparecer como imagem.

        O bloco que "separar áudio" cria vem de um arquivo **com vídeo**, e a
        composição decidia o que desenhar pela mídia do bloco: o vídeo do som
        separado era sobreposto a tudo, no instante para onde o som fosse
        arrastado. Não levanta erro, não muda a duração e não muda os streams —
        só medindo a imagem no trecho em que ela não devia existir.
        """
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        origem = gerar_video(tmp_path / "fonte.mp4", tools, duracao=4.0)
        projeto = new_project(media_ref(probe_file(origem, tools)))
        projeto = projeto.detached_audio(projeto.clips[0].clip_id)
        som = [c for t in projeto.audio_tracks for c in t.clips][0]
        # O som vai para depois do fim da imagem: a edição passa a durar 8 s,
        # e os 4 s finais têm de ser tela preta com som.
        projeto = projeto.moved(
            som.clip_id, projeto.track_index(projeto.audio_tracks[0].track_id), 4.0
        )

        saida = tmp_path / "separado.mp4"
        Converter(
            probe_file(origem, tools), Composition(projeto, "mp4"), saida, tools
        ).run()

        formato, streams = ffprobe_streams(saida, tools)
        assert float(formato["duration"]) == pytest.approx(8.0, abs=0.3)
        assert stream_of(streams, "audio") is not None, "o som separado tem de sair"
        # Medido nesta fonte: 124,6 onde há imagem e 3,5 na tela preta (não é
        # zero cravado porque o h264 deixa resíduo em volta do preto). Com o
        # defeito, os 6 s mediam 124,7 — a imagem inteira, de volta.
        assert brilho_medio(saida, tools, 1.0) > 100, "a imagem existe onde ela está"
        assert brilho_medio(saida, tools, 6.0) < 10, (
            "onde só há som, a tela é preta — não o vídeo do bloco de áudio"
        )

    def test_subir_a_taxa_sozinho_nao_cria_fluidez(self, tmp_path: Path, tools) -> None:
        """24 fps exportado a 60 fps **não** fica mais fluido — e a opção existe.

        Sem interpolar, o arquivo tem 60 quadros por segundo e 24 imagens por
        segundo: os outros 36 são cópias. É o defeito mais fácil de não ver —
        duração certa, taxa certa no container, nenhum erro — e o único jeito de
        afirmar qualquer coisa aqui é contar as imagens **distintas**.
        """
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        duracao = 2.0
        origem = tmp_path / "cinema.mp4"
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"testsrc2=size=320x180:rate=24:duration={duracao}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", str(origem)],
            check=True,
        )
        projeto = replace(new_project(media_ref(probe_file(origem, tools))), fps=60.0)
        assert distintos(origem, tools) == 48, "a fonte tem 24 imagens por segundo"

        duplicado = tmp_path / "duplicado.mp4"
        Converter(
            probe_file(origem, tools), Composition(projeto, "mp4"), duplicado, tools
        ).run()
        taxa, _quadros, _dur = _rate_of(duplicado, tools)
        assert taxa == 60, "o container declara 60 fps"
        assert distintos(duplicado, tools) == 48, (
            "duplicar quadros não cria imagem nenhuma: a fluidez continua a de 24"
        )

        interpolado = tmp_path / "interpolado.mp4"
        Converter(
            probe_file(origem, tools),
            Composition(projeto, "mp4", interpolate=True),
            interpolado,
            tools,
        ).run()
        assert distintos(interpolado, tools) > 100, (
            "interpolando, os quadros que faltavam passam a existir"
        )
        # Para inventar um quadro, o filtro precisa do seguinte — e por isso
        # entrega alguns a menos do que recebeu (medido: 236 de 240). O bloco
        # acabava antes da hora e o fundo preto da composição aparecia no lugar:
        # duração certa, contagem certa, nenhum erro, e o fim preto.
        assert brilho_medio(interpolado, tools, duracao - 0.05) > 10, (
            "o fim do bloco interpolado não pode sair preto"
        )

    def test_interpolar_para_uma_tela_maior_continua_saindo_certo(
        self, tmp_path: Path, tools
    ) -> None:
        """A ordem barata é interpolar antes de ampliar — e o arquivo é o mesmo.

        Estimar movimento em pixels que o ``scale`` acabou de inventar custa o
        tamanho da tela e não acrescenta informação: o movimento está nos pixels
        originais. Mas trocar a ordem mexe no que sai, e é isso que se mede aqui
        — tamanho da tela, imagens distintas de verdade e o fim do bloco ainda
        reposto pelo ``tpad``, que agora corre antes do encaixe.
        """
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        duracao = 2.0
        origem = tmp_path / "pequeno.mp4"
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"testsrc2=size=320x180:rate=24:duration={duracao}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", str(origem)],
            check=True,
        )
        projeto = replace(
            new_project(media_ref(probe_file(origem, tools))),
            width=640, height=360, fps=60.0,
        )

        saida = tmp_path / "ampliado.mp4"
        Converter(
            probe_file(origem, tools),
            Composition(projeto, "mp4", interpolate=True),
            saida,
            tools,
        ).run()

        formato, streams = ffprobe_streams(saida, tools)
        video = stream_of(streams, "video")
        assert (video["width"], video["height"]) == (640, 360), (
            "interpolar antes de ampliar não muda a tela que foi pedida"
        )
        assert float(formato["duration"]) == pytest.approx(duracao, abs=0.2)
        assert distintos(saida, tools) > 100, (
            "os quadros que faltavam existem, estimados no material original"
        )
        assert brilho_medio(saida, tools, duracao - 0.05) > 10, (
            "o ``tpad`` continua repondo o fim, agora antes do encaixe"
        )

    def test_pixel_nao_quadrado_sai_com_a_forma_certa(self, tmp_path: Path, tools) -> None:
        """Rip de DVD e filmadora antiga guardam a imagem espremida.

        O arquivo tem 720×480 com pixel 32:27, que manda exibir em 16:9. O
        encaixe media a proporção em pixels guardados e o ``setsar=1`` logo
        depois fixava pixel quadrado: a imagem saía 3:2, achatada. Nada falhava
        — nem duração, nem streams, nem código de saída.
        """
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        origem = tmp_path / "anamorfico.mp4"
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=720x480:rate=30:duration=2",
             "-vf", "setsar=32/27", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(origem)],
            check=True,
        )
        local = probe_file(origem, tools)
        assert local.video is not None and local.video.sar == pytest.approx(32 / 27)

        projeto = new_project(media_ref(local))
        assert projeto.width == 854, "a tela nasce com a forma exibida"

        saida = tmp_path / "corrigido.mp4"
        Converter(local, Composition(projeto, "mp4"), saida, tools).run()
        _, streams = ffprobe_streams(saida, tools)
        video = stream_of(streams, "video")
        assert video is not None
        exibido = video["width"] / video["height"] * _sar_of(video)
        assert exibido == pytest.approx(16 / 9, abs=0.01), (
            "a fonte é exibida em 16:9 e tem de continuar 16:9"
        )

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


class TestTiraDeMiniaturas:
    """As miniaturas têm de sair nos instantes certos, nos dois caminhos.

    A tira passou a sair de um ffmpeg só (medido: 6,3× a 1080p, 10,6× a 4K), com
    queda para uma busca por miniatura quando o passo é grande demais. O risco
    dessa troca não é falhar: é a tira continuar aparecendo, bonita, mostrando os
    instantes errados — e ninguém percebe olhando doze quadradinhos de vídeo.

    A fonte é um esmaecimento linear de preto para branco, então o brilho médio
    de cada miniatura **diz o instante em que ela foi tirada**. É o que permite
    afirmar o instante sem comparar pixels com um caminho que pode estar errado
    junto.
    """

    def fonte(self, path: Path, tools, duracao: float) -> Path:
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c=white:s=320x180:r=30:d={duracao}",
             "-vf", f"fade=t=in:st=0:d={duracao}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
        return path

    def brilho(self, frame) -> float:
        return sum(frame.data) / len(frame.data)

    @pytest.mark.parametrize(
        ("duracao", "passe_unico"),
        [(12.0, True), (48.0, False)],
        ids=["passe unico", "uma busca por miniatura"],
    )
    def test_cada_miniatura_cai_no_instante_dela(
        self, tmp_path: Path, tools, duracao: float, passe_unico: bool
    ) -> None:
        from videomanager.core.preview import (
            _one_pass_worth_it,
            filmstrip_frames,
            filmstrip_times,
            render_frame,
        )

        origem = self.fonte(tmp_path / "fade.mp4", tools, duracao)
        quantas = 12
        tempos = filmstrip_times(0.0, duracao, quantas)
        assert _one_pass_worth_it(tempos) is passe_unico, (
            "o caminho exercitado não é o que este caso quer medir"
        )

        tira = dict(filmstrip_frames(origem, 0.0, duracao, quantas, (160, 90), tools))
        assert sorted(tira) == list(range(quantas)), "nenhuma miniatura pode faltar"

        for index, frame in tira.items():
            # Duas afirmações, e as duas são necessárias. A primeira é absoluta:
            # o esmaecimento é linear, então o brilho **diz** o instante, e isso
            # vale mesmo que os dois caminhos estejam errados juntos.
            esperado = 255 * tempos[index] / duracao
            assert self.brilho(frame) == pytest.approx(esperado, abs=8), (
                f"a miniatura {index} não é a do instante {tempos[index]:.2f} s"
            )
            # A segunda é a promessa da otimização: mudou o custo, não a imagem.
            # Foi ela que pegou o ``round`` do filtro ``fps`` deslocando a tira
            # inteira meio passo — sem falhar nada, só mostrando outro instante.
            antigo = render_frame(origem, tempos[index], (160, 90), tools)
            assert antigo is not None
            assert frame.data == antigo.data, (
                f"a miniatura {index} não é a mesma que uma busca direta devolve"
            )

    def test_as_miniaturas_saem_em_ordem_e_completas(self, tmp_path: Path, tools) -> None:
        from videomanager.core.preview import filmstrip_frames

        origem = self.fonte(tmp_path / "fade.mp4", tools, 12.0)
        saida = list(filmstrip_frames(origem, 0.0, 12.0, 12, (160, 90), tools))
        assert [i for i, _ in saida] == list(range(12)), (
            "a tira preenche da esquerda para a direita: a ordem é o efeito visível"
        )
        brilhos = [self.brilho(f) for _, f in saida]
        assert brilhos == sorted(brilhos), "o esmaecimento só cresce"

    def test_desistir_no_meio_encerra_o_ffmpeg(
        self, tmp_path: Path, tools, monkeypatch
    ) -> None:
        """Fechar o gerador tem de matar o processo do passe único.

        Sem isso, cada aproximação na linha do tempo deixaria um ffmpeg
        decodificando um trecho que ninguém vai mais ver — que é a raiz do
        estouro de memória que esta aba já causou.
        """
        from videomanager.core import preview

        abertos: list[subprocess.Popen] = []
        original = preview.subprocess.Popen

        def espiao(*args, **kwargs):
            processo = original(*args, **kwargs)
            abertos.append(processo)
            return processo

        monkeypatch.setattr(preview.subprocess, "Popen", espiao)

        origem = self.fonte(tmp_path / "fade.mp4", tools, 12.0)
        gerador = preview.filmstrip_frames(origem, 0.0, 12.0, 12, (160, 90), tools)
        next(gerador)
        assert abertos, "o passe único abre um processo só"
        gerador.close()
        assert abertos[0].poll() is not None, (
            "o ffmpeg continuou vivo depois de a tira ser abandonada"
        )


class TestInterpolacaoEmTrechos:
    """O arquivo paralelo tem de ser o mesmo que o serial produziria.

    O ``minterpolate`` é de uma thread só (medido: 110% de CPU em vinte
    núcleos), e dividir a linha do tempo é a única forma de usar o resto da
    máquina — medido, 43,7 s para 16,6 s em quatro trechos.

    O risco dessa troca não é falhar: é sair um arquivo **quase** certo, com uma
    trepidação a cada emenda ou o som deslocado, e isso não aparece em duração,
    em contagem de quadros nem em código de saída. Por isso a conferência aqui é
    contra o arquivo serial, quadro a quadro.
    """

    def fonte(self, path: Path, tools, *, duracao: float = 6.0) -> Path:
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y",
             "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=24:d={duracao}",
             "-f", "lavfi", "-i", f"sine=f=440:d={duracao}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            check=True,
        )
        return path

    def exporta(self, origem: Path, destino: Path, tools, trechos: int) -> Path:
        from videomanager.core import parallel_export
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        projeto = replace(new_project(media_ref(probe_file(origem, tools))), fps=60.0)
        comp = Composition(projeto, "mp4", interpolate=True)
        # O número de trechos é fixado no teste: ele depende da memória livre da
        # máquina, e um teste que mudasse de caminho conforme a carga não
        # afirmaria nada.
        original = parallel_export.plan_segments
        parallel_export.plan_segments = lambda _c: trechos
        try:
            from videomanager.core import converter as mod
            mod.plan_segments = lambda _c: trechos
            return Converter(probe_file(origem, tools), comp, destino, tools).run()
        finally:
            parallel_export.plan_segments = original
            mod.plan_segments = original

    def distintas(self, path: Path, tools) -> int:
        saida = subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "info", "-i", str(path),
             "-vf", "mpdecimate", "-loglevel", "debug", "-f", "null", "-"],
            capture_output=True, text=True,
        ).stderr
        return saida.count("keep pts")

    def test_o_paralelo_e_o_serial_produzem_o_mesmo_arquivo(
        self, tmp_path: Path, tools
    ) -> None:
        origem = self.fonte(tmp_path / "fonte.mp4", tools)
        serial = self.exporta(origem, tmp_path / "serial.mp4", tools, 1)
        paralelo = self.exporta(origem, tmp_path / "paralelo.mp4", tools, 3)

        fs, ss = ffprobe_streams(serial, tools)
        fp, sp = ffprobe_streams(paralelo, tools)
        assert float(fp["duration"]) == pytest.approx(float(fs["duration"]), abs=0.05)

        vs, vp = stream_of(ss, "video"), stream_of(sp, "video")
        assert (vp["width"], vp["height"]) == (vs["width"], vs["height"])
        assert int(vp["nb_frames"]) == int(vs["nb_frames"]), (
            "dividir não pode mudar quantos quadros saem"
        )

        # A afirmação que importa: a interpolação continua íntegra nas emendas.
        # Sem a sobra que cada trecho decodifica além do próprio fim, o ``tpad``
        # clona os últimos quadros e esta conta cai — medido, 464 contra 476.
        assert self.distintas(paralelo, tools) == self.distintas(serial, tools), (
            "as emendas perderam quadros interpolados"
        )

    def test_o_som_atravessa_inteiro_e_no_mesmo_volume(
        self, tmp_path: Path, tools
    ) -> None:
        # O som sai num passe só justamente para não ser emendado: emendar AAC
        # em ponto arbitrário produz salto ou estalo, que não aparece em
        # nenhuma contagem.
        origem = self.fonte(tmp_path / "fonte.mp4", tools)
        serial = self.exporta(origem, tmp_path / "serial.mp4", tools, 1)
        paralelo = self.exporta(origem, tmp_path / "paralelo.mp4", tools, 3)

        _f, sp = ffprobe_streams(paralelo, tools)
        audio = stream_of(sp, "audio")
        assert audio is not None, "o som não pode sumir na divisão"
        assert float(audio["duration"]) == pytest.approx(6.0, abs=0.15)
        assert volume_medio(paralelo, tools) == pytest.approx(
            volume_medio(serial, tools), abs=0.5
        )


    def test_o_container_do_projeto_vale_para_o_som_intermediario(
        self, tmp_path: Path, tools
    ) -> None:
        """Um projeto .webm sai em Opus, e Opus não cabe num .m4a.

        O som da exportação paralela é gerado num arquivo à parte, e o codec
        dele é escolhido a partir do container de saída. Com um nome fixo
        ".m4a", exportar um .webm interpolado falhava na hora de gerar o som —
        e só ele: o caminho serial escreve tudo num arquivo só e nunca passa por
        aqui. É o tipo de defeito que não aparece em nenhum projeto .mp4.
        """
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        origem = tmp_path / "fonte.webm"
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=6",
             "-f", "lavfi", "-i", "sine=f=440:d=6",
             "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
             "-c:a", "libopus", "-shortest", str(origem)],
            check=True,
        )
        projeto = replace(new_project(media_ref(probe_file(origem, tools))), fps=60.0)
        destino = tmp_path / "saida.webm"

        from videomanager.core import converter as mod
        original = mod.plan_segments
        mod.plan_segments = lambda _c: 3
        try:
            Converter(
                probe_file(origem, tools),
                Composition(projeto, "webm", interpolate=True),
                destino, tools,
            ).run()
        finally:
            mod.plan_segments = original

        _f, streams = ffprobe_streams(destino, tools)
        audio = stream_of(streams, "audio")
        assert audio is not None and audio["codec_name"] == "opus", (
            "o som do .webm precisa atravessar a exportação paralela"
        )


    def test_pasta_de_destino_com_aspa_no_nome(self, tmp_path: Path, tools) -> None:
        """Uma pasta chamada "vídeos do joão's" não pode quebrar a emenda.

        A lista que o demuxer ``concat`` lê põe cada arquivo entre aspas
        simples, e uma aspa no caminho fechava a string: a exportação falhava
        com "No such file or directory" apontando para um caminho cortado ao
        meio. A lista passou a citar só o nome do arquivo — que é gerado aqui e
        nunca tem nada especial —, então a sintaxe do ffmpeg deixou de encostar
        no caminho que o usuário escolheu.
        """
        from videomanager.core import converter as mod
        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.project import media_ref, new_project

        origem = self.fonte(tmp_path / "fonte.mp4", tools)
        pasta = tmp_path / "vídeos do joão's [2026]"
        pasta.mkdir()
        projeto = replace(new_project(media_ref(probe_file(origem, tools))), fps=60.0)

        original = mod.plan_segments
        mod.plan_segments = lambda _c: 2
        try:
            destino = Converter(
                probe_file(origem, tools),
                Composition(projeto, "mp4", interpolate=True),
                pasta / "saida.mp4", tools,
            ).run()
        finally:
            mod.plan_segments = original

        formato, _s = ffprobe_streams(destino, tools)
        assert float(formato["duration"]) == pytest.approx(6.0, abs=0.2)
        assert not [p for p in pasta.iterdir() if p.is_dir()], (
            "o diretório de trabalho não pode sobrar na pasta do usuário"
        )

    def test_cancelar_mata_os_trechos_e_nao_deixa_arquivo(
        self, tmp_path: Path, tools
    ) -> None:
        """Desistir precisa alcançar todos os processos, não só um.

        A exportação paralela abre vários ffmpeg; um cancelamento que parasse
        apenas o primeiro deixaria os outros queimando a máquina até o fim, e é
        exatamente o tipo de sobra que já esgotou a memória daqui.
        """
        import threading

        from videomanager.core.composer import Composition
        from videomanager.core.converter import Converter, probe_file
        from videomanager.core.errors import JobCancelled
        from videomanager.core.project import media_ref, new_project

        origem = self.fonte(tmp_path / "fonte.mp4", tools, duracao=20.0)
        projeto = replace(new_project(media_ref(probe_file(origem, tools))), fps=60.0)
        destino = tmp_path / "cancelada.mp4"
        conv = Converter(
            probe_file(origem, tools),
            Composition(projeto, "mp4", interpolate=True),
            destino,
            tools,
        )
        threading.Timer(2.0, conv.cancel).start()
        with pytest.raises(JobCancelled):
            conv.run()
        assert not destino.exists(), "cancelar não pode deixar arquivo no destino"


class TestReservaDoNomeComFfmpegDeVerdade:
    """A reserva de saída sobrevive a uma gravação de verdade.

    ``output_path`` deixou de apenas consultar o disco e passou a **criar** o
    arquivo vazio que segura o nome — sem isso, dois cliques em "Exportar"
    davam o mesmo caminho às duas tarefas e a segunda apagava o resultado da
    primeira em silêncio.

    O que se mede aqui é o outro lado dessa troca: que o ffmpeg escreve por cima
    da reserva sem reclamar, nos dois caminhos de gravação — o comando único e a
    exportação em trechos paralelos, que entrega o arquivo com um ``move`` sobre
    o destino. Um teste de "não levantou exceção" não serviria: o modo de falha
    seria justamente o arquivo de zero byte entregue como resultado.
    """

    def fonte(self, path: Path, tools) -> Path:
        subprocess.run(
            [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=2",
             "-f", "lavfi", "-i", "sine=f=440:d=2",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(path)],
            check=True,
        )
        return path

    def test_o_ffmpeg_grava_por_cima_da_reserva(self, tmp_path: Path, tools) -> None:
        origem = self.fonte(tmp_path / "fonte.mp4", tools)
        alvo = AudioTarget(codec="mp3", bitrate="128")

        destino = output_path(origem, alvo, tmp_path)
        assert destino.stat().st_size == 0, "a reserva nasce vazia"

        resultado = Converter(probe_file(origem, tools), alvo, destino, tools).run()

        formato, streams = ffprobe_streams(resultado, tools)
        assert resultado == destino
        assert stream_of(streams, "audio") is not None, "saiu com trilha de áudio"
        assert float(formato["duration"]) == pytest.approx(2.0, abs=0.3)

    def test_a_segunda_exportacao_nao_apaga_a_primeira(self, tmp_path: Path, tools) -> None:
        origem = self.fonte(tmp_path / "fonte.mp4", tools)
        alvo = AudioTarget(codec="mp3", bitrate="128")
        media = probe_file(origem, tools)

        # As duas reservas saem **antes** de qualquer gravação, que é a ordem em
        # que a interface enfileira: era exatamente aí que as duas recebiam o
        # mesmo caminho.
        primeiro = output_path(origem, alvo, tmp_path)
        segundo = output_path(origem, alvo, tmp_path)
        assert primeiro != segundo

        Converter(media, alvo, primeiro, tools).run()
        Converter(media, alvo, segundo, tools).run()

        assert primeiro.stat().st_size > 0, "o primeiro resultado continua lá"
        assert segundo.stat().st_size > 0

    def test_a_exportacao_em_trechos_entrega_sobre_a_reserva(
        self, tmp_path: Path, tools
    ) -> None:
        # O caminho paralelo não grava no destino: ele monta num temporário e
        # move por cima. Com o destino já existindo, esse ``move`` precisa
        # substituir em vez de recusar.
        from videomanager.core import converter as mod
        from videomanager.core import parallel_export
        from videomanager.core.composer import Composition
        from videomanager.core.project import media_ref, new_project

        origem = self.fonte(tmp_path / "fonte.mp4", tools)
        media = probe_file(origem, tools)
        projeto = replace(new_project(media_ref(media)), fps=48.0)
        comp = Composition(projeto, "mp4", interpolate=True)

        destino = output_path(origem, comp, tmp_path, " (editado)")
        assert destino.stat().st_size == 0

        original = parallel_export.plan_segments
        parallel_export.plan_segments = mod.plan_segments = lambda _c: 2
        try:
            resultado = Converter(media, comp, destino, tools).run()
        finally:
            parallel_export.plan_segments = mod.plan_segments = original

        formato, streams = ffprobe_streams(resultado, tools)
        assert resultado == destino
        assert destino.stat().st_size > 0, "a reserva virou arquivo de verdade"
        assert stream_of(streams, "video") is not None
        assert float(formato["duration"]) == pytest.approx(2.0, abs=0.3)
