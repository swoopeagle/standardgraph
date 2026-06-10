"""DB coverage tests — verify all 5 subjects are populated and fully embedded."""
import pytest


# ── Per-system minimum counts ─────────────────────────────────────────────────

SUBJECT_HUBS = {
    "ccss":     343,
    "ngss":     100,
    "ccss-ela": 400,
    "c3":       200,
    "csta":      80,
}

MATH_INTL = {
    "sg-moe":    150,
    "jp-mext":    50,
    "nz-moe":    200,
    "au-acara":  100,
    "cambridge": 400,
    "ib-myp":     80,
    "uk-nc":     150,
}

AP_COURSES = {
    "ap-calc-ab":     25,
    "ap-calc-bc":     25,
    "ap-stats":       25,
    "ap-precalc":     25,
    "ap-bio":         70,
    "ap-chem":        70,
    "ap-phys-1":      50,
    "ap-phys-2":      50,
    "ap-phys-c-mech": 50,
    "ap-phys-c-em":   30,
    "ap-env":         80,
}

US_STATE_SAMPLES = {
    # math
    "tx":  500,
    "ca":  100,
    "fl":  400,
    "ny":   80,
    # science
    "tx-sci": 200,
    "ca-sci": 200,
    # ela
    "tx-ela": 200,
    "ca-ela": 200,
    "fl-ela": 400,
    # social studies
    "tx-ss":  300,
    "al-ss":  300,
    # cs
    "ut-cs":   50,
    "fl-cs":   15,
}


@pytest.mark.parametrize("system,min_count", list(SUBJECT_HUBS.items()))
def test_hub_coverage(db, system, min_count):
    count = db.execute(
        "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
    ).fetchone()[0]
    assert count >= min_count, f"{system}: {count} standards (expected ≥ {min_count})"


@pytest.mark.parametrize("system,min_count", list(MATH_INTL.items()))
def test_international_math_coverage(db, system, min_count):
    count = db.execute(
        "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
    ).fetchone()[0]
    assert count >= min_count, f"{system}: {count} standards (expected ≥ {min_count})"


@pytest.mark.parametrize("system,min_count", list(AP_COURSES.items()))
def test_ap_course_coverage(db, system, min_count):
    count = db.execute(
        "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
    ).fetchone()[0]
    assert count >= min_count, f"{system}: {count} standards (expected ≥ {min_count})"


@pytest.mark.parametrize("system,min_count", list(US_STATE_SAMPLES.items()))
def test_us_state_sample_coverage(db, system, min_count):
    count = db.execute(
        "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
    ).fetchone()[0]
    assert count >= min_count, f"{system}: {count} standards (expected ≥ {min_count})"


def test_total_standards(db):
    """DB should have at least 130k standards."""
    count = db.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    assert count >= 130_000, f"Total standards: {count}"


def test_embeddings_complete(db):
    """Every standard must have an embedding."""
    total = db.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    embedded = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    missing = total - embedded
    assert missing == 0, f"{missing} standards are missing embeddings"


def test_relationships_exist(db):
    """Grade-progression relationships must be populated."""
    count = db.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    assert count >= 1_000_000, f"Only {count:,} relationships — expected ≥ 1M"


def test_subject_column_populated(db):
    """Every standard should have a non-null subject."""
    null_count = db.execute(
        "SELECT COUNT(*) FROM standards WHERE subject IS NULL OR subject = ''"
    ).fetchone()[0]
    assert null_count == 0, f"{null_count} standards have no subject"


def test_all_50_states_math(db):
    """All 50 US states + DC should have math standards."""
    states = {
        row[0] for row in db.execute(
            "SELECT DISTINCT system FROM standards WHERE subject='mathematics' "
            "AND length(system)=2"
        ).fetchall()
    }
    expected = {
        "ak","al","ar","az","ca","co","ct","dc","de","fl","ga","hi","ia","id","il",
        "in","ks","ky","la","ma","md","me","mi","mn","mo","ms","mt","nc","nd","ne",
        "nh","nj","nm","nv","ny","oh","ok","or","pa","ri","sc","sd","tn","tx","ut",
        "va","vt","wa","wi","wv","wy",
    }
    missing = expected - states
    assert not missing, f"Missing US state math systems: {sorted(missing)}"


def test_ela_states_coverage(db):
    """At least 45 US states should have ELA standards."""
    count = db.execute(
        "SELECT COUNT(DISTINCT system) FROM standards WHERE system LIKE '%-ela' "
        "AND length(system)=6"
    ).fetchone()[0]
    assert count >= 45, f"Only {count} state ELA systems (expected ≥ 45)"


def test_ss_states_coverage(db):
    """At least 44 US states should have social studies standards."""
    count = db.execute(
        "SELECT COUNT(DISTINCT system) FROM standards WHERE system LIKE '%-ss' "
        "AND length(system)=5"
    ).fetchone()[0]
    assert count >= 44, f"Only {count} state SS systems (expected ≥ 44)"


def test_science_states_coverage(db):
    """All 51 jurisdictions should have science standards."""
    count = db.execute(
        "SELECT COUNT(DISTINCT system) FROM standards WHERE system LIKE '%-sci' "
        "AND length(system)=6"
    ).fetchone()[0]
    assert count >= 51, f"Only {count} state science systems (expected ≥ 51)"
