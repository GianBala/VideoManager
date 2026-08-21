# Empacotamento

O empacotamento usa **PyInstaller**, que não faz compilação cruzada: cada
sistema operacional gera o seu próprio pacote, na própria máquina daquele
sistema.

```bash
./packaging/build_linux.sh       # Linux   -> dist/VideoManager/
./packaging/build_appimage.sh    # Linux   -> dist/Video_Manager-<versão>-<arch>.AppImage
.\packaging\build_windows.ps1    # Windows -> dist\VideoManager\
```

Os três scripts seguem a mesma sequência: instalam as dependências (inclusive
`pyinstaller`), **rodam a suíte de testes primeiro** (um pacote não deve ser
gerado sobre suíte vermelha), baixam o `ffmpeg` a embutir, empacotam com o
`.spec` do projeto e, por fim, **abrem o executável gerado** para confirmar
que ele realmente sobe — ver [`smoke_run.sh`](#conferindo-que-o-pacote-abre)
abaixo.

## `build_linux.sh` / `build_windows.ps1`

Geram uma pasta autocontida (`dist/VideoManager/`) com o executável e tudo que
ele precisa — Python embutido, Qt, yt-dlp e (por padrão) o `ffmpeg`.

```bash
VENV=.venv ./packaging/build_linux.sh   # variável opcional: outro caminho de venv
```

## `build_appimage.sh` (Linux)

Envelopa o resultado de `build_linux.sh` num AppImage — um arquivo só,
executável, sem instalação. Não reimplementa o empacotamento: literalmente
usa a mesma pasta gerada pelo `build_linux.sh`, então tudo que vale para
aquele pacote (bibliotecas, ffmpeg embutido, extratores do yt-dlp) vale aqui
também.

```bash
./packaging/build_appimage.sh                     # build completo
./packaging/build_appimage.sh --reuse-dist        # pula o build_linux.sh, reusa dist/
VM_BUNDLE_FFMPEG=0 ./packaging/build_appimage.sh  # sem ffmpeg embutido: ~290 MB a menos
```

Sem compilação cruzada aqui também: um AppImage x86_64 precisa ser gerado
numa máquina x86_64.

## `fetch_binaries.py`

Baixa `ffmpeg`/`ffprobe` para `vendor/<plataforma>/` **antes** do
empacotamento, para que o executável já saia com os binários dentro e
funcione no primeiro clique, sem precisar baixar nada na primeira execução.
Reaproveita `core.binaries` — a mesma lógica de fonte e validação que a
aplicação usa em tempo de execução, então não existe uma segunda cópia dela
para sair de sincronia.

```bash
PYTHONPATH=src python packaging/fetch_binaries.py
```

Se os binários já estiverem presentes em `vendor/`, o script não baixa de
novo.

## `videomanager.spec`

O ponto de entrada do PyInstaller é `src/videomanager/__main__.py`, com
**import absoluto** de propósito: o PyInstaller executa o script como
`__main__` sem pacote, então um import relativo não só falha em execução como
faz o analisador de dependências do PyInstaller parar ali — o pacote saía
sem o PySide6 inteiro.

O `.spec` também poda bibliotecas C que entram pelo grafo de dependência
transitiva sem nunca serem carregadas em tempo de execução (`excludes` do
PyInstaller só alcança módulos Python, não bibliotecas C). O maior caso é
`platformthemes/libqgtk3.so`: 236 KB que arrastam consigo ~15 MB de GTK,
cairo, pango e atk, inúteis num app que força o estilo Fusion e pinta a
própria paleta. Ao alterar a lista de poda, duas regras:

1. Depois de mexer, conferir que **nenhum** binário remanescente ficou com um
   `NEEDED` (dependência ELF) pendente.
2. O `ffmpeg` embutido também é uma raiz do grafo — uma biblioteca que parece
   órfã pelo lado do Qt pode ser dependência dele.

## Conferindo que o pacote abre

```bash
./packaging/smoke_run.sh dist/VideoManager/VideoManager [segundos]
```

Existe porque o modo de falha típico do PyInstaller é silencioso na geração
e fatal só na abertura: um import que o analisador não enxerga produz um
pacote aparentemente completo que morre no primeiro segundo — foi
exatamente o que já aconteceu neste projeto (pacote sem o PySide6 inteiro,
sem nenhum aviso na geração). O script abre o executável em modo
`QT_QPA_PLATFORM=offscreen` (funciona sem servidor gráfico, inclusive em CI)
e confere que ele continua de pé depois da janela montada e do bootstrap —
não só que ele "rodou sem erro".

## Distribuindo o AppImage

```bash
chmod +x Video_Manager-<versão>-x86_64.AppImage
./Video_Manager-<versão>-x86_64.AppImage
```

Não se instala no menu do sistema sozinho — para isso existe o
[AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher). Numa
máquina sem FUSE, ainda roda assim:

```bash
./Video_Manager-<versão>-x86_64.AppImage --appimage-extract-and-run
```
