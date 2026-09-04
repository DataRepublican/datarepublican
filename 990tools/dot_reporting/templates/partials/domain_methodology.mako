<%doc>
Self-documenting methodology block for suite index pages.
Expects: methodology = {
  title, question, signals[], rank, thresholds, caveats, cutpoint_lines[]
}
</%doc>
% if methodology is not UNDEFINED and methodology:
<section class="methodology" style="margin: 1rem 0 1.25rem; padding: 1rem 1.1rem; border: 1px solid #d1d5db; border-radius: 8px; background: #f8fafc;">
  <h2 style="margin: 0 0 0.5rem; font-size: 1.15rem;">${methodology.get('title') or 'What this view is for'}</h2>
% if methodology.get('question'):
  <p style="margin: 0.35rem 0 0.75rem; font-size: 0.95rem; color: #1f2937;">
    <strong>Question:</strong> ${methodology['question']}
  </p>
% endif
% if methodology.get('signals'):
  <p style="margin: 0.25rem 0 0.35rem; font-size: 0.9rem;"><strong>Primary signals</strong></p>
  <ul style="margin: 0 0 0.75rem 1.2rem; padding: 0; font-size: 0.9rem; color: #374151; line-height: 1.45;">
  % for s in methodology['signals']:
    <li>${s}</li>
  % endfor
  </ul>
% endif
% if methodology.get('rank'):
  <p style="margin: 0.35rem 0; font-size: 0.9rem; color: #374151;">
    <strong>How we rank:</strong> ${methodology['rank']}
  </p>
% endif
% if methodology.get('thresholds'):
  <p style="margin: 0.35rem 0; font-size: 0.9rem; color: #374151;">
    <strong>Thresholds:</strong> ${methodology['thresholds']}
  </p>
% endif
% if methodology.get('carrier_duties'):
  <p style="margin: 0.65rem 0 0.35rem; font-size: 0.9rem;">
    <strong>What a motor carrier is expected to do</strong>
    <span style="color:#6b7280; font-weight:400;">
      (FMCSR / New Entrant — bold = needs more than a computer and a printer)
    </span>
  </p>
  <ul style="margin: 0 0 0.75rem 1.2rem; padding: 0; font-size: 0.88rem; color: #374151; line-height: 1.45;">
  % for d in methodology['carrier_duties']:
    <li style="margin: 0.25rem 0;">
    % if d.get('needs_physical'):
      <strong>${d.get('text') or ''}</strong>
    % else:
      ${d.get('text') or ''}
    % endif
    </li>
  % endfor
  </ul>
% endif
% if methodology.get('cutpoint_lines'):
  <p style="margin: 0.5rem 0 0.25rem; font-size: 0.9rem;"><strong>Population percentiles</strong>
    <span style="color:#6b7280; font-weight:400;">(DuckDB <code>quantile_cont</code> on full tables — absolute, not this page’s top‑N)</span>
  </p>
  <ul style="margin: 0 0 0.5rem 1.2rem; padding: 0; font-size: 0.85rem; color: #4b5563; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;">
  % for line in methodology['cutpoint_lines']:
    <li style="margin: 0.15rem 0;">${line}</li>
  % endfor
  </ul>
% endif
% if methodology.get('caveats'):
  <p style="margin: 0.5rem 0 0; font-size: 0.85rem; color: #6b7280;">
    <strong>Caveats:</strong> ${methodology['caveats']}
  </p>
% endif
</section>
% endif
