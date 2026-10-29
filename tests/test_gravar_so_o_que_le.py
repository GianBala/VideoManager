"""O programa nunca grava um projeto que ele mesmo não consegue abrir.

O arquivo saía com ``in_point`` negativo (resto de ponto flutuante) e o leitor o recusava ao reabrir: a perda só aparecia
quando o projeto já não estava na tela. Gravar valida o que vai para o disco com a mesma regra da leitura.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.application.errors import ProjectError
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, TrackKind
from videomanager.infrastructure.storage.project_json import load_project, save_project

MIDIA = MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=20.0, width=1920, height=1080, fps=30.0, has_audio=True)


def _projeto(**bloco) -> tuple[Project, Clip]:
    clip = Clip(MIDIA, 3.727, 2.0, **bloco)
    return Project(tracks=(), width=1920, height=1080, fps=30.0).with_track(TrackKind.VIDEO).with_clip(0, clip), clip


def test_o_projeto_com_a_ponta_puxada_ate_o_comeco_da_midia_grava_e_reabre(tmp_path):
    projeto, clip = _projeto(in_point=2.86, speed=2.0)
    projeto = projeto.resized(clip.clip_id, "inicio", 0.0)
    destino = tmp_path / "p.vmp"
    save_project(projeto, destino)
    reaberto, _ = load_project(destino)
    assert reaberto.tracks[0].clips[0].in_point == 0.0


def test_um_valor_que_o_leitor_recusaria_nao_chega_ao_disco(tmp_path):
    projeto, clip = _projeto(in_point=1.0)
    object.__setattr__(projeto.tracks[0].clips[0], "in_point", -0.5)   # o que nenhuma conta honesta deveria produzir
    destino = tmp_path / "p.vmp"
    with pytest.raises(ProjectError) as erro:
        save_project(projeto, destino)
    assert "in_point" in str(erro.value)
    assert not destino.exists()
    assert list(tmp_path.iterdir()) == []   # nem o temporário
