<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Address Cluster Report — ${report_date}</title>
  <style>
    ${css}
  </style>
</head>
<body>
  <%include file="partials/breadcrumbs.mako"/>
  <header>
    <h1>Cluster Report${' — ' + slice_label if slice_label else ''}</h1>
    <p class="meta">Generated ${generated_at} · DB: ${db_path} · ${cluster_count} clusters</p>
    <p class="meta">Slice: ${slice_by if slice_by else 'address'} · Admission: phy carriers &gt; 0 · suite cap after rank (DOT records, then types)
% if min_multi_type or min_dot_carriers:
 · Optional floors: multi≥${min_multi_type} carriers≥${min_dot_carriers}
% endif
</p>
  </header>

  <%include file="partials/domain_methodology.mako"/>

  <!-- Review Shell Controls -->
  <div style="margin-bottom: 0.75rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
    <div>
      <strong>Filter:</strong>
      <button onclick="filterRows('all')" style="margin-left: 0.5rem;">All</button>
      <button onclick="filterRows('sus')">Sus (any)</button>
      <button onclick="filterRows('sus-dot')">Sus-DOT</button>
      <button onclick="filterRows('sus-ins')">Sus-Ins</button>
      <button onclick="filterRows('not')">Not</button>
      <button onclick="filterRows('unreviewed')">Unreviewed</button>
    </div>
    <button onclick="exportSusTSV()" style="background: #b91c1c; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;">
      Export Sus (.tsv)
    </button>
    <button onclick="exportReviewedState()" style="background: #374151; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;">
      Export Reviewed State (JSON)
    </button>
    <span id="sus-count" style="font-size: 0.9rem; color: #666;"></span>
  </div>

<%
  _table_json = cluster_table_json if (cluster_table_json is not UNDEFINED and cluster_table_json) else '{"rows":[],"columns":[]}'
%>
<%
  _rank_label = rank_label if (rank_label is not UNDEFINED and rank_label) else 'DOT records · types'
%>
  <p class="meta">Rank metric: <strong>${_rank_label}</strong> (physical DOT identities, then distinct address types — mailing excluded). Active PUs stay a sortable column. Table supports multi-column sort, search, pagination (TanStack Table).</p>
% if map_points is not UNDEFINED and map_points:
  <%include file="partials/leaflet_map_embed.mako" args="map_points=map_points, map_root_id='leaflet-map', map_height=400"/>
% endif
  <div id="ts-table-root"></div>
  <!-- noscript / fallback static table -->
  <noscript>
  <table id="clusters-table">
    <thead>
      <tr>
        <th>Score</th>
        <th>Address</th>
        <th>Types</th>
        <th>DOT</th>
        <th>Active PUs</th>
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
      <tr class="${'dot-heavy' if c['dot_carrier_count'] >= min_dot_carriers else ''}"
          data-slug="${c.get('slug', '')}"
          data-phy-po-box="${'true' if c.get('phy_is_po_box') else 'false'}"
          data-has-physical="${'true' if 'dot_carrier_phy' in c.get('address_types', []) else 'false'}">
        <td>${int(c['suspicion_score'] or 0)}</td>
        <td><a href="${c['maps_url']}" target="_blank" rel="noopener">${c['canonical_address']}</a></td>
        <td>${c['multi_type_count']}</td>
        <td>${c['dot_carrier_count']}</td>
        <td>${'{:,}'.format(c.get('active_power_units') or c.get('dot_active_power_units') or 0)}</td>
        <td>${c['total_rows']}</td>
        <td>${'%.1f' % c['max_grift_ratio'] if c['max_grift_ratio'] is not None else '—'}</td>
        <td>${c['misrep_count']}</td>
        <td>${', '.join(c['reason_codes'])}</td>
        <td>
          <button onclick="setReview(this, '${c.get('slug', '')}', false)" style="font-size:0.75rem; padding:1px 6px;">Not</button>
          <button onclick="setReview(this, '${c.get('slug', '')}', 'ins')" style="font-size:0.75rem; padding:1px 6px; background:#d97706; color:white; border:none;">Ins</button>
          <button onclick="setReview(this, '${c.get('slug', '')}', 'dot')" style="font-size:0.75rem; padding:1px 6px; background:#b91c1c; color:white; border:none;">DOT</button>
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
    <p>Full exports: <code>data/clusters.json</code> · Criteria: <code>export_metadata.json</code></p>
  </footer>

<%text>
<script>
// Review Shell - localStorage based
const STORAGE_KEY = 'address_cluster_review_v2';

function getReviewState() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch (e) {
    return {};
  }
}

function saveReviewState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function getStatus(slug) {
  const state = getReviewState();
  const entry = state[slug];
  if (!entry) return null;

  // Legacy boolean support
  if (typeof entry === 'boolean') {
    return entry ? 'sus-dot' : 'not';
  }

  // New object format
  if (entry && typeof entry === 'object' && entry.status) {
    return entry.status;
  }

  return null;
}

function getNotes(slug) {
  const state = getReviewState();
  const entry = state[slug];
  if (!entry || typeof entry === 'boolean') return '';
  return entry.notes || '';
}

function applyReviewState() {
  const rows = document.querySelectorAll('#clusters-table tbody tr');
  let susCount = 0;

  rows.forEach(row => {
    const slug = row.dataset.slug;
    const isPhyPoBox = row.dataset.phyPoBox === 'true';
    let status = getStatus(slug);

    // Auto-mark PO Box physical addresses as sus-dot on first view
    if (isPhyPoBox && !status) {
      const defaultNote = "Physical address is a PO Box";
      status = 'sus-dot';
      const state = getReviewState();
      state[slug] = {
        status: 'sus-dot',
        notes: defaultNote,
        updated_at: new Date().toISOString()
      };
      saveReviewState(state);
    }

    // Auto-mark clusters with only mail PO Box and no physical address
    const hasPhysical = row.dataset.hasPhysical === 'true';
    const isMailPoBox = row.dataset.phyPoBox === 'false' && !hasPhysical;  // rough proxy: no physical + not already phy po box

    if (isMailPoBox && !status) {
      const defaultNote = "Mail is PO Box, no physical";
      status = 'sus-dot';
      const state = getReviewState();
      state[slug] = {
        status: 'sus-dot',
        notes: defaultNote,
        updated_at: new Date().toISOString()
      };
      saveReviewState(state);
    }

    const isSus = status === 'sus-dot' || status === 'sus-ins';

    if (isSus) {
      row.classList.add('sus-row');
      if (status === 'sus-dot') row.style.backgroundColor = '#fee2e2';
      if (status === 'sus-ins') row.style.backgroundColor = '#fef3c7';
      susCount++;
    } else {
      row.classList.remove('sus-row');
      row.style.backgroundColor = '';
    }

    // Update button styles on index
    const buttons = row.querySelectorAll('td:nth-last-child(2) button');
    if (buttons.length === 3) {
      // buttons[0] = Not, buttons[1] = Ins, buttons[2] = DOT
      if (status === 'not') {
        // Light green frame for reviewed "Not"
        row.style.border = '2px solid #166534';
        buttons[0].style.background = '#166534';
        buttons[0].style.color = 'white';
        buttons[1].style.background = '';
        buttons[1].style.color = '';
        buttons[2].style.background = '';
        buttons[2].style.color = '';
      } else if (status === 'sus-ins') {
        row.style.border = '';
        buttons[0].style.background = '';
        buttons[0].style.color = '';
        buttons[1].style.background = '#d97706';
        buttons[1].style.color = 'white';
        buttons[2].style.background = '';
        buttons[2].style.color = '';
      } else if (status === 'sus-dot') {
        row.style.border = '';
        buttons[0].style.background = '';
        buttons[0].style.color = '';
        buttons[1].style.background = '';
        buttons[1].style.color = '';
        buttons[2].style.background = '#b91c1c';
        buttons[2].style.color = 'white';
      } else {
        // Unreviewed
        row.style.border = '';
        buttons[0].style.background = '';
        buttons[0].style.color = '';
        buttons[1].style.background = '';
        buttons[1].style.color = '';
        buttons[2].style.background = '';
        buttons[2].style.color = '';
      }
    }
  });

  const countEl = document.getElementById('sus-count');
  if (countEl) countEl.textContent = `${susCount} marked Sus`;
}

function setReview(button, slug, decision) {
  const state = getReviewState();
  const current = state[slug] || {};

  let newStatus;
  if (decision === false || decision === 'not') {
    newStatus = 'not';
  } else if (decision === 'ins') {
    newStatus = 'sus-ins';
  } else if (decision === 'dot') {
    newStatus = 'sus-dot';
  } else {
    newStatus = 'sus-dot'; // fallback
  }

  state[slug] = {
    status: newStatus,
    notes: current.notes || '',
    updated_at: new Date().toISOString()
  };
  saveReviewState(state);
  applyReviewState();
}

function filterRows(mode) {
  const rows = document.querySelectorAll('#clusters-table tbody tr');

  rows.forEach(row => {
    const slug = row.dataset.slug;
    const status = getStatus(slug);

    if (mode === 'all') {
      row.style.display = '';
    } else if (mode === 'sus') {
      row.style.display = (status === 'sus-dot' || status === 'sus-ins') ? '' : 'none';
    } else if (mode === 'sus-dot') {
      row.style.display = status === 'sus-dot' ? '' : 'none';
    } else if (mode === 'sus-ins') {
      row.style.display = status === 'sus-ins' ? '' : 'none';
    } else if (mode === 'not') {
      row.style.display = status === 'not' ? '' : 'none';
    } else if (mode === 'unreviewed') {
      row.style.display = !status ? '' : 'none';
    }
  });
}

function exportSusTSV() {
  const rows = document.querySelectorAll('#clusters-table tbody tr');
  const exportRows = [];

  rows.forEach(row => {
    const slug = row.dataset.slug;
    const status = getStatus(slug);
    if (status) {
      const cells = row.cells;
      exportRows.push({
        address: cells[1].innerText.trim(),
        status: status,
        score: cells[0].innerText.trim(),
        dot_count: cells[3].innerText.trim(),
        active_pus: cells[4] ? cells[4].innerText.trim() : '',
        total_rows: cells[5] ? cells[5].innerText.trim() : '',
        types: cells[2].innerText.trim(),
        reasons: cells[8] ? cells[8].innerText.trim() : '',
        notes: getNotes(slug),
        maps_url: cells[1].querySelector('a') ? cells[1].querySelector('a').href : ''
      });
    }
  });

  if (exportRows.length === 0) {
    alert('No reviewed clusters to export.');
    return;
  }

  const headers = ['address', 'status', 'score', 'dot_count', 'active_pus', 'total_rows', 'types', 'reasons', 'notes', 'maps_url'];
  let tsv = headers.join('\t') + '\n';

  exportRows.forEach(r => {
    const line = headers.map(h => String(r[h] || '').replace(/\t/g, ' ')).join('\t');
    tsv += line + '\n';
  });

  const blob = new Blob([tsv], { type: 'text/tab-separated-values' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'reviewed_clusters.tsv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportReviewedState() {
  const state = getReviewState();
  const reviewed = {};

  // Only export clusters that have actually been reviewed
  for (const [slug, entry] of Object.entries(state)) {
    if (entry && typeof entry === 'object' && entry.status) {
      reviewed[slug] = {
        status: entry.status,
        notes: entry.notes || '',
        updated_at: entry.updated_at
      };
    } else if (typeof entry === 'boolean') {
      // legacy support
      reviewed[slug] = {
        status: entry ? 'sus-dot' : 'not',
        notes: '',
        updated_at: null
      };
    }
  }

  if (Object.keys(reviewed).length === 0) {
    alert('No reviewed clusters to export.');
    return;
  }

  const blob = new Blob([JSON.stringify(reviewed, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'reviewed_state.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  // Add some basic style for sus rows
  const style = document.createElement('style');
  style.textContent = `
    tr.sus-row { background-color: #fee2e2 !important; }
    tr.sus-row:hover { background-color: #fecaca !important; }
  `;
  document.head.appendChild(style);

  applyReviewState();

  // Default to Unreviewed view so it acts like a todo list
  filterRows('unreviewed');
});
</script>
</%text>
</body>
</html>
