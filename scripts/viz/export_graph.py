#!/usr/bin/env python3
"""Generate a self-contained interactive visualization of the LLM-validated
CCSS-math prerequisite graph — a shippable single HTML file (like Marble's
curriculum-viz, but interactive).

Grade-layered layout (K -> HS, left to right), nodes coloured by the six
top-level CCSS conceptual categories, HARD edges solid / SOFT toggleable,
cross-domain edges highlighted (our differentiator). Hover a node for its text;
click a node to light up its full prerequisite path (the get_learning_path story).

    uv run python scripts/viz/export_graph.py [db] [out.html]

Data is baked into the HTML so the file is portable (email/host a single file).
"""
import json
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "data/common_core.db"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/viz/prereq_graph.html"

GRADES = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]

# Fine CCSS domain -> top-level conceptual category (for colour + legend).
CATEGORY = {
    # Number & Quantity
    "Counting and Cardinality": "Number & Quantity",
    "Number and Operations in Base Ten": "Number & Quantity",
    "Number and Operations (Fractions)": "Number & Quantity",
    "The Number System": "Number & Quantity",
    "The Real Number System": "Number & Quantity",
    "The Complex Number System": "Number & Quantity",
    "Quantities": "Number & Quantity",
    # Ratios & Proportions
    "Ratios and Proportional Relationships": "Ratios & Proportions",
    # Algebra
    "Operations & Algebraic Thinking": "Algebra",
    "Expressions and Equations": "Algebra",
    "Seeing Structure in Expressions": "Algebra",
    "Arithmetic with Polynomials and Rational Expressions": "Algebra",
    "Creating Equations": "Algebra",
    "Reasoning with Equations and Inequalities": "Algebra",
    # Functions
    "Functions": "Functions",
    "Interpreting Functions": "Functions",
    "Building Functions": "Functions",
    "Linear, Quadratic, and Exponential Functions": "Functions",
    "Linear, Quadratic, and Exponential Models": "Functions",
    "Trigonometric Functions": "Functions",
    # Geometry
    "Geometry": "Geometry",
    "Measurement & Data": "Geometry",
    "Congruence": "Geometry",
    "Similarity, Right Triangles, and Trigonometry": "Geometry",
    "Circles": "Geometry",
    "Expressing Geometric Properties with Equations": "Geometry",
    "Geometric Measurement and Dimension": "Geometry",
    "Modeling with Geometry": "Geometry",
    # Statistics & Probability
    "Statistics and Probability": "Statistics & Probability",
    "Interpreting Categorical and Quantitative Data": "Statistics & Probability",
    "Interpreting categorical and quantitative data": "Statistics & Probability",
    "Making Inferences and Justifying Conclusions": "Statistics & Probability",
    "Conditional Probability and the Rules of Probability": "Statistics & Probability",
}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # nodes: any standard touched by a validated edge
    node_ids = [r[0] for r in con.execute(
        "SELECT DISTINCT id FROM (SELECT source_id id FROM standard_relationships WHERE method='llm_validated' "
        "UNION SELECT target_id FROM standard_relationships WHERE method='llm_validated')").fetchall()]
    nodes = []
    for nid in node_ids:
        r = con.execute("SELECT id, grade, domain, standard_text FROM standards WHERE id=?", (nid,)).fetchone()
        if not r:
            continue
        cat = CATEGORY.get(r["domain"], "Other")
        nodes.append({
            "id": r["id"],
            "label": r["id"].replace("CCSS.MATH.", ""),
            "grade": r["grade"],
            "domain": r["domain"],
            "cat": cat,
            "text": (r["standard_text"] or "")[:280],
        })

    # edges: validated prerequisites (learner=source, prereq=target)
    dom = {n["id"]: n["domain"] for n in nodes}
    edges = []
    for s, t, c in con.execute(
        "SELECT source_id, target_id, confidence_score FROM standard_relationships "
        "WHERE method='llm_validated' AND relationship='prerequisite'").fetchall():
        if s not in dom or t not in dom:
            continue
        edges.append({
            "learner": s, "prereq": t,
            "strength": "hard" if (c or 0) >= 0.9 else "soft",
            "xdom": dom[s] != dom[t],
        })
    con.close()

    n_hard = sum(1 for e in edges if e["strength"] == "hard")
    n_xdom_hard = sum(1 for e in edges if e["strength"] == "hard" and e["xdom"])
    stats = {
        "nodes": len(nodes), "hard": n_hard, "soft": len(edges) - n_hard,
        "xdom_hard_pct": round(100 * n_xdom_hard / n_hard, 1) if n_hard else 0,
    }
    payload = {"grades": GRADES, "nodes": nodes, "edges": edges, "stats": stats}

    import os
    # Vendor D3 inline so the file is fully offline-portable (no CDN dependency —
    # safe for a roadshow venue with flaky/no wifi).
    d3_path = os.path.join(os.path.dirname(__file__), "vendor", "d3.v7.min.js")
    d3_src = open(d3_path).read() if os.path.exists(d3_path) else ""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    html = HTML.replace("__DATA__", json.dumps(payload))
    if d3_src:
        html = html.replace('<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>',
                            "<script>" + d3_src + "</script>")
    with open(OUT, "w") as f:
        f.write(html)
    print(f"wrote {OUT}  ({stats['nodes']} nodes, {stats['hard']} hard / {stats['soft']} soft edges, "
          f"{stats['xdom_hard_pct']}% of hard edges cross-domain)")


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>StandardGraph — CCSS-Math Prerequisite Graph</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
  :root{--bg:#0d1117;--panel:#161b22;--fg:#e6edf3;--muted:#8b949e;--line:#30363d}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif}
  header{padding:16px 20px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:18px;font-weight:650}
  .sub{color:var(--muted);font-size:13px;margin-top:3px}
  .bar{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:10px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
  .legend{display:flex;gap:14px;flex-wrap:wrap}
  .lg{display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;opacity:.95}
  .sw{width:11px;height:11px;border-radius:3px}
  label.ctl{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);cursor:pointer}
  #wrap{position:relative;overflow:auto;height:calc(100vh - 128px)}
  svg{display:block}
  .glabel{fill:var(--muted);font-size:12px;font-weight:600;text-anchor:middle}
  .node circle{stroke:#0d1117;stroke-width:1px;cursor:pointer}
  .node text{fill:var(--fg);font-size:9px;pointer-events:none}
  .edge{fill:none}
  #tip{position:fixed;pointer-events:none;background:#1c2333;border:1px solid var(--line);
       border-radius:8px;padding:9px 11px;max-width:340px;font-size:12px;opacity:0;transition:opacity .1s;z-index:9}
  #tip .id{font-weight:700;color:#79c0ff}
  #tip .dm{color:var(--muted);margin:2px 0 5px}
  .hint{color:var(--muted);font-size:12px;margin-left:auto}
</style></head>
<body>
<header>
  <h1>StandardGraph — CCSS Mathematics Prerequisite Graph</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="bar">
  <div class="legend" id="legend"></div>
  <label class="ctl"><input type="checkbox" id="soft"/> show soft (background) edges</label>
  <label class="ctl"><input type="checkbox" id="xdom" checked/> highlight cross-domain</label>
  <span class="hint">hover a standard for its text · click to trace its full learning path · click empty space to reset</span>
</div>
<div id="wrap"><svg id="svg"></svg></div>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const CATS = ["Number & Quantity","Ratios & Proportions","Algebra","Functions","Geometry","Statistics & Probability","Other"];
const COLOR = {"Number & Quantity":"#58a6ff","Ratios & Proportions":"#d2a8ff","Algebra":"#7ee787",
  "Functions":"#ffa657","Geometry":"#ff7b72","Statistics & Probability":"#f2cc60","Other":"#8b949e"};
const {grades,nodes,edges,stats}=DATA;
document.getElementById('sub').textContent =
  `${stats.nodes} standards · ${stats.hard} hard + ${stats.soft} soft prerequisites · ${stats.xdom_hard_pct}% of hard edges are cross-domain — links the grade heuristic can't make`;

// layout: columns by grade; within a column sort by category then id
const COLW=150, PADX=70, PADY=46, ROWH=22, R=6;
const byId=new Map(nodes.map(n=>[n.id,n]));
const cols=grades.map(()=>[]);
nodes.forEach(n=>{const gi=grades.indexOf(n.grade); if(gi>=0) cols[gi].push(n);});
cols.forEach(col=>col.sort((a,b)=> CATS.indexOf(a.cat)-CATS.indexOf(b.cat) || a.id.localeCompare(b.id)));
cols.forEach((col,gi)=>col.forEach((n,i)=>{ n.x=PADX+gi*COLW; n.y=PADY+i*ROWH; }));
const maxRows=Math.max(...cols.map(c=>c.length));
const W=PADX*2+(grades.length-1)*COLW+60, H=PADY+maxRows*ROWH+30;

const svg=d3.select('#svg').attr('width',W).attr('height',H);
// grade column headers
svg.selectAll('.glabel').data(grades).join('text').attr('class','glabel')
   .attr('x',(d,i)=>PADX+i*COLW).attr('y',22).text(d=>'Grade '+d);

// adjacency for path tracing (learner -> its prereqs)
const pre=new Map(); edges.forEach(e=>{ if(!pre.has(e.learner))pre.set(e.learner,[]); pre.get(e.learner).push(e); });
function ancestors(id){const showSoft=document.getElementById('soft').checked;const seen=new Set(),st=[id];
  while(st.length){const c=st.pop();(pre.get(c)||[]).forEach(e=>{ if(!showSoft&&e.strength!=='hard')return;
    if(!seen.has(e.prereq)){seen.add(e.prereq);st.push(e.prereq);}});} return seen;}

const link=d3.linkHorizontal().x(d=>d.x).y(d=>d.y);
const gE=svg.append('g'), gN=svg.append('g');

function draw(){
  const showSoft=document.getElementById('soft').checked;
  const hlX=document.getElementById('xdom').checked;
  const shown=edges.filter(e=>showSoft||e.strength==='hard');
  gE.selectAll('path').data(shown).join('path').attr('class','edge')
    .attr('d',e=>link({source:byId.get(e.prereq),target:byId.get(e.learner)}))
    .attr('stroke',e=> (hlX&&e.xdom)?'#ff9e64':'#3d444d')
    .attr('stroke-width',e=> (hlX&&e.xdom)?1.3:0.8)
    .attr('stroke-opacity',e=> e.strength==='hard'?(hlX&&e.xdom?0.55:0.32):0.12);
}
const node=gN.selectAll('.node').data(nodes).join('g').attr('class','node')
  .attr('transform',d=>`translate(${d.x},${d.y})`);
node.append('circle').attr('r',R).attr('fill',d=>COLOR[d.cat]);
node.append('text').attr('x',R+3).attr('dy',3).text(d=>d.label);

const tip=document.getElementById('tip');
node.on('mousemove',(ev,d)=>{tip.style.opacity=1;tip.style.left=(ev.clientX+14)+'px';tip.style.top=(ev.clientY+12)+'px';
    tip.innerHTML=`<div class="id">${d.label}</div><div class="dm">Grade ${d.grade} · ${d.domain}</div>${d.text}…`;})
  .on('mouseleave',()=>tip.style.opacity=0)
  .on('click',(ev,d)=>{ev.stopPropagation();trace(d.id);});
d3.select('#wrap').on('click',()=>trace(null));

function trace(id){
  if(!id){node.style('opacity',1).select('circle').attr('stroke','#0d1117').attr('stroke-width',1);
    gE.selectAll('path').attr('stroke-opacity',null); draw(); return;}
  const anc=ancestors(id); anc.add(id);
  node.style('opacity',n=>anc.has(n.id)?1:0.12);
  node.select('circle').attr('stroke',n=>n.id===id?'#fff':(anc.has(n.id)?'#fff':'#0d1117')).attr('stroke-width',n=>anc.has(n.id)?1.6:1);
  gE.selectAll('path').attr('stroke-opacity',e=>(anc.has(e.learner)&&anc.has(e.prereq))?0.85:0.04)
    .attr('stroke',e=>(anc.has(e.learner)&&anc.has(e.prereq))?'#fff':'#3d444d');
}

const lg=d3.select('#legend');
CATS.forEach(c=>{const el=lg.append('div').attr('class','lg');
  el.append('div').attr('class','sw').style('background',COLOR[c]); el.append('span').text(c);});
document.getElementById('soft').onchange=draw;
document.getElementById('xdom').onchange=draw;
draw();
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
