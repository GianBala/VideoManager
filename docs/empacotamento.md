# Empacotamento

O empacotamento usa **PyInstaller**, que não faz compilação cruzada: cada
sistema operacional gera o seu próprio pacote, na própria máquina daquele
sistema.

```bash
./packaging/build_linux.sh       # Linux   -> dist/VideoManager/
./packaging/build_appimage.sh    # Linux   -> dist/Video_Manager-<versão>-<arch>.AppImage
.\packaging\build_windows.ps1    # Windows -> dist\VideoManager.exe (arquivo único)
```

Os três scripts seguem a mesma sequência: instalam as dependências (inclusive
`pyinstaller`), **rodam a suíte de testes primeiro** (um pacote não deve ser
gerado sobre suíte vermelha), baixam o `ffmpeg` a embutir, empacotam com o
`.spec` do projeto e, por fim, **abrem o executável gerado** para confirmar
que ele realmente sobe — ver [`smoke_run.sh`](#conferindo-que-o-pacote-abre)
abaixo. Cada etapa de comando nativo confere o código de saída e interrompe o
script na falha.

### Testes antes do pacote

As integrações com o `ffmpeg` são a parte mais lenta da suíte. Nos scripts de
Linux o padrão é o **modo rápido**: `pytest -m "not ffmpeg and not network"`, que
ainda cobre domínio, aplicação, interface e arquitetura, e deixa as integrações
demoradas para a CI. `VM_FAST_TESTS=0` roda tudo (menos a rede):

```bash
VM_FAST_TESTS=0 ./packaging/build_appimage.sh    # também vale para build_linux.sh
```

`build_windows.ps1` sempre roda a suíte completa. Um pacote gerado no modo
rápido não substitui a CI, que roda o conjunto inteiro com três versões do
ffmpeg (ver [testes](clean-architecture/testes.md#integração-contínua)).

## `build_linux.sh` / `build_windows.ps1`

`build_linux.sh` gera uma pasta autocontida (`dist/VideoManager/`) com o
executável e tudo que ele precisa — Python embutido, Qt, yt-dlp e (por padrão) o
`ffmpeg`.

```bash
VENV=.venv ./packaging/build_linux.sh   # variável opcional: outro caminho de venv
```

`build_windows.ps1` gera um **único arquivo**, `dist\VideoManager.exe`, com o
mesmo conteúdo dentro: ele funciona sozinho, copiado para qualquer lugar. O
preço é que o PyInstaller extrai tudo para uma pasta temporária (`%TEMP%\_MEI…`)
a cada abertura. Medido nesta máquina, com ffmpeg, ffprobe e Deno embutidos
(arquivo de 208 MB, ~500 MB extraídos), o diagnóstico `--smoke-test` levou ~8 s
do clique à saída, contra ~2 s do pacote em pasta: a extração termina em ~3 s, a
janela aparece em ~5,4 s e o resto é o próprio diagnóstico (prévia e exportação
de 1 s). Sem ffmpeg e Deno (`VM_BUNDLE_FFMPEG=0
VM_BUNDLE_DENO=0`, arquivo de 70 MB) levou ~5 s. A pasta temporária é apagada ao
fechar; se o processo for encerrado à força, ela fica para trás e pode ser
removida à mão.

`VM_ONEFILE=0` gera, no Windows, a pasta `dist\VideoManager\` no lugar do
arquivo único: abre na hora, mas o `.exe` só funciona com a subpasta `_internal`
ao lado. No Linux a variável não tem efeito: o AppImage envelopa a pasta.

```powershell
$env:VM_ONEFILE = "0"; .\packaging\build_windows.ps1   # pasta, em vez de arquivo único
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

`scripts/generate_appimage.sh` faz o mesmo de ponta a ponta num só comando —
cria o `.venv`, instala as dependências, testa, baixa os binários, empacota,
monta o AppDir, gera o AppImage e calcula o SHA-256 — para quem parte de um
clone limpo. Aceita `--skip-tests`, `--skip-deps`, `--no-bundle-ffmpeg` e
`--reuse-dist`, e obedece a `VM_FAST_TESTS` como os scripts de `packaging/`.

## `fetch_binaries.py`

Baixa `ffmpeg`/`ffprobe` para `vendor/<plataforma>/` **antes** do
empacotamento, para que o executável já saia com os binários dentro e
funcione no primeiro clique, sem precisar baixar nada na primeira execução.
Reaproveita `infrastructure.system.binaries` — a mesma lógica de fonte e validação que a
aplicação usa em tempo de execução, então não existe uma segunda cópia dela
para sair de sincronia.

```bash
PYTHONPATH=src python packaging/fetch_binaries.py
```

Se os binários já estiverem presentes em `vendor/`, o script não baixa de
novo.

O mesmo script baixa o **Deno** (versão fixa, conferida por SHA-256) para o
yt-dlp resolver os desafios JavaScript do YouTube; sem um runtime JavaScript,
parte dos formatos some. A aplicação não baixa o Deno em execução: ele vem no
pacote ou vale o Deno/Node do sistema (`binaries.find_js_runtime`).
`VM_BUNDLE_DENO=0` dispensa o download e a inclusão (~110 MB a menos).

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

Outros dois pontos do `.spec` que não seguem imports e por isso ficam
explícitos:

- **Scripts do solver JavaScript do yt-dlp** (`collect_data_files("yt_dlp",
  includes=["**/*.js"])`): são lidos com `importlib.resources`; sem eles o
  pacote não resolvia os desafios do YouTube nem com o Deno presente.
- **Ícone do executável** (`icon=`): `packaging/make_icon.py` gera
  `build/videomanager.ico` a partir de `resources/videomanager.png` com o Qt,
  em nove tamanhos de 16 a 256 px. Sem `icon=` o `.exe` saía com o ícone
  padrão do PyInstaller — e o spec só aplica o ícone se o arquivo existir, então
  **o `.ico` precisa ser gerado antes do PyInstaller** (o `build_windows.ps1` e a
  CI fazem isso). Todas as entradas são bitmap clássico (DIB de 32 bits com
  máscara), inclusive a de 256 px: o shell do Windows lê PNG dentro de um
  `.ico`, mas as APIs antigas (GDI+, `System.Drawing`, diálogos e utilitários
  que ainda as usam) não, e devolviam o desenho esticado ou ruído colorido. O
  arquivo fica com cerca de 400 KB. No pacote em pasta (`VM_ONEFILE=0`), o
  `.ico` também vai solto na raiz, ao lado do `.exe` — não em `_internal` —,
  para um atalho feito à mão apontar direto para ele; o arquivo único não tem
  "ao lado". O Explorer guarda ícones em cache: se o desenho antigo persistir,
  renomeie o executável ou rode `ie4uinit.exe -show`.

## Conferindo que o pacote abre

```bash
./packaging/smoke_run.sh dist/VideoManager/VideoManager [segundos]
```

Existe porque o modo de falha típico do PyInstaller é silencioso na geração
e fatal só na abertura: um import que o analisador não enxerga produz um
pacote aparentemente completo que morre no primeiro segundo — foi
exatamente o que já aconteceu neste projeto (pacote sem o PySide6 inteiro,
sem nenhum aviso na geração). O script usa `QT_QPA_PLATFORM=offscreen` e o
argumento `--smoke-test`, com perfil temporário e prazo padrão de 30 segundos.
Exige código de saída zero e o marcador `VM_SMOKE_OK`: janela montada, fonte
Carlito carregada, prévia de texto renderizada e vídeo de 1 segundo exportado
e inspecionado. Também confere que os scripts do solver JavaScript do yt-dlp e
o mutagen estão no pacote, que o Qt do pacote grava e lê JPEG (o cache de
quadros da agulha depende do plugin de imagem, e sem ele o arrasto cairia no
quadro exato sem avisar) e informa o runtime JavaScript encontrado
(`VM_SMOKE_JS_RUNTIME`). Um processo que apenas continua aberto não passa no
teste.

A consulta a dispositivos de áudio fica desabilitada nesse diagnóstico.
ffmpeg/ffprobe precisam estar empacotados, provisionados ou no PATH. Com
`VM_BUNDLE_FFMPEG=0`, disponibilize as ferramentas antes de rodar o teste.
No Windows, execute `VideoManager.exe --smoke-test`, aguarde o término e confira
o código de saída. Valide também áudio e interação no sistema de destino.

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

## Diagnóstico e diretórios isolados

O build Windows executa `packaging/smoke_windows.ps1` e exige código zero
antes de anunciar sucesso. O diagnóstico cria a janela, carrega fontes, gera
uma prévia com texto e exporta mídia de um segundo. O script encerra o processo
se ele ultrapassar o prazo (120 s por padrão: o arquivo único extrai tudo antes
de abrir). Depois confere o que o diagnóstico em execução não alcança: scripts
do solver, `deno.exe` (salvo com `VM_BUNDLE_DENO=0`) e, com `-Icon`, se o ícone
do executável é o do aplicativo. No arquivo único, a lista de entradas vem do
próprio `.exe`, lida com o PyInstaller (parâmetro `-Python`, `python` por
padrão); no pacote em pasta, dos arquivos em `_internal`.

### Diagnóstico de análise de URL

```powershell
VideoManager.exe --diagnose-url "https://..." --report relatorio.txt
```

Refaz, no próprio pacote, o caminho do botão Analisar — worker, pool e os slots
que montam cartão e qualidades — e grava no relatório título, quantidade de
formatos, se o botão de enfileirar ficou habilitado, diálogos de erro e avisos
registrados. Termina com `VM_DIAGNOSE_OK` ou `VM_DIAGNOSE_FAILED`. Foi assim que
se achou o cartão lendo um atributo removido do domínio: a exceção nascia dentro
de um slot e, sem console, não deixava rastro.

O aplicativo grava log com rotação em `videomanager.log`, na pasta de logs do
usuário (`%LOCALAPPDATA%\VideoManager\Logs` no Windows), incluindo exceções não
tratadas em slots e threads (o caminho no Linux e o que ele guarda estão em
[instalação](instalacao.md#onde-fica-o-registro-de-execução)).

A CI gera o pacote do Windows como o build local — provisiona ffmpeg e Deno,
gera o `.ico` antes do PyInstaller e roda `smoke_windows.ps1` com `-Icon`, para
o ícone do `.exe` ser conferido — e guarda o `VideoManager.exe` (arquivo único)
por sete dias. O pacote em pasta do Linux é gerado com `VM_BUNDLE_FFMPEG=0` e
aprovado por `smoke_run.sh`.

Em Linux, `VM_DIST_DIR` e `VM_BUILD_DIR` permitem escolher diretórios separados
para PyInstaller e AppImage. O build não precisa apagar todo o `dist` existente.
O AppImage gera um arquivo `.sha256` após passar no diagnóstico. O download do
runtime só atualiza o cache quando termina com sucesso e o patch de
auto-extração (`packaging/patch_runtime.py`, só para runtimes x86_64 compatíveis)
trabalha numa cópia; se ele não puder ser aplicado, o build avisa e o AppImage
ainda roda com `APPIMAGE_EXTRACT_AND_RUN=1` onde não houver FUSE.
Auto-extração não é garantia de suporte a toda distribuição Linux.

As evidências da migração estão no [checkup final](clean-architecture/validacao-final.md).

O provisionamento usa uma publicação mensal fixa do BtbN, revisão
`n7.1.5-12-g1fdbca85aa`, porque os assets 7.1 foram retirados do `latest`.
A alteração de versão é explícita para manter os requisitos de driver NVIDIA
validados. Os testes de rede verificam os três endereços configurados.
