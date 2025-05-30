const POWER_LAW_RESET = 3;
const TOP_N_INITIAL = 5;
const START_REVEAL = 5;
const MIN_REVEAL = 2;
const NEXT_REVEAL = 3;
const NEXT_REVEAL_MAX = 15;
const GOV_EIN = "001";
const MAX_NODES = 100;
const CHUNK_SIZE = 1000;
const MAX_KEYWORD_NODES = 15;

/* keep this around and export it mostly for debugging*/
let GOV_NODE = null;

/**
 * Tried logarithmic scaling, but it was too drastic 1M vs. 1B was 3. 
 * Power law scaling is more natural, default of cube root means
 * it looks like this:
 * 
 * Steps    Power Law (x^(1/3))    Logarithmic (ln(x))
1K       10                     6.9078
1M       100                    13.8155
1B       1,000                  20.7233
1T       10,000                 27.6310

 * @param {*} amt 
 * @returns 
 */
function scaleValue(amt) {
  return Math.pow(amt, 1 / viewModel.POWER_LAW);
}

/**
 * Aka what ls et all call human scaling.
 * @param {*} num
 * @returns
 */
function formatNumber(num) {
  if (num >= 1e12) return (num / 1e12).toFixed(1) + "T";
  if (num >= 1e9) return (num / 1e9).toFixed(1) + "B";
  if (num >= 1e6) return (num / 1e6).toFixed(1) + "M";
  if (num >= 1e3) return (num / 1e3).toFixed(1) + "K";
  return num == null ? "N/A" : num.toString();
}

/**
 * As they say in Highlander, there can be only one
 */
let viewModel = null;

/**
 * So this is an M-V-VM architecture.
 * M - Model, deals with the data
 * V = View, displays the data
 * VM = View Model, translates between M and V.
 *
 * I've tried MVC, didn't work. MVVM does.
 */
class BrowseViewModel {
  constructor({ POWER_LAW = POWER_LAW_RESET, GOV_EIN = "001" } = {}) {
    this.POWER_LAW = POWER_LAW; /** Users can change the scaling on the fly */
    this.GOV_EIN =
      GOV_EIN; /** Had to pick something, it was this or 0000000001  */
    this.GOV_NODE = null; /** keep this around for debugging */

    /**
     * Ok, a lot of the work between the M and the V is about maintaining visibilitiy.
     * Nominally, we start with 100,000 nodes, 660,000 edges.
     * We need to capture things the user wants (showList) and things they don't want
     * hideList. keywords is another way to specify things to show.
     *
     * Strictly speaking, one could argue that its the ViewModels job to maintain
     * visibility, but we have the Model calculate how that propogates.
     */
    this.hideList = {};
    this.showList = {};

    /** this isn't used yet, but the idea is that eventually we'll keep track
     * of the users explorations, so we can replay them to adjust the visibility.
     */
    this.breadCrumbs = [];
    this.keywords = {};

    /** Essentially globals */
    this.renderData = null;
    this.dataReady = false;
    viewModel = this;
    this.resetAll();
  }

  /**Called when we focus on just one node*/
  resetAll() {
    Object.values(Grant.grantLookup).forEach((g) => {
      g.desiredVisible = false;
      g.impliedVisible = 0;
    });
  }

  /** methods for manipulating the scaling */

  setGraphScale(scale) {
    if (scale != this.POWER_LAW) {
      this.POWER_LAW = scale;
      Charity.disorganzeAll();
    }
  }
  graphScaleDown() {
    this.POWER_LAW++;
    this.computeURLParams(); // update URL
    Charity.disorganzeAll();
  }

  graphScaleUp() {
    this.POWER_LAW--;
    if (this.POWER_LAW < 1) this.POWER_LAW = 1;
    this.computeURLParams(); // update URL
    Charity.disorganzeAll();
  }

  graphScaleReset() {
    this.POWER_LAW = POWER_LAW_RESET;
    this.computeURLParams(); // update URL
    Charity.disorganzeAll();
  }

  /** methods for manipulating the Show List */
  addToShowList(ein) {
    const c = Charity.getCharity(ein);
    if (c) {
      this.showList[c.ein] = ein.split(":").slice(1) || [
        START_REVEAL,
        START_REVEAL,
      ];
      c.desiredVisible = true;
    }
  }

  removeFromShowList(ein) {
    const id = ein.split(":")[0];
    delete this.showList[id];
    const c = Charity.getCharity(id);
    if (c) c.desiredVisible = false;
  }

  getShowList() {
    const result = Object.entries(this.showList)
      .sort((a, b) => a[0] - b[0]) // sort by key
      .map(
        ([key, value]) =>
          `${key}:${value[0] || START_REVEAL}:${value[1] || START_REVEAL}`
      );
    return result;
  }

  setShowList(list) {
    this.showList = {};
    list.forEach((ein) => this.addToShowList(ein));
    return this.getShowList();
  }

  clearShowList() {
    this.showList = {};
  }

  /** methods for manipulating the hide list */
  addToHideList(ein) {
    const c = Charity.getCharity(ein);
    if (c) {
      this.hideList[ein] = 1;
      c.desiredVisible = false;
    }
  }

  removeFromHideList(ein) {
    delete this.hideList[ein];
    const c = Charity.getCharity(ein);
    if (c) c.desiredVisible = true;
    viewModel.computeImpliedVisibility(c, true, true);
  }

  shouldHide(ein) {
    return this.hideList[ein];
  }

  getHideList() {
    return Object.keys(this.hideList).sort();
  }

  setHideList(list) {
    this.hideList = {};
    list.forEach((ein) => this.addToHideList(ein));
    return this.getHideList();
  }

  clearHideList() {
    this.hideList = {};
  }

  /** bread crumbs, as noted, aspirational at the moment */
  addToBreadCrumbs(crumb) {
    this.breadCrumbs.push(crumb);
  }

  removeFromBreadCrumbs(crumb) {
    this.breadCrumbs = this.breadCrumbs.filter((c) => c !== crumb);
  }

  getBreadCrumbs() {
    return this.breadCrumbs;
  }

  setBreadCrumbs(list) {
    this.breadCrumbs = list;
  }

  /** keep track of search keywords */
  addToKeywords(word) {
    this.keywords[word.toLowerCase()] = 1;
  }

  removeFromKeywords(word) {
    delete this.keywords[word.toLowerCase()];
  }

  clearKeywordList() {
    this.keywords = {};
  }

  getKeywordList() {
    return Object.keys(this.keywords).sort();
  }

  setKeywordList(list) {
    this.keywords = Object.fromEntries(list.map((key) => [key, 1]));
  }

  /** match Charities against search terms */
  matchKeys() {
    return Object.values(Charity.charityLookup).filter((c) =>
      c.searchMatch(Object.keys(this.keywords))
    );
  }

  /**
   * After we expand or compress, we have to reset the EIN in the show list.
   *
   */
  resetEIN(ein) {
    const c = Charity.getCharity(ein);
    if (c) {
      this.addToShowList(c.URLPiece());
    }
  }

  /** Given a model in a given state, calculate the minimum URL necessary to replicate that
   * state. Since visibility can be direct (called desired in the model) or implied, we
   * only need to include the desired charities, not the implied.
   */
  computeURLParams() {
    const params = new URLSearchParams();
    let visibleMap = {};
    Charity.desiredCharities.forEach((c) => {
      const p = c.URLPiece();
      if (p) visibleMap[c.ein] = p;
    });
    this.getHideList().forEach((ein) => delete visibleMap[ein]);
    Object.values(visibleMap).forEach((e) => params.append("ein", e));
    this.getHideList().forEach((e) => params.append("nein", e));
    this.getKeywordList().forEach((k) => params.append("keywords", k));
    params.append("scale", this.POWER_LAW);
    return params;
  }

  /** given a URL, parse it into our relevant pieces */
  parseQueryParams(params = new URLSearchParams(window.location.search)) {
    this.showList = {};
    this.setShowList(params.getAll("ein"));
    this.setHideList(params.getAll("nein"));
    this.setBreadCrumbs(params.getAll("breadCrumbs"));
    this.setKeywordList(params.getAll("keywords"));
    const scale = parseInt(params.get("scale") || "0", 10);
    if (scale) this.setGraphScale(scale);
  }

  /** Place holder for when we actually parse the breadcrumb data, for
   * now it insures we have a starting point.
   */
  processBreadCrumbs() {
    if (Charity.visibleCharities.length === 0) {
      this.loadDefaultData();
    }
  }

  /**
   *  Given our URL, match the model. That means seeding the model with desiredVisible nodes
   * from the showList and the search keywords, then turning that off for the hide List items.
   * This is called "placing" a Node, which makes the node visible and then marks the first
   * START_REVEAL incoming and outgoing edges and nodes as implied visible. The ein in the
   * URL actually encodes the number of visilbe upstream and downstream grants, so we can
   * faithfully reproduce some expansion.
   * @param {The URL} params
   * @returns
   */
  matchURL(params = new URLSearchParams(window.location.search)) {
    this.parseQueryParams(params);
    updateStatus("", "green", false);
    console.log("ShowList before processing:", this.getShowList());
    Object.values(Charity.charityLookup).forEach((c) => {
      c.desiredVisible = false;
      c.impliedVisible = 0;
    });
    this.getShowList().forEach((ein) => {
      const parts = ein.split(":");
      const id = parts[0];
      const ups = parts[1] || START_REVEAL;
      const downs = parts[2] || START_REVEAL;
      const charity = Charity.getCharity(id);
      if (charity && !this.shouldHide(id) && !charity.desiredVisible) {
        charity.place(ups, downs);
        console.log(
          `Matched EIN ${ein}, placed ${id}, grants out: ${charity.grants.length}, in: ${charity.grantsIn.length}`
        );
      } else {
        console.log(`no match for ${ein} in match`);
      }
    });
    this.getHideList().forEach((ein) => {
      const c = Charity.getCharity(ein);
      if (c) c.desiredVisible = false;
    });
    if (this.getKeywordList().length) {
      const matches = Charity.invisibleCharities.filter(
        (c) =>
          !this.shouldHide(c.id) &&
          c.searchMatch(Object.keys(this.keywords)) &&
          !c.desiredVisible
      );

      const limitedMatches = matches.slice(0, MAX_KEYWORD_NODES);
      if (matches.length > MAX_KEYWORD_NODES) {
        updateStatus(
          `<span>Note: Graph limited to first ${MAX_KEYWORD_NODES} of ${matches.length} matching results</span>`,
          "black",
          false
        );
      }

      limitedMatches.forEach((c) => {
        c.place(1, 1); // avoid sankey explosion
      });
    }
    this.computeImpliedVisibility(null, true, true);
    console.log(
      "Visible Charities after matchURL:",
      Charity.visibleCharities.length,
      Charity.visibleCharities.map((c) => c.id)
    );
    return Charity.visibleCharities.length;
  }

  /**
   * So the NGO data we're parsing calls out how much money each NGO is getting from the Government.
   * That's treated as an implied grant from a virtual NGO, so we generate that by scanning all the
   * NGOs and creating that data. This is technically a model function, but its here now and I'm
   * not religious about any kind of code architecture enough to bother moving it.
   * @returns
   */
  async buildGovCharity() {
    updateStatus(`Building US Govt from ${Charity.getCharityCount}`);
    const gov_ein = this.GOV_EIN;
    const gov_proto = {
      ein: gov_ein,
      filer_ein: gov_ein,
      name: "US Government",
      xml_name: "The Beast",
      contrib_amt: 4.6e12, // aka 4.6T
    };
    const govChar = new Charity(gov_proto);
    let govGrants = 0;
    let processList = Object.values(Charity.charityLookup)
      .filter((c) => c.govt_amt)
      .sort((a, b) => b.govt_amt - a.govt_amt);
    const govCount = processList.length;
    let govTotal = 0;
    const totalGrants = processList.reduce((sum, c) => sum + c.govt_amt, 0);

    let chunk = processList.slice(0, CHUNK_SIZE);
    processList = processList.slice(CHUNK_SIZE);
    while (chunk.length) {
      chunk.forEach((c) => {
        if (c.govt_amt > 0) {
          const filer = gov_ein;
          const grantee = c.id;
          let amt = c.govt_amt;
          if (isNaN(amt)) amt = 0;
          govGrants++;
          new Grant({
            filer_ein: filer,
            amt: amt,
            grantee_ein: grantee,
          });
          govTotal += amt;
        }
      });
      updateStatus(
        `<span>Gov processing</span><span class="text-[13px] opacity-60">${Math.round(
          (govGrants / govCount) * 100
        )}% ${Math.round(
          (govTotal / totalGrants) * 100
        )}% ${govGrants}/${govCount} ${formatNumber(govTotal)}/${formatNumber(
          totalGrants
        )} complete</span>`
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
      chunk = processList.slice(0, CHUNK_SIZE);
      processList = processList.slice(CHUNK_SIZE);
    }

    updateStatus(
      `<span>Gov charity complete</span><span class="text-[13px] opacity-60">${
        govChar.grants.length
      } generated, ${formatNumber(govTotal)}</span>`
    );
    govChar.isGov = true;
    console.log(`${govGrants} Implied Government Grants Generated`);
    console.log(`Gov Total: ${formatNumber(govTotal)}`);
    this.GOV_NODE = govChar;
    GOV_NODE = govChar;
    return govChar;
  }

  /**
   * NGOs throw money around between each other. Sometimes that's money laundering, sometimes its
   * just how universiies work. But that would confuse the sankey.
   * So we have to scan for circular grants, which we move to the side.
   * Again, a model function.
   * @returns
   */
  async findCircularGrants() {
    const visited = new Set();
    const onStack = new Set();
    const cycleGrants = new Set();
    let badTotal = 0;
    let charitiesWithBadGrants = 0;
    let obviousCirclesCount = 0;
    const charitiesTotal = Object.values(Charity.charityLookup).length;
    let charitiesProcessed = 0;

    updateStatus(
      "<span>Marking circular grants</span><span class='text-[13px] opacity-60'>(A->B->A)</span>"
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let charity of Object.values(Charity.charityLookup)) {
      const obviousCircles = charity.simpleCircular();
      obviousCirclesCount += obviousCircles.length;
      if (obviousCircles.length) charitiesWithBadGrants++;
      if (!(charitiesProcessed++ % CHUNK_SIZE)) {
        updateStatus(
          `${Math.round(
            (charitiesProcessed / charitiesTotal) * 100
          )}% charities scanned`
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
      obviousCircles.forEach((grant) => {
        grant.isCircular = true;
        cycleGrants.add(grant);
        Charity.circularGrant(grant);
      });
    }
    console.log(`${obviousCirclesCount} obvious circular grants found`);
    updateStatus(`${obviousCirclesCount} obvious circular grants found`);

    updateStatus(
      "<span>Finding deeper loopback grants</span><span class='text-[13px] opacity-60'>(A->B->C->A)</span>"
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    const totalGrants = Object.values(Charity.charityLookup).reduce(
      (sum, c) => sum + c.grants.length,
      0
    );
    let processedGrants = 0;

    for (const [startId, startCharity] of Object.entries(
      Charity.charityLookup
    )) {
      if (visited.has(startId)) continue;
      let stack = [{ charity: startCharity, grantIndex: 0 }];
      while (stack.length > 0) {
        let grantCounter = 0;
        while (stack.length > 0 && grantCounter < CHUNK_SIZE) {
          const top = stack.pop();
          const { charity, grantIndex } = top;
          const grants = charity.grants || [];
          if (grantIndex < grants.length) {
            const grant = grants[grantIndex];
            const granteeId = grant.grantee.id;
            top.grantIndex++;
            stack.push(top);
            if (onStack.has(granteeId)) {
              cycleGrants.add(grant);
              grant.isCircular = true;
              Charity.circularGrant(grant);
            } else if (!visited.has(granteeId)) {
              visited.add(granteeId);
              onStack.add(granteeId);
              stack.push({ charity: grant.grantee, grantIndex: 0 });
            }
          } else {
            onStack.delete(charity.id);
          }
          grantCounter++;
          processedGrants++;
        }
        if (stack.length > 0) {
          updateStatus(
            `<span>Circular processing</span><span class="text-[13px] opacity-60">${Math.round(
              (processedGrants / totalGrants) * 100
            )}% complete</span>`
          );
          await new Promise((resolve) => setTimeout(resolve, 0));
        }
      }
    }

    Object.values(Charity.charityLookup).forEach((charity) => {
      let hasBadGrants = false;
      charity.grants.forEach((grant) => {
        if (cycleGrants.has(grant)) {
          hasBadGrants = true;
          badTotal += grant.amt;
        }
      });
      if (hasBadGrants) charitiesWithBadGrants++;
    });

    updateStatus(
      `<span>$${formatNumber(
        badTotal
      )} of loopbacks removed</span><span class="text-[13px] opacity-60">${
        cycleGrants.size
      } in ${charitiesWithBadGrants} charities</span>`
    );
    console.log(`${charitiesWithBadGrants} charities had circular grants`);
    console.log(`${cycleGrants.size} circular grants`);
    Object.values(Charity.charityLookup).forEach((c) => c.organize());

    return cycleGrants;
  }

  /**
   *  A Charity that doesn't have any incoming grants I term a root, with the US Govt being
   * the largest. But it seemed intresting to use them as a starting point. This returns
   * all roots, which can then be sliced.
   * @returns
   */
  getRootCharities() {
    return Object.values(Charity.charityLookup)
      .filter((c) => c.isRoot && !c.govt_amt && !c.isTerminal)
      .filter((c) => !this.shouldHide(c.id))
      .sort((a, b) => b.grantsTotal - a.grantsTotal);
  }

  /**
   * Clicking on a node toggles its visibility.
   * If it's one of the ones we've specifically chosen to be visible, its
   * now just a regular node. If it was implied (we know its  visible if it was
   * clicked on) its now desired, which has implications for the implied propogation
   * as it will step 1 node farther down the graph.
   */
  clickNode(event, charity, refreshCallback) {
    console.log(`Clicked node ${charity.id} ${charity.name}`);
    charity.desiredVisible = !charity.desiredVisible; // Toggle user-driven input
    this.computeImpliedVisibility(charity, true, true); // Compute connected visibility
    this.buildSankeyData(); // Update the graph data
    if (refreshCallback) refreshCallback(); // Always refresh
  }
  /**
   *  Doubleclicking being the "expand/open" gesture means in this
   * case that we force desiredVisible to true, and add more visible grants.
   * Shift double-click is constract, we force desiredToFalse and remove visible grants
   * @param {*} event
   * @param {*} charity
   */
  doubleClickNode(event, charity) {
    if (event.shiftKey) {
      charity.desiredVisible = false;
      charity.compressOutflows(NEXT_REVEAL);
      charity.compressInflows(NEXT_REVEAL);
      console.log(`Compressing ${charity.id} ${charity.name}`);
    } else {
      desiredVisible = true;
      charity.expandOutflows(NEXT_REVEAL);
      charity.expandInflows(NEXT_REVEAL);
      console.log(`Expanding ${charity.id} ${charity.name}`);
    }
    this.computeImpliedVisibility(charity, true, true);
  }

  /**
   * Clicking a grant toggles desired visibility. Which is mostly about
   * affecting implied indirectly.
   * @param {*} event
   * @param {*} grant
   */
  clickGrant(event, grant) {
    grant.desiredVisible = !grant.desiredVisible;
    /*TODO Think about what we should do to grant.filer and grant.grantee  */
    console.log(
      `${grant.desiredVisible ? "Showing" : "Hiding"} grant ${grant.id}`
    );
    this.computeImpliedVisibility(grant.filer, true, false);
    this.computeImpliedVisibility(grant.grantee, false, true);
  }

  /** Double clicking a grant forces both ends of the grang */
  doubleClickGrant(event, grant) {
    if (event.shiftKey) {
      grant.filer.desiredVisible = false;
      grant.grantee.desiredVisible = false;
      console.log(`Hiding nodes for grant ${grant.id}`);
    } else {
      grant.filer.desiredVisible = true;
      grant.grantee.desiredVisible = true;
      grant.desiredVisible = true;
      console.log(`Showing nodes and grant ${grant.id}`);
    }
    this.computeImpliedVisibility(grant.filer, true, false);
    this.computeImpliedVisibility(grant.grantee, false, true);
  }

  /**
   * Because its natural to want to expand just one direction visually we draw
   * these little hats on either side of a node, clicking on the upstream hat
   * expands that way, clicking on the downstream that way.
   */
  handleUpClick(event, charity, refreshCallback) {
    console.log(`Expanding inflows for ${charity.id} ${charity.name}`);
    charity.desiredVisible = true;
    charity.expandInflows(NEXT_REVEAL);
    this.computeImpliedVisibility(charity, true, false);
    this.buildSankeyData();
    if (refreshCallback) refreshCallback();
  }

  handleDownClick(event, charity, refreshCallback) {
    console.log(`Expanding outflows for ${charity.id} ${charity.name}`);
    charity.desiredVisible = true;
    charity.expandOutflows(NEXT_REVEAL);
    this.computeImpliedVisibility(charity, false, true);
    this.buildSankeyData();
    if (refreshCallback) refreshCallback();
  }

  /**
   * Workhorse method for doing all the complicated visiblity shit.
   * If rootCharity is null, we're going to reset everything, start with the
   * desired nodes, then propogate one step from there.
   * If rootCharity is set, we're doing an incremental prop, just need to do
   * one step.
   * @param {*} rootCharity Starting point, or null for all desiredVisible nodes
   * @param {*} inflowsOnly Only go left
   * @param {*} outflowsOnly Only go right
   */
  computeImpliedVisibility(
    rootCharity = null,
    inflowsOnly = false,
    outflowsOnly = false
  ) {
    /** DEAD CODE This was resetting everything. I don't think
     * its necessary, except when rootCharity is null
     * Object.values(Charity.charityLookup).forEach((c) => {
      c.impliedVisible = c.desiredVisible;
    });
    Object.values(Grant.grantLookup).forEach((g) => {
      g.impliedVisible = g.desiredVisible;
    });
    */
    /**
     * Ok, so two cases: rootCharity is null, loop over desiredCharities and prop
     * the implied up and down based on existing state. i.e. if no grants are
     * visibile, make START_REVEAL visible, if some are, make NEXT_REVEAL visible.
     *
     * If root charity is not null, as above, but for one charity.
     *
     * I should refactor this to break out ops.
     * Have to go review the existing operations on Charities though.
     */

    if (rootCharity) {
      // incremental case
      if (inflowsOnly) {
        for (const grant of rootCharity.invisibleGrantsIn.slice(
          0,
          NEXT_REVEAL
        )) {
          if (!this.shouldHide(grant.filer.ein)) {
            grant.filer.impliedVisible++;
            grant.impliedVisible = true;
            console.log(`  Inflow filer ${grant.filer.ein} set visible`);
          }
        }
      }

      if (outflowsOnly) {
        for (const grant of rootCharity.invisibleGrants.slice(0, NEXT_REVEAL)) {
          if (!this.shouldHide(grant.grantee.ein)) {
            grant.grantee.impliedVisible++;
            grant.impliedVisible = true;
            console.log(`  Outflow grantee ${grant.grantee.ein} set visible`);
          }
        }
      }
    } else {
      // brute force whole data model case
      const seeds = Charity.desiredCharities; //handy accessor
      for (const charity of seeds) {
        for (const grant of charity.looseVisibleGrants) {
          if (
            (grant.desiredVisible || charity.desiredVisible) &&
            !this.shouldHide(grant.grantee.ein)
          ) {
            grant.grantee.impliedVisible++;
            grant.impliedVisible = true;
            if (!grant.grantee.isGov || grant.grantee.desiredVisible) {
              console.log(`  Outflow grantee ${grant.grantee.ein} set visible`);
            }
          }
        }
        for (const grant of charity.looseVisibleGrantsIn) {
          if (
            (grant.desiredVisible || charity.desiredVisible) &&
            !this.shouldHide(grant.filer.ein)
          ) {
            grant.filer.impliedVisible++;
            grant.impliedVisible = true;
            if (!grant.filer.isGov || grant.filer.desiredVisible) {
              console.log(`  Inflow filer ${grant.filer.ein} set visible`);
            }
          }
        }
      }
    }
  }

  /**
   * Make sure the sankey data is clean
   */
  buildCleanSankeyData(maxallowed = MAX_NODES) {
    function filterHiddenGrant(grant) {
      if (viewModel.shouldHide(grant.filer.ein)) return true;
      if (viewModel.shouldHide(grant.grantee.ein)) return true;
      return false;
    }
    let maxSeeds = maxallowed;
    this.renderData.links = Grant.visibleGrants.filter(
      (g) => !filterHiddenGrant(g)
    );
    this.renderData.nodes = Charity.visibleCharities.filter(
      (node) => !this.shouldHide(node.ein)
    );
    const nodeSet = new Set();
    const missingSet = new Set();
    this.renderData.nodes.forEach((node) => nodeSet.add(node.ein));
    this.renderData.links.forEach((grant) => {
      if (!nodeSet.has(grant.filer.ein)) missingSet.add(grant.filer.ein);
      if (!nodeSet.has(grant.grantee.ein)) missingSet.add(grant.grantee.ein);
    });
    // add missing nodes
    for (const ein of missingSet) {
      console.log(`bCSD: adding missing node ${ein}`);
      this.renderData.nodes.push(Charity.getCharity(ein));
    }
  }

  /**
   * Build the data we need for the Sankey. The model is close enough to what it needs that we
   * can draw direclty from the data, though we do have to undo the fact that the sankey code
   * replaces source as EIN with source as object.
   * @returns
   */
  buildSankeyData() {
    let maxSeeds = MAX_NODES;
    this.renderData = { nodes: [], links: [] };
    //this.computeImpliedVisibility();
    this.buildCleanSankeyData(maxSeeds);
    /*while (this.renderData.nodes.length > MAX_NODES && maxSeeds > 5) {
      updateStatus(`Too Many Nodes, reducing to ${maxSeeds} seeds`);
      Charity.visibleCharities // reverse sort so largest flows larger get kept
        .sort(
          (a, b) =>
            b.grantsTotal + b.grantsInTotal - (a.grantsTotal + b.grantsInTotal)
        )
        .slice(maxSeeds)
        .forEach((c) => c.clearVisibility());
      this.computeImpliedVisibility(null, true, true);
      this.renderData.nodes = Charity.visibleCharities;
      this.renderData.links = Grant.visibleGrants;
      this.buildCleanSankeyData(maxSeeds);
      maxSeeds /= 2; // try with half as much next time.
    }*/
    console.log(
      `Sankey Data - Nodes: ${this.renderData.nodes.length}, Links: ${this.renderData.links.length}`
    );
    return this.renderData;
  }

  /**
   *  Loads our datafile, builds the model esentially.
   * Also builds the virtual NGO for the USG, and
   * prunes the circular grants.
   * @returns
   */
  async loadData() {
    updateStatus("Loading data...");
    this.dataReady = false;
    const charitiesZipBuf = await fetch("../expose/charities.csv.zip").then(
      (r) => r.arrayBuffer()
    );
    const charitiesZip = await JSZip.loadAsync(charitiesZipBuf);
    const charitiesCsvString = await charitiesZip
      .file("charities_truncated.csv")
      .async("string");

    await new Promise((resolve, reject) => {
      updateStatus("Parsing charities");
      Papa.parse(charitiesCsvString, {
        header: true,
        skipEmptyLines: true,
        complete: (results) => {
          let counter = 0;
          results.data.forEach((row) => {
            Charity.buildCharityFromRow(row);
            counter++;
            if (!(counter % CHUNK_SIZE))
              updateStatus(`Building NGO List ${counter}`);
          });
          resolve();
        },
        error: (err) => reject(err),
      });
    });

    await this.buildGovCharity();
    const grantsZipBuf = await fetch("../expose/grants.csv.zip").then((r) =>
      r.arrayBuffer()
    );
    const grantsZip = await JSZip.loadAsync(grantsZipBuf);
    const grantsCsvString = await grantsZip
      .file("grants_truncated.csv")
      .async("string");
    let totalGrantsCount = 0;
    let totalGrantsRows = 0;

    await new Promise((resolve, reject) => {
      updateStatus("Parsing grants");
      Papa.parse(grantsCsvString, {
        header: true,
        skipEmptyLines: true,
        complete: (results) => {
          results.data.forEach((row) => {
            totalGrantsRows++;
            if (Grant.loadGrantRow(row)) totalGrantsCount++;
            if (!(totalGrantsRows % CHUNK_SIZE))
              updateStatus(`Building Grant List ${totalGrantsCount}`);
          });
          resolve();
        },
        error: (err) => reject(err),
      });
    });

    updateStatus("Marking loopbacks");
    await this.findCircularGrants();
    console.log(`Total Grants Rows ${totalGrantsRows}`);
    console.log(`Total Grants Loaded ${totalGrantsCount}`);
    console.log(`Grants Net ${Object.keys(Grant.grantLookup).length}`);
    updateStatus("USG & NGOs & grants loaded", "black", false);
    this.dataReady = true;
    return { totalGrantsCount };
  }

  /**
   * So I had to pick smothign ast the starting point, so I place the 5 largest root notes.
   */
  loadDefaultData() {
    const usGov = this.GOV_NODE;
    updateStatus("placing US Government");
    usGov.desiredVisible = true;
    usGov.expandOutflows(TOP_N_INITIAL);
    updateStatus(
      `USG placed adding top ${TOP_N_INITIAL} roots`,
      "green",
      false
    );
    this.getRootCharities()
      .slice(1, TOP_N_INITIAL) // skip USG, already placed.
      .forEach((c) => {
        c.desiredVisible = true;
        c.expandOutflows(START_REVEAL);
      });
    this.computeImpliedVisibility(null, true, true);
  }

  /** So the sankey was messing with the data, so we have to reset the link data post
   * render.
   */
  cleanAfterRender() {
    if (this.renderData && this.renderData.links) {
      this.renderData.links.forEach((link) => link.resetSourceTarget());
    }
  }
}

/**
 * Class to hold an NGO.
 */
class Charity {
  /** charities are stored in an object by EIN for quick lookup */
  static charityLookup = {};

  /** Basic methods for puting charites into and out of the lookup */
  static getCharity(ein) {
    const parts = ein.split(":");
    return Charity.charityLookup[parts[0]];
  }

  static registerCharity(ein, c) {
    Charity.charityLookup[ein] = c;
  }

  /** accessors are convenient */
  static get visibleCharities() {
    return Object.values(Charity.charityLookup).filter((c) => c.isVisible);
  }

  static get invisibleCharities() {
    return Object.values(Charity.charityLookup).filter((c) => !c.isVisible);
  }

  static get impliedCharities() {
    return Object.values(Charity.charityLookup).filter(
      (c) => c.impliedVisible > 0
    );
  }

  static get desiredCharities() {
    return Object.values(Charity.charityLookup).filter((c) => c.desiredVisible);
  }

  static get getCharityCount() {
    return Object.keys(Charity.charityLookup).length;
  }

  /**
   * Clear all caches
   */
  static disorganzeAll() {
    Object.values(Charity.charityLookup).forEach(
      (c) => (c.isOrganized = false)
    );
  }

  /**
   * Factory for building one from a data file row.
   * @param {} row
   * @returns
   */
  static buildCharityFromRow(row) {
    const ein = (row["filer_ein"] || "").trim();
    if (!ein) return;
    let rAmt = parseInt((row["receipt_amt"] || "0").trim(), 10);
    if (isNaN(rAmt)) rAmt = 0;
    return new Charity({
      ein,
      name: (row["filer_name"] || "").trim(),
      xml_name: row["xml_name"],
      receipt_amt: rAmt,
      govt_amt: parseInt((row["govt_amt"] || "0").trim(), 10) || 0,
      contrib_amt: parseInt((row["contrib_amt"] || "0").trim(), 10) || 0,
    });
  }

  /** It is what it is. */
  constructor({
    ein,
    name,
    xml_name,
    govt_amt = 0,
    contrib_amt = 0,
    receipt_amt = 0,
    grants = [],
    grantsIn = [],
    loopbackgrants = [],
    loopforwardgrants = [],
    desiredVisible = false,
    isOrganized = false,
  }) {
    this.id = ein; // these 3 are interchangeable
    this.ein = ein;
    this.filer_ein = ein;
    this.name = name;
    this.xml_name = xml_name;
    this.receipt_amt = receipt_amt;
    this.govt_amt = govt_amt;
    this.contrib_amt = contrib_amt;
    this.grants = grants;
    this.grantsIn = grantsIn;
    this.loopbackgrants = loopbackgrants;
    this.loopforwardgrants = loopforwardgrants;
    this._desiredVisible = desiredVisible;
    this._impliedVisible = 0;
    this.isOrganized = isOrganized;
    this.isGov = false;
    this.expanded = false;
    this._valueCache = {};
    this.sourceLinks = [];
    this.targetLinks = [];
    Charity.registerCharity(ein, this);
  }

  /**
   * Note the OR here, a node is visible if its impliedVisible by a desired node
   * or if it itself is desired.
   */
  get isVisible() {
    return this.impliedVisible > 0 || this.desiredVisible;
  }

  /**
   * We use this when we're trying to pare down a graph
   */

  clearVisibility() {
    this.desiredVisible = false;
    this.impliedVisible = 0;
    this.grantsIn.forEach((g) => {
      g.impliedVisible = false;
      g.desiredVisible = false;
    });
    this.grants.forEach((g) => {
      g.impliedVisible = false;
      g.desiredVisible = false;
    });
  }

  get desiredVisible() {
    return this._desiredVisible;
  }

  set desiredVisible(value) {
    if (this._desiredVisible !== value) {
      this._desiredVisible = value;
      this.isOrganized = false;
    }
  }

  get impliedVisible() {
    //if (!this.isOrganized) this.organize(); not necessary
    return this._impliedVisible;
  }

  set impliedVisible(value) {
    if (this._impliedVisible != value) {
      this._impliedVisible = value;
      this.isOrganized = false;
      if (!value) {
        if (this.filer) {
          this.filer.impliedVisible--;
        }
        if (this.grantee) {
          this.grantee.impliedVisible--;
        }
      } else {
        if (this.filer) {
          this.filer.impliedVisible++;
        }
        if (this.grantee) {
          this.grantee.impliedVisible++;
        }
      }
      // Propagate organization state changes to connected charities
      if (this.filer) this.filer.isOrganized = false;
      if (this.grantee) this.grantee.isOrganized = false;
    }
  }

  /**
   * Canonically EIN form
   */
  get longEIN() {
    const matches = this.ein.match(/(\d\d)-*(\d\d\d\d\d\d)/);
    return matches ? `${matches[0]}${matches[1]}` : this.ein;
  }

  /** can only grow to the left if there are grants to show */
  get canExpandInflows() {
    return this.invisibleGrantsIn.length > 0;
  }

  /** can only grow to the right if there are grants to show */
  get canExpandOutflows() {
    return this.invisibleGrants.length > 0;
  }

  /** can only suck grants back in if there are grants to suck back in */
  get canCompressInflows() {
    return this.visibleGrantsIn.length > 0;
  }

  /** can only suck grants back in if there are grants to suck back in */
  get canCompressOutflows() {
    return this.visibleGrants.length > 0;
  }

  /** an NGO that doesn't make any grants of its own is terminal, either because
   * they've sucked up the money into "adminstraiton" or because they just buy stuff
   * on their own, which we have no way of seeing.
   */
  get isTerminal() {
    return this.grants.length === 0;
  }
  /**
   * An NGO that doesn't get money from the GOVT or another charity is a root.
   */
  get isRoot() {
    return this.grantsIn.length === 0;
  }

  /**
   * Ok, a whole bunch of caching accessors on the various kinds of relation ships and
   * the summed values they have. The only thing tricky is that
   * scaled values are stored with the POWER_LAW they were calculated under
   * so that if the POWER_LAW changes, the values will be automatically
   * updated. Also stored based on the number of visible grants for a similar reason.
   */
  get logGrantsTotal() {
    const cacheKey = `logGrantTotal-${viewModel.POWER_LAW}-${this.grants.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = scaleValue(this.grantsTotal));
  }

  get logGrantsInTotal() {
    const cacheKey = `logGrantsInTotal-${viewModel.POWER_LAW}-${this.grantsIn.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = scaleValue(this.grantsInTotal));
  }

  get grantsLogTotal() {
    const vgrants = this.visibleGrants; // use all grants for scaling now
    const cacheKey = `grantsLogTotal-${viewModel.POWER_LAW}-${vgrants.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    if (vgrants.length)
      return (this._valueCache[cacheKey] = vgrants.reduce(
        (total, g) => total + g.value,
        0
      ));
    return 0;
  }

  get grantsInLogTotal() {
    const vgrants = this.visibleGrantsIn; // use all grants for scaling
    const cacheKey = `grantsInLogTotal-${viewModel.POWER_LAW}-${vgrants.length}`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    if (vgrants.length)
      return (this._valueCache[cacheKey] = vgrants.reduce(
        (total, g) => total + g.value,
        0
      ));
    return 0;
  }

  get grantsTotal() {
    const cacheKey = `grantsTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get grantsInTotal() {
    const cacheKey = `grantsInTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get visibleGrantsTotal() {
    const cacheKey = `visibleGrantsTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.visibleGrants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get visibleGrantsInTotal() {
    const cacheKey = `visibleGrantsInTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.visibleGrantsIn.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get invisibleGrantsTotal() {
    const cacheKey = `invisibleGrantsTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.invisibleGrants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get loopbackTotal() {
    const cacheKey = `loopbackTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.loopbackgrants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  get loopForwardTotal() {
    const cacheKey = `loopforwardTotal`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.loopforwardgrants.reduce(
      (total, g) => total + g.amt,
      0
    ));
  }

  /**
   * A grant can only consider itself visible if both its nodes are
   * visible.
   */

  /**
   * Grants only consider themselves visible if both ends are visible, but
   * when propogating visibility, we just need to know if the grants
   * would like to be visible.
   */
  get looseVisibleGrants() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `looseVisibleGrants`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.filter(
      (g) => g.isLooseVisible
    ));
  }

  get looseVisibleGrantsIn() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `looseVisibleGrantsIn`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.filter(
      (g) => g.isLooseVisible
    ));
  }

  get visibleGrants() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `visibleGrants`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.filter(
      (g) => g.isVisible
    ));
  }

  get invisibleGrants() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `invisibleGrants`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grants.filter(
      (g) => !g.isVisible
    ));
  }

  get visibleGrantsIn() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `visibleGrantsIn`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.filter(
      (g) => g.isVisible
    ));
  }

  get invisibleGrantsIn() {
    if (!this.isOrganized) this.organize();
    const cacheKey = `invisibleGrantsIn`;
    if (this._valueCache[cacheKey]) return this._valueCache[cacheKey];
    return (this._valueCache[cacheKey] = this.grantsIn.filter(
      (g) => !g.isVisible
    ));
  }

  get hasVisibleGrants() {
    return this.visibleGrants.length > 0;
  }

  /** accessor to trash the cache */
  set isOrganized(value) {
    if (this._isOrganized !== value) {
      this._valueCache = {};
      this._isOrganized = value;
    }
  }

  /**
   * Accessors for maingining the root lists, and managing the cache
   */
  addGrant(grant) {
    if (grant instanceof Grant) {
      this.grants.push(grant);
      this.isOrganized = false;
    } else {
      console.log("Error: Can only add Grant objects.");
    }
  }

  addGrantIn(grant) {
    if (grant instanceof Grant) {
      this.grantsIn.push(grant);
      this.isOrganized = false;
    } else {
      console.log("Error: Can only add Grant objects.");
    }
  }

  static addGrant(g) {
    const filer = Charity.charityLookup[g.filer_ein];
    const grantee = Charity.charityLookup[g.grantee_ein];
    if (filer && grantee) {
      filer.addGrant(g);
      grantee.addGrantIn(g);
    }
  }

  removeGrant(grant) {
    const index = this.grants.indexOf(grant);
    if (index !== -1) {
      this.grants.splice(index, 1);
      this.isOrganized = false;
      this._origOut += grant.amt;
    }
  }

  removeGrantIn(grant) {
    const index = this.grantsIn.indexOf(grant);
    if (index !== -1) {
      this.grantsIn.splice(index, 1);
      this.isOrganized = false;
      this._origIn += grant.amt;
    }
  }

  /** Part of organizing is keeping the grants sorted */
  organize() {
    if (!this.isOrganized) {
      this.grants.sort((a, b) => b.amt - a.amt);
      this.grantsIn.sort((a, b) => b.amt - a.amt);
      this.isOrganized = true;
    }
  }

  /** Mark a grant circular have to tell both sides*/
  static circularGrant(g) {
    g.grantee.circleGrant(g);
    g.filer.circleGrant(g);
    Grant.unregisterGrant(g);
  }

  /** we've been told, have to move the grant to the
   * siding
   */
  circleGrant(g) {
    if (g.filer === this) {
      this.loopbackgrants.push(g);
      this.removeGrant(g);
    }
    if (g.grantee === this) {
      this.loopforwardgrants.push(g);
      this.removeGrantIn(g);
    }
    this.isOrganized = false;
  }

  /** nice when debugging */
  get grantsTotalString() {
    return formatNumber(this.grantsTotal);
  }

  get invisibleTotalString() {
    return formatNumber(this.invisibleGrantsTotal);
  }

  /**
   * A-B-A is a simple circle which we can handle in a filter
   * Might as well.
   */
  simpleCircular() {
    return this.grants.filter((g1) =>
      g1.grantee.grants.some((g2) => g2.grantee_ein === this.ein)
    );
  }

  /** This may be DEAD CODE now */
  handleClick(e, count = -1) {
    if (e.altKey) return this.tunnelNode(e);
    if (e.metaKey || this.isTerminal) {
      console.log(`Hiding ${this.id} ${this.name}`);
      this.hide();
      return false;
    }
    console.log(`Expanding ${this.id} ${this.name}`);
    this.expandDown(NEXT_REVEAL);
    this.expandUp(NEXT_REVEAL);
    return true;
  }

  /** This should be DEAD CODE now */
  handleGrantClick(e, g) {
    g.filer.handleClick(e, -1);
    g.grantee.handleClick(e, -1);
  }

  /**
   * Swim upstream, making grants visible
   * @param {*} count
   */
  expandInflows(count = NEXT_REVEAL) {
    if (!count || count == "0") return;
    const grantsToReveal = this.invisibleGrantsIn.slice(0, count); // count largest
    grantsToReveal.forEach((grant) => {
      grant.impliedVisible = true; // propogates both directions
    });
    viewModel.resetEIN(this.ein);

    this.isOrganized = false;
  }

  /** make some of the upstream grands invisible */
  // do we need a reference count instead of a simple flag?
  compressInflows(count = NEXT_REVEAL) {
    /*const grantsToHide = this.visibleGrantsIn.slice(-count); // count smallest
    grantsToHide.forEach((grant) => {
      grant.clearVisibility();
    });
    viewModel.resetEIN(this.ein);

    this.isOrganized = false;*/
    let newCount = this.visibleGrantsIn.length - count;
    if (newCount < 0) newCount = 0;
    viewModel.addToShowList(
      `${this.ein}:${newCount}:${this.visibleGrants.length}}`
    ); // match URL will do this for us.
  }

  /**
   * Expand downwards
   * @param {*} count
   */
  expandOutflows(count = NEXT_REVEAL) {
    if (!count || count == "0") return;
    const grantsToReveal = this.invisibleGrants.slice(0, count);
    console.log(
      `Expanding ${grantsToReveal.length} outflows for ${this.id} (total invisible: ${this.invisibleGrants.length})`
    );
    grantsToReveal.forEach((grant) => {
      grant.impliedVisible = true;
      console.log(
        `  Grant ${grant.id} set visible, grantee ${grant.grantee.id} set visible`
      );
    });
    viewModel.resetEIN(this.ein);
    this.isOrganized = false;
  }

  compressOutflows(count = NEXT_REVEAL) {
    /*const grantsToHide = this.visibleGrants.slice(-count);
    grantsToHide.forEach((grant) => {
      grant.clearVisibility();
    });
    this.isOrganized = false;*/
    let newCount = this.visibleGrants.length - count;
    if (newCount < 0) newCount = 0;
    viewModel.addToShowList(
      `${this.ein}:${this.visibleGrantsIn.length}:${newCount}`
    ); // match URL will do this for us.
  }

  /**
   * These manipulate the Hide and HostLists too
   */

  show() {
    this.desiredVisible = true;
    viewModel.removeFromHideList(this.id);
    viewModel.addToBreadCrumbs(`Show|${this.id}`);
  }

  hide() {
    viewModel.addToBreadCrumbs(`Hide|${this.id}`);
    viewModel.addToHideList(this.id);
    this.desiredVisible = false;
    this.grantsIn.forEach((g) => this.clearVisibility());
    this.grants.forEach((g) => this.clearVisibility());
  }

  /**
   *
   * @returns EIN:numberIncoming:numberOutgoing
   */
  URLPiece() {
    if (!this.desiredVisible) return null;
    return `${this.ein}:${this.visibleGrantsIn.length}:${this.visibleGrants.length}`;
  }

  /**
   * DO these search terms match?
   * @param {*} keywords
   * @returns
   */
  searchMatch(keywords) {
    const lowerStr = this.name.toLowerCase();
    return keywords
      .map((kw) => kw.trim().toLowerCase())
      .filter((kw) => kw !== "")
      .some((kw) => lowerStr.includes(kw));
  }

  /**
   *   So at one point I was thinking instead of constantly extending the graph
   * I'd provide a way that it would just jump to a new starting point.
   */
  tunnelNode() {
    const newParams = new URLSearchParams(); //empty
    newParams.add("ein", this.ein);
    viewModel.matchURL(newParams);
  }

  /**
   *  "placing a node" means making it desired, and making sure there
   * are the matching number of visible grants.
   * @param {*} upCount
   * @param {*} downCount
   */
  place(upCount = START_REVEAL, downCount = START_REVEAL) {
    this.desiredVisible = true;
    this.expandOutflows(downCount);
    this.expandInflows(upCount);
    this.organize();
    this.expanded = true;
    console.log(
      `Placed ${this.id}: ${this.visibleGrants.length} outflows visible, ${this.invisibleGrants.length} outflows invisible, ${this.visibleGrantsIn.length} inflows visible`
    );
  }

  /**
   * Technically a VM responsibility, but we just do it here.
   * @returns
   */
  toolTipText() {
    let outFlows = this.grantsTotal
      ? `\ngrants out: $${formatNumber(this.grantsTotal)}`
      : `\nout: N/A`;
    let inFlows = this.grantsInTotal
      ? `\ngrants in: $${formatNumber(this.grantsInTotal)}`
      : `\nin: N/A`;
    let loopbacks = this.loopbackTotal
      ? `\nLoop Backs: $${formatNumber(this.loopbackTotal)}`
      : "";
    if (this.loopForwardTotal)
      loopbacks += `\nLoop Forwards: $${formatNumber(this.loopForwardTotal)}`;
    return `${this.name}\n${this.ein}${inFlows}${outFlows}${loopbacks}`;
  }

  /** links to elsewhere in the site */
  officersLink() {
    return `/officers/?nonprofit_kw=${this.ein}`;
  }

  financialsLink() {
    return `/nonprofit/assets/?filter=${this.ein}`;
  }

  nonprofitsLink() {
    return `/nonprofit/?filter=${this.ein}`;
  }

  propublicaLink(message) {
    return `<a href="https://projects.propublica.org/nonprofits/organizations/${this.ein}/${this.xml_name}/full" target="_blank" rel="noopener noreferrer" class="whitespace-nowrap">${message}</a>`;
  }
  googleLink(message) {
    const params = new URLSearchParams();
    params.set("q", `${this.longEIN} ${this.name}`);
    return `<a href="https://google.com/search?${params.toString()}" target="_blank" rel="noopener noreferrer" class="whitespace-nowrap"}>${message}</a>`;
  }

  grokLink(message) {
    const params = new URLSearchParams();
    params.set(
      "q",
      `Tell me about ${this.name} who has EIN ${this.longEIN} are they legit?`
    );
    return `<a href="https://grok.com/search?${params.toString()}"} target="_blank" rel="noopener noreferrer" class="whitespace-nowrap">${message}</a>`;
  }
}

/**
 * The edge as opposed to a Charity node.
 * filer: from
 * grantee: to
 *
 * aliases for source and target for sankey
 */
class Grant {
  /** so we can find a grant quickly */
  static grantLookup = {};

  static getGrant(id) {
    return Grant.grantLookup[id];
  }

  static registerGrant(g) {
    Grant.grantLookup[g.id] = g;
  }

  static unregisterGrant(g) {
    delete Grant.grantLookup[g.id];
  }

  /**
   * 600,000 grants, only a few charities visible, have to be visible for
   * grant to show, so we work backwards from visible charities.
   */
  static get visibleGrants() {
    // work backwards from visible charities
    const visibleGrants = new Set();
    for (const c of Charity.visibleCharities) {
      for (const g of c.grants) if (g.isLooseVisible) visibleGrants.add(g.id);
      for (const g of c.grantsIn) if (g.isLooseVisible) visibleGrants.add(g.id);
    }
    let result = [];
    for (const id of visibleGrants) {
      const g = Grant.grantLookup[id];
      if (g) result.push(g);
      else console.log(`Couldn't find grant ${g} in visibleGrants`);
    }
    return result;
  }

  /** Commong pattern */
  static get allGrants() {
    return Object.values(Grant.grantLookup);
  }

  /** used when reading from the file */
  static checkGrantMatch(filer_ein, grantee_ein) {
    return (
      filer_ein !== grantee_ein &&
      Charity.getCharity(filer_ein) &&
      Charity.getCharity(grantee_ein)
    );
  }

  /** grants are unique by filer/grantee */
  static grantIDBuilder(filer_ein, grantee_ein) {
    return `${filer_ein}~${grantee_ein}`;
  }

  /** factory for the file read */
  static loadGrantRow(row) {
    const filer = (row["filer_ein"] || "").trim();
    const grantee = (row["grant_ein"] || "").trim();
    let amt = parseInt((row["grant_amt"] || "0").trim(), 10);
    if (isNaN(amt)) amt = 0;
    if (Grant.checkGrantMatch(filer, grantee)) {
      const id = Grant.grantIDBuilder(filer, grantee);
      const g = Grant.getGrant(id);
      if (g) {
        g.addAmt(amt);
        return g;
      } else {
        return new Grant({
          filer_ein: filer,
          grantee_ein: grantee,
          amt: amt,
        });
      }
    } else if (filer !== grantee) {
      console.warn(`Missing charity for EIN: ${filer} or ${grantee}`);
    }
    return null;
  }

  /** it is what it is */
  constructor({
    filer_ein,
    grantee_ein,
    amt = 0,
    isCircular = false,
    desiredVisible = false,
  }) {
    this.registered = false;
    this.amt = amt;
    this.filer_ein = filer_ein;
    this.grantee_ein = grantee_ein;
    this.filer = Charity.getCharity(filer_ein);
    this.grantee = Charity.getCharity(grantee_ein);
    this._desiredVisible = desiredVisible;
    this._impliedVisible = false;
    this._isCircular = isCircular;
    this.sourceLinks = [];
    this.targetLinks = [];
    this._source = null;
    this._target = null;
    Charity.addGrant(this);
    this.registered = true;
    this.buildId();
  }

  /** see Charity for the split visibility explanation */
  get isVisible() {
    return (
      this.isLooseVisible && this.filer.isVisible && this.grantee.isVisible
    );
  }

  /** see Charity for the split visibility explanation
   *
   * We need the loose visible when propagating to capture intent.
   */
  get isLooseVisible() {
    return this.desiredVisible || this.impliedVisible; // || this.isVisible;
  }

  /**
   * This is how the visibility propogates, goes one step to filer/grantee
   */
  set isVisible(value) {
    if (value) {
      if (this.filer) {
        this.filer.impliedVisible++;
      }
      if (this.grantee) {
        this.grantee.impliedVisible++;
      }
    } else {
      if (this.filer) {
        this.filer.impliedVisible--;
      }
      if (this.grantee) {
        this.grantee.impliedVisible--;
      }
    }
    // Propagate organization state changes to connected charities
    if (this.filer) this.filer.isOrganized = false;
    if (this.grantee) this.grantee.isOrganized = false;
  }

  /**
   * accessors
   * One nice thing about accessors is it makes it trivial to set breakpoints
   * when things change
   */
  get desiredVisible() {
    return this._desiredVisible;
  }

  set desiredVisible(value) {
    if (this._desiredVisible !== value) {
      this._desiredVisible = value;
      this.disorganize();
    }
  }

  get impliedVisible() {
    return this._impliedVisible;
  }

  set impliedVisible(value) {
    if (this._impliedVisible != value) {
      this._impliedVisible = value;
      if (!value) {
        if (this.filer) {
          this.filer.impliedVisible--;
        }
        if (this.grantee) {
          this.grantee.impliedVisible--;
        }
      } else {
        if (this.filer) {
          this.filer.impliedVisible++;
        }
        if (this.grantee) {
          this.grantee.impliedVisible++;
        }
      }
      // Propagate organization state changes to connected charities
      if (this.filer) this.filer.isOrganized = false;
      if (this.grantee) this.grantee.isOrganized = false;
    }
  }

  /** this is mostly informative, as the Charity class moves them to the loopbacks */
  get isCircular() {
    return this._isCircular;
  }

  set isCircular(value) {
    if (value !== this._isCircular && this.registered) {
      Charity.circularGrant(this);
    }
    this._isCircular = value;
  }

  /** accessors to match the sankey API */
  get source() {
    return this._source || this.filer_ein;
  }

  set source(s) {
    this._source = s;
  }

  get target() {
    return this._target || this.grantee_ein;
  }

  set target(t) {
    this._target = t;
  }

  /**
   * So we scale the amount so we can see both small and large grants.
   * However, one side effect of this is because sqrt(a+b) != sqrt(a) + sqrt(b)
   */
  get value() {
    return scaleValue(this.amt);
  }

  get scaledAmt() {
    return scaleValue(this.amt);
  }

  /** apsirational code to show what % of grants a particular grant represents */
  get relativeInAmount() {
    return this.amt / (this.filer.grantsTotal + 1);
  }

  get relativeAmount() {
    return this.amt / (this.grantee.grantsTotal + 1);
  }

  clearVisibility() {
    this.impliedVisible = false;
    this.desiredVisible = false;
    this.disorganize();
  }

  /** probably aspirational but if either is charity is hidden so are we */
  shouldHide() {
    return (
      viewModel.shouldHide(this.filer_ein) ||
      viewModel.shouldHide(this.grantee_ein)
    );
  }

  /** so the way the data load works, different grants betweeen the same two NGOs will
   * appear, so we have to aggregate.
   */
  addAmt(amt) {
    this.amt += amt;
  }

  /**
   * build the ID for this grant, and register it
   * @returns
   */
  buildId() {
    this.id = Grant.grantIDBuilder(this.filer_ein, this.grantee_ein);
    Grant.registerGrant(this);
    return this.id;
  }

  /** flow disorganization up to the filer and grantee */
  disorganize() {
    this.filer.isOrganized = false;
    this.grantee.isOrganized = false;
  }

  /**
   * sankey will read the ID, then map that to a Charity, and write it back.
   *
   * Which is ok, except when it fails matching on objects later.
   * Best to reset them back to IDs.
   */
  resetSourceTarget() {
    this._source = null;
    this.sourceLinks = [];
    this._target = null;
    this.targetLinks = [];
  }

  /** Convenience */
  toString() {
    return `${this.id} ${formatNumber(this.amt)} (${this.value})`;
  }

  /**
   * A version of tunneling for grants, show just the two nodes involved.
   */
  tunnelGrant() {
    Object.values(Charity.charityLookup).forEach(
      (c) => (c.desiredVisible = false)
    );
    Object.values(Grant.grantLookup).forEach((g) => (g.desiredVisible = false));
    this.desiredVisible = true;
    this.filer_ein.desiredVisible = true;
    this.grantee_ein.desiredVisible = true;
  }
}

/**
 * Utility function
 * @param {*} message
 * @param {*} color
 * @param {*} loading
 */
function updateStatus(message, color = "black", loading = true) {
  $("#status").html(`<span class="flex flex-col items-end text-sm">
    ${loading ? "" : ""}
    ${message}</span>`);
}

viewModel = new BrowseViewModel();

export { formatNumber, Charity, Grant, scaleValue, BrowseViewModel, viewModel };
