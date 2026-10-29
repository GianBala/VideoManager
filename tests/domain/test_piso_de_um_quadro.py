"""O menor bloco da edição é um quadro, e não 50 ms.

O piso fixo de ``MIN_SEGMENT`` valia 1,5 quadro a 30 q/s e 3 a 60: era impossível
isolar um quadro só, que é o que se faz ao tirar um defeito de uma tomada. Sem imagem
(uma edição só de áudio) não há quadro, e o piso de sempre continua valendo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.domain.constants import MIN_SEGMENT
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, new_project

VIDEO = MediaRef(
    path=Path("/m/filme.mp4"), kind=MediaKind.VIDEO, duration=60.0, width=1920, height=1080,
    fps=30.0, has_audio=True, channels=2,
)
SOM = MediaRef(
    path=Path("/m/musica.mp3"), kind=MediaKind.AUDIO, duration=200.0, has_audio=True, channels=1,
)


def projeto_de_video(fps: float = 30.0, duration: float = 10.0) -> tuple[Project, Clip]:
    bloco = Clip(VIDEO, 0.0, duration)
    return Project(tracks=(Track(TrackKind.VIDEO, clips=(bloco,)),), fps=fps), bloco


def projeto_de_som() -> tuple[Project, Clip]:
    bloco = Clip(SOM, 0.0, 10.0)
    return Project(tracks=(Track(TrackKind.AUDIO, clips=(bloco,)),)), bloco


class TestPiso:
    @pytest.mark.parametrize("fps", (24.0, 30.0, 60.0, 120.0))
    def test_o_piso_e_um_quadro_da_taxa_da_tela(self, fps):
        projeto, _ = projeto_de_video(fps)
        assert projeto.min_block == pytest.approx(1.0 / fps)
        assert projeto.frame_grid == pytest.approx(1.0 / fps)

    def test_sem_imagem_o_piso_e_o_de_sempre_e_nao_ha_grade(self):
        projeto, _ = projeto_de_som()
        assert projeto.frame_grid is None
        assert projeto.min_block == MIN_SEGMENT

    def test_a_grade_guardada_numa_instancia_nao_vaza_para_a_outra(self):
        """``frame_grid`` fica guardada no projeto (a tela a lê a cada tique); cada projeto novo calcula a sua."""
        from dataclasses import replace
        som, bloco = projeto_de_som()
        assert som.frame_grid is None
        com_video = som.with_track(TrackKind.VIDEO).with_clip(1, Clip(VIDEO, 0.0, 5.0))
        assert com_video.frame_grid == pytest.approx(1 / 30) and som.frame_grid is None
        assert replace(com_video, fps=60.0).frame_grid == pytest.approx(1 / 60) and com_video.frame_grid == pytest.approx(1 / 30)
        assert som == Project(tracks=som.tracks) and hash(som) == hash(Project(tracks=som.tracks))

    def test_projeto_vazio_nao_tem_grade(self):
        assert Project().frame_grid is None
        assert Project().min_block == MIN_SEGMENT

    def test_a_tesoura_isola_um_quadro(self):
        projeto, bloco = projeto_de_video(30.0)
        quadro = 1 / 30
        primeiro = projeto.split(bloco.clip_id, 10 * quadro)
        assert [round(c.duration * 30) for c in primeiro.clips] == [10, 290]
        # Segunda divisão, um quadro adiante: o bloco do meio tem um quadro e nada mais.
        resto = max(primeiro.clips, key=lambda c: c.start)
        segundo = primeiro.split(resto.clip_id, 11 * quadro)
        assert [round(c.duration * 30) for c in segundo.clips] == [10, 1, 289]

    def test_a_tesoura_recusa_menos_que_um_quadro(self):
        projeto, bloco = projeto_de_video(30.0)
        assert projeto.split(bloco.clip_id, 0.5 / 30) is projeto
        assert projeto.split(bloco.clip_id, bloco.end - 0.5 / 30) is projeto

    @pytest.mark.parametrize("edge", ("inicio", "fim"))
    def test_a_alca_chega_a_um_quadro_e_nao_passa(self, edge):
        projeto, bloco = projeto_de_video(30.0)
        alvo = bloco.end if edge == "inicio" else bloco.start
        # Puxada além do outro lado, a alça para em um quadro: nem 50 ms, nem zero.
        mexido = projeto.resized(bloco.clip_id, edge, alvo).find(bloco.clip_id)[1]
        assert mexido.duration == pytest.approx(1 / 30)

    def test_sem_imagem_a_alca_para_nos_50_ms(self):
        projeto, bloco = projeto_de_som()
        mexido = projeto.resized(bloco.clip_id, "fim", 0.0).find(bloco.clip_id)[1]
        assert mexido.duration == pytest.approx(MIN_SEGMENT)

    def test_sem_imagem_a_tesoura_segue_recusando_abaixo_de_50_ms(self):
        projeto, bloco = projeto_de_som()
        assert projeto.split(bloco.clip_id, 0.04) is projeto

    def test_a_velocidade_nao_estica_um_bloco_de_um_quadro_para_dois(self):
        projeto, bloco = projeto_de_video(30.0)
        curto = projeto.resized(bloco.clip_id, "fim", 1 / 30).find(bloco.clip_id)[1]
        assert curto.duration_at_speed(1.0, projeto.min_block) == pytest.approx(1 / 30)
        assert curto.duration_at_speed(2.0, projeto.min_block) == pytest.approx(1 / 30)
        # Sem o piso do projeto, o de sempre: quem não o passa não muda.
        assert curto.duration_at_speed(2.0) == pytest.approx(MIN_SEGMENT)


class TestCorteRapido:
    """Copiar os dados não corta um quadro: o cortador recusa o trecho abaixo de 50 ms."""

    def test_um_bloco_de_um_quadro_vai_para_o_compositor(self):
        projeto = new_project(VIDEO)
        curto = projeto.resized(projeto.clips[0].clip_id, "fim", 1 / 30)
        assert curto.clips[0].duration == pytest.approx(1 / 30)
        assert simple_trim(curto) is None

    def test_um_bloco_comum_segue_sendo_corte_simples(self):
        projeto = new_project(VIDEO)
        recortado = projeto.resized(projeto.clips[0].clip_id, "fim", 2.0)
        assert simple_trim(recortado) is not None
