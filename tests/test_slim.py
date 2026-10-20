"""Slimmed-release-DB invariants (also hold on unslimmed DBs): successors derive from prerequisites; float16 vectors decode."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from common_core import server


def test_successors_mirror_prerequisites(db):
    sid, tid = db.execute(
        "SELECT source_id, target_id FROM standard_relationships WHERE relationship='prerequisite' "
        "AND method='llm_validated' LIMIT 1").fetchone()
    succ = json.loads(server.lookup_standard(tid, system=tid.split(".")[0].lower().replace("_", "-"), prefer_validated=True))["successors"]
    assert sid in succ


def test_cosine_decodes_float16(db):
    rows = db.execute("SELECT standard_id, vector, dimensions FROM embeddings LIMIT 5").fetchall()
    dim = rows[0]["dimensions"]
    vecs = np.stack([np.frombuffer(r["vector"], np.float16 if len(r["vector"]) == dim * 2 else np.float32) for r in rows]).astype(np.float32)
    assert vecs.shape == (5, dim) and np.isfinite(vecs).all()
    assert abs(np.linalg.norm(vecs[0]) - 1) < 1e-2  # nomic vectors are unit length in either dtype


def test_slim_script_refuses_live_db():
    script = Path(__file__).parent.parent / "scripts" / "slim_release_db.py"
    r = subprocess.run([sys.executable, str(script), "--dry-run"], env={"DB_PATH": str(Path.home() / ".standardgraph" / "common_core.db")}, capture_output=True, text=True)
    assert r.returncode != 0 and "refusing" in r.stderr
