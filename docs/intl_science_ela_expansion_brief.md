# International Science + ELA Expansion Brief

_Generated 2026-07-12 (Fable research agent, DB-verified). Read alongside `spec_map_standard_scores.md`._

## Why

Of 310 systems, **259 are US and only ~37 non-US systems exist — all mathematics-only.**
Every `-sci`/`-ela`/`-ss` system in the DB is a US state, so international interoperability
is CCSS-Math-only. Hubs are thin on international spokes: NGSS has 208 crosswalk rows,
CCSS-ELA has 504 — all sourced from US states. This brief ranks candidates to give the
science (NGSS) and ELA (CCSS-ELA) hubs their first international spokes.

Correction vs prior notes: **`ph-deped` (Philippines) is NOT in the DB.** Non-US math
systems also include br-bncc, cl-mineduc, co-men, cz-msmt, es-lomloe, fi-oph, it-miur,
ke-kicd, kr-ncf, mx-*, na-nied, ng-nerdc, pe-minedu, pt-dge, tz-tie, ug-ncdc, uy-anep,
zm-cdc, zw-zimsec (plus the ones already tracked).

## Recommended first 3

1. **England (`uk-nc`) — Science + English.** Best value. Clean GOV.UK HTML, **Open
   Government Licence v3.0** (confirmed on both pages), both hub subjects at once, easiest
   ELA mapping of any candidate. ~250–400 statements/subject.
   - Science: https://www.gov.uk/government/publications/national-curriculum-in-england-science-programmes-of-study/national-curriculum-in-england-science-programmes-of-study
   - English: https://www.gov.uk/government/publications/national-curriculum-in-england-english-programmes-of-study/national-curriculum-in-england-english-programmes-of-study
2. **Australia (`au-acara`) — Science + English via MRAC.** Machine-readable RDF/JSON-LD,
   **CC BY 4.0**, near-zero extraction cost. ~100–150 content descriptions/subject F–10.
   - https://www.australiancurriculum.edu.au/machine-readable-australian-curriculum
   (confirm CC BY on the download T&Cs before ingest — low risk)
3. **Singapore (`sg-moe`) — Science** (EL as stretch). Proven fetcher pattern (math already
   uses this site). © MOE, unstated reuse — same posture as ingested sg-moe math.
   - Primary Science 2023: https://www.moe.gov.sg/-/media/files/primary/syllabus/primary-science-syllabus-2023_may24.pdf
   - Lower Sec Science 2021: https://www.moe.gov.sg/-/media/files/secondary/fsbb/syllabus/2021-g2g3-lower-secondary-science-syllabus-updated-apr-2024.pdf

**#4 = Ontario** (`ca-on`, Science&Tech 2022 + Language 2023) — reuses the existing
dcp.edu.gov.on.ca fetcher; JS-heavy but solved in-repo.

Together the first 3 add ~600–1,000 standards, all English, 2 of 3 openly licensed, and
give NGSS its first 3 international spokes + CCSS-ELA its first 2.

## Tier 2 (usable, one friction each)

- **Scotland** (`gb-sco`) — OGL, PDFs verified; Es&Os are broad 5-level first-person
  statements, worst NGSS/CCSS-ELA structural fit — ingest Benchmarks for granularity.
- **Hong Kong** (`hk-edb`) — English PDFs verified; mid-transition (new JS science phases
  in 2027/28 — pick a version), prose-heavy extraction.
- **Ireland** (`ie-ncca`) — Irish PSI licence (CC BY compatible), clean; only ~46 outcomes
  (low effort, low payoff).
- **Ghana** (`gh-nacca`) — direct PDFs, indicator-level granularity is NGSS-friendly; strong
  Africa-expansion continuity after v1.3.0. Terms unstated.
- **South Africa** (`za-caps`) — CAPS PDFs use custom font encodings → mojibake; needs the
  OCR/LLM extraction path (za-caps math proves it's doable).

## Tier 3 — skip for now

- **New Zealand** (`nz-moe`) — mid-rewrite; English final (eff. 2026) but Science still
  draft (eff. 2027). Revisit early 2027, then it's Tier 1.
- **Japan** (`jp-mext`) — English Course-of-Study translations "provisional," scattered,
  prose. No single official English science PDF verifiable.
- **IB / Cambridge** — subject guides login-gated, restrictive copyright; MYP objectives are
  assessment criteria not content standards (poor NGSS fit).
- **India** (`in-ncert`) — textbook/chapter organized, coarse learning-outcome docs, NCF 2023
  restructuring in flight.
- **Rwanda** (`rw-reb`) — CBC syllabi exist but site intermittently down, large scanned PDFs
  (unverified this pass).

## Honest unknowns

ACARA MRAC per-file licence text (CC BY sitewide but not restated at the endpoint); whether
MOE Singapore © permits redistribution in the HuggingFace-hosted DB (same exposure already
exists for math); Rwanda doc reachability; NZ science timing. No URLs invented — each came
from the issuing body's domain; England, ACARA, Ontario, and Scotland were fetched directly.
