# Video Manager

Aplicativo desktop para Windows e Linux que baixa vídeo e áudio de centenas de
plataformas, converte arquivos que você já tem no disco e recorta vídeo. Três
abas — **Download**, **Convert** e **Editar** — sobre uma fila só, que fica fora
delas e à vista embaixo (no editor ela sai de cena, para o vídeo ocupar a
janela). Na de download, no espírito do ATubeCatcher: endereço e destino no topo,
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
- **Edição multipista** na aba **Editar**, com os gestos que o CapCut e o
  Filmora tornaram padrão:
  - **Várias trilhas** de vídeo, imagem e áudio, empilhadas — a de baixo é o
    fundo, as de cima sobrepõem.
  - **Importar** vídeos, fotos e áudios para dentro da edição, arrastando ou
    pelo botão.
  - **Arrastar os blocos** no tempo e entre trilhas, com imantação nas pontas
    dos vizinhos e no cursor; alças para ajustar o corte de cada um.
  - **Volume por bloco em decibéis** e **mudo por trilha ou por bloco**.
  - **Separar o áudio** de um vídeo para uma trilha própria, e mexer nele
    sozinho.
  - **Copiar e colar** blocos, dividir no cursor, excluir, desfazer e refazer.
  - **Prévia retrátil** e **tela cheia** (tecla `F` ou duplo clique), com a
    barra de controles esmaecendo por inatividade.
  - Reprodução **com o som da mixagem** — todas as trilhas somadas, com os
    volumes e mudos aplicados — e navegação **quadro a quadro**.

  O que está na tela é a composição de verdade: o mesmo grafo do ffmpeg que
  exporta o arquivo desenha a prévia. E enquanto a edição for só um recorte de
  um arquivo, o **corte sem recodificar** continua disponível.
- **Playlists e canais** em lote, com seleção item a item.
- **Legendas** (inclusive automáticas), em arquivo separado ou embutidas.
- **Cookies do navegador** para mídias privadas, com restrição de idade, de
  assinantes, e para as resoluções altas do BiliBili.
- **Codificação pela placa de vídeo** (NVENC, Quick Sync, AMF, VAAPI), opcional,
  em *Configurações → Codificação de vídeo*. A opção escolhida é testada de
  verdade antes de ser usada — codificando um quadro — e cai para software
  sozinha quando a placa não responde, em vez de falhar a exportação no meio da
  fila. O padrão continua sendo software, que comprime melhor no mesmo tamanho
  de arquivo; a placa exporta várias vezes mais rápido.
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
chmod +x Video_Manager-0.4.0-x86_64.AppImage
./Video_Manager-0.4.0-x86_64.AppImage
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
./Video_Manager-0.4.0-x86_64.AppImage --appimage-extract-and-run
```

## Como o projeto está organizado

```
src/videomanager/
├── core/      lógica de mídia, sem nenhuma dependência de Qt
├── workers/   ponte para a interface: QRunnable + sinais
└── ui/        janela e painéis (PySide6)
```

A dependência é de mão única: `ui` → `workers` → `core`. É o que permite testar
toda a lógica de mídia sem abrir uma janela — os testes da suíte offline não
instanciam Qt nem tocam a rede.

### Os módulos que importam

O trabalho difícil não está na interface, e sim em três arquivos.

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

**`core/trimmer.py`** é o recorte, e vive do fato de que vídeo comprimido só
pode ser cortado sem recodificar **num keyframe** — quadros completos que
aparecem a cada poucos segundos; entre eles há apenas diferenças, que sozinhas
não formam imagem. Daí as duas saídas honestas, e as duas na tela:

- **Corte exato**, que recodifica o trecho e começa no quadro marcado;
- **Corte rápido**, que copia os dados como estão — sai em segundos, sem perda
  nenhuma, mas começa no keyframe anterior.

O aplicativo mapeia os keyframes com o ffprobe (só demultiplexando, sem
decodificar) e **anuncia o ponto real do corte antes de enfileirar**: “sem
recodificar, o corte vai começar em 0:00:04,000 — 1,30 s antes do ponto
marcado”. As marcas aparecem na linha do tempo e o arrasto se imanta nelas, o
que permite escolher um corte instantâneo e exato de propósito.

A prévia e as miniaturas saem do próprio ffmpeg, em quadros crus, e não de um
player: um player entrega o quadro que conseguir — normalmente o keyframe mais
próximo —, e aqui o que está na tela precisa ser exatamente o quadro do corte.

**`core/composer.py`** monta a edição inteira num grafo de filtros do ffmpeg, e
esse **mesmo grafo serve três usos**: exportar o arquivo, desenhar o quadro
parado da prévia e alimentar a reprodução. A consequência é a que importa —
trilha sobreposta, vão preto, volume em decibéis e mudo aparecem na tela como
vão aparecer no resultado, em vez de só na hora de exportar.

O som segue o mesmo caminho: o compositor produz a mixagem em PCM e um
`QAudioSink` toca. Um player de arquivo não daria conta, porque uma edição com
duas trilhas de áudio não é um arquivo. E enquanto a prévia roda, **o relógio é
o áudio** — o ouvido percebe um engasgo de vinte milissegundos, o olho não
percebe um quadro repetido —, com a imagem se corrigindo contra ele.

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
