"""World-coverage scan 3 (harder countries): CLEAN systems are loaded and floored; STATUTE-ROUTE systems exist only as committed JSON.
DB tests skip on a DB built before this ingest."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
LOADED = [("se-skolverket", "mathematics", 70), ("se-skolverket", "science", 100), ("se-skolverket", "ela", 140), ("se-skolverket", "social-studies", 200),
          ("se-skolverket", "arts", 90), ("se-skolverket", "world-languages", 250), ("jp-mext", "science", 180), ("jp-mext", "world-languages", 70),
          ("it-miur", "ela", 40), ("it-miur", "science", 100), ("it-miur", "social-studies", 130), ("it-miur", "arts", 140), ("it-miur", "cs", 50)]
JSON_ONLY = [("china_compulsory_2022.json", 1100, "text_zh"), ("brazil_bncc_other.json", 900, "text_pt")]


@pytest.fixture(scope="module")
def has_scan3(db):
    if not db.execute("SELECT COUNT(*) FROM standards WHERE system='se-skolverket'").fetchone()[0]:
        pytest.skip("DB predates scan 3")


@pytest.mark.parametrize("system,subject,n", LOADED)
def test_counts(db, has_scan3, system, subject, n):
    assert db.execute("SELECT COUNT(*) FROM standards WHERE system=? AND subject=?", (system, subject)).fetchone()[0] >= n


def test_integrity(db, has_scan3):
    q = lambda s: db.execute(s).fetchone()[0]
    where = ("(system='se-skolverket' OR (system='jp-mext' AND subject IN ('science','world-languages')) OR "
             "(system='it-miur' AND subject<>'mathematics'))")
    assert q(f"SELECT COUNT(*) FROM standards WHERE {where} AND (standard_text='' OR domain='' OR source_url='')") == 0
    assert q(f"SELECT COUNT(*) FROM standards s WHERE {where} AND NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.standard_id=s.id)") == 0
    # translated systems keep the original text next to the English
    assert q("SELECT COUNT(*) FROM standards WHERE system='se-skolverket' AND (cluster IS NULL OR cluster=standard_text)") == 0
    assert q("SELECT COUNT(*) FROM standards WHERE system='it-miur' AND subject<>'mathematics' AND (cluster IS NULL OR cluster=standard_text)") == 0


def test_new_crosswalks_scored_and_floored(db, has_scan3):
    base = """FROM crosswalk_mappings cm JOIN standards s ON s.id=cm.source_id
              WHERE (s.system='se-skolverket' OR (s.system='jp-mext' AND s.subject='science') OR (s.system='it-miur' AND s.subject<>'mathematics')) """
    assert db.execute(f"SELECT COUNT(*) {base} AND cm.notes NOT LIKE '%LLM score%'").fetchone()[0] == 0
    assert db.execute(f"SELECT COUNT(*) {base} AND cm.flagged_for_review=0 AND cm.confidence_score<0.75").fetchone()[0] == 0
    assert db.execute(f"SELECT COUNT(*) {base}").fetchone()[0] > 100


def test_statute_route_systems_not_loaded(db, has_scan3):
    """STATUTE-ROUTE = extracted + committed, NOT in the DB until counsel answers (docs/world-coverage-scan-3.md)."""
    assert db.execute("SELECT COUNT(*) FROM standards WHERE system='cn-moe'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM standards WHERE system='br-bncc' AND subject<>'mathematics'").fetchone()[0] == 0


@pytest.mark.parametrize("fname,n,orig", JSON_ONLY)
def test_json_only_data(fname, n, orig):
    rows = json.loads((ROOT / "data" / fname).read_text())
    assert len(rows) >= n
    for r in rows:
        assert r["text_en"].strip() and r[orig].strip() and r["text_en"] != r[orig]


def test_data_files():
    for f, lo in [("sweden_lgr22.json", 900), ("japan_mext_other.json", 260), ("italy_curricolo_2025.json", 560)]:
        assert len(json.loads((ROOT / "data" / f).read_text())) >= lo, f
