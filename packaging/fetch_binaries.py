"""Baixa ffmpeg/ffprobe para ``vendor/<plataforma>/`` antes de empacotar.

Rode antes do PyInstaller para que o executável já saia com os binários dentro e
funcione no primeiro clique, sem download na primeira execução:

    PYTHONPATH=src python packaging/fetch_binaries.py

Reaproveita :mod:`videomanager.core.binaries`, então a fonte e a validação são
exatamente as mesmas que a aplicação usa em tempo de execução — não há uma
segunda cópia dessa lógica para sair de sincronia.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from videomanager.core import binaries  # noqa: E402


def main() -> int:
    target = binaries.vendor_dir()
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
