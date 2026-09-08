"""Inspeção local e acesso ao sistema de arquivos exigidos pela preparação."""
import os
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.application.errors import BinaryNotFoundError


class FFmpegCatalog:
    def __init__(self, tools_provider=find_tools):
        self.tools_provider = tools_provider

    def exists(self, path):
        return path.is_file()

    def writable(self, directory):
        return os.access(directory, os.W_OK)

    def inspect(self, path):
        tools = self.tools_provider()
        if tools is None:
            raise BinaryNotFoundError('FFmpeg não disponível.')
        return probe_file(path, tools)

__all__ = [
    'BinaryNotFoundError',
]
