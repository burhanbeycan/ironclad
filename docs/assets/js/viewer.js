/* IRONCLAD Viewer — pure client-side */

const els = {
  pdfInput: document.getElementById('pdfInput'),
  analyzePdf: document.getElementById('analyzePdf'),
  pdfStatus: document.getElementById('pdfStatus'),
  fileInput: document.getElementById('fileInput'),
  loadDemo: document.getElementById('loadDemo'),
  clearData: document.getElementById('clearData'),
  searchInput: document.getElementById('searchInput'),
  originSelect: document.getElementById('originSelect'),
  categorySelect: document.getElementById('categorySelect'),
  hardFailOnly: document.getElementById('hardFailOnly'),
  imageInput: document.getElementById('imageInput'),
  exportCsv: document.getElementById('exportCsv'),
  exportJson: document.getElementById('exportJson'),

  statsKv: document.getElementById('statsKv'),

  tabs: document.getElementById('tabs'),
  tabRecords: document.getElementById('tab-records'),
  tabComparison: document.getElementById('tab-comparison'),
  tabTables: document.getElementById('tab-tables'),
  tabFigures: document.getElementById('tab-figures'),
  tabLogs: document.getElementById('tab-logs'),

  recordsTable: document.getElementById('recordsTable'),
  recordsTbody: document.querySelector('#recordsTable tbody'),
  comparisonTable: document.getElementById('comparisonTable'),
  comparisonTbody: document.querySelector('#comparisonTable tbody'),

  recordDetails: document.getElementById('recordDetails'),
  recordKv: document.getElementById('recordKv'),
  recordSnippet: document.getElementById('recordSnippet'),
  recordJson: document.getElementById('recordJson'),

  tablesArea: document.getElementById('tablesArea'),
  figuresArea: document.getElementById('figuresArea'),
  logsPre: document.getElementById('logsPre'),
};

const state = {
  data: null,
  records: [],
  comparison: [],
  tables: [],
  figures: null,
  logs: [],
  imageFilesByName: new Map(),

  recordSort: { key: 'confidence', dir: 'desc' },
  cmpSort: { key: 'material', dir: 'asc' },

  filteredRecordViews: [],
};

function setPdfStatus(msg, cls='status-warn'){
  if (!els.pdfStatus) return;
  els.pdfStatus.textContent = msg;
  els.pdfStatus.classList.remove('status-ok', 'status-warn', 'status-error');
  if (cls) els.pdfStatus.classList.add(cls);
}

function setStats(items){
  els.statsKv.innerHTML = '';
  for (const [k,v] of items){
    const dk = document.createElement('div');
    dk.className = 'k';
    dk.textContent = k;
    const dv = document.createElement('div');
    dv.className = 'v';
    dv.textContent = String(v);
    els.statsKv.appendChild(dk);
    els.statsKv.appendChild(dv);
  }
}

function fmtValue(v){
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'number'){
    // compact formatting
    const av = Math.abs(v);
    if (av !== 0 && (av >= 1e4 || av < 1e-3)) return v.toExponential(3);
    if (av >= 100) return v.toFixed(2);
    if (av >= 1) return v.toFixed(3);
    return v.toFixed(4);
  }
  return String(v);
}

function valueDisplay(rec){
  const a = rec.value_min;
  const b = rec.value_max;
  if (a === null || a === undefined) return '';
  if (b === null || b === undefined || b === '' || b === a) return fmtValue(a);
  return `${fmtValue(a)}–${fmtValue(b)}`;
}

function hardFailDisplay(rec){
  const hf = rec?.constraints?.hard_fail;
  if (!hf || !hf.length) return '';
  return hf.join('; ');
}

function getPage(rec){
  return rec?.provenance?.page ?? '';
}

function rowTag(origin){
  const span = document.createElement('span');
  span.className = 'rowtag';
  if (origin === 'this_work') span.classList.add('tag-this');
  else if (origin === 'literature') span.classList.add('tag-lit');
  else if (origin === 'mixed') span.classList.add('tag-mixed');
  else span.classList.add('tag-unclear');
  span.textContent = origin || '';
  return span;
}

function sanitize(s){
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function rebuildCategoryOptions(){
  const cats = new Set(state.records.map(r => r.category).filter(Boolean));
  const existing = new Set(Array.from(els.categorySelect.options).map(o => o.value));
  // reset
  els.categorySelect.innerHTML = '<option value="all">All</option>';
  Array.from(cats).sort().forEach(c => {
    const opt = document.createElement('option');
    opt.value = c;
    opt.textContent = c;
    els.categorySelect.appendChild(opt);
  });
}

function recordMatchesFilters(rec){
  const q = (els.searchInput.value || '').trim().toLowerCase();
  const origin = els.originSelect.value;
  const cat = els.categorySelect.value;
  const hardFailOnly = els.hardFailOnly.checked;

  if (origin !== 'all' && (rec.origin || '') !== origin) return false;
  if (cat !== 'all' && (rec.category || '') !== cat) return false;
  if (hardFailOnly){
    const hf = rec?.constraints?.hard_fail;
    if (!hf || !hf.length) return false;
  }
  if (q){
    const hay = [
      rec.material, rec.property, rec.category,
      rec?.provenance?.snippet,
      (rec.citations || []).join(' ')
    ].join(' ').toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function buildRecordViews(){
  const views = [];
  for (let i=0; i<state.records.length; i++){
    const r = state.records[i];
    if (!recordMatchesFilters(r)) continue;
    views.push({
      idx: i,
      material: r.material || '',
      category: r.category || '',
      property: r.property || '',
      value_display: valueDisplay(r),
      unit_original: r.unit_original || '',
      page: getPage(r),
      origin: r.origin || '',
      confidence: r.confidence ?? '',
      hard_fail: hardFailDisplay(r),
    });
  }
  state.filteredRecordViews = views;
}

function sortByKey(arr, key, dir){
  const m = dir === 'desc' ? -1 : 1;
  arr.sort((a,b) => {
    const va = a[key];
    const vb = b[key];
    // numeric if possible
    const na = (typeof va === 'number') ? va : (va !== '' && !isNaN(Number(va)) ? Number(va) : null);
    const nb = (typeof vb === 'number') ? vb : (vb !== '' && !isNaN(Number(vb)) ? Number(vb) : null);
    if (na !== null && nb !== null){
      if (na < nb) return -1*m;
      if (na > nb) return 1*m;
      return 0;
    }
    const sa = String(va ?? '').toLowerCase();
    const sb = String(vb ?? '').toLowerCase();
    if (sa < sb) return -1*m;
    if (sa > sb) return 1*m;
    return 0;
  });
}

function renderRecordsTable(){
  buildRecordViews();
  sortByKey(state.filteredRecordViews, state.recordSort.key, state.recordSort.dir);

  els.recordsTbody.innerHTML = '';
  const frag = document.createDocumentFragment();

  state.filteredRecordViews.forEach(view => {
    const tr = document.createElement('tr');
    tr.dataset.idx = String(view.idx);

    const tdMat = document.createElement('td'); tdMat.textContent = view.material;
    const tdCat = document.createElement('td'); tdCat.textContent = view.category;
    const tdProp = document.createElement('td'); tdProp.textContent = view.property;
    const tdVal = document.createElement('td'); tdVal.textContent = view.value_display;
    const tdUnit = document.createElement('td'); tdUnit.textContent = view.unit_original;
    const tdPage = document.createElement('td'); tdPage.textContent = view.page;
    const tdOrigin = document.createElement('td'); tdOrigin.appendChild(rowTag(view.origin));
    const tdConf = document.createElement('td'); tdConf.textContent = String(view.confidence);
    const tdFail = document.createElement('td'); tdFail.textContent = view.hard_fail;

    [tdMat,tdCat,tdProp,tdVal,tdUnit,tdPage,tdOrigin,tdConf,tdFail].forEach(td => tr.appendChild(td));

    tr.addEventListener('click', () => showRecordDetails(view.idx));
    frag.appendChild(tr);
  });

  els.recordsTbody.appendChild(frag);

  // update stats
  const byOrigin = {};
  for (const r of state.records){
    const o = r.origin || 'unclear';
    byOrigin[o] = (byOrigin[o]||0) + 1;
  }
  setStats([
    ['doc_id', state.data?.doc_id ?? '(unknown)'],
    ['records (total)', state.records.length],
    ['records (filtered)', state.filteredRecordViews.length],
    ['this_work', byOrigin['this_work']||0],
    ['literature', byOrigin['literature']||0],
    ['mixed', byOrigin['mixed']||0],
    ['unclear', byOrigin['unclear']||0],
    ['tables', state.tables.length],
    ['figures', state.figures?.images?.length || 0],
  ]);
}

function showRecordDetails(idx){
  const r = state.records[idx];
  if (!r) return;

  els.recordDetails.style.display = 'block';

  const pairs = [
    ['material', r.material],
    ['property', r.property],
    ['category', r.category],
    ['value_min', r.value_min],
    ['value_max', r.value_max],
    ['unit_original', r.unit_original],
    ['value_si_min', r.value_si_min],
    ['value_si_max', r.value_si_max],
    ['unit_si', r.unit_si],
    ['origin', r.origin],
    ['confidence', r.confidence],
    ['page', r?.provenance?.page],
    ['citations', (r.citations || []).join(', ')],
    ['hard_fail', (r?.constraints?.hard_fail || []).join('; ')],
    ['soft_warn', (r?.constraints?.soft_warn || []).join('; ')],
    ['method', r.method || ''],
  ];

  els.recordKv.innerHTML = '';
  for (const [k,v] of pairs){
    const dk = document.createElement('div');
    dk.className = 'k';
    dk.textContent = k;
    const dv = document.createElement('div');
    dv.className = 'v';
    dv.textContent = String(v ?? '');
    els.recordKv.appendChild(dk);
    els.recordKv.appendChild(dv);
  }

  els.recordSnippet.textContent = r?.provenance?.snippet ? r.provenance.snippet : '(no snippet)';
  els.recordJson.textContent = JSON.stringify(r, null, 2);
}

function renderComparisonTable(){
  const rows = Array.isArray(state.comparison) ? [...state.comparison] : [];
  sortByKey(rows, state.cmpSort.key, state.cmpSort.dir);

  els.comparisonTbody.innerHTML = '';
  const frag = document.createDocumentFragment();
  rows.forEach(r => {
    const tr = document.createElement('tr');
    const cols = ['material','property','category','this_work','paper_cited_literature','external_baseline','novelty_flag'];
    cols.forEach(c => {
      const td = document.createElement('td');
      td.textContent = String(r[c] ?? '');
      tr.appendChild(td);
    });
    frag.appendChild(tr);
  });
  els.comparisonTbody.appendChild(frag);
}

function renderTables(){
  els.tablesArea.innerHTML = '';
  if (!state.tables || !state.tables.length){
    els.tablesArea.innerHTML = '<div class="small">(No tables in JSON)</div>';
    return;
  }

  const wrap = document.createElement('div');
  wrap.style.display = 'grid';
  wrap.style.gap = '12px';

  state.tables.forEach((t, i) => {
    const det = document.createElement('details');
    det.className = 'details';
    det.open = (i === 0);

    const sum = document.createElement('summary');
    sum.style.cursor = 'pointer';
    const tid = t.table_id || `T${i+1}`;
    const page = t.page ? `p.${t.page}` : '';
    const label = `${tid} ${page}`.trim();
    sum.textContent = label;
    det.appendChild(sum);

    const meta = t.meta || {};
    const metaLine = document.createElement('div');
    metaLine.className = 'small';
    const parts = [];
    if (meta.table_number !== undefined) parts.push(`table_number: ${meta.table_number}`);
    if (meta.caption) parts.push(`caption: ${meta.caption}`);
    if (parts.length) metaLine.textContent = parts.join(' · ');
    det.appendChild(metaLine);

    const tableWrap = document.createElement('div');
    tableWrap.className = 'table-wrap';
    tableWrap.style.marginTop = '10px';

    const tbl = document.createElement('table');
    tbl.style.minWidth = '720px';

    const thead = document.createElement('thead');
    const trh = document.createElement('tr');
    const header = t.header || [];
    (header.length ? header : (t.rows?.[0] || []).map((_,j)=>`col${j+1}`)).forEach(h => {
      const th = document.createElement('th');
      th.textContent = String(h ?? '');
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    tbl.appendChild(thead);

    const tbody = document.createElement('tbody');
    (t.rows || []).slice(0, 20).forEach(row => {
      const tr = document.createElement('tr');
      (row || []).forEach(cell => {
        const td = document.createElement('td');
        td.textContent = String(cell ?? '');
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);

    tableWrap.appendChild(tbl);
    det.appendChild(tableWrap);

    wrap.appendChild(det);
  });

  els.tablesArea.appendChild(wrap);
}

function fileNameFromPath(p){
  if (!p) return '';
  const s = String(p);
  const parts = s.split(/[\\/]/);
  return parts[parts.length-1];
}

function resolveImageUrl(img){
  // Prefer relative URL paths (demo), else try user-selected files by basename.
  const p = img?.path;
  if (!p) return null;
  const base = fileNameFromPath(p);
  if (p.startsWith('http://') || p.startsWith('https://')) return p;
  if (!p.includes(':') && !p.startsWith('/')){
    // relative path (likely demo)
    return p;
  }
  // absolute/local path -> try map
  if (state.imageFilesByName.has(base)){
    return state.imageFilesByName.get(base);
  }
  return null;
}

function renderFigures(){
  els.figuresArea.innerHTML = '';
  const imgs = state.figures?.images || [];
  if (!imgs.length){
    els.figuresArea.innerHTML = '<div class="small">(No figures in JSON)</div>';
    return;
  }

  const frag = document.createDocumentFragment();
  imgs.forEach(img => {
    const div = document.createElement('div');
    div.className = 'thumb';

    const url = resolveImageUrl(img);
    if (url){
      const im = document.createElement('img');
      im.src = url;
      im.alt = img.caption || fileNameFromPath(img.path) || 'figure';
      div.appendChild(im);
    }else{
      const ph = document.createElement('div');
      ph.style.height = '220px';
      ph.style.display = 'flex';
      ph.style.alignItems = 'center';
      ph.style.justifyContent = 'center';
      ph.style.color = 'rgba(255,255,255,0.65)';
      ph.style.padding = '12px';
      ph.textContent = 'Image not available in browser.\nUse the file picker on the left to load extracted images.';
      div.appendChild(ph);
    }

    const cap = document.createElement('div');
    cap.className = 'cap';
    const bits = [];
    if (img.page) bits.push(`p.${img.page}`);
    if (img.figure_type) bits.push(img.figure_type);
    const prefix = bits.length ? `${bits.join(' · ')} — ` : '';
    cap.textContent = prefix + (img.caption || fileNameFromPath(img.path) || '(no caption)');
    div.appendChild(cap);

    frag.appendChild(div);
  });

  els.figuresArea.appendChild(frag);
}

function renderLogs(){
  const lines = state.logs || [];
  els.logsPre.textContent = lines.length ? lines.join('\n') : '(No logs in JSON)';
}

function clearAll(){
  state.data = null;
  state.records = [];
  state.comparison = [];
  state.tables = [];
  state.figures = null;
  state.logs = [];
  state.imageFilesByName = new Map();
  state.filteredRecordViews = [];

  els.recordsTbody.innerHTML = '';
  els.comparisonTbody.innerHTML = '';
  els.tablesArea.innerHTML = '';
  els.figuresArea.innerHTML = '';
  els.logsPre.textContent = '';
  els.recordDetails.style.display = 'none';

  rebuildCategoryOptions();
  setStats([['status','No data loaded.']]);
}

async function loadJsonObject(obj){
  if (!obj || typeof obj !== 'object'){
    alert('Invalid JSON.');
    return;
  }
  state.data = obj;
  state.records = Array.isArray(obj.records) ? obj.records : [];
  state.comparison = Array.isArray(obj.comparison) ? obj.comparison : [];
  state.tables = Array.isArray(obj.tables) ? obj.tables : [];
  state.figures = obj.figures || null;
  state.logs = Array.isArray(obj.logs) ? obj.logs : [];

  rebuildCategoryOptions();
  renderRecordsTable();
  renderComparisonTable();
  renderTables();
  renderFigures();
  renderLogs();
}

async function loadDemo(){
  const resp = await fetch('assets/demo/demo_output.json');
  const obj = await resp.json();
  await loadJsonObject(obj);
}

function downloadBlob(content, filename, mime){
  const blob = new Blob([content], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2500);
}

function exportFilteredCsv(){
  const cols = ['material','category','property','value_min','value_max','unit_original','origin','confidence','page','citations','hard_fail'];
  const lines = [cols.join(',')];

  for (const v of state.filteredRecordViews){
    const r = state.records[v.idx];
    const row = [
      r.material, r.category, r.property,
      r.value_min, r.value_max, r.unit_original,
      r.origin, r.confidence,
      getPage(r),
      (r.citations || []).join('; '),
      (r?.constraints?.hard_fail || []).join('; ')
    ].map(x => `"${String(x ?? '').replace(/"/g,'""')}"`);
    lines.push(row.join(','));
  }
  downloadBlob(lines.join('\n'), 'ironclad_filtered.csv', 'text/csv;charset=utf-8');
}

function exportFilteredJson(){
  const out = state.filteredRecordViews.map(v => state.records[v.idx]);
  downloadBlob(JSON.stringify(out, null, 2), 'ironclad_filtered.json', 'application/json;charset=utf-8');
}

/* Events */

els.analyzePdf?.addEventListener('click', async () => {
  const pdf = els.pdfInput?.files?.[0];
  if (!pdf){
    setPdfStatus('Select a PDF file first.', 'status-error');
    return;
  }

  const btn = els.analyzePdf;
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Analyzing…';
  setPdfStatus('Uploading PDF and running IRONCLAD… this may take up to a minute.', 'status-warn');

  try{
    const formData = new FormData();
    formData.append('pdf', pdf, pdf.name);
    formData.append('doc_id', pdf.name.replace(/\.pdf$/i, '') || 'local:paper');

    const resp = await fetch('/api/analyze', {
      method: 'POST',
      body: formData,
    });

    const payload = await resp.json().catch(() => null);
    if (!resp.ok || !payload){
      const detail = payload?.error || `HTTP ${resp.status}`;
      throw new Error(detail);
    }

    await loadJsonObject(payload);
    setPdfStatus(`Analysis complete. Loaded ${payload.records?.length || 0} records from ${pdf.name}.`, 'status-ok');
  }catch(err){
    console.error(err);
    setPdfStatus(
      `PDF analysis failed: ${err.message}. Start the local server with "python -m app.web_viewer" and reload this page.`,
      'status-error'
    );
  }finally{
    btn.disabled = false;
    btn.textContent = prev;
  }
});

els.fileInput.addEventListener('change', async (e) => {
  const f = e.target.files?.[0];
  if (!f) return;
  try{
    const txt = await f.text();
    const obj = JSON.parse(txt);
    await loadJsonObject(obj);
  }catch(err){
    console.error(err);
    alert('Could not read JSON file.');
  }
});

els.loadDemo.addEventListener('click', () => loadDemo().catch(err => {
  console.error(err);
  alert('Could not load demo data.');
}));

els.clearData.addEventListener('click', () => clearAll());

['input','change'].forEach(ev => {
  els.searchInput.addEventListener(ev, () => renderRecordsTable());
  els.originSelect.addEventListener(ev, () => renderRecordsTable());
  els.categorySelect.addEventListener(ev, () => renderRecordsTable());
  els.hardFailOnly.addEventListener(ev, () => renderRecordsTable());
});

els.imageInput.addEventListener('change', (e) => {
  const files = Array.from(e.target.files || []);
  state.imageFilesByName = new Map();
  files.forEach(f => {
    state.imageFilesByName.set(f.name, URL.createObjectURL(f));
  });
  renderFigures();
});

els.exportCsv.addEventListener('click', () => exportFilteredCsv());
els.exportJson.addEventListener('click', () => exportFilteredJson());

/* Sorting handlers */

function hookSort(tableEl, which){
  const ths = tableEl.querySelectorAll('th[data-key]');
  ths.forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      const sort = which === 'records' ? state.recordSort : state.cmpSort;
      if (sort.key === key){
        sort.dir = (sort.dir === 'asc') ? 'desc' : 'asc';
      }else{
        sort.key = key;
        sort.dir = 'asc';
      }
      if (which === 'records') renderRecordsTable();
      else renderComparisonTable();
    });
  });
}
hookSort(els.recordsTable, 'records');
hookSort(els.comparisonTable, 'comparison');

/* Tabs */
els.tabs.addEventListener('click', (e) => {
  const t = e.target.closest('.tab');
  if (!t) return;
  const name = t.dataset.tab;
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === t));
  document.querySelectorAll('.tabpanel').forEach(p => p.style.display = 'none');

  const tabId = `tab-${name}`;
  const panel = document.getElementById(tabId);
  if (panel) panel.style.display = '';
});

/* Init */
clearAll();
setPdfStatus('No PDF analyzed yet.', 'status-warn');
