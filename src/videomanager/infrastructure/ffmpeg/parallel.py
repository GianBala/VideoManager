"""Exportação interpolada dividida em trechos paralelos.

O ``minterpolate`` é **de uma thread só** — medido, 110% de CPU numa máquina de
vinte núcleos — e custa dezenas de vezes o tempo de uma exportação normal. Não há
como paralelizá-lo por dentro: ele não implementa fatiamento por threads, e
``-filter_threads`` não muda nada (medido). O que sobra é dividir a linha do
tempo e interpolar os pedaços ao mesmo tempo.

Medido nesta máquina, 8 s de 24 fps para 60 fps em quatro trechos: 43,7 s para
16,6 s (2,6×), com a saída indistinguível da serial — SSIM 0,997 e as mesmas 476
imagens distintas.

Três decisões sustentam isso:

**Cada trecho decodifica meio segundo além do fim dele.** Para inventar um
quadro o filtro precisa do seguinte, e no fim de um trecho esse quadro está no
trecho de outro processo. Sem a sobra, o ``tpad`` clona os últimos: medido, 464
imagens distintas contra 476, exatamente quatro por emenda. A saída é cortada no
tempo exato, então a sobra não aparece no arquivo.

**Os trechos são só de vídeo, e o som sai num passe só.** Emendar trilhas
codificadas em pontos arbitrários produz salto ou estalo na junção — o quadro de
áudio não termina onde o corte cai. O som é barato (não passa por interpolação
nenhuma) e por isso não perde nada em ser feito inteiro de uma vez.

**A emenda copia os dados.** Todos os trechos vêm do mesmo encoder, com os
mesmos parâmetros, e cada um começa em keyframe: são as condições do demuxer
``concat``. Recodificar aqui jogaria fora o tempo que a divisão economizou.

Quantos trechos é decisão de ``composer.interpolation_segments``, e ela é
conservadora de propósito: cada trecho carrega um ``minterpolate`` inteiro na
memória, e foi essa memória que já derrubou esta máquina uma vez.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from videomanager.infrastructure.ffmpeg.command_assets import filter_script
from videomanager.infrastructure.storage.outputs import FileOutputStore
from videomanager.application.ports.output import OutputLease

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.domain.composition import Composition
from videomanager.infrastructure.ffmpeg.composer import audio_only_args
from videomanager.infrastructure.ffmpeg.composer import concat_args
from videomanager.infrastructure.ffmpeg.composer import interpolation_segments
from videomanager.infrastructure.ffmpeg.composer import mux_args
from videomanager.infrastructure.ffmpeg.composer import segment_bounds
from videomanager.infrastructure.ffmpeg.composer import segment_video_args
from videomanager.application.events import Progress
from videomanager.application.errors import ConversionError
from videomanager.domain.i18n import Text
from videomanager.application.errors import JobCancelled
from videomanager.infrastructure.ffmpeg.thumbnail import embed_thumbnail
from videomanager.infrastructure.system.memory import available_bytes
from videomanager.infrastructure.system.process import ProcessControl, terminate_and_wait, terminate_async

_PROGRESS_LINE = re.compile(r"^([a-z_]+)=(.*)$")


def plan_segments(composition: Composition) -> int:
    """Em quantos trechos esta exportação vale a pena ser dividida.

    ``1`` quer dizer "pelo caminho de sempre, num comando só", e é a resposta
    para tudo que não se encaixa — inclusive para uma máquina cuja memória
    disponível não dá para consultar.
    """
    if not composition.interpolate:
        return 1
    return interpolation_segments(
        composition.project,
        available=available_bytes(),
        cores=os.cpu_count() or 1,
    )

# Quanto do progresso cabe aos trechos. O que vem depois — emendar e juntar o som
# — copia dados e leva um piscar de olhos perto da interpolação; reservar uma
# fatia pequena evita a barra parar em 100% enquanto ainda há passos por fazer.
_SEGMENTS_SHARE = 0.92

# Onde as etapas finais (emendar, gerar som, juntar) ficam registradas enquanto
# correm. Índice negativo de propósito: elas dividem o mesmo registro dos
# trechos — que é o que ``cancel`` percorre — sem colidir com os índices deles.
_STEP_SLOT = -1

# Prazo de uma etapa final. Todas as três copiam dados e levam segundos mesmo
# num projeto longo; meia hora é folga tão larga que só se esgota quando alguma
# coisa travou de verdade. Sem prazo, o travamento era permanente.
_STEP_TIMEOUT = 1800

# Verbo mostrado na fila. Difere do "Exportando" da tabela ``_PHASES`` de
# ``converter.py`` de propósito: esta exportação custa dezenas de vezes o tempo
# de uma normal, e dizer **por quê** é o que separa "está travado" de "está
# fazendo a coisa cara que eu pedi".
_PHASE = "PHASE_INTERPOLATING"


class ParallelExport:
    """Executa uma :class:`Composition` interpolada em trechos paralelos."""

    def __init__(
        self,
        composition: Composition,
        destination: Path,
        tools: FFmpegTools,
        segments: int,
        *,
        on_progress: Callable[[Progress], None] | None = None,
        text_assets: dict[int, Path] | None = None,
        lease: OutputLease | None = None,
    ) -> None:
        self._text_assets = text_assets
        self._composition = composition
        self._destination = destination
        self._outputs = FileOutputStore()
        self._lease = lease
        self._tools = tools
        # A duração da **saída**, a mesma do caminho serial. A da edição inteira
        # conta blocos que não saem no arquivo (um áudio mudo depois do fim do
        # vídeo) e deixava o paralelo mais longo que o serial, com tela preta.
        self._bounds = segment_bounds(composition.output_duration, segments)
        self._on_progress = on_progress
        # Duas bandeiras, e não uma: ``_cancelled`` é a desistência do usuário e
        # ``_aborted`` é "pare tudo", que também vale quando um trecho falha.
        # Confundir as duas fazia a falha de um trecho ser relatada como
        # cancelamento — e o usuário via "Cancelado" numa tarefa que ninguém
        # cancelou, sem a causa em lugar nenhum.
        self._postprocess = ProcessControl()
        self._cancelled = False
        self._aborted = False
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen] = {}
        # Quanto de cada trecho já saiu, em segundos. A barra é a soma disto
        # sobre a duração do projeto: com quatro processos correndo, o progresso
        # de um só contaria um quarto da verdade.
        self._done: dict[int, float] = {}
        self._errors: list[str | Text] = []

    # -- controle ---------------------------------------------------------

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._postprocess.cancel()
        self._abort()

    def _abort(self) -> None:
        """Derruba tudo que estiver correndo, seja por desistência ou por falha."""
        self._aborted = True
        with self._lock:
            correntes = list(self._processes.values())
        for process in correntes:
            if process.poll() is None:
                terminate_async(process)

    def _fail(self, detalhe: str | Text) -> None:
        """Registra a falha de um trecho e derruba os irmãos.

        Cada trecho carrega um ``minterpolate`` inteiro, e a interpolação custa
        dezenas de vezes uma exportação normal. Esperar os sete outros
        terminarem por causa de um erro que já apareceu no primeiro segundo
        gastava a única vaga da fila local por dezenas de minutos, e a memória
        junto, para produzir um arquivo que não vai existir.
        """
        with self._lock:
            self._errors.append(detalhe)
        self._abort()

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise JobCancelled("Exportação cancelada.")

    # -- execução ---------------------------------------------------------

    def run(self) -> Path:
        self._destination.parent.mkdir(parents=True, exist_ok=True)
        # O trabalho acontece num diretório temporário próprio, e o destino só
        # recebe arquivo pronto: uma exportação interrompida no meio não pode
        # deixar meio arquivo com o nome do certo.
        #
        # O temporário fica **ao lado do destino**, e não no do sistema, por dois
        # motivos. Em muitas distribuições ``/tmp`` é tmpfs, ou seja memória: uma
        # exportação de vários GB passaria inteira pela RAM, que é exatamente o
        # recurso que esta aplicação já esgotou uma vez. E o destino pode estar
        # noutro disco — no Windows quase sempre está —, o que transformaria a
        # entrega final numa cópia do arquivo inteiro em vez de um rename.
        temp = Path(tempfile.mkdtemp(prefix=".videomanager-", dir=self._destination.parent))
        try:
            return self._build(temp)
        except Exception:
            self._outputs.abort(self._destination, lease=self._lease)
            raise
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def _build(self, temp: Path) -> Path:
        partes = [temp / f"trecho{i:03d}.{self._composition.container}" for i in
                  range(len(self._bounds))]
        threads = [
            threading.Thread(target=self._render, args=(i, parte), daemon=True)
            for i, parte in enumerate(partes)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # A falha vem **antes** da conferência de cancelamento: quem falha
        # derruba os irmãos, e ler o cancelamento primeiro faria toda falha de
        # trecho aparecer como "Cancelado", sem causa nenhuma na tela.
        if self._errors:
            raise ConversionError(Text("PARALLEL_SEGMENT_FAILED", detail=self._errors[0]))
        self._check_cancelled()
        faltando = [p for p in partes if not p.exists()]
        if faltando:
            raise ConversionError(Text("PARALLEL_SEGMENT_MISSING"))

        lista = temp / "trechos.txt"
        # **Só o nome do arquivo**, não o caminho inteiro. O demuxer resolve
        # nomes relativos a partir da pasta da lista, que é esta mesma, e assim a
        # sintaxe dele nunca encosta no caminho escolhido pelo usuário: uma pasta
        # chamada "vídeos do joão's" fazia a emenda falhar com "No such file or
        # directory", porque a aspa simples fecha a string do formato. Os nomes
        # aqui são gerados logo acima e não têm como conter nada disso.
        lista.write_text(
            "".join(f"file '{p.name}'\n" for p in partes), encoding="utf-8"
        )
        video = temp / f"video.{self._composition.container}"
        self._step(concat_args(lista, video, self._tools), Text("STEP_CONCAT"))
        # Os trechos já viraram um arquivo só: mantê-los até o fim dobraria o
        # espaço que a exportação ocupa no pico, sem servir para nada.
        for parte in partes:
            parte.unlink(missing_ok=True)

        # O som intermediário vai no **mesmo container** da saída, e não num
        # ".m4a" fixo: o codec é escolhido a partir do container (um .webm sai
        # em Opus), e Opus não cabe num .m4a. Com o nome fixo, exportar um
        # .webm interpolado falhava na hora de gerar o som — e só ele, porque o
        # caminho serial escreve tudo num arquivo só e nunca passa por aqui.
        som = temp / f"som.{self._composition.container}"
        args = audio_only_args(
            self._composition.project, som, self._tools,
            container=self._composition.container,
         text_assets=self._text_assets)
        if args is not None:
            self._step(args, Text("STEP_AUDIO"))
        else:
            som = None  # type: ignore[assignment]

        pronto = temp / f"pronto.{self._composition.container}"
        self._step(mux_args(video, som, pronto, self._tools), Text("STEP_MUX"))
        self._check_cancelled()
        if not self._composition.audio_only:
            embed_thumbnail(pronto, self._tools, control=self._postprocess)
        self._check_cancelled()
        # Publica sobre a reserva desta tarefa, no mesmo sistema de arquivos.
        # O lock ordena a entrega e o cancelamento; a porta confere a propriedade.
        self._emit(self._composition.output_duration, share=1.0)
        with self._lock:
            self._postprocess.check()
            self._outputs.commit(pronto, self._destination, lease=self._lease)
        try:
            os.utime(str(self._destination), None)
        except OSError:
            pass
        return self._destination

    def _render(self, index: int, destino: Path) -> None:
        """Um trecho, do começo ao fim, na própria thread."""
        at, span = self._bounds[index]
        if self._aborted:
            # Outro trecho já falhou (ou o usuário desistiu) antes desta thread
            # sair do lugar: não há por que abrir mais um ffmpeg.
            return
        try:
            args = segment_video_args(
                self._composition.project, at, span, destino, self._tools,
                container=self._composition.container,
                family=self._composition.family,
                hardware=self._composition.hardware,
                quality=self._composition.quality,
             text_assets=self._text_assets)
        except ConversionError as exc:
            self._fail(str(exc))
            return

        with filter_script(args, destino.parent) as prepared:
            self._render_command(index, prepared)

    def _render_command(self, index: int, args: list[str]) -> None:
        _, span = self._bounds[index]
        kwargs = subprocess_kwargs()
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        try:
            # UTF-8 explícito pelo mesmo motivo de ``Converter._execute_serial``:
            # em cp1252 a leitura do stderr morria e o trecho travava.
            process = subprocess.Popen(args, text=True, bufsize=1, encoding="utf-8",
                                       errors="replace", **kwargs)
        except OSError as exc:
            self._fail(str(exc))
            return

        with self._lock:
            self._processes[index] = process
        if self._aborted:
            # A desistência pode ter chegado entre o Popen e o registro; sem
            # esta conferência o processo ficaria rodando sozinho.
            terminate_async(process)

        cauda: deque[str] = deque(maxlen=20)
        drain = threading.Thread(
            target=self._drain, args=(process.stderr, cauda), daemon=True
        )
        drain.start()
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if self._aborted:
                    terminate_async(process)
                    break
                match = _PROGRESS_LINE.match(line.strip())
                if match and match.group(1) == "out_time_us":
                    valor = match.group(2).strip()
                    if valor.isdigit():
                        self._advance(index, min(span, int(valor) / 1_000_000))
            process.wait()
            drain.join(timeout=5)
        except Exception as exc:
            self._fail(str(exc))
        finally:
            terminate_and_wait(process)
            drain.join(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            with self._lock:
                self._processes.pop(index, None)

        # ``_aborted`` e não ``_cancelled``: um trecho que morreu porque outro
        # falhou também sai com código diferente de zero, e relatar isso
        # esconderia a causa de verdade atrás de um erro derivado.
        if process.returncode != 0 and not self._aborted:
            self._fail(_last_line(cauda))

    def _step(self, args: list[str], what: Text, *, timeout: int = _STEP_TIMEOUT) -> None:
        """Um passo curto e sem progresso — emendar, gerar som, juntar.

        Registrado na mesma lista dos trechos e com prazo, coisas que faltavam
        aqui e existiam lá. Sem o registro, ``cancel`` não alcançava estes
        processos: "Cancelar" durante "gerar o som" — que percorre a linha do
        tempo inteira — não fazia nada até a etapa acabar. E sem o prazo, um
        ffmpeg preso ocupava para sempre a **única** vaga da fila local
        (``_LOCAL_JOBS = 1``), travando toda conversão seguinte da sessão.
        """
        with filter_script(args) as prepared:
            self._step_command(prepared, what, timeout=timeout)

    def _step_command(self, args: list[str], what: Text, *, timeout: int) -> None:
        self._check_cancelled()
        try:
            proc = subprocess.Popen(args, **subprocess_kwargs())
        except OSError as exc:
            raise ConversionError(Text("STEP_START_FAILED", step=what, error=str(exc))) from exc

        with self._lock:
            self._processes[_STEP_SLOT] = proc
        if self._aborted:
            terminate_async(proc)
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise ConversionError(Text("STEP_TIMEOUT", minutes=timeout // 60, step=what)) from None
        finally:
            terminate_and_wait(proc)
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
            with self._lock:
                self._processes.pop(_STEP_SLOT, None)

        self._check_cancelled()
        if proc.returncode != 0:
            detalhe = (stderr or b"").decode("utf-8", "replace").strip()
            raise ConversionError(Text("STEP_FAILED", step=what, detail=detalhe[-300:]))

    # -- progresso --------------------------------------------------------

    def _advance(self, index: int, seconds: float) -> None:
        with self._lock:
            self._done[index] = seconds
            total = sum(self._done.values())
        self._emit(total)

    def _emit(self, seconds: float, share: float = _SEGMENTS_SHARE) -> None:
        if self._on_progress is None:
            return
        duracao = self._composition.output_duration
        percent = min(100.0, seconds * 100.0 * share / duracao) if duracao else None
        self._on_progress(
            Progress(
                phase=Text(_PHASE),
                percent=percent,
                downloaded_bytes=None,
                indeterminate=percent is None,
            )
        )

    @staticmethod
    def _drain(stream, into: deque[str]) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                texto = line.strip()
                if texto:
                    into.append(texto)
        except (OSError, ValueError):
            pass


# Palavras que marcam a linha onde o ffmpeg explica a falha. O resto da cauda é
# estatística de encerramento, que ele despeja mesmo quando morre.
_MARCAS_DE_ERRO = ("error", "invalid", "failed", "unable", "cannot", "not supported",
                   "no space", "killed", "out of memory")


def _last_line(cauda: deque[str]) -> str | Text:
    """A linha da cauda do stderr que explica a falha do trecho.

    A última linha nem sempre é a causa: um trecho que morreu sem mensagem
    final aparecia como "CPB properties: bitrate max/min/avg: 0/0/0", que não
    diz nada a quem lê. Sem nenhuma marca de erro, vão as duas últimas linhas
    com conteúdo — é pouco, mas é contexto de verdade.
    """
    for texto in reversed(cauda):
        if any(marca in texto.lower() for marca in _MARCAS_DE_ERRO):
            return texto
    uteis = [texto.strip() for texto in cauda if texto.strip()]
    return " | ".join(uteis[-2:]) if uteis else Text("PARALLEL_NO_DETAIL")

__all__ = [
    'FFmpegTools',
    'Composition',
    'Progress',
    'ConversionError',
    'JobCancelled',
]
