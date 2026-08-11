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
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_downloads_dir

from .. import APP_NAME


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
class Settings:
    """Preferências da aplicação. Todos os campos têm padrão utilizável."""

    # --- destino ---
    download_dir: str = field(default_factory=_default_download_dir)
    # Subpasta por site (youtube/, bilibili/…). Ajuda quem baixa de muitas fontes.
    separate_by_site: bool = False

    # --- padrões de vídeo ---
    # mkv como padrão porque aceita qualquer combinação de codecs, então nunca
    # obriga a recodificar. Ver core/selector.py.
    default_container: str = "mkv"
    default_height: int = 1080
    default_fps_cap: int = 0  # 0 = sem limite

    # --- padrões de áudio ---
    default_audio_format: str = "mp3"
    default_audio_quality: str = "192"

    # --- metadados ---
    embed_thumbnail: bool = True
    embed_metadata: bool = True

    # --- legendas ---
    write_subtitles: bool = False
    embed_subtitles: bool = False
    subtitle_langs: list[str] = field(default_factory=lambda: ["pt", "pt-BR", "en"])
    include_auto_subtitles: bool = False

    # --- acesso ---
    # Nome do navegador para ler cookies (ver yt_dlp.cookies.SUPPORTED_BROWSERS).
    # Necessário para vídeos com restrição de idade, privados, de membros e para
    # as resoluções altas do BiliBili.
    cookies_browser: str = ""

    # --- rede e desempenho ---
    max_concurrent_jobs: int = 3
    concurrent_fragments: int = 4
    rate_limit_kbps: int = 0  # 0 = ilimitado

    # --- interface ---
    theme: str = "dark"
    window_geometry: str = ""  # QByteArray serializado em base64

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

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

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        """Constrói a partir de um dicionário, ignorando chaves desconhecidas."""
        known = {f.name: f for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for name, spec in known.items():
            if name not in raw:
                continue
            value = raw[name]
            # Confere o tipo de forma tolerante: uma chave com tipo errado volta
            # ao padrão em vez de explodir na primeira vez que for usada.
            if spec.type in ("bool", bool) and isinstance(value, bool):
                kwargs[name] = value
            elif spec.type in ("int", int) and isinstance(value, int) and not isinstance(value, bool):
                kwargs[name] = value
            elif spec.type in ("str", str) and isinstance(value, str):
                kwargs[name] = value
            elif spec.type in ("list[str]",) and isinstance(value, list):
                kwargs[name] = [str(item) for item in value]
        return cls(**kwargs)

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
