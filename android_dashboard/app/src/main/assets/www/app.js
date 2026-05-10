/* ═══════════════════════════════════════════
   GAI MEDashboard – Mobile App Logic v2.0
   ═══════════════════════════════════════════ */

'use strict';

// ──── CONFIG ─────────────────────────────
const CONFIG = {
  rangeYears: 3,
  fredKey: localStorage.getItem('fredKey') || '',
  teKey: localStorage.getItem('teKey') || '',
  cacheTTL: 60 * 60 * 1000, // 1 hour
};

const COLORS = {
  us: '#60A5FA', cn: '#F87171', tw: '#34D399',
  jp: '#FBBF24', eu: '#A78BFA', kr: '#F472B6',
};

const COUNTRY_LABELS = {
  us: '🇺🇸 美國', cn: '🇨🇳 中國', tw: '🇹🇼 台灣',
  jp: '🇯🇵 日本', eu: '🇪🇺 歐洲', kr: '🇰🇷 韓國',
};

// Chart instances registry
const charts = {};
// Visibility toggles
const visibility = {
  pmi: { us: true, cn: true, tw: true, jp: true, eu: true },
  cli: { us: true, cn: true, jp: true, eu: true, kr: true },
};
// Cached data store
const dataStore = {};

// ──── UTILITY ────────────────────────────
function parseDate(s) {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d) ? null : d;
}

function formatDate(d) {
  if (!d) return '—';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function cutoffDate() {
  const d = new Date();
  d.setFullYear(d.getFullYear() - CONFIG.rangeYears);
  return d;
}

function filterByRange(data) {
  if (!data || !data.length) return [];
  const cut = cutoffDate();
  return data.filter(p => p.date >= cut);
}

function getLatest(data) {
  if (!data || !data.length) return { value: null, date: null };
  const last = data[data.length - 1];
  return { value: last.value, date: last.date };
}

function cacheKey(key) { return `cache_${key}`; }

function getCached(key) {
  try {
    const raw = localStorage.getItem(cacheKey(key));
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (Date.now() - obj.ts > CONFIG.cacheTTL) return null;
    return obj.data;
  } catch { return null; }
}

function setCache(key, data) {
  try {
    localStorage.setItem(cacheKey(key), JSON.stringify({ ts: Date.now(), data }));
  } catch { /* storage full, ignore */ }
}

// ──── DATA FETCHERS ──────────────────────

async function fetchJSON(url, timeout = 15000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}

// DBnomics fetch
async function fetchDBnomics(provider, dataset, series) {
  const key = `dbn_${provider}_${dataset}_${series}`;
  const cached = getCached(key);
  if (cached) return cached;

  const url = `https://api.db.nomics.world/v22/series/${provider}/${dataset}/${encodeURIComponent(series)}?observations=1&format=json`;
  const json = await fetchJSON(url);
  const docs = json?.series?.docs;
  if (!docs || !docs.length) return [];

  const doc = docs[0];
  const periods = doc.period || [];
  const values = doc.value || [];
  const data = [];
  for (let i = 0; i < periods.length; i++) {
    const v = parseFloat(values[i]);
    if (isNaN(v)) continue;
    const d = parseDate(periods[i]);
    if (d) data.push({ date: d, value: v });
  }
  data.sort((a, b) => a.date - b.date);
  setCache(key, data);
  return data;
}

// FRED fetch
async function fetchFRED(seriesId, yearsBack = 10) {
  const key = `fred_${seriesId}`;
  const cached = getCached(key);
  if (cached) return cached;

  if (!CONFIG.fredKey) return [];

  const start = new Date();
  start.setFullYear(start.getFullYear() - yearsBack);
  const startStr = start.toISOString().slice(0, 10);
  const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${encodeURIComponent(seriesId)}&api_key=${encodeURIComponent(CONFIG.fredKey)}&file_type=json&observation_start=${startStr}`;

  const json = await fetchJSON(url);
  const obs = json?.observations || [];
  const data = [];
  for (const o of obs) {
    const v = parseFloat(o.value);
    if (isNaN(v)) continue;
    const d = parseDate(o.date);
    if (d) data.push({ date: d, value: v });
  }
  data.sort((a, b) => a.date - b.date);
  setCache(key, data);
  return data;
}

// Compute YoY from level data
function computeYoY(data) {
  if (!data || data.length < 13) return [];
  const result = [];
  for (let i = 12; i < data.length; i++) {
    const prev = data[i - 12].value;
    if (prev === 0) continue;
    result.push({
      date: data[i].date,
      value: ((data[i].value - prev) / Math.abs(prev)) * 100,
    });
  }
  return result;
}

// ──── DATA LOADERS ───────────────────────

async function loadPMI() {
  const results = {};
  const tasks = [
    // US PMI - ISM via DBnomics
    fetchDBnomics('ISM', 'pmi', 'pm-sa').then(d => results.us = d).catch(() => results.us = []),
    // China PMI - NBS via DBnomics
    fetchDBnomics('OECD', 'MEI', 'CHN.BSCICP03.STSA.M').then(d => {
      results.cn = d.map(p => ({ date: p.date, value: p.value > 80 ? p.value - 50 : p.value }));
    }).catch(() => results.cn = []),
    // Taiwan PMI - via DBnomics OECD BCI
    fetchDBnomics('OECD', 'MEI', 'TWN.BSCICP03.STSA.M').then(d => {
      results.tw = d.map(p => ({ date: p.date, value: p.value > 80 ? p.value - 50 : p.value }));
    }).catch(() => results.tw = []),
    // Japan PMI
    fetchDBnomics('OECD', 'MEI', 'JPN.BSCICP03.STSA.M').then(d => {
      results.jp = d.map(p => ({ date: p.date, value: p.value > 80 ? p.value - 50 : p.value }));
    }).catch(() => results.jp = []),
    // Euro PMI
    fetchDBnomics('OECD', 'MEI', 'EA19.BSCICP03.STSA.M').then(d => {
      results.eu = d.map(p => ({ date: p.date, value: p.value > 80 ? p.value - 50 : p.value }));
    }).catch(() => results.eu = []),
  ];
  await Promise.allSettled(tasks);
  dataStore.pmi = results;
  return results;
}

async function loadCLI() {
  const results = {};
  const series = {
    us: 'USA.LOLITONO.STSA.M',
    cn: 'CHN.LOLITONO.STSA.M',
    jp: 'JPN.LOLITONO.STSA.M',
    eu: 'G4E.LOLITONO.STSA.M',
    kr: 'KOR.LOLITONO.STSA.M',
  };
  const tasks = Object.entries(series).map(([k, s]) =>
    fetchDBnomics('OECD', 'MEI', s).then(d => results[k] = d).catch(() => results[k] = [])
  );
  await Promise.allSettled(tasks);
  dataStore.cli = results;
  return results;
}

async function loadExportYoY() {
  let raw = [];
  // Try FRED first
  if (CONFIG.fredKey) {
    try { raw = await fetchFRED('XTEXVA01TWM667S', 10); } catch {}
  }
  // Fallback: DBnomics OECD
  if (!raw.length) {
    try { raw = await fetchDBnomics('OECD', 'MEI', 'TWN.XTEXVA01.STSA.M'); } catch {}
  }
  const yoy = computeYoY(raw);
  dataStore.exportYoY = yoy;
  dataStore.exportRaw = raw;
  return yoy;
}

async function loadMoney() {
  const results = {};
  // US M1
  let usM1 = [];
  if (CONFIG.fredKey) {
    try { usM1 = await fetchFRED('M1SL', 10); } catch {}
  }
  if (!usM1.length) {
    try { usM1 = await fetchDBnomics('OECD', 'MEI', 'USA.MANMM101.STSA.M'); } catch {}
  }
  results.us = computeYoY(usM1);

  // Taiwan M1B via DBnomics OECD
  let twM1 = [];
  try { twM1 = await fetchDBnomics('OECD', 'MEI', 'TWN.MANMM101.STSA.M'); } catch {}
  results.tw = computeYoY(twM1);

  dataStore.money = results;
  return results;
}

async function loadVIX() {
  let data = [];
  if (CONFIG.fredKey) {
    try { data = await fetchFRED('VIXCLS', 11); } catch {}
  }
  dataStore.vix = data;
  return data;
}

async function loadSpread() {
  let data = [];
  if (CONFIG.fredKey) {
    try { data = await fetchFRED('T10Y2Y', 10); } catch {}
  }
  dataStore.spread = data;
  return data;
}

async function loadSemiPPI() {
  let data = [];
  if (CONFIG.fredKey) {
    try { data = await fetchFRED('PCU33443344', 10); } catch {}
  }
  dataStore.semiPPI = data;
  return data;
}

async function loadBrent() {
  let data = [];
  if (CONFIG.fredKey) {
    try { data = await fetchFRED('DCOILBRENTEU', 10); } catch {}
  }
  dataStore.brent = data;
  return data;
}

async function loadUMCSENT() {
  let data = [];
  if (CONFIG.fredKey) {
    try { data = await fetchFRED('UMCSENT', 10); } catch {}
  }
  dataStore.umcsent = data;
  return data;
}

// ──── CHART CREATION ─────────────────────

const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 600, easing: 'easeOutQuart' },
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      display: false,
    },
    tooltip: {
      backgroundColor: 'rgba(22, 27, 34, 0.95)',
      titleColor: '#E6EDF3',
      bodyColor: '#8B949E',
      borderColor: 'rgba(77, 208, 207, 0.3)',
      borderWidth: 1,
      cornerRadius: 8,
      padding: 10,
      titleFont: { size: 12, weight: '600' },
      bodyFont: { size: 11 },
      displayColors: true,
      boxWidth: 8,
      boxHeight: 8,
      boxPadding: 4,
    },
  },
  scales: {
    x: {
      type: 'time',
      time: { unit: 'month', tooltipFormat: 'yyyy-MM', displayFormats: { month: 'yy/MM' } },
      grid: { color: 'rgba(77, 208, 207, 0.06)' },
      ticks: { color: '#6E7681', font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
      border: { display: false },
    },
    y: {
      grid: { color: 'rgba(77, 208, 207, 0.06)' },
      ticks: { color: '#6E7681', font: { size: 10 }, padding: 4 },
      border: { display: false },
    },
  },
};

// We need the date adapter - load it
function loadDateAdapter() {
  return new Promise((resolve) => {
    if (window._dateAdapterLoaded) return resolve();
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js';
    s.onload = () => { window._dateAdapterLoaded = true; resolve(); };
    s.onerror = () => resolve(); // degrade gracefully
    document.head.appendChild(s);
  });
}

function createMultiLineChart(canvasId, datasets, refLine = null) {
  if (charts[canvasId]) { charts[canvasId].destroy(); }
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const config = {
    type: 'line',
    data: { datasets },
    options: {
      ...structuredClone(chartDefaults),
      plugins: {
        ...chartDefaults.plugins,
        annotation: refLine ? {
          annotations: {
            refLine: {
              type: 'line',
              yMin: refLine.y,
              yMax: refLine.y,
              borderColor: refLine.color || 'rgba(251, 191, 36, 0.5)',
              borderWidth: 1.5,
              borderDash: [6, 4],
              label: {
                display: true,
                content: refLine.label || '',
                position: 'end',
                backgroundColor: 'rgba(22, 27, 34, 0.8)',
                color: refLine.color || '#FBBF24',
                font: { size: 10, weight: '500' },
                padding: { top: 2, bottom: 2, left: 6, right: 6 },
              },
            },
          },
        } : {},
      },
    },
  };

  charts[canvasId] = new Chart(ctx, config);
}

function createAreaChart(canvasId, data, color, label, refLine = null) {
  if (charts[canvasId]) { charts[canvasId].destroy(); }
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const filtered = filterByRange(data);
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);

  const config = {
    type: 'line',
    data: {
      datasets: [{
        label,
        data: filtered.map(p => ({ x: p.date, y: p.value })),
        borderColor: color,
        backgroundColor: `rgba(${r},${g},${b},0.15)`,
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        pointHitRadius: 10,
      }],
    },
    options: {
      ...structuredClone(chartDefaults),
      plugins: {
        ...chartDefaults.plugins,
        annotation: refLine ? {
          annotations: {
            refLine: {
              type: 'line', yMin: refLine.y, yMax: refLine.y,
              borderColor: refLine.color || 'rgba(255,255,255,0.2)',
              borderWidth: 1.5, borderDash: [6, 4],
              label: {
                display: true, content: refLine.label || '',
                position: 'end',
                backgroundColor: 'rgba(22,27,34,0.8)',
                color: refLine.color || '#8B949E',
                font: { size: 10, weight: '500' },
                padding: { top: 2, bottom: 2, left: 6, right: 6 },
              },
            },
          },
        } : {},
      },
    },
  };

  charts[canvasId] = new Chart(ctx, config);
}

function createSplitAreaChart(canvasId, data, posColor, negColor, label, refLine = null) {
  if (charts[canvasId]) { charts[canvasId].destroy(); }
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const filtered = filterByRange(data);
  const posData = filtered.map(p => ({ x: p.date, y: Math.max(0, p.value) }));
  const negData = filtered.map(p => ({ x: p.date, y: Math.min(0, p.value) }));

  const pr = parseInt(posColor.slice(1, 3), 16);
  const pg = parseInt(posColor.slice(3, 5), 16);
  const pb = parseInt(posColor.slice(5, 7), 16);
  const nr = parseInt(negColor.slice(1, 3), 16);
  const ng = parseInt(negColor.slice(3, 5), 16);
  const nb = parseInt(negColor.slice(5, 7), 16);

  const annotations = {};
  if (refLine) {
    annotations.refLine = {
      type: 'line', yMin: refLine.y, yMax: refLine.y,
      borderColor: refLine.color || 'rgba(251,191,36,0.5)',
      borderWidth: 1.5, borderDash: [6, 4],
      label: {
        display: true, content: refLine.label || '',
        position: 'end',
        backgroundColor: 'rgba(22,27,34,0.8)',
        color: refLine.color || '#FBBF24',
        font: { size: 10, weight: '500' },
        padding: { top: 2, bottom: 2, left: 6, right: 6 },
      },
    };
  }

  const config = {
    type: 'line',
    data: {
      datasets: [
        {
          label: label + ' (正)',
          data: posData,
          borderColor: posColor,
          backgroundColor: `rgba(${pr},${pg},${pb},0.2)`,
          borderWidth: 1.5, fill: true, tension: 0.3, pointRadius: 0, pointHitRadius: 10,
        },
        {
          label: label + ' (負)',
          data: negData,
          borderColor: negColor,
          backgroundColor: `rgba(${nr},${ng},${nb},0.2)`,
          borderWidth: 1.5, fill: true, tension: 0.3, pointRadius: 0, pointHitRadius: 10,
        },
      ],
    },
    options: {
      ...structuredClone(chartDefaults),
      plugins: {
        ...chartDefaults.plugins,
        annotation: { annotations },
      },
    },
  };

  charts[canvasId] = new Chart(ctx, config);
}

// ──── UI RENDERERS ───────────────────────

function renderValueCards(containerId, items) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = items.map(item => {
    const val = item.value != null ? (typeof item.value === 'number' ? item.value.toFixed(2) : item.value) : '—';
    const dateStr = item.date ? formatDate(item.date) : '—';
    let badgeClass = 'badge-neutral';
    let badgeText = '—';
    if (item.threshold != null && item.value != null) {
      if (item.value >= item.threshold) {
        badgeClass = 'badge-expand';
        badgeText = '擴張';
      } else {
        badgeClass = 'badge-contract';
        badgeText = '收縮';
      }
    } else if (item.badgeText) {
      badgeClass = item.badgeClass || 'badge-neutral';
      badgeText = item.badgeText;
    }
    return `
      <div class="value-card">
        <div class="flag">${item.flag || ''}</div>
        <div class="label">${item.label}</div>
        <div class="value">${val}</div>
        <div class="date">${dateStr}</div>
        <div class="badge ${badgeClass}">${badgeText}</div>
      </div>
    `;
  }).join('');
}

function renderLegendChips(containerId, keys, group) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = keys.map(k => {
    const active = visibility[group]?.[k] !== false;
    return `<button class="legend-chip ${active ? 'active' : ''}"
      style="--chip-color:${COLORS[k]}" data-group="${group}" data-key="${k}">
      ${COUNTRY_LABELS[k] || k}
    </button>`;
  }).join('');

  el.querySelectorAll('.legend-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const g = btn.dataset.group;
      const k = btn.dataset.key;
      visibility[g][k] = !visibility[g][k];
      btn.classList.toggle('active');
      updateChartVisibility(g);
    });
  });
}

function updateChartVisibility(group) {
  const chartId = group === 'pmi' ? 'pmi-chart' : 'cli-chart';
  const chart = charts[chartId];
  if (!chart) return;
  const keys = Object.keys(visibility[group]);
  chart.data.datasets.forEach((ds, i) => {
    if (i < keys.length) {
      ds.hidden = !visibility[group][keys[i]];
    }
  });
  chart.update('none');
}

function renderVIXMetrics(data) {
  const el = document.getElementById('vix-metrics');
  if (!el) return;
  const filtered = filterByRange(data);
  if (!filtered.length) { el.innerHTML = ''; return; }
  const latest = filtered[filtered.length - 1];
  const max = Math.max(...filtered.map(p => p.value));
  const min = Math.min(...filtered.map(p => p.value));
  const cls = latest.value >= 30 ? 'negative' : latest.value >= 20 ? 'neutral' : 'positive';
  el.innerHTML = `
    <div class="metric-card">
      <div class="metric-label">VIX 最新值</div>
      <div class="metric-value ${cls}">${latest.value.toFixed(2)}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">期間最高</div>
      <div class="metric-value negative">${max.toFixed(2)}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">期間最低</div>
      <div class="metric-value positive">${min.toFixed(2)}</div>
    </div>
  `;
}

function hideLoading(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

function showError(msg) {
  const panel = document.getElementById('error-panel');
  const msgEl = document.getElementById('error-msg');
  if (panel && msgEl) {
    msgEl.textContent = msg;
    panel.classList.add('show');
  }
}

// ──── PANEL RENDERERS ────────────────────

async function renderPanelA() {
  // PMI
  try {
    const pmi = await loadPMI();
    const keys = ['us', 'cn', 'tw', 'jp', 'eu'];

    // Cards
    const cards = keys.map(k => {
      const l = getLatest(filterByRange(pmi[k]));
      return { flag: COUNTRY_LABELS[k].slice(0, 2), label: COUNTRY_LABELS[k].slice(2).trim() + ' PMI', value: l.value, date: l.date, threshold: 50 };
    });
    renderValueCards('pmi-cards', cards);
    renderLegendChips('pmi-legends', keys, 'pmi');

    // Chart
    const datasets = keys.map(k => ({
      label: COUNTRY_LABELS[k],
      data: filterByRange(pmi[k]).map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS[k],
      backgroundColor: 'transparent',
      borderWidth: 2,
      tension: 0.3,
      pointRadius: 0,
      pointHitRadius: 10,
      hidden: !visibility.pmi[k],
    }));
    createMultiLineChart('pmi-chart', datasets, { y: 50, label: '50 榮枯線', color: '#FBBF24' });
    hideLoading('pmi-loading');
  } catch (e) {
    hideLoading('pmi-loading');
    console.error('PMI load error:', e);
  }

  // Export YoY
  try {
    const exportYoY = await loadExportYoY();
    const l = getLatest(filterByRange(exportYoY));
    renderValueCards('export-cards', [{
      flag: '🇹🇼', label: '台灣出口 YoY',
      value: l.value != null ? l.value.toFixed(1) + '%' : '—',
      date: l.date,
      badgeText: l.value != null ? (l.value >= 0 ? '正成長' : '負成長') : '—',
      badgeClass: l.value != null ? (l.value >= 0 ? 'badge-expand' : 'badge-contract') : 'badge-neutral',
    }]);
    createSplitAreaChart('export-chart', exportYoY, '#34D399', '#F87171', '出口 YoY',
      { y: 0, label: '0% 基準線', color: '#FBBF24' });
    hideLoading('export-loading');
  } catch (e) {
    hideLoading('export-loading');
    console.error('Export load error:', e);
  }

  // M1B
  try {
    const money = await loadMoney();
    const items = [];
    const l1 = getLatest(filterByRange(money.us));
    items.push({ flag: '🇺🇸', label: '美國 M1 YoY', value: l1.value != null ? l1.value.toFixed(1) + '%' : '—', date: l1.date,
      badgeText: l1.value != null ? (l1.value >= 0 ? '擴張' : '收縮') : '—',
      badgeClass: l1.value != null ? (l1.value >= 0 ? 'badge-expand' : 'badge-contract') : 'badge-neutral',
    });
    const l2 = getLatest(filterByRange(money.tw));
    items.push({ flag: '🇹🇼', label: '台灣 M1B YoY', value: l2.value != null ? l2.value.toFixed(1) + '%' : '—', date: l2.date,
      badgeText: l2.value != null ? (l2.value >= 0 ? '擴張' : '收縮') : '—',
      badgeClass: l2.value != null ? (l2.value >= 0 ? 'badge-expand' : 'badge-contract') : 'badge-neutral',
    });
    renderValueCards('money-cards', items);

    const moneyDatasets = [];
    if (money.us.length) moneyDatasets.push({
      label: '🇺🇸 US M1 YoY', data: filterByRange(money.us).map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS.us, backgroundColor: 'transparent', borderWidth: 2, tension: 0.3, pointRadius: 0, pointHitRadius: 10,
    });
    if (money.tw.length) moneyDatasets.push({
      label: '🇹🇼 TW M1B YoY', data: filterByRange(money.tw).map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS.tw, backgroundColor: 'transparent', borderWidth: 2, tension: 0.3, pointRadius: 0, pointHitRadius: 10,
    });
    createMultiLineChart('money-chart', moneyDatasets, { y: 0, label: '0% 基準', color: '#FBBF24' });
    hideLoading('money-loading');
  } catch (e) {
    hideLoading('money-loading');
    console.error('Money load error:', e);
  }
}

async function renderPanelB() {
  // CLI
  try {
    const cli = await loadCLI();
    const keys = ['us', 'cn', 'jp', 'eu', 'kr'];

    const cards = keys.map(k => {
      const l = getLatest(filterByRange(cli[k]));
      return {
        flag: COUNTRY_LABELS[k].slice(0, 2), label: COUNTRY_LABELS[k].slice(2).trim() + ' CLI',
        value: l.value, date: l.date, threshold: 100,
      };
    });
    renderValueCards('cli-cards', cards);
    renderLegendChips('cli-legends', keys, 'cli');

    const datasets = keys.map(k => ({
      label: COUNTRY_LABELS[k],
      data: filterByRange(cli[k]).map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS[k],
      backgroundColor: 'transparent',
      borderWidth: 2,
      tension: 0.3,
      pointRadius: 0,
      pointHitRadius: 10,
      hidden: !visibility.cli[k],
    }));
    createMultiLineChart('cli-chart', datasets, { y: 100, label: '100 趨勢線', color: '#60A5FA' });
    hideLoading('cli-loading');
  } catch (e) {
    hideLoading('cli-loading');
    console.error('CLI load error:', e);
  }

  // Semiconductor PPI
  try {
    const semiPPI = await loadSemiPPI();
    if (semiPPI.length) {
      createAreaChart('semi-chart', semiPPI, '#00B0F0', 'Semiconductor PPI');
    }
    hideLoading('semi-loading');
  } catch (e) { hideLoading('semi-loading'); }

  // Brent Oil
  try {
    const brent = await loadBrent();
    if (brent.length) {
      createAreaChart('oil-chart', brent, '#8B4513', 'Brent Crude');
    }
    hideLoading('oil-loading');
  } catch (e) { hideLoading('oil-loading'); }
}

async function renderPanelC() {
  // VIX
  try {
    const vix = await loadVIX();
    if (vix.length) {
      renderVIXMetrics(vix);
      const filtered = filterByRange(vix);
      const latest = filtered.length ? filtered[filtered.length - 1].value : 20;
      const color = latest >= 30 ? '#F87171' : latest >= 20 ? '#FBBF24' : '#34D399';
      createAreaChart('vix-chart', vix, color, 'VIX',
        { y: 20, label: '正常 (<20)', color: 'rgba(255,255,255,0.3)' });
    }
    hideLoading('vix-loading');
  } catch (e) { hideLoading('vix-loading'); }

  // 10Y-2Y Spread
  try {
    const spread = await loadSpread();
    if (spread.length) {
      createSplitAreaChart('spread-chart', spread, '#34D399', '#F87171', '利差',
        { y: 0, label: '0% 倒掛分界', color: '#FBBF24' });
    }
    hideLoading('spread-loading');
  } catch (e) { hideLoading('spread-loading'); }

  // Consumer Sentiment
  try {
    const umcsent = await loadUMCSENT();
    if (umcsent.length) {
      createAreaChart('umcsent-chart', umcsent, '#FFA500', 'Consumer Sentiment');
    }
    hideLoading('umcsent-loading');
  } catch (e) { hideLoading('umcsent-loading'); }
}

// ──── UI EVENT HANDLERS ──────────────────

function toggleInfo(id) {
  const panel = document.getElementById(id);
  if (panel) panel.classList.toggle('open');
}

// Make it global for onclick
window.toggleInfo = toggleInfo;

function initTabs() {
  const nav = document.getElementById('tab-nav');
  if (!nav) return;
  const buttons = nav.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.tab-panel');
  const rendered = { 'panel-a': false, 'panel-b': false, 'panel-c': false };

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const tabId = btn.dataset.tab;
      const panel = document.getElementById(tabId);
      if (panel) panel.classList.add('active');

      // Lazy load panel data
      if (!rendered[tabId]) {
        rendered[tabId] = true;
        if (tabId === 'panel-b') renderPanelB();
        if (tabId === 'panel-c') renderPanelC();
      }
    });
  });

  // Panel A loads immediately
  rendered['panel-a'] = true;
  renderPanelA();
}

function initRangePills() {
  const bar = document.getElementById('settings-bar');
  if (!bar) return;
  bar.querySelectorAll('.pill[data-range]').forEach(pill => {
    pill.addEventListener('click', () => {
      bar.querySelectorAll('.pill[data-range]').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      CONFIG.rangeYears = parseInt(pill.dataset.range);
      refreshAllCharts();
    });
  });
}

function initAPIModal() {
  const modal = document.getElementById('api-modal');
  const btnOpen = document.getElementById('btn-api-key');
  const btnCancel = document.getElementById('btn-modal-cancel');
  const btnSave = document.getElementById('btn-modal-save');
  const fredInput = document.getElementById('fred-key-input');
  const teInput = document.getElementById('te-key-input');

  if (btnOpen) btnOpen.addEventListener('click', () => {
    fredInput.value = CONFIG.fredKey;
    teInput.value = CONFIG.teKey;
    modal.classList.add('show');
  });

  if (btnCancel) btnCancel.addEventListener('click', () => modal.classList.remove('show'));

  if (modal) modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.remove('show');
  });

  if (btnSave) btnSave.addEventListener('click', () => {
    CONFIG.fredKey = fredInput.value.trim();
    CONFIG.teKey = teInput.value.trim();
    localStorage.setItem('fredKey', CONFIG.fredKey);
    localStorage.setItem('teKey', CONFIG.teKey);
    modal.classList.remove('show');
    // Clear all caches and reload
    clearAllCaches();
    refreshAllData();
    if (typeof AndroidBridge !== 'undefined') {
      AndroidBridge.showToast('API Key 已儲存，重新載入數據…');
    }
  });
}

function initRetry() {
  const btn = document.getElementById('btn-retry');
  if (btn) btn.addEventListener('click', () => {
    document.getElementById('error-panel').classList.remove('show');
    refreshAllData();
  });
}

function clearAllCaches() {
  const keysToRemove = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith('cache_')) keysToRemove.push(k);
  }
  keysToRemove.forEach(k => localStorage.removeItem(k));
}

async function refreshAllCharts() {
  // Re-render current active panel with new range
  const active = document.querySelector('.tab-btn.active');
  const tabId = active ? active.dataset.tab : 'panel-a';
  if (tabId === 'panel-a') await renderPanelA();
  if (tabId === 'panel-b') await renderPanelB();
  if (tabId === 'panel-c') await renderPanelC();
}

async function refreshAllData() {
  clearAllCaches();
  // Force re-render all rendered panels
  const tabs = document.querySelectorAll('.tab-btn');
  const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab || 'panel-a';

  // Reload the active panel
  if (activeTab === 'panel-a') await renderPanelA();
  if (activeTab === 'panel-b') await renderPanelB();
  if (activeTab === 'panel-c') await renderPanelC();

  // Update timestamp
  document.getElementById('last-updated').textContent = `更新：${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
}

// Make globally accessible for native bridge
window.refreshAllData = refreshAllData;

// ──── INIT ───────────────────────────────

async function init() {
  await loadDateAdapter();
  initTabs();
  initRangePills();
  initAPIModal();
  initRetry();

  // Update timestamp
  document.getElementById('last-updated').textContent = `更新：${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
}

// Boot
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
