"""Testes do projeto de edição: trilhas, blocos e as operações sobre eles.

Tudo aqui é função pura sobre estruturas imutáveis — não precisa de ffmpeg, de
arquivo de mídia nem de Qt. O que se afirma é o que separa uma linha do tempo
utilizável de uma que perde trabalho: bloco que não sobrepõe o vizinho, ponta
que não passa do fim da mídia, e toda operação devolvendo um projeto novo, sem
tocar no anterior — que é o que sustenta o desfazer.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.project import IMAGE_DURATION
from videomanager.domain.project import MAX_AUTO_FPS
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import accepts
from videomanager.domain.project import auto_canvas
from videomanager.domain.project import display_width
from videomanager.domain.project import media_ref
from videomanager.domain.project import new_project

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
        # Imagem é parte da trilha de vídeo; Adicionais ficam com texto e filtro.
        assert accepts(TrackKind.VIDEO, clip(FOTO))
        assert not accepts(TrackKind.ADDITIONAL, clip(FOTO))
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

    def test_so_fotos_nao_definem_a_tela_sozinhas(self) -> None:
        # Com as fotos na trilha de vídeo, adotar o formato delas continua sendo
        # uma escolha explícita (``slideshow_canvas``, botão da interface): uma
        # apresentação de fotos de 6000 px não pode virar a tela da edição.
        from videomanager.domain.project import slideshow_canvas
        projeto = auto_canvas(montado(clip(FOTO)))
        assert (projeto.width, projeto.height) == (1920, 1080)
        assert slideshow_canvas(projeto) == (800, 600)

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


class TestTransicao:
    @staticmethod
    def projeto(duration: float = 1.0) -> tuple[Project, Clip, Clip, Clip]:
        left = clip(start=0.0, duration=4.0, in_point=2.0)
        right = clip(start=4.0, duration=3.0, in_point=8.0)
        marker = Clip(
            media=MediaRef(
                path=Path("Transição_Dissolve"),
                kind=MediaKind.IMAGE,
                duration=duration,
            ),
            start=4.0 - duration / 2.0,
            duration=duration,
            overlay_type="transition",
            transition_name="dissolve",
            transition_left_id=left.clip_id,
            transition_right_id=right.clip_id,
        )
        return montado(left, right).with_clip(0, marker), left, right, marker

    def test_resolve_o_par_por_identidade_no_ponto_de_edicao(self) -> None:
        projeto, left, right, marker = self.projeto()
        context = projeto.transition_context(marker)
        assert context is not None
        assert (context.left, context.right) == (left, right)
        assert context.cut == pytest.approx(4.0)
        assert (context.start, context.end) == pytest.approx((3.5, 4.5))

    def test_duracao_e_limitada_e_recentralizada_pelo_dominio(self) -> None:
        projeto, _, _, marker = self.projeto()
        alterado = projeto.with_updated_clip(marker.clip_id, duration=10.0)
        synced = alterado.find(marker.clip_id)
        assert synced is not None
        _, updated = synced
        assert updated.duration == pytest.approx(3.0)
        assert updated.start == pytest.approx(2.5)

    def test_arrastar_uma_ponta_redimensiona_as_duas_ao_redor_do_corte(self) -> None:
        projeto, _, _, marker = self.projeto()
        alterado = projeto.resized(marker.clip_id, "fim", 5.0)
        found = alterado.find(marker.clip_id)
        assert found is not None
        _, updated = found
        assert updated.duration == pytest.approx(2.0)
        assert updated.start == pytest.approx(3.0)
        assert updated.end == pytest.approx(5.0)

    def test_arrastar_transicao_nao_usa_minimo_de_corte_comum(self) -> None:
        projeto, _, _, marker = self.projeto()
        alterado = projeto.resized(marker.clip_id, "fim", 4.025)
        found = alterado.find(marker.clip_id)
        assert found is not None
        _, updated = found
        assert updated.duration == pytest.approx(0.2)
        assert updated.start == pytest.approx(3.9)

    def test_apagar_uma_ponta_apaga_o_marcador_orfao(self) -> None:
        projeto, left, _, marker = self.projeto()
        alterado = projeto.without_clip(left.clip_id)
        assert alterado.find(marker.clip_id) is None

    def test_separar_as_pontas_remove_a_transicao_do_corte(self) -> None:
        projeto, _, right, marker = self.projeto()
        alterado = projeto.moved(right.clip_id, 0, 10.0)
        assert alterado.find(marker.clip_id) is None

    def test_nao_resolve_transicao_sobre_um_vao(self) -> None:
        projeto, left, right, marker = self.projeto()
        track = Track(
            kind=TrackKind.VIDEO,
            clips=(left, replace(right, start=5.0), marker),
        )
        assert Project(tracks=(track,)).transition_context(marker) is None

    def test_tesoura_nao_divide_um_marcador_de_transicao(self) -> None:
        projeto, _, _, marker = self.projeto()
        assert projeto.split(marker.clip_id, marker.start + 0.25) == projeto

    def test_marcador_nao_alonga_a_duracao_do_projeto(self) -> None:
        projeto, _, _, marker = self.projeto()
        invalido = replace(marker, start=100.0)
        track = replace(
            projeto.tracks[0],
            clips=tuple(
                invalido if clip.clip_id == marker.clip_id else clip
                for clip in projeto.tracks[0].clips
            ),
        )
        assert replace(projeto, tracks=(track,)).duration == pytest.approx(7.0)


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
        assert movido.tracks[0].clips[1].start == pytest.approx(20.0), (
            "D04: troca sem sobrepor nem eliminar o vão de 15 segundos"
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


class TestNomeDaTrilhaNova:
    """Apagar uma trilha do meio não pode fazer a próxima nascer repetida."""

    def test_ocupa_o_primeiro_numero_livre(self) -> None:
        from videomanager.domain.project import Project

        projeto = Project()
        for _ in range(3):
            projeto = projeto.with_track(TrackKind.VIDEO)
        assert sorted(t.name for t in projeto.tracks) == ["Vídeo 1", "Vídeo 2", "Vídeo 3"]

        sem_a_do_meio = projeto.without_track([t.name for t in projeto.tracks].index("Vídeo 2"))
        nova = sem_a_do_meio.with_track(TrackKind.VIDEO)
        assert sorted(t.name for t in nova.tracks) == ["Vídeo 1", "Vídeo 2", "Vídeo 3"]
        seguinte = nova.with_track(TrackKind.VIDEO)
        assert sorted(t.name for t in seguinte.tracks) == ["Vídeo 1", "Vídeo 2", "Vídeo 3", "Vídeo 4"]

    @pytest.mark.parametrize(
        ("kind", "rotulo"), [(TrackKind.AUDIO, "Áudio"), (TrackKind.ADDITIONAL, "Adicionais")]
    )
    def test_vale_para_todas_as_especies(self, kind, rotulo) -> None:
        from videomanager.domain.project import Project

        projeto = Project().with_track(kind).with_track(kind)
        primeira = [t.name for t in projeto.tracks].index(f"{rotulo} 1")
        livre = projeto.without_track(primeira)
        assert [t.name for t in livre.tracks] == [f"{rotulo} 2"]
        assert sorted(t.name for t in livre.with_track(kind).tracks) == [f"{rotulo} 1", f"{rotulo} 2"]

    def test_nome_escolhido_pelo_usuario_nao_entra_na_conta(self) -> None:
        from videomanager.domain.project import Project

        projeto = Project().with_track(TrackKind.VIDEO, name="Narração")
        assert projeto.with_track(TrackKind.VIDEO).tracks[0].name == "Vídeo 1"


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

    def test_reordenar_trilhas_altera_posicao_e_mantem_integridade(self) -> None:
        projeto = new_project().with_track(TrackKind.VIDEO, name="Trilha 2").with_track(TrackKind.VIDEO, name="Trilha 1")
        # tracks: Trilha 1 (index 0), Trilha 2 (index 1), Video 1 (index 2), Audio 1 (index 3)
        assert projeto.tracks[0].name == "Trilha 1"
        assert projeto.tracks[1].name == "Trilha 2"

        # Move index 0 para index 1
        movido = projeto.reordered_track(0, 1)
        assert movido.tracks[0].name == "Trilha 2"
        assert movido.tracks[1].name == "Trilha 1"
        assert len(movido.tracks) == len(projeto.tracks)

        # Mesmos índices ou fora dos limites não alteram o projeto
        assert projeto.reordered_track(0, 0) is projeto
        assert projeto.reordered_track(-1, 2) is projeto
        assert projeto.reordered_track(0, 99) is projeto

    def test_reordenar_trilha_de_video_altera_prioridade_de_exibicao(self) -> None:
        # Projeto com duas trilhas de vídeo com blocos no mesmo instante
        proj = new_project()
        clip_v1 = clip(VIDEO, start=0.0, duration=5.0)
        clip_foto = clip(FOTO, start=0.0, duration=5.0)

        # Trilha 0 terá FOTO, Trilha 1 terá VIDEO
        proj = proj.with_track(TrackKind.VIDEO, name="Camada Superior")
        # proj.tracks: Camada Superior (0), Video 1 (1), Audio 1 (2)
        proj = proj.with_clip(0, clip_foto)
        proj = proj.with_clip(1, clip_v1)

        # No início, Camada Superior (0) é quem aparece por cima
        assert proj.topmost_video_at(2.0).media.kind is MediaKind.IMAGE

        # Ao mover a Trilha 1 (Vídeo) para o índice 0, ela passa a ter prioridade visual máxima
        reordenado = proj.reordered_track(1, 0)
        assert reordenado.tracks[0].name == "Vídeo 1"
        assert reordenado.tracks[1].name == "Camada Superior"
        assert reordenado.topmost_video_at(2.0).media.kind is MediaKind.VIDEO

    def test_trilha_adicionais_e_velocidade(self) -> None:
        proj = new_project().with_track(TrackKind.ADDITIONAL, name="Adicionais 1")
        assert len(proj.additional_tracks) == 1
        assert proj.additional_tracks[0].name == "Adicionais 1"

        c_foto = clip(FOTO, start=0.0, duration=5.0)
        c_text = clip(FOTO, start=2.0, duration=3.0, overlay_type="text", text_content="Olá")
        assert accepts(TrackKind.VIDEO, c_foto) and not accepts(TrackKind.ADDITIONAL, c_foto)
        assert accepts(TrackKind.ADDITIONAL, c_text)

        # Teste de velocidade
        c_fast = clip(VIDEO, start=0.0, duration=5.0, speed=2.0)
        assert c_fast.speed == 2.0
        assert c_fast.speed_label == "2,0x"
        assert c_fast.out_point == 10.0  # 0 + 5.0 * 2.0
        assert c_fast.source_time(2.0) == 4.0  # 0 + 2.0 * 2.0

        c_slow = clip(VIDEO, start=0.0, duration=5.0, speed=0.5)
        assert c_slow.speed_label == "0,5x"
        assert c_slow.out_point == 2.5
        assert c_slow.source_time(2.0) == 1.0

    def test_track_visibility_and_export_duration(self) -> None:
        c_vid = clip(VIDEO, start=0.0, duration=10.0)
        c_add = clip(FOTO, start=5.0, duration=15.0)  # vai até 20.0
        c_aud = clip(SOM, start=0.0, duration=25.0)   # vai até 25.0

        p = Project(
            tracks=(
                Track(kind=TrackKind.VIDEO, clips=(c_vid,), name="Vídeo"),
                Track(kind=TrackKind.ADDITIONAL, clips=(c_add,), name="Adicionais"),
                Track(kind=TrackKind.AUDIO, clips=(c_aud,), name="Áudio"),
            )
        )
        assert all(t.visible for t in p.tracks)
        assert p.duration == 25.0
        assert p.export_duration == 25.0
        assert p.has_video is True
        assert p.has_sound is True

        # Ocultar vídeo: export_duration passa a ser ditado por adicionais e áudio
        p_no_vid = p.with_track_visible(0, False)
        assert p_no_vid.tracks[0].visible is False
        assert p_no_vid.has_video is True  # adicionais ainda tem imagem
        # Se ocultarmos adicionais também, não tem mais vídeo
        p_no_vids = p_no_vid.with_track_visible(1, False)
        assert p_no_vids.has_video is False
        assert p_no_vids.has_sound is True  # áudio ainda toca
        assert p_no_vids.export_duration == 25.0

        # Se calar o áudio com vídeo oculto, não tem som
        p_no_sound = p_no_vid.with_track_muted(2, True)
        assert p_no_sound.has_sound is False
        # export_duration considera apenas o que será exportado (adicionais = 20s)
        assert p_no_sound.export_duration == 20.0

    def test_for_export_descarta_trilhas_invisiveis_e_audios_mudos(self) -> None:
        c_vid1 = clip(VIDEO, start=0.0, duration=10.0)
        c_vid2 = clip(MUDO, start=0.0, duration=20.0)
        c_aud_mudo = clip(SOM, start=0.0, duration=25.0)
        c_aud_ativo = clip(SOM, start=0.0, duration=15.0)

        p = Project(
            tracks=(
                Track(kind=TrackKind.VIDEO, clips=(c_vid1,), visible=True, name="V1"),
                Track(kind=TrackKind.VIDEO, clips=(c_vid2,), visible=False, name="V2_oculto"),
                Track(kind=TrackKind.AUDIO, clips=(c_aud_mudo,), visible=True, muted=True, name="A_mudo"),
                Track(kind=TrackKind.AUDIO, clips=(c_aud_ativo,), visible=True, muted=False, name="A_ativo"),
            )
        )
        exp = p.for_export()
        assert len(exp.tracks) == 2
        assert exp.tracks[0].name == "V1"
        assert exp.tracks[1].name == "A_ativo"
        assert exp.duration == 15.0
        assert exp.export_duration == 15.0

    def test_auto_canvas_ignora_trilhas_invisiveis(self) -> None:
        c_1080p = clip(VIDEO, start=0.0, duration=10.0)  # 1920x1080 @ 30fps
        quatro_k = MediaRef(
            path=Path("/m/4k.mp4"), kind=MediaKind.VIDEO, duration=20, width=3840,
            height=2160, fps=60,
        )
        c_4k = clip(quatro_k, start=0.0, duration=20.0)

        p = Project(
            tracks=(
                Track(kind=TrackKind.VIDEO, clips=(c_1080p,), visible=True),
                Track(kind=TrackKind.VIDEO, clips=(c_4k,), visible=False),
            )
        )
        # Como o 4K está invisível, auto_canvas deve escolher 1080p a 30fps
        canvas = auto_canvas(p)
        assert (canvas.width, canvas.height) == (1920, 1080)
        assert canvas.fps == 30.0

    def test_auto_canvas_imagem_em_trilha_adicional_nao_redefine_canvas_ao_excluir_video(self) -> None:
        c_video = clip(VIDEO, start=0.0, duration=10.0)
        foto_overlay = MediaRef(
            path=Path("/m/overlay.png"), kind=MediaKind.IMAGE, width=1552, height=608
        )
        c_foto = clip(foto_overlay, start=0.0, duration=5.0)

        p = Project(
            tracks=(
                Track(kind=TrackKind.VIDEO, clips=(c_video,)),
                Track(kind=TrackKind.ADDITIONAL, clips=(c_foto,)),
            )
        )
        canvas = auto_canvas(p)
        assert (canvas.width, canvas.height) == (1920, 1080)

        sem_video = p.without_clip(c_video.clip_id)
        canvas_sem_video = auto_canvas(sem_video)
        assert (canvas_sem_video.width, canvas_sem_video.height) == (1920, 1080)

    def test_clip_is_image_apenas_para_imagem_real(self) -> None:
        ref_img = MediaRef(path=Path("/m/foto.png"), kind=MediaKind.IMAGE)
        c_img = clip(ref_img)
        assert c_img.is_image is True

        c_img_overlay = clip(ref_img, overlay_type="image")
        assert c_img_overlay.is_image is True

        ref_pseudo = MediaRef(path=Path("Filtro_PB"), kind=MediaKind.IMAGE, duration=5.0)
        c_filter = clip(ref_pseudo, overlay_type="filter", filter_name="pb")
        assert c_filter.is_image is False

        ref_txt = MediaRef(path=Path("Texto_1"), kind=MediaKind.IMAGE, duration=5.0)
        c_text = clip(ref_txt, overlay_type="text", text_content="Teste")
        assert c_text.is_image is False

        ref_trans = MediaRef(path=Path("Trans_1"), kind=MediaKind.IMAGE, duration=1.0)
        c_trans = clip(ref_trans, overlay_type="transition", transition_name="fade")
        assert c_trans.is_image is False

    def test_trim_clip_filtro_permite_expansao(self) -> None:
        ref_f = MediaRef(path=Path("Filtro_PB"), kind=MediaKind.IMAGE, duration=5.0)
        c_filter = clip(ref_f, start=2.0, duration=5.0, overlay_type="filter", filter_name="pb")
        p = Project(tracks=(Track(kind=TrackKind.ADDITIONAL, clips=(c_filter,)),))
        # Deve permitir esticar além dos 5s originais
        esticado = p.resized(c_filter.clip_id, "fim", 15.0)
        assert esticado.clips[0].duration == 13.0


def test_foto_inicial_esta_em_trilha_compativel():
    project = new_project(FOTO)
    index, photo = project.find(project.clips[0].clip_id)
    assert accepts(project.tracks[index].kind, photo)


@pytest.mark.parametrize('overlay', ['none', 'text', 'filter'])
def test_estender_estatico_a_esquerda_nao_cria_origem_negativa(overlay):
    item = clip(FOTO, start=5, duration=2, overlay_type=overlay)
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(item,)),))
    resized = project.resized(item.clip_id, 'inicio', 1).find(item.clip_id)[1]
    assert resized.start == 1 and resized.end == 7
    assert resized.in_point == 0


@pytest.mark.parametrize('sound', [False, True])
def test_mjpeg_em_avi_e_video(sound):
    streams = (LocalStream(0, 'video', 'mjpeg', width=320, height=240, fps=25),)
    if sound:
        streams += (LocalStream(1, 'audio', 'pcm_s16le'),)
    local = LocalMedia(Path('/m/camera.avi'), 5, 'avi', 100, streams)
    reference = media_ref(local)
    assert reference.kind is MediaKind.VIDEO
    assert reference.duration == 5 and reference.has_audio == sound


@pytest.mark.parametrize('fmt,codec', [('image2', 'mjpeg'), ('png_pipe', 'png'), ('webp_pipe', 'webp')])
def test_formatos_estaticos_continuam_imagens(fmt, codec):
    local = LocalMedia(Path('/m/foto'), None, fmt, 100, (LocalStream(0, 'video', codec),))
    assert media_ref(local).kind is MediaKind.IMAGE


@pytest.mark.parametrize('rotation,size', [(90, (480, 640)), (-90, (480, 640)), (180, (640, 480))])
def test_orientacao_define_geometria_visual(rotation, size):
    local = LocalMedia(Path('/m/rot.mp4'), 2, 'mp4', 100,
                       (LocalStream(0, 'video', 'h264', width=640, height=480, rotation=rotation),))
    reference = media_ref(local)
    assert (reference.width, reference.height) == size
    assert (local.video.width, local.video.height) == (640, 480)


@pytest.mark.parametrize('speed', [.5, 2, 3])
def test_aparar_velocidade_mapeia_origem_e_limite(speed):
    item = clip(VIDEO, start=5, duration=6, in_point=6, speed=speed)
    project = montado(item)
    left = project.resized(item.clip_id, 'inicio', 6).find(item.clip_id)[1]
    assert left.in_point == pytest.approx(6 + speed)
    extended = project.resized(item.clip_id, 'fim', 1000).find(item.clip_id)[1]
    assert extended.out_point == pytest.approx(VIDEO.duration)
    assert extended.duration == pytest.approx((VIDEO.duration-6)/speed)


def test_destacar_audio_preserva_intervalo_em_velocidade_alterada():
    item = clip(VIDEO, start=3, duration=5, in_point=2, speed=2)
    result = montado(item).detached_audio(item.clip_id)
    detached = next(c for c in result.clips if c.audio_only)
    assert detached.speed == 2 and detached.source_time(6) == item.source_time(6)
    assert detached.out_point == item.out_point


def test_marcador_nao_limita_vao_livre():
    item = clip(start=0, duration=5)
    marker = clip(FOTO, start=4, duration=2, overlay_type='transition')
    assert Track(TrackKind.VIDEO, clips=(item, marker)).free_range(2, ignore=item.clip_id) == (0, float('inf'))


def test_dividir_video_mantem_transicao_na_metade_adjacente():
    left, right = clip(start=0, duration=6), clip(start=6, duration=6, in_point=6)
    marker = clip(FOTO, start=5, duration=2, overlay_type='transition',
                  transition_left_id=left.clip_id, transition_right_id=right.clip_id)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(left, right, marker)),))
    divided = project.split(left.clip_id, 3)
    retained = divided.find(marker.clip_id)[1]
    context = divided.transition_context(retained)
    assert context is not None and context.left.start == 3 and context.cut == 6


def test_swap_preserva_vao_intervalo_total_e_inverte_sem_perda():
    media = MediaRef(Path('/m/a.mp4'), MediaKind.VIDEO, duration=30)
    first = Clip(media, 1, 2)
    second = Clip(media, 5, 4)
    third = Clip(media, 10, 2)
    p = Project(tracks=(Track(TrackKind.VIDEO, clips=(first, second, third)),))
    swapped = p._swapped(0, first, 6)
    a, b = swapped.find(second.clip_id)[1], swapped.find(first.clip_id)[1]
    assert (a.start, b.start, b.end) == (1, 7, 9)
    assert b.start - a.end == 2
    assert swapped.find(third.clip_id)[1] == third
    restored = swapped._swapped(0, b, 1)
    assert restored == p


def test_slideshow_e_explicito_e_nao_usa_logo_para_mudar_video():
    from videomanager.domain.project import slideshow_canvas
    photo = MediaRef(Path('/m/foto.jpg'), MediaKind.IMAGE, width=3000, height=4000)
    p = new_project(photo)
    assert (p.width, p.height) == (1920, 1080)
    assert slideshow_canvas(p) == (1440, 1920)
    # A foto agora está na trilha de vídeo 0; o vídeo entra depois dela.
    mixed = p.with_clip(0, Clip(MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, width=1920, height=1080), 10, 3))
    assert slideshow_canvas(mixed) is None


def test_escala_global_proporcional_respeita_limites_da_curva_inteira():
    from videomanager.domain.keyframe import Keyframe
    item = clip(duration=4, keyframes=(Keyframe(0), Keyframe(3, scale_x=10, scale_y=5)))
    changed = item.with_edited_transform(0, {'scale_x': 2, 'scale_y': 2}, fps=30, whole_animation=True)
    assert changed.keyframes == item.keyframes
