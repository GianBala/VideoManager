# Catálogo de módulos

Todos os caminhos abaixo são relativos a `src/videomanager/`. Os arquivos
`__init__.py` das subpastas delimitam pacotes; não montam serviços nem executam
I/O. A tabela cobre os módulos de produção, incluindo as entradas do aplicativo.

## Inicialização

| Módulo | Responsabilidade |
| --- | --- |
| [__init__.py](../../src/videomanager/__init__.py) | Nome público, identificador do aplicativo e versão. |
| [__main__.py](../../src/videomanager/__main__.py) | Entrada python -m videomanager e script inicial do PyInstaller; importa app.main de forma absoluta. |
| [app.py](../../src/videomanager/app.py) | Preflight, QApplication, fontes, tema, ícone, integração desktop e montagem da janela; diagnóstico --smoke-test. |
| [bootstrap.py](../../src/videomanager/bootstrap.py) | Constrói serviços e adaptadores; carrega preferências como DTO e injeta runtime, repositório e renderizador. |
| [preflight.py](../../src/videomanager/preflight.py) | Detecta bibliotecas gráficas ausentes e produz diagnóstico antes da criação da QApplication. |

## Domínio

| Módulo | Responsabilidade |
| --- | --- |
| [domain/compatibility.py](../../src/videomanager/domain/compatibility.py) | Compatibilidade de codecs/containers, decisões de cópia, escala e recodificação; tamanho exibido com rotação (720p é o lado curto) e codec que o container aceita. |
| [domain/composition.py](../../src/videomanager/domain/composition.py) | Pedido semântico de composição/exportação, sem argumentos ffmpeg. |
| [domain/constants.py](../../src/videomanager/domain/constants.py) | Duração mínima de segmento e de transição (0,2 s) e codecs de imagens compartilhados. |
| [domain/estimator.py](../../src/videomanager/domain/estimator.py) | Estimativas de tamanho/bitrate a partir de formatos e escolhas, inclusive o GIF (por pixel, sem áudio). |
| [domain/export_policy.py](../../src/videomanager/domain/export_policy.py) | Elegibilidade de corte simples (velocidade, opacidade, animação, lacunas e sobreposições o descartam) e de interpolação, e adaptação para TrimTarget. |
| [domain/format_policy.py](../../src/videomanager/domain/format_policy.py) | Busca e seleção de opções normalizadas de vídeo/áudio. |
| [domain/formats.py](../../src/videomanager/domain/formats.py) | Modelos normalizados dos formatos, matriz, mídia, legendas e playlists. |
| [domain/geometry.py](../../src/videomanager/domain/geometry.py) | Dimensão base de imagem, ajustada à tela como um vídeo (`image_base_size`), e a regra anterior ao formato 3 (`natural_image_size`), usada só para migrar projetos. |
| [domain/keyframe.py](../../src/videomanager/domain/keyframe.py) | `Keyframe` e `ClipTransform`, curvas de interpolação (linear, ease in/out, degrau), interpolação com o menor caminho angular e presets de entrada. |
| [domain/media.py](../../src/videomanager/domain/media.py) | LocalMedia/LocalStream (rotação, capa embutida, duração por trilha, imagem estática × sequência) e alvos AudioTarget/VideoTarget, sem inspeção externa. |
| [domain/preview.py](../../src/videomanager/domain/preview.py) | RawFrame RGB24, limites de fps, ajuste de dimensões e instantes de miniaturas. |
| [domain/scrub.py](../../src/videomanager/domain/scrub.py) | Assinatura do que compõe um instante e trechos de assinatura constante, para validar quadros guardados. |
| [domain/project.py](../../src/videomanager/domain/project.py) | Project, Track, Clip, MediaRef e operações imutáveis: cortes, trilhas em qualquer ordem, transforms e quadros-chave, transições ligadas ao corte, tela (`auto_canvas`, `slideshow_canvas`), soltura de mídia (`with_dropped_clip`), migração das imagens para a trilha de vídeo, IDs e duração. |
| [domain/render_cost.py](../../src/videomanager/domain/render_cost.py) | Estimativa calibrada de memória da interpolação a partir dos clipes e dimensões. |
| [domain/selection.py](../../src/videomanager/domain/selection.py) | VideoRequest/AudioRequest e escolhas de container/qualidade de download. |
| [domain/targets.py](../../src/videomanager/domain/targets.py) | Catálogo dos formatos de saída oferecidos pelo aplicativo. |
| [domain/timing.py](../../src/videomanager/domain/timing.py) | Segment, TrimTarget, CutMode, timecodes, fps, keyframes e a aritmética temporal única (origem × edição, índice e instante de quadro, último quadro). |

## Aplicação

| Módulo | Responsabilidade |
| --- | --- |
| [application/capabilities.py](../../src/videomanager/application/capabilities.py) | FFmpegTools como descritor de ferramentas já localizadas, sem fazer descoberta. |
| [application/editor/media.py](../../src/videomanager/application/editor/media.py) | ReadMedia e MediaResult: importa/abre, deduplica, inspeciona e agrega ausentes/rejeitados. |
| [application/editor/service.py](../../src/videomanager/application/editor/service.py) | Grava snapshots, aceita resultados de abrir/salvar e prepara recursos de texto por porta. |
| [application/editor/session.py](../../src/videomanager/application/editor/session.py) | Proprietário do projeto atual, caminho, ponto salvo, histórico (60 estados), transações de gesto (`begin_edit`/`commit_edit`/`cancel_edit`) e gerações/revisões. |
| [application/encoding.py](../../src/videomanager/application/encoding.py) | Nomes de hardware/famílias e opções de qualidade, sem sondar encoders. |
| [application/errors.py](../../src/videomanager/application/errors.py) | Categorias de exceções da aplicação e mensagens de erro em pt-BR. |
| [application/events.py](../../src/videomanager/application/events.py) | Progress, ProgressStage e DownloadResult independentes do provedor. |
| [application/format_labels.py](../../src/videomanager/application/format_labels.py) | Rótulos de resolução e escolhas, reutilizados em descrições e apresentação. |
| [application/formatting.py](../../src/videomanager/application/formatting.py) | Formatação compartilhada de tamanho, tempo, fps, bitrate e proporção de aspecto (`format_aspect_ratio`). |
| [application/jobs/models.py](../../src/videomanager/application/jobs/models.py) | Identidade, tipo, estado, progresso e resultado de Job; códigos de estado neutros. |
| [application/jobs/requests.py](../../src/videomanager/application/jobs/requests.py) | DownloadRequest/ConversionRequest e união tipada dos alvos, sem Job.opts. |
| [application/jobs/service.py](../../src/videomanager/application/jobs/service.py) | Transições por tentativa, conclusão única, repetição, remoção e contagem de tarefas. |
| [application/media/conversion_description.py](../../src/videomanager/application/media/conversion_description.py) | Descrição da conversão local com codecs, dimensões e escolhas de saída. |
| [application/media/download_policy.py](../../src/videomanager/application/media/download_policy.py) | Plano de container, avisos de compatibilidade e qualidade de áudio sobre modelos normalizados. |
| [application/media/downloads.py](../../src/videomanager/application/media/downloads.py) | DownloadService: valida URL e coordena análise e planejamento pelo gateway. |
| [application/media/export_description.py](../../src/videomanager/application/media/export_description.py) | Descrição da exportação de projeto, incluindo áudio, qualidade, interpolação e o caso do GIF. |
| [application/media/preview.py](../../src/videomanager/application/media/preview.py) | PreviewRequest e normalização de tempo, tamanho, fps, token e recursos; `PreviewResultKey` (contexto que autoriza mostrar um quadro), `PreviewFrameInbox` (só o último quadro de reprodução) e `playback_clock`. |
| [application/media/interaction.py](../../src/videomanager/application/media/interaction.py) | `InteractionPlan`: separa fundo, objeto e frente de um instante para o arrasto do objeto na prévia responder ao mouse. |
| [application/media/scrub.py](../../src/videomanager/application/media/scrub.py) | ScrubFrameCache: quadros JPEG por índice e assinatura, teto de memória, obsoletos e faltantes. |
| [application/media/processing.py](../../src/videomanager/application/media/processing.py) | ExportOptions e ProcessingService: valida escolhas (inclusive codec × container), define alvos, prepara texto e reserva saída; a referência de nome vem de um vídeo, e foto só na falta dele. |
| [application/media/trim_description.py](../../src/videomanager/application/media/trim_description.py) | Descrição do recorte e seu modo. |
| [application/ports/downloads.py](../../src/videomanager/application/ports/downloads.py) | DownloadGateway e DownloadPlan para análise e planejamento substituíveis. |
| [application/ports/editor.py](../../src/videomanager/application/ports/editor.py) | ProjectRepository, MediaProbe e Cancellation exigidos por abrir/importar/salvar. |
| [application/ports/output.py](../../src/videomanager/application/ports/output.py) | OutputLease: identidade e caminho do placeholder pertencente a uma operação. |
| [application/ports/processing.py](../../src/videomanager/application/ports/processing.py) | MediaCatalog e OutputStore para inspeção, permissão, reserva, limpeza e publicação. |
| [application/ports/rendering.py](../../src/videomanager/application/ports/rendering.py) | TextRasterizer e coleta de PNGs por ID de clipe. |
| [application/preferences.py](../../src/videomanager/application/preferences.py) | DTO Preferences, valores padrão e leitura tolerante de campos, sem acesso a diretórios. |

## Infraestrutura

| Módulo | Responsabilidade |
| --- | --- |
| [infrastructure/ffmpeg/catalog.py](../../src/videomanager/infrastructure/ffmpeg/catalog.py) | Implementa MediaCatalog com disco, find_tools e ffprobe; a gravabilidade de uma pasta é testada criando um arquivo, e não só por `os.access`. |
| [infrastructure/ffmpeg/command_assets.py](../../src/videomanager/infrastructure/ffmpeg/command_assets.py) | Grafo longo em arquivo temporário exclusivo da execução, removido ao sair; escolhe `-filter_complex_script` ou `-/filter_complex` conforme a versão do ffmpeg. |
| [infrastructure/ffmpeg/composer.py](../../src/videomanager/infrastructure/ffmpeg/composer.py) | Grafo de composição e comandos para exportação (inclusive GIF), quadro parado, cache da agulha, camadas de interação, reprodução, áudio e trechos paralelos; traduz quadros-chave em expressões por quadro e monta as transições. |
| [infrastructure/ffmpeg/converter.py](../../src/videomanager/infrastructure/ffmpeg/converter.py) | Inspeção de mídia (rotação, capa, duração por trilha), montagem de conversão (faixas extras do MKV, etiqueta `hvc1`, WAV de 24 bits), execução serial com stderr em UTF-8, progresso, cancelamento e publicação. |
| [infrastructure/ffmpeg/hardware.py](../../src/videomanager/infrastructure/ffmpeg/hardware.py) | Sonda encoders reais, mantém cache e traduz preferências em argumentos com fallback. |
| [infrastructure/ffmpeg/lastframe.py](../../src/videomanager/infrastructure/ffmpeg/lastframe.py) | Instante em que o último quadro de um arquivo começa, lido do próprio arquivo por ffprobe e guardado por caminho, tamanho e data. |
| [infrastructure/ffmpeg/parallel.py](../../src/videomanager/infrastructure/ffmpeg/parallel.py) | Planeja concorrência da interpolação, renderiza trechos, concatena, mistura áudio e publica; o erro de um trecho aponta a linha que explica a falha. |
| [infrastructure/ffmpeg/preview.py](../../src/videomanager/infrastructure/ffmpeg/preview.py) | Decodifica quadros, filmstrips (miniaturas que preservam a proporção), ondas e reprodução por FramePump, com leitura adiantada limitada; separa os JPEGs do cache da agulha. |
| [infrastructure/ffmpeg/thumbnail.py](../../src/videomanager/infrastructure/ffmpeg/thumbnail.py) | Gera/incorpora a capa opcional antes da publicação, com controle de processo; a capa preserva metadados e capítulos. |
| [infrastructure/ffmpeg/trimmer.py](../../src/videomanager/infrastructure/ffmpeg/trimmer.py) | Consulta keyframes e traduz recorte rápido/exato e junção em comandos. |
| [infrastructure/qt/audio.py](../../src/videomanager/infrastructure/qt/audio.py) | PCM, QAudioSink, filas limitadas, relógio de áudio, descarte de gerações antigas e emenda do loop (`queue_next`) sem parar a placa. |
| [infrastructure/qt/runtime.py](../../src/videomanager/infrastructure/qt/runtime.py) | Implementa as fábricas e serviços desktop injetados na apresentação (inclusive camadas de interação, cache da agulha e som encadeado), sem estado de negócio. |
| [infrastructure/qt/text.py](../../src/videomanager/infrastructure/qt/text.py) | QtTextRasterizer com cache por conteúdo/instância, PNGs imutáveis e lock. |
| [infrastructure/qt/workers/convert_worker.py](../../src/videomanager/infrastructure/qt/workers/convert_worker.py) | Executa ConversionRequest com Converter, traduzindo término, falha e cancelamento em sinais. |
| [infrastructure/qt/workers/download_worker.py](../../src/videomanager/infrastructure/qt/workers/download_worker.py) | Constrói opções do pedido e executa Downloader, emitindo eventos da tarefa. |
| [infrastructure/qt/workers/engine_worker.py](../../src/videomanager/infrastructure/qt/workers/engine_worker.py) | Provisionamento do ffmpeg e atualização do mecanismo yt-dlp fora da UI. |
| [infrastructure/qt/workers/function_worker.py](../../src/videomanager/infrastructure/qt/workers/function_worker.py) | Executa uma callable com finished/failed/done; usado na escrita de snapshot. |
| [infrastructure/qt/workers/hwaccel_worker.py](../../src/videomanager/infrastructure/qt/workers/hwaccel_worker.py) | Executa sondagem de hardware em segundo plano. |
| [infrastructure/qt/workers/media_worker.py](../../src/videomanager/infrastructure/qt/workers/media_worker.py) | Adapta ReadMedia, repositório JSON e probe cancelável a QRunnable. |
| [infrastructure/qt/workers/preview_worker.py](../../src/videomanager/infrastructure/qt/workers/preview_worker.py) | Workers de quadro, camadas de interação, reprodução, cache da agulha, filmstrip, waveform e keyframes, com cancelamento/tokens; falha e cancelamento são sinais próprios, e o stderr do ffmpeg é drenado por thread com teto. |
| [infrastructure/qt/workers/probe_worker.py](../../src/videomanager/infrastructure/qt/workers/probe_worker.py) | Executa DownloadService.analyze com preferências capturadas e sinal done garantido. |
| [infrastructure/qt/workers/queue.py](../../src/videomanager/infrastructure/qt/workers/queue.py) | JobQueue: pools separadas e receptores de sinais que alimentam JobService por tentativa. |
| [infrastructure/qt/workers/signals.py](../../src/videomanager/infrastructure/qt/workers/signals.py) | Objetos QObject de sinais (na prévia: `frame`, `primed`, `strip`, `waveform`, `keyframes`, `scrub_frames`, `failed`, `cancelled`) e emissão tolerante a encerramento. |
| [infrastructure/qt/workers/thumbnail_worker.py](../../src/videomanager/infrastructure/qt/workers/thumbnail_worker.py) | Carrega a miniatura remota para apresentação de mídia. |
| [infrastructure/storage/output_paths.py](../../src/videomanager/infrastructure/storage/output_paths.py) | Reserva de nome exclusivo, sufixos e nome personalizado com criação O_EXCL. |
| [infrastructure/storage/outputs.py](../../src/videomanager/infrastructure/storage/outputs.py) | FileOutputStore: lease, verificação de propriedade, abort e commit atômico, com novas tentativas curtas quando o Windows recusa a troca por arquivo em uso. |
| [infrastructure/storage/project_json.py](../../src/videomanager/infrastructure/storage/project_json.py) | Esquema .vmp (escreve a versão 3, lê 1 a 3): quadros-chave, tela e referência do texto, migração das imagens para a trilha de vídeo, cópia `.v1.bak`/`.v2.bak`, caminhos relativos, validação, IDs, mídias ausentes e escrita atômica. |
| [infrastructure/storage/projects.py](../../src/videomanager/infrastructure/storage/projects.py) | JsonProjectRepository adapta o serializador à porta de projetos. |
| [infrastructure/storage/settings.py](../../src/videomanager/infrastructure/storage/settings.py) | Persistência de Preferences, defaults de diretórios do sistema e resolução de pasta de downloads. |
| [infrastructure/system/binaries.py](../../src/videomanager/infrastructure/system/binaries.py) | Localiza/provisiona ffmpeg/ffprobe, lê a versão maior do ffmpeg (`major_version`), localiza o runtime JavaScript (Deno/Node), valida binários, rebaixa a prioridade de processos de fundo (`lower_priority`) e prepara ambiente de subprocessos. |
| [infrastructure/system/logs.py](../../src/videomanager/infrastructure/system/logs.py) | Log em arquivo com rotação (`videomanager.log`, na pasta de logs do usuário) e registro de exceções não tratadas (slots Qt e threads). |
| [infrastructure/system/memory.py](../../src/videomanager/infrastructure/system/memory.py) | Consulta de memória disponível em Linux/Windows para planejamento externo. |
| [infrastructure/system/process.py](../../src/videomanager/infrastructure/system/process.py) | ProcessControl: execução registrada, cancelamento, timeout e encerramento. |
| [infrastructure/yt_dlp/downloader.py](../../src/videomanager/infrastructure/yt_dlp/downloader.py) | Instância de YoutubeDL por tarefa, hooks, progresso, logs, cancelamento e resultado; registra a capa tolerante depois de montar as opções. |
| [infrastructure/yt_dlp/extras.py](../../src/videomanager/infrastructure/yt_dlp/extras.py) | Opção `js_runtimes` conforme o ambiente e capa tolerante (`TolerantEmbedThumbnailPP`) que não derruba o download. |
| [infrastructure/yt_dlp/formats.py](../../src/videomanager/infrastructure/yt_dlp/formats.py) | Normaliza dados brutos dos extratores, classifica presença de streams e monta FormatMatrix. |
| [infrastructure/yt_dlp/gateway.py](../../src/videomanager/infrastructure/yt_dlp/gateway.py) | Implementa DownloadGateway combinando probe e política de planejamento. |
| [infrastructure/yt_dlp/probe.py](../../src/videomanager/infrastructure/yt_dlp/probe.py) | Executa análise de URL, traduz erros (a etapa entra na mensagem sem tradução: analisar × baixar) e constrói MediaInfo/PlaylistInfo; avisos e erros do yt-dlp seguem para o log. |
| [infrastructure/yt_dlp/selector.py](../../src/videomanager/infrastructure/yt_dlp/selector.py) | Traduz escolhas em expressões, templates e pós-processadores yt-dlp. |

## Apresentação

| Módulo | Responsabilidade |
| --- | --- |
| [presentation/formatting.py](../../src/videomanager/presentation/formatting.py) | Exporta os formatadores de escolhas usados pelos presenters. |
| [presentation/qt/editor_project.py](../../src/videomanager/presentation/qt/editor_project.py) | Controller de diálogos e acervo; abre/importa/salva usando API pública do painel e serviços. |
| [presentation/qt/export_dialog.py](../../src/videomanager/presentation/qt/export_dialog.py) | Coleta opções (proporção, tela, taxa, formato — inclusive GIF —, codec, qualidade, corte rápido), apresenta custo/avisos/descrição e pede preparação da exportação. |
| [presentation/qt/ffmpeg_setup.py](../../src/videomanager/presentation/qt/ffmpeg_setup.py) | Diálogo de descoberta/provisionamento, conectado ao worker pelo runtime. |
| [presentation/qt/fonts.py](../../src/videomanager/presentation/qt/fonts.py) | Carrega fontes empacotadas e substituição Calibri/Carlito após iniciar Qt. |
| [presentation/qt/fullscreen_preview.py](../../src/videomanager/presentation/qt/fullscreen_preview.py) | Janela de prévia ampliada, controles e sincronização visual com o editor. |
| [presentation/qt/icons.py](../../src/videomanager/presentation/qt/icons.py) | Cria ícones usados nos controles. |
| [presentation/qt/main_window.py](../../src/videomanager/presentation/qt/main_window.py) | Três abas, menus, destino, análise, playlists, configuração e coordenação da fila. |
| [presentation/qt/panels/convert_panel.py](../../src/videomanager/presentation/qt/panels/convert_panel.py) | Lista de arquivos locais, escolha de alvo e submissão via ProcessingService. |
| [presentation/qt/panels/edit_panel.py](../../src/videomanager/presentation/qt/panels/edit_panel.py) | Widgets e controller de edição: seleção, comandos do domínio, sessão, gestos (agrupados em transações), prévia com camadas e cache da agulha, reprodução, loop, tela/proporção e propriedades. |
| [presentation/qt/panels/edit_widgets.py](../../src/videomanager/presentation/qt/panels/edit_widgets.py) | Componentes visuais do editor: superfície da prévia com alças, acervo arrastável, popups de volume e velocidade e a aba Propriedades (transformação, animação por quadros-chave e chroma key). |
| [presentation/qt/panels/media_card.py](../../src/videomanager/presentation/qt/panels/media_card.py) | Apresenta título, duração, origem e miniatura da mídia analisada. |
| [presentation/qt/panels/profiles_panel.py](../../src/videomanager/presentation/qt/panels/profiles_panel.py) | Perfis rápidos que geram escolhas sem IDs específicos de uma mídia. |
| [presentation/qt/panels/quality_panel.py](../../src/videomanager/presentation/qt/panels/quality_panel.py) | Controles de resolução, fps, container e áudio sobre FormatMatrix. |
| [presentation/qt/panels/queue_panel.py](../../src/videomanager/presentation/qt/panels/queue_panel.py) | Lista/delegate da fila, rótulos de estado, progresso, repetir, cancelar e abrir resultado. |
| [presentation/qt/panels/timeline.py](../../src/videomanager/presentation/qt/panels/timeline.py) | Pintura da timeline (régua e agulha fixas, trilhas rolando por baixo, quadros-chave), hit testing, arrasto de blocos, trilhas e mídia do acervo, ímã, seleção e emissão de intenções. |
| [presentation/qt/playlist_dialog.py](../../src/videomanager/presentation/qt/playlist_dialog.py) | Apresenta entradas e escolhas de download em lote. |
| [presentation/qt/ports.py](../../src/videomanager/presentation/qt/ports.py) | Contrato DesktopRuntimePort consumido pelos widgets/controllers; não importa implementação. |
| [presentation/qt/settings_dialog.py](../../src/videomanager/presentation/qt/settings_dialog.py) | Edita Preferences e apresenta capacidades/versões obtidas pelo runtime. |
| [presentation/qt/strings.py](../../src/videomanager/presentation/qt/strings.py) | Textos dos controles, avisos e mapeamento de códigos de estado para rótulos. |
| [presentation/qt/tasks.py](../../src/videomanager/presentation/qt/tasks.py) | WorkerRunner mantém QRunnable vivo até o término e solicita cancelamento. |
| [presentation/qt/theme.py](../../src/videomanager/presentation/qt/theme.py) | Cores, QPalette, QSS e estilos compartilhados. |

## Recursos e diretórios de apoio

- `resources/`: ícone PNG/SVG e fontes Carlito/Rapier com licença. Não contém estado do usuário.
- `tests/`: domínio, aplicação, contratos, arquitetura e regressões de mídia/Qt; veja [testes](testes.md).
- `packaging/`: especificação PyInstaller, provisionamento do ffmpeg e do Deno (`fetch_binaries.py`), gerador do ícone (`make_icon.py`), scripts Linux/Windows e diagnósticos do pacote (`smoke_run.sh`, `smoke_windows.ps1`).
- `scripts/`: apoio à distribuição (`generate_appimage.sh`), comparação reproduzível de desempenho (`benchmark_architecture.py`) e ensaios opt-in que a suíte não alcança (`validate_audio.py`, `validate_scrub.py`, `validate_preview_gestures.py`, `validate_editor_responsiveness.py`); veja [testes](testes.md#medições-reproduzíveis). `capture_screenshots.py` gera as imagens do README em `docs/imagens/`.
- `.github/workflows/tests.yml`: a CI — núcleo sem dependências desktop e matriz Linux/Windows com o ffmpeg do sistema e o do pacote.
- `vendor/`, `build/`, `dist/`: binários e artefatos locais, ignorados pelo Git.
- `docs/`: manuais de uso e documentação técnica.
