"""Testes da exportação interpolada em trechos paralelos.

O que se afirma aqui é a **decisão** — quantos trechos, e quando nenhum — e a
forma dos comandos. O que sai do ffmpeg é medido em ``test_integration``, que é
onde se pode comparar o arquivo paralelo com o serial.

A decisão importa mais que o normal porque errar para o lado errado não deixa a
exportação lenta: cada trecho carrega um ``minterpolate`` inteiro na memória, e
foi essa memória que já derrubou esta máquina uma vez.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from videomanager.infrastructure.system import memory
from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.composition import Composition
from videomanager.infrastructure.ffmpeg.composer import audio_only_args
from videomanager.infrastructure.ffmpeg.composer import concat_args
from videomanager.domain.render_cost import interpolation_bytes
from videomanager.infrastructure.ffmpeg.composer import interpolation_segments
from videomanager.infrastructure.ffmpeg.composer import mux_args
from videomanager.infrastructure.ffmpeg.composer import segment_bounds
from videomanager.infrastructure.ffmpeg.composer import segment_video_args
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.infrastructure.ffmpeg import parallel as parallel_export
from videomanager.application.errors import ConversionError
from videomanager.application.errors import JobCancelled
from videomanager.infrastructure.ffmpeg.parallel import ParallelExport
from videomanager.infrastructure.ffmpeg.parallel import plan_segments

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
        # O grafo já limitou ambas as entradas. Um novo corte no remux pode
        # perder quadros válidos quando os pacotes AAC terminam antes.
        assert "-shortest" not in args

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


class ProcessoDeMentira:
    """O mínimo de um ``Popen`` para o laço das etapas finais.

    Guarda se foi terminado ou morto, que é o que os testes de cancelamento
    precisam afirmar — a alternativa seria abrir um ffmpeg de verdade e torcer
    para ele demorar o bastante.
    """

    def __init__(self, codigo: int = 0, erro: bytes = b"", ao_esperar=None) -> None:
        self.returncode = codigo
        self._erro = erro
        self._ao_esperar = ao_esperar
        self.terminado = False
        self.morto = False
        self.stdout = self.stderr = None

    def wait(self, timeout=None):
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode if (self.terminado or self.morto) else None

    def terminate(self) -> None:
        self.terminado = True

    def kill(self) -> None:
        self.morto = True

    def communicate(self, timeout: float | None = None):
        # Só a espera **com prazo** reage: a segunda chamada, sem prazo, é a que
        # recolhe o processo depois do ``kill`` e sempre devolve, como no
        # ``Popen`` de verdade.
        if self._ao_esperar is not None and timeout is not None:
            self._ao_esperar(self)
        return (b"", self._erro)


def exportacao(destino: Path, segments: int = 2) -> ParallelExport:
    composicao = Composition(project=projeto(), container="mp4", interpolate=True)
    return ParallelExport(composicao, destino, TOOLS, segments)


class TestCancelamentoDasEtapasFinais:
    """Emendar, gerar som e juntar não eram alcançáveis pelo cancelamento.

    Elas rodavam fora do registro que o ``cancel`` percorre e sem prazo nenhum.
    "Cancelar" durante "gerar o som" — que percorre a linha do tempo inteira —
    não fazia nada até a etapa acabar; e um ffmpeg preso ali ocupava para sempre
    a **única** vaga da fila local, travando toda conversão seguinte da sessão.
    """

    def test_a_etapa_fica_registrada_enquanto_corre(self, tmp_path: Path, monkeypatch) -> None:
        export = exportacao(tmp_path / "saida.mp4")
        visto: dict[str, bool] = {}

        def cancelar_no_meio(processo: ProcessoDeMentira) -> None:
            # Cancelamento chegando **durante** a etapa: só alcança o processo
            # se ele estiver no registro.
            export.cancel()
            visto["terminado"] = processo.terminado

        processo = ProcessoDeMentira(ao_esperar=cancelar_no_meio)
        monkeypatch.setattr(
            parallel_export.subprocess, "Popen", lambda *a, **k: processo
        )

        with pytest.raises(JobCancelled):
            export._step(["ffmpeg"], "emendar os trechos")

        assert visto["terminado"] is True, "o cancelamento alcançou a etapa"

    def test_a_etapa_sai_do_registro_ao_terminar(self, tmp_path: Path, monkeypatch) -> None:
        export = exportacao(tmp_path / "saida.mp4")
        monkeypatch.setattr(
            parallel_export.subprocess, "Popen", lambda *a, **k: ProcessoDeMentira()
        )
        export._step(["ffmpeg"], "emendar os trechos")
        assert export._processes == {}, "nada fica pendurado no registro"

    def test_etapa_travada_e_interrompida_pelo_prazo(self, tmp_path: Path, monkeypatch) -> None:
        export = exportacao(tmp_path / "saida.mp4")

        def travar(_processo: ProcessoDeMentira) -> None:
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

        processo = ProcessoDeMentira(ao_esperar=travar)
        monkeypatch.setattr(
            parallel_export.subprocess, "Popen", lambda *a, **k: processo
        )

        with pytest.raises(ConversionError):
            export._step(["ffmpeg"], "juntar imagem e som", timeout=1)
        assert processo.morto is True, "não fica um ffmpeg vivo segurando a fila"


class TestFalhaDeUmTrecho:
    """Um trecho que falha derruba os irmãos — e é relatado como falha.

    Cada trecho carrega um ``minterpolate`` inteiro, e a interpolação custa
    dezenas de vezes uma exportação normal: esperar os outros sete terminarem
    por causa de um erro do primeiro segundo gastava a única vaga da fila local
    por dezenas de minutos, e a memória junto, por um arquivo que não vai
    existir.
    """

    def test_a_falha_derruba_os_irmaos(self, tmp_path: Path) -> None:
        export = exportacao(tmp_path / "saida.mp4", segments=4)
        irmao = ProcessoDeMentira()
        export._processes[0] = irmao

        export._fail("Unknown encoder 'libx264'")

        assert irmao.terminado is True
        assert export._aborted is True

    def test_falha_nao_e_relatada_como_cancelamento(self, tmp_path: Path, monkeypatch) -> None:
        # Derrubar os irmãos usa a mesma bandeira do cancelamento; se as duas
        # fossem a mesma coisa, toda falha de trecho apareceria como "Cancelado"
        # e a causa não chegaria a lugar nenhum.
        export = exportacao(tmp_path / "saida.mp4", segments=2)
        monkeypatch.setattr(
            export, "_render", lambda index, destino: export._fail("erro do ffmpeg")
        )

        with pytest.raises(ConversionError, match="erro do ffmpeg"):
            export._build(tmp_path)

        assert export._cancelled is False, "ninguém cancelou nada"

    def test_desistir_continua_sendo_cancelamento(self, tmp_path: Path, monkeypatch) -> None:
        export = exportacao(tmp_path / "saida.mp4", segments=2)
        monkeypatch.setattr(export, "_render", lambda index, destino: export.cancel())

        with pytest.raises(JobCancelled):
            export._build(tmp_path)

    def test_trecho_que_nasce_abortado_nao_abre_ffmpeg(self, tmp_path: Path, monkeypatch) -> None:
        export = exportacao(tmp_path / "saida.mp4", segments=4)
        export.cancel()
        abriu: list[str] = []
        monkeypatch.setattr(
            parallel_export.subprocess,
            "Popen",
            lambda *a, **k: abriu.append("abriu") or ProcessoDeMentira(),
        )

        export._render(0, tmp_path / "trecho.mp4")

        assert abriu == [], "não se abre um ffmpeg para trabalho já descartado"
