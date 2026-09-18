# Instalação e primeira execução

## Pacotes prontos

### Linux — AppImage

Um arquivo só, sem instalação:

```bash
chmod +x Video_Manager-<versão>-x86_64.AppImage
./Video_Manager-<versão>-x86_64.AppImage
```

O AppImage já traz Python, Qt, yt-dlp e o `ffmpeg` embutidos — funciona no
primeiro clique, sem baixar nada. Ele não se instala no menu do sistema
sozinho; para isso existe o
[AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher). Se a
imagem não montar por falta de FUSE na máquina, roda assim mesmo:

```bash
./Video_Manager-<versão>-x86_64.AppImage --appimage-extract-and-run
```

Existe também uma variante sem o `ffmpeg` embutido (~290 MB mais leve), gerada
com `VM_BUNDLE_FFMPEG=0` — ver [`empacotamento.md`](empacotamento.md). Ela usa
o `ffmpeg` do sistema se encontrar um, ou oferece baixá-lo na primeira
execução.

### Linux — pasta (`build_linux.sh`)

`dist/VideoManager/` é uma pasta autocontida — descompacte e execute
`VideoManager` de dentro dela.

**Dependência do sistema:** o Qt precisa de `libxcb-cursor0`, que não vem em
toda distribuição:

```bash
sudo apt install libxcb-cursor0
```

Sem essa biblioteca o Qt aborta o processo com *"Could not load the Qt
platform plugin xcb"* antes mesmo de a janela abrir. `preflight.py` detecta a
ausência dela e mostra um aviso explicando o pacote a instalar — mas só
consegue fazer isso porque a checagem roda **antes** de o `QApplication` ser
criado; depois disso já é tarde para explicar qualquer coisa.

### Windows

`dist\VideoManager.exe`, gerado por `build_windows.ps1`, é um arquivo único que
funciona sozinho: copie-o para onde quiser e execute — não há instalador nem
pasta ao lado. Ele traz Python, Qt, yt-dlp, ffmpeg e Deno dentro de si.

O custo é o início: o Windows extrai tudo para uma pasta temporária a cada
abertura (cerca de 3 s), e a janela leva cerca de 5 s para aparecer.
Para um pacote que abre mais rápido, gere a pasta com `VM_ONEFILE=0`
(`dist\VideoManager\`); nesse formato o `.exe` só funciona com a subpasta
`_internal` ao lado dele. Detalhes em [`empacotamento.md`](empacotamento.md).

## Rodar a partir do código-fonte

Para desenvolver ou rodar sem empacotar:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m videomanager
```

No Windows, troque `.venv/bin/` por `.venv\Scripts\`.

Dependências principais (de `pyproject.toml`): `PySide6>=6.6`,
`yt-dlp[default]>=2025.1.1` (sem teto de versão — extratores quebram quando as
plataformas mudam do lado delas, então o yt-dlp precisa poder ser atualizado a
qualquer momento) e `platformdirs>=4.0`. Python 3.10 ou mais novo. O extra
`default` do yt-dlp traz o que o download usa além do núcleo: os scripts do
solver JavaScript do YouTube (`yt-dlp-ejs`), o `mutagen` (capa em opus, ogg e
flac), certificados, `brotli` e `websockets`. O YouTube ainda precisa de um
runtime JavaScript — ver [Aba Download](guia-download.md#youtube-e-runtime-javascript).

## O ffmpeg

O app não funciona sem `ffmpeg` e `ffprobe`. Na primeira execução ele procura,
nesta ordem:

1. Um `ffmpeg`/`ffprobe` **empacotado** junto (pasta `vendor/`, presente nos
   pacotes gerados com `VM_BUNDLE_FFMPEG=1`, o padrão).
2. Uma versão **baixada antes**, guardada na pasta de configuração do usuário.
3. O `ffmpeg` do **`PATH`** do sistema.

Se nenhum for encontrado, o app oferece baixar a build oficial (~130 MB) numa
pasta própria, sem alterar nada no sistema nem exigir privilégio de
administrador. Quem já tem um `ffmpeg` capaz é aproveitado — o download nunca
acontece à toa.

A build usada é a variante **GPL**, porque o projeto depende de três encoders
que só existem nela: `libx264`, `libx265` e `libmp3lame`.

Os pacotes trazem o ffmpeg 7.1. Rodando pelo código-fonte, vale o que estiver
no sistema, e o aplicativo funciona com as versões 6 a 9 — o que muda entre
elas é tratado na hora (ver [versões do ffmpeg](clean-architecture/processamento.md#versões-do-ffmpeg)).
Uma limitação conhecida do ffmpeg 6, o do Ubuntu 24.04: uma transição que
atravessa um adicional com filtro perde esse adicional durante a passagem.

## Onde ficam as preferências

As configurações do usuário (pasta de download, qualidade padrão, tema,
etc.) são salvas em `settings.json`:

- **Linux:** `~/.config/VideoManager/settings.json`
- **Windows:** `%LOCALAPPDATA%\VideoManager\settings.json`

Um arquivo corrompido ou de uma versão futura nunca impede o app de abrir: a
leitura cai para os padrões em qualquer falha, e chaves desconhecidas são
ignoradas.

## Onde fica o registro de execução

O aplicativo grava um log com rotação (1 MB por arquivo, três cópias antigas)
em `videomanager.log`, na pasta de logs do usuário:

- **Linux:** `~/.local/state/VideoManager/log/` (ou o equivalente do
  `platformdirs` na sua distribuição)
- **Windows:** `%LOCALAPPDATA%\VideoManager\Logs`

Ele existe porque o pacote do Windows roda sem console: avisos do yt-dlp,
exceções dentro de slots do Qt e de threads de trabalho iam para um `stderr`
que ninguém vê. Não guarda cookies, cabeçalhos nem URLs assinadas. Ao relatar um
defeito que só acontece no pacote, este arquivo é o primeiro lugar a olhar; e
`VideoManager --diagnose-url URL --report relatorio.txt` refaz a análise de uma
URL dentro do pacote e grava o resultado (ver [empacotamento](empacotamento.md#diagnóstico-de-análise-de-url)).
