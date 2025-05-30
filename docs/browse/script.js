import {
  Charity,
  Grant,
  formatNumber,
  viewModel,
  BrowseViewModel,
} from "./models.js";

let svg = null;
let zoom = null;

const NODE_WIDTH = 50;
const OTHER_WIDTH = 30;
const NODE_PADDING = 25;
const MIN_LINK_HEIGHT = 5;

const colorScale = d3.scaleOrdinal(d3.schemeCategory10);

function updateStatus(message, color = "black") {
  $("#status").text(message).css("color", color);
}

$(document).ready(function () {
  if (viewModel.dataReady) viewModel.parseQueryParams();

  updateStatus("Loading Data...");
  viewModel
    .loadData()
    .then(() => {
      generateGraph();
    })
    .catch((err) => {
      console.error(err);
      updateStatus("Failed to load data.", "red");
    });

  $("#addEinBtn").on("click", addEINFromInput);
  $("#einInput").on("keypress", (e) => {
    if (e.key === "Enter") addEINFromInput();
  });
  $("#clearEINsBtnShow").on("click", () => {
    window.location.href = "/browse/";
  });
  $("#clearEINsBtnHide").on("click", () => {
    viewModel.clearHideList();
    renderHideEINs();
    updateQueryParams();
    generateGraph();
  });
  $("#addFilterBtn").on("click", addKeywordFromInput);
  $("#keywordInput").on("keypress", (e) => {
    if (e.key === "Enter") addKeywordFromInput();
  });
  $("#clearFiltersBtn").on("click", () => {
    viewModel.clearKeywordList();
    renderActiveKeywords();
    updateQueryParams();
    generateGraph();
  });

  $("#downloadBtn").on("click", downloadSVG);

  $("#howItWorksBtn").on("click", function () {
    const $list = $("#howItWorksList");
    const $btn = $(this);
    if ($list.height() === 0) {
      $list.css("height", "auto");
      const autoHeight = $list.height();
      $list.height(0);
      $list.height(autoHeight);
      $btn.text("Hide details");
    } else {
      $list.height(0);
      $btn.text("How it works (& why you should use it)");
    }
  });

  const searchInput = document.getElementById("searchInput");
  const searchResults = document.getElementById("searchResults");
  const clearButton = document.getElementById("clearSearch");

  const newSearchInput = searchInput.cloneNode(true);
  const newSearchResults = searchResults.cloneNode(true);
  const newClearButton = clearButton.cloneNode(true);

  searchInput.parentNode.replaceChild(newSearchInput, searchInput);
  searchResults.parentNode.replaceChild(newSearchResults, searchResults);
  clearButton.parentNode.replaceChild(newClearButton, clearButton);

  newSearchInput.addEventListener("input", handleSearch);
  newSearchInput.addEventListener("blur", handleSearchBlur);
  newSearchInput.addEventListener("keydown", handleSearchKeydown);
  newSearchResults.addEventListener("click", handleSearchClick);

  newClearButton.addEventListener("click", () => {
    newSearchInput.value = "";
    newSearchInput.focus();
    handleSearch({ target: newSearchInput });
  });

  $(window).on("resize", function () {
    if (viewModel.dataReady) generateGraph();
  });
});

function addEINFromInput() {
  let val = $("#einShowInput").val().trim().replace(/[-\s]/g, "");
  if (!/^\d{9}$/.test(val) && val !== "001") {
    alert("EIN must be 9 digits after removing dashes/spaces or 001.");
    return;
  }
  const charity = Charity.getCharity(val);
  if (!charity) console.warn("EIN not found in charities.csv (still adding).");
  viewModel.addToShowList(val);
  $("#einShowInput").val("");
  renderActiveEINs();
  Charity.placeNode(val);
  updateQueryParams();
  generateGraph();
}

function renderActiveEINs() {
  const $c = $("#activeEINs");
  $c.empty();
  $("#clearEINsBtnShow").toggle(viewModel.getShowList().length > 0);

  viewModel.getShowList().forEach((ein) => {
    const name = Charity.getCharity(ein)?.name || "???";
    const $tag = $(
      '<div class="filter-tag flex items-center gap-0.5 rounded border border-green bg-green/10 text-green px-2 py-1 text-xs"></div>'
    );
    const $text = $(
      `<span title="EIN: ${ein.split(":")[0].slice(0, 2)}-${ein
        .split(":")[0]
        .slice(2)}"></span>`
    ).text(name);
    const $rm = $(
      '<span class="remove-filter opacity-50 hover:opacity-100 size-5 -my-0.5 -mr-1 cursor-pointer"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10S2 17.523 2 12Zm7.53-3.53a.75.75 0 0 0-1.06 1.06L10.94 12l-2.47 2.47a.75.75 0 1 0 1.06 1.06L12 13.06l2.47 2.47a.75.75 0 1 0 1.06-1.06L13.06 12l2.47-2.47a.75.75 0 0 0-1.06-1.06L12 10.94 9.53 8.47Z" clip-rule="evenodd"/></svg></span>'
    ).attr("data-ein", ein);
    $rm.on("click", function () {
      viewModel.removeFromShowList(ein);
      renderActiveEINs();
      updateQueryParams();
      generateGraph();
    });
    $tag.append($text).append($rm);
    $c.append($tag);
  });
}

function renderHideEINs() {
  const $c = $("#hideEINs");
  $c.empty();
  $("#clearEINsBtnHide").toggle(viewModel.getHideList().length > 0);

  viewModel.getHideList().forEach((ein) => {
    const name = Charity.getCharity(ein)?.name || "???";
    const $tag = $(
      '<div class="filter-tag flex items-center gap-0.5 rounded border border-red bg-red/10 text-red rounded-md px-2 py-1 text-xs"></div>'
    );
    const $text = $(
      `<span title="EIN: ${ein.split(":")[0].slice(0, 2)}-${ein
        .split(":")[0]
        .slice(2)}"></span>`
    ).text(name);
    const $rm = $(
      '<span class="remove-filter opacity-50 hover:opacity-100 size-5 -my-0.5 -mr-1 cursor-pointer"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10S2 17.523 2 12Zm7.53-3.53a.75.75 0 0 0-1.06 1.06L10.94 12l-2.47 2.47a.75.75 0 1 0 1.06 1.06L12 13.06l2.47 2.47a.75.75 0 1 0 1.06-1.06L13.06 12l2.47-2.47a.75.75 0 0 0-1.06-1.06L12 10.94 9.53 8.47Z" clip-rule="evenodd"/></svg></span>'
    ).attr("data-nein", ein);
    $rm.on("click", function () {
      viewModel.removeFromHideList(ein);
      renderHideEINs();
      updateQueryParams();
      generateGraph();
    });
    $tag.append($text).append($rm);
    $c.append($tag);
  });
}

function addKeywordFromInput() {
  const kw = $("#keywordInput").val().trim();
  if (kw.length > 0) {
    viewModel.addToKeywords(kw.toLowerCase());
    $("#keywordInput").val("");
    renderActiveKeywords();
    updateQueryParams();
    generateGraph();
  }
}

function renderActiveKeywords() {
  const $c = $("#activeFilters");
  $c.empty();
  $("#clearFiltersBtn").toggle(viewModel.getKeywordList().length > 0);

  viewModel.getKeywordList().forEach((kw) => {
    const $tag = $(
      '<div class="filter-tag flex items-center gap-0.5 rounded border border-blue bg-blue/10 text-blue rounded-md px-2 py-1 text-xs"></div>'
    );
    const $text = $("<span></span>").text(kw);
    const $rm = $(
      '<span class="remove-filter opacity-50 hover:opacity-100 size-5 -my-0.5 -mr-1 cursor-pointer"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10S2 17.523 2 12Zm7.53-3.53a.75.75 0 0 0-1.06 1.06L10.94 12l-2.47 2.47a.75.75 0 1 0 1.06 1.06L12 13.06l2.47 2.47a.75.75 0 1 0 1.06-1.06L13.06 12l2.47-2.47a.75.75 0 0 0-1.06-1.06L12 10.94 9.53 8.47Z" clip-rule="evenodd"/></svg></span>'
    ).attr("data-kw", kw);
    $rm.on("click", function () {
      viewModel.removeFromKeywords(kw);
      renderActiveKeywords();
      updateQueryParams();
      generateGraph();
    });
    $tag.append($text).append($rm);
    $c.append($tag);
  });
}

function downloadSVG() {
  const svgEl = document.querySelector("#graph-container svg");
  if (!svgEl) {
    alert("No SVG to download yet.");
    return;
  }
  const svgData = new XMLSerializer().serializeToString(svgEl);
  const blob = new Blob([svgData], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "charity_graph.svg";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function updateQueryParams() {
  const params = viewModel.computeURLParams();
  const newUrl = window.location.pathname + "?" + params.toString();
  window.history.replaceState({}, "", newUrl);
}

function compareCharities(a, b) {
  return (
    b.grantsInTotal + b.grantsTotal - (a.grantsInTotal + a.grantsTotal) ||
    a.name.localeCompare(b.name)
  );
}

function compareLinks(a, b) {
  return b.value - a.value;
}

function generateUniqueId(prefix = "gradient", link) {
  return `${prefix}-${link.filer.id}~${link.grantee.id}`;
}

function calculateScale(graph, width, height) {
  const nodes = graph.nodes;
  if (!nodes.length) return 1;

  let minX = Infinity,
    maxX = -Infinity;
  let minY = Infinity,
    maxY = -Infinity;

  nodes.forEach((node) => {
    minX = Math.min(minX, node.x0);
    maxX = Math.max(maxX, node.x1);
    minY = Math.min(minY, node.y0);
    maxY = Math.max(maxY, node.y1);
  });

  const layoutWidth = Math.max(maxX - minX, 1);
  const layoutHeight = Math.max(maxY - minY, 1);
  return Math.min(width / layoutWidth, height / layoutHeight);
}

function generateTrapezoidPath(d) {
  const midY = (d.y0 + d.y1) / 2;
  const y0In = midY - d.inflowHeight / 2;
  const y1In = midY + d.inflowHeight / 2;
  const y0Out = midY - d.outflowHeight / 2;
  const y1Out = midY + d.outflowHeight / 2;
  return `M${d.x0},${y0In} L${d.x0},${y1In} L${d.x1},${y1Out} L${d.x1},${y0Out} Z`;
}

function generateOctagonPath(d) {
  const radius = d.inflowHeight / 2 || 10;
  const cx = d.x0;
  const cy = (d.y0 + d.y1) / 2;
  const r = d.inflowHeight / ((2 * Math.sqrt(2 + Math.SQRT2)) / 2);

  const c = Math.sqrt(2 + Math.SQRT2) / 2;
  const s = Math.sqrt(2 - Math.SQRT2) / 2;

  return `M${cx + r * c},${cy + r * s} L${cx + r * s},${cy + r * c} L${
    cx - r * s
  },${cy + r * c} L${cx - r * c},${cy + r * s} L${cx - r * c},${cy - r * s} L${
    cx - r * s
  },${cy - r * c} L${cx + r * s},${cy - r * c} L${cx + r * c},${cy - r * s} Z`;
}

function generatePlusPath(d) {
  const radius = OTHER_WIDTH / 2;
  const armWidth = radius * 0.4;
  let cx, circlePath;
  const cy = (d.y0 + d.y1) / 2;

  if (d.isTerminal) {
    const inflowHeight = d.inflowHeight || OTHER_WIDTH;
    cx = d.x0 - inflowHeight / 2;
    circlePath = `M${cx},${cy + radius} A${radius},${radius} 0 0 1 ${cx},${
      cy - radius
    }`; // Bottom to top, left
  } else if (d.isRight) {
    cx = d.x1;
    circlePath = `M${cx},${cy - radius} A${radius},${radius} 0 0 1 ${cx},${
      cy + radius
    }`; // Top to bottom, right
  } else {
    cx = d.x0;
    circlePath = `M${cx},${cy + radius} A${radius},${radius} 0 0 1 ${cx},${
      cy - radius
    }`; // Bottom to top, left
  }

  const plusPath = `
    M${cx - armWidth},${cy} H${cx + armWidth}
    M${cx},${cy - armWidth} V${cy + armWidth}
  `;
  return `${circlePath} ${plusPath}`;
}

function computeLinkY(node, linkIndex, links, heightKey, isSourceSide) {
  const sortedLinks = [...links].sort(compareLinks);
  const cumulativeHeight = d3.sum(
    sortedLinks.slice(0, linkIndex),
    (l) => l.width
  );
  const centerY = (node.y0 + node.y1) / 2;
  const height = node[heightKey] || 0;
  const linkHeight = sortedLinks[linkIndex].width || 0;
  const startY = isSourceSide ? centerY - height / 2 : centerY + height / 2;
  const segmentTop = isSourceSide
    ? startY + cumulativeHeight
    : startY - height + cumulativeHeight;
  return segmentTop + linkHeight / 2;
}

function sankeyLinkHorizontalTrapezoid(curvature = 0.5) {
  return function (link) {
    const source = link.source;
    const originalSourceLinks = [...source.sourceLinks];
    const outflowIndex = source.sourceLinks.sort(compareLinks).indexOf(link);
    const sourceY = computeLinkY(
      source,
      outflowIndex,
      source.sourceLinks,
      "outflowHeight",
      true
    );
    const sourceX = source.x1;

    const target = link.target;
    const originalTargetLinks = [...target.targetLinks];
    const inflowIndex = target.targetLinks.sort(compareLinks).indexOf(link);
    const targetY = computeLinkY(
      target,
      inflowIndex,
      target.targetLinks,
      "inflowHeight",
      false
    );
    const targetX = target.x0;

    source.sourceLinks = originalSourceLinks;
    target.targetLinks = originalTargetLinks;

    const dx = targetX - sourceX;
    const cp1X = sourceX + dx * curvature;
    const cp1Y = sourceY;
    const cp2X = targetX - dx * curvature;
    const cp2Y = targetY;

    return `M${sourceX},${sourceY} C${cp1X},${cp1Y} ${cp2X},${cp2Y} ${targetX},${targetY}`;
  };
}

function calculateRegularPosition(node, scale, height) {
  let scaleFactor = 100;
  // note, this are using only the visible grants.
  const sankeyHeight = node.y1 - node.y0;
  if (node.grantsInLogTotal > node.grantsLogTotal)
    scaleFactor = sankeyHeight / node.grantsInLogTotal;
  else scaleFactor = sankeyHeight / node.grantsLogTotal;
  node.outflowHeight = Math.min(
    sankeyHeight,
    node.grantsLogTotal * scaleFactor
  );
  node.inflowHeight = Math.min(
    sankeyHeight,
    node.grantsInLogTotal * scaleFactor
  );
  if (node.grantsLogTotal === 0) {
    node.inflowHeight = sankeyHeight;
    node.outflowHeight = 5;
  }
  if (node.grantsInLogTotal === 0) {
    node.inflowHeight = 5;
    node.outflowHeight = sankeyHeight;
  }
  if (!isFinite(node.outflowHeight) || !isFinite(node.inflowHeight)) {
    console.error(
      `Invalid heights for ${node.filer_ein}: outflow=${node.outflowHeight}, inflow=${node.inflowHeight}`
    );
    node.outflowHeight = 50;
    node.inflowHeight = 50;
  }
}

function calculateNodePositions(nodes, scale, height) {
  nodes.forEach((d) => calculateRegularPosition(d, scale, height));
}

function normalizeStrokeWidths(sankey) {
  const nodes = sankey.nodes;
  nodes.forEach((node) => {
    const totalOutflowWidth = d3.sum(node.sourceLinks, (l) => l.width);
    const outflowHeight = node.outflowHeight || 0;
    if (totalOutflowWidth > 0 && outflowHeight > 0) {
      const scaleFactor = outflowHeight / totalOutflowWidth;
      node.sourceLinks.forEach(
        (link) => (link.normalizedWidth = link.width * scaleFactor)
      );
    }
    const totalInflowWidth = d3.sum(node.targetLinks, (l) => l.width);
    const inflowHeight = node.inflowHeight || 0;
    if (totalInflowWidth > 0 && inflowHeight > 0) {
      const scaleFactor = inflowHeight / totalInflowWidth;
      node.targetLinks.forEach(
        (link) => (link.normalizedWidth = link.width * scaleFactor)
      );
    }
  });
}
function savePreviousState(data) {
  data.nodes.forEach((node) => {
    if (node.hasOwnProperty("x0")) {
      node.previousX0 = node.x0;
      node.previousY0 = node.y0;
      node.previousX1 = node.x1;
      node.previousY1 = node.y1;
      node.hasLeftHat =
        node.canExpandInflows && node.invisibleGrantsIn.length > 0;
      node.hasRightHat =
        !node.isTerminal &&
        node.canExpandOutflows &&
        node.invisibleGrants.length > 0;
    }
  });
  data.links.forEach((link) => {
    if (link.hasOwnProperty("width")) {
      link.previousWidth = link.width;
      link.previousSource = {
        x0: link.source.x0,
        y0: link.source.y0,
        x1: link.source.x1,
        y1: link.source.y1,
      };
      link.previousTarget = {
        x0: link.target.x0,
        y0: link.target.y0,
        x1: link.target.x1,
        y1: link.target.y1,
      };
    }
  });
}

function bindEvents(g) {
  g.selectAll(".node")
    .on("click", (event, d) => {
      console.log("Node clicked:", d.id);
      event.stopPropagation();
      if (event.shiftKey) {
        d.hide();
        Charity.addToHideList(d.ein);
        refresh();
      } else if (event.metaKey) {
        showControlPanel("node", d, this);
      } else {
        viewModel.clickNode(event, d, refresh);
      }
    })
    .on("dblclick", (event, d) => {
      console.log("Node double-clicked:", d.id);
      event.stopPropagation();
      if (d.isTerminal && !event.shiftKey) {
        d.hideUp();
        Charity.addToHideList(d.ein);
        refresh();
      } else {
        viewModel.doubleClickNode(event, d, refresh);
      }
    });

  g.selectAll(".link")
    .on("click", (event, d) => {
      console.log("Link clicked:", d.id);
      event.stopPropagation();
      showControlPanel("link", d, this);
    })
    .on("dblclick", (event, d) => {
      console.log("Link double-clicked:", d.id);
      event.stopPropagation();
      viewModel.doubleClickGrant(event, d, refresh);
    });

  g.selectAll(".hat-up").on("click", (event, d) => {
    console.log("Hat left clicked:", d.id);
    event.stopPropagation();
    viewModel.handleUpClick(event, d, refresh);
  });

  g.selectAll(".hat-down").on("click", (event, d) => {
    console.log("Hat right clicked:", d.id);
    event.stopPropagation();
    viewModel.handleDownClick(event, d, refresh);
  });
}

function zoomToFit() {
  const g = svg.select("g.main"); // Select g.main dynamically
  const bounds = g.node().getBBox();
  if (
    !isFinite(bounds.width) ||
    bounds.width <= 0 ||
    !isFinite(bounds.height) ||
    bounds.height <= 0
  ) {
    console.warn("Invalid bounds for zoom:", bounds);
    return;
  }
  const container = document.getElementById("graph-container");
  const width = container.offsetWidth;
  const height = container.offsetHeight || window.innerHeight * 0.7;
  const dx = bounds.x;
  const dy = bounds.y;
  const scale = 0.8 / Math.max(bounds.width / width, bounds.height / height);
  svg
    .transition()
    .duration(750)
    .call(
      zoom.transform,
      d3.zoomIdentity
        .translate(width / 2, height / 2)
        .scale(scale)
        .translate(-dx - bounds.width / 2, -dy - bounds.height / 2)
    );
}

function generateGraph() {
  if (!viewModel.dataReady) {
    alert("Data not loaded yet. Please wait.");
    return;
  }

  $("#loading").show();
  $("#graph-container svg").remove();

  const container = document.getElementById("graph-container");
  const width = container.offsetWidth;
  const height = container.offsetHeight || window.innerHeight * 0.7;

  svg = d3
    .select("#graph-container")
    .append("svg")
    .attr("id", "graph")
    .attr("width", "100%")
    .attr("height", "100%")
    .style("display", "block")
    .style("background", "#fff");

  zoom = d3
    .zoom()
    .extent([
      [0, 0],
      [width, height],
    ]) // Match renderFocusedSankey extent
    .scaleExtent([0.1, 4]) // Match original range
    .filter(
      (event) =>
        event.type === "wheel" ||
        (event.type === "mousedown" && event.button === 0)
    ) // Match renderFocusedSankey filter
    .on("zoom", (event) => {
      svg.select("g.main").attr("transform", event.transform); // Target g.main
    });

  svg.call(zoom);

  let g = svg
    .append("g")
    .attr("class", "main")
    .attr("transform", "translate(50, 50)");

  const sankey = d3
    .sankey()
    .nodeId((d) => d.id)
    .nodeWidth(NODE_WIDTH)
    .nodePadding(NODE_PADDING)
    .linkSort(compareLinks)
    .nodeAlign(d3.sankeyCenter)
    .nodeSort(compareCharities)
    .size([width - 100, height - 100]);

  viewModel.parseQueryParams();
  if (!viewModel.matchURL()) viewModel.loadDefaultData();

  viewModel.previousData = renderFocusedSankey(
    g,
    sankey,
    svg, // Use global svg instead of svgRef
    width,
    height,
    viewModel.getShowList().length
      ? viewModel.getShowList()
      : [viewModel.GOV_EIN],
    viewModel.previousData
  );

  // Button handlers using global zoom
  document.getElementById("zoomIn").onclick = () =>
    svg.transition().duration(300).call(zoom.scaleBy, 1.3);
  document.getElementById("zoomOut").onclick = () =>
    svg.transition().duration(300).call(zoom.scaleBy, 0.7);
  document.getElementById("zoomFit").onclick = () => {
    const g = svg.select("g.main"); // Select g.main dynamically
    const bounds = g.node().getBBox();
    if (
      !isFinite(bounds.width) ||
      bounds.width <= 0 ||
      !isFinite(bounds.height) ||
      bounds.height <= 0
    )
      return;
    const dx = bounds.x;
    const dy = bounds.y;
    const scale = 0.8 / Math.max(bounds.width / width, bounds.height / height);
    svg
      .transition()
      .duration(750)
      .call(
        zoom.transform,
        d3.zoomIdentity
          .translate(width / 2, height / 2)
          .scale(scale)
          .translate(-dx - bounds.width / 2, -dy - bounds.height / 2)
      );
  };
  document.getElementById("scaleUp").onclick = () => {
    viewModel.graphScaleUp();
    refresh();
  };
  document.getElementById("scaleDown").onclick = () => {
    viewModel.graphScaleDown();
    refresh();
  };
  document.getElementById("scaleReset").onclick = () => {
    viewModel.graphScaleReset();
    refresh();
  };

  /*setTimeout(() => {
    const g = svg.select("g.main");
    const bounds = g.node().getBBox();
    if (
      !isFinite(bounds.width) ||
      bounds.width <= 0 ||
      !isFinite(bounds.height) ||
      bounds.height <= 0
    ) {
      console.error("Invalid bounds for zoom:", bounds);
      return;
    }
    const dx = bounds.x;
    const dy = bounds.y;
    const scale = 0.8 / Math.max(bounds.width / width, bounds.height / height);
    svg
      .transition()
      .duration(750)
      .call(
        zoom.transform,
        d3.zoomIdentity
          .translate(width / 2, height / 2)
          .scale(scale)
          .translate(-dx - bounds.width / 2, -dy - bounds.height / 2)
      );
  }, 1000);*/

  zoomToFit();
  renderActiveEINs();
  renderActiveKeywords();
  renderHideEINs();
  $("#loading").hide();
}

function renderFocusedSankey(
  g,
  sankey,
  svg,
  width,
  height,
  nodeIds,
  previousData
) {
  const ANIM_NODE = 500;
  const ANIM_LINK = 1200;
  const ANIM_HAT = 1500;
  const ANIM_TEXT = 1500;
  $("#downloadBtn").hide();

  let currentData = viewModel.buildSankeyData();
  savePreviousState(currentData);

  const sankeyWidth = width - 100;
  const sankeyHeight = height - 100;
  sankey.size([sankeyWidth, sankeyHeight]).nodePadding(25);

  const graph = sankey(currentData);

  const scale = calculateScale(graph, width, height);
  calculateNodePositions(graph.nodes, scale, height);
  normalizeStrokeWidths(graph);

  if (!previousData) {
    svg.selectAll("*").remove();
  }

  const defs = svg.selectAll("defs").data([0]).join("defs");
  graph.links.forEach((link) => {
    link.gradientId = link.gradientId || generateUniqueId("gradient", link);
  });

  const gradients = defs
    .selectAll("linearGradient.dynamic")
    .data(graph.links, (d) => d.gradientId);

  gradients.exit().remove();

  const gradientEnter = gradients
    .enter()
    .append("linearGradient")
    .attr("class", "dynamic")
    .attr("id", (d) => d.gradientId)
    .attr("gradientUnits", "objectBoundingBox")
    .attr("x1", "0")
    .attr("y1", "0.5")
    .attr("x2", "1")
    .attr("y2", "0.5");

  gradientEnter
    .append("stop")
    .attr("offset", "0%")
    .attr("stop-color", (d) => colorScale(d.source.id));
  gradientEnter
    .append("stop")
    .attr("offset", "100%")
    .attr("stop-color", (d) => colorScale(d.target.id));

  gradients
    .merge(gradientEnter)
    .selectAll("stop")
    .data((d) => [
      { offset: "0%", color: colorScale(d.source.id) },
      { offset: "100%", color: colorScale(d.target.id) },
    ])
    .join("stop")
    .attr("offset", (d) => d.offset)
    .attr("stop-color", (d) => d.color);

  g = svg
    .selectAll("g.main")
    .data([0])
    .join("g")
    .attr("class", "main")
    .attr("transform", `translate(50, 50) scale(${scale})`);

  // No local zoom definition here—rely on global zoom from generateGraph

  const masterGroup = g
    .selectAll(".graph-group")
    .data([0])
    .join("g")
    .attr("class", "graph-group");

  const linkGroup = masterGroup
    .selectAll("g.links")
    .data([0])
    .join("g")
    .attr("class", "links")
    .attr("fill", "none")
    .attr("stroke-opacity", 1)
    .style("mix-blend-mode", "multiply");

  const link = linkGroup
    .selectAll(".link")
    .data(graph.links, (d) => `${d.source.id}-${d.target.id}`);

  link.exit().transition().duration(ANIM_LINK).attr("stroke-width", 0).remove();

  const linkEnter = link
    .enter()
    .append("path")
    .attr("class", "link")
    .attr("d", sankeyLinkHorizontalTrapezoid())
    .attr("stroke", (d) => colorScale(d.source.id))
    .style("stroke-opacity", "0.3")
    .attr("stroke-width", 0);

  link
    .merge(linkEnter)
    .transition()
    .duration(ANIM_LINK)
    .attr("d", sankeyLinkHorizontalTrapezoid())
    .attr("stroke", (d) => colorScale(d.source.id))
    .attr("stroke-width", (d) => d.width || 1);

  linkEnter
    .append("title")
    .text(
      (d) => `${d.source.name} → ${d.target.name}\n$${formatNumber(d.amt)}`
    );

  const nodeGroup = masterGroup
    .selectAll("g.nodes")
    .data([0])
    .join("g")
    .attr("class", "nodes");

  const nodeElements = nodeGroup
    .selectAll("g.node")
    .data(graph.nodes, (d) => d.id);

  nodeElements
    .exit()
    .transition()
    .duration(ANIM_NODE)
    .attr("transform", "scale(0)")
    .remove();

  const nodeEnter = nodeElements
    .enter()
    .append("g")
    .attr("class", (d) => (d.isTerminal ? "node no-grants" : "node expand"))
    .attr("data-id", (d) => d.id)
    .style("opacity", 0);

  nodeEnter.each(function (d) {
    const sel = d3.select(this);
    sel
      .append("path")
      .attr("stroke", "#000")
      .attr(
        "d",
        d.isTerminal
          ? generateOctagonPath({
              ...d,
              x0: d.previousX0 || d.x0,
              y0: d.previousY0 || d.y0,
              x1: d.previousX1 || d.x1,
              y1: d.previousY1 || d.y1,
            })
          : generateTrapezoidPath({
              ...d,
              x0: d.previousX0 || d.x0,
              y0: d.previousY0 || d.y0,
              x1: d.previousX1 || d.x1,
              y1: d.previousY1 || d.y1,
            })
      )
      .attr("fill", colorScale(d.id))
      .style("cursor", d.isTerminal ? "zoom-out" : "grab")
      .append("title")
      .text((d) => d.toolTipText());
  });

  nodeEnter.transition().duration(ANIM_NODE).style("opacity", 1);

  nodeElements
    .merge(nodeEnter)
    .filter((d) => d.previousX0 !== undefined)
    .select("path")
    .transition()
    .duration(ANIM_NODE)
    .attr("d", (d) =>
      d.isTerminal ? generateOctagonPath(d) : generateTrapezoidPath(d)
    );

  const hatGroup = masterGroup
    .selectAll("g.expand-hats")
    .data([0])
    .join("g")
    .attr("class", "expand-hats");

  const leftHats = hatGroup.selectAll("g.hat-left").data(
    graph.nodes.filter(
      (d) => d.canExpandInflows && d.invisibleGrantsIn.length > 0
    ),
    (d) => `${d.id}-left`
  );

  leftHats
    .exit()
    .filter((d) => d.hasLeftHat)
    .transition()
    .duration(ANIM_HAT)
    .style("opacity", 0)
    .remove();

  const leftHatEnter = leftHats
    .enter()
    .append("g")
    .attr("class", "hat-left")
    .style("opacity", (d) => (d.hasLeftHat ? 1 : 0));

  leftHatEnter
    .append("path")
    .attr("d", (d) =>
      generatePlusPath({ ...d, isRight: false, isTerminal: d.isTerminal })
    )
    .attr("fill", "#ccc")
    .attr("stroke", "#000")
    .attr("class", "hat-up")
    .style("cursor", "pointer")
    .append("title")
    .text("expand more inflows");

  leftHats
    .merge(leftHatEnter)
    .transition()
    .duration(ANIM_HAT)
    .style("opacity", (d) =>
      d.canExpandInflows && d.invisibleGrantsIn.length > 0 && !d.hasLeftHat
        ? 1
        : d.hasLeftHat &&
          !(d.canExpandInflows && d.invisibleGrantsIn.length > 0)
        ? 0
        : 1
    )
    .select("path")
    .attr("d", (d) =>
      generatePlusPath({ ...d, isRight: false, isTerminal: d.isTerminal })
    );
  const rightHats = hatGroup.selectAll("g.hat-right").data(
    graph.nodes.filter(
      (d) =>
        !d.isTerminal && d.canExpandOutflows && d.invisibleGrants.length > 0
    ),
    (d) => `${d.id}-right`
  );

  rightHats
    .exit()
    .filter((d) => d.hasRightHat)
    .transition()
    .duration(ANIM_HAT)
    .style("opacity", 0)
    .remove();

  const rightHatEnter = rightHats
    .enter()
    .append("g")
    .attr("class", "hat-right")
    .style("opacity", (d) => (d.hasRightHat ? 1 : 0));

  rightHatEnter
    .append("path")
    .attr("d", (d) => generatePlusPath({ ...d, isRight: true }))
    .attr("fill", "#ccc")
    .attr("stroke", "#000")
    .attr("class", "hat-down")
    .style("cursor", "pointer")
    .append("title")
    .text("expand more outflows");

  rightHats
    .merge(rightHatEnter)
    .transition()
    .duration(ANIM_HAT)
    .style("opacity", (d) =>
      !d.isTerminal &&
      d.canExpandOutflows &&
      d.invisibleGrants.length > 0 &&
      !d.hasRightHat
        ? 1
        : d.hasRightHat &&
          !(
            !d.isTerminal &&
            d.canExpandOutflows &&
            d.invisibleGrants.length > 0
          )
        ? 0
        : 1
    )
    .select("path")
    .attr("d", (d) => generatePlusPath({ ...d, isRight: true }));

  const textGroup = masterGroup
    .selectAll("g.text")
    .data([0])
    .join("g")
    .attr("class", "text");

  const text = textGroup.selectAll("text").data(graph.nodes, (d) => d.id);

  text.exit().remove();

  const textEnter = text
    .enter()
    .append("text")
    .attr("dy", "0.35em")
    .attr("x", (d) => (d.x0 < sankey.nodeWidth() / 2 ? d.x1 + 6 : d.x0 - 6))
    .attr("y", (d) => ((d.previousY0 || d.y0) + (d.previousY1 || d.y1)) / 2)
    .attr("text-anchor", (d) =>
      d.x0 < sankey.nodeWidth() / 2 ? "start" : "end"
    )
    .style("font-size", `${12 * scale}px`);

  text
    .merge(textEnter)
    .transition()
    .duration(ANIM_TEXT)
    .attr("x", (d) => (d.x0 < sankey.nodeWidth() / 2 ? d.x1 + 6 : d.x0 - 6))
    .attr("y", (d) => (d.y0 + d.y1) / 2)
    .attr("text-anchor", (d) =>
      d.x0 < sankey.nodeWidth() / 2 ? "start" : "end"
    )
    .style("font-size", `${12 * scale}px`)
    .text((d) => d.name);

  bindEvents(g);

  viewModel.cleanAfterRender();
  $("#downloadBtn").show();

  return currentData;
}

// [Rest of the file unchanged...]
function handleSearch(e) {
  const value = e.target.value.toLowerCase();
  const searchResults = document.getElementById("searchResults");
  const clearButton = document.getElementById("clearSearch");

  if (!value) {
    searchResults.classList.add("hidden");
    clearButton.classList.add("hidden");
    return;
  }

  clearButton.classList.remove("hidden");

  const matches = Object.values(Charity.charityLookup)
    .filter(
      (d) => d.name.toLowerCase().includes(value) || d.ein.includes(value)
    )
    .slice(0, 5);

  if (matches.length > 0) {
    searchResults.innerHTML = matches
      .map(
        (d, index) => `
          <div class="p-2 cursor-pointer ${
            index === 0 ? "bg-blue/10" : ""
          } hover:bg-gray-100" 
               data-ein="${d.ein}" data-index="${index}" 
               onmouseenter="handleSearchResultHover(${index})">
            ${d.name}
          </div>
        `
      )
      .join("");
    searchResults.classList.remove("hidden");
    selectedSearchIndex = 0;
    const firstResult = searchResults.querySelector('[data-index="0"]');
    if (firstResult) firstResult.classList.add("bg-blue/10");
  } else {
    searchResults.classList.add("hidden");
    selectedSearchIndex = -1;
  }
}

function handleSearchBlur() {
  // No specific action needed on blur
}

let selectedSearchIndex = 0;

function handleSearchKeydown(e) {
  const searchResults = document.getElementById("searchResults");
  if (searchResults.classList.contains("hidden")) return;

  const results = searchResults.querySelectorAll("[data-index]");
  const maxIndex = results.length - 1;

  if (maxIndex < 0) {
    selectedSearchIndex = -1;
    return;
  }

  switch (e.key) {
    case "ArrowDown":
      e.preventDefault();
      selectedSearchIndex = Math.min(selectedSearchIndex + 1, maxIndex);
      updateSearchSelection(results);
      break;
    case "ArrowUp":
      e.preventDefault();
      selectedSearchIndex = Math.max(selectedSearchIndex - 1, 0);
      updateSearchSelection(results);
      break;
    case "Enter":
      e.preventDefault();
      if (selectedSearchIndex >= 0) {
        const selectedResult = results[selectedSearchIndex];
        if (selectedResult) handleSearchClick({ target: selectedResult });
      }
      break;
    case "Escape":
      e.preventDefault();
      searchResults.classList.add("hidden");
      e.target.blur();
      break;
  }
}

function handleSearchClick(e) {
  const ein = e.target.getAttribute("data-ein");
  if (ein) {
    viewModel.addToShowList(ein);
    renderActiveEINs();
    updateQueryParams();
    generateGraph();
    document.getElementById("searchResults").classList.add("hidden");
  }
}

function updateSearchSelection(results) {
  results.forEach((result, index) => {
    if (index === selectedSearchIndex) {
      result.classList.add("bg-blue/10");
      result.classList.remove("hover:bg-gray-100");
      result.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else {
      result.classList.remove("bg-blue/10");
      result.classList.add("hover:bg-gray-100");
    }
  });
}

function handleSearchResultHover(index) {
  selectedSearchIndex = index;
  updateSearchSelection(document.querySelectorAll("[data-index]"));
}

function refresh() {
  renderHideEINs();
  updateQueryParams();
  generateGraph();
}

function showControlPanel(type, data, element) {
  const panel = document.getElementById("control-panel");
  let content = "";

  function renderButtons(node, withButtons) {
    if (!withButtons) return "";
    return `
      <div class="flex-1 bg-gray-200 p-4">
        <button onclick="focusNode('${node.ein}')">Focus on This</button>
        <button ${
          !node.canExpandInflows ? 'disabled class="bg-gray-100 disabled"' : ""
        } onclick="expandInflows('${node.ein}')">Show 3 Inflows</button>
        <button ${
          !node.canExpandOutflows ? 'disabled class="bg-gray-100 disabled"' : ""
        } onclick="expandOutflows('${node.ein}')">Expand 3 Outflows</button>
      </div>
      <div class="flex-1 bg-gray-200 p-4">
        <button onclick="removeNode('${node.ein}')">Remove This</button>
        <button ${
          !node.canCompressInflows ? "disabled class='disabled'" : ""
        } onclick="compressInflows('${node.ein}')">Hide 3 Inflows</button>
        <button ${
          !node.canCompressOutflows ? "disabled class='disabled'" : ""
        } onclick="compressOutflows('${node.ein}')">Hide 3 Outflows</button>
      </div>
    `;
  }

  function renderNode(node, withButtons = false) {
    let buttons = renderButtons(node, withButtons);
    let links = "";
    let inflows = "<p>Inflows: N/A</p>";
    let outflows = "<p>Outflows: N/A</p>";
    let hiddenInflows = node.invisibleGrantsIn.length
      ? `<p><i>$${formatNumber(
          node.invisibleGrantsIn.reduce((sum, g) => sum + g.amt, 0)
        )} hidden (${node.invisibleGrantsIn.length} grants)</i></p>`
      : "";
    let hiddenOutflows = node.invisibleGrants.length
      ? `<p><i>$${formatNumber(
          node.invisibleGrants.reduce((sum, g) => sum + g.amt, 0)
        )} hidden (${node.invisibleGrants.length} grants)</i></p>`
      : "";

    if (node.isGov) {
      return `
        <div class="bg-blue-500 text-white flex-col p-4 text-center">
          <h3>${node.name}</h3>
          <p>EIN: ${node.ein}</p>
        </div>
        <div class="flex flex-row gap-4">
          <div class="flex-1 bg-gray-200 p-4">
            <p>US Taxpayers: <b>$4.6T</b></p>
            <p>Outflows: $${formatNumber(node.visibleGrantsTotal)} visible (${
        node.visibleGrants.length
      } grants)</p>
            ${hiddenOutflows}
          </div>
          ${buttons}
        </div>
      `;
    } else {
      if (!node.isRoot)
        inflows = `<p>Inflows: $${formatNumber(
          node.visibleGrantsInTotal - node.govt_amt
        )} visible (${
          node.visibleGrantsIn.length
        } grants)</p> ${hiddenInflows}`;
      if (!node.isTerminal)
        outflows = `<p>Outflows: $${formatNumber(
          node.visibleGrantsTotal
        )} visible (${node.visibleGrants.length} grants)</p> ${hiddenOutflows}`;
      links = `
        <p>From US Gov: <b>$${formatNumber(node.govt_amt)}</b></p>
        <p><a href="${node.financialsLink()}">Show me the Financials</a></p>
        <p><a href="${node.officersLink()}">Show me the Officers</a></p>
        <p><a href="${node.nonprofitsLink()}">Show me the Money!</a></p>
        <p>${node.propublicaLink("Take me to Propublica")}</p>
        <p>${node.googleLink("Google")}</p>
        <!--<p>${node.grokLink("Grok")}</p>-->
      `;
    }

    return `
      <div class="bg-blue-500 text-white flex-col p-4 text-center">
        <h3>${node.name}</h3>
        <p>EIN: ${node.ein}</p>
      </div>
      <div class="flex flex-row gap-4">
        <div class="flex-1 bg-gray-200 p-4">
          ${links}
          ${inflows}
          ${outflows}
        </div>
        ${buttons}
      </div>
    `;
  }

  if (type === "node") {
    content = renderNode(data, true);
  } else if (type === "link") {
    content = `
      <div class="flex flex-col gap-4">
        <div class="bg-blue-500 text-white p-4 text-center">
          <h3>Grant Details</h3>
          <p>Amount: $${formatNumber(data.amt)}</p>
        </div>
        <div class="flex flex-row gap-4">
          <div class="flex-1 bg-gray-200 p-4">
            <h4>From:</h4>
            ${renderNode(data.filer)}
            <button onclick="expandOutflows('${
              data.filer.ein
            }')">Expand Source</button>
            <button onclick="compressOutflows('${
              data.filer.ein
            }')">Compress Source</button>
          </div>
          <div class="flex-1 bg-gray-300 p-4">
            <h4>To:</h4>
            ${renderNode(data.grantee)}
            <button onclick="expandInflows('${
              data.grantee.ein
            }')">Expand Target</button>
            <button onclick="compressInflows('${
              data.grantee.ein
            }')">Compress Target</button>
          </div>
        </div>
      </div>
    `;
  }

  panel.innerHTML = content;
  panel.style.display = "block";

  d3.selectAll(".node").classed("selected", false);
  d3.selectAll(".link").classed("selected", false);
  d3.select(element).classed("selected", true);
}

function closePanel() {
  document.getElementById("control-panel").style.display = "none";
  d3.selectAll(".node").classed("selected", false);
  d3.selectAll(".link").classed("selected", false);
}

document.addEventListener("click", closePanel);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closePanel();
});

document.getElementById("control-panel").addEventListener("click", (event) => {
  event.stopPropagation();
});

window.removeNode = function (ein) {
  const charity = Charity.getCharity(ein);
  if (charity) {
    charity.hide();
    refresh();
  }
  closePanel();
};

window.expandInflows = function (ein) {
  const charity = Charity.getCharity(ein);
  if (charity) {
    charity.expandInflows();
    refresh();
  }
  closePanel();
};

window.expandOutflows = function (ein) {
  const charity = Charity.getCharity(ein);
  if (charity) {
    charity.expandOutflows();
    refresh();
  }
  closePanel();
};

window.compressInflows = function (ein) {
  const charity = Charity.getCharity(ein);
  if (charity) {
    charity.compressInflows();
    refresh();
  }
  closePanel();
};

window.compressOutflows = function (ein) {
  const charity = Charity.getCharity(ein);
  if (charity) {
    charity.compressOutflows();
    refresh();
  }
  closePanel();
};

window.focusNode = function (ein) {
  const params = new URLSearchParams();
  params.append("ein", ein);
  const newUrl = window.location.pathname + "?" + params.toString();
  window.history.replaceState({}, "", newUrl);
  viewModel.parseQueryParams();
  viewModel.resetAll();
  generateGraph();
  closePanel();
};

const extraStyle = `
  .node { fill: #999; }
  .node.expand { cursor: grab; }
  .node.no-grants { cursor: zoom-out; }
  .link { stroke-opacity: 0.5; }
  .hat-up, .hat-down { cursor: pointer; }
  text { fill: #000; }
  .selected { stroke: #ff0; stroke-width: 2px; }
`;
d3.select("head").append("style").text(extraStyle);
