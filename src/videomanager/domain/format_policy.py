"""Políticas de escolha sobre formatos já normalizados."""
from videomanager.domain.formats import FormatMatrix
from videomanager.domain.formats import VideoChoice
from videomanager.domain.formats import AudioChoice

def pick_video(
    matrix: FormatMatrix,
    *,
    max_height: int | None = None,
    max_fps: int | None = None,
    family: str | None = None,
) -> VideoChoice | None:
    """Melhor opção de vídeo que respeita os limites pedidos.

    Opções sem altura conhecida não são eliminadas por ``max_height``: não se
    pode afirmar que violam o limite, e descartá-las deixaria sem nenhuma opção
    justamente os sites que não informam resolução.
    """
    for choice in matrix.video:
        if max_height and choice.height and choice.height > max_height:
            continue
        if max_fps and choice.fps and choice.fps > max_fps:
            continue
        if family and choice.family != family:
            continue
        return choice

    # Nada respeitou os limites: devolve a melhor disponível em vez de nada, pois
    # um vídeo só em 4K é melhor que um erro de "resolução indisponível".
    return matrix.video[0] if matrix.video else None


def find_video(
    matrix: FormatMatrix,
    *,
    height: int | None,
    fps: int | None = None,
    family: str | None = None,
) -> VideoChoice | None:
    """Localiza a opção que casa **exatamente** com o que foi escolhido.

    Diferente de :func:`pick_video`, que trata os valores como limites máximos.
    Esta é a busca usada quando o usuário selecionou valores nos combos: pedir
    "1080p, 60fps, H.264" deve devolver aquela linha, não a melhor abaixo dela.

    Restrições em ``None`` são ignoradas, e há um afrouxamento progressivo: se a
    combinação exata não existir (o usuário trocou a resolução e o framecodec
    antigo não existe na nova), cai para o melhor da resolução escolhida em vez
    de devolver nada.
    """
    candidates = [c for c in matrix.video if height is None or c.height == height]
    if not candidates:
        return None

    exact = [
        c
        for c in candidates
        if (fps is None or c.fps == fps) and (family is None or c.family == family)
    ]
    if exact:
        return exact[0]

    # Afrouxa uma restrição por vez, na ordem em que menos importa ao usuário.
    by_family = [c for c in candidates if family is None or c.family == family]
    if by_family:
        return by_family[0]
    by_fps = [c for c in candidates if fps is None or c.fps == fps]
    if by_fps:
        return by_fps[0]
    return candidates[0]


def pick_audio(matrix: FormatMatrix, *, language: str | None = None) -> AudioChoice | None:
    """Melhor trilha de áudio, opcionalmente de um idioma específico."""
    if language:
        for choice in matrix.audio:
            if choice.language == language:
                return choice
    return matrix.audio[0] if matrix.audio else None


def available_heights(matrix: FormatMatrix) -> tuple[int, ...]:
    """Alturas distintas, da maior para a menor, para preencher o combo da UI."""
    heights = {c.height for c in matrix.video if c.height}
    return tuple(sorted(heights, reverse=True))


def available_fps(matrix: FormatMatrix, height: int | None = None) -> tuple[int, ...]:
    """Framerates disponíveis, opcionalmente limitados a uma resolução."""
    values = {
        c.fps
        for c in matrix.video
        if c.fps and (height is None or c.height == height)
    }
    return tuple(sorted(values, reverse=True))


def available_families(matrix: FormatMatrix, height: int | None = None) -> tuple[str, ...]:
    """Famílias de codec disponíveis, opcionalmente limitadas a uma resolução."""
    families = {
        c.family
        for c in matrix.video
        if c.family and (height is None or c.height == height)
    }
    return tuple(sorted(families, key=lambda f: _VIDEO_FAMILY_RANK.get(f, 90)))


_VIDEO_FAMILY_RANK = {"H.264": 0, "HEVC": 1, "AV1": 2, "VP9": 3, "VP8": 4}
