# StandardGraph — Coverage Gaps & Roadmap

Tracking of curriculum systems that are missing, partial, or identified but not yet attempted.
Updated: 2026-06-05

---

## Partially covered (in DB, incomplete)

| System | What's in DB | What's missing | Blocker |
|---|---|---|---|
| `jp-mext` | Elementary Gr 1–6 (76 standards) | Junior High Gr 7–9, Senior High Gr 10–12 | English PDF not found in MEXT 1303755_XXX series; try CRICED or ResearchGate |
| `nz-moe` | Years 0–10 (4 phases, 2025 doc) | Years 11–13 (NCEA Level 1–3) | Different document format; NCEA has achievement standards per topic |
| `hk-edb` | KS1–KS3 (Gr 1–9) | Senior Secondary KS4 (Gr 10–12 / DSE) | Separate PDF for senior secondary curriculum |
| `gb-sco` | CfE early–fourth level | Senior Phase (S4–S6 / Highers) | Separate Higher/Advanced Higher documents |
| `sg-moe` | Primary P1–6, Secondary G1–G3, NT | Additional Maths (A-Math), Further Maths, JC H1/H2 | Separate syllabuses per track on MOE website |

---

## Attempted but failed

| System | Attempted | Reason | Next step |
|---|---|---|---|
| Kenya KICD | fetch_kenya.py (not written — URLs tested) | All PDF URLs return 404; KICD site restructured | Try kicd.ac.ke directly in browser; look for "CBC Mathematics" |
| Japan secondary MEXT | Searched MEXT English PDF series | 1303755_XXX series has Elementary only; secondary in different series | Try `https://www.mext.go.jp/en/policy/education/elsec/title02/detail02/` |

---

## Identified, not yet attempted

### High priority (English docs available, significant coverage)

| System | Country | Notes | Source |
|---|---|---|---|
| `ph-deped` | Philippines | K–12 curriculum, Most Essential Learning Competencies (MELCs) | deped.gov.ph |
| `my-kssm` | Malaysia | KSSM (Kurikulum Standard Sekolah Menengah), good English docs | moe-dl.edu.my |
| `id-kemendikbud` | Indonesia | Kurikulum Merdeka (2022), replaces K13 | kurikulum.kemdikbud.go.id |
| `vn-moet` | Vietnam | General Education Curriculum 2018 | moet.gov.vn |
| `pk-ncert` | Pakistan | National Curriculum 2006 (revised 2022) | mofept.gov.pk |
| `lk-nie` | Sri Lanka | National Curriculum (NIE), Gr 1–13 | nie.lk |
| `rw-reb` | Rwanda | Competence-Based Curriculum (CBC), English medium | reb.rw |
| `tz-necta` | Tanzania | National Curriculum Framework | necta.go.tz |
| `ng-nerdc` | Nigeria | National Curriculum for Basic Education | nerdc.gov.ng |
| `ca-qc` | Quebec, Canada | MEES Progression of Learning (English version available) | education.gouv.qc.ca |
| `ib-pyp` | IB Primary Years Programme | Covers ages 3–12, complements IB-MYP we have | ibo.org |
| `ap-cb` | AP Calculus / AP Statistics (College Board) | US college-level, widely used | apcentral.collegeboard.org |

### Medium priority (docs exist, may need translation or PDF work)

| System | Country | Notes |
|---|---|---|
| `br-bncc` | Brazil | BNCC (Base Nacional Comum Curricular) — Portuguese, but well-structured |
| `mx-sep` | Mexico | Plan y Programas de Estudio — Spanish |
| `tr-meb` | Turkey | MEB curriculum — Turkish, English summary available |
| `se-skolverket` | Sweden | Lgr22 — English translation available |
| `nl-slo` | Netherlands | SLO curriculum — partial English |
| `es-lomloe` | Spain | LOMLOE (2022) — Spanish |
| `pt-dge` | Portugal | DGE Aprendizagens Essenciais — Portuguese |
| `fr-eduscol` | France | Programmes Éduscol — French |
| `de-kmk` | Germany | KMK Bildungsstandards — German; federal structure is complex |
| `cn-pep` | China | PEP/人教版 National Standard — Chinese; no official English translation |
| `kr-kofac` | South Korea | 2022 Revised Curriculum — Korean; partial English docs |
| `fi-oph` | Finland | FNCC (2014/2023) — English translation available |

### Lower priority / niche

| System | Notes |
|---|---|
| IB CP | Career-related Programme — limited math content |
| NAEP | US national assessment framework (not a teaching curriculum) |
| Cambridge IGCSE | We have `cambridge` (CAIE) but not specifically IGCSE syllabus codes |
| Botswana BEC | English medium, similar to SA CAPS |
| Zambia CDC | English medium |
| Zimbabwe ZIMSEC | English medium |
| Uganda NCDC | English medium |
| Ethiopia MOE | English medium from Grade 5 |

---

## Notes on fetcher patterns

- **CSP API systems** (like AERO, DoDEA): zero-effort if the system is indexed at commonstandardsproject.com
- **Clean PDF + English**: ~2-4 hrs Gemma time per system (Ghana-scale = large PDF, many grades)
- **Non-English PDFs**: need translation layer before Gemma extraction — not yet implemented
- **Structured HTML**: some systems (NAEP, Philippines DepEd) publish standards as HTML tables — faster than PDF
