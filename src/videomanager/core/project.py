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

# Tela de uma edição que ainda não tem imagem nenhuma.
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30.0

# Teto da taxa escolhida **automaticamente**. Acima de 60 fps o ganho é
# imperceptível e o custo não é: um clipe de câmera lenta a 240 fps levaria a
# exportação inteira para 240 fps — arquivo e tempo de codificação oito vezes
# maiores — por ter sido arrastado para a linha do tempo. Pedir mais que isso
# continua possível, mas explicitamente, pela escolha de taxa da tela.
MAX_AUTO_FPS = 60.0

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
    ADDITIONAL = "adicionais"


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
    # Este bloco carrega **só o som** da mídia: é o bloco que "separar áudio"
    # cria. Sem a marca, um bloco de trilha de áudio cuja mídia também tem
    # imagem continuava passando por bloco de vídeo — a composição desenhava a
    # imagem dele por cima da montagem, a trilha de áudio recusava recebê-lo de
    # volta num arrasto e colar mandava o som para a trilha de vídeo.
    audio_only: bool = False
    # Velocidade de reprodução do bloco (1.0 = normal, 2.0 = dobro, 0.5 = metade).
    speed: float = 1.0
    # Posição e transformação para trilhas de adicionais
    x: float = 0.5  # Centro X normalizado (0.0 a 1.0)
    y: float = 0.5  # Centro Y normalizado (0.0 a 1.0)
    scale: float = 1.0  # Fator de escala (1.0 = padrão)
    rotation: float = 0.0  # Rotação em graus (0.0 a 360.0)
    # Metadados de sobreposições de adicionais
    overlay_type: str = "none"  # "none", "image", "text", "filter"
    text_content: str = ""
    font_family: str = "Sans Serif"
    font_size: int = 36
    font_bold: bool = False
    font_italic: bool = False
    text_color: str = "#ffffff"
    filter_name: str = ""  # "pb", "sepia", "contraste", "vinheta", "inverter"
    # Identidade estável, preservada por ``dataclasses.replace``: é por ela que
    # a seleção, o cache de miniaturas e o desfazer reconhecem o mesmo bloco
    # depois de qualquer alteração.
    clip_id: int = field(default_factory=next_clip_id, compare=False)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def out_point(self) -> float:
        return self.in_point + self.duration * self.speed

    @property
    def has_sound(self) -> bool:
        return self.media.has_audio and not self.muted and not self.detached and not self.is_additional

    @property
    def has_image(self) -> bool:
        """Se este bloco contribui com imagem para a composição.

        Não basta a mídia ter vídeo: o bloco de "separar áudio" nasce do mesmo
        arquivo e não mostra nada.
        """
        if self.overlay_type in ("image", "text", "filter"):
            return True
        return self.media.has_video and not self.audio_only

    @property
    def is_additional(self) -> bool:
        return self.overlay_type in ("image", "text", "filter") or self.is_image

    @property
    def can_adjust_sound(self) -> bool:
        """Se faz sentido oferecer volume e mudo para este bloco."""
        return self.media.has_audio and not self.detached and not self.is_additional

    @property
    def is_image(self) -> bool:
        return self.media.kind is MediaKind.IMAGE

    def contains(self, seconds: float) -> bool:
        return self.start <= seconds < self.end

    def source_time(self, seconds: float) -> float:
        """Instante dentro do arquivo que corresponde a um instante da edição."""
        return self.in_point + max(0.0, (seconds - self.start) * self.speed)

    @property
    def gain_label(self) -> str:
        if self.detached:
            return "áudio separado"
        if self.muted:
            return "mudo"
        if abs(self.gain_db) < 0.05:
            return ""
        return f"{self.gain_db:+.1f} dB".replace(".", ",")

    @property
    def speed_label(self) -> str:
        if abs(self.speed - 1.0) < 0.05:
            return ""
        return f"{self.speed:.1f}x".replace(".", ",")


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
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: float = DEFAULT_FPS

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
    def additional_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.ADDITIONAL)

    @property
    def audio_tracks(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is TrackKind.AUDIO)

    @property
    def has_video(self) -> bool:
        return any(track.clips for track in (*self.video_tracks, *self.additional_tracks))

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
        """O bloco visual que aparece por cima no instante dado."""
        for track in self.tracks:
            if track.kind in (TrackKind.ADDITIONAL, TrackKind.VIDEO):
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

        Adicionais entram no topo absoluto (camadas superiores).
        Vídeo entra abaixo dos adicionais e no topo dos vídeos existentes.
        Áudio entra no fim da lista.
        """
        track = Track(kind=kind, name=name or _default_name(self, kind))
        tracks = list(self.tracks)
        if kind is TrackKind.ADDITIONAL:
            tracks.insert(0, track)
        elif kind is TrackKind.VIDEO:
            tracks.insert(len(self.additional_tracks), track)
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

    def reordered_track(self, from_index: int, to_index: int) -> Project:
        """Reordena uma trilha na pilha, movendo de ``from_index`` para ``to_index``.

        Mover uma trilha de vídeo para cima ou para baixo altera a ordem das
        camadas visuais da composição: a trilha no topo da lista sobrepõe as de
        baixo. Para trilhas de áudio, organiza a ordem visual na linha do tempo.
        """
        if from_index == to_index or not (
            0 <= from_index < len(self.tracks) and 0 <= to_index < len(self.tracks)
        ):
            return self
        tracks = list(self.tracks)
        track = tracks.pop(from_index)
        tracks.insert(to_index, track)
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

        Duas regras, e ambas existem para o arrasto **sempre** ter uma resposta:

        **Onde não cabe, encosta.** A posição é acomodada no vão livre mais
        próximo em vez de recusada — o bloco encosta no vizinho em vez de sumir
        de volta para onde estava.

        **Por cima do vizinho, troca de lugar.** Sem isso não havia como
        reordenar uma sequência: dois blocos encostados não deixam vão nenhum
        entre eles, então arrastar o segundo para antes do primeiro caía sempre
        na regra de cima e não fazia nada — nenhum gesto reordenava a edição.
        """
        found = self.find(clip_id)
        if found is None or not 0 <= track_index < len(self.tracks):
            return self
        origin, clip = found
        destination = self.tracks[track_index]
        if not accepts(destination.kind, clip):
            return self

        start = max(0.0, start)
        if origin == track_index:
            swapped = self._swapped(track_index, clip, start)
            if swapped is not None:
                return swapped
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

    def _swapped(self, track_index: int, moving: Clip, start: float) -> Project | None:
        """Troca ``moving`` de lugar com o vizinho do lado para onde ele vai.

        **O gatilho é a ponta da frente passar do meio do vizinho** — a ponta
        esquerda quando se arrasta para trás, a direita quando se arrasta para a
        frente. Passar do meio é a intenção inequívoca de ficar do outro lado;
        antes disso o gesto é justapor, que é o mais comum de todos e não pode
        virar troca sem querer.

        Não serve medir pelo meio do bloco **arrastado**: um bloco mais longo
        que o vizinho encosta no zero antes de o meio dele alcançar o vizinho, e
        aí nenhum arrasto reordenava mais nada.

        Os dois ficam dentro do espaço que já ocupavam juntos, encostados no
        começo dele. Como esse espaço nunca cresce, a troca não tem como
        esbarrar num terceiro bloco — e por isso não precisa de exceção.

        Os dois lados são exatamente complementares: o ponto que dispara a troca
        num sentido é o mesmo que a desfaz no outro. É o que impede os blocos de
        ficarem trocando de lugar sozinhos enquanto a mão está parada em cima
        dele.

        ``None`` quando não há troca a fazer: aí vale a acomodação no vão.
        """
        others = [
            clip
            for clip in self.tracks[track_index].clips
            if clip.clip_id != moving.clip_id
        ]
        if start < moving.start:
            partner = max(
                (c for c in others if c.start < moving.start),
                key=lambda c: c.start,
                default=None,
            )
            passed = partner is not None and start < partner.start + partner.duration / 2
        elif start > moving.start:
            partner = min(
                (c for c in others if c.start > moving.start),
                key=lambda c: c.start,
                default=None,
            )
            passed = (
                partner is not None
                and start + moving.duration > partner.start + partner.duration / 2
            )
        else:
            return None
        if partner is None or not passed:
            return None

        first, second = (
            (moving, partner) if moving.start > partner.start else (partner, moving)
        )
        base = min(moving.start, partner.start)
        return self.with_updated_clip(first.clip_id, start=base).with_updated_clip(
            second.clip_id, start=base + first.duration
        )

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
            audio_only=True,
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

    Adicionais (textos, filtros e imagens) vivem exclusivamente em trilhas
    de adicionais. Áudio não sobe para trilha de vídeo (não há o que mostrar)
    e imagem ou vídeo não descem para trilha de áudio (o som deles, quando
    existe, é separado por "separar áudio").

    Quem decide é o **bloco**, não a mídia dele: o bloco criado por "separar
    áudio" vem de um arquivo com imagem e mesmo assim é áudio. Enquanto isso
    saía da mídia, esse bloco não podia ser arrastado nem dentro da própria
    trilha, e colar mandava o som para a trilha de vídeo.
    """
    if kind is TrackKind.ADDITIONAL:
        return clip.is_additional
    if clip.is_additional:
        return False
    if kind is TrackKind.VIDEO:
        return clip.has_image
    return clip.media.kind is MediaKind.AUDIO or clip.audio_only


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

    clip = Clip(media=media, start=0.0, duration=media.natural_duration)
    index = 0 if media.has_video else 1
    # A tela sai da mesma regra que vale do segundo arquivo em diante, e não de
    # uma conta própria do começo: duas contas para a mesma decisão acabam
    # discordando, e nenhum leitor saberia qual delas manda.
    return auto_canvas(project.with_clip(index, clip))


def _even(value: int) -> int:
    """Codificadores trabalham em blocos de dois pixels e recusam ímpar."""
    return max(2, value - value % 2)


def auto_canvas(project: Project) -> Project:
    """Ajusta a tela ao material, escolhendo o que não rebaixa nenhum bloco.

    A **maior** imagem e a **maior** taxa entre os blocos: assim nenhum deles é
    reduzido nem tem quadro descartado, e o que perde é só o material menor, que
    é ampliado. Decidir pelo primeiro bloco — como era — fazia a ordem de
    importação decidir a qualidade do resultado inteiro: entrar com um clipe
    480p rebaixava para 480p todo o material 4K que viesse depois, sem aviso e
    sem volta a não ser esvaziando a linha do tempo.

    **Foto não define a tela quando há vídeo.** Uma imagem de 6000 px levaria a
    edição inteira para um tamanho que ninguém pediu, e ampliar uma foto custa
    muito menos que ampliar um vídeo.

    Sem imagem nenhuma, volta ao padrão: é o que faz a próxima importação
    definir a tela de novo, em vez de herdar a de um material que já saiu.
    """
    visible = [clip for track in project.video_tracks for clip in track.clips
               if clip.has_image]
    videos = [c for c in visible if c.media.kind is MediaKind.VIDEO] or visible
    sized = [c.media for c in videos if c.media.width and c.media.height]
    if not sized:
        return replace(
            project, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS
        )

    biggest = max(sized, key=lambda media: (media.width or 0) * (media.height or 0))
    rates = [media.fps for media in sized if media.fps]
    return replace(
        project,
        width=_even(biggest.width or DEFAULT_WIDTH),
        height=_even(biggest.height or DEFAULT_HEIGHT),
        fps=min(max(rates), MAX_AUTO_FPS) if rates else DEFAULT_FPS,
    )
