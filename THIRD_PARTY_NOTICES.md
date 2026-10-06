# Avisos de terceiros

**Video Manager** — Copyright (C) 2026 GianBala.

Este programa é software livre: você pode redistribuí-lo e modificá-lo sob os
termos da GNU General Public License, versão 3 ou (a seu critério) qualquer
versão posterior, publicada pela Free Software Foundation. Ele é distribuído na
esperança de ser útil, mas **sem nenhuma garantia**, nem mesmo a implícita de
comerciabilidade ou de adequação a um propósito específico. O texto da licença
está em [`LICENSE`](LICENSE).

## O que os pacotes embutem

O AppImage (Linux) e o `VideoManager.exe` (Windows) levam junto os componentes
abaixo. Os textos de licença vão dentro do pacote, na pasta `licenses/` ao lado
dos arquivos do programa (no AppImage, `usr/bin/_internal/licenses/`).

| Componente | Licença | Texto no pacote | Código-fonte correspondente |
| --- | --- | --- | --- |
| **ffmpeg e ffprobe** n7.1.5-12-g1fdbca85aa, build da BtbN, variante `gpl` (publicação `autobuild-2026-07-31-14-10`) | GPL-3.0-or-later (compilado com `--enable-gpl --enable-version3`) | `licenses/LICENSE` | FFmpeg no commit [`1fdbca85aa`](https://github.com/FFmpeg/FFmpeg/commit/1fdbca85aa); scripts de build e versões das bibliotecas em [BtbN/FFmpeg-Builds@autobuild-2026-07-31-14-10](https://github.com/BtbN/FFmpeg-Builds/tree/autobuild-2026-07-31-14-10) |
| **Qt 6**, **PySide6** e **Shiboken6** | LGPL-3.0-only | `licenses/LGPL-3.0.txt` e `licenses/LICENSE` (a GPL-3.0, que a LGPL complementa) | [download.qt.io/official_releases/QtForPython](https://download.qt.io/official_releases/QtForPython/) e [code.qt.io](https://code.qt.io/) |
| **Python** (interpretador e biblioteca padrão) | PSF-2.0 | `licenses/python/LICENSE.txt` | [python.org/downloads/source](https://www.python.org/downloads/source/) |
| **Deno** v2.9.6 | MIT | `licenses/Deno-MIT.txt` | [denoland/deno@v2.9.6](https://github.com/denoland/deno/tree/v2.9.6) |
| **yt-dlp** e **yt-dlp-ejs** | Unlicense (yt-dlp-ejs: Unlicense, MIT e ISC) | `licenses/<pacote>/` | [PyPI](https://pypi.org/project/yt-dlp/) |
| **mutagen** | GPL-2.0-or-later | `licenses/mutagen/` | [PyPI](https://pypi.org/project/mutagen/) |
| **certifi** | MPL-2.0 | `licenses/certifi/` | [PyPI](https://pypi.org/project/certifi/) |
| **requests** | Apache-2.0 | `licenses/requests/` (com o `NOTICE`) | [PyPI](https://pypi.org/project/requests/) |
| **platformdirs**, **urllib3**, **charset-normalizer**, **brotli** | MIT | `licenses/<pacote>/` | PyPI |
| **websockets**, **idna** | BSD-3-Clause | `licenses/<pacote>/` | PyPI |
| **pycryptodomex** | BSD-2-Clause e domínio público | `licenses/pycryptodomex/` | PyPI |

As versões exatas das bibliotecas Python são as do ambiente em que o pacote foi
gerado, e cada pasta `licenses/<pacote>/` traz o texto da versão embutida.

## Código-fonte

O código-fonte deste programa está em
[github.com/GianBala/VideoManager](https://github.com/GianBala/VideoManager),
na tag de cada versão. O dos componentes GPL e LGPL está nos endereços da
tabela, sem custo. Se algum deles deixar de estar disponível, peça pelo
repositório (aba Issues) e uma cópia do código-fonte correspondente será
fornecida, pelo menos durante três anos a partir da distribuição do pacote.
