"""Som da prévia da aba de edição.

**Por que o áudio vem do Qt e a imagem vem do ffmpeg.** As duas exigências são
opostas. A imagem precisa ser o **quadro exato** do corte, e um player entrega o
quadro que conseguir — daí o ffmpeg desenhar cada quadro (ver ``core/preview``).
O som precisa sair **contínuo e no ritmo certo**, alimentando a placa de áudio
sem falhas de milissegundos, que é justamente o que um ``QMediaPlayer`` faz e o
que um cano de processo externo não faz sem um mixador próprio.

Juntar os dois exige um relógio, e o relógio é o **áudio**: ouvido nota um
engasgo de 20 ms no som e não nota um quadro repetido na imagem. Então o
``position()`` deste player é a posição da reprodução, e a imagem se corrige
contra ele (ver ``EditPanel._on_audio_tick``).

**Nada aqui pode derrubar a aba.** O módulo de multimídia do Qt pode faltar no
pacote, o sistema pode não ter servidor de som, o arquivo pode não ter trilha de
áudio: em todos esses casos :attr:`available` é falso e a aba segue funcionando
com a prévia muda, que é como ela nasceu. Por isso o import fica dentro de um
``try`` e todo o resto do módulo trata a ausência como estado normal.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal

try:  # pragma: no cover - depende do que foi empacotado
    from PySide6.QtCore import QLoggingCategory
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    # O backend de multimídia do Qt despeja a estrutura do arquivo no stderr a
    # cada abertura — o mesmo ruído que o resto do aplicativo silencia (ver o
    # logger do yt-dlp em core/probe.py).
    QLoggingCategory.setFilterRules("qt.multimedia.ffmpeg*=false")
    MULTIMEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover
    QAudioOutput = QMediaPlayer = None  # type: ignore[assignment]
    MULTIMEDIA_AVAILABLE = False


class AudioPreview(QObject):
    """Trilha de áudio do arquivo em edição, com volume e posição próprios."""

    # A reprodução terminou sozinha (fim do arquivo) ou falhou.
    stopped = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = None
        self._output = None
        self._volume = 0.7
        self._muted = False
        self._failed = False

        if not MULTIMEDIA_AVAILABLE:
            return
        try:
            self._player = QMediaPlayer(self)
            self._output = QAudioOutput(self)
            self._player.setAudioOutput(self._output)
            self._player.errorOccurred.connect(self._on_error)
        except Exception:  # noqa: BLE001 - sem áudio o editor continua servindo
            self._player = self._output = None
            self._failed = True

    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Se há som para oferecer. Falso desliga o controle de volume na tela."""
        return self._player is not None and not self._failed

    def _on_error(self, *_: object) -> None:
        """Uma falha do backend desliga o som, não a aba.

        Acontece com arquivo sem trilha de áudio, codec que o backend não
        conhece e máquina sem servidor de som. Em todos, continuar mostrando os
        quadros é melhor que interromper a edição.
        """
        self._failed = True
        self.stopped.emit()

    def load(self, path: Path) -> None:
        if self._player is None:
            return
        self._failed = False
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._apply_volume()

    def play(self, seconds: float) -> None:
        if not self.available:
            return
        # A posição é definida antes de tocar: começar do zero e corrigir depois
        # deixaria escapar um estalo do início do arquivo.
        self._player.setPosition(max(0, int(seconds * 1000)))
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def seek(self, seconds: float) -> None:
        if self._player is not None:
            self._player.setPosition(max(0, int(seconds * 1000)))

    @property
    def position(self) -> float:
        """Posição em segundos — o relógio da reprodução."""
        return self._player.position() / 1000 if self._player is not None else 0.0

    @property
    def playing(self) -> bool:
        if self._player is None:
            return False
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ------------------------------------------------------------------

    def set_volume(self, percent: int) -> None:
        self._volume = min(max(0, percent), 100) / 100
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self._output is None:
            return
        # Silenciar por volume zero, e não por ``setMuted``: o Qt lembra do mudo
        # entre trocas de arquivo de formas diferentes conforme o backend, e um
        # editor que abre mudo sem dizer por quê parece quebrado.
        self._output.setVolume(0.0 if self._muted else self._volume)
