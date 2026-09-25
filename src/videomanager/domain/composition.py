"""Pedido semântico de exportação de uma montagem."""
from dataclasses import dataclass
from videomanager.domain.project import Project

@dataclass(frozen=True)
class Composition:
    """Pedido de exportação de um projeto — um alvo de conversão como os outros.

    Quem executa é o :class:`~videomanager.infrastructure.ffmpeg.converter.Converter`, com o mesmo
    progresso, cancelamento e limpeza de saída parcial das outras abas.
    """

    project: Project
    container: str = "mp4"
    family: str | None = None
    # Preferência de codificação por placa, resolvida na hora de gravar (com
    # queda para software quando ela não abrir). Ver ``infrastructure/ffmpeg/hardware.py``.
    hardware: str = "software"
    # Inventar os quadros que faltam ao subir a taxa, em vez de repetir os que
    # existem. Só na exportação: ver :func:`_rate_chain`.
    interpolate: bool = False
    audio_only: bool = False
    audio_codec: str | None = None
    quality: str = "balanced"

    @property
    def extension(self) -> str:
        return self.container

    @property
    def output_duration(self) -> float:
        if self.audio_only:
            return self.project.audible_duration
        if self.container == "gif":
            return self.project.video_duration
        return self.project.export_duration
