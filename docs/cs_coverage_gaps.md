# CS Coverage Gaps

34 of 51 US state jurisdictions have Computer Science standards in CSP.
The 17 missing states are listed below with notes on what exists and a fill-in path.

## Missing States (17)

| State | Notes | Fill-in path |
|---|---|---|
| Alaska | No standalone CS standards; likely CSTA adopter | Mark as CSTA-aligned |
| Connecticut | Has CT CS standards (2019) — not submitted to CSP | PDF ingestion from ct.gov |
| Delaware | No standalone CS standards | Mark as CSTA-aligned |
| District of Columbia | Uses CSTA directly | Mark as CSTA-aligned |
| Hawaii | No standalone CS standards | Mark as CSTA-aligned |
| Iowa | Has Iowa Core Tech Lit — overlaps CS | PDF ingestion |
| Maine | No standalone CS standards | Mark as CSTA-aligned |
| Minnesota | Has MN CS standards (2019) — not in CSP | PDF ingestion from education.mn.gov |
| Montana | No standalone CS standards | Mark as CSTA-aligned |
| New Hampshire | Has NH CS standards — not in CSP | PDF ingestion |
| New Mexico | Has NM CS standards (2021) — not in CSP | PDF ingestion |
| Pennsylvania | Has PA CS standards (2022) — not in CSP | PDF ingestion from pdesas.org |
| Rhode Island | No standalone CS standards | Mark as CSTA-aligned |
| South Dakota | No standalone CS standards | Mark as CSTA-aligned |
| Vermont | No standalone CS standards | Mark as CSTA-aligned |
| Wisconsin | Has WI CS standards (2022) — not in CSP | PDF ingestion |
| Wyoming | No standalone CS standards | Mark as CSTA-aligned |

## Fill-in Plan

### Phase 1 — Mark CSTA-aligned states
States with no separate CS standards (AK, DE, HI, ME, MT, RI, SD, VT, WY, DC)
effectively use CSTA. These don't need a separate system entry — the CSTA hub
crosswalk already covers them. Add a note in the server instructions.

### Phase 2 — PDF ingestion for states with standalone standards
States with published CS standards not yet in CSP (CT, IA, MN, NH, NM, PA, WI):

- CT: Connecticut K-12 CS Standards (2019)
- MN: Minnesota Academic Standards — Computer Science (2019)
- NH: New Hampshire K-12 CS Curriculum Framework
- NM: New Mexico CS Standards (2021)
- PA: Pennsylvania CS and IT Standards (2022)
- WI: Wisconsin CS Standards (2022)

Use Gemma PDF extraction (same approach as AP Science and international curricula).
Add a `fetch_cs_states_pdf.py` fetcher targeting each state's DOE website.

### Phase 3 — Iowa
Iowa Core Technology Literacy standards partially overlap CS but are framed as
technology integration, not discrete CS. Evaluate whether to ingest as `ia-cs`
or leave out as too distinct from CSTA.
