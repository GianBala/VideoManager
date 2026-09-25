"""Estimativa conservadora do custo da interpolação implementada pelo backend."""
from videomanager.domain.project import Project
from videomanager.domain.export_policy import _interpolated_clips

# Memória do ``minterpolate``, por pixel do quadro que ele **recebe**. Medido
# nesta máquina, pico de RSS de uma exportação: 1589 MB a 1920×1080 (803 B/px) e
# 5655 MB a 3840×2160 (715 B/px). Não cresce com a duração — 20 s a 1080p pediu
# os mesmos 1,6 GB que 5 s —, e é por isso que o custo pode ser anunciado antes
# de a exportação começar (ver :func:`interpolation_bytes`). O valor é o maior
# dos dois: errar para cima só antecipa um aviso, errar para baixo derruba a
# máquina.
_INTERPOLATE_BYTES_PER_PIXEL = 803


def interpolation_bytes(project: Project) -> int:
    """Memória que uma exportação interpolada deste projeto vai pedir.

    Existe para a aba **dizer o número antes de enfileirar**, como já diz o ponto
    real do corte rápido. O ``minterpolate`` não tem controle de memória — nem
    ``mb_size``, nem desligar o ``vsbmc`` mudam o pico (medido: 1573 contra 1589
    MB) —, então o que resta é escolher uma tela que caiba e saber disso antes.

    O total soma os blocos porque o grafo instancia **um filtro por bloco**, e
    todos vivem enquanto a exportação existe. Cada um conta pelo quadro que
    recebe, que é o menor entre material e tela — a mesma regra de
    :func:`_rate_first` —, com a tela ampliada pela maior escala do bloco quando
    ele cresce: um bloco ampliado é interpolado no tamanho em que aparece, para
    não perder o detalhe.
    """
    total = 0
    for clip in _interpolated_clips(project):
        peak_x, peak_y = clip.peak_scale
        pixels = int(project.width * project.height * max(1.0, peak_x) * max(1.0, peak_y))
        if clip.media.width and clip.media.height:
            pixels = min(pixels, clip.media.width * clip.media.height)
        total += pixels * _INTERPOLATE_BYTES_PER_PIXEL
    return total
