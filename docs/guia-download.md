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
5. **Trilha de áudio** — só aparece quando o site separa vídeo e áudio em
   streams diferentes (a maioria fora do YouTube já entrega mesclado).

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
- Uma nota mostra o melhor bitrate disponível na origem, para calibrar a
  escolha (pedir 320 kbps de uma fonte de 128 só deixa o arquivo maior, sem
  ganhar qualidade).

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
[fila de tarefas](interface-geral.md#a-fila-de-tarefas), comum às três abas.
