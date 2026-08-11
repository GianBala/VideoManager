# -*- mode: python ; coding: utf-8 -*-
"""Especificação do PyInstaller.

Gera um pacote em pasta (``--onedir``), não um arquivo único. A escolha é
deliberada: o modo arquivo único descompacta tudo num diretório temporário a cada
abertura, o que com PySide6 e os ~180 MB de ffmpeg custa vários segundos de espera
em cada início. Em pasta, abre instantaneamente.

Não há compilação cruzada: cada sistema gera o seu próprio pacote. Rode
``build_linux.sh`` no Linux e ``build_windows.ps1`` no Windows.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from videomanager.core.binaries import exe_name, platform_key  # noqa: E402

# Binários preparados por packaging/fetch_binaries.py. Se ausentes, o pacote
# ainda funciona: a aplicação oferece o download na primeira execução.
_vendor = REPO_ROOT / "vendor" / platform_key()
binaries_to_bundle = [
    (str(_vendor / exe_name(stem)), f"vendor/{platform_key()}")
    for stem in ("ffmpeg", "ffprobe")
    if (_vendor / exe_name(stem)).is_file()
]

a = Analysis(
    [str(REPO_ROOT / "src" / "videomanager" / "__main__.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=binaries_to_bundle,
    datas=[],
    # Os extratores do yt-dlp são carregados dinamicamente; sem coletá-los
    # explicitamente, o pacote reconhece só uma fração dos sites.
    hiddenimports=[
        "yt_dlp.extractor.lazy_extractors",
        "yt_dlp.compat._legacy",
        "yt_dlp.utils._legacy",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Módulos Qt que a aplicação não usa. Excluí-los tira dezenas de MB.
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoManager",
    debug=False,
    strip=False,
    upx=False,
    # Sem console: no Windows um console preto apareceria atrás da janela.
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoManager",
)
