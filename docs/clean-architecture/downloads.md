# Análise de URL e downloads

## Do extrator à escolha do usuário

`DownloadService.analyze` normaliza a URL, rejeita entrada vazia e chama
`DownloadGateway`. O bootstrap fornece `YtDlpGateway`; ele usa o probe
yt-dlp e devolve `MediaInfo` ou `PlaylistInfo`.

O dicionário do extrator fica em `infrastructure/yt_dlp`.
`formats.py` o normaliza para os modelos de `domain/formats.py`:

| Modelo | Papel |
| --- | --- |
| `Fmt` | Formato individual, com evidências e campos desconhecidos explícitos. |
| `VideoChoice` / `AudioChoice` | Agrupamentos selecionáveis de formatos equivalentes. |
| `FormatMatrix` | Opções de vídeo/áudio oferecidas à interface. |
| `MediaInfo` | URL, título, matriz, duração, legendas e metadados consumidos pelo app. |
| `PlaylistInfo` / `PlaylistEntry` | Coleção e entradas ainda sem análise individual completa. |

Os modelos não carregam uma cópia do dicionário bruto.
`domain/format_policy.py` escolhe opções normalizadas.
`application/format_labels.py` produz rótulos; a apresentação decide onde
mostrá-los.

## Ausente não significa inexistente

`"vcodec": "none"` afirma que não há vídeo. A ausência de `vcodec` indica
que o extrator não informou. Essa diferença é preservada pela normalização.

Quando faltam dados, o adaptador usa outras evidências, como descrição,
dimensões e extensão, sem sobrescrever uma ausência explícita. Formatos que
não são mídia, como storyboards, são removidos antes da interface.

As fixtures de YouTube, archive.org, HLS sem metadados, SoundCloud e Instagram
protegem esses casos offline. Elas não contêm URLs assinadas de mídia ou cookies.

## Planejar e enfileirar

A interface monta `VideoRequest` ou `AudioRequest`, objetos do domínio.
Nos perfis automáticos, a escolha usa limites de resolução/fps em vez de IDs
fixos. Isso permite aplicar o perfil a itens diferentes de uma playlist.

`DownloadService.prepare` pede um `DownloadPlan` ao gateway e cria o
`Job` com descrição e avisos. A política neutra de container, compatibilidade
e qualidade fica em `application/media/download_policy.py`.

`DownloadWorker` traduz o pedido em opções com
`infrastructure/yt_dlp/selector.py`. Só esse lado da fronteira conhece
seletores, templates de nome, cookies e pós-processadores específicos do yt-dlp.
Cada download usa sua própria instância de `YoutubeDL`.

Os limites usam filtros tolerantes, como `[height<=?720]`: não informar
altura não torna um formato inválido. A cadeia de alternativas permite
recuperação quando um formato listado deixa de estar disponível.

A escolha de container não deve provocar recodificação silenciosa de vídeo.
Quando a combinação exige substituição de stream ou container, a política
produz o aviso exibido antes da execução. Conversão de áudio explicitamente
solicitada é representada por `AudioRequest`.

## Progresso, término e cancelamento

`Downloader` converte hooks do yt-dlp em `Progress` e devolve
`DownloadResult`. A aplicação recebe fase, percentual, bytes e resultado
sem importar tipos do provedor. A fila decide os estados por `ProgressStage`.

A análise de URL usa `ProbeWorker`, que captura preferências, emite resultado
ou falha e sempre emite `done`. Cancelar impede a aceitação do resultado;
uma requisição externa em andamento pode demorar a terminar.

`MainWindow` conecta um receptor por análise. Se uma resposta já estava na
fila de eventos quando houve cancelamento ou substituição, ela é descartada.
Um erro antigo também não abre diálogo sobre a análise nova.

A autenticação passa por preferências e adaptadores. Não registrar cookies,
cabeçalhos ou URLs assinadas em fixtures, logs ou descrições de tarefas.

## Onde validar e alterar

- Nova estrutura de extrator: normalização em `infrastructure/yt_dlp/formats.py`
  e fixture sanitizada.
- Nova regra sobre qualidade/container: política na aplicação sobre modelos
  normalizados, com teste independente de rede.
- Nova opção específica do yt-dlp: tradução no seletor e teste com o parser
  real `build_format_selector`.
- Novo botão/perfil: apresentação, entregando o mesmo pedido tipado.

`tests/test_format_matrix.py` e `tests/test_selector.py` usam fixtures e
parser real. Testes de rede ficam separados com a marca `network`; a suíte
padrão não certifica disponibilidade atual de cada plataforma.
