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

# --- configurações -----------------------------------------------------------
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
