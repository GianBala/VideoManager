"""Artefatos temporários exclusivos de uma execução de comando."""
from contextlib import contextmanager
from pathlib import Path
import os
import tempfile

from videomanager.infrastructure.system.binaries import major_version

# Como pedir ao ffmpeg que leia o grafo de um arquivo. A opção antiga saiu no
# ffmpeg 8; a forma nova — a genérica "o valor desta opção vem deste arquivo" —
# entrou no 7. Nenhuma das duas serve sozinha: o Ubuntu 24.04 traz o ffmpeg 6.1,
# que só tem a antiga, e o Chocolatey já instala o 9, que só tem a nova.
_SCRIPT_OPTION_OLD = '-filter_complex_script'
_SCRIPT_OPTION_NEW = '-/filter_complex'
_FIRST_VERSION_WITH_NEW = 7
# Grafo acima disto vai para arquivo. A linha de comando do Windows termina em
# 32 KB, e um projeto grande passa disso com folga.
_INLINE_LIMIT = 4000

_script_options: dict[str, str] = {}


def script_option(ffmpeg: str) -> str:
    """Opção de grafo-em-arquivo aceita por **este** ffmpeg, lembrada depois.

    A versão é lida do próprio executável porque a máquina do usuário decide:
    o pacote traz o seu, mas no Linux vale o que estiver instalado. Sem
    conseguir ler a versão, fica a opção antiga — é o que funciona nas versões
    que ainda circulam em distribuições de longo suporte.
    """
    cached = _script_options.get(ffmpeg)
    if cached is not None:
        return cached
    major = major_version(ffmpeg)
    option = _SCRIPT_OPTION_NEW if major and major >= _FIRST_VERSION_WITH_NEW else _SCRIPT_OPTION_OLD
    _script_options[ffmpeg] = option
    return option


@contextmanager
def filter_script(args: list[str], directory: Path | None = None):
    """Externaliza grafos longos; o arquivo vive até o processo consumidor sair."""
    owned = []
    prepared = list(args)
    option = None
    try:
        for index, arg in enumerate(args[:-1]):
            if arg != '-filter_complex' or len(args[index + 1]) <= _INLINE_LIMIT:
                continue
            if option is None:
                option = script_option(args[0])
            descriptor, name = tempfile.mkstemp(prefix='.videomanager-filter-', suffix='.txt', dir=directory)
            path = Path(name)
            owned.append(path)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(args[index + 1])
            prepared[index:index + 2] = [option, str(path)]
        yield prepared
    finally:
        for path in owned:
            path.unlink(missing_ok=True)
