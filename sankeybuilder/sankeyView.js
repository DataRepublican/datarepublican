import { colorString, getColorForId, getTextColorForId } from "./color.js";
import { BADGE, USER_BODY, badgeCenter, linkPath, trapezoidPath } from "./shapes.js";

let zoomBehavior = null;

function money(n) {
  if (!n) return "";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

export function bindSankey(svgEl, vm) {
  const d3 = window.d3;
  if (!d3 || !svgEl) return () => {};

  const svg = d3.select(svgEl);
  zoomBehavior = d3.zoom().scaleExtent([0.2, 8]).on("zoom", (ev) => {
    svg.select("g.sb-main").attr("transform", ev.transform);
  });
  svg.call(zoomBehavior);

  function fit() {
    const g = svg.select("g.sb-main").node();
    if (!g) return;
    const bounds = g.getBBox();
    if (!bounds.width || !bounds.height) return;
    const box = svgEl.getBoundingClientRect();
    const width = box.width || 800;
    const height = box.height || 500;
    const scale =
      0.85 / Math.max(bounds.width / width, bounds.height / height);
    svg
      .transition()
      .duration(400)
      .call(
        zoomBehavior.transform,
        d3.zoomIdentity
          .translate(width / 2, height / 2)
          .scale(scale)
          .translate(-bounds.x - bounds.width / 2, -bounds.y - bounds.height / 2),
      );
  }

  async function draw() {
    if (vm.view === "table") return;
    const data = vm.getSankeyData();
    svg.selectAll("*").remove();
    const main = svg.append("g").attr("class", "sb-main");
    const empty = svgEl.parentElement?.querySelector("[data-empty]");
    if (!data.nodes.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;

    const box = svgEl.getBoundingClientRect();
    const width = Math.max(box.width, 320);
    const height = Math.max(box.height, 240);

    let graph = {
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    };

    let layout;
    try {
      const mod = await import("/browse/d3-sankey-circular.js");
      layout = mod
        .sankeyWithCircles()
        .nodeId((d) => d.id)
        .nodeWidth(18)
        .nodePadding(vm.nodePadding())
        .size([width - 80, height - 80]);
      graph = layout(graph);
    } catch (err) {
      console.warn("circular sankey failed, falling back to columns", err);
      graph = columnFallback(graph, width, height);
    }

    graph.nodes.forEach((d) => {
      const h = Math.max(d.y1 - d.y0, 8);
      d.inflowHeight = h;
      d.outflowHeight = h;
    });

    const drawn = vm.circularLinks
      ? graph.links
      : graph.links.filter((l) => !l.circular);
    const grants = drawn.filter((l) => l.kind !== "partner");
    const partners = drawn.filter((l) => l.kind === "partner");
    const selectedEdge = vm.selectedEdgeId;

    main
      .append("g")
      .attr("class", "sb-hits")
      .selectAll("path.sb-hit")
      .data(drawn)
      .join("path")
      .attr("class", "sb-hit")
      .attr("d", linkPath)
      .attr("fill", "none")
      .attr("stroke", "transparent")
      .attr("stroke-width", 16)
      .style("cursor", "pointer")
      .on("click", (ev, d) => {
        ev.stopPropagation();
        vm.setSelectedEdge(d.id);
      });

    main
      .append("g")
      .attr("class", "sb-links")
      .selectAll("path.sb-grant")
      .data(grants)
      .join("path")
      .attr("class", (d) => (d.id === selectedEdge ? "sb-grant sb-link-on" : "sb-grant"))
      .attr("d", linkPath)
      .attr("fill", "none")
      .attr("stroke", (d) => colorString(getColorForId(d.source.colorKey || d.source.id)))
      .attr("stroke-opacity", (d) => (d.id === selectedEdge ? 0.95 : 0.45))
      .attr("stroke-width", (d) => Math.max(2, d.width || 2))
      .style("pointer-events", "none")
      .append("title")
      .text((d) => `${d.source.name} → ${d.target.name} ${money(d.amount)} ${d.label || ""}`);

    main
      .append("g")
      .attr("class", "sb-partners")
      .selectAll("path.sb-partner")
      .data(partners)
      .join("path")
      .attr("class", (d) =>
        d.id === selectedEdge ? "sb-partner sb-link-on" : "sb-partner",
      )
      .attr("d", linkPath)
      .attr("fill", "none")
      .attr("stroke", "currentColor")
      .attr("stroke-opacity", (d) => (d.id === selectedEdge ? 1 : 0.7))
      .attr("stroke-width", (d) => (d.id === selectedEdge ? 3 : 2))
      .attr("stroke-dasharray", "5 4")
      .style("pointer-events", "none")
      .append("title")
      .text((d) => `${d.source.name} · ${d.label || "partner"} · ${d.target.name}`);

    const nodes = main
      .append("g")
      .attr("class", "sb-nodes")
      .selectAll("g.sb-node")
      .data(graph.nodes)
      .join("g")
      .attr("class", (d) => `sb-node sb-node--${d.kind}`)
      .attr("data-id", (d) => d.id)
      .style("cursor", nodeCursor(vm.clickMode))
      .on("click", (ev, d) => {
        ev.stopPropagation();
        vm.clickNode(d.id, ev);
      });

    nodes
      .append("path")
      .attr("d", trapezoidPath)
      .attr("fill", (d) => colorString(getColorForId(d.colorKey || d.id)))
      .attr("stroke", "#111")
      .attr("stroke-width", (d) => (d.id === vm.selectedId ? 2.5 : 1));

    const people = nodes.filter((d) => d.kind === "person");
    const badge = people.append("g").attr("transform", (d) => {
      const c = badgeCenter(d);
      return `translate(${c.x},${c.y})`;
    });

    badge
      .append("circle")
      .attr("r", BADGE / 2)
      .attr("fill", (d) => colorString(getColorForId(d.colorKey || d.id)))
      .attr("stroke", "#111")
      .attr("stroke-width", 1.5);

    badge.each(function (d) {
      const g = d3.select(this);
      if (d.photo) {
        const clipId = `sb-clip-${cssId(d.id)}`;
        g.append("clipPath")
          .attr("id", clipId)
          .append("circle")
          .attr("r", BADGE / 2 - 1);
        g.append("image")
          .attr("href", d.photo)
          .attr("x", -BADGE / 2)
          .attr("y", -BADGE / 2)
          .attr("width", BADGE)
          .attr("height", BADGE)
          .attr("clip-path", `url(#${clipId})`)
          .attr("preserveAspectRatio", "xMidYMid slice")
          .on("error", function () {
            d3.select(this).remove();
            drawUser(g);
          });
      } else {
        drawUser(g);
      }
    });

    nodes
      .append("text")
      .attr("x", (d) => d.x1 + 8)
      .attr("y", (d) => (d.y0 + d.y1) / 2)
      .attr("dy", "0.35em")
      .attr("fill", (d) => colorString(getTextColorForId(d.colorKey || d.id)))
      .attr("stroke", "white")
      .attr("stroke-width", 3)
      .attr("paint-order", "stroke")
      .style("font-size", "12px")
      .style("font-weight", 600)
      .text((d) => d.name);

    svg.on("click", () => vm.setSelected(null));

    const cam = vm.camera;
    vm.camera = null;
    if (cam === "neighborhood") {
      const n = graph.nodes.find((x) => x.id === vm.selectedId);
      if (n) zoomToNeighborhood(n);
      else fit();
    } else if (cam === "fit") {
      fit();
    }
  }

  function zoomToNeighborhood(node) {
    if (!node || node.x0 == null) {
      fit();
      return;
    }
    const box = svgEl.getBoundingClientRect();
    const width = box.width || 800;
    const height = box.height || 500;
    const nw = Math.max(1, node.x1 - node.x0);
    const nh = Math.max(1, node.y1 - node.y0);
    const cx = (node.x0 + node.x1) / 2;
    const cy = (node.y0 + node.y1) / 2;
    const boxW = nw + Math.min(nh * 3, nw * 8, 220);
    const boxH = nh / 0.55;
    const k = Math.min(8, Math.max(0.2, Math.min(width / boxW, height / boxH)));
    svg
      .transition()
      .duration(400)
      .call(
        zoomBehavior.transform,
        d3.zoomIdentity.translate(width / 2 - cx * k, height / 2 - cy * k).scale(k),
      );
  }

  const unsub = vm.subscribe(() => {
    draw();
  });
  draw();

  return {
    draw,
    fit,
    zoomBy(k) {
      svg.transition().duration(200).call(zoomBehavior.scaleBy, k);
    },
    destroy() {
      unsub();
    },
  };
}

function nodeCursor(mode) {
  if (mode === "add") return "cell";
  if (mode === "inspect") return "zoom-in";
  if (mode === "zoom") return "crosshair";
  if (mode === "subtract") return "not-allowed";
  return "pointer";
}

function drawUser(g) {
  g.append("svg")
    .attr("viewBox", "0 0 24 24")
    .attr("x", -10)
    .attr("y", -10)
    .attr("width", 20)
    .attr("height", 20)
    .attr("fill", "none")
    .attr("stroke", "currentColor")
    .attr("stroke-width", 2)
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .attr("aria-hidden", "true")
    .call((s) => {
      s.append("path").attr("d", USER_BODY);
      s.append("circle").attr("cx", 12).attr("cy", 7).attr("r", 4);
    });
}

function cssId(id) {
  return String(id).replace(/[^a-zA-Z0-9_-]/g, "_");
}

function columnFallback(graph, width, height) {
  const n = graph.nodes.length || 1;
  graph.nodes.forEach((d, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const colW = (width - 80) / 3;
    d.x0 = 40 + col * colW;
    d.x1 = d.x0 + 18;
    d.y0 = 40 + row * 64;
    d.y1 = d.y0 + 40;
  });
  const byId = new Map(graph.nodes.map((d) => [d.id, d]));
  graph.links.forEach((l) => {
    l.source = byId.get(l.source) || l.source;
    l.target = byId.get(l.target) || l.target;
    l.y0 = (l.source.y0 + l.source.y1) / 2;
    l.y1 = (l.target.y0 + l.target.y1) / 2;
    l.width = l.kind === "partner" ? 2 : Math.min(24, Math.max(4, Math.log10((l.amount || 1) + 1) * 6));
  });
  return graph;
}
