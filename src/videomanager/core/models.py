"""Modelos de dados normalizados.

A fronteira entre o mundo caótico dos extratores e o resto da aplicação. Nada
fora de :mod:`format_matrix` deve tocar num dicionário cru do yt-dlp: todo o
resto trabalha sobre :class:`Fmt`, :class:`VideoChoice`, :class:`AudioChoice` e
:class:`MediaInfo`, onde os campos ausentes já foram resolvidos ou marcados
explicitamente como desconhecidos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .humanize import DASH, format_bitrate, format_fps, format_size


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
    def size_label(self) -> str:
        return format_size(self.filesize, estimated=self.filesize_is_estimated)

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

    @property
    def resolution_label(self) -> str:
        """Resolução para exibição.

        Quando o extrator não informa altura — comum em HLS — mostramos o
        bitrate em vez de inventar uma resolução. É honesto e ainda permite ao
        usuário ordenar por qualidade.
        """
        if self.height is None:
            return format_bitrate(self.best.tbr)
        suffix = "" if self.fps is None or self.fps <= 30 else str(self.fps)
        approx = "~" if self.best.height_is_estimated else ""
        return f"{approx}{self.height}p{suffix}"

    @property
    def label(self) -> str:
        parts = [self.resolution_label]
        if self.family:
            parts.append(self.family)
        if self.dynamic_range:
            parts.append(self.dynamic_range)
        size = self.best.size_label
        if size != DASH:
            parts.append(size)
        return " · ".join(parts)


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

    @property
    def label(self) -> str:
        parts: list[str] = []
        rate = format_bitrate(self.bitrate)
        if rate != DASH:
            parts.append(rate)
        # Sempre identifica o áudio em si. Quando o codec é desconhecido a
        # extensão é a única pista disponível, e um rótulo só com o idioma
        # ("en") não diria nada sobre o que se vai baixar.
        parts.append(self.family or self.best.ext.upper())
        if self.language:
            parts.append(self.language)
        if self.is_extracted_from_video:
            # Sem este aviso o tamanho exibido parece um erro: o usuário pediu
            # áudio e vê centenas de MB. Dizer de onde vem explica o número.
            source = f"{self.best.height}p" if self.best.height else self.best.ext.upper()
            parts.append(f"extraído do vídeo {source}")
        size = self.best.size_label
        if size != DASH:
            parts.append(size)
        return " · ".join(parts)


@dataclass(frozen=True)
class SubtitleTrack:
    lang: str
    name: str
    is_auto: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.lang})" + (" [automática]" if self.is_auto else "")


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
    # Preservado para o download: alguns extratores guardam estado na info
    # (tokens, URLs assinadas) que se perde se reanalisarmos a URL depois.
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def duration_label(self) -> str:
        from .humanize import format_duration

        return format_duration(self.duration)

    @property
    def fps_label(self) -> str:
        best = self.matrix.video[0] if self.matrix.video else None
        return format_fps(float(best.fps)) if best and best.fps else DASH


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
