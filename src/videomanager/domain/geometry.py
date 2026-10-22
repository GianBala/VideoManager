"""Dimensões de imagens e regiões na composição."""

import math


def _image_size(media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int,
                *, enlarge: bool) -> tuple[int, int]:
    w = media_w or 400
    h = media_h or 300
    fit_ratio = min(canvas_w / max(1, w), canvas_h / max(1, h))
    if not enlarge:
        fit_ratio = min(1.0, fit_ratio)
    base_w = max(2, int(round(w * fit_ratio / 2.0) * 2))
    base_h = max(2, int(round(h * fit_ratio / 2.0) * 2))
    return base_w, base_h


def image_base_size(
    media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    """Tamanho base de uma imagem: ajustada à tela, como um vídeo.

    Imagem é parte da trilha de vídeo, e como nos editores de referência ela
    ocupa a tela — ampliada ou reduzida, sem deformar. Escala, posição e
    animação partem deste tamanho. Compositor, prévia e propriedades usam esta
    mesma função, e é isso que mantém os três de acordo.
    """
    return _image_size(media_w, media_h, canvas_w, canvas_h, enlarge=True)


def natural_image_size(
    media_w: int | None, media_h: int | None, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    """Regra anterior ao formato 3: tamanho natural, reduzida só se não coubesse.

    Existe apenas para migrar projetos antigos sem mudar a aparência deles.
    """
    return _image_size(media_w, media_h, canvas_w, canvas_h, enlarge=False)


# -- região de um filtro (desfoque de região) ---------------------------------
#
# A região é o retângulo que o bloco ocupa na tela: centro em fração da tela e
# tamanho em fração dela. Compositor e prévia chamam estas mesmas funções, e é isso
# que mantém o que se vê na prévia igual ao que sai na exportação — duas contas
# para a mesma decisão acabam discordando.

def _half_away(value: float) -> int:
    """Arredonda a metade para longe do zero, como o ``round`` do ffmpeg.

    O ``round`` do Python arredonda para o par (2,5 vira 2), e a posição calculada
    aqui precisa cair no mesmo pixel que a expressão do ``overlay``.
    """
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def region_size(scale_x: float, scale_y: float, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    """Largura e altura da região, em pixels pares, entre 2 e a tela.

    Par porque o ``yuv420p`` guarda a cor a cada dois pixels: uma região de largura
    ímpar deixa o croma desalinhado.
    """
    def side(scale: float, canvas: int) -> int:
        # Limitada a 1 antes de multiplicar: o arquivo aceita qualquer escala finita, e ``escala * tela`` estoura para
        # o infinito, que ``_half_away`` não converte em inteiro.
        return max(2, min(canvas // 2 * 2, 2 * _half_away(min(1.0, scale) * canvas / 2)))
    return side(scale_x, canvas_w), side(scale_y, canvas_h)


def _region_limit(total: int, size: int) -> int:
    # Par também, senão o arredondamento do canto poderia passar do limite.
    return max(0, (total - size) // 2 * 2)


def region_origin(cx: float, cy: float, w: int, h: int, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    """Canto superior esquerdo da região: par e preso por dentro da tela.

    Preso por dentro porque o ``crop`` do ffmpeg já desloca a janela para dentro
    quando ela passa da borda, e o ``overlay`` não: sem prender aqui, o recorte e a
    colagem caíam em lugares diferentes. E par porque, com ``x`` ou ``y`` ímpar, o
    croma do ``yuv420p`` diverge uma coluna fora do retângulo (medido: 120 px).
    """
    def corner(center: float, total: int, size: int) -> int:
        limit = _region_limit(total, size)
        return 2 * _half_away(max(0.0, min(float(limit), center * total - size / 2)) / 2)
    return corner(cx, canvas_w, w), corner(cy, canvas_h, h)


def region_origin_expr(center_expr: str, total: int, size: int) -> str:
    """A mesma conta de :func:`region_origin`, como expressão do ffmpeg.

    ``center_expr`` pode depender de ``t`` (quadros-chave de posição). O ``crop`` e
    o ``overlay`` recebem **este mesmo texto**.
    """
    limit = _region_limit(total, size)
    return f"2*round(max(0,min({limit},({center_expr})*{total}-{size}/2))/2)"
