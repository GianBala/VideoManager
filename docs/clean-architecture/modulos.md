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
| [domain/compatibility.py](../../src/videomanager/domain/compatibility.py) | Compatibilidade de codecs/containers e decisões de cópia, escala e recodificação. |
| [domain/composition.py](../../src/videomanager/domain/composition.py) | Pedido semântico de composição/exportação, sem argumentos ffmpeg. |
| [domain/constants.py](../../src/videomanager/domain/constants.py) | Duração mínima de segmento e codecs de imagens compartilhados. |
| [domain/estimator.py](../../src/videomanager/domain/estimator.py) | Estimativas de tamanho/bitrate a partir de formatos e escolhas. |
| [domain/export_policy.py](../../src/videomanager/domain/export_policy.py) | Elegibilidade de corte simples e interpolação e adaptação para TrimTarget. |
| [domain/format_policy.py](../../src/videomanager/domain/format_policy.py) | Busca e seleção de opções normalizadas de vídeo/áudio. |
| [domain/formats.py](../../src/videomanager/domain/formats.py) | Modelos normalizados dos formatos, matriz, mídia, legendas e playlists. |
| [domain/geometry.py](../../src/videomanager/domain/geometry.py) | Dimensão base de imagem para transformações consistentes. |
| [domain/media.py](../../src/videomanager/domain/media.py) | LocalMedia/LocalStream e alvos AudioTarget/VideoTarget, sem inspeção externa. |
| [domain/preview.py](../../src/videomanager/domain/preview.py) | RawFrame RGB24, limites de fps, ajuste de dimensões e instantes de miniaturas. |
| [domain/scrub.py](../../src/videomanager/domain/scrub.py) | Assinatura do que compõe um instante e trechos de assinatura constante, para validar quadros guardados. |
| [domain/project.py](../../src/videomanager/domain/project.py) | Project, Track, Clip, MediaRef e operações imutáveis: cortes, trilhas, transforms, tela, IDs e duração. |
| [domain/render_cost.py](../../src/videomanager/domain/render_cost.py) | Estimativa calibrada de memória da interpolação a partir dos clipes e dimensões. |
| [domain/selection.py](../../src/videomanager/domain/selection.py) | VideoRequest/AudioRequest e escolhas de container/qualidade de download. |
| [domain/targets.py](../../src/videomanager/domain/targets.py) | Catálogo dos formatos de saída oferecidos pelo aplicativo. |
| [domain/timing.py](../../src/videomanager/domain/timing.py) | Segment, TrimTarget, CutMode, timecodes, fps, keyframes e aritmética temporal. |

## Aplicação

| Módulo | Responsabilidade |
| --- | --- |
| [application/capabilities.py](../../src/videomanager/application/capabilities.py) | FFmpegTools como descritor de ferramentas já localizadas, sem fazer descoberta. |
| [application/editor/media.py](../../src/videomanager/application/editor/media.py) | ReadMedia e MediaResult: importa/abre, deduplica, inspeciona e agrega ausentes/rejeitados. |
| [application/editor/service.py](../../src/videomanager/application/editor/service.py) | Grava snapshots, aceita resultados de abrir/salvar e prepara recursos de texto por porta. |
| [application/editor/session.py](../../src/videomanager/application/editor/session.py) | Proprietário do projeto atual, caminho, ponto salvo, histórico e gerações/revisões. |
| [application/encoding.py](../../src/videomanager/application/encoding.py) | Nomes de hardware/famílias e opções de qualidade, sem sondar encoders. |
| [application/errors.py](../../src/videomanager/application/errors.py) | Categorias de exceções da aplicação e mensagens de erro em pt-BR. |
| [application/events.py](../../src/videomanager/application/events.py) | Progress, ProgressStage e DownloadResult independentes do provedor. |
| [application/format_labels.py](../../src/videomanager/application/format_labels.py) | Rótulos de resolução e escolhas, reutilizados em descrições e apresentação. |
| [application/formatting.py](../../src/videomanager/application/formatting.py) | Formatação compartilhada de tamanho, tempo, fps e bitrate. |
| [application/jobs/models.py](../../src/videomanager/application/jobs/models.py) | Identidade, tipo, estado, progresso e resultado de Job; códigos de estado neutros. |
| [application/jobs/requests.py](../../src/videomanager/application/jobs/requests.py) | DownloadRequest/ConversionRequest e união tipada dos alvos, sem Job.opts. |
| [application/jobs/service.py](../../src/videomanager/application/jobs/service.py) | Transições por tentativa, conclusão única, repetição, remoção e contagem de tarefas. |
| [application/media/conversion_description.py](../../src/videomanager/application/media/conversion_description.py) | Descrição da conversão local com codecs, dimensões e escolhas de saída. |
| [application/media/download_policy.py](../../src/videomanager/application/media/download_policy.py) | Plano de container, avisos de compatibilidade e qualidade de áudio sobre modelos normalizados. |
| [application/media/downloads.py](../../src/videomanager/application/media/downloads.py) | DownloadService: valida URL e coordena análise e planejamento pelo gateway. |
| [application/media/export_description.py](../../src/videomanager/application/media/export_description.py) | Descrição da exportação de projeto, incluindo áudio, qualidade e interpolação. |
| [application/media/preview.py](../../src/videomanager/application/media/preview.py) | PreviewRequest e normalização de tempo, tamanho, fps, token e recursos. |
| [application/media/scrub.py](../../src/videomanager/application/media/scrub.py) | ScrubFrameCache: quadros JPEG por índice e assinatura, teto de memória, obsoletos e faltantes. |
| [application/media/processing.py](../../src/videomanager/application/media/processing.py) | ExportOptions e ProcessingService: valida escolhas, define alvos, prepara texto e reserva saída. |
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
| [infrastructure/ffmpeg/catalog.py](../../src/videomanager/infrastructure/ffmpeg/catalog.py) | Implementa MediaCatalog com disco, find_tools e ffprobe. |
| [infrastructure/ffmpeg/composer.py](../../src/videomanager/infrastructure/ffmpeg/composer.py) | Grafo de composição e comandos para exportação, quadros, reprodução, áudio e trechos paralelos. |
| [infrastructure/ffmpeg/converter.py](../../src/videomanager/infrastructure/ffmpeg/converter.py) | Inspeção de mídia, montagem de conversão, execução serial, progresso, cancelamento e publicação. |
| [infrastructure/ffmpeg/hardware.py](../../src/videomanager/infrastructure/ffmpeg/hardware.py) | Sonda encoders reais, mantém cache e traduz preferências em argumentos com fallback. |
| [infrastructure/ffmpeg/parallel.py](../../src/videomanager/infrastructure/ffmpeg/parallel.py) | Planeja concorrência da interpolação, renderiza trechos, concatena, mistura áudio e publica. |
| [infrastructure/ffmpeg/preview.py](../../src/videomanager/infrastructure/ffmpeg/preview.py) | Decodifica quadros, filmstrips, ondas e reprodução por FramePump com fila limitada. |
| [infrastructure/ffmpeg/thumbnail.py](../../src/videomanager/infrastructure/ffmpeg/thumbnail.py) | Gera/incorpora a capa opcional antes da publicação, com controle de processo. |
| [infrastructure/ffmpeg/trimmer.py](../../src/videomanager/infrastructure/ffmpeg/trimmer.py) | Consulta keyframes e traduz recorte rápido/exato e junção em comandos. |
| [infrastructure/qt/audio.py](../../src/videomanager/infrastructure/qt/audio.py) | PCM, QAudioSink, filas limitadas, relógio de áudio e descarte de gerações antigas. |
| [infrastructure/qt/runtime.py](../../src/videomanager/infrastructure/qt/runtime.py) | Implementa as fábricas e serviços desktop injetados na apresentação, sem estado de negócio. |
| [infrastructure/qt/text.py](../../src/videomanager/infrastructure/qt/text.py) | QtTextRasterizer com cache por conteúdo/instância, PNGs imutáveis e lock. |
| [infrastructure/qt/workers/convert_worker.py](../../src/videomanager/infrastructure/qt/workers/convert_worker.py) | Executa ConversionRequest com Converter, traduzindo término, falha e cancelamento em sinais. |
| [infrastructure/qt/workers/download_worker.py](../../src/videomanager/infrastructure/qt/workers/download_worker.py) | Constrói opções do pedido e executa Downloader, emitindo eventos da tarefa. |
| [infrastructure/qt/workers/engine_worker.py](../../src/videomanager/infrastructure/qt/workers/engine_worker.py) | Provisionamento do ffmpeg e atualização do mecanismo yt-dlp fora da UI. |
| [infrastructure/qt/workers/function_worker.py](../../src/videomanager/infrastructure/qt/workers/function_worker.py) | Executa uma callable com finished/failed/done; usado na escrita de snapshot. |
| [infrastructure/qt/workers/hwaccel_worker.py](../../src/videomanager/infrastructure/qt/workers/hwaccel_worker.py) | Executa sondagem de hardware em segundo plano. |
| [infrastructure/qt/workers/media_worker.py](../../src/videomanager/infrastructure/qt/workers/media_worker.py) | Adapta ReadMedia, repositório JSON e probe cancelável a QRunnable. |
| [infrastructure/qt/workers/preview_worker.py](../../src/videomanager/infrastructure/qt/workers/preview_worker.py) | Workers de quadro, reprodução, filmstrip, waveform e keyframes com cancelamento/tokens. |
| [infrastructure/qt/workers/probe_worker.py](../../src/videomanager/infrastructure/qt/workers/probe_worker.py) | Executa DownloadService.analyze com preferências capturadas e sinal done garantido. |
| [infrastructure/qt/workers/queue.py](../../src/videomanager/infrastructure/qt/workers/queue.py) | JobQueue: pools separadas e receptores de sinais que alimentam JobService por tentativa. |
| [infrastructure/qt/workers/signals.py](../../src/videomanager/infrastructure/qt/workers/signals.py) | Objetos QObject de sinais e emissão tolerante a encerramento. |
| [infrastructure/qt/workers/thumbnail_worker.py](../../src/videomanager/infrastructure/qt/workers/thumbnail_worker.py) | Carrega a miniatura remota para apresentação de mídia. |
| [infrastructure/storage/output_paths.py](../../src/videomanager/infrastructure/storage/output_paths.py) | Reserva de nome exclusivo, sufixos e nome personalizado com criação O_EXCL. |
| [infrastructure/storage/outputs.py](../../src/videomanager/infrastructure/storage/outputs.py) | FileOutputStore: lease, verificação de propriedade, abort e commit atômico. |
| [infrastructure/storage/project_json.py](../../src/videomanager/infrastructure/storage/project_json.py) | Esquema .vmp versão 1, caminhos, validação, IDs, mídias ausentes e escrita atômica. |
| [infrastructure/storage/projects.py](../../src/videomanager/infrastructure/storage/projects.py) | JsonProjectRepository adapta o serializador à porta de projetos. |
| [infrastructure/storage/settings.py](../../src/videomanager/infrastructure/storage/settings.py) | Persistência de Preferences, defaults de diretórios do sistema e resolução de pasta de downloads. |
| [infrastructure/system/binaries.py](../../src/videomanager/infrastructure/system/binaries.py) | Localiza/provisiona ffmpeg/ffprobe, localiza o runtime JavaScript (Deno/Node), valida binários e prepara ambiente de subprocessos. |
| [infrastructure/system/logs.py](../../src/videomanager/infrastructure/system/logs.py) | Log em arquivo com rotação e registro de exceções não tratadas (slots Qt e threads). |
| [infrastructure/system/memory.py](../../src/videomanager/infrastructure/system/memory.py) | Consulta de memória disponível em Linux/Windows para planejamento externo. |
| [infrastructure/system/process.py](../../src/videomanager/infrastructure/system/process.py) | ProcessControl: execução registrada, cancelamento, timeout e encerramento. |
| [infrastructure/yt_dlp/downloader.py](../../src/videomanager/infrastructure/yt_dlp/downloader.py) | Instância de YoutubeDL por tarefa, hooks, progresso, logs, cancelamento e resultado. |
| [infrastructure/yt_dlp/extras.py](../../src/videomanager/infrastructure/yt_dlp/extras.py) | Opção `js_runtimes` conforme o ambiente e capa tolerante (`TolerantEmbedThumbnailPP`) que não derruba o download. |
| [infrastructure/yt_dlp/formats.py](../../src/videomanager/infrastructure/yt_dlp/formats.py) | Normaliza dados brutos dos extratores, classifica presença de streams e monta FormatMatrix. |
| [infrastructure/yt_dlp/gateway.py](../../src/videomanager/infrastructure/yt_dlp/gateway.py) | Implementa DownloadGateway combinando probe e política de planejamento. |
| [infrastructure/yt_dlp/probe.py](../../src/videomanager/infrastructure/yt_dlp/probe.py) | Executa análise de URL, traduz erros e constrói MediaInfo/PlaylistInfo. |
| [infrastructure/yt_dlp/selector.py](../../src/videomanager/infrastructure/yt_dlp/selector.py) | Traduz escolhas em expressões, templates e pós-processadores yt-dlp. |

## Apresentação

| Módulo | Responsabilidade |
| --- | --- |
| [presentation/formatting.py](../../src/videomanager/presentation/formatting.py) | Exporta os formatadores de escolhas usados pelos presenters. |
| [presentation/qt/editor_project.py](../../src/videomanager/presentation/qt/editor_project.py) | Controller de diálogos e acervo; abre/importa/salva usando API pública do painel e serviços. |
| [presentation/qt/export_dialog.py](../../src/videomanager/presentation/qt/export_dialog.py) | Coleta opções, apresenta custo/avisos/descrição e pede preparação da exportação. |
| [presentation/qt/ffmpeg_setup.py](../../src/videomanager/presentation/qt/ffmpeg_setup.py) | Diálogo de descoberta/provisionamento, conectado ao worker pelo runtime. |
| [presentation/qt/fonts.py](../../src/videomanager/presentation/qt/fonts.py) | Carrega fontes empacotadas e substituição Calibri/Carlito após iniciar Qt. |
| [presentation/qt/fullscreen_preview.py](../../src/videomanager/presentation/qt/fullscreen_preview.py) | Janela de prévia ampliada, controles e sincronização visual com o editor. |
| [presentation/qt/icons.py](../../src/videomanager/presentation/qt/icons.py) | Cria ícones usados nos controles. |
| [presentation/qt/main_window.py](../../src/videomanager/presentation/qt/main_window.py) | Três abas, menus, destino, análise, playlists, configuração e coordenação da fila. |
| [presentation/qt/panels/convert_panel.py](../../src/videomanager/presentation/qt/panels/convert_panel.py) | Lista de arquivos locais, escolha de alvo e submissão via ProcessingService. |
| [presentation/qt/panels/edit_panel.py](../../src/videomanager/presentation/qt/panels/edit_panel.py) | Widgets e controller de edição: seleção, comandos do domínio, sessão, prévia e propriedades. |
| [presentation/qt/panels/edit_widgets.py](../../src/videomanager/presentation/qt/panels/edit_widgets.py) | Componentes visuais reutilizados pelo editor. |
| [presentation/qt/panels/media_card.py](../../src/videomanager/presentation/qt/panels/media_card.py) | Apresenta título, duração, origem e miniatura da mídia analisada. |
| [presentation/qt/panels/profiles_panel.py](../../src/videomanager/presentation/qt/panels/profiles_panel.py) | Perfis rápidos que geram escolhas sem IDs específicos de uma mídia. |
| [presentation/qt/panels/quality_panel.py](../../src/videomanager/presentation/qt/panels/quality_panel.py) | Controles de resolução, fps, container e áudio sobre FormatMatrix. |
| [presentation/qt/panels/queue_panel.py](../../src/videomanager/presentation/qt/panels/queue_panel.py) | Lista/delegate da fila, rótulos de estado, progresso, repetir, cancelar e abrir resultado. |
| [presentation/qt/panels/timeline.py](../../src/videomanager/presentation/qt/panels/timeline.py) | Pintura da timeline, hit testing, arrasto, seleção e emissão de intenções. |
| [presentation/qt/playlist_dialog.py](../../src/videomanager/presentation/qt/playlist_dialog.py) | Apresenta entradas e escolhas de download em lote. |
| [presentation/qt/ports.py](../../src/videomanager/presentation/qt/ports.py) | Contrato DesktopRuntimePort consumido pelos widgets/controllers; não importa implementação. |
| [presentation/qt/settings_dialog.py](../../src/videomanager/presentation/qt/settings_dialog.py) | Edita Preferences e apresenta capacidades/versões obtidas pelo runtime. |
| [presentation/qt/strings.py](../../src/videomanager/presentation/qt/strings.py) | Textos dos controles, avisos e mapeamento de códigos de estado para rótulos. |
| [presentation/qt/tasks.py](../../src/videomanager/presentation/qt/tasks.py) | WorkerRunner mantém QRunnable vivo até o término e solicita cancelamento. |
| [presentation/qt/theme.py](../../src/videomanager/presentation/qt/theme.py) | Cores, QPalette, QSS e estilos compartilhados. |

## Recursos e diretórios de apoio

- `resources/`: ícone PNG/SVG e fontes Carlito/Rapier com licença. Não contém estado do usuário.
- `tests/`: domínio, aplicação, contratos, arquitetura e regressões de mídia/Qt; veja [testes](testes.md).
- `packaging/`: especificação PyInstaller, provisionamento, scripts Linux/Windows e diagnóstico do pacote.
- `scripts/`: apoio à distribuição e comparação reproduzível de desempenho.
- `vendor/`, `build/`, `dist/`: binários e artefatos locais, ignorados pelo Git.
- `docs/`: manuais de uso e documentação técnica.
