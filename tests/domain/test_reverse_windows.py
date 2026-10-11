"""Em quantas janelas o bloco invertido é lido — o que limita a memória.

O ``reverse`` guarda todos os quadros do trecho que lê e não há como limitá-lo
num processo só (medido: cinco pedaços de 4 s no mesmo grafo gastaram mais que um
de 20 s). A saída são janelas lidas por processos em sequência, e é este
planejador que decide onde cortar. Os números abaixo se conferem de cabeça: em
1080p a 30 q/s o orçamento de 1 GiB dá 5,73 s por janela.
"""
import math
from pathlib import Path

import pytest

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.domain.render_cost import reverse_cuts
from videomanager.domain.reversal import MAX_REVERSE_BYTES, PREVIEW_WINDOW_SECONDS

FPS = 30.0
STEP = 1.0 / FPS


def _media(width=1920, height=1080, duration=600.0, audio=True):
    return MediaRef(Path("/m/v.mp4"), MediaKind.VIDEO, duration=duration, width=width, height=height,
                    fps=FPS, has_audio=audio, channels=2)


def _projeto(*faixas):
    return Project(tracks=tuple(Track(TrackKind.VIDEO, clips=tuple(clips)) for clips in faixas),
                   width=1920, height=1080, fps=FPS)


def _janelas(cuts, start, end):
    edges = (start, *cuts, end)
    return [b - a for a, b in zip(edges, edges[1:])]


def test_sem_bloco_invertido_um_processo_so():
    assert reverse_cuts(_projeto([Clip(_media(), 0.0, 120.0)]), 0.0, 120.0) == ()


def test_bloco_invertido_curto_cabe_numa_janela():
    assert reverse_cuts(_projeto([Clip(_media(), 0.0, 5.0, reversed=True)]), 0.0, 5.0) == ()


def test_bloco_longo_vira_janelas_que_cabem_no_orcamento():
    projeto = _projeto([Clip(_media(), 0.0, 60.0, reversed=True)])
    cortes = reverse_cuts(projeto, 0.0, 60.0)
    janelas = _janelas(cortes, 0.0, 60.0)
    assert len(janelas) == 11
    assert all(j == pytest.approx(5.7333, abs=1e-3) for j in janelas[:-1])
    assert sum(janelas) == pytest.approx(60.0)
    taxa = 1920 * 1080 * 3 * FPS
    assert all(j * taxa <= MAX_REVERSE_BYTES + 1 for j in janelas)


def test_os_cortes_caem_na_grade_de_quadros():
    cortes = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True)]), 0.0, 60.0)
    assert all(abs(c / STEP - round(c / STEP)) < 1e-6 for c in cortes)


def test_cortes_a_partir_de_um_instante_contam_dele():
    cortes = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True)]), 10.3, 60.0)
    assert cortes[0] == pytest.approx(10.3 + 172 * STEP)
    assert all(abs((c - 10.3) / STEP - round((c - 10.3) / STEP)) < 1e-6 for c in cortes)


def test_quadro_maior_encurta_a_janela():
    quatro_k = _projeto([Clip(_media(3840, 2160), 0.0, 10.0, reversed=True)])
    assert _janelas(reverse_cuts(quatro_k, 0.0, 10.0), 0.0, 10.0)[0] == pytest.approx(1.4333, abs=1e-3)


def test_velocidade_dobrada_pesa_o_dobro_por_segundo_de_edicao():
    normal = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True)]), 0.0, 60.0)
    dobro = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True, speed=2.0)]), 0.0, 60.0)
    assert (dobro[0] - 0.0) == pytest.approx((normal[0] - 0.0) / 2, abs=STEP)


def test_blocos_invertidos_simultaneos_somam_a_memoria():
    sozinho = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True)]), 0.0, 60.0)
    dois = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True)],
                                 [Clip(_media(), 0.0, 60.0, reversed=True)]), 0.0, 60.0)
    assert dois[0] == pytest.approx(sozinho[0] / 2, abs=STEP)


def test_blocos_invertidos_em_sequencia_nao_somam():
    """Um depois do outro só um vive por vez: a janela não encolhe."""
    sequencia = _projeto([Clip(_media(), 0.0, 30.0, reversed=True), Clip(_media(), 30.0, 30.0, reversed=True)])
    sozinho = reverse_cuts(_projeto([Clip(_media(), 0.0, 60.0, reversed=True)]), 0.0, 60.0)
    assert reverse_cuts(sequencia, 0.0, 60.0)[0] == pytest.approx(sozinho[0])


def test_pula_o_trecho_sem_bloco_invertido():
    """Só o fim é invertido: cortar a cada janela nos cem segundos de antes abriria processos à toa."""
    projeto = _projeto([Clip(_media(), 0.0, 100.0), Clip(_media(), 100.0, 20.0, reversed=True)])
    cortes = reverse_cuts(projeto, 0.0, 120.0)
    assert cortes[0] == pytest.approx(100.0)
    assert len(cortes) == 4  # 100, e mais três janelas de 5,73 s dentro dos 20 s


def test_depois_do_ultimo_invertido_nao_ha_mais_cortes():
    projeto = _projeto([Clip(_media(), 0.0, 20.0, reversed=True), Clip(_media(), 20.0, 400.0)])
    assert reverse_cuts(projeto, 0.0, 420.0)[-1] < 20.0 + 1e-6


def test_previa_pede_janela_curta_e_metade_do_orcamento():
    projeto = _projeto([Clip(_media(640, 360), 0.0, 120.0, reversed=True)])
    cortes = reverse_cuts(projeto, 0.0, 120.0, window=PREVIEW_WINDOW_SECONDS, budget=MAX_REVERSE_BYTES // 2)
    assert _janelas(cortes, 0.0, 120.0)[0] == pytest.approx(PREVIEW_WINDOW_SECONDS, abs=STEP)
    # E num quadro grande, a memória manda e a janela é menor que a da latência.
    grande = _projeto([Clip(_media(1920, 1080), 0.0, 120.0, reversed=True)])
    cortes = reverse_cuts(grande, 0.0, 120.0, window=PREVIEW_WINDOW_SECONDS, budget=MAX_REVERSE_BYTES // 2)
    assert _janelas(cortes, 0.0, 120.0)[0] == pytest.approx(2.8667, abs=1e-3)


def test_som_invertido_so_pede_janela_curta_na_previa():
    projeto = _projeto([Clip(_media(), 0.0, 60.0, reversed=True)])
    assert reverse_cuts(projeto, 0.0, 60.0, media="audio") == ()
    cortes = reverse_cuts(projeto, 0.0, 60.0, media="audio", window=PREVIEW_WINDOW_SECONDS)
    assert _janelas(cortes, 0.0, 60.0)[0] == pytest.approx(PREVIEW_WINDOW_SECONDS, abs=STEP)


def test_bloco_mudo_ou_de_trilha_oculta_nao_conta():
    invertido = Clip(_media(), 0.0, 60.0, reversed=True)
    oculta = Project(tracks=(Track(TrackKind.VIDEO, clips=(invertido,), visible=False),), fps=FPS)
    assert reverse_cuts(oculta, 0.0, 60.0) == ()
    muda = Project(tracks=(Track(TrackKind.VIDEO, clips=(invertido,), muted=True),), fps=FPS)
    assert reverse_cuts(muda, 0.0, 60.0, media="audio", window=8.0) == ()
    assert reverse_cuts(muda, 0.0, 60.0) != ()  # a imagem de uma trilha muda ainda aparece


def test_tamanho_do_quadro_desconhecido_usa_a_janela_minima():
    projeto = _projeto([Clip(_media(width=None, height=None), 0.0, 10.0, reversed=True)])
    assert _janelas(reverse_cuts(projeto, 0.0, 10.0), 0.0, 10.0)[0] == pytest.approx(1.0, abs=STEP)


def test_o_planejador_termina_e_cobre_tudo():
    """Qualquer combinação termina, com janelas positivas que somam o intervalo."""
    mistura = _projeto(
        [Clip(_media(), 0.0, 40.0, reversed=True), Clip(_media(3840, 2160), 45.0, 30.0, reversed=True)],
        [Clip(_media(1280, 720), 10.0, 70.0, reversed=True, speed=1.5)],
    )
    for janela, orcamento in ((None, MAX_REVERSE_BYTES), (8.0, MAX_REVERSE_BYTES // 2)):
        cortes = reverse_cuts(mistura, 0.0, 80.0, window=janela, budget=orcamento)
        janelas = _janelas(cortes, 0.0, 80.0)
        assert all(j > 0 for j in janelas) and sum(janelas) == pytest.approx(80.0)
        assert list(cortes) == sorted(cortes)
        assert not any(math.isnan(c) for c in cortes)


def test_invertido_pequeno_depois_de_um_trecho_normal_nao_gera_corte():
    """Os pulos até o bloco só valem quando há janelas: o que cabe numa fica num processo só."""
    projeto = _projeto([Clip(_media(), 0.0, 100.0), Clip(_media(), 100.0, 3.0, reversed=True)])
    assert reverse_cuts(projeto, 0.0, 103.0) == ()


def test_intervalo_que_nao_cai_na_grade_nao_ganha_corte_a_toa():
    """Um fim de 1,49 s não é múltiplo de quadro: arredondar para baixo não pode inventar um corte."""
    projeto = _projeto([Clip(_media(640, 360), 0.0, 4.0, reversed=True)])
    assert reverse_cuts(projeto, 2.51, 4.0, window=PREVIEW_WINDOW_SECONDS, budget=MAX_REVERSE_BYTES // 2) == ()
