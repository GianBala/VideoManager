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
último quadro — com fonte e projeto na mesma taxa. Com taxas diferentes
(medido em 24→30 e 60→30 q/s) o quadro parado pode ficar a um quadro de origem
da exportação, o mesmo desvio que o bloco normal já tem: o filtro `fps` da
exportação arredonda de outro jeito que a grade da fonte.

**O `reverse` guarda todos os quadros do trecho, então o bloco é lido em janelas,
uma por processo.** Medido (1080p, 30 q/s): 422 MB para 3 s, 700 MB para 6 s,
1203 MB para 12 s — 87 MB por segundo. Ao contrário do `minterpolate`, o custo
cresce com a duração, e **não dá para limitar dentro de um processo**: cortar o
bloco em pedaços no mesmo grafo não ajuda, porque o ffmpeg abre todos e cada
`reverse` lê o pedaço inteiro logo no começo (cinco pedaços de 4 s gastaram
3,8 GB, mais que um bloco de 20 s; `concat` e o filtro `movie` deram no mesmo, e
com 30 pedaços o kernel matou o processo). Só limita uma janela por processo, em
sequência. A primeira versão desta funcionalidade recusava o bloco acima de
~11 s, e foi o primeiro vídeo importado que a derrubou: era uma funcionalidade
que só servia para clipes de efeito.

`render_cost.reverse_cuts` decide onde cortar. Cada janela cabe em
`MAX_REVERSE_BYTES` (1 GiB, pela conta do pior caso de 3 bytes por pixel) **com
todos os blocos invertidos que a cruzam somados**, porque os `reverse` de blocos
simultâneos vivem juntos; o corte cai na grade de quadros (uma janela que
termina no meio de um quadro faria a seguinte repetir ou perder um) e pula, em
vez de repetir, o trecho em que nada invertido toca. Dois consumidores:

- **Exportação.** `parallel.reversal_bounds` entrega as janelas ao
  `ParallelExport`, com uma vaga só: cada janela é um arquivo de vídeo, as
  janelas se emendam copiando os dados, e o som, que pesa 384 KB por segundo,
  sai num passe só. É o mesmo caminho da interpolação paralela, o que dispensou
  uma segunda máquina de trechos. Medido em 60 s de 1080p: 17 s, 1800 quadros,
  pico de 1,8 GB no maior processo (1,3 GB sem inversão nenhuma, que é o que o
  codificador e o grafo já pesam). O GIF monta uma paleta sobre o fluxo inteiro e
  não se divide: `composer.check_reversal` o recusa, com o nome do bloco que
  mais pesa (o primeiro invertido mandava dividir o bloco errado).

  **Limite conhecido: interpolação + janelas.** `Converter.run` entrega as
  janelas ao `ParallelExport` com uma vaga e **não consulta** `plan_segments`;
  com **Interpolar movimento** ligado, cada janela interpola sozinha (o
  `minterpolate` usa um núcleo só), então a divisão da interpolação em trechos
  paralelos — 17× o tempo normal contra 45× sem dividir — não vale para quem
  inverte um bloco grande. Escolha por ora, não medida nesta combinação: abrir as
  janelas em paralelo somaria a memória do `reverse` à do `minterpolate` (1,6 GB
  a 1080p), a conta que já derrubou a máquina uma vez. Antes de combinar, medir
  o pico com os dois juntos.
- **Reprodução, som e cache da agulha.** A janela da prévia é de 8 s, e menor
  que isso quando a memória manda (metade do orçamento, porque duas janelas
  vivem juntas): o `reverse` só entrega o primeiro quadro depois de ler a janela
  inteira, então janela curta é reprodução que começa logo. `Stages`
  (`infrastructure/ffmpeg/stages.py`) faz vários comandos parecerem **um fluxo
  só** para quem lê quadros ou PCM, e abre a janela seguinte quando a atual passa
  da metade — não antes, para uma prévia pausada, com o primeiro quadro já
  lido, não ter duas janelas na memória. O painel não sabe de nada: `FramePump`
  e `AudioPreview` só trocaram `Popen` por `open_process`. O cache da agulha
  pede só a primeira janela, e o painel volta a pedir o que falta. Medido, 60 s
  de 1080p invertido: 0,17 s até o primeiro quadro, maior intervalo entre
  quadros de 34 ms atravessando 21 emendas e 389 MB no maior processo.

**Ler mais cedo e não passar `-ss 0` num bloco invertido.** Depois de um `-ss` o
primeiro quadro de áudio do AAC sai sem o vizinho de que precisa: cerca de 1000
amostras atenuadas (medido: 995 a 1001 antes de cada emenda de janela). Num bloco
normal isso fica no começo do bloco; num invertido a leitura começa no **fim** do
que toca, e cada janela abria um estalo no meio do som. `_PREROLL` (0,25 s) lê
mais cedo e `trim`/`atrim` descartam a sobra: 0 amostra errada nas emendas, som
das janelas idêntico ao de um passe só. E um `-ss 0` **não** é "não buscar": o
ffmpeg entrega as primeiras 576 amostras zeradas, então a leitura que começa em
zero vai sem `-ss`. O bloco normal tem os dois defeitos e não foi tocado
(diferença não pedida, e o retrato de comandos tem de continuar idêntico).

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

## O volume animado

**A curva é do quadro-chave e é relativa** (`Keyframe.gain_offset_db`, em dB). O volume ouvido num instante é
`Clip.gain_db` mais a curva, limitado a −60/+12 dB (`Clip.gain_at`). Relativa, e não absoluta como a
opacidade, por três razões: com 0 a curva não mexe, então todo quadro-chave antigo continua neutro sem migrar
valor nenhum; o 🔊 da barra continua sendo o volume do bloco inteiro, e não um ponto de animação; e um preset
ou um quadro criado sem pensar em som nunca **cria** volume (os pontos do preset são neutros; ele **troca** a curva
do bloco, como o fim desta seção registra). Por isso o campo se chama `gain_offset_db`, e não
`gain_db`: o mesmo nome convidaria a tratá-lo como absoluto, como o `opacity` do quadro.

**Os mesmos quadros-chave, não uma trilha de volume à parte.** É o "mesmo painel e mecanismo" que se pediu, e
dividir, aparar, mudar a velocidade, colar e desfazer funcionam sem código novo, porque todas já tratam
`Clip.keyframes`. A consequência é que um ponto de volume também fixa a pose daquele instante (se a imagem é
animada, a curva da pose passa por ele); `Keyframe.from_pose` faz o quadro nascer da pose **com** o volume
interpolado, e mexer na posição de um ponto preserva o volume dele — montar o quadro campo a campo zerava o
volume de quem só movia a imagem. A trilha separada evitaria isso, mas custaria um segundo caminho em todas as
operações e uma ◇ ambígua.

**Fade de som não anima a imagem.** Com os dois no mesmo quadro-chave, um bloco que só tem curva de volume
deixaria de ser "sem quadros-chave" e o primeiro gesto na imagem criaria um ponto de pose: o bloco, em vez de se
mover, ia e voltava (x: 0,5 → 0,8 → 0,5). `Clip.has_pose_keyframes` já separava os dois para o compositor; a edição
(`with_edited_transform`, que a aba e o arrasto na prévia usam) passa a perguntar o mesmo: sem pose animada, a
edição fora de um ponto vale para o bloco inteiro e os pontos de volume andam junto (a pose deles é a do bloco).
**Sobre um ponto (◇ aceso) a edição continua sendo dele**, e começa a animar a imagem — sem essa saída, um bloco com
fade de som nunca poderia ter imagem animada, porque o Efeito Rápido troca a curva de volume. O que ficou: o ◇ aceso
é o alvo da edição, e quem acabou de digitar um volume com o cursor sobre o ponto novo e arrasta a imagem ali cria
animação (visível: o ◇ está aceso, e há um losango na linha do tempo). Medido contra a versão anterior em 3000
edições aleatórias, só mudou o caso descrito.

**A velocidade não anima.** Ela muda a duração do bloco; uma curva dela mudaria o tamanho da trilha a cada
ponto. Mudar a velocidade continua reescalando o tempo dos pontos, e a curva de volume acompanha o conteúdo.

**No compositor** (`composer._gain_filter`): sem curva o filtro é o de sempre (`volume=-6.00dB`, comando
idêntico); com curva, `volume='pow(10,max(-60,min(12,G+(CURVA)))/20)':eval=frame`, com a curva montada por
`_keyframe_expr` (a mesma da imagem) e reavaliada a cada quadro de áudio, como os fades. O relógio `t` do
filtro conta desde o começo do trecho lido, então a origem é `-piece.elapsed` (uma janela de bloco invertido, a
prévia a partir do meio) e, na transição, `-_side_elapsed(side)` — antes do `adelay` da alça, que vem depois. A
**interpolação é em dB**, como a automação de volume dos editores de referência: em amplitude a passagem soa
desigual. O mesmo grafo serve à prévia sonora e à exportação.

**A imagem decide o caminho por `Clip.has_pose_keyframes`, não por `has_keyframes`.** O compositor escolhe entre
o caminho barato (`scale` + `pad`) e o das transformações (`scale` e `overlay` com `eval=frame`) pela presença
de quadros-chave; um fade de som num vídeo o tiraria do caminho barato sem que a imagem mudasse. Sem curva de
volume `has_pose_keyframes == has_keyframes`, e o comando de todo projeto antigo sai igual (medido: 9600
comparações em projetos aleatórios, 0 diferenças). O corte contínuo (duas metades da mesma mídia que seguem sem
transição de som) compara o volume **ouvido** nos dois lados, e não só o `gain_db`.

**Separar áudio leva a curva** para o bloco de som e a tira do vídeo, que fica só com a pose (e sem
quadros-chave se a animação era só de volume): o som sai do bloco de vídeo, e o volume com ele.

**No arquivo**, o `.vmp` versão 6 grava `gain_offset_db` em cada quadro-chave. Um v5 abre com a curva zerada e
ganha a cópia `.v5.bak` ao ser salvo; a versão anterior recusa o v6 com mensagem. Sem subir a versão, ela abriria
o arquivo, ignoraria a chave e apagaria a curva ao salvar.

**Efeito Rápido troca a curva de volume junto** com a pose (como o guia já dizia, "troca os quadros-chave"):
preservar a curva seria parcial e mais complexo. Num bloco de áudio só "remover animações" faz sentido, e a
lista filtra o resto. **Fica de fora, por ora:** arrastar losangos na linha do tempo e um selo no bloco que
indique a curva (`gain_label` mostra só o volume do bloco).

## Medir o tamanho em vez de calculá-lo

**`domain/size_model.py`** e **`infrastructure/ffmpeg/sample.py`**. O tamanho que o aplicativo anuncia para tudo o que
recodifica sai de trechos codificados de verdade com o mesmo comando da conversão, e não de uma fórmula: o que um
encoder gasta depende do conteúdo, e a fórmula errava de −66% a +1500% (o mesmo H.264 em CRF 20 saiu de 0,03× a 2,5× o
bitrate da fonte). A conta que leva o trecho ao arquivo todo é a de uma pesquisa por amostragem — **estratos** (nenhuma
região fica de fora), **trecho representativo** de cada estrato pela curva de bytes da fonte e **estimador de razão** —,
e a cobertura cresce com a velocidade do encoder, medida por um piloto: o arquivo que cabe em 20 s de relógio é
codificado inteiro. Erro medido em 10 vídeos inteiros: mediana de 0,5% a 1% e pior caso de 6% (a amostra fixa
anterior: mediana de 4% a 11%, pior caso de −33% a +29%, e −99,9% numa fonte pesada só no começo).

Duas regras que o número depende: soma-se os bytes dos **pacotes** (`ffprobe`), nunca o tamanho do arquivo do trecho,
cujo container distorce; e o `start_time` do `ffprobe` vem **depois** dos pacotes na saída e precisa ser descontado
(TS e câmeras não começam em zero). Quando a medida falha, a conta antiga volta **marcada como aproximada** e a tela não
afirma que o arquivo cresce nem que encolhe. Método, números e limites em
[Estimativas de tamanho](estimativas-de-tamanho.md).

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
