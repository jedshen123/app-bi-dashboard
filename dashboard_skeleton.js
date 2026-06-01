/**
 * 看板分块骨架屏（AI 吸乳计划看板 / V2 共用）
 */
(function (g) {
  const CHART_SLOTS = [
    'chart-reach-pump', 'chart-reach-app',
    'chart-plan-213', 'chart-plan-214',
    'chart-method-cnt', 'chart-method-usr', 'chart-method-avg',
    'chart-funnel', 'chart-funnel-trend',
  ];
  const TABLE_SLOTS = ['funnel-table'];

  function skeletonChartHtml() {
    return '<div class="block-skeleton block-skeleton-chart sk-shimmer" aria-hidden="true"></div>';
  }

  function skeletonTableHtml(rowCount = 6) {
    const rows = Array.from({ length: rowCount }, (_, i) =>
      `<div class="sk-line sk-shimmer" style="width:${58 + (i % 3) * 12}%"></div>`
    ).join('');
    return `<div class="block-skeleton block-skeleton-table" aria-hidden="true">${rows}</div>`;
  }

  function skeletonKpiCompareHtml() {
    return `<div class="kpi-skeleton-cmp" aria-hidden="true">
      <span class="sk-line sk-shimmer sk-w45"></span>
      <span class="sk-line sk-shimmer sk-w38"></span>
    </div>`;
  }

  function skeletonKpiValClass(isPct) {
    return `kpi-val ${isPct ? 'pct' : ''} sk-shimmer kpi-val-skeleton`;
  }

  function clearBlockSkeleton(el) {
    if (!el) return;
    el.querySelectorAll('.block-skeleton, .card-loading').forEach(n => n.remove());
  }

  function setSlotSkeleton(el, kind = 'chart') {
    if (!el) return;
    clearBlockSkeleton(el);
    el.insertAdjacentHTML('beforeend', kind === 'table' ? skeletonTableHtml() : skeletonChartHtml());
  }

  function applyDesignedSkeleton(disposeCharts) {
    if (typeof disposeCharts === 'function') disposeCharts();
    CHART_SLOTS.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = '';
      setSlotSkeleton(el, 'chart');
    });
    TABLE_SLOTS.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = '';
      setSlotSkeleton(el, 'table');
    });
  }

  g.DashSkeleton = {
    CHART_SLOTS,
    TABLE_SLOTS,
    skeletonChartHtml,
    skeletonTableHtml,
    skeletonKpiCompareHtml,
    skeletonKpiValClass,
    clearBlockSkeleton,
    setSlotSkeleton,
    applyDesignedSkeleton,
    skeletonGridCardBodyHtml: skeletonChartHtml,
  };
})(window);
