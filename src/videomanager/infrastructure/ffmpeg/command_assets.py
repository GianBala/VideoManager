"""Artefatos temporários exclusivos de uma execução de comando."""
from contextlib import contextmanager
from pathlib import Path
import os
import tempfile


@contextmanager
def filter_script(args: list[str], directory: Path | None = None):
    """Externaliza grafos longos; o arquivo vive até o processo consumidor sair."""
    owned = []
    prepared = list(args)
    try:
        for index, arg in enumerate(args[:-1]):
            if arg != '-filter_complex' or len(args[index + 1]) <= 4000:
                continue
            descriptor, name = tempfile.mkstemp(prefix='.videomanager-filter-', suffix='.txt', dir=directory)
            path = Path(name)
            owned.append(path)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(args[index + 1])
            prepared[index:index + 2] = ['-filter_complex_script', str(path)]
        yield prepared
    finally:
        for path in owned:
            path.unlink(missing_ok=True)
