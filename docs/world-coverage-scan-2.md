# World-coverage scan 2 (new subjects, new countries, partial systems)

_2026-10-20. Branch `more-countries`, built on `crosswalk-quality`. Pupils = primary + secondary enrollment, `data/world_enrollment.csv`.
Licence bar: ingest only if an official page states terms permitting redistribution (open government licence, CC BY / CC BY-SA / CC0,
an explicit public-domain statute that names this kind of document, or written permission). Unclear / all rights reserved / non-commercial
only = BLOCKED. "Verified" = I fetched that page myself this session and the quote is verbatim; "agent-fetched" = a research subagent fetched it
and quoted it, I did not re-fetch (treat as a lead). Sites that returned a bot challenge were left alone, not bypassed._

## Ingested (6 systems)

| # | System / subject | Pupils | Source | Licence verdict (quoted basis) | Structure / lift | Status |
|---|---|---:|---|---|---|---|
| 1 | **Spain `es-lomloe`**: science, ELA, social studies, CS, arts, languages (1,137 criteria) | 6.5M | BOE XML `https://www.boe.es/diario_boe/xml.php?id=BOE-A-2022-3296` (Primaria), `-4975` (ESO), `-5521` (Bachillerato) | CLEAN (verified). BOE aviso legal, condition 3: "Las presentes condiciones permiten la reutilización de los documentos sometidos a ellas para fines comerciales y no comerciales"; includes "La modificación, adaptación, extracción, reordenación y combinación de la información". Attribution "Fuente de los datos: Agencia Estatal Boletín Oficial del Estado"; must not distort meaning (translation labelled) | One criterio de evaluación per standard; regular XML. LOW. Claude translation | **Ingested** |
| 2 | **Poland `pl-men`**: mathematics, science (physics/chemistry/biology/nature), social studies (history/geography/civics), CS; classes IV-VIII (1,002 items) | 4.9M | Dz.U. 2026 poz. 378, `https://api.sejm.gov.pl/eli/acts/DU/2026/378/text.pdf` | CLEAN by statute (verified). Prawo autorskie Art. 4: "Nie stanowią przedmiotu prawa autorskiego: 1) akty normatywne lub ich urzędowe projekty, 2) urzędowe dokumenty, materiały, znaki i symbole". The podstawa is an annex of a ministerial regulation (legal act). Legal-judgment basis, not a licence: counsel confirmation recommended before release | Numbered requirements, text PDF, MED. Claude translation | **Ingested** |
| 3 | **Norway `no-udir`**: math, science, social studies, ELA, English/foreign languages, arts, years 1-10 (444 aims) | 0.9M | Udir Grep API `https://data.udir.no/kl06/v201906/` | CLEAN (verified). `https://www.udir.no/om-udir/data/`: "Dataene er lagt ut for viderebruk under Norsk lisens for offentlig data (NLOD). Det betyr blant annet at du har lov til å kopiere og tilgjengeliggjøre, endre ... og å benytte datasettet kommersielt." Attribution to Udir | JSON; official English text exists for all 444 aims chosen (only ~15% of all 15k aims have English). LOW. No translation | **Ingested** |
| 4 | **Australia `au-acara`**: social studies (HASS, civics, economics, geography, history), digital technologies, arts, languages (1,681) | 4.9M | ACARA curriculum workbook `https://www.australiancurriculum.edu.au/content/dam/en/curriculum/ac-version-9/downloads/curriculum-workbook.xlsx` | CLEAN (verified). `.../content/acara-curriculum/au/en/copyright-and-terms-of-use.html`: "copyright material available on this website is licensed under a Creative Commons Attribution 4.0 International (CC BY) licence ... share – copy and redistribute ... adapt ... even commercially, provided you attribute ACARA". Exceptions: logos, third-party material, National Literacy Learning Progressions (CC BY-NC; not in the workbook rows used) | One sheet, coded rows. LOW | **Ingested** |
| 5 | **England `uk-nc`**: computing, history, geography, citizenship, art, music, languages (137) | 11.3M (UK) | gov.uk content API of the programmes of study | CLEAN (verified). `https://www.gov.uk/government/collections/national-curriculum`: "All content is available under the Open Government Licence v3.0, except where otherwise stated" | HTML bullets, coarse (key-stage statements). LOW but small | **Ingested** |
| 6 | **Scotland `gb-sco`**: social studies E&Os (117) | (in UK) | Education Scotland E&O PDF `https://education.gov.scot/media/wpsnskgv/all-experiencesoutcomes18.pdf` | CLEAN (verified). `https://education.gov.scot/terms-of-use/`: "© Crown copyright 2022. You may use and re-use the information featured on this website (not including logos) free of charge in any format or medium, under the terms of the Open Government Licence." | Two-column PDF; only social studies parses reliably. Expressive arts, modern languages, technologies were tried and dropped (columns interleave) | **Ingested** (partial) |

Provenance caveat (important): the *held* au-acara math, uk-nc, au-vic etc. were pulled from `commonstandardsproject.com` (see `fetch_international.py`), not from the
official ACARA/gov.uk files, so their redistribution rights rest on the origin licence, which is clean here, but the aggregator's own terms were never checked.

Not ingested although licence-clean (cost/benefit): Netherlands kerndoelen (Besluit Stb. 2026, 198 is a legal act, Auteurswet art. 11; SLO open dataset CC BY 4.0; only Dutch + maths, ~40 goals per level), Sweden Lgr22 (Skolverket API; licence link points to CC0 but the page text itself does not say "CC0"; content is HTML bullets with no one-line outcomes), Estonia (Autoriõiguse seadus § 5 p. 3 excludes "õigusaktidele ja haldusdokumentidele"; curriculum is Government regulation no. 1; PDF layout parsing; 0.19M pupils), Denmark (Ophavsloven § 9 stk. 1, but stk. 2 carve-out and JS-only HTML; 0.95M pupils), Peru (DL 822 art. 9(b) "official texts of ... administrative character"; CNEB is an annex to RM 281-2016; 6.8M pupils, 224-page PDF, needs counsel) - all agent-fetched, none re-verified by me. These are the next candidates (Peru and Estonia/Denmark first).

## Blocked or unresolved

| System / subject | Pupils | Source status | Licence verdict | Status |
|---|---:|---|---|---|
| Wales, Curriculum for Wales (Hwb) | (in UK) | hwb.gov.wales | agent-fetched: copyright statement says content "is protected by copyrights ... and/or other intellectual property rights"; no OGL on Hwb (OGL on gov.wales only) | BLOCKED, **permission candidate** |
| British Columbia (all subjects) | 5.1M (Canada) | HTML only; JSON lists titles only; no dataset in the BC Data Catalogue | agent-fetched: "Copyright © 2026, Province of British Columbia. All rights reserved ... may not be reproduced or redistributed without the prior written permission" | BLOCKED, **permission candidate** |
| Alberta, Ontario, Quebec, Nova Scotia, Newfoundland, NWT | | Ontario: non-commercial only without change; Quebec: exclusive rights reserved; NS/NL: Crown copyright / all rights reserved; NWT non-commercial; Alberta: curriculum.learnalberta.ca 403 (CloudFront); OGL-Alberta exists but programs of study are not under it | agent-fetched quotes | BLOCKED |
| PEI, Yukon, Nunavut | | bot challenge, not bypassed | n/a | UNVERIFIED |
| Finland (ePerusteet API, ~1,285 basic-education + ~1,417 lukio aims) | 0.9M | JSON API works (I confirmed the API responds) | agent-fetched: no data licence stated on ePerusteet; EUPL covers software only; Copyright Act § 9 (no copyright in "viranomaisen ... päätöksiin") arguable but formal-act status unconfirmed | BLOCKED pending OPH confirmation, **permission candidate** |
| Czechia (RVP) | 1.5M | | no licence; Copyright Act 121/2000 § 3 a) covers "právní předpis", RVP not clearly one | BLOCKED |
| Brazil BNCC (+all subjects) | 36.6M | basenacionalcomum.mec.gov.br 403 (WAF) | Lei 9.610 art. 8 IV excludes "demais atos oficiais"; link BNCC to CNE resolution unverified | UNVERIFIED (statute route plausible) |
| Chile (curriculumnacional.cl), Colombia (MEN), Uruguay | 3.1M / 9.0M | Chile: site unreachable from here; Colombia: terms prohibit commercial use; Uruguay: no content licence | agent-fetched | UNVERIFIED / BLOCKED |
| New Zealand, Ireland (NCCA), CXC (Caribbean) | | Cloudflare / block pages | n/a | UNVERIFIED |
| France other subjects (French, sciences, history-geography) | 10.4M | Only `ensel620_annexe1.pdf` (French cycle 3, 21 pp, reachable) was found; education.gouv.fr legal notice, eduscol and BO pages return Cloudflare 403, so other annex URLs cannot be discovered and the Etalab notice cannot be re-fetched | Etalab 2.0 per the earlier pass (not re-verified here) | UNVERIFIED |
| Rwanda REB other subjects | 3.9M | reb.gov.rw loads | no licence found | BLOCKED (no licence), contact `info@reb.rw` |
| African held systems (ke-kicd, ug-ncdc, ng-nerdc ...) | | | footers: Kenya "All Rights Reserved", Uganda "All rights reserved", Nigeria "All rights reserved" (agent-fetched). These are already ingested | **Retroactive licence problem** (see Needs Ian) |
| Algeria, Afghanistan, Myanmar | 11.4M / 10.9M / 9.5M | | all-rights-reserved footers (agent-fetched) | BLOCKED |
| Saudi Arabia, Uzbekistan | 6.8M / 7.8M | sites load, no licence text | none found | BLOCKED (no licence) |
| Morocco, Iraq, Nepal, Sudan, Botswana, Ukraine | 8.2M / 6.9M / 7.2M / 7.5M / / 4.0M | unreachable or gateway blocked from here | n/a | UNVERIFIED (retry from another network) |

## Permission-email candidates (verified official address)

1. **British Columbia**: `QPIPPCopyright@gov.bc.ca` (on the Province's copyright page, fetched). Largest well-structured open ask in Canada; request OGL-BC or written reuse permission for the BC curriculum.
2. **Wales / Hwb**: `support@hwbcymru.net` (Hwb contact page, fetched; this is the platform help desk, ask it to route to the Curriculum for Wales owner). The gov.wales copyright page lists only `brandingqueries@gov.wales`, which is for branding, so do not use that.
3. **Rwanda REB**: `info@reb.rw` (REB home page, fetched). Held rw-reb math has no stated licence; ask for terms for all syllabi.
4. **Finland OPH**: no email address could be verified (oph.fi contact pages returned no address or 404/403); use the contact form linked from `https://www.oph.fi/fi/yhteystiedot`. One line: "is the ePerusteet data CC BY 4.0 / may we redistribute?".
No verified addresses were found for Turkey (MEB), Sri Lanka (NIE) or Philippines (DepEd) from the previous pass; those remain the top permission asks by pupils but need an address first.

## Numbers

World K-12 pupils with at least one subject covered (coverage_report.py): before -> after (scan DB, 313 systems, 180,954 standards):
math 42.1% -> 42.5% (34 -> 36 countries: Norway, Poland); science 13.5% -> 14.4% (15 -> 18); ELA 13.5% -> 14.0% (15 -> 17); social studies 4.4% -> 6.4% (2 -> 7); CS 3.5% -> 5.4% (1 -> 5); arts 3.5% -> 5.1% (1 -> 5); world languages 3.5% -> 5.1% (1 -> 5).

Crosswalks for the 1,054 new links: scored 1-5 by sonnet subagents (1:11+11, 2:106+85, 3:223+218, 4:171+186, 5:17+26; 213 scored <=2 and flagged), then the 0.75 cosine floor flagged 506 more. Surviving unflagged links are low (e.g. es-lomloe science 11 of 238, au-acara cs 4 of 73, pl-men math 73 of 154, no-udir math 34 of 101): national "competency" statements rarely align 1:1 with US hub standards. Hub unflagged coverage: math 55.8% -> 55.7%, science 39.8% -> 39.2%, ELA 58.2% -> 58.0%, social studies 14.4% -> 14.3%, CS 19.6% -> 17.3%. Arts and world languages have no hub, so those 3,000+ standards are searchable but have no crosswalk. Translations (Spain 1,137, Poland 1,002) are unreviewed Claude translations; Poland scoring judged only the first ~230 characters of long items.
