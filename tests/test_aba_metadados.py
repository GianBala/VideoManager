"""A aba Metadados reorganizada: cartão do arquivo, tags em duas colunas com o rótulo em cima e rodapé.

As partes delicadas da aba (a alça de ampliar, o ajuste das linhas da tabela, a regra das colunas) estão em
``test_metadata.py`` e não foram tocadas. Aqui fica o que é do arranjo novo: onde cada tag fica na grade, o que o
cartão do arquivo mostra em cada estado e o que o rodapé reúne.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.preferences import Preferences
from videomanager.bootstrap import build_desktop_runtime
from videomanager.domain import i18n
from videomanager.domain.metadata import COMMON_TAGS, FileMetadata, TrackInfo
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.panels.metadata_panel import MetadataPanel

_TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


def _meta(nome: str, streams) -> FileMetadata:
    tracks = tuple(TrackInfo(i, kind, codec, "", "und") for i, (kind, codec) in enumerate(streams))
    return FileMetadata(Path(f"/origem/{nome}"), "mov,mp4", 15.0, (("title", "Aurora"),), tracks, None, tuple(streams))


@pytest.fixture
def painel(desktop_app):
    instancia = MetadataPanel(Preferences(), lambda: _TOOLS, runtime=build_desktop_runtime(audio_enabled=False))
    instancia.resize(1100, 900)
    instancia.show()
    for _ in range(10):
        desktop_app.processEvents()
    yield instancia
    instancia.shutdown()
    instancia.deleteLater()
    apply_language(i18n.PORTUGUESE)


def _abrir(painel, desktop_app, nome="trilha.mp3", streams=(("audio", "mp3"),)) -> None:
    painel._install(_meta(nome, streams), None)
    for _ in range(10):
        desktop_app.processEvents()


def _pos(widget, ancestral):
    return widget.mapTo(ancestral, widget.rect().topLeft())


# -- tags -----------------------------------------------------------------------------------------------------

def test_as_tags_curtas_dividem_a_linha_e_as_longas_ocupam_a_linha_inteira(painel, desktop_app):
    _abrir(painel, desktop_app)
    campos = painel._fields
    for esquerda, direita in (("artist", "album"), ("album_artist", "date"), ("genre", "track"), ("disc", "composer")):
        assert _pos(campos[esquerda], painel).y() == _pos(campos[direita], painel).y(), (esquerda, direita)
        assert _pos(campos[esquerda], painel).x() < _pos(campos[direita], painel).x()
    for longa in ("title", "comment", "description", "copyright"):
        assert campos[longa].width() > 1.8 * campos["artist"].width(), longa
    # De cima para baixo, na ordem das tags.
    ordem = [_pos(campos[k], painel).y() for k in COMMON_TAGS]
    assert ordem == sorted(ordem)


def test_o_rotulo_de_cada_tag_fica_em_cima_do_campo_e_aponta_para_ele(painel, desktop_app):
    _abrir(painel, desktop_app)
    for chave, rotulo in zip(COMMON_TAGS, painel._labels):
        campo = painel._fields[chave]
        assert _pos(rotulo, painel).y() + rotulo.height() <= _pos(campo, painel).y(), chave
        assert rotulo.buddy() is campo
        assert campo.accessibleName() == strings.META_FIELDS[chave]


def test_as_tags_continuam_se_editando_e_marcam_alteracao(painel, desktop_app):
    _abrir(painel, desktop_app)
    assert not painel.has_unsaved_changes
    painel._fields["album"].setText("Novo")
    painel._fields["album"].textEdited.emit("Novo")
    assert painel.has_unsaved_changes
    assert dict(painel.current_edit().tags)["album"] == "Novo"


# -- cartão do arquivo ----------------------------------------------------------------------------------------

def test_sem_arquivo_so_ha_o_convite(painel):
    assert not painel._file_name.isVisibleTo(painel) and not painel._file_tile.isVisibleTo(painel)
    assert not painel._chip_format.isVisibleTo(painel)
    assert painel._info.text() == strings.META_DROP_HINT


def test_com_arquivo_o_cartao_mostra_nome_formato_e_duracao(painel, desktop_app):
    _abrir(painel, desktop_app, "trilha.mp3")
    assert painel._file_name.text() == "trilha.mp3" and painel._file_name.isVisibleTo(painel)
    assert painel._chip_format.text() == "MP3" and painel._chip_duration.text() == "0:15"
    assert painel._info.text() == strings.META_DROP_AGAIN
    audio = painel._file_tile.pixmap().toImage()
    _abrir(painel, desktop_app, "clipe.mp4", (("video", "h264"), ("audio", "aac")))
    assert painel._file_tile.pixmap().toImage() != audio  # música e vídeo têm ícones diferentes


def test_lendo_um_arquivo_o_cartao_diz_qual(painel):
    painel._loading = Path("/origem/grande.mp4")
    painel._refresh()
    assert painel._info.text() == strings.META_LOADING.format(name="grande.mp4")
    assert not painel._file_name.isVisibleTo(painel)
    painel._loading = None


def test_o_cartao_retraduz_o_convite(painel, desktop_app):
    _abrir(painel, desktop_app)
    apply_language(i18n.ENGLISH)
    assert painel._info.text() == strings.META_DROP_AGAIN == "or drop another video or audio file here"


# -- rodapé ---------------------------------------------------------------------------------------------------

def test_as_acoes_ficam_no_rodape_com_o_resultado_em_linha_propria(painel, desktop_app):
    _abrir(painel, desktop_app)
    assert painel._save.parent() is painel._discard.parent() or painel._save.parentWidget() is painel._discard.parentWidget()
    assert painel._discard.property("role") == "flat" and painel._save.property("role") == "primary"
    painel._saved = type("S", (), {"path": Path("/s/x.mp3"), "fallback_used": False, "not_saved": ()})()
    painel._refresh()
    assert painel._result.isVisibleTo(painel) and painel._result.text()
    # O resultado fica acima dos botões, não ao lado (texto que quebra ao lado de botões nasce cortado).
    assert _pos(painel._result, painel).y() + painel._result.height() <= _pos(painel._save, painel).y()
