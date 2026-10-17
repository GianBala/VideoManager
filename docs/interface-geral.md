# Janela principal

A janela abre com o título "Video Manager {versão}", em 1000 px de altura e 1180 px
de largura de conteúdo (mais o menu lateral). Ela tem quatro partes: a barra de
menu, o **menu lateral**, a área da aba à vista e, à direita, a **gaveta de
tarefas** — comum às abas, para que trocar de aba nunca esconda o que está em
andamento.

O **menu lateral** tem as quatro abas (**Download**, **Converter**, **Editar** e
**Metadados**), de cima para baixo, e embaixo dois itens que não são abas:
**Tarefas**, que abre e fecha a gaveta (com um selo que conta as tarefas em
andamento e na fila) e **Ajustes**, que abre as [configurações](configuracoes.md).
A aba à vista leva uma faixa do acento na borda da janela e o fundo suave.

## Barra de menu

Os menus **Arquivo** e **Ferramentas** acompanham a aba à vista: só aparecem os
comandos que fazem sentido nela, e os atalhos de uma aba ficam desligados nas
outras (`Ctrl+O`, por exemplo, adiciona arquivos na aba Converter e abre um
projeto na aba Editar).

- **&Arquivo**
  - Na aba **Download**: **Abrir pasta de downloads…** (abre no gerenciador de
    arquivos do sistema a pasta configurada) e **Sair**.
  - Na aba **Converter**: **Adicionar arquivos para conversão…** (`Ctrl+O`),
    **Remover arquivos selecionados**, **Limpar lista de conversão**, **Abrir
    pasta de destino…** e **Sair**. Remover e Limpar ficam desabilitados
    quando não há o que remover.
  - Na aba **Editar**: **Novo projeto** (`Ctrl+N`), **Abrir projeto…**
    (`Ctrl+O`), **Salvar projeto** (`Ctrl+S`), **Salvar projeto como…**
    (`Ctrl+Shift+S`), **Importar mídia…** (`Ctrl+I`) e **Exportar vídeo…**
    (`Ctrl+E`) — ver o [guia do editor](guia-edicao.md#projetos).
  - Na aba **Metadados**: **Abrir arquivo…** (`Ctrl+O`) e **Salvar cópia**
    (`Ctrl+S`) — ver o [guia da aba](guia-metadados.md).
  - **Sair** fecha o aplicativo (atalho padrão de encerrar do sistema
    operacional).
- **&Ferramentas**
  - **Configurações…** — abre o diálogo descrito em
    [`configuracoes.md`](configuracoes.md). Está em todas as abas.
  - **Atualizar motor de download (yt-dlp)…** — só na aba Download; atualiza o
    yt-dlp. Fica **desabilitado** em builds empacotadas (AppImage, pacote do
    Windows), com uma dica explicando o motivo: nesses casos o yt-dlp vem
    embutido junto do aplicativo e é atualizado numa nova versão do próprio
    Video Manager, não separadamente.
- **A&juda**
  - **Sobre** — mostra a versão do aplicativo e a versão do yt-dlp em uso.

## As quatro abas

| Aba | Para que serve |
|---|---|
| [Download](guia-download.md) | Baixar vídeo/áudio de uma URL (yt-dlp) |
| [Converter](guia-conversao.md) | Converter arquivos que já estão no disco |
| [Editar](guia-edicao.md) | Cortar e montar uma edição multipista |
| [Metadados](guia-metadados.md) | Editar tags, trilhas e capa, gravando numa cópia |

A gaveta é uma coluna de largura fixa e **trocar de aba não a mexe**: aberta
numa aba, continua aberta nas outras, o Editar e os Metadados incluídos, para
acompanhar uma tarefa enquanto se edita; fechada, continua fechada. O item
**Tarefas** a liga e desliga, e o selo dele conta as tarefas em andamento mesmo
com a gaveta fechada. Ao enfileirar uma exportação, um aviso flutuante diz que
a tarefa entrou na fila e oferece **Ver tarefas**, que abre a gaveta ali mesmo.
A escolha é uma só, de todas as abas: fechar a gaveta no Editar a fecha também ao
voltar a Download ou Converter, e abri-la em qualquer uma a abre nas outras.

**Em janela estreita a gaveta recolhe sozinha.** Quando a janela é mais estreita
que o menu, o conteúdo da aba e os 344 px da gaveta somados, a gaveta sai de
cena em vez de segurar a janela numa largura grande (sem ela, a janela encolhe
até o mínimo do conteúdo). Se a janela volta a ter largura, ela volta. O item
**Tarefas** a abre mesmo assim, e a janela cresce o necessário para caber.

## A gaveta de tarefas

Uma lista de **cartões**, um por tarefa, compartilhada por Download, Converter e
Editar — um download, uma conversão e uma exportação de edição aparecem lado a
lado na mesma lista, na ordem em que foram enfileirados. No título, duas
pastilhas contam as tarefas **ativas** e as **na fila**. Com a lista vazia, ela
mostra "A fila está vazia.".

Cada cartão traz um ícone da situação (baixando, convertendo, concluído, falhou,
na fila), o título, a situação com o perfil ("Baixando · MP4 · 1080p"), a barra
de progresso e, embaixo dela, a porcentagem à esquerda e a velocidade e o tempo
restante à direita. A tarefa concluída mostra o tamanho do arquivo, e a que falhou, o
motivo em vermelho.

- **Duplo clique** num cartão abre o arquivo resultante (se já existir).
- **Botão direito** abre um menu contextual ao que está selecionado:
  - **Cancelar** — se a tarefa ainda não terminou.
  - **Tentar de novo** — se ela falhou ou foi cancelada.
  - **Abrir arquivo** / **Abrir pasta do arquivo** — se o resultado existe.
  - **Copiar mensagem de erro** — se houve erro.
  - **Ver detalhes técnicos** — abre um diálogo somente leitura com o log
    completo daquela tarefa (as mensagens que o yt-dlp/ffmpeg produziram).
- Dois botões fixos embaixo da lista: **Cancelar todos** e **Limpar
  encerrados** (remove da lista o que já terminou, com sucesso ou erro).

Quando o stream é fragmentado e não tem tamanho total conhecido (comum em HLS),
em vez do tempo restante o cartão mostra "parte X/Y". Os avisos que antes ficavam
numa barra de status — "{n} tarefa(s) adicionada(s) à fila", o erro de gravação
das preferências — são **avisos flutuantes** que somem sozinhos; a **origem do
`ffmpeg`** em uso (empacotado, gerenciado ou do sistema) e o caminho dele estão em
**Configurações → Geral**.

## Fechar a janela com tarefas em andamento

Se houver alguma tarefa ativa, fechar a janela pede confirmação ("Sair
mesmo?"), avisando que isso cancela tudo o que está em progresso e descarta
qualquer arquivo parcial gerado até ali.
