/**
 * Momcozy 数据看板 · 图表工厂
 * 依赖：Chart.js 4.x + chartjs-plugin-datalabels
 *
 * 用法：
 *   <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
 *   <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
 *   <script src="/chart-factory.js"></script>
 *
 * 提供：
 *   getTheme()         — 从 CSS 变量读取当前主题色
 *   mkLine()           — 折线图
 *   mkBar()            — 柱形图
 *   mkDonut()          — 环形图
 *   mkStackedBar()     — 堆积柱形图
 *   mkCombo()          — 折线+柱形组合图
 *   renderBarList()    — 水平条形百分比列表
 *   renderBarListNum() — 水平条形数值列表
 *   mkLegend()         — 自定义图例
 *   fmtNum / fmtPct / fmtHours — 数字格式化
 *   dtLabels()         — 日期标签数组
 *   filterByDateRange()— 前端日期裁剪（筛选器优化）
 */

(function (global) {
  'use strict';

  /* ----------------------------------------------------------
     内部状态
  ---------------------------------------------------------- */
  const _chartStore = {};

  /* ----------------------------------------------------------
     主题读取：从 CSS 变量获取当前色板
  ---------------------------------------------------------- */
  function getTheme() {
    const s = getComputedStyle(document.documentElement);
    const v = n => s.getPropertyValue(n).trim();
    return {
      c1: v('--c1'), c2: v('--c2'), c3: v('--c3'),
      c4: v('--c4'), c5: v('--c5'), c6: v('--c6'),
      text:  v('--chart-text'),
      text3: v('--chart-text3'),
      grid:  v('--chart-grid'),
      surface:  v('--surface'),
      surface2: v('--surface2'),
      border:   v('--border'),
      colors: () => [v('--c1'),v('--c2'),v('--c3'),v('--c4'),v('--c5'),v('--c6')],
    };
  }

  /* ----------------------------------------------------------
     颜色工具
  ---------------------------------------------------------- */
  function hexToRgb(hex) {
    hex = (hex || '').replace('#', '');
    if (hex.length === 3) hex = hex.split('').map(x => x + x).join('');
    return [parseInt(hex.slice(0,2),16), parseInt(hex.slice(2,4),16), parseInt(hex.slice(4,6),16)];
  }
  function rgba(hex, a) {
    const [r,g,b] = hexToRgb(hex);
    return `rgba(${r},${g},${b},${a})`;
  }

  /* ----------------------------------------------------------
     数字格式化
  ---------------------------------------------------------- */
  function fmtNum(n) {
    if (n == null || isNaN(n)) return '--';
    n = Number(n);
    if (Math.abs(n) >= 1e8) return (n/1e8).toFixed(1) + '亿';
    if (Math.abs(n) >= 1e4) return (n/1e4).toFixed(1) + '万';
    if (Math.abs(n) >= 1e3) return n.toLocaleString('zh-CN');
    return String(n);
  }

  function fmtPct(v, isRatio = true) {
    const n = Number(v);
    if (isNaN(n)) return '--';
    const pct = isRatio && Math.abs(n) <= 1 ? n * 100 : n;
    return pct.toFixed(1) + '%';
  }

  function fmtHours(h) {
    if (h == null) return '--';
    h = Number(h);
    if (h >= 1e6) return (h/1e6).toFixed(1) + 'M h';
    return Math.round(h).toLocaleString('zh-CN') + ' h';
  }

  function cmpHtml(pct, label, isPp = false) {
    if (pct == null || isNaN(parseFloat(pct))) return '';
    const n = parseFloat(pct);
    const cls = n >= 0 ? 'kpi-up' : 'kpi-down';
    const arrow = n >= 0 ? '↑' : '↓';
    const unit = isPp ? 'pp' : '%';
    return `<span class="${cls}">${arrow} ${Math.abs(n).toFixed(1)}${unit}</span> ${label}`;
  }

  /* ----------------------------------------------------------
     日期工具
  ---------------------------------------------------------- */
  function fmtDtLabel(dt) {
    if (!dt) return '';
    const s = String(dt).slice(0, 10);
    const p = s.split('-');
    return p.length === 3 ? `${+p[1]}/${+p[2]}` : s;
  }

  function dtLabels(rows, key = 'dt') {
    return rows.map(r => fmtDtLabel(r[key] || r.base_date));
  }

  /**
   * 前端日期裁剪 — 筛选器优化核心
   * 对已加载的时序数据按日期范围过滤，无需重新请求后端
   * @param {Array}  rows     — 数据行（必须含 dt / base_date 字段）
   * @param {string} start    — 'YYYY-MM-DD'
   * @param {string} end      — 'YYYY-MM-DD'
   * @param {string} dateKey  — 日期字段名，默认 'dt'
   */
  function filterByDateRange(rows, start, end, dateKey = 'dt') {
    if (!rows || !rows.length) return rows;
    return rows.filter(r => {
      const d = String(r[dateKey] || r.base_date || '').slice(0, 10);
      return d >= start && d <= end;
    });
  }

  /* ----------------------------------------------------------
     Chart 实例管理
  ---------------------------------------------------------- */
  function _ctxId(ctx) { return ctx?.id || ctx?.canvas?.id; }

  function destroyChart(id) {
    if (_chartStore[id]) { _chartStore[id].destroy(); delete _chartStore[id]; }
  }

  function setChartLoading(id, on) {
    const el = typeof id === 'string' ? document.getElementById(id) : id;
    const wrap = el?.closest?.('.chart-wrap');
    if (wrap) wrap.classList.toggle('is-loading', on);
  }

  function clearChartLoading(ctx) {
    const id = typeof ctx === 'string' ? ctx : _ctxId(ctx);
    if (id) setChartLoading(id, false);
  }

  /* ----------------------------------------------------------
     KPI HTML 生成器
  ---------------------------------------------------------- */
  function kpiCard(label, value, sub, icon, color, tip) {
    const tipHtml = tip ? `<span class="help-tip" data-tip="${tip}">?</span>` : '';
    return `<div class="kpi">
      <div class="kpi-label"><i class="ti ${icon}" style="color:var(--${color})"></i>${label}${tipHtml}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-sub">${sub || ''}</div>
    </div>`;
  }

  function kpiCardCmp(label, value, cmp1Html, cmp2Html, icon, color, tip) {
    const tipHtml = tip ? `<span class="help-tip" data-tip="${tip}">?</span>` : '';
    return `<div class="kpi">
      <div class="kpi-label"><i class="ti ${icon}" style="color:var(--${color})"></i>${label}${tipHtml}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-sub"><div>${cmp1Html||''}</div><div>${cmp2Html||''}</div></div>
    </div>`;
  }

  /* ----------------------------------------------------------
     图例生成
  ---------------------------------------------------------- */
  function mkLegend(el, labels, colors) {
    if (!el) return;
    el.innerHTML = labels.map((l, i) =>
      `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--text2);cursor:pointer">
        <span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${colors[i%colors.length]}"></span>${l}
      </span>`
    ).join('');
  }

  /* ----------------------------------------------------------
     折线图 mkLine
  ---------------------------------------------------------- */
  function mkLine(ctx, datasets, labels, opts = {}, isPct = false) {
    clearChartLoading(ctx);
    destroyChart(_ctxId(ctx));
    const p = getTheme();
    const aligns = ['end', 'start'];
    const labelStep = Math.max(1, Math.floor(labels.length / 6));
    const ds = datasets.map((d, i) => ({
      ...d,
      pointRadius: d.pointRadius ?? 2,
      pointHoverRadius: d.pointHoverRadius ?? 4,
      pointBorderColor: d.pointBorderColor ?? 'transparent',
      pointBackgroundColor: d.pointBackgroundColor ?? (d.borderColor || p.c1),
      datalabels: d.datalabels || {
        display: (ctx) => ctx.dataIndex % labelStep === 0,
        color: d.borderColor || p.text3,
        font: { size: 11, weight: '500' },
        anchor: aligns[i % 2], align: aligns[i % 2], offset: 3,
        formatter: isPct
          ? (v) => v == null ? '' : parseFloat(v).toFixed(1) + '%'
          : (v) => v == null ? '' : (typeof v === 'number' ? v.toFixed(v % 1 === 0 ? 0 : 1) : v),
      },
    }));
    const c = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets: ds },
      options: {
        responsive: true, maintainAspectRatio: false,
        layout: { padding: { top: 26 } },
        plugins: {
          legend: { display: false },
          tooltip: { mode: 'index', intersect: false },
          datalabels: {},
        },
        scales: {
          x: { ticks: { font: { size: 10 }, color: p.text3, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }, grid: { display: false } },
          y: { ticks: { font: { size: 10 }, color: p.text3 }, grid: { color: p.grid } },
        },
        ...opts,
      },
    });
    const id = _ctxId(ctx);
    if (id) _chartStore[id] = c;
    return c;
  }

  /* ----------------------------------------------------------
     柱形图 mkBar
  ---------------------------------------------------------- */
  function mkBar(ctx, labels, datasets, opts = {}) {
    clearChartLoading(ctx);
    destroyChart(_ctxId(ctx));
    const p = getTheme();
    const n = labels.length;
    const step = n > 10 ? Math.max(1, Math.floor(n / 6)) : 1;
    const ds = datasets.map(d => ({
      ...d,
      datalabels: d.datalabels || {
        display: (ctx) => ctx.dataIndex % step === 0,
        color: p.text,
        font: { size: 11, weight: '500' },
        anchor: 'end', align: 'top', offset: 2, clamp: true,
        formatter: (v) => v == null ? '' : (typeof v === 'number' ? (v % 1 === 0 ? v : v.toFixed(1)) : v),
      },
    }));
    const c = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: ds },
      options: {
        responsive: true, maintainAspectRatio: false,
        layout: { padding: { top: 28 } },
        plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false }, datalabels: {} },
        scales: {
          x: { ticks: { font: { size: 10 }, color: p.text3 }, grid: { display: false } },
          y: { ticks: { font: { size: 10 }, color: p.text3 }, grid: { color: p.grid } },
        },
        ...opts,
      },
    });
    const id = _ctxId(ctx);
    if (id) _chartStore[id] = c;
    return c;
  }

  /* ----------------------------------------------------------
     环形图 mkDonut
  ---------------------------------------------------------- */
  function mkDonut(ctx, labels, values, colors, cutout = '62%', showLegend = true) {
    clearChartLoading(ctx);
    destroyChart(_ctxId(ctx));
    const total = values.reduce((a, b) => a + (Number(b) || 0), 0);
    const pcts = values.map(v => total > 0 ? (Number(v) / total * 100).toFixed(1) : '0.0');
    const c = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: values.map(Number),
          backgroundColor: colors,
          borderWidth: 0,
          hoverOffset: 4,
          datalabels: { display: false },
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout,
        plugins: {
          legend: showLegend ? { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } } : { display: false },
          tooltip: {
            callbacks: {
              label: (item) => ` ${item.label}: ${fmtNum(item.parsed)} (${pcts[item.dataIndex]}%)`,
            },
          },
          datalabels: { display: false },
        },
      },
    });
    const id = _ctxId(ctx);
    if (id) _chartStore[id] = c;
    // 渲染外部图例
    if (!showLegend) {
      const card = (typeof ctx === 'string' ? document.getElementById(ctx) : ctx)?.closest?.('.card');
      const legendEl = card?.querySelector('.donut-legend');
      if (legendEl) {
        legendEl.innerHTML = labels.map((l, i) =>
          `<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:var(--text2)">
            <span style="width:8px;height:8px;border-radius:2px;background:${colors[i%colors.length]};display:inline-block"></span>
            ${l} <span style="color:var(--text3)">${pcts[i]}%</span>
          </span>`
        ).join('');
      }
    }
    return c;
  }

  /* ----------------------------------------------------------
     堆积柱形图 mkStackedBar
  ---------------------------------------------------------- */
  function mkStackedBar(ctx, labels, seriesLabels, seriesData, colors, opts = {}) {
    clearChartLoading(ctx);
    destroyChart(_ctxId(ctx));
    const datasets = seriesLabels.map((label, i) => ({
      label,
      data: seriesData[i],
      backgroundColor: rgba(colors[i % colors.length], 0.82),
      borderRadius: 2,
      stack: 'total',
      datalabels: { display: false },
    }));
    const c = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false }, datalabels: {} },
        scales: {
          x: { stacked: true, ticks: { font: { size: 10 }, color: getTheme().text3 }, grid: { display: false } },
          y: { stacked: true, ticks: { font: { size: 10 }, color: getTheme().text3 }, grid: { color: getTheme().grid } },
        },
        ...opts,
      },
    });
    const id = _ctxId(ctx);
    if (id) _chartStore[id] = c;
    return c;
  }

  /* ----------------------------------------------------------
     组合图 mkCombo（折线 + 柱形双轴）
  ---------------------------------------------------------- */
  function mkCombo(ctx, labels, barDatasets, lineDatasets, opts = {}) {
    clearChartLoading(ctx);
    destroyChart(_ctxId(ctx));
    const p = getTheme();
    const ds = [
      ...barDatasets.map(d => ({ ...d, type: 'bar', yAxisID: d.yAxisID || 'y', datalabels: d.datalabels || { display: false } })),
      ...lineDatasets.map(d => ({ ...d, type: 'line', yAxisID: d.yAxisID || 'y1', tension: 0.4, pointRadius: 2, datalabels: d.datalabels || { display: false } })),
    ];
    const c = new Chart(ctx, {
      data: { labels, datasets: ds },
      options: {
        responsive: true, maintainAspectRatio: false,
        layout: { padding: { top: 10 } },
        plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false }, datalabels: {} },
        scales: {
          x:  { ticks: { font: { size: 10 }, color: p.text3 }, grid: { display: false } },
          y:  { position: 'left',  ticks: { font: { size: 10 }, color: p.text3 }, grid: { color: p.grid } },
          y1: { position: 'right', ticks: { font: { size: 10 }, color: p.text3 }, grid: { display: false } },
        },
        ...opts,
      },
    });
    const id = _ctxId(ctx);
    if (id) _chartStore[id] = c;
    return c;
  }

  /* ----------------------------------------------------------
     水平条形列表（百分比）
  ---------------------------------------------------------- */
  function renderBarList(el, rows, labelKey, pctKey, colors, wide = false, isRatio = true) {
    if (!el) return;
    const pcts = rows.map(r => {
      const n = Number(r[pctKey]) || 0;
      return isRatio && n <= 1 ? n * 100 : n;
    });
    const max = Math.max(...pcts, 1);
    el.innerHTML = rows.slice(0, 6).map((r, i) => {
      const pct = pcts[i];
      const w = Math.round(pct / max * 100);
      const lbl = (r[labelKey] || '').replace(/</g, '&lt;');
      return `<div class="bar-row">
        <span class="bar-label${wide ? ' wide' : ''}">${lbl}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${colors[i%colors.length]}"></div></div>
        <span class="bar-val">${pct.toFixed(1)}%</span>
      </div>`;
    }).join('') || '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
  }

  /* ----------------------------------------------------------
     水平条形列表（数值）
  ---------------------------------------------------------- */
  function renderBarListNum(el, rows, labelKey, valKey, colors, unit = '') {
    if (!el || !rows.length) {
      if (el) el.innerHTML = '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
      return;
    }
    const vals = rows.map(r => Number(r[valKey]) || 0);
    const max = Math.max(...vals, 0.001);
    el.innerHTML = rows.map((r, i) => {
      const v = vals[i];
      const w = Math.round(v / max * 100);
      const lbl = (r[labelKey] || '').replace(/</g, '&lt;');
      const display = v % 1 === 0 ? v : v.toFixed(2);
      return `<div class="bar-row">
        <span class="bar-label">${lbl}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${colors[i%colors.length]}"></div></div>
        <span class="bar-val">${display}${unit ? ' '+unit : ''}</span>
      </div>`;
    }).join('');
  }

  /* ----------------------------------------------------------
     图例交互绑定
  ---------------------------------------------------------- */
  function wireChartLegend(canvas, chart) {
    if (!canvas || !chart) return;
    const card = canvas.closest?.('.card');
    if (!card) return;
    card.querySelectorAll('.legend > .legend-item').forEach((item, i) => {
      item.style.cursor = 'pointer'; item.style.userSelect = 'none';
      item.onclick = () => {
        const meta = chart.getDatasetMeta(i);
        if (!meta) return;
        meta.hidden = meta.hidden === null ? true : !meta.hidden;
        item.style.opacity = meta.hidden ? '0.35' : '1';
        chart.update();
      };
    });
  }

  function wireLegendEl(legendEl, chart) {
    if (!legendEl || !chart) return;
    [...legendEl.querySelectorAll('span')].filter(s => s.style.display !== undefined).forEach((item, i) => {
      item.style.cursor = 'pointer'; item.style.userSelect = 'none';
      item.onclick = () => {
        const meta = chart.getDatasetMeta(i);
        if (!meta) return;
        meta.hidden = meta.hidden === null ? true : !meta.hidden;
        item.style.opacity = meta.hidden ? '0.35' : '1';
        chart.update();
      };
    });
  }

  /* ----------------------------------------------------------
     全局 resize
  ---------------------------------------------------------- */
  window.addEventListener('resize', () => {
    Object.values(_chartStore).forEach(c => c?.resize());
  });

  /* ----------------------------------------------------------
     导出
  ---------------------------------------------------------- */
  global.DashCharts = {
    getTheme,
    hexToRgb, rgba,
    fmtNum, fmtPct, fmtHours, cmpHtml,
    fmtDtLabel, dtLabels,
    filterByDateRange,          // ← 筛选器优化
    kpiCard, kpiCardCmp,
    mkLegend,
    mkLine, mkBar, mkDonut, mkStackedBar, mkCombo,
    renderBarList, renderBarListNum,
    wireChartLegend, wireLegendEl,
    destroyChart, setChartLoading, clearChartLoading,
    chartStore: _chartStore,
  };

})(window);
