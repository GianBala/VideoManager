"""Regressões de persistência, mudanças pendentes e isolamento dos recursos."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from videomanager.application.editor.session import EditorSession
from videomanager.application.errors import ProjectError
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import next_clip_id
from videomanager.infrastructure.storage.project_json import load_project
from videomanager.infrastructure.storage.project_json import project_from_dict
from videomanager.infrastructure.storage.project_json import save_project
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.infrastructure.qt.text import QtTextRasterizer
from videomanager.bootstrap import build_editor_service
from videomanager.bootstrap import build_processing_service
from videomanager.bootstrap import build_desktop_runtime


def document(identity=1):
    return {"tracks": [{"track_id": identity, "kind": "VIDEO", "clips": [
        {"clip_id": identity, "duration": 2, "media": {"path": "missing.mp4"}}
    ]}]}


def test_ids_restaurados_nao_colidem_com_insercao_e_exclusao():
    identity = next_clip_id() + 1000
    project, _ = project_from_dict(document(identity))
    inserted = Clip(project.clips[0].media, 2, 2)
    assert inserted.clip_id > identity
    assert Track(TrackKind.VIDEO).track_id > identity
    updated = project.with_clip(0, inserted).without_clip(inserted.clip_id)
    assert updated.clips == project.clips


def test_audio_separado_nao_oferece_nova_separacao_nem_altera_historico(panel):
    from videomanager.domain.project import new_project
    from videomanager.presentation.qt import strings

    media = MediaRef(Path('video.mp4'), MediaKind.VIDEO, duration=5, has_audio=True)
    project = new_project(media)
    project = project.detached_audio(project.clips[0].clip_id)
    panel.install_project(project, None, [], {})
    audio = next(c for c in project.clips if c.audio_only)
    panel._timeline.select(audio.clip_id)
    index, _ = project.find(audio.clip_id)
    menu = panel.build_menu('clip', index, audio.clip_id)
    assert strings.EDIT_DETACH not in [action.text() for action in menu.actions()]
    panel._detach_audio()
    assert panel._project is project
    assert not panel._session.history
    assert not panel.has_unsaved_changes


def test_ids_ausentes_sao_gerados_apos_reservar_todos_os_restaurados():
    data = document(next_clip_id() + 1000)
    data["tracks"].insert(0, {"clips": [{"duration": 1, "media": {"path": "other.mp4"}}]})
    project, _ = project_from_dict(data)
    assert len({c.clip_id for c in project.clips}) == 2
    assert len({t.track_id for t in project.tracks}) == 2


@pytest.mark.parametrize("kind", ["clip", "track"])
def test_ids_duplicados_sao_rejeitados(kind):
    data = document()
    if kind == "track":
        data["tracks"].append({"track_id": 1, "clips": []})
    else:
        data["tracks"].append({"track_id": 2, "clips": data["tracks"][0]["clips"]})
    with pytest.raises(ProjectError, match="duplicado"):
        project_from_dict(data)


@pytest.mark.parametrize("data", [
    {"width": "abc"}, {"width": 0}, {"width": True}, {"fps": float("nan")},
    {"fps": float("inf")}, {"version": True}, {"tracks": [None]},
    {"tracks": [{"clips": None}]}, {"tracks": [{"kind": []}]},
    {"tracks": [{"clips": [{"duration": 1, "media": {}}]}]},
])
def test_documentos_invalidos_levantam_erro_de_dominio(data):
    with pytest.raises(ProjectError):
        project_from_dict(data)


@pytest.mark.parametrize("field,value", [
    ("duration", -1), ("duration", 0), ("speed", 0), ("scale_x", -2),
    ("start", -1), ("gain_db", float("nan")), ("font_size", "grande"),
    ("muted", "false"), ("clip_id", 0), ("chromakey_blend", 2),
])
def test_valores_invalidos_de_clipes(field, value):
    data = document()
    data["tracks"][0]["clips"][0][field] = value
    with pytest.raises(ProjectError):
        project_from_dict(data)


def test_arquivo_com_codificacao_invalida(tmp_path):
    path = tmp_path / "invalid.vmp"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ProjectError):
        load_project(path)


def test_ponto_salvo_acompanha_desfazer_refazer_e_exclusao_total():
    session = EditorSession()
    original, _ = project_from_dict(document())
    session.reset(original)
    session.remember()
    session.replace_current(original.without_clip(original.clips[0].clip_id))
    assert session.project.is_empty and session.has_changes
    assert session.undo() and not session.has_changes
    assert session.redo() and session.has_changes
    session.mark_saved()
    assert not session.has_changes


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    instance = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    yield instance
    instance.shutdown()


def test_inserir_colar_transformar_e_apagar_exige_salvar(panel, tmp_path):
    panel._text_input.setText("Título")
    panel._insert_text_clip()
    assert panel.has_unsaved_changes
    panel._project_path = tmp_path / "p.vmp"
    assert panel.save_project()
    assert not panel.has_unsaved_changes
    panel._copy_clip()
    panel._paste_clip()
    assert panel.has_unsaved_changes
    panel._undo_edit()
    assert not panel.has_unsaved_changes
    clip = panel._project.clips[0]
    panel._on_overlay_transformed(clip.clip_id, 0.2, 0.3, 1, 0)
    panel._on_overlay_transform_finished(clip.clip_id)
    assert panel.has_unsaved_changes
    panel._undo_edit()
    assert not panel.has_unsaved_changes
    panel._apply(panel._project.without_clip(clip.clip_id))
    assert panel._project.is_empty and panel.has_unsaved_changes


def test_abrir_preserva_canvas_e_nao_marca_alteracoes(panel, tmp_path, wait_until):
    project, _ = project_from_dict(document(), base_dir=tmp_path)
    project = replace(project, width=720, height=1280, fps=25)
    path = tmp_path / "p.vmp"
    save_project(project, path)
    assert panel.open_project(path)
    wait_until(lambda: not panel._project_actions.busy)
    assert panel._project == project
    assert not panel.has_unsaved_changes


def test_falha_ao_abrir_preserva_projeto_e_caminho(panel, tmp_path, wait_until):
    panel._insert_text_clip()
    previous = panel._project
    panel._project_path = tmp_path / "previous.vmp"
    bad = tmp_path / "bad.vmp"
    bad.write_text('{"width": "inválida"}')
    panel.open_project(bad)
    wait_until(lambda: not panel._project_actions.busy)
    assert panel._project == previous
    assert panel._project_path.name == "previous.vmp"
    assert panel.has_unsaved_changes


def test_textos_de_versoes_distintas_sao_imutaveis():
    clip = Clip(MediaRef(Path("Texto_teste"), MediaKind.IMAGE), 0, 2,
                overlay_type="text", text_content="Primeira versão")
    render_text_to_image = QtTextRasterizer().render
    first = render_text_to_image(clip)
    content = first.read_bytes()
    changed = render_text_to_image(replace(clip, text_content="Segunda versão"))
    assert changed != first
    assert first.read_bytes() == content
    assert changed.read_bytes() != content
    assert render_text_to_image(replace(clip, clip_id=next_clip_id())) == first


def test_botao_atualizar_texto_preserva_texto_vazio(panel):
    """O botão precisa concordar com a digitação ao vivo sobre texto vazio.

    A digitação ao vivo (_on_text_input_changed) já aceita texto vazio de
    verdade, para casar com o rasterizador — inventar "Texto" aqui fazia a
    caixa da prévia divergir do que a exportação desenha. O botão "Atualizar
    texto" tinha ficado para trás com um `.strip() or "Texto"` residual: apagar
    o campo e clicar no botão reescrevia por cima o texto vazio que o usuário
    acabara de confirmar.
    """
    clip = Clip(MediaRef(Path('Texto_x'), MediaKind.IMAGE), 0.0, 2.0,
               overlay_type='text', text_content='ola')
    project = replace(panel._project, tracks=(Track(TrackKind.ADDITIONAL, clips=(clip,)),))
    panel.install_project(project, None, [], {})
    panel._timeline.select(clip.clip_id)
    panel._text_input.setText('')
    panel._update_selected_text_clip()
    assert panel._project.find(clip.clip_id)[1].text_content == ''


def test_importacao_nao_bloqueia_eventos_e_pode_ser_cancelada(panel, monkeypatch, wait_until):
    import threading
    from PySide6.QtCore import QTimer
    from videomanager.application.capabilities import FFmpegTools
    from videomanager.domain.media import LocalMedia
    from videomanager.domain.media import LocalStream

    started, release = threading.Event(), threading.Event()
    ticks = []
    def inspect(path, tools, *, control):
        started.set()
        while not release.wait(0.01):
            control.check()
        return LocalMedia(path, 2, "mp4", 100,
                          (LocalStream(0, "video", "h264", width=160, height=90, fps=24),))
    panel._ensure_tools = lambda: FFmpegTools(Path("/missing/ffmpeg"), Path("/missing/ffprobe"), "teste")
    monkeypatch.setattr("videomanager.infrastructure.qt.workers.media_worker.probe_file", inspect)
    try:
        panel.import_files([Path("/missing/media.mp4")], insert=True)
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait_until(lambda: started.is_set() and bool(ticks))
        assert panel._project_actions.busy
        assert panel._project.is_empty
        panel._project_actions.cancel_pending()
        release.set()
        wait_until(lambda: panel._project_actions.runner.active == 0)
        assert panel._project.is_empty and not panel._pool
    finally:
        release.set()


def test_resposta_de_projeto_anterior_nao_substitui_novo(panel):
    from videomanager.application.editor.media import MediaResult
    previous_token = panel._project_actions.token
    project, _ = project_from_dict(document())
    panel.new_project()
    panel._project_actions._finished(previous_token, MediaResult(project=project))
    assert panel._project.is_empty and panel._project_path is None


def test_cancelar_confirmacao_preserva_edicao(panel, monkeypatch):
    panel._insert_text_clip()
    previous = panel._project
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not panel.new_project()
    assert panel._project == previous and panel.has_unsaved_changes


def test_falha_ao_salvar_preserva_ponto_salvo_e_arquivo(panel, tmp_path, monkeypatch):
    panel._project_path = tmp_path / "project.vmp"
    panel._insert_text_clip()
    assert panel.save_project()
    original = panel._project_path.read_bytes()
    panel._insert_text_clip()
    def fail(*args):
        raise OSError("sem espaço")
    monkeypatch.setattr(Path, "replace", fail)
    assert not panel.save_project()
    assert panel.has_unsaved_changes
    assert panel._project_path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["project.vmp"]


def test_importar_compositor_nao_carrega_qt_ou_interface():
    import os
    import subprocess
    import sys
    result = subprocess.run([
        sys.executable, "-c",
        "import videomanager.infrastructure.ffmpeg.composer, sys; "
        "assert not any(n.startswith(('PySide6', 'videomanager.ui')) for n in sys.modules)",
    ], capture_output=True, timeout=10,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
    assert result.returncode == 0, result.stderr.decode()


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


def test_salvar_snapshot_de_sessao_substituida_nao_autoriza_descartar_atual(panel, tmp_path, monkeypatch):
    from videomanager.domain.project import new_project
    panel._project_path = tmp_path / 'snapshot.vmp'
    panel._insert_text_clip()
    accept = panel.editor.accept_saved
    def replaced(snapshot, path):
        panel.editor.session.reset(new_project())
        return accept(snapshot, path)
    monkeypatch.setattr(panel.editor, 'accept_saved', replaced)
    assert not panel.save_project()
    assert (tmp_path / 'snapshot.vmp').exists()
    assert panel.editor.session.path is None


def test_dialogo_de_gravacao_so_fecha_com_resultado_do_worker(desktop_app):
    from videomanager.presentation.qt.editor_project import _SaveProgress
    dialog = _SaveProgress()
    dialog.setCancelButton(None)
    dialog.show()
    desktop_app.processEvents()
    try:
        dialog.close()
        assert dialog.isVisible()
        dialog.reject()
        assert dialog.isVisible()
        dialog.finish(True)
        assert not dialog.isVisible()
    finally:
        dialog.finish(False)
        dialog.deleteLater()


def test_propriedade_apos_undo_nao_reaproveita_sessao_anterior(panel):
    panel._insert_text_clip()
    clip = panel._timeline.selected_clip
    panel._on_properties_changed(clip.clip_id, {'x': .6})
    panel._undo_edit()
    panel._on_properties_changed(clip.clip_id, {'x': .7})
    panel._redo_edit()
    assert panel._project.find(clip.clip_id)[1].x == .7
    panel._undo_edit()
    assert panel._project.find(clip.clip_id)[1].x == clip.x


def test_reordenacao_de_trilhas_produz_um_unico_undo(panel):
    original = panel._project
    panel._timeline.edit_started.emit()
    panel._timeline.track_reordered.emit(0, 1)
    panel._timeline.edit_finished.emit()
    assert len(panel._session.history) == 1
    panel._undo_edit()
    assert panel._project is original


def test_abrir_projeto_limpa_proporcao_anterior(panel):
    project = replace(panel._project, width=1080, height=1920, fps=24)
    panel._aspect_choice = '16:9'
    panel.install_project(project, Path('/tmp/vertical.vmp'), [], {})
    assert (panel._project.width, panel._project.height, panel._project.fps) == (1080, 1920, 24)
    assert panel._aspect_choice == '9:16'
    assert not panel.has_unsaved_changes


def test_velocidade_que_nao_cabe_nao_trunca_origem(panel):
    media = MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, duration=20)
    item, neighbor = Clip(media, 0, 5), Clip(media, 5, 5)
    project = replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(item, neighbor)),))
    panel.install_project(project, None, [], {})
    panel._timeline.select(item.clip_id)
    panel._on_speed(.5)
    assert panel._project.find(item.clip_id)[1] == item
    assert not panel._session.history


def test_velocidade_rejeitada_repetida_avisa_uma_vez_por_sessao(panel, monkeypatch):
    """Arrastar o spinbox de velocidade dispara valueChanged a cada passo.

    Sem agrupar por sessão (a mesma ideia já usada para ganho/digitação), cada
    passo rejeitado reabria o QMessageBox modal — "descer a velocidade até não
    caber" virava uma enxurrada de diálogos em vez de um aviso só.
    """
    avisos = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: avisos.append(1))
    media = MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, duration=20)
    item, neighbor = Clip(media, 0, 5), Clip(media, 5, 5)
    project = replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(item, neighbor)),))
    panel.install_project(project, None, [], {})
    panel._timeline.select(item.clip_id)

    for _ in range(6):
        panel._on_speed(.5)
    assert len(avisos) == 1, f'esperava 1 aviso para 6 rejeições seguidas, veio {len(avisos)}'

    panel._end_speed_session()
    panel._on_speed(.5)
    assert len(avisos) == 2, 'uma nova sessão de ajuste deve poder avisar de novo'


def test_tesoura_com_selecao_fora_do_cursor_nao_corta_outro(panel):
    media = MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, duration=20)
    item, neighbor = Clip(media, 0, 5), Clip(media, 5, 5)
    project = replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(item, neighbor)),))
    panel.install_project(project, None, [], {})
    panel._timeline.select(item.clip_id)
    panel._timeline.set_position(7)
    panel._split_here()
    assert len(panel._project.clips) == 2


def test_arrastar_afastar_e_devolver_preserva_transicao(panel):
    media = MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, duration=20)
    left, right = Clip(media, 0, 5), Clip(media, 5, 5)
    marker = Clip(MediaRef(Path('Transição_teste'), MediaKind.IMAGE), 4, 2, overlay_type='transition',
                  transition_left_id=left.clip_id, transition_right_id=right.clip_id)
    project = replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(left, right, marker)),))
    panel.install_project(project, None, [], {})
    panel._timeline.edit_started.emit()
    panel._on_clip_moved(right.clip_id, 0, 10)
    assert panel._project.find(marker.clip_id) is None
    panel._on_clip_moved(right.clip_id, 0, 5)
    panel._timeline.edit_finished.emit()
    assert panel._project.find(marker.clip_id) is not None
    assert not panel._session.history


def test_navegacao_keyframe_converte_origem_para_timeline(panel, monkeypatch):
    media = MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, duration=30)
    item = Clip(media, 5, 5, in_point=10, speed=2)
    panel.install_project(replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(item,)),)), None, [], {})
    panel._timeline.select(item.clip_id)
    panel._keyframe_source = media.path
    panel._keyframes = (0, 10, 12, 16, 22)
    panel._timeline.set_position(5)
    positions = []
    monkeypatch.setattr(panel, '_seek_to', positions.append)
    panel._jump_keyframe(1)
    assert positions == [6]


def test_indice_tardio_nao_substitui_midia_atual(panel):
    panel._keyframe_source = Path('/m/atual.mp4')
    panel._keyframe_token = 12
    panel._keyframes = (0, 2, 4)
    panel._on_keyframes((1, 5), Path('/m/anterior.mp4'), 11)
    assert panel._keyframes == (0, 2, 4)
    panel._on_keyframes((1, 5), Path('/m/atual.mp4'), 10)
    assert panel._keyframes == (0, 2, 4)


def test_seek_ocupado_rejeita_quadro_anterior_e_inicia_so_ultimo(panel, monkeypatch):
    from videomanager.domain.project import Project
    from videomanager.domain.preview import RawFrame
    from videomanager.application.media.preview import PreviewResultKey
    clip = Clip(MediaRef(Path('/m/a.mp4'), MediaKind.VIDEO), 0, 5)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),))
    panel._project = project
    panel._timeline.set_project(project)
    panel._frame_busy = True
    panel._frame_token = panel._frame_job_token = 71
    panel._wanted = panel._rendered = 1
    panel._frame_key = PreviewResultKey(71, panel._generation, 0, 1, (2, 2), 30)
    shown, started = [], []
    monkeypatch.setattr(panel, '_show_frame', shown.append)
    monkeypatch.setattr(panel, '_start_frame', lambda: started.append(panel._wanted))
    panel._timeline.set_position(2)
    panel._request_frame()
    panel._timeline.set_position(3)
    panel._request_frame()
    panel._on_frame(71, RawFrame(bytes(12), 2, 2, 1))
    assert not shown
    panel._on_frame_done(0, 71)
    assert started == [3]
    panel._frame_busy = True
    panel._frame_job_token = 72
    panel._on_frame_done(0, 71)
    assert panel._frame_busy
    assert started == [3]


def test_seek_de_ida_e_volta_reagenda_quadro_invalidado(panel, monkeypatch):
    from videomanager.domain.project import Project
    clip = Clip(MediaRef(Path('/m/a.mp4'), MediaKind.VIDEO), 0, 5)
    panel._project = Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),))
    panel._timeline.set_project(panel._project)
    panel._frame_busy = True
    panel._frame_token = panel._frame_job_token = 71
    panel._wanted = panel._rendered = 1
    started = []
    monkeypatch.setattr(panel, '_start_frame', lambda: started.append(panel._wanted))
    panel._timeline.set_position(2)
    panel._request_frame()
    panel._timeline.set_position(1)
    panel._request_frame()
    panel._on_frame_done(0, 71)
    assert started == [1]


def test_callback_apos_fechar_nao_reinicia_worker(panel, monkeypatch):
    started = []
    monkeypatch.setattr(panel, '_start_frame', lambda: started.append(True))
    panel._closed = True
    panel._wanted = 2
    panel._on_frame_done(-1)
    assert not started


def _clock_project(panel, *, speed=1):
    from videomanager.domain.project import Project
    clip = Clip(MediaRef(Path('/m/a.mp4'), MediaKind.VIDEO), 0, 4, speed=speed)
    panel._project = Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),))
    panel._timeline.set_project(panel._project)
    panel._playing = True
    return clip


def test_scrub_durante_play_preserva_destino_e_nao_frame_antigo(panel):
    _clock_project(panel)
    panel._shown_frame = .5
    panel._timeline.set_position(2)
    panel._on_scrub(2)
    assert panel._position == 2
    assert not panel._playing


def test_fim_do_audio_continua_video_e_relogio_monotonico(panel, monkeypatch):
    _clock_project(panel)
    panel._timeline.set_position(1)
    now = [10.0]
    monkeypatch.setattr('videomanager.presentation.qt.panels.edit_panel.playback_clock', lambda: now[0])
    panel._on_audio_stopped()
    assert panel._playing
    now[0] = 12
    panel._on_tick()
    assert panel._position == pytest.approx(3)
    assert panel._playing


@pytest.mark.parametrize('fps', [24, 29.97, 60])
def test_pausa_e_retomada_seguem_frame_exibido_sem_deriva_acumulada(panel, monkeypatch, fps):
    import math
    from types import SimpleNamespace
    _clock_project(panel)
    panel._project = replace(panel._project, fps=fps)
    panel._timeline.set_project(panel._project)
    now = [100.0]
    sound = SimpleNamespace(playing=True, position=0., available=True)
    sound.stop = lambda: setattr(sound, 'playing', False)
    monkeypatch.setattr(panel, '_audio', sound)
    monkeypatch.setattr(panel, '_ensure_tools', lambda: object())
    monkeypatch.setattr(panel, '_prime_playback', lambda: None)
    monkeypatch.setattr(panel, '_start_frames', lambda seconds: (17, True))
    monkeypatch.setattr('videomanager.presentation.qt.panels.edit_panel.playback_clock', lambda: now[0])
    resumed = []
    def start(audio, project, seconds, tools, **kw):
        resumed.append(seconds)
        audio.playing, audio.position = True, seconds
    monkeypatch.setattr(panel._runtime, 'play_audio', start)
    for index in range(30):
        sound.playing = True
        sound.position = .5 + index * .05
        visible = math.floor(sound.position * fps) / fps
        panel._shown_frame = visible
        panel._playing = True
        panel._on_tick()
        assert panel._position == pytest.approx(sound.position)
        panel._stop_playback()
        assert panel._position == pytest.approx(visible)
        assert 0 <= sound.position - panel._position < 1 / fps + 1e-9
        now[0] += .1
        panel._start_playback(panel._position)
        assert resumed[-1] == pytest.approx(visible)
        assert panel._clock_position == pytest.approx(visible)
        assert panel._clock_started == now[0]


def test_velocidade_de_clipe_nao_antecipa_fim(panel, monkeypatch):
    _clock_project(panel, speed=10)
    panel._clock_position = 3.8
    panel._clock_started = 10
    now = [10.0]
    monkeypatch.setattr('videomanager.presentation.qt.panels.edit_panel.playback_clock', lambda: now[0])
    panel._on_tick()
    assert panel._playing
    panel._shown_frame = 119/30
    now[0] = 10.2
    panel._on_tick()
    assert not panel._playing
    assert panel._position == pytest.approx(119/30)


def test_projeto_sem_saida_reproduzivel_nao_habilita_play(panel):
    from videomanager.domain.project import Project
    clip = Clip(MediaRef(Path('/m/a.wav'), MediaKind.AUDIO), 0, 4)
    panel._project = Project(tracks=(Track(TrackKind.AUDIO, clips=(clip,), muted=True),))
    assert not panel._playable


def test_onda_equivalente_reusa_worker_e_done_antigo_nao_libera_novo(panel, monkeypatch):
    from videomanager.infrastructure.qt.workers.signals import PreviewSignals
    from types import SimpleNamespace
    clip = Clip(MediaRef(Path('/m/a.wav'), MediaKind.AUDIO), 0, 5)
    workers = []
    def make(*args):
        worker = SimpleNamespace(signals=PreviewSignals(), cancel=lambda: None)
        workers.append(worker)
        return worker
    monkeypatch.setattr(panel._runtime, 'waveform_worker', make)
    monkeypatch.setattr(panel._background, 'start', lambda *args: None)
    monkeypatch.setattr(panel, '_strip_window', lambda clip: (0, 2))
    panel._request_wave(clip, None)
    first_token = panel._strip_tokens[clip.clip_id]
    panel._request_wave(clip, None)
    assert len(workers) == 1
    monkeypatch.setattr(panel, '_strip_window', lambda clip: (2, 4))
    panel._request_wave(clip, None)
    assert len(workers) == 2
    panel._on_strip_done(clip.clip_id, first_token)
    assert panel._strip_workers[clip.clip_id] is workers[-1]
    panel._request_wave(clip, None)
    assert len(workers) == 2


def test_slideshow_preserva_formato_sugerido_nos_controles_e_edicoes(panel):
    from videomanager.domain.project import Project
    photo = MediaRef(Path('/m/vertical.png'), MediaKind.IMAGE, width=3000, height=4000)
    clip = Clip(photo, 0, 5)
    panel._project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(clip,)),))
    panel._apply_slideshow_canvas()
    assert panel._canvas_choice == (1440, 1920)
    assert panel._canvas_box.currentData() == (1440, 1920)
    assert panel._aspect_box.currentData() == '3:4'
    panel._after_edit()
    assert (panel._project.width, panel._project.height) == (1440, 1920)


def test_salvar_e_desfazer_apos_mudar_resolucao_preserva_controles_e_texto(panel, tmp_path):
    panel._insert_text_clip()
    clip = panel._project.clips[0]
    reference = (panel._project.text_reference_width, panel._project.text_reference_height)
    panel._project_path = tmp_path / 'resolution.vmp'
    assert panel.save_project()
    panel._canvas_choice = (3840, 2160)
    panel._aspect_choice = '16:9'
    panel._after_edit()
    assert panel.save_project()
    panel._on_overlay_transformed(clip.clip_id, .3, .4, 1, 0)
    panel._on_overlay_transform_finished(clip.clip_id)
    assert panel.has_unsaved_changes
    panel._undo_edit()
    assert not panel.has_unsaved_changes
    assert panel._canvas_box.currentData() == (3840, 2160)
    assert (panel._project.width, panel._project.height) == (3840, 2160)
    assert (panel._project.text_reference_width, panel._project.text_reference_height) == reference
    saved, _ = load_project(panel._project_path)
    assert saved == panel._project


def test_insercao_automatica_evita_trilha_oculta_e_muda(panel):
    from videomanager.domain.project import Project
    media = MediaRef(Path('/m/a.mp4'), MediaKind.VIDEO, has_audio=True, duration=2)
    panel._project = Project(tracks=(Track(TrackKind.VIDEO, visible=False), Track(TrackKind.VIDEO, muted=True)))
    panel._place(media, at=0)
    found = next((t for t in panel._project.tracks if t.clips))
    assert found.visible and not found.muted
    assert len(panel._project.tracks) == 3


def test_digitacao_e_undo_preservam_sessao_espacos_e_cursor(panel):
    from PySide6.QtTest import QTest
    from videomanager.domain.project import Project
    clip = Clip(None, 0, 5, overlay_type='text', text_content='Oi')
    panel._project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(clip,)),))
    panel._timeline.set_project(panel._project)
    panel._timeline.select(clip.clip_id)
    panel._text_input.setCursorPosition(2)
    QTest.keyClicks(panel._text_input, ' tudo bem')
    assert panel._project.find(clip.clip_id)[1].text_content == 'Oi tudo bem'
    assert len(panel._session.history) == 1
    panel._text_input.setCursorPosition(3)
    QTest.keyClicks(panel._text_input, 'muito ')
    assert panel._project.find(clip.clip_id)[1].text_content == 'Oi muito tudo bem'
    assert panel._text_input.cursorPosition() == 9
    panel._undo_edit()
    assert panel._project.find(clip.clip_id)[1].text_content == 'Oi'
    panel._redo_edit()
    assert panel._project.find(clip.clip_id)[1].text_content == 'Oi muito tudo bem'
    panel.commit_pending_edits()
    QTest.keyClicks(panel._text_input, '!')
    assert len(panel._session.history) == 2


@pytest.mark.parametrize('reason', ['escape', 'capture', 'hide'])
def test_cancelamento_de_gesto_no_preview_restaura_projeto_e_historico(panel, reason):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    panel._insert_text_clip()
    original = panel._project
    clip = original.clips[0]
    history = panel._session.history
    panel._on_overlay_transformed(clip.clip_id, .2, .3, 1, 0)
    panel._preview._drag_mode = 'move'
    panel._preview._drag_clip_id = clip.clip_id
    panel._preview._drag_original_clip = clip
    if reason == 'escape':
        panel._preview.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    else:
        panel._preview.event(QEvent(QEvent.Type.UngrabMouse if reason == 'capture' else QEvent.Type.Hide))
    assert panel._project == original
    assert panel._session.history == history
    assert not panel._session.editing
    assert panel._preview._drag_mode is None


def test_gesto_do_preview_de_ida_e_volta_preserva_refazer(panel):
    panel._insert_text_clip()
    clip = panel._project.clips[0]
    panel._on_overlay_transformed(clip.clip_id, .2, .3, 1, 0)
    panel._on_overlay_transform_finished(clip.clip_id)
    panel._undo_edit()
    history, future = panel._session.history, panel._session.future
    panel._on_overlay_transformed(clip.clip_id, .1, .2, 1, 0)
    panel._on_overlay_transformed(clip.clip_id, clip.x, clip.y, clip.scale, clip.rotation)
    panel._on_overlay_transform_finished(clip.clip_id)
    assert panel._session.history == history
    assert panel._session.future == future


def test_gesto_continuo_apresenta_snapshot_com_indicacao_de_atualizacao(panel, monkeypatch):
    from videomanager.application.media.preview import PreviewResultKey
    from videomanager.domain.preview import RawFrame
    _clock_project(panel)
    panel._playing = False
    panel._session.begin_edit()
    panel._wanted = 1
    panel._frame_key = PreviewResultKey(71, panel._generation, 1, 1, (2, 2), 30)
    panel._frame_revision = 2
    panel._frame_token = 72
    shown = []
    monkeypatch.setattr(panel, '_preview_size', lambda: (2, 2))
    monkeypatch.setattr(panel, '_show_frame', shown.append)
    frame = RawFrame(bytes(12), 2, 2, 1)
    panel._on_frame(71, frame)
    assert shown == [frame]
    assert panel._loading_label.text()
    panel._session.commit_edit()
    panel._on_frame(71, frame)
    assert len(shown) == 1
    panel._frame_key = PreviewResultKey(72, panel._generation, 2, 1, (2, 2), 30)
    panel._on_frame(72, frame)
    assert len(shown) == 2 and not panel._loading_label.text()


def test_arrastar_agulha_apresenta_quadros_intermediarios_sem_piscar_aviso(panel, monkeypatch):
    """Arrastar a agulha mostra o que já ficou pronto, e não só quando a mão para.

    Exigir que o instante do quadro fosse o último pedido descartava todos os
    quadros do gesto — a prévia ficava parada com o aviso de atualização aceso
    do começo ao fim do arrasto.
    """
    from videomanager.application.media.preview import PreviewResultKey
    from videomanager.domain.preview import RawFrame
    _clock_project(panel)
    panel._playing = False
    panel._frame_revision = 1
    monkeypatch.setattr(panel, '_preview_size', lambda: (2, 2))
    shown = []
    monkeypatch.setattr(panel, '_show_frame', shown.append)

    # A agulha já avançou para 2,0 quando o quadro pedido para 1,0 fica pronto.
    panel._wanted = 2.0
    panel._frame_token = 91
    panel._frame_key = PreviewResultKey(90, panel._generation, 1, 1.0, (2, 2), 30)
    panel._on_frame(90, RawFrame(bytes(12), 2, 2, 1.0))
    assert len(shown) == 1, 'quadro intermediário do arrasto foi descartado'
    assert panel._preview._position == 1.0, 'o quadro deve entrar com o próprio instante'
    assert not panel._loading_label.text(), 'aviso não pode piscar a cada quadro do gesto'

    # Chegando o quadro da posição pedida, o aviso é encerrado de vez.
    panel._frame_key = PreviewResultKey(91, panel._generation, 1, 2.0, (2, 2), 30)
    panel._on_frame(91, RawFrame(bytes(12), 2, 2, 2.0))
    assert len(shown) == 2
    assert not panel._loading_label.text()
    assert not panel._loading_timer.isActive()


def test_aviso_de_atualizacao_aparece_quando_a_previa_realmente_para(panel, monkeypatch):
    """O aviso continua existindo: some do gesto, não da espera de verdade."""
    _clock_project(panel)
    panel._playing = False
    monkeypatch.setattr(panel, '_start_frame', lambda: None)
    panel._frame_busy = False
    panel._timeline.set_position(3.0)
    panel._request_frame()
    assert not panel._loading_label.text(), 'não anuncia antes da espera'
    assert panel._loading_timer.isActive()
    panel._loading_timer.timeout.emit()  # o prazo venceu sem quadro
    assert panel._loading_label.text()


@pytest.mark.parametrize('width', [1280, 1440])
def test_editor_estreito_permite_alcancar_controles_e_status(panel, desktop_app, width):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QScrollArea
    from videomanager.presentation.qt.main_window import MainWindow
    from videomanager.presentation.qt import strings

    wrapper = MainWindow._wrap_tab(panel, horizontal=True)
    wrapper.resize(width, 900)
    wrapper.show()
    try:
        desktop_app.processEvents()
        area = wrapper.findChild(QScrollArea)
        # Cabe sem rolagem lateral: a barra de transporte quebra em duas linhas
        # em vez de levar o volume (e o Exportar) para fora da vista.
        assert not area.horizontalScrollBar().isVisible()
        for controle in (panel._mute, panel._export_button):
            centro = controle.mapTo(area.viewport(), controle.rect().center())
            assert area.viewport().rect().contains(centro)
        volume = panel._mute
        center = volume.mapTo(area.viewport(), volume.rect().center())
        assert area.viewport().rect().contains(center)
        assert volume.visibleRegion().contains(volume.rect().center())
        label = panel._loading_label
        panel._loading_label.setText(strings.EDIT_LOADING_FRAME)
        desktop_app.processEvents()
        assert label.isVisibleTo(wrapper)
        assert label.visibleRegion().contains(label.rect().center())
        preview_size = panel._preview.size()
        label.setText('')
        desktop_app.processEvents()
        assert panel._preview.size() == preview_size
        assert label.mapTo(area.viewport(), QPoint(0, 0)).y() >= 0
    finally:
        wrapper.hide()
        panel.setParent(None)


def test_propriedades_estreitas_permite_alcancar_valores(desktop_app):
    from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget

    widget = _ClipPropertiesWidget()
    clip = Clip(MediaRef(Path('Texto'), MediaKind.IMAGE), 0, 5,
                overlay_type='text', text_content='Título')
    widget.load_clip(clip, 1920, 1080)
    widget.resize(260, 600)
    widget.show()
    try:
        desktop_app.processEvents()
        area = widget._scroll
        assert area.horizontalScrollBar().isVisible()
        target = widget._spin_opacity
        area.ensureWidgetVisible(target)
        desktop_app.processEvents()
        assert area.viewport().rect().contains(target.mapTo(area.viewport(), target.rect().center()))
        assert target.visibleRegion().contains(target.rect().center())
    finally:
        widget.close()


def _properties_fit(panel) -> bool:
    """Se a aba Propriedades cabe na coluna: sem rolar para o lado e com as quatro abas à vista."""
    bar = panel._extras_tabs.tabBar()
    return (panel._properties_widget._scroll.horizontalScrollBar().maximum() == 0
            and bar.sizeHint().width() <= bar.width())


def _image_clip_shown(panel, desktop_app):
    from videomanager.domain.project import Project
    clip = Clip(MediaRef(Path('foto.png'), MediaKind.IMAGE, width=640, height=360), 0, 5)
    panel.install_project(Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),), width=1280, height=720),
                          None, [], {})
    panel.resize(1880, 900)
    panel.show()
    desktop_app.processEvents()
    return clip


def test_coluna_de_adicionais_nasce_com_a_aba_propriedades_inteira(panel, desktop_app):
    """A coluna de Adicionais nasce larga o bastante para a aba Propriedades.

    Nascia no mínimo (260 px) e crescia para 340 ao abrir a aba, que pede
    ~390 no Windows: rolagem para o lado, campos cortados à direita e a aba
    Texto escondida atrás das setas da barra.
    """
    clip = _image_clip_shown(panel, desktop_app)
    try:
        initial = panel._top_splitter.sizes()[1]
        panel._open_properties_tab(clip.clip_id)
        desktop_app.processEvents()
        assert panel._top_splitter.sizes()[1] == initial, 'a coluna precisou crescer ao abrir a aba'
        assert _properties_fit(panel), 'a aba Propriedades não cabe na coluna'
    finally:
        panel.hide()


def test_abrir_propriedades_devolve_a_largura_da_aba_a_coluna_estreitada(panel, desktop_app):
    clip = _image_clip_shown(panel, desktop_app)
    try:
        sizes = panel._top_splitter.sizes()
        panel._top_splitter.setSizes([sizes[0], 270, sizes[2] + sizes[1] - 270])
        desktop_app.processEvents()
        panel._open_properties_tab(clip.clip_id)
        desktop_app.processEvents()
        assert _properties_fit(panel), 'a aba Propriedades não cabe na coluna'
    finally:
        panel.hide()


def test_selecao_com_quadro_disponivel_nao_dispara_render(panel, monkeypatch):
    from PySide6.QtGui import QPixmap
    panel._text_input.setText('Teste')
    panel._insert_text_clip()
    panel._preview.set_frame_pixmap(QPixmap(320, 180))
    requests = []
    monkeypatch.setattr(panel, '_request_frame', lambda **kwargs: requests.append(kwargs))
    panel._on_clip_selected(panel._project.clips[0].clip_id)
    assert requests == []


def test_pausa_sem_adicionais_restaura_alvos_selecionaveis(panel, monkeypatch):
    from videomanager.domain.project import Project
    clip = Clip(MediaRef(Path('video.mp4'), MediaKind.VIDEO, width=320, height=180), 0, 5)
    panel._project = Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),))
    panel._playing = True
    panel._shown_frame = 1
    panel._preview.set_position(1)
    panel._preview._selectable_clips = ()
    monkeypatch.setattr(panel, '_prime_playback', lambda: None)
    panel._stop_playback()
    assert [c.clip_id for c in panel._preview._selectable_clips] == [clip.clip_id]


@pytest.mark.parametrize('command', ['undo', 'seek', 'play'])
def test_comando_durante_arrasto_nao_deixa_gesto_ressuscitar(panel, monkeypatch, command):
    from PySide6.QtCore import Qt, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    panel._insert_text_clip()
    original = panel._project
    clip = original.clips[0]
    panel._preview._drag_mode = 'move'
    panel._preview._drag_clip_id = clip.clip_id
    panel._preview._drag_original_clip = clip
    panel._on_overlay_transformed(clip.clip_id, .7, .5, 1, 0)
    if command == 'undo':
        panel._undo_edit()
        assert panel._project == original
    elif command == 'seek':
        panel._seek_to(1)
    else:
        monkeypatch.setattr(panel, '_ensure_tools', lambda: object())
        monkeypatch.setattr(panel, '_request_frame', lambda **kwargs: None)
        monkeypatch.setattr(panel, '_open_stream', lambda seconds: None)
        panel._start_playback(0)
    expected = panel._project
    assert not panel._session.editing
    assert panel._preview._drag_mode is None
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(200, 180), QPointF(200, 180),
                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel._preview.mouseMoveEvent(event)
    assert panel._project == expected


def test_camadas_atrasadas_descartadas_apos_seek_selecao_e_edicao(panel):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    panel._insert_text_clip()
    context = panel._interaction_key()
    assert context is not None
    panel._interaction_context = context
    panel._interaction_token = 987
    img = QImage(32, 32, QImage.Format.Format_RGBA8888)
    img.fill(0)
    buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly); img.save(buf, 'PNG')
    images = (bytes(buf.data()),) * 3
    panel._timeline.set_position(1)
    panel._on_interaction_ready(987, images)
    assert panel._preview._interaction_layers is None
    panel._timeline.set_position(0)
    clip = panel._project.clips[0]
    panel._project = panel._project.with_updated_clip(clip.clip_id, text_content='Outro conteúdo')
    panel._on_interaction_ready(987, images)
    assert panel._preview._interaction_layers is None
    panel._preview.set_active_clip(None, 1920, 1080)
    panel._on_interaction_ready(987, images)
    assert panel._preview._interaction_layers is None


def _video_sobre_audio(panel):
    """Vídeo em cima, áudio embaixo começando depois: o caso do corte no som."""
    video = MediaRef(Path('/m/video.mp4'), MediaKind.VIDEO, duration=20, width=320, height=180)
    som = MediaRef(Path('/m/som.mp3'), MediaKind.AUDIO, duration=20, has_audio=True, channels=2)
    clip_v, clip_a = Clip(video, 0, 10), Clip(som, 2, 8)
    project = replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(clip_v,)),
                                               Track(TrackKind.AUDIO, clips=(clip_a,))))
    panel.install_project(project, None, [], {})
    return clip_v, clip_a


def test_botoes_de_corte_acompanham_a_agulha_movida_pela_reproducao(panel):
    """Com o áudio selecionado e a agulha fora dele, a tesoura fica desligada.

    Tocar e pausar dentro do áudio anda a agulha sem passar pela busca, e os
    botões ficavam desligados até o usuário clicar num vídeo e voltar no áudio
    — o único caminho que recalculava o estado deles.
    """
    _, clip_a = _video_sobre_audio(panel)
    panel._timeline.set_position(1)
    panel._timeline.select(clip_a.clip_id)
    assert not panel._split_button.isEnabled()
    panel._timeline.set_position(5)  # o que o relógio da reprodução faz
    assert panel._split_button.isEnabled()
    assert panel._trim_left_button.isEnabled() and panel._trim_right_button.isEnabled()
    panel._split_here()
    cortado = [c for c in panel._project.tracks[1].clips]
    assert len(cortado) == 2 and len(panel._project.tracks[0].clips) == 1


def test_clicar_na_regua_move_a_agulha_sem_perder_a_selecao(panel):
    """A régua é onde se posiciona o corte; desselecionar ali fazia a tesoura
    cair no bloco de cima — o vídeo — em vez do áudio escolhido."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from videomanager.presentation.qt.panels.timeline import RULER_HEIGHT

    clip_v, clip_a = _video_sobre_audio(panel)
    timeline = panel._timeline
    timeline.resize(900, 300)
    timeline.set_view(0, 10)
    timeline.select(clip_a.clip_id)
    pos = QPointF(timeline._x_of(6), RULER_HEIGHT / 2)
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        event = QMouseEvent(kind, pos, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        (timeline.mousePressEvent if kind == QMouseEvent.Type.MouseButtonPress else timeline.mouseReleaseEvent)(event)
    assert timeline.selected == clip_a.clip_id
    assert abs(panel._position - 6) < 0.05
    panel._split_here()
    assert len(panel._project.tracks[1].clips) == 2
    assert len(panel._project.tracks[0].clips) == 1


def test_barra_de_rolagem_e_divisoria_nao_desselecionam(panel):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    _, clip_a = _video_sobre_audio(panel)
    panel._timeline.select(clip_a.clip_id)
    pos = QPointF(2, 2)
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel.eventFilter(panel._scroll, event)
    panel.eventFilter(panel._split_view.handle(1), event)
    assert panel._timeline.selected == clip_a.clip_id
