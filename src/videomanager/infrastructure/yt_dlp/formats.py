"""Normalização dos formatos crus do yt-dlp para opções selecionáveis.

Este é o módulo mais importante da aplicação. Cada extrator do yt-dlp devolve uma
estrutura diferente, e a diferença não é cosmética:

* O YouTube entrega DASH com vídeo e áudio separados, vários codecs por
  resolução, HDR, e uma pilha de storyboards em ``mhtml`` que não são mídia.
* Muitos sites entregam apenas HLS, frequentemente **sem** ``height`` e sem
  ``fps`` — só um ``tbr``.
* Outros entregam um único formato já mesclado.
* Alguns marcam formatos com ``has_drm``, que aparecem na listagem e falham no
  meio do download se forem escolhidos.

A regra que orienta tudo aqui: **nunca confiar num campo e nunca deixar um
palpite sobrescrever um valor declarado**. Um campo ausente é uma informação a
exibir como desconhecida, não um motivo para levantar exceção nem para inventar
um valor plausível. Palpites (inclusive a partir da extensão) só entram onde o
extrator não declarou nada — ver :func:`classify`.

Uma distinção sustenta isso e é fácil de perder de vista: ``"vcodec": "none"``
significa *"conferi, não há trilha de vídeo"*, enquanto a **ausência** da chave
``vcodec`` significa *"não sei"*. Tratar as duas como a mesma coisa descarta
mídia perfeitamente baixável — o archive.org não declara codec algum, e o HLS da
Apple declara ``vcodec`` mas omite ``acodec`` nas faixas de áudio.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from enum import Enum
from typing import Any

from videomanager.domain.formats import AudioChoice
from videomanager.domain.formats import Fmt
from videomanager.domain.formats import FormatMatrix
from videomanager.domain.formats import Kind
from videomanager.domain.formats import VideoChoice

from videomanager.domain.format_policy import pick_video as pick_video
from videomanager.domain.format_policy import find_video as find_video
from videomanager.domain.format_policy import pick_audio as pick_audio
from videomanager.domain.format_policy import available_heights as available_heights
from videomanager.domain.format_policy import available_fps as available_fps
from videomanager.domain.format_policy import available_families as available_families

# --- famílias de codec -------------------------------------------------------
# Casadas por prefixo, porque os valores reais carregam perfil e nível
# ("avc1.640028", "vp09.00.50.08", "mp4a.40.2"). A ordem importa: prefixos mais
# longos primeiro, para "vp09" não ser capturado por uma entrada "vp0".

_VIDEO_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("avc1", "avc2", "avc3", "avc4", "h264", "h.264", "x264"), "H.264"),
    (("hev1", "hvc1", "hevc", "h265", "h.265", "x265"), "HEVC"),
    (("av01", "av1"), "AV1"),
    (("vp09", "vp9"), "VP9"),
    (("vp08", "vp8"), "VP8"),
    (("theora",), "Theora"),
    (("mp4v", "mpeg4", "divx", "xvid"), "MPEG-4"),
    (("mpeg2", "mpeg1"), "MPEG-2"),
    (("dvh1", "dvhe"), "Dolby Vision"),
)

_AUDIO_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("mp4a", "aac"), "AAC"),
    (("opus",), "Opus"),
    (("vorbis",), "Vorbis"),
    (("ec-3", "eac3"), "E-AC-3"),
    (("ac-3", "ac3"), "AC-3"),
    (("mp3", "mp4a.69", "mp4a.6b"), "MP3"),
    (("flac",), "FLAC"),
    (("alac",), "ALAC"),
    (("dts",), "DTS"),
    (("pcm", "wav"), "PCM"),
)

# Faixa dinâmica: "SDR" é o caso comum e não precisa poluir o rótulo.
_TRIVIAL_DYNAMIC_RANGE = {"", "sdr", "none", "unknown"}

# Ordem de preferência entre codecs de vídeo da mesma resolução. H.264 primeiro
# porque é o que reproduz em qualquer lugar e remuxa direto para MP4 sem
# recodificar; os mais eficientes vêm depois. Isto só ordena dentro de um mesmo
# grupo de resolução, então nenhuma opção fica escondida.
from videomanager.domain.format_policy import _VIDEO_FAMILY_RANK

_AUDIO_FAMILY_RANK = {"AAC": 0, "Opus": 1, "Vorbis": 2, "MP3": 3}


# ---------------------------------------------------------------------------
# Conversores tolerantes
# ---------------------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    """Converte para int aceitando str e float; ``None`` em qualquer falha."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def normalize_codec(value: Any) -> str | None:
    """Limpa uma string de codec. ``none`` e vazio viram ``None``."""
    text = _as_text(value).strip().lower()
    if text in ("", "none", "null", "unknown", "?"):
        return None
    return text


def _family(codec: str | None, table: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    if not codec:
        return None
    for prefixes, name in table:
        if codec.startswith(prefixes):
            return name
    # Codec desconhecido: devolve a primeira parte em maiúsculas em vez de
    # ``None``, para o usuário ao menos ver com o que está lidando.
    return codec.split(".")[0].upper()


def video_family(codec: str | None) -> str | None:
    return _family(codec, _VIDEO_FAMILIES)


def video_family_filter(family: str | None) -> str:
    """Filtro do yt-dlp que restringe a família de codec, ou ``""``.

    Sai da mesma tabela que dá nome à família, para que o que a interface
    mostra e o que o yt-dlp procura nunca discordem.
    """
    for prefixes, name in _VIDEO_FAMILIES:
        if name == family:
            alternativas = "|".join(re.escape(prefix) for prefix in prefixes)
            return f"[vcodec~='^({alternativas})']"
    return ""


def audio_family(codec: str | None) -> str | None:
    return _family(codec, _AUDIO_FAMILIES)


# ---------------------------------------------------------------------------
# Cadeias de fallback dos metadados
# ---------------------------------------------------------------------------

_RESOLUTION_RE = re.compile(r"(\d{2,5})\s*[x×]\s*(\d{2,5})")
# Sem \b depois do "p": em "1080p60" não existe fronteira de palavra entre
# "p" e "6", e exigir uma quebraria justamente o caso mais comum.
_HEIGHT_RE = re.compile(r"(\d{3,4})\s*[pPiI](?![a-zA-Z])")
_FPS_RE = re.compile(r"(\d{2,3})\s*fps", re.IGNORECASE)
_HEIGHT_FPS_RE = re.compile(r"\d{3,4}[pP](\d{2,3})")

_TEXT_HINT_KEYS = ("format_note", "format", "format_id", "resolution")


def _hint_text(raw: dict[str, Any]) -> str:
    return " ".join(_as_text(raw.get(key)) for key in _TEXT_HINT_KEYS)


def extract_height(raw: dict[str, Any]) -> tuple[int | None, bool]:
    """Descobre a altura do vídeo. Devolve ``(altura, foi_estimada)``.

    Cadeia: campo ``height`` → ``resolution`` ("1920x1080") → um "1080p" solto
    no texto descritivo → estimativa a partir da largura assumindo 16:9.
    """
    height = _as_int(raw.get("height"))
    if height:
        return height, False

    match = _RESOLUTION_RE.search(_as_text(raw.get("resolution")))
    if match:
        parsed = _as_int(match.group(2))
        if parsed:
            return parsed, False

    match = _HEIGHT_RE.search(_hint_text(raw))
    if match:
        parsed = _as_int(match.group(1))
        # Faixa de sanidade: descarta coisas como um id de formato "2160" que
        # não seja resolução, e alturas absurdas.
        if parsed and 100 <= parsed <= 8000:
            return parsed, False

    width = _as_int(raw.get("width"))
    if width:
        return int(round(width * 9 / 16)), True

    return None, False


def extract_fps(raw: dict[str, Any]) -> float | None:
    """Descobre o framerate: campo ``fps`` → "60fps" no texto → "1080p60"."""
    fps = _as_float(raw.get("fps"))
    if fps:
        return fps

    text = _hint_text(raw)
    match = _FPS_RE.search(text)
    if match:
        parsed = _as_float(match.group(1))
        if parsed and parsed <= 480:
            return parsed

    match = _HEIGHT_FPS_RE.search(text)
    if match:
        parsed = _as_float(match.group(1))
        if parsed and 12 <= parsed <= 480:
            return parsed

    return None


def extract_filesize(raw: dict[str, Any]) -> tuple[int | None, bool]:
    """Tamanho do arquivo. Devolve ``(bytes, é_estimativa)``."""
    exact = _as_int(raw.get("filesize"))
    if exact:
        return exact, False
    approx = _as_int(raw.get("filesize_approx"))
    if approx:
        return approx, True
    return None, False


def _dynamic_range(raw: dict[str, Any]) -> str | None:
    text = _as_text(raw.get("dynamic_range")).strip()
    if text.lower() in _TRIVIAL_DYNAMIC_RANGE:
        return None
    return text


def _language(raw: dict[str, Any]) -> str | None:
    text = _as_text(raw.get("language")).strip()
    return text or None


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------


class _Presence(Enum):
    """Se uma trilha existe, não existe, ou o extrator não informou."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


# Extensões usadas só como última evidência, quando o extrator não declarou
# codec nenhum. Nunca sobrescrevem um valor declarado.
_AUDIO_EXTS = {
    "mp3", "m4a", "aac", "opus", "ogg", "oga", "flac", "wav", "alac",
    "weba", "mka", "aiff", "ac3", "dts", "wma", "vorbis",
}
_VIDEO_EXTS = {
    "mp4", "mkv", "webm", "avi", "mov", "flv", "ogv", "3gp", "wmv",
    "mpg", "mpeg", "m4v", "ts", "mts", "m2ts", "asf", "divx", "vob",
}


def _presence(raw: dict[str, Any], key: str, codec: str | None) -> _Presence:
    """Distingue "não tem" de "não informado".

    Se o codec normalizou para um valor, a trilha existe. Se a chave está
    presente mas normalizou para ``None``, o extrator afirmou que a trilha não
    existe. Se a chave nem está lá, não sabemos.
    """
    if codec is not None:
        return _Presence.YES
    return _Presence.NO if key in raw else _Presence.UNKNOWN


def _infer_presence(
    raw: dict[str, Any], video: _Presence, audio: _Presence
) -> tuple[_Presence, _Presence]:
    """Completa o que o extrator não declarou, usando outras evidências.

    A ordem das evidências vai da mais confiável para a menos: a marcação
    explícita ``audio only`` que o yt-dlp coloca em ``resolution``, depois a
    existência de dimensões de imagem, e só então a extensão do arquivo.
    """
    hints = f"{_as_text(raw.get('resolution'))} {_as_text(raw.get('format_note'))}".lower()
    audio_only_hint = "audio only" in hints
    video_only_hint = "video only" in hints
    has_dimensions = bool(_as_int(raw.get("height")) or _as_int(raw.get("width")))
    ext = _as_text(raw.get("ext")).lower()

    if video is _Presence.UNKNOWN:
        if audio_only_hint or ext in _AUDIO_EXTS:
            video = _Presence.NO
        elif has_dimensions or ext in _VIDEO_EXTS:
            video = _Presence.YES
        else:
            video = _Presence.NO

    if audio is _Presence.UNKNOWN:
        if video_only_hint:
            audio = _Presence.NO
        elif audio_only_hint or ext in _AUDIO_EXTS:
            audio = _Presence.YES
        elif video is _Presence.YES and (has_dimensions or ext in _VIDEO_EXTS):
            # Arquivo de vídeo completo servido direto (archive.org, servidores
            # próprios): quem publica um .mp4 avulso praticamente sempre inclui
            # áudio. Tratar como mesclado é a leitura certa — e se por acaso não
            # houver áudio, o resultado é o mesmo arquivo, sem prejuízo.
            audio = _Presence.YES
        else:
            # Sem nenhuma evidência, não inventamos uma trilha de áudio.
            audio = _Presence.NO

    return video, audio


def classify(raw: dict[str, Any], vcodec: str | None, acodec: str | None) -> Kind:
    """Decide o que um formato é.

    Storyboards do YouTube são o caso a barrar: chegam como ``mhtml`` sem codec
    algum e, se vazarem para a interface, aparecem como se fossem resoluções
    baixinhas selecionáveis.
    """
    if _as_text(raw.get("ext")).lower() == "mhtml":
        return Kind.NON_MEDIA
    if _as_text(raw.get("protocol")).lower() == "mhtml":
        return Kind.NON_MEDIA
    if "storyboard" in _as_text(raw.get("format_note")).lower():
        return Kind.NON_MEDIA

    video = _presence(raw, "vcodec", vcodec)
    audio = _presence(raw, "acodec", acodec)
    if _Presence.UNKNOWN in (video, audio):
        video, audio = _infer_presence(raw, video, audio)

    if video is _Presence.YES and audio is _Presence.YES:
        return Kind.MUXED
    if video is _Presence.YES:
        return Kind.VIDEO_ONLY
    if audio is _Presence.YES:
        return Kind.AUDIO_ONLY
    return Kind.NON_MEDIA


def parse_format(raw: dict[str, Any]) -> Fmt | None:
    """Converte um dicionário cru num :class:`Fmt`.

    Devolve ``None`` para entradas sem ``format_id`` — sem ele não há como pedir
    o formato ao yt-dlp depois, então a entrada é inútil.
    """
    format_id = _as_text(raw.get("format_id")).strip()
    if not format_id:
        return None

    vcodec = normalize_codec(raw.get("vcodec"))
    acodec = normalize_codec(raw.get("acodec"))
    kind = classify(raw, vcodec, acodec)

    height, height_estimated = extract_height(raw)
    filesize, size_estimated = extract_filesize(raw)

    return Fmt(
        format_id=format_id,
        ext=_as_text(raw.get("ext")).lower() or "bin",
        kind=kind,
        vcodec=vcodec,
        acodec=acodec,
        video_family=video_family(vcodec),
        audio_family=audio_family(acodec),
        height=height if kind is not Kind.AUDIO_ONLY else None,
        width=_as_int(raw.get("width")),
        height_is_estimated=height_estimated,
        fps=extract_fps(raw) if kind is not Kind.AUDIO_ONLY else None,
        tbr=_as_float(raw.get("tbr")),
        vbr=_as_float(raw.get("vbr")),
        abr=_as_float(raw.get("abr")),
        asr=_as_int(raw.get("asr")),
        filesize=filesize,
        filesize_is_estimated=size_estimated,
        dynamic_range=_dynamic_range(raw),
        protocol=_as_text(raw.get("protocol")) or None,
        language=_language(raw),
        note=_as_text(raw.get("format_note")) or None,
        has_drm=bool(raw.get("has_drm")),
    )


# ---------------------------------------------------------------------------
# Agrupamento
# ---------------------------------------------------------------------------


def _quality_key(fmt: Fmt) -> tuple:
    """Ordena formatos equivalentes, do melhor para o pior.

    Formato com áudio e vídeo separados vem antes do já mesclado na mesma
    resolução: o mesclado costuma carregar um áudio pior e fixo, enquanto o
    separado pode ser pareado com a melhor trilha disponível.
    """
    kind_rank = 0 if fmt.kind is Kind.VIDEO_ONLY else 1
    return (
        kind_rank,
        -(fmt.filesize or 0),
        -(fmt.effective_video_bitrate or 0),
        -(fmt.tbr or 0),
    )


def _audio_quality_key(fmt: Fmt) -> tuple:
    """Ordena trilhas de áudio equivalentes, da melhor para a pior.

    O caso sutil é o do bitrate desconhecido numa fonte **mesclada**: ali o
    tamanho do arquivo é dominado pelo vídeo, que vai ser descartado depois da
    extração. Preferir o maior arquivo faria o usuário baixar centenas de MB
    para obter o mesmo áudio que vem no arquivo pequeno — no archive.org, 332 MB
    em vez de 45 MB pelo mesmo MP3. Então, sem informação de bitrate e com fonte
    mesclada, o menor arquivo é a escolha certa.
    """
    kind_rank = 0 if fmt.kind is Kind.AUDIO_ONLY else 1
    # O YouTube publica variantes "DRC" (compressão de faixa dinâmica) com
    # bitrate e tamanho idênticos aos da trilha normal. Como empatam em tudo, o
    # desempate ficava arbitrário — e a DRC soa achatada, com os picos nivelados.
    # Preferimos a trilha original.
    drc_rank = 1 if _is_drc(fmt) else 0
    bitrate = fmt.effective_audio_bitrate
    if bitrate:
        return (kind_rank, -bitrate, drc_rank, -(fmt.filesize or 0), -(fmt.asr or 0))
    if fmt.kind is Kind.MUXED:
        return (kind_rank, 0.0, drc_rank, fmt.filesize or 0, -(fmt.asr or 0))
    return (kind_rank, 0.0, drc_rank, -(fmt.filesize or 0), -(fmt.asr or 0))


def _is_drc(fmt: Fmt) -> bool:
    return "drc" in fmt.format_id.lower() or "drc" in (fmt.note or "").lower()


def _fps_bucket(fps: float | None) -> int | None:
    """Agrupa 29,97 com 30 e 59,94 com 60 — a diferença não é escolha do usuário."""
    if fps is None:
        return None
    return int(round(fps))


def _bitrate_bucket(bitrate: float | None) -> int | None:
    """Agrupa bitrates próximos para não gerar dezenas de linhas quase iguais."""
    if bitrate is None:
        return None
    return int(round(bitrate / 8.0) * 8)


def _build_video_choices(formats: list[Fmt]) -> tuple[VideoChoice, ...]:
    candidates = [f for f in formats if f.kind in (Kind.VIDEO_ONLY, Kind.MUXED) and not f.has_drm]
    groups: OrderedDict[tuple, list[Fmt]] = OrderedDict()
    for fmt in candidates:
        key = (fmt.height, _fps_bucket(fmt.fps), fmt.video_family, fmt.dynamic_range)
        groups.setdefault(key, []).append(fmt)

    choices: list[VideoChoice] = []
    for (height, fps, family, dynamic_range), members in groups.items():
        members.sort(key=_quality_key)
        choices.append(
            VideoChoice(
                height=height,
                fps=fps,
                family=family,
                dynamic_range=dynamic_range,
                formats=tuple(members),
            )
        )

    # Melhor primeiro: resolução, depois framerate, depois compatibilidade do
    # codec. Alturas desconhecidas vão para o fim, ordenadas por bitrate — é o
    # único sinal de qualidade que sobra nesses casos.
    def sort_key(choice: VideoChoice) -> tuple:
        return (
            0 if choice.height is not None else 1,
            -(choice.height or 0),
            -(choice.fps or 0),
            _VIDEO_FAMILY_RANK.get(choice.family or "", 90),
            -(choice.best.tbr or 0),
        )

    choices.sort(key=sort_key)
    return tuple(choices)


def _build_audio_choices(formats: list[Fmt]) -> tuple[AudioChoice, ...]:
    candidates = [f for f in formats if f.kind is Kind.AUDIO_ONLY and not f.has_drm]
    # Sem trilhas separadas, os formatos mesclados servem de fonte de áudio —
    # é como "somente áudio" funciona em sites que não separam as trilhas.
    if not candidates:
        candidates = [f for f in formats if f.kind is Kind.MUXED and not f.has_drm]

    groups: OrderedDict[tuple, list[Fmt]] = OrderedDict()
    for fmt in candidates:
        key = (
            fmt.audio_family,
            _bitrate_bucket(fmt.effective_audio_bitrate),
            fmt.language,
        )
        groups.setdefault(key, []).append(fmt)

    choices: list[AudioChoice] = []
    for (family, _bucket, language), members in groups.items():
        members.sort(key=_audio_quality_key)
        choices.append(
            AudioChoice(
                family=family,
                bitrate=members[0].effective_audio_bitrate,
                language=language,
                formats=tuple(members),
            )
        )

    choices.sort(
        key=lambda c: (
            -(c.bitrate or 0),
            _AUDIO_FAMILY_RANK.get(c.family or "", 90),
            c.language or "",
        )
    )
    return tuple(choices)


def build_matrix(raw_formats: Any) -> FormatMatrix:
    """Constrói a matriz de opções a partir de ``info['formats']``.

    Nunca levanta exceção por dado malformado: entradas irreconhecíveis são
    contadas em ``discarded`` e ignoradas. Se o resultado vier vazio, quem chama
    decide o que dizer ao usuário — este módulo não sabe se o problema foi DRM,
    uma live ou um extrator quebrado.
    """
    if not isinstance(raw_formats, list):
        return FormatMatrix()

    parsed: list[Fmt] = []
    discarded = 0
    for entry in raw_formats:
        if not isinstance(entry, dict):
            discarded += 1
            continue
        fmt = parse_format(entry)
        if fmt is None or fmt.kind is Kind.NON_MEDIA:
            discarded += 1
            continue
        parsed.append(fmt)

    drm_blocked = tuple(f for f in parsed if f.has_drm)

    return FormatMatrix(
        video=_build_video_choices(parsed),
        audio=_build_audio_choices(parsed),
        drm_blocked=drm_blocked,
        discarded=discarded,
    )


# ---------------------------------------------------------------------------
# Busca dentro da matriz (usada pela interface ao aplicar padrões e perfis)
# ---------------------------------------------------------------------------


__all__ = [
    'pick_video',
    'find_video',
    'pick_audio',
    'available_heights',
    'available_fps',
    'available_families',
    'AudioChoice',
    'Fmt',
    'FormatMatrix',
    'Kind',
    'VideoChoice',
    '_VIDEO_FAMILY_RANK',
]
