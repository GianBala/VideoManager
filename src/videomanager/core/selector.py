"""Tradução de uma escolha do usuário em opções concretas do yt-dlp.

Duas ideias governam este módulo.

**Filtros não-estritos.** Todo filtro numérico usa a forma ``[height<=?720]``. O
``?`` diz ao yt-dlp para não descartar formatos que simplesmente não têm aquele
campo. Sem ele, pedir "no máximo 720p, no máximo 30fps" elimina todos os
formatos de sites que não informam ``fps`` — ou seja, quase tudo fora do
YouTube — e o download falha com "nenhum formato disponível" num vídeo que
estava perfeitamente acessível.

**Nunca recodificar sem consentimento.** Trocar de container é remux: cópia dos
streams, instantâneo e sem perda. Recodificar é lento e degrada a imagem. Quando
o container pedido não aceita o codec escolhido, a saída aqui é **trocar de
stream ou trocar de container** — nunca recodificar por conta própria. Toda
substituição feita vira um aviso em :attr:`ContainerPlan.warnings`, que a
interface mostra antes do download começar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .binaries import FFmpegTools
from .format_matrix import video_family_filter
from .humanize import format_bitrate
from .models import AudioChoice, FormatMatrix, MediaInfo, VideoChoice
from .settings import Settings

# --- compatibilidade de container -------------------------------------------
# "Muxable" = o ffmpeg consegue empacotar o stream neste container sem
# recodificar. "Bem suportado" = além de válido, reproduz na maioria dos
# players e aparelhos. VP9 e Opus dentro de MP4 são válidos mas caem no primeiro
# grupo apenas: geram arquivo legítimo que muita TV e celular não abre.

_MP4_MUXABLE_VIDEO = {"H.264", "HEVC", "AV1", "VP9", "MPEG-4", "Dolby Vision"}
_MP4_MUXABLE_AUDIO = {"AAC", "MP3", "AC-3", "E-AC-3", "ALAC", "Opus", "FLAC"}
_MP4_SAFE_VIDEO = {"H.264", "HEVC", "AV1"}
_MP4_SAFE_AUDIO = {"AAC", "MP3", "AC-3", "E-AC-3"}

_WEBM_MUXABLE_VIDEO = {"VP8", "VP9", "AV1"}
_WEBM_MUXABLE_AUDIO = {"Opus", "Vorbis"}

# MKV aceita qualquer combinação, por isso é o padrão seguro da aplicação.
CONTAINER_AUTO = "auto"
CONTAINERS = (CONTAINER_AUTO, "mp4", "mkv", "webm")

# Preferências de codec por container, para o modo automático. Expressas como
# regex do yt-dlp (operador ``~=``).
_CONTAINER_VIDEO_PREF = {
    "mp4": r"[vcodec~='^(avc1|avc3|h264)']",
    "webm": r"[vcodec~='^(vp0?9|vp0?8|av01)']",
}
_CONTAINER_AUDIO_PREF = {
    "mp4": r"[acodec~='^(mp4a|aac)']",
    "webm": r"[acodec~='^(opus|vorbis)']",
}

# Codecs de áudio aceitos pelo FFmpegExtractAudioPP (conferido na instalação).
AUDIO_CODECS = ("best", "mp3", "m4a", "aac", "opus", "vorbis", "flac", "alac", "wav")
# Formatos sem perda: pedir bitrate para eles não faz sentido.
LOSSLESS_AUDIO = {"flac", "alac", "wav"}
AUDIO_BITRATES = ("320", "256", "192", "160", "128", "96", "64")


@dataclass(frozen=True)
class VideoRequest:
    """Pedido de download de vídeo.

    ``video`` e ``audio`` em ``None`` significam modo automático: em vez de ids
    fixos, o seletor emite filtros por resolução e framerate. É o modo usado
    pelos perfis rápidos e por downloads em lote, onde cada item da playlist tem
    formatos diferentes e ids concretos não valeriam para todos.
    """

    video: VideoChoice | None = None
    audio: AudioChoice | None = None
    container: str = CONTAINER_AUTO
    max_height: int | None = None
    max_fps: int | None = None


@dataclass(frozen=True)
class AudioRequest:
    """Pedido de download somente-áudio."""

    audio: AudioChoice | None = None
    codec: str = "mp3"
    quality: str = "192"


Request = VideoRequest | AudioRequest


@dataclass(frozen=True)
class ContainerPlan:
    """Resultado da negociação entre o container pedido e os codecs disponíveis."""

    container: str
    video: VideoChoice | None
    audio: AudioChoice | None
    warnings: tuple[str, ...] = ()

    @property
    def merge_output_format(self) -> str | None:
        """Valor para ``merge_output_format``; ``None`` deixa o yt-dlp decidir."""
        return None if self.container == CONTAINER_AUTO else self.container


def _first_compatible_audio(matrix: FormatMatrix, allowed: set[str]) -> AudioChoice | None:
    for choice in matrix.audio:
        if choice.family in allowed:
            return choice
    return None


def _first_compatible_video(
    matrix: FormatMatrix, allowed: set[str], height: int | None
) -> VideoChoice | None:
    """Melhor vídeo compatível, priorizando manter a resolução escolhida."""
    if height is not None:
        for choice in matrix.video:
            if choice.family in allowed and choice.height == height:
                return choice
    for choice in matrix.video:
        if choice.family in allowed:
            return choice
    return None


def plan_container(
    matrix: FormatMatrix,
    video: VideoChoice | None,
    audio: AudioChoice | None,
    container: str,
) -> ContainerPlan:
    """Concilia o container pedido com os codecs realmente disponíveis.

    A ordem de preferência ao resolver um conflito é sempre: trocar de stream
    (sem perda, mesma qualidade) → trocar de container (sem perda, arquivo
    diferente do pedido) → e nunca recodificar.
    """
    warnings: list[str] = []

    if container == CONTAINER_AUTO or container == "mkv":
        # MKV aceita tudo, e no modo automático o próprio yt-dlp escolhe um
        # container compatível. Nada a negociar.
        return ContainerPlan(container, video, audio, ())

    muxable_video, muxable_audio, safe_video, safe_audio = {
        "mp4": (_MP4_MUXABLE_VIDEO, _MP4_MUXABLE_AUDIO, _MP4_SAFE_VIDEO, _MP4_SAFE_AUDIO),
        "webm": (
            _WEBM_MUXABLE_VIDEO,
            _WEBM_MUXABLE_AUDIO,
            _WEBM_MUXABLE_VIDEO,
            _WEBM_MUXABLE_AUDIO,
        ),
    }[container]

    # --- vídeo ---
    if video and video.family and video.family not in muxable_video:
        alternative = _first_compatible_video(matrix, safe_video, video.height)
        if alternative:
            warnings.append(
                f"{video.family} não cabe em .{container}: usando "
                f"{alternative.family} em {alternative.resolution_label} "
                "(sem recodificar)."
            )
            video = alternative
        else:
            warnings.append(
                f"{video.family} não cabe em .{container} e não há alternativa "
                "compatível nesta mídia. Salvando em .mkv, que aceita qualquer "
                "codec — sem recodificar nem perder qualidade."
            )
            return ContainerPlan("mkv", video, audio, tuple(warnings))
    elif video and video.family and video.family not in safe_video:
        warnings.append(
            f"{video.family} em .{container} gera arquivo válido, mas alguns "
            "aparelhos e TVs não reproduzem. .mkv ou H.264 são mais seguros."
        )

    # --- áudio ---
    if audio and audio.family and audio.family not in muxable_audio:
        alternative = _first_compatible_audio(matrix, safe_audio)
        if alternative:
            warnings.append(
                f"Trilha {audio.family} não cabe em .{container}: usando "
                f"{alternative.family} {format_bitrate(alternative.bitrate)} "
                "(sem recodificar)."
            )
            audio = alternative
        else:
            warnings.append(
                f"A única trilha de áudio é {audio.family}, incompatível com "
                f".{container}. Salvando em .mkv para preservar o áudio original."
            )
            return ContainerPlan("mkv", video, audio, tuple(warnings))
    elif audio and audio.family and audio.family not in safe_audio:
        alternative = _first_compatible_audio(matrix, safe_audio)
        if alternative:
            warnings.append(
                f"Trilha {alternative.family} "
                f"{format_bitrate(alternative.bitrate)} escolhida em vez de "
                f"{audio.family}: {audio.family} em .{container} tem suporte "
                "irregular nos players. A troca é sem recodificar."
            )
            audio = alternative

    return ContainerPlan(container, video, audio, tuple(warnings))


# ---------------------------------------------------------------------------
# Expressões de formato
# ---------------------------------------------------------------------------


def _limits(max_height: int | None, max_fps: int | None) -> str:
    """Filtros de limite, sempre não-estritos (ver docstring do módulo)."""
    parts = []
    if max_height:
        parts.append(f"[height<=?{max_height}]")
    if max_fps:
        parts.append(f"[fps<=?{max_fps}]")
    return "".join(parts)


def build_video_format_string(
    matrix: FormatMatrix,
    video: VideoChoice | None,
    audio: AudioChoice | None,
    *,
    container: str = CONTAINER_AUTO,
    max_height: int | None = None,
    max_fps: int | None = None,
) -> str:
    """Monta a expressão de formato, com cadeia de degradação.

    A cadeia existe porque um extrator pode listar um formato que já não está
    servível quando o download começa. Cada elo é uma tentativa mais genérica, e
    o último é sempre ``b`` — algo utilizável, em vez de uma falha.

    Nenhum elo baixa vídeo sem áudio quando a mídia tem áudio: um arquivo mudo é
    um defeito silencioso, pior que um erro explícito.
    """
    chain: list[str] = []
    limits = _limits(max_height, max_fps)

    if video is not None:
        vid = video.best.format_id
        video_alts = [f.format_id for f in video.formats[1:3]]

        if video.is_muxed or not matrix.has_audio:
            # Já tem áudio embutido, ou a mídia não tem trilha alguma.
            chain.append(vid)
            chain.extend(video_alts)
        else:
            if audio is not None:
                chain.append(f"{vid}+{audio.best.format_id}")
                chain.extend(
                    f"{vid}+{alt.format_id}" for alt in audio.formats[1:2]
                )
            chain.append(f"{vid}+ba")
            chain.extend(f"{alt}+ba" for alt in video_alts)
    else:
        # Modo automático: filtros em vez de ids.
        video_pref = _CONTAINER_VIDEO_PREF.get(container, "")
        audio_pref = _CONTAINER_AUDIO_PREF.get(container, "")
        if video_pref or audio_pref:
            chain.append(f"bv*{limits}{video_pref}+ba{audio_pref}")
            chain.append(f"bv*{limits}{video_pref}+ba")
        chain.append(f"bv*{limits}+ba")

    # Elos genéricos finais, comuns aos dois modos.
    height_limit = max_height or (video.height if video else None)
    if height_limit:
        # Antes de abrir mão do codec escolhido, tenta outro formato da mesma
        # família: quem pediu H.264 costuma precisar dele (TV, editor antigo),
        # e receber AV1 calado por causa de um id que saiu do ar não serve.
        family_filter = video_family_filter(video.family) if video else ""
        if family_filter:
            chain.append(f"bv*[height<=?{height_limit}]{family_filter}+ba")
        chain.append(f"bv*[height<=?{height_limit}]+ba")
        chain.append(f"b[height<=?{height_limit}]")
    chain.append("b")

    # Remove duplicatas preservando a ordem: elos repetidos só fazem o yt-dlp
    # reprocessar a mesma tentativa.
    seen: set[str] = set()
    unique = [link for link in chain if not (link in seen or seen.add(link))]
    return "/".join(unique)


def build_audio_format_string(audio: AudioChoice | None) -> str:
    """Expressão de formato para download somente-áudio.

    ``ba`` pega a melhor trilha só-áudio; ``ba*`` aceita um formato mesclado
    quando o site não separa as trilhas (o áudio é extraído depois pelo ffmpeg);
    ``b`` é a última rede de segurança.
    """
    chain: list[str] = []
    if audio is not None:
        chain.append(audio.best.format_id)
        chain.extend(alt.format_id for alt in audio.formats[1:3])
    chain.extend(("ba", "ba*", "b"))
    seen: set[str] = set()
    unique = [link for link in chain if not (link in seen or seen.add(link))]
    return "/".join(unique)


# ---------------------------------------------------------------------------
# Montagem das opções
# ---------------------------------------------------------------------------


def build_outtmpl(settings: Settings) -> str:
    """Template de nome de arquivo.

    ``%(title).150B`` corta o título em 150 **bytes** (não caracteres). Isso
    resolve de uma vez três problemas distintos: o limite de 260 caracteres de
    caminho no Windows, títulos longos de mais para o sistema de arquivos, e o
    corte no meio de um caractere UTF-8 multibyte — que produziria um nome
    inválido em títulos com acentos, japonês ou chinês, exatamente o tipo de
    coisa que aparece ao baixar do BiliBili.

    O id no fim garante nomes distintos para vídeos de título igual.
    """
    # Quando separado por site, reduzimos um pouco o teto do título para dar margem
    # ao nome da pasta do extrator no limite de caminho de 260 bytes do Windows.
    max_bytes = 120 if settings.separate_by_site else 150
    name = f"%(title).{max_bytes}B [%(id)s].%(ext)s"
    if settings.separate_by_site:
        return "%(extractor_key,extractor)s/" + name
    return name


def _base_opts(
    settings: Settings,
    tools: FFmpegTools,
    dest: Path,
    temp: Path,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "ffmpeg_location": tools.ffmpeg_str,
        "outtmpl": build_outtmpl(settings),
        # 'temp' mantém arquivos .part e fragmentos fora da pasta de destino,
        # que só recebe o arquivo final, já completo.
        "paths": {"home": str(dest), "temp": str(temp)},
        # Sanitização no estilo Windows em todos os sistemas: mantém acentos e
        # ideogramas, mas remove os caracteres que impedem o arquivo de ser
        # copiado depois para um pendrive ou compartilhamento Windows.
        "windowsfilenames": True,
        # Uma URL com "&list=" não deve arrastar a playlist inteira num download
        # de vídeo único. Downloads de playlist passam por outro caminho.
        "noplaylist": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "concurrent_fragment_downloads": max(1, settings.concurrent_fragments),
        # A interface é a única a reportar progresso; o console fica limpo.
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "consoletitle": False,
        "postprocessor_args": {
            "default": ["-metadata", "title="],
        },
    }

    if settings.rate_limit_kbps > 0:
        opts["ratelimit"] = settings.rate_limit_kbps * 1024

    if settings.cookies_file and Path(settings.cookies_file).is_file():
        opts["cookiefile"] = str(Path(settings.cookies_file).resolve())
    elif settings.cookies_browser:
        # A tupla é o formato esperado: (navegador, perfil, keyring, container).
        opts["cookiesfrombrowser"] = (settings.cookies_browser, None, None, None)

    return opts


def _subtitle_opts(settings: Settings) -> dict[str, Any]:
    if not (settings.write_subtitles or settings.embed_subtitles):
        return {}
    opts: dict[str, Any] = {
        "writesubtitles": True,
        "subtitleslangs": list(settings.subtitle_langs) or ["pt", "en"],
        "writeautomaticsub": settings.include_auto_subtitles,
    }
    return opts


def _metadata_postprocessors(settings: Settings) -> list[dict[str, Any]]:
    """Postprocessors de metadados, na ordem em que devem rodar.

    Os metadados vêm antes da miniatura porque o EmbedThumbnail reescreve o
    container; invertida, a ordem pode descartar as tags recém-gravadas.
    """
    processors: list[dict[str, Any]] = []
    if settings.embed_metadata:
        processors.append({"key": "FFmpegMetadata", "add_metadata": True})
    if settings.embed_thumbnail:
        processors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
    return processors


def build_video_opts(
    request: VideoRequest,
    media: MediaInfo,
    settings: Settings,
    tools: FFmpegTools,
    dest: Path,
    temp: Path,
) -> tuple[dict[str, Any], ContainerPlan]:
    """Opções do yt-dlp para baixar vídeo. Devolve também o plano de container,
    cujos avisos a interface deve mostrar."""
    plan = plan_container(media.matrix, request.video, request.audio, request.container)

    opts = _base_opts(settings, tools, dest, temp)
    opts["format"] = build_video_format_string(
        media.matrix,
        plan.video,
        plan.audio,
        container=plan.container,
        max_height=request.max_height,
        max_fps=request.max_fps,
    )

    merge = plan.merge_output_format
    if merge:
        opts["merge_output_format"] = merge

    postprocessors = _metadata_postprocessors(settings)
    if settings.embed_subtitles:
        postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
    if postprocessors:
        opts["postprocessors"] = postprocessors
    if settings.embed_thumbnail:
        opts["writethumbnail"] = True

    opts.update(_subtitle_opts(settings))
    return opts, plan


def audio_quality_warning(matrix: FormatMatrix, codec: str, quality: str) -> str | None:
    """Avisa quando o bitrate pedido excede o que a fonte realmente tem.

    Transcodificar um Opus de 128 kbps para um MP3 de 320 kbps não recupera
    nada: o arquivo triplica de tamanho e a qualidade continua sendo a do
    original — na prática, um pouco pior, porque é uma segunda compressão com
    perda. O usuário merece saber disso antes, não depois.
    """
    if codec in LOSSLESS_AUDIO or codec == "best":
        return None
    try:
        requested = float(quality)
    except (TypeError, ValueError):
        return None

    source = matrix.best_audio_bitrate
    if source and requested > source * 1.1:
        return (
            f"A melhor trilha desta mídia tem {format_bitrate(source)}. "
            f"Gerar um {codec.upper()} de {int(requested)} kbps só aumenta o "
            "arquivo, sem recuperar qualidade — a compressão original é "
            "irreversível. Considere “Original (sem perda)” ou um valor próximo "
            f"de {format_bitrate(source)}."
        )
    return None


def build_audio_opts(
    request: AudioRequest,
    media: MediaInfo,
    settings: Settings,
    tools: FFmpegTools,
    dest: Path,
    temp: Path,
) -> dict[str, Any]:
    """Opções do yt-dlp para baixar somente o áudio.

    Com ``codec="best"`` o áudio original é apenas extraído do container, sem
    recodificar: é instantâneo e sem perda nenhuma. É a melhor opção para quem
    quer só ouvir, e por isso aparece primeiro na interface.
    """
    opts = _base_opts(settings, tools, dest, temp)
    opts["format"] = build_audio_format_string(request.audio)

    extract: dict[str, Any] = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": request.codec,
        "nopostoverwrites": False,
    }
    if request.codec not in LOSSLESS_AUDIO and request.codec != "best":
        extract["preferredquality"] = request.quality

    opts["postprocessors"] = [extract, *_metadata_postprocessors(settings)]
    if settings.embed_thumbnail:
        opts["writethumbnail"] = True

    if request.codec == "mp3":
        # Sem ID3v2.3 o Windows Explorer e vários aparelhos antigos não exibem
        # título nem artista; o padrão do ffmpeg é a versão 2.4.
        pp_args = dict(opts.get("postprocessor_args", {}))
        pp_args["extractaudio"] = ["-id3v2_version", "3", "-metadata", "title="]
        opts["postprocessor_args"] = pp_args

    return opts


def build_opts(
    request: Request,
    media: MediaInfo,
    settings: Settings,
    tools: FFmpegTools,
    dest: Path,
    temp: Path,
) -> tuple[dict[str, Any], ContainerPlan | None]:
    """Ponto de entrada único: despacha conforme o tipo do pedido."""
    if isinstance(request, AudioRequest):
        return build_audio_opts(request, media, settings, tools, dest, temp), None
    return build_video_opts(request, media, settings, tools, dest, temp)


def describe_request(request: Request, plan: ContainerPlan | None) -> str:
    """Resumo curto do que será baixado, para a coluna de destino na fila."""
    if isinstance(request, AudioRequest):
        if request.codec == "best":
            return "Áudio · original (sem perda)"
        if request.codec in LOSSLESS_AUDIO:
            return f"Áudio · {request.codec.upper()}"
        return f"Áudio · {request.codec.upper()} {request.quality} kbps"

    parts: list[str] = []
    choice = plan.video if plan else request.video
    if choice is not None:
        parts.append(choice.resolution_label)
        if choice.family:
            parts.append(choice.family)
    elif request.max_height:
        parts.append(f"até {request.max_height}p")
    container = plan.container if plan else request.container
    parts.append(".mkv" if container == CONTAINER_AUTO else f".{container}")
    return " · ".join(parts)
