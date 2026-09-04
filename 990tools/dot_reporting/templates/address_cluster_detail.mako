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
    <p class="meta">${generated_at} · suspicion score ${int(cluster.get('suspicion_score') or 0)}</p>
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

  <!-- Review Decision (client-side localStorage) -->
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
      <button onclick="saveDecision('sus-dot')" style="background:#b91c1c; color:white; border:none; padding:8px 16px; border-radius:4px; cursor:pointer;">Sus-DOT</button>
      <button onclick="saveDecision('sus-ins')" style="background:#d97706; color:white; border:none; padding:8px 16px; border-radius:4px; cursor:pointer;">Sus-Ins</button>
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
    <div class="card"><strong>${cluster['dot_carrier_count']}</strong><span>DOT rows</span></div>
    <div class="card"><strong>${cluster['total_rows']}</strong><span>total address rows</span></div>
    <div class="card"><strong>${cluster['charity_count']}</strong><span>charities</span></div>
    <div class="card"><strong>${cluster['grant_count']}</strong><span>grants</span></div>
  </section>

  <p class="types"><strong>Types present:</strong> ${', '.join(cluster['address_types'])}</p>
% if show_address_subgroups and cluster.get('distinct_address_count'):
  <p class="types"><strong>Distinct street addresses in cluster:</strong> ${int(cluster['distinct_address_count'])}</p>
% endif
% if map_points is not UNDEFINED and map_points:
  <%include file="partials/leaflet_map_embed.mako" args="map_points=map_points, map_root_id='leaflet-map-detail', map_height=320"/>
% endif

  <!-- Active vs Inactive Summary -->
  <section>
    <h2>DOT Carrier Status Summary</h2>
    <div class="cards">
      <div class="card">
        <strong>${cluster.get('dot_active_count', 0)}</strong>
        <span>Active (A)</span>
        <div style="font-size:0.85rem; color:#166534;">${"{:,}".format(cluster.get('dot_active_power_units', 0))} Power Units</div>
      </div>
      <div class="card" style="border-color:#f87171;">
        <strong>${cluster.get('dot_inactive_count', 0)}</strong>
        <span>Inactive (I)</span>
        <div style="font-size:0.85rem; color:#b91c1c;">${"{:,}".format(cluster.get('dot_inactive_power_units', 0))} Power Units</div>
      </div>
      <div class="card">
        <strong>${cluster.get('inactive_pct', 0)}%</strong>
        <span>Inactive Ratio</span>
      </div>
    </div>
  </section>

% if show_address_subgroups and address_subgroups:
  <section>
    <h2>Addresses in this cluster (${len(address_subgroups)})</h2>
    <p style="font-size:0.85rem; color:#666; margin-bottom:0.5rem;">
      Non-address slices (colocator / zip / loose grid) often span multiple suites or streets.
      Sortable / filterable table of distinct <code>canonical_address</code> values.
    </p>
    <div id="ts-address-subgroups" class="ts-table-root"></div>
  </section>
% endif

% if phone_groups or address_groups:
  <section>
    <h2>DOT by shared phone</h2>
    <p style="font-size:0.85rem; color:#666; margin-bottom:0.5rem;">
      Physical addresses only (<code>dot_carrier_phy</code>) — mailing / UPS-store rows are excluded.
      Classic shell breakout: one row per phone with active vs inactive counts and power units.
      Click a phone number to filter the carrier list below to that stack
      (e.g. one dispatcher number reused across dozens of paper carriers).
    </p>
    <div id="ts-phone-groups" class="ts-table-root"></div>
  </section>
  <section>
    <h2>DOT carriers (physical)</h2>
    <p style="font-size:0.85rem; color:#666; margin-bottom:0.5rem;">
      Carriers with this key as <strong>physical</strong> address only.
      Default sort: phone → status (A before I) → power units.
      Search for a phone or status <code>I</code>, or click a phone above to filter.
      Live MCS-150 on Search Carriers may show a newer physical than this snapshot.
    </p>
    <div id="ts-carriers" class="ts-table-root"></div>
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
const STORAGE_KEY = 'address_cluster_review_v2';
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
      statusEl.innerHTML = `Current: <strong>${entry.status}</strong> <span style="color:#888;">(${new Date(entry.updated_at || '').toLocaleString()})</span>`;
    }
  } else if (entry === true) {
    // legacy
    if (statusEl) statusEl.innerHTML = `Current: <strong>sus-dot</strong> (legacy)`;
  }
}

function saveDecision(status) {
  if (!SLUG) return;
  const textarea = document.getElementById('review-notes');
  const notes = textarea ? textarea.value.trim() : '';

  const state = getReviewState();
  state[SLUG] = {
    status: status,
    notes: notes,
    updated_at: new Date().toISOString()
  };
  saveReviewState(state);

  // brief visual feedback then go back
  const statusEl = document.getElementById('review-status');
  if (statusEl) statusEl.innerHTML = `Saved as <strong>${status}</strong>. Returning to index...`;

  setTimeout(() => {
    window.location.href = 'index.html';
  }, 650);
}

document.addEventListener('DOMContentLoaded', loadReview);
</script>
</%text>

</body>
</html>
