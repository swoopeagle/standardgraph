"""World-coverage additions: fr-men ingest integrity + the coverage report's inputs.

fr-men tests skip on a DB built before the 2026-10-19 France ingest."""
import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def fr(db):
    n = db.execute("SELECT COUNT(*) FROM standards WHERE system='fr-men'").fetchone()[0]
    if not n:
        pytest.skip("DB predates the fr-men ingest")
    return n


def test_fr_men_ingest(db, fr):
    assert fr >= 650
    q = lambda s: db.execute(s).fetchone()[0]
    assert q("SELECT COUNT(*) FROM standards WHERE system='fr-men' AND (standard_text='' OR domain='' OR cluster IS NULL)") == 0
    assert q("SELECT COUNT(DISTINCT grade) FROM standards WHERE system='fr-men'") == 9  # CP..3e = grades 1-9
    assert q("SELECT COUNT(*) FROM standards WHERE system='fr-men' AND subject<>'mathematics'") == 0
    # English text, French original kept in cluster
    assert q("SELECT COUNT(*) FROM standards WHERE system='fr-men' AND standard_text=cluster") == 0


def test_fr_men_embedded_and_crosswalked(db, fr):
    q = lambda s: db.execute(s).fetchone()[0]
    assert q("SELECT COUNT(*) FROM standards s LEFT JOIN embeddings e ON e.standard_id=s.id WHERE s.system='fr-men' AND e.standard_id IS NULL") == 0
    n = q("SELECT COUNT(DISTINCT source_id) FROM crosswalk_mappings WHERE source_system='fr-men' AND target_system='ccss'")
    assert n / fr >= 0.5


def test_fr_men_data_file_matches_loader():
    rows = json.loads((ROOT / "data" / "france_math_programmes.json").read_text())
    assert len(rows) >= 650 and all(r["text_en"] and r["text_fr"] and r["grade"] in "123456789" for r in rows)


def test_coverage_inputs():
    enr = list(csv.DictReader(open(ROOT / "data" / "world_enrollment.csv")))
    assert len(enr) > 190 and {"USA", "IND", "CHN"} <= {r["iso3"] for r in enr}
    gold = list(csv.DictReader(open(ROOT / "data" / "crosswalk_gold.csv")))
    assert len(gold) >= 50 and {r["label"] for r in gold} <= {"Y", "P", "N"}


def test_system_meta_has_france():
    from common_core.server import SYSTEM_META
    assert SYSTEM_META["fr-men"]["country_code"] == "FR"
