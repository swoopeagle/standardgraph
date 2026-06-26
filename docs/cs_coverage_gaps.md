# CS Coverage Gaps

34 of 51 US state jurisdictions have Computer Science standards in CSP.
The 17 missing states are categorized below after investigation.

## Status: CSTA adopters — already covered by `csta` hub

These states adopted CSTA K-12 2017 verbatim. No separate ingestion needed
since the `csta` hub crosswalk already covers them.

AK, AZ, CT, DC, DE, HI, ME, MN (integrated into broader standards), MT,
NM (adopted CSTA wholesale), RI, SD, VT, WY

## Status: PDF ingestion candidates

| State | Notes | PDF URL | Status |
|---|---|---|---|
| NH | NH-specific CS framework (2018) | education.nh.gov | 403 blocked — requires manual download |
| WI | Wisconsin-specific CS standards (2025) | dpi.wi.gov | 404 — URL moved |
| PA | Business, Computer & IT Standards (BCIT) | pdesas.org/BCIT_standards.pdf | Available but likely vocational; evaluate before ingesting |
| IA | Iowa Core Technology Literacy — overlaps CS | — | Framed as tech integration, not discrete CS |

## Next steps

- NH/WI: manually download PDFs and drop into `data/raw/cs_states_pdf/`; then
  write `fetch_cs_states_pdf.py` using the AP Science page-by-page Gemma pattern.
- PA BCIT: review PDF content before committing to ingestion — may duplicate CSTA.
