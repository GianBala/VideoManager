"""Regras de formato dos metadados: onde moram as tags, a capa e o nome da trilha."""
from pathlib import Path

import pytest

from videomanager.domain.metadata import FileMetadata
from videomanager.domain.metadata import MetadataEdit
from videomanager.domain.metadata import TrackInfo
from videomanager.domain.metadata import editable_tags
from videomanager.domain.metadata import unchanged_edit


def _meta(nome: str, formato: str = "x") -> FileMetadata:
    return FileMetadata(Path(f"/origem/{nome}"), formato, 10.0,
                        (("title", "T"), ("encoder", "Lavf"), ("major_brand", "isom"), ("meu_campo", "v")),
                        (TrackInfo(0, "video", "h264", "V", "und"), TrackInfo(1, "audio", "aac", "", "eng")),
                        streams=(("video", "h264"), ("audio", "aac")))


@pytest.mark.parametrize(("nome", "capa", "anexo"), [
    ("a.mp4", True, False), ("a.m4a", True, False), ("a.mp3", True, False), ("a.flac", True, False),
    ("a.mkv", True, True), ("a.MKA", True, True),
    # Medido: recusam a imagem (Ogg, Opus, WebM, WAV) ou a guardam como trilha de
    # vídeo de um quadro (MOV, AVI).
    ("a.ogg", False, False), ("a.opus", False, False), ("a.webm", False, False), ("a.wav", False, False),
    ("a.mov", False, False), ("a.avi", False, False),
])
def test_capa_por_formato(nome, capa, anexo):
    meta = _meta(nome)
    assert (meta.accepts_cover, meta.cover_as_attachment) == (capa, anexo)


def test_titulo_da_trilha_no_mp4_e_o_handler_name():
    assert _meta("a.mp4").track_title_key == "handler_name"
    assert _meta("a.mov").track_title_key == "handler_name"
    assert _meta("a.mkv").track_title_key == "title"


def test_ogg_e_opus_guardam_as_tags_na_trilha():
    assert _meta("a.opus", "ogg").tags_on_stream
    assert _meta("a.ogg", "ogg").tags_on_stream
    assert not _meta("a.mkv", "matroska,webm").tags_on_stream


def test_tags_geradas_pelo_formato_nao_se_editam():
    assert editable_tags(_meta("a.mp4")) == (("title", "T"), ("meu_campo", "v"))


def test_edicao_sem_mudanca_e_o_ponto_de_partida():
    meta = _meta("a.mp4")
    assert unchanged_edit(meta) == MetadataEdit(
        (("title", "T"), ("meu_campo", "v")), ((0, "V", "und"), (1, "", "eng")))


def test_copia_sai_no_mesmo_formato():
    assert _meta("Filme.MKV").extension == "mkv"
