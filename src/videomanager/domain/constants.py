"""Limites e categorias compartilhados pelas regras de mídia."""
import re

MIN_SEGMENT = 0.05
# Abaixo de 0,2 s, uma transição a 24 fps tem menos de cinco quadros e deixa de
# comunicar movimento. A timeline e os campos de propriedades compartilham
# este limite; ele não pode ser o mínimo genérico usado por cortes comuns.
MIN_TRANSITION_DURATION = 0.2
# Capa de MP3 e miniatura embutida aparecem como trilha de vídeo. Recodificá-las
# como vídeo produz um arquivo de uma imagem só, com horas de duração.
IMAGE_CODECS = frozenset({"mjpeg", "png", "bmp", "gif", "webp"})
# Cor do chroma key: só hexadecimal. Ela é o único texto livre do projeto que
# chega ao grafo do ffmpeg, e um .vmp com ':' ou ',' nela encadeava filtros
# arbitrários — escrita de arquivo inclusive — só de abrir a edição.
CHROMA_COLOR = re.compile(r"(#|0x)?[0-9A-Fa-f]{6}")
# Ganho abaixo disto é zero: o controle anda de 0,1 dB, e um resto de float
# não pode virar um filtro "volume" no grafo nem tirar a edição do corte rápido.
GAIN_EPSILON = 0.05
