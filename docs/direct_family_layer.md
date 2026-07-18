# Family-structured direct crosswalk layer

**Status:** data-generation layer for mathematics crosswalks

## Purpose

StandardGraph's main crosswalk graph is deliberately hub-and-spoke: a
non-hub curriculum maps to the subject hub (for mathematics, CCSS). That is a
useful global baseline, but it is lossy for two closely related non-hub
curricula. A route such as `A → CCSS → B` asks both systems to express their
relationship through CCSS, even when their own sequence, terminology, and
standard granularity are more closely aligned.

The family-structured direct crosswalk layer materializes direct `A → B` and
`B → A` edges for systems that belong to the same content-affinity family.
Those edges are ordinary precomputed crosswalk rows, so they are returned by
`map_standard` without an MCP-server architecture change.

Families were discovered by clustering curricula on **content-affinity
residual**, not by geography. The labels are shorthand for the resulting
clusters, not a claim that every member shares a country, language, or
governance model.

## Family taxonomy

`ccss` is intentionally excluded from every family: it remains the global
mathematics hub rather than a sibling-family member.

| Family | Member systems |
|---|---|
| `commonwealth` | `uk-nc`, `au-acara`, `nz-moe`, `sg-moe`, `in-ncert`, `ke-kicd`, `tz-tie`, `ug-ncdc`, `gh-nacca`, `ng-nerdc`, `za-caps`, `zm-cdc`, `na-nied` |
| `atomic_style` | `cl-mineduc`, `jp-mext`, `kr-ncf` |
| `iberian_continental` | `pe-minedu`, `co-men`, `es-lomloe`, `pt-dge`, `de-kmk`, `it-miur`, `fi-oph`, `gb-sco`, `rw-reb` |
| `latin_southern` | `mx-sep-2017`, `br-bncc`, `uy-anep`, `cz-msmt` |
| `anglophone_distinct` | `ca-on`, `ie-ncca`, `hk-edb`, `zw-zimsec` |

The authoritative taxonomy is `FAMILIES` in
`packages/crosswalk-engine/src/crosswalk_engine/direct_family.py`.

## Edge construction

The pass operates on every **ordered** pair of distinct systems in the chosen
family. For each mathematics standard in source system `A`, it selects the
single highest-cosine embedding match in target system `B`.

An edge is inserted only when both gates pass:

```text
cosine similarity >= 0.70
abs(target grade key - source grade key) <= 5
```

The grade calculation is shared with `nlp_pass`:

- `K` maps to 0; numeric grades map to their number; `HS` maps to 9.
- Spelled-out grades are supported.
- Grade ranges use their lower endpoint (for example, `6-8` becomes 6).

Rows use `relationship = "equivalent"`, retain the cosine score and grade
delta in their normal columns, and are identified in `notes`, for example:

```text
direct_family cosine=0.8234
```

Because the algorithm visits both `A → B` and `B → A`, the layer is direct in
both directions; it is not a transitive closure. The generated rows are
intended to be reversible by provenance tag:

```sql
DELETE FROM crosswalk_mappings
WHERE notes LIKE 'direct_family%';
```

Use this only against a deliberately selected database copy or approved
maintenance workflow.

## Serving behavior

`map_standard` first searches `crosswalk_mappings` for a precomputed edge
from the requested source standard to the requested target system. It does
not require that target to be a hub. A qualifying family edge therefore
returns normally as:

```json
{
  "mapping_method": "precomputed_crosswalk",
  "mappings": [ ... ]
}
```

If no qualifying direct edge exists, the usual fallback remains available:
`map_standard` can assemble a `two_hop_via_ccss` result before using its
semantic nearest-by-concept fallback. By putting sibling-curriculum matches
in the precomputed layer, a direct edge takes priority over that lossy
hub-mediated route.

By default, edges marked `flagged_for_review` are excluded from precomputed
results. Callers performing review can opt in with `include_flagged=true`.

## Quality scoring and review suppression

Direct-family edges may receive the same optional LLM quality assessment used
by other crosswalk rows. The score and rationale live in `notes` in this form:

```text
[LLM score N/5] <rationale>
```

The score is surfaced by `map_standard` as `quality_score`. A score of 2 or
below sets `flagged_for_review = 1`; that suppresses the edge from default
precomputed results while preserving it for audit or an
`include_flagged=true` request. This is a review mechanism, not a claim that
unscored edges have passed an LLM assessment.

Counts change as scoring runs progress. Check the current state rather than
copying a count into documentation:

```sql
SELECT
  COUNT(*) AS llm_scored_edges,
  SUM(flagged_for_review = 1) AS flagged_edges
FROM crosswalk_mappings
WHERE notes LIKE '%LLM score%';
```

## Running the pass

Run one family at a time:

```bash
uv run python -m crosswalk_engine.direct_family --family <name>
```

`<name>` must be one of `commonwealth`, `atomic_style`,
`iberian_continental`, `latin_southern`, or `anglophone_distinct`. The command
defaults to `commonwealth`; it also accepts `--threshold` to override the
0.70 cosine cutoff. The grade-delta maximum is fixed at 5 by the command's
current interface.

## How this differs from the direct-crosswalk pilot

[`direct_crosswalk_pilot_report.md`](direct_crosswalk_pilot_report.md)
documents an earlier, separate experiment. That pilot targeted six
high-orphan source systems, drew candidate targets from the broader orphan
pool, used a lower candidate-generation floor, and passed candidates through
an LLM guardrail before inserting approved `direct_equivalent` rows.

The family layer instead has a bounded, taxonomy-driven scope: it compares
every ordered sibling pair within a content-affinity family, chooses top-1
cosine matches, applies the 0.70 and grade-delta gates, and writes
`equivalent` rows tagged `direct_family`. Both approaches rely on the same
important server property: peer-to-peer rows already participate in
`map_standard`'s precomputed lookup.

## Relationship to the documented limitations

The README correctly cautions that hub-directed crosswalks are one-way and
that non-hub-to-non-hub comparisons have historically been less reliable than
routing through a hub. This layer narrows that limitation only for selected
within-family mathematics pairs. It does not make all systems bidirectional,
does not replace subject hubs, and does not turn cosine similarity into
human verification. Treat returned mappings as closest available matches and
use expert review for high-stakes decisions.
