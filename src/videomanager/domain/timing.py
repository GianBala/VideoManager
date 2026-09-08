"""Tempos, segmentos e escolhas de recorte sem execução de mídia."""
from __future__ import annotations
import bisect
import re
from dataclasses import dataclass
from enum import Enum
from videomanager.domain.media import LocalMedia
from videomanager.domain.constants import IMAGE_CODECS
from videomanager.domain.constants import MIN_SEGMENT

class CutMode(Enum):
    """Como o corte trata os quadros que não são keyframe."""

    FAST = "rapido"  # -c copy: instantâneo, começa no keyframe anterior
    EXACT = "exato"  # recodifica: começa no quadro marcado


_SECONDS = re.compile(r"^\d{1,2}(?:[.,]\d{1,6})?$")


_WHOLE = re.compile(r"^\d{1,3}$")


def parse_timecode(text: str) -> float | None:
    """Converte ``h:mm:ss,mmm`` em segundos. ``None`` se não for um timecode.

    Devolver ``None`` em vez de levantar é deliberado: quem chama é um campo de
    texto sendo digitado, onde um valor incompleto é o estado normal e não um
    erro a relatar.
    """
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or not _SECONDS.match(parts[-1]):
        return None
    if any(not _WHOLE.match(part) for part in parts[:-1]):
        return None

    total = float(parts[-1].replace(",", "."))
    # Com minuto ou hora à frente, os campos seguintes são de timecode e não
    # aceitam transbordo: "1:99" tanto pode ser um erro de digitação quanto
    # 2:39, e num campo de precisão adivinhar é pior que devolver o valor
    # anterior, que continua à vista.
    if len(parts) >= 2:
        if total >= 60:
            return None
        total += int(parts[-2]) * 60
    if len(parts) == 3:
        if int(parts[-2]) >= 60:
            return None
        total += int(parts[0]) * 3600
    return total


def format_timecode(seconds: float | None, *, milliseconds: bool = True) -> str:
    """Segundos como ``h:mm:ss,mmm`` — a forma que o campo de tempo aceita de volta.

    Arredondado ao milissegundo, e não truncado: um instante marcado em 5,3 s
    chega aqui como 5,2999999 (é o que o float guarda), e truncar mostraria
    "5,299" a quem acabou de digitar "5,3". O erro do arredondamento é de meio
    milissegundo — fração de quadro em qualquer framerate — e o que o corte usa
    é o valor em segundos, não este texto.
    """
    if seconds is None or seconds < 0:
        seconds = 0.0
    total = int(seconds * 1000 + 0.5)
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    base = f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{base},{millis:03d}" if milliseconds else base


def format_span(seconds: float) -> str:
    """Duração de um trecho, para rótulos onde o timecode completo seria ruído.

    Abaixo de um minuto, segundos com duas casas ("4,25 s") — que é como se fala
    da duração de um corte. Acima, o timecode sem a hora enquanto ela for zero.
    """
    if seconds < 60:
        return f"{seconds:.2f}".replace(".", ",") + " s"
    label = format_timecode(seconds)
    return label[2:] if label.startswith("0:") else label


def frame_index(seconds: float, fps: float | None) -> int:
    """Número do quadro que está na tela no instante dado."""
    if not fps or fps <= 0:
        return 0
    # A tolerância absorve o erro do float: sem ela, um instante calculado como
    # 7,499999999 em vez de 7,5 devolve o quadro anterior.
    return max(0, int(seconds * fps + 1e-6))


def frame_time(index: int, fps: float | None) -> float:
    if not fps or fps <= 0:
        return 0.0
    return max(0, index) / fps


def frame_step(fps: float | None) -> float:
    """Duração de um quadro — o passo fino da navegação.

    Sem vídeo (um arquivo de áudio na aba de edição) não há quadro; 10 ms é um
    passo que ainda é preciso para o ouvido e não deixa a navegação travada.
    """
    return 1.0 / fps if fps and fps > 0 else 0.010


def seek_time(seconds: float, fps: float | None) -> float:
    """Instante a pedir ao ffmpeg para obter o quadro que contém ``seconds``.

    Ver a explicação no topo do módulo: o ``-ss`` entrega o primeiro quadro com
    pts ``>=`` ao pedido, então pedimos o começo do quadro recuado de um quarto
    de quadro.
    """
    if not fps or fps <= 0:
        return max(0.0, seconds)
    start = frame_time(frame_index(seconds, fps), fps)
    return max(0.0, start - 0.25 / fps)


@dataclass(frozen=True)
class Segment:
    """Um trecho do arquivo, em segundos a partir do início."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def is_usable(self) -> bool:
        return self.duration >= MIN_SEGMENT

    def contains(self, seconds: float) -> bool:
        return self.start <= seconds <= self.end

    def split_at(self, seconds: float) -> tuple[Segment, ...]:
        """Divide no instante dado. Devolve o trecho intacto se o corte não couber.

        É a operação da tesoura: dividir onde não há espaço para os dois lados
        criaria um trecho de duração zero, que o ffmpeg recusa.
        """
        if (
            seconds - self.start < MIN_SEGMENT
            or self.end - seconds < MIN_SEGMENT
        ):
            return (self,)
        return (Segment(self.start, seconds), Segment(seconds, self.end))

    @property
    def label(self) -> str:
        return (
            f"{format_timecode(self.start)} → {format_timecode(self.end)}"
            f"  ({format_span(self.duration)})"
        )


@dataclass(frozen=True)
class TrimTarget:
    """Pedido de recorte, pronto para virar argumentos do ffmpeg.

    ``anchor`` é o keyframe em que a cópia direta vai realmente começar, quando
    ele já é conhecido. Fica no pedido — e não é descoberto na hora de montar os
    argumentos — para que a tela mostre o ponto real de corte antes de
    enfileirar, com o mesmo número que o ffmpeg vai usar.
    """

    segments: tuple[Segment, ...]
    container: str = "mp4"
    mode: CutMode = CutMode.EXACT
    anchor: float | None = None
    # Preferência de codificação por placa. Fica no pedido, e não numa variável
    # global, porque é o pedido que atravessa a fila até o worker.
    hardware: str = "software"
    copy_metadata: bool = False

    @property
    def extension(self) -> str:
        return self.container

    @property
    def joins(self) -> bool:
        return len(self.segments) > 1

    @property
    def effective_segments(self) -> tuple[Segment, ...]:
        """Os trechos que a saída vai conter de fato.

        Diferem dos marcados apenas na cópia direta, onde o início escorrega
        para o keyframe anterior.
        """
        if self.mode is CutMode.FAST and self.anchor is not None and self.segments:
            first = self.segments[0]
            return (Segment(min(self.anchor, first.start), first.end),) + self.segments[1:]
        return self.segments

    @property
    def output_duration(self) -> float:
        return sum(segment.duration for segment in self.effective_segments)

    @property
    def drift(self) -> float:
        """Quanto o corte real começa antes do ponto marcado, em segundos."""
        if self.mode is not CutMode.FAST or self.anchor is None or not self.segments:
            return 0.0
        return max(0.0, self.segments[0].start - self.anchor)


def keyframe_at_or_before(times: tuple[float, ...], seconds: float) -> float | None:
    """Onde a cópia direta começaria se o corte fosse pedido em ``seconds``."""
    if not times:
        return None
    position = bisect.bisect_right(times, seconds + 1e-6)
    return times[position - 1] if position else times[0]


def keyframe_after(times: tuple[float, ...], seconds: float) -> float | None:
    """Próximo keyframe, para quem prefere mover a marca a recodificar."""
    if not times:
        return None
    position = bisect.bisect_right(times, seconds + 1e-6)
    return times[position] if position < len(times) else None


def nearest_keyframe(times: tuple[float, ...], seconds: float) -> float | None:
    before = keyframe_at_or_before(times, seconds)
    after = keyframe_after(times, seconds)
    if before is None:
        return after
    if after is None:
        return before
    return before if seconds - before <= after - seconds else after


def has_real_video(media: LocalMedia) -> bool:
    """Se há trilha de vídeo de verdade, e não a capa embutida de um áudio."""
    stream = media.video
    return stream is not None and stream.codec.lower() not in IMAGE_CODECS
