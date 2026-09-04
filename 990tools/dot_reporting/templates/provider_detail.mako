<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NPI ${dossier['npi']} — ${dossier['display_name'][:80]}</title>
  <style>
    ${css}
    .btn {
      display: inline-block; margin: 0.2rem 0.4rem 0.2rem 0;
      padding: 0.4rem 0.75rem; border-radius: 6px;
      background: #0b57d0; color: #fff !important; text-decoration: none;
      font-size: 0.9rem;
    }
    .btn.secondary { background: #5f6368; }
    .btn.ghost { background: #fff; color: #0b57d0 !important; border: 1px solid #0b57d0; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    code { font-size: 0.9em; }
    .search-bar { margin: 0.75rem 0 1rem; }
  </style>
</head>
<body>
<%
  d = dossier
  npi = d.get('npi') or ''
  name = d.get('display_name') or npi
  cred = d.get('credential')
  org = d.get('organization_name')
  person = d.get('person_name')
  primary_maps = ''
  for a in (d.get('addresses') or []):
    if a.get('maps_url') and a.get('address_type') == 'nppes_practice':
      primary_maps = a['maps_url']
      break
  if not primary_maps:
    for a in (d.get('addresses') or []):
      if a.get('maps_url'):
        primary_maps = a['maps_url']
        break
%>
<header>
  <p class="meta"><a href="../master_index.html">Reports</a> · <a href="index.html">Providers</a> · Provider detail</p>
  <h1>${name}</h1>
  <p class="meta">NPI <code>${npi}</code>${' · ' + cred if cred else ''}
    · ${d.get('entity_type_label') or '—'}
    · Generated ${generated_at}</p>
  <div class="search-bar">
% if primary_maps:
    <a class="btn" href="${primary_maps}" target="_blank" rel="noopener">Google Maps</a>
% endif
    <a class="btn secondary" href="${d.get('google_search_url')}" target="_blank" rel="noopener">Google Search</a>
    <a class="btn secondary" href="${d.get('grok_search_url')}" target="_blank" rel="noopener">Grok Search</a>
    <a class="btn ghost" href="${d.get('nppes_registry_url')}" target="_blank" rel="noopener">NPPES registry</a>
  </div>
</header>

<section class="cards">
  <div class="card"><strong>${d.get('total_paid_fmt') or '—'}</strong><span>Medicare paid (billing rollup)</span></div>
  <div class="card"><strong>${'{:,}'.format(int(d.get('total_claims') or 0))}</strong><span>Claims</span></div>
  <div class="card"><strong>${'{:,}'.format(int(d.get('total_beneficiaries') or 0))}</strong><span>Beneficiary-months</span></div>
  <div class="card"><strong>${'{:,}'.format(int(d.get('hcpcs_type_count') or 0))}</strong><span>HCPCS types</span></div>
  <div class="card"><strong>${d.get('first_month') or '—'} → ${d.get('last_month') or '—'}</strong><span>Spend window</span></div>
  <div class="card"><strong>${d.get('top_hcpcs_label') or d.get('top_hcpcs_code') or '—'}</strong><span>Top code (${d.get('top_hcpcs_paid_fmt') or '—'})</span></div>
</section>

<section class="section">
  <h2>Identity</h2>
  <table>
    <tr><th>NPI</th><td><code>${npi}</code></td></tr>
    <tr><th>Display name</th><td>${name}</td></tr>
% if org and person and org != person:
    <tr><th>Organization</th><td>${org}</td></tr>
    <tr><th>Person</th><td>${person}</td></tr>
% elif person and not org:
    <tr><th>Person</th><td>${person}</td></tr>
% endif
% if d.get('ein'):
    <tr><th>EIN (NPPES)</th><td>${d['ein']}</td></tr>
% endif
    <tr><th>Entity type</th><td>${d.get('entity_type_label') or '—'} (${d.get('entity_type_code') or '—'})</td></tr>
    <tr><th>Credential</th><td>${d.get('credential') or '—'}</td></tr>
    <tr><th>Sole proprietor</th><td>${d.get('is_sole_proprietor') or '—'}</td></tr>
    <tr><th>NPPES enumerated</th><td>${d.get('enumeration_date') or '—'}</td></tr>
    <tr><th>NPPES last update</th><td>${d.get('last_update_date') or '—'}</td></tr>
  </table>
</section>

<section class="section">
  <h2>Addresses</h2>
  <div id="ts-addresses" class="ts-table-root"></div>
</section>

<section class="section">
  <h2>Billing / servicing role</h2>
  <div id="ts-roles" class="ts-table-root"></div>
  <p class="meta">Rollup $ above is billing-NPI centric. Servicing-only clinicians may show $0 rollup
    but appear under other billers below.</p>
</section>

% if d.get('as_servicing'):
<section class="section">
  <h2>As servicing provider (billed under other NPIs)</h2>
  <div id="ts-servicing" class="ts-table-root"></div>
</section>
% endif

<section class="section">
  <h2>HCPCS / procedure codes (${len(d.get('hcpcs') or [])})</h2>
  <div id="ts-hcpcs" class="ts-table-root"></div>
</section>

<footer>
  <p class="disclaimer">Medicare amounts are from CMS open-data style spend tables loaded into this
    project (billing / servicing NPI grain). Not a complete PECOS profile. Co-location with other
    entities on shared addresses is not proof of affiliation.</p>
  <p><a href="index.html">← Provider index</a> · <a href="../master_index.html">Master index</a></p>
</footer>

<script>
  window.__TS_TABLES__ = ${detail_tables_json};
</script>
<%include file="partials/tanstack_table_assets.mako"/>
</body>
</html>
