"""Guards the crosswalk-quality rule: no served (unflagged) crosswalk below the cosine floor."""
import importlib.util, sqlite3
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("acf", Path(__file__).parent.parent / "scripts" / "apply_cosine_floor.py")
acf = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(acf)


def _mem():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE crosswalk_mappings (id INTEGER PRIMARY KEY, confidence_score REAL, notes TEXT, flagged_for_review INT DEFAULT 0, verified_by_human INT DEFAULT 0, updated_at TEXT)")
    c.executemany("INSERT INTO crosswalk_mappings (confidence_score, notes) VALUES (?, ?)",
                  [(0.70, "[LLM score 4/5] x."), (0.7499, None), (0.75, "[LLM score 3/5] y."), (0.90, "z")])
    return c


def test_floor_flags_below_only_and_is_idempotent_and_reversible():
    c = _mem()
    assert acf.apply(c) == 2 and acf.apply(c) == 0
    assert [r[0] for r in c.execute("SELECT flagged_for_review FROM crosswalk_mappings ORDER BY id")] == [1, 1, 0, 0]
    assert c.execute("SELECT notes FROM crosswalk_mappings WHERE id=1").fetchone()[0].startswith("[LLM score 4/5]")  # score still parseable
    assert acf.revert(c) == 2 and c.execute("SELECT SUM(flagged_for_review) FROM crosswalk_mappings").fetchone()[0] == 0


def test_db_serves_nothing_below_floor(db):
    """Only enforced on a DB the rule has been applied to (marker present); the pre-change live DB skips."""
    if not db.execute("SELECT 1 FROM crosswalk_mappings WHERE notes LIKE '%'||?||'%' LIMIT 1", (acf.MARKER,)).fetchone():
        pytest.skip("cosine floor not applied to this DB")
    bad = db.execute("SELECT COUNT(*) FROM crosswalk_mappings WHERE flagged_for_review=0 AND verified_by_human=0 AND confidence_score<?", (acf.FLOOR,)).fetchone()[0]
    assert bad == 0
