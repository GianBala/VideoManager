# Decisões de projeto

Os algoritmos e as regras por trás das principais escolhas do Video Manager, com
o motivo de cada uma. Os caminhos são relativos a `src/videomanager/`; para o
mapa de todos os módulos, veja o [catálogo](clean-architecture/modulos.md).

## Normalizar cada extrator

**`infrastructure/yt_dlp/formats.py`** normaliza a resposta crua de cada extrator. Cada
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

Mais detalhes em [Análise de URL e downloads](clean-architecture/downloads.md).

## Traduzir a escolha em opções do yt-dlp

**`infrastructure/yt_dlp/selector.py`** traduz a escolha em opções do yt-dlp, sob duas regras:

- **Filtros não-estritos.** Todo limite sai como `[height<=?720]`. O `?` impede
  que formatos sem aquele campo sejam descartados. Sem ele, pedir “no máximo
  30 fps” elimina todos os formatos de sites que não informam `fps` — ou seja,
  quase tudo fora do YouTube.
- **Nunca recodificar sem consentimento.** Quando o container pedido não aceita o
  codec escolhido, a saída é **trocar de stream** (sem perda, mesma qualidade) ou
  **trocar de container** — nunca recodificar por conta própria. Toda substituição
  vira um aviso na tela, antes de o download começar.

## Cortar sem recodificar

**`infrastructure/ffmpeg/trimmer.py`** é o recorte, e vive do fato de que vídeo comprimido só
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

Mais detalhes em [Conversão e exportação](clean-architecture/processamento.md#corte-rápido-e-corte-exato).

## Um grafo do ffmpeg para a prévia e para o arquivo

**`infrastructure/ffmpeg/composer.py`** monta a edição inteira num grafo de filtros do ffmpeg, e
esse **mesmo grafo serve três usos**: exportar o arquivo, desenhar o quadro
parado da prévia e alimentar a reprodução. A consequência é a que importa —
trilha sobreposta, vão preto, volume em decibéis e mudo aparecem na tela como
vão aparecer no resultado, em vez de só na hora de exportar.

Animações seguem a mesma regra: os quadros-chave viram expressões que o ffmpeg
avalia a cada quadro (escala, rotação, posição e opacidade), e por isso a prévia
e o arquivo exportado se movem igual.

O som segue o mesmo caminho: o compositor produz a mixagem em PCM e um
`QAudioSink` toca. Um player de arquivo não daria conta, porque uma edição com
duas trilhas de áudio não é um arquivo. E enquanto a prévia roda, **o relógio é
o áudio** — o ouvido percebe um engasgo de vinte milissegundos, o olho não
percebe um quadro repetido —, com a imagem se corrigindo contra ele.

Mais detalhes em [Conversão e exportação](clean-architecture/processamento.md#um-compositor-para-todos-os-consumidores)
e em [Prévia, áudio e texto](clean-architecture/previa.md).

## Fixtures reais em vez de suposições

O que sustenta a promessa de funcionar em plataformas diversas são **fixtures
reais** — respostas de extratores capturadas em `tests/fixtures/`, cada uma
escolhida por expor uma estrutura diferente (ver o [README de lá](../tests/fixtures/README.md)).
Sobre elas se afirma o que precisa valer para qualquer extrator: nada de
storyboards vazando, nada de exceção com campo nulo, nenhuma mídia baixável
resultando em zero opções.

Além disso, cada expressão de formato gerada é submetida ao **parser real do
yt-dlp**. Um erro de sintaxe no `~=` ou no `<=?` não apareceria em nenhum teste de
comparação de strings — apareceria no primeiro download do usuário. Veja
[Testes e regras de dependência](clean-architecture/testes.md).
