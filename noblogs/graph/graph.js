/* The epistemic-anchor graph, as a module both callers share.
 *
 * It used to live inside graph/index.html and be reached from the explorer
 * through an iframe. The frame was there because three documents each assumed
 * they owned the page: this one styles bare `header` and `aside`, and its
 * `#panel` and `#search` collide with the explorer's own. Scoping its CSS under
 * .nbgraph (graph/graph.css) and renaming those two IDs is what replaces it.
 *
 * Usage — both callers load cytoscape, graph_data.js, logos.embed.js,
 * quotes.embed.js, graph.css and this file, then:
 *
 *   var g = NBGraph.init(container, {
 *     standalone: false,
 *     onOpenHost: function (host) { ... }   // a blog node was tapped
 *   });
 *   g.setHosts(['a.org', ...]);   // cross-filter from the explorer facets
 *   g.focus(host, instDomains);   // returns true if it resolved a node
 *
 * The markup is built here rather than written into both pages, so the two
 * cannot drift apart.
 */
(function (global) {
  'use strict';

  /* Every control here is icon-only. The name lives in aria-label and in the
   * DRTip tooltip, which is also where the sentence explaining a mode goes \u2014
   * "Focus mode" names it without saying what it does, and that is the one
   * thing a label cannot do. */
  var ICON = {
    search:   '<path d="M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16"/><path d="m21 21-4.3-4.3"/>',
    zin:      '<path d="M5 12h14"/><path d="M12 5v14"/>',
    zout:     '<path d="M5 12h14"/>',
    fit:      '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>',
    relayout: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    focus:    '<circle cx="12" cy="12" r="10"/><path d="M22 12h-4"/><path d="M6 12H2"/><path d="M12 6V2"/><path d="M12 22v-4"/>',
    target:   '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>'
  };
  function svg(k) {
    return '<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICON[k] + '</svg>';
  }
  /* `tip` is the explanation, `name` the accessible name. They are different
   * strings on purpose: a sentence makes a poor accessible name, and an
   * icon-only control still needs one.
   *
   * data-tip, never `title`. DRTip is instant and styled; the native tooltip is
   * neither, and leaving both would stack a second one underneath ours a
   * second later and read the text twice to a screen reader. */
  function btn(o) {
    return '<button type="button" id="' + o.id + '" class="dr-btn dr-btn--icon" ' +
      'aria-label="' + (o.name || o.tipTitle || o.tip) + '" ' +
      (o.tipTitle ? 'data-tip-title="' + o.tipTitle + '" ' : '') +
      'data-tip="' + o.tip + '" ' + (o.extra || '') + '>' +
      svg(o.icon) +
      (o.toggle ? '<span class="dr-btn__dot" aria-hidden="true"></span>' : '') +
      '</button>';
  }

  var MARKUP =
    '<div id="stage">' +
      '<div id="cy"></div>' +
      '<div id="controls">' +
      /* No search field on the canvas: the explorer's HEADER field is the
       * graph's search on this view. See `find` in the returned API. */
        btn({id:'zin', icon:'zin', tip:'Zoom in'}) +
        btn({id:'zout', icon:'zout', tip:'Zoom out'}) +
        btn({id:'fit', icon:'fit', tipTitle:'Reset view', name:'Reset view',
             tip:'Back to the whole network, fitted to the canvas, with any focus cleared.'}) +
        btn({id:'relayout', icon:'relayout', tipTitle:'Re-layout', name:'Re-layout',
             tip:'Recompute where every node sits. Useful when labels overlap after a lot of panning.'}) +
        btn({id:'focusToggle', icon:'focus', toggle:true, name:'Focus mode',
             tipTitle:'Focus mode',
             tip:'Clicking a node shows only that node and its direct ties, so you can follow the network one node at a time. Turn it off to keep the whole graph visible and select without fading the rest.',
             extra:'aria-pressed="true"'}) +
        btn({id:'tgtOnly', icon:'target', toggle:true, name:'Target edges only',
             tipTitle:'Target edges only',
             tip:'Hide every citation except the ones backing a target designation \u2014 the red edges in the key.',
             extra:'aria-pressed="false"'}) +
        btn({id:'export', icon:'download', name:'Export',
             tipTitle:'Export',
             tip:'Download a high-resolution PNG of exactly this view \u2014 same pan, zoom and fade, at print quality.'}) +
      '</div>' +
      '<div id="legend"></div>' +
    '</div>' +
    '<aside id="gpanel"><div class="empty">Click a node to see its role and ties.<br><br>' +
      '<b>Institutions</b> are naming authorities; <b>blogs</b> cite them. ' +
      'Edge width is citation weight; red marks target designations.</div></aside>';

  function init(root, options) {
    options = options || {};
    var standalone = !!options.standalone;

    root.classList.add('nbgraph');
    root.classList.add('collapsed');          // was <div id="app" class="collapsed">
    // beforeend, not afterbegin: standalone puts a <header> in the container and
    // .nbgraph is a grid whose first row is that header.
    root.insertAdjacentHTML('beforeend', '<span id="counts" hidden></span>' + MARKUP);

    // Every lookup is scoped to this graph, so nothing reaches the host page.
    var $id = function (id) { return root.querySelector('#' + id); };

    // Logo paths in logos.index.js are relative to noblogs/graph/. This module
    // is loaded from two depths — /noblogs/graph/ standalone, and /noblogs/ for
    // the explorer's Graph tab — so the caller says which.
    var assetBase = options.assetBase || '';
    var logoSrc = function (u) { return u ? assetBase + u : ''; };

  const ICLASS = {
    authority_legal:   {c:'#991B1B', label:'Mainstream authority (SPLC/ADL/Amnesty/HRW/EFF)'},
    watchdog_research: {c:'#DB2777', label:'Antifa/watchdog research (the naming shops)'},
    legal_support:     {c:'#B45309', label:'Movement legal defense (Rote Hilfe/ABC/FAU)'},
    party_foundation:  {c:'#7C3AED', label:'Party foundation (Rosa-Luxemburg-Stiftung)'},
    movement_infra:    {c:'#0E7490', label:'Movement infrastructure / epistemic commons'},
  };
  const BLOG_COL='#64748B', DOX_COL='#7F1D1D';
  const EDGE = {
    target:  {c:'#DC2626', label:'Backs a target designation'},
    critical:{c:'#EA580C', label:'Critical / adversarial citation'},
    authority:{c:'#6366F1', label:'Authority citation'},
    infra:   {c:'#94A3B8', label:'Movement-infra citation'},
  };
  function edgeType(e){
    if(e.data('tgt')>0) return 'target';
    if(e.data('valence')==='critical') return 'critical';
    return e.data('kind')==='authority' ? 'authority' : 'infra';
  }

  const G = window.__GRAPH__;

  /* ---- territory partition: every node carries a __terr key so the layout packs each
     institution-class as its own spatial "continent". movement_infra (by far the biggest) is
     the free-floating CORE; the other 4 classes hug it on a compass. A blog is assigned to the
     class it cites most heavily (ties break toward the naming-authority continent), so doxxing
     blogs pack into the SPLC/ADL/watchdog tiles and anarchist blogs into the movement commons. */
  const CORE_TERR='movement_infra';
  const PRIO=['authority_legal','watchdog_research','legal_support','party_foundation','movement_infra'];
  const REGION_POS={
    authority_legal:  [ 0.10,-1.20],   // top — the mainstream-authority continent
    watchdog_research:[ 1.15,-0.25],   // right — the naming shops
    legal_support:    [-1.15,-0.30],   // left — movement legal defense
    party_foundation: [-0.30, 1.20],   // bottom-left — RLS
  };
  const CLASS_OF={}; G.nodes.forEach(n=>{ if(n.kind==='institution') CLASS_OF[n.id]=n.iclass; });
  const blogW={};
  G.edges.forEach(e=>{ const cl=CLASS_OF[e.target]; if(!cl) return;
    (blogW[e.source]=blogW[e.source]||{}); blogW[e.source][cl]=(blogW[e.source][cl]||0)+e.w; });
  function blogClass(id){ const w=blogW[id]||{}; let best='movement_infra',bw=-1;
    PRIO.forEach(cl=>{ const v=w[cl]||0; if(v>bw){bw=v;best=cl;} }); return best; }
  function terrKey(cl){ return cl===CORE_TERR?'CORE':cl; }

  const els = [];
  G.nodes.forEach(n=>{
    const L = window.NODE_LOGOS && window.NODE_LOGOS[n.id];
    const __terr = terrKey(n.kind==='institution' ? n.iclass : blogClass(n.id));
    if(n.kind==='institution'){
      const col = (ICLASS[n.iclass]||{}).c || '#555';
      const size = Math.max(46, 30 + Math.sqrt(n.total_citations)*4.2);
      els.push({data:{...n, __terr, col, size, hasLogo:L?1:0, logoUri:L?logoSrc(L.uri):'', tile:L?L.tile:'#fff'}});
    } else {
      const col = n.dox ? DOX_COL : BLOG_COL;
      const size = Math.max(26, 20 + Math.sqrt(n.impact)*2.6);
      els.push({data:{...n, __terr, col, size, hasLogo:L?1:0, logoUri:L?logoSrc(L.uri):'', tile:L?L.tile:'#fff'}});
    }
  });
  G.edges.forEach(e=>{
    els.push({data:{...e, col:EDGE[(e.tgt>0)?'target':(e.valence==='critical'?'critical':(e.kind==='authority'?'authority':'infra'))].c,
                    width: Math.max(1.2, Math.sqrt(e.w)*1.3)}});
  });

  $id('counts').textContent =
    `${G.meta.n_institutions} institutions · ${G.meta.n_blogs} blogs · ${G.meta.n_edges} edges · ${G.meta.n_target_edges} target-designation · blog floor impact ≥${G.meta.impact_floor}`;

  const cy = cytoscape({
    container:$id('cy'), elements:els, wheelSensitivity:0.25,
    textureOnViewport:true, hideEdgesOnViewport:true, motionBlur:false, pixelRatio:1,
    style:[
      {selector:'node',style:{
        'shape':'ellipse','background-color':'data(col)','background-opacity':0.92,
        'width':'data(size)','height':'data(size)','border-width':1.5,'border-color':'#ffffffcc',
        'label':'data(label)','font-size':'10px','font-weight':'600','color':'#1A1A1A',
        'text-wrap':'wrap','text-max-width':'96px','text-valign':'bottom','text-margin-y':3,
        'text-background-color':'#fff','text-background-opacity':0.78,'text-background-padding':'2px',
        'text-background-shape':'roundrectangle','min-zoomed-font-size':7}},
      {selector:'node[kind = "institution"]',style:{
        'shape':'round-rectangle','border-width':4,'border-color':'data(col)','font-size':'12px','font-weight':'700','text-max-width':'120px'}},
      {selector:'node[?hasLogo]',style:{
        'background-color':'data(tile)','background-opacity':1,'background-image':'data(logoUri)',
        'background-fit':'contain','background-clip':'node'}},
      {selector:'node[kind = "institution"][?hasLogo]',style:{'border-width':5}},
      {selector:'node[kind = "blog"][dox = 1]',style:{'border-width':3.5,'border-color':'#DC2626'}},
      {selector:'edge',style:{
        'width':'data(width)','line-color':'data(col)','curve-style':'straight',
        'line-opacity':ele=>ele.data('kind')==='infra'?0.4:0.72,
        'target-arrow-shape':'none','opacity':1}},
      {selector:'.faded',style:{'opacity':0.09,'text-opacity':0,'transition-property':'opacity','transition-duration':'200ms'}},
      {selector:'node.nbr',style:{'opacity':1,'text-opacity':1}},
      {selector:'edge.nbr',style:{'opacity':1,'line-opacity':0.95}},
      {selector:'node.sel',style:{'border-width':5,'border-color':'#000'}},
    ],
    layout:{name:'preset'}
  });
  window.cy = cy;

  /* ============ TERRITORY LAYOUT (ported from DataRepublican relations-explorer) ============
     Instead of one global force sim (which superclusters at this size), partition nodes into
     disjoint class "territories", pack each in its own tile, and place tiles so they can't overlap. */
  const GUTTER=90, PAD=54, GAP=30;
  function nodeRadius(n){ const bb=n.boundingBox({includeLabels:false});
    return Math.max(bb.w,bb.h)/2 || (+n.data('size')||38)/2; }

  function placeTile(box, members, opts){
    const core=!!(opts&&opts.core);
    const cxc=(box.x0+box.x1)/2, cyc=(box.y0+box.y1)/2;
    const P={}, keys=members.map(m=>m.id);
    const boxRad=Math.min(box.x1-box.x0,box.y1-box.y0)/2;
    const bydeg=[...members].sort((a,b)=>b.deg-a.deg);
    const gAng=Math.PI*(3-Math.sqrt(5));
    const spread=boxRad*(core?0.55:0.92);
    bydeg.forEach((m,i)=>{ const rr=spread*Math.sqrt(i/Math.max(1,bydeg.length-1)), a=i*gAng;
      P[m.id]={x:cxc+Math.cos(a)*rr, y:cyc+Math.sin(a)*rr, r:m.r, deg:m.deg}; });
    const idset=new Set(keys), links=[];
    cy.edges().forEach(e=>{const s=e.source().id(),t=e.target().id(); if(idset.has(s)&&idset.has(t)) links.push([s,t]);});
    const clampRect=p=>{p.x=Math.min(box.x1-p.r,Math.max(box.x0+p.r,p.x)); p.y=Math.min(box.y1-p.r,Math.max(box.y0+p.r,p.y));};
    const clampCirc=p=>{const dx=p.x-cxc, dy=p.y-cyc, R=Math.hypot(dx,dy)||1e-6, lim=boxRad-p.r; if(R>lim){ p.x=cxc+dx/R*lim; p.y=cyc+dy/R*lim; }};
    const clamp=core?clampCirc:clampRect;
    const REP=core?1.6:3.4;
    const ITER=280;
    for(let it=0; it<ITER; it++){
      const k=1-it/ITER;
      const gk=core?(0.4+0.6*k):k;
      for(let i=0;i<keys.length;i++) for(let j=i+1;j<keys.length;j++){
        const a=P[keys[i]], b=P[keys[j]];
        let dx=a.x-b.x, dy=a.y-b.y, d2=dx*dx+dy*dy||0.01, d=Math.sqrt(d2);
        const mind=a.r+b.r+GAP;
        let f=(a.r*b.r*REP)/d2; if(d<mind) f+=(mind-d)*0.85/d;
        a.x+=dx/d*f*k; a.y+=dy/d*f*k; b.x-=dx/d*f*k; b.y-=dy/d*f*k;
      }
      for(const [s,t] of links){
        const a=P[s], b=P[t]; let dx=b.x-a.x, dy=b.y-a.y, d=Math.hypot(dx,dy)||0.01;
        const ideal=a.r+b.r+80, f=(d-ideal)*0.02*k;
        a.x+=dx/d*f; a.y+=dy/d*f; b.x-=dx/d*f; b.y-=dy/d*f;
      }
      for(const id of keys){ const p=P[id];
        const cf=core?0.05*(1+Math.min(p.deg,20)/12):0.006*(1+Math.min(p.deg,20)/10);
        p.x+=(cxc-p.x)*cf*gk; p.y+=(cyc-p.y)*cf*gk; clamp(p); }
    }
    const NOPASS=core?140:60;
    for(let pass=0; pass<NOPASS; pass++){
      let moved=false;
      for(let i=0;i<keys.length;i++) for(let j=i+1;j<keys.length;j++){
        const a=P[keys[i]], b=P[keys[j]];
        let dx=a.x-b.x, dy=a.y-b.y, d=Math.hypot(dx,dy)||0.01, mind=a.r+b.r+GAP*0.6;
        if(d<mind){ const ux=dx/d, uy=dy/d, full=mind-d, half=full/2;
          a.x+=ux*half; a.y+=uy*half; b.x-=ux*half; b.y-=uy*half; moved=true; }
      }
      for(const id of keys) clamp(P[id]);
      if(!moved) break;
    }
    cy.batch(()=>{ for(const id of keys) cy.$id(id).position({x:P[id].x,y:P[id].y}); });
  }

  function territoryLayout(){
    const terr={};
    cy.nodes().forEach(n=>{ const key=n.data('__terr'); if(!key) return;
      (terr[key]=terr[key]||[]).push({id:n.id(), r:nodeRadius(n), deg:n.degree(false)}); });
    const tiles={};
    Object.entries(terr).forEach(([key,members])=>{
      const n=members.length, maxR=Math.max(...members.map(m=>m.r));
      const areaSum=members.reduce((s,m)=>s+Math.PI*(m.r+GAP)*(m.r+GAP),0);
      const fill = key==='CORE' ? 0.60 : 0.32;
      let side=Math.max(Math.sqrt(areaSum/fill),(2*maxR+GAP)*Math.ceil(Math.sqrt(n)),2*maxR+120);
      tiles[key]={key,members,side,w:side+2*PAD,h:side+2*PAD};
    });
    const setCenter=(t,cx,cy)=>{ t.cx=cx; t.cy=cy; t.x=cx-t.w/2; t.y=cy-t.h/2; };

    const core=tiles['CORE'];
    let chw = core ? core.w/2 : 320, chh = core ? core.h/2 : 320, ccx=0, ccy=0;
    if(core){
      setCenter(core,0,0);
      placeTile({x0:core.x+PAD,y0:core.y+PAD,x1:core.x+core.w-PAD,y1:core.y+core.h-PAD}, core.members, {core:true});
      let minX=1e9,minY=1e9,maxX=-1e9,maxY=-1e9;
      core.members.forEach(m=>{ const p=cy.$id(m.id).position();
        minX=Math.min(minX,p.x-m.r); maxX=Math.max(maxX,p.x+m.r); minY=Math.min(minY,p.y-m.r); maxY=Math.max(maxY,p.y+m.r); });
      ccx=(minX+maxX)/2; ccy=(minY+maxY)/2;
      chw=(maxX-minX)/2+PAD*0.5; chh=(maxY-minY)/2+PAD*0.5;
      core.w=2*chw; core.h=2*chh; setCenter(core,ccx,ccy);
    }

    const classes=Object.values(tiles).filter(t=>t.key!=='CORE');
    let fb=0; const fbN=classes.length||1;
    classes.forEach(t=>{
      let dir=REGION_POS[t.key];
      if(!dir){ const a=(fb++/fbN)*2*Math.PI; dir=[Math.cos(a),Math.sin(a)]; }
      const dl=Math.hypot(dir[0],dir[1])||1, ux=dir[0]/dl, uy=dir[1]/dl;
      const ax=Math.abs(ux)||1e-6, ay=Math.abs(uy)||1e-6;
      const tCore=Math.min(chw/ax, chh/ay);
      const tTile=Math.min((t.w/2)/ax,(t.h/2)/ay);
      const R=tCore+GUTTER+tTile;
      setCenter(t, ccx+ux*R, ccy+uy*R);
    });

    const movers=[core,...classes].filter(Boolean);
    for(let pass=0; pass<200; pass++){
      let moved=false;
      for(let i=0;i<movers.length;i++)for(let j=i+1;j<movers.length;j++){
        const a=movers[i], b=movers[j];
        const dx=a.cx-b.cx, dy=a.cy-b.cy;
        const ox=(a.w/2+b.w/2+GUTTER)-Math.abs(dx);
        const oy=(a.h/2+b.h/2+GUTTER)-Math.abs(dy);
        if(ox>0 && oy>0){
          if(ox<oy){ const s=dx>=0?1:-1;
            if(a.key==='CORE') setCenter(b,b.cx-s*ox,b.cy);
            else if(b.key==='CORE') setCenter(a,a.cx+s*ox,a.cy);
            else { setCenter(a,a.cx+s*ox/2,a.cy); setCenter(b,b.cx-s*ox/2,b.cy); }
          } else { const s=dy>=0?1:-1;
            if(a.key==='CORE') setCenter(b,b.cx,b.cy-s*oy);
            else if(b.key==='CORE') setCenter(a,a.cx,a.cy+s*oy);
            else { setCenter(a,a.cx,a.cy+s*oy/2); setCenter(b,b.cx,b.cy-s*oy/2); }
          }
          moved=true;
        }
      }
      if(!moved) break;
    }

    classes.forEach(t=>placeTile({x0:t.x+PAD,y0:t.y+PAD,x1:t.x+t.w-PAD,y1:t.y+t.h-PAD}, t.members));
    cy.fit(70);
  }
  territoryLayout();

  /* ---- legend (rows are clickable filters — click anywhere on a row to toggle) ---- */
  const hiddenN=new Set(), hiddenE=new Set();
  function applyLegendFilter(){
    const nHidden=new Set();
    cy.batch(()=>{
      cy.nodes().forEach(n=>{
        const key = n.data('kind')==='institution' ? 'n:'+n.data('iclass') : (n.data('dox')?'n:dox':'n:blog');
        const hide = hiddenN.has(key);
        if(hide) nHidden.add(n.id());
        n.style('display', hide?'none':'element');
      });
      cy.edges().forEach(e=>{
        const hide = hiddenE.has('e:'+edgeType(e)) || nHidden.has(e.source().id()) || nHidden.has(e.target().id());
        e.style('display', hide?'none':'element');
      });
    });
  }
  (function(){
    const classes = [...new Set(G.nodes.filter(n=>n.kind==='institution').map(n=>n.iclass))];
    const order=['authority_legal','watchdog_research','legal_support','party_foundation','movement_infra'];
    const irows = order.filter(k=>classes.includes(k)).map(k=>
      `<button type="button" class="row" data-nkey="n:${k}" aria-pressed="true"><span class="sw" style="background:${ICLASS[k].c}"></span>${ICLASS[k].label}</button>`).join('');
    const erows = ['target','critical','authority','infra'].map(k=>
      `<button type="button" class="row" data-ekey="e:${k}" aria-pressed="true"><span class="ln" style="border-color:${EDGE[k].c}"></span>${EDGE[k].label}</button>`).join('');
    const legend=$id('legend');
    /* A real disclosure and real toggles.
       The rows show and hide a class or an edge type, so they are buttons with
       aria-pressed — pressed means SHOWN, which is how the graph loads. They
       were <div>s with a delegated click: not focusable, no state announced.
       And the legend had no collapse at all, so on a phone it simply ran down
       the screen over the graph it was describing. */
    legend.innerHTML =
      `<button type="button" class="legtoggle" aria-expanded="false" aria-controls="glegend-body">Legend</button>`+
      `<div id="glegend-body" class="legbody">`+
      `<h4>Institution class — node color</h4>${irows}`+
      `<h4>Blogs</h4><button type="button" class="row" data-nkey="n:blog" aria-pressed="true"><span class="sw" style="background:${BLOG_COL};border-radius:50%"></span>Blog (round · size = impact)</button>`+
      `<button type="button" class="row" data-nkey="n:dox" aria-pressed="true"><span class="sw" style="background:${DOX_COL};border-radius:50%;box-shadow:0 0 0 2px #DC2626"></span>Doxxing-flagged blog</button>`+
      `<h4>Edge — “cited-by”</h4>${erows}`+
      `<div class="hint">Click a legend row to hide or show that class or edge type. Click any node to see its ties.</div>`+
      `</div>`;
    legend.addEventListener('click',ev=>{
      const t=ev.target.closest('.legtoggle');
      if(t){ t.setAttribute('aria-expanded', t.getAttribute('aria-expanded')==='true'?'false':'true'); return; }
      const row=ev.target.closest('.row'); if(!row) return;
      const nk=row.dataset.nkey, ek=row.dataset.ekey;
      if(nk){ hiddenN.has(nk)?hiddenN.delete(nk):hiddenN.add(nk); }
      else if(ek){ hiddenE.has(ek)?hiddenE.delete(ek):hiddenE.add(ek); }
      else return;
      const hidden=row.classList.toggle('off');
      // `off` is the dimming; aria-pressed is the state a screen reader reads.
      // Pressed means shown, so the two run in opposite directions.
      row.setAttribute('aria-pressed', String(!hidden));
      applyLegendFilter();
    });
  })();

  /* ---- detail panel + focus mode ---- */
  const panel=$id('gpanel');
  const EMPTY=panel.innerHTML;
  let focusMode=true, focusId=null;
  // root IS the old #app — the grid container and the .collapsed toggle.
  const appEl=root;

  /* The panel opens and closes ITSELF, in response to selection. There is no
   * user-facing control for it any more.
   *
   * There used to be a `‹` / `›` chevron floating at the top-right of the
   * canvas. It was a control for a state the user never has to manage: the
   * panel is empty until you click a node, and clicking the background empties
   * it again. So the button's only honest use was hiding a panel that already
   * had something in it — and the same click on the background did that plus
   * the deselect you actually wanted.
   *
   * Removing it also removes a worse problem. Three call sites — collapsePanel,
   * the sheet's onClose and revealPanel — all reached for `pt.onclick()`, a
   * TOGGLE, to express "close" or "open" specifically. Each had to test the
   * current state first and skip the call if it was already right; miss that
   * guard and the call does the exact opposite of what the site wanted. This is
   * an idempotent setter instead, so the call sites say what they mean. */
  function setPanel(open){
    if(appEl.classList.contains('collapsed')===!open) return;
    appEl.classList.toggle('collapsed',!open);
    requestAnimationFrame(()=>cy.resize());
  }
  // deselect → return the graph to full width (empty panel is just wasted whitespace)
  function collapsePanel(){panel.innerHTML=EMPTY;setPanel(false);}

  /* On a phone the detail panel is a bottom sheet, the same one noblogs and
     dsa-explorer use.

     Without this the panel still opened — it just opened as a block BELOW a
     full-viewport canvas, at y≈578 on an 844px screen, so tapping a node looked
     like nothing happened. The content was there and off the fold.

     DRSheet WRAPS rather than nests, which is required here: every open path
     below rewrites panel.innerHTML wholesale, so anything inserted as a child
     would be destroyed on the first tap. On desktop the wrapper is
     display:contents, so #gpanel stays a direct grid child of the 1fr/370px
     grid and nothing about that layout changes.

     window.DRSheet is undefined on the standalone /noblogs/graph/ page, which
     loads no site chrome; the guard keeps that page working as it did. */
  const gSheet = (window.DRSheet ? window.DRSheet.attach(panel, {
    label: 'Node details',
    detent: 'half',
    /* Closing hides the panel again and does NOT touch the graph. The sheet is
       a view of the selection, not the selection itself — dsa-explorer cleared
       cy classes here and dismissing the sheet threw away the focus ring and
       your place in the graph. Leave the fade, the selected node and the camera alone. */
    onClose: ()=>setPanel(false)
  }) : null);

  // The one way to reveal the panel, so the two states cannot drift apart.
  function revealPanel(){
    setPanel(true);
    if(gSheet && window.DRSheet.isMobile()) gSheet.open();
  }

  /* ---- shared quote renderer (English leads, foreign source collapsible) ---- */
  const IQ=(window.__IQUOTES__||{byInst:{},byHost:{}});
  function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  function quoteCard(q,labelType){
    const head=[];
    if(labelType==='host'&&q.host) head.push(`<span class="qhost">${esc(q.host.split('.')[0])}</span>`);
    else if(labelType==='inst'&&q.inst) head.push(`<span class="qhost">${esc(q.inst)}</span>`);
    if(q.inv) head.push(esc(q.inv.replace(/_/g,' ')));
    if(q.depth) head.push('depth '+q.depth);
    if(q.date) head.push(esc(q.date));
    if(q.val==='critical') head.push('<span class="qcrit">critical</span>');
    if(q.tgt) head.push('<span class="qflag">⚠ target designation</span>');
    const src=q.link?`<a href="${q.link}" target="_blank" rel="noopener">source ↗</a>`
      :`<span class="wh" title="Source link withheld — doxxing blog or residual redaction">source withheld</span>`;
    return `<div class="q${q.tgt?' tgt':''}">
      <div class="qhead">${head.join(' · ')}</div>
      <div class="en">${esc(q.en)}</div>
      ${q.fo?`<details class="orig"><summary>show original${q.lang?' · '+esc(q.lang):''}</summary><div class="fo">${esc(q.fo)}</div></details>`:''}
      <div class="qsrc">${src}</div>
    </div>`;
  }
  // Institutions: click-to-expand dropdown → all citing quotes across quoting blogs,
  // scrollable+contained. Blogs: up to 5, always-shown, no scroll box.
  function quotesBlock(list,{scroll,cap,labelType,title,collapse}){
    if(!list||!list.length) return '';
    const shown=cap?list.slice(0,cap):list;
    const more=cap&&list.length>cap?`<div class="qhead" style="margin-top:2px">+${list.length-cap} more not shown</div>`:'';
    const body=shown.map(q=>quoteCard(q,labelType)).join('');
    const inner=`${scroll?`<div class="qscroll">${body}</div>`:body}${more}`;
    if(collapse){
      const nblogs=new Set(list.map(q=>q.host)).size;
      return `<details class="qdrop"><summary>${title} (${list.length})
        <span class="sc">across ${nblogs} blog${nblogs!==1?'s':''} · click to expand</span></summary>${inner}</details>`;
    }
    return `<div class="quotes"><h3>${title} (${list.length})</h3>${inner}</div>`;
  }

  function instPanel(node){
    const d=node.data();
    const conns=node.connectedEdges().map(e=>{
      const blog=e.source().id()===d.id?e.target():e.source();
      return {id:blog.id(),label:blog.data('label'),w:e.data('w'),tgt:e.data('tgt'),
              inv:e.data('involvement'),dox:blog.data('dox')};
    }).sort((a,b)=>b.w-a.w);
    const nTgt=conns.filter(c=>c.tgt>0).length;
    const logo=d.logoUri?`<div style="float:right;width:56px;height:56px;border-radius:8px;border:2px solid ${d.col};background:${d.tile} center/contain no-repeat url('${d.logoUri}');margin:0 0 6px 8px"></div>`:'';

    // Quotes: show the top 3 MOST CONCERNING inline (IQ is pre-sorted target→critical→
    // depth→recent), then a clear dropdown for the rest — so you read the worst first
    // and can drill everything without a wall of text (#1).
    const iq=IQ.byInst[d.id]||[];
    const qTop=iq.slice(0,3), qRest=iq.slice(3);
    const nblogs=new Set(iq.map(q=>q.host)).size;
    const quotesHtml=iq.length?`<div class="quotes"><h3>Most concerning citations (${iq.length})</h3>
      ${qTop.map(q=>quoteCard(q,'host')).join('')}
      ${qRest.length?`<details class="qdrop"><summary>Show all ${iq.length} citing quotes
        <span class="sc">across ${nblogs} blog${nblogs!==1?'s':''}</span></summary>
        <div class="qscroll">${qRest.map(q=>quoteCard(q,'host')).join('')}</div></details>`:''}
    </div>`:'';

    // Connections: top 3 most-connected shown, rest behind a "show N more" expander (#1).
    const connRow=c=>`<div class="conn" data-goto="${c.id}"><div class="conn-head">${c.label} <span class="rel">— ${c.w} post${c.w!==1?'s':''}${c.dox?' · doxxing':''}</span>${c.tgt>0?` <span class="tgtflag">⚠ target×${c.tgt}</span>`:''}</div></div>`;
    const cTop=conns.slice(0,3), cRest=conns.slice(3);
    const connsHtml=`<div class="conns"><h3>${conns.length} citing blog${conns.length!==1?'s':''} — click to open</h3>
        ${cTop.map(connRow).join('')}
        ${cRest.length?`<details class="mdrop"><summary>Show ${cRest.length} more blog${cRest.length!==1?'s':''}</summary>${cRest.map(connRow).join('')}</details>`:''}
      </div>`;

    panel.innerHTML=`${logo}<span class="tag" style="background:${d.col}">${(ICLASS[d.iclass]||{}).label||d.iclass}</span>
      <h2>${d.label}</h2>
      <div class="kv"><b>Reach</b>${d.distinct_blogs} distinct citing blogs (corpus-wide)</div>
      <div class="kv"><b>Total citations</b>${d.total_citations}</div>
      ${nTgt?`<div class="kv"><b>Target-designation citations (in graph)</b><span style="color:#DC2626;font-weight:700">${nTgt} blogs cite it to back a target designation</span></div>`:''}
      ${quotesHtml}
      ${connsHtml}`;
    wire();
  }
  function blogPanel(node){
    const d=node.data();
    const conns=node.connectedEdges().map(e=>{
      const inst=e.target().id()===d.id?e.source():e.target();
      return {id:inst.id(),label:inst.data('label'),iclass:inst.data('iclass'),w:e.data('w'),
              tgt:e.data('tgt'),inv:e.data('involvement'),depth:e.data('depth'),val:e.data('valence')};
    }).sort((a,b)=>b.w-a.w);
    const doxBadge=d.dox?`<span class="tag" style="background:#DC2626">⚠ doxxing · ${d.dxn} target contacts</span>`:'';
    const link=d.url?`<div class="kv"><b>Site</b><a class="src" href="${d.url}" target="_blank" rel="noopener">${d.url}</a></div>`
                    :(d.dox?`<div class="kv"><b>Site</b><span style="color:#c0392b;font-weight:600">link withheld (doxxing-flagged)</span></div>`:'');
    const logo=d.logoUri?`<div style="float:right;width:52px;height:52px;border-radius:50%;border:2px solid ${d.col};background:${d.tile} center/cover no-repeat url('${d.logoUri}');margin:0 0 6px 8px"></div>`:'';
    panel.innerHTML=`${logo}${doxBadge}<span class="tag" style="background:#475569">blog</span>
      <h2>${d.label}</h2>
      <div class="kv"><b>Category · militancy</b>${d.cat} · ${d.mil}</div>
      ${(d.city||d.country)?`<div class="kv"><b>Location</b>${[d.city,d.country].filter(Boolean).join(' · ')} (${d.scope})</div>`:''}
      <div class="kv"><b>Citation impact</b>${d.impact}</div>
      ${link}
      ${d.summary?`<div class="notes">${d.summary}</div>`:''}
      ${quotesBlock(IQ.byHost[d.id],{scroll:true,labelType:'inst',title:'Verified institutional citations'})}
      <div class="conns"><h3>${conns.length} institution${conns.length!==1?'s':''} cited — click to open</h3>
        ${conns.map(c=>`<div class="conn" data-goto="${c.id}"><div class="conn-head">${c.label} <span class="rel">— ${c.w} post${c.w!==1?'s':''} · ${c.inv}${c.depth?(' · depth '+c.depth):''}${c.val==='critical'?' · critical':''}</span>${c.tgt>0?` <span class="tgtflag">⚠ target×${c.tgt}</span>`:''}</div></div>`).join('')}
      </div>`;
    wire();
  }
  function wire(){panel.querySelectorAll('.conn').forEach(el=>el.onclick=e=>{if(e.target.closest('a'))return;goto(el.dataset.goto);});}
  function paintRing(node){const nb=node.closedNeighborhood();cy.batch(()=>{cy.elements().addClass('faded').removeClass('nbr sel');nb.removeClass('faded').addClass('nbr');node.addClass('sel');});return nb;}
  function render(node){node.data('kind')==='institution'?instPanel(node):blogPanel(node);}
  function applyFocus(id,fit){const n=cy.$id(id);if(n.empty())return;focusId=id;const nb=paintRing(n);
    if(fit!==false){const bb=nb.boundingBox(),pad=90;const fz=Math.min((cy.width()-2*pad)/Math.max(bb.w,1),(cy.height()-2*pad)/Math.max(bb.h,1));cy.animate({center:{eles:n},zoom:Math.max(0.5,Math.min(1.6,fz))},{duration:400});}
    render(n);}
  function goto(id){const n=cy.$id(id);if(n.empty())return;if(focusMode)applyFocus(id);else{cy.batch(()=>{cy.elements().addClass('faded').removeClass('nbr sel');n.closedNeighborhood().removeClass('faded').addClass('nbr');n.addClass('sel');});render(n);cy.animate({center:{eles:n},zoom:1.3},{duration:300});}}
  // When embedded in the explorer, a BLOG node opens the SAME shared detail drawer
  // (consistent detail surface across dashboard/map/graph). Institutions keep the
  // graph's own panel (the explorer drawer has no institution view). Standalone: own panel.
  // Was `window.parent!==window`. The host says so directly now.
    const EMBEDDED = !standalone;
  cy.on('tap','node',ev=>{
    const n=ev.target;
    if(EMBEDDED && n.data('kind')==='blog'){
      if(focusMode){focusId=n.id();paintRing(n);}          // keep the ring highlight in-graph
      if(options.onOpenHost) options.onOpenHost(n.id());
      return;
    }
    revealPanel();
    focusMode?applyFocus(n.id()):goto(n.id());
  });
  cy.on('tap',ev=>{if(ev.target===cy){if(focusMode&&focusId)applyFocus(focusId,false);else{cy.elements().removeClass('faded nbr sel');collapsePanel();}}});

  /* ---- controls ---- */
  $id('zin').onclick=()=>cy.zoom({level:cy.zoom()*1.3,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
  $id('zout').onclick=()=>cy.zoom({level:cy.zoom()/1.3,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
  $id('fit').onclick=()=>{cy.elements().removeClass('faded nbr sel');focusId=null;collapsePanel();requestAnimationFrame(()=>cy.fit(45));};
  $id('relayout').onclick=()=>{territoryLayout();if(focusMode&&focusId)applyFocus(focusId,false);};
  /* aria-pressed is the whole state. .dr-btn__dot is shown and hidden by CSS
     keyed on that attribute, so there is nothing else to write. */
  function setToggle(btn,on){ btn.setAttribute('aria-pressed',String(on)); }
  $id('focusToggle').onclick=function(){focusMode=!focusMode;setToggle(this,focusMode);cy.elements().removeClass('faded nbr sel');if(!focusMode)collapsePanel();};
  let tgtOnly=false;
  $id('tgtOnly').onclick=function(){tgtOnly=!tgtOnly;setToggle(this,tgtOnly);
    cy.batch(()=>{cy.edges().forEach(e=>e.style('display',(!tgtOnly||e.data('tgt')>0)?'element':'none'));});};
  /* aria-busy and disabled, never a text swap. The button has no text to swap
     now, and when it did, doing it with button.textContent replaced every
     child — the <svg> was destroyed on the first export and restoring the
     string never brought it back. aria-busy is what button.css styles and what
     a screen reader reads. */
  $id('export').onclick=function(){
    const b=this;
    b.setAttribute('aria-busy','true');
    setTimeout(()=>{
      try{
        const uri=cy.png({full:false,scale:3,bg:'#fff',maxWidth:12000,maxHeight:12000});
        const a=document.createElement('a');a.href=uri;a.download='noblogs-graph.png';a.click();
      }catch(e){alert('Export failed: '+e.message);}
      b.removeAttribute('aria-busy');
    },60);
  };

  /* findNodes — the explorer's header field drives this on the Graph view.
     It HIGHLIGHTS; it never filters. Filtering a network removes the structure
     you opened it to look at, and the corpus index covers blogs only, so the
     77 institutions would be unreachable by any filtering search.

     Debounced at 200ms to match the page field: undebounced, each keystroke
     iterated over every node and rewrote classes across the whole element set inside a
     cy.batch, and a fast typist queued one full restyle per letter.

     Returns the hit count so the caller can report it. */
  let qTimer=null, lastQuery='';
  function paintFind(v){
    if(!v){
      if(focusMode&&focusId)applyFocus(focusId,false);
      else cy.elements().removeClass('faded nbr sel');
      return 0;
    }
    let n=0;
    cy.batch(()=>{
      cy.elements().addClass('faded').removeClass('nbr sel');
      /* Visible nodes only: without the display check this matched nodes the
         facet cross-filter had already hidden, so the ring went off screen. */
      const m=cy.nodes().filter(x=>x.style('display')!=='none'&&
        ((x.data('label')||'').toLowerCase().includes(v)||x.id().toLowerCase().includes(v)));
      m.removeClass('faded').addClass('nbr');
      m.connectedEdges().removeClass('faded');
      n=m.length;
    });
    return n;
  }
  function findNodes(query,onCount){
    const v=String(query||'').trim().toLowerCase();
    lastQuery=v;
    clearTimeout(qTimer);
    qTimer=setTimeout(()=>{
      const n=paintFind(v);
      /* Frame the hits so a search that matches one node off-screen is not a
         search that appears to do nothing. One hit gets centered; several get
         fitted. Nothing matched leaves the camera alone — moving the view to
         show an empty result is worse than not moving it. */
      if(n===1) cy.animate({center:{eles:cy.$('.nbr')},zoom:Math.max(cy.zoom(),1.1)},{duration:350});
      else if(n>1) cy.animate({fit:{eles:cy.$('.nbr'),padding:90}},{duration:350});
      if(typeof onCount==='function') onCount(n);
    },200);
  }
  // Re-run the current find after the host set changes under it.
  function refind(){ if(lastQuery) paintFind(lastQuery); }

  addEventListener('resize',()=>cy.resize());

  /* ---- cross-filter from the explorer facets (postMessage host-set) ---- */
  let FILTER=null;
  function applyGraphFilter(hosts){
    /* `Array.isArray`, not `hosts.length`. An EMPTY array means the filter
       matched nothing; `null` means there is no filter. Testing length
       collapsed the two, so a search with no results showed the whole network
       instead of an empty one. map.js's setHosts already guards it this way —
       this was the graph diverging from its sibling. */
    FILTER=Array.isArray(hosts)?new Set(hosts):null;
    cy.batch(()=>{
      cy.nodes('[kind = "blog"]').forEach(n=>n.style('display',(!FILTER||FILTER.has(n.id()))?'element':'none'));
      cy.edges().forEach(e=>{const s=e.source(),t=e.target();
        const b=s.data('kind')==='blog'?s:(t.data('kind')==='blog'?t:null);
        const shown=!b||!FILTER||FILTER.has(b.id());
        e.style('display',(shown&&!(tgtOnly&&e.data('tgt')<=0))?'element':'none');});
    });
  }
  /* The explorer used to push {type:'filter'} and {type:'focus'} over
       postMessage, re-posting focus every 150ms up to 40 times until the graph
       ACKed with {type:'focusDone'} — a retry loop that existed only because the
       frame might still be laying out. focusNode returns whether it resolved the
       node, so the caller knows without being told twice. */
    function focusNode(host, insts){
      const id=[host,...(insts||[])].filter(Boolean).find(d=>cy.$id(d).nonempty());
      if(!id) return false;
      revealPanel();
      applyFocus(id);
      setTimeout(()=>{if(cy.$id(id).nonempty())applyFocus(id);},400); // survive layout settle
      return true;
    }

  /* ---- deep-link: index.html#<nodeId> focuses that node ---- */
  function openHash(){const id=decodeURIComponent(location.hash.slice(1));if(id&&cy.$id(id).nonempty())setTimeout(()=>applyFocus(id),200);}
  if(standalone){openHash();window.addEventListener('hashchange',openHash);}

    return {
      cy: cy,
      setHosts: function (hosts) { applyGraphFilter(hosts); refind(); },
      find: findNodes,
      focus: focusNode,
      resize: function () { cy.resize(); },
      destroy: function () { cy.destroy(); }
    };
  }

  global.NBGraph = { init: init };
})(window);
