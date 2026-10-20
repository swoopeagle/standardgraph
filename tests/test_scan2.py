"""World-coverage scan 2: new subjects/systems (au-acara, uk-nc, gb-sco, es-lomloe other subjects; no-udir; pl-men).
DB tests skip on a DB built before this ingest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from withhold_systems import withheld  # noqa: E402
WITHHELD = set(withheld())

ROOT = Path(__file__).parent.parent
# (system, subject, min rows)
EXPECT = [("au-acara", "social-studies", 300), ("au-acara", "cs", 70), ("au-acara", "arts", 150), ("au-acara", "world-languages", 1000),
          ("uk-nc", "social-studies", 50), ("uk-nc", "cs", 20), ("gb-sco", "social-studies", 100),
          ("es-lomloe", "science", 200), ("es-lomloe", "ela", 150), ("es-lomloe", "social-studies", 150), ("es-lomloe", "arts", 250),
          ("no-udir", "mathematics", 90), ("no-udir", "science", 60)]


@pytest.fixture(scope="module")
def has_scan(db):
    if not db.execute("SELECT COUNT(*) FROM standards WHERE system='no-udir'").fetchone()[0]:
        pytest.skip("DB predates scan 2")


@pytest.mark.parametrize("system,subject,n", EXPECT)
def test_counts(db, has_scan, system, subject, n):
    if system in WITHHELD:
        pytest.skip(f"{system} is withheld from release DBs")
    assert db.execute("SELECT COUNT(*) FROM standards WHERE system=? AND subject=?", (system, subject)).fetchone()[0] >= n


def test_integrity(db, has_scan):
    q = lambda s: db.execute(s).fetchone()[0]
    where = "(system IN ('no-udir') OR (system='au-acara' AND subject IN ('social-studies','cs','arts','world-languages')) OR (system='es-lomloe' AND subject<>'mathematics') OR (system='uk-nc' AND subject IN ('social-studies','cs','arts','world-languages')) OR (system='gb-sco' AND subject='social-studies'))"
    assert q(f"SELECT COUNT(*) FROM standards WHERE {where} AND (standard_text='' OR domain='' OR source_url='')") == 0
    assert q(f"SELECT COUNT(*) FROM standards s WHERE {where} AND NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.standard_id=s.id)") == 0
    # translated systems keep the original text and it differs from the English
    assert q("SELECT COUNT(*) FROM standards WHERE system IN ('es-lomloe') AND subject<>'mathematics' AND (cluster IS NULL OR cluster=standard_text)") == 0


def test_new_crosswalks_respect_floor(db, has_scan):
    n = db.execute("""SELECT COUNT(*) FROM crosswalk_mappings cm JOIN standards s ON s.id=cm.source_id
        WHERE s.system IN ('no-udir') AND cm.flagged_for_review=0 AND cm.confidence_score<0.75""").fetchone()[0]
    assert n == 0
    assert db.execute("SELECT COUNT(*) FROM crosswalk_mappings WHERE source_system='no-udir'").fetchone()[0] > 50


def test_new_crosswalks_scored(db, has_scan):
    n = db.execute("""SELECT COUNT(*) FROM crosswalk_mappings cm JOIN standards s ON s.id=cm.source_id
        WHERE s.system IN ('no-udir') AND cm.notes NOT LIKE '%LLM score%'""").fetchone()[0]
    assert n == 0


def test_data_files():
    for f, lo in [("au_acara_v9_other.json", 1600), ("uk_nc_other.json", 130), ("scotland_eo_other.json", 100), ("spain_lomloe_other.json", 1100),
                  ("norway_lk20_raw.json", 400), ("poland_podstawa_2026.json", 1000)]:
        rows = json.loads((ROOT / "data" / f).read_text())
        assert len(rows) >= lo, f
    for r in json.loads((ROOT / "data" / "spain_lomloe_other.json").read_text()):
        assert r["text_en"] and r["text_es"] and r["text_en"] != r["text_es"]
    for r in json.loads((ROOT / "data" / "poland_podstawa_2026.json").read_text()):
        assert r["text_en"] and r["text_pl"]


def test_system_meta():
    from common_core.server import SYSTEM_META
    assert SYSTEM_META["no-udir"]["country_code"] == "NO" and SYSTEM_META["pl-men"]["country_code"] == "PL"
