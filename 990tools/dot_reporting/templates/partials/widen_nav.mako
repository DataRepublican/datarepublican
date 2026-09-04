<%doc>
widen_links: list of {label, href, key, level, exists, scope?}
Address detail pages use this for address → colocator → loose → state.
"missing" = target HTML not generated (e.g. national top-N omitted this key).
</%doc>
% if widen_links is not UNDEFINED and widen_links:
<section class="widen-nav" aria-label="Widen geographic scope">
  <strong class="widen-label">Widen:</strong>
  <span class="widen-links">
% for i, w in enumerate(widen_links):
  % if i > 0:
    <span class="widen-sep">·</span>
  % endif
<%
  _missing = w.get('exists') == '0'
  _title = w.get('key') or ''
  if _missing:
    _title = (str(_title) + ' — page not generated (not in national top-N; try by-state suite)').strip(' —')
  elif w.get('scope') == 'by_state':
    _title = (str(_title) + ' · by-state pack').strip()
%>
  <a href="${w['href']}" class="widen-link${' missing' if _missing else ''}" title="${_title}">${w['label']}</a>
% endfor
  </span>
</section>
% endif
