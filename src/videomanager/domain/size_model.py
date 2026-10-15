"""Do que foi medido em trechos ao tamanho do arquivo inteiro.

Codificar o arquivo todo para saber o tamanho é fazer a conversão; codificar alguns trechos e extrapolar é o que o
aplicativo faz, e o que decide a precisão é **onde** os trechos ficam e **como** a conta passa do trecho ao todo.

- **Estratos.** O arquivo é dividido em partes iguais, com um trecho em cada. Trechos em frações fixas (25%, 50%, 75%)
  caem, por azar, só nas cenas leves ou só nas pesadas; uma parte de cada região do arquivo não deixa nenhuma de fora.
- **Janela representativa.** Dentro de cada estrato, o trecho medido é o que a **fonte** gasta, por segundo, mais perto do
  que ela gasta no estrato inteiro. A fonte diz onde o arquivo é pesado e onde é leve (o tamanho de cada pacote custa só
  um ``ffprobe`` sem decodificar), e medir o trecho típico, e não o primeiro, tira o viés de ter caído numa cena
  fora do comum.
- **Quanto medir depende de quanto custa.** Um piloto de poucos segundos mede a velocidade do encoder neste conteúdo.
  Se o arquivo inteiro cabe no orçamento de tempo (gravação de tela, que codifica a 15–30× o tempo real), ele é
  codificado inteiro e o tamanho sai exato; senão a cobertura cresce com a velocidade. Foi o que faltava: numa gravação
  de tela de 218 s, quase parada e com rajadas de movimento, os 24 s de amostra erravam de −33% a +50% conforme caíssem
  ou não numa rajada.
- **Razão pela fonte.** O que sai de cada trecho é multiplicado pelo quanto a fonte pesa no estrato inteiro em relação ao
  que pesa no trecho (estimador de razão, o mesmo das pesquisas por amostragem): o que a amostra erra de representativa,
  a curva da fonte corrige.

Medido contra a codificação inteira de vídeos reais (ver ``docs/estimativas-de-tamanho.md``), isso reduz o erro mediano
da amostra de 3 trechos de 8 s a frações dele. Este módulo é só conta: quem codifica os trechos é
``infrastructure/ffmpeg/sample.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from videomanager.domain.media import AudioTarget
    from videomanager.domain.media import LocalMedia
    from videomanager.domain.media import VideoTarget

# O desenho mínimo (conteúdo caro de codificar): 6 partes iguais, um trecho de 4 s em cada, 24 s ao todo. Medido em 9
# vídeos reais, a razão pela fonte o deixa em 1–4% de erro no conteúdo contínuo.
STRATA = 6
MIN_LENGTH = 4.0
MAX_LENGTH = 8.0
MAX_STRATA = 24
MIN_CONTENT = STRATA * MIN_LENGTH
# Quanto tempo de relógio a medida pode gastar, e quanto do arquivo ela cobre se o resto não couber: a conta é a
# velocidade do piloto vezes o orçamento. O piloto soma a partida do processo à codificação e por isso subestima a
# velocidade (medido: entre 0,4× e 1× a real), o que erra para o lado de medir menos, nunca de gastar mais.
TIME_BUDGET = 20.0
PILOT_SECONDS = 4.0
# Cabendo 90% do arquivo no orçamento, mede-se o arquivo todo: os 10% restantes não valem uma extrapolação.
_WHOLE_FILE_SHARE = 0.9
# Um trecho com menos que esta fração do que a fonte pesa, em média, por trecho não serve de razão (cena quase parada,
# tela preta): a divisão amplificaria o ruído, e a conta daquele estrato volta à extrapolação direta.
_MIN_SOURCE_SHARE = 0.05


@dataclass(frozen=True)
class SourceCurve:
    """Bytes do vídeo da fonte ao longo do tempo, em baldes de ``step`` segundos."""

    cumulative: tuple[float, ...]
    step: float = 1.0

    @classmethod
    def from_packets(cls, packets: Iterable[tuple[float, int]], duration: float, step: float = 1.0) -> SourceCurve:
        """``packets``: pares ``(instante, bytes)``, na ordem em que o ffprobe os lista."""
        buckets = [0.0] * max(1, int(duration / step) + 1)
        for instant, size in packets:
            index = min(len(buckets) - 1, max(0, int(instant / step)))
            buckets[index] += size
        cumulative = [0.0]
        for value in buckets:
            cumulative.append(cumulative[-1] + value)
        return cls(tuple(cumulative), step)

    @property
    def total(self) -> float:
        return self.cumulative[-1]

    def _at(self, instant: float) -> float:
        # Interpolação linear dentro do balde: as pontas de um trecho raramente caem em segundos inteiros.
        position = max(0.0, instant / self.step)
        index = min(int(position), len(self.cumulative) - 2)
        fraction = min(1.0, position - index)
        return self.cumulative[index] + (self.cumulative[index + 1] - self.cumulative[index]) * fraction

    def between(self, start: float, end: float) -> float:
        return max(0.0, self._at(end) - self._at(start))


@dataclass(frozen=True)
class Window:
    """Um trecho medido: onde começa, quanto dura e quantos bytes de vídeo a codificação dele gravou."""

    start: float
    length: float
    size: float


def plan_design(duration: float, speed: float) -> tuple[int, float]:
    """``(estratos, duração do trecho)`` para um arquivo de ``duration`` s que o encoder processa a ``speed``× o tempo real.

    Um estrato do tamanho do arquivo todo (``1, duration``) é medir o arquivo inteiro.
    """
    affordable = TIME_BUDGET * speed
    if duration <= MIN_CONTENT or affordable >= duration * _WHOLE_FILE_SHARE:
        return 1, duration
    content = max(MIN_CONTENT, affordable)
    length = min(MAX_LENGTH, max(MIN_LENGTH, content / STRATA))
    return max(STRATA, min(MAX_STRATA, round(content / length))), length


def plan_windows(duration: float, curve: SourceCurve | None, strata: int = STRATA,
                 length: float = MIN_LENGTH) -> list[tuple[float, float]]:
    """Os trechos a medir: ``(início, duração)``. Um arquivo curto demais para os estratos é medido inteiro."""
    if duration <= 0:
        return []
    if duration <= strata * length:
        return [(0.0, duration)]
    span = duration / strata
    windows = []
    for index in range(strata):
        low, high = span * index, span * (index + 1)
        centered = (low + high) / 2 - length / 2
        windows.append((_representative(curve, low, high, length, centered), length))
    return windows


def _representative(curve: SourceCurve | None, low: float, high: float, length: float, centered: float) -> float:
    """O início do trecho, dentro do estrato, que pesa na fonte o mais perto da média do estrato."""
    if curve is None or curve.total <= 0:
        return centered
    mean_rate = curve.between(low, high) / (high - low)
    if mean_rate <= 0:
        return centered
    best = (float("inf"), float("inf"), centered)
    start = low
    while start + length <= high + 1e-9:
        deviation = abs(curve.between(start, start + length) / length - mean_rate) / mean_rate
        # Faixas de 2%: numa fonte de taxa constante todos os trechos empatam, e o desempate é o mais perto do centro,
        # e não o primeiro (que escolheria sempre a borda do estrato).
        best = min(best, (round(deviation / 0.02), abs(start - centered), start))
        start += curve.step
    return best[2]


def project_bytes(duration: float, windows: list[Window], curve: SourceCurve | None) -> float | None:
    """Os bytes de vídeo do arquivo inteiro, a partir dos trechos medidos; ``None`` se nada foi medido."""
    measured = sum(window.length for window in windows)
    if duration <= 0 or measured <= 0:
        return None
    if len(windows) == 1 and windows[0].length >= duration - 1e-6:
        return windows[0].size  # o arquivo inteiro foi medido: não há o que extrapolar
    span = duration / len(windows)
    total = 0.0
    for index, window in enumerate(windows):
        direct = window.size / window.length * span
        if curve is None:
            total += direct
            continue
        in_window = curve.between(window.start, window.start + window.length)
        in_stratum = curve.between(span * index, span * (index + 1))
        typical = curve.total / duration * window.length  # o que um trecho deste tamanho pesa, em média
        if in_window <= 0 or in_window < typical * _MIN_SOURCE_SHARE:
            total += direct
        else:
            total += window.size * in_stratum / in_window
    return total


def container_overhead_bytes(container: str, samples: int) -> int:
    """O que o container grava além dos pacotes: tabelas de amostras, índices, cabeçalhos.

    Medido remultiplexando vídeos reais (mp4: 0,17–0,25% em 1080p, 2,6% num arquivo de 0,75 Mbps; mkv: 0,05–0,65%; webm:
    0,25–0,4%): cresce com o número de amostras (quadros de vídeo e de áudio), não com o tamanho.
    """
    per_sample = 20 if container in ("mp4", "mov", "m4a") else 8
    return 4096 + samples * per_sample


# O que o container de áudio grava além dos pacotes, medido em 2 minutos de áudio de vídeos reais: o M4A paga ~4 bytes
# por quadro (1,2%), o Ogg paga o cabeçalho de cada página (Opus 0,8%, Vorbis 1,3%), o MP3, o FLAC, o ALAC e o WAV quase
# nada (menos de 0,1%). Mais um bloco fixo de cabeçalho, etiquetas e tabela de busca.
_AUDIO_OVERHEAD = {"m4a": 0.012, "aac": 0.012, "opus": 0.008, "vorbis": 0.013, "ogg": 0.013}
AUDIO_FILE_OVERHEAD = 8192


def audio_overhead(codec: str) -> float:
    return _AUDIO_OVERHEAD.get(codec, 0.0)


# Os codecs de áudio cujo tamanho a conta já acerta: o MP3 é de taxa constante e o WAV é PCM. Os demais variam com o
# conteúdo (medido: o AAC de 128 kbps saiu entre 0,78× e 1,12× do pedido; o Opus, entre 0,76× e 1,27×).
AUDIO_EXACT = frozenset({"mp3", "wav"})


def needs_sample(media: LocalMedia, target: VideoTarget | AudioTarget) -> bool:
    """Se o tamanho do que ``target`` grava só se conhece medindo, e não por conta.

    Copiar não precisa: sai o que já está lá. Recodificar o vídeo precisa sempre, porque o conteúdo decide o quanto o
    encoder gasta (medido: de 0,03× a 2,5× o bitrate da fonte no mesmo H.264). Recodificar áudio, só nos codecs de taxa
    variável.
    """
    from videomanager.domain.compatibility import copies_audio
    from videomanager.domain.media import AudioTarget

    if not media.duration or media.duration <= 0:
        return False
    if isinstance(target, AudioTarget):
        return media.has_audio and not copies_audio(media, target) and target.codec not in AUDIO_EXACT
    return target.video_codec != "copy" and media.video is not None and not media.is_image and not media.video_is_cover


# O PCM que o compositor entrega ao encoder de áudio da exportação: 48 kHz, estéreo, 16 bits.
COMPOSER_PCM_KBPS = 48_000 * 2 * 16 / 1000
