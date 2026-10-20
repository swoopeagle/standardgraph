# World-coverage candidates (math, missing countries)

_2026-10-19. Pupils = primary + secondary enrollment, World Bank WDI / UNESCO UIS, `data/world_enrollment.csv`.
Lift = official source reachable and machine-readable x licence permits redistribution. Licensing is non-negotiable:
unclear terms = BLOCKED, not ingested. Every URL below was fetched in this session unless marked **unverified**.
Research was done from a US network; "unreachable" means unreachable from here, not nonexistent._

## Ranked list (pupils x lift)

| # | Country | Pupils | Source status | Licence basis | Verdict |
|---|---|---:|---|---|---|
| 1 | **France** | 10.4M | 4 BO annex PDFs on education.gouv.fr fetched; text layer, ~38/28/20/16 pp | Etalab-2.0 stated on eduscol legal notice (via Wayback): "mis à disposition selon les termes de la licence etalab-2.0"; attribution required | **LOW-LIFT. Ingested (fr-men).** |
| 2 | Vietnam | 18.5M | Official copy of Toán programme (annex to Thông tư 32/2018/TT-BGDĐT) not reachable: moet.gov.vn 404s, vbpl.vn 403, thuvienphapluat is a commercial mirror | Strongest statutory basis of any country: IP Law 2005 Art. 15(2) excludes normative and administrative documents (read on a secondary site; law amended 2025, unconfirmed) | BLOCKED on source, not law. Needs a human to download the annex from congbao/vanban.chinhphu.vn. Best next target. |
| 3 | Russia | 18.4M | edsoo.ru ФРП Математика 1-4 (64 pp, text, ~100 outcomes). Official order 370 on publication.pravo.gov.ru is 312 MB / 5,683 pp, likely scanned | GK RF Art. 1259(6) excludes official documents, but the extractable edsoo copy (ISMO, not ministry) says "Все права защищены" | MEDIUM. Needs OCR of the gazette PDF or ISMO/ministry clearance. |
| 4 | Turkey | 17.8M | mufredat.meb.gov.tr 2026 TYMM math 1-4/5-8/9-12 (162/222/208 pp), text, ~367 coded outcomes (MAT.5.1.1). Best structure of all | Footer "MEB © Tüm Hakları Saklıdır"; FSEK Art. 31 covers laws, regulations, circulars, not curricula | BLOCKED (reuse unclear). Technically easiest; one MEB permission email unblocks ~370 standards. |
| 5 | China | 206.6M | moe.gov.cn compulsory 2022 math (189 pp, **image-only, needs Chinese OCR**), senior-high zip (188 pp, text) | Copyright Law Art. 5(1) excludes "documents of an administrative nature"; untested for curriculum standards; site says 版权所有 | BLOCKED pending a legal read. Single biggest lever (14.6% of world pupils). |
| 6 | Indonesia | 56.5M | kurikulum.kemdikbud.go.id / kemendikdasmen.go.id fail DNS from here; CP is prose by phase, not discrete outcomes (tens of items) | UU 28/2014 Art. 42 excludes "peraturan perundang-undangan"; curriculum not named | BLOCKED (unverified source + unclear law) |
| 7 | Pakistan | 45.1M | mofept.gov.pk SNC Mathematics 1-5 (98 pp, English, text) fetched. Grades 6+ not found federally | No licence text; Copyright Ordinance 1962 gives Govt ownership (from snippets) | BLOCKED. Silence is not a licence. Grades I-V only anyway. |
| 8 | Bangladesh | 31.8M | nctb.gov.bd up (JS CMS); no standalone math curriculum found, Bengali-first | none found | BLOCKED |
| 9 | DR Congo | 29.1M | none found | n/a | BLOCKED |
| 10 | Egypt | 27.0M | moe.gov.eg 403 | n/a | BLOCKED (unreachable) |
| 11 | Philippines | 24.9M | deped.gov.ph 403 to automated fetch (repo notes manual download needed); existing `fetch_philippines.py` | RA 8293 Sec. 176: no copyright in govt works but prior approval for "exploitation for profit"; "for profit" undefined | BLOCKED pending DepEd written OK. Cheap to unblock: fetcher exists. |
| 12 | Ethiopia | 21.0M | moe.gov.et refuses connections | n/a | BLOCKED (unreachable) |
| 13 | Iran | 15.7M | none found | n/a | BLOCKED |
| 14 | Argentina | 9.1M | NAP PDFs on backend.educ.ar (95/131/26 pp, text). `nap.educ.ar` in repo fetcher no longer resolves | educ.ar terms: free use "excepto para cualquier uso comercial" (non-commercial only) | BLOCKED |
| 15 | Thailand | 8.7M | academic.obec.go.th 403 | Copyright Act s.7 maybe; unconfirmed | BLOCKED |
| 16 | Malaysia | 5.7M | official host unreachable | "(c) Kementerian Pendidikan", written permission required | BLOCKED |
| 17 | Sri Lanka | 4.1M | nie.lk Gr 9 Maths Teacher's Guide (142 pp, English, tagged competency levels) | "(c) National Institute of Education", no reuse terms | BLOCKED. Cleanest English structure; NIE permission email would unblock. |

Not researched (no English/structured source expected or low enrollment): Algeria, Afghanistan, Nepal, Saudi Arabia, Morocco, Myanmar,
Sudan, Iraq, Uzbekistan, Ukraine, Poland, Netherlands, Sweden (Lgr22 English translation), Italy-style European countries already covered.

## Findings

- **Only France cleared both gates.** Everything else large is either all-rights-reserved or unreachable.
- The licence problem is the common cause, not extraction: Turkey, Sri Lanka, Pakistan, Argentina and (if OCRed) China have
  usable documents. A short written-permission request is the cheapest lever: Turkey (MEB), Sri Lanka (NIE), Philippines (DepEd).
- Vietnam and Russia have the best statutory footing (official normative acts excluded from copyright) but need a human to fetch the
  official copy; both are worth a counsel read if Ian wants a policy that "official normative act = redistributable".
- The repo's existing posture (e.g. Singapore MOE, Kenya, Ghana ingested with unstated or (c) terms) is looser than the bar applied here.
  Applying this bar retroactively is a separate decision for Ian.
- Existing unrun fetchers: `fetch_philippines.py` (ph-deped), `fetch_argentina.py` (ar-nap), `fetch_france.py` (fr-men; its eduscol URL is
  now Cloudflare-blocked; the new fetcher uses the education.gouv.fr annexes).
- Upper-bound effect: ingesting China alone would raise the math headline from 41.4% to 56%; Vietnam+Russia+Turkey add 3.8 points; Indonesia 4.0.
