"""Quanto custa inverter um trecho de vídeo, em memória.

O filtro ``reverse`` do ffmpeg só entrega o primeiro quadro depois de ter lido o
último: ele **guarda todos os quadros do trecho** decodificados. Medido (pico de
RSS, 1920×1080 a 30 q/s): 422 MB para 3 s, 700 MB para 6 s e 1203 MB para 12 s —
cerca de 2,9 MB por quadro, ou 87 MB por segundo. Cresce com a duração, ao
contrário do ``minterpolate``, e por isso o bloco invertido tem um teto: quem
passa dele não é invertido, e não fica pesado em silêncio.

Moram aqui, e não em ``render_cost``, porque o bloco precisa responder se pode
ser invertido (``Clip.can_reverse``) e ``render_cost`` importa o projeto.
"""

from __future__ import annotations

# Bytes por pixel contados por quadro. O 8 bits em 4:2:0 gasta 1,5 (medido: 1,4),
# mas o ffmpeg guarda o quadro no formato em que o decodificador o entrega, e
# 10 bits ou 4:2:2 gastam o dobro. O valor é o do pior caso: errar para cima só
# recusa um bloco antes, errar para baixo esgota a memória da máquina — que é o
# que já aconteceu aqui com a interpolação.
REVERSE_BYTES_PER_PIXEL = 3

# Teto de memória do trecho invertido por bloco. Pela conta do pior caso, em
# 1080p a 30 q/s são 11,5 s; num vídeo de 8 bits a memória real desse trecho é
# metade do teto (~1 GB), e num de 10 bits chega a ele.
MAX_REVERSE_BYTES = 2 * 1024 ** 3

# Taxa presumida quando o arquivo não informa: a mais alta que o editor aceita
# sem cerimônia, para a conta errar para o lado seguro.
_ASSUMED_FPS = 60.0


def reverse_bytes(width: int | None, height: int | None, fps: float | None, seconds: float) -> int:
    """Memória que ``reverse`` pede para ``seconds`` de material de origem.

    ``seconds`` é o trecho **da mídia** (``duração × velocidade`` do bloco), e
    não o da edição: é a quantidade de quadros decodificados que decide, não a
    de quadros exibidos. Sem o tamanho do quadro não há como medir, e nesse
    caso a conta devolve o teto — recusar é o lado seguro de "não sei".
    """
    if not width or not height:
        return MAX_REVERSE_BYTES + 1
    frames = max(0.0, seconds) * (fps or _ASSUMED_FPS)
    return int(frames * width * height * REVERSE_BYTES_PER_PIXEL)


def reverse_seconds_limit(width: int | None, height: int | None, fps: float | None) -> float:
    """Quantos segundos de material cabem no teto para um quadro deste tamanho.

    É a mesma conta de :func:`reverse_bytes` lida ao contrário, para quem
    precisa de um limite a respeitar (a alça que estica um bloco já invertido) e
    não só de um número a comparar.
    """
    if not width or not height:
        return 0.0
    return MAX_REVERSE_BYTES / (width * height * REVERSE_BYTES_PER_PIXEL * (fps or _ASSUMED_FPS))
