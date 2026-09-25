"""Texto visível da interface, em inglês.

Os mesmos nomes de :mod:`strings`, com os mesmos parâmetros e as mesmas
estruturas, na mesma ordem: a troca de idioma copia estes valores por cima dos
de lá (ver :mod:`videomanager.presentation.qt.i18n`). Um nome que faltasse aqui
ficaria em português sem erro nenhum — é o que ``tests/test_language.py``
confere.

Menus, botões, abas e títulos de janela em Title Case; rótulos, dicas,
mensagens e itens de lista em sentence case. Nada de ``&`` fora dos menus: em
botão, aba e rótulo de formulário o Qt o lê como tecla de atalho e o some da
tela.
"""

from __future__ import annotations

# --- janela ------------------------------------------------------------------
ABOUT_TITLE = "About Video Manager"
ABOUT_BODY = (
    "<b>Video Manager {version}</b><br><br>"
    "Downloads video and audio from hundreds of platforms and converts local files.<br><br>"
    "Uses <b>yt-dlp</b> {ytdlp} for extraction and <b>ffmpeg</b> for processing.<br><br>"
    "Respecting each platform's terms of use and copyright is the user's "
    "responsibility."
)

# --- abas --------------------------------------------------------------------
TAB_DOWNLOAD = "Download"
TAB_CONVERT = "Convert"
TAB_EDIT = "Edit"

# --- menus -------------------------------------------------------------------
MENU_FILE = "&File"
MENU_TOOLS = "&Tools"
MENU_HELP = "&Help"
ACTION_SETTINGS = "Settings…"
ACTION_UPDATE_ENGINE = "Update Download Engine (yt-dlp)…"
ACTION_NEW_PROJECT = "New Project"
ACTION_OPEN_PROJECT = "Open Project…"
ACTION_SAVE_PROJECT = "Save Project"
ACTION_SAVE_PROJECT_AS = "Save Project As…"
ACTION_IMPORT_MEDIA = "Import Media…"
ACTION_EXPORT_VIDEO = "Export Video…"
ACTION_CONVERT_ADD = "Add Files to Convert…"
ACTION_CONVERT_REMOVE = "Remove Selected Files"
ACTION_CONVERT_CLEAR = "Clear Conversion List"
ACTION_OPEN_DOWNLOAD_DEST = "Open Downloads Folder…"
ACTION_OPEN_CONVERT_DEST = "Open Destination Folder…"
ACTION_QUIT = "Quit"
ACTION_ABOUT = "About"
EDIT_NEW_BUTTON = "New"
EDIT_OPEN_BUTTON = "Open…"
EDIT_SAVE_BUTTON = "Save"
EDIT_SAVE_AS_BUTTON = "Save As…"
EDIT_PROJECT_STATUS = "Project: {name}{dirty}"
EDIT_UNTITLED = "Untitled"
CONVERT_CLEAR = "Clear List"

# --- barra de URL ------------------------------------------------------------
URL_LABEL = "URL"
URL_PLACEHOLDER = "Paste the link to a video, playlist or channel here"
URL_ANALYZE = "Analyze"
URL_CANCEL = "Cancel"
URL_CANCEL_TIP = "Cancel the URL analysis in progress"
URL_PASTE_AND_ANALYZE = "Paste and Analyze"

# --- card da mídia -----------------------------------------------------------
CARD_EMPTY = "No media analyzed.\nPaste a URL above and click Analyze."
CARD_LIVE = "LIVE STREAM"
CARD_NO_THUMB = "no\nthumbnail"
CARD_SUBTITLES = "{count} subtitle(s) available"
CARD_DRM = "{count} format(s) blocked by DRM"

# --- modo --------------------------------------------------------------------
MODE_LABEL = "What to download"
MODE_VIDEO = "Video (with audio)"
MODE_AUDIO = "Audio only"

# --- controles de vídeo ------------------------------------------------------
QUALITY_GROUP = "Quality"
LABEL_RESOLUTION = "Resolution"
LABEL_FPS = "Frame rate"
LABEL_CODEC = "Video codec"
LABEL_CONTAINER = "Container"
LABEL_AUDIO_TRACK = "Audio track"
LABEL_ESTIMATED_SIZE = "Estimated size"
ANY_FPS = "Any"
ANY_CODEC = "Any"
QUALITY_BEST_AVAILABLE = "Best available"
CONTAINER_AUTO_LABEL = "Automatic (best without re-encoding)"

TIP_CONTAINER = (
    "MKV accepts any combination of codecs, so it never forces a re-encode.\n"
    "MP4 is the most compatible with devices and TVs.\n"
    "In automatic mode, yt-dlp itself picks a compatible container."
)
TIP_RESOLUTION = (
    "Only the resolutions this media actually offers are listed.\n"
    "When the platform doesn't report the resolution, the option is shown by bitrate."
)
QUALITY_WARN_EXTRACTED = (
    "This media doesn't keep its tracks separate: the whole video has to be "
    "downloaded and the audio extracted from it."
)
QUALITY_WARN_NO_FAMILY = "This media has no {family}: {actual} will be downloaded."
QUALITY_WARN_NO_FAMILY_AT = (
    "This media has no {family} at {resolution}: {actual} will be downloaded. "
    "With {family}, the highest available resolution is {reach}p."
)
QUALITY_WARN_FAMILY_LIMIT = (
    "{family} in this media goes up to {reach}p. There is {top}p, but only in other codecs."
)
TIP_CODEC = (
    "Only the codecs available at the chosen resolution are listed. Above 1080p "
    "there is often no H.264: YouTube serves 1440p and 2160p only in VP9 and AV1.\n"
    "Your choice is remembered — if it isn't available at the current resolution, "
    "it comes back on its own as soon as you pick a resolution that has it."
)

# --- controles de áudio ------------------------------------------------------
LABEL_AUDIO_FORMAT = "Format"
LABEL_AUDIO_QUALITY = "Bitrate"
AUDIO_CODEC_BEST = "Original (lossless, fastest)"
AUDIO_SOURCE_INFO = "Best source track: {bitrate}"

TIP_AUDIO_FORMAT = (
    "“Original” just extracts the audio from the file, without re-encoding: it's "
    "instant and loses nothing.\nThe other formats re-encode, which always costs "
    "some quality."
)

# --- destino -----------------------------------------------------------------
DEST_LABEL = "Destination"
DEST_BROWSE = "Browse…"
DEST_TOOLTIP = "Folder where finished files are saved"

# --- perfis ------------------------------------------------------------------
PROFILES_GROUP = "Quick profiles"
PROFILE_HINT = "One click sets everything up and adds it to the queue."
PROFILE_MP4_1080 = "MP4 1080p"
PROFILE_MP4_1080_SUB = "plays everywhere"
PROFILE_MP3_320 = "MP3 320k"
PROFILE_MP3_320_SUB = "audio only"
PROFILE_MAX = "Maximum quality"
PROFILE_MAX_SUB = "MKV, no re-encode"
PROFILE_AUDIO_ORIGINAL = "Original audio"
PROFILE_AUDIO_ORIGINAL_SUB = "lossless"

# --- ação --------------------------------------------------------------------
ADD_TO_QUEUE = "Add to Queue"
ADD_TO_QUEUE_TIP = "Analyze a URL before adding it to the queue"

# --- fila --------------------------------------------------------------------
QUEUE_GROUP = "Queue"
QUEUE_COLUMNS = ("Title", "Output", "Status", "Progress", "Speed")
QUEUE_EMPTY = "The queue is empty."
QUEUE_CANCEL = "Cancel"
QUEUE_RETRY = "Retry"
QUEUE_OPEN_FOLDER = "Open Containing Folder"
QUEUE_OPEN_FILE = "Open File"
QUEUE_COPY_ERROR = "Copy Error Message"
QUEUE_SHOW_LOG = "Show Technical Details"
QUEUE_CLEAR_FINISHED = "Clear Finished"
QUEUE_CANCEL_ALL = "Cancel All"
QUEUE_LOG_TITLE = "Technical Details — {title}"
QUEUE_LOG_CLOSE = "Close"

# --- status bar --------------------------------------------------------------
STATUS_COUNTS = "{active} in progress · {pending} queued · {done} completed"
STATUS_FFMPEG = "ffmpeg: {source}"
FFMPEG_SOURCES = {"empacotado": "bundled", "gerenciado": "managed", "sistema": "system"}
STATUS_ENQUEUED = "{count} task(s) added to the queue — follow them in the Download tab"
STATUS_SETTINGS_FAILED = "Could not save the preferences: {error}"

# --- playlist ----------------------------------------------------------------
PLAYLIST_TITLE = "Select Playlist Items"
PLAYLIST_HEADER = "“{title}” has {count} items. Check the ones you want to download."
PLAYLIST_SELECT_ALL = "Select All"
PLAYLIST_SELECT_NONE = "Deselect All"
PLAYLIST_ADD = "Add {count} to Queue"
PLAYLIST_MODE_LABEL = "Download as"
PLAYLIST_MODE_VIDEO = "Video"
PLAYLIST_MODE_AUDIO = "Audio only"
PLAYLIST_LIMIT_UP_TO = "up to {height}p"
PLAYLIST_NOTE = (
    "Items use the current quality settings. Each video may offer different "
    "formats, so the choice is made by a resolution limit rather than a fixed "
    "format."
)

# --- conversor local ---------------------------------------------------------
CONVERT_FILES_GROUP = "Files to convert"
CONVERT_PICK = "Choose Files…"
CONVERT_INSPECTING = "Inspecting {count} file(s)…"
CONVERT_REJECTED = "These files were skipped:"
CONVERT_REMOVE = "Remove Selected"
CONVERT_DROP_HINT = "Drag files here, or click “Choose Files…”"
CONVERT_TO_AUDIO = "Convert to audio"
CONVERT_TO_VIDEO = "Convert video"
CONVERT_START = "Convert"
CONVERT_SAME_FOLDER = "Save in the same folder as the original file"
CONVERT_TARGET_GROUP = "Convert to"
CONVERT_PLAN = "What will happen: {plan}"
CONVERT_ESTIMATED_SIZE = "Estimated size: {size}"
CONVERT_RESIZE = "Resize to"
CONVERT_KEEP = "Keep original"
CONVERT_NO_FILES = "Choose at least one file."
CONVERT_COPY_CODEC = "Copy (no re-encode)"
CONVERT_PICK_TIP = "{label} (Ctrl+O)"
CONVERT_REMOVE_TIP = "{label} (Del)"
CONVERT_FILE_FILTER = (
    "Media (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts "
    "*.mp3 *.m4a *.aac *.opus *.ogg *.flac *.wav *.wma);;All files (*)"
)
CONVERT_PLAN_MIXED = "{plan} (and other formats that differ among the {count} files)"
CONVERT_FALLBACK = (
    "The source folder is not writable. The files will be saved in the downloads "
    "folder:\n{folder}"
)
CONVERT_SKIPPED = "Skipped:"

# --- editor de vídeo ---------------------------------------------------------
EDIT_IMPORT = "Import Media…"
EDIT_IMPORT_TIP = (
    "Brings videos, audio and images into the library. Then drag the media to "
    "the track and time you want on the timeline."
)
EDIT_IMPORT_REJECTED = "These files were skipped:"
EDIT_POOL_TIP = "Media already imported into this edit · drag one onto the timeline"
EDIT_MEDIA_POOL_TITLE = "Project media"
EDIT_MEDIA_EMPTY = "Drag media here\nor click “+ Import”"
EDIT_MEDIA_REMOVE = "Delete  (Del)"
EDIT_CLEAR_UNUSED = "Remove Unused"
EDIT_CLEAR_UNUSED_TIP = "Removes from the library the media that isn't on any track"
EDIT_MEDIA_IN_USE_TITLE = "Media in Use"
EDIT_MEDIA_IN_USE_MSG = (
    "The media “{name}” is used by {count} clip(s) on the timeline and can't be removed. "
    "Remove its clips from the tracks first."
)
EDIT_MEDIA_COUNT = "{count} item(s)"
EDIT_IMPORT_BUTTON = "+ Import"
EDIT_CLEAR_UNUSED_BUTTON = "🧹 Remove Unused"
EDIT_MEDIA_KINDS = {"VIDEO": "Video", "IMAGE": "Image", "AUDIO": "Audio"}
EDIT_CHANNELS_STEREO = "stereo"
EDIT_CHANNELS_MONO = "mono"
EDIT_CHANNELS = "{count} channels"
EDIT_EXPORT_BUTTON = "Export"
EDIT_EXPORT_BUTTON_TIP = "Set up the video export and add it to the queue (Ctrl+E)"
EXPORT_DIALOG_TITLE = "Export Video"
EXPORT_SUMMARY_GROUP = "Project summary"
EXPORT_SETTINGS_GROUP = "Output settings"
EXPORT_DESTINATION_GROUP = "Destination"
EXPORT_DESTINATION_FOLDER = "Destination folder:"
EXPORT_DESTINATION_PICK = "Browse…"
EXPORT_DESTINATION_PICK_TITLE = "Choose Destination Folder"
EXPORT_ACTION_ENQUEUE = "Add to Queue"
EXPORT_ACTION_CANCEL = "Cancel"
EXPORT_MODE_AUDIO_ONLY = "Export audio only"
EXPORT_MODE_AUDIO_ONLY_TIP = (
    "Drops the picture and exports only the sound mix of all tracks"
)
EXPORT_CONTAINER = "Video format"
EXPORT_CONTAINER_TIP = "File format of the generated video (container)"
EXPORT_GIF_NO_FAST = "GIF is always re-encoded: there is no way to copy the data as is."
EXPORT_GIF_NOTE = (
    "GIF holds no sound: the audio track is left out. In \"Automatic\", the "
    "canvas goes up to 640 px and the frame rate up to 15 frames per second — "
    "every frame is a whole image, and at the project's canvas the file would be "
    "ten times larger. Choosing the canvas or frame rate by hand still applies."
)
EXPORT_VIDEO_CODEC = "Video codec"
EXPORT_VIDEO_CODEC_TIP = "Video compression algorithm (H.264, HEVC, AV1, VP9)"
EXPORT_QUALITY = "Video quality"
EXPORT_QUALITY_TIP = (
    "Controls picture fidelity and the final file size.\n"
    "Balanced (CRF 23): excellent visual quality, indistinguishable to the naked eye, in a light file (recommended).\n"
    "High (CRF 18): maximum quality for archiving, with significantly larger files.\n"
    "Economy (CRF 28): aggressive compression in a very compact file, ideal for quick sharing."
)
EXPORT_QUALITY_BALANCED = "Balanced (CRF 23 - recommended)"
EXPORT_QUALITY_HIGH = "High quality (CRF 18 - larger file)"
EXPORT_QUALITY_ECONOMY = "Economy (CRF 28 - smaller file)"
EXPORT_AUDIO_FORMAT = "Audio format"
EXPORT_AUDIO_FORMAT_TIP = "Format and codec of the generated sound file"
EXPORT_ESTIMATED_SIZE = "Estimated size"
EXPORT_SUMMARY = "Total duration: <b>{duration}</b> · {tracks} track(s) · {clips} clip(s)"
EXPORT_FILENAME = "File name:"
EXPORT_FILENAME_PLACEHOLDER = "File name (without extension)"
EXPORT_DEFAULT_SUFFIX = "_edited"
EXPORT_DEFAULT_STEM = "edited_video"
EXPORT_CONTAINERS = {
    "mp4": "MP4 (.mp4)",
    "mkv": "MKV (.mkv)",
    "webm": "WebM (.webm)",
    "mov": "QuickTime (.mov)",
    "gif": "Animated GIF (.gif)",
}
EXPORT_VIDEO_CODECS = {
    "h264": "H.264 / AVC (universal standard)",
    "hevc": "HEVC / H.265 (high efficiency)",
    "av1": "AV1 (high compression)",
    "vp9": "VP9 (web)",
}
EXPORT_AUDIO_FORMATS = {
    "mp3": "MP3 (.mp3 - 192 kbps)",
    "m4a": "AAC / M4A (.m4a - 192 kbps)",
    "flac": "FLAC (.flac - lossless)",
    "wav": "WAV (.wav - lossless PCM)",
    "opus": "Opus (.opus - 128 kbps)",
    "ogg": "OGG Vorbis (.ogg)",
}
EXPORT_ASPECTS = {
    "16:9": "16:9 (Widescreen)",
    "4:3": "4:3 (Standard)",
    "9:16": "9:16 (Vertical / Shorts / Reels)",
    "1:1": "1:1 (Square)",
    "21:9": "21:9 (Ultrawide)",
}
EDIT_INSERT = "Insert at Playhead"
EDIT_INSERT_TIP = (
    "Places the chosen media on the timeline, starting where the playhead is. "
    "If no compatible track has free space, a new track is created."
)
EDIT_EMPTY = (
    "Import videos, photos or audio and drag them from the library\n"
    "onto the timeline to build the edit."
)
EDIT_COLLAPSE = "Collapse Preview"
EDIT_EXPAND = "Expand Preview"
EDIT_COLLAPSE_TIP = "Shrinks the picture so the timeline gets the window"
EDIT_FILE_FILTER = (
    "Media (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts *.mpg *.mpeg "
    "*.mp3 *.m4a *.aac *.opus *.ogg *.flac *.wav "
    "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;"
    "Video (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts);;"
    "Audio (*.mp3 *.m4a *.aac *.opus *.ogg *.flac *.wav);;"
    "Image (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All files (*)"
)
EDIT_NO_PLAYBACK = "This file has no picture or sound to play"

# transporte
EDIT_PLAY = "Play"
EDIT_PAUSE = "Pause"
EDIT_TO_START = "Go to start"
EDIT_TO_END = "Go to end"
EDIT_PREV_FRAME = "Previous frame"
EDIT_NEXT_FRAME = "Next frame"
EDIT_BACK = "Back 1 s"
EDIT_FORWARD = "Forward 1 s"
EDIT_PREV_KEY = (
    "Previous keyframe — the nearest fast-cut point before the playhead"
)
EDIT_NEXT_KEY = "Next keyframe — the fast-cut point just ahead"
EDIT_PREV_KEY_SHORT = "◁ keyframe"
EDIT_NEXT_KEY_SHORT = "keyframe ▷"
EDIT_POSITION = "{current}  /  {total}"
EDIT_KEY_SPACE = "Space"
EDIT_SHORTCUT = "{label}  ({key})"
EDIT_FRAME_NUMBER = "frame {index}"
EDIT_FULLSCREEN = "Full Screen"
EDIT_FULLSCREEN_TIP = "View the preview in full screen (F) — the bar hides on its own"
EDIT_FULLSCREEN_TITLE = "Full-Screen Preview"
EDIT_EXIT_FULLSCREEN = "Exit"
EDIT_EXIT_FULLSCREEN_TIP = "Exit full screen (Esc)"
EDIT_VOLUME = "Preview volume"
EDIT_LOOP = "Loop"
EDIT_LOOP_TIP = "Keep playing in a loop when the end is reached"
EDIT_SNAP = "🧲"
EDIT_SNAP_TIP = "Magnetic snapping to edges and rotation (auto-attach)"
EDIT_PROPERTIES = "Properties"
EDIT_PROPERTIES_TIP = "Open the Properties tab to edit the item with precise numbers"
EDIT_TAB_PROPERTIES = "Properties"
EDIT_MUTE = "Mute"
EDIT_UNMUTE = "Unmute"
EDIT_SOUND = "♪"
EDIT_MUTED = "✕"

# barra da linha do tempo
EDIT_SPLIT = "Split"
EDIT_DELETE = "Delete Clip"
EDIT_TRIM_LEFT = "Delete Left"
EDIT_TRIM_LEFT_TIP = (
    "Deletes the part of the clip before the playhead. The same as dragging the "
    "left edge here, without having to aim at the frame."
)
EDIT_TRIM_RIGHT = "Delete Right"
EDIT_TRIM_RIGHT_TIP = (
    "Deletes the part of the clip after the playhead. The same as dragging the "
    "right edge here, without having to aim at the frame."
)
EDIT_DETACH = "Detach Audio"
EDIT_DETACH_TIP = (
    "Takes the sound out of the video clip and puts it on its own audio track, "
    "at the same position — the video goes silent and the sound moves on its own"
)
EDIT_COPY = "Copy"
EDIT_PASTE = "Paste"
EDIT_ADD_VIDEO_TRACK = "+ Video"
EDIT_ADD_AUDIO_TRACK = "+ Audio"
EDIT_ADD_ADDITIONAL_TRACK = "+ Overlays"
EDIT_ADD_VIDEO_TRACK_FULL = "New Video Track"
EDIT_ADD_AUDIO_TRACK_FULL = "New Audio Track"
EDIT_ADD_ADDITIONAL_TRACK_FULL = "New Overlay Track"
EDIT_EXTRAS_TITLE = "Overlays"
EDIT_TAB_TEXT = "Text"
EDIT_TAB_FILTERS = "Filters"
EDIT_TAB_TRANSITIONS = "Transitions"
EDIT_TRANSITION_NEEDS_CUT = (
    "Place two video clips back to back on the same track to insert a transition."
)
EDIT_TRANSITION_TRACK_HINT = (
    "Select one of the clips at the cut to pick the exact track; with no "
    "selection, the cut nearest the playhead is used."
)
EDIT_TEXT_PLACEHOLDER = "Type your text here…"
EDIT_TEXT_DEFAULT = "Title"
EDIT_FONT_SMALLER = "Decrease font size (1 pt)"
EDIT_FONT_LARGER = "Increase font size (1 pt)"
EDIT_FONT_SIZE_PRESET = "Set size to {size} pt"
EDIT_TEXT_COLOR_TIP = "Choose a custom color"
EDIT_TEXT_COLOR_TITLE = "Text Color"
EDIT_STROKE = "Outline:"
EDIT_STROKE_TIP = "Turn the text outline on or off"
EDIT_STROKE_WIDTH_TIP = "Outline thickness in pixels"
EDIT_STROKE_COLOR_TIP = "Choose the outline color"
EDIT_STROKE_COLOR_TITLE = "Outline Color"
EDIT_FONT_SIZE = "Size:"
EDIT_FONT_BOLD = "B"
EDIT_FONT_ITALIC = "I"
EDIT_INSERT_TEXT = "+ Insert Text"
EDIT_UPDATE_TEXT = "✓ Save Text Changes"
EDIT_INSERT_NEW_TEXT = "+ Insert as New Text"
EDIT_APPLY_FILTER = "+ Apply Filter"
EDIT_UPDATE_FILTER = "✓ Update Selected Filter"
EDIT_INSERT_NEW_FILTER = "+ Insert as New Filter"
EDIT_FILTER_BW = "Black and White"
EDIT_FILTER_SEPIA = "Sepia"
EDIT_FILTER_VIGNETTE = "Vignette"
EDIT_FILTER_INVERT = "Invert"
EDIT_FILTER_CONTRAST = "High Contrast"
EDIT_FILTERS = {
    "pb": ("🎬", EDIT_FILTER_BW),
    "sepia": ("☕", EDIT_FILTER_SEPIA),
    "contraste": ("⚡", EDIT_FILTER_CONTRAST),
    "vinheta": ("🎯", EDIT_FILTER_VIGNETTE),
    "inverter": ("🔄", EDIT_FILTER_INVERT),
}
EDIT_TRANSITIONS = {
    "fade": ("🌑", "Fade"),
    "fadeblack": ("⬛", "Fade to Black"),
    "fadewhite": ("⬜", "Fade to White"),
    "dissolve": ("🎬", "Dissolve"),
    "wipeleft": ("◀", "Wipe Left"),
    "wiperight": ("▶", "Wipe Right"),
    "slideleft": ("◀", "Slide Left"),
    "slideright": ("▶", "Slide Right"),
}
EDIT_CHOOSE_FILTER = "Choose a visual effect:"
EDIT_CHOOSE_TRANSITION = "Choose a video transition:"
EDIT_EXTRA_DURATION = "Duration:"
EDIT_INSERT_TRANSITION = "+ Insert Transition"
EDIT_UPDATE_TRANSITION = "✓ Update Selected Transition"
EDIT_INSERT_NEW_TRANSITION = "+ Insert as New Transition"
EDIT_CLIP_TEXT = "Text"
EDIT_CLIP_FILTER = "Filter"
EDIT_CLIP_TRANSITION = "Transition"
EDIT_TRANSITION_TITLE = "Transition: {name}"
EDIT_SPEED_TIP = "Adjust the clip's playback speed (0.1x to 10x)"
EDIT_SPEED_POPUP_TITLE = "Clip speed"
EDIT_VOLUME_POPUP_TITLE = "Clip volume"
EDIT_TRACK_MUTE = "Mute Track"
EDIT_TRACK_UNMUTE = "Unmute Track"
EDIT_TRACK_HIDE = "Hide Track"
EDIT_TRACK_SHOW = "Show Track"
EDIT_TRACK_DRAG_TIP = "Drag up or down to reorder the track"
EDIT_DELETE_TRACK = "Delete Track “{name}”"
EDIT_DELETE_TRACK_TIP = (
    "Removes the track and everything on it. Importing media creates the track "
    "it needs, so there is no need to keep empty tracks around."
)
EDIT_DELETE_TRACK_TITLE = "Delete Track?"
EDIT_DELETE_TRACK_BODY = (
    "The track “{name}” has {count} clip(s). Deleting it removes them all.\n\n"
    "You can undo this with Ctrl+Z."
)
EDIT_TRACK_COUNT = "{tracks} tracks · {clips} clips · {duration}"
EDIT_UNDO = "Undo"
EDIT_REDO = "Redo"
EDIT_ZOOM_IN = "Zoom In"
EDIT_ZOOM_OUT = "Zoom Out"
EDIT_ZOOM_FIT = "Fit All"
EDIT_ZOOM_FIT_TIP = (
    "Frames the whole edit. Zooming out further still works — the empty space "
    "after the last clip is where you drop a clip to put it at the end."
)
EDIT_TIMELINE_HINT = (
    "Drag a clip to move it in time or to another track · the edges adjust the "
    "cut · wheel scrolls vertically · Shift+wheel scrolls horizontally · Ctrl+wheel zooms · M on the header mutes "
    "the track"
)

# trecho selecionado
EDIT_CLIP_NONE = "No clip selected."
EDIT_CLIP_INFO = "{name} · {duration}"
EDIT_GAIN_TIP = (
    "Gain applied only to this clip, in decibels. 0 dB leaves the sound as is; "
    "−6 dB is half the amplitude; +6 dB is double.\n"
    "To mute the whole track, use the M on its header."
)
EDIT_CLIP_MUTE = "Mute Clip"
EDIT_CLIP_UNMUTE = "Unmute Clip"
EDIT_CLIP_DETACHED = "audio detached to another track"
EDIT_GAIN_DETACHED = (
    "This clip's sound was detached to a track of its own — that is where its "
    "volume is adjusted now."
)

# tela do projeto
EDIT_CANVAS = "Canvas:"
EDIT_CANVAS_ASPECT = "Aspect ratio:"
EDIT_CANVAS_ASPECT_AUTO = "Automatic"
EDIT_CANVAS_ASPECT_TIP = (
    "Locks the aspect ratio of the editing canvas and the preview (e.g. 16:9, 4:3, 9:16, 1:1, 21:9).\n"
    "Clips are fitted proportionally, without distortion."
)
EXPORT_ASPECT = "Aspect ratio:"
EXPORT_ASPECT_AUTO = "Same as project"
EXPORT_ASPECT_TIP = (
    "Aspect ratio of the final exported video (16:9 widescreen, 4:3 standard, 9:16 vertical, etc.)."
)
EDIT_CANVAS_RATE = "Frame rate:"
EDIT_CANVAS_AUTO = "Automatic · follows the media"
EDIT_CANVAS_RATE_AUTO = "Automatic"
EDIT_CANVAS_SIZE = "{width} × {height}"
EDIT_CANVAS_FPS = "{fps} fps"
EDIT_CANVAS_TIP = (
    "The size of the exported video. Every clip is fitted into it whole, with "
    "black bars where there is room left — nothing is stretched or cropped.\n"
    "Automatic uses the largest clip in the edit, so the best footage isn't "
    "downgraded because of the order in which the files came in."
)
EDIT_CANVAS_RATE_TIP = (
    "The frames per second of the exported video. Clips at another frame rate "
    "have frames duplicated or dropped to match it — no motion is invented, so "
    "changing a clip's frame rate doesn't make it any smoother.\n"
    "Automatic uses the highest frame rate in the edit, up to 60 fps."
)
EDIT_INTERPOLATE = "Motion interpolation"
EDIT_INTERPOLATE_TIP = (
    "Invents the missing frames instead of repeating the existing ones: it's the "
    "only way for 24 fps footage to actually come out smoother at 60.\n"
    "It's expensive — measured at 17 to 45 times the export time, depending on "
    "whether the machine can split the work — and what it invents shows: fast "
    "motion, occlusion and scene cuts come out warped.\n"
    "The preview keeps showing the repeated frames; interpolating in real time "
    "wouldn't keep up with playback."
)
EDIT_INTERPOLATE_OFF = (
    "There is only something to interpolate when a clip is below the canvas frame rate."
)
EDIT_INTERPOLATE_WARN = (
    "Interpolating multiplies the export time (measured: 17× splitting the work "
    "across cores, 45× without splitting), warps fast motion and reserves about "
    "{memory} of memory — lower the canvas if that's too much for this machine."
)

# exportação
EDIT_MODE_FAST = "Fast cut (no re-encode)"
EDIT_MODE_TIP = (
    "Compressed video can only be cut without re-encoding at a keyframe, which "
    "comes every few seconds.\n"
    "An exact cut starts at the marked frame, but re-encodes the segment — it takes "
    "time and costs a little quality.\n"
    "A fast cut copies the data as is: it's done in seconds with no loss at "
    "all, but starts at the keyframe before the marked point."
)
EDIT_PLAN = "What will happen: {plan}"
EDIT_PLAN_FAST = ".{container} · direct copy (no re-encode) · {duration}"
EDIT_FAST_UNAVAILABLE = (
    "Fast cut works while the edit is a trim of a single file, at its own canvas "
    "and frame rate. With more than one clip, added media, changed volume, an "
    "overlapping track or another canvas chosen, the export has to composite — "
    "and compositing re-encodes."
)
EDIT_DRIFT = (
    "Without re-encoding, the cut will start at {time} — {delta} before the marked "
    "point."
)
EDIT_DRIFT_NONE = (
    "The marked point falls on a keyframe: even without re-encoding, the cut is exact."
)
EDIT_SAME_FOLDER = "Save in the same folder as the original file"
EDIT_NO_CLIPS = "There is nothing left to export."
EDIT_SUFFIX_ONE = " (cut)"
EDIT_SUFFIX_EDIT = " (edit)"
EDIT_SAVE_PROJECT = "Save Project"
EDIT_OPEN_PROJECT = "Open Project"
EDIT_PROJECT_FILTER = "Video Manager project (*.vmp *.json);;All files (*)"
EDIT_DEFAULT_PROJECT_NAME = "project.vmp"
EDIT_LOADING_FRAME = "Loading frame…"
PROJECT_MODIFIED_TITLE = "Unsaved Changes"
PROJECT_MODIFIED_BODY = (
    "The editing project has changes that haven't been saved yet.\n\n"
    "Close the application anyway?"
)
SETTINGS_TITLE = "Settings"
SETTINGS_TAB_GENERAL = "General"
SETTINGS_TAB_NETWORK = "Network"
SETTINGS_TAB_SUBS = "Subtitles and Metadata"
SETTINGS_DEST = "Destination folder"
SETTINGS_SEPARATE_BY_SITE = "Create a subfolder per site"
SETTINGS_CONCURRENT = "Simultaneous downloads"
SETTINGS_FRAGMENTS = "Simultaneous fragments per download"
SETTINGS_RATE_LIMIT = "Bandwidth limit (KB/s, 0 = unlimited)"
SETTINGS_COOKIES = "Read cookies from browser"
SETTINGS_COOKIES_NONE = "Don't use cookies"
SETTINGS_COOKIES_TIP = (
    "Required for private, age-restricted and subscriber-only media, and for "
    "BiliBili's high resolutions — they all need a signed-in session.\n"
    "On some systems the chosen browser has to be closed for its cookie "
    "database to be read."
)
SETTINGS_COOKIES_FILE = "Cookies file (.txt)"
SETTINGS_COOKIES_FILE_BROWSE = "Browse…"
SETTINGS_COOKIES_FILE_PLACEHOLDER = "Optional: path to cookies.txt"
SETTINGS_COOKIES_FILTER = "Cookies (*.txt);;All files (*)"
SETTINGS_COOKIES_FILE_TIP = (
    "Cookies file exported in Netscape format (cookies.txt). "
    "Takes priority over reading from the browser and works around encryption "
    "restrictions (e.g. recent Chrome on Windows or sandboxed browsers)."
)
SETTINGS_EMBED_THUMB = "Embed thumbnail in the file"
SETTINGS_EMBED_META = "Write metadata (title, author, date)"
SETTINGS_WRITE_SUBS = "Download subtitles as a separate file (.srt)"
SETTINGS_EMBED_SUBS = "Embed subtitles in the file"
SETTINGS_AUTO_SUBS = "Include auto-generated subtitles"
SETTINGS_SUB_LANGS = "Languages (comma-separated)"
SETTINGS_ENCODER = "Video encoding"
SETTINGS_ENCODER_TIP = (
    "By default, video is re-encoded by the processor: x264 compresses better "
    "than any GPU at the same file size.\n"
    "Using the GPU is usually several times faster, at the cost of a little "
    "efficiency — worth it when the export is long and size is not the issue.\n"
    "If the chosen GPU fails to open when it's time to write, the task falls "
    "back to software on its own instead of failing."
)
SETTINGS_ENCODER_TESTING = "Checking what this machine supports…"
SETTINGS_ENCODER_TEST = "Test Now"
SETTINGS_ENCODER_TEST_TIP = (
    "Has the GPU encode a real frame. It's the only way to know: ffmpeg lists "
    "encoders that don't open on this machine."
)
SETTINGS_THEME = "Theme"
THEME_DARK = "Dark"
THEME_LIGHT = "Light"

# --- diálogos e erros --------------------------------------------------------
DIALOG_ERROR_TITLE = "Unable to Continue"
DIALOG_WARNING_TITLE = "Warning"
DIALOG_INFO_TITLE = "Information"
DIALOG_FFMPEG_TITLE = "ffmpeg Required"
DIALOG_FFMPEG_UNAVAILABLE = "FFmpeg is not available."
DIALOG_FFMPEG_BODY = (
    "ffmpeg is needed to merge video with audio and to convert files, and it "
    "wasn't found on this computer.\n\n"
    "Download the official build now (about {size})? It is kept only for this "
    "application and doesn't change anything on the system."
)
DIALOG_FFMPEG_DOWNLOAD = "Download Now"
DIALOG_FFMPEG_PROGRESS = "Downloading ffmpeg… {done} of {total}"
DIALOG_FFMPEG_FAILED = (
    "Failed to install ffmpeg:\n\n{error}\n\n"
    "Alternative: install ffmpeg manually and reopen the application — it is "
    "detected automatically on the system PATH."
)
DIALOG_QUIT_TITLE = "Quit Anyway?"
DIALOG_QUIT_BODY = (
    "There are {count} task(s) in progress. Quitting now cancels everything and "
    "discards the partial files."
)
DIALOG_ENGINE_TITLE = "Update Engine"
DIALOG_ENGINE_BODY = (
    "Platforms change often and the yt-dlp extractors need to keep up. "
    "Update now?\n\nInstalled version: {current}"
)
DIALOG_ENGINE_RUNNING = "Updating yt-dlp…"
DIALOG_ENGINE_DONE = (
    "yt-dlp updated to {version}.\n\nRestart the application to use the new "
    "version."
)
DIALOG_ENGINE_UPTODATE = "yt-dlp is already at the latest version ({version})."
DIALOG_ENGINE_FAILED = "Update failed:\n\n{error}"
DIALOG_ENGINE_PACKAGED = (
    "This is a packaged build: yt-dlp comes bundled and is updated together with "
    "the application. Download the latest version of Video Manager to get the "
    "new extractors."
)

# Leitura assíncrona da edição
EDIT_READING_MEDIA = "Reading the project and inspecting media…"
EDIT_LOAD_CHANGED = "The edit changed while loading. Open the project again to replace the current edit."
EDIT_MISSING_MEDIA = "The project was opened, but the following files were not found:\n\n{files}"
EDIT_READ_CANCEL = "Cancel"

EDIT_SAVING_PROJECT = "Saving project v3… Older projects get a .v1.bak or .v2.bak copy before the upgrade."

EDIT_TRANSITION_AFFECT_ADDITIONALS = "Affect overlay items"
EDIT_TRANSITION_AFFECT_ADDITIONALS_TIP = (
    "Includes filters, images and texts active on both sides of the transition. "
    "Unchecked, these items stay on top of the effect."
)

# Quadros-chave (Keyframes) e Animações
EDIT_KEYFRAME_TITLE = "Animation / Keyframes"
EDIT_KEYFRAME_PREV = "Previous keyframe"
EDIT_KEYFRAME_NEXT = "Next keyframe"
EDIT_KEYFRAME_ADD = "Add a keyframe at the current time"
EDIT_KEYFRAME_REMOVE = "Remove the keyframe at this time"
EDIT_KEYFRAME_TOGGLE = "Toggle a keyframe at the playhead"
EDIT_KEYFRAME_EASING = "Easing:"
EDIT_OPACITY = "Opacity:"
EDIT_ANIMATION_PRESETS = {
    "": "— Select a preset —",
    "slide_up": "Slide Up (from the bottom)",
    "slide_down": "Slide Down (from the top)",
    "slide_left": "Slide Left (from the right)",
    "slide_right": "Slide Right (from the left)",
    "fade_in": "Fade In",
    "zoom_in": "Pop In (zoom)",
    "spin_in": "Spin In",
    "clear": "Remove Animations",
}
EDIT_EASINGS = {
    "linear": "Linear (constant)",
    "ease_in": "Ease In",
    "ease_out": "Ease Out",
    "ease_in_out": "Ease In-Out",
    "hold": "Hold (step)",
}

# aba Propriedades
PROP_TITLE = "Properties"
PROP_TITLE_CLIP = "Properties: {name}"
PROP_CLOSE_TIP = "Close the Properties tab"
PROP_CLIP_ID = "ID #{id} · {kind}"
PROP_KINDS = {"none": "Media", "image": "Image", "text": "Text", "filter": "Filter", "transition": "Transition"}
PROP_TRANSFORM = "Transform"
PROP_POS_X = "Position X:"
PROP_POS_Y = "Position Y:"
PROP_WIDTH = "Width:"
PROP_HEIGHT = "Height:"
PROP_LOCK_RATIO = "Lock aspect ratio"
PROP_SCALE = "Scale:"
PROP_ROTATION = "Rotation:"
PROP_KEYFRAMES_NONE = "No keyframes"
PROP_KEYFRAMES_COUNT = "{count} keyframe(s)"
PROP_QUICK_EFFECT = "Quick effect:"
PROP_CHROMA = "Green screen (chroma key)"
PROP_CHROMA_ENABLE = "Enable green screen removal"
PROP_CHROMA_COLOR = "Color to remove:"
PROP_CHROMA_COLOR_TIP = "Click to choose the color to remove"
PROP_CHROMA_PICK_TITLE = "Choose Color to Remove"
PROP_CHROMA_PRESETS = {"#00FF00": "Standard green", "#00B140": "Studio green", "#0000FF": "Blue"}
PROP_CHROMA_PRESET_TIP = "{name} ({color})"
PROP_CHROMA_TOLERANCE = "Tolerance:"
PROP_CHROMA_SMOOTHING = "Smoothing:"
PROP_TRANSITION = "Video transition"
PROP_TRANSITION_EFFECT = "Effect:"
EDIT_FONT_SEARCH = "🔍 Search fonts…"

JOB_STATUS_LABELS = {
    "pending": "Queued", "running": "Downloading", "processing": "Processing",
    "done": "Completed", "failed": "Failed", "cancelled": "Cancelled",
}
EXPORT_SOURCE_CODEC = "source codec"
EXPORT_COPY_CODEC = "Copy without re-encoding ({codec})"
EDIT_SPEED_COLLISION = "There is no room before the next clip for this speed. Move the next clip or choose another speed."
EDIT_PROJECT_V2_TIP = "v3 format: images on the video track, fitted to the canvas, and trimmed animations preserved. Older versions of the application can't open v3. When a v1 or v2 project is upgraded, the original is kept as .vmp.v1.bak or .vmp.v2.bak (or a numbered copy)."

EDIT_ANIMATION_GLOBAL = "Edit the whole animation"
EDIT_ANIMATION_GLOBAL_TIP = "Applies the change to every point, including the ones kept outside trimmed edges. Unchecked: edits only the current time."

EDIT_SLIDESHOW = "Slideshow"
EDIT_SLIDESHOW_TIP = "Use the size of the largest photo, capped at 1920 px. Available in projects with no visible video; doesn't change the role of the images on the tracks."
