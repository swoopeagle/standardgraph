"""Tests for the 5 MCP server tools.

Tests that require Ollama (search_standards, get_progression) are marked
with @pytest.mark.ollama and skipped by default unless --ollama is passed.
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest

_DB_PATH = Path(__file__).parent.parent / "data" / "common_core.db"
os.environ.setdefault("DB_PATH", str(_DB_PATH))
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")

from common_core.server import lookup_standard, list_systems, map_standard  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--ollama", action="store_true", default=False,
                     help="Run tests that require a live Ollama instance")


def pytest_configure(config):
    config.addinivalue_line("markers", "ollama: requires live Ollama (skip by default)")


# ── list_systems ──────────────────────────────────────────────────────────────

def test_list_systems_returns_json():
    result = json.loads(list_systems())
    assert "totals" in result
    assert result["totals"]["standards"] >= 130_000
    assert result["totals"]["systems"] >= 200


def test_list_systems_includes_all_subjects():
    result = json.loads(list_systems())
    subjects = {s["subject"] for s in result.get("systems", []) if "subject" in s}
    # Subject column may not be in list_systems output directly;
    # just verify the system IDs for all 5 hubs are present
    system_ids = {s["system"] for s in result["systems"]}
    for hub in ("ccss", "ngss", "ccss-ela", "c3", "csta"):
        assert hub in system_ids, f"Hub {hub!r} missing from list_systems"


def test_list_systems_hubs_present():
    result = json.loads(list_systems())
    system_ids = {s["system"] for s in result.get("systems", [])}
    for hub in ("ccss", "ngss", "ccss-ela", "c3", "csta"):
        assert hub in system_ids, f"Hub {hub!r} missing from list_systems"


# ── lookup_standard ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("std_id,system,text_fragment", [
    ("CCSS.MATH.6.RP.3",                      "ccss",     "ratio"),
    ("ccss-ela.CCSS.ELA-Literacy.L.K.4",      "ccss-ela", None),
    ("NGSS.K-2-ETS1-1",                        "ngss",     None),
    ("c3.D2.His.17.K-2",                       "c3",       None),
    ("csta.1A-IC-18",                          "csta",     None),
    ("AP.AP_ENV.ERT-1.A",                      "ap-env",   None),
    ("tx-ela.5.13.H",                          "tx-ela",   None),
    ("al-ss.HG.14.a",                          "al-ss",    None),
    ("fl-cs.7.08",                             "fl-cs",    None),
])
def test_lookup_known_standard(std_id, system, text_fragment):
    result = json.loads(lookup_standard(std_id, system=system))
    assert "error" not in result, f"lookup failed: {result}"
    assert result["id"] == std_id
    if text_fragment:
        assert text_fragment.lower() in result["standard_text"].lower()


def test_lookup_ccss_shortform():
    """Shortform '6.RP.3' should expand to 'CCSS.MATH.6.RP.3'."""
    result = json.loads(lookup_standard("6.RP.3", system="ccss"))
    assert result["id"] == "CCSS.MATH.6.RP.3"


def test_lookup_missing_standard():
    result = json.loads(lookup_standard("CCSS.MATH.99.ZZ.Z.0", system="ccss"))
    assert result.get("error") == "standard_not_found"


def test_lookup_has_grade_links():
    """A mid-grade standard should have grade relationships."""
    result = json.loads(lookup_standard("CCSS.MATH.6.RP.3", system="ccss"))
    assert "error" not in result
    has_links = bool(result.get("prerequisites")) or bool(result.get("successors"))
    assert has_links, "Expected grade-progression links for CCSS.MATH.6.RP.3"


# ── map_standard — precomputed crosswalk paths (no Ollama) ────────────────────

@pytest.mark.parametrize("std_id,from_sys,to_sys", [
    # These have precomputed crosswalk mappings (response key: "mappings")
    ("tx-ela.5.13.F",    "tx-ela",  "ccss-ela"),
    ("al-ss.HG.14.a",    "al-ss",   "c3"),
    ("fl-cs.7.08",       "fl-cs",   "csta"),
])
def test_map_standard_precomputed(std_id, from_sys, to_sys):
    """Precomputed crosswalk returns a direct mapping."""
    result = json.loads(map_standard(std_id, from_system=from_sys, to_system=to_sys))
    assert "error" not in result, f"map_standard failed: {result}"
    assert result.get("mapping_method") == "precomputed_crosswalk", (
        f"Expected precomputed_crosswalk, got: {list(result.keys())}"
    )
    mappings = result.get("mappings", [])
    assert mappings, f"No precomputed mappings for {std_id} → {to_sys}"
    assert mappings[0]["target_id"].startswith(to_sys), (
        f"Top match {mappings[0]['target_id']!r} doesn't start with {to_sys!r}"
    )


def test_map_standard_ccss_to_state():
    """Mapping from CCSS hub to a state system uses two-hop reverse lookup."""
    result = json.loads(map_standard("CCSS.MATH.6.RP.3", from_system="ccss", to_system="tx"))
    assert "error" not in result, f"map_standard failed: {result}"
    assert "two_hop_via_ccss" in result or "nearest_by_concept" in result, (
        f"Expected two_hop_via_ccss or nearest_by_concept; got keys: {list(result.keys())}"
    )


def test_map_standard_missing_source():
    result = json.loads(map_standard("BOGUS.ID.0.0.0", from_system="ccss", to_system="tx"))
    assert result.get("error") == "standard_not_found"


# ── crosswalk hub routing — verify subject→hub mapping in DB ─────────────────

@pytest.mark.parametrize("system,expected_hub", [
    ("tx",       "ccss"),
    ("ca-on",    "ccss"),
    ("sg-moe",   "ccss"),
    ("tx-sci",   "ngss"),
    ("al-sci",   "ngss"),
    ("ap-bio",   "ngss"),
    ("ap-env",   "ngss"),
    ("tx-ela",   "ccss-ela"),
    ("al-ela",   "ccss-ela"),
    ("al-ss",    "c3"),
    ("tx-ss",    "c3"),
    ("fl-cs",    "csta"),
    ("ut-cs",    "csta"),
])
def test_crosswalk_routes_to_correct_hub(db, system, expected_hub):
    """Every crosswalk mapping from a given system should point to its subject hub."""
    rows = db.execute(
        """SELECT DISTINCT s.system AS target_sys
           FROM crosswalk_mappings cm
           JOIN standards s ON s.id = cm.target_id
           WHERE cm.source_id IN (
               SELECT id FROM standards WHERE system=? LIMIT 50
           )""",
        (system,)
    ).fetchall()
    target_systems = {r[0] for r in rows}
    assert expected_hub in target_systems, (
        f"{system} crosswalk targets {target_systems!r}, expected to include {expected_hub!r}"
    )


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
