"""Valores de configuração, sem descoberta de diretórios ou persistência."""
from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import Any

@dataclass
class Preferences:
    """Preferências da aplicação. Todos os campos têm padrão utilizável."""

    # --- destino ---
    download_dir: str = ""
    # Subpasta por site (youtube/, bilibili/…). Ajuda quem baixa de muitas fontes.
    separate_by_site: bool = False

    # --- padrões de vídeo ---
    # mkv como padrão porque aceita qualquer combinação de codecs, então nunca
    # obriga a recodificar. Ver infrastructure/yt_dlp/selector.py.
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
    # Caminho para arquivo de cookies (.txt), alternativa mais robusta quando o
    # navegador está bloqueado ou encriptado pelo sistema.
    cookies_file: str = ""

    # --- rede e desempenho ---
    max_concurrent_jobs: int = 3
    concurrent_fragments: int = 4
    rate_limit_kbps: int = 0  # 0 = ilimitado

    # --- codificação ---
    # Preferência de encoder de vídeo: "software" (padrão), "auto" ou o nome de
    # uma placa. É só uma preferência — o que vale é o que abre na máquina, e a
    # queda para software é automática (ver infrastructure/ffmpeg/hardware.py).
    hardware_encoder: str = "software"
    # Qualidade padrão de exportação da edição: "balanced" (CRF 23), "high" (CRF 18), "economy" (CRF 28)
    default_export_quality: str = "balanced"

    # --- interface ---
    theme: str = "dark"
    window_geometry: str = ""  # QByteArray serializado em base64
    # Volume da prévia da aba de edição, de 0 a 100. Guardado porque é ajustado
    # pelo ambiente em que se edita (fone, caixa, escritório), e não pelo vídeo:
    # reencontrar o volume de ontem a cada abertura seria trabalho repetido.
    preview_volume: int = 70
    preview_muted: bool = False
    preview_snap: bool = True

    # ------------------------------------------------------------------
    # Validação de valores
    # ------------------------------------------------------------------


    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Preferences:
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


