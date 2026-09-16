"""REG-R03: stream copy não pode descartar alterações da timeline."""
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.export_policy import simple_trim
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import MediaKind, MediaRef, new_project


@pytest.mark.parametrize('changes', [
    {'speed': 2}, {'speed': .5}, {'opacity': .5}, {'start': 1},
    {'keyframes': (Keyframe(time_offset=0, x=.2),)},
    {'x': .5005}, {'scale_x': 1.0005}, {'rotation': .05},
])
def test_corte_direto_recusa_edicao_nao_representavel(changes):
    media = MediaRef(Path('/video.mp4'), MediaKind.VIDEO, duration=10, width=640, height=360, fps=30)
    project = new_project(media)
    original = project.clips[0]
    assert simple_trim(project) is not None
    assert simple_trim(project.with_updated_clip(original.clip_id, **changes)) is None


def test_corte_direto_preserva_lacunas_e_recusa_sobreposicoes():
    media = MediaRef(Path('/video.mp4'), MediaKind.VIDEO, duration=10, width=640, height=360, fps=30)
    project = new_project(media)
    first = replace(project.clips[0], duration=2)
    for start in (1, 3):
        second = replace(first, start=start, in_point=4, clip_id=999)
        track = replace(project.tracks[0], clips=(first, second))
        assert simple_trim(replace(project, tracks=(track,))) is None
