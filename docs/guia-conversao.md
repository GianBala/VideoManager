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

Grupo **Converter para**, com três rádios que trocam o formulário abaixo:

### Converter para áudio

- **Formato** — mesma lista da aba Download: mp3, m4a/aac, opus, vorbis,
  flac, alac, wav.
- **Bitrate** — em kbps, desabilitado para formatos sem perda.

O WAV sai em 16 bits, ou em 24 bits quando a origem tem mais resolução que isso
(PCM de 24/32 bits ou ponto flutuante) — "sem perda" continua valendo.

### Converter vídeo

- **Container** — `.mp4`, `.mkv`, `.webm`, entre outros.
- **Codec de vídeo** — **Copiar (sem recodificar)** faz um remux instantâneo
  quando o container aceita o codec de origem, sem perda de qualidade nem
  espera; ou force H.264, HEVC, VP9 ou AV1, o que sempre recodifica. Só ficam
  habilitados os codecs que o container aceita (`.webm` recebe VP9 e AV1;
  `.mp4`, H.264, HEVC e AV1); ao trocar para um container que recusa o codec
  escolhido, a opção volta para **Copiar**. HEVC em `.mp4` sai com a etiqueta
  `hvc1`, exigida por aparelhos Apple e pelo app Filmes e TV.
- **Redimensionar para** — "Manter original" ou uma resolução de 2160p a 360p.
  A resolução é o **lado curto** da imagem como ela aparece: num vídeo retrato
  (inclusive gravado de lado, com rotação nos metadados), 720p reduz a largura
  para 720.

### Comprimir

Deixa os arquivos menores sem trocar de formato à toa. Uma tabela mostra os
quatro níveis lado a lado, cada um com a qualidade esperada e o **tamanho** que
os arquivos da lista vão ter, com a redução em relação ao original:

| Nível | Qualidade | Vídeo | Áudio |
| --- | --- | --- | --- |
| Leve | quase idêntica ao original | CRF 18 (x264) | até 192 kbps |
| Equilibrada (padrão) | ótima | CRF 23 | até 128 kbps |
| Forte | boa, perda visível de perto | CRF 28 | até 96 kbps |
| Máxima | aceitável | CRF 28 e no máximo 720p | até 64 kbps |

- **Codec de vídeo** — H.264 (toca em qualquer lugar), HEVC ou AV1 (menores,
  mais lentos para codificar). A placa de vídeo configurada é usada em H.264 e
  HEVC, com o número de qualidade de cada nível.
- **O tamanho é medido, não adivinhado.** Ao entrar no modo, a aba codifica
  três trechos de 8 s de cada vídeo em cada nível, em segundo plano, e mostra
  "medindo…" até o número chegar. Quanto um vídeo encolhe depende do conteúdo:
  uma gravação de tela quase parada encolhe para poucos por cento, uma cena com
  movimento bem menos.
- **Nada é ampliado nem recodificado para ficar igual.** O teto de 720p só vale
  para o que é maior que isso; um áudio que já está abaixo do teto do nível é
  copiado.
- **Resultado que não encolhe não é gravado.** Um vídeo baixado da internet
  costuma já estar bem comprimido, e recodificá-lo pode aumentá-lo. A tabela
  mostra isso antes (redução com sinal de `+`), o plano conta os arquivos que
  não devem encolher, e a tarefa que não terminar menor que o original falha com
  o aviso, sem deixar arquivo na pasta.
- **A medida só roda com memória para ela.** Uma amostra 4K pede tanto quanto a
  conversão 4K (até 4,3 GB); com a fila convertendo outro arquivo grande ao lado,
  a tabela usa uma conta aproximada no lugar.
- Vídeo e áudio podem estar na mesma lista: cada arquivo é comprimido no seu
  tipo. O áudio fica no formato em que chegou (MP3, AAC, Opus, Vorbis); os sem
  perda (FLAC, WAV) e os demais vão para AAC (`.m4a`). O vídeo sai em `.mp4`,
  ou em `.mkv` quando a origem é MKV, para manter todas as faixas e legendas.
- A saída leva " (comprimido)" no nome.

### Faixas extras

O `.mkv` guarda todas as faixas de áudio, as legendas e os anexos (como as
fontes de uma legenda ASS). `.mp4` e `.webm` levam o primeiro vídeo e a
primeira faixa de áudio, e o plano avisa quando algo fica de fora. Legendas
`mov_text` (as do MP4) não são copiadas para `.mkv`. Capas embutidas em áudio
(MP3, M4A, FLAC) não contam como vídeo: esses arquivos são pulados em
"Converter vídeo".

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

Se a pasta de origem não permitir criar arquivos — inclusive por permissão do
Windows ou pelo Acesso controlado a pastas do Defender, que o atributo
somente-leitura não revela —, a saída vai para a pasta de downloads, com aviso.
Mudanças feitas em Configurações (encoder de placa, pasta) valem na hora, sem
reiniciar.

## Acompanhando a conversão

O progresso de cada arquivo aparece na
[fila de tarefas](interface-geral.md#a-fila-de-tarefas), junto com downloads
e exportações de edição em andamento.
