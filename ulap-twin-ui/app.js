/* ULAP · Barbados RF Digital Twin — canvas engine
   Brand: Amini (Space Black / Marble White / Sunglow). Dark-first. */
(() => {
'use strict';
const D = window.TWIN_DATA;
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');

// ---------- palette ----------
const C = {
  black:'#121212', white:'#FFFFFF', sun:'#FFC83C',
  charcoal:'#202020', eerie:'#1A1A1A',
  strong:'#7CFF9B', weak:'#ff5a5a'
};

// ---------- geo bounds ----------
const B = (() => {
  let minx=Infinity,miny=Infinity,maxx=-Infinity,maxy=-Infinity;
  for (const b of D.buildings) for (const [x,y] of b.r){
    if(x<minx)minx=x; if(x>maxx)maxx=x; if(y<miny)miny=y; if(y>maxy)maxy=y;
  }
  for (const t of D.towers){
    minx=Math.min(minx,t.lon); maxx=Math.max(maxx,t.lon);
    miny=Math.min(miny,t.lat); maxy=Math.max(maxy,t.lat);
  }
  return {minx,miny,maxx,maxy,cx:(minx+maxx)/2,cy:(miny+maxy)/2};
})();

// Web-mercator projection — X and Y in the SAME (radian) units for correct aspect
const mercX = lon => lon*Math.PI/180;
const mercY = lat => Math.log(Math.tan(Math.PI/4 + lat*Math.PI/360));
const MX0=mercX(B.minx), MX1=mercX(B.maxx);
const MY0=mercY(B.miny), MY1=mercY(B.maxy);
const MCX=(MX0+MX1)/2, MCY=(MY0+MY1)/2;

// ---------- view (pan/zoom) ----------
const view = {scale:1, px:0, py:0, base:1};
let W=0,H=0,DPR=1;
function resize(){
  DPR = Math.min(window.devicePixelRatio||1, 2);
  W = window.innerWidth; H = window.innerHeight;
  canvas.width = W*DPR; canvas.height = H*DPR;
  canvas.style.width=W+'px'; canvas.style.height=H+'px';
  ctx.setTransform(DPR,0,0,DPR,0,0);
}
// projection lon/lat -> screen (mercator, uniform units)
function proj(lon,lat){
  const s = view.base*view.scale;
  return [
    (mercX(lon)-MCX)*s + W/2 + view.px,
    -(mercY(lat)-MCY)*s + H/2 + view.py
  ];
}
// fit the study area into the region right of the panel
function fit(){
  const leftPad=360, rightPad=48, topPad=64, botPad=96;
  const availW=W-leftPad-rightPad, availH=H-topPad-botPad;
  const gw=MX1-MX0, gh=MY1-MY0;
  view.base=Math.min(availW/gw, availH/gh)*0.95;
  view.scale=1;
  view.px = leftPad + availW/2 - W/2;
  view.py = topPad + availH/2 - H/2;
}

// ---------- state ----------
const state = {
  base:'twin',
  layers:{coverage:true, rings:true, buildings:true, labels:true},
  towers:D.towers.map((t,i)=>({...t, on:true, id:i,
    az:[Math.random()*360], sel:i===1})),
  pwr:43, freq:3600, rxSens:-100,
  rx:null, // placed receiver {lon,lat}
  analyzed:false, coverPct:0, t:0
};

// Path loss: log-distance model, urban exponent n≈4, ref FSPL at 1 m.
const GAINS = 8; // combined TX/RX antenna gain (dBi)
const PLE = 4.0; // path-loss exponent (dense urban / obstructed)
function fspl1m(){ return 32.44 + 20*Math.log10(state.freq) + 20*Math.log10(0.001); }
function rssAt(d){ return state.pwr + GAINS - (fspl1m() + 10*PLE*Math.log10(Math.max(d,1))); }
// cell radius (m): distance where RSS drops to receiver sensitivity
function cellRadiusM(){
  const budget = state.pwr + GAINS - state.rxSens;
  const d = Math.pow(10, (budget - fspl1m())/(10*PLE));
  return Math.max(120, Math.min(1600, d));
}
// meters -> pixels (measured directly through the projection, robust to CRS)
function m2px(){
  const p1=proj(B.cx, B.cy), p2=proj(B.cx, B.cy+0.001);
  return Math.abs(p2[1]-p1[1])/(0.001*111320);
}

// ---------- drawing ----------
function clear(){
  ctx.fillStyle = C.black;
  ctx.fillRect(0,0,W,H);
  if(state.base==='sat'){
    // faux terrain wash
    const g=ctx.createRadialGradient(W/2,H/2,50,W/2,H/2,Math.max(W,H)*0.7);
    g.addColorStop(0,'#241d12'); g.addColorStop(.5,'#191510'); g.addColorStop(1,'#0e0d0b');
    ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
  }
}

function drawGrid(){
  const s=view.base*view.scale;
  const step = 0.002; // deg
  ctx.lineWidth=1; ctx.strokeStyle='rgba(255,255,255,.035)';
  ctx.beginPath();
  for(let lon=Math.ceil(B.minx/step)*step; lon<=B.maxx; lon+=step){
    const [x0,y0]=proj(lon,B.miny),[x1,y1]=proj(lon,B.maxy);
    ctx.moveTo(x0,y0); ctx.lineTo(x1,y1);
  }
  for(let lat=Math.ceil(B.miny/step)*step; lat<=B.maxy; lat+=step){
    const [x0,y0]=proj(B.minx,lat),[x1,y1]=proj(B.maxx,lat);
    ctx.moveTo(x0,y0); ctx.lineTo(x1,y1);
  }
  ctx.stroke();
}

function drawCoverage(){
  if(!state.layers.coverage) return;
  const r = cellRadiusM()*m2px();
  ctx.save();
  ctx.globalCompositeOperation='screen';
  for(const t of state.towers){
    if(!t.on) continue;
    const [x,y]=proj(t.lon,t.lat);
    const g=ctx.createRadialGradient(x,y,0,x,y,r);
    // green core -> sunglow mid -> red edge -> transparent
    g.addColorStop(0,'rgba(124,255,155,.34)');
    g.addColorStop(0.42,'rgba(255,200,60,.24)');
    g.addColorStop(0.72,'rgba(255,90,90,.16)');
    g.addColorStop(1,'rgba(255,90,90,0)');
    ctx.fillStyle=g;
    ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fill();
  }
  ctx.restore();
}

function drawBuildings(){
  if(!state.layers.buildings) return;
  ctx.lineWidth = 0.7;
  for(const b of D.buildings){
    const r=b.r;
    ctx.beginPath();
    for(let i=0;i<r.length;i++){
      const [x,y]=proj(r[i][0],r[i][1]);
      if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.closePath();
    // height tint
    const h=b.h; const a=Math.min(.9,.18+h/16);
    if(state.base==='twin'){
      ctx.fillStyle=`rgba(46,130,150,${0.10+h/60})`;
      ctx.strokeStyle=`rgba(120,220,255,${0.18+h/40})`;
    } else if(state.base==='sat'){
      ctx.fillStyle=`rgba(40,34,26,${0.55})`;
      ctx.strokeStyle=`rgba(255,200,60,${0.10+h/50})`;
    } else {
      ctx.fillStyle=`rgba(255,255,255,${0.045+h/120})`;
      ctx.strokeStyle=`rgba(255,255,255,${0.14+h/50})`;
    }
    ctx.fill(); ctx.stroke();
  }
}

// animated propagation rings
function drawRings(){
  if(!state.layers.rings) return;
  const r = cellRadiusM()*m2px();
  const t = state.t;
  for(const tw of state.towers){
    if(!tw.on) continue;
    const [x,y]=proj(tw.lon,tw.lat);
    // expanding pulses
    for(let k=0;k<3;k++){
      const phase = ((t/2600 + k/3)%1);
      const rr = phase*r;
      const alpha = (1-phase)*0.5*(tw.sel?1:0.6);
      ctx.beginPath(); ctx.arc(x,y,rr,0,Math.PI*2);
      ctx.strokeStyle=`rgba(255,200,60,${alpha})`;
      ctx.lineWidth = tw.sel?1.6:1; ctx.stroke();
    }
    // static reference rings
    ctx.setLineDash([2,5]);
    for(let f=0.33;f<1.01;f+=0.335){
      ctx.beginPath(); ctx.arc(x,y,r*f,0,Math.PI*2);
      ctx.strokeStyle=`rgba(255,200,60,${0.14*(tw.sel?1.4:1)})`;
      ctx.lineWidth=1; ctx.stroke();
    }
    ctx.setLineDash([]);
  }
}

function drawRays(){
  if(!state.rx) return;
  const [rx,ry]=proj(state.rx.lon,state.rx.lat);
  for(const tw of state.towers){
    if(!tw.on) continue;
    const [tx,ty]=proj(tw.lon,tw.lat);
    const d=Math.hypot(tw.lon-state.rx.lon,(tw.lat-state.rx.lat))*111000;
    const strong = d < cellRadiusM();
    ctx.beginPath(); ctx.moveTo(tx,ty); ctx.lineTo(rx,ry);
    ctx.strokeStyle = strong? 'rgba(124,255,155,.55)':'rgba(255,90,90,.4)';
    ctx.setLineDash([4,4]); ctx.lineWidth=1.2; ctx.stroke(); ctx.setLineDash([]);
    // travelling packet
    const p=((state.t/900)%1);
    const px=tx+(rx-tx)*p, py=ty+(ry-ty)*p;
    ctx.beginPath(); ctx.arc(px,py,2.4,0,Math.PI*2);
    ctx.fillStyle=strong?C.strong:C.weak; ctx.fill();
  }
}

function drawTowers(){
  for(const tw of state.towers){
    const [x,y]=proj(tw.lon,tw.lat);
    const dim = !tw.on;
    // glow
    if(tw.on){
      const g=ctx.createRadialGradient(x,y,0,x,y,18);
      g.addColorStop(0,'rgba(255,200,60,.5)'); g.addColorStop(1,'rgba(255,200,60,0)');
      ctx.fillStyle=g; ctx.beginPath(); ctx.arc(x,y,18,0,Math.PI*2); ctx.fill();
    }
    // mast
    ctx.strokeStyle=dim?'rgba(255,255,255,.3)':C.sun;
    ctx.lineWidth= tw.sel?2:1.5;
    ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x,y-14); ctx.stroke();
    // node
    ctx.beginPath(); ctx.arc(x,y,tw.sel?5:4,0,Math.PI*2);
    ctx.fillStyle=dim?'#666':C.sun; ctx.fill();
    ctx.strokeStyle=C.black; ctx.lineWidth=1.5; ctx.stroke();
    if(tw.sel){
      ctx.beginPath(); ctx.arc(x,y,8,0,Math.PI*2);
      ctx.strokeStyle='rgba(255,200,60,.8)'; ctx.lineWidth=1.2; ctx.stroke();
    }
    // label
    if(state.layers.labels){
      const lbl=tw.name.toUpperCase();
      ctx.font='600 10px "Geist Mono", monospace';
      const w=ctx.measureText(lbl).width;
      ctx.fillStyle='rgba(18,18,18,.82)';
      ctx.fillRect(x+10,y-20,w+14,17);
      ctx.strokeStyle='rgba(255,200,60,.35)'; ctx.lineWidth=1; ctx.strokeRect(x+10,y-20,w+14,17);
      ctx.fillStyle=dim?'#888':C.sun; ctx.textBaseline='middle';
      ctx.fillText(lbl,x+17,y-11.5);
      ctx.fillStyle='rgba(255,255,255,.45)'; ctx.font='9px "Geist Mono", monospace';
      ctx.fillText(tw.height+'m '+tw.struct.toUpperCase(), x+17, y+2);
    }
  }
}

function drawRx(){
  if(!state.rx) return;
  const [x,y]=proj(state.rx.lon,state.rx.lat);
  ctx.beginPath(); ctx.arc(x,y,5,0,Math.PI*2);
  ctx.fillStyle=C.white; ctx.fill(); ctx.strokeStyle=C.black; ctx.lineWidth=1.5; ctx.stroke();
  ctx.font='600 9px "Geist Mono", monospace'; ctx.fillStyle=C.white;
  ctx.fillText('RX', x+9, y-4);
}

function frame(ts){
  state.t = ts;
  clear();
  if(state.base!=='sat') drawGrid();
  drawCoverage();
  drawBuildings();
  drawRings();
  drawRays();
  drawTowers();
  drawRx();
  updateFps(ts);
  requestAnimationFrame(frame);
}

// ---------- FPS + telemetry ----------
let lastT=0, frames=0, fps=60, acc=0;
const elFps=document.getElementById('t-fps');
function updateFps(ts){
  frames++; acc+=ts-lastT; lastT=ts;
  if(acc>500){ fps=Math.round(frames/(acc/1000)); frames=0; acc=0; elFps.textContent=Math.min(60,fps); }
}

// ---------- analysis metrics ----------
function computeMetrics(){
  const r = cellRadiusM();
  // coverage % = fraction of buildings within any active cell
  let covered=0, total=0; let rssSum=0;
  for(const b of D.buildings){
    total++;
    const cx=b.r.reduce((s,p)=>s+p[0],0)/b.r.length;
    const cy=b.r.reduce((s,p)=>s+p[1],0)/b.r.length;
    let best=-999;
    for(const tw of state.towers){ if(!tw.on)continue;
      const d=Math.hypot((tw.lon-cx)*Math.cos(B.cy*Math.PI/180),(tw.lat-cy))*111320;
      const rss = rssAt(d);
      if(rss>best) best=rss;
    }
    if(best>=state.rxSens){ covered++; }
    rssSum+=best;
  }
  const pct = total? covered/total*100 : 0;
  const rssP50 = rssSum/total;
  const sinr = Math.max(-3, Math.min(28, (rssP50 - state.rxSens)*0.7 + 2));
  const cells = Math.round((r*r*Math.PI/ (100)) /1000); // faux grid cell count k
  return {pct, rssP50, sinr, r, cells:Math.max(4, cells)};
}

function num(el,to,suffix='',dec=0){
  const o={v:parseFloat(el.dataset.v||'0')};
  anime({targets:o, v:to, duration:900, easing:'easeOutCubic',
    update:()=>{ el.childNodes[0].nodeValue = (dec?o.v.toFixed(dec):Math.round(o.v)); },
    complete:()=>{ el.dataset.v=to; }});
}
function refreshReadout(animated){
  const m=computeMetrics();
  state.coverPct=m.pct;
  const covEl=document.getElementById('m-cov');
  const setTxt=(id,v)=>{const e=document.getElementById(id); e.childNodes[0].nodeValue=v;};
  if(animated){
    num(covEl, m.pct, '', 1);
  } else { covEl.childNodes[0].nodeValue=m.pct.toFixed(1); }
  document.getElementById('m-cov-bar').style.width=Math.min(100,m.pct)+'%';
  setTxt('m-rss', Math.round(m.rssP50));
  setTxt('m-sinr', m.sinr.toFixed(1));
  setTxt('m-rad', Math.round(m.r));
  setTxt('m-cells', m.cells);
}

// ---------- UI: tower list ----------
const towerIcon = `<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round"><path d="M12 8v13"/><path d="M6.5 21l5.5-9 5.5 9"/><path d="M7 6a7 7 0 0110 0M9.5 8.5a3.5 3.5 0 015 0"/><circle cx="12" cy="6" r="1"/></svg>`;
function renderTowers(){
  const list=document.getElementById('tower-list'); list.innerHTML='';
  state.towers.forEach(tw=>{
    const el=document.createElement('div');
    el.className='tower'+(tw.sel?' active':'');
    el.innerHTML=`<div class="ico">${towerIcon}</div>
      <div class="meta"><div class="nm">${tw.name}</div>
      <div class="dt">${tw.code} · ${tw.height}m ${tw.struct}</div></div>
      <div class="sw" title="toggle"></div>`;
    el.querySelector('.sw').classList.toggle('on',tw.on);
    el.querySelector('.meta').onclick=()=>selectTower(tw);
    el.querySelector('.ico').onclick=()=>selectTower(tw);
    el.querySelector('.sw').onclick=(e)=>{e.stopPropagation(); tw.on=!tw.on; renderTowers(); refreshReadout(true);};
    el.classList.toggle('active',tw.sel);
    list.appendChild(el);
  });
  document.getElementById('tx-count').textContent=state.towers.filter(t=>t.on).length+' sites';
}
function selectTower(tw){
  state.towers.forEach(t=>t.sel=false); tw.sel=true; tw.on=true;
  renderTowers();
  toast(`Focused ${tw.name} — ${tw.height}m ${tw.struct}`);
}

// ---------- sliders ----------
function bindSlider(id,fmt,onchange){
  const s=document.getElementById(id);
  const upd=()=>{ const min=+s.min,max=+s.max; s.style.setProperty('--fill',((s.value-min)/(max-min)*100)+'%'); onchange(+s.value); };
  s.addEventListener('input',upd); upd();
}
bindSlider('s-pwr', v=>v, v=>{ state.pwr=v; document.getElementById('v-pwr').textContent=v+' dBm'; refreshReadout(false); });
bindSlider('s-freq', v=>v, v=>{ state.freq=v; document.getElementById('v-freq').textContent=v+' MHz';
  const band = v<1000?'n71':v<2200?'n1':v<2700?'n7':v<4000?'n78':'n79';
  document.getElementById('p-band').textContent=band+' · '+(v/1000).toFixed(1)+' GHz';
  refreshReadout(false); });
bindSlider('s-rx', v=>v, v=>{ state.rxSens=v; document.getElementById('v-rx').textContent=v+' dBm'; refreshReadout(false); });

// ---------- layer toggles ----------
document.querySelectorAll('.layer').forEach(l=>{
  l.onclick=()=>{ const k=l.dataset.layer; state.layers[k]=!state.layers[k]; l.classList.toggle('on',state.layers[k]);
    const n=Object.values(state.layers).filter(Boolean).length; document.getElementById('l-count').textContent=n+' / 4'; };
});

// ---------- basemap dock ----------
document.querySelectorAll('.dock button').forEach(b=>{
  b.onclick=()=>{ document.querySelectorAll('.dock button').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); state.base=b.dataset.base; toast('Basemap · '+b.textContent.trim()); };
});

// ---------- zoom / pan ----------
document.getElementById('zin').onclick=()=>zoomBy(1.25);
document.getElementById('zout').onclick=()=>zoomBy(0.8);
function zoomBy(f){ view.scale=Math.max(0.5,Math.min(6,view.scale*f)); updZoomLabel(); }
function updZoomLabel(){ document.getElementById('t-zoom').textContent=(14+Math.log2(view.scale)).toFixed(1); }
canvas.addEventListener('wheel',e=>{ e.preventDefault();
  const f = e.deltaY<0?1.1:0.9;
  const before = screenToGeo(e.clientX,e.clientY); // geo under cursor
  view.scale=Math.max(0.5,Math.min(6,view.scale*f));
  // recompute pan so the same geo point stays under the cursor
  const s=view.base*view.scale;
  view.px = e.clientX - ((mercX(before.lon)-MCX)*s + W/2);
  view.py = e.clientY - (-(mercY(before.lat)-MCY)*s + H/2);
  updZoomLabel();
},{passive:false});

let drag=null;
canvas.addEventListener('pointerdown',e=>{ drag={x:e.clientX,y:e.clientY,px:view.px,py:view.py,moved:false}; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener('pointermove',e=>{
  if(drag){ view.px=drag.px+(e.clientX-drag.x); view.py=drag.py+(e.clientY-drag.y);
    if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>3)drag.moved=true; }
  else hover(e);
  // update lat/lng telemetry
  const g=screenToGeo(e.clientX,e.clientY);
  document.getElementById('t-lat').textContent=g.lat.toFixed(4)+'°';
  document.getElementById('t-lng').textContent=(g.lon<0?'−':'')+Math.abs(g.lon).toFixed(4)+'°';
});
canvas.addEventListener('pointerup',e=>{
  if(drag && !drag.moved){ onClick(e); }
  drag=null;
});
function screenToGeo(sx,sy){
  const s=view.base*view.scale;
  const mx = (sx - W/2 - view.px)/s + MCX;
  const myv = -(sy - H/2 - view.py)/s + MCY;
  const lon = mx*180/Math.PI;
  const lat = (Math.atan(Math.exp(myv))*360/Math.PI - 90);
  return {lon,lat};
}

// ---------- hover tooltip ----------
const tip=document.getElementById('tip');
function hover(e){
  // tower hit test
  for(const tw of state.towers){
    const [x,y]=proj(tw.lon,tw.lat);
    if(Math.hypot(e.clientX-x,e.clientY-y)<12){
      showTip(e, tw.name, [['Code',tw.code],['Height',tw.height+' m'],['Type',tw.struct],['Status',tw.on?'ACTIVE':'OFF']]);
      canvas.style.cursor='pointer'; return;
    }
  }
  canvas.style.cursor= drag?'grabbing':'crosshair';
  hideTip();
}
function showTip(e,title,rows){
  tip.innerHTML=`<div class="tt">${title}</div>`+rows.map(r=>`<div class="tr"><span>${r[0]}</span><b>${r[1]}</b></div>`).join('');
  tip.style.left=Math.min(e.clientX+14,W-230)+'px'; tip.style.top=(e.clientY+14)+'px';
  tip.classList.add('show');
}
function hideTip(){ tip.classList.remove('show'); }

function onClick(e){
  // tower?
  for(const tw of state.towers){
    const [x,y]=proj(tw.lon,tw.lat);
    if(Math.hypot(e.clientX-x,e.clientY-y)<12){ selectTower(tw); return; }
  }
  // place RX
  const g=screenToGeo(e.clientX,e.clientY);
  state.rx=g;
  // link metrics
  let best=-999,bestTw=null;
  for(const tw of state.towers){ if(!tw.on)continue;
    const d=Math.hypot((tw.lon-g.lon)*Math.cos(B.cy*Math.PI/180),(tw.lat-g.lat))*111320;
    const rss=rssAt(d); if(rss>best){best=rss;bestTw=tw;}
  }
  const q = best>-75?'STRONG':best>-95?'USABLE':'WEAK';
  toast(`RX placed · ${Math.round(best)} dBm from ${bestTw?bestTw.name:'—'} · ${q}`);
}

// ---------- run analysis ----------
document.getElementById('run').onclick=()=>{
  const btn=document.getElementById('run');
  btn.style.pointerEvents='none';
  const orig=btn.innerHTML;
  btn.innerHTML='<span class="mono">TRACING RAYS…</span>';
  // sweep pulse
  anime({targets:{p:0},p:1,duration:1200,easing:'easeInOutQuad',complete:()=>{
    state.analyzed=true; refreshReadout(true);
    btn.innerHTML=orig; btn.style.pointerEvents='auto';
    const m=computeMetrics();
    toast(`Analysis complete · ${m.pct.toFixed(1)}% coverage · ${Math.round(m.r)} m cells`);
  }});
  toast('Computing propagation paths…');
};

// ---------- toast ----------
let toastTimer;
function toast(msg){
  document.getElementById('toast-msg').textContent=msg;
  const t=document.getElementById('toast'); t.classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.remove('show'),2600);
}

// ---------- clock ----------
setInterval(()=>{
  const el=document.getElementById('t-clock');
  el.textContent = el.textContent==='LIVE' ? '● REC' : 'LIVE';
},2000);

// ---------- intro ----------
function runIntro(){
  const wm=document.querySelector('.intro .wm'), il=document.querySelector('.intro .il');
  anime.timeline({easing:'easeOutExpo'})
    .add({targets:wm,opacity:[0,1],translateY:[12,0],duration:700})
    .add({targets:il,opacity:[0,1],duration:500},'-=300')
    .add({targets:'#iprog',width:['0%','100%'],duration:1100,easing:'easeInOutQuad'},'-=200');
  setTimeout(()=>{
    const intro=document.getElementById('intro'); intro.style.opacity=0;
    setTimeout(()=>intro.remove(),820);
    // panel entrance
    anime({targets:'.panel',opacity:[0,1],translateX:[-24,0],duration:700,easing:'easeOutExpo'});
    anime({targets:'.readout',opacity:[0,1],translateX:[24,0],duration:700,delay:120,easing:'easeOutExpo'});
    anime({targets:'.dock,.zoomer',opacity:[0,1],translateY:[16,0],duration:700,delay:220,easing:'easeOutExpo'});
    anime({targets:'.topbar',opacity:[0,1],duration:600});
    anime({targets:'.tower',opacity:[0,1],translateX:[-14,0],delay:anime.stagger(90,{start:300}),easing:'easeOutExpo'});
    refreshReadout(true);
    toast('Barbados Digital Twin · 576 buildings · 2 active sites');
  },1900);
}

// ---------- boot ----------
window.addEventListener('resize',()=>{resize();fit();});
resize(); fit(); updZoomLabel();
renderTowers();
document.getElementById('m-cov').dataset.v=0;
requestAnimationFrame(frame);
try { runIntro(); } catch(err){ console.warn('intro skipped',err); refreshReadout(false); }
// hard failsafe: never let the intro overlay trap the view
setTimeout(()=>{ const i=document.getElementById('intro'); if(i) i.remove(); }, 2600);
})();
