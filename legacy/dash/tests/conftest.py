"""Materialise test-fixture CSVs into the app's data directories.

The season CSVs no longer live in git — production data lives on the server
and is fetched from FanGraphs. Tests still need a deterministic, offline data
set, so a frozen snapshot of the seasons they exercise is kept under
tests/fixtures/ (mirroring the data-directory layout) and copied into place
here. Existing files are never overwritten, so a dev machine or server with
real (fresher) data keeps using it.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    for src in FIXTURES.glob("*/*.csv"):
        dst = ROOT / src.parent.name / src.name
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)

    # Enforce the suite's no-network contract: a season missing from the
    # fixtures must fail loudly and deterministically, not fall through to a
    # live FanGraphs fetch (which would make CI slow, flaky and impolite).
    import pandas as pd
    import data
    data._live_fetch = lambda path: pd.DataFrame()
