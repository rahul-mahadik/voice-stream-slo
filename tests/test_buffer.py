import pytest

from voice_stream_slo.buffer import simulate_jitter_buffer
from voice_stream_slo.schema import ChunkEvent


def _chunk(sequence: int, arrival_ms: float, duration_ms: float = 40.0) -> ChunkEvent:
    return ChunkEvent(sequence, arrival_ms, round(duration_ms * 48), duration_ms)


def test_smooth_stream_stays_playable() -> None:
    chunks = [_chunk(index, 100.0 + index * 30.0) for index in range(8)]
    result = simulate_jitter_buffer(chunks, depth_ms=80)
    assert result.playback_start_ms == 130.0
    assert result.underrun_count == 0
    assert result.glitch_free


def test_starvation_and_recovery_are_measured() -> None:
    chunks = [
        _chunk(0, 100.0),
        _chunk(1, 130.0),
        _chunk(2, 170.0),
        _chunk(3, 300.0),
        _chunk(4, 330.0),
    ]
    result = simulate_jitter_buffer(chunks, depth_ms=80)
    assert result.underrun_count == 1
    assert result.total_stall_ms == pytest.approx(50.0)
    assert result.stalls[0].started_ms == pytest.approx(250.0)
    assert result.stalls[0].recovered_ms == pytest.approx(300.0)


def test_more_initial_buffer_can_prevent_underruns() -> None:
    chunks = [
        _chunk(0, 100.0),
        _chunk(1, 130.0),
        _chunk(2, 170.0),
        _chunk(3, 300.0),
        _chunk(4, 330.0),
    ]
    shallow = simulate_jitter_buffer(chunks, depth_ms=80)
    deep = simulate_jitter_buffer(chunks, depth_ms=160)
    assert shallow.underrun_count == 1
    assert deep.underrun_count == 0


def test_empty_trace_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one chunk"):
        simulate_jitter_buffer([], depth_ms=80)
