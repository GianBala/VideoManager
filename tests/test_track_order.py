"""Ordem livre das trilhas: a posição na pilha decide quem aparece por cima.

Antes a ordem era fixa — adicionais, depois vídeos, depois áudios — e o
cabeçalho só podia ser arrastado entre trilhas da mesma espécie. O compositor já
empilhava pela posição; o que prendia a ordem era a interface e a inserção.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind

VIDEO = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=10, width=160, height=120, fps=25)


def _names(project: Project) -> list[str]:
    return [track.name for track in project.tracks]


class TestInsercao:
    def _misturado(self) -> Project:
        return Project(tracks=(Track(TrackKind.ADDITIONAL, name="A1"), Track(TrackKind.AUDIO, name="S1"),
                               Track(TrackKind.VIDEO, name="V1"), Track(TrackKind.VIDEO, name="V2")))

    def test_video_novo_entra_acima_do_video_mais_alto(self) -> None:
        project = self._misturado().with_track(TrackKind.VIDEO, name="novo")
        assert _names(project) == ["A1", "S1", "novo", "V1", "V2"]

    def test_sem_video_entra_antes_do_primeiro_audio(self) -> None:
        project = Project(tracks=(Track(TrackKind.ADDITIONAL, name="A1"), Track(TrackKind.AUDIO, name="S1")))
        assert _names(project.with_track(TrackKind.VIDEO, name="novo")) == ["A1", "novo", "S1"]

    def test_adicionais_no_topo_e_audio_no_fim(self) -> None:
        project = self._misturado().with_track(TrackKind.ADDITIONAL, name="A0").with_track(TrackKind.AUDIO, name="S9")
        assert _names(project)[0] == "A0" and _names(project)[-1] == "S9"


def test_cabecalho_pode_ir_para_qualquer_posicao(desktop_app) -> None:
    from videomanager.presentation.qt.panels.timeline import Timeline
    from videomanager.presentation.qt.theme import DARK

    timeline = Timeline(DARK)
    timeline.set_project(Project(tracks=(Track(TrackKind.ADDITIONAL), Track(TrackKind.VIDEO), Track(TrackKind.AUDIO))))
    timeline.resize(900, 400)
    timeline._drag_track = 2  # áudio
    assert timeline._target_reorder_track(timeline._lane_rect(0).center().y()) == 0
    timeline._drag_track = 0  # adicionais
    assert timeline._target_reorder_track(timeline._lane_rect(2).center().y()) == 2
    assert timeline._target_reorder_track(timeline.height() - 1) == 2


def _transicao(affects: bool = True):
    left, right = Clip(VIDEO, 0, 4, in_point=1), Clip(VIDEO, 4, 4, in_point=5)
    marker = Clip(MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1), 3.5, 1, overlay_type="transition",
                  transition_name="dissolve", transition_left_id=left.clip_id, transition_right_id=right.clip_id,
                  transition_affects_additionals=affects)
    text = Clip(MediaRef(Path("Texto"), MediaKind.IMAGE), 2, 4, overlay_type="text", text_content="Oi")
    return Track(TrackKind.VIDEO, clips=(left, right, marker)), Track(TrackKind.ADDITIONAL, clips=(text,))


@pytest.mark.parametrize("above", [True, False])
def test_transicao_so_leva_adicionais_que_estao_acima_dela(above) -> None:
    from videomanager.infrastructure.ffmpeg.composer import _transition_additional_pieces

    video, extras = _transicao()
    project = Project(tracks=(extras, video) if above else (video, extras))
    context = project.transition_contexts()[0]
    left, _ = _transition_additional_pieces(project, context, "left", 0)
    assert bool(left) is above


@pytest.mark.ffmpeg
@pytest.mark.parametrize(("filter_above", "gray"), [(True, True), (False, False)])
def test_filtro_abaixo_do_video_nao_o_afeta(tmp_path, filter_above, gray) -> None:
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    from videomanager.domain.project import media_ref

    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")
    source = tmp_path / "blue.mp4"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x120:r=25:d=2", "-c:v", "libx264", str(source)],
                   check=True, timeout=30, **subprocess_kwargs())
    video = Track(TrackKind.VIDEO, clips=(Clip(media_ref(probe_file(source, tools)), 0, 2),))
    effect = Track(TrackKind.ADDITIONAL, clips=(Clip(MediaRef(Path("Filtro"), MediaKind.IMAGE), 0, 2,
                                                     overlay_type="filter", filter_name="pb"),))
    project = Project(tracks=(effect, video) if filter_above else (video, effect), width=160, height=120, fps=25)
    frame = frame_from_command(frame_command(project, .5, (160, 120), tools), (160, 120))
    assert frame is not None and frame.is_complete
    r, g, b = frame.data[(60 * 160 + 80) * 3:(60 * 160 + 80) * 3 + 3]
    if gray:
        assert abs(r - b) < 20
    else:
        assert b > 200 and r < 60
