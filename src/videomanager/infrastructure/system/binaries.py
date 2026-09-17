"""Localização e provisionamento dos binários externos (ffmpeg e ffprobe).

Ordem de resolução, da mais específica para a mais genérica:

1. ``vendor/<plataforma>/`` — binários empacotados junto do executável
2. diretório de dados do app — binários baixados numa execução anterior
3. ``PATH`` do sistema
4. download sob demanda (só acontece com confirmação da interface)

O PATH do sistema vem antes do download de propósito: quem já tem ffmpeg
instalado (``apt install ffmpeg``) nunca paga um download de ~130 MB.

Este módulo também concentra a execução de processos externos, porque no Windows
todo ``subprocess`` precisa de ``CREATE_NO_WINDOW`` — sem isso, cada chamada ao
ffmpeg pisca um console preto na frente da janela.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from platformdirs import user_data_dir

from videomanager import APP_NAME
from videomanager.application.errors import BinaryDownloadError
from videomanager.application.errors import BinaryNotFoundError
from videomanager.application.errors import JobCancelled

from videomanager.application.capabilities import FFmpegTools as FFmpegTools

# Builds estáticas do BtbN. Usamos a variante GPL porque é a única que inclui
# libx264/libx265 e libmp3lame — sem elas não há como recodificar para H.264
# nem para MP3, que são justamente os alvos mais pedidos.
#
# **Ramo estável (n7.1), e não o master.** As builds de master acompanham o
# ffmpeg em desenvolvimento e são ligadas aos cabeçalhos de codec mais recentes
# da NVIDIA: a de agosto/2026 exige a API NVENC 13.1, que só existe em drivers
# 610 ou mais novos. O resultado é uma placa perfeitamente capaz recusando
# codificar — medido aqui com um driver 580, que é a série corrente:
#
#     "Driver does not support the required nvenc API version.
#      Required: 13.1  Found: 13.0"
#
# A build estável, com o mesmo driver, codifica sem reclamar. Empacotar o ramo
# de desenvolvimento troca estabilidade por novidades que este aplicativo não
# usa, e cobra isso justamente de quem tem placa de vídeo.
_ARCHIVES: dict[str, str] = {
    "linux64": "ffmpeg-n7.1.5-12-g1fdbca85aa-linux64-gpl-7.1.tar.xz",
    "linuxarm64": "ffmpeg-n7.1.5-12-g1fdbca85aa-linuxarm64-gpl-7.1.tar.xz",
    "win64": "ffmpeg-n7.1.5-12-g1fdbca85aa-win64-gpl-7.1.zip",
}
# O fornecedor retirou 7.1 do latest. Uma publicação mensal fixa mantém o
# provisionamento e a compatibilidade de drivers testada. Atualizações desta
# versão exigem validar novamente encoders, filtros e empacotamento.
_RELEASE_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/"

# Progresso do download: (bytes recebidos, total ou None se desconhecido).
ProgressCb = Callable[[int, int | None], None]
# Consultado durante o download; ``True`` interrompe.
CancelCheck = Callable[[], bool]

_CREATE_NO_WINDOW = 0x08000000


def is_windows() -> bool:
    return os.name == "nt"


def platform_key() -> str:
    """Identifica a plataforma no formato usado pelos nomes dos arquivos."""
    if is_windows():
        return "win64"
    machine = os.uname().machine.lower()
    if machine in ("aarch64", "arm64"):
        return "linuxarm64"
    return "linux64"


def exe_name(stem: str) -> str:
    return f"{stem}.exe" if is_windows() else stem


# Variáveis de caminho de biblioteca que o bootloader do PyInstaller reescreve.
# Ver :func:`clean_env`.
_LIBRARY_PATH_VARS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LIBPATH", "SHLIB_PATH")


def clean_env() -> dict[str, str]:
    """Ambiente do processo, **sem** o caminho de bibliotecas do empacotador.

    O bootloader do PyInstaller aponta ``LD_LIBRARY_PATH`` para a pasta interna
    do pacote, e todo processo filho herda isso. O ``AppRun`` do AppImage evita
    exportar a variável justamente por isso, mas não adianta: quem a define é o
    bootloader, depois dele.

    O estrago é concreto, porque a pasta interna traz a ``libavcodec`` do
    QtMultimedia — mesmo ``SONAME`` da do ffmpeg. Um ffmpeg ligado
    dinamicamente (o do sistema, ou uma build *shared*) carrega a biblioteca do
    Qt em vez da própria e **perde os codecs que ela não tem**. Medido nesta
    máquina: de 230 encoders para 190, sem ``libx264``, ``libx265`` nem
    ``libmp3lame`` — exatamente os três que fazem esta aplicação escolher a
    variante GPL. E não falha de forma visível: o ``-encoders`` some com eles
    enquanto o banner de configuração, que é compilado dentro do executável e
    não da biblioteca, continua anunciando que os tem.

    Quando havia um valor antes do empacotamento, o bootloader o guarda em
    ``*_ORIG`` e é ele que vale; quando não havia, a variável simplesmente não
    deve existir para o filho.
    """
    env = dict(os.environ)
    for var in _LIBRARY_PATH_VARS:
        original = env.pop(f"{var}_ORIG", None)
        if original:
            env[var] = original
        else:
            env.pop(var, None)
    return env


def subprocess_kwargs() -> dict:
    """Argumentos padrão para todo processo externo que a aplicação inicia.

    ``stdin=DEVNULL`` é essencial para o ffmpeg: se ele herdar o stdin do
    processo pai, consome a entrada e pode travar. ``CREATE_NO_WINDOW`` evita a
    janela de console piscando no Windows. O ambiente vai limpo do caminho de
    bibliotecas do empacotador (ver :func:`clean_env`).
    """
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": clean_env(),
    }
    if is_windows():
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def lower_priority(process: subprocess.Popen) -> None:
    """Rebaixa um processo de fundo para não disputar CPU com a interface.

    Serve ao preenchimento do cache da agulha: ele pode rodar por minutos, e
    quem está editando ou tocando a prévia vem primeiro. Falhar aqui não é
    motivo para interromper o trabalho.
    """
    try:
        if is_windows():
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, process.pid)  # SET_INFORMATION
            if handle:
                ctypes.windll.kernel32.SetPriorityClass(handle, _BELOW_NORMAL_PRIORITY_CLASS)
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.setpriority(os.PRIO_PROCESS, process.pid, 10)
    except (OSError, AttributeError):
        pass


# Teto de threads de decodificação para o que serve à **prévia**. O padrão do
# ffmpeg é uma thread por núcleo, e numa máquina de vinte núcleos montar vinte
# threads para devolver um quadro custa mais do que decodificá-lo. Medido, dez
# quadros isolados: 1,00 s e 3,34 s de CPU no padrão contra 0,77 s e 2,58 s com
# oito — mais rápido **e** com menos CPU, que é o que sobra para a exportação
# que estiver correndo ao lado. Oito é o melhor ou empatado em cinco dos seis
# casos medidos (h264 e HEVC, 1080p e 4K, quadro isolado e tira); só a tira de
# HEVC 4K perde 6% de tempo, em troca de 39% menos CPU.
#
# Não vale para a exportação: lá o que se quer é o arquivo pronto antes, e todo
# núcleo é bem-vindo.
_MAX_DECODE_THREADS = 8


def decode_threads() -> int:
    """Quantas threads a decodificação da prévia pode usar."""
    return max(1, min(_MAX_DECODE_THREADS, os.cpu_count() or _MAX_DECODE_THREADS))


def decode_thread_args() -> list[str]:
    """O limite acima, na forma de argumento — vai **antes** de cada ``-i``.

    A posição não é detalhe: ``-threads`` é opção de entrada, e depois do ``-i``
    ele valeria para o codificador da saída, que aqui nem existe.
    """
    return ["-threads", str(decode_threads())]


def vendor_dir() -> Path:
    """Pasta de binários empacotados, ao lado do executável ou do código."""
    base = getattr(sys, "_MEIPASS", None)  # definido pelo PyInstaller
    if base:
        return Path(base) / "vendor" / platform_key()
    # src/videomanager/infrastructure/system/binaries.py -> raiz do repositório
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "vendor" / platform_key()


def managed_dir() -> Path:
    """Pasta onde guardamos os binários que nós mesmos baixamos."""
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "bin"


def _usable(path: Path | None) -> bool:
    return bool(path) and path.is_file() and os.access(path, os.X_OK)


def _look_in(directory: Path) -> tuple[Path, Path] | None:
    ffmpeg = directory / exe_name("ffmpeg")
    ffprobe = directory / exe_name("ffprobe")
    if _usable(ffmpeg) and _usable(ffprobe):
        return ffmpeg, ffprobe
    return None


def _look_in_path() -> tuple[Path, Path] | None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return Path(ffmpeg), Path(ffprobe)
    return None


def find_tools() -> FFmpegTools | None:
    """Procura o par ffmpeg/ffprobe sem baixar nada. ``None`` se não achar."""
    for directory, origin in ((vendor_dir(), "empacotado"), (managed_dir(), "gerenciado")):
        found = _look_in(directory)
        if found:
            return FFmpegTools(found[0], found[1], origin)

    found = _look_in_path()
    if found:
        return FFmpegTools(found[0], found[1], "sistema")
    return None


def find_js_runtime() -> tuple[str, Path] | None:
    """Runtime JavaScript para o yt-dlp resolver os desafios do YouTube.

    Sem um, o yt-dlp cai num cliente sem JavaScript e parte dos formatos some.
    O Deno empacotado vem primeiro, pelo mesmo motivo do ffmpeg: o pacote tem de
    funcionar num computador sem nada instalado. Depois valem Deno e Node do
    ``PATH`` — o yt-dlp só habilita o Deno sozinho, então o Node instalado era
    ignorado mesmo estando ali.
    """
    bundled = vendor_dir() / exe_name("deno")
    if _usable(bundled):
        return "deno", bundled
    for name in ("deno", "node"):
        found = shutil.which(name)
        if found:
            return name, Path(found)
    return None


def probe_version(ffmpeg: Path) -> str:
    """Executa ``ffmpeg -version`` e devolve a primeira linha.

    Serve como validação real: um arquivo pode existir e ter permissão de
    execução mas estar truncado ou ser de outra arquitetura.
    """
    try:
        proc = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-version"],
            timeout=20,
            check=False,
            **subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BinaryNotFoundError(f"Não foi possível executar o ffmpeg: {exc}") from exc

    if proc.returncode != 0:
        raise BinaryNotFoundError(
            "O ffmpeg encontrado não executou corretamente "
            f"(código {proc.returncode}). O arquivo pode estar corrompido."
        )
    first_line = (proc.stdout or b"").decode("utf-8", "replace").splitlines()
    return first_line[0].strip() if first_line else "ffmpeg (versão desconhecida)"


def download_url() -> str:
    key = platform_key()
    try:
        return _RELEASE_BASE + _ARCHIVES[key]
    except KeyError:
        raise BinaryDownloadError(
            f"Não há build automática de ffmpeg para esta plataforma ({key}). "
            "Instale o ffmpeg manualmente e ele será detectado no PATH."
        ) from None


def _stream_download(
    url: str,
    dest: Path,
    progress: ProgressCb | None,
    cancelled: CancelCheck | None = None,
) -> None:
    request = Request(url, headers={"User-Agent": f"{APP_NAME}/instalador"})
    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310 - URL fixa e https
            # O urllib segue redirecionamento em silêncio, **inclusive de https
            # para http**. Como o que vem por aqui é um executável de 130 MB que
            # a aplicação vai rodar, a conferência é no endereço final e não no
            # pedido: sem ela, quem estiver no meio do caminho decide o que é
            # instalado.
            if urlparse(response.geturl()).scheme != "https":
                raise BinaryDownloadError(
                    "O download do ffmpeg foi redirecionado para uma conexão "
                    "sem criptografia e foi interrompido."
                )
            raw_length = response.headers.get("Content-Length")
            total = int(raw_length) if raw_length and raw_length.isdigit() else None
            received = 0
            with dest.open("wb") as handle:
                while True:
                    # Verificado a cada pedaço: são 130 MB, e quem desiste
                    # espera que desistir tenha efeito imediato.
                    if cancelled and cancelled():
                        raise JobCancelled("Download do ffmpeg cancelado.")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
    except URLError as exc:
        raise BinaryDownloadError(
            f"Falha ao baixar o ffmpeg: {exc.reason}. Verifique a conexão."
        ) from exc
    except OSError as exc:
        raise BinaryDownloadError(f"Falha ao gravar o download do ffmpeg: {exc}") from exc


def _extract_wanted(archive: Path, target_dir: Path) -> None:
    """Extrai apenas ffmpeg e ffprobe de dentro do arquivo baixado.

    Os binários vivem em ``<pasta-raiz>/bin/`` dentro do arquivo, então casamos
    pelo nome final do caminho em vez de assumir o nome da pasta raiz — que
    carrega a data da build e muda a cada release.
    """
    wanted = {exe_name("ffmpeg"), exe_name("ffprobe")}
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted: set[str] = set()

    def write_member(name: str, reader) -> None:
        out = target_dir / name
        with out.open("wb") as handle:
            shutil.copyfileobj(reader, handle)
        out.chmod(0o755)
        extracted.add(name)

    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    base = Path(member.filename).name
                    if base in wanted and not member.is_dir():
                        with zf.open(member) as reader:
                            write_member(base, reader)
        else:
            with tarfile.open(archive, "r:xz") as tf:
                for member in tf.getmembers():
                    base = Path(member.name).name
                    if base in wanted and member.isfile():
                        reader = tf.extractfile(member)
                        if reader is not None:
                            with reader:
                                write_member(base, reader)
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise BinaryDownloadError(
            f"O arquivo do ffmpeg baixado parece corrompido: {exc}"
        ) from exc

    missing = wanted - extracted
    if missing:
        raise BinaryDownloadError(
            "O arquivo baixado não continha: " + ", ".join(sorted(missing))
        )


def download_tools(
    progress: ProgressCb | None = None, cancelled: CancelCheck | None = None
) -> FFmpegTools:
    """Baixa e instala ffmpeg/ffprobe no diretório gerenciado.

    Usa a publicação fixa declarada acima, exige HTTPS também após os
    redirecionamentos e executa ``ffmpeg -version`` ao final. Esse diagnóstico
    detecta executável truncado ou arquitetura incompatível. A publicação e
    os nomes dos assets são cobertos por verificação de rede opt-in.
    """
    url = download_url()
    target = managed_dir()
    target.mkdir(parents=True, exist_ok=True)
    # Nome único, e não "download.tar.xz": duas janelas abertas ao mesmo tempo
    # escreviam no mesmo arquivo, e a que terminasse primeiro extraía o que a
    # outra ainda estava baixando.
    handle, raw = tempfile.mkstemp(
        dir=target, prefix="download-", suffix=".zip" if url.endswith(".zip") else ".tar.xz"
    )
    os.close(handle)
    archive = Path(raw)

    try:
        _stream_download(url, archive, progress, cancelled)
        _extract_wanted(archive, target)
    finally:
        archive.unlink(missing_ok=True)

    found = _look_in(target)
    if not found:
        raise BinaryDownloadError(
            "Os binários foram extraídos mas não ficaram utilizáveis em "
            f"{target}. Verifique as permissões da pasta."
        )
    probe_version(found[0])  # valida de verdade; levanta se não executar
    return FFmpegTools(found[0], found[1], "gerenciado")


def resolve(progress: ProgressCb | None = None, *, allow_download: bool = False) -> FFmpegTools:
    """Devolve um par ffmpeg/ffprobe pronto, baixando se autorizado.

    A interface chama primeiro com ``allow_download=False`` para descobrir se
    precisa perguntar algo ao usuário; depois de confirmado, chama de novo com
    ``allow_download=True``.
    """
    tools = find_tools()
    if tools:
        return tools
    if not allow_download:
        raise BinaryNotFoundError(
            "ffmpeg e ffprobe não foram encontrados. Eles são necessários para "
            "juntar vídeo com áudio e para converter arquivos."
        )
    return download_tools(progress)

__all__ = [
    'BinaryDownloadError',
    'BinaryNotFoundError',
    'JobCancelled',
    'FFmpegTools',
]
