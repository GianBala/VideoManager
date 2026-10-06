"""Pedidos de prévia independentes de comandos e da representação gráfica."""
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from ...domain.project import Project
from ...domain.preview import RawFrame, preview_fps


def playback_clock() -> float:
    """Relógio da reprodução da prévia, em segundos.

    Um só para o painel e para o fluxo de quadros, que trocam instantes entre si
    (a hora marcada da volta do loop, o acerto pelo som). É ``perf_counter`` e
    não ``monotonic`` porque, no Windows até o Python 3.12, ``monotonic`` anda
    em degraus de 15,6 ms: o ritmo dos quadros medido por ele errava a espera
    de cada quadro em até um degrau, e a imagem andava aos trancos — intervalos
    de 25 a 42 ms num fluxo de 33 ms, o tempo todo.
    """
    return time.perf_counter()


class PreviewFrameInbox:
    """Uma notificação pendente e somente o quadro mais recente de reprodução.

    O produtor pode continuar enquanto a UI está ocupada sem acumular imagens
    RGB na fila de eventos. Cada consumidor retira um snapshot imutável.
    """
    def __init__(self):
        self._lock = Lock()
        self._latest: RawFrame | None = None

    def publish(self, frame: RawFrame) -> bool:
        with self._lock:
            notify = self._latest is None
            self._latest = frame
            return notify

    def take(self) -> RawFrame | None:
        with self._lock:
            frame, self._latest = self._latest, None
            return frame


@dataclass(frozen=True)
class PreviewResultKey:
    """Contexto imutável que autoriza a apresentação de um quadro."""
    token: int
    generation: int
    revision: int
    seconds: float
    size: tuple[int, int]
    fps: float


@dataclass(frozen=True)
class FrameContext:
    """O que o editor sabe no instante em que um quadro da prévia chega."""
    playing: bool
    play_token: int
    loop_token: int
    loop_video_live: bool
    playback_current: bool  # o fluxo de reprodução veio do projeto que está na tela
    frame_key: PreviewResultKey | None
    frame_token: int
    frame_revision: int
    generation: int
    preview_size: tuple[int, int]
    gesture: bool  # um gesto (arrasto, propriedade, digitação) está em curso
    interaction_visible: bool  # as camadas de interação já mostram a pose nova
    cache_shown_for: float | None  # instante do quadro guardado em tela, se houver
    wanted: float
    presented: PreviewResultKey | None


@dataclass(frozen=True)
class FrameVerdict:
    show: bool
    current: bool = False  # o quadro é o do instante e da revisão pedidos agora
    gesture: bool = False
    loop_frame: bool = False
    presented: PreviewResultKey | None = None


def accept_frame(token: int, ctx: FrameContext) -> FrameVerdict:
    """Decide se um quadro que chegou pode ir para a tela.

    É a política que impede a tela de voltar no tempo ou mostrar um projeto
    velho; morava inteira no ``EditPanel._on_frame``, onde só se testava
    abrindo o painel.
    """
    # O fluxo do começo do loop sai no instante exato do fim, e a troca de dono
    # só acontece no tique seguinte (até 40 ms depois). Os quadros dele entram
    # já, senão o primeiro do começo se perdia e o último do fim ficava parado.
    loop_frame = ctx.playing and ctx.loop_token != 0 and token == ctx.loop_token
    if (token == ctx.play_token and ctx.playing) or loop_frame:
        if not loop_frame and ctx.loop_video_live:
            return FrameVerdict(False)
        return FrameVerdict(True, current=ctx.playback_current, loop_frame=loop_frame,
                            presented=ctx.presented)
    key = ctx.frame_key
    if key is None:
        return FrameVerdict(token == ctx.frame_token, current=True, presented=ctx.presented)
    if (ctx.playing or key.token != token or key.generation != ctx.generation
            or key.size != ctx.preview_size):
        return FrameVerdict(False)
    stale = key.revision != ctx.frame_revision
    # Revisão antiga só entra durante um gesto, e não se as camadas já mostram
    # a pose nova: um quadro composto antes dela voltaria o objeto até o
    # definitivo chegar.
    if stale and (not ctx.gesture or ctx.interaction_visible):
        return FrameVerdict(False)
    if ctx.cache_shown_for is not None and key.seconds != ctx.wanted:
        # A tela já mostra o quadro guardado de um instante mais novo: o exato
        # de um ponto anterior do arrasto voltaria no tempo.
        return FrameVerdict(False)
    # Arrastar a agulha pede um quadro por evento, e o instante pedido já mudou
    # quando o anterior fica pronto. Exigir ``key.seconds == wanted`` descartava
    # **todos** esses quadros: a imagem só voltava quando a mão parava. O
    # quadro entra com o próprio instante e ``current`` continua falso.
    current = token == ctx.frame_token and not stale and key.seconds == ctx.wanted
    # Durante um gesto, apresentar snapshots completos em ordem evita esperar a
    # mão parar; a indicação de atualização só some na revisão final.
    presented = ctx.presented
    if presented is not None and presented.generation == key.generation and presented.revision > key.revision:
        return FrameVerdict(False)
    return FrameVerdict(True, current=current, gesture=ctx.gesture, presented=key)


@dataclass(frozen=True)
class PreviewRequest:
    project: Project
    seconds: float
    size: tuple[int, int]
    token: int
    fps: float
    text_assets: tuple[tuple[int, Path], ...] = ()


def prepare_preview(
    project,
    seconds,
    size,
    token,
    *,
    fps = None,
    text_assets = None,
):
    if min(size) <= 0:
        raise ValueError('A prévia precisa de dimensões positivas.')
    return PreviewRequest(project, max(0.0, seconds), size, token,
                          preview_fps(fps or project.fps), tuple((text_assets or {}).items()))
