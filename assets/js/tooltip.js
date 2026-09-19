/* DRTip — one instant tooltip, shared by every tool.
 *
 * Usage is an attribute, not a call:
 *
 *   <button data-tip="Recompute node positions from scratch.">…</button>
 *   <button data-tip-title="Focus mode" data-tip="Click a node to isolate…">…</button>
 *
 * WHY THIS EXISTS. `title` cannot be styled, cannot control its own wrapping,
 * and waits about a second before appearing. On a toolbar of icon-only controls
 * that delay is the entire interaction: you hover a glyph you do not recognize,
 * get nothing, and give up. A tooltip that exists to explain an ambiguous
 * control has to be instant.
 *
 * Delegated from `document`, so controls that are built at runtime — both graph
 * toolbars and all three legends rewrite their own markup — are covered without
 * anyone remembering to re-bind. There is one tip element for the whole page.
 *
 * ACCESSIBILITY. The tip is descriptive, not a name, so the trigger keeps its
 * own accessible name (`aria-label` on icon-only controls) and gets
 * `aria-describedby` only while the tip is up. Removing `title` entirely is the
 * point — leaving both would make a screen reader read the text twice and would
 * put the native tooltip back on a one-second delay underneath this one.
 */
(function (global) {
  'use strict';

  var TIP_ID = 'dr-tip';
  var GAP = 8;          // between the trigger and the tip
  var EDGE = 8;         // keep this far off the viewport edges
  var tip = null;
  var current = null;

  function el() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'dr-tip';
    tip.id = TIP_ID;
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);
    return tip;
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
  }

  /* A two-state control says which state it is in, in the tip's title row.
     Read from aria-pressed rather than a second attribute, so a toggle gets
     this by existing and nothing can drift out of sync with the button. The
     dot on the button says a mode is on without room to say which; this says
     which and what it is set to. Controls with no aria-pressed get nothing. */
  function stateOf(trigger) {
    var pressed = trigger.getAttribute('aria-pressed');
    if (pressed === 'true') return 'on';
    if (pressed === 'false') return 'off';
    return '';
  }

  function render(trigger) {
    var t = el();
    var title = trigger.getAttribute('data-tip-title');
    var state = stateOf(trigger);
    var head = '';
    if (title) {
      head = '<b class="dr-tip__title">' + esc(title) +
        (state
          ? '<span class="dr-tip__state" data-state="' + state + '">' +
              (state === 'on' ? 'ON' : 'OFF') + '</span>'
          : '') +
        '</b>';
    }
    t.innerHTML = head + esc(trigger.getAttribute('data-tip'));
  }

  function place(trigger) {
    var t = el();
    var r = trigger.getBoundingClientRect();
    var w = t.offsetWidth;
    var h = t.offsetHeight;

    // Above by default; below when there is not room, which is what happens to
    // the first row of a toolbar pinned to the top of a canvas.
    var above = r.top - GAP - h >= EDGE;
    var top = above ? r.top - GAP - h : r.bottom + GAP;

    // Center on the trigger, then clamp into the viewport. The arrow tracks the
    // trigger's real center rather than the tip's, so clamping does not leave it
    // pointing at nothing.
    var center = r.left + r.width / 2;
    var left = center - w / 2;
    var max = global.innerWidth - EDGE - w;
    if (left > max) left = max;
    if (left < EDGE) left = EDGE;

    t.style.top = Math.round(top) + 'px';
    t.style.left = Math.round(left) + 'px';
    t.style.setProperty('--dr-tip-arrow', Math.round(center - left) + 'px');
    t.classList.toggle('dr-tip--above', above);
    t.classList.toggle('dr-tip--below', !above);
  }

  function show(trigger) {
    var text = trigger.getAttribute('data-tip');
    if (!text) return;
    if (current === trigger) return;
    hide();

    var t = el();
    render(trigger);
    t.hidden = false;
    // Measure, then place: offsetWidth is 0 while hidden.
    place(trigger);
    t.classList.add('is-on');

    trigger.setAttribute('aria-describedby', TIP_ID);
    current = trigger;
  }

  function hide() {
    if (!current) return;
    current.removeAttribute('aria-describedby');
    current = null;
    if (!tip) return;
    tip.classList.remove('is-on');
    tip.hidden = true;
  }

  function trigger(e) {
    var node = e.target && e.target.closest ? e.target.closest('[data-tip]') : null;
    return node;
  }

  /* Pointer. `pointerover`/`pointerout` rather than enter/leave so one
     delegated pair covers the whole document; the relatedTarget check is what
     stops a move between a button and its own <svg> counting as a leave. */
  document.addEventListener('pointerover', function (e) {
    if (e.pointerType === 'touch') return;   // a tap should not leave a tip up
    var node = trigger(e);
    if (node) show(node); else hide();
  });

  document.addEventListener('pointerout', function (e) {
    var node = trigger(e);
    if (!node) return;
    if (e.relatedTarget && node.contains(e.relatedTarget)) return;
    hide();
  });

  // Keyboard. focusin/out, not focus/blur — those do not bubble.
  document.addEventListener('focusin', function (e) {
    var node = trigger(e);
    if (node) show(node); else hide();
  });
  document.addEventListener('focusout', hide);

  document.addEventListener('keydown', function (e) {
    // Escape dismisses the tip and nothing else — stopPropagation would eat the
    // key the tools use to close their drawers.
    if (e.key === 'Escape') hide();
  });

  /* A fixed-position tip does not travel with its trigger, so anything that
     moves the page has to take it down. `capture` catches scrolls inside the
     tools' own scrolling panels, which do not bubble. */
  global.addEventListener('scroll', hide, true);
  global.addEventListener('resize', hide);
  // A control that vanishes under the pointer — the panel collapsing, a legend
  // rebuilding — would otherwise leave its tip orphaned on screen.
  document.addEventListener('click', function (e) {
    if (!current) return;
    if (!current.isConnected) hide();
    else if (trigger(e) !== current) hide();
    /* Clicking the control the tip is already describing: its state or its
       copy has just changed under the pointer, so re-render rather than leave
       a toggle reading ON straight after it was switched off. Bubble phase, so
       the control's own handler has already run. Re-place too — the new text
       can be a different size. */
    else { render(current); place(current); }
  });

  global.DRTip = { show: show, hide: hide };
})(window);
