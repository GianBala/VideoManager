# Video Manager

Aplicativo desktop para Windows e Linux que baixa vídeo e áudio de centenas de
plataformas e converte arquivos que você já tem no disco. Duas abas — **Download**
e **Convert** — sobre uma fila só, que fica fora delas e sempre à vista embaixo.
Na de download, no espírito do ATubeCatcher: endereço e destino no topo,
qualidade à esquerda, perfis rápidos à direita.

Usa **yt-dlp** para extração e **ffmpeg** para processamento.

## O que faz

- **Vídeo** com escolha explícita de resolução, framerate, codec e container —
  populados a partir do que a mídia **realmente** oferece, não de uma lista fixa.
- **Somente áudio** em MP3, M4A/AAC, Opus, Vorbis, FLAC ou WAV, com bitrate à
  escolha; ou **“Original”**, que apenas extrai o áudio sem recodificar.
- **Conversão de arquivos locais** para MP3 e outros formatos, com
  arrastar-e-soltar, na aba **Convert** — que enfileira na mesma fila dos
  downloads, sem interromper o que já está em andamento.
- **Playlists e canais** em lote, com seleção item a item.
- **Legendas** (inclusive automáticas), em arquivo separado ou embutidas.
- **Cookies do navegador** para mídias privadas, com restrição de idade, de
  assinantes, e para as resoluções altas do BiliBili.
- Fila com vários downloads simultâneos, cancelar, retomar e histórico de erros.

## Rodar a partir do código

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m videomanager
```

Na primeira execução o app procura o `ffmpeg` — empacotado, baixado antes, ou no
`PATH` do sistema. Se não achar nenhum, oferece baixar a versão oficial (~130 MB)
numa pasta só dele, sem alterar nada no sistema. Quem já tem `ffmpeg` instalado
nunca paga esse download.

**Linux:** o Qt precisa de `libxcb-cursor0`, que não vem em toda distribuição:

```bash
sudo apt install libxcb-cursor0
```

Sem ele o Qt falha com *“Could not load the Qt platform plugin xcb”*.

## Testes

```bash
.venv/bin/python -m pytest -q          # suíte offline, sem rede
.venv/bin/python -m pytest -m network  # testes que acessam a internet
```

## Empacotar

Cada sistema gera o seu próprio pacote — o PyInstaller não faz compilação cruzada.

```bash
./packaging/build_appimage.sh  # Linux  -> dist/Video_Manager-<versão>-<arch>.AppImage
./packaging/build_linux.sh     # Linux  -> dist/VideoManager/
.\packaging\build_windows.ps1  # Windows -> dist\VideoManager\
```

Os scripts rodam os testes, baixam o `ffmpeg` para embutir, empacotam e por fim
abrem o executável gerado para conferir que ele realmente sobe.

### AppImage

Um arquivo só, sem instalação: baixe, dê permissão de execução, clique.

```bash
chmod +x Video_Manager-0.1.0-x86_64.AppImage
./Video_Manager-0.1.0-x86_64.AppImage
```

Ele envelopa o mesmo pacote do `build_linux.sh`, então tem tudo dentro: Python,
Qt, yt-dlp e o `ffmpeg`. Duas opções úteis:

```bash
./packaging/build_appimage.sh --reuse-dist        # pula o build, reusa dist/
VM_BUNDLE_FFMPEG=0 ./packaging/build_appimage.sh  # sem ffmpeg: ~290 MB a menos
```

Com `VM_BUNDLE_FFMPEG=0` o app usa o `ffmpeg` do sistema ou oferece baixá-lo na
primeira execução — vale a pena quando o AppImage vai ser distribuído por
download.

O AppImage não se instala no menu do sistema sozinho; para isso existe o
[AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher). Se a imagem
não montar por falta de FUSE na máquina, roda assim mesmo:

```bash
./Video_Manager-0.1.0-x86_64.AppImage --appimage-extract-and-run
```

## Como o projeto está organizado

```
src/videomanager/
├── core/      lógica de mídia, sem nenhuma dependência de Qt
├── workers/   ponte para a interface: QRunnable + sinais
└── ui/        janela e painéis (PySide6)
```

A dependência é de mão única: `ui` → `workers` → `core`. É o que permite testar
toda a lógica de mídia sem abrir uma janela — os 265 testes da suíte offline não
instanciam Qt nem tocam a rede.

### Os dois módulos que importam

O trabalho difícil não está na interface, e sim em dois arquivos.

**`core/format_matrix.py`** normaliza a resposta crua de cada extrator. Cada
plataforma devolve uma estrutura diferente, e a diferença não é cosmética:

- O YouTube manda DASH com trilhas separadas, três codecs por resolução, HDR, e
  uma pilha de storyboards `mhtml` que não são mídia.
- O archive.org **não declara codec algum** e nenhum formato tem `fps`.
- O HLS da Apple declara `vcodec: "none"` nas faixas de áudio mas **omite**
  `acodec`.
- Muitos sites servem só HLS, sem `height`, sem `fps` e sem tamanho.

A distinção que sustenta o módulo: `"vcodec": "none"` significa *“conferi, não há
vídeo”*, enquanto a **ausência** da chave significa *“não sei”*. Tratar as duas
como a mesma coisa descarta mídia perfeitamente baixável — e foi exatamente o bug
que as fixtures pegaram: o archive.org ficava 100% inacessível e o HLS da Apple
baixava vídeo **mudo**.

**`core/selector.py`** traduz a escolha em opções do yt-dlp, sob duas regras:

- **Filtros não-estritos.** Todo limite sai como `[height<=?720]`. O `?` impede
  que formatos sem aquele campo sejam descartados. Sem ele, pedir “no máximo
  30 fps” elimina todos os formatos de sites que não informam `fps` — ou seja,
  quase tudo fora do YouTube.
- **Nunca recodificar sem consentimento.** Quando o container pedido não aceita o
  codec escolhido, a saída é **trocar de stream** (sem perda, mesma qualidade) ou
  **trocar de container** — nunca recodificar por conta própria. Toda substituição
  vira um aviso na tela, antes de o download começar.

### Testes

O que sustenta a promessa de funcionar em plataformas diversas são **fixtures
reais** — respostas de extratores capturadas em `tests/fixtures/`, cada uma
escolhida por expor uma estrutura diferente (ver o README de lá). Sobre elas se
afirma o que precisa valer para qualquer extrator: nada de storyboards vazando,
nada de exceção com campo nulo, nenhuma mídia baixável resultando em zero opções.

Além disso, cada expressão de formato gerada é submetida ao **parser real do
yt-dlp**. Um erro de sintaxe no `~=` ou no `<=?` não apareceria em nenhum teste de
comparação de strings — apareceria no primeiro download do usuário.

## Aviso

Este aplicativo é uma interface para o yt-dlp. Respeitar os termos de uso e os
direitos autorais de cada plataforma é responsabilidade de quem usa.
