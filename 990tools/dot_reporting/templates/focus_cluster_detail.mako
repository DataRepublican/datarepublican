<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${cluster['canonical_address'][:60]}…</title>
  <style>
    ${css}
  </style>
</head>
<body>
  <%include file="partials/breadcrumbs.mako"/>
  <header>
<%
  from html_format import linkify_zip_codes, zip_link_html
  _title = cluster.get('canonical_address') or ''
  _ck = str(cluster.get('cluster_key') or '')
  if _ck.isdigit() and len(_ck) == 5:
    _title_html = zip_link_html(_ck) + (
      f'  ·  e.g. <a href="{cluster["maps_url"]}" target="_blank" rel="noopener">'
      f'{linkify_zip_codes(cluster.get("sample_address") or "")}</a>'
      if cluster.get('sample_address') else ''
    )
  else:
    _title_html = (
      f'<a href="{cluster["maps_url"]}" target="_blank" rel="noopener">'
      f'{linkify_zip_codes(_title)}</a>'
    )
%>
    <h1>${_title_html}</h1>
    <p class="meta">${generated_at} · ${domain['label']} · score ${int(cluster.get('suspicion_score') or 0)}</p>
    <div class="chips">
% for code in cluster['reason_codes']:
      <span class="chip">${code}</span>
% endfor
% if cluster.get('percentile_chips'):
% for chip in cluster['percentile_chips']:
      <span class="chip" style="background:#ede9fe; color:#5b21b6;" title="Absolute population percentile (full DB)">${chip}</span>
% endfor
% endif
% if cluster.get('phy_is_po_box'):
      <span class="chip" style="background:#fee2e2; color:#991b1b;">phy_po_box</span>
% endif
    </div>
  </header>
  <%include file="partials/widen_nav.mako"/>

  <section id="review-section"
           data-slug="${cluster.get('slug', '')}"
           style="margin: 1rem 0; padding: 1rem; border: 1px solid #ddd; border-radius: 8px; background: #f8f9fa;">
    <h3 style="margin-top:0; margin-bottom:0.5rem;">Review Decision</h3>
    <div style="margin-bottom: 0.75rem;">
      <label style="font-size:0.9rem; color:#555;">Notes / Analysis</label><br>
      <textarea id="review-notes" rows="4" style="width:100%; font-family: inherit; padding:0.5rem; border:1px solid #ccc; border-radius:4px;"></textarea>
    </div>
    <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
      <button onclick="saveDecision('not')" style="background:#166534; color:white; border:none; padding:8px 16px; border-radius:4px; cursor:pointer;">Not</button>
      <button onclick="saveDecision('sus-${domain.get('review_tag', 'focus')}')" style="background:#b91c1c; color:white; border:none; padding:8px 16px; border-radius:4px; cursor:pointer;">Sus-${domain.get('review_tag', 'focus')}</button>
      <button onclick="saveDecision('sus-other')" style="background:#d97706; color:white; border:none; padding:8px 16px; border-radius:4px; cursor:pointer;">Sus-other</button>
    </div>
    <div id="review-status" style="margin-top:0.5rem; font-size:0.85rem; color:#555;"></div>
  </section>

  <section class="physical">
    <h2>Physical Footprint Assessment</h2>
    <p>${physical_note or 'No manual physical note on file. Review Google Maps / Street View via the address link above.'}</p>
    <div style="margin-top: 0.5rem;">
      <a href="${cluster['maps_url']}" target="Maps" style="font-size: 0.9rem; color: #0b57d0; text-decoration: none;">
        Open in Google Maps →
      </a>
    </div>
  </section>

  <section class="cards">
    <div class="card"><strong>${cluster['multi_type_count']}</strong><span>address types</span></div>
    <div class="card"><strong>${cluster['focus_count']}</strong><span>focus entities</span></div>
    <div class="card"><strong>${cluster.get('focus_amount_fmt') or '—'}</strong><span>${domain['amount_label']}</span></div>
    <div class="card"><strong>${cluster['total_rows']}</strong><span>total address rows</span></div>
    <div class="card"><strong>${cluster['charity_count']}</strong><span>charities</span></div>
    <div class="card"><strong>${cluster['grant_count']}</strong><span>grants</span></div>
    <div class="card"><strong>${cluster.get('dot_carrier_count') or 0}</strong><span>DOT rows</span></div>
  </section>

  <p class="types"><strong>Types present:</strong> ${', '.join(cluster['address_types'] or [])}</p>
% if map_points is not UNDEFINED and map_points:
  <%include file="partials/leaflet_map_embed.mako" args="map_points=map_points, map_root_id='leaflet-map-detail', map_height=320"/>
% endif

% if entities:
  <section>
    <h2>${domain['entity_title']} (top ${len(entities)})</h2>
    <div id="ts-entities" class="ts-table-root"></div>
  </section>
% endif

% if charities:
  <section>
    <h2>Charities (top ${len(charities)})</h2>
    <div id="ts-charities" class="ts-table-root"></div>
  </section>
% endif

% if officers:
  <section>
    <h2>Officers (top ${len(officers)})</h2>
    <div id="ts-officers" class="ts-table-root"></div>
  </section>
% endif

% if grants:
  <section>
    <h2>Grants (top ${len(grants)})</h2>
    <div id="ts-grants" class="ts-table-root"></div>
  </section>
% endif

  <footer>
% if breadcrumbs is not UNDEFINED and breadcrumbs and len(breadcrumbs) >= 2 and breadcrumbs[-2].get('href'):
    <a href="${breadcrumbs[-2]['href']}">← ${breadcrumbs[-2]['label']}</a>
    · <a href="${breadcrumbs[0]['href']}">All reports</a>
% else:
    <a href="index.html">← Suite index</a>
% endif
  </footer>

<%
  _detail_json = detail_tables_json if (detail_tables_json is not UNDEFINED and detail_tables_json) else '[]'
%>
<script>
  window.__TS_TABLES__ = ${_detail_json};
</script>
<%include file="partials/tanstack_table_assets.mako"/>

<%text>
<script>
const STORAGE_KEY = 'focus_cluster_review_v1';
const reviewSection = document.getElementById('review-section');
const SLUG = reviewSection ? reviewSection.dataset.slug : '';

function getReviewState() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch(e) { return {}; }
}
function saveReviewState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}
function loadReview() {
  if (!SLUG) return;
  const state = getReviewState();
  const entry = state[SLUG];
  const textarea = document.getElementById('review-notes');
  const statusEl = document.getElementById('review-status');
  if (entry && typeof entry === 'object') {
    if (textarea) textarea.value = entry.notes || '';
    if (statusEl && entry.status) {
      statusEl.textContent = 'Saved: ' + entry.status + (entry.ts ? ' @ ' + entry.ts : '');
    }
  }
}
function saveDecision(status) {
  if (!SLUG) return;
  const state = getReviewState();
  const notes = (document.getElementById('review-notes') || {}).value || '';
  state[SLUG] = { status: status, notes: notes, ts: new Date().toISOString() };
  saveReviewState(state);
  const statusEl = document.getElementById('review-status');
  if (statusEl) statusEl.textContent = 'Saved: ' + status;
}
loadReview();
</script>
</%text>
</body>
</html>
