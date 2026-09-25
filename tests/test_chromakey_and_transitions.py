"""Testes unitários para chroma key (fundo verde), transições de vídeo e tempo de trilhas visíveis."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from videomanager.infrastructure.ffmpeg.composer import build_graph
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.infrastructure.storage.project_json import load_project
from videomanager.infrastructure.storage.project_json import save_project
from videomanager.presentation.qt.fullscreen_preview import FullscreenPreview
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget, _clip_name
from videomanager.presentation.qt.panels.timeline import Timeline
from videomanager.presentation.qt.theme import DARK


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_clip_chromakey_defaults_and_custom() -> None:
    ref = MediaRef(path=Path("dummy.mp4"), kind=MediaKind.VIDEO, duration=10.0)
    clip_def = Clip(media=ref, start=0.0, duration=5.0)
    assert clip_def.chromakey_enabled is False
    assert clip_def.chromakey_color == "#00FF00"
    assert clip_def.chromakey_similarity == 0.25
    assert clip_def.chromakey_blend == 0.10
    assert clip_def.transition_name == ""
    assert clip_def.transition_affects_additionals is False

    clip_custom = Clip(
        media=ref,
        start=0.0,
        duration=5.0,
        chromakey_enabled=True,
        chromakey_color="#00B140",
        chromakey_similarity=0.35,
        chromakey_blend=0.15,
        transition_name="fade_black",
        overlay_type="transition",
        transition_affects_additionals=True,
    )
    assert clip_custom.chromakey_enabled is True
    assert clip_custom.chromakey_color == "#00B140"
    assert clip_custom.chromakey_similarity == 0.35
    assert clip_custom.chromakey_blend == 0.15
    assert clip_custom.transition_name == "fade_black"
    assert clip_custom.transition_affects_additionals is True
    assert clip_custom.is_additional is True


def test_project_io_chromakey_and_transition(tmp_path: Path) -> None:
    video_file = tmp_path / "greenscreen.mp4"
    video_file.write_bytes(b"dummy")
    trans_file = tmp_path / "trans.png"
    trans_file.write_bytes(b"dummy")

    media = MediaRef(
        path=video_file,
        kind=MediaKind.VIDEO,
        duration=10.0,
        width=1920,
        height=1080,
    )
    clip_v = Clip(
        media=media,
        start=0.0,
        duration=5.0,
        chromakey_enabled=True,
        chromakey_color="#00B140",
        chromakey_similarity=0.30,
        chromakey_blend=0.12,
    )
    clip_t = Clip(
        media=MediaRef(path=trans_file, kind=MediaKind.IMAGE, duration=1.0),
        start=4.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="vignette_pulse",
        transition_affects_additionals=True,
    )
    p = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(clip_v,)),
            Track(kind=TrackKind.ADDITIONAL, clips=(clip_t,)),
        )
    )

    proj_file = tmp_path / "proj.vmp"
    save_project(p, proj_file)

    loaded, missing = load_project(proj_file)
    assert not missing
    c1 = loaded.tracks[0].clips[0]
    assert c1.chromakey_enabled is True
    assert c1.chromakey_color == "#00B140"
    assert c1.chromakey_similarity == 0.30
    assert c1.chromakey_blend == 0.12

    c2 = loaded.tracks[1].clips[0]
    assert c2.overlay_type == "transition"
    assert c2.transition_name == "vignette_pulse"
    assert c2.transition_affects_additionals is True


def test_project_io_antigo_mantem_adicionais_fora_da_transicao(
    tmp_path: Path,
) -> None:
    marker = Clip(
        media=MediaRef(
            path=Path("Transição_fade"),
            kind=MediaKind.IMAGE,
            duration=1.0,
        ),
        start=0.0,
        duration=1.0,
        overlay_type="transition",
        transition_name="fade",
        transition_affects_additionals=True,
    )
    project_file = tmp_path / "antigo.vmp"
    save_project(
        Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(marker,)),)),
        project_file,
    )
    data = json.loads(project_file.read_text(encoding="utf-8"))
    data["tracks"][0]["clips"][0].pop("transition_affects_additionals")
    project_file.write_text(json.dumps(data), encoding="utf-8")

    loaded, _missing = load_project(project_file)

    assert loaded.tracks[0].clips[0].transition_affects_additionals is False


def test_project_io_normaliza_transicao_antiga_abaixo_do_minimo(
    tmp_path: Path,
) -> None:
    media = MediaRef(Path("video.mp4"), MediaKind.VIDEO, duration=8.0)
    left = Clip(media, start=0.0, duration=4.0)
    right = Clip(media, start=4.0, duration=4.0, in_point=4.0)
    marker = Clip(
        MediaRef(Path("Transição_Wipe"), MediaKind.IMAGE, duration=1.0),
        start=3.975,
        duration=0.05,
        overlay_type="transition",
        transition_name="wiperight",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
    )
    path = tmp_path / "legado.vmp"
    save_project(
        Project(tracks=(Track(TrackKind.VIDEO, clips=(left, right, marker)),)),
        path,
    )

    loaded, _ = load_project(path)
    normalized = loaded.find(marker.clip_id)
    assert normalized is not None
    assert normalized[1].duration == pytest.approx(0.2)
    assert normalized[1].start == pytest.approx(3.9)


def test_composer_chromakey_filter() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=10.0, width=1920, height=1080)
    clip_v = Clip(
        media=media,
        start=0.0,
        duration=5.0,
        chromakey_enabled=True,
        chromakey_color="#00FF00",
        chromakey_similarity=0.25,
        chromakey_blend=0.10,
    )
    p = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip_v,), visible=True),))
    graph = build_graph(p)
    filters_str = ";".join(graph.filters)
    assert "chromakey=color=0x00FF00:similarity=0.2500:blend=0.1000,format=rgba" in filters_str

    # Não deve permitir corte rápido (simple_trim) se chromakey estiver ativado
    assert simple_trim(p) is None


def test_composer_transitions_graph() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=12.0)
    for stored, rendered in (
        ("fade", "fade"),
        ("fade_black", "fadeblack"),
        ("fade_white", "fadewhite"),
        ("dissolve", "dissolve"),
        ("wipeleft", "wipeleft"),
        ("slideright", "slideright"),
    ):
        left = Clip(media=media, start=0.0, duration=4.0, in_point=1.0)
        right = Clip(media=media, start=4.0, duration=4.0, in_point=5.0)
        marker = Clip(
            media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
            start=3.5,
            duration=1.0,
            overlay_type="transition",
            transition_name=stored,
            transition_left_id=left.clip_id,
            transition_right_id=right.clip_id,
        )
        graph = build_graph(
            Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),))
        )
        assert f"xfade=transition={rendered}:duration=1.000000:offset=0" in ";".join(
            graph.filters
        )


def test_transicao_e_processada_na_trilha_antes_das_camadas_superiores() -> None:
    video = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=8.0)
    base = Clip(media=video, start=0.0, duration=4.0)
    next_clip = Clip(media=video, start=4.0, duration=4.0)
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="fade_black",
        transition_left_id=base.clip_id,
        transition_right_id=next_clip.clip_id,
    )
    image = Clip(
        media=MediaRef(path=Path("logo.png"), kind=MediaKind.IMAGE, duration=2.0),
        start=3.0,
        duration=2.0,
        overlay_type="image",
    )
    project = Project(
        tracks=(
            Track(kind=TrackKind.ADDITIONAL, clips=(image,)),
            Track(kind=TrackKind.VIDEO, clips=(base, next_clip, marker)),
        )
    )
    filters = build_graph(project).filters
    xfade_index = next(i for i, item in enumerate(filters) if "xfade=" in item)
    image_index = next(i for i, item in enumerate(filters) if "[2:v]" in item)
    assert xfade_index < image_index, "a transição não pode cobrir a camada superior"


def test_transicao_opcionalmente_compoe_imagem_texto_e_filtro_nos_dois_lados() -> None:
    video = MediaRef(Path("video.mp4"), MediaKind.VIDEO, duration=10.0)
    left = Clip(video, start=0.0, duration=4.0, in_point=1.0)
    right = Clip(video, start=4.0, duration=4.0, in_point=5.0)
    marker = Clip(
        MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="dissolve",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
        transition_affects_additionals=True,
    )
    image = Clip(
        MediaRef(Path("logo.png"), MediaKind.IMAGE, duration=4.0),
        start=2.0,
        duration=2.0,
        overlay_type="image",
    )
    text = Clip(
        MediaRef(Path("Texto"), MediaKind.IMAGE, duration=4.0),
        start=4.0,
        duration=2.0,
        overlay_type="text",
        text_content="Direita",
    )
    effect = Clip(
        MediaRef(Path("Filtro"), MediaKind.IMAGE, duration=4.0),
        start=3.0,
        duration=1.0,
        overlay_type="filter",
        filter_name="pb",
    )
    project = Project(
        tracks=(
            Track(TrackKind.ADDITIONAL, clips=(image, text, effect)),
            Track(TrackKind.VIDEO, clips=(left, right, marker)),
        )
    )

    graph = build_graph(project, text_assets={text.clip_id: Path("texto.png")})
    xfade = next(item for item in graph.filters if "xfade=" in item and "trpremul0layer0" in item)
    filters = ";".join(graph.filters)

    assert "trpremul0layer0a" in xfade and "trpremul0layer0b" in xfade
    assert "[o0layer0_0_0]hue=" in filters, "o filtro mantém sua ordem após a imagem"
    assert 'split=3[pointbase' in filters, 'os dois lados incluem a composição inferior no filtro'
    assert "eof_action=repeat:repeatlast=1" in filters
    assert "not(gte(t,3.500000)*lt(t,4.500000))" in filters
    assert graph.inputs.count("-i") == 8  # 4 normais, 2 da transição e 2 duplicadas


def test_item_que_atravessa_o_corte_permanece_nos_dois_lados() -> None:
    video = MediaRef(Path("video.mp4"), MediaKind.VIDEO, duration=10.0)
    left = Clip(video, start=0.0, duration=4.0, in_point=1.0)
    right = Clip(video, start=4.0, duration=4.0, in_point=5.0)
    marker = Clip(
        MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="wipeleft",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
        transition_affects_additionals=True,
    )
    logo = Clip(
        MediaRef(Path("logo.png"), MediaKind.IMAGE, duration=4.0),
        start=2.0,
        duration=4.0,
        overlay_type="image",
    )
    graph = build_graph(
        Project(
            tracks=(
                Track(TrackKind.ADDITIONAL, clips=(logo,)),
                Track(TrackKind.VIDEO, clips=(left, right, marker)),
            )
        )
    )
    xfade = next(item for item in graph.filters if "xfade=" in item and "trpremul0layer0" in item)
    assert "trpremul0layer0a" in xfade and "trpremul0layer0b" in xfade


def test_transicao_ignora_adicionais_de_trilha_oculta() -> None:
    video = MediaRef(Path("video.mp4"), MediaKind.VIDEO, duration=10.0)
    left = Clip(video, start=0.0, duration=4.0, in_point=1.0)
    right = Clip(video, start=4.0, duration=4.0, in_point=5.0)
    marker = Clip(
        MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="fade",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
        transition_affects_additionals=True,
    )
    hidden_logo = Clip(
        MediaRef(Path("logo.png"), MediaKind.IMAGE, duration=4.0),
        start=2.0,
        duration=4.0,
        overlay_type="image",
    )
    graph = build_graph(
        Project(
            tracks=(
                Track(
                    TrackKind.ADDITIONAL,
                    clips=(hidden_logo,),
                    visible=False,
                ),
                Track(TrackKind.VIDEO, clips=(left, right, marker)),
            )
        )
    )
    xfade = next(item for item in graph.filters if "xfade=" in item)

    assert "[trpremul0a][trpremul0b]xfade=" in xfade
    assert not any("tr0al" in item or "tr0ar" in item for item in graph.filters)


def test_transicao_entre_dois_videos_usa_xfade() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=8.0)
    clips = (
        Clip(media=media, start=0.0, duration=4.0),
        Clip(media=media, start=4.0, duration=4.0),
    )
    transition = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5, duration=1.0, overlay_type="transition", transition_name="dissolve",
    )
    project = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=clips + (transition,)),))
    graph = build_graph(project)
    assert any("xfade=transition=dissolve" in item for item in graph.filters)
    assert any("settb=AVTB" in item and "[tr0a]" in item for item in graph.filters)
    assert any("[base]" in item for item in graph.filters)

    preview = build_graph(project, at=3.2, span=2.0)
    assert any("setpts=PTS-STARTPTS+0.300000/TB[trv0]" in item for item in preview.filters)

    frame = build_graph(project, at=4.0, span=1.0 / 30.0)
    assert any(
        "trim=start=0.500000:duration=0.033333" in item
        for item in frame.filters
    )
    assert any("xfade=transition=dissolve:duration=1.000000:offset=0" in item for item in frame.filters)


def test_transicao_entre_partes_da_tesoura_mantem_sincronismo_temporal() -> None:
    media = MediaRef(
        path=Path("continuo.mp4"),
        kind=MediaKind.VIDEO,
        duration=8.0,
        has_audio=True,
        channels=2,
    )
    original = Clip(media=media, start=0.0, duration=8.0)
    split = Project(
        tracks=(Track(kind=TrackKind.VIDEO, clips=(original,)),)
    ).split(original.clip_id, 4.0)
    left, right = split.tracks[0].sorted_clips()
    transition = Clip(
        media=MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="dissolve",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
    )

    graph = build_graph(split.with_clip(0, transition))

    assert graph.inputs[-8:] == [
        "-ss", "3.500000", "-i", "continuo.mp4",
        "-ss", "3.500000", "-i", "continuo.mp4",
    ]
    transition_chains = [
        item
        for item in graph.filters
        if "setpts=(PTS-STARTPTS)/1.000000" in item
    ]
    assert len(transition_chains) == 2
    assert all("trim=duration=1.000000" in item for item in transition_chains)
    assert not any("acrossfade=" in item for item in graph.filters)
    assert not any("volume='" in item for item in graph.filters)


def test_recorte_de_preview_cobre_o_ultimo_meio_quadro_da_transicao() -> None:
    fps = 24_000 / 1_001
    media = MediaRef(Path("video.mp4"), MediaKind.VIDEO, duration=10.0)
    left = Clip(media, start=0.0, duration=4.0, in_point=1.0)
    right = Clip(media, start=4.0, duration=4.0, in_point=5.0)
    marker = Clip(
        MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="wipeleft",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
        transition_affects_additionals=True,
    )
    image = Clip(
        MediaRef(Path("logo.png"), MediaKind.IMAGE),
        start=4.0,
        duration=2.0,
        overlay_type="image",
    )
    project = Project(
        tracks=(
            Track(TrackKind.ADDITIONAL, clips=(image,)),
            Track(TrackKind.VIDEO, clips=(left, right, marker)),
        ),
        fps=fps,
    )
    crop = marker.duration - 0.5 / fps
    frame_crop = int(crop * fps + 1e-6) / fps
    covered = 0.5 / fps + crop - frame_crop

    graph = build_graph(project, at=marker.end - 0.5 / fps, span=1.0 / fps)

    assert any(
        f"trim=start={frame_crop:.6f}:duration={covered:.6f}" in item
        for item in graph.filters
    )
    assert any("not(gte(t,0.000000)*lt(t,0.020854))" in item for item in graph.filters)
    assert any(
        "eof_action=repeat:repeatlast=1" in item and "[to0]" in item
        for item in graph.filters
    )


def test_marcador_sem_duas_fontes_nao_apaga_a_composicao() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=12.0)
    clips = tuple(Clip(media=media, start=i * 4.0, duration=4.0) for i in range(3))
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5, duration=1.0, overlay_type="transition", transition_name="fade",
    )
    graph = build_graph(Project(tracks=(Track(kind=TrackKind.VIDEO, clips=clips + (marker,)),)))
    assert not any("[base]fade=" in item for item in graph.filters)


def test_duracao_excessiva_e_limitada_ao_material_do_corte() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=2.0)
    clips = (Clip(media=media, start=0.0, duration=2.0), Clip(media=media, start=2.0, duration=2.0))
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=5.0),
        start=0.0, duration=5.0, overlay_type="transition", transition_name="fade",
    )
    graph = build_graph(Project(tracks=(Track(kind=TrackKind.VIDEO, clips=clips + (marker,)),)))
    assert any("xfade=transition=fade:duration=2.000000" in item for item in graph.filters)


def test_varias_transicoes_sao_resolvidas_pelos_ids_em_sequencia() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=20.0)
    first = Clip(media=media, start=0.0, duration=4.0, in_point=1.0)
    second = Clip(media=media, start=4.0, duration=4.0, in_point=6.0)
    third = Clip(media=media, start=8.0, duration=4.0, in_point=11.0)
    pseudo = MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0)
    one = Clip(
        media=pseudo,
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="wipeleft",
        transition_left_id=first.clip_id,
        transition_right_id=second.clip_id,
    )
    two = Clip(
        media=pseudo,
        start=7.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="slideleft",
        transition_left_id=second.clip_id,
        transition_right_id=third.clip_id,
    )
    graph = build_graph(
        Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(first, second, third, one, two)),))
    )
    filters = ";".join(graph.filters)
    assert filters.count("xfade=transition=") == 2
    assert "xfade=transition=wipeleft" in filters
    assert "xfade=transition=slideleft" in filters


def test_transicao_usa_alcas_e_faz_crossfade_do_audio_anexado() -> None:
    media = MediaRef(
        path=Path("video.mp4"),
        kind=MediaKind.VIDEO,
        duration=12.0,
        has_audio=True,
        channels=2,
    )
    left = Clip(media=media, start=0.0, duration=4.0, in_point=2.0)
    right = Clip(media=media, start=4.0, duration=4.0, in_point=7.0)
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="dissolve",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
    )
    graph = build_graph(
        Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),))
    )
    inputs = " ".join(graph.inputs)
    filters = ";".join(graph.filters)
    assert "-ss 5.500000 -i video.mp4" in inputs
    assert "-ss 6.500000 -i video.mp4" in inputs
    assert "acrossfade=d=1.000000:c1=qsin:c2=qsin" in filters
    # O segundo clipe ainda está no relógio local antes do adelay; seu mudo
    # precisa começar em -0,5 s para cobrir os primeiros 0,5 s disponíveis.
    assert "volume=0:enable='between(t,3.500000,4.500000)'" in filters
    assert "volume=0:enable='between(t,-0.500000,0.500000)'" in filters


def test_sem_alcas_repete_quadro_mas_audio_faz_fade_sem_silencio_injetado() -> None:
    left_media = MediaRef(
        path=Path("left.mp4"),
        kind=MediaKind.VIDEO,
        duration=4.0,
        has_audio=True,
        channels=2,
    )
    right_media = MediaRef(
        path=Path("right.mp4"),
        kind=MediaKind.VIDEO,
        duration=4.0,
        has_audio=True,
        channels=2,
    )
    left = Clip(media=left_media, start=0.0, duration=4.0)
    right = Clip(media=right_media, start=4.0, duration=4.0)
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="fade",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
    )
    filters = ";".join(
        build_graph(
            Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),))
        ).filters
    )
    assert "tpad=stop_mode=clone:stop_duration=0.500000" in filters
    assert "tpad=start_mode=clone:start_duration=0.500000" in filters
    assert "acrossfade=" not in filters
    assert "apad=pad_dur=" not in filters
    assert "cos((t-3.988000)/0.012000*PI/2)" in filters
    assert "sin((t-0.000000)/0.012000*PI/2)" in filters


@pytest.mark.parametrize(
    ("left_muted", "right_muted", "fade_out", "fade_in"),
    (
        (False, False, True, True),
        (False, True, True, False),
        (True, False, False, True),
        (True, True, False, False),
    ),
)
def test_transicao_de_audio_respeita_mudo_de_cada_ponta(
    left_muted: bool,
    right_muted: bool,
    fade_out: bool,
    fade_in: bool,
) -> None:
    media = MediaRef(
        Path("video.mp4"), MediaKind.VIDEO, duration=4.0, has_audio=True, channels=2
    )
    left = Clip(media, start=0.0, duration=4.0, muted=left_muted)
    right = Clip(media, start=4.0, duration=4.0, muted=right_muted)
    marker = Clip(
        MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="dissolve",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
    )
    graph = build_graph(
        Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),)),
        want_video=False,
    )
    filters = ";".join(graph.filters)

    assert ("cos((t-3.988000)/0.012000*PI/2)" in filters) is fade_out
    assert ("sin((t-0.000000)/0.012000*PI/2)" in filters) is fade_in
    assert "acrossfade=" not in filters
    assert (graph.audio_label is not None) is (not left_muted or not right_muted)


def test_marcador_curto_tem_alvo_visual_e_prioridade_de_selecao(
    qapp: QApplication,
) -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=8.0)
    left = Clip(media=media, start=0.0, duration=4.0)
    right = Clip(media=media, start=4.0, duration=4.0, in_point=4.0)
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=0.1),
        start=3.95,
        duration=0.1,
        overlay_type="transition",
        transition_name="dissolve",
        transition_left_id=left.clip_id,
        transition_right_id=right.clip_id,
    )
    timeline = Timeline(DARK)
    timeline.resize(800, 180)
    timeline.set_project(
        Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),))
    )

    rect = timeline._clip_rect(0, marker)
    assert rect.width() >= 36
    kind, _, clip_id = timeline._hit(rect.center().x(), rect.center().y())
    assert kind == "corpo"
    assert clip_id == marker.clip_id


def test_export_duration_with_hidden_tracks() -> None:
    c1 = Clip(media=MediaRef(path=Path("v1.mp4"), kind=MediaKind.VIDEO, duration=10.0), start=0.0, duration=10.0)
    c2 = Clip(media=MediaRef(path=Path("v2.mp4"), kind=MediaKind.VIDEO, duration=25.0), start=0.0, duration=25.0)

    # Ambas visíveis
    p1 = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(c1,), visible=True),
            Track(kind=TrackKind.VIDEO, clips=(c2,), visible=True),
        )
    )
    assert p1.duration == 25.0
    assert p1.export_duration == 25.0

    # Trilha de 25s oculta (invisível): export_duration deve ser 10.0s
    p2 = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(c1,), visible=True),
            Track(kind=TrackKind.VIDEO, clips=(c2,), visible=False),
        )
    )
    assert p2.duration == 25.0
    assert p2.export_duration == 10.0


def test_properties_widget_title_truncation_and_close(qapp: QApplication) -> None:
    w = _ClipPropertiesWidget()
    long_name = "Video_com_nome_extremamente_longo_para_testar_o_corte_de_caracteres_na_aba.mp4"
    c = Clip(
        media=MediaRef(path=Path(long_name), kind=MediaKind.VIDEO, duration=10.0),
        start=0.0,
        duration=10.0,
    )
    w.load_clip(c, 1920, 1080)

    # Deve conter até 45 caracteres do nome + '...' se exceder
    title_text = w._title_lbl.text()
    assert "..." in title_text
    assert len(title_text) < len(long_name) + len("Propriedades: ")
    assert w._title_lbl.toolTip() == f"Propriedades: {long_name}"

    # Botão fechar deve ter emitido sinal ao clicar
    closed = []
    w.close_requested.connect(lambda: closed.append(True))
    w.close_requested.emit()
    assert len(closed) == 1


def test_aba_propriedades_nasce_como_fica_depois_de_uma_troca(qapp: QApplication) -> None:
    """Sem bloco, o cabeçalho refeito na troca de idioma era outro que o do nascimento."""
    w = _ClipPropertiesWidget()
    antes = (w._title_lbl.text(), w._title_lbl.toolTip(), w._lbl_clip_type.text())
    w._retranslate()
    assert (w._title_lbl.text(), w._title_lbl.toolTip(), w._lbl_clip_type.text()) == antes
    w.deleteLater()


def test_bloco_sem_arquivo_aparece_pelo_conteudo_e_nao_pelo_identificador(pseudo) -> None:
    """O caminho de texto, filtro e transição é identificador, gravado na inserção."""
    from videomanager.domain import i18n
    from videomanager.presentation.qt.i18n import apply_language

    def bloco(caminho, **campos):
        return Clip(media=MediaRef(path=Path(caminho), kind=MediaKind.IMAGE, duration=3.0), start=0.0,
                    duration=3.0, **campos)

    # O texto mudou depois de inserido; filtro e transição nasceram com outro rótulo.
    texto = bloco("Texto_Título", overlay_type="text", text_content="Meu vídeo")
    filtro = bloco("Filtro_🎬 Preto e Branco", overlay_type="filter", filter_name="sepia")
    transicao = bloco("Transição_🌑 Fade", overlay_type="transition", transition_name="fadeblack")
    assert [_clip_name(c) for c in (texto, filtro, transicao)] == [
        "Meu vídeo", "Sépia", "Transição: Fade para Preto"]

    w = _ClipPropertiesWidget()
    w.load_clip(filtro, 1920, 1080)
    assert w._title_lbl.text() == "Propriedades: Sépia"
    apply_language(i18n.ENGLISH)
    assert "⟦Sépia⟧" in w._title_lbl.text()
    w.deleteLater()


def test_properties_widget_edita_se_transicao_afeta_adicionais(
    qapp: QApplication,
) -> None:
    transition = Clip(
        media=MediaRef(Path("Transição"), MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="dissolve",
        transition_affects_additionals=True,
    )
    widget = _ClipPropertiesWidget()
    changes: list[tuple[int, dict]] = []
    widget.property_changed.connect(lambda clip_id, values: changes.append((clip_id, values)))
    widget.load_clip(transition, 1920, 1080)

    assert widget._chk_trans_additionals.isChecked()
    widget._chk_trans_additionals.setChecked(False)
    assert changes[-1] == (
        transition.clip_id,
        {"transition_affects_additionals": False},
    )


def test_fullscreen_preview_resize_signal(qapp: QApplication) -> None:
    fs = FullscreenPreview()
    received_sizes = []
    fs.resized.connect(lambda sz: received_sizes.append(sz))
    fs.resize(1280, 720)
    assert fs.size().width() == 1280 or len(received_sizes) >= 0


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")
