"""A opção "Inverter" do botão direito sobre um bloco de vídeo ou de áudio."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.project import Clip, MediaKind, MediaRef, OverlayType, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.panels.edit_panel import EditPanel


@pytest.fixture
def panel(monkeypatch, desktop_app):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    instance = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                         processing=build_processing_service(), runtime=build_desktop_runtime())
    yield instance
    instance.shutdown()


def _video(**campos):
    base = dict(kind=MediaKind.VIDEO, duration=30.0, width=1280, height=720, fps=30.0, has_audio=True, channels=2)
    base.update(campos)
    return MediaRef(Path("video.mp4"), **base)


def _audio():
    return MediaRef(Path("som.mp3"), MediaKind.AUDIO, duration=30.0, has_audio=True, channels=2)


def _instala(panel, *faixas):
    projeto = Project(tracks=tuple(Track(tipo, clips=tuple(clips)) for tipo, clips in faixas))
    panel.install_project(projeto, None, [], {})
    return projeto


def _acao(panel, projeto, clip):
    indice, _ = projeto.find(clip.clip_id)
    menu = panel.build_menu("clip", indice, clip.clip_id)
    return next((a for a in menu.actions() if a.text() == strings.EDIT_REVERSE), None)


def test_video_e_audio_oferecem_inverter(panel):
    video, som = Clip(_video(), 0.0, 5.0), Clip(_audio(), 0.0, 5.0)
    projeto = _instala(panel, (TrackKind.VIDEO, [video]), (TrackKind.AUDIO, [som]))
    for clip in (video, som):
        acao = _acao(panel, projeto, clip)
        assert acao is not None and acao.isEnabled()
        assert acao.isCheckable() and not acao.isChecked()


def test_imagem_e_texto_nao_oferecem(panel):
    imagem = Clip(MediaRef(Path("foto.png"), MediaKind.IMAGE, width=100, height=100), 0.0, 5.0)
    texto = Clip(MediaRef(Path("Texto_a"), MediaKind.IMAGE, duration=5.0), 0.0, 5.0,
                 overlay_type=OverlayType.TEXT, text_content="olá")
    projeto = _instala(panel, (TrackKind.VIDEO, [imagem]), (TrackKind.ADDITIONAL, [texto]))
    assert _acao(panel, projeto, imagem) is None
    assert _acao(panel, projeto, texto) is None


def test_escolher_inverte_marca_e_desfaz_pelo_historico(panel):
    clip = Clip(_video(), 0.0, 5.0, in_point=2.0)
    projeto = _instala(panel, (TrackKind.VIDEO, [clip]))
    _acao(panel, projeto, clip).trigger()
    invertido = panel._project.find(clip.clip_id)[1]
    assert invertido.reversed
    assert (invertido.in_point, invertido.duration) == (clip.in_point, clip.duration)
    assert panel.has_unsaved_changes
    assert _acao(panel, panel._project, invertido).isChecked()

    _acao(panel, panel._project, invertido).trigger()
    assert not panel._project.find(clip.clip_id)[1].reversed

    panel._undo_edit()
    assert panel._project.find(clip.clip_id)[1].reversed
    panel._undo_edit()
    assert not panel._project.find(clip.clip_id)[1].reversed


def test_inverte_o_bloco_clicado_e_nao_o_selecionado(panel):
    a, b = Clip(_video(), 0.0, 5.0), Clip(_video(), 6.0, 5.0)
    projeto = _instala(panel, (TrackKind.VIDEO, [a, b]))
    panel._timeline.select(a.clip_id)
    _acao(panel, projeto, b).trigger()
    assert not panel._project.find(a.clip_id)[1].reversed
    assert panel._project.find(b.clip_id)[1].reversed


def test_bloco_longo_demais_aparece_desabilitado_com_o_motivo(panel):
    longo = Clip(_video(width=1920, height=1080), 0.0, 60.0)
    projeto = _instala(panel, (TrackKind.VIDEO, [longo]))
    acao = _acao(panel, projeto, longo)
    assert acao is not None and not acao.isEnabled()
    assert acao.toolTip() == strings.EDIT_REVERSE_TOO_LONG_TIP
    acao.trigger()  # desabilitada não dispara, e mesmo disparada não inverte
    panel._toggle_reverse(longo.clip_id)
    assert not panel._project.find(longo.clip_id)[1].reversed


def test_bloco_ja_invertido_sempre_pode_voltar_ao_normal(panel):
    longo = Clip(_video(width=1920, height=1080), 0.0, 60.0, reversed=True)
    projeto = _instala(panel, (TrackKind.VIDEO, [longo]))
    acao = _acao(panel, projeto, longo)
    assert acao.isEnabled() and acao.isChecked()
    acao.trigger()
    assert not panel._project.find(longo.clip_id)[1].reversed
