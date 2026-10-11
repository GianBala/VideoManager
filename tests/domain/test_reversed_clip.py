"""Bloco invertido: o que o modelo diz sobre ele, sem abrir o ffmpeg.

O bloco invertido cobre o mesmo trecho da mídia (``in_point`` a ``out_point``) e
a edição o percorre ao contrário. Quase tudo que muda é a ponta: o começo do
bloco passa a ser o topo do trecho, então aparar, dividir e esticar mexem em
pontos diferentes dos de um bloco normal. Cada teste abaixo trava um desses
pontos com números que se conferem de cabeça.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.export_policy import simple_trim
from videomanager.domain.project import Clip, MediaKind, MediaRef, OverlayType, Project, Track, TrackKind
from videomanager.domain.reversal import MAX_REVERSE_SPAN, reverse_rate


def _media(duration=20.0, width=1280, height=720, fps=30.0, kind=MediaKind.VIDEO, audio=True):
    return MediaRef(path=Path("/m/clipe.mp4"), kind=kind, duration=duration, width=width,
                    height=height, fps=fps, has_audio=audio, channels=2)


def _projeto(clip):
    return Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),))


def _bloco(projeto):
    return projeto.tracks[0].clips[0]


class TestTempoDaOrigem:
    def test_o_comeco_do_bloco_e_o_topo_do_trecho(self):
        clip = Clip(_media(), start=2.0, duration=10.0, in_point=4.0, reversed=True)
        assert clip.out_point == 14.0
        assert clip.head_point == 14.0 and clip.tail_point == 4.0
        assert clip.source_time(2.0) == pytest.approx(14.0)
        assert clip.source_time(7.0) == pytest.approx(9.0)
        assert clip.source_time(12.0) == pytest.approx(4.0)

    def test_a_velocidade_encurta_o_trecho_percorrido_por_segundo_de_edicao(self):
        clip = Clip(_media(), start=0.0, duration=5.0, in_point=2.0, speed=2.0, reversed=True)
        assert clip.out_point == 12.0
        assert clip.source_time(1.0) == pytest.approx(10.0)

    def test_bloco_normal_nao_muda(self):
        clip = Clip(_media(), start=2.0, duration=10.0, in_point=4.0)
        assert clip.head_point == 4.0 and clip.tail_point == 14.0
        assert clip.source_time(7.0) == pytest.approx(9.0)


class TestDividir:
    def test_a_primeira_metade_da_edicao_fica_com_o_topo(self):
        clip = Clip(_media(), start=2.0, duration=10.0, in_point=4.0, reversed=True)
        esquerda, direita = sorted(_projeto(clip).split(clip.clip_id, 6.0).tracks[0].clips, key=lambda c: c.start)
        assert (esquerda.in_point, esquerda.out_point) == (pytest.approx(10.0), pytest.approx(14.0))
        assert (direita.in_point, direita.out_point) == (pytest.approx(4.0), pytest.approx(10.0))
        assert esquerda.reversed and direita.reversed

    def test_as_metades_cobrem_o_trecho_sem_perder_nem_repetir(self):
        clip = Clip(_media(), start=0.0, duration=9.0, in_point=3.0, reversed=True)
        metades = sorted(_projeto(clip).split(clip.clip_id, 2.5).tracks[0].clips, key=lambda c: c.start)
        # O que a primeira termina é onde a segunda começa, na origem.
        assert metades[0].tail_point == pytest.approx(metades[1].head_point)
        assert metades[0].head_point == pytest.approx(clip.head_point)
        assert metades[1].tail_point == pytest.approx(clip.tail_point)

    def test_bloco_normal_continua_dividindo_como_antes(self):
        clip = Clip(_media(), start=2.0, duration=10.0, in_point=4.0)
        esquerda, direita = sorted(_projeto(clip).split(clip.clip_id, 6.0).tracks[0].clips, key=lambda c: c.start)
        assert (esquerda.in_point, direita.in_point) == (pytest.approx(4.0), pytest.approx(8.0))


class TestAlcas:
    def test_encurtar_o_comeco_tira_do_topo(self):
        clip = Clip(_media(), start=2.0, duration=10.0, in_point=4.0, reversed=True)
        novo = _bloco(_projeto(clip).resized(clip.clip_id, "inicio", 5.0))
        assert (novo.start, novo.duration) == (pytest.approx(5.0), pytest.approx(7.0))
        assert novo.in_point == pytest.approx(4.0)
        assert novo.out_point == pytest.approx(11.0)

    def test_encurtar_o_fim_tira_da_base(self):
        clip = Clip(_media(), start=2.0, duration=10.0, in_point=4.0, reversed=True)
        novo = _bloco(_projeto(clip).resized(clip.clip_id, "fim", 9.0))
        assert novo.duration == pytest.approx(7.0)
        assert novo.out_point == pytest.approx(14.0)
        assert novo.in_point == pytest.approx(7.0)

    def test_esticar_o_fim_para_no_comeco_da_midia_sem_entrada_negativa(self):
        clip = Clip(_media(), start=0.0, duration=4.0, in_point=4.0, reversed=True, speed=1.0)
        novo = _bloco(_projeto(clip).resized(clip.clip_id, "fim", 11.0))
        assert novo.duration == pytest.approx(8.0)
        assert novo.in_point >= 0.0

    def test_esticar_o_comeco_para_no_fim_da_midia(self):
        clip = Clip(_media(duration=20.0), start=5.0, duration=5.0, in_point=10.0, reversed=True)
        novo = _bloco(_projeto(clip).resized(clip.clip_id, "inicio", 0.0))
        assert novo.out_point <= 20.0 + 1e-9
        assert novo.out_point == pytest.approx(15.0 + 5.0)  # 5 s a mais no topo

    def test_bloco_invertido_estica_sem_teto_de_memoria_e_para_no_teto_de_sanidade(self):
        """O vídeo é lido em janelas: o que limita a alça é a mídia e o teto de meia hora."""
        longa = _media(duration=7200.0, width=1920, height=1080)
        clip = Clip(longa, start=0.0, duration=8.0, in_point=4000.0, reversed=True)
        novo = _bloco(_projeto(clip).resized(clip.clip_id, "fim", 3000.0))
        assert novo.duration == pytest.approx(MAX_REVERSE_SPAN)
        assert novo.duration > 60.0  # bem além do que um processo só aguentaria

    def test_bloco_ja_acima_do_teto_pode_encolher_mas_nao_crescer(self):
        grande = Clip(_media(duration=7200.0), start=0.0, duration=2000.0, in_point=4000.0, reversed=True)
        projeto = _projeto(grande)
        assert _bloco(projeto.resized(grande.clip_id, "fim", 2500.0)).duration == pytest.approx(2000.0)
        assert _bloco(projeto.resized(grande.clip_id, "fim", 1500.0)).duration == pytest.approx(1500.0)


class TestSepararAudio:
    def test_o_audio_separado_segue_o_sentido_da_imagem(self):
        clip = Clip(_media(), start=0.0, duration=6.0, in_point=2.0, reversed=True)
        projeto = _projeto(clip).detached_audio(clip.clip_id)
        audio = next(c for t in projeto.tracks for c in t.clips if c.audio_only)
        assert audio.reversed
        assert (audio.in_point, audio.out_point) == (clip.in_point, clip.out_point)


class TestQuemPodeSerInvertido:
    def test_video_e_audio_podem(self):
        assert Clip(_media(), 0.0, 5.0).can_reverse
        assert Clip(_media(kind=MediaKind.AUDIO, width=None, height=None, fps=None), 0.0, 5.0).can_reverse

    def test_imagem_texto_e_filtro_nao(self):
        assert not Clip(_media(kind=MediaKind.IMAGE, duration=None), 0.0, 5.0).is_reversible
        texto = Clip(_media(kind=MediaKind.IMAGE, duration=None), 0.0, 5.0, overlay_type=OverlayType.TEXT)
        assert not texto.is_reversible

    def test_projeto_antigo_nao_inverte_o_que_nao_tem_sentido(self):
        """Um .vmp editado à mão com ``reversed`` numa imagem não pode inverter nada."""
        imagem = Clip(_media(kind=MediaKind.IMAGE, duration=None), 0.0, 5.0, reversed=True)
        assert imagem.reversed is False

    def test_video_longo_pode_ser_invertido(self):
        """Era o defeito: um vídeo de 1080p com mais de ~11 s ficava com o item desabilitado."""
        assert Clip(_media(width=1920, height=1080, duration=600.0), 0.0, 120.0).can_reverse

    def test_acima_de_meia_hora_nao_se_oferece_mas_o_invertido_sempre_desfaz(self):
        longo = Clip(_media(duration=7200.0), 0.0, MAX_REVERSE_SPAN + 60.0)
        assert not longo.can_reverse
        assert replace(longo, reversed=True).can_reverse

    def test_o_limite_vale_na_mídia_percorrida_e_nao_na_edição(self):
        # 20 min de edição a 2× percorrem 40 min de mídia.
        assert not Clip(_media(duration=7200.0), 0.0, 1200.0, speed=2.0).can_reverse
        assert Clip(_media(duration=7200.0), 0.0, 1200.0, speed=1.0).can_reverse

    def test_som_sozinho_nao_pesa(self):
        audio = Clip(_media(kind=MediaKind.AUDIO, width=None, height=None, fps=None), 0.0, 1500.0)
        assert audio.reverse_rate == 0 and audio.can_reverse

    def test_tamanho_do_quadro_desconhecido_nao_se_oferece(self):
        sem_tamanho = Clip(_media(width=None, height=None), 0.0, 5.0)
        assert sem_tamanho.reverse_rate == float("inf") and not sem_tamanho.can_reverse

    def test_a_taxa_acompanha_a_midia_percorrida_por_segundo_de_edicao(self):
        normal = Clip(_media(), 0.0, 10.0)
        dobro = Clip(_media(), 0.0, 5.0, speed=2.0)
        assert dobro.reverse_rate == pytest.approx(2 * normal.reverse_rate)
        assert reverse_rate(1280, 720, 30.0) == normal.reverse_rate


def test_copiar_os_dados_nao_inverte():
    """O corte sem recodificar copia os pacotes: o bloco invertido só sai composto."""
    midia = _media(duration=10.0)

    def projeto(clip):
        return Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),),
                       width=midia.width, height=midia.height, fps=midia.fps)

    normal = Clip(midia, 0.0, 4.0)
    assert simple_trim(projeto(normal)) is not None
    assert simple_trim(projeto(replace(normal, reversed=True))) is None


def test_a_marca_do_bloco_invertido_existe_nos_dois_idiomas():
    from videomanager.domain import i18n

    invertido, normal = Clip(_media(), 0.0, 5.0, reversed=True), Clip(_media(), 0.0, 5.0)
    assert invertido.reverse_label == "invertido" and normal.reverse_label == ""
    i18n.set_language(i18n.ENGLISH)
    assert invertido.reverse_label == "reversed" and normal.reverse_label == ""
