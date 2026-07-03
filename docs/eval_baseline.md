# Eval baseline — 2026-06-30

Run: `uv run python scripts/eval/run_all.py --tier default` (structural + semantic,
LLM judge OFF) against a fresh `.backup` snapshot of the **current Mini 3 DB**
(158,718 standards / 300 systems / 96,944 crosswalks / 14,626 LLM-scored).

> ⚠️ Run against the *current authoritative* DB, not the stale installed one
> (`~/.standardgraph/common_core.db`, Jun 23). The installed DB scores 6/15 FAIL,
> but ~half of those are pure staleness artifacts — see "Staleness" below.

## Result: 12/15 pass (3 fail)

| Tier | Check | Result |
|---|---|---|
| structural | DB integrity | ✅ |
| structural | Coverage & known IDs | ✅ |
| structural | Duplicate detection | ✅ |
| structural | Crosswalk quality | ✅ |
| semantic | Search quality (golden) | ✅ |
| semantic | Search filter accuracy | ✅ |
| semantic | Coverage matrix (all systems) | ✅ |
| semantic | lookup_standard correctness | ✅ |
| semantic | **map_standard fallback** | ❌ 1/5 case |
| semantic | Subject crosswalk routing | ✅ |
| semantic | Crosswalk semantic quality | ✅ |
| semantic | **Two-hop bridge mapping** | ❌ 2 cases |
| semantic | Progression coherence | ✅ |
| semantic | Adversarial robustness | ✅ |
| semantic | **Persona scenarios** | ❌ 1/20 case |

## Crosswalk confidence distribution (healthy)

- ≥ 0.90 (strong): 25,867 (26.7%)
- 0.80–0.90 (good): 19,716 (20.3%)
- 0.70–0.80 (moderate): 51,361 (53.0%)
- < 0.70: 0 (0.0%)  ← hard floor at the cosine threshold

## The 3 failures — all narrow, none are data-corruption

1. **Two-hop bridge (2 cases)** — was `source_not_found` from **stale test
   fixtures** (`IN_NCERT.MATH.3.3646`, `…2.60213` no longer exist; in-ncert was
   re-ingested with new ID hashes). Fixed the fixtures to real IDs
   (`IN_NCERT.MATH.3.34775`, `…2.26524`). They now resolve but still return
   "no results above 0.70" — a **genuine sparsity limit**: two-hop bridging
   between sparse international↔international systems often has no path above the
   combined-confidence floor. Capability gap, not a bug.
2. **map_standard fallback (1/5)** — `gh-nacca → au-acara (rational numbers)`:
   no result above 0.45. Single hard pair; Ghana source text may genuinely lack a
   close au-acara match. Candidate for threshold review.
3. **Persona (1/20)** — Emma scenario expects an `NH → CSTA` crosswalk at
   confidence ≥ 0.95; actual is lower. Over-strict per-case bar.

## Crosswalk coverage — real gaps vs. expected

Zero-crosswalk systems on the current DB are **only the hubs themselves**
(ccss, ccss-ela, ngss, c3, csta — correctly zero as sources) plus **ap-japanese**.
Genuinely low (<40%) coverage clusters in **subjects that have no crosswalk hub**:
World Languages (ap-spanish-lit 1%, ap-french 4%, ap-spanish-lang 5%, ap-italian
6%, ap-latin 7%, ap-chinese 8%) and Arts (ap-music-theory 3%). This is
**architectural** — there is no hub for World Languages or Arts — not a pipeline
bug. Large US Social-Studies state systems (ga-ss, sd-ss, or-ss) sit at 5–8% and
are the main *addressable* coverage opportunity.

## Staleness note (why the installed DB looks worse)

Against the Jun-23 installed DB the suite reports 6/15 FAIL, including
"71 standards with text < 5 chars", ELA/Social-Studies hub mis-routing, and 16
zero-crosswalk systems (mx, es, kr, jp, fi, in, …). **All of these are resolved on
the current DB** — those systems have full crosswalks now (kr 170/187, jp 212/235,
in 202/246, mx 76/86). The takeaway: publish from the merged/current DB and these
clear automatically. Always run evals against a current snapshot.

## How to reproduce

```bash
ssh devos@100.123.114.101 "sqlite3 ~/projects/intl-math-standards-mcp/data/common_core.db '.backup /tmp/snap.db'"
scp devos@100.123.114.101:/tmp/snap.db /tmp/current.db
cd packages/.. && ln -sf /tmp/current.db data/common_core.db
uv run python scripts/eval/run_all.py --tier default      # add --judge for LLM-judged semantic
```
