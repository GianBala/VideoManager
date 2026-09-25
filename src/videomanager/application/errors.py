"""Exceções do domínio da aplicação.

A mensagem de qualquer subclasse de :class:`VideoManagerError` é considerada
apresentável ao usuário: vem de um catálogo de textos, sem jargão de stack
trace. A camada de UI mostra a mensagem diretamente, então mensagens vagas como
"erro inesperado" não servem — diga o que falhou e, quando possível, o que fazer.
"""

from __future__ import annotations

from videomanager.domain.i18n import Text


def error_message(exc: BaseException) -> str | Text:
    """A mensagem de ``exc`` como foi escrita.

    Um ``Text`` continua ``Text``: a mensagem de erro fica na fila e precisa
    acompanhar a troca de idioma, o que ``str(exc)`` congelaria.
    """
    if len(exc.args) == 1 and isinstance(exc.args[0], Text):
        return exc.args[0]
    return str(exc)


class VideoManagerError(Exception):
    """Base de todos os erros previstos da aplicação."""


# --- binários externos -------------------------------------------------------

class BinaryNotFoundError(VideoManagerError):
    """ffmpeg ou ffprobe não foi encontrado em nenhum local conhecido."""


class BinaryDownloadError(VideoManagerError):
    """Falha ao baixar ou extrair os binários do ffmpeg."""


# --- análise de URL ----------------------------------------------------------

class ProbeError(VideoManagerError):
    """Falha ao analisar uma URL."""


class UnsupportedUrlError(ProbeError):
    """Nenhum extrator do yt-dlp reconhece esta URL."""


class DrmProtectedError(ProbeError):
    """A mídia é protegida por DRM e não pode ser baixada."""


class NoFormatsError(ProbeError):
    """A URL foi reconhecida, mas nenhum formato utilizável foi oferecido."""


# --- download e conversão ----------------------------------------------------

class DownloadFailedError(VideoManagerError):
    """O download falhou por um motivo já traduzido para o usuário."""


class ConversionError(VideoManagerError):
    """O ffmpeg terminou com erro durante uma conversão."""


class JobCancelled(VideoManagerError):
    """O usuário cancelou a tarefa.

    Não é uma falha: a UI trata este caso como estado ``cancelado``, sem
    diálogo de erro.
    """


# --- edição e projeto --------------------------------------------------------

class ProjectError(VideoManagerError):
    """Falha ao carregar ou salvar arquivo de projeto de edição."""

