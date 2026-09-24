"""Rótulos de mídia; os modelos não conhecem textos de interface."""
from videomanager.application.formatting import DASH
from videomanager.application.formatting import format_bitrate
from videomanager.application.formatting import format_size
from videomanager.domain.formats import VideoChoice
from videomanager.domain.i18n import t


def resolution_label(choice):
    if choice.height is None:
        return format_bitrate(choice.best.tbr)
    suffix = '' if choice.fps is None or choice.fps <= 30 else str(choice.fps)
    approx = '~' if choice.best.height_is_estimated else ''
    return f'{approx}{choice.height}p{suffix}'


def choice_label(choice):
    if isinstance(choice, VideoChoice):
        parts = [resolution_label(choice)]
        if choice.family:
            parts.append(choice.family)
        if choice.dynamic_range:
            parts.append(choice.dynamic_range)
    else:
        rate = format_bitrate(choice.bitrate)
        parts = [rate] if rate != DASH else []
        parts.append(choice.family or choice.best.ext.upper())
        if choice.language:
            parts.append(choice.language)
        if choice.is_extracted_from_video:
            source = f'{choice.best.height}p' if choice.best.height else choice.best.ext.upper()
            parts.append(t('DESC_EXTRACTED_FROM', source=source))
    size = format_size(choice.best.filesize, estimated=choice.best.filesize_is_estimated)
    if size != DASH:
        parts.append(size)
    return ' · '.join(parts)
