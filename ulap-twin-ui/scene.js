/* ULAP · Barbados 3D Ray-Trace Scene — Three.js viewer in the style of
   NVIDIA's sionna-rt-gui: extruded buildings, ray paths, and a viridis radio
   map computed with real line-of-sight shadowing over the height field. */
(() => {
'use strict';
const D = window.TWIN_DATA;
const THREE = window.THREE;

/* ---------------- geo -> local ENU metres ---------------- */
let minLon=Infinity,maxLon=-Infinity,minLat=Infinity,maxLat=-Infinity;
for (const b of D.buildings) for (const [lo,la] of b.r){
  if(lo<minLon)minLon=lo; if(lo>maxLon)maxLon=lo; if(la<minLat)minLat=la; if(la>maxLat)maxLat=la;
}
for (const t of D.towers){ minLon=Math.min(minLon,t.lon);maxLon=Math.max(maxLon,t.lon);
  minLat=Math.min(minLat,t.lat);maxLat=Math.max(maxLat,t.lat); }
const lon0=(minLon+maxLon)/2, lat0=(minLat+maxLat)/2;
const mPerLon=111320*Math.cos(lat0*Math.PI/180), mPerLat=111320;
// world: X = east(m), Z = -north(m), Y = up
const toX = lon => (lon-lon0)*mPerLon;
const toZ = lat => -(lat-lat0)*mPerLat;
const EXT = { x0:toX(minLon), x1:toX(maxLon), z0:toZ(maxLat), z1:toZ(minLat) };
const MARGIN=140;
const WX0=EXT.x0-MARGIN, WX1=EXT.x1+MARGIN, WZ0=EXT.z0-MARGIN, WZ1=EXT.z1+MARGIN;
const WW=WX1-WX0, WH=WZ1-WZ0;

const towers = D.towers.map((t,i)=>({...t, id:i, x:toX(t.lon), z:toZ(t.lat), sel:i===1}));

/* ---------------- height field (rasterised footprints) ---------------- */
const GN=Math.round(Math.max(WW,WH)/4); // ~4 m cells
const HGX=GN, HGZ=Math.round(GN*WH/WW);
const HEIGHT=new Float32Array(HGX*HGZ);
const gx=x=>Math.round((x-WX0)/WW*(HGX-1));
const gz=z=>Math.round((z-WZ0)/WH*(HGZ-1));
function rasterise(){
  for(const b of D.buildings){
    const pts=b.r.map(([lo,la])=>[toX(lo),toZ(la)]);
    let bx0=1e9,bx1=-1e9,bz0=1e9,bz1=-1e9;
    for(const[px,pz]of pts){bx0=Math.min(bx0,px);bx1=Math.max(bx1,px);bz0=Math.min(bz0,pz);bz1=Math.max(bz1,pz);}
    const i0=gx(bx0),i1=gx(bx1),j0=gz(bz0),j1=gz(bz1);
    for(let j=j0;j<=j1;j++)for(let i=i0;i<=i1;i++){
      const wx=WX0+i/(HGX-1)*WW, wz=WZ0+j/(HGZ-1)*WH;
      if(pointIn(pts,wx,wz)){ const k=j*HGX+i; if(b.h>HEIGHT[k])HEIGHT[k]=b.h; }
    }
  }
}
function pointIn(poly,x,z){ let c=false;
  for(let i=0,j=poly.length-1;i<poly.length;j=i++){
    const xi=poly[i][0],zi=poly[i][1],xj=poly[j][0],zj=poly[j][1];
    if(((zi>z)!==(zj>z)) && (x < (xj-xi)*(z-zi)/(zj-zi)+xi)) c=!c;
  } return c;
}
function heightAtGrid(i,j){ if(i<0||j<0||i>=HGX||j>=HGZ)return 0; return HEIGHT[j*HGX+i]; }
// DDA line-of-sight over the height field. returns true if BLOCKED.
function losBlocked(x0,y0,z0, x1,y1,z1){
  const i0=(x0-WX0)/WW*(HGX-1), j0=(z0-WZ0)/WH*(HGZ-1);
  const i1=(x1-WX0)/WW*(HGX-1), j1=(z1-WZ0)/WH*(HGZ-1);
  const steps=Math.max(2,Math.ceil(Math.hypot(i1-i0,j1-j0)));
  for(let s=1;s<steps;s++){
    const t=s/steps, ii=Math.round(i0+(i1-i0)*t), jj=Math.round(j0+(j1-j0)*t);
    const rayY=y0+(y1-y0)*t, h=heightAtGrid(ii,jj);
    if(h>rayY+0.6) return true;
  }
  return false;
}

/* ---------------- viridis colormap ---------------- */
const VIR=[[68,1,84],[72,40,120],[62,74,137],[49,104,142],[38,130,142],[31,158,137],[53,183,121],[110,206,88],[181,222,43],[253,231,37]];
function viridis(t){ t=Math.max(0,Math.min(1,t)); const f=t*(VIR.length-1); const i=Math.floor(f),k=f-i;
  const a=VIR[i],b=VIR[Math.min(i+1,VIR.length-1)];
  return [a[0]+(b[0]-a[0])*k, a[1]+(b[1]-a[1])*k, a[2]+(b[2]-a[2])*k]; }

/* ---------------- three basics ---------------- */
const canvas=document.getElementById('gl');
const renderer=new THREE.WebGLRenderer({canvas,antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setClearColor(0x0c0c0e,1);
const scene=new THREE.Scene();
scene.fog=new THREE.Fog(0x0c0c0e, WW*0.9, WW*2.4);
const camera=new THREE.PerspectiveCamera(46, innerWidth/innerHeight, 1, WW*6);
const controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true; controls.dampingFactor=0.08;
controls.maxPolarAngle=Math.PI*0.49; controls.minDistance=120; controls.maxDistance=WW*2.2;

scene.add(new THREE.HemisphereLight(0xbfd3ff,0x141410,0.85));
const sun=new THREE.DirectionalLight(0xfff2d8,1.15); sun.position.set(-0.5,1,0.35); scene.add(sun);

/* ---------------- buildings (merged extrusions) ---------------- */
function buildBuildings(){
  const geos=[];
  for(const b of D.buildings){
    const shape=new THREE.Shape();
    b.r.forEach(([lo,la],k)=>{ const X=toX(lo), Nz=-toZ(la); // shape XY: X east, Y north
      k===0?shape.moveTo(X,Nz):shape.lineTo(X,Nz); });
    const g=new THREE.ExtrudeGeometry(shape,{depth:Math.max(b.h,2),bevelEnabled:false});
    g.rotateX(-Math.PI/2); // Z(up)->Y up ; Y(north)-> -Z
    geos.push(g);
  }
  const merged=THREE.BufferGeometryUtils.mergeBufferGeometries(geos,false);
  const mat=new THREE.MeshStandardMaterial({color:0xb2b7bf,roughness:0.96,metalness:0.0,flatShading:true});
  const mesh=new THREE.Mesh(merged,mat);
  scene.add(mesh);
  // subtle edge overlay for definition
  const eg=new THREE.EdgesGeometry(merged,32);
  scene.add(new THREE.LineSegments(eg,new THREE.LineBasicMaterial({color:0x2a2d33,transparent:true,opacity:0.5})));
}

/* ---------------- ground + radio-map texture ---------------- */
const RM=220; const RMZ=Math.round(RM*WH/WW);
const rmCanvas=document.createElement('canvas'); rmCanvas.width=RM; rmCanvas.height=RMZ;
const rmCtx=rmCanvas.getContext('2d');
const rmTex=new THREE.CanvasTexture(rmCanvas); rmTex.minFilter=THREE.LinearFilter;
const gridTex=makeGridTexture();
const groundMat=new THREE.MeshBasicMaterial({map:gridTex});
const ground=new THREE.Mesh(new THREE.PlaneGeometry(WW,WH),groundMat);
ground.rotation.x=-Math.PI/2;
ground.position.set((WX0+WX1)/2,0,(WZ0+WZ1)/2);
scene.add(ground);
function makeGridTexture(){
  const c=document.createElement('canvas'); c.width=c.height=512; const x=c.getContext('2d');
  x.fillStyle='#141417'; x.fillRect(0,0,512,512);
  x.strokeStyle='rgba(255,255,255,.05)'; x.lineWidth=1;
  for(let i=0;i<=32;i++){const p=i/32*512; x.beginPath();x.moveTo(p,0);x.lineTo(p,512);x.moveTo(0,p);x.lineTo(512,p);x.stroke();}
  const t=new THREE.CanvasTexture(c); return t;
}

const state={mode:'radio', tx:1, steer:0, pwr:43, depth:3, rx:null};
const GAINS=8, PLE_LOS=2.3, PLE_N=3.7, FREQ=3500;
const fspl1m=32.44+20*Math.log10(FREQ)+20*Math.log10(0.001);
function rss(d,blocked){ const n=blocked?PLE_N:PLE_LOS;
  return state.pwr+GAINS-(fspl1m+10*n*Math.log10(Math.max(d,1))); }
function beamGain(azDeg){ // directional lobe around steering angle
  let d=azDeg-state.steer; while(d>180)d-=360; while(d<-180)d+=360;
  const main=Math.pow(Math.cos(Math.min(Math.abs(d),90)*Math.PI/180),6);
  return -14 + 14*main; // dB, -14 floor .. 0 peak
}

/* compute radio map -> viridis, with LOS shadowing + beam. returns {ms,cov} */
function computeRadioMap(){
  const t=towers[state.tx], txY=t.height;
  const img=rmCtx.createImageData(RM,RMZ), data=img.data;
  let vmin=-112, vmax=-52, covered=0, total=0;
  const cellW=WW/RM, cellH=WH/RMZ;
  for(let j=0;j<RMZ;j++)for(let i=0;i<RM;i++){
    const wx=WX0+(i+0.5)*cellW, wz=WZ0+(j+0.5)*cellH;
    const k=(j*RM+i)*4;
    // inside a building footprint -> leave dark (roofs drawn by mesh)
    if(heightAtGrid(gx(wx),gz(wz))>1.5){ data[k]=18;data[k+1]=19;data[k+2]=23;data[k+3]=255; continue; }
    const dx=wx-t.x, dz=wz-t.z, d=Math.hypot(dx,dz, txY-1.5);
    const az=Math.atan2(dx,-dz)*180/Math.PI; // 0deg = north(-Z)
    const blocked=losBlocked(t.x,txY,t.z, wx,1.5,wz);
    const r=rss(d,blocked)+beamGain(az);
    total++; if(r>-105)covered++;
    let v=(r-vmin)/(vmax-vmin); v=Math.max(0,Math.min(1,v));
    if(blocked) v*=0.55; // deepen shadows toward purple
    const c=viridis(v);
    data[k]=c[0];data[k+1]=c[1];data[k+2]=c[2];data[k+3]=255;
  }
  rmCtx.putImageData(img,0,0); rmTex.needsUpdate=true;
  return {cov: total?covered/total*100:0};
}

/* ---------------- transmitter marker ---------------- */
let txGroup=null;
function placeTx(){
  if(txGroup) scene.remove(txGroup);
  txGroup=new THREE.Group();
  const t=towers[state.tx];
  const mast=new THREE.Mesh(new THREE.CylinderGeometry(0.6,0.9,t.height,8),
    new THREE.MeshStandardMaterial({color:0x9a7a20,roughness:.6}));
  mast.position.set(t.x,t.height/2,t.z); txGroup.add(mast);
  const ball=new THREE.Mesh(new THREE.SphereGeometry(6,20,20),
    new THREE.MeshBasicMaterial({color:0xffc83c}));
  ball.position.set(t.x,t.height+6,t.z); txGroup.add(ball);
  const glow=new THREE.Mesh(new THREE.SphereGeometry(12,16,16),
    new THREE.MeshBasicMaterial({color:0xffc83c,transparent:true,opacity:0.18}));
  glow.position.copy(ball.position); txGroup.add(glow);
  txGroup.add(makeLabel('Transmitter', t.x, t.height+22, t.z));
  scene.add(txGroup);
}
function makeLabel(text,x,y,z){
  const c=document.createElement('canvas'),ctx=c.getContext('2d');
  ctx.font='600 34px "Geist Mono", monospace'; const w=ctx.measureText(text).width;
  c.width=w+40; c.height=54;
  ctx.font='600 34px "Geist Mono", monospace';
  ctx.fillStyle='rgba(12,12,14,.85)'; roundRect(ctx,2,6,c.width-4,42,8); ctx.fill();
  ctx.strokeStyle='rgba(255,200,60,.5)'; ctx.lineWidth=2; roundRect(ctx,2,6,c.width-4,42,8); ctx.stroke();
  ctx.fillStyle='#ffc83c'; ctx.textBaseline='middle'; ctx.fillText(text,20,29);
  const tex=new THREE.CanvasTexture(c);
  const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:tex,depthTest:false}));
  sp.scale.set(c.width*0.55,c.height*0.55,1); sp.position.set(x,y,z);
  return sp;
}
function roundRect(ctx,x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);
  ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}

/* ---------------- ray paths ---------------- */
let pathObj=null, raysCast=0;
function tracePaths(){
  if(pathObj) scene.remove(pathObj);
  const t=towers[state.tx], txPos=new THREE.Vector3(t.x,t.height+6,t.z);
  const verts=[], N=440;
  const spread = state.rx? 60 : 360;      // focus a beam if an RX is set
  const center = state.rx? Math.atan2(state.rx.x-t.x,-(state.rx.z-t.z))*180/Math.PI : state.steer;
  for(let a=0;a<N;a++){
    const azDeg = center + (a/N-0.5)*spread + state.steer*0.15;
    const az=azDeg*Math.PI/180;
    const dirx=Math.sin(az), dirz=-Math.cos(az);
    const hit=marchRay(t.x,t.height+6,t.z, dirx,dirz);
    verts.push(txPos.x,txPos.y,txPos.z, hit.x,hit.y,hit.z);
    // one reflection bounce for depth>0
    if(state.depth>0 && hit.blocked){
      const bx=hit.x+ (Math.random()-0.5)*0, bz=hit.z;
      const h2=marchRay(hit.x,hit.y,hit.z, -dirz, dirx); // turn ~90°
      verts.push(hit.x,hit.y,hit.z, h2.x,h2.y,h2.z);
    }
  }
  raysCast=N;
  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));
  pathObj=new THREE.LineSegments(g,new THREE.LineBasicMaterial({
    color:0xffffff,transparent:true,opacity:state.rx?0.55:0.2}));
  scene.add(pathObj);
  // strong LOS/NLOS link to the receiver
  if(state.rx) traceReceiver(txPos);
}
function marchRay(x,y,z,dirx,dirz){
  const maxR=Math.max(WW,WH); const step=6;
  const dy=(1.5-y)/(maxR); // descend gently toward ground over range
  let px=x,py=y,pz=z, blocked=false;
  for(let r=step;r<maxR;r+=step){
    px=x+dirx*r; pz=z+dirz*r; py=y+dy*r;
    if(px<WX0||px>WX1||pz<WZ0||pz>WZ1){py=Math.max(py,0.5);break;}
    const h=heightAtGrid(gx(px),gz(pz));
    if(h>py){ blocked=true; py=Math.min(py+2,h); break; }
    if(py<=1.5){ py=1.5; break; }
  }
  return {x:px,y:Math.max(py,0.5),z:pz,blocked};
}
let rxObj=null;
function traceReceiver(txPos){
  if(rxObj) scene.remove(rxObj);
  rxObj=new THREE.Group();
  const rx=new THREE.Vector3(state.rx.x,1.5,state.rx.z);
  const blocked=losBlocked(txPos.x,txPos.y,txPos.z, rx.x,rx.y,rx.z);
  const seg=[];
  if(!blocked){ seg.push(txPos.x,txPos.y,txPos.z, rx.x,rx.y,rx.z); }
  else { // bounce via the strongest nearby unblocked reflector midpoint on ground
    const mid=new THREE.Vector3((txPos.x+rx.x)/2+40,2,(txPos.z+rx.z)/2+40);
    seg.push(txPos.x,txPos.y,txPos.z, mid.x,mid.y,mid.z, mid.x,mid.y,mid.z, rx.x,rx.y,rx.z);
  }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(seg,3));
  rxObj.add(new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:blocked?0xff5a5a:0x7cff9b,linewidth:2})));
  const marker=new THREE.Mesh(new THREE.SphereGeometry(4,16,16),new THREE.MeshBasicMaterial({color:0xffffff}));
  marker.position.copy(rx); rxObj.add(marker);
  const t=towers[state.tx]; const d=Math.hypot(rx.x-t.x,rx.z-t.z,txPos.y-1.5);
  const r=rss(d,blocked)+beamGain(Math.atan2(rx.x-t.x,-(rx.z-t.z))*180/Math.PI);
  rxObj.add(makeLabel(`RX ${Math.round(r)} dBm`, rx.x, 26, rx.z));
  scene.add(rxObj);
}

/* ---------------- apply mode / refresh ---------------- */
function refresh(recompute){
  placeTx();
  const t0=performance.now();
  let cov=null;
  if(state.mode==='radio'||state.mode==='both'){
    ground.material=groundMat; groundMat.map=rmTex;
    cov=computeRadioMap().cov;
    const ms=(performance.now()-t0);
    setBadge(`Radio map computed in <b>${ms.toFixed(1)} ms</b>`);
    document.getElementById('leg-title').textContent='Path gain (dB)';
  } else {
    groundMat.map=gridTex;
  }
  if(state.mode==='paths'||state.mode==='both'){
    const p0=performance.now(); tracePaths(); const ms=(performance.now()-p0);
    if(state.mode==='paths'){ setBadge(`Paths computed in <b>${ms.toFixed(1)} ms</b>`);
      document.getElementById('leg-title').textContent='Ray density'; }
  } else if(pathObj){ scene.remove(pathObj); pathObj=null; if(rxObj){scene.remove(rxObj);rxObj=null;} }
  // legend swatch follows the active layer
  const grad=document.querySelector('.legend .grad');
  if(grad) grad.style.background = (state.mode==='paths')
    ? 'linear-gradient(90deg,rgba(255,255,255,.06),#ffffff)'
    : 'linear-gradient(90deg,#440154,#3b528b,#21918c,#5ec962,#fde725)';
  groundMat.needsUpdate=true;
  // readout
  if(cov!=null) document.getElementById('m-cov').textContent=cov.toFixed(0);
  document.getElementById('m-rays').textContent=(state.mode==='radio')? (RM*RMZ/1000).toFixed(0) : (raysCast/1000).toFixed(1);
  document.getElementById('s-site').textContent=towers[state.tx].name;
}
function setBadge(html){ document.getElementById('badge-txt').innerHTML=html; }

/* ---------------- interactions ---------------- */
const ray=new THREE.Raycaster(), mouse=new THREE.Vector2();
renderer.domElement.addEventListener('pointerdown',e=>{ down={x:e.clientX,y:e.clientY,moved:false}; });
renderer.domElement.addEventListener('pointermove',e=>{ if(down&&Math.hypot(e.clientX-down.x,e.clientY-down.y)>4)down.moved=true; });
let down=null;
renderer.domElement.addEventListener('pointerup',e=>{
  if(down&&!down.moved){ pickGround(e); } down=null;
});
function pickGround(e){
  mouse.x=(e.clientX/innerWidth)*2-1; mouse.y=-(e.clientY/innerHeight)*2+1;
  ray.setFromCamera(mouse,camera);
  const hit=ray.intersectObject(ground)[0];
  if(hit){ state.rx={x:hit.point.x,z:hit.point.z};
    if(state.mode==='radio'){ state.mode='both'; syncModeButtons(); }
    refresh(true);
  }
}
function syncModeButtons(){ document.querySelectorAll('.modes button').forEach(b=>b.classList.toggle('active',b.dataset.mode===state.mode)); }

document.querySelectorAll('.modes button').forEach(b=>b.onclick=()=>{
  state.mode=b.dataset.mode; syncModeButtons(); refresh(true);
});
document.querySelectorAll('.txsel button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.txsel button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); state.tx=+b.dataset.tx; state.rx=null; towers.forEach(t=>t.sel=false); towers[state.tx].sel=true;
  focusTx(); refresh(true);
});
function bindSlider(id,fn){ const s=document.getElementById(id);
  const upd=()=>{const mn=+s.min,mx=+s.max; s.style.setProperty('--fill',((s.value-mn)/(mx-mn)*100)+'%'); fn(+s.value);};
  s.addEventListener('input',upd); upd(); }
let refreshTimer;
function debounced(){ clearTimeout(refreshTimer); refreshTimer=setTimeout(()=>refresh(true),90); }
bindSlider('s-steer',v=>{state.steer=v; document.getElementById('v-steer').textContent=(v>=0?'+':'')+v+'°'; debounced();});
bindSlider('s-pwr',v=>{state.pwr=v; document.getElementById('v-pwr').textContent=v+' dBm'; debounced();});
bindSlider('s-depth',v=>{state.depth=v; document.getElementById('v-depth').textContent=v; debounced();});

/* ---------------- camera framing ---------------- */
function focusTx(){
  const t=towers[state.tx];
  controls.target.set(t.x,10,t.z);
  camera.position.set(t.x-Math.min(WW,WH)*0.42, Math.max(WW,WH)*0.34, t.z+Math.min(WW,WH)*0.5);
  controls.update();
}

/* ---------------- loop ---------------- */
let lastT=performance.now(),frames=0,acc=0;
function animate(){
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene,camera);
  const now=performance.now(); frames++; acc+=now-lastT; lastT=now;
  if(acc>500){ document.getElementById('s-fps').textContent=Math.min(60,Math.round(frames/(acc/1000))); frames=0;acc=0; }
}
addEventListener('resize',()=>{ camera.aspect=innerWidth/innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth,innerHeight); });

/* ---------------- boot ---------------- */
function boot(){
  renderer.setSize(innerWidth,innerHeight);
  const h=location.hash.replace('#','');
  if(['paths','radio','both'].includes(h)){ state.mode=h; syncModeButtons(); }
  rasterise();
  buildBuildings();
  focusTx();
  refresh(true);
  animate();
  const l=document.getElementById('loader'); l.style.opacity=0; setTimeout(()=>l.remove(),700);
}
// let the loader paint first
setTimeout(boot,60);
})();
