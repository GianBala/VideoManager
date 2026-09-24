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

A barra do topo traz, da esquerda para a direita: **Novo**, **Abrir…**,
**Salvar** e **Salvar como…**; o nome do projeto, com um asterisco enquanto há
alterações não salvas; **Slideshow**, **Proporção** e **Tela** (ver
[Exportando a edição](#exportando-a-edição) para o que cada uma decide);
**Retrair prévia**, **Tela cheia** e **Exportar**.

A coluna de Adicionais já abre com a largura da aba Propriedades, e abrir a
aba devolve essa largura a uma coluna que tenha sido estreitada, quando a
janela tem espaço para isso. Em janelas estreitas, a barra horizontal na base
da aba permite alcançar as colunas laterais. Propriedades também oferece
rolagem quando seus campos não cabem no painel.

## Projetos

Um projeto é um arquivo `.vmp`: a montagem (trilhas, blocos, ajustes) e o
caminho das mídias, sem os bytes delas. Mover só o `.vmp` não move os vídeos;
caminhos relativos são resolvidos a partir da pasta do projeto.

| Comando | Atalho | O que faz |
|---|---|---|
| **Novo** | `Ctrl+N` | Esvazia a edição (pergunta antes de descartar alterações). |
| **Abrir…** | `Ctrl+O` | Abre um `.vmp`; mídias que sumiram são listadas, e a montagem é preservada. |
| **Salvar** | `Ctrl+S` | Grava no arquivo atual, ou pergunta onde, se o projeto ainda não tem um. |
| **Salvar como…** | `Ctrl+Shift+S` | Grava uma cópia em outro `.vmp` e passa a editar essa cópia, com o histórico de desfazer e o estado atual da edição intactos. |

Os mesmos comandos, mais **Importar mídia…** (`Ctrl+I`) e **Exportar vídeo…**
(`Ctrl+E`), estão no menu **Arquivo** enquanto a aba Editar está à vista. Salvar
e Salvar como funcionam mesmo com o cursor num campo de texto; antes de gravar,
o editor fecha os agrupamentos de desfazer em andamento, para o arquivo conter
o que está na tela.

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

## Importando mídia

No acervo de mídia à esquerda:

- **Importar** (ou `Ctrl+I`) abre o seletor de arquivos (vídeo, foto ou áudio).
  Arquivos arrastados para o acervo ou para outra área da aba também são
  importados. **Importar não coloca nada na edição**: a mídia fica no acervo.
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

Numa janela estreita (tela de notebook, ou escala de 125% ou mais no Windows),
os controles da direita da barra — keyframe, Loop, ímã e volume — descem para
uma segunda linha, as listas de tela e proporção encolhem e as abas de
Adicionais rolam por dentro: a aba inteira cabe a partir de 1280 × 720 sem
rolagem lateral.

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
6. **+ Vídeo**, **+ Áudio** e **+ Adicionais** — criam uma trilha nova do tipo.
   A de vídeo entra acima da trilha de vídeo mais alta; a de adicionais, no
   topo; a de áudio, no fim. O número do nome é o primeiro livre entre os
   "Vídeo N" existentes: apagar a "Vídeo 2" e criar outra devolve "Vídeo 2",
   e um nome que você escolheu não entra na conta.
7. Contador de trilhas/blocos/duração total do projeto.
8. Nome do bloco selecionado.
9. **Volume do bloco** (`🔊`) — abre um painel com o ganho em decibéis; só fica
   habilitado quando o bloco tem som próprio ajustável (um bloco de vídeo com
   o áudio já separado para outra trilha não tem mais volume próprio ali).
10. **Velocidade do bloco** (`⚡`) — ver [Velocidade e volume do bloco](#velocidade-e-volume-do-bloco).
11. Zoom: **−** / **+** / **Ver tudo** (enquadra o projeto inteiro na largura
    visível).

### Gestos com o mouse

- **Arrastar o corpo de um bloco** — move entre posições e entre trilhas,
  com imã (*snap*) no cursor de reprodução, nas bordas de outros blocos e no
  início da linha do tempo. Se a ponta da frente do bloco arrastado passar do
  **meio** de um vizinho, os dois **trocam de lugar**, sem sobrepor um
  terceiro. O intervalo vazio entre o par é preservado.
- **Arrastar as pontas (alças)** de um bloco — ajusta o corte daquele lado,
  com o mesmo imã. Entre dois blocos encostados, o lado da emenda em que o
  ponteiro está decide qual bloco é aparado.
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

### Adicionais: texto, filtros e transições

A coluna à direita do acervo tem uma aba por tipo de item. Cada um vira um
bloco numa trilha de **Adicionais** (ou, no caso da transição, na trilha de
vídeo, sobre o corte):

- **Texto** — conteúdo, fonte, tamanho, negrito e itálico, cor e contorno.
- **Filtros** — Preto e Branco, Sépia, Alto Contraste, Vinheta e Inversão. Um
  filtro age sobre tudo que está **abaixo** da trilha dele.
- **Transições** — Fade, Fade para Preto, Fade para Branco, Dissolve, Wipe e
  Slide (esquerda/direita), com duração de 0,2 a 5 s (padrão 1 s) e a opção
  **Afetar itens adicionais** descrita acima. O botão **+ Inserir Transição**
  usa o corte escolhido pelo bloco selecionado; sem cortes encostados, a aba
  avisa que é preciso encostar dois clipes de vídeo na mesma trilha.
- **Propriedades** — aparece ao escolher **Propriedades** no menu do botão
  direito sobre um bloco, e se fecha pelo ✕ do título. É a edição numérica
  precisa do bloco selecionado (ver a seguir).

### Propriedades e animação

A aba **Propriedades** mostra o bloco selecionado em campos numéricos:

- **Transformação** — posição X/Y e largura/altura em pixels da tela do projeto,
  **Travar proporção**, escala (0,05× a 10×), rotação (0° a 360°, com atalhos
  para 0°, 90°, 180° e 270°) e **Opacidade** (0 a 100 %). Os mesmos ajustes
  podem ser feitos direto na prévia, arrastando o objeto e suas alças —
  inclusive a de rotação, acima da caixa de seleção. Um objeto arrastado ou
  digitado aparece na hora; o quadro completo do compositor chega logo depois.
- **Fundo Verde (Chroma Key)** — remove uma cor do bloco (verde padrão, verde
  de estúdio, azul ou qualquer outra pelo seletor), com **Tolerância** e
  **Suavização**.
- **Animação / Quadros-chave** — anima posição, escala, rotação e opacidade ao
  longo do bloco:
  - **◀ ◇ ▶** vão ao quadro-chave anterior, adicionam ou removem um quadro-chave
    no cursor e vão ao próximo. Cada quadro-chave é um losango na parte de
    baixo do bloco, na linha do tempo — amarelo, ou azul quando o cursor está
    sobre ele —, e o ímã da linha do tempo também os reconhece: ao arrastar
    um bloco, os dos outros blocos (os dele andam junto com ele); ao aparar
    pela alça, também os do próprio bloco, que ali ficam parados — é o que deixa
    cortar exatamente onde a animação acaba.
  - Num bloco ainda **sem** quadros-chave, mudar um valor vale para o bloco
    inteiro. Num bloco animado, altera **só o instante atual**, criando ou
    atualizando o quadro-chave dali. Marque **Editar toda a animação** para
    aplicar o ajuste à curva inteira, inclusive aos pontos que sustentam a
    curva depois de um corte.
  - **Interpolação** escolhe a curva do quadro-chave selecionado: Linear, Suave
    ao Entrar (*ease in*), Suave ao Sair (*ease out*), Suave Completo (*ease
    in-out*) ou Degrau (*hold*). Em cada trecho vale a curva do quadro-chave de
    chegada; o Degrau em qualquer das duas pontas mantém o valor até o ponto
    seguinte.
  - **Efeito Rápido** troca os quadros-chave do bloco por uma entrada pronta,
    que dura até 0,6 s a partir do começo do bloco (menos, se ele for mais
    curto): deslizar de baixo, de cima, da direita ou da esquerda, surgir com
    fade, surgir com zoom ou girar e entrar. **Remover Animações** apaga todos
    os quadros-chave.

  A rotação segue o caminho angular mais curto entre dois pontos. Dividir ou
  aparar um bloco preserva a curva: o trecho que sobra continua avaliando a
  animação original, com pontos de suporte fora da janela visível.

O que a prévia mostra e o que o arquivo exportado contém coincide também para
animação: o compositor traduz os quadros-chave em expressões que o ffmpeg avalia
a cada quadro (escala, rotação, posição e opacidade).

### Texto

A digitação é agrupada no histórico do projeto até 1,2 s sem escrever, troca
de campo ou outro comando. Dentro do campo, os atalhos de edição do texto
continuam disponíveis. Um texto apagado por completo continua vazio — o editor
não o troca por "Texto", e a caixa de seleção tem o mesmo tamanho do que sai no
arquivo. Alterar a resolução de saída mantendo a proporção preserva tamanho e
posição relativos do texto, incluindo contorno e animação.

### Velocidade e volume do bloco

Os botões **🔊 dB** e **⚡ velocidade**, na barra da linha do tempo, abrem um
painel curto para o bloco selecionado. A velocidade vai de 0,1× a 10×, com
atalhos (0,5×, 1×, 1,5×, 2×, 4×); o bloco encurta ou alonga na trilha, e a
animação por quadros-chave encurta ou alonga junto. Se a
nova duração passaria por cima do bloco seguinte, a velocidade é recusada com
**um** aviso por sessão do painel — mova o vizinho ou escolha outro valor. O
áudio separado de um vídeo acelerado acompanha a mesma velocidade. Fotos,
textos, filtros e transições não têm velocidade.

### Menu de contexto (botão direito)

O conteúdo muda conforme o alvo sob o cursor:

**Sobre um bloco:**
- **Propriedades**
- *separador*
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

Salvar, salvar como, abrir, novo projeto, importar, exportar e F11 continuam
disponíveis mesmo com um campo em edição. Letras simples e
copiar/colar/desfazer respeitam o campo que possui o foco.

| Tecla | Ação |
|---|---|
| `Espaço` | Reproduzir/Pausar |
| `,` / `.` | Quadro anterior/próximo |
| `S` / `Ctrl+B` | Dividir no cursor |
| `Q` / `W` | Apagar à esquerda/à direita do cursor |
| `Del` / `Backspace` | Excluir bloco selecionado |
| `Ctrl+C` / `Ctrl+V` | Copiar/colar bloco |
| `Ctrl+Z` / `Ctrl+Shift+Z` ou `Ctrl+Y` | Desfazer/refazer |
| `Ctrl+N` / `Ctrl+O` | Novo projeto / abrir projeto |
| `Ctrl+S` / `Ctrl+Shift+S` | Salvar / salvar como |
| `Ctrl+I` | Importar mídia para o acervo |
| `Ctrl+E` | Abrir a janela de exportação |
| `F` / `F11` | Tela cheia |
| setas (com foco na linha do tempo) | andam quadro a quadro; `Shift`+seta anda 1 segundo |
| `Home` / `End` (idem) | vão para o início/fim |

## Tela cheia

Ative com **F**, **F11**, duplo clique na prévia, ou o botão **Tela cheia**.
A barra de controles some depois de 2,5 s sem movimento do mouse ou tecla —
reaparece a qualquer movimento, e nunca some enquanto o ponteiro está sobre
ela ou uma posição está sendo arrastada.

Controles da barra: Play/Pause, quadro anterior/próximo, tempo decorrido,
barra de posição (um clique salta direto para o ponto clicado, e arrastar
acompanha o ponteiro), tempo total, mudo + volume, e **Sair** (ou tecla `Esc`).

Atalhos exclusivos da tela cheia: `Espaço` play/pause; `←`/`,` e `→`/`.`
quadro a quadro; `↑`/`↓` sobem/descem o volume em 5.

## Exportando a edição

Os pacotes (Windows e Linux) trazem o próprio ffmpeg. Rodando pelo
código-fonte, vale o que estiver instalado — e com o ffmpeg 6 (o do Ubuntu
24.04) uma transição que atravessa um adicional **com filtro** perde esse
adicional durante a transição. A partir do ffmpeg 7 funciona.

Use **Exportar** (`Ctrl+E`), no topo do editor, para abrir as opções de saída.
A **Proporção** e a **Tela** do projeto também podem ser escolhidas nos
seletores do topo — são as mesmas escolhas da janela de exportação, e valem
para a prévia e para o arquivo. Elas são uma preferência de saída, como o corte
rápido, e não uma alteração da montagem: não entram no histórico de desfazer.
A tela resultante é gravada no `.vmp`. Ao abrir o projeto, tela e taxa iguais
às que o material produz voltam como **Automática**, como estavam antes de
fechar — um clipe maior ou mais fluido acrescentado depois sobe a edição, e o
corte rápido continua disponível —; o que difere do material volta fixo.

- **Proporção** — **Automática** (a da tela que o material produz, mostrada
  entre parênteses), 16:9, 4:3, 9:16 (vertical), 1:1 (quadrado) ou 21:9
  (ultrawide). Escolher uma proporção restringe a lista de **Tela** aos
  tamanhos dela, e os blocos são encaixados sem deformar; escolher uma tela
  atualiza a proporção. Voltar a "Automática" solta também a tela.
- **Tela** — tamanhos predefinidos por proporção (16:9: 4K, 1440p, 1080p, 720p,
  480p; 9:16: 1080×1920 e 720×1280; 4:3: 1440×1080, 960×720 e 640×480; 1:1:
  1080×1080 e 720×720; 21:9: 2560×1080), mais os tamanhos das mídias do acervo,
  ou **"Automática · segue o material"**, que usa o maior **vídeo** do projeto
  para decidir o tamanho — fotos não definem a tela quando há vídeo (ver
  [Editor e projetos](clean-architecture/editor.md)).
- **Taxa** — 24/25/30/50/60 fps e as taxas das mídias do acervo, ou
  **Automática** (a maior taxa entre os vídeos, com teto). Com GIF escolhido,
  entram também 10, 12,5, 20 e 25 — taxas que cabem certo na forma como o GIF
  guarda a duração de cada quadro.
- **Formato de vídeo** — MP4, MKV, WebM, MOV ou **GIF animado**. O GIF sai em
  loop infinito e com 256 cores; ele não guarda som, então a trilha de áudio
  fica de fora — e o GIF termina na última imagem, mesmo que a música vá além
  —, e não tem codec nem nível de qualidade para escolher (esses
  campos somem). Cada quadro de um GIF é uma imagem inteira, então em
  **Automática** a tela vai a no máximo 640 px e a taxa a 15 quadros por
  segundo: numa edição de 4 s isso é a diferença entre 1,1 MB e 14,9 MB (na
  tela do projeto, em 1080p a 30 q/s). Escolher tela ou taxa na mão continua
  valendo, e o tamanho estimado ao lado acompanha a escolha.
- **Interpolar movimento** — gera quadros de verdade para blocos de vídeo
  abaixo da taxa da tela, em vez de só duplicar o quadro anterior; a conta usa
  a taxa do arquivo já multiplicada pela velocidade do bloco, e fotos não
  contam. Fica desabilitado quando nenhum bloco está abaixo da taxa escolhida.
  É uma opção cara — o aviso ao lado mostra o custo estimado de memória antes
  de confirmar, e a **prévia nunca usa interpolação** (ela é rápida demais para
  caber no ritmo da reprodução; só aparece no arquivo exportado).
- **Corte rápido (sem recodificar)** — só fica disponível quando a edição
  ainda é um recorte de um único arquivo, na ordem e sem lacunas nem
  sobreposição entre os blocos, na tela e na taxa do próprio arquivo, sem
  volume, velocidade, opacidade, animação, posição, escala, rotação ou chroma
  key alterados, sem mudo e sem trilha sobreposta. Qualquer um desses efeitos
  tira a edição do corte rápido, em vez de a exportação copiar os dados e
  descartá-lo sem avisar. Quando o corte rápido está valendo, exportar é
  instantâneo: os dados são copiados como estão, sem qualidade perdida, e os
  campos de formato e codec passam a mostrar o container e o codec da origem
  ("Copiar sem recodificar (h264)"), desabilitados; as escolhas de
  recodificação voltam ao desmarcar. GIF nunca usa o corte rápido.
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
