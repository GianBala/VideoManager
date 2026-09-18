# Janela principal

A janela abre com o título "Video Manager {versão}", em 1180×1000 px. Ela tem
três partes fixas: a barra de menu, três abas (**Download**, **Convert** e
**Editar**) e, embaixo delas, a **fila de tarefas** — comum às três abas, para
que trocar de aba nunca esconda o que está em andamento.

## Barra de menu

Os menus **Arquivo** e **Ferramentas** acompanham a aba à vista: só aparecem os
comandos que fazem sentido nela, e os atalhos de uma aba ficam desligados nas
outras (`Ctrl+O`, por exemplo, adiciona arquivos na aba Convert e abre um
projeto na aba Editar).

- **&Arquivo**
  - Na aba **Download**: **Abrir pasta de downloads…** (abre no gerenciador de
    arquivos do sistema a pasta configurada) e **Sair**.
  - Na aba **Convert**: **Adicionar arquivos para conversão…** (`Ctrl+O`),
    **Remover arquivos selecionados**, **Limpar lista de conversão**, **Abrir
    pasta de destino…** e **Sair**. Remover e Limpar ficam desabilitados
    quando não há o que remover.
  - Na aba **Editar**: **Novo projeto** (`Ctrl+N`), **Abrir projeto…**
    (`Ctrl+O`), **Salvar projeto** (`Ctrl+S`), **Salvar projeto como…**
    (`Ctrl+Shift+S`), **Importar mídia…** (`Ctrl+I`) e **Exportar vídeo…**
    (`Ctrl+E`) — ver o [guia do editor](guia-edicao.md#projetos).
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

## As três abas

| Aba | Para que serve |
|---|---|
| [Download](guia-download.md) | Baixar vídeo/áudio de uma URL (yt-dlp) |
| [Convert](guia-conversao.md) | Converter arquivos que já estão no disco |
| [Editar](guia-edicao.md) | Cortar e montar uma edição multipista |

O divisor entre as abas e a fila é ajustado automaticamente conforme o
tamanho da janela — até o usuário arrastá-lo manualmente, quando a escolha
passa a ser dele e para de mudar sozinha. **Na aba Editar a fila fica
oculta**: ali o espaço vale mais como área de prévia e edição, e a barra de
status continua contando as tarefas em andamento mesmo sem a fila visível.

## A fila de tarefas

Tabela com as colunas **Título**, **Saída**, **Situação**, **Progresso** e
**Velocidade**, compartilhada pelas três abas — um download, uma conversão e
uma exportação de edição aparecem lado a lado na mesma lista, na ordem em que
foram enfileirados. Com a fila vazia, ela mostra "A fila está vazia."

- **Duplo clique** numa linha abre o arquivo resultante (se já existir).
- **Botão direito** abre um menu contextual ao que está selecionado:
  - **Cancelar** — se a tarefa ainda não terminou.
  - **Tentar de novo** — se ela falhou ou foi cancelada.
  - **Abrir arquivo** / **Abrir pasta do arquivo** — se o resultado existe.
  - **Copiar mensagem de erro** — se houve erro.
  - **Ver detalhes técnicos** — abre um diálogo somente leitura com o log
    completo daquela tarefa (as mensagens que o yt-dlp/ffmpeg produziram).
- Dois botões fixos abaixo da tabela: **Cancelar todos** e **Limpar
  encerrados** (remove da lista o que já terminou, com sucesso ou erro).

A coluna **Velocidade** muda de significado conforme a fase: taxa de
transferência e tempo estimado enquanto baixa; "parte X/Y" quando o stream é
fragmentado e não tem tamanho total conhecido (comum em HLS); o tamanho final
do arquivo quando a tarefa termina; um traço quando não há nada a mostrar.

A barra de status, na base da janela, resume o estado da fila
("`{ativos} em andamento · {pendentes} na fila · {concluídos} concluídos`")
e mostra a origem do `ffmpeg` em uso (embutido, baixado ou do sistema).

## Fechar a janela com tarefas em andamento

Se houver alguma tarefa ativa, fechar a janela pede confirmação ("Sair
mesmo?"), avisando que isso cancela tudo o que está em progresso e descarta
qualquer arquivo parcial gerado até ali.
