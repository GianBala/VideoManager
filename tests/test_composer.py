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

import os
from pathlib import Path

import pytest

from videomanager.core.binaries import FFmpegTools, decode_threads
from videomanager.core.composer import (
    SAMPLE_RATE,
    audio_command,
    build_graph,
    can_interpolate,
    describe_export,
    export_args,
    frame_command,
    interpolation_bytes,
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


class TestInterpolacao:
    """Inventar os quadros que faltam, em vez de repetir os que existem.

    O padrão duplica: subir 24 para 60 entrega um arquivo de 60 fps com 24
    imagens por segundo (medido). Interpolar é a única forma de ganhar fluidez
    de verdade, custa 38× o tempo de exportação (medido) e deforma o que se move
    depressa — por isso é escolha explícita, nunca o padrão, e não vale para a
    prévia.
    """

    def lento(self, fps: float = 24.0) -> MediaRef:
        return MediaRef(
            path=Path("/m/cinema.mp4"), kind=MediaKind.VIDEO, duration=30.0,
            width=1920, height=1080, fps=fps, has_audio=True, channels=2,
        )

    def em_60(self, *clips: Clip) -> Project:
        return Project(
            tracks=(video_track(*clips),), width=1920, height=1080, fps=60.0
        )

    def test_por_padrao_duplica_quadros(self) -> None:
        texto = filtros(self.em_60(clip(self.lento())))
        assert "fps=60.000000" in texto
        assert "minterpolate" not in texto

    def test_quando_pedida_inventa_os_quadros(self) -> None:
        texto = filtros(self.em_60(clip(self.lento())), interpolate=True)
        assert "minterpolate=fps=60.000000" in texto
        assert "mi_mode=mci" in texto, "sem modo de compensação não há quadro novo"

    def test_o_fim_do_bloco_e_reposto(self) -> None:
        # O filtro precisa do quadro seguinte para inventar um, e entrega menos
        # quadros do que recebe: sem repor, o bloco acabava antes da hora e o
        # fundo preto da composição aparecia no lugar.
        texto = filtros(self.em_60(clip(self.lento())), interpolate=True)
        assert "tpad=stop_mode=clone" in texto
        assert texto.index("minterpolate") < texto.index("tpad"), "reposição vem depois"

    def test_bloco_que_ja_esta_na_taxa_nao_paga_a_conta(self) -> None:
        # Estimar movimento para chegar onde já se está é custo puro.
        texto = filtros(self.em_60(clip(self.lento(60.0))), interpolate=True)
        assert "minterpolate" not in texto

    def test_imagem_parada_nao_tem_movimento_a_estimar(self) -> None:
        texto = filtros(self.em_60(clip(FOTO)), interpolate=True)
        assert "minterpolate" not in texto

    def test_a_previa_nunca_interpola(self) -> None:
        # O mesmo grafo alimenta o quadro parado e a reprodução, que precisam
        # sair na hora: 38× o tempo não cabe no ritmo de uma prévia.
        projeto = self.em_60(clip(self.lento()))
        for comando in (
            frame_command(projeto, 1.0, (640, 360), TOOLS),
            playback_command(projeto, 1.0, (640, 360), TOOLS, fps=60),
        ):
            assert "minterpolate" not in " ".join(comando)

    def test_so_ha_o_que_interpolar_abaixo_da_taxa_da_tela(self) -> None:
        assert can_interpolate(self.em_60(clip(self.lento())))
        assert not can_interpolate(self.em_60(clip(self.lento(60.0))))
        assert not can_interpolate(self.em_60(clip(FOTO)))
        assert not can_interpolate(projeto(audio_track(clip(ESTEREO))))

    def test_o_resumo_anuncia_o_que_vai_custar(self) -> None:
        projeto_lento = self.em_60(clip(self.lento()))
        assert "interpolado" in describe_export(projeto_lento, "mp4", interpolate=True)
        assert "interpolado" not in describe_export(projeto_lento, "mp4")
        # Pedir onde não há o que interpolar não pode anunciar o que não vai
        # acontecer.
        rapido = self.em_60(clip(self.lento(60.0)))
        assert "interpolado" not in describe_export(rapido, "mp4", interpolate=True)


class TestCustoDaInterpolacao:
    """O que impede uma exportação interpolada de derrubar a máquina.

    A memória do ``minterpolate`` é função do tamanho do quadro que ele recebe —
    medido: 1,6 GB a 1080p e 5,6 GB a 4K, iguais para 5 s e para 20 s — e o
    filtro não tem controle nenhum para isso (``mb_size`` vai só até 16, e
    desligar o ``vsbmc`` muda 16 MB). Restam duas defesas, e as duas estão aqui:
    **dar ao filtro o menor quadro possível** e **dizer o número antes**.
    """

    def em(self, largura: int, altura: int, fps: float = 60.0) -> Project:
        return Project(
            tracks=(video_track(clip(self.material())),),
            width=largura, height=altura, fps=fps,
        )

    def material(self, largura: int = 1920, altura: int = 1080) -> MediaRef:
        return MediaRef(
            path=Path("/m/cinema.mp4"), kind=MediaKind.VIDEO, duration=30.0,
            width=largura, height=altura, fps=24.0, has_audio=True, channels=2,
        )

    def test_material_maior_que_a_tela_encolhe_antes_de_interpolar(self) -> None:
        # 4K numa tela 1080p: estimar movimento em 4K para depois jogar fora três
        # quartos dos pixels é pagar 5,6 GB onde 1,6 GB dá o mesmo resultado.
        projeto_4k = Project(
            tracks=(video_track(clip(self.material(3840, 2160))),),
            width=1920, height=1080, fps=60.0,
        )
        texto = filtros(projeto_4k, interpolate=True)
        assert texto.index("scale=") < texto.index("minterpolate")

    def test_material_menor_que_a_tela_interpola_antes_de_crescer(self) -> None:
        # O movimento está nos pixels originais: ampliar primeiro só faria o
        # filtro estimar movimento em pixels que o próprio scale inventou, pelo
        # preço da tela grande.
        projeto_hd = Project(
            tracks=(video_track(clip(self.material(1280, 720))),),
            width=3840, height=2160, fps=60.0,
        )
        texto = filtros(projeto_hd, interpolate=True)
        assert texto.index("minterpolate") < texto.index("scale=")

    def test_duplicar_quadro_e_sempre_depois_de_encaixar(self) -> None:
        # Sem interpolação a ordem não tem escolha a fazer: encaixar primeiro faz
        # o scale receber os 24 quadros da origem em vez dos 60 da tela, e
        # duplicar depois é de graça.
        texto = filtros(self.em(3840, 2160), interpolate=False)
        assert texto.index("scale=") < texto.index("fps=60.000000")

    def test_sem_tamanho_conhecido_a_tela_e_o_teto(self) -> None:
        # A tela é um teto conhecido; o do material não. Encaixar primeiro é o
        # lado que não pode surpreender.
        sem_tamanho = MediaRef(
            path=Path("/m/x.mp4"), kind=MediaKind.VIDEO, duration=30.0,
            width=None, height=None, fps=24.0, has_audio=True, channels=2,
        )
        projeto_cego = Project(
            tracks=(video_track(clip(sem_tamanho)),),
            width=1920, height=1080, fps=60.0,
        )
        texto = filtros(projeto_cego, interpolate=True)
        assert texto.index("scale=") < texto.index("minterpolate")

    def test_a_memoria_anunciada_e_a_do_quadro_que_o_filtro_recebe(self) -> None:
        grande = interpolation_bytes(self.em(3840, 2160))
        pequena = interpolation_bytes(self.em(1920, 1080))
        # O material é 1080p: numa tela 4K ele é interpolado antes de crescer, e
        # por isso as duas telas custam o mesmo. É a diferença entre anunciar o
        # custo real e anunciar o que a tela sugere.
        assert grande == pequena
        assert pequena == pytest.approx(1920 * 1080 * 803, rel=0.01)

    def test_a_tela_menor_limita_o_custo(self) -> None:
        projeto_4k = Project(
            tracks=(video_track(clip(self.material(3840, 2160))),),
            width=1280, height=720, fps=60.0,
        )
        assert interpolation_bytes(projeto_4k) == pytest.approx(
            1280 * 720 * 803, rel=0.01
        )

    def test_cada_bloco_soma_porque_cada_um_vira_um_filtro(self) -> None:
        # O grafo instancia um ``minterpolate`` por bloco, e todos vivem
        # enquanto a exportação existe: o pico é a soma, não o maior.
        dois = Project(
            tracks=(video_track(
                clip(self.material(), start=0.0, duration=10.0),
                clip(self.material(), start=10.0, duration=10.0),
            ),),
            width=1920, height=1080, fps=60.0,
        )
        assert interpolation_bytes(dois) == 2 * interpolation_bytes(self.em(1920, 1080))

    def test_sem_o_que_interpolar_nao_ha_custo(self) -> None:
        na_taxa = Project(
            tracks=(video_track(clip(VIDEO)),), width=1920, height=1080, fps=30.0
        )
        assert interpolation_bytes(na_taxa) == 0
        assert interpolation_bytes(projeto(audio_track(clip(ESTEREO)))) == 0


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


class TestThreadsDaPrevia:
    """O teto de threads vale para a prévia, e só para ela.

    O padrão do ffmpeg é uma thread por núcleo. Numa máquina de vinte núcleos,
    montar vinte threads para devolver **um** quadro custa mais do que
    decodificá-lo: medido no quadro composto, 1,31 s e 3,93 s de CPU no padrão
    contra 1,01 s e 3,12 s com o teto a 1080p, e 6,22 s / 40,08 s contra
    5,46 s / 26,52 s em HEVC 4K. Mais rápido e com menos CPU — e a CPU que sobra
    é a da exportação que estiver correndo ao lado.
    """

    def dois_blocos(self) -> Project:
        # Dois arquivos no mesmo instante: é o caso que revela um limite posto
        # uma vez só na frente do comando, que valeria apenas para o primeiro.
        return projeto(
            video_track(clip(VIDEO, start=0.0, duration=10.0)),
            video_track(clip(OUTRO, start=0.0, duration=10.0)),
        )

    def entradas_sem_limite(self, args: list[str]) -> list[int]:
        return [
            i for i, a in enumerate(args)
            if a == "-i" and args[i - 2 : i] != ["-threads", str(decode_threads())]
        ]

    def test_o_quadro_parado_limita_todas_as_entradas(self) -> None:
        args = frame_command(self.dois_blocos(), 1.0, (640, 360), TOOLS)
        assert args.count("-i") == 2, "as duas entradas precisam estar no comando"
        assert not self.entradas_sem_limite(args), (
            "``-threads`` é opção de entrada: uma vez só na frente limitaria "
            "apenas o primeiro arquivo"
        )

    def test_a_exportacao_continua_com_todos_os_nucleos(self) -> None:
        # Aqui o que se quer é o arquivo pronto antes, e todo núcleo é bem-vindo.
        args = export_args(self.dois_blocos(), DEST, TOOLS)
        assert "-threads" not in args

    def test_a_reproducao_nao_e_apertada(self) -> None:
        # O relógio já limita o trabalho dela — decodifica na velocidade em que
        # consome —, e apertar as threads só arriscaria não acompanhar o
        # material mais pesado.
        args = playback_command(self.dois_blocos(), 0.0, (640, 360), TOOLS, fps=30)
        assert "-threads" not in args

    def test_o_teto_nunca_passa_do_que_a_maquina_tem(self) -> None:
        assert 1 <= decode_threads() <= min(8, os.cpu_count() or 8)


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

    def test_tela_diferente_da_origem_nao_e_recorte(self) -> None:
        # Copiar os dados entrega a imagem como ela está no arquivo: a tela
        # pedida seria ignorada, e o arquivo sairia diferente do que o editor
        # anuncia. Melhor a tela desligar o corte rápido do que mentir.
        outra = Project(
            tracks=(video_track(clip()),), width=1280, height=720, fps=30.0
        )
        assert simple_trim(outra) is None

    def test_taxa_diferente_da_origem_nao_e_recorte(self) -> None:
        outra = Project(
            tracks=(video_track(clip()),), width=1920, height=1080, fps=24.0
        )
        assert simple_trim(outra) is None

    def test_tela_igual_a_origem_continua_sendo_recorte(self) -> None:
        assert simple_trim(projeto(video_track(clip()))) is not None

    def test_som_separado_nao_e_recorte(self) -> None:
        # Copiar os dados levaria a imagem junto do bloco que só tem som: o que
        # está na tela deixaria de ser o que sai do arquivo.
        so_o_som = projeto(audio_track(clip(audio_only=True)))
        assert simple_trim(so_o_som) is None


class TestSomSeparado:
    """O bloco de "separar áudio" entra na mixagem e **não** na imagem.

    Ele vem de um arquivo com vídeo, e enquanto a espécie saía da mídia o
    compositor o tratava como bloco de imagem: desenhava o vídeo dele por cima
    da montagem inteira, no instante em que o som estivesse, e ainda pagava a
    decodificação de um vídeo que ninguém pediu.
    """

    def montagem(self) -> Project:
        return projeto(
            video_track(clip(VIDEO, start=0.0, duration=10.0, detached=True)),
            audio_track(clip(VIDEO, start=4.0, duration=10.0, audio_only=True)),
        )

    def test_nao_entra_na_imagem(self) -> None:
        graph = build_graph(self.montagem())
        assert graph.filters is not None
        assert sum(1 for f in graph.filters if "overlay" in f) == 1, (
            "só o bloco da trilha de vídeo é sobreposto"
        )

    def test_entra_na_mixagem(self) -> None:
        graph = build_graph(self.montagem())
        assert graph.audio_label is not None
        assert "[1:a]" in ";".join(graph.filters), "o som do bloco separado é o que toca"

    def test_o_video_de_origem_ficou_sem_som(self) -> None:
        # O som saiu do bloco de vídeo: entrar duas vezes na mixagem dobraria o
        # volume de tudo que foi separado.
        graph = build_graph(self.montagem())
        assert "[0:a]" not in ";".join(graph.filters)


class TestDescricao:
    def test_conta_o_que_vai_para_o_arquivo(self) -> None:
        texto = describe_export(
            projeto(video_track(clip()), audio_track(clip(ESTEREO))), "mp4"
        )
        assert "1 bloco(s) de imagem" in texto
        assert "1 de áudio" in texto
        assert "1920×1080" in texto
