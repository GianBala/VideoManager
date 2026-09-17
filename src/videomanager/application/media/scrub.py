"""Quadros já compostos, guardados para a agulha arrastada responder na hora.

Cada quadro é um JPEG pequeno, identificado pelo índice na taxa do cache e pela
assinatura da composição daquele instante (``domain.scrub``). Uma edição não
apaga nada: o quadro cuja assinatura deixou de valer é descartado quando é
consultado ou na conferência antes de preencher mais.

A memória tem teto. Passando dele, saem os quadros **mais distantes da agulha**,
que são os que menos provavelmente vão ser pedidos em seguida.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from videomanager.domain.scrub import Signature, signature_at


@dataclass(frozen=True)
class ScrubFrame:
    data: bytes
    signature: Signature


class ScrubFrameCache:
    def __init__(self, fps: float, size: tuple[int, int], budget_bytes: int) -> None:
        self.fps = float(fps)
        self.size = size
        self.budget_bytes = max(1, int(budget_bytes))
        self._frames: dict[int, ScrubFrame] = {}
        self._bytes = 0

    def __len__(self) -> int:
        return len(self._frames)

    @property
    def bytes_used(self) -> int:
        return self._bytes

    @property
    def average_frame_bytes(self) -> int | None:
        return self._bytes // len(self._frames) if self._frames else None

    def index_of(self, seconds: float) -> int:
        """Quadro do cache que está na tela em ``seconds``."""
        return max(0, int(math.floor(seconds * self.fps + 1e-6)))

    def seconds_of(self, index: int) -> float:
        return index / self.fps

    def get(self, index: int, signature: Signature) -> bytes | None:
        entry = self._frames.get(index)
        if entry is None:
            return None
        if entry.signature != signature:
            self._drop(index)
            return None
        return entry.data

    def put(self, index: int, signature: Signature, data: bytes, *, focus_index: int) -> None:
        self._drop(index)
        self._frames[index] = ScrubFrame(data, signature)
        self._bytes += len(data)
        if self._bytes > self.budget_bytes:
            self._evict(focus_index)

    def clear(self) -> None:
        self._frames.clear()
        self._bytes = 0

    def discard_stale(self, segments: list[tuple[float, float, Signature]]) -> int:
        """Descarta quadros cuja composição mudou. Devolve quantos saíram."""
        stale = [index for index, entry in self._frames.items()
                 if signature_at(segments, self.seconds_of(index)) != entry.signature]
        for index in stale:
            self._drop(index)
        return len(stale)

    def missing(self, segments: list[tuple[float, float, Signature]],
                start_index: int, end_index: int) -> list[tuple[int, int]]:
        """Trechos ``[a, b)`` de índices sem quadro válido."""
        result: list[tuple[int, int]] = []
        run_start: int | None = None
        for index in range(max(0, start_index), end_index):
            entry = self._frames.get(index)
            valid = entry is not None and signature_at(segments, self.seconds_of(index)) == entry.signature
            if not valid and run_start is None:
                run_start = index
            elif valid and run_start is not None:
                result.append((run_start, index))
                run_start = None
        if run_start is not None:
            result.append((run_start, end_index))
        return result

    def _drop(self, index: int) -> None:
        entry = self._frames.pop(index, None)
        if entry is not None:
            self._bytes -= len(entry.data)

    def _evict(self, focus_index: int) -> None:
        for index in sorted(self._frames, key=lambda key: abs(key - focus_index), reverse=True):
            if self._bytes <= self.budget_bytes:
                break
            self._drop(index)
