from videomanager.domain.keyframe import (
    ClipTransform,
    Keyframe,
    create_preset_keyframes,
    evaluate_easing,
    interpolate_keyframes,
    resolve_segment_easing,
)


def test_evaluate_easing():
    assert evaluate_easing(0.0, "linear") == 0.0
    assert evaluate_easing(0.5, "linear") == 0.5
    assert evaluate_easing(1.0, "linear") == 1.0

    # ease_in: t^2
    assert evaluate_easing(0.5, "ease_in") == 0.25
    # ease_out: 1 - (1-t)^2
    assert evaluate_easing(0.5, "ease_out") == 0.75
    # ease_in_out: 2*t^2 (t < 0.5)
    assert evaluate_easing(0.25, "ease_in_out") == 0.125
    assert evaluate_easing(0.5, "ease_in_out") == 0.5
    assert evaluate_easing(0.75, "ease_in_out") == 0.875

    # hold
    assert evaluate_easing(0.99, "hold") == 0.0
    assert evaluate_easing(1.0, "hold") == 1.0


def test_interpolate_keyframes_empty_uses_fallback():
    fallback = ClipTransform(x=0.5, y=0.5, scale_x=1.0, scale_y=1.0, rotation=0.0, opacity=1.0)
    res = interpolate_keyframes((), 2.0, fallback)
    assert res == fallback


def test_interpolate_keyframes_single():
    kf = Keyframe(time_offset=1.0, x=0.2, y=0.8, scale_x=2.0, scale_y=2.0, rotation=45.0, opacity=0.5)
    fallback = ClipTransform()
    # Before time_offset
    res_before = interpolate_keyframes((kf,), 0.0, fallback)
    assert res_before.x == 0.2
    assert res_before.opacity == 0.5
    # After time_offset
    res_after = interpolate_keyframes((kf,), 5.0, fallback)
    assert res_after.y == 0.8


def test_interpolate_keyframes_multi():
    k0 = Keyframe(time_offset=0.0, x=0.0, y=0.0, rotation=0.0, opacity=0.0, easing="linear")
    k1 = Keyframe(time_offset=2.0, x=1.0, y=2.0, rotation=90.0, opacity=1.0, easing="linear")
    fallback = ClipTransform()

    # Midpoint at t=1.0
    mid = interpolate_keyframes((k0, k1), 1.0, fallback)
    assert abs(mid.x - 0.5) < 1e-4
    assert abs(mid.y - 1.0) < 1e-4
    assert abs(mid.rotation - 45.0) < 1e-4
    assert abs(mid.opacity - 0.5) < 1e-4

    # Clamping outside bounds
    before = interpolate_keyframes((k0, k1), -1.0, fallback)
    assert before.x == 0.0
    after = interpolate_keyframes((k0, k1), 3.0, fallback)
    assert after.x == 1.0


def test_create_preset_keyframes():
    target = ClipTransform(x=0.5, y=0.5, scale_x=1.0, scale_y=1.0, rotation=0.0, opacity=1.0)
    kfs = create_preset_keyframes("slide_up", target, duration=0.6)
    assert len(kfs) == 2
    assert kfs[0].time_offset == 0.0
    assert kfs[0].y == 1.3
    assert kfs[0].opacity == 0.0
    assert kfs[0].easing == "ease_out"
    assert kfs[1].time_offset == 0.6
    assert kfs[1].y == 0.5
    assert kfs[1].opacity == 1.0


def test_clip_keyframe_methods():
    from pathlib import Path
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind

    media = MediaRef(path=Path("/tmp/test.mp4"), kind=MediaKind.VIDEO, duration=10.0)
    clip = Clip(media=media, start=0.0, duration=10.0, x=0.5, y=0.5)

    assert not clip.has_keyframes
    assert clip.transform_at(2.0).x == 0.5

    kf0 = Keyframe(time_offset=1.0, x=0.2, y=0.2)
    kf1 = Keyframe(time_offset=3.0, x=0.8, y=0.8)

    clip = clip.with_keyframe(kf0).with_keyframe(kf1)
    assert clip.has_keyframes
    assert len(clip.keyframes) == 2
    assert clip.keyframes[0].time_offset == 1.0
    assert clip.keyframes[1].time_offset == 3.0

    # Test nearest_keyframe
    assert clip.nearest_keyframe(1.0) == kf0
    assert clip.nearest_keyframe(1.00001) == kf0
    assert clip.nearest_keyframe(2.0) is None

    # Test without_keyframe
    clip_removed = clip.without_keyframe(1.0)
    assert len(clip_removed.keyframes) == 1
    assert clip_removed.keyframes[0].time_offset == 3.0

    # Test Project split with keyframes
    track = Track(kind=TrackKind.VIDEO, clips=(clip,))
    proj = Project(tracks=(track,))
    split_proj = proj.split(clip.clip_id, seconds=2.0)
    track_split = split_proj.tracks[0]
    assert len(track_split.clips) == 2
    left_clip, right_clip = track_split.clips

    assert len(left_clip.keyframes) == 1
    assert left_clip.keyframes[0].time_offset == 1.0
    assert abs(right_clip.keyframes[0].time_offset - 1.0) < 1e-4


def test_rotation_interpolation_full_spin():
    # 0 -> 360 degrees should NOT collapse to 0 degrees at midpoint
    k0 = Keyframe(time_offset=0.0, rotation=0.0)
    k1 = Keyframe(time_offset=1.0, rotation=360.0)
    fallback = ClipTransform()

    mid = interpolate_keyframes((k0, k1), 0.5, fallback)
    assert abs(mid.rotation - 180.0) < 1e-4

    # 360 -> 0 degrees should also interpolate smoothly
    k_rev0 = Keyframe(time_offset=0.0, rotation=360.0)
    k_rev1 = Keyframe(time_offset=1.0, rotation=0.0)
    mid_rev = interpolate_keyframes((k_rev0, k_rev1), 0.5, fallback)
    assert abs(mid_rev.rotation - 180.0) < 1e-4

    # Negative spin: -360 -> 0 degrees
    k_neg0 = Keyframe(time_offset=0.0, rotation=-360.0)
    k_neg1 = Keyframe(time_offset=1.0, rotation=0.0)
    mid_neg = interpolate_keyframes((k_neg0, k_neg1), 0.5, fallback)
    assert abs(mid_neg.rotation - (-180.0)) < 1e-4


def test_create_preset_spin_in():
    target = ClipTransform(x=0.5, y=0.5, scale_x=1.0, scale_y=1.0, rotation=0.0, opacity=1.0)
    kfs = create_preset_keyframes("spin_in", target, duration=0.6)
    assert len(kfs) == 2
    assert kfs[0].time_offset == 0.0
    assert kfs[0].rotation == -360.0
    assert kfs[0].scale_x == 0.05
    assert kfs[0].opacity == 0.0
    assert kfs[1].time_offset == 0.6
    assert kfs[1].rotation == 0.0
    assert kfs[1].scale_x == 1.0
    assert kfs[1].opacity == 1.0


def test_resolve_segment_easing():
    assert resolve_segment_easing("linear", "linear") == "linear"
    assert resolve_segment_easing("linear", "ease_in_out") == "ease_in_out"
    assert resolve_segment_easing("ease_out", "linear") == "ease_out"
    assert resolve_segment_easing("ease_out", "ease_in") == "ease_in_out"
    assert resolve_segment_easing("hold", "linear") == "hold"
    assert resolve_segment_easing("linear", "hold") == "hold"


def test_interpolate_keyframes_destination_easing():
    k0 = Keyframe(time_offset=0.0, x=0.0, easing="linear")
    k1 = Keyframe(time_offset=2.0, x=1.0, easing="ease_in_out")
    fallback = ClipTransform()

    # Midpoint at raw_t = 0.25 (time_offset = 0.5)
    # ease_in_out at 0.25 is 2 * 0.25^2 = 0.125
    res = interpolate_keyframes((k0, k1), 0.5, fallback)
    assert abs(res.x - 0.125) < 1e-4
