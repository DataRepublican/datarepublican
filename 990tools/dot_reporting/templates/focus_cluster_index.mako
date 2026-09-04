<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${focus_label} — ${report_date}</title>
  <style>
    ${css}
  </style>
</head>
<body>
  <%include file="partials/breadcrumbs.mako"/>
  <header>
    <h1>${focus_label}</h1>
    <p class="meta">Generated ${generated_at} · DB: ${db_path} · ${cluster_count} clusters</p>
    <p class="meta">
      Focus: <strong>${focus}</strong> · Slice: ${slice_by}${(' — ' + slice_label) if slice_label else ''}
      · Admission: focus rows &gt; 0 · suite cap ${max_clusters if max_clusters is not UNDEFINED else 100} after rank
% if min_multi_type or min_focus:
      · Optional floors: multi≥${min_multi_type} focus≥${min_focus}
% endif
    </p>
  </header>

  <%include file="partials/domain_methodology.mako"/>

  <div style="margin-bottom: 0.75rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
    <div>
      <strong>Filter:</strong>
      <button onclick="filterRows('all')" style="margin-left: 0.5rem;">All</button>
      <button onclick="filterRows('sus')">Sus (any)</button>
      <button onclick="filterRows('not')">Not</button>
      <button onclick="filterRows('unreviewed')">Unreviewed</button>
    </div>
    <span id="sus-count" style="font-size: 0.9rem; color: #666;"></span>
  </div>

<%
  _rank_label = rank_label if (rank_label is not UNDEFINED and rank_label) else 'focus intensity'
  _table_json = cluster_table_json if (cluster_table_json is not UNDEFINED and cluster_table_json) else '{"rows":[],"columns":[]}'
%>
  <p class="meta">Rank metric: <strong>${_rank_label}</strong>. Table supports multi-column sort, search, pagination (TanStack Table).</p>
% if map_points is not UNDEFINED and map_points:
  <%include file="partials/leaflet_map_embed.mako" args="map_points=map_points, map_root_id='leaflet-map', map_height=400"/>
% endif
  <div id="ts-table-root"></div>
  <noscript>
  <table id="clusters-table">
    <thead>
      <tr>
        <th>Score</th>
        <th>Cluster</th>
        <th>Types</th>
        <th>Focus #</th>
        <th>${_rank_label}</th>
        <th>Rows</th>
        <th>Max Grift</th>
        <th>Misrep</th>
        <th>Reasons</th>
        <th>Review</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
% for c in clusters:
      <tr class="${'dot-heavy' if (c.get('focus_count') or 0) >= min_focus else ''}"
          data-slug="${c.get('slug', '')}">
        <td>${int(c.get('suspicion_score') or 0)}</td>
        <td><a href="${c['maps_url']}" target="_blank" rel="noopener">${c['canonical_address']}</a></td>
        <td>${c['multi_type_count']}</td>
        <td>${c.get('focus_count') or 0}</td>
        <td>${c.get('rank_metric_fmt') or c.get('focus_amount_fmt') or '—'}</td>
        <td>${c['total_rows']}</td>
        <td>${'%.1f' % c['max_grift_ratio'] if c.get('max_grift_ratio') is not None else '—'}</td>
        <td>${c.get('misrep_count') or 0}</td>
        <td>${', '.join(c.get('reason_codes') or [])}</td>
        <td>
          <button onclick="setReview(this, '${c.get('slug', '')}', 'not')" style="font-size:0.75rem; padding:1px 6px;">Not</button>
          <button onclick="setReview(this, '${c.get('slug', '')}', 'sus')" style="font-size:0.75rem; padding:1px 6px; background:#b91c1c; color:white; border:none;">Sus</button>
        </td>
        <td><a href="${c['detail_file']}">Detail →</a></td>
      </tr>
% endfor
    </tbody>
  </table>
  </noscript>
  <script>
    window.__CLUSTER_TABLE__ = ${_table_json};
  </script>
  <%include file="partials/tanstack_table_assets.mako"/>
  <footer>
    <p>Exports: <code>data/clusters.json</code> · <code>export_metadata.json</code></p>
  </footer>

<%text>
<script>
const STORAGE_KEY = 'focus_cluster_review_v1';
function getState() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch(e) { return {}; }
}
function setReview(btn, slug, status) {
  const st = getState();
  st[slug] = { status: status, ts: new Date().toISOString(), notes: (st[slug]||{}).notes || '' };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(st));
  const tr = btn.closest('tr');
  if (tr) tr.dataset.review = status;
  updateCount();
}
function filterRows(mode) {
  const st = getState();
  document.querySelectorAll('#clusters-table tbody tr').forEach(tr => {
    const slug = tr.dataset.slug;
    const status = (st[slug] && st[slug].status) || '';
    let show = true;
    if (mode === 'sus') show = status.startsWith('sus');
    else if (mode === 'not') show = status === 'not';
    else if (mode === 'unreviewed') show = !status;
    tr.style.display = show ? '' : 'none';
  });
}
function updateCount() {
  const st = getState();
  let n = 0;
  Object.values(st).forEach(v => { if (v && String(v.status||'').startsWith('sus')) n++; });
  const el = document.getElementById('sus-count');
  if (el) el.textContent = n + ' sus marked';
}
document.querySelectorAll('#clusters-table tbody tr').forEach(tr => {
  const st = getState();
  const slug = tr.dataset.slug;
  if (st[slug] && st[slug].status) tr.dataset.review = st[slug].status;
});
updateCount();
</script>
</%text>
</body>
</html>
