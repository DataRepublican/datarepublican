<%doc>
Leaflet + OSM basemap.
Expects: window.__LEAFLET_MAP__ = { rootId, points: [...], height? }
</%doc>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<style>
  .leaflet-map-wrap {
    margin: 0.75rem 0 1.25rem;
    border: 1px solid #ddd;
    border-radius: 8px;
    overflow: hidden;
    background: #f3f4f6;
  }
  .leaflet-map-wrap .leaflet-container {
    width: 100%;
    height: var(--map-h, 360px);
    font: inherit;
  }
  .leaflet-map-meta {
    font-size: 0.8rem;
    color: #666;
    padding: 0.4rem 0.65rem;
    background: #fafafa;
    border-top: 1px solid #eee;
  }
  .leaflet-map-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.65rem 1.1rem;
    align-items: center;
    font-size: 0.78rem;
    color: #374151;
    padding: 0.4rem 0.65rem 0.5rem;
    background: #fff;
    border-top: 1px solid #eee;
  }
  .leaflet-map-legend .leg-title {
    font-weight: 600;
    color: #111;
    margin-right: 0.15rem;
  }
  .leaflet-map-legend .swatch {
    display: inline-block;
    width: 0.85rem;
    height: 0.85rem;
    border-radius: 999px;
    border: 1px solid rgba(0,0,0,0.15);
    vertical-align: -2px;
    margin-right: 0.28rem;
  }
  .leaflet-map-legend .swatch.rect {
    border-radius: 2px;
    opacity: 0.85;
  }
  .leaflet-map-legend .swatch.po {
    border: 2px solid #7c3aed;
    background: #a78bfa;
  }
  .leaflet-popup-content { font-size: 0.85rem; line-height: 1.35; }
  .leaflet-popup-content a { color: #0b57d0; }
</style>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
(function () {
  function metricColor(t) {
    // t in [0,1]
    if (t > 0.66) return "#b91c1c"; // high
    if (t > 0.33) return "#d97706"; // mid
    return "#2563eb"; // low
  }

  function bootOne(cfg) {
    if (!cfg || !cfg.points || !cfg.points.length) return;
    const rootId = cfg.rootId || "leaflet-map";
    const el = document.getElementById(rootId);
    if (!el || el.dataset.leafletMounted) return;
    el.dataset.leafletMounted = "1";
    const h = cfg.height || 360;
    el.style.setProperty("--map-h", h + "px");

    const mapDiv = document.createElement("div");
    mapDiv.className = "leaflet-container";
    el.appendChild(mapDiv);

    // Legend: rank metric intensity + geometry kinds
    const kinds = {};
    cfg.points.forEach((p) => {
      const k = p.kind || (p.bounds ? "loose" : "ll");
      kinds[k] = (kinds[k] || 0) + 1;
    });
    const legend = document.createElement("div");
    legend.className = "leaflet-map-legend";
    let legHtml =
      '<span class="leg-title">Legend</span>' +
      '<span><i class="swatch" style="background:#2563eb"></i>Lower rank metric</span>' +
      '<span><i class="swatch" style="background:#d97706"></i>Mid</span>' +
      '<span><i class="swatch" style="background:#b91c1c"></i>Higher rank metric</span>';
    if (kinds.ll || kinds.point || kinds.zip)
      legHtml +=
        '<span><i class="swatch" style="background:#2563eb"></i>LL: / zip point</span>';
    if (kinds.po_zip)
      legHtml +=
        '<span><i class="swatch po"></i>PO Box (zip centroid)</span>';
    if (kinds.loose)
      legHtml +=
        '<span><i class="swatch rect" style="background:#2563eb;opacity:0.35;border:1.5px solid #2563eb"></i>Loose 0.5° cell</span>';
    legend.innerHTML = legHtml;
    el.appendChild(legend);

    const meta = document.createElement("div");
    meta.className = "leaflet-map-meta";
    const nRect = cfg.points.filter((p) => p.bounds).length;
    meta.textContent =
      cfg.points.length +
      " feature" +
      (cfg.points.length === 1 ? "" : "s") +
      (nRect ? " · " + nRect + " loose cell" + (nRect === 1 ? "" : "s") : "") +
      " · © OpenStreetMap · Leaflet";
    el.appendChild(meta);

    const map = L.map(mapDiv, { scrollWheelZoom: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    const fitPads = [];
    const maxMetric = Math.max(
      1,
      ...cfg.points.map((p) => Number(p.metric) || 0)
    );

    cfg.points.forEach((p) => {
      const lat = Number(p.lat);
      const lon = Number(p.lon);
      const t = Math.min(1, (Number(p.metric) || 0) / maxMetric);
      const color = metricColor(t);
      const html =
        p.popup_html ||
        p.label ||
        (Number.isFinite(lat) ? lat.toFixed(4) + ", " + lon.toFixed(4) : "");
      const kind = p.kind || (p.bounds ? "loose" : "ll");

      let layer = null;
      // Loose colocator: 0.5° cell as rectangle (min/max bounds)
      if (p.bounds && Array.isArray(p.bounds) && p.bounds.length === 2) {
        const b = p.bounds;
        const sw = b[0];
        const ne = b[1];
        if (
          Array.isArray(sw) &&
          Array.isArray(ne) &&
          Number.isFinite(sw[0]) &&
          Number.isFinite(sw[1]) &&
          Number.isFinite(ne[0]) &&
          Number.isFinite(ne[1])
        ) {
          layer = L.rectangle([sw, ne], {
            color: color,
            weight: 1.5,
            fillColor: color,
            fillOpacity: 0.22,
          });
          fitPads.push(sw, ne);
          if (Number.isFinite(lat) && Number.isFinite(lon)) {
            const cm = L.circleMarker([lat, lon], {
              radius: 4,
              color: "#fff",
              weight: 1,
              fillColor: color,
              fillOpacity: 0.95,
            });
            cm.bindPopup(html);
            if (p.href) {
              cm.on("dblclick", () => {
                window.location.href = p.href;
              });
            }
            cm.addTo(map);
          }
        }
      }
      if (!layer && Number.isFinite(lat) && Number.isFinite(lon)) {
        const r = 6 + t * 10;
        const isPo = kind === "po_zip";
        layer = L.circleMarker([lat, lon], {
          radius: isPo ? 7 : r,
          color: isPo ? "#7c3aed" : "#fff",
          weight: isPo ? 2 : 1,
          fillColor: isPo ? "#a78bfa" : color,
          fillOpacity: 0.85,
        });
        fitPads.push([lat, lon]);
      }
      if (!layer) return;
      layer.bindPopup(html);
      if (p.href) {
        layer.on("dblclick", () => {
          window.location.href = p.href;
        });
      }
      layer.addTo(map);
    });

    if (fitPads.length === 1) {
      map.setView(fitPads[0], cfg.singleZoom || 14);
    } else if (fitPads.length > 1) {
      map.fitBounds(fitPads, { padding: [28, 28], maxZoom: cfg.maxZoom || 12 });
    }
  }

  function boot() {
    if (window.__LEAFLET_MAP__) {
      bootOne(window.__LEAFLET_MAP__);
    }
    if (Array.isArray(window.__LEAFLET_MAPS__)) {
      window.__LEAFLET_MAPS__.forEach(bootOne);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  window.bootLeafletMap = bootOne;
})();
</script>
