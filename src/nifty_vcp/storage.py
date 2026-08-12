"""Atomic publication of scan artifacts."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pandas as pd


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def publish_run(
    output_root: str | Path,
    artifacts: dict[str, pd.DataFrame],
    manifest: dict,
) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    staging = root / f".staging-{token}"
    staging.mkdir()
    for filename, frame in artifacts.items():
        compression = "gzip" if filename.endswith(".gz") else None
        frame.to_csv(staging / filename, index=False, compression=compression)
    _write_json(staging / "run_manifest.json", manifest)
    timestamp = str(manifest.get("finished_at", "run"))[:19]
    safe_timestamp = timestamp.replace("-", "").replace(":", "").replace("T", "-")
    final = root / safe_timestamp
    if final.exists():
        final = root / f"{safe_timestamp}-{token}"
    os.replace(staging, final)
    latest_temp = root / f".latest-{token}.json"
    _write_json(latest_temp, {"run_directory": final.name})
    os.replace(latest_temp, root / "latest.json")
    return final

