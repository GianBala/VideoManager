"""Limites e categorias compartilhados pelas regras de mídia."""

MIN_SEGMENT = 0.05
# Abaixo de 0,2 s, uma transição a 24 fps tem menos de cinco quadros e deixa de
# comunicar movimento. A timeline e os campos de propriedades compartilham
# este limite; ele não pode ser o mínimo genérico usado por cortes comuns.
MIN_TRANSITION_DURATION = 0.2
IMAGE_CODECS = frozenset({"mjpeg", "png", "bmp", "gif", "webp"})
