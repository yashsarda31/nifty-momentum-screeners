"""Command-line entry point for the Nifty Total Market scanner."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from nifty_vcp.models import RunStatus, ScanConfig, ScanSummary
from nifty_vcp.pipeline import run_scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--high-rs", type=int, default=80)
    parser.add_argument("--coverage", type=float, default=0.90)
    parser.add_argument("--max-symbols", type=int)
    parser.add_argument("--now", type=datetime.fromisoformat)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., ScanSummary] = run_scan,
) -> int:
    args = build_parser().parse_args(argv)
    config = ScanConfig(
        high_rs_threshold=args.high_rs,
        coverage_threshold=args.coverage,
        max_symbols=args.max_symbols,
    )
    summary = runner(config, now=args.now, output_root=args.output_dir)
    print(f"Status: {summary.status.value}")
    print(f"Outcome: {summary.outcome}")
    print(
        "Coverage: "
        f"{summary.valid_history_count}/{summary.universe_count} histories, "
        f"{summary.valid_quote_count}/{summary.high_rs_count} high-RS quotes"
    )
    print(f"Breakouts: {summary.breakout_count}")
    print(f"Output: {summary.output_path}")
    return 0 if summary.status == RunStatus.COMPLETE else 2


if __name__ == "__main__":
    raise SystemExit(main())

