"""Withheld systems (data/withheld_systems.txt) must not ship in a release DB."""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from withhold_systems import withheld  # noqa: E402

DB = os.path.expanduser(os.environ.get("DB_PATH", "~/.standardgraph/common_core.db"))


def test_list_parses():
    assert {"ca-bc", "fi-oph", "rw-reb", "ke-kicd", "ug-ncdc", "ng-nerdc"} <= set(withheld())


@pytest.mark.skipif(os.path.basename(DB) == "common_core.db", reason="live DB predates the withhold; checked on release copies")
def test_release_db_has_no_withheld_rows():
    db = sqlite3.connect(DB)
    q = ",".join("?" * len(withheld()))
    assert db.execute(f"SELECT COUNT(*) FROM standards WHERE system IN ({q})", withheld()).fetchone()[0] == 0
    assert db.execute(f"SELECT COUNT(*) FROM crosswalk_mappings WHERE source_system IN ({q}) OR target_system IN ({q})", withheld() * 2).fetchone()[0] == 0


@pytest.mark.skipif(os.path.basename(DB) == "common_core.db", reason="live DB predates the score-flag fix; checked on release copies")
def test_no_unflagged_score_one_edges():
    db = sqlite3.connect(DB)
    n = db.execute("SELECT COUNT(*) FROM crosswalk_mappings WHERE flagged_for_review=0 AND verified_by_human=0 "
                   "AND notes LIKE '%[LLM score 1/%'").fetchone()[0]
    assert n == 0
