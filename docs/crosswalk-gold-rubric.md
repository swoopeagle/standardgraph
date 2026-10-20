# Crosswalk gold-set rubric (v2)

Task: given a source standard (from some curriculum) and a target standard (from the subject hub:
CCSS math, NGSS, CCSS-ELA, C3, CSTA), judge whether the link is a usable crosswalk: would a student
who met the source be assumed to have (substantially) met the target?

Labelers see ONLY: subject, system ids, grades, domains and standard text. No similarity or quality
score, no grade delta, no prior label.

| Label | Meaning | Test |
|---|---|---|
| **exact** (Y) | Same learning objective at essentially the same level | Same skill/concept, same task type, same depth. Wording, examples, or a small scope difference are fine. A teacher would say "these are the same standard". |
| **partial** (P) | Real overlap but not the same standard | One is a clear subset/superset of the other; or same topic but different depth/task type; or same skill at a grade gap of 2+ years; or same skill but one adds a major extra requirement. "Related; one partly covers the other". |
| **wrong** (N) | No usable skill match | Shares vocabulary or a broad topic ("fractions", "data") but the skill taught/assessed differs; different concept; different strand. "No, different things". |

Rules of thumb
- Judge the skill, not shared words. Same topic word with a different skill is **wrong**.
- Do not penalise a 1-year grade gap between systems (curricula sequence differently); a gap of 2+ years on the same skill is at best **partial**.
- A vague/broad source against one specific case of it is **partial**.
- Texts may be machine translations; judge intended meaning.
- Torn between two labels: pick the stricter one is NOT the rule; pick the one a careful teacher would defend, and if still torn choose the lower (exact > partial > wrong).
- Lenient precision = exact+partial; strict precision = exact only.

Protocol: two independent labelers (separate Claude sonnet subagents given only this rubric and the blind
file); disagreements go to a third adjudicator subagent that sees the two labels and reasons; Cohen's kappa
is reported on the two independent labels (3-class, and strict-binary exact vs not).
