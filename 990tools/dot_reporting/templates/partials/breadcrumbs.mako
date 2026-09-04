<%doc>
breadcrumbs: list of {"label": str, "href": str|None}
last crumb is current page (no href).
</%doc>
% if breadcrumbs is not UNDEFINED and breadcrumbs:
<nav class="breadcrumbs" aria-label="Breadcrumb">
% for i, crumb in enumerate(breadcrumbs):
  % if i > 0:
  <span class="bc-sep">›</span>
  % endif
  % if crumb.get("href") and i < len(breadcrumbs) - 1:
  <a href="${crumb['href']}">${crumb['label']}</a>
  % else:
  <span class="bc-current" aria-current="page">${crumb['label']}</span>
  % endif
% endfor
</nav>
% endif
