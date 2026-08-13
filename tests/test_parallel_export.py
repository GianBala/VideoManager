"""Testes da exportação interpolada em trechos paralelos.

O que se afirma aqui é a **decisão** — quantos trechos, e quando nenhum — e a
forma dos comandos. O que sai do ffmpeg é medido em ``test_integration``, que é
onde se pode comparar o arquivo paralelo com o serial.

A decisão importa mais que o normal porque errar para o lado errado não deixa a
exportação lenta: cada trecho carrega um ``minterpolate`` inteiro na memória, e
foi essa memória que já derrubou esta máquina uma vez.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.core import memory
from videomanager.core.binaries import FFmpegTools
from videomanager.core.composer import (
    Composition,
    audio_only_args,
    concat_args,
    interpolation_bytes,
    interpolation_segments,
    mux_args,
    segment_bounds,
    segment_video_args,
)
from videomanager.core.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)
from videomanager.core.parallel_export import plan_segments

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
GIGA = 1024 ** 3

LENTO = MediaRef(
    path=Path("/m/cinema.mp4"), kind=MediaKind.VIDEO, duration=600.0, width=1920,
    height=1080, fps=24.0, has_audio=True, channels=2,
)
MUDO = MediaRef(
    path=Path("/m/mudo.mp4"), kind=MediaKind.VIDEO, duration=600.0, width=1920,
    height=1080, fps=24.0, has_audio=False,
)


def projeto(media: MediaRef = LENTO, duration: float = 60.0, fps: float = 60.0) -> Project:
    track = Track(
        kind=TrackKind.VIDEO,
        clips=(Clip(media=media, start=0.0, duration=duration),),
        name="V",
    )
    return Project(tracks=(track,), width=1920, height=1080, fps=fps)


class TestQuantosTrechos:
    def test_sem_o_que_interpolar_nao_divide(self) -> None:
        # Material já na taxa da tela: não há filtro caro a paralelizar.
        parado = projeto(fps=24.0)
        assert interpolation_segments(parado, available=16 * GIGA, cores=16) == 1

    def test_memoria_desconhecida_nao_multiplica_nada(self) -> None:
        # Onde não dá para perguntar quanta memória há, o caminho seguro é o de
        # sempre: um comando só, um ``minterpolate`` só.
        assert interpolation_segments(projeto(), available=None, cores=16) == 1

    def test_a_memoria_limita_os_trechos(self) -> None:
        custo = interpolation_bytes(projeto())
        # Metade de "três custos" dá um trecho; a outra metade fica para o
        # sistema e para o que mais estiver aberto.
        assert interpolation_segments(projeto(), available=custo * 3, cores=16) == 1
        assert interpolation_segments(projeto(), available=custo * 8, cores=16) == 4

    def test_os_nucleos_limitam_os_trechos(self) -> None:
        assert interpolation_segments(projeto(), available=64 * GIGA, cores=2) == 2

    def test_edicao_curta_nao_vale_dividir(self) -> None:
        # Abrir processo, decodificar a sobra e concatenar come o que se ganha.
        curto = projeto(duration=3.0)
        assert interpolation_segments(curto, available=64 * GIGA, cores=16) == 1

    def test_a_duracao_limita_os_trechos(self) -> None:
        # Trechos abaixo de dois segundos não se pagam.
        assert interpolation_segments(
            projeto(duration=9.0), available=64 * GIGA, cores=16
        ) == 4

    def test_ha_um_teto_de_trechos(self) -> None:
        # Além dele o gargalo passa a ser ler o mesmo arquivo por todos.
        assert interpolation_segments(
            projeto(duration=600.0), available=512 * GIGA, cores=64
        ) == 8

    def test_sem_interpolar_o_plano_e_sempre_um(self) -> None:
        assert plan_segments(Composition(projeto(), "mp4", interpolate=False)) == 1


class TestLimitesDosTrechos:
    def test_cobrem_a_edicao_inteira_sem_sobrepor(self) -> None:
        limites = segment_bounds(10.0, 4)
        assert limites[0][0] == 0.0
        assert sum(span for _, span in limites) == pytest.approx(10.0)
        for (inicio, span), (seguinte, _) in zip(limites, limites[1:]):
            assert inicio + span == pytest.approx(seguinte), "vão ou sobreposição"

    def test_o_ultimo_absorve_a_sobra_da_divisao(self) -> None:
        # Somar arredondamentos erraria o fim por alguns milissegundos, e o
        # arquivo sairia mais curto que a edição.
        limites = segment_bounds(10.0, 3)
        assert limites[-1][0] + limites[-1][1] == pytest.approx(10.0)

    def test_um_trecho_e_a_edicao_toda(self) -> None:
        assert segment_bounds(7.5, 1) == ((0.0, 7.5),)


class TestComandoDoTrecho:
    def comando(self, at: float = 0.0, span: float = 10.0) -> list[str]:
        return segment_video_args(
            projeto(), at, span, Path("/tmp/t.mp4"), TOOLS
        )

    def test_decodifica_alem_do_fim_e_corta_no_tempo_certo(self) -> None:
        # A sobra é o que dá ao filtro o quadro seguinte para inventar os
        # últimos do trecho. Medido: sem ela, 464 imagens distintas contra 476,
        # exatamente quatro por emenda.
        args = self.comando(span=10.0)
        assert "trim=duration=10.500000" in " ".join(args), "faltou a sobra no grafo"
        assert args[args.index("-t") + 1] == "10.000000", "a saída sai no tempo exato"

    def test_o_trecho_nao_leva_audio(self) -> None:
        # Emendar trilhas codificadas em ponto arbitrário produz salto ou
        # estalo: o som sai num passe só, depois.
        args = self.comando()
        assert "-an" in args
        assert "amix" not in " ".join(args)

    def test_o_trecho_interpola(self) -> None:
        assert "minterpolate" in " ".join(self.comando())

    def test_o_trecho_relata_progresso(self) -> None:
        # São vários processos ao mesmo tempo; sem o progresso de cada um, a
        # barra não teria como somar.
        args = self.comando()
        assert args[args.index("-progress") + 1] == "pipe:1"


class TestEmendaEMixagem:
    def test_a_emenda_copia_os_dados(self) -> None:
        # Recodificar aqui jogaria fora o tempo que a divisão economizou.
        args = concat_args(Path("/tmp/l.txt"), Path("/tmp/v.mp4"), TOOLS)
        assert args[args.index("-c") + 1] == "copy"
        assert args[args.index("-f") + 1] == "concat"

    def test_edicao_sem_som_nao_gera_passe_de_audio(self) -> None:
        assert audio_only_args(projeto(MUDO), Path("/tmp/a.m4a"), TOOLS) is None

    def test_o_som_sai_da_mixagem_inteira(self) -> None:
        args = audio_only_args(projeto(), Path("/tmp/a.m4a"), TOOLS)
        assert args is not None
        assert "minterpolate" not in " ".join(args), "som não passa por interpolação"

    def test_juntar_copia_os_dois(self) -> None:
        args = mux_args(Path("/tmp/v.mp4"), Path("/tmp/a.m4a"), Path("/tmp/f.mp4"), TOOLS)
        assert args[args.index("-c") + 1] == "copy"
        assert "-shortest" in args

    def test_sem_som_nao_ha_segunda_entrada(self) -> None:
        args = mux_args(Path("/tmp/v.mp4"), None, Path("/tmp/f.mp4"), TOOLS)
        assert args.count("-i") == 1
        assert "-shortest" not in args


class TestMemoriaDisponivel:
    def test_le_o_campo_certo_do_proc(self, tmp_path: Path, monkeypatch) -> None:
        # ``MemFree`` seria o campo errado: o kernel usa quase toda a memória
        # livre como cache de disco, e num sistema em uso ele fica perto de zero
        # — a conta recusaria dividir sempre.
        arquivo = tmp_path / "meminfo"
        arquivo.write_text(
            "MemTotal:       16000000 kB\n"
            "MemFree:           80000 kB\n"
            "MemAvailable:    8000000 kB\n"
        )
        monkeypatch.setattr(memory, "_MEMINFO", arquivo)
        assert memory._linux_available() == 8_000_000 * 1024

    def test_sem_o_campo_devolve_desconhecido(self, tmp_path: Path, monkeypatch) -> None:
        arquivo = tmp_path / "meminfo"
        arquivo.write_text("MemTotal: 16000000 kB\n")
        monkeypatch.setattr(memory, "_MEMINFO", arquivo)
        assert memory._linux_available() is None

    def test_arquivo_ausente_devolve_desconhecido(self, tmp_path: Path, monkeypatch) -> None:
        # "Não sei" é diferente de zero: quem chama tem de escolher o caminho
        # conservador em vez de supor que há memória sobrando.
        monkeypatch.setattr(memory, "_MEMINFO", tmp_path / "nao-existe")
        assert memory._linux_available() is None
