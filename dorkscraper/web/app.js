'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="workspace-token"]').content;
let currentJob = null, timer = null, resultRows = [], cleanRows = [];
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('show'), 4500); }
async function api(path, method='GET', body) {
  const response = await fetch(path, {method, headers: {'X-Workspace-Token': token, ...(body ? {'Content-Type':'application/json'} : {})}, body: body ? JSON.stringify(body) : undefined});
  let data; try { data = await response.json(); } catch (_) { throw new Error('Unexpected server response'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Invalid request');
  return data;
}
function view(name) {
  document.querySelectorAll('.view').forEach(e => e.hidden = e.id !== `${name}-view`);
  document.querySelectorAll('.nav').forEach(e => e.classList.toggle('active', e.dataset.view === name));
  $('breadcrumb').textContent = name.toUpperCase();
  if (name === 'history') loadHistory();
}
document.querySelectorAll('.nav').forEach(e => e.addEventListener('click', () => view(e.dataset.view)));
$('theme').addEventListener('click', () => { document.body.classList.toggle('light'); localStorage.setItem('dork-theme', document.body.classList.contains('light') ? 'light' : 'dark'); });
const savedTheme = localStorage.getItem('dork-theme');
if (savedTheme === 'light' || (!savedTheme && matchMedia('(prefers-color-scheme: light)').matches)) document.body.classList.add('light');
function opts(prefix) { return {strip_tracking: $(`${prefix}-track`).checked, drop_static: $(`${prefix}-static`).checked, params_only: $(`${prefix}-params`).checked, unique_mode: $(`${prefix}-unique`).value, include_domains: $(`${prefix}-domain`).value.split(',').map(x => x.trim()).filter(Boolean), exclude_domains: []}; }
function lines(s) { return s.split(/\r?\n/).map(x=>x.trim()).filter(Boolean); }
$('queries').addEventListener('input', () => { const multi = lines($('queries').value).some(line => (line.match(/(?:^|\s)site:/gi) || []).length > 1 && !line.includes('`')); $('query-warning').hidden = !multi; });
function setChildren(container, nodes) { container.replaceChildren(...nodes); }
function empty(title, description) { const box = document.createElement('div'); box.className='empty'; const b=document.createElement('b'); b.textContent=title; const p=document.createElement('p'); p.textContent=description; box.append(b,p); return box; }
function urlRow(url, detail) { const row=document.createElement('div'); row.className='result-row'; const a=document.createElement('a'); a.href=url; a.target='_blank'; a.rel='noopener noreferrer'; a.textContent=url; const sub=document.createElement('small'); sub.textContent=detail; row.append(a,sub); return row; }
function download(filename, data, type) { const blob = new Blob([data], {type}); const url = URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=filename; a.click(); setTimeout(()=>URL.revokeObjectURL(url), 1000); }
function safeCsv(value) { let s=String(value); if (/^[\s\x00-\x1f]*[=+@\-\t\r]/.test(s)) s="'"+s; return '"'+s.replace(/"/g,'""')+'"'; }
function renderResults() {
  const needle=$('result-filter').value.toLowerCase(); const filtered=resultRows.filter(r => `${r.url} ${r.sources.join(' ')}`.toLowerCase().includes(needle));
  $('result-count').textContent=String(resultRows.length);
  setChildren($('search-results'), filtered.length ? filtered.map(r=>urlRow(r.url, r.sources.join('  ·  '))) : [empty('No results to show', resultRows.length ? 'Try another filter.' : 'Check the engine statuses or try a different query.')]);
  $('result-controls').hidden = resultRows.length === 0;
}
$('result-filter').addEventListener('input', renderResults);
$('export-txt').onclick=()=>download('dork-results.txt', resultRows.map(r=>r.url).join('\n')+'\n','text/plain');
$('export-json').onclick=()=>download('dork-results.json', JSON.stringify({job:currentJob, urls:resultRows},null,2),'application/json');
$('export-csv').onclick=()=>download('dork-results.csv', ['url,sources',...resultRows.map(r=>[r.url,r.sources.join(' | ')].map(safeCsv).join(','))].join('\r\n')+'\r\n','text/csv');
function renderJob(job) {
  currentJob=job;
  const running=['queued','running'].includes(job.status);
  $('cancel').hidden=!running; $('progress-wrap').hidden=false;
  $('progress').style.width=`${job.total ? Math.round(job.completed / job.total * 100) : 0}%`;
  $('progress-label').textContent=`${cap(job.status)} · ${job.completed} / ${job.total} searches completed`;
  $('result-subtitle').textContent=job.queries.join('  ·  ');
  const statuses=job.results.map(r => {const div=document.createElement('div'); div.className='status-item'+(r.blocked || r.error ? ' error' : ''); const effective=r.effective_query && r.effective_query !== r.query ? ` · Sent: ${r.effective_query}` : ''; const literal=r.literal_filter ? ` · Exact URL contains ${r.literal_filter}: ${r.literal_filtered_count || 0} removed` : ''; const scope=r.scope_warning ? ` · ${r.scope_warning}` : ` · Scope guard: ${r.out_of_scope_count || 0} out-of-scope URLs removed`; div.textContent=`${cap(r.engine)} · ${r.query} — ${r.blocked ? 'Blocked / CAPTCHA' : r.error ? 'Error: '+r.error : `${r.urls.length} URLs · ${r.pages_fetched} pages`}${scope}${literal}${effective}`; return div;});
  if(job.error) { const div=document.createElement('div'); div.className='status-item error'; div.textContent=job.error; statuses.push(div); }
  setChildren($('search-status'),statuses);
  resultRows=job.items || []; renderResults();
  if(running) { clearTimeout(timer); timer=setTimeout(async()=>{try {renderJob(await api('/api/jobs/'+job.id));} catch(e) {toast(e.message);}},1200); }
}
$('search-form').addEventListener('submit', async e=>{e.preventDefault(); const queries=lines($('queries').value); const engines=[...document.querySelectorAll('#engines input:checked')].map(e=>e.value); if(!engines.length) return toast('Choose at least one search engine.'); if(!queries.length) return toast('Enter a search query.'); const button=e.submitter; button.disabled=true; try {const job=await api('/api/jobs','POST',{queries,engines,pages:Number($('pages').value),delay:Number($('delay').value),options:opts('search')}); $('result-filter').value=''; if(job.queries.join('\n') !== queries.join('\n')) { $('queries').value=job.queries.join('\n'); $('query-warning').hidden=true; toast('Copied code spans were separated into individual queries.'); } renderJob(job); } catch(err){toast(err.message);} finally {button.disabled=false;} });
$('cancel').addEventListener('click',async()=>{if(!currentJob)return; try{const r=await api(`/api/jobs/${currentJob.id}/cancel`,'POST');toast(r.message);}catch(e){toast(e.message);}});
$('clean-form').addEventListener('submit',async e=>{e.preventDefault(); try {const data=await api('/api/clean','POST',{urls:lines($('urls').value),options:opts('clean')}); cleanRows=data.items; $('clean-count').textContent=data.output_count; $('clean-summary').textContent=`${data.input_count} input · ${data.output_count} kept · ${data.removed_count} removed`; setChildren($('clean-results'),cleanRows.length ? cleanRows.map(r=>urlRow(r.url,r.original!==r.url ? `Original: ${r.original}` : 'Unchanged')) : [empty('No URLs kept','Check your input and filters.')]); $('clean-export').disabled=!cleanRows.length; $('clean-json').disabled=!cleanRows.length; } catch(err){toast(err.message);} });
$('clean-export').onclick=()=>download('clean-urls.txt',cleanRows.map(x=>x.url).join('\n')+'\n','text/plain');
$('clean-json').onclick=()=>download('clean-urls.json',JSON.stringify(cleanRows,null,2),'application/json');
$('file').addEventListener('change',async e=>{const f=e.target.files[0]; if(!f)return; if(f.size>2*1024*1024){toast('File exceeds the 2 MB limit.'); e.target.value=''; return;} try{$('urls').value=await f.text(); $('file-label').textContent=f.name;}catch(_){toast('Could not read this file.');}});
async function loadHistory(){try {const jobs=await api('/api/jobs'); const nodes=jobs.map(j=>{const row=document.createElement('div');row.className='history-row';const info=document.createElement('div');const b=document.createElement('b');b.textContent=j.queries.join(' · ');const sm=document.createElement('small');sm.textContent=`${new Date(j.created*1000).toLocaleString()} · ${j.engines.join(', ')} · ${j.status} · ${j.completed}/${j.total}`;info.append(b,sm);const actions=document.createElement('div');actions.className='actions';const open=document.createElement('button');open.className='secondary';open.textContent='Open';open.onclick=()=>{clearTimeout(timer);view('search');renderJob(j);};const del=document.createElement('button');del.className='secondary';del.textContent='Delete';del.onclick=async()=>{if(!confirm('Delete this search history?'))return;try{await api('/api/jobs/'+j.id,'DELETE');loadHistory();}catch(e){toast(e.message);}};actions.append(open,del);row.append(info,actions);return row;});setChildren($('history-list'),nodes.length?nodes:[empty('No searches yet','Your completed searches will appear here.')]);}catch(e){toast(e.message);}}
$('refresh-history').onclick=loadHistory;
async function setup(){try {const config=await api('/api/config');const nodes=config.engines.map(engine=>{const label=document.createElement('label');label.className='engine';const input=document.createElement('input');input.type='checkbox';input.value=engine;input.checked=engine==='duckduckgo'; const text=document.createElement('span'); text.textContent=cap(engine)+(engine==='brave'&&!config.brave_configured?' · API key required':'');label.append(input,text);return label;});setChildren($('engines'),nodes); const jobs=await api('/api/jobs'); const active=jobs.find(j=>['running','queued'].includes(j.status));if(active)renderJob(active);}catch(e){toast(e.message);}}
setup();
