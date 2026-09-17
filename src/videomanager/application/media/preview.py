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
