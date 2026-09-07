"""Regressões de persistência, mudanças pendentes e isolamento dos recursos."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from videomanager.core.editor_session import EditorSession
from videomanager.core.errors import ProjectError
from videomanager.core.project import Clip, MediaKind, MediaRef, Track, TrackKind, next_clip_id
from videomanager.core.project_io import load_project, project_from_dict, save_project
from videomanager.core.settings import Settings
from videomanager.ui.panels.edit_panel import EditPanel
from videomanager.ui.text_renderer import render_text_to_image


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
    session.project = original.without_clip(original.clips[0].clip_id)
    assert session.project.is_empty and session.has_changes
    assert session.undo() and not session.has_changes
    assert session.redo() and session.has_changes
    session.mark_saved()
    assert not session.has_changes


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    instance = EditPanel(Settings(), ensure_tools=lambda: None)
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
    project, _ = project_from_dict(document())
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
    first = render_text_to_image(clip)
    content = first.read_bytes()
    changed = render_text_to_image(replace(clip, text_content="Segunda versão"))
    assert changed != first
    assert first.read_bytes() == content
    assert changed.read_bytes() != content
    assert render_text_to_image(replace(clip, clip_id=next_clip_id())) == first


def test_importacao_nao_bloqueia_eventos_e_pode_ser_cancelada(panel, monkeypatch, wait_until):
    import threading
    from PySide6.QtCore import QTimer
    from videomanager.core.binaries import FFmpegTools
    from videomanager.core.converter import LocalMedia, LocalStream

    started, release = threading.Event(), threading.Event()
    ticks = []
    def inspect(path, tools, *, control):
        started.set()
        while not release.wait(0.01):
            control.check()
        return LocalMedia(path, 2, "mp4", 100,
                          (LocalStream(0, "video", "h264", width=160, height=90, fps=24),))
    panel._ensure_tools = lambda: FFmpegTools(Path("/missing/ffmpeg"), Path("/missing/ffprobe"), "teste")
    monkeypatch.setattr("videomanager.workers.media_worker.probe_file", inspect)
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
    from videomanager.workers.media_worker import MediaResult
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
        "import videomanager.core.composer, sys; "
        "assert not any(n.startswith(('PySide6', 'videomanager.ui')) for n in sys.modules)",
    ], capture_output=True, timeout=10,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
    assert result.returncode == 0, result.stderr.decode()
