# Aba Metadados

Edita os metadados de um arquivo de vídeo ou áudio — título, artista, álbum,
data, gênero, qualquer outro campo, o título e o idioma de cada trilha e a capa —
e grava o resultado **numa cópia**. O original nunca é alterado.

## Abrindo um arquivo

**Abrir arquivo…** (`Ctrl+O`) ou arrastar o arquivo para a aba. A linha do grupo
**Arquivo** mostra nome, formato e duração. Um arquivo por vez.

## O que se edita

- **Tags** — os campos mais comuns, cada um com seu rótulo: Título, Artista,
  Álbum, Artista do álbum, Data, Nº da faixa, Nº do disco, Gênero, Compositor,
  Comentário, Descrição e Direitos autorais. Comentário e Descrição aceitam
  várias linhas: arraste a alça sob cada um deles para ampliá-lo e ler o texto
  inteiro (clique duplo na alça volta ao tamanho original). O tamanho escolhido
  vale também para os próximos arquivos que você abrir. Apagar o texto de um
  campo apaga o campo na cópia.
- **Outros campos** — tudo o mais que o arquivo traz (a sinopse de um vídeo
  baixado, um campo criado por outro programa), com **Adicionar campo** e
  **Remover campo**. Campos que o próprio formato reescreve a cada gravação
  (`encoder`, `major_brand` e parecidos) não aparecem, porque editá-los não teria
  efeito. As linhas se ajustam sozinhas ao texto do valor — com quebra de linha,
  até 8 linhas de altura —, então um valor de várias linhas aparece inteiro, sem
  reticências. Para ampliar mais uma linha, arraste a alça (o traço duplo) no pé
  dela, para baixo ou para cima; o clique duplo na alça — ou arrastá-la de volta
  até a altura automática — devolve o ajuste automático. Para editar um valor,
  dê um clique duplo nele: abre um campo de várias linhas, como o da Descrição
  (Enter quebra a linha; Tab ou um clique fora confirma; Esc desfaz; Ctrl+Enter
  confirma). Arraste também a
  **divisão entre Campo e Valor** para dar mais largura a um dos lados, e a alça
  abaixo da tabela para ampliá-la (ela já cresce sozinha para mostrar as linhas
  ajustadas). A divisão e a altura da tabela valem também para os próximos
  arquivos; a altura de cada linha volta ao ajuste automático.
- **Trilhas** — título e idioma de cada trilha de vídeo, áudio e legenda; o
  idioma é o código de três letras (`por`, `eng`, `spa`). No Ogg e no Opus os
  campos da trilha são os do próprio arquivo e se editam em Tags.
- **Capa** — ver, **Trocar…** por uma imagem JPEG ou PNG, ou **Remover**. MP4,
  M4A, MP3, FLAC e MKV guardam capa; nos outros formatos a aba diz que não há
  onde guardá-la.

## Salvando

**Salvar cópia** (`Ctrl+S`) grava `nome (metadados).ext` ao lado do original —
ou na pasta de downloads, com aviso, quando a pasta do original não permite
escrita. Os dados de vídeo e de áudio são copiados sem recodificar: a cópia tem
exatamente as mesmas trilhas, e o salvamento leva só o tempo de copiar o arquivo.
Salvar de novo gera `nome (metadados) (2).ext`.

Antes de aparecer na pasta, a cópia é conferida: se não tiver as mesmas trilhas
e a mesma duração do original, ela não é gravada. Depois, a aba diz **o que o
formato não guardou** — cada formato aceita uma parte diferente do que se pede:

| Formato | Não guarda |
|---|---|
| MKV, WebM | — (guardam tudo) |
| MP4, M4A | campos livres |
| MOV | campos livres e vários comuns (artista do álbum, nº da faixa, compositor, descrição) |
| AVI | campos livres, álbum, artista do álbum, compositor, descrição e idioma de trilha |
| MP3, FLAC, WAV | título e idioma de trilha; o WAV também não guarda campos livres |

**Mostrar na pasta** abre a pasta da cópia. **Descartar alterações** volta ao
que o arquivo tem. Abrir outro arquivo ou fechar o aplicativo com alterações
ainda não salvas numa cópia pede confirmação.

A fila de tarefas fica escondida nesta aba, como no editor: salvar não passa
pela fila, e o espaço vale mais como formulário.
