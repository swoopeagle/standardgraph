# Prerequisite-graph pilot (WIP — in flight as of 2026-07-09)

LLM-validated CCSS-math prerequisite graph + `get_learning_path` tool.
Full design: `~/.claude/plans/rippling-yawning-codd.md`. State + resume notes:
memory `project_prereq_graph_pilot`.

- `prereq_candidates.py` — Phase 0. Regenerates ~2,568 candidate prereq pairs
  from a scratch fork of prod (CCSS-math content, strictly-lower-grade,
  cross-domain, cosine≥0.45, grade-window≤3, top-6, MP excluded). Deterministic.
  Repoint DB path + output path to a fresh scratch dir before running.
- `prereq_gate.py` — Phase 1. Directional HARD/SOFT/NONE gate on Studio
  qwen2.5:72b, validated against the 40-pair gold set. **The GOLD dict (38
  hand-labeled pairs keyed by id-suffix) is the non-regenerable treasure** —
  20 HARD / 10 SOFT / 8 NONE, with MUST_NOT_HARD (spurious traps) and MUST_HARD
  (real cross-domain prereqs relate.py misses) as critical sets. Bar: ≥85%
  binary (HARD vs not) + 0 spurious accepted + 0 cross-domain missed.
- `prereq_gold_sample.json` — the 40 sampled candidates (texts) the gate reads.

Paths inside the scripts point at a now-defunct session scratchpad — repoint
them. Scratch DB is `prereq_pilot.db` (a `.backup` fork of prod).
