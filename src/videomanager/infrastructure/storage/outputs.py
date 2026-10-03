"""Reservas com propriedade explícita e publicação atômica no mesmo volume."""
import json
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from videomanager.application.errors import ConversionError
from videomanager.domain.i18n import Text
from videomanager.application.ports.output import OutputLease
from .output_paths import output_path


_REPLACE_ATTEMPTS = 6
_REPLACE_WAIT = 0.25
_TEMP = ".videomanager-"

# Diário da sessão (ver ``infrastructure/qt/sessions.py``). Uma queda ou um
# ``kill`` no meio de uma conversão deixava na pasta do usuário a reserva de
# 0 byte com o nome do resultado — a conversão seguinte virava "nome (2)" — e
# o render parcial ``.videomanager-*`` (visível no Windows), e nada os
# apagava. O diário anota cada reserva, cada pasta em que a sessão trabalhou e
# o fim de cada reserva; quem abre o aplicativo desfaz o que uma sessão morta
# deixou em aberto, só no que ainda é dela (:meth:`FileOutputStore.owns` e o
# nome da sessão nos temporários).
_token = ""
_journal: Callable[[], Path] | None = None
_journal_lock = threading.Lock()
_folders: set[str] = set()


def use_session(token: str, journal: Callable[[], Path]) -> None:
    global _token, _journal
    _token, _journal = token, journal
    _folders.clear()


def temp_prefix(kind: str = "") -> str:
    """Prefixo dos temporários que ficam ao lado do destino.

    Leva o nome da sessão: na mesma pasta pode haver uma exportação de outra
    janela aberta, e só os temporários da sessão morta podem ser apagados.
    """
    return f"{_TEMP}{_token}-{kind}" if _token else f"{_TEMP}{kind}"


def _note(entry: dict) -> None:
    if _journal is None:
        return
    try:
        # Fora da trava: o primeiro acesso cria a pasta da sessão, e criá-la
        # varre (e recupera) as sessões mortas.
        journal = _journal()
        with _journal_lock:
            folder = entry.get("reserva") and str(Path(entry["reserva"]).parent)
            lines = [json.dumps(entry)]
            if folder and folder not in _folders:
                _folders.add(folder)
                lines.append(json.dumps({"pasta": folder}))
            with journal.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
    except OSError:
        pass  # o diário ajuda a limpar depois de uma queda; nunca é motivo de falha


def recover(journal: Path, token: str) -> None:
    """Desfaz o que uma sessão morta deixou em aberto."""
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    leases: dict[str, dict] = {}
    folders: set[str] = set()
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # linha cortada pela própria queda
        if "reserva" in entry:
            leases[entry["reserva"]] = entry
        elif "fim" in entry:
            leases.pop(entry["fim"], None)
        elif "pasta" in entry:
            folders.add(entry["pasta"])
    store = FileOutputStore()
    for path, entry in leases.items():
        # Sem anotar: o diário em leitura é o da sessão morta, não o desta.
        store.discard(Path(path), lease=OutputLease(Path(path), entry["dev"], entry["ino"]))
    prefix = f"{_TEMP}{token}-"
    for folder in folders:
        try:
            items = list(Path(folder).iterdir())
        except OSError:
            continue
        for item in items:
            if item.name.startswith(prefix):
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)


class FileOutputStore:
    def reserve(self, source, target, directory=None, suffix='', custom_stem=None):
        path = output_path(source, target, directory, suffix, custom_stem)
        info = path.stat()
        _note({"reserva": str(path), "dev": info.st_dev, "ino": info.st_ino})
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
        self.discard(destination, lease=lease)
        _note({"fim": str(destination)})

    def discard(self, destination: Path, *, lease: OutputLease | None = None) -> None:
        """Apaga a reserva se ela ainda for dela (0 byte, mesmo inode)."""
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
                _note({"fim": str(destination)})
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_WAIT * (attempt + 1))
