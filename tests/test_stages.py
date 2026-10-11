"""Vários comandos em sequência que, para quem lê, são um cano só.

O bloco invertido da prévia é lido em janelas, uma por processo (ver
``domain.reversal``), e quem lê quadros ou som não pode perceber as emendas. Os
estágios aqui são fontes sintéticas do próprio ffmpeg, cada uma de uma cor, o que
deixa a ordem e a contagem conferíveis byte a byte.
"""

import subprocess
import time

import pytest

from videomanager.infrastructure.ffmpeg.command_assets import filter_script
from videomanager.infrastructure.ffmpeg.stages import Stages, StagedProcess, open_process
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

pytestmark = pytest.mark.ffmpeg
LADO = 16
QUADRO = LADO * LADO * 3


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _estagio(tools, cor, quadros):
    return (tools.ffmpeg_str, "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"color=c={cor}:s={LADO}x{LADO}:r=30",
            "-frames:v", str(quadros), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")


def _abrir(estagios):
    return open_process(estagios, **subprocess_kwargs())


def _quadros(processo):
    cores = []
    while True:
        dados = processo.stdout.read(QUADRO)
        if len(dados) < QUADRO:
            return cores, dados
        cores.append(tuple(dados[:3]))


def test_a_leitura_atravessa_as_emendas_na_ordem(tools):
    estagios = Stages((_estagio(tools, "red", 10), _estagio(tools, "lime", 5), _estagio(tools, "blue", 7)),
                      (10 * QUADRO, 5 * QUADRO, 7 * QUADRO))
    processo = _abrir(estagios)
    cores, resto = _quadros(processo)
    processo.wait(timeout=10)
    assert len(cores) == 22 and resto == b""
    assert cores[0][0] > 200 and cores[9][0] > 200            # vermelho
    assert cores[10][1] > 200 and cores[14][1] > 200          # verde
    assert cores[15][2] > 200 and cores[21][2] > 200          # azul
    assert processo.returncode == 0 and processo.poll() == 0


def test_uma_leitura_maior_que_o_estagio_continua_no_seguinte(tools):
    """O leitor pede um quadro por vez, mas o cano de áudio pede pedaços de tamanho qualquer."""
    processo = _abrir(Stages((_estagio(tools, "red", 3), _estagio(tools, "blue", 3))))
    dados = processo.stdout.read(-1)
    processo.wait(timeout=10)
    assert len(dados) == 6 * QUADRO


def test_o_estagio_seguinte_so_abre_depois_da_metade_do_atual(tools):
    """Uma prévia pausada, com o primeiro quadro lido, não pode ter duas janelas na memória."""
    processo = _abrir(Stages((_estagio(tools, "red", 40), _estagio(tools, "lime", 40)), (40 * QUADRO, 40 * QUADRO)))
    abertos = []
    for _ in range(40):
        processo.stdout.read(QUADRO)
        abertos.append(len(processo._procs))
    assert set(abertos[:19]) == {1}
    assert set(abertos[19:]) == {2}
    processo.terminate()
    processo.stdout.close()
    processo.wait(timeout=10)


def test_sem_o_tamanho_o_seguinte_abre_ao_primeiro_byte(tools):
    processo = _abrir(Stages((_estagio(tools, "red", 20), _estagio(tools, "lime", 20))))
    processo.stdout.read(QUADRO)
    assert len(processo._procs) == 2
    processo.terminate()
    processo.stdout.close()
    processo.wait(timeout=10)


def test_falha_no_meio_encerra_o_fluxo_com_o_codigo_e_a_causa(tools):
    ruim = (tools.ffmpeg_str, "-nostdin", "-v", "error", "-i", "/nao/existe.mp4", "-f", "rawvideo", "pipe:1")
    processo = _abrir(Stages((_estagio(tools, "red", 4), ruim, _estagio(tools, "blue", 4)),
                             (4 * QUADRO, None, 4 * QUADRO)))
    cores, _ = _quadros(processo)
    processo.wait(timeout=10)
    assert len(cores) == 4                     # o que veio antes da falha chegou
    assert processo.returncode not in (None, 0)
    assert b"Error opening input" in processo.stderr.read(4096)
    assert len(processo._procs) <= 2           # e o terceiro nunca abriu


def test_terminar_derruba_todos_os_estagios_abertos(tools):
    processo = _abrir(Stages((_estagio(tools, "red", 300), _estagio(tools, "lime", 300)),
                             (300 * QUADRO, 300 * QUADRO)))
    processo.stdout.read(QUADRO * 200)
    assert len(processo._procs) == 2
    processo.terminate()
    processo.stdout.close()
    processo.wait(timeout=10)
    assert all(p.poll() is not None for p in processo._procs)
    assert processo.returncode == -15
    assert processo.stdout.read(QUADRO) == b""     # depois de terminado não lê mais nada


def test_comando_unico_continua_sendo_um_popen(tools):
    processo = open_process(list(_estagio(tools, "red", 2)), **subprocess_kwargs())
    assert isinstance(processo, subprocess.Popen)
    processo.communicate()


def test_estagios_vazios_sao_recusados():
    with pytest.raises(ValueError):
        Stages(())


def test_filter_script_prepara_cada_estagio_e_os_arquivos_vivem_ate_o_fim(tools, tmp_path):
    longo = "color=c=black:s=16x16:r=30," + ",".join(["null"] * 1500)
    estagio = (tools.ffmpeg_str, "-nostdin", "-v", "error", "-filter_complex", f"{longo}[o]", "-map", "[o]",
               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
    with filter_script(Stages((estagio, estagio), (QUADRO, None))) as pronto:
        assert isinstance(pronto, Stages) and len(pronto.commands) == 2
        assert all("-filter_complex" not in comando for comando in pronto.commands)   # foi para arquivo
        arquivos = [comando[comando.index(next(a for a in comando if a.startswith("-") and "filter" in a)) + 1]
                    for comando in pronto.commands]
        processo = _abrir(pronto)
        dados = processo.stdout.read(-1)
        processo.wait(timeout=20)
        assert len(dados) == 2 * QUADRO and processo.returncode == 0
    from pathlib import Path
    assert not any(Path(a).exists() for a in arquivos)   # e saíram junto, ao fim do conjunto


def test_leitor_bloqueado_nao_trava_o_encerramento(tools):
    """O ffmpeg bloqueado num cano cheio não atende ao SIGTERM: fechar o cano o libera."""
    processo = _abrir(Stages((_estagio(tools, "red", 100_000),)))
    processo.stdout.read(QUADRO)
    inicio = time.time()
    processo.terminate()
    processo.stdout.close()
    processo.wait(timeout=10)
    assert time.time() - inicio < 5
    assert isinstance(processo, StagedProcess)
