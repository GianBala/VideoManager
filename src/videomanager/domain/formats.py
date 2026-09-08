"""Modelos de dados normalizados.

A fronteira entre o mundo caótico dos extratores e o resto da aplicação. Nada
fora de :mod:`videomanager.infrastructure.yt_dlp.formats` deve tocar num dicionário cru do yt-dlp: todo o
resto trabalha sobre :class:`Fmt`, :class:`VideoChoice`, :class:`AudioChoice` e
:class:`MediaInfo`, onde os campos ausentes já foram resolvidos ou marcados
explicitamente como desconhecidos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    """Natureza de um formato oferecido pelo extrator."""

    VIDEO_ONLY = "video"
    AUDIO_ONLY = "audio"
    MUXED = "muxed"
    NON_MEDIA = "non_media"  # storyboards, mhtml — nunca oferecidos ao usuário


class Mode(Enum):
    """O que o usuário quer obter da URL."""

    VIDEO = "video"
    AUDIO_ONLY = "audio"


@dataclass(frozen=True)
class Fmt:
    """Um formato do extrator, com os metadados já normalizados."""

    format_id: str
    ext: str
    kind: Kind
    vcodec: str | None = None
    acodec: str | None = None
    video_family: str | None = None
    audio_family: str | None = None
    height: int | None = None
    width: int | None = None
    height_is_estimated: bool = False
    fps: float | None = None
    tbr: float | None = None
    vbr: float | None = None
    abr: float | None = None
    asr: int | None = None
    filesize: int | None = None
    filesize_is_estimated: bool = False
    dynamic_range: str | None = None
    protocol: str | None = None
    language: str | None = None
    note: str | None = None
    has_drm: bool = False


    @property
    def effective_video_bitrate(self) -> float | None:
        """Melhor estimativa de bitrate de vídeo disponível."""
        return self.vbr or self.tbr

    @property
    def effective_audio_bitrate(self) -> float | None:
        """Melhor estimativa de bitrate de áudio disponível.

        Em formatos só-áudio, ``tbr`` é o bitrate do áudio, então serve de
        substituto quando ``abr`` vem vazio — o que é comum fora do YouTube.
        """
        if self.abr:
            return self.abr
        if self.kind is Kind.AUDIO_ONLY:
            return self.tbr
        return None


@dataclass(frozen=True)
class VideoChoice:
    """Uma linha de vídeo selecionável na interface.

    Agrupa formatos equivalentes (mesma resolução, framerate, família de codec e
    faixa dinâmica). ``formats`` está ordenado do melhor para o pior: o primeiro
    é o que será baixado e os seguintes alimentam a cadeia de degradação do
    seletor, para o caso de o extrator ter listado um formato que já saiu do ar.
    """

    height: int | None
    fps: int | None
    family: str | None
    dynamic_range: str | None
    formats: tuple[Fmt, ...]

    @property
    def best(self) -> Fmt:
        return self.formats[0]

    @property
    def is_muxed(self) -> bool:
        """Se o melhor formato do grupo já traz áudio embutido."""
        return self.best.kind is Kind.MUXED


@dataclass(frozen=True)
class AudioChoice:
    """Uma linha de áudio selecionável na interface."""

    family: str | None
    bitrate: float | None
    language: str | None
    formats: tuple[Fmt, ...]

    @property
    def best(self) -> Fmt:
        return self.formats[0]

    @property
    def is_extracted_from_video(self) -> bool:
        """Se o áudio vem de um arquivo mesclado, e não de trilha separada.

        Acontece em sites que não separam as trilhas: para obter o áudio é
        preciso baixar o vídeo inteiro e descartar a imagem depois.
        """
        return self.best.kind is Kind.MUXED


@dataclass(frozen=True)
class SubtitleTrack:
    lang: str
    name: str
    is_auto: bool


@dataclass(frozen=True)
class FormatMatrix:
    """Todas as opções utilizáveis de uma mídia, prontas para a interface."""

    video: tuple[VideoChoice, ...] = ()
    audio: tuple[AudioChoice, ...] = ()
    drm_blocked: tuple[Fmt, ...] = ()
    discarded: int = 0  # formatos não-mídia descartados (storyboards etc.)

    @property
    def has_video(self) -> bool:
        return bool(self.video)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio)

    @property
    def needs_muxing(self) -> bool:
        """Se a interface deve oferecer escolha separada de trilha de áudio.

        Falso quando o site só entrega formatos já mesclados — caso em que um
        seletor de áudio separado só confundiria, porque não há o que escolher.
        """
        return any(not choice.is_muxed for choice in self.video) and self.has_audio

    @property
    def is_empty(self) -> bool:
        return not self.video and not self.audio

    @property
    def best_audio_bitrate(self) -> float | None:
        """Maior bitrate de áudio disponível na origem.

        A interface usa isto para avisar quando o usuário pede um MP3 de 320 kbps
        de uma fonte que só tem 128: o arquivo fica maior sem ganhar qualidade.
        """
        rates = [choice.bitrate for choice in self.audio if choice.bitrate]
        return max(rates) if rates else None


@dataclass(frozen=True)
class MediaInfo:
    """Uma mídia analisada e pronta para ser enfileirada."""

    url: str
    title: str
    matrix: FormatMatrix
    media_id: str = ""
    extractor: str = ""
    uploader: str = ""
    duration: float | None = None
    thumbnail_url: str = ""
    is_live: bool = False
    subtitles: tuple[SubtitleTrack, ...] = ()


@dataclass(frozen=True)
class PlaylistEntry:
    """Item de uma playlist, ainda não analisado em detalhe."""

    url: str
    title: str
    index: int
    media_id: str = ""
    duration: float | None = None


@dataclass(frozen=True)
class PlaylistInfo:
    url: str
    title: str
    entries: tuple[PlaylistEntry, ...]
    extractor: str = ""
    uploader: str = ""
