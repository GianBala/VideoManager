"""Preferências persistidas do usuário.

Guardadas como JSON simples no diretório de configuração do sistema operacional
(``~/.config/VideoManager`` no Linux, ``%LOCALAPPDATA%`` no Windows). A gravação
é atômica — escreve num arquivo temporário e renomeia — para que um desligamento
no meio do processo não deixe um JSON truncado que impediria o app de abrir na
próxima vez.

Campos desconhecidos no arquivo são ignorados e campos ausentes assumem o
padrão, então uma configuração salva por uma versão futura não quebra uma versão
antiga, e vice-versa.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from videomanager.application.preferences import Preferences

from platformdirs import user_config_dir, user_downloads_dir

from videomanager import APP_NAME


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False))


def config_file() -> Path:
    return config_dir() / "settings.json"


def _default_download_dir() -> str:
    """Pasta de downloads do sistema, com fallback para a home."""
    try:
        return str(Path(user_downloads_dir()))
    except Exception:  # noqa: BLE001 - platformdirs pode falhar em ambiente sem HOME
        return str(Path.home())


@dataclass
class Settings(Preferences):
    """Preferências da aplicação. Todos os campos têm padrão utilizável."""

    download_dir: str = field(default_factory=_default_download_dir)

    @classmethod
    def load(cls) -> Settings:
        """Carrega as preferências, caindo para os padrões em qualquer falha.

        Um arquivo corrompido nunca impede o app de abrir: perder preferências é
        um incômodo, não abrir é um defeito.
        """
        path = config_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls.from_dict(raw)

    def save(self) -> None:
        """Grava as preferências de forma atômica."""
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), indent=2, ensure_ascii=False)

        # Arquivo temporário na mesma pasta: os.replace só é atômico dentro do
        # mesmo sistema de arquivos.
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix="settings-", suffix=".tmp", delete=False
        )
        temp_path = Path(handle.name)
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, config_file())
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Derivados
    # ------------------------------------------------------------------

    def resolved_download_dir(self) -> Path:
        """Pasta de destino garantidamente existente."""
        path = Path(self.download_dir).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            path = Path.home()
            path.mkdir(parents=True, exist_ok=True)
        return path
