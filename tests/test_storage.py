import json

import pandas as pd
import pytest

from nifty_vcp.storage import publish_run


def artifacts():
    return {
        "all_rankings.csv": pd.DataFrame(columns=["symbol", "rs_rating"]),
        "high_rs_setups.csv": pd.DataFrame(columns=["symbol", "vcp_stars"]),
        "live_breakouts.csv": pd.DataFrame(columns=["symbol", "live_price"]),
        "exclusions.csv": pd.DataFrame(columns=["symbol", "stage", "reason"]),
        "chart_history.csv.gz": pd.DataFrame(columns=["symbol", "date", "Close"]),
    }


def test_publish_run_writes_all_artifacts_and_latest_pointer(tmp_path):
    output = publish_run(
        tmp_path,
        artifacts(),
        {"finished_at": "2026-08-12T10:00:00+05:30", "status": "COMPLETE"},
    )
    assert output.is_dir()
    for name in [*artifacts(), "run_manifest.json"]:
        assert (output / name).exists()
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_directory"] == output.name
    assert list(pd.read_csv(output / "live_breakouts.csv").columns) == [
        "symbol",
        "live_price",
    ]


def test_failed_publish_does_not_replace_latest_pointer(tmp_path):
    old = {"run_directory": "old-run"}
    (tmp_path / "latest.json").write_text(json.dumps(old), encoding="utf-8")

    class BrokenArtifact:
        def to_csv(self, *_args, **_kwargs):
            raise OSError("disk full")

    broken = artifacts()
    broken["all_rankings.csv"] = BrokenArtifact()
    with pytest.raises(OSError, match="disk full"):
        publish_run(
            tmp_path,
            broken,
            {"finished_at": "2026-08-12T10:00:00+05:30"},
        )
    assert json.loads((tmp_path / "latest.json").read_text()) == old

