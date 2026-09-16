"""Modelos e regras de interpolação para quadros-chave (keyframes).

Permite animar propriedades de transformação (posição, escala, rotação e
opacidade) ao longo do tempo relativo de um clipe, preservando o modelo
imutável do domínio sem dependências de frameworks ou subprocessos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

SUPPORTED_EASINGS = (
    "linear",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "hold",
)


@dataclass(frozen=True)
class ClipTransform:
    """Valores de transformação de um bloco em um instante específico."""

    x: float = 0.5
    y: float = 0.5
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0


@dataclass(frozen=True)
class Keyframe:
    """Ponto da curva em segundos locais; negativos sustentam trechos recortados."""

    time_offset: float
    x: float = 0.5
    y: float = 0.5
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    easing: str = "linear"

    def __post_init__(self) -> None:
        if self.easing not in SUPPORTED_EASINGS:
            object.__setattr__(self, "easing", "linear")
        clamped_opacity = max(0.0, min(1.0, float(self.opacity)))
        object.__setattr__(self, "opacity", clamped_opacity)

    @property
    def transform(self) -> ClipTransform:
        return ClipTransform(
            x=self.x,
            y=self.y,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            rotation=self.rotation,
            opacity=self.opacity,
        )


def evaluate_easing(progress: float, easing: str) -> float:
    """Calcula o progresso interpolado [0.0, 1.0] dada uma curva de aceleração."""
    t = max(0.0, min(1.0, progress))
    if easing == "ease_in":
        return t * t
    if easing == "ease_out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if easing == "ease_in_out":
        if t < 0.5:
            return 2.0 * t * t
        return 1.0 - 2.0 * (1.0 - t) * (1.0 - t)
    if easing == "hold":
        return 0.0 if t < 1.0 else 1.0
    return t  # linear por padrão


def resolve_segment_easing(start_easing: str, end_easing: str) -> str:
    """Resolve a curva de interpolação entre dois quadros-chave consecutivos.

    Se o usuário configurou uma curva no quadro de destino (ao chegar ao ponto),
    ela prevalece sobre o padrão linear do quadro de partida. Se ambos definirem
    curvas não-lineares complementares (ease_out e ease_in), a combinação resulta
    em ease_in_out.
    """
    if start_easing == "hold" or end_easing == "hold":
        return "hold"
    if end_easing != "linear" and start_easing != "linear":
        if (start_easing == "ease_out" and end_easing == "ease_in") or "ease_in_out" in (start_easing, end_easing):
            return "ease_in_out"
        return end_easing
    if end_easing != "linear":
        return end_easing
    return start_easing


def _interpolate_scalar(
    v0: float, v1: float, factor: float, is_angle: bool = False
) -> float:
    if not is_angle or abs(v1 - v0) >= 359.9:
        return v0 + (v1 - v0) * factor
    # Menor caminho angular para interpolação de rotação (-180 a +180)
    diff = (v1 - v0) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return (v0 + diff * factor) % 360.0


def interpolate_keyframes(
    keyframes: Sequence[Keyframe],
    time_offset: float,
    fallback: ClipTransform,
) -> ClipTransform:
    """Interpola o estado das propriedades no tempo indicado dentro do bloco.

    - Se não houver keyframes, devolve o estado base `fallback`.
    - Se houver apenas um keyframe ou o tempo for anterior ao primeiro,
      devolve os valores do primeiro keyframe.
    - Se o tempo for posterior ao último keyframe, devolve os valores do último.
    - Entre dois keyframes consecutivos, calcula a interpolação com a curva
      resolvida entre os dois quadros-chave.
    """
    if not keyframes:
        return fallback

    sorted_kfs = sorted(keyframes, key=lambda k: k.time_offset)
    if time_offset <= sorted_kfs[0].time_offset:
        return sorted_kfs[0].transform
    if time_offset >= sorted_kfs[-1].time_offset:
        return sorted_kfs[-1].transform

    # Localizar os dois keyframes que delimitam o instante
    for i in range(len(sorted_kfs) - 1):
        k0 = sorted_kfs[i]
        k1 = sorted_kfs[i + 1]
        if k0.time_offset <= time_offset <= k1.time_offset:
            dt = k1.time_offset - k0.time_offset
            if dt < 1e-6:
                return k0.transform
            raw_t = (time_offset - k0.time_offset) / dt
            easing = resolve_segment_easing(k0.easing, k1.easing)
            factor = evaluate_easing(raw_t, easing)

            return ClipTransform(
                x=_interpolate_scalar(k0.x, k1.x, factor),
                y=_interpolate_scalar(k0.y, k1.y, factor),
                scale_x=_interpolate_scalar(k0.scale_x, k1.scale_x, factor),
                scale_y=_interpolate_scalar(k0.scale_y, k1.scale_y, factor),
                rotation=_interpolate_scalar(
                    k0.rotation, k1.rotation, factor, is_angle=True
                ),
                opacity=max(
                    0.0,
                    min(
                        1.0,
                        _interpolate_scalar(k0.opacity, k1.opacity, factor),
                    ),
                ),
            )

    return sorted_kfs[-1].transform


def create_preset_keyframes(
    preset_name: str,
    target: ClipTransform,
    duration: float = 0.5,
) -> tuple[Keyframe, ...]:
    """Gera keyframes predefinidos para efeitos comuns de entrada e saída.

    - slide_up: desliza da borda inferior para a posição de destino com ease_out.
    - slide_down: desliza da borda superior para a posição de destino com ease_out.
    - slide_left: desliza da borda direita para a posição de destino com ease_out.
    - slide_right: desliza da borda esquerda para a posição de destino com ease_out.
    - fade_in: surge de opacidade 0.0 para a opacidade alvo com linear.
    - zoom_in: surge com escala 0.05 e opacidade 0.0 para a escala alvo com ease_out.
    """
    if duration <= 0:
        return (Keyframe(0, x=target.x, y=target.y, scale_x=target.scale_x,
                         scale_y=target.scale_y, rotation=target.rotation, opacity=target.opacity),)
    dur = duration
    if preset_name == "slide_up":
        k0 = Keyframe(
            time_offset=0.0,
            x=target.x,
            y=1.3,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=0.0,
            easing="ease_out",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    if preset_name == "slide_down":
        k0 = Keyframe(
            time_offset=0.0,
            x=target.x,
            y=-0.3,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=0.0,
            easing="ease_out",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    if preset_name == "slide_left":
        k0 = Keyframe(
            time_offset=0.0,
            x=1.3,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=0.0,
            easing="ease_out",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    if preset_name == "slide_right":
        k0 = Keyframe(
            time_offset=0.0,
            x=-0.3,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=0.0,
            easing="ease_out",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    if preset_name == "fade_in":
        k0 = Keyframe(
            time_offset=0.0,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=0.0,
            easing="linear",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    if preset_name == "zoom_in":
        k0 = Keyframe(
            time_offset=0.0,
            x=target.x,
            y=target.y,
            scale_x=0.05,
            scale_y=0.05,
            rotation=target.rotation,
            opacity=0.0,
            easing="ease_out",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    if preset_name == "spin_in":
        k0 = Keyframe(
            time_offset=0.0,
            x=target.x,
            y=target.y,
            scale_x=0.05,
            scale_y=0.05,
            rotation=target.rotation - 360.0,
            opacity=0.0,
            easing="ease_out",
        )
        k1 = Keyframe(
            time_offset=dur,
            x=target.x,
            y=target.y,
            scale_x=target.scale_x,
            scale_y=target.scale_y,
            rotation=target.rotation,
            opacity=target.opacity,
            easing="linear",
        )
        return (k0, k1)

    return ()
