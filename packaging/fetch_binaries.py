"""Baixa ffmpeg/ffprobe para ``vendor/<plataforma>/`` antes de empacotar.

Rode antes do PyInstaller para que o executável já saia com os binários dentro e
funcione no primeiro clique, sem download na primeira execução:

    PYTHONPATH=src python packaging/fetch_binaries.py

Reaproveita :mod:`videomanager.infrastructure.system.binaries`, então a fonte e a validação são
exatamente as mesmas que a aplicação usa em tempo de execução — não há uma
segunda cópia dessa lógica para sair de sincronia.

Também baixa o Deno, que o yt-dlp usa para resolver os desafios JavaScript do
YouTube (sem ele parte dos formatos some). Diferente do ffmpeg, a aplicação não
o baixa em tempo de execução: ou vem no pacote, ou vale o Deno/Node do sistema.
``VM_BUNDLE_DENO=0`` dispensa o download.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from videomanager.infrastructure.system import binaries  # noqa: E402


# Versão fixa e conferida por SHA-256, como a publicação do ffmpeg: o binário
# vai dentro do pacote e roda com os privilégios do usuário. Os resumos são os
# que o GitHub publica para cada arquivo da versão.
DENO_VERSION = "v2.9.6"
_DENO_ARCHIVES = {
    "win64": ("deno-x86_64-pc-windows-msvc.zip",
              "15e5300b0ba3c3695a7621d90160a746ec9e710228cee639afa9d580f6e3cd11"),
    "linux64": ("deno-x86_64-unknown-linux-gnu.zip",
                "394f07f4da2bebe6ce6f1e7ce0fa16429b29b08c35e3fac3fe25972676dff4b2"),
    "linuxarm64": ("deno-aarch64-unknown-linux-gnu.zip",
                   "9a46afc6c392c7cd2ff71a31558935545b46408d0e87f7a86908c712721c046e"),
}
_DENO_BASE = f"https://github.com/denoland/deno/releases/download/{DENO_VERSION}/"


def fetch_deno(target: Path) -> Path | None:
    """Baixa, confere e extrai o Deno para ``target``. ``None`` se dispensado."""
    if os.environ.get("VM_BUNDLE_DENO", "1") == "0":
        print("Deno NÃO será embutido (VM_BUNDLE_DENO=0)")
        return None
    destination = target / binaries.exe_name("deno")
    if destination.is_file():
        print(f"Deno já presente em {destination}")
        return destination
    name, digest = _DENO_ARCHIVES[binaries.platform_key()]
    url = _DENO_BASE + name
    print(f"baixando {url}")
    request = Request(url, headers={"User-Agent": "VideoManager/instalador"})
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target) as temp:
        archive = Path(temp) / name
        sha = hashlib.sha256()
        with urlopen(request, timeout=60) as response, archive.open("wb") as handle:  # noqa: S310
            if urlparse(response.geturl()).scheme != "https":
                raise SystemExit("Download do Deno redirecionado para conexão sem criptografia.")
            while chunk := response.read(256 * 1024):
                handle.write(chunk)
                sha.update(chunk)
        if sha.hexdigest() != digest:
            raise SystemExit(f"SHA-256 do Deno não confere: {sha.hexdigest()}")
        with zipfile.ZipFile(archive) as zf:
            member = next(m for m in zf.infolist() if Path(m.filename).name == destination.name)
            with zf.open(member) as reader, destination.open("wb") as writer:
                shutil.copyfileobj(reader, writer)
    destination.chmod(0o755)
    print(f"  -> {destination}")
    return destination


def main() -> int:
    target = binaries.vendor_dir()
    fetch_deno(target)
    if binaries._look_in(target):  # noqa: SLF001 - script do próprio projeto
        print(f"já presentes em {target}")
        return 0

    print(f"baixando de {binaries.download_url()}")

    def progress(received: int, total: int | None) -> None:
        if total:
            print(f"\r  {received * 100 // total}%  {received / 1048576:.0f} MB", end="", flush=True)

    tools = binaries.download_tools(progress)
    print()

    # download_tools grava no diretório gerenciado; para empacotar, os binários
    # precisam estar em vendor/, que o PyInstaller inclui.
    target.mkdir(parents=True, exist_ok=True)
    for source in (tools.ffmpeg, tools.ffprobe):
        destination = target / source.name
        shutil.copy2(source, destination)
        destination.chmod(0o755)
        print(f"  -> {destination}")

    print(binaries.probe_version(target / tools.ffmpeg.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
