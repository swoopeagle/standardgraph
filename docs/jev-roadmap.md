# Jev × StandardGraph — mechanism and roadmap

Drafted 2026-09-22. Supersedes nothing; `~/projects/Jev/CONTEXT.md` remains the
adoption authority for Jev generally, and **is now partly stale** — it says "nobody
here has run Jev, we are not on the waitlist." We have since run ~7,000 judgments
against `jev-1.13.0` on real data (2026-09-20, see that session's harness in the
scratchpad). That repo needs a correction pass.

---

## Why StandardGraph is the right home for this, when Umbel wasn't

The Jev repo rejected Jev for Umbel on **egress**: every call ships screen contents
to a third party, and no local form exists. That objection is absolute and it still
stands for Umbel.

It does not apply here at all. StandardGraph's corpus is **published curriculum
standards** — CCSS, NGSS, IB, Singapore MOE. Public documents, already on the open
web, with no personal data of any kind. The one reason Jev was refused is the one
reason that cannot arise in this repo.

The other standing decision — *"don't design around confidence-gated escalation,
measured to degrade precision"* — is respected below rather than ignored. Nothing in
this roadmap auto-suppresses an edge because a confidence number crossed a line. Jev
supplies a **ranking and a disagreement signal**; the gate is always a structural
invariant or a human.

---

## The mechanism, plainly

A Jev call is: send a *state*, send typed *questions*, get back calibrated
probabilities. No prose, no parsing. Three question types — `Noul` (0–1 truth),
`Choice` (pick one of ≤255), `Score` (2–10 ordered levels, returns a
probability-weighted mean plus the full distribution).

StandardGraph fits this unusually well for two reasons.

**1. The answer space is finite and enumerable.** Every question this graph asks has
a bounded candidate set — a grade has 40–50 standards, a domain has 6–10, a crosswalk
is a yes/no about one pair. That is exactly `Choice` and `Noul` territory. There is
never a case where the right answer isn't already in the database.

**2. The graph can check itself.** This is the important one, and it is what makes
this different from pointing an LLM at the problem. StandardGraph contains
**internal redundancy**: the same fact is derivable more than one way. So a wrong
answer can be caught without anyone labelling anything.

### The five invariants — the try/fail mechanism

| # | Invariant | What a failure means |
|---|---|---|
| 1 | **Symmetry** — if A→B scores 0.9, B→A should too | One direction was scored wrong |
| 2 | **Round-trip** — CCSS.X → Singapore → back to CCSS should land on X or a near neighbour | The hop through the other system loses the concept |
| 3 | **Direct vs. two-hop** — the 88,944 `direct_family` edges assert A→C; the hub route asserts A→hub→C. **Both derivations already exist.** | They disagree; one is wrong, and Jev arbitrates |
| 4 | **Grade monotonicity** — a prerequisite sits at or below its successor's grade | Automatic fail, no model needed |
| 5 | **Path coherence** — every step of a `get_learning_path` chain should hold as a pairwise `Noul` | The path has a broken link |

Invariant 3 is the free lunch: **you already have two independent derivations of the
same relationship, for 88,944 edges.** Where they agree, both are probably right.
Where they disagree, something is wrong and you did not have to label a single row to
find out. That is a genuine try/fail loop over a corpus with zero human verification
in it.

---

## What is actually wrong today

Three measured facts from the current DB, all of which Jev addresses directly.

### 1. 99.95% of the relationship graph has never been checked

```
method           relationship      rows
grade_heuristic  prerequisite  1,891,579
grade_heuristic  successor     1,891,579
llm_validated    prerequisite      2,016
llm_validated    successor         2,016
```

**1.89 million prerequisite claims derived from a grade heuristic** — roughly "lower
grade, same domain, therefore prerequisite." Two of the six shipped MCP tools
(`get_progression`, `get_learning_path`) read straight off this table. 0.05% of it
has been semantically validated. This is the largest unexamined surface in the
product and nobody has looked at it because looking cost too much.

### 2. The crosswalk quality scores are uncalibrated by the repo's own admission

208,442 crosswalks carry a 1–5 score, stored as text in `notes` (`[LLM score 4/5] …`).
CLAUDE.md states plainly: *"scores span calibration regimes (earlier Sonnet mode=4;
fleet 14b generous top-end)."* They also carry no confidence, and they gate what users
see — 37,335 edges are suppressed from `map_standard` on the strength of them.

```
score      rows   flagged
    1     7,005     6,600
    2    58,363    30,687     <- 27,676 score-2 edges are live and unflagged
    3    61,040        46
    4    40,206         2
    5    41,828         0
```

Producing those scores took **two overnight runs across three machines** (Studio +
Mini 2 + IWPC, qwen2.5:14b). Calibration is the one thing Jev's training objective
targets, and a full rescore is about an hour and $3.50.

### 3. Nothing has ever been verified by a human

`SUM(verified_by_human)` across all 208,442 crosswalks: **0**. Which is precisely why
the invariants matter — they are the only try/fail signal available that does not
require Ian to read 200,000 rows.

---

## Roadmap

Sequenced so each phase pays for the next and nothing ships on an unverified claim.

### Phase 0 — Fix the data defects (no model, ~half a day)

Found while testing against oer-mcp on 2026-09-20; these corrupt any measurement
taken downstream, so they come first.

- **Cluster-level codes are absent from StandardGraph.** CCSS officially defines
  codes like `4.MD.A`, `K.CC.B`, `1.G.A` and publishers use them in alignment guides.
  The DB has 533 numbered CCSS math standards and **zero** cluster-level ones. 33
  distinct such codes appeared in a single publisher's guide.
- **ID normalisation.** oer-mcp emits `5.NF.1` and `7.EE.4b`; StandardGraph expects
  `CCSS.MATH.5.NF.A.1`. 110 distinct codes fail to join. A canonicaliser belongs in
  `shared/`, used by both repos.
- **oer-mcp truncates every sub-standard** (`4.NF.B.3.c` → `4.NF.B.3`) — all 3,124
  publisher alignments. StandardGraph *has* the sub-standard rows; the ingest is
  throwing away precision the graph can represent.

Together these dropped 9.6% of a gold set before any model saw it. Pure engineering,
no inference, and every number downstream improves for free.

### Phase 1 — Arbitrate direct vs. two-hop (the honest first test, ~$1.50)

Do this *before* the big runs, because it is the one place the graph already holds
two answers and can grade Jev without a human.

Take the 88,944 `direct_family` math edges. For each, score the direct assertion and
the hub two-hop assertion as `Noul`s. Three outcomes:

- **Both high** → the edge is corroborated. No action.
- **Both low** → both derivations are weak. Candidate for suppression.
- **They disagree** → exactly the interesting set. Sample 30, read them, and decide
  whether Jev or the existing pipeline is right.

This is the go/no-go. If Jev cannot adjudicate cases where the graph already knows
the answer two ways, nothing further is worth running.

### Phase 2 — Recalibrate the crosswalks (~$3.50, ~1–3 hours)

Rescore all 208,442 as a 4-level `Score` with calibrated probabilities. Write to
**new columns** (`jev_score`, `jev_confidence`) — never overwrite `notes`; the fleet
scores are the comparison set and two overnight runs bought them.

The deliverable is the **disagreement matrix**: where the fleet said 4 and Jev says
"not related," and vice versa. In particular, re-examine the **27,676 score-2 edges
that are currently live and unflagged** because hub-layer policy only flags 1s.

### Phase 3 — Validate the 1.89M prerequisites (~$8–20, overnight)

The flagship, and the thing that has never been possible before.

Batch by source standard — send the source once as state, ask a `Noul` per candidate
successor in the same call. That collapses ~1.89M pair-checks into roughly 95k calls
and cuts the token bill by more than half.

Gate on **invariant 4 first** (grade monotonicity) — it is free SQL, it needs no model,
and it will eliminate a chunk of the work before a single call is made. Then write
`method='jev_validated'` alongside the existing rows rather than replacing them.

What this buys: `get_learning_path` and `get_progression` stop being grade heuristics
and start being validated claims. That is a product change, not a data-cleaning
change, and it is the thing worth putting in a release note.

### Phase 4 — New capability: `align_resource`

Only after 0–3. On 2026-09-20 Jev scored 78 of 78 single-tagged SBAC assessment items
correctly against their publisher standard (mean confidence 0.955). That result was
clean — those items carry exactly 1.0 standards each, so there was no ambiguity to
hide behind.

A seventh MCP tool: hand it resource text, get back ranked standards with calibrated
confidence, across any of 310 systems. StandardGraph currently answers "what does this
standard mean and what is it equivalent to." This answers **"what standard is this
thing?"** — which is the question every publisher, district and OER repository
actually has, and the one the graph has never been able to answer.

---

## Cost and time, all in

| Phase | Work | Cost | Wall clock |
|---|---|---|---|
| 0 | Data defects | $0 | half a day |
| 1 | Direct vs two-hop, 88,944 edges | ~$1.50 | ~30 min |
| 2 | Crosswalk recalibration, 208,442 | ~$3.50 | 1–3 h |
| 3 | Prerequisite validation, 1.89M pairs | ~$8–20 | overnight |
| 4 | `align_resource` tool | build time | — |

**Under $30 to put a calibrated confidence on every claim in a 175,738-standard,
3.99-million-edge graph.** The comparison is not "cheaper than Sonnet" — it is that
the crosswalk layer alone previously took two overnight runs across three machines
and still came out uncalibrated, and the prerequisite layer was never attempted at all.

---

## Risks and open questions

- ⚠️ **TypeSafe's ToU reportedly prohibits customers publishing performance
  information.** Flagged in `~/projects/Jev/CONTEXT.md` and never resolved. Benchmark
  numbers were written into a private artifact on 2026-09-20. **Read the ToU before
  anything here becomes a public release note, a README claim, or a blog post.**
- **Prefix/state caching is unknown** (open question 3 in the Jev repo, asked on HN,
  never answered). Phase 3's batching assumes state is charged once per call, which
  is true within a call but says nothing across calls. If there is no cross-call
  caching the estimates hold; if there is, they fall.
- **Rate limits are unmeasured.** TypeSafe lost API capacity to demand during launch
  week. Phase 3 is ~95k calls; run it with backoff and expect to be throttled.
- **Design to a 32k state cap.** Docs contradict themselves on 32k vs 64k; Cloudflare
  and Vercel both say 32k. Irrelevant for crosswalks (tiny states), relevant if
  Phase 4 ever ingests long documents.
- **Vendor concentration.** One company, seven days old at time of writing, one model.
  Writing `jev_score` to its own columns rather than overwriting is the hedge — if
  this goes away, the fleet scores are untouched and the graph is unharmed.
- **The invariants are necessary, not sufficient.** A crosswalk layer could be
  self-consistent and uniformly wrong. Invariants catch contradiction, not shared bias.
  Phase 1's 30-row hand read is what guards against that, and it should not be skipped.
