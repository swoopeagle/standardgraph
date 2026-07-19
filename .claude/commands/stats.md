Refresh (or audit) every published fact and figure across BOTH public surfaces — the
StandardGraph GitHub repo and the walkmakewalk portfolio — so they match the live database.

## 1. Gather the authoritative numbers

```bash
python3 - <<'PY'
import sqlite3, os
c=sqlite3.connect(os.path.expanduser("~/.standardgraph/common_core.db"))
def q(s): return c.execute(s).fetchone()[0]
std   = q("SELECT COUNT(*) FROM standards")
sysN  = q("SELECT COUNT(DISTINCT system) FROM standards")
xw    = q("SELECT COUNT(*) FROM crosswalk_mappings")
scored= q("SELECT COUNT(*) FROM crosswalk_mappings WHERE notes LIKE '%[LLM score%'")
flagged=q("SELECT COUNT(*) FROM crosswalk_mappings WHERE flagged_for_review=1")
direct= q("SELECT COUNT(*) FROM crosswalk_mappings WHERE notes LIKE '%direct_family%'")
rel   = q("SELECT COUNT(*) FROM standard_relationships")
subj  = q("SELECT COUNT(DISTINCT subject) FROM standards")
size  = os.path.getsize(os.path.expanduser("~/.standardgraph/common_core.db"))/1073741824
print(f"standards      = {std:,}      (display as '{std//1000}k+' or exact)")
print(f"systems        = {sysN}")
print(f"subjects       = {subj}")
print(f"crosswalks     = {xw:,}")
print(f"scored         = {scored:,}   ({100*scored/xw:.0f}% of crosswalks)")
print(f"flagged        = {flagged:,}")
print(f"direct_family  = {direct:,}")
print(f"relationships  = {rel:,}      (display as '{rel/1e6:.1f}M')")
print(f"db_size_gb     = {size:.2f}   (display as '~{size:.1f} GB')")
# per-region coverage counts used on the landing-page cards
for label, clause in [("US","system IN ('ccss','ccss-ela','ngss','c3','csta') OR system GLOB '[a-z][a-z]' OR system LIKE '%-sci' OR system LIKE '%-ela' OR system LIKE '%-ss' OR system LIKE '%-cs' OR system LIKE 'ap-%'"),
                       ("Canada","system LIKE 'ca-%'"),("UK","system IN ('uk-nc','uk-aqa','gb-sco')")]:
    print(f"coverage[{label}] = {q(f'SELECT COUNT(*) FROM standards WHERE {clause}'):,}")
c.close()
PY
```

Formatting rules:
- "N+ standards" displays round DOWN to nearest thousand (175,738 → "175,000+"). Exact stat blocks use the full number.
- DB size: one decimal GB (`~2.1 GB`).
- Relationships: one decimal million (`3.8M`).
- Scored %: whole number.

## 2. The figure inventory — check EVERY location

Do NOT grep for known old numbers (they change every release). Instead, open each file below and
check the figure in context against the authoritative value. These are the only places figures live:

**StandardGraph repo (`~/projects/standardgraph`):**
- `README.md` — hero line (standards, systems, countries); 🎯 scoring callout (crosswalks, scored %, direct_family); install blurb (DB size)
- `packages/common-core/README.md` — headline (standards, systems); scoring paragraph (crosswalks, direct_family) — **rebuild the package after editing** (`cd packages/common-core && uv build`), it ships in the wheel
- `docs/index.html` — `<meta description>`; hero `<p>`; the 4 stat tiles (standards / systems / crosswalks / relationships); scoring callout; coverage cards (US / Canada / UK counts)
- `docs/install.md` — DB size (2 places)
- `docs/quickstart.md` — standards, systems (2 places)
- `CLAUDE.md` — "Key facts" block (standards, systems, crosswalks, scored, flagged, direct_family, relationships, DB size)
- Do NOT edit `CHANGELOG.md` past releases or the concept-map viz numbers in walkmakewalk (449 concepts / 2,016 links / 46 systems describe a fixed artifact, not the live graph).

**walkmakewalk portfolio (`~/projects/walkmakewalk`) — separate repo, deploys via Vercel on push:**
- `index.html` — StandardGraph project card (standards)
- `work.html` — StandardGraph project card (standards)
- `work/standardgraph.html` — lede (standards, systems); overview paragraph (crosswalks, scored, direct_family); install (DB size)

(Sanity-check the inventory is still complete: `grep -rnoE "[0-9]{2,3},[0-9]{3}" README.md docs/*.html docs/*.md CLAUDE.md packages/common-core/README.md` in each repo, and confirm every hit is a known location. Ignore font-weight values like `144,500` in Google Fonts URLs.)

## 3. Report and fix

Produce a drift table: `file:line · stated · actual · fix`. Then:
- If auditing only: report ✓/✗ and stop.
- If fixing: apply edits in both repos. Commit each repo separately (author `swoopeagle`), and push.
  Pushing walkmakewalk triggers a Vercel redeploy of the public site. If `packages/common-core/README.md`
  changed and a release is in flight, rebuild the wheel so the corrected README ships.
- After pushing walkmakewalk, verify the live site picked it up:
  `curl -s https://walkmakewalk.com/work/standardgraph.html | grep -o "[0-9]\{3\},[0-9]\{3\}"`.

Never touch tokens here; this skill only edits/commits/pushes text.
