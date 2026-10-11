"""O volume do bloco como curva dos quadros-chave: o modelo, sem abrir ffmpeg nem Qt.

O quadro-chave ganha ``gain_offset_db``: volume em dB **relativo** ao do bloco (``gain_db``). Relativo
de propósito: com 0 a curva não mexe, então todo quadro-chave antigo continua neutro sem migração, e o
🔊 da barra continua sendo o volume do bloco inteiro. A curva anda junto da pose — é o mesmo mecanismo
de animação, e dividir, aparar, mudar a velocidade e desfazer funcionam sem código novo.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import MAX_GAIN_DB, MIN_GAIN_DB, Clip, MediaKind, MediaRef, Project, Track, TrackKind

FPS = 30.0


def _video(audio=True) -> MediaRef:
    return MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=30.0, width=1280, height=720, fps=FPS,
                    has_audio=audio, channels=2)


def _bloco(**campos) -> Clip:
    return Clip(_video(), 0.0, 10.0, **campos)


def _rampa(**campos) -> Clip:
    """Fade-in de 2 s: começa 30 dB abaixo do volume do bloco e chega nele em t = 2 s."""
    return _bloco(keyframes=(Keyframe(0.0, gain_offset_db=-30.0), Keyframe(2.0, gain_offset_db=0.0)), **campos)


class TestInterpolacao:
    def test_o_volume_anda_na_mesma_curva_da_pose(self):
        assert _rampa().gain_at(0.0) == pytest.approx(-30.0)
        assert _rampa().gain_at(1.0) == pytest.approx(-15.0)       # linear: metade do caminho
        assert _rampa().gain_at(2.0) == pytest.approx(0.0)
        assert _rampa().gain_at(7.0) == pytest.approx(0.0), "depois do último ponto, fica nele"

    def test_as_curvas_de_easing_valem_para_o_volume(self):
        suave = _bloco(keyframes=(Keyframe(0.0, gain_offset_db=-30.0),
                                  Keyframe(2.0, gain_offset_db=0.0, easing="ease_in")))
        assert suave.gain_at(1.0) == pytest.approx(-30.0 * (1 - 0.25))   # ease_in: t² = 0,25
        degrau = _bloco(keyframes=(Keyframe(0.0, gain_offset_db=-30.0),
                                   Keyframe(2.0, gain_offset_db=0.0, easing="hold")))
        assert degrau.gain_at(1.9) == pytest.approx(-30.0)

    def test_a_curva_soma_ao_volume_do_bloco(self):
        assert _rampa(gain_db=-6.0).gain_at(0.0) == pytest.approx(-36.0)
        assert _rampa(gain_db=-6.0).gain_at(2.0) == pytest.approx(-6.0)

    def test_o_resultado_respeita_os_limites_do_controle(self):
        assert _rampa(gain_db=-40.0).gain_at(0.0) == MIN_GAIN_DB
        alto = _bloco(gain_db=10.0, keyframes=(Keyframe(0.0, gain_offset_db=6.0), Keyframe(1.0)))
        assert alto.gain_at(0.0) == MAX_GAIN_DB


class TestSemCurva:
    def test_sem_curva_o_volume_e_o_do_bloco_cru(self):
        assert _bloco(gain_db=-80.0).gain_at(3.0) == -80.0, "sem curva nada é limitado: é o valor do arquivo"
        assert not _bloco().animates_gain

    def test_quadro_chave_de_pose_nao_cria_curva(self):
        pose = _bloco(keyframes=(Keyframe(0.0, x=0.2), Keyframe(2.0, x=0.8)), gain_db=-6.0)
        assert not pose.animates_gain
        assert pose.gain_at(1.0) == -6.0

    def test_curva_abaixo_do_limiar_conta_como_sem_curva(self):
        assert not _bloco(keyframes=(Keyframe(0.0, gain_offset_db=0.01), Keyframe(1.0))).animates_gain


class TestQuadrosChaveDaImagem:
    """``has_pose_keyframes``: o compositor escolhe o caminho do vídeo por ele, e não por ``has_keyframes``."""

    def test_projeto_antigo_com_pose_animada(self):
        assert _bloco(keyframes=(Keyframe(0.0, x=0.2), Keyframe(2.0, x=0.8))).has_pose_keyframes

    def test_projeto_antigo_com_quadro_igual_ao_bloco_segue_como_sempre(self):
        # Sem curva de volume é o que sempre foi: existir quadro-chave basta.
        assert _bloco(keyframes=(Keyframe(0.0), Keyframe(2.0))).has_pose_keyframes

    def test_so_volume_nao_mexe_na_imagem(self):
        assert _rampa().has_keyframes and not _rampa().has_pose_keyframes

    def test_volume_e_pose_juntos_mexem_na_imagem(self):
        misto = _bloco(keyframes=(Keyframe(0.0, x=0.2, gain_offset_db=-30.0), Keyframe(2.0, x=0.8)))
        assert misto.has_pose_keyframes and misto.animates_gain


class TestEditarOVolume:
    def test_sem_quadros_chave_muda_o_volume_do_bloco(self):
        editado = _bloco(gain_db=-3.0).with_edited_gain(4.0, -9.0, fps=FPS)
        assert editado.gain_db == -9.0 and not editado.keyframes

    def test_com_quadros_chave_cria_o_ponto_no_instante_com_a_pose_de_agora(self):
        animado = _bloco(gain_db=-6.0, keyframes=(Keyframe(0.0, x=0.2), Keyframe(4.0, x=0.8)))
        editado = animado.with_edited_gain(2.0, -18.0, fps=FPS)
        ponto = next(k for k in editado.keyframes if k.time_offset == pytest.approx(2.0))
        assert ponto.gain_offset_db == pytest.approx(-12.0)          # −18 ouvidos = −6 do bloco + (−12)
        assert ponto.x == pytest.approx(0.5), "a pose do ponto é a que a curva tinha ali"
        assert editado.gain_at(2.0) == pytest.approx(-18.0)
        assert editado.gain_db == -6.0, "o volume do bloco não mexe"

    def test_ponto_no_mesmo_quadro_so_troca_o_volume(self):
        animado = _bloco(keyframes=(Keyframe(0.0, x=0.2, easing="ease_out"), Keyframe(2.0, x=0.8)))
        editado = animado.with_edited_gain(0.0, -12.0, fps=FPS)
        assert len(editado.keyframes) == 2
        primeiro = editado.keyframes[0]
        assert (primeiro.gain_offset_db, primeiro.x, primeiro.easing) == (pytest.approx(-12.0), 0.2, "ease_out")

    def test_editar_a_animacao_inteira_desloca_o_volume_do_bloco_e_deixa_os_pontos(self):
        editado = _rampa().with_edited_gain(1.0, -5.0, fps=FPS, whole_animation=True)
        assert editado.keyframes == _rampa().keyframes
        assert editado.gain_at(1.0) == pytest.approx(-5.0)           # a curva toda sobe 10 dB
        assert editado.gain_at(2.0) == pytest.approx(10.0)

    def test_o_valor_pedido_e_limitado_ao_controle(self):
        assert _bloco().with_edited_gain(0.0, 99.0, fps=FPS).gain_db == MAX_GAIN_DB
        assert _bloco().with_edited_gain(0.0, -99.0, fps=FPS).gain_db == MIN_GAIN_DB


class TestEditarAPoseNaoApagaOVolume:
    """Montar o quadro à mão (sem ``Keyframe.from_pose``) zerava o volume de quem só mexia na posição."""

    def test_mexer_na_posicao_de_um_ponto_preserva_o_volume_dele(self):
        editado = _rampa().with_edited_transform(0.0, {"x": 0.9}, fps=FPS)
        primeiro = editado.keyframes[0]
        assert (primeiro.x, primeiro.gain_offset_db) == (pytest.approx(0.9), pytest.approx(-30.0))

    def test_pose_criada_no_meio_da_rampa_captura_o_volume_interpolado_e_nao_zero(self):
        editado = _rampa().with_edited_transform(1.0, {"x": 0.9}, fps=FPS)
        meio = next(k for k in editado.keyframes if k.time_offset == pytest.approx(1.0))
        assert meio.gain_offset_db == pytest.approx(-15.0)
        assert editado.gain_at(1.0) == pytest.approx(-15.0), "a rampa continua a mesma"

    def test_editar_a_animacao_inteira_nao_mexe_no_volume(self):
        misto = _bloco(keyframes=(Keyframe(0.0, x=0.2, gain_offset_db=-30.0), Keyframe(2.0, x=0.8)))
        editado = misto.with_edited_transform(1.0, {"x": 0.7}, fps=FPS, whole_animation=True)
        assert [k.gain_offset_db for k in editado.keyframes] == [-30.0, 0.0]


def _projeto(clip: Clip) -> Project:
    return Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),))


class TestOperacoesDaLinhaDoTempo:
    def test_dividir_nao_cria_degrau_na_emenda(self):
        clip = _rampa()
        esquerda, direita = sorted(_projeto(clip).split(clip.clip_id, 1.3).tracks[0].clips, key=lambda c: c.start)
        assert esquerda.gain_at(esquerda.duration) == pytest.approx(clip.gain_at(1.3))
        assert direita.gain_at(0.0) == pytest.approx(clip.gain_at(1.3))
        for t in (0.2, 0.9, 1.2):                      # cada metade segue a curva original nos mesmos instantes
            assert esquerda.gain_at(t) == pytest.approx(clip.gain_at(t))
        for t in (1.4, 1.9, 5.0):
            assert direita.gain_at(t - 1.3) == pytest.approx(clip.gain_at(t))

    def test_aparar_o_comeco_mantem_o_volume_nos_mesmos_instantes_da_edicao(self):
        clip = _rampa()
        aparado = _projeto(clip).resized(clip.clip_id, "inicio", 0.5).tracks[0].clips[0]
        assert aparado.start == pytest.approx(0.5)
        for instante in (0.5, 1.0, 1.7, 4.0):
            assert aparado.gain_at(instante - aparado.start) == pytest.approx(clip.gain_at(instante - clip.start))

    def test_mudar_a_velocidade_leva_a_curva_junto_com_o_conteudo(self):
        # O painel reescala os pontos pelo fator da duração (edit_panel._on_speed): o fade de 2 s a 2× dura 1 s.
        clip = _rampa()
        fator = 0.5
        acelerado = replace(clip, speed=2.0, duration=clip.duration * fator,
                            keyframes=tuple(replace(k, time_offset=k.time_offset * fator) for k in clip.keyframes))
        assert acelerado.gain_at(0.5) == pytest.approx(clip.gain_at(1.0))


class TestSepararAudio:
    @staticmethod
    def _separar(clip: Clip):
        projeto = _projeto(clip).detached_audio(clip.clip_id)
        video = next(c for c in projeto.clips if not c.audio_only)
        som = next(c for c in projeto.clips if c.audio_only)
        return video, som

    def test_a_curva_vai_para_o_bloco_de_som_com_o_mesmo_volume_em_todo_instante(self):
        clip = _rampa(gain_db=-4.0)
        _, som = self._separar(clip)
        for t in (0.0, 0.5, 1.0, 1.5, 2.0, 6.0):
            assert som.gain_at(t) == pytest.approx(clip.gain_at(t))
        assert not som.has_pose_keyframes

    def test_o_video_que_so_tinha_curva_de_volume_fica_sem_quadros_chave(self):
        video, _ = self._separar(_rampa())
        assert video.detached and video.keyframes == ()

    def test_o_video_com_pose_animada_fica_com_a_pose_e_sem_volume(self):
        clip = _bloco(keyframes=(Keyframe(0.0, x=0.2, gain_offset_db=-30.0), Keyframe(2.0, x=0.8)))
        video, som = self._separar(clip)
        assert [(k.x, k.gain_offset_db) for k in video.keyframes] == [(0.2, 0.0), (0.8, 0.0)]
        assert som.gain_at(0.0) == pytest.approx(-30.0) and som.gain_at(2.0) == pytest.approx(0.0)

    def test_sem_curva_de_volume_o_video_mantem_os_quadros_chave_de_antes(self):
        clip = _bloco(keyframes=(Keyframe(0.0, x=0.2), Keyframe(2.0, x=0.8)))
        video, som = self._separar(clip)
        assert video.keyframes == clip.keyframes and som.keyframes == ()
