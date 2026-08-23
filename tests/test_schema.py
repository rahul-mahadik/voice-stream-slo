from datetime import UTC, datetime

import pytest

from voice_stream_slo.schema import AudioSpec, ChunkEvent, Trace


def test_pcm_duration_is_derived_from_bytes() -> None:
    audio = AudioSpec(sample_rate_hz=24_000, sample_width_bytes=2, channels=1)
    assert audio.duration_ms(1_920) == pytest.approx(40.0)


def test_trace_round_trip() -> None:
    audio = AudioSpec()
    trace = Trace.create(
        trace_id="one",
        provider="fixture",
        model="fixture-v1",
        voice="voice",
        prompt_id="p1",
        text="hello",
        started_at_utc=datetime.now(UTC).isoformat(),
        transport="fixture",
        connection_reused=True,
        connection_setup_ms=0.0,
        audio=audio,
        chunks=[ChunkEvent(0, 100.0, 1_920, 40.0)],
        completed_ms=145.0,
    )
    restored = Trace.from_dict(trace.to_dict())
    assert restored == trace
    assert restored.text_sha256 != "hello"


def test_trace_rejects_non_monotonic_arrivals() -> None:
    audio = AudioSpec()
    trace = Trace.create(
        trace_id="bad",
        provider="fixture",
        model="fixture-v1",
        voice="voice",
        prompt_id="p1",
        text="hello",
        started_at_utc=datetime.now(UTC).isoformat(),
        transport="fixture",
        connection_reused=True,
        connection_setup_ms=0.0,
        audio=audio,
        chunks=[
            ChunkEvent(0, 120.0, 1_920, 40.0),
            ChunkEvent(1, 110.0, 1_920, 40.0),
        ],
        completed_ms=130.0,
    )
    with pytest.raises(ValueError, match="monotonic"):
        trace.validate()
