"""Testes do projeto de edição: trilhas, blocos e as operações sobre eles.

Tudo aqui é função pura sobre estruturas imutáveis — não precisa de ffmpeg, de
arquivo de mídia nem de Qt. O que se afirma é o que separa uma linha do tempo
utilizável de uma que perde trabalho: bloco que não sobrepõe o vizinho, ponta
que não passa do fim da mídia, e toda operação devolvendo um projeto novo, sem
tocar no anterior — que é o que sustenta o desfazer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.core.converter import LocalMedia, LocalStream
from videomanager.core.project import (
    IMAGE_DURATION,
    MAX_AUTO_FPS,
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
    accepts,
    auto_canvas,
    display_width,
    media_ref,
    new_project,
)

VIDEO = MediaRef(
    path=Path("/m/filme.mp4"),
    kind=MediaKind.VIDEO,
    duration=60.0,
    width=1920,
    height=1080,
    fps=30.0,
    has_audio=True,
    channels=2,
)
MUDO = MediaRef(
    path=Path("/m/mudo.mp4"), kind=MediaKind.VIDEO, duration=30.0, width=640, height=480
)
FOTO = MediaRef(path=Path("/m/foto.png"), kind=MediaKind.IMAGE, width=800, height=600)
SOM = MediaRef(
    path=Path("/m/musica.mp3"), kind=MediaKind.AUDIO, duration=200.0,
    has_audio=True, channels=1,
)


def clip(media: MediaRef = VIDEO, start: float = 0.0, duration: float = 10.0, **kw) -> Clip:
    return Clip(media=media, start=start, duration=duration, **kw)


def montado(*clips: Clip) -> Project:
    """Projeto com os blocos numa trilha de vídeo e uma de áudio vazia."""
    videos = tuple(c for c in clips if c.media.has_video)
    audios = tuple(c for c in clips if not c.media.has_video)
    return Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=videos, name="Vídeo 1"),
            Track(kind=TrackKind.AUDIO, clips=audios, name="Áudio 1"),
        )
    )


class TestMidia:
    def test_imagem_nasce_com_duracao_de_cartao(self) -> None:
        assert FOTO.natural_duration == IMAGE_DURATION
        assert FOTO.duration is None, "imagem não tem duração própria"

    def test_video_entra_com_a_duracao_que_tem(self) -> None:
        assert VIDEO.natural_duration == 60.0

    def test_trilha_so_aceita_o_que_ela_mostra(self) -> None:
        assert accepts(TrackKind.VIDEO, clip(VIDEO))
        assert accepts(TrackKind.VIDEO, clip(FOTO))
        assert not accepts(TrackKind.VIDEO, clip(SOM))
        assert accepts(TrackKind.AUDIO, clip(SOM))
        # O som de um vídeo só desce para a trilha de áudio por "separar áudio".
        assert not accepts(TrackKind.AUDIO, clip(VIDEO))


class TestTela:
    """A tela do projeto, que decide o tamanho e a taxa do arquivo exportado.

    A regra é **o maior bloco**, e não o primeiro. Com o primeiro, a ordem de
    importação decidia a qualidade do resultado inteiro — entrar com um clipe
    480p rebaixava para 480p todo o material 4K que viesse depois — e a única
    saída era esvaziar a linha do tempo e recomeçar.
    """

    def test_o_video_define_o_formato(self) -> None:
        # Sem isto, um vídeo vertical de celular sairia com tarja preta dos dois
        # lados numa tela 16:9 que ninguém pediu.
        vertical = MediaRef(
            path=Path("/m/v.mp4"), kind=MediaKind.VIDEO, duration=10, width=1080,
            height=1920, fps=30,
        )
        projeto = new_project(vertical)
        assert (projeto.width, projeto.height) == (1080, 1920)

    def test_o_maior_bloco_manda_e_nao_o_primeiro(self) -> None:
        pequeno = MediaRef(
            path=Path("/m/p.mp4"), kind=MediaKind.VIDEO, duration=10, width=640,
            height=480, fps=30,
        )
        projeto = auto_canvas(montado(clip(pequeno), clip(VIDEO, start=10.0)))
        assert (projeto.width, projeto.height) == (1920, 1080)

    def test_a_maior_taxa_manda(self) -> None:
        rapido = MediaRef(
            path=Path("/m/r.mp4"), kind=MediaKind.VIDEO, duration=10, width=640,
            height=480, fps=60,
        )
        projeto = auto_canvas(montado(clip(VIDEO), clip(rapido, start=10.0)))
        assert projeto.fps == 60, "nenhum bloco perde quadro"

    def test_taxa_altissima_nao_arrasta_a_edicao_junto(self) -> None:
        # Um clipe de câmera lenta a 240 fps levaria o arquivo inteiro para 240
        # fps só por ter sido arrastado para a linha do tempo.
        lenta = MediaRef(
            path=Path("/m/l.mp4"), kind=MediaKind.VIDEO, duration=5, width=1920,
            height=1080, fps=240,
        )
        assert auto_canvas(montado(clip(lenta))).fps == MAX_AUTO_FPS

    def test_audio_nao_define_formato(self) -> None:
        projeto = new_project(SOM)
        assert (projeto.width, projeto.height) == (1920, 1080)

    def test_foto_nao_manda_onde_ha_video(self) -> None:
        # Ampliar uma foto custa muito menos que ampliar um vídeo, e uma imagem
        # de 6000 px levaria a edição para um tamanho que ninguém pediu.
        enorme = MediaRef(
            path=Path("/m/g.png"), kind=MediaKind.IMAGE, width=6000, height=4000
        )
        projeto = auto_canvas(montado(clip(VIDEO), clip(enorme, start=10.0)))
        assert (projeto.width, projeto.height) == (1920, 1080)

    def test_so_fotos_definem_a_tela(self) -> None:
        projeto = auto_canvas(montado(clip(FOTO)))
        assert (projeto.width, projeto.height) == (800, 600)

    def test_edicao_vazia_volta_ao_padrao(self) -> None:
        # É o que faz a próxima importação definir a tela, em vez de herdar a de
        # um material que já saiu da edição.
        projeto = new_project(VIDEO)
        vazio = auto_canvas(projeto.without_clip(projeto.clips[0].clip_id))
        assert (vazio.width, vazio.height, vazio.fps) == (1920, 1080, 30.0)

    def test_dimensoes_saem_pares(self) -> None:
        # Codecs de vídeo trabalham em blocos de dois pixels e recusam ímpar.
        estranho = MediaRef(
            path=Path("/m/x.mp4"), kind=MediaKind.VIDEO, duration=5, width=1281,
            height=721, fps=30,
        )
        projeto = new_project(estranho)
        assert projeto.width % 2 == 0 and projeto.height % 2 == 0


class TestPixelNaoQuadrado:
    """Mídia que guarda a imagem espremida — rip de DVD, filmadora antiga.

    O arquivo tem 720×480 e um pixel 32:27 que manda exibir em 16:9. Medindo só
    a largura guardada, a edição nascia com a proporção errada e a imagem
    achatada, sem nada falhar.
    """

    def midia(self, sar: float | None) -> LocalMedia:
        return LocalMedia(
            path=Path("/m/dvd.mpg"),
            duration=60.0,
            format_name="mpeg",
            size=None,
            streams=(
                LocalStream(
                    index=0, kind="video", codec="mpeg2video", width=720,
                    height=480, fps=29.97, sar=sar,
                ),
            ),
        )

    def test_a_largura_guardada_vira_a_de_exibicao(self) -> None:
        assert display_width(720, 32 / 27) == 854
        assert media_ref(self.midia(32 / 27)).width == 854

    def test_pixel_quadrado_nao_mexe_em_nada(self) -> None:
        assert display_width(1920, 1.0) == 1920
        assert media_ref(self.midia(1.0)).width == 720

    def test_pixel_desconhecido_e_tratado_como_quadrado(self) -> None:
        # É o que o ffmpeg faz, e a conta tem de concordar com ele.
        assert display_width(1920, None) == 1920
        assert media_ref(self.midia(None)).width == 720


class TestBloco:
    def test_tempo_de_origem_acompanha_o_corte(self) -> None:
        bloco = clip(start=10.0, duration=5.0, in_point=30.0)
        assert bloco.source_time(12.0) == pytest.approx(32.0)
        assert bloco.out_point == pytest.approx(35.0)

    def test_bloco_mudo_nao_tem_som(self) -> None:
        assert clip(VIDEO).has_sound
        assert not clip(VIDEO, muted=True).has_sound
        assert not clip(MUDO).has_sound, "arquivo sem trilha de áudio"

    def test_rotulo_do_ganho(self) -> None:
        assert clip(VIDEO).gain_label == ""
        assert clip(VIDEO, gain_db=-6.0).gain_label == "-6,0 dB"
        assert clip(VIDEO, muted=True).gain_label == "mudo"


class TestMover:
    def test_move_no_tempo(self) -> None:
        projeto = montado(clip(start=0.0, duration=5.0))
        alvo = projeto.clips[0]
        movido = projeto.moved(alvo.clip_id, 0, 12.0)
        assert movido.clips[0].start == pytest.approx(12.0)

    def test_nao_atravessa_o_vizinho(self) -> None:
        # Dois blocos de vídeo sobrepostos na mesma trilha não têm resposta
        # certa — qual aparece? —, então a sobreposição não acontece.
        projeto = montado(clip(start=0.0, duration=5.0), clip(start=20.0, duration=5.0))
        segundo = projeto.tracks[0].clips[1]
        movido = projeto.moved(segundo.clip_id, 0, 2.0)
        assert movido.tracks[0].clips[1].start == pytest.approx(5.0), (
            "encosta no vizinho em vez de passar por cima"
        )

    def test_nao_vai_para_antes_do_zero(self) -> None:
        projeto = montado(clip(start=10.0, duration=5.0))
        movido = projeto.moved(projeto.clips[0].clip_id, 0, -30.0)
        assert movido.clips[0].start == 0.0

    def test_troca_de_trilha_compativel(self) -> None:
        projeto = montado(clip(SOM, start=0.0, duration=5.0))
        projeto = projeto.with_track(TrackKind.AUDIO)
        som = projeto.clips[0]
        destino = len(projeto.tracks) - 1
        movido = projeto.moved(som.clip_id, destino, 0.0)
        assert len(movido.tracks[destino].clips) == 1

    def test_audio_nao_sobe_para_trilha_de_video(self) -> None:
        projeto = montado(clip(SOM, start=0.0, duration=5.0))
        som = projeto.clips[0]
        movido = projeto.moved(som.clip_id, 0, 0.0)
        assert movido.tracks[1].clips, "continua na trilha de áudio"
        assert not movido.tracks[0].clips

    def test_projeto_original_nao_muda(self) -> None:
        # É o que sustenta o desfazer: guardar o projeto anterior basta.
        projeto = montado(clip(start=0.0, duration=5.0))
        projeto.moved(projeto.clips[0].clip_id, 0, 30.0)
        assert projeto.clips[0].start == 0.0


class TestTrocarDeLugar:
    """Reordenar dois blocos encostados, que é o gesto que não existia.

    Dois blocos colados não deixam vão nenhum entre si, então a acomodação no
    vão mais próximo devolvia sempre a mesma posição: arrastar o segundo para
    antes do primeiro não fazia **nada**, e não havia outro caminho na tela para
    reordenar uma sequência.

    O que estes testes guardam, além da troca em si, é que ela **não se repete
    sozinha**: o arrasto reaplica a mesma posição a cada movimento do mouse, e
    uma troca que valesse nos dois sentidos no mesmo ponto faria os blocos
    piscarem de lugar dezenas de vezes por segundo com a mão parada.
    """

    def montagem(self) -> tuple[Project, Clip, Clip]:
        projeto = montado(
            clip(start=0.0, duration=10.0), clip(start=10.0, duration=10.0)
        )
        primeiro, segundo = projeto.tracks[0].sorted_clips()
        return projeto, primeiro, segundo

    def posicoes(self, projeto: Project, *clips: Clip) -> list[float]:
        """Onde cada bloco está agora, na ordem em que foram pedidos."""
        return [projeto.find(c.clip_id)[1].start for c in clips]  # type: ignore[index]

    def test_passar_do_meio_do_vizinho_troca_os_dois(self) -> None:
        projeto, primeiro, segundo = self.montagem()
        # O vizinho ocupa [0, 10]: a ponta esquerda do arrastado passou de 5.
        movido = projeto.moved(segundo.clip_id, 0, 4.9)
        assert self.posicoes(movido, segundo, primeiro) == [0.0, 10.0]

    def test_encostar_a_ponta_nao_troca(self) -> None:
        # Justapor é o gesto mais comum da linha do tempo, e ele não pode virar
        # troca sem querer: até passar do meio do vizinho, nada muda.
        projeto, primeiro, segundo = self.montagem()
        movido = projeto.moved(segundo.clip_id, 0, 6.0)
        assert self.posicoes(movido, primeiro, segundo) == [0.0, 10.0]

    def test_bloco_mais_longo_que_o_vizinho_tambem_troca(self) -> None:
        # Medir pelo meio do bloco **arrastado** não serve: um bloco de 40 s
        # encosta no zero com o meio dele ainda em 20, longe de alcançar um
        # vizinho de 20 s — e nenhum arrasto reordenava mais nada.
        projeto = montado(clip(start=0.0, duration=20.0), clip(start=20.0, duration=40.0))
        curto, longo = projeto.tracks[0].sorted_clips()
        movido = projeto.moved(longo.clip_id, 0, 0.0)
        assert self.posicoes(movido, longo, curto) == [0.0, 40.0]

    def test_o_longo_volta_pelo_mesmo_ponto(self) -> None:
        projeto = montado(clip(start=0.0, duration=20.0), clip(start=20.0, duration=40.0))
        curto, longo = projeto.tracks[0].sorted_clips()
        trocado = projeto.moved(longo.clip_id, 0, 0.0)
        assert self.posicoes(trocado.moved(longo.clip_id, 0, 9.9), longo, curto) == [
            0.0, 40.0
        ], "aquém do ponto de troca, continua na frente"
        voltou = trocado.moved(longo.clip_id, 0, 10.1)
        assert self.posicoes(voltou, curto, longo) == [0.0, 20.0]

    def test_a_troca_volta_pelo_mesmo_caminho(self) -> None:
        projeto, primeiro, segundo = self.montagem()
        trocado = projeto.moved(segundo.clip_id, 0, 4.9)
        voltou = trocado.moved(segundo.clip_id, 0, 5.1)
        assert self.posicoes(voltou, primeiro, segundo) == [0.0, 10.0]

    def test_insistir_no_mesmo_ponto_nao_fica_piscando(self) -> None:
        # O arrasto reaplica a mesma posição a cada movimento do mouse: se a
        # troca se repetisse, os dois blocos trocariam de lugar dezenas de vezes
        # por segundo enquanto a mão estivesse parada.
        projeto, primeiro, segundo = self.montagem()
        trocado = projeto.moved(segundo.clip_id, 0, 4.9)
        de_novo = trocado.moved(segundo.clip_id, 0, 4.9)
        assert self.posicoes(de_novo, segundo, primeiro) == [0.0, 10.0]

    def test_duracoes_diferentes_ficam_encostadas_no_comeco(self) -> None:
        projeto = montado(
            clip(start=0.0, duration=10.0), clip(start=10.0, duration=3.0)
        )
        longo, curto = projeto.tracks[0].sorted_clips()
        movido = projeto.moved(curto.clip_id, 0, 2.0)
        assert self.posicoes(movido, curto, longo) == [0.0, 3.0]

    def test_a_troca_nao_esbarra_num_terceiro(self) -> None:
        # Os dois ficam dentro do espaço que já ocupavam juntos, e por isso a
        # troca nunca sobrepõe quem está ao lado.
        projeto = montado(
            clip(start=0.0, duration=10.0),
            clip(start=10.0, duration=3.0),
            clip(start=13.0, duration=5.0),
        )
        longo, curto, vizinho = projeto.tracks[0].sorted_clips()
        movido = projeto.moved(curto.clip_id, 0, 2.0)
        assert self.posicoes(movido, curto, longo, vizinho) == [0.0, 3.0, 13.0]

    def test_com_vao_no_meio_o_bloco_so_anda(self) -> None:
        # Onde há espaço não há o que trocar: o bloco vai para onde foi solto.
        projeto = montado(clip(start=0.0, duration=5.0), clip(start=20.0, duration=5.0))
        primeiro, segundo = projeto.tracks[0].sorted_clips()
        movido = projeto.moved(segundo.clip_id, 0, 12.0)
        assert self.posicoes(movido, primeiro, segundo) == [0.0, 12.0]


class TestSomSeparadoEUmBlocoDeAudio:
    """O bloco que "separar áudio" cria é áudio, mesmo vindo de um arquivo com
    imagem.

    Enquanto essa espécie saía da mídia, ele não podia ser arrastado nem dentro
    da própria trilha, copiar e colar o mandava para a trilha de vídeo, e a
    composição desenhava o vídeo dele por cima da montagem.
    """

    def separado(self) -> tuple[Project, Clip]:
        projeto = montado(clip(VIDEO, start=0.0, duration=10.0))
        projeto = projeto.detached_audio(projeto.clips[0].clip_id)
        som = [c for t in projeto.audio_tracks for c in t.clips][0]
        return projeto, som

    def test_a_trilha_de_audio_aceita_e_a_de_video_nao(self) -> None:
        _, som = self.separado()
        assert som.audio_only
        assert accepts(TrackKind.AUDIO, som)
        assert not accepts(TrackKind.VIDEO, som)

    def test_nao_mostra_imagem(self) -> None:
        projeto, som = self.separado()
        assert not som.has_image
        assert projeto.tracks[0].clips[0].has_image, "o bloco de vídeo continua sendo"

    def test_pode_ser_movido_na_propria_trilha(self) -> None:
        projeto, som = self.separado()
        destino = projeto.track_index(projeto.audio_tracks[0].track_id)
        movido = projeto.moved(som.clip_id, destino, 4.0)
        assert movido.find(som.clip_id)[1].start == pytest.approx(4.0)  # type: ignore[index]

    def test_continua_com_som(self) -> None:
        projeto, som = self.separado()
        assert som.has_sound and som.can_adjust_sound
        assert projeto.has_sound


class TestPontas:
    def test_encurtar_pelo_fim(self) -> None:
        projeto = montado(clip(start=0.0, duration=10.0))
        alvo = projeto.clips[0]
        cortado = projeto.resized(alvo.clip_id, "fim", 4.0)
        assert cortado.clips[0].duration == pytest.approx(4.0)
        assert cortado.clips[0].in_point == 0.0

    def test_encurtar_pelo_inicio_anda_dentro_da_midia(self) -> None:
        projeto = montado(clip(start=0.0, duration=10.0))
        cortado = projeto.resized(projeto.clips[0].clip_id, "inicio", 3.0)
        bloco = cortado.clips[0]
        assert bloco.start == pytest.approx(3.0)
        assert bloco.in_point == pytest.approx(3.0), "avança dentro do arquivo"
        assert bloco.duration == pytest.approx(7.0)

    def test_nao_estica_alem_do_fim_do_arquivo(self) -> None:
        # A mídia tem 60 s; um bloco que começa nela aos 55 não pode durar 20.
        projeto = montado(clip(start=0.0, duration=5.0, in_point=55.0))
        esticado = projeto.resized(projeto.clips[0].clip_id, "fim", 40.0)
        assert esticado.clips[0].duration == pytest.approx(5.0)

    def test_imagem_estica_a_vontade(self) -> None:
        # Uma imagem não acaba: ela dura o que mandarem.
        projeto = montado(clip(FOTO, start=0.0, duration=5.0))
        esticado = projeto.resized(projeto.clips[0].clip_id, "fim", 42.0)
        assert esticado.clips[0].duration == pytest.approx(42.0)

    def test_nao_encolhe_ate_sumir(self) -> None:
        projeto = montado(clip(start=0.0, duration=10.0))
        cortado = projeto.resized(projeto.clips[0].clip_id, "fim", 0.0)
        assert cortado.clips[0].duration > 0


class TestDividir:
    def test_divide_em_dois_com_a_origem_certa(self) -> None:
        projeto = montado(clip(start=0.0, duration=10.0, in_point=5.0))
        dividido = projeto.split(projeto.clips[0].clip_id, 4.0)
        esquerda, direita = dividido.tracks[0].sorted_clips()
        assert (esquerda.start, esquerda.duration) == (0.0, 4.0)
        assert (direita.start, direita.duration) == (4.0, 6.0)
        assert direita.in_point == pytest.approx(9.0), "continua de onde parou"

    def test_nao_divide_na_ponta(self) -> None:
        projeto = montado(clip(start=0.0, duration=10.0))
        assert len(projeto.split(projeto.clips[0].clip_id, 0.0).clips) == 1

    def test_os_dois_lados_tem_identidade_propria(self) -> None:
        projeto = montado(clip(start=0.0, duration=10.0))
        dividido = projeto.split(projeto.clips[0].clip_id, 5.0)
        ids = {c.clip_id for c in dividido.clips}
        assert len(ids) == 2, "sem isso a seleção e o cache confundem os dois"


class TestSepararAudio:
    def test_som_sai_do_video_para_trilha_propria(self) -> None:
        projeto = montado(clip(VIDEO, start=3.0, duration=8.0))
        separado = projeto.detached_audio(projeto.clips[0].clip_id)
        video = separado.tracks[0].clips[0]
        audio = [c for t in separado.audio_tracks for c in t.clips]
        assert video.detached, "o som saiu do bloco, não foi apenas silenciado"
        assert not video.has_sound
        assert len(audio) == 1
        assert audio[0].start == pytest.approx(3.0), "o som fica casado com a imagem"
        assert audio[0].duration == pytest.approx(8.0)

    def test_o_bloco_de_video_nao_oferece_mais_volume(self) -> None:
        # É o que a tela usa para desligar o controle: o volume daquele som
        # agora se ajusta no bloco novo, e oferecer o campo aqui seria oferecer
        # um controle que não faz nada.
        projeto = montado(clip(VIDEO, start=0.0, duration=5.0))
        separado = projeto.detached_audio(projeto.clips[0].clip_id)
        assert not separado.tracks[0].clips[0].can_adjust_sound
        assert separado.tracks[0].clips[0].gain_label == "áudio separado"

    def test_nao_separa_duas_vezes(self) -> None:
        projeto = montado(clip(VIDEO, start=0.0, duration=5.0))
        uma_vez = projeto.detached_audio(projeto.clips[0].clip_id)
        alvo = uma_vez.tracks[0].clips[0]
        assert uma_vez.detached_audio(alvo.clip_id) == uma_vez

    def test_arquivo_sem_som_nao_separa_nada(self) -> None:
        projeto = montado(clip(MUDO, start=0.0, duration=5.0))
        assert projeto.detached_audio(projeto.clips[0].clip_id) == projeto

    def test_cria_trilha_quando_nao_ha_lugar(self) -> None:
        projeto = montado(
            clip(VIDEO, start=0.0, duration=10.0), clip(SOM, start=0.0, duration=10.0)
        )
        separado = projeto.detached_audio(projeto.tracks[0].clips[0].clip_id)
        assert len(separado.audio_tracks) == 2, "não empurra o que já estava lá"


class TestExcluirTrilha:
    def test_apaga_a_trilha_com_o_que_houver_nela(self) -> None:
        projeto = montado(clip(VIDEO), clip(SOM))
        sem_audio = projeto.without_track(1)
        assert len(sem_audio.tracks) == 1
        assert sem_audio.tracks[0].kind is TrackKind.VIDEO

    def test_apagar_tudo_e_estado_valido(self) -> None:
        # Importar uma mídia cria a trilha de que ela precisa, então não é
        # preciso guardar uma última trilha "por precaução".
        projeto = montado(clip(VIDEO)).without_track(0).without_track(0)
        assert projeto.tracks == ()
        assert projeto.is_empty

    def test_indice_fora_da_lista_nao_faz_nada(self) -> None:
        projeto = montado(clip(VIDEO))
        assert projeto.without_track(7) == projeto


class TestSomDoProjeto:
    def test_trilha_muda_nao_conta(self) -> None:
        projeto = montado(clip(VIDEO, start=0.0, duration=5.0))
        assert projeto.has_sound
        assert not projeto.with_track_muted(0, True).has_sound

    def test_bloco_mudo_nao_conta(self) -> None:
        projeto = montado(clip(VIDEO, start=0.0, duration=5.0))
        calado = projeto.with_updated_clip(projeto.clips[0].clip_id, muted=True)
        assert not calado.has_sound

    def test_duracao_e_a_do_bloco_mais_distante(self) -> None:
        projeto = montado(
            clip(VIDEO, start=0.0, duration=5.0), clip(SOM, start=12.0, duration=9.0)
        )
        assert projeto.duration == pytest.approx(21.0)


class TestOrdemDasTrilhas:
    def test_video_novo_entra_por_cima_e_audio_embaixo(self) -> None:
        # É a ordem da tela e a da composição: a trilha de vídeo mais baixa é o
        # fundo, e as de cima passam por cima dela.
        projeto = new_project().with_track(TrackKind.VIDEO).with_track(TrackKind.AUDIO)
        espécies = [t.kind for t in projeto.tracks]
        assert espécies == [
            TrackKind.VIDEO, TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.AUDIO
        ]

    def test_bloco_de_cima_e_o_que_aparece(self) -> None:
        projeto = new_project(VIDEO).with_track(TrackKind.VIDEO)
        foto = clip(FOTO, start=1.0, duration=3.0)
        projeto = projeto.with_clip(0, foto)
        visivel = projeto.topmost_video_at(2.0)
        assert visivel is not None and visivel.media.kind is MediaKind.IMAGE
