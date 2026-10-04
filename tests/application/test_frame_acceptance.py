"""Política de aceitação de quadros da prévia (``accept_frame``).

Antes ela só existia dentro do ``EditPanel._on_frame`` e só se testava com o
painel aberto. Cada caso aqui é uma regra que já foi defeito: a tela voltar no
tempo, mostrar um projeto velho, esconder o quadro do loop.
"""

from dataclasses import replace

from videomanager.application.media.preview import FrameContext, PreviewResultKey, accept_frame

TAMANHO = (640, 360)


def chave(token=7, revision=3, seconds=2.0, generation=1):
    return PreviewResultKey(token=token, generation=generation, revision=revision, seconds=seconds,
                            size=TAMANHO, fps=30.0)


def contexto(**mudancas):
    base = FrameContext(
        playing=False, play_token=0, loop_token=0, loop_video_live=False, playback_current=True,
        frame_key=chave(), frame_token=7, frame_revision=3, generation=1, preview_size=TAMANHO,
        gesture=False, interaction_visible=False, cache_shown_for=None, wanted=2.0, presented=None,
    )
    return replace(base, **mudancas)


def test_quadro_pedido_entra_e_e_o_atual():
    veredito = accept_frame(7, contexto())
    assert veredito.show and veredito.current and veredito.presented == chave()


def test_revisao_antiga_fora_de_gesto_nao_entra():
    assert not accept_frame(7, contexto(frame_revision=4)).show


def test_revisao_antiga_entra_durante_gesto_sem_ser_atual():
    veredito = accept_frame(7, contexto(frame_revision=4, gesture=True))
    assert veredito.show and not veredito.current and veredito.gesture


def test_revisao_antiga_nao_volta_a_pose_que_as_camadas_ja_mostram():
    assert not accept_frame(7, contexto(frame_revision=4, gesture=True, interaction_visible=True)).show


def test_arrasto_da_agulha_mostra_o_instante_anterior_sem_dizer_que_e_o_atual():
    veredito = accept_frame(7, contexto(wanted=2.5))
    assert veredito.show and not veredito.current


def test_quadro_exato_mais_velho_que_o_guardado_em_tela_nao_volta_no_tempo():
    assert not accept_frame(7, contexto(wanted=2.5, cache_shown_for=2.5)).show


def test_revisao_ja_superada_na_tela_nao_e_apresentada():
    assert not accept_frame(7, contexto(gesture=True, presented=chave(revision=5))).show


def test_outro_tamanho_outra_geracao_ou_reproducao_nao_entram():
    for mudanca in ({"preview_size": (320, 180)}, {"generation": 2}, {"playing": True}):
        assert not accept_frame(7, contexto(**mudanca)).show


def test_reproducao_entra_e_diz_se_veio_do_projeto_em_tela():
    veredito = accept_frame(9, contexto(playing=True, play_token=9, playback_current=False))
    assert veredito.show and not veredito.current


def test_quadro_do_loop_entra_antes_da_troca_de_dono_e_o_fluxo_antigo_cede():
    loop = accept_frame(11, contexto(playing=True, play_token=9, loop_token=11))
    assert loop.show and loop.loop_frame
    assert not accept_frame(9, contexto(playing=True, play_token=9, loop_token=11, loop_video_live=True)).show


def test_sem_chave_vale_o_token():
    assert accept_frame(7, contexto(frame_key=None)).show
    assert not accept_frame(8, contexto(frame_key=None)).show
