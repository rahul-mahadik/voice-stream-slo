"""Interleaved, warmed live-provider benchmark runner."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from voice_stream_slo.providers import ADAPTERS, ProviderAdapter, ProviderConfig
from voice_stream_slo.schema import AudioSpec, Trace
from voice_stream_slo.trace_io import write_trace


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def _audio_spec(config: dict[str, Any]) -> AudioSpec:
    return AudioSpec(**config["audio"])


def _provider_config(name: str, config: dict[str, Any]) -> ProviderConfig:
    provider = dict(config["providers"][name])
    known = {"endpoint", "model", "voice", "transport", "key_env"}
    return ProviderConfig(
        name=name,
        endpoint=provider["endpoint"],
        model=provider["model"],
        voice=provider["voice"],
        transport=provider["transport"],
        key_env=provider["key_env"],
        timeout_seconds=float(config["run"]["timeout_seconds"]),
        extra={key: value for key, value in provider.items() if key not in known},
    )


def missing_credentials(provider_names: list[str], config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for name in provider_names:
        key_env = config["providers"][name]["key_env"]
        if not os.environ.get(key_env):
            missing.append(key_env)
    return missing


def _failure_trace(
    adapter: ProviderAdapter,
    trace_id: str,
    prompt: dict[str, str],
    error: Exception,
) -> Trace:
    return Trace.create(
        trace_id=trace_id,
        provider=adapter.config.name,
        model=adapter.config.model,
        voice=adapter.config.voice,
        prompt_id=prompt["id"],
        text=prompt["text"],
        started_at_utc=datetime.now(UTC).isoformat(),
        transport=adapter.config.transport,
        connection_reused=True,
        connection_setup_ms=adapter.connection_setup_ms,
        audio=adapter.audio,
        chunks=[],
        completed_ms=0.0,
        success=False,
        error=f"{type(error).__name__}: {error}",
    )


async def run_live(
    config: dict[str, Any],
    prompts: list[dict[str, str]],
    destination: str | Path,
    provider_names: list[str],
) -> dict[str, int]:
    """Run warmed, globally serial, deterministically interleaved TTS turns."""

    unknown = sorted(set(provider_names) - ADAPTERS.keys())
    if unknown:
        raise ValueError(f"unknown providers: {', '.join(unknown)}")
    missing = missing_credentials(provider_names, config)
    if missing:
        raise RuntimeError(f"missing API key environment variables: {', '.join(missing)}")

    output = Path(destination)
    trace_dir = output / "raw" / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    audio = _audio_spec(config)
    adapters: dict[str, ProviderAdapter] = {}
    counts = {"success": 0, "failure": 0}

    manifest = {
        "schema_version": "1.0",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "providers": provider_names,
        "models": {name: config["providers"][name]["model"] for name in provider_names},
        "repetitions": int(config["run"]["repetitions"]),
        "warmups": int(config["run"]["warmups"]),
        "seed": int(config["run"]["seed"]),
        "network_label": config["run"]["network_label"],
        "audio": config["audio"],
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    (output / "raw" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    try:
        for name in provider_names:
            provider_config = _provider_config(name, config)
            adapter = ADAPTERS[name](provider_config, os.environ[provider_config.key_env], audio)
            await adapter.setup()
            adapters[name] = adapter

        warmup_prompt = prompts[0]
        for name, adapter in adapters.items():
            for warmup in range(int(config["run"]["warmups"])):
                await adapter.synthesize(
                    f"warmup-{name}-{warmup:02d}",
                    warmup_prompt["id"],
                    warmup_prompt["text"],
                )

        schedule = [
            (name, prompt, repetition)
            for repetition in range(int(config["run"]["repetitions"]))
            for prompt in prompts
            for name in provider_names
        ]
        random.Random(int(config["run"]["seed"])).shuffle(schedule)
        cooldown_seconds = float(config["run"]["cooldown_ms"]) / 1000.0

        for name, prompt, repetition in schedule:
            adapter = adapters[name]
            trace_id = f"{name}-{prompt['id']}-r{repetition:03d}"
            try:
                trace = await adapter.synthesize(trace_id, prompt["id"], prompt["text"])
                counts["success"] += 1
            except Exception as error:  # continue the matrix and preserve failure evidence
                trace = _failure_trace(adapter, trace_id, prompt, error)
                counts["failure"] += 1
            write_trace(trace, trace_dir / name / f"{trace_id}.json")
            if cooldown_seconds:
                await asyncio.sleep(cooldown_seconds)
    finally:
        await asyncio.gather(
            *(adapter.close() for adapter in adapters.values()),
            return_exceptions=True,
        )

    manifest["completed_at_utc"] = datetime.now(UTC).isoformat()
    manifest["counts"] = counts
    (output / "raw" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return counts
