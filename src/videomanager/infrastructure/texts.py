"""Textos da infraestrutura nos dois idiomas (ver :mod:`videomanager.domain.i18n`).

Mensagens do ffmpeg, do yt-dlp e do disco que chegam à tela, e as fases de
progresso da fila. O que só vai para o arquivo de log continua em português.
"""

from videomanager.domain.i18n import register

register({
    # --- genéricos ------------------------------------------------------------------
    "ERROR_UNEXPECTED": ("Erro inesperado ({kind}): {detail}", "Unexpected error ({kind}): {detail}"),
    "ERROR_UNEXPECTED_PROBE": (
        "Erro inesperado ao analisar a URL ({kind}): {detail}",
        "Unexpected error while analyzing the URL ({kind}): {detail}",
    ),
    "ERROR_NO_DETAIL": ("erro não informado", "unreported error"),
    "LOG_WARNING": ("aviso: {message}", "warning: {message}"),
    "LOG_ERROR": ("erro: {message}", "error: {message}"),

    # --- fases de progresso ---------------------------------------------------------
    "PHASE_DOWNLOADING": ("Baixando", "Downloading"),
    "PHASE_DOWNLOADED": ("Download concluído, processando", "Download finished, processing"),
    "PHASE_MERGING": ("Juntando vídeo e áudio", "Merging video and audio"),
    "PHASE_EXTRACTING_AUDIO": ("Extraindo áudio", "Extracting audio"),
    "PHASE_CONVERTING_VIDEO": ("Convertendo vídeo", "Converting video"),
    "PHASE_REMUXING": ("Trocando o container", "Changing the container"),
    "PHASE_METADATA": ("Gravando metadados", "Writing metadata"),
    "PHASE_THUMBNAIL": ("Embutindo a capa", "Embedding the thumbnail"),
    "PHASE_SUBTITLES": ("Embutindo legendas", "Embedding subtitles"),
    "PHASE_MOVING": ("Movendo para a pasta de destino", "Moving to the destination folder"),
    "PHASE_PROCESSING": ("Processando", "Processing"),
    "PHASE_CONVERTING": ("Convertendo", "Converting"),
    "PHASE_TRIMMING": ("Recortando", "Trimming"),
    "PHASE_EXPORTING": ("Exportando", "Exporting"),
    "PHASE_INTERPOLATING": ("Interpolando", "Interpolating"),

    # --- ffmpeg: disponibilidade e instalação ---------------------------------------
    "FFMPEG_UNAVAILABLE": ("FFmpeg não disponível.", "FFmpeg isn't available."),
    "FFMPEG_RUN_FAILED": ("Não foi possível executar o ffmpeg: {error}", "Couldn't run ffmpeg: {error}"),
    "FFMPEG_BROKEN": (
        "O ffmpeg encontrado não executou corretamente (código {code}). O arquivo pode estar corrompido.",
        "The ffmpeg found didn't run correctly (code {code}). The file may be corrupt.",
    ),
    "FFMPEG_NO_BUILD": (
        "Não há build automática de ffmpeg para esta plataforma ({platform}). Instale o ffmpeg "
        "manualmente e ele será detectado no PATH.",
        "There's no automatic ffmpeg build for this platform ({platform}). Install ffmpeg "
        "manually and it will be detected on the PATH.",
    ),
    "FFMPEG_INSECURE_REDIRECT": (
        "O download do ffmpeg foi redirecionado para uma conexão sem criptografia e foi interrompido.",
        "The ffmpeg download was redirected to an unencrypted connection and was stopped.",
    ),
    "FFMPEG_DOWNLOAD_FAILED": (
        "Falha ao baixar o ffmpeg: {reason}. Verifique a conexão.",
        "Couldn't download ffmpeg: {reason}. Check your connection.",
    ),
    "FFMPEG_WRITE_FAILED": ("Falha ao gravar o download do ffmpeg: {error}", "Couldn't save the ffmpeg download: {error}"),
    "FFMPEG_ARCHIVE_CORRUPT": (
        "O arquivo do ffmpeg baixado parece corrompido: {error}",
        "The downloaded ffmpeg archive looks corrupt: {error}",
    ),
    "FFMPEG_ARCHIVE_MISSING": ("O arquivo baixado não continha: {names}", "The downloaded archive didn't contain: {names}"),
    "FFMPEG_EXTRACTED_UNUSABLE": (
        "Os binários foram extraídos mas não ficaram utilizáveis em {path}. Verifique as permissões da pasta.",
        "The binaries were extracted but aren't usable in {path}. Check the folder's permissions.",
    ),
    "FFMPEG_NOT_FOUND": (
        "ffmpeg e ffprobe não foram encontrados. Eles são necessários para juntar vídeo com áudio e "
        "para converter arquivos.",
        "ffmpeg and ffprobe weren't found. They're needed to merge video with audio and to convert files.",
    ),

    # --- conversão --------------------------------------------------------------------
    "CONVERT_FILE_NOT_FOUND": ("Arquivo não encontrado: {path}", "File not found: {path}"),
    "CONVERT_INSPECT_FAILED": ("Falha ao inspecionar o arquivo: {error}", "Couldn't inspect the file: {error}"),
    "CONVERT_NOT_MEDIA": (
        "O ffprobe não reconheceu “{name}” como arquivo de mídia.",
        "ffprobe didn't recognize “{name}” as a media file.",
    ),
    "CONVERT_PROBE_UNREADABLE": ("Resposta do ffprobe ilegível.", "Unreadable ffprobe response."),
    "CONVERT_NO_AUDIO": ("“{name}” não tem trilha de áudio para converter.", "“{name}” has no audio track to convert."),
    "CONVERT_NO_VIDEO": (
        "“{name}” não tem trilha de vídeo. Use a conversão para áudio.",
        "“{name}” has no video track. Use the audio conversion.",
    ),
    "CONVERT_AUDIO_FORMAT_UNSUPPORTED": ("Formato de áudio não suportado: {codec}", "Unsupported audio format: {codec}"),
    "CONVERT_VIDEO_CODEC_UNSUPPORTED": ("Codec de vídeo não suportado: {codec}", "Unsupported video codec: {codec}"),
    "CONVERT_AUDIO_CODEC_UNSUPPORTED": ("Codec de áudio não suportado: {codec}", "Unsupported audio codec: {codec}"),
    "CONVERT_START_FAILED": ("Não foi possível iniciar o ffmpeg: {error}", "Couldn't start ffmpeg: {error}"),
    "CONVERT_FAILED": ("O ffmpeg falhou na conversão: {detail}", "ffmpeg failed during the conversion: {detail}"),
    "CONVERT_NO_OUTPUT": (
        "O ffmpeg terminou sem erro mas não gerou o arquivo de saída.",
        "ffmpeg finished without errors but didn't create the output file.",
    ),

    # --- composição e exportação ----------------------------------------------------
    "COMPOSE_TEXT_ASSETS_MISSING": (
        "Os recursos de texto não foram preparados para esta renderização.",
        "The text assets weren't prepared for this render.",
    ),
    "COMPOSE_GIF_NO_IMAGE": (
        "Não há imagem na linha do tempo para exportar como GIF.",
        "There's no image on the timeline to export as a GIF.",
    ),
    "COMPOSE_NOTHING": ("Não há nada na linha do tempo para exportar.", "There's nothing on the timeline to export."),
    "COMPOSE_NO_AUDIBLE": (
        "Não há blocos de áudio audíveis na linha do tempo para exportar.",
        "There are no audible audio clips on the timeline to export.",
    ),
    "COMPOSE_ALL_MUTED": (
        "Todos os blocos estão mudos ou vazios: não há o que exportar.",
        "Every clip is muted or empty: there's nothing to export.",
    ),
    "COMPOSE_SEGMENT_NO_IMAGE": ("O trecho não tem imagem para exportar.", "The segment has no image to export."),
    "PARALLEL_SEGMENT_FAILED": (
        "O ffmpeg falhou ao interpolar um dos trechos: {detail}",
        "ffmpeg failed to interpolate one of the segments: {detail}",
    ),
    "PARALLEL_SEGMENT_MISSING": (
        "Um dos trechos da exportação não foi gerado; nada foi gravado.",
        "One of the export segments wasn't created; nothing was saved.",
    ),
    "PARALLEL_NO_DETAIL": ("sem detalhes do ffmpeg", "no details from ffmpeg"),
    # Etapas finais da exportação dividida, que completam as três frases abaixo.
    "STEP_CONCAT": ("emendar os trechos", "join the segments"),
    "STEP_AUDIO": ("gerar o som", "render the audio"),
    "STEP_MUX": ("juntar imagem e som", "combine picture and sound"),
    "STEP_START_FAILED": ("Não foi possível {step}: {error}", "Couldn't {step}: {error}"),
    "STEP_TIMEOUT": (
        "O ffmpeg passou de {minutes} min para {step} e foi interrompido.",
        "ffmpeg took more than {minutes} min to {step} and was stopped.",
    ),
    "STEP_FAILED": ("O ffmpeg falhou ao {step}: {detail}", "ffmpeg failed to {step}: {detail}"),

    # --- recorte ----------------------------------------------------------------------
    "TRIM_KEYFRAMES_FAILED": ("Falha ao mapear os keyframes: {error}", "Couldn't map the keyframes: {error}"),
    "TRIM_KEYFRAMES_TIMEOUT": (
        "O ffprobe passou do tempo ao mapear os keyframes deste arquivo.",
        "ffprobe timed out mapping this file's keyframes.",
    ),
    "TRIM_KEYFRAMES_UNREADABLE": (
        "O ffprobe não conseguiu mapear os keyframes deste arquivo.",
        "ffprobe couldn't map this file's keyframes.",
    ),
    "TRIM_NO_SEGMENTS": ("Não há nenhum trecho para exportar.", "There are no segments to export."),
    "TRIM_SEGMENT_TOO_SHORT": (
        "O trecho {segment} é curto demais para virar um arquivo.",
        "The segment {segment} is too short to become a file.",
    ),
    "TRIM_NO_TRACKS": (
        "“{name}” não tem trilha de vídeo nem de áudio para recortar.",
        "“{name}” has no video or audio track to trim.",
    ),
    "TRIM_JOIN_NEEDS_REENCODE": (
        "Juntar vários trechos num arquivo só exige recodificar. Escolha o corte exato, ou exporte "
        "cada trecho em um arquivo.",
        "Joining several segments into one file requires re-encoding. Choose the exact cut, or "
        "export each segment to its own file.",
    ),

    # --- prévia -----------------------------------------------------------------------
    "PREVIEW_START_FAILED": (
        "Não foi possível iniciar o FFmpeg para atualizar a prévia.",
        "Couldn't start FFmpeg to update the preview.",
    ),
    "PREVIEW_TIMEOUT": (
        "A atualização da prévia excedeu o prazo. Tente novamente.",
        "The preview update timed out. Try again.",
    ),
    "PREVIEW_READ_FAILED": (
        "Não foi possível ler uma mídia da prévia. Confira os arquivos do projeto.",
        "Couldn't read a media file for the preview. Check the project's files.",
    ),
    "PREVIEW_FILTER_FAILED": (
        "O FFmpeg não conseguiu aplicar um efeito da prévia. Confira a versão instalada.",
        "FFmpeg couldn't apply a preview effect. Check the installed version.",
    ),
    "PREVIEW_RENDER_FAILED": (
        "Não foi possível renderizar a prévia. Confira as mídias e os efeitos do projeto.",
        "Couldn't render the preview. Check the project's media and effects.",
    ),
    "PREVIEW_INCOMPLETE": (
        "A prévia não retornou um quadro completo. Confira a mídia nesse instante.",
        "The preview didn't return a complete frame. Check the media at this point.",
    ),
    "PREVIEW_STREAM_INVALID": ("Fluxo de quadros da prévia inválido.", "Invalid preview frame stream."),
    "PREVIEW_PLAYBACK_START_FAILED": (
        "Não foi possível iniciar a reprodução da prévia.",
        "Couldn't start the preview playback.",
    ),
    "PREVIEW_UPDATE_FAILED": ("Não foi possível atualizar a prévia.", "Couldn't update the preview."),
    "PREVIEW_PLAYBACK_INTERRUPTED": (
        "A reprodução da prévia foi interrompida por uma falha.",
        "The preview playback stopped because of a failure.",
    ),
    "TEXT_NEEDS_GUI": (
        "A aplicação gráfica precisa estar inicializada para preparar textos.",
        "The graphical application must be running to prepare texts.",
    ),
    "TEXT_IMAGE_FAILED": ("Não foi possível preparar a imagem do texto.", "Couldn't prepare the text image."),

    # --- encoder ----------------------------------------------------------------------
    "ENCODER_USING": ("Usando {encoder}.", "Using {encoder}."),
    "ENCODER_NO_FFMPEG": (
        "O ffmpeg ainda não foi localizado; a exportação usará software.",
        "ffmpeg hasn't been found yet; exports will use software.",
    ),
    "ENCODER_NO_GPU": (
        "Nenhuma placa disponível respondeu ao teste — a exportação vai usar {encoder}.",
        "No available GPU passed the test — exports will use {encoder}.",
    ),
    "ENCODER_GPU_IN_USE": ("Placa em uso: {encoder}.", "GPU in use: {encoder}."),

    # --- arquivos de saída e de projeto --------------------------------------------
    "OUTPUT_BAD_NAME": (
        "Use somente um nome de arquivo, sem caminhos ou separadores.",
        "Use just a file name, without paths or separators.",
    ),
    # Nome do arquivo, e por isso dado: sai no idioma do momento em que é criado.
    "OUTPUT_CONVERTED_SUFFIX": (" (convertido)", " (converted)"),
    "OUTPUT_DIR_FAILED": (
        "Não foi possível usar a pasta de destino {directory}: {error}",
        "Couldn't use the destination folder {directory}: {error}",
    ),
    "OUTPUT_CREATE_FAILED": (
        "Não foi possível criar o arquivo de saída em {directory}: {error}",
        "Couldn't create the output file in {directory}: {error}",
    ),
    "OUTPUT_LEASE_CHANGED": (
        "O destino reservado foi alterado por outra operação.",
        "The reserved destination was changed by another operation.",
    ),
    "PROJECT_INVALID": ("Estrutura do arquivo de projeto inválida: {field}.", "Invalid project file structure: {field}."),
    "PROJECT_INVALID_DETAIL": ("Estrutura do arquivo de projeto inválida: {error}", "Invalid project file structure: {error}"),
    "PROJECT_VERSION_UNSUPPORTED": (
        "Versão de projeto {version} não é suportada por esta versão do aplicativo.",
        "Project version {version} isn't supported by this version of the app.",
    ),
    "PROJECT_TRACKS_CORRUPT": (
        "Estrutura do arquivo de projeto corrompida: trilhas inválidas.",
        "Corrupt project file structure: invalid tracks.",
    ),
    "PROJECT_SAVE_FAILED": ("Não foi possível salvar o projeto em {path}: {error}", "Couldn't save the project to {path}: {error}"),
    "PROJECT_NOT_FOUND": ("Arquivo de projeto não encontrado: {path}", "Project file not found: {path}"),
    "PROJECT_CORRUPT": ("Arquivo de projeto corrompido ou inválido: {error}", "Corrupt or invalid project file: {error}"),
    "PROJECT_READ_FAILED": ("Erro ao ler arquivo de projeto: {error}", "Error reading the project file: {error}"),
    "PROJECT_FORMAT_INVALID": ("Formato de projeto inválido.", "Invalid project format."),
    # O campo que a validação recusou, quando não é o nome de uma chave do JSON.
    "PROJECT_FIELD_DOCUMENT": ("documento", "document"),
    "PROJECT_FIELD_TRACKS": ("trilhas", "tracks"),
    "PROJECT_FIELD_TRACK": ("trilha", "track"),
    "PROJECT_FIELD_TRACK_ID": ("ID de trilha duplicado", "duplicate track ID"),
    "PROJECT_FIELD_TRACK_KIND": ("tipo de trilha", "track type"),
    "PROJECT_FIELD_CLIPS": ("clipes", "clips"),
    "PROJECT_FIELD_CLIP": ("clipe", "clip"),
    "PROJECT_FIELD_CLIP_ID": ("ID de clipe duplicado", "duplicate clip ID"),
    "PROJECT_FIELD_CLIP_DURATION": ("duração do clipe", "clip duration"),
    "PROJECT_FIELD_KEYFRAMES": ("quadros-chave", "keyframes"),
    "PROJECT_FIELD_KEYFRAME": ("quadro-chave", "keyframe"),
    "PROJECT_FIELD_KEYFRAME_OPACITY": ("opacidade do quadro-chave", "keyframe opacity"),
    "PROJECT_FIELD_OVERLAY": ("tipo de sobreposição", "overlay type"),
    "PROJECT_FIELD_MEDIA_PATH": ("caminho da mídia", "media path"),
    "PROJECT_FIELD_MEDIA_KIND": ("tipo de mídia", "media type"),

    # --- yt-dlp ---------------------------------------------------------------------
    "MEDIA_UNTITLED": ("Sem título", "Untitled"),
    # O motor se atualiza pelo menu Ferramentas; o texto apontava Configurações,
    # onde não há como fazer isso.
    "PROBE_UNSUPPORTED": (
        "Nenhum extrator reconhece esta URL. Confira o endereço; se o site for novo, atualizar o "
        "motor de download, no menu Ferramentas, pode resolver.",
        "No extractor recognizes this URL. Check the address; if the site is new, updating the "
        "download engine from the Tools menu may help.",
    ),
    "PROBE_DRM": (
        "Esta mídia é protegida por DRM e não pode ser baixada.",
        "This media is DRM-protected and can't be downloaded.",
    ),
    "PROBE_LOGIN": (
        "Esta mídia exige conta conectada (privada, de membros ou com restrição de idade). Em "
        "Configurações, escolha o navegador em que você já está logado para que os cookies sejam usados.",
        "This media requires a signed-in account (private, members-only or age-restricted). In "
        "Settings, choose the browser you're already signed in to so its cookies are used.",
    ),
    "PROBE_GEO": ("Esta mídia está bloqueada na sua região.", "This media is blocked in your region."),
    "PROBE_UNAVAILABLE": ("Esta mídia não está mais disponível.", "This media is no longer available."),
    "PROBE_NETWORK": (
        "Não foi possível conectar. Verifique sua conexão e tente novamente.",
        "Couldn't connect. Check your connection and try again.",
    ),
    # A etapa que falhou, completando a frase seguinte.
    "ACTION_ANALYZE": ("analisar a URL", "analyze the URL"),
    "ACTION_DOWNLOAD": ("baixar", "download"),
    "PROBE_FAILED": ("Falha ao {action}: {detail}", "Couldn't {action}: {detail}"),
    "PROBE_NETWORK_FAILED": ("Falha de rede ao analisar a URL: {error}", "Network error while analyzing the URL: {error}"),
    "PROBE_NO_INFO": ("O extrator não devolveu informação utilizável.", "The extractor returned no usable information."),
    "PROBE_EMPTY_PLAYLIST": ("Esta playlist está vazia ou é inacessível.", "This playlist is empty or inaccessible."),
    "PROBE_ALL_DRM": ("Todos os formatos desta mídia são protegidos por DRM.", "Every format of this media is DRM-protected."),
    "PROBE_LIVE_NOT_STARTED": (
        "Esta transmissão ao vivo ainda não oferece formatos para baixar. Tente novamente depois que "
        "ela começar.",
        "This live stream doesn't offer downloadable formats yet. Try again after it starts.",
    ),
    "PROBE_NO_FORMATS": (
        "A URL foi reconhecida, mas nenhum formato utilizável foi oferecido. Se a mídia exige login, "
        "configure o navegador para leitura de cookies.",
        "The URL was recognized, but no usable format was offered. If the media requires signing "
        "in, set up the browser for reading cookies.",
    ),
    "DOWNLOAD_WRITE_FAILED": (
        "Falha ao gravar o arquivo: {error}. Verifique espaço em disco e permissões da pasta de destino.",
        "Couldn't write the file: {error}. Check the disk space and the destination folder's permissions.",
    ),
    "THUMBNAIL_NOT_EMBEDDED": ("A capa não foi embutida: {error}", "The thumbnail wasn't embedded: {error}"),
})
