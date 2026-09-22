/* Site chrome behavior. Loaded with `defer` from _includes/head-custom.html.
 *
 * Deliberately dependency-free — this runs on every page, including tool pages
 * that already carry their own copy of jQuery, and it has no reason to wait on
 * any of them.
 */
(function () {
  'use strict';

  /* ---- Trailer overlay -------------------------------------------------
   * Opened by any [data-trailer-open] button in the site banner. The <video>
   * is preload="none", so the 17 MB file is not fetched until this runs.
   */
  function initTrailer() {
    var modal = document.getElementById('trailer-modal');
    var video = document.getElementById('trailer-video');
    if (!modal || !video) return;

    var lastFocused = null;

    function open() {
      lastFocused = document.activeElement;
      modal.hidden = false;
      modal.classList.add('flex');
      // Stop the page behind the overlay from scrolling under it on touch.
      document.body.style.overflow = 'hidden';
      var close = modal.querySelector('[data-trailer-close]');
      if (close) close.focus();
      try {
        video.currentTime = 0;
        var played = video.play();
        if (played && typeof played.catch === 'function') played.catch(function () {});
      } catch (e) { /* autoplay refused; the controls still work */ }
    }

    function close() {
      video.pause();
      modal.hidden = true;
      modal.classList.remove('flex');
      document.body.style.overflow = '';
      if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    Array.prototype.forEach.call(
      document.querySelectorAll('[data-trailer-open]'),
      function (el) { el.addEventListener('click', open); }
    );

    var closer = modal.querySelector('[data-trailer-close]');
    if (closer) closer.addEventListener('click', close);

    // Click the backdrop, but not the video itself.
    modal.addEventListener('click', function (e) {
      if (e.target === modal) close();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) close();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTrailer);
  } else {
    initTrailer();
  }
})();
