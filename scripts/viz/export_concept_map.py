#!/usr/bin/env python3
"""Export the Marble-style 3D interactive concept map.

Builds a single self-contained HTML file (canvas 3D force layout, data inlined —
works fully offline, no server or CDN) from the LLM-validated CCSS-math
prerequisite graph in the DB.

Usage:
    uv run python scripts/viz/export_concept_map.py ~/.standardgraph/common_core.db docs/viz/concept_map.html
"""
import json
import sqlite3
import sys
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StandardGraph — Concept Map</title>
<style>
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:radial-gradient(1200px 800px at 70% 20%,#111b33 0%,#070a12 60%,#04060c 100%);color:#e8edf7;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;overflow:hidden}
  #stage{position:fixed;inset:0}
  canvas{display:block;position:absolute;inset:0;cursor:grab}
  canvas.grab{cursor:grabbing}
  header{position:fixed;top:0;left:0;right:0;padding:16px 20px;pointer-events:none;background:linear-gradient(#04060ccc,transparent)}
  header h1{margin:0;font-size:16px;font-weight:650;letter-spacing:.2px}
  header p{margin:3px 0 0;font-size:12px;color:#93a1c0}
  .legend{position:fixed;left:20px;bottom:18px;display:flex;flex-wrap:wrap;gap:6px 12px;max-width:340px;font-size:11px;color:#b7c2db}
  .legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle;box-shadow:0 0 6px currentColor}
  .hint{position:fixed;right:20px;bottom:18px;font-size:11px;color:#6d7a97;text-align:right;line-height:1.6}
  #panel{position:fixed;top:64px;right:16px;width:340px;max-height:calc(100vh - 150px);overflow:auto;background:rgba(14,20,36,.82);backdrop-filter:blur(10px);border:1px solid #23304d;border-radius:14px;padding:16px;box-shadow:0 20px 50px #000a;transform:translateX(380px);transition:transform .28s cubic-bezier(.2,.8,.2,1);pointer-events:auto}
  #panel.open{transform:none}
  #panel .id{font:600 12px ui-monospace,Menlo,monospace;color:#7fd0ff;word-break:break-all}
  #panel .chip{display:inline-block;font-size:10.5px;padding:2px 8px;border-radius:20px;margin:6px 6px 0 0;background:#1b2947;color:#c9d6f2}
  #panel h3{margin:14px 0 6px;font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:#8fa0c4}
  #panel .txt{margin-top:8px;font-size:12.5px;color:#d5deef}
  .rel{border-left:2px solid #2a3a5e;padding:6px 0 6px 10px;margin:7px 0;cursor:pointer;transition:border-color .15s}
  .rel:hover{border-color:#7fd0ff}
  .rel .rid{font:600 11px ui-monospace,monospace}
  .rel .why{font-size:11.5px;color:#9fb0d2;margin-top:2px}
  .rel.hard .rid{color:#ffd27f}.rel.soft .rid{color:#a6c8ff}
  .tag{font-size:9.5px;padding:1px 6px;border-radius:10px;margin-left:6px;vertical-align:middle}
  .tag.hard{background:#4a3410;color:#ffcf7a}.tag.soft{background:#20304f;color:#a6c8ff}
  #close{position:absolute;top:10px;right:12px;cursor:pointer;color:#8090b0;font-size:18px;line-height:1}
  #tip{position:fixed;pointer-events:none;background:#0b1224e6;border:1px solid #26355a;border-radius:8px;padding:6px 9px;font-size:11.5px;max-width:260px;display:none;z-index:5;box-shadow:0 8px 20px #0008}
  #tip .tid{font:600 11px ui-monospace,monospace;color:#7fd0ff}
  #loading{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;font-size:13px;color:#8fa0c4;background:#04060c}
  #regions{position:fixed;top:58px;left:20px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;max-width:64vw}
  #regions .rb{font-size:11px;padding:4px 10px;border-radius:20px;border:1px solid #2a3a5e;background:#111b30;color:#c3cee6;cursor:pointer;transition:.15s;user-select:none}
  #regions .rb:hover{border-color:#4a608f}
  #regions .rb.on{background:#1f3a63;border-color:#6ea8fe;color:#fff}
  #regions .rb .n{opacity:.6;margin-left:5px;font-size:10px}
  #panel .wsec{margin-top:6px}
  #panel .wgrp{font-size:10.5px;letter-spacing:.5px;text-transform:uppercase;color:#7f8fb3;margin:10px 0 4px}
  .wrow{display:flex;align-items:baseline;gap:6px;padding:3px 0 3px 10px;border-left:2px solid #263a5e;margin:3px 0;font-size:11.5px}
  .wrow .flag{font-size:12px}
  .wrow .wsys{color:#d3ddf0;font-weight:600;white-space:nowrap}
  .wrow .wid{font:11px ui-monospace,monospace;color:#8fa8d6;word-break:break-all}
  .wrow .wc{margin-left:auto;font-size:10px;color:#8b9ac0;white-space:nowrap}
  .wdisc{font-size:10.5px;color:#6f7d9c;margin:2px 0 0;font-style:italic}
</style>
</head>
<body>
<div id="stage"><canvas id="c"></canvas></div>
<header>
  <h1>StandardGraph — Learning Concept Map</h1>
  <p>CCSS Mathematics · K→High School · <b id="nc"></b> concepts · <b id="ec"></b> prerequisite links · crosswalked to <b id="ic"></b> curriculum systems in <b id="rc"></b> world regions. Tap a node for its chain and worldwide equivalents.</p>
</header>
<div id="regions"></div>
<div class="legend" id="legend"></div>
<div class="hint">drag to rotate · scroll to zoom · tap a node for its chain · double-click to reset</div>
<div id="panel"><span id="close">×</span><div id="pbody"></div></div>
<div id="tip"></div>
<div id="loading">Laying out the concept map…</div>
<script>
const DATA = __DATA__;
const GRADES = ["K","1","2","3","4","5","6","7","8","HS"];
const GCOL = {K:"#6ea8fe","1":"#4dd0e1","2":"#4db6ac","3":"#81c784","4":"#aed581","5":"#ffd54f","6":"#ffb74d","7":"#ff8a65","8":"#f06292","HS":"#ba68c8"};
function gidx(g){const i=GRADES.indexOf(g);return i<0?0:i;}

const N = DATA.nodes, E = DATA.edges;
const INTL = DATA.intl || {};           // ccssId -> [[sys, srcId, conf, grade, text], ...]
const META = DATA.meta || {};           // sys -> [label, region, flag]
const REGIONS = ["North America","Asia-Pacific","Europe","International Baccalaureate","Africa","Latin America"];
const RCOL = {"North America":"#6ea8fe","Asia-Pacific":"#4db6ac","Europe":"#ffd54f","International Baccalaureate":"#ba68c8","Africa":"#ff8a65","Latin America":"#f06292"};
const byId = {}; N.forEach((n,i)=>{n.i=i;byId[n.id]=n;});

// per-node region coverage (from crosswalks)
const nodeRegions = {}; const nodeSysCount = {};
N.forEach(n=>{ const rows=INTL[n.id]||[]; const rs=new Set(); rows.forEach(r=>{const m=META[r[0]]; if(m)rs.add(m[1]);}); nodeRegions[n.id]=rs; nodeSysCount[n.id]=rows.length; });
const allSys = new Set(); Object.values(INTL).forEach(rows=>rows.forEach(r=>allSys.add(r[0])));
document.getElementById('nc').textContent=N.length;
document.getElementById('ec').textContent=E.length;
document.getElementById('ic').textContent=allSys.size;
document.getElementById('rc').textContent=REGIONS.filter(r=>[...allSys].some(s=>META[s]&&META[s][1]===r)).length;

// edge s requires t  => t is prerequisite of s ; t unlocks s
const prereq = {}, unlock = {};
N.forEach(n=>{prereq[n.id]=[];unlock[n.id]=[];});
E.forEach(e=>{ if(byId[e.s]&&byId[e.t]){ prereq[e.s].push(e); unlock[e.t].push(e); }});

// ---- 3D force layout ----
const P = N.map(()=>({x:(Math.random()-.5)*600,y:(Math.random()-.5)*600,z:(Math.random()-.5)*600,vx:0,vy:0,vz:0}));
function layout(){
  const REP=2200, SPR=0.02, REST=70, GRAV=0.012, GY=0.05, DAMP=0.86;
  for(let it=0; it<320; it++){
    const cool = 1-it/360;
    for(let i=0;i<N.length;i++){
      let fx=0,fy=0,fz=0; const a=P[i];
      for(let j=0;j<N.length;j++){ if(i===j)continue; const b=P[j];
        let dx=a.x-b.x,dy=a.y-b.y,dz=a.z-b.z; let d2=dx*dx+dy*dy+dz*dz+0.01; let f=REP/d2; let d=Math.sqrt(d2);
        fx+=dx/d*f; fy+=dy/d*f; fz+=dz/d*f;
      }
      fx-=a.x*GRAV; fy-=a.y*GRAV; fz-=a.z*GRAV;
      const targetY=(gidx(N[i].grade)/9-0.5)*520; fy+=(targetY-a.y)*GY;
      a.vx=(a.vx+fx*cool)*DAMP; a.vy=(a.vy+fy*cool)*DAMP; a.vz=(a.vz+fz*cool)*DAMP;
    }
    for(const e of E){ const a=P[byId[e.s].i], b=P[byId[e.t].i];
      let dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z; let d=Math.sqrt(dx*dx+dy*dy+dz*dz)+0.01;
      let f=SPR*(d-REST)*(e.c>0.7?1.6:1); let ux=dx/d,uy=dy/d,uz=dz/d;
      a.vx+=ux*f;a.vy+=uy*f;a.vz+=uz*f; b.vx-=ux*f;b.vy-=uy*f;b.vz-=uz*f;
    }
    for(let i=0;i<N.length;i++){P[i].x+=P[i].vx;P[i].y+=P[i].vy;P[i].z+=P[i].vz;}
  }
}

const cv=document.getElementById('c'), ctx=cv.getContext('2d');
let W,H,DPR; function resize(){DPR=Math.min(2,devicePixelRatio||1);W=innerWidth;H=innerHeight;cv.width=W*DPR;cv.height=H*DPR;cv.style.width=W+'px';cv.style.height=H+'px';ctx.setTransform(DPR,0,0,DPR,0,0);}
addEventListener('resize',resize); resize();

let rx=-0.35, ry=0.5, zoom=0.9, autor=true;
let sel=null, hi={pre:new Set(),unl:new Set()}, hover=null, region=null;
const proj = new Array(N.length);

function rot(p){
  let cy=Math.cos(ry),sy=Math.sin(ry),cx=Math.cos(rx),sx=Math.sin(rx);
  let x=p.x*cy - p.z*sy, z=p.x*sy + p.z*cy;
  let y=p.y*cx - z*sx, z2=p.y*sx + z*cx;
  return {x,y,z:z2};
}
function project(){
  const cam=900;
  for(let i=0;i<N.length;i++){ const r=rot(P[i]); const s=cam/(cam - r.z*zoom + 300);
    proj[i]={sx:W/2 + r.x*zoom*s, sy:H/2 + r.y*zoom*s, z:r.z, s};
  }
}
function chainSet(id,map){ const out=new Set(); const stack=[id];
  while(stack.length){ const cur=stack.pop(); for(const e of map[cur]){ const nx=(map===prereq?e.t:e.s); if(!out.has(nx)){out.add(nx);stack.push(nx);} } }
  return out;
}
function select(id){ sel=id; hi.pre=chainSet(id,prereq); hi.unl=chainSet(id,unlock); autor=false; renderPanel(); }
function clearSel(){ sel=null; hi.pre.clear(); hi.unl.clear(); document.getElementById('panel').classList.remove('open'); }

function draw(){
  if(autor) ry+=0.0016;
  project();
  ctx.clearRect(0,0,W,H);
  const order=[...Array(N.length).keys()].sort((a,b)=>proj[a].z-proj[b].z);
  const active = sel!==null;
  ctx.lineWidth=1;
  for(const e of E){ const A=proj[byId[e.s].i], B=proj[byId[e.t].i];
    let on=false, col='rgba(120,140,180,0.05)';
    if(active){
      const inPre = (n)=> n===sel||hi.pre.has(n); const inUnl=(n)=> n===sel||hi.unl.has(n);
      if(inPre(e.s)&&inPre(e.t)){on=true;col='rgba(130,180,255,0.55)';}
      else if(inUnl(e.s)&&inUnl(e.t)){on=true;col='rgba(255,180,120,0.5)';}
    }
    if(!active || on){
      ctx.strokeStyle=col; ctx.globalAlpha=1;
      ctx.beginPath(); ctx.moveTo(A.sx,A.sy); ctx.lineTo(B.sx,B.sy); ctx.stroke();
    }
  }
  for(const i of order){ const p=proj[i], n=N[i];
    let r=Math.max(1.6, 4.2*p.s);
    let base=GCOL[n.grade]||'#8899bb';
    let alpha=0.55+0.45*Math.max(0,Math.min(1,(p.z+300)/600));
    let ring=null;
    if(active){
      if(n.id===sel){ r*=1.9; ring='#ffffff'; alpha=1; }
      else if(hi.pre.has(n.id)){ alpha=1; ring='rgba(150,190,255,.9)'; }
      else if(hi.unl.has(n.id)){ alpha=1; ring='rgba(255,190,130,.9)'; }
      else { alpha=0.08; }
    } else if(region){
      if(nodeRegions[n.id] && nodeRegions[n.id].has(region)){ alpha=1; base=RCOL[region]; r*=1.15; }
      else { alpha=0.07; }
    }
    if(hover===i){ ring='#fff'; }
    ctx.globalAlpha=alpha;
    ctx.beginPath(); ctx.arc(p.sx,p.sy,r,0,7); ctx.fillStyle=base; ctx.fill();
    if(ring){ ctx.globalAlpha=Math.min(1,alpha+0.3); ctx.lineWidth=1.5; ctx.strokeStyle=ring; ctx.stroke();
      ctx.globalAlpha=0.25; ctx.beginPath(); ctx.arc(p.sx,p.sy,r+3,0,7); ctx.strokeStyle=ring; ctx.stroke(); }
  }
  ctx.globalAlpha=1;
  requestAnimationFrame(draw);
}

function pick(mx,my){ let best=-1,bd=1e9; for(let i=0;i<N.length;i++){ const p=proj[i]; const r=Math.max(3,4.2*p.s)+4; const d=(p.sx-mx)**2+(p.sy-my)**2; if(d<r*r && d<bd){bd=d;best=i;} } return best; }

let drag=false,px,py,moved=0;
cv.addEventListener('mousedown',e=>{drag=true;px=e.clientX;py=e.clientY;moved=0;cv.classList.add('grab');});
addEventListener('mouseup',e=>{ if(drag&&moved<4){ const i=pick(e.clientX,e.clientY); if(i>=0){select(N[i].id);} else {clearSel();autor=false;} } drag=false;cv.classList.remove('grab'); });
addEventListener('mousemove',e=>{
  if(drag){ const dx=e.clientX-px,dy=e.clientY-py; px=e.clientX;py=e.clientY; moved+=Math.abs(dx)+Math.abs(dy); ry+=dx*0.006; rx+=dy*0.006; autor=false; hideTip(); }
  else { const i=pick(e.clientX,e.clientY); hover=i; if(i>=0) showTip(e.clientX,e.clientY,N[i]); else hideTip(); }
});
cv.addEventListener('wheel',e=>{e.preventDefault(); zoom*=e.deltaY<0?1.08:0.92; zoom=Math.max(0.25,Math.min(3.5,zoom));},{passive:false});
cv.addEventListener('dblclick',()=>{ rx=-0.35;ry=0.5;zoom=0.9;autor=true;clearSel(); });
document.getElementById('close').onclick=clearSel;

const tip=document.getElementById('tip');
function showTip(x,y,n){ tip.style.display='block'; tip.style.left=Math.min(x+14,innerWidth-270)+'px'; tip.style.top=(y+14)+'px'; tip.innerHTML='<div class="tid">'+n.id+'</div><div>'+esc(n.text.slice(0,120))+(n.text.length>120?'…':'')+'</div>'; }
function hideTip(){tip.style.display='none';}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

function relRow(e,dir){ const other=dir==='pre'?e.t:e.s; const n=byId[other]; const hard=e.c>0.7;
  return '<div class="rel '+(hard?'hard':'soft')+'" data-id="'+other+'"><span class="rid">'+other+'</span>'+
    '<span class="tag '+(hard?'hard':'soft')+'">'+(hard?'hard':'soft')+'</span>'+
    '<div class="why">'+esc(n?n.text.slice(0,70)+'… ':'')+'</div>'+
    (e.why?'<div class="why">↳ '+esc(e.why.slice(0,150))+'</div>':'')+'</div>';
}
function worldwideHTML(id){
  const rows=(INTL[id]||[]).slice().sort((a,b)=>b[2]-a[2]);
  if(!rows.length) return '<h3>Same concept worldwide</h3><div class="why">No international crosswalks for this concept yet.</div>';
  const regionsHit=new Set(rows.map(r=>META[r[0]]&&META[r[0]][1]).filter(Boolean));
  let html='<h3>Same concept worldwide · '+rows.length+' systems, '+regionsHit.size+' regions</h3>'+
    '<div class="wdisc">Algorithmic crosswalks — candidate equivalences, not human-verified.</div><div class="wsec">';
  for(const reg of REGIONS){
    const rr=rows.filter(r=>META[r[0]]&&META[r[0]][1]===reg);
    if(!rr.length) continue;
    html+='<div class="wgrp" style="color:'+RCOL[reg]+'">'+reg+'</div>';
    for(const r of rr){ const m=META[r[0]]; const pct=Math.round(r[2]*100);
      html+='<div class="wrow"><span class="flag">'+m[2]+'</span><span class="wsys">'+esc(m[0])+'</span>'+
        '<span class="wid">'+esc(r[1])+'</span><span class="wc">'+pct+'%</span></div>'+
        '<div class="wdisc" style="margin:0 0 4px 26px">'+esc((r[4]||'').slice(0,90))+((r[4]||'').length>90?'…':'')+'</div>';
    }
  }
  return html+'</div>';
}
function renderPanel(){
  const n=byId[sel]; const pb=document.getElementById('pbody');
  const pr=prereq[sel], ul=unlock[sel];
  pb.innerHTML='<div class="id">'+n.id+'</div>'+
    '<span class="chip" style="background:'+(GCOL[n.grade])+'22;color:'+GCOL[n.grade]+'">Grade '+n.grade+'</span>'+
    '<span class="chip">'+esc(n.domain)+'</span>'+
    '<div class="txt">'+esc(n.text)+'</div>'+
    '<h3>Requires first · '+pr.length+'</h3>'+(pr.length?pr.map(e=>relRow(e,'pre')).join(''):'<div class="why">Foundational — no prerequisites in this graph.</div>')+
    '<h3>Unlocks next · '+ul.length+'</h3>'+(ul.length?ul.map(e=>relRow(e,'unl')).join(''):'<div class="why">Leaf — nothing builds on it yet.</div>')+
    worldwideHTML(sel);
  document.getElementById('panel').classList.add('open');
  pb.querySelectorAll('.rel').forEach(r=>r.onclick=()=>select(r.dataset.id));
}
function buildRegionBar(){
  const bar=document.getElementById('regions');
  const cov={}; REGIONS.forEach(r=>cov[r]=0);
  N.forEach(n=>nodeRegions[n.id].forEach(r=>{if(cov[r]!=null)cov[r]++;}));
  bar.innerHTML='';
  const mk=(label,reg)=>{ const b=document.createElement('div'); b.className='rb'+(region===reg?' on':'');
    b.innerHTML=label+(reg?'<span class="n">'+cov[reg]+'</span>':''); if(reg)b.style.borderColor=region===reg?RCOL[reg]:'';
    b.onclick=()=>{ region=(region===reg)?null:reg; buildRegionBar(); }; bar.appendChild(b); };
  mk('All regions',null);
  REGIONS.forEach(r=>mk(r,r));
}

document.getElementById('legend').innerHTML=GRADES.map(g=>'<span><i style="color:'+GCOL[g]+'"></i>'+(g==='K'?'K':g==='HS'?'HS':'Gr '+g)+'</span>').join('');
buildRegionBar();

setTimeout(()=>{ layout(); document.getElementById('loading').style.display='none'; draw(); }, 30);
</script>
</body>
</html>"""


# International (non-US) curriculum systems that crosswalk into CCSS math.
# code -> [display label, region, flag]
SYSTEM_META = {
    # North America (Canada)
    "ca-on": ["Ontario", "North America", "\U0001F1E8\U0001F1E6"],
    "ca-ab": ["Alberta", "North America", "\U0001F1E8\U0001F1E6"],
    "ca-sk": ["Saskatchewan", "North America", "\U0001F1E8\U0001F1E6"],
    "ca-qc": ["Québec", "North America", "\U0001F1E8\U0001F1E6"],
    "ca-bc": ["British Columbia", "North America", "\U0001F1E8\U0001F1E6"],
    "ca-mb": ["Manitoba", "North America", "\U0001F1E8\U0001F1E6"],
    "ca-nb": ["New Brunswick", "North America", "\U0001F1E8\U0001F1E6"],
    # Asia-Pacific
    "nz-moe": ["New Zealand", "Asia-Pacific", "\U0001F1F3\U0001F1FF"],
    "au-acara": ["Australia (ACARA)", "Asia-Pacific", "\U0001F1E6\U0001F1FA"],
    "au-vic": ["Victoria (AU)", "Asia-Pacific", "\U0001F1E6\U0001F1FA"],
    "sg-moe": ["Singapore", "Asia-Pacific", "\U0001F1F8\U0001F1EC"],
    "jp-mext": ["Japan", "Asia-Pacific", "\U0001F1EF\U0001F1F5"],
    "kr-ncf": ["South Korea", "Asia-Pacific", "\U0001F1F0\U0001F1F7"],
    "hk-edb": ["Hong Kong", "Asia-Pacific", "\U0001F1ED\U0001F1F0"],
    "in-ncert": ["India (NCERT)", "Asia-Pacific", "\U0001F1EE\U0001F1F3"],
    # Europe
    "uk-nc": ["England (NC)", "Europe", "\U0001F1EC\U0001F1E7"],
    "uk-aqa": ["England (AQA)", "Europe", "\U0001F1EC\U0001F1E7"],
    "gb-sco": ["Scotland", "Europe", "\U0001F3F4"],
    "ie-ncca": ["Ireland", "Europe", "\U0001F1EE\U0001F1EA"],
    "de-kmk": ["Germany", "Europe", "\U0001F1E9\U0001F1EA"],
    "it-miur": ["Italy", "Europe", "\U0001F1EE\U0001F1F9"],
    "es-lomloe": ["Spain", "Europe", "\U0001F1EA\U0001F1F8"],
    "fi-oph": ["Finland", "Europe", "\U0001F1EB\U0001F1EE"],
    "cz-msmt": ["Czechia", "Europe", "\U0001F1E8\U0001F1FF"],
    "pt-dge": ["Portugal", "Europe", "\U0001F1F5\U0001F1F9"],
    "cambridge": ["Cambridge Intl", "Europe", "\U0001F30D"],
    # International Baccalaureate
    "ib-pyp": ["IB PYP", "International Baccalaureate", "\U0001F30D"],
    "ib-myp": ["IB MYP", "International Baccalaureate", "\U0001F30D"],
    "ib-dp": ["IB DP", "International Baccalaureate", "\U0001F30D"],
    # Africa
    "za-caps": ["South Africa", "Africa", "\U0001F1FF\U0001F1E6"],
    "na-nied": ["Namibia", "Africa", "\U0001F1F3\U0001F1E6"],
    "ke-kicd": ["Kenya", "Africa", "\U0001F1F0\U0001F1EA"],
    "tz-tie": ["Tanzania", "Africa", "\U0001F1F9\U0001F1FF"],
    "zm-cdc": ["Zambia", "Africa", "\U0001F1FF\U0001F1F2"],
    "ug-ncdc": ["Uganda", "Africa", "\U0001F1FA\U0001F1EC"],
    "ng-nerdc": ["Nigeria", "Africa", "\U0001F1F3\U0001F1EC"],
    "gh-nacca": ["Ghana", "Africa", "\U0001F1EC\U0001F1ED"],
    "rw-reb": ["Rwanda", "Africa", "\U0001F1F7\U0001F1FC"],
    "zw-zimsec": ["Zimbabwe", "Africa", "\U0001F1FF\U0001F1FC"],
    # Latin America
    "br-bncc": ["Brazil", "Latin America", "\U0001F1E7\U0001F1F7"],
    "cl-mineduc": ["Chile", "Latin America", "\U0001F1E8\U0001F1F1"],
    "co-men": ["Colombia", "Latin America", "\U0001F1E8\U0001F1F4"],
    "mx-sep-2017": ["Mexico", "Latin America", "\U0001F1F2\U0001F1FD"],
    "mx-dgb-ems": ["Mexico (upper sec)", "Latin America", "\U0001F1F2\U0001F1FD"],
    "uy-anep": ["Uruguay", "Latin America", "\U0001F1FA\U0001F1FE"],
    "pe-minedu": ["Peru", "Latin America", "\U0001F1F5\U0001F1EA"],
}


def extract_why(notes: str) -> str:
    for key in ("hard:", "soft:"):
        idx = notes.find(key)
        if idx >= 0:
            return notes[idx + len(key):].strip()
    return ""


def build(db_path: str, out_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ids = {
        r[0]
        for r in con.execute(
            "SELECT source_id FROM standard_relationships WHERE method='llm_validated' "
            "UNION SELECT target_id FROM standard_relationships WHERE method='llm_validated'"
        )
    }
    placeholders = ",".join("?" * len(ids))
    nodes = [
        {"id": r["id"], "grade": r["grade"], "domain": r["domain"], "text": r["standard_text"]}
        for r in con.execute(
            f"SELECT id, grade, domain, standard_text FROM standards WHERE id IN ({placeholders})",
            list(ids),
        )
    ]
    edges = []
    for r in con.execute(
        "SELECT source_id, target_id, confidence_score, COALESCE(notes,'') AS notes "
        "FROM standard_relationships "
        "WHERE method='llm_validated' AND relationship='prerequisite'"
    ):
        edges.append(
            {
                "s": r["source_id"],
                "t": r["target_id"],
                "c": 0.9 if (r["confidence_score"] or 0) > 0.7 else 0.5,
                "why": extract_why(r["notes"]),
            }
        )
    # International crosswalks landing on the concept nodes.
    # Keep the single best (highest-confidence) row per (concept, source system).
    sys_ph = ",".join("?" * len(SYSTEM_META))
    best: dict = {}  # (ccss_id, sys) -> row tuple
    for r in con.execute(
        f"SELECT c.target_id AS ccss, c.source_system AS sys, c.source_id AS sid, "
        f"       c.confidence_score AS conf, s.grade AS grade, s.standard_text AS text "
        f"FROM crosswalk_mappings c JOIN standards s ON s.id = c.source_id "
        f"WHERE c.target_system='ccss' AND c.target_id IN ({placeholders}) "
        f"  AND c.source_system IN ({sys_ph})",
        list(ids) + list(SYSTEM_META),
    ):
        key = (r["ccss"], r["sys"])
        prev = best.get(key)
        if prev is None or (r["conf"] or 0) > prev[2]:
            best[key] = [r["sys"], r["sid"], round(r["conf"] or 0, 2), r["grade"], (r["text"] or "")[:110]]
    con.close()

    intl: dict = {}
    for (ccss, _sys), row in best.items():
        intl.setdefault(ccss, []).append(row)

    data = json.dumps(
        {"nodes": nodes, "edges": edges, "intl": intl, "meta": SYSTEM_META},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    html = TEMPLATE.replace("__DATA__", data)
    Path(out_path).write_text(html)
    n_rows = sum(len(v) for v in intl.values())
    print(
        f"wrote {out_path}: {len(nodes)} nodes, {len(edges)} edges, "
        f"{n_rows} intl crosswalks across {len(intl)} nodes, {len(html)} bytes"
    )


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / ".standardgraph/common_core.db")
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/viz/concept_map.html"
    build(db, out)
