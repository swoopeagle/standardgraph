# DB merge strategy — reconciling the diverged Mini 2 / Mini 3 databases

> **Status: implemented & rehearsed (2026-06-30).** The plan below is realized in
> [`scripts/merge_dbs.py`](../scripts/merge_dbs.py). A rehearsal on current read-only
> snapshots produced a valid merged DB in ~3 s of SQL: standards preserved at
> 158,718 / 300 systems, scored rationales **14,626 → 69,450 (+54,824)**, 0 orphan
> crosswalks. Re-run it once tonight's rationale jobs finish (counts will be higher),
> then promote. Implementation notes: stages the overlay's scored rows into an indexed
> temp table, then uses `UPDATE..FROM` + a join-based INSERT (correlated subqueries
> were ~100× slower).

## Problem

Rationale generation ran on two **independent copies** of the DB, so they
diverged on different axes:

| | Standards | Systems | Crosswalks | LLM rationales |
|---|---|---|---|---|
| **Mini 3** | 158,718 | 300 | 96,944 | 14,368 (15%) |
| **Mini 2** | 157,548 | 295 | 97,208 | 57,947 (60%) |

- **Mini 3** is the *standards/systems* superset (has Portugal, full France, the
  5 systems Mini 2 lacks).
- **Mini 2** is the *rationale* leader (≈4× the LLM-scored crosswalks, written by
  bigger models — qwen2.5:72b / gemma4:26b vs Mini 3's qwen2.5:14b).

Neither is publishable alone. We want one authoritative DB =
**Mini 3 standards superset + the best rationale for every crosswalk**.

## Approach: rationale-overlay merge

Do **not** try to reconcile standards / embeddings / relationships row-by-row.
Take Mini 3 as the base (its standards, embeddings, relationships, and crosswalk
structure win outright) and overlay only the **rationale** (the `notes` text +
`confidence_score`) from both DBs onto Mini 3's crosswalk rows.

**Join key is `(source_id, target_id, relationship)` — never `id`.** `id` is a
per-DB autoincrement and means nothing across copies.

A row is "scored" (has a real LLM rationale) when `notes NOT LIKE 'nlp_pass%'`.
Unscored rows still hold the pipeline's placeholder `nlp_pass cosine=…`.

### Steps

1. **Snapshot both DBs to the MacBook (read-only, safe).**
   ```bash
   ssh devos@100.101.100.96 "sqlite3 ~/projects/intl-math-standards-mcp/data/common_core.db '.backup /tmp/mini2.db'"
   scp devos@100.101.100.96:/tmp/mini2.db /tmp/mini2.db
   ssh devos@100.123.114.101 "sqlite3 ~/projects/intl-math-standards-mcp/data/common_core.db '.backup /tmp/mini3.db'"
   scp devos@100.123.114.101:/tmp/mini3.db /tmp/mini3.db
   ```

2. **Base = Mini 3.** `cp /tmp/mini3.db /tmp/merged.db`

3. **Attach Mini 2 and overlay scored rationales.** Mini 2 wins on conflicts
   (bigger models); only its *scored* rows are considered.
   ```sql
   ATTACH '/tmp/mini2.db' AS m2;

   -- a) Fill Mini 3 rows that are unscored, where Mini 2 has a rationale
   -- b) Upgrade Mini 3 rows even if already scored (Mini 2 model is stronger)
   UPDATE crosswalk_mappings AS c
   SET notes = (SELECT s.notes FROM m2.crosswalk_mappings s
                 WHERE s.source_id = c.source_id
                   AND s.target_id = c.target_id
                   AND s.relationship = c.relationship
                   AND s.notes NOT LIKE 'nlp_pass%'),
       confidence_score = (SELECT s.confidence_score FROM m2.crosswalk_mappings s
                 WHERE s.source_id = c.source_id
                   AND s.target_id = c.target_id
                   AND s.relationship = c.relationship
                   AND s.notes NOT LIKE 'nlp_pass%')
   WHERE EXISTS (SELECT 1 FROM m2.crosswalk_mappings s
                  WHERE s.source_id = c.source_id
                    AND s.target_id = c.target_id
                    AND s.relationship = c.relationship
                    AND s.notes NOT LIKE 'nlp_pass%');
   ```

4. **(Optional) Add Mini-2-only scored crosswalks that are missing in Mini 3,**
   but only when both endpoints exist in the merged `standards` table (FK safety):
   ```sql
   INSERT INTO crosswalk_mappings
     (source_id, target_id, source_system, target_system, relationship,
      confidence_score, grade_delta, notes, created_at, updated_at)
   SELECT s.source_id, s.target_id, s.source_system, s.target_system,
          s.relationship, s.confidence_score, s.grade_delta, s.notes,
          s.created_at, s.updated_at
   FROM m2.crosswalk_mappings s
   WHERE s.notes NOT LIKE 'nlp_pass%'
     AND s.source_id IN (SELECT id FROM standards)
     AND s.target_id IN (SELECT id FROM standards)
     AND NOT EXISTS (SELECT 1 FROM crosswalk_mappings c
                      WHERE c.source_id = s.source_id
                        AND c.target_id = s.target_id
                        AND c.relationship = s.relationship);
   ```

5. **Validate `merged.db`:**
   - `standards` = 158,718 / 300 systems (unchanged — base preserved).
   - scored crosswalks ≈ union of both (expect ≈ 58–62k, up from 14k).
   - `ln -sf /tmp/merged.db data/common_core.db && uv run python scripts/eval/run_all.py --tier structural`
   - Spot-check 10 rationales for sane text.

6. **Promote:** copy `merged.db` → `~/.standardgraph/common_core.db`, push the
   same file to **both minis** so they restart from a common base, then upload to
   HuggingFace (separate, token-gated step — rotate token after).

## Root cause / prevention

Divergence happened because both minis wrote rationales to their own DB copy and
their queues overlapped (both ended last night on `ca-sk`).

**Fix: partition systems disjointly across devices** so the nightly result is a
pure union with zero conflicts and no merge ambiguity. The queue scripts already
roughly split (Mini 2 = AP/IB/international, Mini 3 = ELA/science states) — tighten
them so no system is ever assigned to two devices in the same run. Alternatives
(single networked writer, job-queue coordinator) add complexity for little gain at
this fleet size.
