/* A bottom sheet for tool detail panels.
 *
 * The problem it solves: every graph and map tool on this site puts its detail
 * panel in a column beside the canvas. On a phone that column stacks *below*
 * the canvas, so tapping a node — the primary interaction of the whole tool —
 * produces no visible feedback at all. The response is 500-700px down the page.
 *
 * On a narrow viewport the panel becomes a sheet that rises over the canvas
 * with the tapped thing still visible behind it. At >= 768px it is an ordinary
 * side panel again and none of this code does anything.
 *
 * Usage:
 *   var sheet = DRSheet.attach(document.getElementById('panel'), {
 *     label: 'Details',
 *     onClose: function () { ... }
 *   });
 *   sheet.open();            // rise to the default detent
 *   sheet.open('full');      // rise to full height
 *   sheet.close();
 *   sheet.isOpen();
 *
 * Detents are fractions of the viewport height. 'peek' shows the header and a
 * couple of lines, which is usually enough to read what you tapped without
 * losing sight of it.
 */
(function (global) {
  'use strict';

  var MOBILE = '(max-width: 767px)';
  var DETENTS = { peek: 0.32, half: 0.55, full: 0.92 };

  function isMobile() {
    return global.matchMedia && global.matchMedia(MOBILE).matches;
  }

  var FOCUSABLE = [
    'a[href]', 'button:not([disabled])', 'input:not([disabled])',
    'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  function attach(el, options) {
    if (!el) return null;
    options = options || {};

    var state = { open: false, detent: options.detent || 'half', dragging: false };
    var startY = 0;
    var startTranslate = 0;
    var lastFocused = null;

    // The grip and close button go in a WRAPPER around the host element, not
    // inside it. Every one of these tools owns its panel's innerHTML and
    // rewrites it wholesale on each tap — `panel.innerHTML = ...` — so
    // anything inserted as a child is silently destroyed on the first
    // interaction. That is exactly what happened the first time around.
    //
    // The wrapper is `display: contents` at desktop width, so the host element
    // stays a direct grid child of the tool's layout and its existing
    // `grid-column` / `grid-row` rules keep working. Only on a phone does the
    // wrapper become a real box.
    var wrap = document.createElement('div');
    wrap.className = 'dr-sheet';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'false');
    if (options.label) wrap.setAttribute('aria-label', options.label);
    el.parentNode.insertBefore(wrap, el);
    wrap.appendChild(el);
    el.classList.add('dr-sheet__body');

    // Grabber. Visible only on mobile, via CSS.
    var grip = document.createElement('div');
    grip.className = 'dr-sheet__grip';
    grip.setAttribute('aria-hidden', 'true');
    wrap.insertBefore(grip, el);

    // Close button, for people who do not know the sheet can be dragged.
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'dr-sheet__close';
    closeBtn.setAttribute('aria-label', 'Close ' + (options.label || 'panel'));
    closeBtn.innerHTML = '&times;';
    closeBtn.addEventListener('click', function () { close(); });
    wrap.insertBefore(closeBtn, grip);

    // Everything below acts on the wrapper.
    el = wrap;

    var scrim = document.createElement('div');
    scrim.className = 'dr-sheet__scrim';
    scrim.hidden = true;
    scrim.addEventListener('click', function () { close(); });
    document.body.appendChild(scrim);

    function heightFor(detent) {
      return Math.round(global.innerHeight * (DETENTS[detent] || DETENTS.half));
    }

    function applyHeight() {
      if (!isMobile()) {
        el.style.height = '';
        el.style.transform = '';
        return;
      }
      el.style.height = heightFor(state.detent) + 'px';
      el.style.transform = state.open ? 'translateY(0)' : '';
    }

    function open(detent) {
      if (detent) state.detent = detent;
      state.open = true;
      el.classList.add('is-open');
      if (isMobile()) {
        lastFocused = document.activeElement;
        scrim.hidden = false;
        el.setAttribute('aria-modal', 'true');
        applyHeight();
        // Focus the sheet itself rather than its first control, so a screen
        // reader announces the panel before its contents.
        el.setAttribute('tabindex', '-1');
        el.focus({ preventScroll: true });
      }
    }

    function close() {
      if (!state.open) return;
      state.open = false;
      el.classList.remove('is-open');
      scrim.hidden = true;
      el.setAttribute('aria-modal', 'false');
      el.style.transform = '';
      if (lastFocused && lastFocused.focus) lastFocused.focus({ preventScroll: true });
      if (typeof options.onClose === 'function') options.onClose();
    }

    /* ---- Drag ---------------------------------------------------------- */

    function onPointerDown(e) {
      if (!isMobile() || !state.open) return;
      state.dragging = true;
      startY = e.clientY;
      startTranslate = 0;
      el.classList.add('is-dragging');
      grip.setPointerCapture && grip.setPointerCapture(e.pointerId);
    }

    function onPointerMove(e) {
      if (!state.dragging) return;
      var dy = e.clientY - startY;
      // Resist upward drag past the full detent.
      if (dy < 0) dy = dy / 3;
      el.style.transform = 'translateY(' + (startTranslate + dy) + 'px)';
    }

    function onPointerUp(e) {
      if (!state.dragging) return;
      state.dragging = false;
      el.classList.remove('is-dragging');
      var dy = e.clientY - startY;
      el.style.transform = '';

      var order = ['peek', 'half', 'full'];
      var i = order.indexOf(state.detent);

      if (dy > 120) {
        // Dragged down hard: step down a detent, or close from the lowest.
        if (i <= 0) return close();
        state.detent = order[i - 1];
      } else if (dy < -80) {
        state.detent = order[Math.min(i + 1, order.length - 1)];
      }
      applyHeight();
    }

    grip.addEventListener('pointerdown', onPointerDown);
    grip.addEventListener('pointermove', onPointerMove);
    grip.addEventListener('pointerup', onPointerUp);
    grip.addEventListener('pointercancel', onPointerUp);

    /* ---- Keyboard and viewport ------------------------------------------ */

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.open && isMobile()) {
        close();
        return;
      }
      // Keep tab focus inside the sheet while it is modal.
      if (e.key !== 'Tab' || !state.open || !isMobile()) return;
      var items = el.querySelectorAll(FOCUSABLE);
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    var resizeTimer;
    global.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        // Crossing the breakpoint with the sheet up would otherwise leave a
        // desktop side panel wearing a mobile height and a live scrim.
        if (!isMobile()) {
          scrim.hidden = true;
          el.style.height = '';
          el.style.transform = '';
        } else if (state.open) {
          applyHeight();
        }
      }, 120);
    });

    return {
      el: el,
      open: open,
      close: close,
      isOpen: function () { return state.open; },
      setDetent: function (d) { state.detent = d; applyHeight(); },
      isMobile: isMobile
    };
  }

  global.DRSheet = { attach: attach, isMobile: isMobile, DETENTS: DETENTS };
})(window);
