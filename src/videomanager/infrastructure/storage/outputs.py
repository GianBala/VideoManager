"""Reservas com propriedade explícita e publicação atômica no mesmo volume."""
from pathlib import Path
from videomanager.application.errors import ConversionError
from videomanager.application.ports.output import OutputLease
from .output_paths import output_path


class FileOutputStore:
    def reserve(self, source, target, directory=None, suffix='', custom_stem=None):
        path = output_path(source, target, directory, suffix, custom_stem)
        info = path.stat()
        return OutputLease(path, info.st_dev, info.st_ino)

    def owns(
        self,
        destination: Path,
        lease: OutputLease | None,
    ):
        try:
            info = destination.stat()
        except FileNotFoundError:
            return lease is None
        return info.st_size == 0 and (lease is None or (
            destination == lease.path and (info.st_dev, info.st_ino) == (lease.device, lease.inode)))

    def abort(
        self,
        destination: Path,
        *,
        lease: OutputLease | None = None,
    ):
        try:
            if self.owns(destination, lease):
                destination.unlink(missing_ok=True)
        except OSError:
            # A falha de limpeza não deve substituir o erro original da tarefa.
            pass

    def commit(
        self,
        temporary: Path,
        destination: Path,
        *,
        lease: OutputLease | None = None,
    ):
        if not self.owns(destination, lease):
            raise ConversionError('O destino reservado foi alterado por outra operação.')
        temporary.replace(destination)
