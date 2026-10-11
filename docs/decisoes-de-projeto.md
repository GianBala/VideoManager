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

## O fundo desfocado do bloco

**Uma camada própria, opaca e de tela cheia por baixo do bloco**
(`Clip.blur_background`): o próprio bloco, ampliado até cobrir a tela e
desfocado, no lugar do preto das laterais. Fica por baixo da frente e por cima
das trilhas de baixo, **só na janela de tempo do bloco** — por isso cobre o que
estiver embaixo, e a opção nasce desligada. Acompanha a opacidade do bloco
(senão, num fade, a frente sumiria e o borrão ficaria na tela). O chroma key a
desliga, porque o borrão apareceria onde a cor foi removida, sem apagar a
escolha.

**Uma regra só decide se o fundo aparece** (`Clip.shows_blur_background`), e ela
é perguntada **uma vez** por grafo, com a tela de exportação
(`_blur_where_visible`). Um bloco que já preenche a tela em pose neutra — no
bloco, em cada quadro-chave e entre eles (um giro de 0° a 360° não é neutro) —
não ganha o ramo, e o arquivo sai byte a byte igual ao de antes. Perguntar pela
tela da prévia, arredondada para par, faria um clipe 16:9 deixar de "preencher"
só ali, e prévia e exportação discordariam. Prévia, exportação, transições e
arrasto leem a mesma resposta.

**O desfoque nasce pequeno.** O bloco é coberto à tela de trabalho (lado menor
136, sigma 6), borrado ali e só então ampliado: é uma mancha de cor, e desfocar
4K inteiro custa o que não se vê. Medido numa exportação de 5 s: com o `gblur`
em tamanho cheio ela leva 2,44 s a 1080p e 8,47 s a 4K; na tela de trabalho,
1,36 s e 4,69 s, com SSIM 0,998 contra o desfoque cheio. O lado menor fixo faz prévia e arquivo saírem do mesmo desenho
(com fração fixa ou sigma em pixels a prévia pequena divergia: SSIM 0,935 e
0,781). As duas ampliações são bilineares: o bicúbico gastava CPU num detalhe
que o desfoque já tirou.

O `gblur` roda num formato fixo e volta a `yuv420p` ainda pequeno. Sem isso ele
borrava os planos de cor de um vídeo na metade da resolução, e o fundo do vídeo
saía mais lavado que o da foto do mesmo quadro (6,5 a 13,4 de 255). Esse formato
não tem alfa, e a conversão o descartava: numa imagem com transparência o fundo
nascia da cor escondida sob o alfa, que depende de como o arquivo foi exportado.
O alfa é composto sobre preto antes da conversão; para fonte sem alfa nada muda.

**O fundo não passa pelo `minterpolate`** (o movimento some no desfoque, e
interpolar custaria memória sem mostrar nada) e leva o `fps` da tela no **fim**
do ramo: sem ele o último instante do bloco, numa tela de taxa maior que a da
fonte, caía depois do último quadro do fundo — um quadro preto nas laterais em
cada emenda, com duração e contagem de quadros certas (medido: o quadro 89 de 90).

**No arrasto, o fundo é a quarta imagem do worker** (`interaction_commands`):
ele cobre a tela e não depende da pose, então uma imagem serve o gesto todo, e
o Qt a pinta entre o que está por baixo e a textura, com a opacidade ao vivo e
só onde o quadro final a mostraria. Sem ela cada movimento caía num ffmpeg e a
imagem ficava 30,5 px atrás da mão; com ela o erro é o do gesto sem fundo (0,5
px).

**No arquivo**, o `.vmp` versão 4 grava `blur_background`. Um v3 abre com a
opção desligada e ganha a cópia `.v3.bak` ao ser salvo; a 3.1 recusa o v4 com
mensagem (ver o [formato .vmp](clean-architecture/editor.md#formato-vmp)).

Mais detalhes em [Prévia, áudio e texto](clean-architecture/previa.md) e em
[Conversão e exportação](clean-architecture/processamento.md).

## O bloco invertido

**Uma marca no bloco, não um arquivo novo** (`Clip.reversed`). O bloco continua
cobrindo o trecho `in_point`–`out_point` da mídia e a edição o percorre ao
contrário: o começo do bloco é o `out_point`. Inverter e desinverter são
instantâneos e desfazíveis, e nenhuma mídia derivada fica na pasta do usuário.
O preço é que **tudo que mexe numa ponta precisa saber o sentido**: aparar o
começo de um invertido tira do topo do trecho (o `in_point` fica), aparar o fim
tira da base e o `in_point` sobe; dividir dá o ponto novo à primeira metade da
edição; esticar para no começo ou no fim da mídia conforme o sentido
(`Project._head_reach` e `_tail_reach`). `Clip.source_time` já devolve o tempo
certo nos dois sentidos, e `head_point`/`tail_point` dizem onde o bloco começa e
termina **na edição**, que é o que a transição usa.

**O quadro que a exportação mostra, não o "mais perto" do tempo espelhado.** A
exportação lê o trecho, vira a lista de quadros e a coloca no relógio da edição
desde o começo do bloco. O quadro parado da prévia repete essa conta
(`_reversed_still_seek`): o `k`-ésimo quadro do relógio é o `k`-ésimo contado do
fim do trecho. Espelhar o instante e procurar o quadro mais perto errava por um
quadro nas bordas dos quadros da edição. O quadro parado também **não usa
`reverse`**: lê o quadro certo de frente, sem guardar nada. Medido contra a
exportação, 0 de diferença nos instantes testados, inclusive no primeiro e no
último quadro.

**O `reverse` guarda todos os quadros do trecho, e por isso há um teto.** Medido
(1080p, 30 q/s): 422 MB para 3 s, 700 MB para 6 s, 1203 MB para 12 s. Ao
contrário do `minterpolate`, o custo cresce com a duração. O teto é de 2 GiB por
bloco pela conta do pior caso (3 bytes por pixel, para 10 bits), o que dá ~11 s
em 1080p a 30 q/s. Três defesas: o menu não oferece a inversão acima dele
(`Clip.can_reverse`, com o motivo na dica); as alças de um bloco invertido não
o ultrapassam (`Clip.reverse_limit`); e `composer.check_reversal` recusa a
exportação, com o número, de um projeto que ainda assim o passe — arquivo
editado à mão, mídia que mudou. **A prévia não recusa**: ela monta o comando na
thread da interface, onde uma exceção não tem quem a mostre. Dividir o trecho em
vários processos para vencer o teto ficou de fora: exigiria renderizar pedaços
intermediários, como a exportação paralela, e o uso comum — cortar e inverter
trechos curtos — não precisa.

**Lado invertido de uma transição lê um quadro antes.** A janela da transição
começa no meio de um quadro, e a regra do `-ss` descarta o quadro que a
atravessa na ponta de **entrada**. Lida para baixo, a ponta que abre a transição
é a de cima, e ali o mesmo quadro entrava: o cross-fade repetia um quadro no
começo. `_transition_side` recua a leitura quase um quadro (`_FRAME_EDGE` mantém
a regra certa quando a janela cai na grade) e o som descarta a sobra
(`atrim=start`). Medido contra o mesmo projeto montado com um arquivo invertido
de verdade: antes, 12 de 90 quadros divergiam; depois, nenhum, nos três
arranjos (os dois invertidos, só o da esquerda, só o da direita).

**No arquivo**, o `.vmp` versão 5 grava `reversed`. Um v4 abre com o bloco no
sentido normal e ganha a cópia `.v4.bak` ao ser salvo; a versão anterior recusa
o v5 com mensagem. Imagem, texto, filtro e transição nunca ficam invertidos,
mesmo num arquivo editado à mão.

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
