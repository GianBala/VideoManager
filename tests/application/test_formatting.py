from __future__ import annotations

import pytest

from videomanager.application.formatting import format_aspect_ratio


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1920, 1080, "16:9"),
        (1280, 720, "16:9"),
        (3840, 2160, "16:9"),
        (854, 480, "16:9"),
        (1440, 1080, "4:3"),
        (960, 720, "4:3"),
        (640, 480, "4:3"),
        (1080, 1920, "9:16"),
        (720, 1280, "9:16"),
        (1080, 1080, "1:1"),
        (720, 720, "1:1"),
        (2560, 1080, "21:9"),
        (None, 1080, ""),
        (1920, None, ""),
        (0, 0, ""),
    ],
)
def test_format_aspect_ratio(width: int | None, height: int | None, expected: str) -> None:
    assert format_aspect_ratio(width, height) == expected
