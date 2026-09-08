"""Sondagem dos encoders de placa fora da thread da interface.

A sondagem manda o ffmpeg **codificar um quadro de verdade** — é o que separa
"o ffmpeg lista o encoder" de "o encoder abre nesta máquina" (ver
``infrastructure/ffmpeg/hardware.py``). Isso custa um processo por candidato, e nesta máquina
custa 0,51 s para a primeira placa que responde e 3,41 s para varrer a família
inteira: o VAAPI daqui **aborta** o processo, e um aborto demora mais que uma
recusa.

Feita onde estava, esse tempo caía nos dois piores lugares possíveis: na thread
da interface ao abrir as configurações, congelando o diálogo, e no começo da
primeira exportação, que é justamente quando o usuário está esperando o
resultado. O trabalho é o mesmo; o que muda é quem espera.

O worker não devolve nada: ele existe para **aquecer o cache** de
``hwaccel.probe``, que é por execução. Quem precisa da resposta continua
chamando ``hwaccel.describe`` ou ``hwaccel.resolve`` normalmente — só que agora
elas respondem na hora.
"""

from __future__ import annotations

from PySide6.QtCore import QRunnable, Slot

from videomanager.infrastructure.ffmpeg import hardware as hwaccel
from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.qt.workers.signals import PreviewSignals
from videomanager.infrastructure.qt.workers.signals import emit_safely


class HardwareProbeWorker(QRunnable):
    """Sonda os encoders de placa e emite ``done`` ao terminar."""

    def __init__(self, tools: FFmpegTools, families: tuple[str, ...] = ("h264",)) -> None:
        super().__init__()
        self._tools = tools
        self._families = families
        self.signals = PreviewSignals()

    @Slot()
    def run(self) -> None:
        try:
            for family in self._families:
                # ``available`` sonda todos os candidatos da família, e é isso
                # que se quer: aquecer só o preferido deixaria a varredura do
                # modo automático para a hora da exportação.
                hwaccel.available(self._tools, family)
        finally:
            # Sempre, inclusive se um candidato derrubar o processo: quem espera
            # a resposta não pode ficar esperando para sempre.
            emit_safely(self.signals.done)

__all__ = [
    'FFmpegTools',
]
