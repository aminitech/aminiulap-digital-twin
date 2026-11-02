/* twin-status: a small badge that shows where the viewer's data came from.
   Added by twin-web (server.py) to each page; reads window.TWIN_SOURCE, set by
   /data.js, and records one page view through twin-web -> twin-api -> Postgres. */
(() => {
  'use strict';
  const s = window.TWIN_SOURCE || { ok: false, error: 'no data source' };
  const el = document.createElement('div');
  el.id = 'twin-status';
  el.setAttribute('role', 'status');
  el.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;max-width:min(360px,calc(100vw - 32px));' +
    'font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:#fff;background:rgba(18,18,18,.88);' +
    'border:1px solid ' + (s.ok ? '#3a3a3a' : '#ff5a5a') + ';border-radius:10px;padding:10px 12px;backdrop-filter:blur(8px)';
  const line = (k, v) => { const d = document.createElement('div'); d.textContent = k + ' ' + v; return d; };
  const title = document.createElement('div');
  title.style.cssText = 'font-weight:600;margin-bottom:4px;color:' + (s.ok ? '#ffd23f' : '#ff5a5a');
  title.textContent = s.ok ? 'twin-web → twin-api → Postgres' : 'Data not loaded';
  el.appendChild(title);
  if (s.ok) {
    el.appendChild(line('buildings', s.buildings + ' · towers ' + s.towers));
    el.appendChild(line('fetched in', s.fetch_ms + ' ms'));
    if (s.provenance) el.appendChild(line('data', s.provenance));
    const views = line('page views', '…');
    el.appendChild(views);
    const page = location.pathname.includes('scene') ? 'scene' : 'index';
    fetch('api/views', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page }) })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then(j => { views.textContent = 'page views ' + j.views + ' (written to Postgres)'; })
      .catch(e => { views.textContent = 'page views: could not write (' + e.message + ')'; });
  } else {
    el.appendChild(line('', s.error));
  }
  el.appendChild(line('request', s.request_id || '-'));
  document.body.appendChild(el);
})();
