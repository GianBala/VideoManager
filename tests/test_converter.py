"""Testes da conversão de arquivos locais.

Todos operam sobre a montagem dos argumentos do ffmpeg — que é função pura — e por
isso não precisam do ffmpeg instalado nem de nenhum arquivo de mídia real. O que
se afirma aqui é o que separa uma conversão de um segundo de uma de dez minutos:
quando há cópia direta e quando há recodificação.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.media import VideoTarget
from videomanager.infrastructure.ffmpeg.converter import _ratio
from videomanager.infrastructure.ffmpeg.converter import build_args
from videomanager.domain.compatibility import can_copy_audio
from videomanager.application.media.conversion_description import describe_target
from videomanager.domain.compatibility import needs_video_reencode
from videomanager.infrastructure.ffmpeg.converter import output_path
from videomanager.application.errors import ConversionError

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
DEST = Path("/saida/arquivo.mp3")


def media(
    *,
    audio_codec: str | None = "aac",
    video_codec: str | None = "h264",
    height: int = 1080,
    name: str = "entrada.mp4",
) -> LocalMedia:
    streams: list[LocalStream] = []
    if video_codec:
        streams.append(
            LocalStream(index=0, kind="video", codec=video_codec, height=height, width=1920, fps=30.0)
        )
    if audio_codec:
        streams.append(
            LocalStream(index=1, kind="audio", codec=audio_codec, bitrate=160.0, sample_rate=48000, channels=2)
        )
    return LocalMedia(
        path=Path(f"/entrada/{name}"),
        duration=600.0,
        format_name="mov,mp4",
        size=90_000_000,
        streams=tuple(streams),
    )


def args_for(m: LocalMedia, target, dest: Path = DEST) -> list[str]:
    return build_args(m, target, dest, TOOLS)


# ---------------------------------------------------------------------------
# Cópia direta: o que faz a conversão levar um segundo em vez de dez minutos
# ---------------------------------------------------------------------------


class TestCopiaDireta:
    @pytest.mark.parametrize(
        ("origem", "alvo"),
        [("aac", "m4a"), ("aac", "aac"), ("mp3", "mp3"), ("opus", "opus"),
         ("flac", "flac"), ("vorbis", "vorbis"), ("pcm_s16le", "wav")],
    )
    def test_mesmo_codec_copia(self, origem: str, alvo: str) -> None:
        assert can_copy_audio(media(audio_codec=origem), alvo) is True

    @pytest.mark.parametrize(
        ("origem", "alvo"), [("aac", "mp3"), ("mp3", "m4a"), ("opus", "mp3"), ("aac", "flac")]
    )
    def test_codec_diferente_recodifica(self, origem: str, alvo: str) -> None:
        assert can_copy_audio(media(audio_codec=origem), alvo) is False

    def test_copia_usa_c_copy_e_nao_define_bitrate(self) -> None:
        args = args_for(media(audio_codec="aac"), AudioTarget(codec="m4a", bitrate="320"))
        assert "-c:a" in args and args[args.index("-c:a") + 1] == "copy"
        assert "-b:a" not in args, "pedir bitrate junto de cópia é contraditório"

    def test_sem_audio_no_arquivo_falha_com_mensagem_clara(self) -> None:
        with pytest.raises(ConversionError, match="não tem trilha de áudio"):
            args_for(media(audio_codec=None), AudioTarget(codec="mp3"))


# ---------------------------------------------------------------------------
# Áudio
# ---------------------------------------------------------------------------


class TestAudio:
    def test_mp3_usa_lame_com_bitrate_e_id3v23(self) -> None:
        args = args_for(media(), AudioTarget(codec="mp3", bitrate="320"))
        assert args[args.index("-c:a") + 1] == "libmp3lame"
        assert args[args.index("-b:a") + 1] == "320k"
        # Sem ID3v2.3 o Windows Explorer não exibe título nem artista.
        assert args[args.index("-id3v2_version") + 1] == "3"

    @pytest.mark.parametrize("codec", ("flac", "wav", "alac"))
    def test_sem_perda_nao_recebe_bitrate(self, codec: str) -> None:
        args = args_for(media(audio_codec="aac"), AudioTarget(codec=codec, bitrate="320"))
        assert "-b:a" not in args

    def test_descarta_video_e_legendas(self) -> None:
        args = args_for(media(), AudioTarget(codec="mp3"))
        assert "-vn" in args and "-sn" in args
        assert args[args.index("-map") + 1] == "0:a:0"

    def test_progresso_legivel_por_maquina(self) -> None:
        """``-progress pipe:1`` é estável entre versões e independe de locale."""
        args = args_for(media(), AudioTarget(codec="mp3"))
        assert args[args.index("-progress") + 1] == "pipe:1"
        assert "-nostats" in args

    def test_nostdin_sempre_presente(self) -> None:
        """Sem isso o ffmpeg consome o stdin do processo pai e pode travar."""
        for target in (AudioTarget(codec="mp3"), VideoTarget(container="mkv")):
            assert "-nostdin" in args_for(media(), target)

    def test_metadados_preservados(self) -> None:
        args = args_for(media(), AudioTarget(codec="mp3"))
        assert args[args.index("-map_metadata") + 1] == "0"


# ---------------------------------------------------------------------------
# Vídeo: recodificar só quando é inevitável
# ---------------------------------------------------------------------------


class TestVideo:
    def test_troca_de_container_apenas_copia(self) -> None:
        target = VideoTarget(container="mkv", video_codec="copy", audio_codec="copy")
        assert needs_video_reencode(media(), target) is False
        args = args_for(media(), target, Path("/saida/x.mkv"))
        assert args[args.index("-c:v") + 1] == "copy"

    def test_redimensionar_forca_recodificacao(self) -> None:
        """Não existe redimensionar copiando: o quadro tem de ser reencodado."""
        target = VideoTarget(container="mp4", video_codec="copy", height=480)
        assert needs_video_reencode(media(height=1080), target) is True
        args = args_for(media(height=1080), target, Path("/saida/x.mp4"))
        assert args[args.index("-c:v") + 1] == "libx264"
        assert args[args.index("-vf") + 1] == "scale=-2:480"

    def test_scale_usa_menos_2_para_largura_par(self) -> None:
        """H.264 exige dimensões pares; ``-2`` garante isso mantendo a proporção."""
        args = args_for(media(), VideoTarget(video_codec="h264", height=720), Path("/s/x.mp4"))
        assert "scale=-2:720" in args

    def test_mudar_fps_forca_recodificacao(self) -> None:
        target = VideoTarget(container="mp4", video_codec="copy", fps=30.0)
        assert needs_video_reencode(media(), target) is True

    def test_altura_igual_a_origem_nao_recodifica(self) -> None:
        """Pedir 1080p num vídeo que já é 1080p não deve recodificar."""
        target = VideoTarget(container="mkv", video_codec="copy", height=1080)
        assert needs_video_reencode(media(height=1080), target) is False

    def test_h264_recebe_pix_fmt_compativel(self) -> None:
        args = args_for(media(), VideoTarget(video_codec="h264"), Path("/s/x.mp4"))
        assert args[args.index("-pix_fmt") + 1] == "yuv420p"

    def test_mp4_recebe_faststart(self) -> None:
        """Índice no início: permite começar a assistir antes de baixar tudo."""
        args = args_for(media(), VideoTarget(container="mp4"), Path("/s/x.mp4"))
        assert args[args.index("-movflags") + 1] == "+faststart"

    def test_mkv_nao_recebe_faststart(self) -> None:
        assert "-movflags" not in args_for(
            media(), VideoTarget(container="mkv"), Path("/s/x.mkv")
        )

    def test_arquivo_sem_video_falha_com_mensagem_clara(self) -> None:
        with pytest.raises(ConversionError, match="não tem trilha de vídeo"):
            args_for(media(video_codec=None), VideoTarget(container="mp4"))

    def test_arquivo_sem_audio_nao_mapeia_audio(self) -> None:
        args = args_for(media(audio_codec=None), VideoTarget(container="mkv"), Path("/s/x.mkv"))
        assert "0:a:0" not in args
        assert "-c:a" not in args


class TestContainerNaoAceitaOCodec:
    """Copiar para um container que não guarda aquele codec não é possível.

    Regressão: pedir "copiar sem recodificar" de um MP4 (H.264+AAC) para .webm
    montava ``-c:v copy`` e o ffmpeg abortava com "Only VP8/VP9/AV1 video and
    Vorbis/Opus audio are supported for WebM" — depois de a tarefa já estar na
    fila. Agora a incompatibilidade é resolvida na montagem e anunciada antes.
    """

    def test_h264_para_webm_recodifica_as_duas_trilhas(self) -> None:
        target = VideoTarget(container="webm", video_codec="copy", audio_codec="copy")
        args = args_for(media(), target, Path("/s/x.webm"))
        assert args[args.index("-c:v") + 1] == "libvpx-vp9"
        assert args[args.index("-c:a") + 1] == "libopus"

    def test_vp9_para_mp4_recodifica_as_duas_trilhas(self) -> None:
        origem = media(video_codec="vp9", audio_codec="opus")
        target = VideoTarget(container="mp4", video_codec="copy", audio_codec="copy")
        args = args_for(origem, target, Path("/s/x.mp4"))
        assert args[args.index("-c:v") + 1] == "libx264"
        assert args[args.index("-c:a") + 1] == "aac"

    def test_vp9_para_webm_ainda_copia(self) -> None:
        """O que o container aceita continua sendo copiado, sem custo nenhum."""
        origem = media(video_codec="vp9", audio_codec="opus")
        target = VideoTarget(container="webm", video_codec="copy", audio_codec="copy")
        args = args_for(origem, target, Path("/s/x.webm"))
        assert args[args.index("-c:v") + 1] == "copy"
        assert args[args.index("-c:a") + 1] == "copy"

    def test_a_descricao_avisa_antes_de_converter(self) -> None:
        target = VideoTarget(container="webm", video_codec="copy", audio_codec="copy")
        texto = describe_target(media(), target)
        assert "VP9" in texto and "copiado" not in texto


# ---------------------------------------------------------------------------
# Descrição: precisa dizer a verdade sobre recodificação
# ---------------------------------------------------------------------------


class TestDescricao:
    def test_avisa_copia_direta(self) -> None:
        texto = describe_target(media(audio_codec="aac"), AudioTarget(codec="m4a"))
        assert "cópia direta" in texto

    def test_mostra_bitrate_quando_recodifica(self) -> None:
        texto = describe_target(media(audio_codec="aac"), AudioTarget(codec="mp3", bitrate="192"))
        assert "192" in texto

    def test_descricao_de_video_acompanha_a_decisao_real(self) -> None:
        """Regressão: a descrição dizia "vídeo copiado" numa conversão que
        recodificava, porque a decisão estava duplicada em dois lugares."""
        target = VideoTarget(container="mp4", video_codec="copy", height=240)
        texto = describe_target(media(height=1080), target)
        assert "recodifica" in texto
        assert "copiado" not in texto

    def test_descricao_diz_copiado_quando_de_fato_copia(self) -> None:
        texto = describe_target(media(), VideoTarget(container="mkv", video_codec="copy"))
        assert "copiado" in texto


# ---------------------------------------------------------------------------
# Caminho de saída
# ---------------------------------------------------------------------------


class TestOutputPath:
    """O nome de saída. Todos usam ``tmp_path`` porque a função **reserva** o
    nome criando o arquivo, e não apenas o calcula — ver
    :class:`TestReservaDoDestino`."""

    def test_extensao_vem_do_alvo(self, tmp_path: Path) -> None:
        destino = output_path(tmp_path / "video.mp4", AudioTarget(codec="mp3"), tmp_path)
        assert destino == tmp_path / "video.mp3"

    def test_m4a_para_aac_e_alac(self, tmp_path: Path) -> None:
        assert output_path(tmp_path / "a.mp4", AudioTarget(codec="aac"), tmp_path).suffix == ".m4a"
        assert output_path(tmp_path / "b.mp4", AudioTarget(codec="alac"), tmp_path).suffix == ".m4a"

    def test_vorbis_sai_como_ogg(self, tmp_path: Path) -> None:
        destino = output_path(tmp_path / "a.mp4", AudioTarget(codec="vorbis"), tmp_path)
        assert destino.suffix == ".ogg"

    def test_nunca_sobrescreve_a_origem(self, tmp_path: Path) -> None:
        """Converter um MP3 para MP3 com outro bitrate é pedido legítimo.

        Sem esta proteção, a saída apontaria para o próprio arquivo de entrada e
        o ffmpeg o destruiria durante a leitura.
        """
        origem = tmp_path / "musica.mp3"
        origem.write_bytes(b"conteudo")
        destino = output_path(origem, AudioTarget(codec="mp3"), tmp_path)
        assert destino != origem
        assert "convertido" in destino.name

    def test_nao_sobrescreve_arquivo_existente(self, tmp_path: Path) -> None:
        (tmp_path / "video.mp4").write_bytes(b"origem")
        (tmp_path / "video.mp3").write_bytes(b"ja existe")
        destino = output_path(tmp_path / "video.mp4", AudioTarget(codec="mp3"), tmp_path)
        assert destino.name == "video (2).mp3"


class TestReservaDoDestino:
    """O nome é reservado no ato, e não apenas consultado.

    ``output_path`` é chamado ao **enfileirar**, e o ffmpeg grava minutos
    depois: enquanto era só uma consulta ao disco, duas tarefas da mesma origem
    recebiam o mesmo caminho e a segunda sobrescrevia o resultado pronto da
    primeira — sem aviso, e com o ``-y`` do ffmpeg contra o qual não havia
    defesa.
    """

    def test_dois_pedidos_da_mesma_origem_nao_colidem(self, tmp_path: Path) -> None:
        origem = tmp_path / "video.mp4"
        origem.write_bytes(b"origem")
        alvo = AudioTarget(codec="mp3")

        primeiro = output_path(origem, alvo, tmp_path)
        segundo = output_path(origem, alvo, tmp_path)

        assert primeiro != segundo
        assert primeiro.name == "video.mp3"
        assert segundo.name == "video (2).mp3"

    def test_a_reserva_existe_em_disco(self, tmp_path: Path) -> None:
        # É o arquivo vazio que segura o nome; sem ele a consulta seguinte
        # devolveria o mesmo caminho.
        destino = output_path(tmp_path / "a.mp4", AudioTarget(codec="mp3"), tmp_path)
        assert destino.is_file()
        assert destino.stat().st_size == 0

    def test_pasta_de_destino_e_criada(self, tmp_path: Path) -> None:
        destino = output_path(
            tmp_path / "a.mp4", AudioTarget(codec="mp3"), tmp_path / "nova" / "pasta"
        )
        assert destino.parent.is_dir()

    def test_pasta_impossivel_vira_erro_do_dominio(self, tmp_path: Path) -> None:
        # Uma pasta que não dá para criar precisa falhar com mensagem
        # apresentável ao enfileirar, e não com OSError cru dentro de um slot.
        bloqueio = tmp_path / "arquivo"
        bloqueio.write_bytes(b"nao sou pasta")
        with pytest.raises(ConversionError):
            output_path(tmp_path / "a.mp4", AudioTarget(codec="mp3"), bloqueio / "dentro")


class TestProporcaoDoPixel:
    """A leitura do ``sample_aspect_ratio``, que o ffprobe escreve com ":".

    Só este número distingue um arquivo 720×480 de 4:3 de um 720×480 que se
    exibe em 16:9. Sem ele, o segundo saía achatado da edição — e nada falhava.
    """

    def test_le_a_razao_com_dois_pontos(self) -> None:
        assert _ratio("32:27") == pytest.approx(32 / 27)
        assert _ratio("1:1") == 1.0

    def test_desconhecida_vira_nada(self) -> None:
        # "0:1" e "N/A" são como o ffprobe diz "não sei" — diferente de "é
        # quadrado", ainda que o ffmpeg trate os dois igual na hora de desenhar.
        assert _ratio("0:1") is None
        assert _ratio("N/A") is None
        assert _ratio(None) is None

    def test_barra_nao_e_razao_de_pixel(self) -> None:
        # O framerate usa barra; a proporção do pixel, dois-pontos. Aceitar as
        # duas formas aqui esconderia um campo lido do lugar errado.
        assert _ratio("30/1") is None
