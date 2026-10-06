"""Metadados de um arquivo, como a aba Metadados os lê, edita e grava numa cópia.

Cada formato guarda uma parte diferente do que se pede, e isso foi medido
gravando os mesmos campos em onze formatos: o MKV e o WebM guardam tudo; o MP4
descarta campo livre e título de faixa; o MOV e o AVI descartam até campos
comuns; o MP3 não tem título nem idioma por faixa. Por isso a gravação confere
a cópia e diz o que não ficou, em vez de prometer por uma tabela. As regras
abaixo são só as que mudam **como** se grava.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Os campos que ganham um rótulo próprio na aba; qualquer outro vai na lista
# de campos livres. São os nomes que o ffmpeg traduz para cada formato (frame
# ID3, átomo do MP4, comentário Vorbis, tag do Matroska).
COMMON_TAGS = (
    "title", "artist", "album", "album_artist", "date", "genre",
    "track", "disc", "composer", "comment", "description", "copyright",
)

# Reescritos pelo muxer a cada gravação: editar não teria efeito, e mostrar como
# editável prometeria o que a cópia não entrega.
GENERATED_TAGS = frozenset({"encoder", "major_brand", "minor_version", "compatible_brands"})

# Formatos em que a capa é uma imagem marcada como capa (``attached_pic``), e em
# que o Matroska a guarda como anexo. Nos outros, medido: Ogg, Opus, WebM e WAV
# recusam a imagem, e MOV e AVI a aceitam como uma trilha de vídeo de um quadro
# — um defeito, não uma capa.
_PICTURE_COVER = frozenset({".mp4", ".m4a", ".m4v", ".mp3", ".flac"})
_ATTACHED_COVER = frozenset({".mkv", ".mka"})
_MP4_FAMILY = frozenset({".mp4", ".m4a", ".m4v", ".mov"})


@dataclass(frozen=True)
class TrackInfo:
    index: int  # no arquivo de origem
    kind: str
    codec: str
    title: str = ""
    language: str = ""


@dataclass(frozen=True)
class CoverInfo:
    index: int
    # "picture": trilha marcada como capa, extraída copiando o pacote;
    # "attachment": anexo do Matroska que o ffmpeg não expõe como imagem (WebP).
    stream: str
    mimetype: str = ""
    filename: str = ""


@dataclass(frozen=True)
class FileMetadata:
    path: Path
    format_name: str
    duration: float | None
    tags: tuple[tuple[str, str], ...]
    # As faixas que se editam: sem a capa e sem anexos (fontes de legenda).
    tracks: tuple[TrackInfo, ...]
    cover: CoverInfo | None = None
    # (tipo, codec) de cada trilha, na ordem do arquivo: é o que a cópia tem de
    # repetir, fora a capa, e o que situa cada trilha no comando.
    streams: tuple[tuple[str, str], ...] = ()

    @property
    def extension(self) -> str:
        # Também serve de alvo a ``output_path``: a cópia sai no mesmo formato.
        return self.path.suffix.lstrip(".").lower()

    @property
    def tags_on_stream(self) -> bool:
        """No Ogg e no Opus as tags do arquivo moram na trilha de áudio.

        Medido: gravadas no arquivo, nenhuma ficou; na trilha, todas, inclusive
        campo livre. Nesses formatos o título da faixa **é** o título do
        arquivo, e as faixas não se editam à parte.
        """
        return "ogg" in self.format_name.split(",")

    @property
    def accepts_cover(self) -> bool:
        return self.path.suffix.lower() in _PICTURE_COVER | _ATTACHED_COVER

    @property
    def cover_as_attachment(self) -> bool:
        return self.path.suffix.lower() in _ATTACHED_COVER

    @property
    def track_title_key(self) -> str:
        """O MP4 e o MOV guardam o nome da faixa em ``handler_name``, não em ``title``."""
        return "handler_name" if self.path.suffix.lower() in _MP4_FAMILY else "title"


@dataclass(frozen=True)
class MetadataEdit:
    """O estado desejado: as tags do arquivo inteiras, e não só as diferenças."""

    tags: tuple[tuple[str, str], ...]
    # (índice na origem, título, idioma)
    tracks: tuple[tuple[int, str, str], ...] = ()
    cover_image: Path | None = None
    remove_cover: bool = False


@dataclass(frozen=True)
class SavedCopy:
    path: Path
    # O que se pediu e a cópia não guardou, como a aba o mostra ("meu_campo",
    # "faixa 2: título").
    not_saved: tuple[str, ...] = field(default=())
    fallback_used: bool = False


def editable_tags(meta: FileMetadata) -> tuple[tuple[str, str], ...]:
    return tuple((key, value) for key, value in meta.tags if key.lower() not in GENERATED_TAGS)
