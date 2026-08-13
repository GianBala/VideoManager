"""O projeto de edição: trilhas, blocos e as operações sobre eles.

O modelo é **imutável**. Toda operação — mover um bloco, dividir, mudar volume,
colar — devolve um projeto novo, e a interface guarda o anterior numa pilha. É o
que faz o desfazer ser uma linha de código em vez de um caderno de anotações
sobre o que cada ação alterou, e o que garante que nenhuma tela fique segurando
um bloco que já não existe.

**Um bloco não é um pedaço de arquivo, é um pedaço de arquivo colocado em algum
lugar do tempo.** Daí os três números que ele carrega: ``in_point`` diz onde
começa dentro da mídia de origem, ``start`` diz onde começa na linha do tempo, e
``duration`` vale para os dois. Separar as duas linhas do tempo — a do arquivo e
a da edição — é o que permite o mesmo arquivo aparecer duas vezes, em posições
diferentes, sem cópia nenhuma.

**Volume em decibéis, e não em porcentagem.** É a unidade em que se fala de som
("abaixa 3 dB"), é a que o ffmpeg aceita direto, e 0 dB significa exatamente "não
mexe" — enquanto "100%" convida a ser interpretado como um teto.

A ordem de ``tracks`` é a da tela, de cima para baixo: trilhas de vídeo primeiro,
depois as de áudio. Na composição isso se inverte — a trilha de vídeo mais baixa
é o fundo e as de cima são sobrepostas —, que é a convenção de todo editor.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .trimmer import IMAGE_CODECS, MIN_SEGMENT

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    from .converter import LocalMedia

# Duração que uma imagem assume ao entrar na linha do tempo. Cinco segundos é o
# padrão dos editores de consumo, e o bloco pode ser esticado pela alça depois.
IMAGE_DURATION = 5.0

# Limites do volume por bloco. Abaixo de -60 dB é silêncio para qualquer
# ouvido; acima de +12 dB o que se ganha é distorção.
MIN_GAIN_DB = -60.0
MAX_GAIN_DB = 12.0

_clip_ids = itertools.count(1)
_track_ids = itertools.count(1)


def next_clip_id() -> int:
    """Identidade nova para um bloco.

    Público porque colar cria um bloco que não é o copiado: sem identidade
    própria, a seleção e o cache de miniaturas tratariam os dois como o mesmo.
    Um contador só para todos evita duas fontes de identidade se cruzarem.
    """
    return next(_clip_ids)


class MediaKind(Enum):
    VIDEO = "vídeo"
    IMAGE = "imagem"
    AUDIO = "áudio"


class TrackKind(Enum):
    VIDEO = "vídeo"
    AUDIO = "áudio"


@dataclass(frozen=True)
class MediaRef:
    """Uma mídia importada, já inspecionada.

    Guarda o que a composição precisa saber sem reabrir o arquivo: se tem
    imagem, se tem som, o tamanho e a duração.
    """

    path: Path
    kind: MediaKind
    duration: float | None = None  # None numa imagem: ela dura o que mandarem
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = False
    # Número de canais da trilha de áudio. Guardado porque a mixagem trata mono
    # de forma diferente de estéreo (ver ``composer._audio_chain``).
    channels: int | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def has_video(self) -> bool:
        return self.kind in (MediaKind.VIDEO, MediaKind.IMAGE)

    @property
    def natural_duration(self) -> float:
        """Quanto o bloco dura ao ser inserido pela primeira vez."""
        if self.kind is MediaKind.IMAGE:
            return IMAGE_DURATION
        return self.duration or IMAGE_DURATION

    @property
    def label(self) -> str:
        return f"{self.name}  ·  {self.kind.value}"


def display_width(width: int | None, sar: float | None) -> int | None:
    """Largura com que a imagem é exibida, dado o pixel do arquivo.

    Pixel quadrado (ou desconhecido, que o ffmpeg trata como quadrado) devolve a
    largura como está — que é o caso de praticamente toda mídia atual.
    """
    if not width:
        return None
    if not sar or abs(sar - 1.0) < 1e-3:
        return width
    return max(2, round(width * sar / 2) * 2)


def media_ref(local: LocalMedia) -> MediaRef:
    """Constrói a referência a partir de um arquivo já inspecionado.

    Recebe o resultado do ``probe_file`` em vez de chamá-lo: é o que mantém este
    módulo livre de subprocesso — e o ``converter``, que faz a inspeção, livre
    para importar o compositor sem fechar um ciclo.
    """
    video = local.video
    is_image = (
        video is not None
        and video.codec.lower() in IMAGE_CODECS
        and not local.has_audio
    )
    if is_image:
        kind = MediaKind.IMAGE
    elif video is not None and video.codec.lower() not in IMAGE_CODECS:
        kind = MediaKind.VIDEO
    else:
        kind = MediaKind.AUDIO

    return MediaRef(
        path=local.path,
        kind=kind,
        duration=None if kind is MediaKind.IMAGE else local.duration,
        # Largura de **exibição**, e não a de armazenamento: um rip de DVD
        # guarda 720×480 para aparecer em 16:9, e é a forma exibida que decide o
        # formato da tela do projeto. Guardar a largura crua fazia a edição
        # nascer com a proporção errada e a imagem achatada.
        width=display_width(video.width, video.sar) if video else None,
        height=video.height if video else None,
        fps=video.fps if video else None,
        has_audio=local.has_audio,
        channels=local.audio.channels if local.audio else None,
    )


@dataclass(frozen=True)
class Clip:
    """Um pedaço de mídia colocado num instante da linha do tempo."""

    media: MediaRef
    start: float
    duration: float
    in_point: float = 0.0
    gain_db: float = 0.0
    muted: bool = False
    # O som deste bloco saiu para uma trilha própria ("separar áudio"). Distinto
    # de ``muted``: mudo é uma escolha que se desfaz no mesmo bloco, separado
    # significa que o som agora se ajusta noutro lugar — e é o que permite à
    # tela dizer isso, em vez de oferecer um controle de volume que não faz nada.
    detached: bool = False
    # Identidade estável, preservada por ``dataclasses.replace``: é por ela que
    # a seleção, o cache de miniaturas e o desfazer reconhecem o mesmo bloco
    # depois de qualquer alteração.
    clip_id: int = field(default_factory=next_clip_id, compare=False)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def out_point(self) -> float:
        return self.in_point + self.duration

    @property
    def has_sound(self) -> bool:
        return self.media.has_audio and not self.muted and not self.detached

    @property
    def can_adjust_sound(self) -> bool:
        """Se faz sentido oferecer volume e mudo para este bloco."""
        return self.media.has_audio and not self.detached

    @property
    def is_image(self) -> bool:
        return self.media.kind is MediaKind.IMAGE

    def contains(self, seconds: float) -> bool:
        return self.start <= seconds < self.end

    def source_time(self, seconds: float) -> float:
        """Instante dentro do arquivo que corresponde a um instante da edição."""
        return self.in_point + max(0.0, seconds - self.start)

    @property
    def gain_label(self) -> str:
        if self.detached:
            return "áudio separado"
        if self.muted:
            return "mudo"
        if abs(self.gain_db) < 0.05:
            return ""
        return f"{self.gain_db:+.1f} dB".replace(".", ",")


@dataclass(frozen=True)
class Track:
    """Uma faixa da linha do tempo, com os blocos em ordem de tempo."""

    kind: TrackKind
    clips: tuple[Clip, ...] = ()
    muted: bool = False
    name: str = ""
    track_id: int = field(default_factory=lambda: next(_track_ids), compare=False)

    @property
    def duration(self) -> float:
        return max((clip.end for clip in self.clips), default=0.0)

    def clip_at(self, seconds: float) -> Clip | None:
        return next((clip for clip in self.clips if clip.contains(seconds)), None)

    def sorted_clips(self) -> tuple[Clip, ...]:
        return tuple(sorted(self.clips, key=lambda clip: clip.start))

    def gaps(self, ignore: int | None = None) -> list[tuple[float, float]]:
        """Vãos livres da trilha, do começo ao infinito.

        É a lista de onde um bloco pode ser solto. Existe para o arrasto ter
        sempre uma resposta: soltar em cima de outro bloco não cancela o
        movimento, acomoda no vão mais próximo que couber.
        """
        occupied = sorted(
            (clip for clip in self.clips if clip.clip_id != ignore),
            key=lambda clip: clip.start,
        )
        result: list[tuple[float, float]] = []
        cursor = 0.0
        for clip in occupied:
            if clip.start > cursor:
                result.append((cursor, clip.start))
            cursor = max(cursor, clip.end)
        result.append((cursor, float("inf")))
        return result

    def free_range(self, seconds: float, ignore: int | None = None) -> tuple[float, float]:
        """Vão livre que contém ``seconds``, entre os blocos vizinhos.

        É o que limita um arrasto: um bloco só pode ser solto onde cabe, e não
        por cima do vizinho. Sobreposição de vídeo na mesma trilha não tem
        resposta certa — qual dos dois aparece? —, então ela não acontece.
        """
        floor = 0.0
        ceiling = float("inf")
        for clip in self.clips:
            if clip.clip_id == ignore:
                continue
            if clip.end <= seconds:
                floor = max(floor, clip.end)
            elif clip.start >= seconds:
                ceiling = min(ceiling, clip.start)
            else:
                # O instante cai dentro de um bloco: não há vão aqui.
                return (clip.start, clip.start)
        return (floor, ceiling)


@dataclass(frozen=True)
class Project:
    """A edição inteira: trilhas, blocos e o formato da tela."""

    tracks: tuple[Track, ...] = ()
    width: int = 1920
    height: int = 1080
    fps: float = 30.0

    # -- leitura ---------------------------------------------------------

    @property
    def duration(self) -> float:
        return max((track.duration for track in self.tracks), default=0.0)

    @property
    def is_empty(self) -> bool:
        return not any(track.clips for track in self.tracks)

    @property
    def clips(self) -> tuple[Clip, ...]:
        return tuple(clip for track in self.tracks for clip in track.clips)

    @property
    def video_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.VIDEO)

    @property
    def audio_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.AUDIO)

    @property
    def has_video(self) -> bool:
        return any(track.clips for track in self.video_tracks)

    @property
    def has_sound(self) -> bool:
        """Se alguma coisa vai sair pelos alto-falantes."""
        return any(
            clip.has_sound
            for track in self.tracks
            if not track.muted
            for clip in track.clips
        )

    def track_index(self, track_id: int) -> int:
        return next(
            (i for i, track in enumerate(self.tracks) if track.track_id == track_id), -1
        )

    def find(self, clip_id: int) -> tuple[int, Clip] | None:
        """Devolve (índice da trilha, bloco) do bloco pedido."""
        for index, track in enumerate(self.tracks):
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    return index, clip
        return None

    def clip_at(self, track_index: int, seconds: float) -> Clip | None:
        if not 0 <= track_index < len(self.tracks):
            return None
        return self.tracks[track_index].clip_at(seconds)

    def topmost_video_at(self, seconds: float) -> Clip | None:
        """O bloco de vídeo que aparece por cima no instante dado."""
        for track in self.video_tracks:
            clip = track.clip_at(seconds)
            if clip is not None:
                return clip
        return None

    # -- escrita (sempre devolvendo um projeto novo) ----------------------

    def _replace_track(self, index: int, track: Track) -> Project:
        tracks = list(self.tracks)
        tracks[index] = track
        return replace(self, tracks=tuple(tracks))

    def with_track(self, kind: TrackKind, name: str = "") -> Project:
        """Acrescenta uma trilha vazia, no lugar certo da pilha.

        Vídeo entra por cima das de vídeo, áudio entra no fim: é a ordem que a
        composição espera, e a que o usuário vê na tela.
        """
        track = Track(kind=kind, name=name or _default_name(self, kind))
        tracks = list(self.tracks)
        if kind is TrackKind.VIDEO:
            tracks.insert(0, track)
        else:
            tracks.append(track)
        return replace(self, tracks=tuple(tracks))

    def without_track(self, track_index: int) -> Project:
        """Remove a trilha inteira, com o que houver nela.

        Não se guarda uma última trilha "por precaução": importar uma mídia cria
        a trilha de que ela precisa (ver ``EditPanel._place``), então uma linha
        do tempo sem trilha nenhuma é um estado válido — e é o que se espera de
        quem acabou de apagar tudo.
        """
        if not 0 <= track_index < len(self.tracks):
            return self
        tracks = list(self.tracks)
        del tracks[track_index]
        return replace(self, tracks=tuple(tracks))

    def with_clip(self, track_index: int, clip: Clip) -> Project:
        track = self.tracks[track_index]
        clips = tuple(sorted((*track.clips, clip), key=lambda c: c.start))
        return self._replace_track(track_index, replace(track, clips=clips))

    def without_clip(self, clip_id: int) -> Project:
        found = self.find(clip_id)
        if found is None:
            return self
        index, _ = found
        track = self.tracks[index]
        clips = tuple(c for c in track.clips if c.clip_id != clip_id)
        return self._replace_track(index, replace(track, clips=clips))

    def with_updated_clip(self, clip_id: int, **changes: object) -> Project:
        found = self.find(clip_id)
        if found is None:
            return self
        index, clip = found
        track = self.tracks[index]
        updated = replace(clip, **changes)  # type: ignore[arg-type]
        clips = tuple(
            sorted(
                (updated if c.clip_id == clip_id else c for c in track.clips),
                key=lambda c: c.start,
            )
        )
        return self._replace_track(index, replace(track, clips=clips))

    def with_track_muted(self, track_index: int, muted: bool) -> Project:
        track = self.tracks[track_index]
        return self._replace_track(track_index, replace(track, muted=muted))

    def moved(self, clip_id: int, track_index: int, start: float) -> Project:
        """Move um bloco no tempo e, se pedido, para outra trilha.

        A posição é acomodada no vão livre mais próximo em vez de recusada: o
        arrasto continua respondendo ao mouse, e o bloco simplesmente encosta no
        vizinho em vez de sumir de volta para onde estava.
        """
        found = self.find(clip_id)
        if found is None or not 0 <= track_index < len(self.tracks):
            return self
        origin, clip = found
        destination = self.tracks[track_index]
        if not accepts(destination.kind, clip):
            return self

        start = max(0.0, start)
        ignore = clip_id if origin == track_index else None
        options = [
            min(max(floor, start), ceiling - clip.duration)
            for floor, ceiling in destination.gaps(ignore=ignore)
            if ceiling - floor >= clip.duration
        ]
        if not options:
            # Nenhum vão comporta o bloco nesta trilha: fica onde estava.
            return self
        start = min(options, key=lambda value: abs(value - start))

        moved = replace(clip, start=start)
        if origin == track_index:
            return self.with_updated_clip(clip_id, start=start)
        return self.without_clip(clip_id).with_clip(track_index, moved)

    def resized(self, clip_id: int, edge: str, seconds: float) -> Project:
        """Arrasta uma das pontas do bloco, respeitando a mídia e os vizinhos."""
        found = self.find(clip_id)
        if found is None:
            return self
        index, clip = found
        floor, ceiling = self.tracks[index].free_range(
            (clip.start + clip.end) / 2, ignore=clip_id
        )

        if edge == "inicio":
            # Uma imagem não tem começo de arquivo para respeitar; um vídeo não
            # pode ser puxado para antes do primeiro quadro que ele tem.
            limit = clip.start - clip.in_point if not clip.is_image else floor
            value = min(max(max(floor, limit), seconds), clip.end - MIN_SEGMENT)
            return self.with_updated_clip(
                clip_id,
                start=value,
                duration=clip.end - value,
                in_point=clip.in_point + (value - clip.start),
            )

        available = (
            float("inf")
            if clip.is_image
            else max(0.0, (clip.media.duration or 0.0) - clip.in_point)
        )
        value = min(
            max(seconds, clip.start + MIN_SEGMENT), min(ceiling, clip.start + available)
        )
        return self.with_updated_clip(clip_id, duration=value - clip.start)

    def split(self, clip_id: int, seconds: float) -> Project:
        """Divide o bloco no instante dado, como a tesoura da barra."""
        found = self.find(clip_id)
        if found is None:
            return self
        index, clip = found
        if (
            seconds - clip.start < MIN_SEGMENT
            or clip.end - seconds < MIN_SEGMENT
        ):
            return self

        left = replace(clip, duration=seconds - clip.start)
        right = replace(
            clip,
            start=seconds,
            duration=clip.end - seconds,
            in_point=clip.source_time(seconds),
            clip_id=next_clip_id(),
        )
        track = self.tracks[index]
        clips = tuple(
            sorted(
                (left if c.clip_id == clip_id else c for c in track.clips),
                key=lambda c: c.start,
            )
        )
        return self._replace_track(index, replace(track, clips=(*clips, right))).tidy()

    def detached_audio(self, clip_id: int) -> Project:
        """Separa o som de um bloco de vídeo numa trilha de áudio própria.

        O som **sai** do bloco de vídeo, não é apenas silenciado: a partir daí
        ele se move, se corta e se ajusta sozinho, e é no bloco novo que o
        volume passa a valer. O bloco novo nasce na mesma posição, para o som
        continuar casado com a imagem; desfazer devolve os dois ao que eram.
        """
        found = self.find(clip_id)
        if found is None:
            return self
        _, clip = found
        if not clip.can_adjust_sound or clip.media.kind is MediaKind.AUDIO:
            return self

        project = self.with_updated_clip(clip_id, detached=True, muted=False)
        target = project._free_audio_track(clip.start, clip.duration)
        if target is None:
            project = project.with_track(TrackKind.AUDIO)
            target = len(project.tracks) - 1
        detached = Clip(
            media=clip.media,
            start=clip.start,
            duration=clip.duration,
            in_point=clip.in_point,
            gain_db=clip.gain_db,
        )
        return project.with_clip(target, detached)

    def _free_audio_track(self, start: float, duration: float) -> int | None:
        for index, track in enumerate(self.tracks):
            if track.kind is not TrackKind.AUDIO:
                continue
            floor, ceiling = track.free_range(start)
            if floor <= start and start + duration <= ceiling:
                return index
        return None

    def tidy(self) -> Project:
        """Reordena os blocos de cada trilha por tempo."""
        return replace(
            self,
            tracks=tuple(replace(t, clips=t.sorted_clips()) for t in self.tracks),
        )

    def without_empty_tracks(self, keep: int = 2) -> Project:
        """Descarta trilhas vazias, mantendo um mínimo para trabalhar."""
        used = [t for t in self.tracks if t.clips]
        if len(used) >= keep:
            return replace(self, tracks=tuple(used))
        return self


def accepts(kind: TrackKind, clip: Clip) -> bool:
    """Se um bloco pode viver numa trilha desta espécie.

    Áudio não sobe para trilha de vídeo (não há o que mostrar) e imagem ou vídeo
    não descem para trilha de áudio (o som deles, quando existe, é separado por
    "separar áudio").
    """
    if kind is TrackKind.VIDEO:
        return clip.media.has_video
    return clip.media.kind is MediaKind.AUDIO


def _default_name(project: Project, kind: TrackKind) -> str:
    same = sum(1 for track in project.tracks if track.kind is kind)
    return f"{kind.value.capitalize()} {same + 1}"


def new_project(media: MediaRef | None = None) -> Project:
    """Projeto inicial: uma trilha de vídeo e uma de áudio.

    Duas trilhas desde o começo, mesmo vazias, porque é o que dá lugar para
    soltar o primeiro arquivo — e porque separar o áudio de um vídeo precisa de
    um destino que já exista.
    """
    project = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, name="Vídeo 1"),
            Track(kind=TrackKind.AUDIO, name="Áudio 1"),
        )
    )
    if media is None:
        return project

    project = fit_canvas(project, media)
    clip = Clip(media=media, start=0.0, duration=media.natural_duration)
    index = 0 if media.has_video else 1
    return project.with_clip(index, clip)


def fit_canvas(project: Project, media: MediaRef) -> Project:
    """Ajusta o formato da tela ao primeiro vídeo que entrar.

    Sem isto, um vídeo vertical de celular sairia com tarjas pretas dos dois
    lados numa tela 16:9 que ninguém pediu.
    """
    if project.has_video or media.kind is MediaKind.AUDIO:
        return project
    if not media.width or not media.height:
        return project
    return replace(
        project,
        width=media.width - media.width % 2,
        height=media.height - media.height % 2,
        fps=media.fps or project.fps,
    )
