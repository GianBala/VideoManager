"""O projeto de edição: trilhas, blocos e as operações sobre eles.

O modelo é **imutável**. Toda operação — mover um bloco, dividir, mudar volume,
colar — devolve um projeto novo, e a interface guarda o anterior numa pilha. É o
que faz o desfazer ser uma linha de código em vez de um caderno de anotações
sobre o que cada ação alterou, e o que garante que nenhuma tela fique segurando
um bloco que já não existe.

**Um bloco não é um pedaço de arquivo, é um pedaço de arquivo colocado em algum
lugar do tempo.** Daí os três números que ele carrega: ``in_point`` diz onde
começa dentro da mídia de origem, ``start`` diz onde começa na linha do tempo, e
``duration`` vale para os dois. Separar as duas linhas do tempo — a do arquivo e
a da edição — é o que permite o mesmo arquivo aparecer duas vezes, em posições
diferentes, sem cópia nenhuma.

**Volume em decibéis, e não em porcentagem.** É a unidade em que se fala de som
("abaixa 3 dB"), é a que o ffmpeg aceita direto, e 0 dB significa exatamente "não
mexe" — enquanto "100%" convida a ser interpretado como um teto.

A ordem de ``tracks`` é a da tela, de cima para baixo: trilhas de vídeo primeiro,
depois as de áudio. Na composição isso se inverte — a trilha de vídeo mais baixa
é o fundo e as de cima são sobrepostas —, que é a convenção de todo editor.
"""

from __future__ import annotations

import threading
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from videomanager.domain.constants import MIN_SEGMENT
from videomanager.domain.constants import MIN_TRANSITION_DURATION
from videomanager.domain.keyframe import ClipTransform
from videomanager.domain.geometry import image_base_size, natural_image_size
from videomanager.domain.i18n import decimal, t, variants
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.keyframe import interpolate_keyframes
from videomanager.domain.timing import source_time, available_duration, frame_index

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    from videomanager.domain.media import LocalMedia

# Duração que uma imagem assume ao entrar na linha do tempo. Cinco segundos é o
# padrão dos editores de consumo, e o bloco pode ser esticado pela alça depois.
IMAGE_DURATION = 5.0

# Limites do volume por bloco. Abaixo de -60 dB é silêncio para qualquer
# ouvido; acima de +12 dB o que se ganha é distorção.
MIN_GAIN_DB = -60.0
MAX_GAIN_DB = 12.0

# Tela de uma edição que ainda não tem imagem nenhuma.
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30.0

# Teto da taxa escolhida **automaticamente**. Acima de 60 fps o ganho é
# imperceptível e o custo não é: um clipe de câmera lenta a 240 fps levaria a
# exportação inteira para 240 fps — arquivo e tempo de codificação oito vezes
# maiores — por ter sido arrastado para a linha do tempo. Pedir mais que isso
# continua possível, mas explicitamente, pela escolha de taxa da tela.
MAX_AUTO_FPS = 60.0


class _IdentitySequence:
    """Reserva também IDs restaurados, para não reutilizá-los após abrir um projeto."""

    def __init__(self) -> None:
        self._last = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._last += 1
            return self._last

    def reserve(self, identity: int) -> None:
        with self._lock:
            self._last = max(self._last, identity)


_clip_ids = _IdentitySequence()
_track_ids = _IdentitySequence()


def next_clip_id() -> int:
    """Identidade nova para inserção, divisão e cópia de blocos."""
    return _clip_ids.next()


def reserve_project_ids(clip_ids: Iterable[int], track_ids: Iterable[int]) -> None:
    """Reserva identidades de um documento antes de gerar quaisquer IDs ausentes."""
    for identity in clip_ids:
        _clip_ids.reserve(identity)
    for identity in track_ids:
        _track_ids.reserve(identity)


class MediaKind(Enum):
    VIDEO = "vídeo"
    IMAGE = "imagem"
    AUDIO = "áudio"


class TrackKind(Enum):
    VIDEO = "vídeo"
    AUDIO = "áudio"
    ADDITIONAL = "adicionais"


@dataclass(frozen=True)
class MediaRef:
    """Uma mídia importada, já inspecionada.

    Guarda o que a composição precisa saber sem reabrir o arquivo: se tem
    imagem, se tem som, o tamanho e a duração.
    """

    path: Path
    kind: MediaKind
    duration: float | None = None  # None numa imagem: ela dura o que mandarem
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = False
    # Número de canais da trilha de áudio. Guardado porque a mixagem trata mono
    # de forma diferente de estéreo (ver ``composer._audio_chain``).
    channels: int | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def has_video(self) -> bool:
        return self.kind in (MediaKind.VIDEO, MediaKind.IMAGE)

    @property
    def natural_duration(self) -> float:
        """Quanto o bloco dura ao ser inserido pela primeira vez."""
        if self.kind is MediaKind.IMAGE:
            return IMAGE_DURATION
        return self.duration or IMAGE_DURATION


def display_width(width: int | None, sar: float | None) -> int | None:
    """Largura com que a imagem é exibida, dado o pixel do arquivo.

    Pixel quadrado (ou desconhecido, que o ffmpeg trata como quadrado) devolve a
    largura como está — que é o caso de praticamente toda mídia atual.
    """
    if not width:
        return None
    if not sar or abs(sar - 1.0) < 1e-3:
        return width
    return max(2, round(width * sar / 2) * 2)


def media_ref(local: LocalMedia) -> MediaRef:
    """Constrói a referência a partir de um arquivo já inspecionado.

    Recebe o resultado do ``probe_file`` em vez de chamá-lo: é o que mantém este
    módulo livre de subprocesso — e o ``converter``, que faz a inspeção, livre
    para importar o compositor sem fechar um ciclo.
    """
    video = local.video
    is_image = local.is_image
    if is_image:
        kind = MediaKind.IMAGE
    elif video is not None and not local.video_is_cover:
        kind = MediaKind.VIDEO
    else:
        kind = MediaKind.AUDIO

    width = display_width(video.width, video.sar) if video else None
    height = video.height if video else None
    if video and width and height and video.rotation:
        radians = math.radians(video.rotation)
        c, s = abs(math.cos(radians)), abs(math.sin(radians))
        width, height = round(width * c + height * s), round(width * s + height * c)
    duration = local.duration
    if (kind is MediaKind.VIDEO and video is not None and video.duration and duration
            and video.duration < duration - 1e-3):
        # O bloco dura o que tem imagem. Com a duração do container, os últimos
        # quadros do bloco saíam pretos — lampejo entre blocos e tela preta na
        # emenda do loop da prévia.
        duration = video.duration
    return MediaRef(
        path=local.path,
        kind=kind,
        duration=None if kind is MediaKind.IMAGE else duration,
        # Largura de **exibição**, e não a de armazenamento: um rip de DVD
        # guarda 720×480 para aparecer em 16:9, e é a forma exibida que decide o
        # formato da tela do projeto. Guardar a largura crua fazia a edição
        # nascer com a proporção errada e a imagem achatada.
        width=width,
        height=height,
        fps=video.fps if video else None,
        has_audio=local.has_audio,
        channels=local.audio.channels if local.audio else None,
    )


@dataclass(frozen=True)
class Clip:
    """Um pedaço de mídia colocado num instante da linha do tempo."""

    media: MediaRef
    start: float
    duration: float
    in_point: float = 0.0
    gain_db: float = 0.0
    muted: bool = False
    # O som deste bloco saiu para uma trilha própria ("separar áudio"). Distinto
    # de ``muted``: mudo é uma escolha que se desfaz no mesmo bloco, separado
    # significa que o som agora se ajusta noutro lugar — e é o que permite à
    # tela dizer isso, em vez de oferecer um controle de volume que não faz nada.
    detached: bool = False
    # Este bloco carrega **só o som** da mídia: é o bloco que "separar áudio"
    # cria. Sem a marca, um bloco de trilha de áudio cuja mídia também tem
    # imagem continuava passando por bloco de vídeo — a composição desenhava a
    # imagem dele por cima da montagem, a trilha de áudio recusava recebê-lo de
    # volta num arrasto e colar mandava o som para a trilha de vídeo.
    audio_only: bool = False
    # Velocidade de reprodução do bloco (1.0 = normal, 2.0 = dobro, 0.5 = metade).
    speed: float = 1.0
    # Posição e transformação para trilhas de adicionais
    x: float = 0.5  # Centro X normalizado (0.0 a 1.0)
    y: float = 0.5  # Centro Y normalizado (0.0 a 1.0)
    scale: float = 1.0  # Fator de escala uniforme (1.0 = padrão)
    scale_x: float = 1.0  # Escala horizontal (1.0 = padrão)
    scale_y: float = 1.0  # Escala vertical (1.0 = padrão)
    rotation: float = 0.0  # Rotação em graus (0.0 a 360.0)
    # Metadados de sobreposições de adicionais
    overlay_type: str = "none"  # "none", "image", "text", "filter"
    text_content: str = ""
    font_family: str = "Sans Serif"
    font_size: int = 36
    font_bold: bool = False
    font_italic: bool = False
    text_color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: int = 0  # 0 significa sem contorno
    filter_name: str = ""  # "pb", "sepia", "contraste", "vinheta", "inverter"
    transition_name: str = ""  # nomes do filtro xfade (fade, dissolve, wipe*, slide*)
    transition_left_id: int | None = None
    transition_right_id: int | None = None
    # Quando habilitado, filtros, imagens e textos das trilhas de Adicionais
    # entram nos dois lados compostos pelo efeito. Desligado preserva o modelo
    # tradicional de trilhas: a transição atua no vídeo e os overlays ficam por
    # cima dela.
    transition_affects_additionals: bool = False
    # Configurações de Fundo Verde (Chroma Key)
    chromakey_enabled: bool = False
    chromakey_color: str = "#00FF00"
    chromakey_similarity: float = 0.25
    chromakey_blend: float = 0.10
    # Opacidade do bloco (1.0 = 100% opaco, 0.0 = transparente)
    opacity: float = 1.0
    # Sequência de quadros-chave para animação de transformações
    keyframes: tuple[Keyframe, ...] = ()
    # Identidade estável, preservada por ``dataclasses.replace``: é por ela que
    # a seleção, o cache de miniaturas e o desfazer reconhecem o mesmo bloco
    # depois de qualquer alteração.
    clip_id: int = field(default_factory=next_clip_id, compare=False)

    def __post_init__(self) -> None:
        _clip_ids.reserve(self.clip_id)
        if self.scale != 1.0 and self.scale_x == 1.0 and self.scale_y == 1.0:
            object.__setattr__(self, "scale_x", self.scale)
            object.__setattr__(self, "scale_y", self.scale)
        object.__setattr__(self, "opacity", max(0.0, min(1.0, float(self.opacity))))
        if self.keyframes and not isinstance(self.keyframes, tuple):
            object.__setattr__(
                self,
                "keyframes",
                tuple(sorted(self.keyframes, key=lambda k: k.time_offset)),
            )

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def out_point(self) -> float:
        return self.in_point + self.duration * self.speed

    @property
    def has_sound(self) -> bool:
        return bool(self.media and self.media.has_audio and not self.muted and not self.detached and not self.is_additional)

    @property
    def has_image(self) -> bool:
        """Se este bloco contribui com imagem para a composição.

        Não basta a mídia ter vídeo: o bloco de "separar áudio" nasce do mesmo
        arquivo e não mostra nada.
        """
        if self.is_transition:
            return False
        if self.overlay_type in ("image", "text", "filter"):
            return True
        return bool(self.media and self.media.has_video and not self.audio_only)

    @property
    def is_additional(self) -> bool:
        """Bloco sem relógio de mídia próprio: imagem, texto, filtro, transição.

        Decide o que vale para o tempo do bloco — sem ``in_point``, fim livre,
        sem som, fora do corte rápido. **Não** decide a trilha: imagem é
        adicional neste sentido e mesmo assim vive na trilha de vídeo (ver
        :attr:`is_overlay`).
        """
        return self.overlay_type in ("image", "text", "filter", "transition") or self.is_image

    @property
    def is_overlay(self) -> bool:
        """Texto e filtro: o que vive nas trilhas de Adicionais."""
        return self.overlay_type in ("text", "filter")

    @property
    def is_transition(self) -> bool:
        """Se este bloco representa uma transição entre dois vídeos."""
        return self.overlay_type == "transition"

    @property
    def can_adjust_sound(self) -> bool:
        """Se faz sentido oferecer volume e mudo para este bloco."""
        return bool(self.media and self.media.has_audio and not self.detached and not self.is_additional)

    @property
    def can_detach_audio(self) -> bool:
        """Somente vídeo com som ainda incorporado permite separar áudio."""
        return self.can_adjust_sound and self.has_image and self.media.kind is MediaKind.VIDEO

    @property
    def is_image(self) -> bool:
        return (
            self.overlay_type in ("none", "image")
            and self.media is not None
            and self.media.kind is MediaKind.IMAGE
        )

    def contains(self, seconds: float) -> bool:
        return self.start <= seconds < self.end

    def source_time(self, seconds: float) -> float:
        """Instante dentro do arquivo que corresponde a um instante da edição."""
        return source_time(max(seconds, self.start), self.start, self.in_point, self.speed)

    @property
    def gain_label(self) -> str:
        if self.detached:
            return t("CLIP_DETACHED")
        if self.muted:
            return t("CLIP_MUTED")
        if abs(self.gain_db) < 0.05:
            return ""
        return f"{decimal(self.gain_db, sign=True)} dB"

    @property
    def speed_label(self) -> str:
        if abs(self.speed - 1.0) < 0.05:
            return ""
        return f"{decimal(self.speed)}x"

    @property
    def has_keyframes(self) -> bool:
        """Indica se este bloco possui animação definida por quadros-chave."""
        return bool(self.keyframes)

    @property
    def peak_scale(self) -> tuple[float, float]:
        """A maior escala que o bloco atinge em cada eixo, parado ou animado.

        É o tamanho em que a imagem dele aparece no máximo: o que o compositor
        entrega à interpolação e o que a estimativa de memória conta.
        """
        return (max([self.scale_x, *(k.scale_x for k in self.keyframes)]),
                max([self.scale_y, *(k.scale_y for k in self.keyframes)]))

    @property
    def base_transform(self) -> ClipTransform:
        """Transformação estática base do clipe."""
        return ClipTransform(
            x=self.x,
            y=self.y,
            scale_x=getattr(self, "scale_x", self.scale),
            scale_y=getattr(self, "scale_y", self.scale),
            rotation=self.rotation,
            opacity=self.opacity,
        )

    def transform_at(self, time_offset: float) -> ClipTransform:
        """Calcula o estado da transformação no tempo relativo informado."""
        return interpolate_keyframes(self.keyframes, time_offset, self.base_transform)

    @property
    def visible_keyframes(self) -> tuple[Keyframe, ...]:
        """Pontos editáveis; suportes fora da janela preservam a curva original."""
        return tuple(k for k in self.keyframes if 0 <= k.time_offset <= self.duration)

    def with_edited_transform(self, offset: float, changes: dict, *, fps: float,
                              whole_animation: bool = False) -> Clip:
        """Edita uma pose ou transforma a curva inteira por comando explícito."""
        names = ("x", "y", "scale_x", "scale_y", "rotation", "opacity")
        # O ponto no fim do clipe também é editável: ele sustenta a curva até
        # a borda. Recuar um quadro editaria outra pose e criaria outro ponto.
        offset = max(0, min(self.duration, offset))
        current = self.transform_at(offset)
        target = replace(current, **{k: v for k, v in changes.items() if k in names})
        if not self.keyframes:
            return replace(self, scale=(target.scale_x + target.scale_y) / 2, **{k: getattr(target, k) for k in names})
        if whole_animation:
            dx, dy = target.x - current.x, target.y - current.y
            rotation = target.rotation - current.rotation
            opacity = max(-min(k.opacity for k in self.keyframes),
                          min(1 - max(k.opacity for k in self.keyframes), target.opacity - current.opacity))
            factors = {}
            for axis in ("scale_x", "scale_y"):
                factor = getattr(target, axis) / max(.000001, getattr(current, axis))
                if abs(factor - 1) < 1e-9:
                    factors[axis] = 1.0
                    continue
                minimum = min(getattr(k, axis) for k in self.keyframes)
                maximum = max(getattr(k, axis) for k in self.keyframes)
                factors[axis] = max(.05 / max(minimum, .000001), min(10 / maximum, factor))
            requested_x = target.scale_x / max(.000001, current.scale_x)
            requested_y = target.scale_y / max(.000001, current.scale_y)
            if abs(requested_x - requested_y) < 1e-9 and abs(requested_x - 1) >= 1e-9:
                # Um redimensionamento proporcional precisa de um único fator,
                # inclusive quando um ponto distante já está no limite da escala.
                values = [value for k in self.keyframes for value in (k.scale_x, k.scale_y)]
                factor = max(.05 / max(min(values), .000001), min(10 / max(values), requested_x))
                factors = {'scale_x': factor, 'scale_y': factor}
            points = tuple(replace(k, x=k.x + dx, y=k.y + dy,
                                   rotation=k.rotation + rotation, opacity=k.opacity + opacity,
                                   scale_x=k.scale_x * factors["scale_x"],
                                   scale_y=k.scale_y * factors["scale_y"]) for k in self.keyframes)
            updated = replace(self, keyframes=points)
        else:
            frame = frame_index(self.start + offset, fps)
            nearest = min((k for k in self.visible_keyframes
                           if frame_index(self.start + k.time_offset, fps) == frame),
                          key=lambda k: abs(k.time_offset - offset), default=None)
            point = Keyframe(nearest.time_offset if nearest else offset,
                             **{k: getattr(target, k) for k in names},
                             easing=nearest.easing if nearest else "linear")
            updated = self.with_keyframe(point)
        pose = updated.transform_at(offset)
        return replace(updated, scale=(pose.scale_x + pose.scale_y) / 2, **{k: getattr(pose, k) for k in names})

    def with_keyframe(self, keyframe: Keyframe) -> Clip:
        """Adiciona ou atualiza um keyframe mantendo a lista ordenada por time_offset."""
        clamped_time = max(0.0, min(self.duration, keyframe.time_offset))
        adjusted = replace(keyframe, time_offset=clamped_time)
        filtered = [
            k for k in self.keyframes if k not in self.visible_keyframes or abs(k.time_offset - clamped_time) >= 1e-9
        ]
        filtered.append(adjusted)
        filtered.sort(key=lambda k: k.time_offset)
        return replace(self, keyframes=tuple(filtered))

    def without_keyframe(self, time_offset: float, tolerance: float = 1e-4) -> Clip:
        """Remove o keyframe presente no instante indicado, caso exista."""
        filtered = tuple(
            k for k in self.keyframes if k not in self.visible_keyframes or abs(k.time_offset - time_offset) >= tolerance
        )
        return replace(self, keyframes=filtered)

    def nearest_keyframe(
        self, time_offset: float, tolerance: float = 1e-4
    ) -> Keyframe | None:
        """Retorna o keyframe mais próximo dentro da tolerância, ou None."""
        for k in self.visible_keyframes:
            if abs(k.time_offset - time_offset) <= tolerance:
                return k
        return None


@dataclass(frozen=True)
class Track:
    """Uma faixa da linha do tempo, com os blocos em ordem de tempo."""

    kind: TrackKind
    clips: tuple[Clip, ...] = ()
    muted: bool = False
    visible: bool = True
    name: str = ""
    track_id: int = field(default_factory=_track_ids.next, compare=False)

    def __post_init__(self) -> None:
        _track_ids.reserve(self.track_id)

    @property
    def title(self) -> str:
        """O nome como aparece na tela.

        O nome é dado do projeto e não se traduz; só o padrão "Vídeo N", que foi
        o aplicativo quem escolheu, sai no idioma da tela. Senão um projeto
        criado em português mostraria "Vídeo 1" no meio da interface em inglês.
        """
        number = _default_number(self.kind, self.name)
        return self.name if number is None else f"{t(_KIND_KEYS[self.kind])} {number}"

    @property
    def duration(self) -> float:
        return max((clip.end for clip in self.clips), default=0.0)

    def clip_at(self, seconds: float) -> Clip | None:
        return next((clip for clip in self.clips if clip.contains(seconds)), None)

    def sorted_clips(self) -> tuple[Clip, ...]:
        return tuple(sorted(self.clips, key=lambda clip: clip.start))

    def gaps(self, ignore: int | None = None) -> list[tuple[float, float]]:
        """Vãos livres da trilha, do começo ao infinito.

        É a lista de onde um bloco pode ser solto. Existe para o arrasto ter
        sempre uma resposta: soltar em cima de outro bloco não cancela o
        movimento, acomoda no vão mais próximo que couber.
        """
        occupied = sorted(
            (clip for clip in self.clips if clip.clip_id != ignore and not clip.is_transition),
            key=lambda clip: clip.start,
        )
        result: list[tuple[float, float]] = []
        cursor = 0.0
        for clip in occupied:
            if clip.start > cursor:
                result.append((cursor, clip.start))
            cursor = max(cursor, clip.end)
        result.append((cursor, float("inf")))
        return result

    def free_range(self, seconds: float, ignore: int | None = None) -> tuple[float, float]:
        """Vão livre que contém ``seconds``, entre os blocos vizinhos.

        É o que limita um arrasto: um bloco só pode ser solto onde cabe, e não
        por cima do vizinho. Sobreposição de vídeo na mesma trilha não tem
        resposta certa — qual dos dois aparece? —, então ela não acontece.
        """
        floor = 0.0
        ceiling = float("inf")
        for clip in self.clips:
            if clip.clip_id == ignore or clip.is_transition:
                continue
            if clip.end <= seconds:
                floor = max(floor, clip.end)
            elif clip.start >= seconds:
                ceiling = min(ceiling, clip.start)
            else:
                # O instante cai dentro de um bloco: não há vão aqui.
                return (clip.start, clip.start)
        return (floor, ceiling)


@dataclass(frozen=True)
class TransitionContext:
    """Uma transição resolvida para o corte e os dois clipes que ela une.

    O marcador guardado no ``.vmp`` é apenas a representação editável na linha
    do tempo. A identidade da transição é o ponto de edição entre ``left`` e
    ``right``; centralizar e limitar a duração aqui impede prévia, exportação e
    interface de inventarem regras diferentes.
    """

    marker: Clip
    left: Clip
    right: Clip
    track_index: int
    cut: float
    duration: float

    @property
    def start(self) -> float:
        return self.cut - self.duration / 2.0

    @property
    def end(self) -> float:
        return self.cut + self.duration / 2.0


@dataclass(frozen=True)
class Project:
    """A edição inteira: trilhas, blocos e o formato da tela."""

    tracks: tuple[Track, ...] = ()
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: float = DEFAULT_FPS
    text_reference_width: int | None = None
    text_reference_height: int | None = None

    def __post_init__(self) -> None:
        if self.text_reference_width is None:
            object.__setattr__(self, "text_reference_width", self.width)
        if self.text_reference_height is None:
            object.__setattr__(self, "text_reference_height", self.height)

    @property
    def text_ratio(self) -> float:
        return min(self.width / self.text_reference_width, self.height / self.text_reference_height)

    def with_output_canvas(self, width: int, height: int, fps: float | None = None) -> Project:
        has_text = any(c.overlay_type == "text" for c in self.clips)
        return replace(self, width=width, height=height, fps=self.fps if fps is None else fps,
                       text_reference_width=self.text_reference_width if has_text else width,
                       text_reference_height=self.text_reference_height if has_text else height)

    def for_render(self, width: int | None = None, height: int | None = None) -> Project:
        """Deriva pixels de saída sem modificar fonte, contorno ou curva de edição."""
        width, height = width or self.width, height or self.height
        ratio = min(width / self.text_reference_width, height / self.text_reference_height)
        if ratio == 1 and (width, height) == (self.width, self.height):
            return self
        tracks = tuple(replace(t, clips=tuple(
            replace(c, scale=1.0, scale_x=c.scale_x * ratio, scale_y=c.scale_y * ratio,
                    keyframes=tuple(replace(k, scale_x=k.scale_x * ratio, scale_y=k.scale_y * ratio)
                                    for k in c.keyframes)) if c.overlay_type == "text" else c
            for c in t.clips)) for t in self.tracks)
        return replace(self, tracks=tracks, width=width, height=height,
                       text_reference_width=width, text_reference_height=height)

    # -- leitura ---------------------------------------------------------

    @property
    def duration(self) -> float:
        # Marcadores de transição descrevem um corte existente; não são
        # conteúdo e nunca podem alongar a edição, nem quando um projeto antigo
        # traz um marcador inválido fora dos clipes.
        return max(
            (
                clip.end
                for track in self.tracks
                for clip in track.clips
                if not clip.is_transition
            ),
            default=0.0,
        )

    @property
    def export_duration(self) -> float:
        return max(self.video_duration, self.audible_duration)

    @property
    def video_duration(self) -> float:
        """Fim da última imagem visível: a duração de uma saída sem som (GIF)."""
        return max((clip.end for clip in self.visible_video_clips), default=0.0)

    @property
    def audible_duration(self) -> float:
        return max((clip.end for clip in self.audible_clips), default=0.0)

    @property
    def is_empty(self) -> bool:
        return not any(track.clips for track in self.tracks)

    @property
    def clips(self) -> tuple[Clip, ...]:
        return tuple(clip for track in self.tracks for clip in track.clips)

    @property
    def visible_video_clips(self) -> tuple[Clip, ...]:
        return tuple(
            clip
            for track in (*self.video_tracks, *self.additional_tracks)
            if track.visible
            for clip in track.clips
            if clip.has_image
        )

    @property
    def video_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.VIDEO)

    @property
    def additional_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.ADDITIONAL)

    @property
    def audio_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.AUDIO)

    @property
    def has_video(self) -> bool:
        return any(
            clip.has_image
            for track in (*self.video_tracks, *self.additional_tracks)
            if track.visible
            for clip in track.clips
        )

    @property
    def has_sound(self) -> bool:
        """Se alguma coisa vai sair pelos alto-falantes."""
        return any(
            clip.has_sound
            for track in self.tracks
            if not track.muted and track.visible
            for clip in track.clips
        )

    @property
    def audible_clips(self) -> tuple[Clip, ...]:
        return tuple(
            clip
            for track in self.tracks
            if not track.muted and track.visible
            for clip in track.clips
            if clip.has_sound
        )

    def for_export(self) -> Project:
        """Devolve uma cópia do projeto para exportação.

        Contém apenas as trilhas que contribuem para a saída:
        trilhas visíveis com blocos (e para áudio, que não estejam totalmente mudas).
        """
        active = tuple(
            t
            for t in self.tracks
            if t.visible and t.clips and not (t.kind is TrackKind.AUDIO and t.muted)
        )
        return replace(self, tracks=active)

    def track_index(self, track_id: int) -> int:
        return next(
            (i for i, track in enumerate(self.tracks) if track.track_id == track_id), -1
        )

    def find(self, clip_id: int) -> tuple[int, Clip] | None:
        """Devolve (índice da trilha, bloco) do bloco pedido."""
        for index, track in enumerate(self.tracks):
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    return index, clip
        return None

    def transition_context(self, marker: Clip) -> TransitionContext | None:
        """Resolve um marcador para um corte válido entre clipes adjacentes.

        Projetos novos carregam os IDs das duas pontas. Para projetos antigos,
        sem esses campos, o corte encostado mais próximo do centro do marcador
        é inferido durante a composição. Marcadores órfãos, entre trilhas
        diferentes, sobre vãos ou sobre clipes não adjacentes não são efeitos
        válidos e portanto não são resolvidos.
        """
        if not marker.is_transition:
            return None

        candidates: list[tuple[float, int, Clip, Clip]] = []
        if marker.transition_left_id is not None and marker.transition_right_id is not None:
            left_found = self.find(marker.transition_left_id)
            right_found = self.find(marker.transition_right_id)
            if left_found is None or right_found is None:
                return None
            left_index, left = left_found
            right_index, right = right_found
            if left_index != right_index:
                return None
            track = self.tracks[left_index]
            if track.kind is not TrackKind.VIDEO:
                return None
            ordered = [c for c in track.sorted_clips() if not c.is_transition]
            try:
                adjacent = ordered.index(right) == ordered.index(left) + 1
            except ValueError:
                return None
            if not adjacent or abs(left.end - right.start) > 1e-4:
                return None
            candidates.append((0.0, left_index, left, right))
        else:
            center = marker.start + marker.duration / 2.0
            for index, track in enumerate(self.tracks):
                if track.kind is not TrackKind.VIDEO:
                    continue
                ordered = [c for c in track.sorted_clips() if not c.is_transition]
                for left, right in zip(ordered, ordered[1:]):
                    if abs(left.end - right.start) > 1e-4:
                        continue
                    distance = abs(center - left.end)
                    if distance <= max(0.05, marker.duration / 2.0 + 1e-4):
                        candidates.append((distance, index, left, right))

        if not candidates:
            return None
        _, index, left, right = min(candidates, key=lambda item: item[0])
        duration = min(marker.duration, left.duration, right.duration)
        if duration <= 0:
            return None
        return TransitionContext(
            marker=marker,
            left=left,
            right=right,
            track_index=index,
            cut=left.end,
            duration=duration,
        )

    def transition_contexts(self) -> tuple[TransitionContext, ...]:
        """Transições válidas, sem permitir duas no mesmo ponto de edição."""
        result: list[TransitionContext] = []
        occupied: set[tuple[int, int, int]] = set()
        for marker in (c for c in self.clips if c.is_transition):
            context = self.transition_context(marker)
            if context is None:
                continue
            key = (context.track_index, context.left.clip_id, context.right.clip_id)
            if key in occupied:
                continue
            occupied.add(key)
            result.append(context)
        return tuple(result)

    def clip_at(self, track_index: int, seconds: float) -> Clip | None:
        if not 0 <= track_index < len(self.tracks):
            return None
        return self.tracks[track_index].clip_at(seconds)

    # -- escrita (sempre devolvendo um projeto novo) ----------------------

    def _replace_track(self, index: int, track: Track) -> Project:
        tracks = list(self.tracks)
        tracks[index] = track
        return replace(self, tracks=tuple(tracks))

    def with_track(self, kind: TrackKind, name: str = "", *, index: int | None = None) -> Project:
        """Acrescenta uma trilha vazia, num lugar previsível da pilha.

        Adicionais entram no topo absoluto. Vídeo entra logo acima da trilha de
        vídeo mais alta — ou, sem vídeo nenhum, antes do primeiro áudio. Áudio
        entra no fim.

        A ordem das trilhas é livre: o usuário arrasta qualquer uma para qualquer
        posição, e é a posição que decide quem aparece por cima. Por isso a
        regra procura as trilhas pela espécie em vez de contar quantos
        adicionais há no topo, o que só valia com a pilha agrupada.
        """
        track = Track(kind=kind, name=name or _default_name(self, kind))
        tracks = list(self.tracks)
        if index is not None:
            # Posição escolhida pelo gesto (soltar mídia entre trilhas).
            tracks.insert(max(0, min(index, len(tracks))), track)
        elif kind is TrackKind.ADDITIONAL:
            tracks.insert(0, track)
        elif kind is TrackKind.VIDEO:
            anchor = next((i for i, t in enumerate(tracks) if t.kind is TrackKind.VIDEO),
                          next((i for i, t in enumerate(tracks) if t.kind is TrackKind.AUDIO), len(tracks)))
            tracks.insert(anchor, track)
        else:
            tracks.append(track)
        return replace(self, tracks=tuple(tracks))

    def without_track(self, track_index: int) -> Project:
        """Remove a trilha inteira, com o que houver nela.

        Não se guarda uma última trilha "por precaução": importar uma mídia cria
        a trilha de que ela precisa (ver ``EditPanel._place``), então uma linha
        do tempo sem trilha nenhuma é um estado válido — e é o que se espera de
        quem acabou de apagar tudo.
        """
        if not 0 <= track_index < len(self.tracks):
            return self
        tracks = list(self.tracks)
        del tracks[track_index]
        return replace(self, tracks=tuple(tracks))

    def reordered_track(self, from_index: int, to_index: int) -> Project:
        """Reordena uma trilha na pilha, movendo de ``from_index`` para ``to_index``.

        Mover uma trilha de vídeo para cima ou para baixo altera a ordem das
        camadas visuais da composição: a trilha no topo da lista sobrepõe as de
        baixo. Para trilhas de áudio, organiza a ordem visual na linha do tempo.
        """
        if from_index == to_index or not (
            0 <= from_index < len(self.tracks) and 0 <= to_index < len(self.tracks)
        ):
            return self
        tracks = list(self.tracks)
        track = tracks.pop(from_index)
        tracks.insert(to_index, track)
        return replace(self, tracks=tuple(tracks))

    def with_clip(self, track_index: int, clip: Clip) -> Project:
        track = self.tracks[track_index]
        clips = tuple(sorted((*track.clips, clip), key=lambda c: c.start))
        return self._replace_track(track_index, replace(track, clips=clips))

    def without_clip(self, clip_id: int) -> Project:
        found = self.find(clip_id)
        if found is None:
            return self
        index, removed = found
        track = self.tracks[index]
        clips = tuple(c for c in track.clips if c.clip_id != clip_id)
        project = self._replace_track(index, replace(track, clips=clips))
        if removed.is_transition:
            return project
        # A transição pertence ao corte, não sobrevive sem qualquer uma das
        # pontas. Um marcador órfão nunca deve se religar por proximidade a
        # vídeos que não faziam parte da edição original.
        tracks = tuple(
            replace(
                item,
                clips=tuple(
                    clip
                    for clip in item.clips
                    if not (
                        clip.is_transition
                        and clip_id in (clip.transition_left_id, clip.transition_right_id)
                    )
                ),
            )
            for item in project.tracks
        )
        return replace(project, tracks=tracks)

    def with_updated_clip(self, clip_id: int, **changes: object) -> Project:
        found = self.find(clip_id)
        if found is None:
            return self
        index, clip = found
        track = self.tracks[index]
        updated = replace(clip, **changes)  # type: ignore[arg-type]
        clips = tuple(
            sorted(
                (updated if c.clip_id == clip_id else c for c in track.clips),
                key=lambda c: c.start,
            )
        )
        updated_project = self._replace_track(index, replace(track, clips=clips))
        if clip.is_transition:
            updated_project = updated_project._sync_transition_markers(clip_id)
        elif {"start", "duration", "in_point", "speed"}.intersection(changes):
            updated_project = updated_project._sync_transition_markers(clip_id)
        return updated_project

    def _sync_transition_markers(self, clip_id: int) -> Project:
        """Mantém marcadores ligados ao corte ou remove os que ficaram órfãos."""
        tracks = []
        changed = False
        for track in self.tracks:
            new_clips = []
            for marker in track.clips:
                affected = marker.is_transition and (
                    marker.clip_id == clip_id
                    or clip_id in (marker.transition_left_id, marker.transition_right_id)
                )
                if not affected:
                    new_clips.append(marker)
                    continue
                context = self.transition_context(marker)
                if context is None:
                    # Marcadores legados sem IDs continuam legíveis. Os novos,
                    # explicitamente ligados, não podem flutuar fora do corte.
                    if marker.transition_left_id is None or marker.transition_right_id is None:
                        new_clips.append(marker)
                    else:
                        changed = True
                    continue
                synced = replace(
                    marker,
                    # Uma transição usa um mínimo próprio. Empregar aqui os
                    # 50 ms de um corte comum permitia salvar efeitos com um só
                    # quadro intermediário, embora a interface anunciasse 0,2 s.
                    duration=max(
                        min(
                            MIN_TRANSITION_DURATION,
                            context.left.duration,
                            context.right.duration,
                        ),
                        context.duration,
                    ),
                )
                synced = replace(
                    synced,
                    start=max(0.0, context.cut - synced.duration / 2.0),
                )
                new_clips.append(synced)
                changed = changed or synced != marker
            tracks.append(replace(track, clips=tuple(sorted(new_clips, key=lambda c: c.start))))
        return replace(self, tracks=tuple(tracks)) if changed else self

    def with_normalized_transitions(self) -> Project:
        """Normaliza marcadores persistidos por versões com regras divergentes."""
        project = self
        for marker in tuple(clip for clip in self.clips if clip.is_transition):
            project = project._sync_transition_markers(marker.clip_id)
        return project

    def with_track_muted(self, track_index: int, muted: bool) -> Project:
        track = self.tracks[track_index]
        return self._replace_track(track_index, replace(track, muted=muted))

    def with_track_visible(self, track_index: int, visible: bool) -> Project:
        track = self.tracks[track_index]
        return self._replace_track(track_index, replace(track, visible=visible))

    def moved(self, clip_id: int, track_index: int, start: float) -> Project:
        """Move um bloco no tempo e, se pedido, para outra trilha.

        Duas regras, e ambas existem para o arrasto **sempre** ter uma resposta:

        **Onde não cabe, encosta.** A posição é acomodada no vão livre mais
        próximo em vez de recusada — o bloco encosta no vizinho em vez de sumir
        de volta para onde estava.

        **Por cima do vizinho, troca de lugar.** Sem isso não havia como
        reordenar uma sequência: dois blocos encostados não deixam vão nenhum
        entre eles, então arrastar o segundo para antes do primeiro caía sempre
        na regra de cima e não fazia nada — nenhum gesto reordenava a edição.
        """
        found = self.find(clip_id)
        if found is None or not 0 <= track_index < len(self.tracks):
            return self
        origin, clip = found
        destination = self.tracks[track_index]
        if not accepts(destination.kind, clip):
            return self

        start = max(0.0, start)
        if origin == track_index and start == clip.start:
            return self
        if origin == track_index:
            swapped = self._swapped(track_index, clip, start)
            if swapped is not None:
                return swapped
        ignore = clip_id if origin == track_index else None
        options = [
            min(max(floor, start), ceiling - clip.duration)
            for floor, ceiling in destination.gaps(ignore=ignore)
            if ceiling - floor >= clip.duration
        ]
        if not options:
            # Nenhum vão comporta o bloco nesta trilha: fica onde estava.
            return self
        start = min(options, key=lambda value: abs(value - start))

        moved = replace(clip, start=start)
        if origin == track_index:
            return self.with_updated_clip(clip_id, start=start)
        return self.without_clip(clip_id).with_clip(track_index, moved)._sync_transition_markers(clip_id)

    def _swapped(self, track_index: int, moving: Clip, start: float) -> Project | None:
        """Troca ``moving`` de lugar com o vizinho do lado para onde ele vai.

        **O gatilho é a ponta da frente passar do meio do vizinho** — a ponta
        esquerda quando se arrasta para trás, a direita quando se arrasta para a
        frente. Passar do meio é a intenção inequívoca de ficar do outro lado;
        antes disso o gesto é justapor, que é o mais comum de todos e não pode
        virar troca sem querer.

        Não serve medir pelo meio do bloco **arrastado**: um bloco mais longo
        que o vizinho encosta no zero antes de o meio dele alcançar o vizinho, e
        aí nenhum arrasto reordenava mais nada.

        Os dois ficam dentro do espaço que já ocupavam juntos, preservando o
        vão entre eles. Como esse espaço nunca cresce, a troca não tem como
        esbarrar num terceiro bloco — e por isso não precisa de exceção.

        Os dois lados são exatamente complementares: o ponto que dispara a troca
        num sentido é o mesmo que a desfaz no outro. É o que impede os blocos de
        ficarem trocando de lugar sozinhos enquanto a mão está parada em cima
        dele.

        ``None`` quando não há troca a fazer: aí vale a acomodação no vão.
        """
        others = [
            clip
            for clip in self.tracks[track_index].clips
            if clip.clip_id != moving.clip_id and not clip.is_transition
        ]
        if start < moving.start:
            partner = max(
                (c for c in others if c.start < moving.start),
                key=lambda c: c.start,
                default=None,
            )
            passed = partner is not None and start < partner.start + partner.duration / 2
        elif start > moving.start:
            partner = min(
                (c for c in others if c.start > moving.start),
                key=lambda c: c.start,
                default=None,
            )
            passed = (
                partner is not None
                and start + moving.duration > partner.start + partner.duration / 2
            )
        else:
            return None
        if partner is None or not passed:
            return None

        first, second = (
            (moving, partner) if moving.start > partner.start else (partner, moving)
        )
        base = min(moving.start, partner.start)
        earlier, later = sorted((moving, partner), key=lambda c: c.start)
        gap = max(0.0, later.start - earlier.end)
        positions = {first.clip_id: base, second.clip_id: base + first.duration + gap}
        track = self.tracks[track_index]
        clips = []
        for clip in track.clips:
            if clip.clip_id in positions:
                clip = replace(clip, start=positions[clip.clip_id])
            elif (clip.is_transition and
                  {clip.transition_left_id, clip.transition_right_id} == {first.clip_id, second.clip_id}):
                clip = replace(clip, transition_left_id=first.clip_id, transition_right_id=second.clip_id)
            clips.append(clip)
        result = self._replace_track(track_index, replace(track, clips=tuple(sorted(clips, key=lambda c: c.start))))
        return result._sync_transition_markers(first.clip_id)._sync_transition_markers(second.clip_id)

    def resized(self, clip_id: int, edge: str, seconds: float) -> Project:
        """Arrasta uma das pontas do bloco, respeitando a mídia e os vizinhos."""
        found = self.find(clip_id)
        if found is None:
            return self
        index, clip = found
        if clip.is_transition:
            context = self.transition_context(clip)
            if context is None:
                return self
            # As duas pontas se movem simetricamente, como nos editores de
            # referência: a transição continua centrada no ponto de edição.
            requested = (
                2.0 * (context.cut - seconds)
                if edge == "inicio"
                else 2.0 * (seconds - context.cut)
            )
            minimum = min(
                MIN_TRANSITION_DURATION,
                context.left.duration,
                context.right.duration,
            )
            duration = min(
                max(minimum, requested),
                context.left.duration,
                context.right.duration,
            )
            return self.with_updated_clip(clip_id, duration=duration)
        floor, ceiling = self.tracks[index].free_range(
            (clip.start + clip.end) / 2, ignore=clip_id
        )

        if edge == "inicio":
            # Uma imagem não tem começo de arquivo para respeitar; um vídeo não
            # pode ser puxado para antes do primeiro quadro que ele tem.
            limit = (
                clip.start - clip.in_point / clip.speed
                if not (clip.is_image or clip.is_additional)
                else floor
            )
            value = min(max(max(floor, limit), seconds), clip.end - MIN_SEGMENT)
            return self.with_updated_clip(
                clip_id,
                start=value,
                duration=clip.end - value,
                in_point=0.0 if clip.is_additional else source_time(value, clip.start, clip.in_point, clip.speed),
                keyframes=tuple(replace(k, time_offset=k.time_offset - (value-clip.start)) for k in clip.keyframes),
            )

        available = (
            float("inf")
            if (clip.is_image or clip.is_additional)
            else available_duration(clip.media.duration or 0.0, clip.in_point, clip.speed)
        )
        value = min(
            max(seconds, clip.start + MIN_SEGMENT), min(ceiling, clip.start + available)
        )
        return self.with_updated_clip(clip_id, duration=value - clip.start)

    def split(self, clip_id: int, seconds: float) -> Project:
        """Divide o bloco no instante dado, como a tesoura da barra."""
        found = self.find(clip_id)
        if found is None:
            return self
        index, clip = found
        if clip.is_transition:
            return self
        if (
            seconds - clip.start < MIN_SEGMENT
            or clip.end - seconds < MIN_SEGMENT
        ):
            return self

        split_offset = seconds - clip.start
        # A janela é a duração do clipe; suportes exteriores continuam na
        # curva para não reiniciar a fase de easings nem aproximar rotações.
        left_kfs = clip.keyframes
        right_kfs = tuple(
            replace(k, time_offset=k.time_offset - split_offset)
            for k in clip.keyframes
        )
        left = replace(clip, duration=split_offset, keyframes=left_kfs)
        right = replace(
            clip,
            start=seconds,
            duration=clip.end - seconds,
            in_point=0.0 if clip.is_additional else clip.source_time(seconds),
            clip_id=next_clip_id(),
            keyframes=right_kfs,
        )
        track = self.tracks[index]
        clips = tuple(
            sorted(
                (left if c.clip_id == clip_id else c for c in track.clips),
                key=lambda c: c.start,
            )
        )
        result = self._replace_track(index, replace(track, clips=(*clips, right)))
        result = replace(result, tracks=tuple(replace(t, clips=tuple(
            replace(c, transition_left_id=right.clip_id)
            if c.is_transition and c.transition_left_id == clip_id else c
            for c in t.clips)) for t in result.tracks))
        return result.tidy().with_normalized_transitions()

    def with_dropped_clip(self, clip: Clip, track_index: int, new_track_index: int) -> tuple[Project, int]:
        """Coloca um bloco novo onde o usuário soltou a mídia, sem mexer em nada.

        Se a trilha sob o ponteiro aceita o bloco e o vão ali comporta a duração
        dele, o bloco fica no instante pedido — encostado na borda do vão quando
        não cabe inteiro a partir dali. Se não — trilha de outra espécie, soltura
        em cima de um bloco, vão curto —, nasce uma trilha da espécie certa em
        ``new_track_index``, com o bloco no instante pedido. Os blocos que já
        estavam na edição nunca são empurrados.

        Devolve o projeto e o índice da trilha que recebeu o bloco.
        """
        if 0 <= track_index < len(self.tracks) and accepts(self.tracks[track_index].kind, clip):
            floor, ceiling = self.tracks[track_index].free_range(clip.start)
            if ceiling - floor >= clip.duration - 1e-9:
                start = min(max(floor, clip.start), ceiling - clip.duration)
                return self.with_clip(track_index, replace(clip, start=max(0.0, start))), track_index
        kind = (
            TrackKind.ADDITIONAL if clip.is_overlay
            else TrackKind.VIDEO if clip.has_image or clip.is_transition
            else TrackKind.AUDIO
        )
        index = max(0, min(new_track_index, len(self.tracks)))
        project = self.with_track(kind, index=index)
        return project.with_clip(index, clip), index

    def detached_audio(self, clip_id: int) -> Project:
        """Separa o som de um bloco de vídeo numa trilha de áudio própria.

        O som **sai** do bloco de vídeo, não é apenas silenciado: a partir daí
        ele se move, se corta e se ajusta sozinho, e é no bloco novo que o
        volume passa a valer. O bloco novo nasce na mesma posição, para o som
        continuar casado com a imagem; desfazer devolve os dois ao que eram.
        """
        found = self.find(clip_id)
        if found is None:
            return self
        _, clip = found
        if not clip.can_detach_audio:
            return self

        project = self.with_updated_clip(clip_id, detached=True, muted=False)
        target = project._free_audio_track(clip.start, clip.duration)
        if target is None:
            project = project.with_track(TrackKind.AUDIO)
            target = len(project.tracks) - 1
        detached = Clip(
            media=clip.media,
            start=clip.start,
            duration=clip.duration,
            in_point=clip.in_point,
            gain_db=clip.gain_db,
            muted=clip.muted,
            speed=clip.speed,
            audio_only=True,
        )
        return project.with_clip(target, detached)

    def _free_audio_track(self, start: float, duration: float) -> int | None:
        for index, track in enumerate(self.tracks):
            if track.kind is not TrackKind.AUDIO:
                continue
            floor, ceiling = track.free_range(start)
            if floor <= start and start + duration <= ceiling:
                return index
        return None

    def tidy(self) -> Project:
        """Reordena os blocos de cada trilha por tempo."""
        return replace(
            self,
            tracks=tuple(replace(t, clips=t.sorted_clips()) for t in self.tracks),
        )

    def with_images_in_video_tracks(self, *, legacy_scale: bool) -> Project:
        """Leva imagens de trilhas de Adicionais para trilhas de vídeo.

        Uma trilha de adicionais só com imagens vira trilha de vídeo, com a
        mesma identidade e posição na pilha. Uma trilha mista ganha, logo acima,
        uma trilha de vídeo com as imagens; como blocos da mesma trilha nunca se
        sobrepõem no tempo, a ordem entre eles não muda o resultado.

        ``legacy_scale`` converte a escala de projetos gravados antes do
        formato 3, em que a imagem aparecia no tamanho natural: o fator é o que
        leva o tamanho novo (ajustado à tela) de volta ao antigo, eixo a eixo e
        também nos quadros-chave. Assim a foto continua do mesmo tamanho e no
        mesmo lugar.
        """
        if not any(t.kind is TrackKind.ADDITIONAL and any(c.is_image for c in t.clips) for t in self.tracks):
            return self
        nomes = [t.name for t in self.tracks if t.kind is TrackKind.VIDEO]

        def video_name() -> str:
            nome = _free_name(TrackKind.VIDEO, nomes)
            nomes.append(nome)
            return nome

        tracks: list[Track] = []
        for track in self.tracks:
            images = tuple(
                self._with_natural_image_scale(c) if legacy_scale else c
                for c in track.clips if c.is_image
            ) if track.kind is TrackKind.ADDITIONAL else ()
            if not images:
                tracks.append(track)
                continue
            others = tuple(c for c in track.clips if not c.is_image)
            if others:
                tracks.append(Track(kind=TrackKind.VIDEO, clips=images, name=video_name(),
                                    muted=track.muted, visible=track.visible))
                tracks.append(replace(track, clips=others))
            else:
                default = _default_number(TrackKind.ADDITIONAL, track.name) is not None
                tracks.append(replace(track, kind=TrackKind.VIDEO, clips=images,
                                      name=video_name() if default or not track.name else track.name))
        return replace(self, tracks=tuple(tracks))

    def _with_natural_image_scale(self, clip: Clip) -> Clip:
        media = clip.media
        new_w, new_h = image_base_size(media.width, media.height, self.width, self.height)
        old_w, old_h = natural_image_size(media.width, media.height, self.width, self.height)
        fx, fy = old_w / new_w, old_h / new_h
        if abs(fx - 1) < 1e-9 and abs(fy - 1) < 1e-9:
            return clip

        def exact(value: float) -> float:
            # O compositor escreve a escala com seis casas e trunca o tamanho
            # nas animações; 400/1440 viraria 399,999 px e perderia dois pixels.
            # Arredondar para cima nas mesmas seis casas nunca fica abaixo do
            # tamanho antigo, e o excesso é menor que um milésimo de pixel.
            return math.ceil(round(value * 1e6, 3)) / 1e6

        sx, sy = exact(clip.scale_x * fx), exact(clip.scale_y * fy)
        return replace(
            clip, scale_x=sx, scale_y=sy, scale=(sx + sy) / 2,
            keyframes=tuple(replace(k, scale_x=exact(k.scale_x * fx), scale_y=exact(k.scale_y * fy))
                            for k in clip.keyframes),
        )


def accepts(kind: TrackKind, clip: Clip) -> bool:
    """Se um bloco pode viver numa trilha desta espécie.

    Textos e filtros vivem exclusivamente em trilhas de adicionais. Imagem é
    parte da trilha de vídeo, como nos editores de referência, e pode formar
    corte e transição com um vídeo vizinho. Áudio não sobe para trilha de vídeo
    (não há o que mostrar) e imagem ou vídeo não descem para trilha de áudio (o
    som deles, quando existe, é separado por "separar áudio").

    Quem decide é o **bloco**, não a mídia dele: o bloco criado por "separar
    áudio" vem de um arquivo com imagem e mesmo assim é áudio. Enquanto isso
    saía da mídia, esse bloco não podia ser arrastado nem dentro da própria
    trilha, e colar mandava o som para a trilha de vídeo.
    """
    if clip.is_transition:
        return kind is TrackKind.VIDEO
    if kind is TrackKind.ADDITIONAL:
        return clip.is_overlay
    if clip.is_overlay:
        return False
    if kind is TrackKind.VIDEO:
        return clip.has_image
    return clip.media.kind is MediaKind.AUDIO or clip.audio_only


_KIND_KEYS = {
    TrackKind.VIDEO: "TRACK_VIDEO",
    TrackKind.AUDIO: "TRACK_AUDIO",
    TrackKind.ADDITIONAL: "TRACK_ADDITIONAL",
}


def _default_number(kind: TrackKind, name: str | None) -> int | None:
    """O N de um nome no padrão "Espécie N", escrito em qualquer idioma."""
    for label in variants(_KIND_KEYS[kind]):
        match = re.fullmatch(rf"{re.escape(label)} (\d+)", (name or "").strip())
        if match:
            return int(match.group(1))
    return None


def _free_name(kind: TrackKind, names: Iterable[str]) -> str:
    """Nome da trilha nova: o primeiro número livre da espécie, no idioma da tela.

    Contar quantas trilhas existem repetia nome depois de apagar uma do meio:
    com "Vídeo 1" e "Vídeo 3" na tela, a conta dava 3 e a nova nascia "Vídeo 3"
    também. Nomes escolhidos pelo usuário não entram na conta — só os do
    padrão "Espécie N", nos dois idiomas: a trilha criada depois da troca não
    pode repetir o número de uma "Vídeo 1" criada antes dela.
    """
    used = {number for number in (_default_number(kind, name) for name in names) if number is not None}
    number = 1
    while number in used:
        number += 1
    return f"{t(_KIND_KEYS[kind])} {number}"


def _default_name(project: Project, kind: TrackKind) -> str:
    return _free_name(kind, [track.name for track in project.tracks if track.kind is kind])


def new_project(media: MediaRef | None = None) -> Project:
    """Projeto inicial: uma trilha de vídeo e uma de áudio.

    Duas trilhas desde o começo, mesmo vazias, porque é o que dá lugar para
    soltar o primeiro arquivo — e porque separar o áudio de um vídeo precisa de
    um destino que já exista.
    """
    project = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, name=_free_name(TrackKind.VIDEO, ())),
            Track(kind=TrackKind.AUDIO, name=_free_name(TrackKind.AUDIO, ())),
        )
    )
    if media is None:
        return project

    clip = Clip(media=media, start=0.0, duration=media.natural_duration)
    # Imagem entra na trilha de vídeo, como um vídeo.
    index = 0 if media.has_video else 1
    # A tela sai da mesma regra que vale do segundo arquivo em diante, e não de
    # uma conta própria do começo: duas contas para a mesma decisão acabam
    # discordando, e nenhum leitor saberia qual delas manda.
    return auto_canvas(project.with_clip(index, clip))


def _even(value: int) -> int:
    """Codificadores trabalham em blocos de dois pixels e recusam ímpar."""
    return max(2, value - value % 2)


def auto_canvas(project: Project) -> Project:
    """Ajusta a tela ao material, escolhendo o que não rebaixa nenhum bloco.

    A **maior** imagem e a **maior** taxa entre os blocos: assim nenhum deles é
    reduzido nem tem quadro descartado, e o que perde é só o material menor, que
    é ampliado. Decidir pelo primeiro bloco — como era — fazia a ordem de
    importação decidir a qualidade do resultado inteiro: entrar com um clipe
    480p rebaixava para 480p todo o material 4K que viesse depois, sem aviso e
    sem volta a não ser esvaziando a linha do tempo.

    **Foto não define a tela quando há vídeo.** Uma imagem de 6000 px levaria a
    edição inteira para um tamanho que ninguém pediu, e ampliar uma foto custa
    muito menos que ampliar um vídeo.

    Sem imagem nenhuma, volta ao padrão: é o que faz a próxima importação
    definir a tela de novo, em vez de herdar a de um material que já saiu.
    """
    # Só vídeo decide a tela. Fotos agora vivem na trilha de vídeo, e contá-las
    # aqui levaria uma apresentação de fotos grandes a uma tela de 6000 px.
    videos = [
        clip
        for track in (*project.video_tracks, *project.additional_tracks)
        if track.visible
        for clip in track.clips
        if clip.has_image and clip.media and clip.media.kind is MediaKind.VIDEO
    ]
    sized = [c.media for c in videos if c.media.width and c.media.height]
    if not sized:
        return project.with_output_canvas(DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS)

    biggest = max(sized, key=lambda media: (media.width or 0) * (media.height or 0))
    rates = [media.fps for media in sized if media.fps]
    return project.with_output_canvas(
        width=_even(biggest.width or DEFAULT_WIDTH),
        height=_even(biggest.height or DEFAULT_HEIGHT),
        fps=min(max(rates), MAX_AUTO_FPS) if rates else DEFAULT_FPS,
    )


def slideshow_canvas(project: Project) -> tuple[int, int] | None:
    """Sugere o formato pela maior foto, somente quando não há vídeo visível."""
    clips = project.visible_video_clips
    if any(c.media and c.media.kind is MediaKind.VIDEO for c in clips):
        return None
    photos = [c.media for c in clips if c.is_image and c.media and c.media.width and c.media.height
              and c.overlay_type not in ('text', 'filter', 'transition')]
    if not photos:
        return None
    biggest = max(photos, key=lambda m: m.width * m.height)
    ratio = min(1, 1920 / max(biggest.width, biggest.height))
    return _even(round(biggest.width * ratio)), _even(round(biggest.height * ratio))
