"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from voice_stream_slo.analyze import analyze
from voice_stream_slo.runner import load_json, run_live
from voice_stream_slo.schema import AudioSpec
from voice_stream_slo.synthetic import write_synthetic_traces


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voice-stream-slo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="generate and analyze synthetic validation traces")
    demo.add_argument("--config", default="configs/benchmark.json")
    demo.add_argument("--prompts", default="prompts/prompts.json")
    demo.add_argument("--output", default="results/synthetic")
    demo.add_argument("--repetitions", type=int, default=20)

    run = subparsers.add_parser("run", help="run live provider adapters")
    run.add_argument("--config", default="configs/benchmark.json")
    run.add_argument("--prompts", default="prompts/prompts.json")
    run.add_argument("--output", required=True)
    run.add_argument(
        "--providers",
        default="cartesia,deepgram,elevenlabs,openai",
        help="comma-separated adapter names",
    )

    analyze_parser = subparsers.add_parser("analyze", help="analyze an existing trace directory")
    analyze_parser.add_argument("--config", default="configs/benchmark.json")
    analyze_parser.add_argument("--input", required=True)
    analyze_parser.add_argument("--output", required=True)
    analyze_parser.add_argument("--synthetic", action="store_true")
    return parser


def _demo(args: argparse.Namespace) -> None:
    config = load_json(args.config)
    prompts = load_json(args.prompts)
    output = Path(args.output)
    raw = output / "raw" / "traces"
    audio = AudioSpec(**config["audio"])
    write_synthetic_traces(
        prompts,
        raw,
        audio,
        repetitions=args.repetitions,
        seed=int(config["run"]["seed"]),
    )
    counts = analyze(
        raw,
        output / "analysis",
        [float(value) for value in config["buffer_depths_ms"]],
        seed=int(config["run"]["seed"]),
        synthetic=True,
        stress_replay=config.get("stress_replay"),
    )
    print(json.dumps(counts, indent=2))


def main() -> None:
    load_dotenv()
    args = _parser().parse_args()
    config = load_json(args.config)
    if args.command == "demo":
        _demo(args)
    elif args.command == "run":
        prompts = load_json(args.prompts)
        providers = [name.strip() for name in args.providers.split(",") if name.strip()]
        counts = asyncio.run(run_live(config, prompts, args.output, providers))
        print(json.dumps(counts, indent=2))
    elif args.command == "analyze":
        counts = analyze(
            args.input,
            args.output,
            [float(value) for value in config["buffer_depths_ms"]],
            seed=int(config["run"]["seed"]),
            synthetic=args.synthetic,
            stress_replay=config.get("stress_replay"),
        )
        print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
