"""Quanto custa inverter material de vídeo e de áudio, em memória e em espera.

O filtro ``reverse`` do ffmpeg só entrega o primeiro quadro depois de ter lido o
último: ele **guarda todos os quadros do trecho** decodificados. Medido (pico de
RSS, 1920×1080 a 30 q/s): 422 MB para 3 s, 700 MB para 6 s e 1203 MB para 12 s —
cerca de 2,9 MB por quadro, ou 87 MB por segundo. Cresce com a duração, ao
contrário do ``minterpolate``.

**Não dá para limitar isso dentro de um processo só.** Cortar o bloco em
pedaços no mesmo grafo não ajuda: o ffmpeg abre todos e cada ``reverse`` lê o
pedaço dele inteiro logo no começo (medido: cinco pedaços de 4 s gastaram 3,8 GB,
mais que um bloco de 20 s; com ``concat`` e com o filtro ``movie`` foi igual). O
que limita é **uma janela por processo, em sequência**: a exportação grava cada
janela num arquivo e os emenda; a reprodução abre a janela seguinte enquanto a
atual toca. Quem decide o tamanho das janelas é ``render_cost.reverse_cuts``;
aqui moram só os números.
"""

from __future__ import annotations

# Bytes por pixel contados por quadro. O 8 bits em 4:2:0 gasta 1,5 (medido: 1,4),
# mas o ffmpeg guarda o quadro no formato em que o decodificador o entrega, e
# 10 bits ou 4:2:2 gastam o dobro. O valor é o do pior caso: errar para cima só
# encurta a janela, errar para baixo esgota a memória da máquina — que é o que já
# aconteceu aqui com a interpolação.
REVERSE_BYTES_PER_PIXEL = 3

# Memória que **uma janela** de vídeo invertido pode pedir a um processo, pela
# conta do pior caso. Em 1080p a 30 q/s são 5,7 s. Medido numa exportação de 60 s
# em 1080p/30, pico do maior processo: 1,3 GB sem inversão nenhuma (o codificador
# e o grafo já pesam isso), 1,8 GB com janelas de orçamento de 1 GiB e 2,3 GB com
# 2 GiB. A conta é o dobro do que um vídeo de 8 bits usa de verdade (1,4 B/px, e
# não 3), então o que a janela soma ao pico é ~0,5 GB; num de 10 bits, ~1 GB.
MAX_REVERSE_BYTES = 1024 ** 3

# Duração da janela na prévia. Menor que a da memória, de propósito: a reprodução
# só começa depois que a janela inteira foi lida e virada, então janela curta é
# janela que começa a tocar logo (medido em 1080p: 0,25 s para 3 s de vídeo,
# 0,75 s para 12 s). A seguinte já está sendo preparada enquanto a atual toca.
PREVIEW_WINDOW_SECONDS = 8.0

# Maior trecho de mídia que um bloco pode inverter. O som não passa por janelas
# na exportação — sai num passe só, e o ``areverse`` guarda ~384 KB por segundo
# (estéreo, 48 kHz, ponto flutuante) —, então meia hora é o que cabe sem pesar.
MAX_REVERSE_SPAN = 1800.0

# Taxa presumida quando o arquivo não informa: a mais alta que o editor aceita
# sem cerimônia, para a conta errar para o lado seguro.
_ASSUMED_FPS = 60.0


def reverse_rate(width: int | None, height: int | None, fps: float | None, speed: float = 1.0) -> float:
    """Bytes que ``reverse`` guarda por **segundo de edição** deste bloco.

    A conta é feita sobre os quadros decodificados, e não sobre os exibidos: um
    bloco a 2× percorre dois segundos de mídia por segundo de edição e por isso
    pesa o dobro. Sem o tamanho do quadro não há como medir; devolve infinito, e
    quem planeja trata isso como "não sei" — a janela não existe e o bloco não é
    oferecido para inversão.
    """
    if not width or not height:
        return float("inf")
    return width * height * REVERSE_BYTES_PER_PIXEL * (fps or _ASSUMED_FPS) * max(0.0, speed)
