"""Regras de sessão e persistência sem Qt, arquivos ou ffmpeg."""
from dataclasses import replace
from pathlib import Path
import pytest
from videomanager.application.editor.media import MediaResult
from videomanager.application.editor.media import ReadMedia
from videomanager.application.editor.service import EditorService
from videomanager.application.editor.session import EditorSession
from videomanager.application.errors import JobCancelled
from videomanager.application.errors import ProjectError
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.project import new_project


class Repository:
    def __init__(self):
        self.project = new_project()
        self.fail = False
        self.written = []

    def load(self, path):
        return self.project, [Path('ausente.mp4')]

    def save(self, project, path):
        if self.fail:
            raise ProjectError('sem espaço')
        self.written.append((project, path))


class Cancellation:
    cancelled = False
    def check(self):
        if self.cancelled:
            raise JobCancelled('Cancelado')


def test_salvamento_de_snapshot_nao_apaga_edicoes_posteriores():
    repository = Repository()
    editor = EditorService(repository)
    captured = editor.session.snapshot()
    editor.session.replace_current(replace(captured.project, width=640))
    editor.write_snapshot(captured, Path('p.vmp'))
    assert editor.accept_saved(captured, Path('p.vmp'))
    assert repository.written[0][0] == captured.project
    assert editor.session.has_changes


def test_resultado_de_salvamento_nao_modifica_sessao_substituida():
    editor = EditorService(Repository())
    captured = editor.session.snapshot()
    editor.session.reset(new_project())
    assert not editor.accept_saved(captured, Path('antigo.vmp'))
    assert editor.session.path is None


def test_abrir_nao_sobrescreve_edicao_feita_durante_leitura():
    editor = EditorService(Repository())
    captured = editor.session.snapshot()
    editor.session.replace_current(replace(captured.project, width=640))
    assert not editor.accept_opened(captured, MediaResult(project=new_project()), Path('p.vmp'))
    assert editor.session.project.width == 640


def test_falha_de_gravacao_nao_altera_sessao():
    repository = Repository()
    editor = EditorService(repository)
    editor.session.replace_current(replace(editor.session.project, width=640))
    repository.fail = True
    with pytest.raises(ProjectError):
        editor.write_snapshot(editor.session.snapshot(), Path('p.vmp'))
    assert editor.session.has_changes and editor.session.path is None


def test_historico_limitado_e_exposto_como_tupla():
    session = EditorSession()
    for width in range(100, 180):
        session.remember()
        session.replace_current(replace(session.project, width=width))
    assert len(session.history) == 60
    assert isinstance(session.history, tuple)
    assert session.undo() and session.project.width == 178
    assert session.redo() and session.project.width == 179


def test_importacao_elimina_duplicatas_e_respeita_cancelamento():
    cancellation = Cancellation()
    calls = []
    class Probe:
        def inspect(self, path, control):
            calls.append(path)
            return LocalMedia(path, 10, 'mp4', 100, (LocalStream(0, 'video', 'h264'),))
    reader = ReadMedia(Repository(), Probe())
    result = reader.execute([Path('a'), Path('a')], cancellation)
    assert len(result.references) == 1 and calls == [Path('a')]
    cancellation.cancelled = True
    with pytest.raises(JobCancelled):
        reader.execute([Path('b')], cancellation)
    assert calls == [Path('a')]
def test_identidades_novas_sao_instaladas_e_preservadas_no_historico():
    from dataclasses import replace
    from videomanager.application.editor.session import EditorSession

    session = EditorSession()
    before = session.snapshot()
    project = replace(session.project, tracks=tuple(
        replace(track, track_id=track.track_id + 1000 + index)
        for index, track in enumerate(session.project.tracks)
    ))
    assert project == session.project
    session.remember()
    session.replace_current(project)
    assert session.project is project
    assert not session.is_current(before)
    assert not session.has_changes
    assert session.undo()
    assert session.project is before.project
    assert session.redo()
    assert session.project is project


def test_transacao_sem_alteracao_preserva_redo_e_nao_consume_historico():
    session = EditorSession()
    original = session.project
    session.remember()
    session.replace_current(replace(original, width=640))
    session.undo()
    future = session.future
    session.begin_edit()
    session.replace_current(replace(original, width=720))
    session.replace_current(original)
    session.commit_edit()
    assert session.history == ()
    assert session.future == future


def test_transacao_agrupa_atualizacoes_e_cancelamento_restaura_tudo():
    session = EditorSession()
    original = session.project
    session.begin_edit()
    for width in (640, 720, 800):
        session.replace_current(replace(original, width=width))
    session.commit_edit()
    assert len(session.history) == 1
    assert session.undo() and session.project is original
    session.begin_edit()
    session.replace_current(replace(original, width=900))
    assert not session.future
    session.cancel_edit()
    assert session.project is original and session.future[0].width == 800
