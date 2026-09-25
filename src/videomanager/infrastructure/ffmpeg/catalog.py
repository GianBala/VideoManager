"""Inspeção local e acesso ao sistema de arquivos exigidos pela preparação."""
import os
import tempfile
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.application.errors import BinaryNotFoundError
from videomanager.domain.i18n import Text


class FFmpegCatalog:
    def __init__(self, tools_provider=find_tools):
        self.tools_provider = tools_provider

    def exists(self, path):
        return path.is_file()

    def writable(self, directory):
        """Se dá para criar arquivo na pasta — tentando, e não perguntando.

        No Windows ``os.access`` só olha o atributo somente-leitura: ACL, UAC e
        o Acesso controlado a pastas do Defender passavam, e a conversão falhava
        depois ao criar a saída, em vez de usar a pasta de downloads.
        """
        if not os.access(directory, os.W_OK):
            return False
        try:
            with tempfile.TemporaryFile(dir=directory):
                return True
        except OSError:
            return False

    def inspect(self, path):
        tools = self.tools_provider()
        if tools is None:
            raise BinaryNotFoundError(Text('FFMPEG_UNAVAILABLE'))
        return probe_file(path, tools)

__all__ = [
    'BinaryNotFoundError',
]
