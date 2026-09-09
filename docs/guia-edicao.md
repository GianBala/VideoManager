# Aba Editar

Editor multipista com os gestos que CapCut e Filmora tornaram padrão: prévia
em cima, trilhas empilhadas embaixo, blocos que se arrastam no tempo e entre
trilhas. **O que está nas trilhas é o que vai ser exportado** — não há marca
de entrada/saída escondida num formulário à parte.

A janela é dividida, de cima para baixo: linha de importação → prévia e
transporte → linha do tempo → linha de exportação. O divisor entre a prévia e
a linha do tempo é um `QSplitter` livre — arraste para dar mais espaço a quem
precisar dele naquele momento; **"Retrair prévia"** é só o atalho para o
extremo mais pedido (linha do tempo ocupando quase tudo).

## Importando mídia

Na linha do topo:

- **Importar mídia…** abre o seletor de arquivos (vídeo, foto ou áudio).
  Também é possível **arrastar arquivos direto para a aba**.
- O combo ao lado lista tudo já importado nesta sessão de edição.
- **Inserir no cursor** — coloca o item selecionado do combo na trilha ativa,
  na posição atual do cursor de reprodução (desabilitado sem itens
  importados).

Com a linha do tempo vazia, a prévia mostra: *"Importe vídeos, fotos ou
áudios para montar a edição. Você também pode arrastar os arquivos para
cá."*

## Prévia e transporte

A prévia mostra sempre **o quadro exato da posição do cursor** — não o
keyframe mais próximo, como faria um player comum — porque é desenhada pelo
mesmo grafo de filtros que vai gerar o arquivo final (ver
[`arquitetura.md`](arquitetura.md)).

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
  terceiro.
- **Arrastar as pontas (alças)** de um bloco — ajusta o corte daquele lado,
  com o mesmo imã.
- **Clique simples** no vazio da trilha ou na régua de tempo — move o cursor
  de reprodução para ali.
- **Botão direito** — abre o menu de contexto (ver abaixo), relativo ao que
  está sob o cursor.
- **Botão do meio, arrastando** — paneia a vista horizontalmente.
- **Roda do mouse** — zoom, centrado na posição do ponteiro.
- **Shift + roda** — desloca a vista horizontalmente sem mudar o zoom.
- **Duplo clique num bloco** — enquadra aquele bloco na largura visível.
- **Clique no "M" do cabeçalho de uma trilha** — muda/desmuda a trilha
  inteira.

Um clique isolado nunca conta como edição: só a partir de alguns pixels de
arrasto é que a ação entra na pilha de desfazer — selecionar um bloco sem
mover nada não empilha um "desfazer" vazio.

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

Na linha de exportação, abaixo da linha do tempo:

- **Tela** — tamanhos predefinidos (4K, 1440p, 1080p, 720p, 480p, e variantes
  verticais/quadradas) ou **"Automática · segue o material"**, que usa o
  maior bloco do projeto para decidir o tamanho (ver
  [`arquitetura.md`](arquitetura.md#projectpy--composerpy-o-editor)).
- **Taxa** — 24/25/30/50/60 fps, ou **Automática**.
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
