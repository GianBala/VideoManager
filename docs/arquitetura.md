# Arquitetura

## Visão geral

```
src/videomanager/
├── core/      lógica de mídia, sem nenhuma dependência de Qt
├── workers/   ponte para a interface: QRunnable + sinais
└── ui/        janela e painéis (PySide6)
```

A dependência é de **mão única**: `ui` → `workers` → `core`. Nada em `core`
importa Qt, o que permite testar toda a lógica de mídia (seleção de formato,
montagem de comandos do ffmpeg, corte, composição) sem abrir uma janela.
Os testes de domínio independem da interface. A suíte também contém testes Qt
offscreen e integração local com ffmpeg; nenhum deles exige display.

- **`core/`** — análise de URL, matriz de formatos, seleção, download,
  conversão, preferências, binários externos, projeto de edição, composição,
  corte.
- **`workers/`** — `QRunnable` + um objeto de sinais à parte (um `QRunnable`
  não é `QObject` e não pode declarar sinais Qt diretamente). `JobQueue` é a
  **única** dona do estado das tarefas; a interface só lê `Job` e reage aos
  sinais emitidos.
- **`ui/`** — janela principal e painéis. Três abas — **Download**, **Convert**
  e **Editar** — sobre uma fila de tarefas só, que fica fora das abas (trocar
  de aba não deve esconder o que está em andamento).

## Módulos de `core/`

| Módulo | Responsabilidade |
|---|---|
| `probe.py` | Analisa uma URL sem baixar nada (`extract_info(download=False)`), traduz exceções do yt-dlp em erros com mensagem em pt-BR. |
| `format_matrix.py` | Normaliza a resposta crua de cada extrator em opções selecionáveis de vídeo/áudio. O módulo mais importante do projeto — ver seção própria abaixo. |
| `selector.py` | Traduz a escolha do usuário (resolução, fps, codec, container) em opções concretas do yt-dlp (expressão de formato, postprocessors). |
| `downloader.py` | Executa um download com progresso e cancelamento, numa instância nova de `YoutubeDL` por tarefa. |
| `converter.py` | Conversão de arquivos locais já em disco: monta e executa o comando de ffmpeg, reserva o nome de saída, mede o resultado. |
| `trimmer.py` | Recorte de vídeo (aba Editar): mapeia keyframes com `ffprobe`, decide entre corte exato (recodifica) e corte rápido (copia, começa no keyframe anterior). |
| `project.py` | Modelo imutável da edição e identidades de trilhas e clipes. |
| `editor_session.py` | Projeto atual, histórico de desfazer/refazer e comparação com o ponto salvo. |
| `text_assets.py` | Contrato de rasterização, implementado pelo adaptador Qt em `ui/text_renderer.py`. |
| `process.py` / `thumbnail.py` | Subprocessos com prazo/cancelamento e capa opcional antes da entrega do arquivo. |
| `composer.py` | Traduz um `Project` num grafo de filtros do ffmpeg. O mesmo grafo serve para exportar, desenhar o quadro parado da prévia e alimentar a reprodução. |
| `preview.py` | Chama o ffmpeg para produzir quadro, tira de miniaturas e forma de onda — sempre pelo ffmpeg, nunca por um player, porque a prévia precisa mostrar o quadro exato do corte. |
| `parallel_export.py` | Divide uma exportação com interpolação de quadros (`minterpolate`, de uma thread só) em trechos processados em paralelo. |
| `hwaccel.py` | Decide o encoder de vídeo: sonda se a placa realmente codifica (não confia no que `ffmpeg -encoders` lista) e cai para software automaticamente. |
| `binaries.py` | Localiza, baixa e valida `ffmpeg`/`ffprobe`; monta o `subprocess_kwargs()` usado por todo processo externo. |
| `settings.py` | Preferências persistidas em JSON, com leitura tolerante a arquivo corrompido ou de outra versão. |
| `models.py` | Modelos de dados imutáveis (`Fmt`, `VideoChoice`, `AudioChoice`, `FormatMatrix`, `MediaInfo`...) — a fronteira entre o dicionário cru do yt-dlp e o resto da aplicação. |
| `job.py` | Representa uma tarefa da fila (baixando/convertendo), seu estado e progresso. |
| `humanize.py` | Formatação de tamanho, duração, fps e bitrate para exibição. |
| `errors.py` | Hierarquia de exceções do domínio — toda mensagem é considerada apresentável ao usuário, em pt-BR. |
| `memory.py` | Estimativa de memória disponível, usada para decidir quantos trechos paralelos uma exportação interpolada pode usar. |

### `format_matrix.py`: a distinção que sustenta o projeto

Cada extrator do yt-dlp devolve uma estrutura diferente para o mesmo conceito
("quais formatos existem"). A regra que orienta o módulo:

> `"vcodec": "none"` significa **"conferi, não há vídeo"**. A **ausência** da
> chave `vcodec` significa **"não sei"**.

Tratar as duas como a mesma coisa descarta mídia perfeitamente baixável — foi
o bug que deixava o archive.org 100% inacessível (não declara codec algum) e
fazia o HLS da Apple baixar vídeo **mudo** (declara `vcodec` mas omite
`acodec` nas faixas de áudio). Quando o extrator não declara nada, entra uma
cadeia de evidências mais fraca — marcação `"audio only"`/`"video only"` no
texto descritivo, presença de dimensões, e por último a extensão do arquivo —
nessa ordem, nunca sobrescrevendo um valor que o extrator afirmou
explicitamente.

Formatos não-mídia (storyboards `mhtml` do YouTube) são identificados e
descartados antes de chegar à interface.

### `selector.py`: duas regras inegociáveis

- **Filtros não-estritos.** Todo limite vira `[height<=?720]`, nunca
  `[height<=720]`. O `?` diz ao yt-dlp para não descartar formatos que
  simplesmente não têm aquele campo — sem ele, pedir "no máximo 30 fps"
  eliminaria todo site que não informa `fps`.
- **Nunca recodificar sem consentimento.** Quando o container escolhido não
  aceita o codec, a saída é trocar de stream ou de container — nunca
  recodificar por conta própria. Toda substituição feita vira aviso na tela
  antes do download começar.

A expressão de formato final é uma **cadeia de degradação**
(`id+id / id+ba / … / b`): um extrator pode listar um formato que já saiu do
ar, e os elos genéricos do fim garantem que ainda sobre alguma opção.

### `project.py` / `composer.py`: o editor

O modelo de edição (`Project`) é **imutável** — toda operação (arrastar,
cortar, colar) devolve um projeto novo, e desfazer/refazer é simplesmente
uma pilha desses projetos, não um caderno de ações reversíveis para
inverter.

Um bloco (`Clip`/bloco de trilha) carrega três números porque existem duas
linhas do tempo: `in_point` (onde começa dentro do arquivo de origem),
`start` (onde começa na edição) e `duration`. A ordem das trilhas é a da
tela, de cima para baixo; a composição inverte essa ordem porque a trilha
mais baixa é o fundo.

`composer.py` traduz esse projeto num grafo de filtros do ffmpeg, e o mesmo
grafo serve **três usos**: exportar o arquivo final, desenhar o quadro parado
da prévia, e alimentar a reprodução. Isso garante que o que aparece na tela
seja exatamente a composição que vai sair no arquivo — inclusive volume em
decibéis, mudo, sobreposição de trilhas e vãos pretos.

Decisões relevantes de montagem:

- Blocos são **sobrepostos a um fundo preto**, nunca emendados — resolve com
  uma regra só os casos de tamanhos diferentes, vão entre blocos e trilhas
  sobrepostas.
- Mixagem de áudio usa `amix` com `normalize=0`, porque o padrão do ffmpeg
  divide o volume pelo número de entradas — dois blocos simultâneos sairiam
  pela metade sem ninguém pedir.
- Ajustar a taxa de quadros para a taxa da tela é feito **duplicando quadro**,
  não interpolando, a menos que o usuário peça interpolação de verdade
  (`minterpolate`) — que só entra explicitamente porque é cara: 1,3 de 20
  núcleos, sem uso de GPU, e memória proporcional ao tamanho do quadro (medida:
  1,6 GB a 1080p, 5,6 GB a 4K, independente da duração). Uma exportação
  interpolada é dividida em trechos paralelos (`parallel_export.py`) para
  não usar um único núcleo de vinte.

### `trimmer.py`: corte sem recodificar só existe num keyframe

Cortar sem recodificar (`-c copy`) só é possível começando exatamente num
keyframe — quadro completo, sem depender dos anteriores. `keyframe_times`
mapeia os keyframes com `ffprobe -show_packets` (que só demultiplexa, sem
decodificar, e por isso é ordens de grandeza mais rápido). A aba Editar
mostra as duas saídas honestas antes de enfileirar:

- **Corte exato** — recodifica o trecho, começa exatamente no ponto marcado.
- **Corte rápido** — copia os dados como estão, começa no keyframe anterior
  ao ponto marcado, e a interface anuncia o desvio real (`drift`) antes do
  download entrar na fila.

### `hwaccel.py`: nada confia no que o ffmpeg anuncia

`ffmpeg -encoders` lista `h264_nvenc` em qualquer build moderna, inclusive
onde ele não abre de verdade. A disponibilidade de um encoder de placa é
decidida **sondando**: mandando codificar um quadro de verdade, com o
resultado em cache por execução. Se a sondagem falhar, a exportação cai para
software automaticamente — uma exportação que não acontece é pior que uma
mais lenta. O padrão continua sendo software (x264), que comprime melhor no
mesmo tamanho de arquivo; usar a placa é escolha explícita do usuário em
Configurações.

## Filas e concorrência

**Nenhum worker que abre ffmpeg roda no `QThreadPool` global.** A pool global
dimensiona por núcleo de CPU, que é a conta certa para trabalho que ocupa um
núcleo — e a errada para um processo de ffmpeg, onde cada vaga custa a
memória de um decodificador inteiro. Por isso existem filas próprias e
estreitas, separadas pelo tipo de espera:

- **`JobQueue`** (fila visível na interface) tem duas filas internas:
  baixar espera a **rede** (`max_concurrent_jobs`, preferência do usuário) e
  converter espera a **máquina** (`_LOCAL_JOBS = 1`, fixo — um ffmpeg já usa
  todos os núcleos sozinho).
- **`EditPanel`** tem outras duas: uma para quadro e reprodução (responde ao
  usuário, não pode ficar atrás de trabalho de fundo) e outra para tira de
  miniaturas, forma de onda e keyframes (pode esperar).

No pior caso, isso soma **5** processos de ffmpeg locais simultâneos — contra
23 se tudo corresse na pool global sem essa separação.

Todo processo externo é alcançável por um cancelamento, e todo worker de
fundo sabe parar: o fechamento da janela chama `cancel_all()` nas filas do
editor, e a fila local de conversão registra o processo assim que ele abre —
inclusive nas etapas finais de uma exportação paralela, que ganharam prazo e
registro por esse motivo.

## Interface (`ui/`)

O editor distribui suas responsabilidades entre `panels/edit_panel.py`
(coordenação da edição e reprodução), `panels/edit_widgets.py` (widgets visuais)
e `editor_project.py` (acervo e ciclo de vida de arquivos). A abertura de `.vmp`
e a inspeção de mídias usam `workers/media_worker.py`, com progresso,
cancelamento e tokens para descartar respostas de operações anteriores.

`text_renderer.py` prepara PNGs identificados pelo conteúdo em um diretório
exclusivo do processo. O compositor recebe esse adaptador pelo contrato
`core/text_assets.py`, sem importar Qt. Versões distintas do mesmo texto não
sobrescrevem arquivos que uma prévia ou exportação ainda estejam usando.


- **`ui/theme.py`** é a fonte única de cores, QSS e paleta da aplicação —
  necessária porque QSS sozinho não alcança tudo que um `delegate` desenha
  (como a barra de progresso da fila).
- A linha do tempo (`ui/panels/timeline.py`) é **pintada à mão**, não widget
  por bloco: um widget por bloco tornaria as miniaturas recortadas pelas
  bordas um problema de camadas, e o layout teria que ser refeito várias
  vezes por segundo a cada movimento do cursor.
- **A linha do tempo não é dona de nada.** O projeto vive no painel; o widget
  só desenha e avisa intenção ("este bloco foi solto ali"); o painel aplica
  sobre o modelo imutável e devolve um projeto novo para redesenhar.
- **`MainWindow._balance_panes`** reparte a altura entre as abas e a fila em
  proporção ao tamanho corrente da janela — até o usuário arrastar o divisor,
  quando a escolha passa a ser dele. Na aba Editar, a fila fica oculta e a
  janela inteira vira prévia.

Para os detalhes internos mais delicados de cada módulo — e o porquê de cada
decisão não-óbvia, com as medições que a sustentam — ver `CLAUDE.md` na raiz
do repositório, escrito para orientar mudanças futuras no código.

## Testes

**A ausência de exceção não prova nada.** Os defeitos mais caros deste
projeto não levantaram erro nenhum: vídeo mudo, som acelerado, mixagem 3 dB
abaixo do esperado. Por isso, tudo que produz mídia é conferido **medindo a
saída com o `ffprobe`** (duração, trilhas presentes, volume médio), nunca só
pela ausência de exceção.

O que sustenta a promessa de funcionar com extratores diversos são
**fixtures reais** em `tests/fixtures/` — respostas de extratores gravadas em
disco, cada uma escolhida por expor uma estrutura diferente. Ver
[`desenvolvimento.md`](desenvolvimento.md) e `tests/fixtures/README.md`.
