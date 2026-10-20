# Curriculum permission requests, batch 2: British Columbia, Rwanda, Wales, Finland

_Drafted 2026-10-20. Not sent. Ian reviews, edits, sends from his own account._

Source for the licence findings and addresses: `docs/world-coverage-scan-2.md` on branch
`more-countries`. Batch 1 (Turkey, Philippines) is `2026-10-19-curriculum-permission-emails.md`.

**Three of these four are already in the published database without clear terms.** BC math
(`ca-bc`, 168 standards), Finland math (`fi-oph`, 46) and Rwanda math (`rw-reb`, 151) were
ingested before the licence bar existed and ship today on PyPI/HuggingFace and the hosted
server. The drafts say so plainly and offer to remove them. Do not send a version that hides
this: if they later find their content already published, an ask that pretended otherwise
loses the relationship. Decide before sending whether to pull these three from the next
release while waiting for answers (recommended: yes, it costs ~365 standards).

| # | Who | Address | Verified from | Today |
|---|---|---|---|---|
| 1 | British Columbia, Province copyright office | `QPIPPCopyright@gov.bc.ca` | Province of BC copyright page | Math held; "All rights reserved ... prior written permission" |
| 2 | Rwanda Basic Education Board | `info@reb.rw` | REB home page | Math held; no licence stated |
| 3 | Wales, Curriculum for Wales (Hwb) | `support@hwbcymru.net` | Hwb contact page (help desk; asks to be routed) | Not held; Hwb is not under OGL |
| 4 | Finland, Finnish National Agency for Education (OPH) | contact form at https://www.oph.fi/fi/yhteystiedot | no email could be verified | Math held; ePerusteet states no data licence |

Before sending:
- [ ] Same check as batch 1: the "free, MIT, no paid access" line must still be true.
- [ ] Decide whether to pull `ca-bc`, `fi-oph`, `rw-reb` from the next release while waiting.
- [ ] Which account to send from. Log each in the CRM as `email_sent`.

---

## 1. British Columbia: to QPIPPCopyright@gov.bc.ca

**Subject:** Permission request: B.C. curriculum learning standards in a free, open curriculum database

Hello,

My name is Ian Wang. I maintain StandardGraph, a free and open-source database that lines up
school curriculum standards across countries. It holds about 180,000 standards from more than
300 curriculum systems and shows which standard in one system matches a standard in another.
Teachers and curriculum teams use it to compare systems and align materials.

I am writing about the B.C. curriculum learning standards published on curriculum.gov.bc.ca.
The site says the content may not be reproduced or redistributed without prior written
permission, so I am asking for that permission.

I should also tell you up front: an earlier version of StandardGraph already includes 168 B.C.
Mathematics learning standards, added before I put a licence check in place. If you would
rather they not be included, I will remove them in the next release. If you are open to it,
I would like to:

1. keep the Mathematics standards, and add the curricular competencies and content standards
   for Science, English Language Arts, Social Studies and Applied Design, Skills and
   Technologies;
2. use only the standard text and its grade and area of learning, not the full curriculum
   pages; and
3. credit the Province of British Columbia on every record, in whatever wording you prefer.

The project is free to use, released under the MIT license, and does not charge for access. If
B.C. offers this content under the Open Government Licence - British Columbia, a pointer to
that would answer the question just as well.

Thank you for your time.

Ian Wang
StandardGraph
https://walkmakewalk.com/standardgraph.html

---

## 2. Rwanda: to info@reb.rw

**Subject:** Permission request: Rwanda Competence-Based Curriculum in a free, open curriculum database

Dear Rwanda Basic Education Board,

My name is Ian Wang. I maintain StandardGraph, a free and open-source database that lines up
school curriculum standards across countries. It holds about 180,000 standards from more than
300 curriculum systems and shows which learning outcome in one country matches an outcome in
another. Teachers and curriculum teams use it to compare systems and align materials.

StandardGraph already includes 151 learning outcomes from Rwanda's Competence-Based Curriculum
for Mathematics. I added them before I began checking reuse terms, and I could not find a stated
licence for the syllabi on reb.rw. I would like to ask properly:

1. May StandardGraph include and redistribute the learning outcomes (the outcome text, grade
   and unit only, not the full syllabus documents) from the Mathematics syllabi, and also from
   Science, English and Social Studies?
2. What credit would you like on each record?

If you would rather the Mathematics outcomes not be included, I will remove them in the next
release.

The project is free to use, released under the MIT license, and does not charge for access. If
you agree, Rwanda's curriculum would be mapped to curricula in Kenya, Ghana, South Africa, the
United States, the United Kingdom and others, and I am glad to share those mappings with your
team.

If another office handles these requests, I would be grateful if you could forward this.

Thank you for your time.

Ian Wang
StandardGraph
https://walkmakewalk.com/standardgraph.html

---

## 3. Wales: to support@hwbcymru.net

**Subject:** Please route: permission request for Curriculum for Wales content in a free, open curriculum database

Hello,

I know this address is the Hwb help desk. Could you please pass this to whoever handles reuse
of Curriculum for Wales content? Thank you.

My name is Ian Wang. I maintain StandardGraph, a free and open-source database that lines up
school curriculum standards across countries. It holds about 180,000 standards from more than
300 curriculum systems, including the national curricula of England and Scotland under the Open
Government Licence, and shows which standard in one system matches a standard in another.

I would like to include the Curriculum for Wales descriptions of learning (by Area of Learning
and Experience and progression step). The Hwb copyright statement says the content is
protected, and I could not find it under the Open Government Licence the way gov.wales content
is, so I am asking before using it:

1. May StandardGraph include and redistribute the descriptions of learning (the text, Area and
   progression step only) as part of its open dataset?
2. If so, under what terms and with what credit? If the Open Government Licence applies, a
   pointer to that would answer it.

The project is free to use, released under the MIT license, and does not charge for access.
Wales would sit next to England and Scotland, mapped to each other and to curricula in other
countries, and I am glad to share those mappings.

Thank you for your time.

Ian Wang
StandardGraph
https://walkmakewalk.com/standardgraph.html

---

## 4. Finland: via the contact form at https://www.oph.fi/fi/yhteystiedot

(The form has a length limit on some fields; this version is short on purpose. English is fine
for OPH.)

**Subject:** Licence for ePerusteet curriculum data (perusopetus, lukio)

Hello,

My name is Ian Wang. I maintain StandardGraph, a free and open-source database (MIT license,
no paid access) that lines up school curriculum standards across about 300 systems worldwide.

I would like to use the objectives from the national core curricula published through
ePerusteet (basic education and general upper secondary). The API is excellent, but I could not
find a data licence for the content; the EUPL appears to cover the software only.

1. Is the ePerusteet curriculum content available under an open licence (for example CC BY 4.0)?
   If not, may StandardGraph include and redistribute the objectives, with credit to the
   Finnish National Agency for Education?
2. StandardGraph already includes 46 Finnish Mathematics objectives, added before I began
   checking terms. If you would rather they not be included, I will remove them.

Thank you.

Ian Wang
StandardGraph
https://walkmakewalk.com/standardgraph.html
