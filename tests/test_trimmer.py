"""Testes do recorte de vídeo — a aba de edição.

Todos operam sobre funções puras: leitura de timecode, contas de quadro e
montagem dos argumentos do ffmpeg. Não é preciso ffmpeg instalado nem arquivo de
mídia real.

O que se afirma aqui é o que separa um recorte correto de um que parece correto:
que o quadro pedido é o quadro entregue (e não o seguinte), que a cópia direta
começa no keyframe que a tela anunciou, e que juntar trechos nunca acontece em
silêncio no modo "sem recodificar".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.core.binaries import FFmpegTools
from videomanager.core.converter import (
    LocalMedia,
    LocalStream,
    build_args,
    output_duration,
    output_path,
)
from videomanager.core.errors import ConversionError
from videomanager.core.trimmer import (
    CutMode,
    Segment,
    TrimTarget,
    build_trim_args,
    describe_trim,
    format_timecode,
    frame_index,
    frame_step,
    frame_time,
    keyframe_after,
    keyframe_at_or_before,
    nearest_keyframe,
    parse_timecode,
    seek_time,
)

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
DEST = Path("/saida/corte.mp4")

# Keyframes a cada 1,6 s — o intervalo que um encoder comum produz.
KEYFRAMES = (0.0, 1.6, 3.2, 4.8, 6.4, 8.0)


def media(
    *,
    video_codec: str | None = "h264",
    audio_codec: str | None = "aac",
    fps: float = 30.0,
    name: str = "entrada.mp4",
) -> LocalMedia:
    streams: list[LocalStream] = []
    if video_codec:
        streams.append(
            LocalStream(
                index=0, kind="video", codec=video_codec,
                height=1080, width=1920, fps=fps,
            )
        )
    if audio_codec:
        streams.append(
            LocalStream(index=1, kind="audio", codec=audio_codec, bitrate=160.0)
        )
    return LocalMedia(
        path=Path(f"/entrada/{name}"),
        duration=600.0,
        format_name="mov,mp4",
        size=90_000_000,
        streams=tuple(streams),
    )


def target(
    start: float = 10.0,
    end: float = 20.0,
    *,
    mode: CutMode = CutMode.EXACT,
    container: str = "mp4",
    anchor: float | None = None,
    extra: tuple[Segment, ...] = (),
    copy_metadata: bool = False,
) -> TrimTarget:
    return TrimTarget(
        segments=(Segment(start, end), *extra),
        container=container,
        mode=mode,
        anchor=anchor,
        copy_metadata=copy_metadata,
    )


def args_for(m: LocalMedia, t: TrimTarget, dest: Path = DEST) -> list[str]:
    return build_trim_args(m, t, dest, TOOLS)


# ---------------------------------------------------------------------------
# Timecode: o campo de tempo é digitável, então precisa aceitar o que se digita
# ---------------------------------------------------------------------------


class TestTimecode:
    @pytest.mark.parametrize(
        ("texto", "segundos"),
        [
            ("12", 12.0),
            ("12,5", 12.5),
            ("12.5", 12.5),          # o teclado numérico produz ponto
            ("1:23", 83.0),
            ("1:23,250", 83.25),
            ("0:01:02", 62.0),
            ("2:00:00", 7200.0),
            ("  0:00:05,001  ", 5.001),
        ],
    )
    def test_le_as_formas_que_o_usuario_digita(self, texto: str, segundos: float) -> None:
        assert parse_timecode(texto) == pytest.approx(segundos)

    @pytest.mark.parametrize(
        "texto", ["", "abc", "1:2:3:4", "-5", "1:99", "inf", "nan", "1e3", "10:"]
    )
    def test_recusa_o_que_nao_e_timecode(self, texto: str) -> None:
        assert parse_timecode(texto) is None

    @pytest.mark.parametrize("segundos", [0.0, 0.001, 5.5, 83.25, 3661.999])
    def test_ida_e_volta(self, segundos: float) -> None:
        # A ida e volta é o contrato do campo: o que a tela mostra tem de voltar
        # como o mesmo instante quando o usuário confirma sem editar.
        assert parse_timecode(format_timecode(segundos)) == pytest.approx(
            segundos, abs=0.001
        )

    def test_milissegundo_e_arredondado(self) -> None:
        # 5,3 chega aqui como 5,2999999: truncar mostraria "5,299" para quem
        # acabou de digitar "5,3".
        assert format_timecode(5.2999999) == "0:00:05,300"
        assert format_timecode(1.9996) == "0:00:02,000"

    def test_arredondamento_sobe_de_casa_sem_estourar(self) -> None:
        assert format_timecode(59.9999) == "0:01:00,000"

    def test_sem_milissegundos_para_a_regua(self) -> None:
        assert format_timecode(3725.4, milliseconds=False) == "1:02:05"


# ---------------------------------------------------------------------------
# Quadros: buscar o quadro certo é a promessa da aba inteira
# ---------------------------------------------------------------------------


class TestQuadros:
    def test_indice_do_quadro_na_tela(self) -> None:
        assert frame_index(0.0, 30) == 0
        assert frame_index(0.999, 30) == 29
        assert frame_index(1.0, 30) == 30

    def test_indice_absorve_erro_de_float(self) -> None:
        # 7,5 em 30 fps é a fronteira do quadro 225; calculado por acumulação de
        # float ele vira 7,499999999 e devolveria o quadro anterior.
        assert frame_index(7.499999999, 30) == 225

    def test_busca_recua_um_quarto_de_quadro(self) -> None:
        # O -ss entrega o primeiro quadro com pts >= ao pedido. Pedir o instante
        # exato erra por um quadro quando o float arredonda para cima.
        assert seek_time(7.5, 30) == pytest.approx(7.5 - 0.25 / 30)

    def test_busca_nunca_fica_negativa(self) -> None:
        assert seek_time(0.0, 30) == 0.0

    def test_busca_de_instante_no_meio_do_quadro_pega_o_quadro_de_tras(self) -> None:
        # 7,52 está dentro do quadro 225 (7,5 a 7,533): o que a tela mostra ali
        # é o 225, e é ele que o corte tem de conter.
        pedido = seek_time(7.52, 30)
        assert frame_time(225, 30) > pedido > frame_time(224, 30)

    def test_sem_fps_o_passo_fino_ainda_existe(self) -> None:
        # Um arquivo de áudio não tem quadro; 10 ms mantém a navegação útil.
        assert frame_step(None) == pytest.approx(0.010)
        assert seek_time(3.3, None) == pytest.approx(3.3)


# ---------------------------------------------------------------------------
# Trechos
# ---------------------------------------------------------------------------


class TestSegmento:
    def test_divide_em_dois(self) -> None:
        assert Segment(0, 10).split_at(4) == (Segment(0, 4), Segment(4, 10))

    @pytest.mark.parametrize("ponto", [0.0, 0.01, 9.99, 10.0])
    def test_nao_divide_onde_nao_cabe(self, ponto: float) -> None:
        # Dividir na ponta criaria um trecho de duração zero, que o ffmpeg
        # recusa — e que o usuário não pediu, já que ele clicou na borda.
        assert Segment(0, 10).split_at(ponto) == (Segment(0, 10),)

    def test_duracao_e_uso(self) -> None:
        assert Segment(2.5, 7.5).duration == pytest.approx(5.0)
        assert Segment(2.5, 7.5).is_usable
        assert not Segment(2.5, 2.51).is_usable


class TestAlvo:
    def test_sem_ancora_o_trecho_e_o_marcado(self) -> None:
        alvo = target(10.0, 20.0, mode=CutMode.EXACT)
        assert alvo.effective_segments == (Segment(10.0, 20.0),)
        assert alvo.output_duration == pytest.approx(10.0)
        assert alvo.drift == 0.0

    def test_copia_direta_comeca_no_keyframe(self) -> None:
        alvo = target(10.0, 20.0, mode=CutMode.FAST, anchor=9.6)
        assert alvo.effective_segments[0] == Segment(9.6, 20.0)
        assert alvo.output_duration == pytest.approx(10.4)
        assert alvo.drift == pytest.approx(0.4)

    def test_recodificacao_ignora_a_ancora(self) -> None:
        # A âncora é do modo rápido; no exato o corte é no quadro marcado, e
        # anunciar deslocamento ali seria mentira.
        alvo = target(10.0, 20.0, mode=CutMode.EXACT, anchor=9.6)
        assert alvo.drift == 0.0
        assert alvo.output_duration == pytest.approx(10.0)

    def test_duracao_da_saida_soma_os_trechos(self) -> None:
        alvo = target(0.0, 5.0, extra=(Segment(10.0, 12.5),))
        assert alvo.output_duration == pytest.approx(7.5)
        # É esta duração que vira o percentual da barra de progresso.
        assert output_duration(media(), alvo) == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------


class TestKeyframes:
    def test_onde_a_copia_comecaria(self) -> None:
        assert keyframe_at_or_before(KEYFRAMES, 5.0) == 4.8
        assert keyframe_at_or_before(KEYFRAMES, 4.8) == 4.8
        assert keyframe_at_or_before(KEYFRAMES, 0.0) == 0.0

    def test_proximo_serve_para_mover_a_marca(self) -> None:
        assert keyframe_after(KEYFRAMES, 5.0) == 6.4
        assert keyframe_after(KEYFRAMES, 8.0) is None

    def test_mais_proximo(self) -> None:
        assert nearest_keyframe(KEYFRAMES, 5.0) == 4.8
        assert nearest_keyframe(KEYFRAMES, 6.0) == 6.4

    def test_sem_mapa_de_keyframes_nao_quebra(self) -> None:
        # O mapeamento pode falhar num arquivo estranho; a aba continua servindo.
        assert keyframe_at_or_before((), 5.0) is None
        assert keyframe_after((), 5.0) is None


# ---------------------------------------------------------------------------
# Um trecho só: o caminho rápido, com -ss antes do -i
# ---------------------------------------------------------------------------


class TestTrechoUnico:
    def test_busca_acontece_na_entrada(self) -> None:
        # -ss depois do -i decodificaria o arquivo desde o começo. Num vídeo de
        # uma hora, a diferença entre as duas ordens é de minutos.
        args = args_for(media(), target(10.0, 20.0))
        assert args.index("-ss") < args.index("-i")

    def test_copia_direta_usa_a_ancora_anunciada(self) -> None:
        args = args_for(media(), target(10.0, 20.0, mode=CutMode.FAST, anchor=9.6))
        assert float(args[args.index("-ss") + 1]) == pytest.approx(9.6)
        assert args[args.index("-c") + 1] == "copy"
        # A duração conta a partir de onde a busca parou: sem isso o trecho
        # terminaria 0,4 s depois do ponto marcado.
        assert float(args[args.index("-t") + 1]) == pytest.approx(10.4)

    def test_copia_direta_evita_timestamp_negativo(self) -> None:
        args = args_for(media(), target(mode=CutMode.FAST, anchor=9.6))
        assert args[args.index("-avoid_negative_ts") + 1] == "make_zero"

    def test_corte_exato_recua_a_busca_e_recodifica(self) -> None:
        args = args_for(media(fps=30), target(10.0, 20.0, mode=CutMode.EXACT))
        assert float(args[args.index("-ss") + 1]) == pytest.approx(10.0 - 0.25 / 30)
        assert args[args.index("-c:v") + 1] == "libx264"
        assert "-c" not in args, "recodificar e copiar são excludentes"

    def test_corte_exato_recodifica_o_audio_junto(self) -> None:
        # Copiar o áudio manteria os quadros de som inteiros da origem, que
        # começam antes do corte e empurram a imagem para fora de sincronia.
        args = args_for(media(), target(mode=CutMode.EXACT))
        assert args[args.index("-c:a") + 1] == "aac"

    def test_webm_recodifica_para_vp9_e_opus(self) -> None:
        # H.264 dentro de um .webm gera arquivo que quase nenhum player abre.
        args = args_for(media(video_codec="vp9"), target(container="webm"))
        assert args[args.index("-c:v") + 1] == "libvpx-vp9"
        assert args[args.index("-c:a") + 1] == "libopus"
        assert args[args.index("-b:v") + 1] == "0", "sem isto o VP9 ignora o CRF"

    def test_mp4_recebe_faststart(self) -> None:
        assert "+faststart" in args_for(media(), target())

    def test_mkv_nao_recebe_faststart(self) -> None:
        assert "+faststart" not in args_for(media(), target(container="mkv"))

    def test_arquivo_sem_audio_nao_mapeia_audio(self) -> None:
        args = args_for(media(audio_codec=None), target())
        assert "0:a:0" not in args
        assert "-c:a" not in args

    def test_capa_de_audio_nao_vira_trilha_de_video(self) -> None:
        # A capa de um MP3 aparece como trilha de vídeo (mjpeg). Recodificá-la
        # produziria um arquivo de uma imagem só, com a duração do áudio.
        args = args_for(
            media(video_codec="mjpeg", name="musica.mp3"), target(container="mp3")
        )
        assert "0:v:0" not in args
        assert "-c:v" not in args

    @pytest.mark.parametrize(
        ("container", "encoder"),
        [
            ("mp3", "libmp3lame"),
            ("m4a", "aac"),
            ("opus", "libopus"),
            ("ogg", "libvorbis"),
            ("flac", "flac"),
            ("wav", "pcm_s16le"),
        ],
    )
    def test_audio_recodifica_no_codec_do_container(
        self, container: str, encoder: str
    ) -> None:
        # O recorte preserva o container da origem: AAC dentro de um .mp3 é
        # recusado pelo próprio ffmpeg, com a tarefa já na fila.
        args = args_for(
            media(video_codec=None, name=f"musica.{container}"),
            target(container=container),
        )
        assert args[args.index("-c:a") + 1] == encoder

    @pytest.mark.parametrize("container", ["flac", "wav"])
    def test_sem_perda_nao_recebe_bitrate(self, container: str) -> None:
        args = args_for(
            media(video_codec=None, name=f"musica.{container}"),
            target(container=container),
        )
        assert "-b:a" not in args, "pedir bitrate a um codec sem perda é contraditório"

    def test_progresso_legivel_por_maquina(self) -> None:
        args = args_for(media(), target())
        assert args[args.index("-progress") + 1] == "pipe:1"
        assert "-nostdin" in args


# ---------------------------------------------------------------------------
# Vários trechos: um arquivo só, pelo filtro concat
# ---------------------------------------------------------------------------


class TestJuncao:
    def test_junta_pelo_filtro_com_as_duas_trilhas(self) -> None:
        alvo = target(0.0, 5.0, extra=(Segment(10.0, 12.5),))
        args = args_for(media(), alvo)
        filtro = args[args.index("-filter_complex") + 1]
        assert "concat=n=2:v=1:a=1" in filtro
        assert "trim=start=0.000000:end=5.000000" in filtro
        assert "atrim=start=10.000000:end=12.500000" in filtro

    def test_cada_trecho_recomeca_do_zero(self) -> None:
        # Sem setpts, os trechos mantêm o tempo original e o arquivo sai com
        # horas de vazio entre um e outro.
        args = args_for(media(), target(extra=(Segment(30.0, 35.0),)))
        filtro = args[args.index("-filter_complex") + 1]
        assert filtro.count(",setpts=PTS-STARTPTS") == 2
        assert filtro.count(",asetpts=PTS-STARTPTS") == 2

    def test_video_sem_audio_junta_so_o_video(self) -> None:
        args = args_for(media(audio_codec=None), target(extra=(Segment(30.0, 35.0),)))
        filtro = args[args.index("-filter_complex") + 1]
        assert "concat=n=2:v=1:a=0" in filtro
        assert "atrim" not in filtro

    def test_juntar_sem_recodificar_e_recusado(self) -> None:
        # A promessa de "sem recodificar" não pode ser quebrada em silêncio, e
        # não existe concat em -c copy num comando só.
        with pytest.raises(ConversionError, match="exige recodificar"):
            args_for(
                media(), target(mode=CutMode.FAST, extra=(Segment(30.0, 35.0),))
            )


# ---------------------------------------------------------------------------
# Recusas e descrição
# ---------------------------------------------------------------------------


class TestRecusas:
    def test_trecho_curto_demais(self) -> None:
        with pytest.raises(ConversionError, match="curto demais"):
            args_for(media(), target(10.0, 10.01))

    def test_sem_nenhum_trecho(self) -> None:
        with pytest.raises(ConversionError, match="nenhum trecho"):
            args_for(media(), TrimTarget(segments=()))

    def test_arquivo_sem_midia_utilizavel(self) -> None:
        with pytest.raises(ConversionError, match="não tem trilha"):
            args_for(media(video_codec=None, audio_codec=None), target())


class TestDescricao:
    def test_avisa_quando_recodifica(self) -> None:
        texto = describe_trim(media(), target(mode=CutMode.EXACT))
        assert "recodifica em H.264" in texto

    def test_avisa_quando_copia(self) -> None:
        texto = describe_trim(media(), target(mode=CutMode.FAST, anchor=9.6))
        assert "sem recodificar" in texto

    def test_diz_quantos_trechos_serao_unidos(self) -> None:
        texto = describe_trim(media(), target(extra=(Segment(30.0, 35.0),)))
        assert "2 trechos unidos" in texto

    def test_arquivo_de_audio_nao_anuncia_codec_de_video(self) -> None:
        # Dizer "recodifica em H.264" ao recortar um MP3 descreveria um arquivo
        # que não existe.
        texto = describe_trim(
            media(video_codec=None, name="musica.mp3"), target(container="mp3")
        )
        assert "somente áudio" in texto
        assert "recodifica em MP3" in texto
        assert "H.264" not in texto


class TestNomeDeSaida:
    def test_sufixo_distingue_os_trechos(self, tmp_path: Path) -> None:
        origem = tmp_path / "video.mp4"
        origem.write_bytes(b"")
        alvo = target()
        assert output_path(origem, alvo, tmp_path, " (corte 2)").name == (
            "video (corte 2).mp4"
        )

    def test_nunca_sobrescreve_a_origem(self, tmp_path: Path) -> None:
        origem = tmp_path / "video.mp4"
        origem.write_bytes(b"")
        # Sem sufixo o recorte de um .mp4 para .mp4 destruiria a origem no meio
        # da leitura.
        assert output_path(origem, target(), tmp_path).resolve() != origem.resolve()


class TestDespachoDoConversor:
    def test_o_conversor_reconhece_o_alvo_de_recorte(self) -> None:
        # O recorte é executado pelo mesmo Converter da aba de conversão; só a
        # montagem dos argumentos muda.
        args = build_args(media(), target(), DEST, TOOLS)
        assert args[args.index("-t") + 1] is not None
        assert str(DEST) == args[-1]

    def test_recorte_nao_copia_metadados_por_padrao(self) -> None:
        args = build_args(media(), target(), DEST, TOOLS)
        assert "-map_metadata" in args
        assert args[args.index("-map_metadata") + 1] == "-1"
        assert "-map_chapters" in args
        assert args[args.index("-map_chapters") + 1] == "-1"

    def test_recorte_copia_metadados_quando_pedido(self) -> None:
        alvo = target(copy_metadata=True)
        args = build_args(media(), alvo, DEST, TOOLS)
        assert "-map_metadata" in args
        assert args[args.index("-map_metadata") + 1] == "0"
        assert "-map_chapters" not in args
