#!/usr/bin/env python3
"""Generate cross-country crosswalk visualizations — the breadth story.

Every one of ~294 curriculum systems (28 countries) crosswalks into the five
shared hubs (CCSS math/ELA, NGSS, C3, CSTA), so any country's standards are
mappable to any other's *through the hub*. Two offline single-file HTML views:

  world_map.html      — countries on a world map, sized by mapping volume,
                        connection arcs to the shared hubs; click a country to
                        light up every other curriculum it can map to.
  crosswalk_chord.html — countries around a circle, ribbons = shared hub subjects
                        (interoperability breadth), coloured by region.

    uv run python scripts/viz/export_crosswalk_viz.py [db] [outdir]
"""
import json
import os
import sqlite3
import sys

from common_core.server import _meta

DB = sys.argv[1] if len(sys.argv) > 1 else "data/common_core.db"
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else "docs/viz"
VDIR = os.path.join(os.path.dirname(__file__), "vendor")

# Country → (lat, lon, region). Supplements _meta for systems lacking country data.
COUNTRY = {
    "United States": (39.5, -98.35, "North America"),
    "Canada": (56.1, -106.3, "North America"),
    "Mexico": (23.6, -102.5, "Latin America"),
    "Brazil": (-14.2, -51.9, "Latin America"),
    "Chile": (-35.7, -71.5, "Latin America"),
    "Colombia": (4.6, -74.3, "Latin America"),
    "Peru": (-9.2, -75.0, "Latin America"),
    "Uruguay": (-32.5, -55.8, "Latin America"),
    "England": (52.5, -1.5, "Europe"),
    "Scotland": (56.5, -4.2, "Europe"),
    "Ireland": (53.1, -7.7, "Europe"),
    "Germany": (51.2, 10.5, "Europe"),
    "Czech Republic": (49.8, 15.5, "Europe"),
    "Spain": (40.5, -3.7, "Europe"),
    "Italy": (41.9, 12.6, "Europe"),
    "Finland": (61.9, 25.8, "Europe"),
    "Portugal": (39.4, -8.2, "Europe"),
    "Singapore": (1.35, 103.8, "Asia-Pacific"),
    "Japan": (36.2, 138.3, "Asia-Pacific"),
    "South Korea": (35.9, 127.8, "Asia-Pacific"),
    "Hong Kong": (22.3, 114.2, "Asia-Pacific"),
    "New Zealand": (-40.9, 174.9, "Asia-Pacific"),
    "Australia": (-25.3, 133.8, "Asia-Pacific"),
    "India": (20.6, 79.0, "South Asia"),
    "Ghana": (7.95, -1.0, "Sub-Saharan Africa"),
    "Rwanda": (-1.9, 29.9, "Sub-Saharan Africa"),
    "South Africa": (-30.6, 22.9, "Sub-Saharan Africa"),
    "International": (46.8, 8.2, "International"),  # IB — anchor at Switzerland
}
# system-code prefix → country, for systems _meta doesn't tag
SUPPLEMENT = {
    "br-bncc": "Brazil", "cl-mineduc": "Chile", "co-men": "Colombia",
    "cz-msmt": "Czech Republic", "dodea": "United States", "es-lomloe": "Spain",
    "fi-oph": "Finland", "ib-pyp": "International", "it-miur": "Italy",
    "kr-ncf": "South Korea", "mx-dgb-ems": "Mexico", "mx-sep-2017": "Mexico",
    "pe-minedu": "Peru", "pt-dge": "Portugal", "uy-anep": "Uruguay",
}
REGION_COLOR = {
    "North America": "#58a6ff", "Latin America": "#7ee787", "Europe": "#d2a8ff",
    "Asia-Pacific": "#ffa657", "South Asia": "#f2cc60", "Sub-Saharan Africa": "#ff7b72",
    "International": "#79c0ff",
}
HUBS = {"ccss": "CCSS Math", "ccss-ela": "CCSS ELA", "ngss": "NGSS Science",
        "c3": "C3 Social Studies", "csta": "CSTA CS"}
HUB_ANCHOR = (39.5, -96.0)  # the shared hubs are US frameworks


def country_of(system: str) -> str | None:
    c = _meta(system).get("country")
    return c or SUPPLEMENT.get(system)


def main():
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT s.system, cm.target_system, COUNT(*) FROM crosswalk_mappings cm "
        "JOIN standards s ON s.id = cm.source_id GROUP BY s.system, cm.target_system").fetchall()
    total_xwalk = con.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    con.close()

    # aggregate per country
    from collections import defaultdict
    c_systems = defaultdict(set)
    c_mappings = defaultdict(int)
    c_hubs = defaultdict(set)
    for sysc, hub, n in rows:
        c = country_of(sysc)
        if not c or c not in COUNTRY:
            continue
        c_systems[c].add(sysc)
        c_mappings[c] += n
        c_hubs[c].add(hub)

    countries = []
    for c, (lat, lon, region) in COUNTRY.items():
        if c not in c_mappings:
            continue
        countries.append({
            "name": c, "lat": lat, "lon": lon, "region": region,
            "systems": len(c_systems[c]), "mappings": c_mappings[c],
            "hubs": sorted(c_hubs[c]),
        })
    countries.sort(key=lambda d: -d["mappings"])

    # chord matrix: shared hub-subjects between each country pair
    names = [c["name"] for c in countries]
    idx = {n: i for i, n in enumerate(names)}
    matrix = [[0] * len(names) for _ in names]
    for a in countries:
        for b in countries:
            if a["name"] == b["name"]:
                continue
            shared = len(set(a["hubs"]) & set(b["hubs"]))
            matrix[idx[a["name"]]][idx[b["name"]]] = shared

    stats = {
        "systems": sum(len(v) for v in c_systems.values()),
        "countries": len(countries),
        "crosswalks": total_xwalk,
        "regions": len({c["region"] for c in countries}),
    }
    payload = {
        "countries": countries, "matrix": matrix, "names": names,
        "region_color": REGION_COLOR, "hub_anchor": HUB_ANCHOR,
        "hubs": HUBS, "stats": stats,
    }

    d3 = open(os.path.join(VDIR, "d3.v7.min.js")).read()
    topo = open(os.path.join(VDIR, "topojson-client.min.js")).read()
    land = open(os.path.join(VDIR, "land-110m.json")).read()
    ctx = {"__DATA__": json.dumps(payload), "__D3__": d3,
           "__TOPO__": topo, "__LAND__": land}

    os.makedirs(OUTDIR, exist_ok=True)
    for fname, tmpl in (("world_map.html", WORLD), ("crosswalk_chord.html", CHORD)):
        html = tmpl
        for k, v in ctx.items():
            html = html.replace(k, v)
        open(os.path.join(OUTDIR, fname), "w").write(html)
        print(f"wrote {OUTDIR}/{fname}")
    print(f"  {stats['countries']} countries · {stats['systems']} systems · "
          f"{stats['crosswalks']:,} crosswalks · {stats['regions']} regions")


_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>__TITLE__</title>
<style>
 :root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--panel:#161b22}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
   font:14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif}
 header{padding:16px 20px;border-bottom:1px solid var(--line)}
 h1{margin:0;font-size:18px;font-weight:650}.sub{color:var(--muted);font-size:13px;margin-top:3px}
 .legend{display:flex;gap:14px;flex-wrap:wrap;padding:10px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
 .lg{display:flex;align-items:center;gap:6px;font-size:12px}.sw{width:11px;height:11px;border-radius:3px}
 .hint{color:var(--muted);font-size:12px;margin-left:auto}
 #tip{position:fixed;pointer-events:none;background:#1c2333;border:1px solid var(--line);border-radius:8px;
   padding:9px 11px;max-width:300px;font-size:12px;opacity:0;transition:opacity .1s;z-index:9}
 #tip .id{font-weight:700;color:#79c0ff}#tip .dm{color:var(--muted);margin-top:2px}
 svg{display:block}
</style></head><body>
<header><h1>__H1__</h1><div class="sub" id="sub"></div></header>
<div class="legend" id="legend"><span class="hint" id="hint">__HINT__</span></div>
<div id="wrap"></div><div id="tip"></div>
<script>__D3__</script>"""

WORLD = _HEAD.replace("__TITLE__", "StandardGraph — Global Crosswalk Reach") \
    .replace("__H1__", "StandardGraph — Global Crosswalk Reach") \
    .replace("__HINT__", "hover a country for its curricula · click a country to light every curriculum it maps to · click empty space to reset") + r"""
<script>__TOPO__</script>
<script>
const DATA=__DATA__, LAND=__LAND__;
const {countries,region_color,hub_anchor,stats}=DATA;
document.getElementById('sub').textContent=
 `${stats.countries} countries · ${stats.systems} curriculum systems · ${stats.crosswalks.toLocaleString()} crosswalks — every curriculum interoperable through the shared hubs`;
const W=Math.min(1500,(window.innerWidth||document.documentElement.clientWidth||1280)), H=Math.round(W*0.52);
const svg=d3.select('#wrap').append('svg').attr('width',W).attr('height',H);
const proj=d3.geoNaturalEarth1().fitSize([W,H], topojson.feature(LAND,LAND.objects.land));
const path=d3.geoPath(proj);
svg.append('path').datum(topojson.feature(LAND,LAND.objects.land)).attr('d',path)
   .attr('fill','#1b2230').attr('stroke','#2b3444').attr('stroke-width',0.5);
const hub=proj([hub_anchor[1],hub_anchor[0]]);
const pt=c=>proj([c.lon,c.lat]);
function arc(a,b){const dx=b[0]-a[0],dy=b[1]-a[1];const c=[(a[0]+b[0])/2+dy*0.18,(a[1]+b[1])/2-dx*0.18];
  return `M${a[0]},${a[1]} Q${c[0]},${c[1]} ${b[0]},${b[1]}`;}
const gA=svg.append('g'), gN=svg.append('g');
function spokes(){gA.selectAll('path').data(countries).join('path').attr('d',c=>arc(pt(c),hub))
  .attr('fill','none').attr('stroke','#3d444d').attr('stroke-width',0.7).attr('stroke-opacity',0.35);}
spokes();
const rmax=d3.scaleSqrt().domain([1,d3.max(countries,c=>c.mappings)]).range([3,22]);
const node=gN.selectAll('circle').data(countries).join('circle')
  .attr('cx',c=>pt(c)[0]).attr('cy',c=>pt(c)[1]).attr('r',c=>rmax(c.mappings))
  .attr('fill',c=>region_color[c.region]).attr('fill-opacity',0.82).attr('stroke','#0d1117').attr('stroke-width',1)
  .style('cursor','pointer');
const tip=document.getElementById('tip');
node.on('mousemove',(ev,c)=>{tip.style.opacity=1;tip.style.left=(ev.clientX+14)+'px';tip.style.top=(ev.clientY+12)+'px';
   tip.innerHTML=`<div class="id">${c.name}</div><div class="dm">${c.region} · ${c.systems} system${c.systems>1?'s':''} · ${c.mappings.toLocaleString()} crosswalks<br>hubs: ${c.hubs.join(', ')}</div>`;})
 .on('mouseleave',()=>tip.style.opacity=0)
 .on('click',(ev,c)=>{ev.stopPropagation();focus(c);});
d3.select('#wrap').on('click',()=>{node.attr('fill-opacity',0.82);spokes();});
function focus(c){const a=pt(c);
  // arcs to every other country sharing ≥1 hub (interoperable via that hub)
  const links=countries.filter(o=>o.name!==c.name && o.hubs.some(h=>c.hubs.includes(h)));
  gA.selectAll('path').data(links).join('path').attr('d',o=>arc(a,pt(o)))
    .attr('fill','none').attr('stroke',region_color[c.region]).attr('stroke-width',1.1).attr('stroke-opacity',0.7);
  node.attr('fill-opacity',o=>(o.name===c.name||links.includes(o))?0.95:0.15);}
const lg=d3.select('#legend');
Object.entries(region_color).forEach(([r,col])=>{const el=lg.insert('div',':first-child').attr('class','lg');
  el.append('div').attr('class','sw').style('background',col);el.append('span').text(r);});
</script></body></html>"""

CHORD = _HEAD.replace("__TITLE__", "StandardGraph — Country Interoperability") \
    .replace("__H1__", "StandardGraph — Country Interoperability (shared hub subjects)") \
    .replace("__HINT__", "ribbon = number of hub subjects two countries share (how many subjects are mutually mappable) · hover a country arc") + r"""
<script>
const DATA=__DATA__;
const {countries,names,matrix,region_color,stats}=DATA;
const regionOf=Object.fromEntries(countries.map(c=>[c.name,c.region]));
document.getElementById('sub').textContent=
 `${stats.countries} countries linked through 5 shared hubs — ribbons show subjects mutually mappable between each pair`;
const vw=window.innerWidth||document.documentElement.clientWidth||1000;
const vh=window.innerHeight||document.documentElement.clientHeight||800;
const sz=Math.max(520,Math.min(720,vw-40,vh-200)), R=sz/2, inner=R-96, outer=inner+12;
const svg=d3.select('#wrap').append('svg').attr('width',sz).attr('height',sz)
  .style('display','block').style('margin','10px auto')
  .append('g').attr('transform',`translate(${R},${R})`);
const chord=d3.chordDirected().padAngle(0.03).sortSubgroups(d3.descending)(matrix);
const arc=d3.arc().innerRadius(inner).outerRadius(outer);
const ribbon=d3.ribbonArrow().radius(inner-2);
const col=n=>region_color[regionOf[n]]||'#8b949e';
svg.append('g').selectAll('path').data(chord.groups).join('path').attr('d',arc)
  .attr('fill',d=>col(names[d.index])).attr('stroke','#0d1117')
  .on('mouseover',(e,d)=>{svg.selectAll('.rb').attr('opacity',r=>(r.source.index===d.index||r.target.index===d.index)?0.9:0.06);})
  .on('mouseout',()=>svg.selectAll('.rb').attr('opacity',0.45));
svg.append('g').attr('fill-opacity',0.45).selectAll('path').data(chord).join('path').attr('class','rb')
  .attr('d',ribbon).attr('fill',d=>col(names[d.source.index])).attr('opacity',0.45).attr('stroke','none');
svg.append('g').selectAll('text').data(chord.groups).join('text')
  .each(d=>{d.a=(d.startAngle+d.endAngle)/2;})
  .attr('transform',d=>`rotate(${d.a*180/Math.PI-90}) translate(${outer+6}) ${d.a>Math.PI?'rotate(180)':''}`)
  .attr('text-anchor',d=>d.a>Math.PI?'end':'start').attr('dy','0.35em')
  .attr('fill','#e6edf3').style('font-size','10px').text(d=>names[d.index]);
const lg=d3.select('#legend');
Object.entries(region_color).forEach(([r,c])=>{const el=lg.insert('div',':first-child').attr('class','lg');
  el.append('div').attr('class','sw').style('background',c);el.append('span').text(r);});
</script></body></html>"""


if __name__ == "__main__":
    main()
