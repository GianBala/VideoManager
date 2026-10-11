"""Estimativa conservadora do custo da interpolação e da inversão implementadas pelo backend."""
import math

from videomanager.domain.project import Project
from videomanager.domain.export_policy import _interpolated_clips
from videomanager.domain.reversal import MAX_REVERSE_BYTES

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


# Piso de uma janela, em segundos. Abaixo disto o que se paga para abrir um
# processo e posicionar a leitura come o que se ganha em memória — e é o que
# sobra quando o arquivo não informa o tamanho do quadro e não há como medir.
_MIN_WINDOW = 1.0


def reverse_cuts(
    project: Project,
    start: float,
    end: float,
    *,
    media: str = "video",
    window: float | None = None,
    budget: int = MAX_REVERSE_BYTES,
    fps: float | None = None,
) -> tuple[float, ...]:
    """Instantes de ``(start, end)`` em que a leitura se divide em janelas.

    O ``reverse`` guarda os quadros do trecho inteiro (ver ``domain.reversal``) e
    não dá para limitá-lo dentro de um processo, então cada janela é lida por um
    processo, em sequência. Devolve os pontos de corte; vazio quer dizer "um
    processo só dá conta", que é o caso de tudo sem bloco invertido.

    ``media`` diz o que está sendo lido: ``"video"`` conta a memória das imagens
    invertidas, ``"audio"`` só quer janelas curtas (o som invertido pesa pouco,
    mas só começa a tocar depois de lido inteiro). ``window`` é o teto de duração
    — a prévia o pede, e a exportação, que só se limita pela memória, não.

    **Cada janela cabe no ``budget`` com todos os blocos invertidos que a
    cruzam somados**, porque os ``reverse`` de blocos simultâneos vivem juntos.
    Os cortes caem na grade de ``fps`` a partir de ``start``: uma janela que
    termina no meio de um quadro faria o trecho seguinte repetir ou perder um.

    Onde nenhum bloco invertido cruza a janela, o corte vai direto para o começo
    do próximo: cortar a cada oito segundos uma edição que só inverte algo no
    minuto dez abriria dezenas de processos para nada.
    """
    step = 1.0 / (fps or project.fps)
    # Só o que a composição de fato lê: trilha oculta não entra, e trilha muda
    # não entra no som (a mesma regra de ``composer._pieces``).
    wanted = [c for track in project.tracks if track.visible and not (media == "audio" and track.muted)
              for c in track.clips if c.reversed and c.end > start and c.start < end
              and (c.has_sound if media == "audio" else c.has_image)]
    if not wanted:
        return ()
    limit = math.inf if window is None else max(step, window)
    cuts: list[float] = []
    windowed = False
    t = start
    while t < end - step / 2:
        ahead = [c for c in wanted if c.end > t + step / 2]
        if not ahead:
            break
        if not any(c.start <= t + step / 2 for c in ahead):
            # Nada invertido ainda: pula para onde o próximo bloco começa.
            nxt = start + math.ceil((min(c.start for c in ahead) - start) / step - 1e-6) * step
            if nxt >= end - step / 2:
                break
            cuts.append(nxt)
            t = nxt
            continue
        size = _window_size(ahead, t, min(limit, end - t), budget if media == "video" else None)
        # A janela que já alcança o fim do intervalo, ou o do último bloco
        # invertido, não precisa de corte: o que sobra depois dele não pesa nada.
        # Conferido **antes** de arredondar para a grade, que só encurta.
        if t + size >= end - step / 2 or t + size >= max(c.end for c in ahead) - step / 2:
            break
        nt = t + max(1, math.floor(size / step + 1e-6)) * step
        cuts.append(nt)
        windowed = True
        t = nt
    # Os pulos só servem a quem de fato divide em janelas: se tudo o que é
    # invertido cabe numa janela, um processo só dá conta e não há corte.
    return tuple(cuts) if windowed else ()


def _window_size(clips, t: float, cap: float, budget: int | None) -> float:
    """Maior janela a partir de ``t``, de até ``cap``, cuja memória cabe em ``budget``.

    A memória de uma janela de ``w`` segundos é ``w`` vezes a soma das taxas dos
    blocos que a cruzam, e um bloco só entra quando a janela passa do começo
    dele. Percorre esses instantes de entrada em ordem: enquanto a janela cabe com
    os blocos que já entraram, segue; quando deixa de caber, ela termina no que
    couber — ou, se nem chegaria ao próximo bloco, **antes dele**, que fica para a
    janela seguinte. Sem orçamento (o som), só vale ``cap``.
    """
    if budget is None:
        return cap
    entries = sorted((max(0.0, c.start - t), c.reverse_rate) for c in clips)
    rate = 0.0
    previous = 0.0
    index = 0
    size = cap
    while True:
        # Os blocos que entram no instante ``previous`` passam a contar.
        while index < len(entries) and entries[index][0] <= previous + 1e-9:
            rate += entries[index][1]
            index += 1
        following = entries[index][0] if index < len(entries) else math.inf
        if rate > 0:
            fits = _MIN_WINDOW if math.isinf(rate) else budget / rate
            if fits < following and fits < size:
                # Não chega ao próximo bloco: termina onde couber, e nunca antes
                # de onde esta janela já começou a valer nem abaixo do piso.
                size = max(fits, min(previous, size), min(_MIN_WINDOW, size))
                break
        if following >= size:
            break
        previous = following
    return size
