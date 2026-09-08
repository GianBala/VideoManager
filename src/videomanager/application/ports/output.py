"""Propriedade de um nome reservado; dados sem operações de sistema de arquivos."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutputLease:
    path: Path
    device: int
    inode: int
