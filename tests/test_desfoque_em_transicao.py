"""O desfoque dentro da janela de uma transição que afeta os adicionais, e o aviso de exportação que ele pede.

No ffmpeg anterior ao 7 o agendamento interno mudou: o ramo do adicional de uma transição que atravessa um filtro
fica sem quadros e some durante a passagem (``tests/test_editor_media_integration.py``). Para quem usa o desfoque
para esconder algo, isso é a área escondida aparecendo; por isso a exportação avisa. Quem decide **se** o desfoque
cai nessa janela é ``region_blur_in_affecting_transition``, que repete o roteamento do compositor, e o teste de
concordância abaixo garante que as duas contas não se separem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.domain.export_policy import region_blur_in_affecting_transition
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import OverlayType
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import filter_pose
from videomanager.domain.project import pseudo_media
from videomanager.infrastructure.ffmpeg import composer

VIDEO = MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=4.0, width=320, height=180, fps=30.0)


def _projeto(*, afeta: bool = True, inicio: float = 1.0, duracao: float = 2.0, filtro: str = "desfoque",
             adicional_abaixo: bool = False, visivel: bool = True) -> Project:
    """Dois vídeos com uma transição de 1 s no corte de 2 s (janela de 1,5 s a 2,5 s) e um filtro numa trilha de adicionais."""
    esquerda, direita = Clip(VIDEO, 0.0, 2.0), Clip(VIDEO, 2.0, 2.0)
    marca = Clip(pseudo_media(OverlayType.TRANSITION, "T", 1.0), 1.5, 1.0, overlay_type="transition",
                 transition_name="dissolve", transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id,
                 transition_affects_additionals=afeta)
    pose = filter_pose(filtro) if filtro == "desfoque" else {}
    bloco = Clip(pseudo_media(OverlayType.FILTER, filtro, duracao), inicio, duracao, overlay_type="filter",
                 filter_name=filtro, **pose)
    adicional = Track(TrackKind.ADDITIONAL, clips=(bloco,), name="A", visible=visivel)
    video = Track(TrackKind.VIDEO, clips=(esquerda, marca, direita), name="V")
    return Project(tracks=(video, adicional) if adicional_abaixo else (adicional, video), width=320, height=180, fps=30.0)


CASOS = {
    "atravessa a janela": (dict(), True),
    "termina dentro da janela": (dict(inicio=0.5, duracao=1.5), True),
    "começa dentro da janela": (dict(inicio=2.2, duracao=1.0), True),
    "a transição não afeta os adicionais": (dict(afeta=False), False),
    "termina antes da janela": (dict(inicio=0.0, duracao=1.5), False),
    "começa depois da janela": (dict(inicio=2.5, duracao=1.0), False),
    "a trilha dele está abaixo da transição": (dict(adicional_abaixo=True), False),
    "a trilha está oculta": (dict(visivel=False), False),
    "é outro filtro": (dict(filtro="sepia"), False),
}


@pytest.mark.parametrize("nome", CASOS)
def test_o_desfoque_na_janela_de_uma_transicao_que_afeta_adicionais(nome):
    parametros, esperado = CASOS[nome]
    assert region_blur_in_affecting_transition(_projeto(**parametros)) is esperado


@pytest.mark.parametrize("nome", CASOS)
def test_a_conta_do_dominio_concorda_com_o_roteamento_do_compositor(nome):
    """O compositor só leva o filtro para dentro da transição se ela afeta adicionais e se ele a atravessa."""
    parametros, _ = CASOS[nome]
    projeto = _projeto(**parametros)
    renderizado = projeto.for_render()
    roteado = any(
        piece.clip.has_region
        for contexto in renderizado.transition_contexts() if contexto.marker.transition_affects_additionals
        for lado in ("left", "right")
        for piece in composer._transition_additional_pieces(renderizado, contexto, lado, 0)[0])
    assert region_blur_in_affecting_transition(projeto) is roteado
