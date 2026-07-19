"""MCP App HTML views for USPTO Patent File Wrapper MCP."""

# ---------------------------------------------------------------------------
# View 1: Search Results (used by all pfw_search_* tools)
# Handles both application search and inventor search result shapes.
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PFW Search Results</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #1a3a6b; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .badge { background: #4a90d9; border-radius: 4px; padding: 2px 7px; font-size: 11px; }
.summary-bar { background: #e8f0fe; border-bottom: 1px solid #c5d8f7; padding: 7px 14px; font-size: 12px; color: #1a3a6b; display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.summary-bar span { font-weight: 600; }

.filter-bar { background: #f4f7fd; border: 1px solid #c5d8f7; border-radius: 6px; margin: 8px 14px 0; padding: 7px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.sort-bar { background: #f4f7fd; border: 1px solid #c5d8f7; border-radius: 6px; margin: 6px 14px 0; padding: 5px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.field-notice { background: #fffbe6; border-bottom: 1px solid #ffe58f; padding: 5px 14px; font-size: 11px; color: #7d5a00; line-height: 1.5; }
.filter-label { font-size: 10px; color: #888; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; margin-right: 2px; }
.pill { border: 1px solid #c5d8f7; border-radius: 12px; padding: 2px 9px; font-size: 11px; font-weight: 700; cursor: pointer; background: #fff; color: #1a3a6b; transition: all 0.12s; user-select: none; }
.pill:hover { border-color: #4a90d9; background: #e8f0fe; }
.pill.active { background: #1a3a6b; color: #fff; border-color: #1a3a6b; }
.pill-count { font-size: 9px; font-weight: 700; background: #e8f0fe; color: #1a3a6b; border-radius: 8px; padding: 0 4px; margin-left: 3px; }
.pill.active .pill-count { background: rgba(255,255,255,0.25); }
.sort-pill { border: 1px solid #c5d8f7; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 600; cursor: pointer; background: #fff; color: #555; transition: all 0.12s; user-select: none; }
.sort-pill:hover { border-color: #4a90d9; background: #e8f0fe; color: #1a3a6b; }
.sort-pill.active { background: #1a3a6b; color: #fff; border-color: #1a3a6b; }
.filter-result { font-size: 11px; color: #888; margin-left: auto; }
.clear-link { font-size: 11px; color: #c0392b; cursor: pointer; text-decoration: underline; display: none; }

.container { padding: 10px 14px; }
.card { background: #fff; border: 1px solid #dde3ed; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; }
.card:hover { border-color: #4a90d9; box-shadow: 0 1px 4px rgba(74,144,217,0.15); }
.card.hidden { display: none; }
.card-title { font-weight: 600; font-size: 13px; margin-bottom: 5px; }
.app-num { font-size: 11px; color: #4a90d9; font-weight: 700; font-family: monospace; }
.meta { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 4px 12px; font-size: 11px; margin-top: 6px; }
.meta-item { display: flex; flex-direction: column; }
.meta-label { color: #888; font-size: 10px; text-transform: uppercase; letter-spacing: 0.3px; }
.meta-val { color: #1a1a2e; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { margin-top: 7px; display: flex; gap: 6px; flex-wrap: wrap; }
.btn { display: inline-block; border: none; border-radius: 4px; padding: 3px 9px; font-size: 11px; cursor: pointer; }
.btn-primary { background: #1a3a6b; color: #fff; }
.btn-primary:hover { background: #4a90d9; }
.btn-secondary { background: #e8f0fe; color: #1a3a6b; border: 1px solid #c5d8f7; }
.btn-secondary:hover { background: #c5d8f7; }
.status-badge { display: inline-block; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 600; }
.status-granted { background: #27ae60; color: #fff; }
.status-pending { background: #e67e22; color: #fff; }
.status-abandoned { background: #888; color: #fff; }
.status-other { background: #4a90d9; color: #fff; }

#loading { text-align: center; padding: 30px; color: #666; }
#error { background: #fde8e8; border: 1px solid #f5c6cb; color: #721c24; padding: 10px 14px; margin: 10px 14px; border-radius: 4px; }
.no-match { text-align: center; padding: 20px; color: #888; font-size: 12px; display: none; }
</style>
</head>
<body>
<div class="header">
  <h1>Patent File Wrapper Search</h1>
  <span class="badge" id="tier-badge">—</span>
</div>
<div class="summary-bar" id="summary-bar" style="display:none"></div>
<div class="field-notice" id="field-notice" style="display:none"><strong>Note:</strong> Fields showing <strong>"—"</strong> were not requested in this tool call. The LLM selects fields to balance context efficiency. See the <em>Query</em> in the bar above for what was requested.</div>
<div class="filter-bar" id="filter-bar" style="display:none"></div>
<div class="sort-bar" id="sort-bar" style="display:none"></div>
<div id="loading">Waiting for search results...</div>
<div id="error" style="display:none"></div>
<div class="container" id="content" style="display:none">
  <div id="cards"></div>
  <div class="no-match" id="no-match">No results match the selected filters.</div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'PFW Search Results', version: '1.0.0' });

let allDocs = [];
let cardEls = [];
let activeFilters = {};
let currentSort = null;

app.ontoolresult = (result) => {
  const text = result.content?.find(c => c.type === 'text')?.text;
  try { render(JSON.parse(text)); }
  catch(e) { showError('Could not parse search results: ' + e.message); }
};

app.connect();

function render(data) {
  document.getElementById('loading').style.display = 'none';
  if (data.error || data.status === 'error') { showError(data.message || data.error || 'API error'); return; }

  allDocs = data.applications || data.unique_applications || [];
  activeFilters = {};
  currentSort = null;

  const total = data.total || data.total_unique_applications || allDocs.length;
  const tier = data.query_info?.search_tier || 'search';
  document.getElementById('tier-badge').textContent = tier.toUpperCase();

  const grantedCount = allDocs.filter(a => getStatus(a) === 'granted').length;
  const q = data.query_info?.constructed_query || '';
  const requestedFields = data.query_info?.requested_fields;
  const bar = document.getElementById('summary-bar');
  bar.style.display = 'flex';
  bar.innerHTML = `
    <div>Found: <span>${total.toLocaleString()}</span> applications</div>
    <div>Showing: <span>${allDocs.length}</span></div>
    ${grantedCount ? `<div>Granted: <span>${grantedCount}</span></div>` : ''}
    ${q ? `<div style="color:#888;font-size:11px;font-weight:400;max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${q.replace(/"/g,'&quot;')}">Query: ${q}</div>` : ''}
    ${requestedFields ? `<div style="color:#888;font-size:11px;font-weight:400;" title="Fields requested in this tool call">Fields: ${requestedFields.join(', ')}</div>` : ''}
  `;

  // Show field notice for minimal tiers (many fields will be —)
  const noticeEl = document.getElementById('field-notice');
  noticeEl.style.display = tier.includes('minimal') ? 'block' : 'none';

  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '';
  cardEls = [];
  if (allDocs.length === 0) {
    cardsEl.innerHTML = '<div style="text-align:center;padding:24px;color:#888">No applications found.</div>';
  } else {
    allDocs.forEach(a => {
      const el = buildCard(a);
      cardsEl.appendChild(el);
      cardEls.push(el);
    });
  }

  buildFilterBar();
  buildSortBar();
  document.getElementById('content').style.display = 'block';
}

function getStatus(a) {
  const meta = a.applicationMetaData || a;
  const code = String(meta.applicationStatusCode || '');
  if (code === '150') return 'granted';
  if (['161','162','163','164','165','170','175'].includes(code)) return 'abandoned';
  if (code) return 'pending';
  if (meta.patentNumber) return 'granted';
  return 'unknown';  // status not in returned fields — show no badge
}

function statusBadge(statusKey) {
  const labels = { granted: 'Granted', pending: 'Pending', abandoned: 'Abandoned' };
  return `<span class="status-badge status-${statusKey}">${labels[statusKey] || statusKey}</span>`;
}

function buildCard(a) {
  const div = document.createElement('div');
  div.className = 'card';

  const meta = a.applicationMetaData || a;
  const appNum = a.applicationNumberText || a.applicationNumber || '—';
  const title = meta.inventionTitle || meta.inventionSubjectMatterCategory || '(no title)';
  const filingDate = (meta.filingDate || '').split('T')[0];
  const grantDate = (meta.grantDate || '').split('T')[0];
  const patentNum = meta.patentNumber || '';
  const artUnit = meta.groupArtUnitNumber || '—';
  const examiner = meta.examinerNameText || '—';
  const applicant = meta.firstApplicantName || meta.assignee || '—';
  const inventorBag = meta.inventorBag;
  const inventor = meta.firstInventorName
    || (Array.isArray(inventorBag) ? inventorBag[0]?.inventorNameText : inventorBag?.inventorNameText)
    || '—';
  const statusKey = getStatus(a);

  div.dataset.status = statusKey;
  div.dataset.artunit = artUnit;
  div.dataset.examiner = examiner;
  div.dataset.applicant = applicant;
  div.dataset.inventor = inventor;
  div.dataset.appnum = appNum;
  div.dataset.patentnum = patentNum;
  div.dataset.title = title;

  div.innerHTML = `
    <div class="app-num">Application ${appNum}${patentNum ? ` · Patent ${patentNum}` : ''}${statusKey !== 'unknown' ? ' ' + statusBadge(statusKey) : ''}</div>
    <div class="card-title">${title}</div>
    <div class="meta">
      <div class="meta-item"><span class="meta-label">Filing Date</span><span class="meta-val">${filingDate || '—'}</span></div>
      ${grantDate ? `<div class="meta-item"><span class="meta-label">Grant Date</span><span class="meta-val">${grantDate}</span></div>` : ''}
      <div class="meta-item"><span class="meta-label">Art Unit</span><span class="meta-val">${artUnit}</span></div>
      <div class="meta-item"><span class="meta-label">Examiner</span><span class="meta-val">${examiner}</span></div>
      <div class="meta-item"><span class="meta-label">Applicant</span><span class="meta-val">${applicant}</span></div>
      <div class="meta-item"><span class="meta-label">Inventor</span><span class="meta-val">${inventor}</span></div>
    </div>
    <div class="actions">
      <button class="btn btn-primary" data-app="${appNum}">Open in Patent Center →</button>
      ${patentNum ? `<button class="btn btn-secondary" data-patent="${patentNum}">Google Patents →</button>` : ''}
    </div>
  `;

  div.querySelector('[data-app]')?.addEventListener('click', () => {
    const num = appNum.replace(/\//g, '').replace(/,/g, '');
    app.openLink({ url: `https://patentcenter.uspto.gov/applications/${num}` });
  });
  div.querySelector('[data-patent]')?.addEventListener('click', () => {
    app.openLink({ url: `https://patents.google.com/patent/US${patentNum}` });
  });

  return div;
}

function buildFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (allDocs.length < 2) { bar.style.display = 'none'; return; }

  // Exclude 'unknown' from status filter (no badge shown for those cards)
  const statuses = countBy(a => getStatus(a), v => v !== 'unknown');
  const artUnits = countBy(a => (a.applicationMetaData || a).groupArtUnitNumber, v => !!v && v !== '—');
  const examiners = countBy(a => (a.applicationMetaData || a).examinerNameText, v => !!v && v !== '—');
  const applicants = countBy(a => (a.applicationMetaData || a).firstApplicantName || (a.applicationMetaData || a).assignee, v => !!v && v !== '—');
  const inventorBagFn = a => {
    const meta = a.applicationMetaData || a;
    const bag = meta.inventorBag;
    return meta.firstInventorName || (Array.isArray(bag) ? bag[0]?.inventorNameText : bag?.inventorNameText) || '—';
  };
  const inventors = countBy(inventorBagFn, v => !!v && v !== '—');

  bar.style.display = 'flex';
  bar.innerHTML = '';

  let hasAnyFilter = false;

  if (Object.keys(statuses).length > 1) {
    hasAnyFilter = true;
    appendLabel(bar, 'Status:');
    const labels = { granted: 'Granted', pending: 'Pending', abandoned: 'Abandoned' };
    Object.entries(statuses).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(labels[val]||val, count, 'status', val));
    });
  }

  // Show art unit filter only if ≤8 unique values
  if (Object.keys(artUnits).length > 1 && Object.keys(artUnits).length <= 8) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Art Unit:');
    Object.entries(artUnits).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'artunit', val));
    });
  }

  // Examiner filter: only show pills for examiners appearing ≥2 times (useful for large result sets)
  const frequentExaminers = Object.fromEntries(Object.entries(examiners).filter(([,c]) => c >= 2));
  if (Object.keys(frequentExaminers).length >= 1 && Object.keys(frequentExaminers).length <= 8) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Examiner:');
    Object.entries(frequentExaminers).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'examiner', val));
    });
  }

  // Applicant filter: show when ≤6 unique and >1
  if (Object.keys(applicants).length > 1 && Object.keys(applicants).length <= 6) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Applicant:');
    Object.entries(applicants).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'applicant', val));
    });
  }

  // Inventor filter: only show pills for inventors appearing ≥2 times
  const frequentInventors = Object.fromEntries(Object.entries(inventors).filter(([,c]) => c >= 2));
  if (Object.keys(frequentInventors).length >= 1 && Object.keys(frequentInventors).length <= 6) {
    hasAnyFilter = true;
    appendSep(bar);
    appendLabel(bar, 'Inventor:');
    Object.entries(frequentInventors).sort((a,b)=>b[1]-a[1]).forEach(([val, count]) => {
      bar.appendChild(makePill(val, count, 'inventor', val));
    });
  }

  if (!hasAnyFilter) { bar.style.display = 'none'; return; }

  const counter = document.createElement('span');
  counter.className = 'filter-result';
  counter.id = 'filter-result';
  bar.appendChild(counter);

  const clearLink = document.createElement('a');
  clearLink.className = 'clear-link';
  clearLink.id = 'clear-link';
  clearLink.textContent = '× Clear';
  clearLink.addEventListener('click', clearFilters);
  bar.appendChild(clearLink);
}

function appendLabel(bar, text) {
  const lbl = document.createElement('span');
  lbl.className = 'filter-label';
  lbl.textContent = text;
  bar.appendChild(lbl);
}

function appendSep(bar) {
  const sep = document.createElement('div');
  sep.style.cssText = 'width:1px;background:#dde3ed;height:18px;margin:0 4px;align-self:center;flex-shrink:0;';
  bar.appendChild(sep);
}

function buildSortBar() {
  const bar = document.getElementById('sort-bar');
  if (allDocs.length < 2) { bar.style.display = 'none'; return; }

  // Only show sort options that have real data — prevents phantom sort buttons
  // for fields that were not requested (they would all show "—" which sorts meaninglessly).
  // App # is always included as the primary identifier.
  const hasData = (key) => cardEls.some(el => el.dataset[key] && el.dataset[key] !== '—' && el.dataset[key] !== '');
  const sortOptions = [
    { label: 'App #', key: 'appnum' },
    { label: 'Patent #', key: 'patentnum' },
    { label: 'Title', key: 'title' },
    { label: 'Art Unit', key: 'artunit' },
  ].filter(opt => opt.key === 'appnum' || hasData(opt.key));

  if (sortOptions.length < 2) { bar.style.display = 'none'; return; }

  bar.style.display = 'flex';
  bar.innerHTML = '';

  appendLabel(bar, 'Sort:');

  sortOptions.forEach(({ label, key }) => {
    const pill = document.createElement('span');
    pill.className = 'sort-pill';
    pill.textContent = label;
    pill.dataset.sortkey = key;
    pill.addEventListener('click', () => {
      document.querySelectorAll('.sort-pill').forEach(p => p.classList.remove('active'));
      if (currentSort === key) {
        currentSort = null;
        renderCardsInOrder(allDocs);
      } else {
        currentSort = key;
        pill.classList.add('active');
        const sorted = [...allDocs].sort((a, b) => {
          const aEl = cardEls[allDocs.indexOf(a)];
          const bEl = cardEls[allDocs.indexOf(b)];
          const aVal = (aEl?.dataset[key] || '').toLowerCase();
          const bVal = (bEl?.dataset[key] || '').toLowerCase();
          return aVal.localeCompare(bVal, undefined, { numeric: key === 'appnum' || key === 'patentnum' });
        });
        renderCardsInOrder(sorted);
      }
    });
    bar.appendChild(pill);
  });
}

function renderCardsInOrder(orderedDocs) {
  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '';
  orderedDocs.forEach(a => {
    const idx = allDocs.indexOf(a);
    if (idx >= 0 && cardEls[idx]) cardsEl.appendChild(cardEls[idx]);
  });
  applyFilters();
}

function makePill(label, count, dim, val) {
  const pill = document.createElement('span');
  pill.className = 'pill';
  pill.dataset.dim = dim;
  pill.dataset.val = val;
  pill.innerHTML = `${label} <span class="pill-count">${count}</span>`;
  pill.addEventListener('click', () => {
    if (activeFilters[dim] === val) {
      activeFilters[dim] = null;
      pill.classList.remove('active');
    } else {
      document.querySelectorAll(`.pill[data-dim="${dim}"]`).forEach(p => p.classList.remove('active'));
      activeFilters[dim] = val;
      pill.classList.add('active');
    }
    applyFilters();
  });
  return pill;
}

function countBy(fn, filterFn = () => true) {
  const map = {};
  allDocs.forEach(d => {
    const v = fn(d);
    if (filterFn(v)) map[v] = (map[v] || 0) + 1;
  });
  return map;
}

function applyFilters() {
  let visible = 0;
  cardEls.forEach((el) => {
    const show =
      (!activeFilters.status   || el.dataset.status   === activeFilters.status) &&
      (!activeFilters.artunit  || el.dataset.artunit  === activeFilters.artunit) &&
      (!activeFilters.examiner || el.dataset.examiner === activeFilters.examiner) &&
      (!activeFilters.applicant|| el.dataset.applicant=== activeFilters.applicant) &&
      (!activeFilters.inventor || el.dataset.inventor === activeFilters.inventor);
    el.classList.toggle('hidden', !show);
    if (show) visible++;
  });
  document.getElementById('no-match').style.display = visible === 0 ? 'block' : 'none';
  const counter = document.getElementById('filter-result');
  const clearEl = document.getElementById('clear-link');
  const hasFilter = Object.values(activeFilters).some(Boolean);
  if (counter) counter.textContent = hasFilter ? `${visible} of ${allDocs.length} shown` : '';
  if (clearEl) clearEl.style.display = hasFilter ? 'inline' : 'none';
}

window.clearFilters = function() {
  activeFilters = {};
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  cardEls.forEach(el => el.classList.remove('hidden'));
  document.getElementById('no-match').style.display = 'none';
  const counter = document.getElementById('filter-result');
  const clearEl = document.getElementById('clear-link');
  if (counter) counter.textContent = '';
  if (clearEl) clearEl.style.display = 'none';
};

function clearFilters() { window.clearFilters(); }

function showError(msg) {
  document.getElementById('loading').style.display = 'none';
  const el = document.getElementById('error');
  el.style.display = 'block';
  el.textContent = 'Error: ' + msg;
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# View 2: Patent / Application XML — Claims & Abstract reader
# ---------------------------------------------------------------------------

XML_VIEW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Patent Claims & Abstract</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #1a3a6b; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .badge { background: #4a90d9; border-radius: 4px; padding: 2px 7px; font-size: 11px; }

.meta-bar { background: #e8f0fe; border-bottom: 1px solid #c5d8f7; padding: 8px 14px; font-size: 12px; }
.meta-bar h2 { font-size: 14px; font-weight: 600; color: #1a3a6b; margin-bottom: 4px; }
.meta-grid { display: flex; gap: 16px; flex-wrap: wrap; font-size: 11px; color: #555; }
.meta-item { display: flex; flex-direction: column; }
.meta-label { color: #888; font-size: 10px; text-transform: uppercase; }
.meta-val { color: #1a1a2e; font-weight: 500; }

.tabs { display: flex; border-bottom: 2px solid #dde3ed; background: #fff; padding: 0 14px; }
.tab { padding: 8px 14px; font-size: 12px; font-weight: 600; cursor: pointer; color: #888; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab.active { color: #1a3a6b; border-bottom-color: #1a3a6b; }
.tab:hover:not(.active) { color: #4a90d9; }

.tab-content { display: none; padding: 12px 14px; }
.tab-content.active { display: block; }

.abstract-text { background: #fff; border: 1px solid #dde3ed; border-radius: 6px; padding: 12px; line-height: 1.6; font-size: 13px; color: #333; }

.claim { background: #fff; border: 1px solid #dde3ed; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; }
.claim-num { font-size: 11px; font-weight: 700; color: #4a90d9; margin-bottom: 4px; }
.claim-text { line-height: 1.6; font-size: 12px; color: #333; white-space: pre-wrap; word-break: break-word; }
.claims-header { font-size: 11px; font-weight: 600; color: #1a3a6b; background: #e8f0fe; border: 1px solid #c5d8f7; border-radius: 4px; padding: 4px 10px; margin-bottom: 8px; }
.claim-type { display: inline-block; border-radius: 3px; padding: 1px 5px; font-size: 9px; font-weight: 700; margin-left: 6px; }
.claim-type-ind { background: #1a3a6b; color: #fff; }
.claim-type-dep { background: #6c757d; color: #fff; }

.actions { padding: 10px 14px; }
.btn { display: inline-block; border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; cursor: pointer; background: #1a3a6b; color: #fff; }
.btn:hover { background: #4a90d9; }

#loading { text-align: center; padding: 30px; color: #666; }
#error { background: #fde8e8; border: 1px solid #f5c6cb; color: #721c24; padding: 10px 14px; margin: 10px 14px; border-radius: 4px; }
</style>
</head>
<body>
<div class="header">
  <h1>Patent Claims &amp; Abstract</h1>
  <span class="badge" id="type-badge">—</span>
</div>
<div id="loading">Waiting for patent data...</div>
<div id="error" style="display:none"></div>
<div id="content" style="display:none">
  <div class="meta-bar">
    <h2 id="title">—</h2>
    <div class="meta-grid" id="meta-grid"></div>
  </div>
  <div class="actions">
    <button class="btn" id="open-btn">Open in Patent Center →</button>
    <button class="btn" id="google-btn" style="display:none;background:#4a90d9;margin-left:6px">Google Patents →</button>
  </div>
  <div class="tabs">
    <div class="tab active" data-tab="claims">Claims</div>
    <div class="tab" data-tab="abstract">Abstract</div>
  </div>
  <div class="tab-content active" id="tab-claims">
    <div class="claims-header" id="claims-header" style="display:none"></div>
    <div id="claims-list"></div>
  </div>
  <div class="tab-content" id="tab-abstract">
    <div class="abstract-text" id="abstract-text">No abstract available.</div>
  </div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'Patent XML View', version: '1.0.0' });

let currentAppNum = '';

app.ontoolresult = (result) => {
  const text = result.content?.find(c => c.type === 'text')?.text;
  try { render(JSON.parse(text)); }
  catch(e) { showError('Could not parse XML result: ' + e.message); }
};

app.connect();

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

document.getElementById('open-btn').addEventListener('click', () => {
  if (currentAppNum) {
    const num = currentAppNum.replace(/\//g, '').replace(/,/g, '');
    app.openLink({ url: `https://patentcenter.uspto.gov/applications/${num}` });
  }
});

let currentPatentNum = '';
document.getElementById('google-btn').addEventListener('click', () => {
  if (currentPatentNum) {
    app.openLink({ url: `https://patents.google.com/patent/US${currentPatentNum}` });
  }
});

function render(data) {
  document.getElementById('loading').style.display = 'none';
  if (data.error || data.status === 'error') { showError(data.message || data.error || 'API error'); return; }

  const appNum = data.application_number || data.applicationNumberText || '—';
  const patentNum = data.patent_number || data.patentNumber || '';
  const xmlType = data.xml_type || '';
  const isGranted = xmlType === 'PTGRXML';

  currentAppNum = appNum;
  currentPatentNum = patentNum;

  // Show Google Patents link for granted patents where we know the patent number
  const googleBtn = document.getElementById('google-btn');
  if (googleBtn) googleBtn.style.display = (isGranted && patentNum) ? '' : 'none';

  document.getElementById('type-badge').textContent = isGranted ? 'GRANTED PATENT' : 'APPLICATION';

  // Title from structured content, fields, or top-level
  const sc = data.structured_content || {};
  const title = sc.inventionTitle || data.fields?.inventionTitle || data.title || data.inventionTitle || '—';
  document.getElementById('title').textContent = title;

  // Meta grid — show Application always; show Patent when available
  const metaItems = [
    isGranted && patentNum ? ['Patent Number', patentNum] : null,
    ['Application Number', appNum],
    data.fields?.filingDate ? ['Filing Date', data.fields.filingDate.split('T')[0]] : null,
    data.fields?.grantDate  ? ['Grant Date',  data.fields.grantDate.split('T')[0]]  : null,
    data.fields?.groupArtUnitNumber ? ['Art Unit', data.fields.groupArtUnitNumber] : null,
    data.fields?.examinerNameText   ? ['Examiner', data.fields.examinerNameText]   : null,
  ].filter(Boolean);

  document.getElementById('meta-grid').innerHTML = metaItems.map(([label, val]) => `
    <div class="meta-item"><span class="meta-label">${label}</span><span class="meta-val">${val}</span></div>
  `).join('');

  // Abstract — look in structured_content first
  const abstractRaw = sc.abstract || data.fields?.abstract || data.abstract || data.extracted?.abstract || '';
  document.getElementById('abstract-text').textContent = abstractRaw || 'No abstract available.';

  // Claims — look in structured_content first
  const claimsEl = document.getElementById('claims-list');
  const claimsRaw = sc.claims || data.fields?.claims || data.claims || data.extracted?.claims || '';

  if (!claimsRaw || (Array.isArray(claimsRaw) && claimsRaw.length === 0)) {
    claimsEl.innerHTML = '<div style="text-align:center;padding:20px;color:#888">No claims data available.</div>';
  } else if (Array.isArray(claimsRaw)) {
    claimsEl.innerHTML = claimsRaw.map((c, i) => renderClaim(c, i + 1)).join('');
  } else {
    // Parse text claims — split on numbered patterns like "1." at line start
    const claimTexts = parseClaimsText(String(claimsRaw));
    claimsEl.innerHTML = claimTexts.length > 0
      ? claimTexts.map((c, i) => renderClaim(c, i + 1)).join('')
      : `<div class="claim"><div class="claim-text">${String(claimsRaw)}</div></div>`;
  }

  // Claims section sub-header indicating claim type
  const claimsHeader = document.getElementById('claims-header');
  if (claimsHeader) {
    claimsHeader.textContent = isGranted
      ? 'Final Granted Claims (PTGRXML)'
      : 'Application\'s Original Claims (APPXML)';
    claimsHeader.style.display = claimsRaw ? 'block' : 'none';
  }

  // Show/hide tabs based on what data was actually returned
  const hasClaims = !!(claimsRaw && (Array.isArray(claimsRaw) ? claimsRaw.length > 0 : String(claimsRaw).trim()));
  const hasAbstract = !!(abstractRaw && abstractRaw.trim());
  document.querySelector('.tab[data-tab="claims"]').style.display = hasClaims ? '' : 'none';
  document.querySelector('.tab[data-tab="abstract"]').style.display = hasAbstract ? '' : 'none';
  // Auto-activate first available tab
  if (!hasClaims && hasAbstract) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector('.tab[data-tab="abstract"]').classList.add('active');
    document.getElementById('tab-abstract').classList.add('active');
  }

  document.getElementById('content').style.display = 'block';
}

function parseClaimsText(text) {
  // Split on lines starting with a claim number: "1.", "2.", etc.
  const parts = text.split(/\n(?=\d+\.\s)/);
  return parts.map(p => p.trim()).filter(Boolean);
}

function renderClaim(claimText, num) {
  const text = typeof claimText === 'object' ? (claimText.text || JSON.stringify(claimText)) : String(claimText);
  const isDependent = /claim\s+\d+/i.test(text) || text.toLowerCase().includes('the method of claim');
  const typeLabel = isDependent ? 'DEP' : 'IND';
  const typeCls = isDependent ? 'claim-type-dep' : 'claim-type-ind';
  return `
    <div class="claim">
      <div class="claim-num">Claim ${num} <span class="claim-type ${typeCls}">${typeLabel}</span></div>
      <div class="claim-text">${text}</div>
    </div>
  `;
}

function showError(msg) {
  document.getElementById('loading').style.display = 'none';
  const el = document.getElementById('error');
  el.style.display = 'block';
  el.textContent = 'Error: ' + msg;
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# View 3: Recent Downloads panel
# Fetches from the local proxy /api/recent-downloads endpoint and renders
# a navigable list. Refreshes when pfw_get_document_download or
# pfw_get_granted_patent_documents_download tools return a result.
# ---------------------------------------------------------------------------

DOWNLOADS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Recent Downloads</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; background: #f8f9fa; color: #1a1a2e; }

.header { background: #1a3a6b; color: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 14px; font-weight: 600; }
.header .count { background: #4a90d9; border-radius: 4px; padding: 2px 7px; font-size: 11px; }
.header .refresh-btn { margin-left: auto; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); color: #fff; border-radius: 4px; padding: 3px 8px; font-size: 11px; cursor: pointer; }
.header .refresh-btn:hover { background: rgba(255,255,255,0.25); }

.tip { background: #fff9e6; border-bottom: 1px solid #ffe08a; padding: 5px 14px; font-size: 11px; color: #6b5000; }

.container { padding: 10px 14px; }

.empty-state { text-align: center; padding: 40px 20px; color: #888; }
.empty-icon { font-size: 32px; margin-bottom: 8px; }
.empty-text { font-size: 13px; }
.empty-hint { font-size: 11px; color: #aaa; margin-top: 4px; }

.doc-card { background: #fff; border: 1px solid #dde3ed; border-radius: 6px; margin-bottom: 8px; padding: 10px 12px; display: flex; align-items: flex-start; gap: 10px; }
.doc-card:hover { border-color: #4a90d9; box-shadow: 0 1px 4px rgba(74,144,217,0.12); }

.doc-icon { width: 32px; height: 32px; border-radius: 4px; background: #e8f0fe; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.doc-info { flex: 1; min-width: 0; }
.doc-title { font-weight: 600; font-size: 12px; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-meta { font-size: 11px; color: #888; display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 5px; }
.doc-type-badge { display: inline-block; background: #e8f0fe; color: #1a3a6b; border-radius: 3px; padding: 1px 5px; font-size: 10px; font-weight: 700; }
.doc-type-CTNF { background: #fde8e8; color: #721c24; }
.doc-type-CTFR { background: #fff3cd; color: #856404; }
.doc-type-NOA  { background: #d4edda; color: #155724; }
.doc-actions { display: flex; gap: 6px; }
.btn { border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.btn-download { background: #1a3a6b; color: #fff; text-decoration: none; display: inline-block; }
.btn-download:hover { background: #4a90d9; }

.timestamp { font-size: 10px; color: #bbb; margin-left: auto; white-space: nowrap; align-self: center; }

#status { font-size: 11px; color: #888; text-align: center; padding: 6px; }
</style>
</head>
<body>
<div class="header">
  <h1>Recent Downloads</h1>
  <span class="count" id="count-badge">0</span>
  <button class="refresh-btn" onclick="loadDownloads()">↻ Refresh</button>
</div>
<div class="tip">Click Download to open a document in your browser. Links are valid for 7 days.</div>
<div id="status"></div>
<div class="container" id="content">
  <div class="empty-state" id="empty-state">
    <div class="empty-icon">📂</div>
    <div class="empty-text">No recent downloads yet</div>
    <div class="empty-hint">Use pfw_get_document_download or pfw_get_granted_patent_documents_download to generate links</div>
  </div>
  <div id="cards"></div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const app = new App({ name: 'PFW Recent Downloads', version: '1.0.0' });

// In-session download store — populated directly from tool results (no fetch needed)
let sessionDownloads = [];
// proxyBaseUrl: derived from the first proxy_download_url seen in a tool result.
// For localhost deployments: http://localhost:8084
// For external deployments: https://mcp.example.com
let proxyBaseUrl = 'http://localhost:8080';

const COMP_TITLES = { abstract: 'Abstract', drawings: 'Drawings', specification: 'Specification', claims: 'Claims (Granted)' };

app.ontoolresult = (result) => {
  try {
    const text = result.content?.find(c => c.type === 'text')?.text;
    const data = JSON.parse(text);
    const now = new Date().toISOString();
    const newDocs = [];

    // pfw_get_document_download
    if (data.proxy_download_url && data.document_info) {
      const info = data.document_info;
      newDocs.push({
        title: info.document_description || info.document_code || 'Document',
        doc_type: info.document_code || '',
        app_number: data.application_number || '',
        proxy_url: data.proxy_download_url,
        generated_at: now,
      });
      const baseMatch = data.proxy_download_url.match(/^(https?:\/\/[^/]+)/);
      if (baseMatch) proxyBaseUrl = baseMatch[1];
    }

    // pfw_get_granted_patent_documents_download
    if (data.granted_patent_components) {
      for (const [comp, compData] of Object.entries(data.granted_patent_components)) {
        if (compData.proxy_download_url) {
          newDocs.push({
            title: `${COMP_TITLES[comp] || comp} \u2014 App ${data.application_number}`,
            doc_type: comp,
            app_number: data.application_number || '',
            proxy_url: compData.proxy_download_url,
            generated_at: now,
          });
          const baseMatch = compData.proxy_download_url.match(/^(https?:\/\/[^/]+)/);
          if (baseMatch) proxyBaseUrl = baseMatch[1];
        }
      }
    }

    if (newDocs.length > 0) {
      sessionDownloads = [...newDocs, ...sessionDownloads].slice(0, 10);
      renderDownloads(sessionDownloads);
      document.getElementById('status').textContent = '';
      return;
    }
  } catch {}
  // No directly parseable downloads — try proxy fetch as fallback
  loadDownloads();
};

app.connect();

// Delegated click handler — use app.openLink() so Claude Desktop opens the
// URL in the system browser, bypassing iframe sandbox restrictions.
document.getElementById('cards').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-url]');
  if (!btn) return;
  const url = btn.dataset.url;
  if (!url) return;
  try {
    await app.openLink({ url });
  } catch {
    // Fallback for hosts that don't support openLink
    window.open(url, '_blank');
  }
});

window.loadDownloads = async function() {
  const statusEl = document.getElementById('status');
  statusEl.textContent = 'Refreshing...';
  try {
    const resp = await fetch(`${proxyBaseUrl}/api/recent-downloads`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const docs = await resp.json();
    // Merge proxy results with session store, deduplicate by proxy_url
    const seen = new Set(sessionDownloads.map(d => d.proxy_url));
    const merged = [...sessionDownloads, ...docs.filter(d => !seen.has(d.proxy_url))].slice(0, 10);
    sessionDownloads = merged;
    renderDownloads(sessionDownloads);
    statusEl.textContent = '';
  } catch (e) {
    // Proxy fetch failed (CSP/CORS/not running) — show what we have from session
    renderDownloads(sessionDownloads);
    statusEl.textContent = sessionDownloads.length === 0 ? `Generate a download to see links here.` : '';
  }
};

function renderDownloads(docs) {
  const countBadge = document.getElementById('count-badge');
  const emptyState = document.getElementById('empty-state');
  const cardsEl = document.getElementById('cards');

  countBadge.textContent = docs.length;
  emptyState.style.display = docs.length === 0 ? 'block' : 'none';
  cardsEl.innerHTML = '';

  docs.forEach(doc => {
    const card = buildCard(doc);
    cardsEl.appendChild(card);
  });
}

const DOC_ICONS = {
  CTNF: '📋', CTFR: '📋', NOA: '✅', CTAV: '⚡', CTEQ: '❓',
  claims: '📜', abstract: '📝', drawings: '🖼️', spec: '📖', default: '📄'
};

function buildCard(doc) {
  const div = document.createElement('div');
  div.className = 'doc-card';

  const docType = doc.doc_type || 'default';
  const icon = DOC_ICONS[docType] || DOC_ICONS.default;
  const typeCls = `doc-type-badge doc-type-${docType}`;
  const time = doc.generated_at ? formatTime(doc.generated_at) : '';

  div.innerHTML = `
    <div class="doc-icon">${icon}</div>
    <div class="doc-info">
      <div class="doc-title">${doc.title || doc.filename || 'Document'}</div>
      <div class="doc-meta">
        <span class="${typeCls}">${docType}</span>
        <span>App: ${doc.app_number || '—'}</span>
      </div>
      <div class="doc-actions">
        <button class="btn btn-download" data-url="${doc.proxy_url}">Download PDF</button>
      </div>
    </div>
    ${time ? `<div class="timestamp">${time}</div>` : ''}
  `;

  return div;
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return d.toLocaleDateString();
  } catch { return ''; }
}
</script>
</body>
</html>"""
