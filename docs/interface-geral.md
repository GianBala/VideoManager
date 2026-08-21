# Janela principal

A janela abre com o título "Video Manager {versão}", em 1180×1000 px. Ela tem
três partes fixas: a barra de menu, três abas (**Download**, **Convert** e
**Editar**) e, embaixo delas, a **fila de tarefas** — comum às três abas, para
que trocar de aba nunca esconda o que está em andamento.

## Barra de menu

- **&Arquivo**
  - **Abrir pasta de destino** — abre no gerenciador de arquivos do sistema a
    pasta configurada para onde os resultados vão.
  - **Sair** — fecha o aplicativo (atalho padrão de encerrar do sistema
    operacional).
- **&Ferramentas**
  - **Configurações…** — abre o diálogo descrito em
    [`configuracoes.md`](configuracoes.md).
  - **Atualizar engine (yt-dlp)…** — atualiza o yt-dlp embutido. Fica
    **desabilitado** em builds empacotadas (AppImage, pasta do Windows), com
    uma dica explicando o motivo: nesses casos o yt-dlp vem embutido junto do
    aplicativo e é atualizado numa nova versão do próprio Video Manager, não
    separadamente.
- **Ajuda**
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
