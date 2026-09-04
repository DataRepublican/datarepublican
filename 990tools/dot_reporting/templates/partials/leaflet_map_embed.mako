<%page args="map_points, map_root_id='leaflet-map', map_height=380"/>
<%doc>
Include with: <%include file="partials/leaflet_map_embed.mako" args="map_points=map_points"/>
</%doc>
% if map_points:
<%
  import json
  _root = map_root_id if (map_root_id is not UNDEFINED and map_root_id) else "leaflet-map"
  _h = map_height if (map_height is not UNDEFINED and map_height) else 380
  _payload = {
    "rootId": _root,
    "height": int(_h),
    "points": map_points,
  }
  _json = json.dumps(_payload, ensure_ascii=False, default=str).replace("</", "<\\/")
%>
  <section class="leaflet-map-section">
    <h2 style="font-size:1.05rem; margin-bottom:0.35rem;">Map</h2>
    <p class="meta" style="margin-top:0;">
      Free basemap (OpenStreetMap + Leaflet). Marker size/color scales with rank metric.
      Double-click a marker to open its detail page when linked.
    </p>
    <div id="${_root}" class="leaflet-map-wrap"></div>
  </section>
  <script>
    window.__LEAFLET_MAP__ = ${_json};
  </script>
  <%include file="leaflet_map.mako"/>
% endif
