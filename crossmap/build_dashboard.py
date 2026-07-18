"""Cross-Map Network QA/QC dashboard (Stage 2) — renders reports/<CID>/dashboard_data.json.

Fully SELF-CONTAINED: no internet, no tiles, no CDN. Left panel is an inline-SVG map whose basemap
is the real road network (from arizona.pbf), with the reference corridor + each source's matched
alignment + clickable issue points on top (wheel-zoom / drag-pan). Right panel: synchronized
linear corridor strips on one milepost axis (segmentation preserved, bar thickness = lanes) +
reasoned issue cards + review lifecycle. (Satellite imagery can overlay later when online.)
"""
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def render(cid):
    rdir = os.path.join(BASE, "reports", cid)
    d = json.load(open(os.path.join(rdir, "dashboard_data.json"), encoding="utf-8"))
    reviews = list(csv.DictReader(open(os.path.join(rdir, "review_log.csv"), encoding="utf-8-sig")))
    for r in reviews:                              # demo: pre-verify one high-confidence issue
        if r["issue_type"] == "LANE_PROVENANCE" and r["status"] == "Detected":
            r["status"] = "Verified"; r["verdict"] = "valid issue"; r["reviewer"] = "demo"
            r["resolution"] = "Overture lane inventory is class-default; flag for update"
            break
    payload = json.dumps({**d, "reviews": reviews}, separators=(",", ":"), ensure_ascii=False)
    out = os.path.join(rdir, f"{cid}_dashboard.html")
    open(out, "w", encoding="utf-8").write(TEMPLATE.replace("/*DATA*/null", payload))
    print(f"wrote {out}  ({os.path.getsize(out)/1024:.0f} KB)  — self-contained, opens offline")
    return out


TEMPLATE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Cross-Map Network QA/QC</title>
<style>
:root{--bg:#0f141a;--card:#1a212b;--ink:#e6edf3;--mut:#9aa7b4;--line:#2b3542;
--crit:#fc8181;--hi:#f6ad55;--med:#f6e05e;--lo:#90cdf4}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:12px 18px;border-bottom:1px solid var(--line)}
h1{font-size:19px;margin:0}.sub{color:var(--mut);font-size:12.5px}
.ban{display:inline-block;margin-top:6px;padding:2px 10px;border-radius:5px;background:#2a2410;color:#e6d38a;border:1px solid #4a3f1a;font-size:12px}
.legend{margin-top:8px;display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px}
.legend b{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:middle}
.wrap{display:grid;grid-template-columns:1fr 1fr;gap:0;height:calc(100vh - 96px)}
@media(max-width:900px){.wrap{grid-template-columns:1fr;height:auto}}
.mapwrap{position:relative;height:100%;min-height:440px;background:#0c1116;border-right:1px solid var(--line)}
#map{width:100%;height:100%;cursor:grab;touch-action:none}#map:active{cursor:grabbing}
.maphint{position:absolute;left:8px;bottom:8px;font-size:11px;color:#6b7684;background:#0c1116cc;padding:2px 7px;border-radius:4px}
.mapctl{position:absolute;right:8px;top:8px;display:flex;gap:4px}
.mapctl button{background:#1a212b;color:var(--ink);border:1px solid var(--line);border-radius:5px;width:28px;height:28px;font-size:16px;cursor:pointer}
.maptog{position:absolute;left:8px;top:8px;background:#0c1116d8;border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px}
.maptog label{display:block;cursor:pointer;user-select:none;line-height:1.7}
.maptog b{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 5px 0 3px;vertical-align:middle}
.maptog input{vertical-align:middle;margin:0}
.right{overflow-y:auto;padding:14px 16px;height:100%}
h2{font-size:14px;margin:4px 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
svg.strip{display:block;background:#0c1116;border:1px solid var(--line);border-radius:6px;width:100%}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mut);border-radius:8px;padding:9px 11px;margin-bottom:9px;cursor:pointer}
.card:hover{border-color:#4a90d9}.card.flash{outline:2px solid #90cdf4}
.card.high{border-left-color:var(--hi)}.card.medium{border-left-color:var(--med)}.card.low{border-left-color:var(--lo)}
.card .h{font-weight:700;font-size:13px}.card .m{color:var(--mut);font-size:12px;margin-top:3px}
.tag{font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:9px;background:#243040;color:#cbd5e0;margin-left:6px}
.life{display:flex;gap:3px;margin-top:6px;font-size:10px;flex-wrap:wrap}
.life span{padding:1px 6px;border-radius:8px;background:#20293480;color:#6b7684}
.life span.on{background:#22543d;color:#9ae6b4}.life span.now{background:#2a4365;color:#90cdf4;font-weight:700}
.pill{font-size:10.5px;color:var(--mut)}
circle.im{cursor:pointer}circle.im:hover{stroke:#fff}
</style></head><body>
<header>
<h1>One-to-Many Corridor Inventory &amp; Cross-Map Comparison <span class=pill id=corr></span></h1>
<div class=sub id=ruler></div>
<div class=ban id=ban>Report-only — no source network is modified · offline self-contained map (satellite overlay optional when online)</div>
<div class=legend id=legend></div>
</header>
<div class=wrap>
  <div class=mapwrap><svg id=map></svg>
    <div class=maptog id=maptog></div>
    <div class=mapctl><button id=zin>+</button><button id=zout>&minus;</button><button id=zfit title="fit">&#9723;</button></div>
    <div class=maphint>each source is offset into its own colored strand (nodes = dots) · scroll to zoom, drag to pan · toggle layers ↖</div>
  </div>
  <div class=right>
    <h2>Synchronized corridor strips <span class=pill>(one milepost axis · segmentation preserved · bar thickness = lanes)</span></h2>
    <div id=strips></div>
    <h2 style="margin-top:16px">Reasoned QA/QC issues <span class=pill id=icount></span></h2>
    <div id=issues></div>
  </div>
</div>
<script>
const D=/*DATA*/null;
const PAL=['#38a169','#9f7aea','#dd6b20','#3182ce','#e53e3e','#38b2ac'];
const COL={};D.sources.forEach((s,i)=>COL[s]=PAL[i%PAL.length]);
const CC={high:'#f6ad55',medium:'#f6e05e',low:'#90cdf4'};
document.getElementById('corr').textContent='· '+D.corridor;
document.getElementById('ruler').textContent=D.ruler_note;
document.getElementById('legend').innerHTML=D.sources.map(s=>{
  const ex=D.extents[s]?` MP ${D.extents[s][0]}–${D.extents[s][1]}`:'';
  const pt=D.partial&&D.partial[s]?' *partial':'';
  return `<span><b style="background:${COL[s]}"></b>${s} <span class=pill>${D.roles[s]||''}${ex}${pt}</span></span>`;
}).join('') + `<span><b style="background:#33404d"></b><span class=pill>basemap roads (arizona.pbf)</span></span>`;

// ---------- inline SVG map (offline; no tiles) ----------
const svg=document.getElementById('map');
const flat=a=>a.reduce((o,x)=>o.concat(x),[]);
const allpts=flat(D.context).concat(D.reference.map(p=>[p[0],p[1]]),
                  flat(D.sources.map(s=>flat(D.geom[s].map(g=>g.c||[])))));
const lons=allpts.map(p=>p[0]),lats=allpts.map(p=>p[1]);
const minlon=Math.min(...lons),maxlon=Math.max(...lons),minlat=Math.min(...lats),maxlat=Math.max(...lats);
const kx=Math.cos((minlat+maxlat)/2*Math.PI/180);
const PW=(maxlon-minlon)*kx||1, PH=(maxlat-minlat)||1, M=PW*0.04;
const px=lon=>(lon-minlon)*kx, py=lat=>(maxlat-lat);
const proj=c=>c.map(p=>[px(p[0]),py(p[1])]);
const dP=P=>P.map((p,i)=>(i?'L':'M')+p[0].toFixed(5)+' '+p[1].toFixed(5)).join('');
// offset a projected polyline sideways by o (perpendicular to local direction) -> parallel strand
function offset(P,o){const O=[];for(let i=0;i<P.length;i++){
  const a=P[Math.max(0,i-1)],b=P[Math.min(P.length-1,i+1)];
  let dx=b[0]-a[0],dy=b[1]-a[1];const L=Math.hypot(dx,dy)||1;
  O.push([P[i][0]-dy/L*o, P[i][1]+dx/L*o]);}return O;}
const w=PW/650, n=D.sources.length, spc=PW/150;
let g='';
// basemap roads (dim)
g+=`<g id="lyr-base" stroke="#2b3947" stroke-width="${w}" fill="none" stroke-linecap="round">`;
for(const c of D.context) g+=`<path d="${dP(proj(c))}"/>`; g+='</g>';
// reference centerline (thin dashed, under the source strands)
g+=`<g id="lyr-ref"><path d="${dP(proj(D.reference.map(p=>[p[0],p[1]])))}" stroke="#e2e8f0" `+
   `stroke-width="${w*1.6}" fill="none" stroke-dasharray="${w*7} ${w*5}" opacity="0.8"/></g>`;
// each source = its own parallel offset strand of links + nodes
D.sources.forEach((s,si)=>{const o=(si-(n-1)/2)*spc;let links='',nodes='';
  for(const seg of D.geom[s]){if(!seg.c||seg.c.length<2)continue;
    const P=offset(proj(seg.c),o);links+=`<path d="${dP(P)}"/>`;
    const a=P[0],b=P[P.length-1];
    nodes+=`<circle cx="${a[0].toFixed(5)}" cy="${a[1].toFixed(5)}" r="${w*2.1}"/>`+
           `<circle cx="${b[0].toFixed(5)}" cy="${b[1].toFixed(5)}" r="${w*2.1}"/>`;}
  g+=`<g id="lyr-${s}"><g stroke="${COL[s]}" stroke-width="${w*2.4}" fill="none" opacity="0.92" stroke-linecap="round">${links}</g>`+
     `<g fill="${COL[s]}" stroke="#0c1116" stroke-width="${w*0.5}">${nodes}</g></g>`;});
// issue markers (top layer)
function mp2lonlat(mp){const R=D.reference;for(let i=0;i<R.length-1;i++){const a=R[i],b=R[i+1];
  if(mp<=b[2]||i===R.length-2){const t=b[2]===a[2]?0:(mp-a[2])/(b[2]-a[2]);
    return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];}}return [R[0][0],R[0][1]];}
let im='';D.issues.forEach((it,i)=>{const q=mp2lonlat(it.mp);
  im+=`<circle class=im data-i="${i}" cx="${px(q[0]).toFixed(5)}" cy="${py(q[1]).toFixed(5)}" r="${PW/110}" `+
      `fill="${CC[it.conf]}" stroke="#0c1116" stroke-width="${PW/1400}"><title>${it.type} · MP ${it.mp} · ${it.conf}</title></circle>`;});
g+=`<g id="lyr-iss">${im}</g>`;
svg.innerHTML=g;
// layer toggles
const layers=[['base','basemap','#2b3947'],['ref','reference','#e2e8f0'],
              ...D.sources.map(s=>[s,s,COL[s]]),['iss','issues','#f6ad55']];
document.getElementById('maptog').innerHTML=layers.map(([id,lab,col])=>
  `<label><input type=checkbox checked data-l="${id}"><b style="background:${col}"></b>${lab}</label>`).join('');
document.getElementById('maptog').addEventListener('change',e=>{
  const gr=document.getElementById('lyr-'+e.target.dataset.l);if(gr)gr.style.display=e.target.checked?'':'none';});
// zoom / pan via viewBox
let vb={x:-M,y:-M,w:PW+2*M,h:PH+2*M};
const setVB=()=>svg.setAttribute('viewBox',`${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
const fit=()=>{vb={x:-M,y:-M,w:PW+2*M,h:PH+2*M};setVB();}; fit();
function zoomAt(cx,cy,f){const r=svg.getBoundingClientRect();
  const mx=vb.x+(cx-r.left)/r.width*vb.w, my=vb.y+(cy-r.top)/r.height*vb.h;
  vb.w*=f;vb.h*=f; vb.x=mx-(cx-r.left)/r.width*vb.w; vb.y=my-(cy-r.top)/r.height*vb.h; setVB();}
svg.addEventListener('wheel',e=>{e.preventDefault();zoomAt(e.clientX,e.clientY,e.deltaY<0?0.82:1.22);},{passive:false});
let drag=null;
svg.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,vx:vb.x,vy:vb.y};});
window.addEventListener('mousemove',e=>{if(!drag)return;const r=svg.getBoundingClientRect();
  vb.x=drag.vx-(e.clientX-drag.x)/r.width*vb.w; vb.y=drag.vy-(e.clientY-drag.y)/r.height*vb.h; setVB();});
window.addEventListener('mouseup',()=>drag=null);
document.getElementById('zin').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,0.7);};
document.getElementById('zout').onclick=()=>{const r=svg.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,1.43);};
document.getElementById('zfit').onclick=fit;
svg.addEventListener('click',e=>{const c=e.target.closest('.im');if(c)focusCard(+c.dataset.i);});

// ---------- linear strips ----------
const L0=Math.min(...D.reference.map(p=>p[2])),L1=Math.max(...D.reference.map(p=>p[2]));
const SW=Math.max(360,Math.round((L1-L0)*22)),padL=6;
const sx=mp=>padL+(mp-L0)/(L1-L0)*(SW-2*padL);
const maxLane=Math.max(3,...D.sources.flatMap(s=>D.geom[s].map(g=>g.lanes||0)));
let defs='<defs>';for(const s of D.sources){defs+=`<pattern id="h${s}" width="4" height="4" patternTransform="rotate(45)" patternUnits="userSpaceOnUse"><rect width="4" height="4" fill="${COL[s]}" opacity="0.3"/><line x1="0" y1="0" x2="0" y2="4" stroke="${COL[s]}" stroke-width="1.5"/></pattern>`;}defs+='</defs>';
let st=`<svg class=strip viewBox="0 0 ${SW} ${D.sources.length*46+30}" height="${D.sources.length*46+30}">${defs}`;
for(let mp=Math.ceil(L0);mp<=L1;mp+=Math.max(1,Math.round((L1-L0)/15))){
  st+=`<line x1="${sx(mp)}" y1="16" x2="${sx(mp)}" y2="${D.sources.length*46+22}" stroke="#1b2530"/><text x="${sx(mp)}" y="12" fill="#6b7684" font-size="9" text-anchor="middle">${mp}</text>`;}
D.issues.forEach(it=>{st+=`<rect x="${sx(it.mp)-1.5}" y="15" width="3" height="6" fill="${CC[it.conf]}"/>`;});
D.sources.forEach((s,si)=>{const y0=26+si*46;
  st+=`<text x="${padL}" y="${y0-2}" fill="${COL[s]}" font-size="10" font-weight="700">${s}</text>`;
  for(const gg of D.geom[s]){const xa=sx(Math.min(gg.mp0,gg.mp1)),xb=sx(Math.max(gg.mp0,gg.mp1));
    const h=Math.max(3,(gg.lanes||1)/maxLane*22),yy=y0+6+(22-h)/2,wd=Math.max(1,xb-xa);
    st+=`<rect x="${xa}" y="${yy}" width="${wd}" height="${h}" fill="${gg.inf?`url(#h${s})`:COL[s]}" opacity="0.9"><title>${s} MP ${(+gg.mp0).toFixed(1)}–${(+gg.mp1).toFixed(1)} · ${gg.lanes||'?'}L ${gg.speed||'?'}mph${gg.inf?' (inferred)':''}</title></rect>`;}});
st+='</svg><div class=pill style="margin-top:4px">hatched = attribute is an inferred class-default (not surveyed)</div>';
document.getElementById('strips').innerHTML=st;

// ---------- issue cards ----------
const LIFE=['Detected','Reviewed','Verified','Assigned','Corrected','Revalidated'];
const rev={};D.reviews.forEach(r=>rev[r.mp_bin+'|'+r.issue_type]=r);
document.getElementById('icount').textContent=`(${D.issues.length})`;
document.getElementById('issues').innerHTML=D.issues.map((it,i)=>{
  const r=rev[it.mp+'|'+it.type]||{status:'Detected'};const si=LIFE.indexOf(r.status);
  const life=LIFE.map((L,k)=>`<span class="${k<si?'on':k===si?'now':''}">${L}</span>`).join('');
  return `<div class="card ${it.conf}" id="c${i}" onclick="focusMap(${i})">
    <div class=h>${it.type} <span class=tag>MP ${it.mp}</span> <span class=tag>${it.conf}</span></div>
    <div class=m>${it.why}</div><div class=life>${life}</div>
    ${r.resolution?`<div class=m style="color:#9ae6b4">✓ ${r.resolution}</div>`:''}</div>`;}).join('');
function focusMap(i){const it=D.issues[i];const q=mp2lonlat(it.mp);const s=PW*0.12;
  vb={x:px(q[0])-s/2,y:py(q[1])-s*PH/PW/2,w:s,h:s*PH/PW};setVB();
  const c=svg.querySelector(`.im[data-i="${i}"]`);if(c){c.setAttribute('r',PW/60);setTimeout(()=>c.setAttribute('r',PW/110),700);}}
function focusCard(i){const el=document.getElementById('c'+i);el.scrollIntoView({behavior:'smooth',block:'center'});
  el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),1200);}
</script></body></html>"""


if __name__ == "__main__":
    for cid in (sys.argv[1:] or ["I10_EB"]):
        render(cid)
