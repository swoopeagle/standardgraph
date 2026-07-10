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
    c_hubvol = defaultdict(lambda: defaultdict(int))  # country -> hub -> volume
    for sysc, hub, n in rows:
        c = country_of(sysc)
        if not c or c not in COUNTRY:
            continue
        c_systems[c].add(sysc)
        c_mappings[c] += n
        c_hubvol[c][hub] += n

    countries = []
    for c, (lat, lon, region) in COUNTRY.items():
        if c not in c_mappings:
            continue
        countries.append({
            "name": c, "lat": lat, "lon": lon, "region": region,
            "systems": len(c_systems[c]), "mappings": c_mappings[c],
            "hubs": sorted(c_hubvol[c]),
            "hubvol": dict(c_hubvol[c]),
        })
    countries.sort(key=lambda d: -d["mappings"])
    names = [c["name"] for c in countries]

    stats = {
        "systems": sum(len(v) for v in c_systems.values()),
        "countries": len(countries),
        "crosswalks": total_xwalk,
        "regions": len({c["region"] for c in countries}),
    }
    payload = {
        "countries": countries, "names": names,
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
    .replace("__H1__", "StandardGraph — Country Interoperability") \
    .replace("__HINT__", "filter by region · ▶ autoplay cycles regions (the animation) · hover a country to isolate its links") + r"""
<style>
 #ctl{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 20px;border-bottom:1px solid var(--line)}
 .fbtn{font-size:12px;padding:4px 11px;border-radius:14px;border:1px solid var(--line);background:#161b22;color:var(--muted);cursor:pointer}
 .fbtn.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
</style>
<div id="ctl"><span style="color:var(--muted);font-size:12px">Region:</span><span id="fbtns"></span>
  <button class="fbtn" id="play" style="margin-left:6px">▶ autoplay</button></div>
<script>
const DATA=__DATA__;
const {countries,names,region_color,hubs,stats}=DATA;
const regionOf=Object.fromEntries(countries.map(c=>[c.name,c.region]));
const col=n=>region_color[regionOf[n]]||'#8b949e';
const subEl=document.getElementById('sub');
const vw=window.innerWidth||document.documentElement.clientWidth||1000;
const vh=window.innerHeight||document.documentElement.clientHeight||800;
const sz=Math.max(500,Math.min(700,vw-40,vh-260)), R=sz/2, inner=R-96, outer=inner+12;
const svg=d3.select('#wrap').append('svg').attr('width',sz).attr('height',sz)
  .style('display','block').style('margin','8px auto').append('g').attr('transform',`translate(${R},${R})`);
const gR=svg.append('g').attr('fill-opacity',0.5), gG=svg.append('g'), gT=svg.append('g');
const chord=d3.chord().padAngle(0.025).sortSubgroups(d3.descending);
const arc=d3.arc().innerRadius(inner).outerRadius(outer);
const ribbon=d3.ribbon().radius(inner-2);

// filter by region: All + every region with >=2 countries (a chord needs a pair).
// (Country-to-country interoperability runs through CCSS Math — the only hub with
//  multi-country coverage — so region is the meaningful cut, not subject.)
const regionCount={}; countries.forEach(c=>regionCount[c.region]=(regionCount[c.region]||0)+1);
const FILTERS=[["all","All countries"],
  ...Object.keys(region_color).filter(r=>regionCount[r]>=2).map(r=>[r,r])];
function shared(i,j){const hi=countries[i].hubvol,hj=countries[j].hubvol;return Object.keys(hi).filter(h=>h in hj).length;}
function build(f){const N=names.length,m=Array.from({length:N},()=>Array(N).fill(0));
  for(let i=0;i<N;i++)for(let j=0;j<N;j++){if(i===j)continue;
    if(f!=="all" && (regionOf[names[i]]!==f || regionOf[names[j]]!==f))continue;
    m[i][j]=shared(i,j);}
  return m;}
function nParticipants(f){return f==="all"?names.length:regionCount[f];}
function arcTween(d){const i=d3.interpolate(this._c||d,d);this._c=d;return t=>arc(i(t));}
function ribTween(d){const i=d3.interpolate(this._c||d,d);this._c=d;return t=>ribbon(i(t));}
function midAngle(d){return (d.startAngle+d.endAngle)/2;}
function update(f,dur=850){
  subEl.textContent = f==="all"
    ? `${stats.countries} countries interoperable through the shared hubs — filter to a region to see its internal interconnection`
    : `${f}: ${nParticipants(f)} countries' curricula mutually mappable`;
  const ch=chord(build(f));
  gG.selectAll('path').data(ch.groups,d=>d.index).join(
     e=>e.append('path').attr('fill',d=>col(names[d.index])).attr('stroke','#0d1117').each(function(d){this._c=d;})
        .on('mouseover',(ev,d)=>gR.selectAll('path').attr('opacity',r=>(r.source.index===d.index||r.target.index===d.index)?0.95:0.05))
        .on('mouseout',()=>gR.selectAll('path').attr('opacity',0.5)),
     u=>u).transition().duration(dur).attrTween('d',arcTween);
  gR.selectAll('path').data(ch,d=>d.source.index+'-'+d.target.index).join(
     e=>e.append('path').attr('fill',d=>col(names[d.source.index])).attr('stroke','none').attr('opacity',0).each(function(d){this._c=d;}),
     u=>u, x=>x.transition().duration(dur*0.6).attr('opacity',0).remove())
   .transition().duration(dur).attr('opacity',0.5).attr('fill',d=>col(names[d.source.index])).attrTween('d',ribTween);
  gT.selectAll('text').data(ch.groups,d=>d.index).join(
     e=>e.append('text').attr('fill','#e6edf3').style('font-size','10px').attr('dy','0.35em').text(d=>names[d.index]).each(function(d){this._c=d;}),
     u=>u)
   .attr('text-anchor',d=>midAngle(d)>Math.PI?'end':'start')
   .transition().duration(dur)
   .style('opacity',d=>(d.endAngle-d.startAngle)>0.006?1:0)
   .attrTween('transform',function(d){const i=d3.interpolate(this._c||d,d);this._c=d;
     return t=>{const a=midAngle(i(t));return `rotate(${a*180/Math.PI-90}) translate(${outer+6}) ${a>Math.PI?'rotate(180)':''}`;};});
}

let cur="all", timer=null;
const fb=d3.select('#fbtns');
FILTERS.forEach(([k,label])=>fb.append('button').attr('class','fbtn'+(k==='all'?' on':'')).attr('data-k',k)
  .text(label).on('click',()=>{cur=k;stop();sel();update(k);}));
function sel(){d3.selectAll('.fbtn').classed('on',function(){return this.getAttribute('data-k')===cur;});}
function stop(){if(timer){clearInterval(timer);timer=null;}d3.select('#play').text('▶ autoplay').classed('on',false);}
d3.select('#play').on('click',function(){
  if(timer){stop();return;}
  d3.select(this).text('❚❚ pause').classed('on',true);
  let i=FILTERS.findIndex(x=>x[0]===cur);
  timer=setInterval(()=>{i=(i+1)%FILTERS.length;cur=FILTERS[i][0];sel();update(cur);},2400);
});

const lg=d3.select('#legend');
Object.entries(region_color).forEach(([r,c])=>{const el=lg.insert('div',':first-child').attr('class','lg');
  el.append('div').attr('class','sw').style('background',c);el.append('span').text(r);});
update("all",1200);
</script></body></html>"""


if __name__ == "__main__":
    main()
