"""Reservas com propriedade explícita e publicação atômica no mesmo volume."""
import time
from pathlib import Path
from videomanager.application.errors import ConversionError
from videomanager.domain.i18n import Text
from videomanager.application.ports.output import OutputLease
from .output_paths import output_path


_REPLACE_ATTEMPTS = 6
_REPLACE_WAIT = 0.25


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
            raise ConversionError(Text('OUTPUT_LEASE_CHANGED'))
        # Antivírus, indexador e OneDrive abrem o arquivo recém-criado por um
        # instante; no Windows a troca falha com "arquivo em uso" (WinError 32)
        # e a conversão inteira terminava em erro. Algumas tentativas curtas
        # resolvem sem mascarar um bloqueio de verdade.
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                temporary.replace(destination)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_WAIT * (attempt + 1))
