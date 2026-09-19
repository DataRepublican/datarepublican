/* The world hyperlocal map, as a module both callers share.
 *
 * It used to live inside world_hyperlocal_map.html and be reached from the
 * explorer through an iframe and postMessage. The iframe existed to keep three
 * documents from colliding, and cost a `{type:'filter'}` round trip for every
 * facet change plus a retry loop for focus, because the frame might not be
 * ready yet. Direct calls need neither.
 *
 * Both callers now load leaflet, map_data.js and this file, then:
 *
 *   var map = NBMap.init(document.getElementById('mapcanvas'), {
 *     standalone: false,           // true draws the disclaimer bar and popups
 *     onOpenHost: function (host) { ... }   // a pin was tapped
 *   });
 *   map.setHosts(['a.org', ...]);  // or null for "all"
 *   map.focus('a.org');
 *
 * Requires window.NB_MAP_DATA and window.NB_MAP_EDGES.
 */
(function (global) {
  'use strict';

  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function init(container, options) {
    options = options || {};
    var DATA = global.NB_MAP_DATA || [];
    var EDGES = global.NB_MAP_EDGES || [];
    var standalone = !!options.standalone;

    var map = L.map(container, { preferCanvas: true });

    // #lat/lon/zoom deep links, kept from the standalone page.
    var h = location.hash.match(/#(-?\d+\.?\d*)\/(-?\d+\.?\d*)\/(\d+)/);
    map.setView(h ? [+h[1], +h[2]] : [30, 10], h ? +h[3] : 3);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }).addTo(map);

    var cluster = L.markerClusterGroup({
      maxClusterRadius: 45,
      spiderfyOnMaxZoom: true,
      chunkedLoading: true
    });

    var MARKERS = new Map();

    function openDetail(host) {
      if (typeof options.onOpenHost === 'function') options.onOpenHost(host);
      else location.href = 'index.html?host=' + encodeURIComponent(host);
    }
    // The popup's "full details" link is inline HTML, so it needs a global.
    global.__nbOpenDetail = openDetail;

    function makeMarker(d) {
      var m;
      if (d.img) {
        var icon = L.divIcon({
          className: 'logopin',
          html: '<i style="background-image:url(\'' + d.img + '\');border:3px solid ' + d.color + '"></i>',
          iconSize: [46, 46], iconAnchor: [23, 23], popupAnchor: [0, -23]
        });
        m = L.marker([d.lat, d.lon], { icon: icon });
      } else {
        m = L.circleMarker([d.lat, d.lon], {
          radius: 6, color: '#222', weight: 1, fillColor: d.color, fillOpacity: 0.85
        });
      }

      // A pin tap opens the shared drawer directly when embedded — the extra
      // popup step was a frame artefact. Standalone keeps the popup, which is
      // the only detail surface that page has.
      if (!standalone) {
        m.on('click', function () { openDetail(d.host); });
      } else {
        var pop = '<h3>' + esc(d.name) + '</h3>'
          + '<div class="meta">' + esc(d.city)
          + (d.region ? ', ' + esc(d.region) : '')
          + (d.country ? ' (' + esc(d.country) + ')' : '')
          + ' &middot; ' + esc(String(d.cat).replace(/_/g, ' '))
          + (d.militancy && d.militancy !== 'none' ? ' &middot; militancy: ' + esc(d.militancy) : '')
          + '</div><div>' + (d.summary || '') + '</div>'
          // Restores master's behaviour exactly: the hostname is shown either way,
          // as a link for a normal blog and as a withheld notice for a flagged one.
          // An earlier rewrite dropped both the hostname and the outbound link,
          // which on this page - where the popup IS the detail view - left no way
          // to reach the blog at all.
          + '<div style="margin-top:4px;font-size:11px">'
          + (d.dox
              ? '<span style="color:#8a5a5a;font-style:italic" title="Live-link withheld - doxxing blog">' + esc(d.host) + ' &middot; link withheld</span>'
              : '<a href="https://' + esc(d.host) + '" target="_blank" rel="noopener">' + esc(d.host) + '</a>')
          + '</div>'
          + (d.contacts || '')
          + '<div style="margin-top:6px;font-size:12px"><a href="#" onclick="window.__nbOpenDetail(\''
          + esc(d.host) + '\');return false" style="color:#2980b9;font-weight:600">full details &#8599;</a></div>';
        m.bindPopup(pop);
      }
      return m;
    }

    for (var i = 0; i < DATA.length; i++) {
      MARKERS.set(DATA[i].host, makeMarker(DATA[i]));
    }

    // Two filters combine: the explorer's exact host set, and the legend's
    // category selection (empty = all).
    var hostFilter = null;
    var legendCats = new Set();

    function applyFilters() {
      cluster.clearLayers();
      var shown = 0;
      for (var j = 0; j < DATA.length; j++) {
        var d = DATA[j];
        if (hostFilter && !hostFilter.has(d.host)) continue;
        if (legendCats.size && !legendCats.has(d.lc)) continue;
        var mk = MARKERS.get(d.host);
        if (mk) { cluster.addLayer(mk); shown++; }
      }
      var el = container.querySelector('#shownCount') || document.getElementById('shownCount');
      if (el) el.textContent = shown.toLocaleString();
      return shown;
    }

    function setHosts(hosts) {
      hostFilter = Array.isArray(hosts) ? new Set(hosts) : null;
      return applyFilters();
    }

    setHosts(null);
    map.addLayer(cluster);

    // Clickable legend.
    var scope = options.legendScope || document;
    function paintLegend() {
      scope.querySelectorAll('.legend .lgrow').forEach(function (r) {
        var on = legendCats.has(r.dataset.cat);
        // Two different states, deliberately. `off` is "some other category is
        // selected and this one is not", which is a dimming; aria-pressed is
        // "this one is chosen", which is what a screen reader needs. With no
        // selection at all nothing is pressed and nothing is dimmed.
        r.classList.toggle('off', legendCats.size > 0 && !on);
        r.setAttribute('aria-pressed', String(on));
      });
    }
    scope.querySelectorAll('.legend .lgrow').forEach(function (row) {
      row.addEventListener('click', function () {
        var c = row.dataset.cat;
        if (legendCats.has(c)) legendCats.delete(c); else legendCats.add(c);
        paintLegend();
        applyFilters();
      });
    });

    // Co-citation edges. featureGroup, not layerGroup: only FeatureGroup has
    // bringToBack, and syncEdges calls it.
    var edgeLayer = L.featureGroup();
    for (var k = 0; k < EDGES.length; k++) {
      var e = EDGES[k];
      var wn = e.wn;
      // interactive:false — the dense European edge mass otherwise swallows
      // clicks meant for the clusters underneath it.
      edgeLayer.addLayer(L.polyline([[e.lat1, e.lon1], [e.lat2, e.lon2]], {
        color: '#B03A2E', weight: 0.6 + 3.4 * wn, opacity: 0.12 + 0.5 * wn,
        interactive: false, className: 'coedge'
      }));
    }

    /* Edge visibility is state here, not a DOM read.
     *
     * It used to be `edgeToggle.checked` read live inside syncEdges, which tied
     * the layer to one specific checkbox existing in the page. The explorer no
     * longer has that checkbox — its map chrome moved into the filter popover,
     * and that popover rewrites its own innerHTML on every facet change, so any
     * element inside it is destroyed and recreated with no listener attached.
     *
     * So the module owns the boolean and exposes setEdges(). The standalone
     * world_hyperlocal_map.html still ships an #edgeToggle and still drives it
     * the same way; it just writes through this variable now. Default is on,
     * matching the standalone page's `checked` attribute. */
    var edgeToggle = scope.querySelector('#edgeToggle');
    var edgesOn = edgeToggle ? edgeToggle.checked : true;
    function syncEdges() {
      if (edgesOn) { edgeLayer.addTo(map); edgeLayer.bringToBack(); }
      else map.removeLayer(edgeLayer);
    }
    if (edgeToggle) edgeToggle.addEventListener('change', function () {
      edgesOn = edgeToggle.checked;
      syncEdges();
    });
    syncEdges();

    function focus(host) {
      var mk = MARKERS.get(host);
      if (!mk) return false;
      var go = function () { map.setView(mk.getLatLng(), Math.max(map.getZoom(), 12)); };
      if (cluster.zoomToShowLayer) cluster.zoomToShowLayer(mk, go); else go();
      return true;
    }

    return {
      map: map,
      markers: MARKERS,
      setHosts: setHosts,
      setEdges: function (on) { edgesOn = !!on; syncEdges(); },
      focus: focus,
      invalidateSize: function () { map.invalidateSize(); },
      destroy: function () { map.remove(); }
    };
  }

  global.NBMap = { init: init };
})(window);
