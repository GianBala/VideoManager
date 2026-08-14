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
ACTION_UPDATE_ENGINE = "Atualizar engine (yt-dlp)…"
ACTION_OPEN_DEST = "Abrir pasta de destino"
ACTION_QUIT = "Sair"
ACTION_ABOUT = "Sobre"

# --- barra de URL ------------------------------------------------------------
URL_LABEL = "Endereço"
URL_PLACEHOLDER = "Cole aqui o link do vídeo, da playlist ou do canal"
URL_ANALYZE = "Analisar"
URL_ANALYZING = "Analisando…"
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
CONVERT_RESIZE = "Redimensionar para"
CONVERT_KEEP = "Manter original"
CONVERT_NO_FILES = "Escolha ao menos um arquivo."

# --- editor de vídeo ---------------------------------------------------------
EDIT_IMPORT = "Importar mídia…"
EDIT_IMPORT_TIP = (
    "Traz vídeos, fotos ou áudios para a edição. Também aceita arrastar "
    "arquivos para dentro da aba."
)
EDIT_IMPORT_REJECTED = "Estes arquivos foram ignorados:"
EDIT_POOL_TIP = "Mídias já importadas nesta edição"
EDIT_INSERT = "Inserir no cursor"
EDIT_INSERT_TIP = (
    "Coloca a mídia escolhida na primeira trilha em que ela caiba, a partir do "
    "cursor"
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
EDIT_ADD_VIDEO_TRACK_FULL = "Nova trilha de vídeo"
EDIT_ADD_AUDIO_TRACK_FULL = "Nova trilha de áudio"
EDIT_TRACK_MUTE = "Calar a trilha"
EDIT_TRACK_UNMUTE = "Voltar o som da trilha"
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
