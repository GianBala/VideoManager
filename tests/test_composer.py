"""Testes do compositor: o grafo do ffmpeg que monta a edição.

Operam sobre a montagem dos argumentos, que é função pura — não é preciso
ffmpeg nem arquivo de mídia. O que se afirma aqui é o que separa uma exportação
correta de uma que parece correta: a trilha de cima aparecendo por cima, o vão
saindo preto em vez de emendado, o volume em decibéis chegando ao filtro, e o
bloco mudo não entrando na mixagem — nada disso apareceria numa comparação de
strings feita de fora.

O mesmo grafo serve à prévia e à reprodução, então testá-lo cobre também o que
o usuário vê na tela antes de exportar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.core.binaries import FFmpegTools
from videomanager.core.composer import (
    SAMPLE_RATE,
    audio_command,
    build_graph,
    describe_export,
    export_args,
    frame_command,
    playback_command,
    simple_trim,
)
from videomanager.core.errors import ConversionError
from videomanager.core.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
DEST = Path("/saida/edicao.mp4")

VIDEO = MediaRef(
    path=Path("/m/filme.mp4"), kind=MediaKind.VIDEO, duration=60.0, width=1920,
    height=1080, fps=30.0, has_audio=True, channels=2,
)
OUTRO = MediaRef(
    path=Path("/m/outro.mp4"), kind=MediaKind.VIDEO, duration=20.0, width=1280,
    height=720, fps=30.0, has_audio=True, channels=2,
)
FOTO = MediaRef(path=Path("/m/foto.png"), kind=MediaKind.IMAGE, width=800, height=600)
MONO = MediaRef(
    path=Path("/m/voz.mp3"), kind=MediaKind.AUDIO, duration=40.0, has_audio=True,
    channels=1,
)
ESTEREO = MediaRef(
    path=Path("/m/musica.mp3"), kind=MediaKind.AUDIO, duration=40.0, has_audio=True,
    channels=2,
)


def projeto(*tracks: Track, width: int = 1920, height: int = 1080) -> Project:
    return Project(tracks=tracks, width=width, height=height, fps=30.0)


def video_track(*clips: Clip, muted: bool = False) -> Track:
    return Track(kind=TrackKind.VIDEO, clips=clips, muted=muted, name="V")


def audio_track(*clips: Clip, muted: bool = False) -> Track:
    return Track(kind=TrackKind.AUDIO, clips=clips, muted=muted, name="A")


def clip(media: MediaRef = VIDEO, start: float = 0.0, duration: float = 10.0, **kw) -> Clip:
    return Clip(media=media, start=start, duration=duration, **kw)


def filtros(project: Project, **kw) -> str:
    return ";".join(build_graph(project, **kw).filters)


class TestVideo:
    def test_o_fundo_e_uma_tela_preta_do_tamanho_do_projeto(self) -> None:
        # Não se "emenda" vídeo: emendar só funciona com tudo do mesmo tamanho,
        # sem vão e sem trilha por cima. Sobrepor a um fundo resolve os três.
        texto = filtros(projeto(video_track(clip())))
        assert "color=c=black:s=1920x1080" in texto

    def test_cada_bloco_e_ajustado_a_tela(self) -> None:
        # Um vídeo de outro tamanho entra inteiro, com tarja, em vez de esticado.
        texto = filtros(projeto(video_track(clip(OUTRO))))
        assert "pad=1920:1080" in texto
        assert "setsar=1" in texto

    def test_o_encaixe_mede_a_forma_exibida_e_nao_a_guardada(self) -> None:
        # ``force_original_aspect_ratio`` mede a proporção em pixels guardados e
        # ignora a proporção do pixel: com o ``setsar=1`` logo depois, um rip de
        # DVD (720×480 exibido em 16:9) saía achatado. ``dar`` é a proporção de
        # exibição, que já traz o pixel embutido.
        texto = filtros(projeto(video_track(clip(OUTRO))))
        assert "min(1920,1080*dar)" in texto
        assert "min(1080,1920/dar)" in texto
        assert "force_original_aspect_ratio" not in texto

    def test_bloco_entra_no_instante_em_que_foi_colocado(self) -> None:
        texto = filtros(projeto(video_track(clip(start=4.0, duration=6.0))))
        assert "setpts=PTS-STARTPTS+4.000000/TB" in texto
        assert "between(t,4.000000,10.000000)" in texto

    def test_bloco_no_zero_nao_recebe_atraso(self) -> None:
        texto = filtros(projeto(video_track(clip(start=0.0))))
        assert "setpts=PTS-STARTPTS," in texto or "setpts=PTS-STARTPTS[" in texto

    def test_trilha_de_baixo_e_o_fundo_e_a_de_cima_sobrepoe(self) -> None:
        # A ordem de ``tracks`` é a da tela, de cima para baixo; a composição
        # inverte, senão a trilha principal cobriria as sobreposições.
        alta = video_track(clip(FOTO, start=2.0, duration=3.0))
        baixa = video_track(clip(VIDEO, start=0.0, duration=10.0))
        graph = build_graph(projeto(alta, baixa))
        entradas = " ".join(graph.inputs)
        assert entradas.index("filme.mp4") < entradas.index("foto.png")

    def test_cada_bloco_vira_uma_sobreposicao(self) -> None:
        texto = filtros(
            projeto(
                video_track(clip(FOTO, start=1.0, duration=2.0)),
                video_track(clip(VIDEO, start=0.0, duration=8.0)),
            )
        )
        assert texto.count("overlay=") == 2

    def test_o_bloco_nao_congela_depois_de_acabar(self) -> None:
        # Sem repeatlast=0 o último quadro do bloco fica na tela para sempre.
        texto = filtros(projeto(video_track(clip(start=0.0, duration=3.0))))
        assert "repeatlast=0" in texto
        assert "eof_action=pass" in texto

    def test_imagem_entra_em_laco_com_duracao_propria(self) -> None:
        graph = build_graph(projeto(video_track(clip(FOTO, start=0.0, duration=7.0))))
        entradas = " ".join(graph.inputs)
        assert "-loop 1" in entradas
        assert "-t 7.000000" in entradas

    def test_video_normal_entra_pelo_ponto_de_origem(self) -> None:
        graph = build_graph(
            projeto(video_track(clip(start=0.0, duration=5.0, in_point=12.0)))
        )
        entradas = " ".join(graph.inputs)
        assert "-ss 12.000000" in entradas
        assert "-loop" not in entradas


class TestAudio:
    def test_volume_em_decibeis_chega_ao_filtro(self) -> None:
        texto = filtros(projeto(audio_track(clip(ESTEREO, gain_db=-6.0))))
        assert "volume=-6.00dB" in texto

    def test_ganho_zero_nao_gera_filtro(self) -> None:
        texto = filtros(projeto(audio_track(clip(ESTEREO, gain_db=0.0))))
        assert "volume=" not in texto

    def test_bloco_atrasado_entra_no_lugar_certo(self) -> None:
        texto = filtros(projeto(audio_track(clip(ESTEREO, start=2.5, duration=4.0))))
        # ``all=1``: sem ele só o primeiro canal atrasa, e o som sai torto.
        assert "adelay=2500:all=1" in texto

    def test_mixagem_nao_normaliza(self) -> None:
        # O padrão do amix divide o volume pelo número de entradas: dois blocos
        # simultâneos sairiam pela metade sem ninguém ter pedido.
        texto = filtros(
            projeto(audio_track(clip(ESTEREO), clip(MONO, start=20.0)))
        )
        assert "amix=inputs=2:normalize=0" in texto
        assert "dropout_transition=0" in texto

    def test_uma_fonte_so_nao_passa_por_amix(self) -> None:
        graph = build_graph(projeto(audio_track(clip(ESTEREO))))
        assert "amix" not in ";".join(graph.filters)
        assert graph.audio_label == "[a0]"

    def test_mono_vira_estereo_por_copia_e_nao_por_conversao(self) -> None:
        # A conversão de layout do ffmpeg normaliza a potência e tira 3 dB
        # exatos — o que quebraria a promessa de que 0 dB não mexe no som.
        texto = filtros(projeto(audio_track(clip(MONO))))
        assert "pan=stereo|c0=c0|c1=c0" in texto
        assert "channel_layouts=stereo" not in texto

    def test_estereo_usa_a_conversao_normal(self) -> None:
        texto = filtros(projeto(audio_track(clip(ESTEREO))))
        assert "aformat=channel_layouts=stereo" in texto

    def test_taxa_fixada_antes_da_mixagem(self) -> None:
        texto = filtros(projeto(audio_track(clip(ESTEREO))))
        assert f"sample_rates={SAMPLE_RATE}" in texto

    def test_bloco_mudo_fica_de_fora(self) -> None:
        graph = build_graph(projeto(audio_track(clip(ESTEREO, muted=True))))
        assert graph.audio_label is None

    def test_trilha_muda_fica_de_fora(self) -> None:
        graph = build_graph(projeto(audio_track(clip(ESTEREO), muted=True)))
        assert graph.audio_label is None

    def test_video_mudo_nao_leva_som(self) -> None:
        graph = build_graph(projeto(video_track(clip(VIDEO, muted=True))))
        assert graph.audio_label is None
        assert graph.video_label is not None, "a imagem continua"


class TestJanela:
    def test_bloco_que_ja_passou_nao_entra(self) -> None:
        # Ao reproduzir a partir dos 30 s, o que acabou aos 10 não é aberto.
        graph = build_graph(
            projeto(video_track(clip(start=0.0, duration=10.0))), at=30.0
        )
        assert not graph.inputs

    def test_bloco_em_andamento_entra_pelo_meio(self) -> None:
        graph = build_graph(
            projeto(video_track(clip(start=0.0, duration=60.0, in_point=5.0))), at=20.0
        )
        entradas = " ".join(graph.inputs)
        assert "-ss 25.000000" in entradas, "5 s de origem + 20 s de linha do tempo"

    def test_bloco_futuro_entra_com_o_atraso_relativo(self) -> None:
        texto = filtros(
            projeto(video_track(clip(start=30.0, duration=5.0))), at=20.0
        )
        assert "setpts=PTS-STARTPTS+10.000000/TB" in texto


class TestComandos:
    def test_exportacao_grava_com_progresso_legivel(self) -> None:
        args = export_args(projeto(video_track(clip())), DEST, TOOLS)
        assert args[args.index("-progress") + 1] == "pipe:1"
        assert args[-1] == str(DEST)
        assert "-nostdin" in args

    def test_exportacao_de_projeto_vazio_e_recusada(self) -> None:
        with pytest.raises(ConversionError, match="nada na linha do tempo"):
            export_args(Project(), DEST, TOOLS)

    def test_quadro_parado_abre_so_o_que_aparece_nele(self) -> None:
        # Sem o limite de um quadro, desenhar um instante abria todos os
        # arquivos seguintes da edição: num projeto de vinte blocos eram vinte
        # arquivos e 0,77 s por quadro, com o custo crescendo a cada bloco.
        longo = Project(
            tracks=(
                video_track(
                    *[
                        Clip(media=VIDEO, start=i * 3.0, duration=2.5, in_point=i * 2.0)
                        for i in range(20)
                    ]
                ),
            ),
            fps=30.0,
        )
        args = frame_command(longo, 1.0, (320, 180), TOOLS)
        assert args.count("-i") == 1, "só o bloco que aparece em t=1s é aberto"

    def test_quadro_da_previa_sai_cru(self) -> None:
        args = frame_command(projeto(video_track(clip())), 3.0, (640, 360), TOOLS)
        assert args[args.index("-frames:v") + 1] == "1"
        assert args[args.index("-pix_fmt") + 1] == "rgb24"
        assert "scale=640:360" in " ".join(args)

    def test_quadro_sem_imagem_no_instante_sai_preto(self) -> None:
        # Melhor que a tela vazia da prévia, que parece falha de carregamento.
        args = frame_command(projeto(audio_track(clip(ESTEREO))), 1.0, (320, 180), TOOLS)
        assert "color=c=black:s=320x180:d=0.1" in " ".join(args)

    def test_reproducao_pede_a_taxa_da_previa(self) -> None:
        args = playback_command(
            projeto(video_track(clip())), 0.0, (640, 360), TOOLS, fps=15
        )
        assert "r=15.000000" in " ".join(args) or "fps=15.000000" in " ".join(args)

    def test_audio_da_previa_sai_em_pcm(self) -> None:
        args = audio_command(projeto(audio_track(clip(ESTEREO))), 0.0, TOOLS)
        assert args is not None
        assert args[args.index("-f") + 1] == "s16le"
        assert args[args.index("-ar") + 1] == str(SAMPLE_RATE)

    def test_sem_som_nao_ha_comando_de_audio(self) -> None:
        # A interface usa isto para não abrir processo nenhum, em vez de tocar
        # silêncio.
        projeto_calado = projeto(video_track(clip(VIDEO, muted=True)))
        assert audio_command(projeto_calado, 0.0, TOOLS) is None

    def test_projeto_so_de_audio_nao_grava_video(self) -> None:
        args = export_args(projeto(audio_track(clip(ESTEREO))), DEST, TOOLS)
        assert "-c:v" not in args


class TestCaminhoRapido:
    def test_um_arquivo_intacto_ainda_e_um_recorte(self) -> None:
        # É o que preserva o corte sem recodificar depois de o editor virar
        # multipista.
        segments = simple_trim(projeto(video_track(clip(start=0.0, duration=10.0))))
        assert segments is not None and len(segments) == 1

    def test_duas_midias_nao_sao_recorte(self) -> None:
        assert simple_trim(
            projeto(video_track(clip(VIDEO), clip(OUTRO, start=20.0)))
        ) is None

    def test_volume_alterado_nao_e_recorte(self) -> None:
        assert simple_trim(projeto(video_track(clip(gain_db=-3.0)))) is None

    def test_bloco_mudo_nao_e_recorte(self) -> None:
        assert simple_trim(projeto(video_track(clip(muted=True)))) is None

    def test_imagem_nao_e_recorte(self) -> None:
        assert simple_trim(projeto(video_track(clip(FOTO)))) is None

    def test_blocos_fora_de_ordem_nao_sao_recorte(self) -> None:
        # Reordenar no tempo é montagem, e montagem se compõe.
        fora = projeto(
            video_track(
                clip(start=0.0, duration=5.0, in_point=30.0),
                clip(start=5.0, duration=5.0, in_point=0.0),
            )
        )
        assert simple_trim(fora) is None

    def test_trilha_muda_nao_e_recorte(self) -> None:
        assert simple_trim(projeto(video_track(clip(), muted=True))) is None


class TestDescricao:
    def test_conta_o_que_vai_para_o_arquivo(self) -> None:
        texto = describe_export(
            projeto(video_track(clip()), audio_track(clip(ESTEREO))), "mp4"
        )
        assert "1 bloco(s) de imagem" in texto
        assert "1 de áudio" in texto
        assert "1920×1080" in texto
