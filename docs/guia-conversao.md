# Aba Convert

Converte arquivos que já estão no disco — diferente da aba Download, aqui não
há rede envolvida, só o `ffmpeg` local.

## Adicionando arquivos

Grupo **Arquivos a converter**:

- **Arraste arquivos** direto para a lista, ou clique em **Escolher
  arquivos…** para abrir o seletor do sistema.
- Cada item da lista mostra nome, codec e resolução de vídeo, codec de áudio,
  duração e tamanho — o suficiente para conferir o que vai ser convertido sem
  abrir o arquivo em outro programa.
- **Remover selecionados** tira itens da lista (só habilitado com algo
  selecionado). Isso não apaga o arquivo original, só o retira da fila de
  conversão.

## Escolhendo o destino da conversão

Grupo **Converter para**, com dois rádios que trocam o formulário abaixo:

### Converter para áudio

- **Formato** — mesma lista da aba Download: mp3, m4a/aac, opus, vorbis,
  flac, alac, wav.
- **Bitrate** — em kbps, desabilitado para formatos sem perda.

### Converter vídeo

- **Container** — `.mp4`, `.mkv`, `.webm`, entre outros.
- **Codec de vídeo** — **Copiar (sem recodificar)** faz um remux instantâneo
  quando o container aceita o codec de origem, sem perda de qualidade nem
  espera; ou force H.264, HEVC, VP9 ou AV1, o que sempre recodifica.
- **Redimensionar para** — "Manter original" ou um teto de altura, de 2160p a
  360p.

## Conferindo o resultado antes de converter

O texto **"O que vai acontecer: {plano}"**, logo abaixo do formulário,
descreve exatamente o que será feito a partir do primeiro arquivo da lista —
se é uma cópia direta (remux, instantânea) ou uma recodificação (mais lenta,
usa a CPU ou a placa conforme configurado em
[Configurações](configuracoes.md)). O mesmo texto que a aba Editar usa para
anunciar o plano de exportação — a ideia é nunca começar um processamento
sem que o usuário saiba de antemão o que vai sair do outro lado.

## Destino e conversão

- **"Salvar na mesma pasta do arquivo original"** vem marcado por padrão —
  desmarque para escolher uma pasta de destino única para todo o lote.
- O botão **Converter** enfileira todos os arquivos da lista de uma vez, na
  mesma fila comum das outras abas.

Um arquivo que não tem a trilha necessária para o alvo escolhido (por
exemplo, pedir conversão de vídeo a partir de um arquivo só de áudio) é
avisado e **pulado**, sem travar o restante do lote.

## Acompanhando a conversão

O progresso de cada arquivo aparece na
[fila de tarefas](interface-geral.md#a-fila-de-tarefas), junto com downloads
e exportações de edição em andamento.
