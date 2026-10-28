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
# Desfoque de região (um filtro da aba Filtros que age só num retângulo). O nome
# é identificador gravado no .vmp: projetos salvos dependem dele.
REGION_BLUR = "desfoque"
# Tamanho com que o bloco nasce: tela cheia não diz que há um retângulo para mexer.
REGION_BLUR_DEFAULT_SCALE = 0.3
# Menor região que se aceita, em fração da tela: abaixo disso a alça some sob o cursor.
REGION_MIN_SCALE = 0.05
# A região é borrada numa tela de trabalho de lado menor fixo e só depois ampliada
# de volta, com σ proporcional a esse lado. Valores medidos (docs/plans/
# desfoque-de-regiao.md, §3.1): com σ de 0,25 do lado ou ``steps=1`` o texto de uma
# placa ainda se lê; com 0,35 e ``steps=3`` o resultado fica a SSIM ≥ 0,993 de um
# desfoque em resolução cheia, e abaixo de 16 px de lado aparecem faixas escuras
# nas bordas.
REGION_BLUR_WORK_SIDE = 16
REGION_BLUR_SIGMA_RATIO = 0.35
REGION_BLUR_STEPS = 3
# Quantos pixels a prévia do arrasto aceita passar, a cada movimento, por um filtro de cor móvel (``color_filters``, em
# Python): ~10 ms para o Sépia (o mais caro) e ~6 para o Contraste. Acima disso o retângulo de um filtro de cor móvel
# acima do que se arrasta devolve o quadro ao ffmpeg, como antes: uma interface travada é pior que uma prévia que atrasa.
# Medido: 23 ms em 640×360 e 98 ms em 1280×720 com o retângulo na tela inteira; o do filtro recém-ligado (30% de lado)
# custa 2 e 8 ms.
REGION_COLOR_STAGE_MAX_PIXELS = 100_000
# Filtros de tela inteira (ids gravados no .vmp). Os de cor agem pixel a pixel e são afins (``a·x + b``): somar um item
# translúcido e depois filtrar dá o mesmo que filtrar cada camada e somar, então a prévia do arrasto os aplica às camadas
# prontas. Os que têm termo constante (``b``) não comutam com a multiplicação da vinheta, que depende da posição na tela.
COLOR_FILTERS = ("pb", "sepia", "inverter", "contraste")
OFFSET_COLOR_FILTERS = ("inverter", "contraste")
VIGNETTE_FILTER = "vinheta"
# Ganho abaixo disto é zero: o controle anda de 0,1 dB, e um resto de float
# não pode virar um filtro "volume" no grafo nem tirar a edição do corte rápido.
GAIN_EPSILON = 0.05
