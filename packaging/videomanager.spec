# -*- mode: python ; coding: utf-8 -*-
"""Especificação do PyInstaller.

Gera um pacote em pasta (``--onedir``), não um arquivo único. A escolha é
deliberada: o modo arquivo único descompacta tudo num diretório temporário a cada
abertura, o que com PySide6 e os ~180 MB de ffmpeg custa vários segundos de espera
em cada início. Em pasta, abre instantaneamente.

Não há compilação cruzada: cada sistema gera o seu próprio pacote. Rode
``build_linux.sh`` no Linux e ``build_windows.ps1`` no Windows.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from videomanager.infrastructure.system.binaries import exe_name
from videomanager.infrastructure.system.binaries import platform_key  # noqa: E402

# Binários preparados por packaging/fetch_binaries.py. Se ausentes, o pacote
# ainda funciona: a aplicação oferece o download na primeira execução.
#
# VM_BUNDLE_FFMPEG=0 gera um pacote ~290 MB menor, que usa o ffmpeg do sistema
# ou baixa na primeira execução. Existe porque um AppImage é feito para ser
# distribuído por download, onde esse peso é o custo principal.
_vendor = REPO_ROOT / "vendor" / platform_key()
binaries_to_bundle = (
    [
        (str(_vendor / exe_name(stem)), f"vendor/{platform_key()}")
        for stem in ("ffmpeg", "ffprobe")
        if (_vendor / exe_name(stem)).is_file()
    ]
    if os.environ.get("VM_BUNDLE_FFMPEG", "1") != "0"
    else []
)
# Deno para o yt-dlp resolver os desafios JavaScript do YouTube; baixado pelo
# mesmo fetch_binaries.py. Ausente, a aplicação usa Deno ou Node do sistema.
if os.environ.get("VM_BUNDLE_DENO", "1") != "0" and (_vendor / exe_name("deno")).is_file():
    binaries_to_bundle.append((str(_vendor / exe_name("deno")), f"vendor/{platform_key()}"))

# Os scripts do solver JavaScript que o yt-dlp traz dentro do próprio pacote
# são lidos por ``importlib.resources`` e não seguem os imports: sem coletá-los,
# o pacote não resolvia os desafios do YouTube nem com um runtime disponível.
from PyInstaller.utils.hooks import collect_data_files  # noqa: E402

a = Analysis(
    [str(REPO_ROOT / "src" / "videomanager" / "__main__.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=binaries_to_bundle,
    datas=[
        (str(REPO_ROOT / "src" / "videomanager" / "resources"), "resources"),
        *collect_data_files("yt_dlp", includes=["**/*.js"]),
    ],
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
    #
    # QtMultimedia **não** está na lista, ainda que seja o mais pesado deles:
    # é ele que toca o som da prévia na aba de edição (ver infrastructure/qt/audio.py).
    # Cortar áudio de um editor de vídeo para economizar espaço seria economizar
    # no lugar errado. Ele traz junto o próprio backend de mídia do Qt, que o
    # hook do PySide6 coleta em PySide6/Qt/plugins/multimedia.
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)

# --- poda do que é coletado por dependência transitiva ------------------------
#
# ``excludes`` acima só alcança **módulos Python**. As bibliotecas C entram por
# outro caminho: o analisador segue o grafo de dependências e traz tudo que
# alguém declara precisar, sem perguntar se aquilo chega a ser carregado.
#
# O caso extremo é o tema GTK. ``platformthemes/libqgtk3.so`` tem 236 KB e
# arrasta 15 MB de GTK, cairo, pango e atk — e a aplicação nunca o usa: ela
# força o estilo Fusion e pinta a própria paleta (``presentation/qt/theme.py``), então nada
# do que esse plugin decide sobrevive ao QSS. O que se perde ao tirá-lo é o
# seletor de arquivos do GTK, no lugar do qual entra o do próprio Qt (ou o do
# portal, cujo plugin continua no pacote).
#
# A lista saiu do fecho transitivo de dependências a partir das raízes reais —
# o executável, as extensões C do Python e os plugins Qt que a aplicação pode
# carregar. Tudo aqui é inalcançável a partir delas: medido, 24,8 MB. Depois da
# poda, conferido que nenhum arquivo remanescente tem NEEDED pendente e que a
# janela abre numa sessão X11 de verdade sem uma linha de erro.
#
# **``libmvec.so.1`` não entra**, por mais que o grafo do Qt a mostre como
# órfã: ela é NEEDED do ffmpeg empacotado, que resolve pelo sistema numa máquina
# atual e falharia numa glibc mais antiga — que é justamente o que um AppImage
# promete atender.
_PODAR = {
    # tema GTK e tudo que só ele alcança
    "libqgtk3.so",
    "libgtk-3.so.0", "libgdk-3.so.0", "libcairo.so.2", "libcairo-gobject.so.2",
    "libepoxy.so.0", "libpixman-1.so.0", "libharfbuzz.so.0", "libgraphite2.so.3",
    "libpango-1.0.so.0", "libpangocairo-1.0.so.0", "libpangoft2-1.0.so.0",
    "libgdk_pixbuf-2.0.so.0", "libatk-1.0.so.0", "libatk-bridge-2.0.so.0",
    "libatspi.so.0", "libjpeg.so.8", "libfribidi.so.0", "libXi.so.6",
    # PDF como formato de imagem: a prévia é rgb24 cru e a onda é PNG
    "libqpdf.so", "libQt6Pdf.so.6",
    # teclado virtual: isto se opera com teclado e mouse
    "libqtvirtualkeyboardplugin.so",
    "libQt6VirtualKeyboard.so.6", "libQt6VirtualKeyboardQml.so.6",
    # plataformas de embarcado e quiosque; ficam xcb, wayland, minimal e
    # offscreen — offscreen não sai porque é o que packaging/smoke_run.sh usa
    "libqlinuxfb.so", "libqvnc.so", "libqvkkhrdisplay.so", "libqeglfs.so",
    "libqminimalegl.so",
    "libQt6EglFSDeviceIntegration.so.6", "libQt6EglFsKmsSupport.so.6",
    # formatos de imagem que nada abre; ficam png (embutido no Qt), jpeg, webp
    # (miniaturas de site vêm nesses dois), gif, ico e svg
    "libqtiff.so", "libqtga.so", "libqwbmp.so", "libqicns.so",
}
_PODAR_PASTAS = ("plugins/egldeviceintegrations", "plugins/generic")

# Traduções do Qt: 124 idiomas, 7,1 MB, para uma interface que só existe em
# pt-BR. Ficam as de português e as de inglês, que é o recurso do Qt quando o
# idioma do sistema não é nenhum dos dois.
_IDIOMAS = ("_pt", "_pt_BR", "_en")


def _manter(entrada) -> bool:
    destino = str(entrada[0]).replace(os.sep, "/")
    nome = Path(destino).name
    if nome in _PODAR:
        return False
    if any(pasta in destino for pasta in _PODAR_PASTAS):
        return False
    if "Qt/translations/" in destino:
        return Path(destino).stem.endswith(_IDIOMAS)
    return True


a.binaries = [entrada for entrada in a.binaries if _manter(entrada)]
a.datas = [entrada for entrada in a.datas if _manter(entrada)]

pyz = PYZ(a.pure)

# Ícone do executável no Windows, gerado por packaging/make_icon.py a partir do
# PNG do aplicativo. Sem ``icon=`` o .exe saía com o ícone padrão do
# PyInstaller; a janela em execução já usava o certo (ver app.py), e era só o
# Explorer, o atalho e a barra fixada que mostravam o errado.
_ICON = REPO_ROOT / "build" / "videomanager.ico"
_icon_arg = str(_ICON) if sys.platform == "win32" and _ICON.is_file() else None

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
    icon=_icon_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoManager",
)
