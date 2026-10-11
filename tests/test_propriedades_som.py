"""A aba Propriedades por tipo de bloco: o que aparece para vídeo, áudio, imagem, texto, filtro e transição.

A espécie é do bloco, não da mídia dele. O bloco que "separar áudio" cria vem de um arquivo com
imagem e mesmo assim é áudio: decidir pela mídia mostrava, nele, o Fundo Verde (de um bloco que
não tem imagem). Nenhum desses erros levanta exceção: a seção errada simplesmente aparece.
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget

pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    instance = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                         processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    yield instance
    instance.shutdown()


def _video(audio=True) -> MediaRef:
    return MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=10.0, width=1280, height=720, fps=30.0,
                    has_audio=audio, channels=2)


def _som() -> MediaRef:
    return MediaRef(Path("/m/som.mp3"), MediaKind.AUDIO, duration=10.0, has_audio=True, channels=2)


def _rotulo() -> MediaRef:
    return MediaRef(Path("Rótulo"), MediaKind.IMAGE, duration=3.0)


# Cada tipo de bloco e o que a aba tem de mostrar para ele (ver a tabela do relatório da revisão).
BLOCOS = {
    "video_com_som": lambda: Clip(_video(), 0.0, 5.0),
    "video_sem_som": lambda: Clip(_video(audio=False), 0.0, 5.0),
    "video_com_audio_separado": lambda: Clip(_video(), 0.0, 5.0, detached=True),
    "audio_separado": lambda: Clip(_video(), 0.0, 5.0, audio_only=True),
    "audio_puro": lambda: Clip(_som(), 0.0, 5.0),
    "imagem": lambda: Clip(MediaRef(Path("/m/foto.jpg"), MediaKind.IMAGE, width=800, height=600), 0.0, 5.0),
    "texto": lambda: Clip(_rotulo(), 0.0, 3.0, overlay_type="text", text_content="oi"),
    "filtro": lambda: Clip(_rotulo(), 0.0, 3.0, overlay_type="filter", filter_name="sepia"),
    "transicao": lambda: Clip(_rotulo(), 0.0, 1.0, overlay_type="transition", transition_name="fade"),
}


def _carregado(nome: str) -> _ClipPropertiesWidget:
    widget = _ClipPropertiesWidget()
    widget.load_clip(BLOCOS[nome](), 1920, 1080)
    return widget


@pytest.mark.parametrize(("nome", "fundo_verde", "desfoque"), [
    ("video_com_som", True, True),
    ("video_sem_som", True, True),
    ("video_com_audio_separado", True, True),
    ("audio_separado", False, False),      # era o defeito: a mídia tem imagem, o bloco não
    ("audio_puro", False, False),
    ("imagem", True, True),
    ("texto", False, False),
    ("filtro", False, False),
    ("transicao", False, False),
])
def test_fundo_verde_e_desfoque_so_aparecem_onde_ha_imagem(nome, fundo_verde, desfoque):
    widget = _carregado(nome)
    assert (not widget._chromakey_group.isHidden()) is fundo_verde, nome
    assert (not widget._blur_group.isHidden()) is desfoque, nome
    widget.deleteLater()


def test_propriedades_do_audio_separado_pelo_menu_nao_mostram_fundo_verde(panel):
    video = _video()
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0.0, 5.0),)),))
    projeto = projeto.detached_audio(projeto.clips[0].clip_id)
    separado = next(c for c in projeto.clips if c.audio_only)
    panel.install_project(projeto, None, [], {})

    indice, _ = projeto.find(separado.clip_id)
    menu = panel.build_menu("clip", indice, separado.clip_id)
    next(a for a in menu.actions() if a.text() == strings.EDIT_PROPERTIES).trigger()

    assert panel._properties_widget._chromakey_group.isHidden()
    assert panel._properties_widget._blur_group.isHidden()
