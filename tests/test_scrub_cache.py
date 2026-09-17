"""Cache de quadros para a agulha arrastada: assinatura, memória e preenchimento."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.application.media.scrub import ScrubFrameCache
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.domain.scrub import render_signature, signature_at, signature_segments

VIDEO = MediaRef(Path("/m/v.mp4"), MediaKind.VIDEO, duration=30, width=320, height=180, fps=30)
SOM = MediaRef(Path("/m/s.mp3"), MediaKind.AUDIO, duration=30, has_audio=True, channels=2)
TEXTO = MediaRef(Path("Texto"), MediaKind.IMAGE)


def _project() -> Project:
    a, b = Clip(VIDEO, 0, 5), Clip(VIDEO, 5, 5, in_point=5)
    title = Clip(TEXTO, 2, 2, overlay_type="text", text_content="Oi")
    return Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(title,)),
                           Track(TrackKind.VIDEO, clips=(a, b)),
                           Track(TrackKind.AUDIO, clips=(Clip(SOM, 0, 10),))), width=320, height=180, fps=30)


class TestAssinatura:
    def test_editar_um_bloco_so_muda_onde_ele_aparece(self) -> None:
        project = _project()
        title = project.tracks[0].clips[0]
        edited = project.with_updated_clip(title.clip_id, text_content="Tchau")
        assert render_signature(project, 3) != render_signature(edited, 3)
        assert render_signature(project, 7) == render_signature(edited, 7)

    def test_mover_um_bloco_muda_onde_ele_estava_e_onde_chegou(self) -> None:
        project = _project()
        title = project.tracks[0].clips[0]
        moved = project.with_updated_clip(title.clip_id, start=7)
        assert render_signature(project, 3) != render_signature(moved, 3)
        assert render_signature(project, 8) != render_signature(moved, 8)
        assert render_signature(project, 1) == render_signature(moved, 1)

    def test_audio_e_trilha_oculta_nao_mudam_a_imagem(self) -> None:
        project = _project()
        louder = project.with_updated_clip(project.tracks[2].clips[0].clip_id, gain_db=6)
        assert render_signature(project, 3) == render_signature(louder, 3)
        hidden = project.with_track_visible(0, False)
        video = project.tracks[1].sorted_clips()[0]
        # Com o título oculto, só a camada do vídeo compõe o instante.
        assert render_signature(hidden, 3)[5] == ((video,),)
        assert render_signature(hidden, 3) != render_signature(project, 3)

    def test_ordem_das_camadas_entra(self) -> None:
        project = _project()
        swapped = project.reordered_track(0, 1)
        assert render_signature(project, 3) != render_signature(swapped, 3)

    def test_transicao_liga_os_dois_lados_na_janela(self) -> None:
        project = _project()
        a, b = project.tracks[1].sorted_clips()
        marker = Clip(TEXTO, 4.5, 1, overlay_type="transition", transition_name="fade",
                      transition_left_id=a.clip_id, transition_right_id=b.clip_id)
        with_transition = project.with_clip(1, marker)
        right_changed = with_transition.with_updated_clip(b.clip_id, opacity=.5)
        # 4,7 s ainda é o bloco da esquerda, mas a transição mistura o da direita.
        assert render_signature(with_transition, 4.7) != render_signature(right_changed, 4.7)
        assert render_signature(with_transition, 3.0) == render_signature(right_changed, 3.0)

    def test_trechos_batem_com_a_assinatura_de_cada_instante(self) -> None:
        project = _project()
        segments = signature_segments(project, 0, 10)
        for index in range(0, 300):
            seconds = index / 30
            assert signature_at(segments, seconds) == render_signature(project, seconds), seconds


class TestCache:
    def test_quadro_valido_volta_e_o_de_outra_composicao_sai(self) -> None:
        cache = ScrubFrameCache(30, (320, 180), 10_000)
        cache.put(90, ("a",), b"x" * 100, focus_index=90)
        assert cache.get(90, ("a",)) == b"x" * 100
        assert cache.get(90, ("b",)) is None
        assert len(cache) == 0 and cache.bytes_used == 0

    def test_passando_do_teto_saem_os_mais_distantes_da_agulha(self) -> None:
        cache = ScrubFrameCache(30, (320, 180), 350)
        for index in (0, 10, 20, 30):
            cache.put(index, ("s",), b"x" * 100, focus_index=10)
        assert sorted(cache._frames) == [0, 10, 20]
        assert cache.bytes_used == 300

    def test_indice_e_o_quadro_na_tela(self) -> None:
        cache = ScrubFrameCache(30, (320, 180), 1)
        assert cache.index_of(1.0) == 30 and cache.index_of(1.0 - 1e-9) == 30
        assert cache.index_of(1.02) == 30 and cache.index_of(1.034) == 31

    def test_faltantes_e_obsoletos_apos_edicao(self) -> None:
        project = _project()
        cache = ScrubFrameCache(30, (320, 180), 10**9)
        segments = signature_segments(project, 0, 10)
        for index in range(300):
            cache.put(index, signature_at(segments, index / 30), b"j", focus_index=0)
        assert cache.missing(segments, 0, 300) == []
        title = project.tracks[0].clips[0]
        edited = project.with_updated_clip(title.clip_id, text_content="Tchau")
        new_segments = signature_segments(edited, 0, 10)
        assert cache.missing(new_segments, 0, 300) == [(60, 120)]
        assert cache.discard_stale(new_segments) == 60
        assert len(cache) == 240


def test_assinatura_ignora_troca_de_objeto_com_mesmo_conteudo() -> None:
    project = _project()
    clip = project.tracks[1].clips[0]
    same = replace(project, tracks=tuple(
        replace(t, clips=tuple(replace(c) for c in t.clips)) for t in project.tracks))
    assert render_signature(same, 1) == render_signature(project, 1)
    assert clip in same.tracks[1].clips


# --- infraestrutura -------------------------------------------------------------

def _jpeg(color: str, size=(64, 36)) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPG", 80)
    buffer.close()
    return bytes(data.data())


@pytest.mark.usefixtures("desktop_app")
@pytest.mark.parametrize("chunk", [1, 7, 4096, 1 << 16])
def test_fluxo_mjpeg_e_separado_em_imagens_inteiras(chunk) -> None:
    import io

    from videomanager.infrastructure.ffmpeg.preview import jpeg_frames
    images = [_jpeg(color) for color in ("red", "lime", "blue")]
    stream = io.BytesIO(b"".join(images))
    assert list(jpeg_frames(stream.read, chunk)) == images


def test_fluxo_corrompido_e_recusado() -> None:
    import io

    from videomanager.application.errors import VideoManagerError
    from videomanager.infrastructure.ffmpeg.preview import jpeg_frames
    with pytest.raises(VideoManagerError):
        list(jpeg_frames(io.BytesIO(b"lixo que nao e jpeg").read))


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("desktop_app")
def test_quadros_do_cache_batem_com_o_quadro_exato(tmp_path) -> None:
    """O quadro ``k`` do trecho é o instante ``at + k/fps`` da composição."""
    import subprocess

    from PySide6.QtGui import QImage

    from videomanager.domain.project import media_ref
    from videomanager.infrastructure.ffmpeg.composer import frame_command, scrub_command
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command, jpeg_frames
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")
    source = tmp_path / "cores.mp4"
    graph = ("color=c=red:s=320x180:r=30:d=1[a];color=c=lime:s=320x180:r=30:d=1[b];"
             "color=c=blue:s=320x180:r=30:d=1[c];[a][b][c]concat=n=3:v=1:a=0")
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", graph,
                    "-c:v", "libx264", "-g", "30", str(source)], check=True, timeout=60, **subprocess_kwargs())
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(media_ref(probe_file(source, tools)), 0, 3),)),),
                      width=320, height=180, fps=30)
    command = scrub_command(project, 0.5, 2.0, (160, 90), tools, fps=30)
    result = subprocess.run(command, timeout=60, **subprocess_kwargs())
    import io
    images = list(jpeg_frames(io.BytesIO(result.stdout).read))
    assert len(images) == 60

    def dominant(r, g, b):
        return max((r, "r"), (g, "g"), (b, "b"))[1]

    for k in (0, 14, 16, 44, 46, 59):
        seconds = 0.5 + k / 30
        image = QImage.fromData(images[k], "JPG")
        color = image.pixelColor(80, 45)
        exact = frame_from_command(frame_command(project, seconds, (160, 90), tools), (160, 90))
        offset = (45 * 160 + 80) * 3
        expected = dominant(*exact.data[offset:offset + 3])
        assert dominant(color.red(), color.green(), color.blue()) == expected, (k, seconds)


# --- painel -----------------------------------------------------------------------

@pytest.fixture
def scrub_panel(desktop_app, isolated_audio, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from videomanager.application.capabilities import FFmpegTools
    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.infrastructure.qt.workers.signals import PreviewSignals
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.edit_panel import EditPanel

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    tools = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
    runtime = build_desktop_runtime(audio_enabled=False)
    calls = SimpleNamespace(frames=[], scrub=[], playback=[])

    def fake(kind):
        def factory(*args, **kwargs):
            worker = SimpleNamespace(args=args, kwargs=kwargs, signals=PreviewSignals(), cancelled=[])
            worker.cancel = lambda: worker.cancelled.append(True)
            worker.start_playback = lambda: None
            getattr(calls, kind).append(worker)
            return worker
        return factory

    monkeypatch.setattr(runtime, "frame_worker", fake("frames"))
    monkeypatch.setattr(runtime, "scrub_cache_worker", fake("scrub"))
    monkeypatch.setattr(runtime, "playback_worker", fake("playback"))
    monkeypatch.setattr(runtime, "scrub_cache_budget", lambda: 10**8)
    panel = EditPanel(Settings(), ensure_tools=lambda: tools, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=runtime)
    for runner in (panel._runner, panel._scrub_runner, panel._background):
        monkeypatch.setattr(runner, "start", lambda *args: None)
    panel.install_project(replace(panel._project, tracks=(
        Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0, 10),)),), width=320, height=180, fps=30), None, [], {})
    # O quadro pedido ao instalar o projeto termina, como terminaria no ffmpeg.
    for worker in list(calls.frames):
        worker.signals.done.emit()
    yield panel, calls
    panel.shutdown()


def _fill_cache(panel) -> None:
    cache = ScrubFrameCache(panel._scrub_fps(), panel._scrub_size(), 10**8)
    segments = signature_segments(panel._project, 0, 10)
    image = _jpeg("red", panel._scrub_size())
    for index in range(300):
        cache.put(index, signature_at(segments, index / 30), image, focus_index=0)
    panel._scrub_cache = cache


def _drag_to(panel, seconds: float) -> None:
    panel._timeline._drag = "cursor"  # arrasto em andamento, como no mousePress
    panel._timeline.scrubbed.emit(seconds)


def test_arrasto_com_quadro_guardado_nao_abre_ffmpeg(scrub_panel) -> None:
    panel, calls = scrub_panel
    _fill_cache(panel)
    before = len(calls.frames)
    for seconds in (1.0, 1.5, 2.0, 2.5, 3.0):
        _drag_to(panel, seconds)
    assert len(calls.frames) == before, "cada movimento usou o quadro guardado"
    assert panel._cache_shown_for == pytest.approx(3.0)
    assert not calls.playback or all(w.cancelled for w in calls.playback[:-1])
    panel._scrub_settle_timer.timeout.emit()  # a mão parou
    assert len(calls.frames) == before + 1
    assert calls.frames[-1].args[1] == pytest.approx(3.0)


def test_soltar_a_agulha_pede_o_quadro_exato(scrub_panel) -> None:
    panel, calls = scrub_panel
    _fill_cache(panel)
    _drag_to(panel, 4.0)
    before = len(calls.frames)
    panel._timeline._drag = ""
    panel._timeline.scrub_finished.emit()
    assert len(calls.frames) == before + 1 and calls.frames[-1].args[1] == pytest.approx(4.0)


def test_sem_quadro_guardado_vale_o_caminho_exato(scrub_panel) -> None:
    panel, calls = scrub_panel
    before = len(calls.frames)
    _drag_to(panel, 2.0)
    assert len(calls.frames) == before + 1


def test_quadro_exato_atrasado_nao_cobre_o_guardado_mais_novo(scrub_panel) -> None:
    from videomanager.domain.preview import RawFrame

    panel, calls = scrub_panel
    _drag_to(panel, 1.0)  # sem cache: pede o exato de 1,0 s
    old = calls.frames[-1]
    _fill_cache(panel)
    _drag_to(panel, 3.0)  # agora com cache: mostra 3,0 s guardado
    size = panel._preview_size()
    frame = RawFrame(b"\x00" * (size[0] * size[1] * 3), size[0], size[1], 1.0)
    old.signals.frame.emit(panel._frame_token, frame)
    assert panel._cache_shown_for == pytest.approx(3.0)


def test_preenchimento_comeca_perto_da_agulha_e_para_na_reproducao(scrub_panel) -> None:
    panel, calls = scrub_panel
    panel._timeline.set_position(6.0)
    panel._start_scrub_fill()
    job = calls.scrub[-1]
    seconds, span = job.args[1], job.args[2]
    assert seconds == pytest.approx(5.0) and span > 0
    assert job.kwargs["first_index"] == 150
    image = _jpeg("red", panel._scrub_size())
    job.signals.scrub_frames.emit(panel._scrub_job[0], 150, [image, image])
    assert len(panel._scrub_cache) == 2
    panel._start_playback(6.0)
    assert job.cancelled and panel._scrub_job is None
    count = len(calls.scrub)
    panel._start_scrub_fill()
    assert len(calls.scrub) == count, "tocando, não se preenche"
