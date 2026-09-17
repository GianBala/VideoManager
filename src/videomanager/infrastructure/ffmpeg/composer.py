"""Monta o grafo do ffmpeg que transforma um projeto em imagem e som.

**Um grafo só, três usos.** O mesmo montador serve para exportar o arquivo
final, para desenhar o quadro parado da prévia e para alimentar a reprodução. A
consequência é a que importa: **o que está na tela é a composição de verdade** —
com as trilhas sobrepostas na ordem certa, com os volumes e os mudos aplicados —,
e não uma aproximação que só vira o resultado na hora de exportar.

O que muda entre os três usos é só onde a leitura começa (``at``), quanto dura
(``span``) e para onde vai a saída. O montador :func:`build_graph`
recebe o projeto e devolve entradas, filtros e rótulos; quem chama decide
se aquilo vira arquivo, um quadro cru ou um fluxo de PCM. Textos usam o
adaptador de rasterização instalado pela interface, sem importar Qt no domínio.

Três decisões de montagem:

**A tela é um fundo preto do tamanho do projeto, e cada bloco é sobreposto a
ele.** Não se "emenda" vídeo: emendar só funciona quando tudo tem o mesmo
tamanho, o mesmo framerate e nenhuma trilha por cima da outra. Sobrepor a um
fundo resolve vão, formato misturado e trilha de cima com a mesma regra.

**Cada bloco é ajustado à tela antes de entrar.** ``scale`` preservando a
proporção e ``pad`` centralizando: um vídeo vertical no meio de horizontais
aparece inteiro, com tarja, em vez de esticado.

**A mixagem não normaliza.** O ``amix`` do ffmpeg divide o volume pelo número de
entradas por padrão — dois blocos simultâneos sairiam pela metade, sem ninguém
ter pedido. Com ``normalize=0`` cada bloco sai no volume que o usuário ajustou,
e a soma é responsabilidade dele.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from videomanager.infrastructure.ffmpeg import hardware as hwaccel
from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import decode_thread_args
from videomanager.application.errors import ConversionError
from videomanager.domain.keyframe import Keyframe, resolve_segment_easing
from videomanager.domain.preview import fit_size
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import Project
from videomanager.domain.project import TrackKind
from videomanager.domain.project import TransitionContext
from videomanager.infrastructure.ffmpeg.trimmer import encode_audio_args
from videomanager.domain.timing import format_span
from videomanager.infrastructure.ffmpeg.trimmer import tail_args

from videomanager.domain.composition import Composition as Composition

from videomanager.domain.export_policy import simple_trim as simple_trim
from videomanager.domain.export_policy import as_trim_target as as_trim_target
from videomanager.domain.export_policy import _interpolated_clips as _interpolated_clips
from videomanager.domain.export_policy import can_interpolate as can_interpolate

from videomanager.domain.geometry import image_base_size as image_base_size

from videomanager.domain.render_cost import _INTERPOLATE_BYTES_PER_PIXEL as _INTERPOLATE_BYTES_PER_PIXEL
from videomanager.domain.render_cost import interpolation_bytes as interpolation_bytes

from videomanager.application.media.export_description import describe_export as describe_export

# Formato interno do áudio. Fixá-lo antes da mixagem evita o erro mais comum de
# ``amix``: entradas com taxas ou layouts diferentes, que ele recusa.
SAMPLE_RATE = 48_000
CHANNELS = 2
_AUDIO_BASE = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}"

# Mono vira estéreo copiando o canal, e não pela conversão de layout do ffmpeg:
# a conversão normaliza a potência e tira **3 dB** exatos do material, o que
# quebraria a promessa de que 0 dB no bloco significa "não mexe". Medido: uma
# trilha mono de -21,5 dB sai a -24,5 dB por ``aformat=channel_layouts=stereo``
# e a -21,5 dB por ``pan``.
_MONO_TO_STEREO = "pan=stereo|c0=c0|c1=c0"
# De 5.1 para estéreo a atenuação é desejada — é o que evita a soma dos canais
# estourar —, então ali a conversão normal é a correta.
_TO_STEREO = "aformat=channel_layouts=stereo"

# Quando não existem alças para sobrepor áudio de verdade, uma rampa curta
# elimina o estalo do corte sem baixar o som durante toda a transição visual.
# Transições de imagem e áudio são decisões distintas; inventar meio segundo de
# silêncio para sustentar um efeito de vídeo soa pior que preservar o corte.
_AUDIO_DECLICK = 0.012

# Duração mínima do fundo. Um projeto vazio ainda precisa de um quadro para
# mostrar, senão o ffmpeg sai sem escrever nada e a prévia fica sem explicação.
_MIN_CANVAS = 0.04

# Sobra clonada no fim de um bloco interpolado (ver :func:`_rate_chain`). Meio
# segundo cobre com folga os poucos quadros que o filtro não consegue produzir,
# e nada disso aparece: a sobreposição é desligada no fim do bloco.
_INTERPOLATE_TAIL = 0.5

# Memória do ``minterpolate``, por pixel do quadro que ele **recebe**. Medido
# nesta máquina, pico de RSS de uma exportação: 1589 MB a 1920×1080 (803 B/px) e
# 5655 MB a 3840×2160 (715 B/px). Não cresce com a duração — 20 s a 1080p pediu
# os mesmos 1,6 GB que 5 s —, e é por isso que o custo pode ser anunciado antes
# de a exportação começar (ver :func:`interpolation_bytes`). O valor é o maior
# dos dois: errar para cima só antecipa um aviso, errar para baixo derruba a
# máquina.


@dataclass(frozen=True)
class _Piece:
    """Um bloco já traduzido para a janela de tempo pedida."""

    clip: Clip
    index: int  # posição na lista de entradas do ffmpeg
    seek: float  # onde começar a ler dentro do arquivo
    offset: float  # onde entra na saída, em segundos
    duration: float
    track_index: int
    track_muted: bool = False


def _pieces(
    project: Project,
    at: float,
    span: float | None,
    *,
    want_video: bool = True,
    want_audio: bool = True,
) -> list[_Piece]:
    """Blocos que aparecem na janela pedida, na ordem de composição.

    A ordem é a de baixo para cima: a trilha de vídeo mais baixa é o fundo e as
    de cima passam por cima dela. Em seguida vêm as trilhas de adicionais
    (sobreposições, textos, filtros) no topo visual.
    """
    end = None if span is None else at + span
    visual_tracks = [
        (index, track)
        for index, track in enumerate(project.tracks)
        if track.kind in (TrackKind.VIDEO, TrackKind.ADDITIONAL)
    ]
    ordered = [
        *reversed(visual_tracks),
        *(
            (index, track)
            for index, track in enumerate(project.tracks)
            if track.kind is TrackKind.AUDIO
        ),
    ]

    pieces: list[_Piece] = []
    input_idx = 0
    for track_index, track in ordered:
        if not track.visible:
            continue
        if track.muted and track.kind is TrackKind.AUDIO:
            continue
        if track.muted and not want_video:
            continue
        for clip in track.sorted_clips():
            if clip.end <= at or (end is not None and clip.start >= end):
                continue
            begin = max(clip.start, at)
            finish = clip.end if end is None else min(clip.end, end)
            if finish - begin <= 0:
                continue
            has_v = want_video and (clip.has_image or clip.is_transition)
            has_a = want_audio and clip.has_sound and not track.muted
            if not has_v and not has_a:
                continue
            is_overlay_filter = clip.overlay_type in ("filter", "transition")
            idx = -1 if is_overlay_filter else input_idx
            if not is_overlay_filter:
                input_idx += 1
            pieces.append(
                _Piece(
                    clip=clip,
                    index=idx,
                    seek=clip.source_time(begin),
                    offset=begin - at,
                    duration=finish - begin,
                    track_index=track_index,
                    track_muted=track.muted,
                )
            )
    return pieces


def _input_args(
    piece: _Piece,
    fps: float,
    *,
    text_assets: dict[int, Path] | None = None,
) -> list[str]:
    clip = piece.clip
    if clip.overlay_type in ("filter", "transition"):
        return []
    if clip.overlay_type == "text":
        path = (text_assets or {}).get(clip.clip_id)
        if path is None:
            raise ConversionError("Os recursos de texto não foram preparados para esta renderização.")
        return [
            "-loop", "1",
            "-framerate", f"{fps:.6f}",
            "-t", f"{piece.duration:.6f}",
            "-i", str(path),
        ]
    if clip.media.kind is MediaKind.IMAGE:
        # Uma imagem não tem duração: ela é repetida pelo tempo do bloco. O
        # ``-t`` na entrada é o que encerra essa repetição.
        return [
            "-loop", "1",
            "-framerate", f"{fps:.6f}",
            "-t", f"{piece.duration:.6f}",
            "-i", str(clip.media.path),
        ]
    return ["-ss", f"{piece.seek:.6f}", "-i", str(clip.media.path)]


def _interpolates(piece: _Piece, fps: float, interpolate: bool) -> bool:
    """Se **este** bloco vai ter quadros inventados.

    A caixa marcada não basta: só há o que interpolar num bloco de vídeo abaixo
    da taxa da tela. Um bloco já na taxa (ou acima) pagaria a estimativa de
    movimento para nada, e uma imagem parada não tem movimento a estimar.
    """
    origem = piece.clip.media.fps
    return bool(interpolate and origem and origem * piece.clip.speed < fps - 0.01)


def _rate_chain(piece: _Piece, fps: float, interpolate: bool) -> str:
    """Como este bloco chega à taxa da tela.

    O normal é ``fps``, que **duplica ou descarta quadros inteiros**: subir de 24
    para 60 assim entrega um arquivo de 60 fps com 24 imagens por segundo (e uma
    cadência 2-3-2-3, que treme mais que os 24 originais). É o comportamento
    certo por padrão — é instantâneo e não inventa nada.

    ``minterpolate`` estima o movimento e **sintetiza** os quadros que faltam;
    é a única forma de ganhar fluidez de verdade. Medido nesta máquina, 5 s a
    24→60 fps: 0,15 s duplicando contra 5,73 s interpolando (38×), com 296 dos
    300 quadros distintos contra 120. Em troca, ela inventa pixels — movimento
    rápido, oclusão e corte de cena saem deformados —, e por isso é escolha
    explícita e nunca o padrão.

    Só entra onde há o que interpolar: ver :func:`_interpolates`.
    """
    if _interpolates(piece, fps, interpolate):
        # ``tpad`` repõe o fim: para inventar um quadro, o filtro precisa do
        # **seguinte**, e por isso ele entrega alguns quadros a menos do que
        # recebeu. Medido: 236 de 240. O bloco acabava antes da hora e o que
        # aparecia no lugar era o fundo preto da composição — duração certa,
        # contagem de quadros certa, nenhum erro, e o último décimo de segundo
        # preto. O excedente clonado não vaza: a sobreposição já é desligada no
        # fim do bloco.
        return (
            f"minterpolate=fps={fps:.6f}:mi_mode=mci:mc_mode=aobmc:vsbmc=1,"
            f"tpad=stop_mode=clone:stop_duration={_INTERPOLATE_TAIL}"
        )
    return f"fps={fps:.6f}"


def _atempo_filters(speed: float) -> list[str]:
    filters: list[str] = []
    s = speed
    while s > 2.0:
        filters.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        filters.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 0.005:
        filters.append(f"atempo={s:.4f}")
    return filters


def _alpha_before_dynamic_scale(steps: list[str]) -> list[str]:
    """Põe o alfa animado antes do ``scale`` que muda de tamanho a cada quadro.

    ``geq`` fixa as dimensões do link quando o filtro é configurado. Estando
    **depois** de um ``scale=…:eval=frame``, ele trava justamente o tamanho que
    o scale deveria variar, e a escala animada desaparece do arquivo sem erro
    nenhum. Medido: o preset ``zoom_in`` — que anima escala e opacidade juntas —
    exportava a imagem no tamanho do primeiro quadro-chave do começo ao fim
    (0,49 de largura em todo o clipe, contra 0,51 → 0,74 → 0,97 esperados),
    enquanto a prévia, que monta um grafo por quadro, mostrava o movimento
    certo. A opacidade animada é um fator uniforme no quadro, então aplicá-la
    antes do scale dá o mesmo resultado; o chromakey precisa vir junto porque
    ele **grava** o alfa em vez de multiplicá-lo, e ficaria por cima do fator.
    """
    alpha = next((i for i, s in enumerate(steps) if s.startswith("geq=")), None)
    scale = next(
        (i for i, s in enumerate(steps) if s.startswith("scale=") and "eval=frame" in s), None
    )
    if alpha is None or scale is None or alpha < scale:
        return steps
    chroma = next((i for i, s in enumerate(steps) if s.startswith("chromakey=")), None)
    movidos = {i for i in (chroma, alpha) if i is not None}
    adiantado = ([steps[chroma]] if chroma is not None else []) + ["format=rgba", steps[alpha]]
    return (
        steps[:scale]
        + adiantado
        + [s for i, s in enumerate(steps[scale:], start=scale) if i not in movidos]
    )


def _chromakey_filter(clip: Clip) -> str | None:
    """Gera a cláusula do filtro chromakey se habilitado no clipe."""
    if not clip.chromakey_enabled:
        return None
    raw_col = clip.chromakey_color or "#00FF00"
    if raw_col.startswith("#"):
        col = f"0x{raw_col[1:]}"
    elif not raw_col.startswith("0x"):
        col = f"0x{raw_col}"
    else:
        col = raw_col
    sim = max(0.001, min(1.0, clip.chromakey_similarity))
    blend = max(0.0, min(1.0, clip.chromakey_blend))
    return f"chromakey=color={col}:similarity={sim:.4f}:blend={blend:.4f}"


def _clip_stream_origin(piece: _Piece) -> float:
    """Calcula a origem temporal do clipe no fluxo (PTS=0), considerando o seek."""
    clip = piece.clip
    speed = max(0.001, clip.speed)
    elapsed = max(0.0, (piece.seek - clip.in_point) / speed)
    return piece.offset - elapsed


def _keyframe_expr(
    keyframes: tuple[Keyframe, ...],
    prop_name: str,
    clip_offset: float,
    fallback: float,
    time_var: str = "t",
    is_angle: bool = False,
) -> str:
    """Gera uma expressão matemática do FFmpeg para interpolação contínua em função do tempo."""
    if not keyframes:
        return f"{fallback:.6f}"
    sorted_kfs = sorted(keyframes, key=lambda k: k.time_offset)
    if len(sorted_kfs) == 1:
        v0 = getattr(sorted_kfs[0], prop_name)
        return f"{v0:.6f}"
    if all(
        abs(getattr(k, prop_name) - getattr(sorted_kfs[0], prop_name)) < 1e-6
        for k in sorted_kfs
    ):
        return f"{getattr(sorted_kfs[0], prop_name):.6f}"

    segments: list[tuple[float, str]] = []
    t0 = clip_offset + sorted_kfs[0].time_offset
    v0 = getattr(sorted_kfs[0], prop_name)
    segments.append((t0, f"{v0:.6f}"))

    for i in range(len(sorted_kfs) - 1):
        k_start = sorted_kfs[i]
        k_end = sorted_kfs[i + 1]
        t_start = clip_offset + k_start.time_offset
        t_end = clip_offset + k_end.time_offset
        dt = max(1e-5, t_end - t_start)
        val_start = getattr(k_start, prop_name)
        val_end = getattr(k_end, prop_name)

        if is_angle and abs(val_end - val_start) < 359.9:
            val_diff = (val_end - val_start) % 360.0
            if val_diff > 180.0:
                val_diff -= 360.0
        else:
            val_diff = val_end - val_start

        if abs(val_diff) < 1e-6:
            seg_expr = f"{val_start:.6f}"
        else:
            tau = f"(({time_var}-{t_start:.6f})/{dt:.6f})"
            easing = resolve_segment_easing(k_start.easing, k_end.easing)
            if easing == "ease_in":
                factor = f"({tau}*{tau})"
            elif easing == "ease_out":
                factor = f"((2-{tau})*{tau})"
            elif easing == "ease_in_out":
                factor = f"if(lt({tau},0.5),2*{tau}*{tau},1-2*(1-{tau})*(1-{tau}))"
            elif easing == "hold":
                factor = "0"
            else:
                factor = tau
            seg_expr = f"({val_start:.6f}+({val_diff:.6f})*{factor})"

        segments.append((t_end, seg_expr))

    v_last = getattr(sorted_kfs[-1], prop_name)
    expr = f"{v_last:.6f}"
    for t_thresh, seg_content in reversed(segments):
        expr = f"if(lt({time_var},{t_thresh:.6f}),{seg_content},{expr})"

    return expr


def _video_chain(
    piece: _Piece,
    project: Project,
    fps: float,
    interpolate: bool = False,
    canonical_size: tuple[int, int] | None = None,
    standalone: bool = False,
) -> str:
    """Ajusta um bloco ao formato da tela e o coloca no instante certo."""
    clip = piece.clip
    is_overlay = clip.overlay_type in ("image", "text") or clip.is_image
    if is_overlay:
        steps = [f"trim=duration={piece.duration:.6f}"]
        if piece.offset > 0:
            steps.append(f"setpts=PTS-STARTPTS+{piece.offset:.6f}/TB")
        else:
            steps.append("setpts=PTS-STARTPTS")
        steps.append(f"fps={fps:.6f}")
        steps.append("format=rgba")
        sx = getattr(clip, "scale_x", clip.scale)
        sy = getattr(clip, "scale_y", clip.scale)
        origin = _clip_stream_origin(piece)
        has_anim_scale = clip.has_keyframes and (
            any(
                abs(k.scale_x - sx) > 1e-9 or abs(k.scale_y - sy) > 1e-9
                for k in clip.keyframes
            )
            or any(
                abs(clip.keyframes[i].scale_x - clip.keyframes[i + 1].scale_x) > 1e-9
                or abs(clip.keyframes[i].scale_y - clip.keyframes[i + 1].scale_y) > 1e-9
                for i in range(len(clip.keyframes) - 1)
            )
        )
        if has_anim_scale:
            expr_sx = _keyframe_expr(clip.keyframes, "scale_x", origin, sx, time_var="t")
            expr_sy = _keyframe_expr(clip.keyframes, "scale_y", origin, sy, time_var="t")
            if clip.overlay_type == "text":
                steps.append(
                    f"scale=w='max(2,trunc(iw*({expr_sx})/2)*2)':h='max(2,trunc(ih*({expr_sy})/2)*2)':eval=frame"
                )
            else:
                canon_w, canon_h = canonical_size or (project.width, project.height)
                canon_base_w, canon_base_h = image_base_size(
                    clip.media.width if clip.media else None,
                    clip.media.height if clip.media else None,
                    canon_w,
                    canon_h,
                )
                ratio_w = project.width / max(1, canon_w)
                ratio_h = project.height / max(1, canon_h)
                base_w = max(2, int(round(canon_base_w * ratio_w / 2.0) * 2))
                base_h = max(2, int(round(canon_base_h * ratio_h / 2.0) * 2))
                steps.append(
                    f"scale=w='max(2,trunc({base_w}*({expr_sx})/2)*2)':h='max(2,trunc({base_h}*({expr_sy})/2)*2)':eval=frame"
                )
        elif clip.overlay_type == "text":
            if abs(sx - 1.0) > 1e-9 or abs(sy - 1.0) > 1e-9:
                steps.append(f"scale=w='max(2,trunc(iw*{sx:.6f}/2)*2)':h='max(2,trunc(ih*{sy:.6f}/2)*2)'")
        elif clip.overlay_type == "image" or clip.is_image:
            canon_w, canon_h = canonical_size or (project.width, project.height)
            canon_base_w, canon_base_h = image_base_size(
                clip.media.width if clip.media else None,
                clip.media.height if clip.media else None,
                canon_w,
                canon_h,
            )
            ratio_w = project.width / max(1, canon_w)
            ratio_h = project.height / max(1, canon_h)
            base_w = max(2, int(round(canon_base_w * ratio_w / 2.0) * 2))
            base_h = max(2, int(round(canon_base_h * ratio_h / 2.0) * 2))
            target_w = max(2, int(round(base_w * sx / 2.0) * 2))
            target_h = max(2, int(round(base_h * sy / 2.0) * 2))
            steps.append(f"scale={target_w}:{target_h}")
        elif abs(sx - 1.0) > 1e-9 or abs(sy - 1.0) > 1e-9:
            steps.append(f"scale=w='max(2,trunc(iw*{sx:.6f}/2)*2)':h='max(2,trunc(ih*{sy:.6f}/2)*2)'")
        if clip.chromakey_enabled:
            ck = _chromakey_filter(clip)
            if ck:
                steps.append(ck)

        has_anim_rotation = clip.has_keyframes and (
            any(abs(k.rotation - clip.rotation) > 1e-9 for k in clip.keyframes)
            or any(
                abs(clip.keyframes[i].rotation - clip.keyframes[i + 1].rotation) > 1e-9
                for i in range(len(clip.keyframes) - 1)
            )
        )
        max_diag: int | None = None
        if clip.has_keyframes:
            all_k_sx = [getattr(clip, "scale_x", clip.scale)] + [k.scale_x for k in clip.keyframes]
            all_k_sy = [getattr(clip, "scale_y", clip.scale)] + [k.scale_y for k in clip.keyframes]
            max_k_sx = max(all_k_sx)
            max_k_sy = max(all_k_sy)
            if clip.overlay_type == "text":
                tw = project.width
                th = project.height
                max_diag = max(2, int(math.ceil(math.hypot(tw * max_k_sx, th * max_k_sy))) // 2 * 2)
            else:
                canon_w, canon_h = canonical_size or (project.width, project.height)
                canon_base_w, canon_base_h = image_base_size(
                    clip.media.width if clip.media else None,
                    clip.media.height if clip.media else None,
                    canon_w,
                    canon_h,
                )
                ratio_w = project.width / max(1, canon_w)
                ratio_h = project.height / max(1, canon_h)
                base_w = max(2, int(round(canon_base_w * ratio_w / 2.0) * 2))
                base_h = max(2, int(round(canon_base_h * ratio_h / 2.0) * 2))
                max_diag = max(2, int(math.ceil(math.hypot(base_w * max_k_sx, base_h * max_k_sy))) // 2 * 2)

        if has_anim_rotation:
            expr_rot = _keyframe_expr(
                clip.keyframes, "rotation", origin, clip.rotation, time_var="t", is_angle=True
            )
            if max_diag is not None:
                steps.append(
                    f"rotate=a='({expr_rot})*PI/180':ow='2*ceil(max(hypot(iw,ih),{max_diag})/2)':oh='2*ceil(max(hypot(iw,ih),{max_diag})/2)':c=black@0"
                )
            else:
                steps.append(
                    f"rotate=a='({expr_rot})*PI/180':ow='2*ceil(hypot(iw,ih)/2)':oh='2*ceil(hypot(iw,ih)/2)':c=black@0"
                )
        elif abs(clip.rotation) > 1e-9:
            rad = math.radians(clip.rotation)
            if max_diag is not None:
                steps.append(
                    f"rotate={rad:.4f}:ow='2*ceil(max(rotw({rad:.4f}),{max_diag})/2)':oh='2*ceil(max(roth({rad:.4f}),{max_diag})/2)':c=black@0"
                )
            else:
                steps.append(
                    f"rotate={rad:.4f}:ow='2*ceil(rotw({rad:.4f})/2)':oh='2*ceil(roth({rad:.4f})/2)':c=black@0"
                )

        if clip.has_keyframes:
            has_anim_opacity = any(
                abs(k.opacity - clip.opacity) > 1e-9 for k in clip.keyframes
            ) or any(
                abs(clip.keyframes[i].opacity - clip.keyframes[i + 1].opacity) > 1e-9
                for i in range(len(clip.keyframes) - 1)
            )
            if has_anim_opacity:
                expr_op = _keyframe_expr(
                    clip.keyframes, "opacity", origin, clip.opacity, time_var="T"
                )
                steps.append("format=rgba")
                steps.append(
                    f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({expr_op})'"
                )
            elif clip.opacity < 1 - 1e-9:
                steps.append(f"colorchannelmixer=aa={clip.opacity:.4f}")
        elif clip.opacity < 1 - 1e-9:
            steps.append(f"colorchannelmixer=aa={clip.opacity:.4f}")
        steps.append("format=rgba")
        steps = _alpha_before_dynamic_scale(steps)
        return f"[{piece.index}:v]" + ",".join(steps) + f"[v{piece.index}]"

    steps = []
    if abs(clip.speed - 1.0) > 1e-9:
        steps.append(f"trim=duration={piece.duration * clip.speed:.6f}")
        inv = 1.0 / clip.speed
        if piece.offset > 0:
            steps.append(f"setpts={inv:.6f}*(PTS-STARTPTS)+{piece.offset:.6f}/TB")
        else:
            steps.append(f"setpts={inv:.6f}*(PTS-STARTPTS)")
    else:
        steps.append(f"trim=duration={piece.duration:.6f}")
        if piece.offset > 0:
            steps.append(f"setpts=PTS-STARTPTS+{piece.offset:.6f}/TB")
        else:
            steps.append("setpts=PTS-STARTPTS")

    sx = getattr(clip, "scale_x", clip.scale)
    sy = getattr(clip, "scale_y", clip.scale)
    has_keyframes = clip.has_keyframes
    origin = _clip_stream_origin(piece)
    has_anim_scale = has_keyframes and (
        any(
            abs(k.scale_x - sx) > 1e-9 or abs(k.scale_y - sy) > 1e-9
            for k in clip.keyframes
        )
        or any(
            abs(clip.keyframes[i].scale_x - clip.keyframes[i + 1].scale_x) > 1e-9
            or abs(clip.keyframes[i].scale_y - clip.keyframes[i + 1].scale_y) > 1e-9
            for i in range(len(clip.keyframes) - 1)
        )
    )
    has_anim_rotation = has_keyframes and (
        any(abs(k.rotation - clip.rotation) > 1e-9 for k in clip.keyframes)
        or any(
            abs(clip.keyframes[i].rotation - clip.keyframes[i + 1].rotation) > 1e-9
            for i in range(len(clip.keyframes) - 1)
        )
    )
    has_transform = (
        standalone
        or has_keyframes
        or abs(clip.x - 0.5) > 1e-9
        or abs(clip.y - 0.5) > 1e-9
        or abs(sx - 1.0) > 1e-9
        or abs(sy - 1.0) > 1e-9
        or abs(clip.rotation) > 1e-9
        or clip.chromakey_enabled
        or clip.opacity < 1 - 1e-9
    )
    if has_transform:
        steps.append(_rate_chain(piece, fps, interpolate))
        steps.append("format=rgba")
        mw = clip.media.width if clip.media else None
        mh = clip.media.height if clip.media else None
        base_w, base_h = fit_size(mw, mh, project.width, project.height)
        if has_anim_scale:
            expr_sx = _keyframe_expr(clip.keyframes, "scale_x", origin, sx, time_var="t")
            expr_sy = _keyframe_expr(clip.keyframes, "scale_y", origin, sy, time_var="t")
            steps.append(
                f"scale=w='max(2,trunc({base_w}*({expr_sx})/2)*2)':h='max(2,trunc({base_h}*({expr_sy})/2)*2)':eval=frame"
            )
        else:
            target_w = max(2, int(round(base_w * sx / 2.0) * 2))
            target_h = max(2, int(round(base_h * sy / 2.0) * 2))
            steps.append(f"scale={target_w}:{target_h}")

        if clip.chromakey_enabled:
            ck = _chromakey_filter(clip)
            if ck:
                steps.append(ck)

        max_diag: int | None = None
        if clip.has_keyframes:
            all_k_sx = [getattr(clip, "scale_x", clip.scale)] + [k.scale_x for k in clip.keyframes]
            all_k_sy = [getattr(clip, "scale_y", clip.scale)] + [k.scale_y for k in clip.keyframes]
            max_k_sx = max(all_k_sx)
            max_k_sy = max(all_k_sy)
            max_diag = max(2, int(math.ceil(math.hypot(base_w * max_k_sx, base_h * max_k_sy))) // 2 * 2)

        if has_anim_rotation:
            expr_rot = _keyframe_expr(
                clip.keyframes, "rotation", origin, clip.rotation, time_var="t", is_angle=True
            )
            if max_diag is not None:
                steps.append(
                    f"rotate=a='({expr_rot})*PI/180':ow='2*ceil(max(hypot(iw,ih),{max_diag})/2)':oh='2*ceil(max(hypot(iw,ih),{max_diag})/2)':c=black@0"
                )
            else:
                steps.append(
                    f"rotate=a='({expr_rot})*PI/180':ow='2*ceil(hypot(iw,ih)/2)':oh='2*ceil(hypot(iw,ih)/2)':c=black@0"
                )
        elif abs(clip.rotation) > 1e-9:
            rad = math.radians(clip.rotation)
            if max_diag is not None:
                steps.append(
                    f"rotate={rad:.4f}:ow='2*ceil(max(rotw({rad:.4f}),{max_diag})/2)':oh='2*ceil(max(roth({rad:.4f}),{max_diag})/2)':c=black@0"
                )
            else:
                steps.append(
                    f"rotate={rad:.4f}:ow='2*ceil(rotw({rad:.4f})/2)':oh='2*ceil(roth({rad:.4f})/2)':c=black@0"
                )

        if clip.has_keyframes:
            has_anim_opacity = any(
                abs(k.opacity - clip.opacity) > 1e-9 for k in clip.keyframes
            ) or any(
                abs(clip.keyframes[i].opacity - clip.keyframes[i + 1].opacity) > 1e-9
                for i in range(len(clip.keyframes) - 1)
            )
            if has_anim_opacity:
                expr_op = _keyframe_expr(
                    clip.keyframes, "opacity", origin, clip.opacity, time_var="T"
                )
                steps.append("format=rgba")
                steps.append(
                    f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({expr_op})'"
                )
            elif clip.opacity < 1 - 1e-9:
                steps.append(f"colorchannelmixer=aa={clip.opacity:.4f}")
        elif clip.opacity < 1 - 1e-9:
            steps.append(f"colorchannelmixer=aa={clip.opacity:.4f}")
        steps.append("format=rgba")
        steps.append("setsar=1")
        steps = _alpha_before_dynamic_scale(steps)
        steps += _tail_hold(clip)
        return f"[{piece.index}:v]" + ",".join(steps) + f"[v{piece.index}]"

    if _rate_first(piece, project, fps, interpolate):
        steps.append(_rate_chain(piece, fps, interpolate))
        steps.append(_fit_scale(project.width, project.height))
    else:
        steps.append(_fit_scale(project.width, project.height))
        steps.append(_rate_chain(piece, fps, interpolate))
    steps.append("format=rgba")
    steps.append(
        f"pad={project.width}:{project.height}:(ow-iw)/2:(oh-ih)/2:color=black@0"
    )
    steps.append("setsar=1")
    steps += _tail_hold(clip)
    return f"[{piece.index}:v]" + ",".join(steps) + f"[v{piece.index}]"


# Quanto um bloco de vídeo pode segurar o último quadro quando a trilha de vídeo
# acaba antes do bloco. Cobre a sobra comum do container (AAC, 23,976 fps) em
# projetos gravados antes de o bloco durar a trilha de vídeo; uma parte só de
# áudio de verdade, mais longa que isto, continua preta como no arquivo.
_TAIL_HOLD_SECONDS = 1.0


def _tail_hold(clip: Clip) -> list[str]:
    """Segura o último quadro de um bloco de vídeo em vez de deixar preto.

    Os quadros clonados passam do fim do bloco, mas a janela ``enable`` do
    ``overlay`` não os desenha fora dele: só preenchem o vão entre o fim da
    trilha de vídeo e o fim do bloco.
    """
    if clip.media is None or clip.media.kind is not MediaKind.VIDEO:
        return []
    return [f"tpad=stop_mode=clone:stop_duration={_TAIL_HOLD_SECONDS:.3f}"]


def _rate_first(
    piece: _Piece, project: Project, fps: float, interpolate: bool
) -> bool:
    """Se a taxa é ajustada **antes** do encaixe na tela.

    A regra é uma só: **o trabalho pesado acontece no menor dos dois tamanhos.**

    Duplicar quadro é sempre depois de encaixar. Assim o ``scale`` recebe os
    quadros da origem (24) em vez dos da tela (60) — a duplicação em si é de
    graça, porque o ffmpeg só repassa o mesmo quadro.

    Interpolar é o contrário quando a tela é **maior** que o material: estimar
    movimento em pixels que o ``scale`` acabou de inventar custa o tamanho da
    tela e não acrescenta informação nenhuma — o movimento está nos pixels
    originais. Subir depois sai mais barato e mais fiel.

    A ordem não é detalhe de desempenho: a memória do ``minterpolate`` é função
    do tamanho do quadro (medido: 1,6 GB a 1080p, 5,6 GB a 4K, com 20 s gastando
    o mesmo que 5 s). Interpolar um material 1080p numa tela 4K reservava os
    5,6 GB **sem nada em troca**, e foi assim que uma exportação sozinha comeu a
    memória da máquina.
    """
    if not _interpolates(piece, fps, interpolate):
        return False
    media = piece.clip.media
    if not media.width or not media.height:
        # Sem saber o tamanho da origem, encaixar primeiro é o lado seguro: a
        # tela é um teto conhecido, e o do material não.
        return False
    return media.width * media.height < project.width * project.height


def _fit_scale(width: int, height: int) -> str:
    """Encaixa o bloco na tela **pela forma com que ele é exibido**.

    ``force_original_aspect_ratio=decrease`` mede a proporção em pixels
    armazenados e ignora a proporção do pixel; com o ``setsar=1`` logo depois, um
    arquivo de pixel não quadrado — rip de DVD, filmadora antiga — saía achatado
    na horizontal. Medido: uma fonte 720×480 com pixel 32:27 (exibida em 16:9)
    saía 720×480 quadrado, ou seja 3:2. Nada falhava; a imagem só ficava
    espremida.

    ``dar`` é a proporção de exibição da entrada, que o ffmpeg já calcula com o
    pixel embutido. Onde o arquivo não informa o pixel, ele assume quadrado e a
    conta devolve o mesmo de antes (conferido com uma entrada de ``sar``
    desconhecido). O arredondamento para par é exigência dos codificadores.
    """
    largest = f"min({width},{height}*dar)"
    tallest = f"min({height},{width}/dar)"
    return f"scale=w='trunc({largest}/2)*2':h='trunc({tallest}/2)*2'"


def _audio_chain(
    piece: _Piece,
    muted_ranges: tuple[tuple[float, float], ...] = (),
    fades: tuple[tuple[str, float, float], ...] = (),
) -> str:
    """Monta o áudio do bloco com envelopes no relógio local da entrada.

    Os intervalos recebidos usam o relógio da saída. Convertê-los pelo
    ``piece.offset`` é indispensável: o áudio do segundo clipe começa em zero
    antes do ``adelay``. Aplicar ali o tempo absoluto do projeto fazia o mudo e
    o fade acontecerem vários segundos depois do corte.
    """
    clip = piece.clip
    if abs(clip.speed - 1.0) >= 0.01:
        steps = [f"atrim=duration={piece.duration * clip.speed:.6f}", "asetpts=PTS-STARTPTS"]
        steps += _atempo_filters(clip.speed)
    else:
        steps = [f"atrim=duration={piece.duration:.6f}", "asetpts=PTS-STARTPTS"]
    if abs(clip.gain_db) >= 0.05:
        steps.append(f"volume={clip.gain_db:.2f}dB")
    steps.append(_AUDIO_BASE)
    steps.append(
        _MONO_TO_STEREO if clip.media.channels == 1 else _TO_STEREO
    )
    for start, end in muted_ranges:
        local_start = start - piece.offset
        local_end = end - piece.offset
        if local_end > -1e-6 and local_start < piece.duration + 1e-6:
            steps.append(
                f"volume=0:enable='between(t,{local_start:.6f},{local_end:.6f})'"
            )
    for kind, start, end in fades:
        duration = end - start
        if duration <= 1e-6:
            continue
        local_start = start - piece.offset
        local_end = end - piece.offset
        if local_end <= -1e-6 or local_start >= piece.duration + 1e-6:
            continue
        progress = f"(t-{local_start:.6f})/{duration:.6f}"
        if kind == "out":
            gain = (
                f"if(lte(t,{local_start:.6f}),1,"
                f"if(gte(t,{local_end:.6f}),0,cos({progress}*PI/2)))"
            )
        else:
            gain = (
                f"if(lte(t,{local_start:.6f}),0,"
                f"if(gte(t,{local_end:.6f}),1,sin({progress}*PI/2)))"
            )
        # Seno/cosseno dão uma passagem perceptualmente mais uniforme que duas
        # retas de amplitude. ``eval=frame`` acompanha o relógio continuamente.
        steps.append(f"volume='{gain}':eval=frame")
    if piece.offset > 0:
        # ``all=1`` aplica o atraso a todos os canais; sem ele, só o primeiro
        # canal é atrasado e o bloco sai com a imagem à frente do som num lado.
        steps.append(f"adelay={int(piece.offset * 1000)}:all=1")
    return f"[{piece.index}:a]" + ",".join(steps) + f"[a{piece.index}]"


@dataclass(frozen=True)
class _TransitionSide:
    """Trecho de uma fonte necessário para cobrir uma transição centralizada."""

    clip: Clip
    index: int
    seek: float
    source_duration: float
    prepad: float
    postpad: float
    duration: float
    playback_speed: float


@dataclass(frozen=True)
class _TransitionRender:
    context: TransitionContext
    left: _TransitionSide
    right: _TransitionSide
    crop: float
    offset: float
    visible_duration: float
    audio: bool
    left_additionals: tuple[_Piece, ...]
    right_additionals: tuple[_Piece, ...]


def _transition_additional_pieces(
    project: Project,
    context: TransitionContext,
    side: str,
    first_input: int,
) -> tuple[tuple[_Piece, ...], int]:
    """Adicionais que pertencem ao lado esquerdo ou direito da passagem.

    Um item que cruza o corte existe nos dois lados e por isso permanece
    contínuo. Um item que termina no corte só existe à esquerda e sai com a
    transição; um que começa ali só existe à direita e entra com ela. Imagem e
    texto são fontes estáticas, portanto podem cobrir a metade de alça sem
    inventar movimento. Filtros não têm entrada própria e seguem a mesma janela.
    """
    result: list[_Piece] = []
    next_input = first_input
    for track_index, track in reversed(tuple(enumerate(project.tracks))):
        if not track.visible or track.kind is not TrackKind.ADDITIONAL:
            continue
        # Com a ordem livre, uma trilha de adicionais pode estar **abaixo** da
        # trilha da transição. Ela não passa por cima do efeito e não pode
        # entrar nos lados dele: seria desenhada acima do vídeo que a cobre.
        if track_index >= context.track_index:
            continue
        for clip in track.sorted_clips():
            if clip.is_transition or not clip.has_image:
                continue
            if side == "left":
                active_start = max(context.start, clip.start)
                active_end = min(context.cut, clip.end)
                if active_end - active_start <= 1e-6:
                    continue
                begin = active_start
                end = context.end if clip.end >= context.cut - 1e-6 else clip.end
                source_at = active_start
            else:
                active_start = max(context.cut, clip.start)
                active_end = min(context.end, clip.end)
                if active_end - active_start <= 1e-6:
                    continue
                begin = context.start if clip.start <= context.cut + 1e-6 else clip.start
                end = min(context.end, clip.end)
                source_at = begin
            begin = max(context.start, begin)
            end = min(context.end, end)
            if end - begin <= 1e-6:
                continue
            index = -1 if clip.overlay_type == "filter" else next_input
            if index >= 0:
                next_input += 1
            result.append(
                _Piece(
                    clip=clip,
                    index=index,
                    seek=clip.source_time(source_at),
                    offset=begin - context.start,
                    duration=end - begin,
                    track_index=track_index,
                    track_muted=track.muted,
                )
            )
    return tuple(result), next_input


def _is_continuous_source_cut(context: TransitionContext) -> bool:
    """Se o corte veio da tesoura sem alterar o relógio da mesma origem."""
    return bool(
        context.left.media.path == context.right.media.path
        and context.left.media.kind is context.right.media.kind
        and abs(context.left.out_point - context.right.in_point) <= 1e-4
        and abs(context.left.speed - context.right.speed) <= 1e-6
    )


def _transition_side(
    clip: Clip,
    index: int,
    center: float,
    duration: float,
) -> _TransitionSide:
    """Calcula alças de mídia e o preenchimento necessário numa das pontas.

    Mantém a velocidade real do clipe e o sincronismo temporal com a linha do
    tempo tanto em mídias distintas quanto em cortes contínuos da mesma origem.
    """
    speed = max(0.01, clip.speed)
    half_source = duration * speed / 2.0
    wanted_start = center - half_source
    wanted_end = center + half_source
    playback_speed = speed
    actual_start = max(0.0, wanted_start)
    actual_end = wanted_end
    if clip.media.duration is not None:
        actual_end = min(actual_end, clip.media.duration)
    actual_end = max(actual_start, actual_end)
    return _TransitionSide(
        clip=clip,
        index=index,
        seek=actual_start,
        source_duration=max(0.001, actual_end - actual_start),
        prepad=max(0.0, (actual_start - wanted_start) / playback_speed),
        postpad=max(0.0, (wanted_end - actual_end) / playback_speed),
        duration=duration,
        playback_speed=playback_speed,
    )


def _has_audio_handles(context: TransitionContext) -> bool:
    """Se os dois áudios cobrem a sobreposição sem silêncio inventado.

    Vídeo pode sustentar um quadro quando falta material. Repetir amostras de
    áudio produziria zumbido; preencher com zero, como antes, abria um buraco no
    centro. O crossfade integral só é usado quando existem alças reais nos dois
    lados. Sem elas, o áudio normal recebe fades curtos até/depois do corte.
    """
    half = context.duration / 2.0
    left_media_end = context.left.media.duration
    if left_media_end is None:
        return False
    left_handle = max(0.0, (left_media_end - context.left.out_point) / context.left.speed)
    right_handle = max(0.0, context.right.in_point / context.right.speed)
    return left_handle + 1e-6 >= half and right_handle + 1e-6 >= half


def _transition_input_args(side: _TransitionSide, fps: float) -> list[str]:
    if side.clip.media.kind is MediaKind.IMAGE:
        return [
            "-loop", "1", "-framerate", f"{fps:.6f}",
            "-t", f"{side.duration:.6f}", "-i", str(side.clip.media.path),
        ]
    return ["-ss", f"{side.seek:.6f}", "-i", str(side.clip.media.path)]


def _transition_video_chain(
    side: _TransitionSide,
    project: Project,
    fps: float,
    label: str,
) -> list[str]:
    """Produz uma fonte de tela inteira com duração exata para o ``xfade``."""
    clip = side.clip
    steps = [
        f"trim=duration={side.source_duration:.6f}",
        f"setpts=(PTS-STARTPTS)/{side.playback_speed:.6f}",
        # ``tpad`` só consegue converter segundos em quadros quando estes já
        # têm duração. Alguns MP4 entregam ``duration=0`` no fim do arquivo;
        # aplicado antes de ``fps``, o preenchimento não criava quadro algum e
        # uma transição de 0,2 s a 23,976 fps acabava com apenas 2 ou 3 quadros.
        f"fps={fps:.6f}",
        "settb=AVTB",
    ]
    if side.prepad > 1e-6:
        steps.append(f"tpad=start_mode=clone:start_duration={side.prepad:.6f}")
    if side.postpad > 1e-6:
        steps.append(f"tpad=stop_mode=clone:stop_duration={side.postpad:.6f}")
    # Dois quadros sentinela garantem cobertura até o último instante amostrado
    # da transição. Há duas fronteiras discretas (entrada→fps e tpad→trim), e
    # cada uma pode arredondar para baixo. O ``trim`` seguinte descarta a sobra
    # quando a fonte já era longa o bastante.
    steps.append(f"tpad=stop_mode=clone:stop_duration={2.0 / fps:.6f}")
    steps.extend(
        (
            f"trim=duration={side.duration:.6f}",
            "setpts=PTS-STARTPTS",
            # Restabelece a taxa declarada depois de ``tpad``/``setpts``;
            # ``xfade`` recusa entradas cuja taxa aparece como 1/0.
            f"fps={fps:.6f}",
            "settb=AVTB",
        )
    )

    # Decodificação/alças são específicas da transição; transformação e alfa
    # usam a mesma composição de uma camada normal, no relógio da timeline.
    elapsed = (side.seek - clip.in_point) / side.playback_speed - side.prepad
    local_clip = replace(clip, start=0, duration=side.duration, in_point=0, speed=1,
                         keyframes=tuple(replace(k, time_offset=k.time_offset-elapsed) for k in clip.keyframes))
    decoded = f"{label[:-1]}_decoded]"
    base = f"{label[:-1]}_base]"
    filters = [
        f"[{side.index}:v]" + ",".join(steps) + decoded,
        f"color=c=black@0:s={project.width}x{project.height}:r={fps:.6f}:d={side.duration:.6f},format=rgba{base}",
    ]
    transformed: list[str] = []
    piece = _Piece(local_clip, side.index, 0, 0, side.duration, -1)
    output = _compose_video_piece(transformed, base, piece, project, fps, False,
                                  f"{label[1:-1]}_pose", hold_last=True)
    filters.extend(part.replace(f"[{side.index}:v]", decoded) for part in transformed)
    filters.append(f"{output}format=gbrap,setsar=1,settb=AVTB{label}")
    return filters


def _transition_audio_chain(side: _TransitionSide, label: str) -> str:
    clip = side.clip
    steps = [
        f"atrim=duration={side.source_duration:.6f}",
        "asetpts=PTS-STARTPTS",
        *_atempo_filters(side.playback_speed),
    ]
    if abs(clip.gain_db) >= 0.05:
        steps.append(f"volume={clip.gain_db:.2f}dB")
    steps.extend(
        (
            _AUDIO_BASE,
            _MONO_TO_STEREO if clip.media.channels == 1 else _TO_STEREO,
        )
    )
    if side.prepad > 1e-6:
        steps.append(f"adelay={int(round(side.prepad * 1000))}:all=1")
    if side.postpad > 1e-6:
        steps.append(f"apad=pad_dur={side.postpad:.6f}")
    steps.append(f"atrim=duration={side.duration:.6f}")
    return f"[{side.index}:a]" + ",".join(steps) + label


def _xfade_name(name: str) -> str:
    return {
        "fade": "fade",
        "fadeblack": "fadeblack",
        "fadewhite": "fadewhite",
        "dissolve": "dissolve",
        "wipeleft": "wipeleft",
        "wiperight": "wiperight",
        "slideleft": "slideleft",
        "slideright": "slideright",
        # Nomes antigos permanecem legíveis em projetos já salvos.
        "fade_black": "fadeblack",
        "fade_white": "fadewhite",
    }.get(name, "fade")


def _compose_video_piece(
    filters: list[str],
    current: str,
    piece: _Piece,
    project: Project,
    fps: float,
    interpolate: bool,
    order: int | str,
    excluded_ranges: tuple[tuple[float, float], ...] = (),
    hold_last: bool = False,
    canonical_size: tuple[int, int] | None = None,
    label_suffix: str = '',
) -> str:
    """Aplica um bloco visual e devolve o novo rótulo da composição."""
    start, end = piece.offset, piece.offset + piece.duration
    enable = f"gte(t,{start:.6f})*lt(t,{end:.6f})"
    for excluded_start, excluded_end in excluded_ranges:
        if excluded_end <= start + 1e-6 or excluded_start >= end - 1e-6:
            continue
        enable += (
            f"*not(gte(t,{excluded_start:.6f})*lt(t,{excluded_end:.6f}))"
        )
    if piece.clip.overlay_type == "filter":
        name = piece.clip.filter_name
        if name == "pb":
            expression = f"hue=s=0:enable='{enable}'"
        elif name == "sepia":
            expression = (
                f"colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"
                f":enable='{enable}'"
            )
        elif name == "vinheta":
            expression = f"vignette=PI/4:enable='{enable}'"
        elif name == "inverter":
            expression = f"negate=enable='{enable}'"
        elif name == "contraste":
            expression = f"eq=contrast=1.5:enable='{enable}'"
        else:
            expression = f"hue=s=0:enable='{enable}'"
        label = f"[f{order}]"
        filters.append(f"{current}{expression}{label}")
        return label

    video_label = f'[v{piece.index}{label_suffix}]'
    filters.append(_video_chain(piece, project, fps, interpolate, canonical_size=canonical_size)
                   .replace(f'[v{piece.index}]', video_label))
    label = f"[o{order}]"
    is_overlay_item = piece.clip.overlay_type in ("image", "text") or piece.clip.is_image
    has_transform = (
        piece.clip.has_keyframes
        or abs(piece.clip.x - 0.5) > 1e-9
        or abs(piece.clip.y - 0.5) > 1e-9
        or abs(getattr(piece.clip, "scale_x", piece.clip.scale) - 1.0) > 1e-9
        or abs(getattr(piece.clip, "scale_y", piece.clip.scale) - 1.0) > 1e-9
        or abs(piece.clip.rotation) > 1e-9
        or piece.clip.chromakey_enabled
        or piece.clip.opacity < 1 - 1e-9
    )
    if piece.clip.has_keyframes:
        origin = _clip_stream_origin(piece)
        expr_x = _keyframe_expr(piece.clip.keyframes, "x", origin, piece.clip.x)
        expr_y = _keyframe_expr(piece.clip.keyframes, "y", origin, piece.clip.y)
        coordinates = f"x='round(({expr_x})*W-w/2)':y='round(({expr_y})*H-h/2)'"
    elif is_overlay_item or has_transform:
        coordinates = (
            f"x='round(({piece.clip.x:.6f})*W-w/2)':y='round(({piece.clip.y:.6f})*H-h/2)'"
        )
    else:
        coordinates = "x=0:y=0"
    eof = "repeat:repeatlast=1" if hold_last else "pass:repeatlast=0"
    filters.append(
        f"{current}{video_label}"
        f"overlay={coordinates}:eof_action={eof}:format=auto"
        f":enable='{enable}'{label}"
    )
    return label


def _compose_video_transition(
    filters: list[str],
    current: str,
    render: _TransitionRender,
    project: Project,
    fps: float,
    number: int,
    interpolate: bool,
    canonical_size: tuple[int, int] | None = None,
) -> str:
    left_label = f"[tr{number}a]"
    right_label = f"[tr{number}b]"
    filters.extend(_transition_video_chain(render.left, project, fps, left_label))
    filters.extend(_transition_video_chain(render.right, project, fps, right_label))
    visible_label = _transition_window(filters, left_label, right_label, render, fps, str(number), alpha=True)
    label = f"[to{number}]"
    filters.append(
        f"{current}{visible_label}overlay=x=0:y=0:eof_action=repeat:repeatlast=1:format=auto:"
        f"enable='{_ranges_enable(((render.offset, render.offset+render.visible_duration),))}'{label}"
    )
    return label


def _ranges_enable(ranges: tuple[tuple[float, float], ...]) -> str:
    return '+'.join(f'gte(t,{a:.6f})*lt(t,{b:.6f})' for a, b in ranges) or '0'


def _transition_window(filters: list[str], left: str, right: str,
                       render: _TransitionRender, fps: float, name: str, *, alpha: bool = False) -> str:
    """Mantém a fase do xfade mesmo quando a busca começa no meio de um frame."""
    raw, visible = f'[trx{name}]', f'[trv{name}]'
    if alpha:
        # A interpolação deve ponderar cores pela cobertura de cada lado.
        # Misturar RGB e alfa independentes produz halos e cores indevidas
        # quando uma das fontes é transparente ou tem opacidade diferente.
        for suffix, source in (('a', left), ('b', right)):
            filters.append(f'{source}premultiply=inplace=1[trpremul{name}{suffix}]')
        left, right = f'[trpremul{name}a]', f'[trpremul{name}b]'
    filters.append(f'{left}{right}xfade=transition={_xfade_name(render.context.marker.transition_name)}:'
                   f'duration={render.context.duration:.6f}:offset=0{raw}')
    if alpha:
        straight = f'[trstraight{name}]'
        filters.append(f'{raw}unpremultiply=inplace=1{straight}')
        raw = straight
    crop = math.floor(render.crop * fps + 1e-6) / fps
    duration = render.visible_duration + render.crop - crop
    filters.append(f'{raw}trim=start={crop:.6f}:duration={duration:.6f},'
                   f'setpts=PTS-STARTPTS+{render.offset:.6f}/TB{visible}')
    return visible


def _additional_windows(renders: list[_TransitionRender], track_index: int, clip_id: int | None = None
                        ) -> dict[int, tuple[tuple[float, float], ...]]:
    """Particiona o tempo; somente a transição elegível mais alta vence."""
    candidates = {i: r for i, r in enumerate(renders)
                  if any(p.track_index == track_index and (clip_id is None or p.clip.clip_id == clip_id)
                         for p in (*r.left_additionals, *r.right_additionals))}
    edges = sorted({t for r in candidates.values() for t in (r.offset, r.offset+r.visible_duration)})
    result: dict[int, list[tuple[float, float]]] = {}
    for a, b in zip(edges, edges[1:]):
        active = [i for i, r in candidates.items() if r.offset <= a < r.offset+r.visible_duration]
        if active:
            winner = min(active, key=lambda i: (renders[i].context.track_index, renders[i].context.marker.clip_id))
            result.setdefault(winner, []).append((a, b))
    return {i: tuple(ranges) for i, ranges in result.items()}


def _compose_mixed_additional_windows(filters, current, renders, track_index, windows,
                                      clip_windows, normal_parts, project, fps, canonical_size):
    """Arbitra por item quando passagens diferentes alcançam a mesma trilha.

    Um item pode estar na alça de uma passagem inferior sem pertencer à superior.
    Agrupar apenas pela trilha apagaria esse item. Particionamos tempo e pilha,
    conservando juntos itens consecutivos que têm o mesmo controlador.
    """
    normal = {p.clip.clip_id: p for p in normal_parts if p.track_index == track_index}
    ordered = [c for c in project.tracks[track_index].sorted_clips() if c.has_image and not c.is_transition]
    intervals = sorted(interval for ranges in windows.values() for interval in ranges)
    for window, (a, b) in enumerate(intervals):
        groups: list[tuple[int | None, list[int]]] = []
        for clip in ordered:
            winner = next((i for i, ranges in clip_windows[clip.clip_id].items()
                           if any(start <= a < end for start, end in ranges)), None)
            if groups and groups[-1][0] == winner:
                groups[-1][1].append(clip.clip_id)
            else:
                groups.append((winner, [clip.clip_id]))
        for group, (winner, identities) in enumerate(groups):
            name = f'm{track_index}w{window}g{group}'
            if winner is None:
                for index, identity in enumerate(identities):
                    piece = normal.get(identity)
                    if piece is None or piece.offset >= b or piece.offset + piece.duration <= a:
                        continue
                    current = _compose_video_piece(filters, current, piece, project, fps, False,
                                                    f'{name}n{index}', ((0, a), (b, project.export_duration)),
                                                    canonical_size=canonical_size, label_suffix=f'_{name}n{index}')
                continue
            render = renders[winner]
            part = replace(render,
                           left_additionals=tuple(p for p in render.left_additionals if p.clip.clip_id in identities),
                           right_additionals=tuple(p for p in render.right_additionals if p.clip.clip_id in identities))
            current = _compose_additional_transition(filters, current, part, track_index, ((a, b),),
                                                      project, fps, name, canonical_size)
    return current


def _compose_additional_transition(filters: list[str], current: str, render: _TransitionRender,
                                   track_index: int, ranges: tuple[tuple[float, float], ...],
                                   project: Project, fps: float, name: str,
                                   canonical_size: tuple[int, int]) -> str:
    """Aplica a passagem na camada original do adicional, sem rebaixá-lo ao vídeo."""
    sides = [[p for p in pieces if p.track_index == track_index]
             for pieces in (render.left_additionals, render.right_additionals)]
    effects = [p for side in sides for p in side if p.clip.overlay_type == 'filter']
    if effects:
        # Filtros recebem os pixels compostos de cada lado, inclusive o fundo.
        # As passagens espaciais compensam o movimento desse fundo abaixo.
        transition = _xfade_name(render.context.marker.transition_name)
        original, left_base, right_base = f'[pointbase{name}]', f'[pointleft{name}]', f'[pointright{name}]'
        recovery = f'[pointrecovery{name}]'
        if transition == 'fadeblack':
            filters.append(f'{current}split=4{original}{left_base}{right_base}{recovery}')
        else:
            filters.append(f'{current}split=3{original}{left_base}{right_base}')
        prepared = []
        for index, (side, base) in enumerate(zip(sides, (left_base, right_base))):
            label = f'[pointlocal{name}_{index}]'
            filters.append(f'{base}trim=start={render.offset:.6f},setpts=PTS-STARTPTS,fps={fps:.6f},'
                           f'tpad=start_mode=clone:start_duration={render.crop:.6f}:'
                           f'stop_mode=clone:stop_duration={render.context.duration:.6f},'
                           f'trim=duration={render.context.duration:.6f},settb=AVTB{label}')
            transition = _xfade_name(render.context.marker.transition_name)
            if transition in ('slideleft', 'slideright'):
                # Compensa só o deslocamento do fundo. Os adicionais continuam
                # deslizando; o vídeo inferior já composto permanece no lugar.
                direction = '-' if transition == 'slideleft' else '+'
                x = f'mod(mod(X{direction}floor(W*T/{render.context.duration:.6f}),W)+W,W)'
                shifted = f'[pointshifted{name}_{index}]'
                filters.append(f"{label}format=gbrap,geq=r='r({x},Y)':g='g({x},Y)':"
                               f"b='b({x},Y)':a='alpha({x},Y)':interpolation=nearest{shifted}")
                label = shifted
            for item, piece in enumerate(side):
                label = _compose_video_piece(filters, label, piece, project, fps, False,
                                              f'{name}_{index}_{item}', hold_last=True, canonical_size=canonical_size,
                                              label_suffix=f'_{name}_{index}_{item}')
            output = f'[pointprepared{name}_{index}]'
            filters.append(f'{label}format=gbrap,setsar=1,settb=AVTB{output}')
            prepared.append(output)
        visible = _transition_window(filters, *prepared, render, fps, name, alpha=True)
        if transition == 'fadeblack':
            # O preto faz os adicionais desaparecerem, revelando o fundo. A
            # curva vem do próprio xfade, sem aproximar suas fases por uma rampa.
            white_a, white_b = f'[white{name}a]', f'[white{name}b]'
            filters.append(f'color=c=white:s={project.width}x{project.height}:r={fps:.6f}:'
                           f'd={render.context.duration:.6f},format=gbrp,settb=AVTB,split=2{white_a}{white_b}')
            weight = _transition_window(filters, white_a, white_b, render, fps, f'{name}weight')
            black, rgb_base, rgb_weight = f'[black{name}]', f'[recoverrgb{name}]', f'[weightrgb{name}]'
            filters.append(f'color=c=black:s={project.width}x{project.height}:r={fps:.6f}:'
                           f'd={project.export_duration:.6f},format=gbrp,settb=AVTB{black}')
            filters.append(f'{recovery}format=gbrp{rgb_base}')
            filters.append(f'{weight}format=gbrp{rgb_weight}')
            restored, rgb_visible, combined = f'[restored{name}]', f'[visiblergb{name}]', f'[combined{name}]'
            filters.append(f'{rgb_base}{black}{rgb_weight}maskedmerge=planes=7{restored}')
            filters.append(f'{visible}format=gbrp{rgb_visible}')
            filters.append(f'{rgb_visible}{restored}blend=all_mode=addition{combined}')
            visible = combined
        result = f'[pointout{name}]'
        filters.append(f'{original}{visible}overlay=x=0:y=0:eof_action=repeat:repeatlast=1:format=auto:'
                       f"enable='{_ranges_enable(ranges)}'{result}")
        return result
    labels = []
    for index, side in enumerate(sides):
        label = f'[additional{name}_{index}]'
        filters.append(f'color=c=black@0:s={project.width}x{project.height}:r={fps:.6f}:'
                       f'd={render.context.duration:.6f},format=rgba{label}')
        for item, piece in enumerate(side):
            label = _compose_video_piece(filters, label, piece, project, fps, False,
                                          f'{name}_{index}_{item}', hold_last=True, canonical_size=canonical_size,
                                          label_suffix=f'_{name}_{index}_{item}')
        prepared = f'[prepared{name}_{index}]'
        filters.append(f'{label}format=gbrap,setsar=1,settb=AVTB{prepared}')
        labels.append(prepared)
    visible = _transition_window(filters, labels[0], labels[1], render, fps, name, alpha=True)
    output = f'[additionalout{name}]'
    filters.append(f'{current}{visible}overlay=x=0:y=0:eof_action=repeat:repeatlast=1:format=auto:'
                   f"enable='{_ranges_enable(ranges)}'{output}")
    return output


@dataclass(frozen=True)
class Graph:
    """Entradas e filtros prontos, com os rótulos de saída."""

    inputs: list[str]
    filters: list[str]
    video_label: str | None
    audio_label: str | None


def build_graph(
    project: Project,
    *,
    at: float = 0.0,
    span: float | None = None,
    fps: float | None = None,
    want_video: bool = True,
    want_audio: bool = True,
    interpolate: bool = False,
    text_assets: dict[int, Path] | None = None,
    canonical_size: tuple[int, int] | None = None,
    transparent: bool = False,
) -> Graph:
    """Traduz o projeto num grafo de filtros do ffmpeg.

    ``interpolate`` é pedido **só pela exportação**: ele multiplica o tempo de
    codificação por dezenas, e o mesmo grafo alimenta o quadro parado e a
    reprodução da prévia, que precisam sair na hora. É a única coisa que a
    prévia não mostra do resultado, e a aba diz isso ao lado do controle.
    """
    project = project.for_render()
    fps = fps or project.fps
    pieces = _pieces(project, at, span, want_video=want_video, want_audio=want_audio)
    duration = span if span is not None else max(_MIN_CANVAS, project.export_duration - at)

    inputs: list[str] = []
    filters: list[str] = []
    video_parts: list[_Piece] = []
    audio_parts: list[_Piece] = []

    for piece in pieces:
        inputs += _input_args(piece, fps, text_assets=text_assets)
        # ``has_image``, e não ``media.has_video``: o bloco de "separar áudio"
        # vem de um arquivo com imagem, e pela mídia ele entrava aqui — a
        # composição desenhava o vídeo dele por cima de tudo, no instante em que
        # o som estivesse, e ainda pagava a decodificação.
        if want_video and piece.clip.has_image and not piece.clip.is_transition:
            video_parts.append(piece)
        if want_audio and piece.clip.has_sound and not piece.track_muted:
            audio_parts.append(piece)

    # A transição é resolvida pelo par de IDs, nunca pela quantidade de vídeos
    # que por acaso entrou na janela. Isso permite várias transições no projeto
    # e mantém o mesmo progresso ao renderizar um quadro isolado da prévia.
    transition_renders: list[_TransitionRender] = []
    audio_edits: list[tuple[TransitionContext, bool]] = []
    next_input = max((piece.index for piece in pieces), default=-1) + 1
    window_end = at + duration
    for context in project.transition_contexts():
        marker_found = project.find(context.marker.clip_id)
        if (
            marker_found is None
            or not project.tracks[marker_found[0]].visible
            or not project.tracks[context.track_index].visible
        ):
            continue
        visible_start = max(at, context.start)
        visible_end = min(window_end, context.end)
        if visible_end - visible_start <= 1e-6:
            continue
        track = project.tracks[context.track_index]
        has_video_transition = bool(
            want_video and context.left.has_image and context.right.has_image
        )
        has_audio_at_cut = bool(
            want_audio
            and not track.muted
            and (context.left.has_sound or context.right.has_sound)
        )
        continuous_source_cut = _is_continuous_source_cut(context)
        continuous_audio = bool(
            continuous_source_cut
            and context.left.has_sound
            and context.right.has_sound
            and abs(context.left.gain_db - context.right.gain_db) < 0.05
        )
        has_audio_transition = bool(
            has_audio_at_cut
            and context.left.has_sound
            and context.right.has_sound
            and _has_audio_handles(context)
            and not continuous_audio
        )
        if has_audio_at_cut and not continuous_audio:
            audio_edits.append((context, has_audio_transition))
        if not has_video_transition and not has_audio_transition:
            continue
        left = _transition_side(
            context.left,
            next_input,
            context.left.out_point,
            context.duration,
        )
        right = _transition_side(
            context.right,
            next_input + 1,
            context.right.in_point,
            context.duration,
        )
        inputs += _transition_input_args(left, fps)
        inputs += _transition_input_args(right, fps)
        next_input += 2
        left_additionals: tuple[_Piece, ...] = ()
        right_additionals: tuple[_Piece, ...] = ()
        if context.marker.transition_affects_additionals and want_video:
            left_additionals, next_input = _transition_additional_pieces(
                project, context, "left", next_input
            )
            for piece in left_additionals:
                inputs += _input_args(piece, fps, text_assets=text_assets)
            right_additionals, next_input = _transition_additional_pieces(
                project, context, "right", next_input
            )
            for piece in right_additionals:
                inputs += _input_args(piece, fps, text_assets=text_assets)
        transition_renders.append(
            _TransitionRender(
                context=context,
                left=left,
                right=right,
                crop=visible_start - context.start,
                offset=visible_start - at,
                visible_duration=visible_end - visible_start,
                audio=has_audio_transition,
                left_additionals=left_additionals,
                right_additionals=right_additionals,
            )
        )

    video_label = None
    if want_video and project.has_video:
        filters.append(
            f"color=c={'black@0' if transparent else 'black'}:s={project.width}x{project.height}"
            f":r={fps:.6f}:d={max(_MIN_CANVAS, duration):.6f}"
            f"{',format=rgba' if transparent else ''}[base]"
        )
        current = "[base]"
        visual_layers = [
            index
            for index, track in reversed(tuple(enumerate(project.tracks)))
            if track.visible and track.kind in (TrackKind.VIDEO, TrackKind.ADDITIONAL)
        ]
        additional_exclusions: dict[int, list[tuple[float, float]]] = {}
        for render in transition_renders:
            interval = (render.offset, render.offset + render.visible_duration)
            for clip in (render.context.left, render.context.right):
                additional_exclusions.setdefault(clip.clip_id, []).append(interval)
        layer_windows = {index: _additional_windows(transition_renders, index)
                         for index in visual_layers if project.tracks[index].kind is TrackKind.ADDITIONAL}
        for track_index, windows in layer_windows.items():
            intervals = [interval for ranges in windows.values() for interval in ranges]
            for clip in project.tracks[track_index].clips:
                additional_exclusions.setdefault(clip.clip_id, []).extend(intervals)
        order = 0
        canon_size = canonical_size or (project.width, project.height)
        for track_index in visual_layers:
            for piece in (part for part in video_parts if part.track_index == track_index):
                current = _compose_video_piece(
                    filters,
                    current,
                    piece,
                    project,
                    fps,
                    interpolate,
                    order,
                    tuple(additional_exclusions.get(piece.clip.clip_id, ())),
                    canonical_size=canon_size,
                )
                order += 1

            windows = layer_windows.get(track_index, {})
            clip_windows = {clip.clip_id: _additional_windows(transition_renders, track_index, clip.clip_id)
                            for clip in project.tracks[track_index].clips if clip.has_image and not clip.is_transition} if windows else {}
            signatures = {tuple((i, ranges) for i, ranges in mapping.items()) for mapping in clip_windows.values()}
            if windows and len(signatures) > 1:
                current = _compose_mixed_additional_windows(filters, current, transition_renders, track_index,
                                                             windows, clip_windows, video_parts, project, fps, canon_size)
            else:
                for number, ranges in windows.items():
                    current = _compose_additional_transition(
                        filters, current, transition_renders[number], track_index, ranges,
                        project, fps, f'{number}layer{track_index}', canon_size)

            # A transição é parte desta trilha de vídeo. Por padrão, aplicá-la
            # antes da próxima camada preserva os Adicionais por cima. Quando o
            # marcador os afeta, eles já chegaram compostos nos dois lados e o
            # intervalo excluído acima impede que sejam desenhados duas vezes.
            for number, render in enumerate(transition_renders):
                context = render.context
                if context.track_index != track_index:
                    continue
                if not context.left.has_image or not context.right.has_image:
                    continue
                current = _compose_video_transition(
                    filters,
                    current,
                    render,
                    project,
                    fps,
                    number,
                    interpolate,
                    canonical_size=canon_size,
                )
        video_label = current

    audio_label = None
    audio_transition_renders = [render for render in transition_renders if render.audio]
    if want_audio and (audio_parts or audio_transition_renders):
        muted_ranges: dict[int, list[tuple[float, float]]] = {}
        fade_ranges: dict[int, list[tuple[str, float, float]]] = {}
        for context, crossfade in audio_edits:
            interval = (
                context.start - at,
                context.end - at,
            )
            if crossfade:
                muted_ranges.setdefault(context.left.clip_id, []).append(interval)
                muted_ranges.setdefault(context.right.clip_id, []).append(interval)
                continue
            # Sem alças, preservar o som da linha do tempo é mais correto que
            # criar uma sobreposição preenchida com silêncio. Só uma rampa de
            # de-click envolve o corte; se um lado está mudo, apenas o lado
            # audível recebe seu envelope.
            if context.left.has_sound:
                fade_ranges.setdefault(context.left.clip_id, []).append(
                    (
                        "out",
                        max(context.start, context.cut - _AUDIO_DECLICK) - at,
                        context.cut - at,
                    )
                )
            if context.right.has_sound:
                fade_ranges.setdefault(context.right.clip_id, []).append(
                    (
                        "in",
                        context.cut - at,
                        min(context.end, context.cut + _AUDIO_DECLICK) - at,
                    )
                )

        labels: list[str] = []
        for piece in audio_parts:
            ranges = tuple(muted_ranges.get(piece.clip.clip_id, ()))
            fades = tuple(fade_ranges.get(piece.clip.clip_id, ()))
            filters.append(_audio_chain(piece, ranges, fades))
            labels.append(f"[a{piece.index}]")

        for number, render in enumerate(audio_transition_renders):
            left_label = f"[tra{number}a]"
            right_label = f"[tra{number}b]"
            filters.append(_transition_audio_chain(render.left, left_label))
            filters.append(_transition_audio_chain(render.right, right_label))
            raw_label = f"[trax{number}]"
            output_label = f"[trao{number}]"
            filters.append(
                f"{left_label}{right_label}acrossfade=d={render.context.duration:.6f}:"
                # Curvas de potência constante: duas retas de amplitude perdem
                # cerca de 3 dB no centro com fontes não correlacionadas.
                f"c1=qsin:c2=qsin{raw_label}"
            )
            delay = int(round(render.offset * 1000))
            filters.append(
                f"{raw_label}atrim=start={render.crop:.6f}:"
                f"duration={render.visible_duration:.6f},asetpts=PTS-STARTPTS,"
                f"adelay={delay}:all=1{output_label}"
            )
            labels.append(output_label)

        joined = "".join(labels)
        if len(labels) == 1:
            audio_label = joined
        else:
            filters.append(
                f"{joined}amix=inputs={len(labels)}:normalize=0"
                # Sem isto o ffmpeg baixa o volume por alguns instantes cada vez
                # que uma das entradas termina, e a mixagem "respira".
                ":dropout_transition=0[mix]"
            )
            audio_label = "[mix]"

    return Graph(inputs, filters, video_label, audio_label)


# ---------------------------------------------------------------------------
# Os três usos
# ---------------------------------------------------------------------------


def export_args(
    project: Project,
    destination: Path,
    tools: FFmpegTools,
    *,
    container: str = 'mp4',
    family: str | None = None,
    hardware: str = hwaccel.SOFTWARE,
    interpolate: bool = False,
    audio_only: bool = False,
    audio_codec: str | None = None,
    quality: str = hwaccel.DEFAULT_QUALITY,
    text_assets: dict[int, Path] | None = None,
) -> list[str]:
    """Comando que grava o projeto inteiro em um arquivo."""
    project = project.for_export()
    if project.is_empty:
        raise ConversionError("Não há nada na linha do tempo para exportar.")

    if audio_only:
        graph = build_graph(project, want_video=False, want_audio=True, text_assets=text_assets)
        if not graph.audio_label:
            raise ConversionError(
                "Não há blocos de áudio audíveis na linha do tempo para exportar."
            )
        args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y", *graph.inputs]
        filters = list(graph.filters)
        if filters:
            filter_text = ";".join(filters)
            args += ["-filter_complex", filter_text]

        target_codec = (audio_codec or container).lower()
        args += ["-map", graph.audio_label, "-vn"]
        if target_codec in ("mp3", "libmp3lame"):
            args += ["-c:a", "libmp3lame", "-b:a", "192k", "-id3v2_version", "3"]
        elif target_codec in ("m4a", "aac"):
            args += ["-c:a", "aac", "-b:a", "192k"]
        elif target_codec in ("flac",):
            args += ["-c:a", "flac"]
        elif target_codec in ("wav", "pcm"):
            args += ["-c:a", "pcm_s16le"]
        elif target_codec in ("opus", "libopus"):
            args += ["-c:a", "libopus", "-b:a", "128k"]
        elif target_codec in ("ogg", "vorbis", "libvorbis"):
            args += ["-c:a", "libvorbis", "-q:a", "5"]
        else:
            args += encode_audio_args(container)
        return args + [
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-progress", "pipe:1",
            "-nostats",
            str(destination),
        ]

    graph = build_graph(project, interpolate=interpolate, text_assets=text_assets)
    codec_family = family or hwaccel.family_for(container)
    encoder = hwaccel.resolve(codec_family, hardware, tools, quality=quality)
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y"]
    # O dispositivo é declarado antes das entradas: o VAAPI precisa dele para
    # abrir o contexto em que os quadros serão enviados à placa.
    args += [*encoder.device, *graph.inputs]

    filters = list(graph.filters)
    video_label = graph.video_label
    if video_label and encoder.filter_suffix:
        filters.append(f"{video_label}{encoder.filter_suffix}[vhw]")
        video_label = "[vhw]"
    if filters:
        filter_text = ";".join(filters)
        args += ["-filter_complex", filter_text]
    if video_label:
        args += ["-map", video_label, "-c:v", encoder.name, *encoder.quality]
        if (
            encoder.name in ("libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_vaapi")
            and container in ("mp4", "mov")
        ):
            args += ["-tag:v", "hvc1"]
    if graph.audio_label:
        args += ["-map", graph.audio_label, *encode_audio_args(container)]
    elif video_label:
        args += ["-an"]
    if not video_label and not graph.audio_label:
        raise ConversionError(
            "Todos os blocos estão mudos ou vazios: não há o que exportar."
        )
    return args + tail_args(container, destination, map_metadata=False)


def _limited_inputs(inputs: list[str]) -> list[str]:
    """Repete o teto de threads de decodificação antes de **cada** entrada.

    ``-threads`` é opção de entrada e vale para a que vem logo depois: pôr uma
    vez só na frente limitaria o primeiro arquivo e deixaria os outros no padrão.

    Vale para quadro parado e reprodução da prévia, não para exportação. Na
    exportação o que se quer é o arquivo pronto antes, e todo núcleo é bem-vindo.
    Na prévia o teto reduz o custo de abrir simultaneamente as duas pontas de
    uma transição; oito threads por entrada ainda deixam ampla folga para
    acompanhar a taxa do material.
    """
    limitados: list[str] = []
    for arg in inputs:
        if arg == "-i":
            limitados += decode_thread_args()
        limitados.append(arg)
    return limitados


def _preview_project(project: Project, size: tuple[int, int]) -> Project:
    """Reduz a tela de composição para a resolução realmente exibida.

    A prévia não ganha informação ao montar uma tela 4K para, no último filtro,
    reduzi-la a poucos pixels do painel. Isso ficava especialmente caro numa
    transição, porque os dois lados do corte precisam existir ao mesmo tempo.
    A composição continua sendo a mesma; somente trabalha em uma resolução
    proporcional, limitada ao tamanho visível. Exportação não passa por aqui.

    Texto é rasterizado antes do compositor e, ao contrário de vídeo e imagem,
    sua entrada já tem tamanho em pixels. A escala compensatória mantém sua
    proporção em relação à tela reduzida.
    """
    max_width = max(2, int(size[0]))
    max_height = max(2, int(size[1]))
    width, height = fit_size(
        project.width,
        project.height,
        min(project.width, max_width),
        min(project.height, max_height),
    )
    width = max(2, int(width) // 2 * 2)
    height = max(2, int(height) // 2 * 2)
    return project.for_render(width, height)


def frame_command(
    project: Project,
    at: float,
    size: tuple[int, int],
    tools: FFmpegTools,
    *,
    text_assets: dict[int, Path] | None = None,
    transparent: bool = False,
    png: bool = False,
) -> list[str]:
    """Comando que devolve **um** quadro da composição, em rgb24 cru.

    A janela é a de **um quadro**, e não a do projeto até o fim: para desenhar
    um instante só interessa o que aparece nele. Sem esse limite, cada quadro da
    navegação abria todos os arquivos seguintes da edição — medido num projeto
    de vinte blocos: vinte arquivos abertos e 0,77 s por quadro, com o custo
    crescendo a cada bloco acrescentado.
    """
    width, height = size
    preview_project = _preview_project(project, size)
    graph = build_graph(
        preview_project,
        at=at,
        span=1.0 / max(1.0, project.fps),
        want_audio=False,
        text_assets=text_assets,
        canonical_size=(project.width, project.height),
        transparent=transparent,
    )
    args = [
        tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error",
        *_limited_inputs(graph.inputs),
    ]
    filters = list(graph.filters)
    if graph.video_label:
        filters.append(f"{graph.video_label}scale={width}:{height}[out]")
        args += ["-filter_complex", ";".join(filters), "-map", "[out]"]
    else:
        # Projeto sem imagem no instante pedido: um quadro preto diz isso melhor
        # que a tela vazia da prévia, que parece falha de carregamento.
        color = 'black@0' if transparent else 'black'
        args += ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:d=0.1,format=rgba"]
    if png:
        return args + ["-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-pix_fmt", "rgba", "pipe:1"]
    return args + [
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"
    ]


def playback_command(
    project: Project,
    at: float,
    size: tuple[int, int],
    tools: FFmpegTools,
    *,
    fps: float,
    text_assets: dict[int, Path] | None = None,
) -> list[str]:
    """Comando que produz o fluxo de quadros da reprodução, a partir de ``at``."""
    width, height = size
    preview_project = _preview_project(project, size)
    graph = build_graph(
        preview_project,
        at=at,
        span=None,
        fps=float(fps),
        want_audio=False,
        text_assets=text_assets,
        canonical_size=(project.width, project.height),
    )
    args = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v",
        "error",
        *_limited_inputs(graph.inputs),
    ]
    filters = list(graph.filters)
    if graph.video_label:
        filters.append(f"{graph.video_label}scale={width}:{height}[out]")
        args += ["-filter_complex", ";".join(filters), "-map", "[out]"]
    else:
        remaining = max(_MIN_CANVAS, project.duration - at)
        args += [
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:r={fps}:d={remaining:.3f}",
        ]
    return args + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def audio_command(
    project: Project,
    at: float,
    tools: FFmpegTools,
    *,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
    text_assets: dict[int, Path] | None = None,
    until: float | None = None,
) -> list[str] | None:
    """Comando que produz a mixagem em PCM, a partir de ``at``.

    ``None`` quando não há som a tocar — o que a interface usa para não abrir
    processo nenhum, em vez de tocar silêncio.

    ``until`` completa com silêncio e corta a mixagem exatamente no fim do loop
    da prévia: o trecho seguinte é emendado quando este acaba, e um som que
    terminasse antes do fim da edição faria a volta ao começo chegar cedo.
    """
    graph = build_graph(project, at=at, span=None, want_video=False, text_assets=text_assets)
    if not graph.audio_label:
        return None
    filters = list(graph.filters)
    label = graph.audio_label
    if until is not None and until > at:
        filters.append(f"{label}apad,atrim=end={until - at:.6f}[loopmix]")
        label = "[loopmix]"
    return [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        *graph.inputs,
        "-filter_complex", ";".join(filters),
        "-map", label,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "pipe:1",
    ]


# ---------------------------------------------------------------------------
# Caminho rápido
# ---------------------------------------------------------------------------


# Quanto de um trecho paralelo é decodificado **além** do fim dele, só para o
# ``minterpolate`` ter o quadro seguinte na hora de inventar os últimos. Sem essa
# sobra, cada emenda perde os quadros que o ``tpad`` clonou: medido, 476 imagens
# distintas com sobra contra 464 sem ela, num vídeo cortado em quatro — doze
# quadros, exatamente quatro por emenda.
_SEGMENT_TAIL = 0.5

# Piso de duração de um trecho. Abaixo disto o que se paga para abrir um
# processo, decodificar a sobra e concatenar come o que se ganha dividindo.
_MIN_SEGMENT = 2.0

# Teto de trechos simultâneos. Mais que isto não acelera — o gargalo passa a ser
# a leitura do mesmo arquivo por todos eles — e multiplica a memória sem retorno.
_MAX_SEGMENTS = 8

# Fração da memória disponível que a exportação pode reservar. O resto fica para
# o sistema e para o que mais estiver aberto: o número que ``available_bytes``
# devolve é um palpite honesto do instante, não uma promessa para os próximos
# minutos, e errar aqui é derrubar a máquina — não ficar lento.
_MEMORY_SHARE = 0.5


def interpolation_segments(
    project: Project,
    *,
    available: int | None,
    cores: int,
) -> int:
    """Em quantos trechos paralelos a interpolação deste projeto pode ser feita.

    O ``minterpolate`` é **de uma thread só** — medido, 110% de CPU numa máquina
    de vinte núcleos — e é o filtro mais caro que esta aplicação usa. Dividir a
    linha do tempo e interpolar os pedaços ao mesmo tempo é a única forma de usar
    o resto da máquina: medido, 43,7 s para 16,6 s em quatro trechos (2,6×), com
    a saída indistinguível da serial (SSIM 0,997, as mesmas 476 imagens
    distintas).

    Devolver ``1`` significa "faça do jeito de sempre, num comando só", e é a
    resposta para tudo que não se encaixa: projeto sem o que interpolar, curto
    demais para dividir, máquina sem núcleos sobrando — e, principalmente,
    **memória desconhecida**. Cada trecho carrega um ``minterpolate`` inteiro, e
    foi exatamente essa memória que já derrubou a máquina uma vez: onde não dá
    para perguntar quanta há, o caminho seguro é não multiplicar nada.
    """
    custo = interpolation_bytes(project)
    if custo <= 0 or project.export_duration < _MIN_SEGMENT * 2:
        return 1
    if available is None:
        return 1

    por_memoria = int(available * _MEMORY_SHARE) // custo
    por_duracao = int(project.export_duration // _MIN_SEGMENT)
    return max(1, min(_MAX_SEGMENTS, cores, por_memoria, por_duracao))


def segment_bounds(duration: float, segments: int) -> tuple[tuple[float, float], ...]:
    """Início e duração de cada trecho, cobrindo a edição inteira sem sobrepor.

    O último absorve o resto da divisão, em vez de todos carregarem um pedaço da
    sobra: assim a soma das durações é exatamente a do projeto, e não uma soma de
    arredondamentos que erra o fim por alguns milissegundos.
    """
    if segments <= 1:
        return ((0.0, duration),)
    passo = duration / segments
    return tuple(
        (i * passo, passo if i < segments - 1 else duration - i * passo)
        for i in range(segments)
    )


def segment_video_args(
    project: Project,
    at: float,
    span: float,
    destination: Path,
    tools: FFmpegTools,
    *,
    container: str = 'mp4',
    family: str | None = None,
    hardware: str = hwaccel.SOFTWARE,
    quality: str = hwaccel.DEFAULT_QUALITY,
    text_assets: dict[int, Path] | None = None,
) -> list[str]:
    """Um trecho da composição, **só vídeo**, para ser concatenado depois.

    O grafo é montado com uma sobra no fim (:data:`_SEGMENT_TAIL`) e a saída é
    cortada em ``span``: é a sobra que dá ao ``minterpolate`` o quadro seguinte
    de que ele precisa para inventar os últimos do trecho. Sem ela a emenda perde
    quadros interpolados, e o que aparece no lugar são clones.

    Áudio não entra aqui de propósito. Emendar trilhas codificadas em pontos
    arbitrários produz salto ou estalo na junção, porque o quadro de áudio não
    termina onde o corte cai; o som sai num passe só, que é barato.
    """
    graph = build_graph(
        project, at=at, span=span + _SEGMENT_TAIL, want_audio=False, interpolate=True
    , text_assets=text_assets)
    if not graph.video_label:
        raise ConversionError("O trecho não tem imagem para exportar.")
    codec_family = family or hwaccel.family_for(container)
    encoder = hwaccel.resolve(codec_family, hardware, tools, quality=quality)
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y", "-progress", "pipe:1"]
    args += [*encoder.device, *graph.inputs]
    filters = list(graph.filters)
    video_label = graph.video_label
    if encoder.filter_suffix:
        filters.append(f"{video_label}{encoder.filter_suffix}[vhw]")
        video_label = "[vhw]"
    filter_text = ";".join(filters)
    args += ["-filter_complex", filter_text]
    args += ["-map", video_label, "-c:v", encoder.name, *encoder.quality]
    if encoder.name in ("libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_vaapi") and container == "mp4":
        args += ["-tag:v", "hvc1"]
    # ``-t`` na saída, e não ``-frames:v``: a conta que interessa é a do tempo,
    # e é ela que faz a soma dos trechos bater com a duração do projeto.
    return args + [
        "-an",
        "-t",
        f"{span:.6f}",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        str(destination),
    ]


def concat_args(
    parts: Path, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Emenda os trechos **sem recodificar**, pelo demuxer ``concat``.

    Todos saíram do mesmo encoder com os mesmos parâmetros e cada um começa em
    keyframe, que são as condições para copiar os dados em vez de decodificar
    tudo de novo — o que jogaria fora o tempo que a divisão economizou.
    """
    return [
        tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(parts),
        "-c", "copy",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        str(destination),
    ]


def audio_only_args(
    project: Project,
    destination: Path,
    tools: FFmpegTools,
    *,
    container: str = 'mp4',
    text_assets: dict[int, Path] | None = None,
) -> list[str] | None:
    """A mixagem inteira num passe só, ou ``None`` se a edição não tem som."""
    graph = build_graph(project, want_video=False, text_assets=text_assets)
    if not graph.audio_label:
        return None
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y"]
    args += [*graph.inputs, "-filter_complex", ";".join(graph.filters)]
    args += ["-map", graph.audio_label, *encode_audio_args(container)]
    return args + [
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        str(destination),
    ]


def mux_args(
    video: Path, audio: Path | None, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Junta imagem e som já prontos, copiando os dois."""
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(video)]
    if audio is not None:
        args += ["-i", str(audio)]
    args += ["-c", "copy"]
    # As duas entradas já foram limitadas pelo projeto. -shortest sobre
    # streams codificadas pode cortar os últimos quadros por diferenças de
    # pacotes AAC e reordenação de B-frames. Preserve todos os pacotes prontos.
    args += ["-map_metadata", "-1", "-map_chapters", "-1"]
    return args + [str(destination)]


__all__ = [
    'simple_trim',
    'as_trim_target',
    'can_interpolate',
    'Composition',
    'FFmpegTools',
    'ConversionError',
    'fit_size',
    'Clip',
    'MediaKind',
    'Project',
    'TrackKind',
    'format_span',
    '_interpolated_clips',
    'image_base_size',
    '_INTERPOLATE_BYTES_PER_PIXEL',
    'interpolation_bytes',
    'describe_export',
]


def interaction_commands(plan, size, tools, *, text_assets=None) -> tuple[list[str], ...]:
    """Fundo e frente canônicos; textura isolada sem recortar pixels da cena."""
    background = frame_command(plan.background, plan.seconds, size, tools, text_assets=text_assets, png=True)
    foreground = frame_command(plan.foreground, plan.seconds, size, tools, text_assets=text_assets,
                               transparent=True, png=True)
    source = _preview_project(plan.source, size)
    pieces = _pieces(source, plan.seconds, 1 / source.fps, want_audio=False)
    piece = next(p for p in pieces if p.clip.clip_id == plan.clip_id)
    graph = _video_chain(piece, source, source.fps, canonical_size=(plan.source.width, plan.source.height),
                         standalone=True)
    # Texto pode exceder o canvas. Conservar a textura inteira, com memória
    # limitada, permite revelar conteúdo ao arrastar sem recorte na borda.
    graph += (f";[v{piece.index}]scale=w='min(iw,{size[0] * 2})':"
              f"h='min(ih,{size[1] * 2})':force_original_aspect_ratio=decrease[texture]")
    texture = [tools.ffmpeg_str, '-nostdin', '-hide_banner', '-v', 'error',
               *_limited_inputs(_input_args(piece, source.fps, text_assets=text_assets)),
               '-filter_complex', graph, '-map', '[texture]',
               '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', '-pix_fmt', 'rgba', 'pipe:1']
    return background, texture, foreground
