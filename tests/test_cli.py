from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nifty_vcp.models import RunStatus, ScanSummary
from scan import main

TZ = ZoneInfo("Asia/Kolkata")


def summary(status):
    now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
    return ScanSummary(status, status.value, 10, 9, 2, 2, 0, now, now, Path("run"))


def test_cli_passes_smoke_limit_and_returns_zero_for_complete(capsys):
    received = {}

    def runner(config, **kwargs):
        received["config"] = config
        received.update(kwargs)
        return summary(RunStatus.COMPLETE)

    code = main(["--max-symbols", "10", "--output-dir", "custom"], runner=runner)
    assert code == 0
    assert received["config"].max_symbols == 10
    assert received["output_root"] == Path("custom")
    output = capsys.readouterr().out
    assert "COMPLETE" in output
    assert "run" in output


def test_cli_returns_two_for_incomplete(capsys):
    code = main([], runner=lambda *_args, **_kwargs: summary(RunStatus.INCOMPLETE))
    assert code == 2
    assert "SCAN INCOMPLETE" in capsys.readouterr().out

