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
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from platformdirs import user_data_dir

from .. import APP_NAME
from .errors import BinaryDownloadError, BinaryNotFoundError, JobCancelled

# Builds estáticas do BtbN. Usamos a variante GPL porque é a única que inclui
# libx264/libx265 e libmp3lame — sem elas não há como recodificar para H.264
# nem para MP3, que são justamente os alvos mais pedidos.
_ARCHIVES: dict[str, str] = {
    "linux64": "ffmpeg-master-latest-linux64-gpl.tar.xz",
    "linuxarm64": "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
    "win64": "ffmpeg-master-latest-win64-gpl.zip",
}
_RELEASE_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"

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


def subprocess_kwargs() -> dict:
    """Argumentos padrão para todo processo externo que a aplicação inicia.

    ``stdin=DEVNULL`` é essencial para o ffmpeg: se ele herdar o stdin do
    processo pai, consome a entrada e pode travar. ``CREATE_NO_WINDOW`` evita a
    janela de console piscando no Windows.
    """
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if is_windows():
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


def vendor_dir() -> Path:
    """Pasta de binários empacotados, ao lado do executável ou do código."""
    base = getattr(sys, "_MEIPASS", None)  # definido pelo PyInstaller
    if base:
        return Path(base) / "vendor" / platform_key()
    # src/videomanager/core/binaries.py -> raiz do repositório
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "vendor" / platform_key()


def managed_dir() -> Path:
    """Pasta onde guardamos os binários que nós mesmos baixamos."""
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "bin"


@dataclass(frozen=True)
class FFmpegTools:
    """Par ffmpeg/ffprobe validado e pronto para uso."""

    ffmpeg: Path
    ffprobe: Path
    source: str  # "empacotado" | "gerenciado" | "sistema" — para exibir na UI

    @property
    def ffmpeg_str(self) -> str:
        return str(self.ffmpeg)

    @property
    def ffprobe_str(self) -> str:
        return str(self.ffprobe)


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

    Não há verificação por hash fixo porque a tag ``latest`` do BtbN é um alvo
    móvel: qualquer hash embutido aqui quebraria na próxima build publicada. A
    integridade é garantida pelo HTTPS e, principalmente, por executar
    ``ffmpeg -version`` no fim — que detecta download truncado ou arquitetura
    errada, coisas que um hash desatualizado não detectaria.
    """
    url = download_url()
    target = managed_dir()
    target.mkdir(parents=True, exist_ok=True)
    archive = target / f"download{'.zip' if url.endswith('.zip') else '.tar.xz'}"

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
