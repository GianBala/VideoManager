# Aba Download

Baixa vídeo e áudio de centenas de plataformas suportadas pelo yt-dlp
(YouTube, Instagram, TikTok, Vimeo, SoundCloud, arquivos servidos direto por
HTTP/HLS, e muitas outras) — sem lista fixa: qualquer URL que o yt-dlp
reconheça funciona, e as opções de qualidade oferecidas vêm do que aquela
mídia especificamente disponibiliza.

## Fluxo básico

1. **Cole o endereço** no campo "Endereço" (aceita colar com `Ctrl+V` ou pelo
   botão **Colar e analisar**, que cola e já dispara a análise num só clique).
   Pressionar `Enter` no campo também analisa.
2. Clique em **Analisar** (ou deixe o **Colar e analisar** fazer os dois
   passos). O botão mostra "Analisando…" e fica desabilitado enquanto a URL é
   consultada.
3. O resultado aparece no **card de mídia**: miniatura, título, autor,
   duração, extrator reconhecido e, quando houver, contagem de legendas
   disponíveis ou de formatos bloqueados por DRM. Transmissões ao vivo são
   sinalizadas com "TRANSMISSÃO AO VIVO".
4. Se a URL for de uma **playlist ou canal**, abre-se o diálogo de seleção —
   ver [seção própria](#playlists-e-canais) abaixo — em vez do card de mídia.
5. Ajuste a **qualidade** desejada (ver abaixo) ou use um dos **perfis
   rápidos**.
6. Clique em **Adicionar à fila**. O botão só é habilitado depois de uma
   análise bem-sucedida.
7. Escolha a **pasta de destino** no campo "Destino" (com o botão
   **Escolher…**) antes ou depois de analisar — ela vale para o que for
   enfileirado a partir dali.

## Escolha de qualidade

O grupo **Qualidade** tem dois modos, escolhidos pelos rádios no topo — a
opção que a mídia analisada não oferece fica desabilitada:

### Vídeo (com áudio)

Uma cadeia de combos em cascata, cada um populado só com o que a mídia
**realmente** tem (nunca uma lista fixa de resoluções):

1. **Resolução** — inclui "Melhor disponível" no topo; opções sem altura
   conhecida (comum em HLS) mostram o bitrate em vez de inventar um número.
2. **Framerate** — "Qualquer" mais os valores existentes naquela resolução.
3. **Codec de vídeo** — idem, restrito ao que existe na resolução escolhida.
4. **Container** — Automático, `.mp4`, `.mkv` ou `.webm`.
5. **Bitrate** — "Igual ao da fonte" (o padrão, que mostra o bitrate que a fonte
   tem) baixa o vídeo como o site o entrega, sem recodificar. Um valor pronto
   (500 kbps a 12 Mbps) ou "Personalizado…" (de 100 a 100 000 kbps) é o
   consentimento de **recodificar**: depois do download, o vídeo é codificado de
   novo a esse bitrate médio, em **duas passadas** (x264, x265 e VP9; o SVT-AV1
   usa uma), no codec que ele já tinha (ou H.264 se o container não o aceita), e
   o áudio, as legendas e a capa ficam como estão. O arquivo sai perto de
   *bitrate × duração* — medido em vídeos reais, de +3% a +5% acima do pedido num
   1080p60, e menos quando a imagem é simples demais para gastar o bitrate (uma
   gravação de tela de 10 Mbps cabe em 0,3 a 0,7 Mbps, qualquer que seja o alvo).
   O tamanho estimado acompanha o valor, e é, portanto, um teto.
   Uma fonte que já está no bitrate pedido, ou abaixo, é mantida: recodificar
   para cima só aumentaria o arquivo (o painel avisa antes de baixar). Os perfis
   rápidos voltam o bitrate ao da fonte. O campo do valor livre aparece numa
   fileira abaixo, só com "Personalizado…" escolhido.

   A recodificação usa todos os núcleos e de 1,2 GB a 4 GB de memória por vídeo, e por isso
   acontece **uma por vez**: os downloads seguintes terminam de baixar e esperam a vez (a tarefa diz
   "Aguardando a vez de recodificar"), em vez de somar três encodes na mesma máquina.
6. **Trilha de áudio** — "Melhor disponível" ou uma das trilhas que o site
   oferece (idioma, codec, bitrate). O campo está sempre à vista; só se
   escolhe quando o site separa vídeo e áudio em streams diferentes (o YouTube
   separa, a maioria dos outros já entrega mesclado). Nos outros casos ele fica
   apagado e diz por quê: "Já vem junto com o vídeo" numa mídia mesclada, e
   "Melhor disponível" enquanto nada foi analisado.

Sempre que a combinação escolhida implica **trocar de codec**, **recodificar**
ou baixar uma **resolução menor** que a melhor disponível naquele codec, ou
**extrair o áudio de um vídeo inteiro**, um aviso aparece abaixo dos combos
explicando o porquê — nada disso acontece em silêncio.

> O app nunca recodifica vídeo sem avisar antes: quando o container pedido
> não aceita o codec escolhido, ele troca de stream ou de container primeiro,
> e só recodifica se realmente não houver alternativa — sempre anunciado.

### Somente áudio

- **Formato** — "Original (sem perda, mais rápido)" extrai o áudio como veio,
  sem recodificar; ou um formato específico: MP3, M4A/AAC, Opus, Vorbis,
  FLAC, ALAC, WAV.
- **Bitrate** — em kbps; desabilitado para formatos sem perda e para
  "Original", já que bitrate não se aplica a eles.
- **Trilha de áudio** — a mesma escolha do modo de vídeo, vista daqui: trocar
  num modo troca no outro. Decide qual stream da origem vira o arquivo (em
  "Original", é o arquivo que se recebe, com o codec e o bitrate dela) ou a
  matéria-prima da recodificação, e é a única forma de escolher o idioma de uma
  mídia com dublagens. Só se escolhe quando o site separa vídeo e áudio; senão
  o campo fica apagado.
- Uma nota mostra o melhor bitrate disponível na origem — ou o da trilha
  escolhida, quando há escolha —, para calibrar a qualidade (pedir 320 kbps de
  uma fonte de 128 só deixa o arquivo maior, sem ganhar qualidade, e o aviso
  compara com a mesma trilha).

## Perfis rápidos

Quatro botões no painel à direita aplicam uma configuração pronta **e já
enfileiram** em um clique só (desabilitados até haver uma mídia analisada):

| Perfil | O que faz |
|---|---|
| **MP4 1080p** | vídeo compatível com qualquer aparelho, até 1080p |
| **Máxima qualidade** | MKV, sem recodificar — o melhor que a origem oferece |
| **MP3 320k** | só o áudio, MP3 a 320 kbps |
| **Áudio original** | só o áudio, extraído sem recodificar |

## Playlists e canais

Quando a URL analisada é uma playlist ou um canal, abre-se um diálogo:
"'{título}' tem {N} itens. Marque os que deseja baixar." — todos marcados por
padrão, com **Marcar todos** / **Desmarcar todos**, e um combo de **limite de
resolução** (Melhor disponível, ou um teto de 2160p até 360p; padrão 1080p) —
a nota ao lado deixa claro que é um *limite*, já que cada item da lista pode
oferecer formatos diferentes dos outros. O botão de confirmação muda de texto
conforme a seleção ("Adicionar {N} à fila") e fica desabilitado com zero itens
marcados.

## Legendas, metadados e cookies

Essas opções não ficam na aba Download — são preferências gerais, ajustadas
uma vez em **Configurações** e aplicadas a todo download seguinte. Ver
[`configuracoes.md`](configuracoes.md).

## YouTube e runtime JavaScript

O YouTube só libera todos os formatos para quem resolve os desafios JavaScript
da página. O pacote traz o **Deno** para isso; rodando do código-fonte (ou num
pacote gerado com `VM_BUNDLE_DENO=0`), vale o Deno ou o Node instalado no
sistema. Sem nenhum deles a análise ainda funciona, mas algumas qualidades
podem não aparecer.

## Acompanhando o download

Depois de **Adicionar à fila**, o progresso aparece na
[fila de tarefas](interface-geral.md#a-fila-de-tarefas), comum às abas Download, Converter e Editar.
