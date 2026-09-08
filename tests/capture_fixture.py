"""Captura respostas reais de extratores para usar como fixtures nos testes.

Uso::

    PYTHONPATH=src python tests/capture_fixture.py <nome> <url>

As fixtures existem porque nenhum teste sintético cobre a criatividade dos
extratores de verdade. Mas a resposta crua não vai para o repositório como veio:

* URLs de mídia, cabeçalhos HTTP e listas de fragmentos são **removidos**. São
  assinados com tokens de sessão, expiram em minutos e não devem ser versionados.
* Campos que a aplicação nunca lê (miniaturas, mapa de calor, legendas
  automáticas em massa) são removidos para a fixture continuar legível numa
  revisão de código.

Todos os campos que :mod:`videomanager.infrastructure.yt_dlp.formats` consulta são
preservados exatamente como vieram — inclusive quando vieram ausentes, nulos ou
com o tipo errado, que é justamente o que se quer testar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yt_dlp

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Removidos de cada formato: volumosos, sensíveis ou nunca lidos.
_DROP_FROM_FORMAT = (
    "url",
    "fragments",
    "http_headers",
    "manifest_url",
    "downloader_options",
    "fragment_base_url",
    "manifest_stream_number",
    "_filename",
)

# Removidos da raiz.
_DROP_FROM_ROOT = (
    "url",
    "http_headers",
    "thumbnails",
    "heatmap",
    "automatic_captions",
    "requested_formats",
    "requested_downloads",
    "chapters",
    "description",
    "formats_sort_fields",
    # O Instagram devolve comentários (com usuário e texto de terceiros) mesmo
    # numa extração só de metadados. O parser nunca lê isso, e versionar dados
    # pessoais de quem comentou não tem motivo.
    "comments",
    "comment_count",
    "like_count",
)


def slim(info: dict) -> dict:
    """Reduz a resposta preservando tudo que o parser da aplicação consulta."""
    result = {key: value for key, value in info.items() if key not in _DROP_FROM_ROOT}

    formats = info.get("formats")
    if isinstance(formats, list):
        result["formats"] = [
            {k: v for k, v in fmt.items() if k not in _DROP_FROM_FORMAT}
            if isinstance(fmt, dict)
            else fmt
            for fmt in formats
        ]

    # Das legendas guardamos só os idiomas: o conteúdo não interessa ao teste.
    subs = info.get("subtitles")
    if isinstance(subs, dict):
        result["subtitles"] = {
            lang: [{"ext": (v[0] or {}).get("ext", "vtt")}] if isinstance(v, list) and v else []
            for lang, v in subs.items()
        }

    return result


def capture(name: str, url: str) -> Path:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.sanitize_info(ydl.extract_info(url, download=False))

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    target = FIXTURE_DIR / f"{name}.json"
    target.write_text(
        json.dumps(slim(info), indent=1, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return target


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    name, url = sys.argv[1], sys.argv[2]
    try:
        path = capture(name, url)
    except Exception as exc:  # noqa: BLE001 - ferramenta de linha de comando
        print(f"falhou: {type(exc).__name__}: {str(exc)[:400]}")
        return 1
    size_kb = path.stat().st_size / 1024
    print(f"gravado: {path}  ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
