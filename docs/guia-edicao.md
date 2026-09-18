# Aba Editar

Editor multipista com os gestos que CapCut e Filmora tornaram padrão: prévia
em cima, trilhas empilhadas embaixo, blocos que se arrastam no tempo e entre
trilhas. **O que está nas trilhas é o que vai ser exportado** — não há marca
de entrada/saída escondida num formulário à parte.

A janela reúne os comandos de projeto e exportação no topo, acervo e Adicionais
ao lado da prévia e, abaixo, a linha do tempo. O divisor entre a prévia e
a linha do tempo é livre — arraste para dar mais espaço a quem
precisar dele naquele momento; **"Retrair prévia"** é só o atalho para o
extremo mais pedido (linha do tempo ocupando quase tudo).

Em janelas estreitas, a barra horizontal na base da aba permite alcançar as
colunas laterais. Propriedades também oferece rolagem quando seus campos não
cabem no painel.

## Importando mídia

No acervo de mídia à esquerda:

- **Importar** abre o seletor de arquivos (vídeo, foto ou áudio). Arquivos
  arrastados para o acervo ou para outra área da aba também são importados.
  **Importar não coloca nada na edição**: a mídia fica no acervo.
- A lista do acervo mostra tudo já importado nesta sessão de edição. A
  miniatura de um vídeo é o quadro do **meio** dele, que representa o conteúdo
  melhor que o primeiro (quase sempre preto ou um título). Arquivos exportados
  e convertidos também recebem como capa o quadro do meio.
- **Arrastar um cartão do acervo até a linha do tempo** coloca a mídia na
  trilha e no instante em que ela for solta, com o mesmo ímã dos blocos. Um
  bloco fantasma mostra onde ela vai cair. Se a trilha sob o ponteiro não
  aceitar a mídia, ou se ela cair em cima de outro bloco, nasce uma trilha nova
  ali — nada do que já está na edição é empurrado. Várias mídias entram em
  sequência. Arrastar arquivos do sistema direto para a linha do tempo importa
  e coloca no ponto de soltura. Tudo isso é um único passo de desfazer.
- **Inserir no cursor** (ou duplo clique no cartão) — coloca a mídia na posição
  atual, numa trilha compatível, visível e com som habilitado quando necessário;
  cria outra se não houver espaço.

Fotos entram na **trilha de vídeo**, como um vídeo: ajustam-se à tela (ampliadas
ou reduzidas, sem deformar), podem formar corte e transição com o vídeo vizinho
e aceitam posição, escala, rotação, opacidade e animação a partir desse tamanho.
Uma foto numa trilha de vídeo acima de outra funciona como sobreposição
(logotipo, moldura). Velocidade não se aplica a fotos. **Adicionais** ficam com
textos e filtros.

Em montagens somente de fotos, **Slideshow** sugere a tela pelas dimensões das
imagens, limitada a 1920 pixels no maior lado. A escolha é explícita; fotos não
mudam automaticamente a tela.

Com a linha do tempo vazia, a prévia mostra: *"Importe vídeos, fotos ou
áudios para montar a edição. Você também pode arrastar os arquivos para
cá."*

## Prévia e transporte

A prévia solicita o quadro da posição do cursor e usa o mesmo compositor da
exportação. Durante uma atualização, conserva o último quadro entregue e mostra
a indicação de carregamento. Ao arrastar um objeto, usa camadas preparadas para
responder diretamente ao mouse e confirma o resultado com o compositor ao
soltar. Com transições ou filtros que dependem do objeto e das camadas inferiores,
apresenta versões completas conforme ficam prontas. A indicação de carregamento
termina quando a versão final chega (ver
[`arquitetura.md`](arquitetura.md)).

Arrastar a agulha responde na hora: em segundo plano, com prioridade baixa, a
prévia guarda versões menores dos quadros em volta da agulha, e é uma delas que
aparece durante o arrasto. Ao parar ou soltar, chega o quadro exato. Depois de
uma edição, só o trecho afetado volta a ser preparado.

Abaixo da imagem, a barra de transporte:

| Controle | Atalho | Ação |
|---|---|---|
| Ir ao início | — | volta o cursor para `0:00` |
| Voltar 1s | — | recua um segundo |
| Quadro anterior | `,` | recua um quadro |
| **Reproduzir/Pausar** | `Espaço` | alterna reprodução |
| Próximo quadro | `.` | avança um quadro |
| Avançar 1s | — | avança um segundo |
| Ir ao fim | — | vai para o fim da edição |
| ◁ keyframe / keyframe ▷ | — | pula para o ponto de corte rápido mais próximo, antes/depois do cursor |

Com **Loop** marcado, a reprodução volta ao começo sem corte: um pouco antes do
fim, imagem e som do começo já ficam prontos, e o som é emendado na mesma saída
de áudio. A volta acontece no fim do que se vê e se ouve (o mesmo fim do arquivo
exportado). Um bloco de vídeo nunca termina em preto por causa de sobra no
arquivo: blocos novos duram exatamente a trilha de vídeo, e os de projetos
antigos seguram o último quadro.

Ao lado, um botão de mudo e um controle de volume regulam **apenas a prévia**
(não afetam o volume dos blocos nem o resultado exportado).

O relógio de posição e o contador de quadros usam fonte monoespaçada com
largura travada no maior valor daquele projeto, para a barra inteira não
tremer a cada troca de dígito durante a reprodução.

## A linha do tempo

### Barra de ferramentas da linha do tempo

Da esquerda para a direita:

1. **Desfazer** (`Ctrl+Z`) / **Refazer** (`Ctrl+Shift+Z` ou `Ctrl+Y`).
2. Tesoura **Dividir** (`S` ou `Ctrl+B`) — corta o bloco selecionado no ponto
   do cursor.
3. **Apagar à esquerda** (`Q`) — remove o trecho do bloco antes do cursor.
4. **Apagar à direita** (`W`) — remove o trecho do bloco depois do cursor.

   Os três agem sobre o bloco **selecionado** e ficam habilitados só quando o
   cursor está dentro dele; o estado acompanha o cursor também durante a
   reprodução, então dá para tocar, pausar no ponto e cortar.
5. Lixeira **Excluir bloco** (`Del`).
6. Contador de trilhas/blocos/duração total do projeto.
7. Nome do bloco selecionado.
8. **Volume do bloco** — spinbox em decibéis; só habilitado quando o bloco
   tem som próprio ajustável (um bloco de vídeo com o áudio já separado para
   outra trilha não tem mais volume próprio ali).
9. Zoom: **−** / **+** / **Ver tudo** (enquadra o projeto inteiro na largura
   visível).

### Gestos com o mouse

- **Arrastar o corpo de um bloco** — move entre posições e entre trilhas,
  com imã (*snap*) no cursor de reprodução, nas bordas de outros blocos e no
  início da linha do tempo. Se a ponta da frente do bloco arrastado passar do
  **meio** de um vizinho, os dois **trocam de lugar**, sem sobrepor um
  terceiro. O intervalo vazio entre o par é preservado.
- **Arrastar as pontas (alças)** de um bloco — ajusta o corte daquele lado,
  com o mesmo imã.
- **Clique simples** no vazio da trilha ou na régua de tempo — move o cursor
  de reprodução para ali. Na trilha vazia a seleção é desfeita; **na régua ela
  é mantida**, para posicionar o corte do bloco escolhido (por exemplo, um
  áudio abaixo de um vídeo). Barras de rolagem e divisórias também não
  desfazem a seleção.
- **Botão direito** — abre o menu de contexto (ver abaixo), relativo ao que
  está sob o cursor.
- **Botão do meio, arrastando** — paneia a vista horizontalmente.
- **Roda do mouse** — desloca verticalmente pelas trilhas. A régua de tempo e a
  cabeça da agulha ficam **fixas no topo**: com mais trilhas do que cabem, as
  trilhas rolam por baixo da régua e uma barra vertical aparece ao lado.
  Arrastar um bloco ou o cabeçalho de uma trilha até a borda de cima ou de
  baixo rola sozinho, para alcançar trilhas fora da vista.
- **Shift + roda** — desloca a vista horizontalmente sem mudar o zoom.
- **Ctrl + roda** — zoom, centrado na posição do ponteiro. Ctrl prevalece
  quando Shift também estiver pressionado.
- **Duplo clique num bloco** — enquadra aquele bloco na largura visível.
- **Clique no "M" do cabeçalho de uma trilha** — muda/desmuda a trilha
  inteira.
- **Arrastar o cabeçalho de uma trilha** — muda a posição dela na pilha, para
  qualquer lugar e com qualquer espécie (vídeo, adicionais ou áudio). Entre
  trilhas de vídeo e de adicionais, **a que está mais acima aparece por cima**
  na prévia e na exportação: um texto numa trilha abaixo de um vídeo fica
  coberto por ele, e um filtro só age sobre o que está abaixo da trilha dele.
  A posição do áudio não muda o som, só a organização.

Um clique isolado nunca conta como edição: só a partir de alguns pixels de
arrasto é que a ação entra na pilha de desfazer — selecionar um bloco sem
mover nada não empilha um "desfazer" vazio.
Escape cancela um arrasto da timeline ou da prévia. Perder a captura do mouse
ou ocultar a área durante o gesto também cancela a operação incompleta.

### Transições

Uma transição pertence ao corte entre dois blocos de vídeo encostados. Para
escolher exatamente a trilha quando várias têm cortes no mesmo instante,
selecione um dos dois blocos dessa trilha antes de inserir o efeito. A transição
será ligada àquele par. Se nenhum bloco estiver selecionado, o editor usa o
corte válido mais próximo do cursor, preservando o comportamento automático.

O marcador permanece centralizado no corte. Arrastar uma de suas bordas aumenta
ou reduz os dois lados simetricamente; o mínimo é 0,2 s e o máximo é limitado
pela duração dos blocos conectados. Sua largura visual tem um alvo mínimo para
facilitar a seleção em zoom distante, sem alterar a duração renderizada. Excluir
ou afastar uma das pontas remove a transição ligada, em vez de associá-la
silenciosamente a outro corte.

Quando existem amostras de mídia além das bordas cortadas, vídeo e áudio usam
essas alças durante a passagem. Sem alça de áudio suficiente, o editor preserva
o corte original e aplica apenas uma curva curta contra estalos; não cria um
buraco de silêncio para acompanhar o efeito visual.

Também é possível dividir um vídeo com a tesoura e aplicar a transição no
novo corte. O editor usa momentos diferentes das duas partes para que Fade,
Dissolve, Wipe e Slide não desapareçam por misturar duas cópias do mesmo quadro.
O movimento permanece contínuo nas extremidades e o áudio original não é
duplicado durante essa passagem.

Marque **Afetar itens adicionais** para incluir filtros e textos das trilhas de
Adicionais **acima** da transição no efeito. Um item que termina exatamente no corte desaparece com o vídeo da
esquerda; um que começa ali aparece com o vídeo da direita; um item que continua
pelos dois lados permanece visível sem piscar. Deixe desmarcado quando títulos,
logotipos ou filtros devam ficar estáveis acima da transição. A opção também
fica disponível nas propriedades do marcador e é salva no projeto.
Com duas passagens simultâneas habilitadas, a da trilha de vídeo mais alta
controla cada adicional, preservando sua posição na pilha e sem duplicar o efeito.

### Texto e animação

Ao mudar posição, escala, rotação ou opacidade de um clipe animado, o editor
altera o instante atual. Marque **Editar toda a animação** para ajustar a curva
inteira. Cortar ou aparar preserva a interpolação do trecho restante.

A digitação é agrupada no histórico do projeto até 1,2 s sem escrever, troca
de campo ou outro comando. Dentro do campo, os atalhos de edição do texto
continuam disponíveis. Alterar a resolução de saída mantendo a proporção
preserva tamanho e posição relativos do texto, incluindo contorno e animação.

Projetos são salvos em `.vmp` versão 3. A versão atual abre v1, v2 e v3;
aplicativos antigos não abrem v3. Ao salvar sobre v1 ou v2, uma cópia
`.vmp.v1.bak` ou `.vmp.v2.bak` conserva o arquivo original, com numeração se
necessário. Guarde também as mídias externas.

Ao abrir um projeto v1 ou v2, fotos que estavam em trilhas de Adicionais passam
para trilhas de vídeo na mesma posição da pilha — a trilha inteira, se só tinha
fotos, ou uma trilha de vídeo nova logo acima, se também tinha textos ou
filtros. A escala é convertida para a foto continuar do mesmo tamanho e no mesmo
lugar. Única diferença conhecida: numa transição com **Afetar itens adicionais**
marcado, essas fotos deixam de participar do efeito e ficam estáveis por cima.

### Menu de contexto (botão direito)

O conteúdo muda conforme o alvo sob o cursor:

**Sobre um bloco:**
- Dividir (`S`)
- Apagar à esquerda (`Q`) / Apagar à direita (`W`) — só aparecem habilitados
  quando o corte ali é possível
- Copiar (`Ctrl+C`)
- Excluir bloco (`Del`)
- *separador*
- **Separar áudio** — só quando o bloco tem áudio embutido ainda não
  separado; cria um bloco de áudio independente na trilha de som, e o volume
  do bloco original passa a não fazer mais efeito (o som agora vive no bloco
  novo)
- **Bloco mudo** / **Voltar o som do bloco**

**Sobre um espaço vazio, com algo copiado antes:**
- **Colar** (`Ctrl+V`)

**Sobre o cabeçalho de uma trilha:**
- **Calar a trilha** / **Voltar o som da trilha**
- **Excluir a trilha "{nome}"** — se a trilha tiver blocos, pede confirmação
  ("Excluir a trilha?"), lembrando que dá para desfazer com `Ctrl+Z`

**Sempre presentes, no fim do menu:**
- **Nova trilha de vídeo**
- **Nova trilha de áudio**

### Ordem das trilhas

A ordem na tela, de cima para baixo, é a ordem de composição: a trilha mais
**baixa** é o fundo, e as de cima sobrepõem — igual a qualquer editor de
consumo.

## Atalhos com o painel em foco

Válidos sempre que o foco não estiver dentro de um campo de texto, número ou
combo:

Salvar, salvar como, abrir, novo projeto, exportar e F11 continuam disponíveis
mesmo com um campo em edição. Letras simples e copiar/colar/desfazer respeitam
o campo que possui o foco.

| Tecla | Ação |
|---|---|
| `Espaço` | Reproduzir/Pausar |
| `,` / `.` | Quadro anterior/próximo |
| `S` / `Ctrl+B` | Dividir no cursor |
| `Q` / `W` | Apagar à esquerda/à direita do cursor |
| `Del` | Excluir bloco selecionado |
| `Ctrl+C` / `Ctrl+V` | Copiar/colar bloco |
| `Ctrl+Z` / `Ctrl+Shift+Z` ou `Ctrl+Y` | Desfazer/refazer |
| `F` / `F11` | Tela cheia |
| setas (com foco na linha do tempo) | andam quadro a quadro; `Shift`+seta anda 1 segundo |
| `Home` / `End` (idem) | vão para o início/fim |

## Tela cheia

Ative com **F**, **F11**, duplo clique na prévia, ou o botão **Tela cheia**.
A barra de controles some depois de 2,5 s sem movimento do mouse ou tecla —
reaparece a qualquer movimento, e nunca some enquanto o ponteiro está sobre
ela ou uma posição está sendo arrastada.

Controles da barra: Play/Pause, quadro anterior/próximo, tempo decorrido,
barra de posição (um clique salta direto para o ponto clicado), tempo total,
mudo + volume, e **Sair** (ou tecla `Esc`).

Atalhos exclusivos da tela cheia: `Espaço` play/pause; `←`/`,` e `→`/`.`
quadro a quadro; `↑`/`↓` sobem/descem o volume em 5.

## Exportando a edição

Os pacotes (Windows e Linux) trazem o próprio ffmpeg. Rodando pelo
código-fonte, vale o que estiver instalado — e com o ffmpeg 6 (o do Ubuntu
24.04) uma transição que atravessa um adicional **com filtro** perde esse
adicional durante a transição. A partir do ffmpeg 7 funciona.

Use **Exportar**, no topo do editor, para abrir as opções de saída. A tela do
projeto pode ser escolhida no seletor **Tela**, também no topo:

- **Tela** — tamanhos predefinidos (4K, 1440p, 1080p, 720p, 480p, e variantes
  verticais/quadradas) ou **"Automática · segue o material"**, que usa o
  maior bloco do projeto para decidir o tamanho (ver
  [`arquitetura.md`](arquitetura.md#projectpy--composerpy-o-editor)).
- **Taxa** — 24/25/30/50/60 fps, ou **Automática**. Com GIF escolhido,
  entram também 10, 12,5, 20 e 25 — taxas que cabem certo na forma como o GIF
  guarda a duração de cada quadro.
- **Formato de vídeo** — MP4, MKV, WebM, MOV ou **GIF animado**. O GIF sai em
  loop infinito e com 256 cores; ele não guarda som, então a trilha de áudio
  fica de fora, e não tem codec nem nível de qualidade para escolher (esses
  campos somem). Cada quadro de um GIF é uma imagem inteira: reduza a tela e
  fique entre 10 e 15 quadros por segundo, ou o arquivo cresce depressa.
- **Interpolar movimento** — gera quadros de verdade para blocos abaixo da
  taxa da tela, em vez de só duplicar o quadro anterior. Fica desabilitado
  quando nenhum bloco está abaixo da taxa escolhida. É uma opção cara — o
  aviso ao lado mostra o custo estimado de memória antes de confirmar, e a
  **prévia nunca usa interpolação** (ela é rápida demais para caber no ritmo
  da reprodução; só aparece no arquivo exportado).
- **Corte rápido (sem recodificar)** — só fica disponível quando a edição
  ainda é um recorte de um único arquivo, na ordem, sem volume alterado e sem
  trilha sobreposta. Nesse caso, exportar é instantâneo: os dados são
  copiados como estão, sem qualidade perdida.
- **"Salvar na mesma pasta do arquivo original"** — mesmo padrão da aba
  Convert.

O texto **"O que vai acontecer: {plano}"** resume o resultado antes de
confirmar, com um aviso extra quando aplicável: a memória estimada da
interpolação, a indisponibilidade do corte rápido para aquela edição, ou o
desvio real do ponto de corte em relação ao keyframe mais próximo (quando o
corte rápido está ativo mas o ponto marcado não cai exatamente num
keyframe).

**Adicionar à fila** enfileira a exportação junto com downloads e conversões
em andamento, na mesma [fila de tarefas](interface-geral.md#a-fila-de-tarefas)
— com a diferença de que, na aba Editar, a fila fica oculta e a janela
inteira permanece dedicada à edição; o progresso da exportação continua
visível na barra de status.
