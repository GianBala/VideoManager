"""Texto visível da interface, em pt-BR.

Concentrado num módulo só para que traduzir a aplicação depois não exija mexer em
nenhuma tela. Organizado por área da janela, na mesma ordem em que aparece.
"""

from __future__ import annotations

# --- janela ------------------------------------------------------------------
ABOUT_TITLE = "Sobre o Video Manager"
ABOUT_BODY = (
    "<b>Video Manager {version}</b><br><br>"
    "Baixa vídeo e áudio de centenas de plataformas e converte arquivos locais.<br><br>"
    "Usa <b>yt-dlp</b> {ytdlp} para extração e <b>ffmpeg</b> para processamento.<br><br>"
    "Respeitar os termos de uso e os direitos autorais de cada plataforma é "
    "responsabilidade de quem usa."
)

# --- abas --------------------------------------------------------------------
TAB_DOWNLOAD = "Download"
TAB_CONVERT = "Convert"
TAB_EDIT = "Editar"

# --- menus -------------------------------------------------------------------
MENU_FILE = "&Arquivo"
MENU_TOOLS = "&Ferramentas"
MENU_HELP = "A&juda"
ACTION_SETTINGS = "Configurações…"
ACTION_UPDATE_ENGINE = "Atualizar motor de download (yt-dlp)…"
ACTION_NEW_PROJECT = "Novo projeto"
ACTION_OPEN_PROJECT = "Abrir projeto…"
ACTION_SAVE_PROJECT = "Salvar projeto"
ACTION_SAVE_PROJECT_AS = "Salvar projeto como…"
ACTION_IMPORT_MEDIA = "Importar mídia…"
ACTION_EXPORT_VIDEO = "Exportar vídeo…"
ACTION_CONVERT_ADD = "Adicionar arquivos para conversão…"
ACTION_CONVERT_REMOVE = "Remover arquivos selecionados"
ACTION_CONVERT_CLEAR = "Limpar lista de conversão"
ACTION_OPEN_DEST = "Abrir pasta de destino"
ACTION_OPEN_DOWNLOAD_DEST = "Abrir pasta de downloads…"
ACTION_OPEN_CONVERT_DEST = "Abrir pasta de destino…"
ACTION_QUIT = "Sair"
ACTION_ABOUT = "Sobre"
EDIT_NEW_BUTTON = "Novo"
EDIT_OPEN_BUTTON = "Abrir…"
EDIT_SAVE_BUTTON = "Salvar"
EDIT_PROJECT_STATUS = "Projeto: {name}{dirty}"
EDIT_UNTITLED = "Sem título"
CONVERT_CLEAR = "Limpar lista"

# --- barra de URL ------------------------------------------------------------
URL_LABEL = "Endereço"
URL_PLACEHOLDER = "Cole aqui o link do vídeo, da playlist ou do canal"
URL_ANALYZE = "Analisar"
URL_ANALYZING = "Analisando…"
URL_CANCEL = "Cancelar"
URL_CANCEL_TIP = "Cancelar a análise do endereço em andamento"
URL_PASTE_AND_ANALYZE = "Colar e analisar"

# --- card da mídia -----------------------------------------------------------
CARD_EMPTY = "Nenhuma mídia analisada.\nCole um endereço acima e clique em Analisar."
CARD_LIVE = "TRANSMISSÃO AO VIVO"
CARD_NO_THUMB = "sem\nminiatura"
CARD_SUBTITLES = "{count} legenda(s) disponível(is)"

# --- modo --------------------------------------------------------------------
MODE_LABEL = "O que baixar"
MODE_VIDEO = "Vídeo (com áudio)"
MODE_AUDIO = "Somente áudio"

# --- controles de vídeo ------------------------------------------------------
QUALITY_GROUP = "Qualidade"
LABEL_RESOLUTION = "Resolução"
LABEL_FPS = "Framerate"
LABEL_CODEC = "Codec de vídeo"
LABEL_CONTAINER = "Container"
LABEL_AUDIO_TRACK = "Trilha de áudio"
LABEL_ESTIMATED_SIZE = "Tamanho estimado"
ANY_FPS = "Qualquer"
ANY_CODEC = "Qualquer"
CONTAINER_AUTO_LABEL = "Automático (o melhor sem recodificar)"

TIP_CONTAINER = (
    "MKV aceita qualquer combinação de codecs, então nunca obriga a recodificar.\n"
    "MP4 é o mais compatível com aparelhos e TVs.\n"
    "No modo automático o próprio yt-dlp escolhe um container compatível."
)
TIP_RESOLUTION = (
    "Só aparecem as resoluções que esta mídia realmente oferece.\n"
    "Quando a plataforma não informa a resolução, a opção é exibida pelo bitrate."
)
TIP_CODEC = (
    "Só aparecem os codecs que existem na resolução escolhida. Acima de 1080p é "
    "comum não haver H.264: o YouTube entrega 1440p e 2160p só em VP9 e AV1.\n"
    "A escolha fica guardada — se ela não existir na resolução atual, volta "
    "sozinha assim que você escolher uma resolução que a tenha."
)

# --- controles de áudio ------------------------------------------------------
LABEL_AUDIO_FORMAT = "Formato"
LABEL_AUDIO_QUALITY = "Bitrate"
AUDIO_CODEC_BEST = "Original (sem perda, mais rápido)"
AUDIO_SOURCE_INFO = "Melhor trilha da origem: {bitrate}"

TIP_AUDIO_FORMAT = (
    "“Original” apenas extrai o áudio do arquivo, sem recodificar: é instantâneo "
    "e não perde nada.\nOs outros formatos recodificam, o que sempre custa alguma "
    "qualidade."
)

# --- destino -----------------------------------------------------------------
DEST_LABEL = "Destino"
DEST_BROWSE = "Escolher…"
DEST_TOOLTIP = "Pasta onde os arquivos concluídos são salvos"

# --- perfis ------------------------------------------------------------------
PROFILES_GROUP = "Perfis rápidos"
PROFILE_HINT = "Um clique configura tudo e adiciona à fila."
PROFILE_MP4_1080 = "MP4 1080p"
PROFILE_MP4_1080_SUB = "compatível com tudo"
PROFILE_MP3_320 = "MP3 320k"
PROFILE_MP3_320_SUB = "só o áudio"
PROFILE_MAX = "Máxima qualidade"
PROFILE_MAX_SUB = "MKV, sem recodificar"
PROFILE_AUDIO_ORIGINAL = "Áudio original"
PROFILE_AUDIO_ORIGINAL_SUB = "sem perda"

# --- ação --------------------------------------------------------------------
ADD_TO_QUEUE = "Adicionar à fila"
ADD_TO_QUEUE_TIP = "Analise um endereço antes de adicionar à fila"

# --- fila --------------------------------------------------------------------
QUEUE_GROUP = "Fila"
QUEUE_COLUMNS = ("Título", "Saída", "Situação", "Progresso", "Velocidade")
QUEUE_EMPTY = "A fila está vazia."
QUEUE_CANCEL = "Cancelar"
QUEUE_RETRY = "Tentar de novo"
QUEUE_OPEN_FOLDER = "Abrir pasta do arquivo"
QUEUE_OPEN_FILE = "Abrir arquivo"
QUEUE_COPY_ERROR = "Copiar mensagem de erro"
QUEUE_SHOW_LOG = "Ver detalhes técnicos"
QUEUE_CLEAR_FINISHED = "Limpar encerrados"
QUEUE_CANCEL_ALL = "Cancelar todos"
QUEUE_LOG_TITLE = "Detalhes técnicos — {title}"

# --- status bar --------------------------------------------------------------
STATUS_COUNTS = "{active} em andamento · {pending} na fila · {done} concluídos"
STATUS_FFMPEG = "ffmpeg: {source}"
STATUS_ENQUEUED = "{count} tarefa(s) adicionada(s) à fila — acompanhe na aba Download"
# Na barra de status, e não num diálogo: não poder gravar as preferências não
# interrompe nada do que está em andamento.
STATUS_SETTINGS_FAILED = "Não foi possível gravar as preferências: {error}"

# --- playlist ----------------------------------------------------------------
PLAYLIST_TITLE = "Selecionar itens da playlist"
PLAYLIST_HEADER = "“{title}” tem {count} itens. Marque os que deseja baixar."
PLAYLIST_SELECT_ALL = "Marcar todos"
PLAYLIST_SELECT_NONE = "Desmarcar todos"
PLAYLIST_ADD = "Adicionar {count} à fila"
PLAYLIST_MODE_LABEL = "Baixar como"
PLAYLIST_MODE_VIDEO = "Vídeo"
PLAYLIST_MODE_AUDIO = "Somente áudio"
PLAYLIST_NOTE = (
    "Os itens usam a configuração de qualidade atual. Cada vídeo pode oferecer "
    "formatos diferentes, então a escolha é feita por limite de resolução e não "
    "por formato fixo."
)

# --- conversor local ---------------------------------------------------------
CONVERT_FILES_GROUP = "Arquivos a converter"
CONVERT_PICK = "Escolher arquivos…"
CONVERT_REMOVE = "Remover selecionados"
CONVERT_DROP_HINT = "Arraste arquivos aqui, ou clique em “Escolher arquivos…”"
CONVERT_TO_AUDIO = "Converter para áudio"
CONVERT_TO_VIDEO = "Converter vídeo"
CONVERT_START = "Converter"
CONVERT_SAME_FOLDER = "Salvar na mesma pasta do arquivo original"
CONVERT_TARGET_GROUP = "Converter para"
CONVERT_PLAN = "O que vai acontecer: {plan}"
CONVERT_ESTIMATED_SIZE = "Tamanho estimado: {size}"
CONVERT_RESIZE = "Redimensionar para"
CONVERT_KEEP = "Manter original"
CONVERT_NO_FILES = "Escolha ao menos um arquivo."

# --- editor de vídeo ---------------------------------------------------------
EDIT_IMPORT = "Importar mídia…"
EDIT_IMPORT_TIP = (
    "Traz vídeos, áudios e imagens para a edição. Você também pode "
    "arrastar arquivos direto da área de trabalho para cá."
)
EDIT_IMPORT_REJECTED = "Estes arquivos foram ignorados:"
EDIT_POOL_TIP = "Mídias já importadas nesta edição"
EDIT_MEDIA_POOL_TITLE = "Mídia do projeto"
EDIT_MEDIA_EMPTY = "Arraste mídias para cá\nou clique em “+ Importar”"
EDIT_MEDIA_REMOVE = "Remover do projeto"
EDIT_MEDIA_REMOVE_TITLE = "Remover mídia?"
EDIT_MEDIA_REMOVE_BODY = (
    "A mídia “{name}” está sendo usada em {count} bloco(s) da linha do tempo. "
    "Removê-la do projeto também excluirá esses blocos.\n\nDeseja continuar?"
)
EDIT_CLEAR_UNUSED = "Limpar não utilizados"
EDIT_CLEAR_UNUSED_TIP = "Remove da biblioteca as mídias que não estão em nenhuma faixa"
EDIT_MEDIA_IN_USE_TITLE = "Mídia em Uso"
EDIT_MEDIA_IN_USE_MSG = (
    "A mídia “{name}” está em uso em {count} bloco(s) na linha do tempo e não pode ser removida. "
    "Remova seus blocos das faixas primeiro."
)
EDIT_MEDIA_COUNT = "{count} mídia(s)"
EDIT_EXPORT_BUTTON = "Exportar"
EDIT_EXPORT_BUTTON_TIP = "Configurar e exportar o vídeo para a fila (Ctrl+E)"
EXPORT_DIALOG_TITLE = "Exportar Vídeo"
EXPORT_SUMMARY_GROUP = "Resumo do Projeto"
EXPORT_SETTINGS_GROUP = "Configurações de Saída"
EXPORT_DESTINATION_GROUP = "Destino"
EXPORT_DESTINATION_FOLDER = "Pasta de destino:"
EXPORT_DESTINATION_PICK = "Procurar…"
EXPORT_DESTINATION_PICK_TITLE = "Escolher pasta de destino"
EXPORT_ACTION_ENQUEUE = "Adicionar à fila"
EXPORT_ACTION_CANCEL = "Cancelar"
EXPORT_MODE_AUDIO_ONLY = "Exportar somente áudio"
EXPORT_MODE_AUDIO_ONLY_TIP = (
    "Descarta a imagem e exporta apenas a mixagem sonora de todas as trilhas"
)
EXPORT_CONTAINER = "Formato de vídeo"
EXPORT_CONTAINER_TIP = "Formato do arquivo de vídeo gerado (container)"
EXPORT_VIDEO_CODEC = "Codec de vídeo"
EXPORT_VIDEO_CODEC_TIP = "Algoritmo de compressão de vídeo (H.264, HEVC, AV1, VP9)"
EXPORT_AUDIO_FORMAT = "Formato de áudio"
EXPORT_AUDIO_FORMAT_TIP = "Formato e codec do arquivo de som gerado"
EXPORT_ESTIMATED_SIZE = "Tamanho estimado"
EDIT_INSERT = "Inserir no cursor"
EDIT_INSERT_TIP = (
    "Coloca a mídia escolhida na linha do tempo, a partir de onde o "
    "cursor estiver. Se não houver trilha compatível com espaço livre, "
    "uma trilha nova é criada."
)
EDIT_EMPTY = (
    "Importe vídeos, fotos ou áudios para montar a edição.\n"
    "Você também pode arrastar os arquivos para cá."
)
EDIT_COLLAPSE = "Retrair prévia"
EDIT_EXPAND = "Expandir prévia"
EDIT_COLLAPSE_TIP = "Encolhe a imagem para a linha do tempo ficar com a janela"
EDIT_FILE_FILTER = (
    "Mídia (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts *.mpg *.mpeg "
    "*.mp3 *.m4a *.aac *.opus *.ogg *.flac *.wav "
    "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;"
    "Vídeo (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts);;"
    "Áudio (*.mp3 *.m4a *.aac *.opus *.ogg *.flac *.wav);;"
    "Imagem (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Todos (*)"
)
EDIT_NO_PLAYBACK = "Não há imagem nem som para reproduzir neste arquivo"

# transporte
EDIT_PLAY = "Reproduzir"
EDIT_PAUSE = "Pausar"
EDIT_TO_START = "Ir para o início"
EDIT_TO_END = "Ir para o fim"
EDIT_PREV_FRAME = "Quadro anterior"
EDIT_NEXT_FRAME = "Próximo quadro"
EDIT_BACK = "Voltar 1 s"
EDIT_FORWARD = "Avançar 1 s"
EDIT_PREV_KEY = (
    "Keyframe anterior — o ponto de corte rápido mais próximo antes do cursor"
)
EDIT_NEXT_KEY = "Próximo keyframe — o ponto de corte rápido logo à frente"
EDIT_PREV_KEY_SHORT = "◁ keyframe"
EDIT_NEXT_KEY_SHORT = "keyframe ▷"
EDIT_POSITION = "{current}  /  {total}"
EDIT_FRAME_NUMBER = "quadro {index}"
EDIT_FULLSCREEN = "Tela cheia"
EDIT_FULLSCREEN_TIP = "Ver a prévia em tela cheia (F) — a barra some sozinha"
EDIT_FULLSCREEN_TITLE = "Prévia em tela cheia"
EDIT_EXIT_FULLSCREEN = "Sair"
EDIT_EXIT_FULLSCREEN_TIP = "Sair da tela cheia (Esc)"
EDIT_VOLUME = "Volume da prévia"
EDIT_LOOP = "Loop"
EDIT_LOOP_TIP = "Reproduzir continuamente em loop ao chegar ao final"
EDIT_MUTE = "Silenciar"
EDIT_UNMUTE = "Voltar o som"
EDIT_SOUND = "♪"
EDIT_MUTED = "✕"

# barra da linha do tempo
EDIT_SPLIT = "Dividir"
EDIT_DELETE = "Excluir bloco"
EDIT_TRIM_LEFT = "Apagar à esquerda"
EDIT_TRIM_LEFT_TIP = (
    "Apaga o trecho do bloco que está antes do cursor. O mesmo que arrastar a "
    "ponta esquerda até aqui, sem precisar mirar no quadro."
)
EDIT_TRIM_RIGHT = "Apagar à direita"
EDIT_TRIM_RIGHT_TIP = (
    "Apaga o trecho do bloco que está depois do cursor. O mesmo que arrastar a "
    "ponta direita até aqui, sem precisar mirar no quadro."
)
EDIT_DETACH = "Separar áudio"
EDIT_DETACH_TIP = (
    "Tira o som do bloco de vídeo e o põe numa trilha de áudio própria, na "
    "mesma posição — o vídeo fica mudo e o som passa a se mover sozinho"
)
EDIT_COPY = "Copiar"
EDIT_PASTE = "Colar"
EDIT_ADD_VIDEO_TRACK = "+ Vídeo"
EDIT_ADD_AUDIO_TRACK = "+ Áudio"
EDIT_ADD_ADDITIONAL_TRACK = "+ Adicionais"
EDIT_ADD_VIDEO_TRACK_FULL = "Nova trilha de vídeo"
EDIT_ADD_AUDIO_TRACK_FULL = "Nova trilha de áudio"
EDIT_ADD_ADDITIONAL_TRACK_FULL = "Nova trilha de adicionais"
EDIT_EXTRAS_TITLE = "Adicionais"
EDIT_TAB_TEXT = "Texto"
EDIT_TAB_FILTERS = "Filtros"
EDIT_TEXT_PLACEHOLDER = "Digite o texto aqui…"
EDIT_FONT_FAMILY = "Fonte:"
EDIT_FONT_SIZE = "Tamanho:"
EDIT_FONT_BOLD = "B"
EDIT_FONT_ITALIC = "I"
EDIT_TEXT_COLOR = "Cor do texto:"
EDIT_INSERT_TEXT = "+ Inserir Texto"
EDIT_UPDATE_TEXT = "✓ Salvar Alterações no Texto"
EDIT_INSERT_NEW_TEXT = "+ Inserir como Novo Texto"
EDIT_APPLY_FILTER = "+ Aplicar Filtro"
EDIT_UPDATE_FILTER = "✓ Atualizar Filtro Selecionado"
EDIT_INSERT_NEW_FILTER = "+ Inserir como Novo Filtro"
EDIT_SELECT_FONT = "Fonte"
EDIT_FILTER_BW = "Preto e Branco"
EDIT_FILTER_SEPIA = "Sépia"
EDIT_FILTER_VIGNETTE = "Vinheta"
EDIT_FILTER_INVERT = "Inversão"
EDIT_FILTER_CONTRAST = "Alto Contraste"
EDIT_SPEED = "Velocidade"
EDIT_SPEED_TIP = "Ajustar velocidade de reprodução do bloco (0.1x a 10.0x)"
EDIT_SPEED_NORMAL = "Normal (1,0x)"
EDIT_SPEED_POPUP_TITLE = "Velocidade do Bloco"
EDIT_VOLUME_POPUP_TITLE = "Volume do Bloco"
EDIT_TRACK_MUTE = "Calar a trilha"
EDIT_TRACK_UNMUTE = "Voltar o som da trilha"
EDIT_TRACK_DRAG_TIP = "Arraste para cima ou para baixo para reordenar a trilha"
EDIT_DELETE_TRACK = "Excluir a trilha “{name}”"
EDIT_DELETE_TRACK_TIP = (
    "Some com a trilha e com o que estiver nela. Importar uma mídia cria a "
    "trilha de que ela precisa, então não é preciso guardar trilha vazia."
)
EDIT_DELETE_TRACK_TITLE = "Excluir a trilha?"
EDIT_DELETE_TRACK_BODY = (
    "A trilha “{name}” tem {count} bloco(s). Excluí-la leva todos junto.\n\n"
    "Dá para desfazer com Ctrl+Z."
)
EDIT_TRACK_COUNT = "{tracks} trilhas · {clips} blocos · {duration}"
EDIT_UNDO = "Desfazer"
EDIT_REDO = "Refazer"
EDIT_ZOOM_IN = "Aproximar"
EDIT_ZOOM_OUT = "Afastar"
EDIT_ZOOM_FIT = "Ver tudo"
EDIT_ZOOM_FIT_TIP = (
    "Enquadra a edição inteira. Afastar além disso continua valendo — o vazio "
    "depois do último bloco é onde se solta um bloco para o fim."
)
EDIT_TIMELINE_HINT = (
    "Arraste o bloco para mudá-lo de lugar ou de trilha · as pontas ajustam o "
    "corte · roda do mouse aproxima · Shift+roda desloca · M no cabeçalho cala "
    "a trilha"
)

# trecho selecionado
EDIT_CLIP_NONE = "Nenhum bloco selecionado."
EDIT_CLIP_INFO = "{name} · {duration}"
EDIT_GAIN = "Volume do bloco"
EDIT_GAIN_TIP = (
    "Ganho aplicado só a este bloco, em decibéis. 0 dB não mexe no som; "
    "−6 dB é metade da amplitude; +6 dB é o dobro.\n"
    "Para calar a trilha inteira, use o M no cabeçalho dela."
)
EDIT_CLIP_MUTE = "Bloco mudo"
EDIT_CLIP_UNMUTE = "Voltar o som do bloco"
EDIT_CLIP_DETACHED = "áudio separado em outra trilha"
EDIT_GAIN_DETACHED = (
    "O som deste bloco foi separado para uma trilha própria — é lá que o "
    "volume dele se ajusta agora."
)

# tela do projeto
EDIT_CANVAS = "Tela:"
EDIT_CANVAS_RATE = "Taxa:"
EDIT_CANVAS_AUTO = "Automática · segue o material"
EDIT_CANVAS_RATE_AUTO = "Automática"
EDIT_CANVAS_SIZE = "{width} × {height}"
EDIT_CANVAS_FPS = "{fps} fps"
EDIT_CANVAS_TIP = (
    "O tamanho do vídeo exportado. Todo bloco é encaixado nela inteiro, com "
    "tarja preta onde sobra — nada é esticado nem cortado.\n"
    "Automática usa o maior bloco da edição, para não rebaixar o melhor "
    "material por causa da ordem em que os arquivos entraram."
)
EDIT_CANVAS_RATE_TIP = (
    "Os quadros por segundo do vídeo exportado. Blocos de outra taxa têm "
    "quadros duplicados ou descartados para chegar nela — não há invenção de "
    "movimento, então trocar a taxa de um material não o deixa mais fluido.\n"
    "Automática usa a maior taxa da edição, até 60 fps."
)
EDIT_INTERPOLATE = "Interpolar movimento"
EDIT_INTERPOLATE_TIP = (
    "Inventa os quadros que faltam, em vez de repetir os que existem: é a "
    "única forma de um material de 24 fps sair de fato mais fluido a 60.\n"
    "Custa caro — medido, de 17 a 45 vezes o tempo de exportação, conforme a "
    "máquina possa ou não dividir o trabalho — e o que ela inventa aparece: "
    "movimento rápido, oclusão e corte de cena saem deformados.\n"
    "A prévia continua mostrando os quadros repetidos; interpolar em tempo "
    "real não caberia no ritmo da reprodução."
)
EDIT_INTERPOLATE_OFF = (
    "Só há o que interpolar quando algum bloco está abaixo da taxa da tela."
)
EDIT_INTERPOLATE_WARN = (
    "Interpolar multiplica o tempo da exportação (medido: 17× dividindo o "
    "trabalho entre os núcleos, 45× sem dividir), deforma o que se move "
    "depressa e reserva cerca de {memory} de memória — reduza a tela se for "
    "demais para esta máquina."
)

# exportação
EDIT_MODE_FAST = "Corte rápido (sem recodificar)"
EDIT_MODE_TIP = (
    "Vídeo comprimido só pode ser cortado sem recodificar em um keyframe, que "
    "aparece a cada poucos segundos.\n"
    "O corte exato começa no quadro marcado, mas recodifica o trecho — leva "
    "tempo e custa um pouco de qualidade.\n"
    "O corte rápido copia os dados como estão: sai em segundos e sem perda "
    "nenhuma, mas começa no keyframe anterior ao ponto marcado."
)
EDIT_PLAN = "O que vai acontecer: {plan}"
EDIT_PLAN_FAST = ".{container} · cópia direta (sem recodificar) · {duration}"
EDIT_FAST_UNAVAILABLE = (
    "O corte rápido vale enquanto a edição for um recorte de um arquivo só. "
    "Com mais de um bloco, mídia acrescentada, volume alterado ou trilha "
    "sobreposta, a exportação precisa compor — e compor recodifica."
)
EDIT_DRIFT = (
    "Sem recodificar, o corte vai começar em {time} — {delta} antes do ponto "
    "marcado."
)
EDIT_DRIFT_NONE = (
    "O ponto marcado cai num keyframe: mesmo sem recodificar, o corte sai exato."
)
EDIT_SAME_FOLDER = "Salvar na mesma pasta do arquivo original"
EDIT_EXPORT = "Adicionar à fila"
EDIT_NO_CLIPS = "Não sobrou nenhum trecho para exportar."
EDIT_SUFFIX_ONE = " (corte)"
EDIT_SUFFIX_EDIT = " (edição)"
EDIT_SAVE_PROJECT = "Salvar projeto"
EDIT_OPEN_PROJECT = "Abrir projeto"
EDIT_SAVED = "Projeto salvo em “{name}”."
EDIT_LOADED = "Projeto “{name}” carregado."
EDIT_PROJECT_FILTER = "Projeto Video Manager (*.vmp *.json);;Todos os arquivos (*)"
EDIT_LOADING_FRAME = "Carregando quadro…"
PROJECT_MODIFIED_TITLE = "Alterações não salvas"
PROJECT_MODIFIED_BODY = (
    "Há alterações no projeto de edição que ainda não foram salvas.\n\n"
    "Deseja fechar o aplicativo mesmo assim?"
)
SETTINGS_TITLE = "Configurações"
SETTINGS_TAB_GENERAL = "Geral"
SETTINGS_TAB_NETWORK = "Rede"
SETTINGS_TAB_SUBS = "Legendas e metadados"
SETTINGS_DEST = "Pasta de destino"
SETTINGS_SEPARATE_BY_SITE = "Criar uma subpasta por site"
SETTINGS_CONCURRENT = "Downloads simultâneos"
SETTINGS_FRAGMENTS = "Fragmentos simultâneos por download"
SETTINGS_RATE_LIMIT = "Limite de banda (KB/s, 0 = ilimitado)"
SETTINGS_COOKIES = "Ler cookies do navegador"
SETTINGS_COOKIES_NONE = "Não usar cookies"
SETTINGS_COOKIES_TIP = (
    "Necessário para mídias privadas, com restrição de idade, de assinantes, e "
    "para as resoluções altas do BiliBili — todas exigem sessão conectada.\n"
    "O navegador escolhido precisa estar fechado em alguns sistemas para que o "
    "banco de cookies possa ser lido."
)
SETTINGS_COOKIES_FILE = "Arquivo de cookies (.txt)"
SETTINGS_COOKIES_FILE_BROWSE = "Escolher…"
SETTINGS_COOKIES_FILE_PLACEHOLDER = "Opcional: caminho para cookies.txt"
SETTINGS_COOKIES_FILE_TIP = (
    "Arquivo de cookies exportado no formato Netscape (cookies.txt). "
    "Tem prioridade sobre a leitura do navegador e contorna restrições "
    "de criptografia (ex: Chrome recente no Windows ou navegadores em sandbox)."
)
SETTINGS_EMBED_THUMB = "Embutir a capa no arquivo"
SETTINGS_EMBED_META = "Gravar metadados (título, autor, data)"
SETTINGS_WRITE_SUBS = "Baixar legendas em arquivo separado (.srt)"
SETTINGS_EMBED_SUBS = "Embutir legendas no arquivo"
SETTINGS_AUTO_SUBS = "Incluir legendas geradas automaticamente"
SETTINGS_SUB_LANGS = "Idiomas (separados por vírgula)"
SETTINGS_ENCODER = "Codificação de vídeo"
SETTINGS_ENCODER_TIP = (
    "Quem recodifica vídeo é o processador, por padrão: o x264 comprime melhor "
    "que qualquer placa no mesmo tamanho de arquivo.\n"
    "Usar a placa costuma ser várias vezes mais rápido, em troca de um pouco de "
    "eficiência — vale quando a exportação é longa e o tamanho não é o problema.\n"
    "Se a placa escolhida não abrir na hora de gravar, a tarefa sai em software "
    "sozinha, em vez de falhar."
)
SETTINGS_ENCODER_TESTING = "Verificando o que esta máquina aceita…"
SETTINGS_ENCODER_TEST = "Testar agora"
SETTINGS_ENCODER_TEST_TIP = (
    "Manda a placa codificar um quadro de verdade. É o único jeito de saber: "
    "o ffmpeg lista encoders que não abrem nesta máquina."
)
SETTINGS_THEME = "Tema"
THEME_DARK = "Escuro"
THEME_LIGHT = "Claro"

# --- diálogos e erros --------------------------------------------------------
DIALOG_ERROR_TITLE = "Não foi possível continuar"
DIALOG_WARNING_TITLE = "Atenção"
DIALOG_INFO_TITLE = "Informação"
DIALOG_FFMPEG_TITLE = "ffmpeg necessário"
DIALOG_FFMPEG_BODY = (
    "O ffmpeg é necessário para juntar vídeo com áudio e para converter "
    "arquivos, e não foi encontrado neste computador.\n\n"
    "Baixar agora a versão oficial (cerca de {size})? Ela fica guardada apenas "
    "para este aplicativo e não altera nada no sistema."
)
DIALOG_FFMPEG_DOWNLOAD = "Baixar agora"
DIALOG_FFMPEG_PROGRESS = "Baixando ffmpeg… {done} de {total}"
DIALOG_FFMPEG_FAILED = (
    "Falha ao instalar o ffmpeg:\n\n{error}\n\n"
    "Alternativa: instale o ffmpeg manualmente e reabra o aplicativo — ele é "
    "detectado automaticamente no PATH do sistema."
)
DIALOG_QUIT_TITLE = "Sair mesmo?"
DIALOG_QUIT_BODY = (
    "Há {count} tarefa(s) em andamento. Sair agora cancela tudo e descarta os "
    "arquivos parciais."
)
DIALOG_ENGINE_TITLE = "Atualizar engine"
DIALOG_ENGINE_BODY = (
    "As plataformas mudam com frequência e os extratores do yt-dlp precisam "
    "acompanhar. Atualizar agora?\n\nVersão instalada: {current}"
)
DIALOG_ENGINE_RUNNING = "Atualizando o yt-dlp…"
DIALOG_ENGINE_DONE = (
    "yt-dlp atualizado para {version}.\n\nReinicie o aplicativo para usar a "
    "versão nova."
)
DIALOG_ENGINE_UPTODATE = "O yt-dlp já está na versão mais recente ({version})."
DIALOG_ENGINE_FAILED = "Falha ao atualizar:\n\n{error}"
# Versão empacotada: não há pip por perto e o yt-dlp vem embutido. Ver
# workers/engine_worker.py.
DIALOG_ENGINE_PACKAGED = (
    "Esta é uma versão empacotada: o yt-dlp vem embutido e é atualizado junto "
    "com o aplicativo. Baixe a versão mais recente do Video Manager para "
    "receber os extratores novos."
)
