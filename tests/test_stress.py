import pytest

from voice_stream_slo.buffer import simulate_jitter_buffer
from voice_stream_slo.schema import ChunkEvent
from voice_stream_slo.stress import inject_receive_pause


def _chunks() -> list[ChunkEvent]:
    return [
        ChunkEvent(index, 100.0 + index * 30.0, 1_920, 40.0)
        for index in range(8)
    ]


def test_receive_pause_shifts_only_the_suffix() -> None:
    original = _chunks()
    shifted = inject_receive_pause(original, pause_ms=120.0, audio_fraction=0.5)

    assert [chunk.arrival_ms for chunk in shifted[:3]] == [100.0, 130.0, 160.0]
    assert [chunk.arrival_ms for chunk in shifted[3:]] == [310.0, 340.0, 370.0, 400.0, 430.0]
    assert [chunk.media_duration_ms for chunk in shifted] == [40.0] * 8


def test_receive_pause_can_turn_a_playable_trace_into_an_underrun() -> None:
    original = _chunks()
    assert simulate_jitter_buffer(original, depth_ms=80.0).glitch_free

    shifted = inject_receive_pause(original, pause_ms=200.0, audio_fraction=0.5)

    assert not simulate_jitter_buffer(shifted, depth_ms=80.0).glitch_free


@pytest.mark.parametrize(
    ("pause_ms", "audio_fraction", "message"),
    [
        (-1.0, 0.5, "non-negative"),
        (10.0, 0.0, "between zero and one"),
        (10.0, 1.0, "between zero and one"),
    ],
)
def test_receive_pause_rejects_invalid_parameters(
    pause_ms: float,
    audio_fraction: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        inject_receive_pause(_chunks(), pause_ms, audio_fraction)
