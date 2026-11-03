(function () {
	'use strict';

	// Comparison points. "n" = the SoS report nearest to where 2026 is now (Election Day: nearest in time of day),
	// "f" = that year's last early-vote report and full Election Day.
	const BASES = {
		'22n': { year: 2022, short: '2022 nearest', final: false },
		'22f': { year: 2022, short: '2022 final', final: true },
		'24n': { year: 2024, short: '2024 nearest', final: false },
		'24f': { year: 2024, short: '2024 final', final: true },
	};
	const ORDER = ['22n', '22f', '24n', '24f'];
	const MIX_KEY = '24f'; // method mix used by the "2024 mix" option
	const RURAL = (n) => n !== 'Clark' && n !== 'Washoe';
	const LABELED = ['Clark', 'Nye', 'Elko', 'Washoe', 'Lincoln', 'Humboldt', 'Lander', 'Eureka', 'White Pine', 'Pershing', 'Mineral', 'Esmeralda', 'Churchill'];

	// Shift in the county's D−R margin vs the baseline, in points, most Republican first. NC's palette, symmetric
	// bins: Nevada's shifts run much wider than North Carolina's.
	const ADV_BINS = [
		[20, '#7f1d18', 'R 20+'],
		[10, '#9e241e', 'R 10–20'],
		[5, '#c4312a', 'R 5–10'],
		[2.5, '#e8837a', 'R 2.5–5'],
		[1, '#f3b5ae', 'R 1–2.5'],
		[0, '#f9e0dd', 'R 0–1'],
		[-1, '#dfe7f9', 'D 0–1'],
		[-2.5, '#bccdf3', 'D 1–2.5'],
		[-5, '#98b2ec', 'D 2.5–5'],
		[-10, '#6d8fe2', 'D 5–10'],
		[-20, '#2456c9', 'D 10–20'],
		[-Infinity, '#183d94', 'D 20+'],
	];
	const NO_DATA_COLOR = '#EBECED';
	const OUT_COLOR = '#F7F7F8'; // counties outside the selected area

	let M = null;
	const S = { mail: true, ev: true, ed: false, mix: false, area: 'st', base: '22n', county: null, sort: 'shift', dir: 1 };
	const NAMES = { mail: 'Mail', ev: 'In person early', ed: 'Election Day' };

	const $ = (id) => document.getElementById(id);
	const sum = (a) => a.reduce((x, y) => x + y, 0);
	const add = (a, b) => a.map((v, i) => v + b[i]);
	const fmt = (n) => Math.round(n).toLocaleString('en-US');
	const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
	const pct1 = (n, d) => (d > 0 ? ((100 * n) / d).toFixed(1) + '%' : '–');
	const docLink = (id) => `<a href="https://www.nvsos.gov/home/showpublisheddocument/${id}" target="_blank" rel="noopener">SoS doc ${id}</a>`;

	/** A D−R margin in points as "D +3.4" / "R +2.1", colored by side. */
	function lean(m) {
		if (m == null || !isFinite(m)) return '–';
		if (Math.abs(m) < 0.05) return 'Even';
		const side = m < 0 ? 'rep' : 'dem';
		return `<span class="nv-${side}">${m < 0 ? 'R' : 'D'} +${Math.abs(m).toFixed(1)}</span>`;
	}
	/** A D−R ballot lead as "D +1,129". */
	function leadN(n) {
		if (Math.round(n) === 0) return 'Even';
		const side = n < 0 ? 'rep' : 'dem';
		return `<span class="nv-${side}">${n < 0 ? 'R' : 'D'} +${fmt(Math.abs(n))}</span>`;
	}
	function dateTxt(iso, time = true) {
		const d = new Date(iso);
		const s = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
		if (iso.endsWith('T23:59')) return s + ', end of day';
		if (!time) return s;
		return s + ', ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) + ' PT';
	}
	const shortDate = (iso) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

	// ---------------------------------------------------------------- data access
	function methods() {
		const m = [];
		if (S.mail) m.push('mail');
		if (S.ev) m.push('ev');
		if (S.ed) m.push('ed');
		return m.length ? m : ['mail', 'ev'];
	}
	const mixOn = (ms = methods()) => S.mix && ms.length === 2 && !ms.includes('ed');
	function methodName(ms = methods()) {
		if (ms.length === 3) return 'All ballots';
		if (ms.length === 2) return ms.includes('ed') ? ms.map((m) => NAMES[m]).join(' + ') : 'Mail + in person' + (mixOn(ms) ? ' at 2024 mix' : '');
		return { mail: 'Mail ballots', ev: 'In-person early votes', ed: 'Election Day votes' }[ms[0]];
	}
	/** Difference of two margins; null when either side has no ballots. */
	const diff = (a, b) => (a == null || b == null ? null : a - b);
	/** [D, R, Other] ballots for a county at key ('y26' or a baseline key) for the given methods. */
	function val(c, key, ms = methods()) {
		const o = key === 'y26' ? c.y26 : c.b[key];
		return ms.reduce((a, m) => add(a, o[m] || [0, 0, 0]), [0, 0, 0]);
	}
	/**
	 * Per-county [D, R, Other] for the list. With the 2024 mix on, each method's ballots are rescaled so mail and in
	 * person make up the same shares of the total as they did for these counties in 2024's final early vote; the
	 * total is unchanged and the margin becomes the 2024-weighted average of the mail and in-person margins.
	 */
	function rowsFor(list, key, ms) {
		const raw = list.map((c) => val(c, key, ms));
		if (!mixOn(ms)) return raw;
		const o = (c) => (key === 'y26' ? c.y26 : c.b[key]);
		const t = (k, m) => sum(list.map((c) => sum((k === MIX_KEY ? c.b[MIX_KEY] : o(c))[m] || [0])));
		const w = { ev: t(MIX_KEY, 'ev'), mail: t(MIX_KEY, 'mail') }, now = { ev: t(key, 'ev'), mail: t(key, 'mail') };
		const W = w.ev + w.mail, T = now.ev + now.mail;
		if (!w.ev || !w.mail || !now.ev || !now.mail) return raw;
		const f = { ev: (w.ev / W) * (T / now.ev), mail: (w.mail / W) * (T / now.mail) };
		return list.map((c) => ms.reduce((a, m) => add(a, (o(c)[m] || [0, 0, 0]).map((v) => v * f[m])), [0, 0, 0]));
	}
	function counties(f = () => true) {
		return M.counties.filter((c) => f(c.n));
	}
	/** Is county n in the selected area ('st' = statewide, else a key of M.areas). */
	const inArea = (n, a = S.area) => a === 'st' || M.areas[a].counties.includes(n);
	const areaName = (a = S.area) => (a === 'st' ? 'Statewide' : M.areas[a].name);
	const CD2 = (n) => inArea(n, 'cd2');

	/**
	 * Other = every voter not registered D or R. Each county's Other ballots are split by that county's D:R
	 * ratio; a county with no D or R ballots uses the area's ratio. Same heuristic as North Carolina's I split.
	 */
	function summarize(list, key, ms = methods()) {
		const rows = rowsFor(list, key, ms);
		const s = { D: 0, R: 0, O: 0, total: 0, oD: 0, oR: 0 };
		rows.forEach((a) => { s.D += a[0]; s.R += a[1]; s.O += a[2]; });
		s.total = s.D + s.R + s.O;
		const areaR = s.D + s.R > 0 ? s.R / (s.D + s.R) : 0.5;
		rows.forEach((a) => {
			const r = a[0] + a[1] > 0 ? a[1] / (a[0] + a[1]) : areaR;
			s.oR += a[2] * r;
			s.oD += a[2] * (1 - r);
		});
		s.adjD = s.D + s.oD;
		s.adjR = s.R + s.oR;
		return s;
	}
	const margin = (s) => (s.total > 0 ? (100 * (s.D - s.R)) / s.total : null);
	const adjMargin = (s) => (s.total > 0 ? (100 * (s.adjD - s.adjR)) / s.total : null);
	const gapPts = (a) => (sum(a) ? (100 * (a[0] - a[1])) / sum(a) : null);

	function binColor(shift) {
		if (shift == null || !isFinite(shift)) return NO_DATA_COLOR;
		const r = -shift;
		for (const b of ADV_BINS) if (r > b[0] || (b[0] === 0 && r === 0)) return b[1];
		return ADV_BINS[ADV_BINS.length - 1][1];
	}

	// ---------------------------------------------------------------- caveats
	function point(key, m) {
		return M.base[key][m];
	}
	function mixShare() {
		const t = (m) => sum(M.counties.map((c) => sum(c.b[MIX_KEY][m] || [0])));
		const e = t('ev'), m = t('mail');
		return `${Math.round((100 * e) / (e + m))}% in person, ${Math.round((100 * m) / (e + m))}% mail`;
	}
	function warnings() {
		const out = [];
		const b = BASES[S.base], ms = methods();
		if (ms.includes('ev') && M.cur.ev.in_progress) {
			out.push(`Day ${M.cur.ev.ev_day} of 2026 early voting is still being counted.` + (S.base === '24n' ? ' 2024’s figure is the full day.' : ''));
		}
		if (ms.includes('ed')) {
			const p = point(S.base, 'ed'), now = sum(M.counties.filter((c) => inArea(c.n)).map((c) => sum(c.y26.ed)));
			if (!now) out.push('No 2026 Election Day votes have been reported yet. Polls open at 7 AM PT.');
			else if (M.cur.ed.in_progress) out.push(`2026 Election Day is still being counted (as of ${dateTxt(M.cur.ed.as_of)}). ${b.short}’s Election Day figure is ${p.as_of.endsWith('T19:00') ? 'the full day' : 'from ' + dateTxt(p.as_of)}, so compare shares, not raw totals.`);
			if (b.year === 2022) out.push('2022 Election Day is the final count; the Secretary of State published no intraday Election Day turnout that year. Its party breakdown leaves out counted provisional ballots.');
		}
		if (!b.final) {
			ms.filter((m) => m !== 'ed').forEach((m) => {
				const d = point(S.base, m).days_out - M.cur[m].days_out;
				if (d !== 0) out.push(`The nearest ${b.year} ${m === 'ev' ? 'in-person' : 'mail'} report is ${Math.abs(d)} day${Math.abs(d) === 1 ? '' : 's'} ${d > 0 ? 'earlier' : 'later'} in the count, so its raw totals are not like-for-like; compare shares.`);
			});
		}
		if (ms.includes('mail')) {
			const f = M.counties.filter((c) => inArea(c.n) && c.b[S.base].mail_src);
			f.forEach((c) => out.push(`${c.n} had not reported ${b.year} mail to the Secretary of State at this point; its nearest report (${dateTxt(c.b[S.base].mail_src.as_of)}) is used, so mail comparisons with ${b.short} are unreliable.`));
		}
		if (mixOn(ms)) out.push('2024 mix: mail and in-person ballots are reweighted to each area’s 2024 final shares (statewide ' + mixShare() + '), for 2026 and the comparison point alike. Ballot totals are real; party counts and leads are reweighted.');
		else if (S.mix) out.push('2024 mix needs Mail and In person early checked, and Election Day unchecked; showing ballots as counted.');
		if (S.area !== 'st') out.push(M.areas[S.area].note);
		return out;
	}

	// ---------------------------------------------------------------- results card + party table
	function kpi(label, value, sub, m) {
		const side = m == null || !isFinite(m) || Math.abs(m) < 0.05 ? '' : ' nv-kpi--' + (m < 0 ? 'rep' : 'dem');
		return `<div class="nv-kpi${side}"><div class="nv-kpi-label">${label}</div><div class="nv-kpi-value">${value}</div><div class="nv-kpi-sub">${sub}</div></div>`;
	}
	function seg(cls, n, s, tip) {
		const share = s.total > 0 ? (100 * n) / s.total : 0;
		return `<span class="${cls}" style="flex:${share.toFixed(3)} 1 0" title="${tip}: ${fmt(n)} ballots, ${share.toFixed(1)}%">${share >= 9 ? share.toFixed(0) + '%' : ''}</span>`;
	}
	function barRow(name, s) {
		if (!s.total) return `<div class="nv-bar-name">${name}</div><div class="nv-bar"></div>`;
		return `<div class="nv-bar-name">${name}</div><div class="nv-bar">` +
			seg('nv-seg-d', s.D, s, 'Democrat') + seg('nv-seg-id', s.oD, s, 'Other share to D') +
			seg('nv-seg-ir', s.oR, s, 'Other share to R') + seg('nv-seg-r', s.R, s, 'Republican') + '</div>';
	}
	const key = (v, label) => `<span><span class="nv-swatch" style="background:var(${v});border:0"></span>${label}</span>`;
	const barKey = '<div class="nv-bar-key">' + key('--nv-dem', 'Democrat') + key('--nv-dem-light', 'Other → D') +
		key('--nv-rep-light', 'Other → R') + key('--nv-rep', 'Republican') + '</div>';

	function renderResults() {
		const b = BASES[S.base];
		const all = counties(inArea);
		const now = summarize(all, 'y26'), base = summarize(all, S.base);
		const raw0 = margin(now), raw1 = margin(base), adj0 = adjMargin(now), adj1 = adjMargin(base);
		const none = now.total ? null : 'no 2026 ballots yet';
		$('nvTitle').textContent = `${areaName()} · ${methodName()} · 2026 vs ${b.short}`;
		$('nvKpis').innerHTML =
			kpi('2026 ballots', fmt(now.total), `${fmt(base.total)} in ${b.short}`) +
			kpi('Advantage now', none ? '–' : leadN(now.D - now.R), `${none ? none : lean(raw0) + ' pts'} · ${b.short}: ${leadN(base.D - base.R)}`, raw0) +
			kpi('Shift, with Other split', lean(diff(adj0, adj1)), none || `${lean(adj0)} now, ${lean(adj1)} then`, diff(adj0, adj1)) +
			kpi('Shift, raw', lean(diff(raw0, raw1)), none || `${lean(raw0)} now, ${lean(raw1)} then`, diff(raw0, raw1));
		$('nvBars').innerHTML = barRow('2026', now) + barRow(b.short, base) + barKey;
		const w = warnings();
		$('nvWarn').hidden = !w.length;
		$('nvWarn').innerHTML = w.map(esc).join('<br>');

		const cells = (k) => `<td>${fmt(now[k])}<small>${pct1(now[k], now.total)}</small></td><td>${fmt(base[k])}<small>${pct1(base[k], base.total)}</small></td>`;
		const change = (k, side) => {
			if (!now.total || !base.total) return '<td>–</td>';
			const d = (now.total ? (100 * now[k]) / now.total : 0) - (base.total ? (100 * base[k]) / base.total : 0);
			return `<td${side && d > 0 ? ` class="nv-up-${side}"` : ''}>${d < 0 ? '−' : '+'}${Math.abs(d).toFixed(1)}</td>`;
		};
		const row = (label, k, side) => `<tr class="nv-row-${side || 'ind'}"><th scope="row">${label}</th>${cells(k)}${change(k, side)}</tr>`;
		const mRow = (m0, m1) => `<tr class="nv-margin"><th scope="row">D − R margin</th><td>${lean(m0)}</td><td>${lean(m1)}</td><td>${lean(diff(m0, m1))}</td></tr>`;
		$('nvTable').innerHTML =
			`<thead><tr><th>Registered party</th><th>2026</th><th>${b.short}<small>${baseSub(S.base)}</small></th><th>Change<small>pts</small></th></tr></thead>` +
			'<tbody>' + row('Democrat', 'D', 'dem') + row('Republican', 'R', 'rep') + row('Other (nonpartisan &amp; minor)', 'O') +
			`<tr><th scope="row">Total</th><td>${fmt(now.total)}</td><td>${fmt(base.total)}</td><td></td></tr>` + mRow(raw0, raw1) + '</tbody>' +
			'<tbody><tr class="nv-section"><th colspan="4">With Other split by county</th></tr>' +
			row('Democrat + Other share', 'adjD', 'dem') + row('Republican + Other share', 'adjR', 'rep') + mRow(adj0, adj1) + '</tbody>';
		$('nvFoot').textContent = `2026 so far is ${pct1(now.total, base.total)} of ${b.short}'s ballots for this selection. ` +
			'Other split: each county’s Other ballots go to D and R in that county’s D:R ratio. A heuristic, not a measurement.';
	}

	// ---------------------------------------------------------------- map
	function shiftOf(c, k = S.base) {
		const a = summarize([c], 'y26'), b = summarize([c], k);
		if (!a.total || !b.total) return null;
		return margin(a) - margin(b);
	}
	function renderMap() {
		const svg = $('nvSvg');
		svg.setAttribute('viewBox', `0 0 ${M.geo.w} ${M.geo.h}`);
		svg.innerHTML = M.counties.map((c, i) => {
			const v = shiftOf(c);
			const lbl = v == null ? 'no ballots to compare' : (Math.abs(v) < 0.05 ? 'no change' : Math.abs(v).toFixed(1) + ' pts toward ' + (v > 0 ? 'D' : 'R'));
			return `<path class="nv-cty${S.county === c.n ? ' is-sel' : ''}${inArea(c.n) ? '' : ' is-out'}" data-i="${i}" d="${c.d}" fill="${inArea(c.n) ? binColor(v) : OUT_COLOR}" tabindex="0" role="button" aria-label="${esc(c.n)}: ${lbl}"></path>`;
		}).join('') + M.counties.filter((c) => LABELED.includes(c.n)).map((c) => `<text class="nv-lbl" x="${c.cx}" y="${c.cy}">${esc(c.n)}</text>`).join('');
		$('nvMapTitle').textContent = `County shift in D−R margin · ${areaName()} · ${methodName()} · vs ${BASES[S.base].short}`;
		const tip = $('nvTip');
		svg.querySelectorAll('.nv-cty').forEach((p) => {
			const c = M.counties[+p.dataset.i];
			p.addEventListener('mousemove', (e) => {
				const a = summarize([c], 'y26'), b = summarize([c], S.base), v = shiftOf(c);
				tip.innerHTML = `<b>${esc(c.n)}</b><br>2026: ${fmt(a.total)} ballots${a.total ? `, ${leadN(a.D - a.R)} (${lean(margin(a))})` : ''}<br>` +
					`${BASES[S.base].short}: ${fmt(b.total)}, ${leadN(b.D - b.R)} (${lean(margin(b))})<br>Shift: <b>${lean(v)}</b> pts`;
				const r = $('nvMapWrap').getBoundingClientRect();
				tip.style.left = Math.max(0, Math.min(e.clientX - r.left + 12, r.width - 190)) + 'px';
				tip.style.top = e.clientY - r.top + 12 + 'px';
				tip.hidden = false;
			});
			p.addEventListener('mouseleave', () => (tip.hidden = true));
			p.addEventListener('click', () => select(c.n));
			p.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(c.n); } });
		});
		$('nvLegend').innerHTML = '<div>' + (mixOn() ? 'D−R margin at 2024 method mix' : 'Raw D−R margin') + ', party registration, no Other split</div><div class="nv-legend-bar">' +
			ADV_BINS.map((b) => `<span style="background:${b[1]}" title="${b[2]} pts"></span>`).join('') +
			'</div><div class="nv-legend-ends"><span class="nv-rep">R 20+ pts</span><span>no change</span><span class="nv-dem">D 20+ pts</span></div>' +
			`<div><span class="nv-swatch" style="background:${NO_DATA_COLOR}"></span>No ballots to compare</div>` +
			(S.area === 'st' ? '' : `<div><span class="nv-swatch" style="background:${OUT_COLOR}"></span>Outside ${esc(areaName())}</div>`);
	}

	// ---------------------------------------------------------------- county panel (left column)
	function select(n) {
		S.county = S.county === n ? null : n;
		renderMap();
		renderCounty();
		renderCounties();
	}
	function renderCounty() {
		const el = $('nvCounty');
		const c = M.counties.find((x) => x.n === S.county);
		if (!c) {
			el.innerHTML = '<div class="nv-label">County</div><p class="nv-note">Select a county on the map or in the county table to see it against all four comparison points.</p>';
			return;
		}
		const now = summarize([c], 'y26');
		const rows = ORDER.map((k) => {
			const s = summarize([c], k), d = diff(margin(now), margin(s));
			return `<tr${k === S.base ? ' class="is-sel"' : ''}><th scope="row">${BASES[k].short}</th><td>${fmt(s.total)}</td><td>${lean(margin(s))}</td><td>${lean(d)}</td></tr>`;
		}).join('');
		const notes = [];
		if (methods().includes('mail') && c.y26.mail_note) notes.push('2026 mail: ' + esc(c.y26.mail_note) + '.');
		ORDER.forEach((k) => {
			const src = c.b[k].mail_src;
			if (src && methods().includes('mail')) notes.push(`${BASES[k].short} mail: the matched report has no ${esc(c.n)} row, so ${src.doc ? docLink(src.doc) : 'the nearest report'} from ${dateTxt(src.as_of)} is used.`);
		});
		const sent = methods().includes('mail') && sum(c.y26.sent || [0]) ? `<p class="nv-note">2026: ${fmt(sum(c.y26.rcvd))} mail ballots received, ${fmt(sum(c.y26.mail))} accepted, of ${fmt(sum(c.y26.sent))} sent.</p>` : '';
		el.innerHTML = `<div class="nv-d-head"><h2>${esc(c.n)} County</h2><button type="button" class="nv-close" id="nvClose">Close</button></div>
			<p class="nv-note">${methodName()}. 2026: ${fmt(now.total)} ballots${now.total ? `, ${leadN(now.D - now.R)} (${lean(margin(now))})` : ''}.</p>
			<div class="nv-bars">${barRow('2026', now)}${barRow(BASES[S.base].short, summarize([c], S.base))}</div>
			<h3>Shift vs each comparison point</h3>
			<table class="nv-table"><thead><tr><th>Then</th><th>Ballots</th><th>Margin</th><th>Shift<small>pts</small></th></tr></thead><tbody>${rows}</tbody></table>
			${sent}${notes.map((n) => `<p class="nv-note nv-warn">${n}</p>`).join('')}`;
		$('nvClose').addEventListener('click', () => select(c.n));
	}

	// ---------------------------------------------------------------- shift table: every area vs every comparison point
	function chipCell(d) {
		if (d == null || !isFinite(d)) return '–';
		return `<span class="nv-chip-cell" style="background:${binColor(d)};color:${Math.abs(d) >= 10 ? '#fff' : 'var(--dr-ink)'}">${Math.abs(d) < 0.05 ? 'Even' : (d > 0 ? 'D' : 'R') + ' +' + Math.abs(d).toFixed(1)}</span>`;
	}
	function renderShift() {
		const groups = [['Clark', (n) => n === 'Clark'], ['Washoe', (n) => n === 'Washoe'], ['15 rural counties', RURAL], ['CD2', CD2], ['CD2 outside Washoe', (n) => CD2(n) && n !== 'Washoe'], ['Statewide', () => true]];
		const head = '<thead><tr><th>Area</th><th>2026 advantage<small>ballots · pts</small></th>' +
			ORDER.map((k) => `<th class="${k === S.base ? 'is-cur' : ''}">vs ${BASES[k].short}<small>then → shift</small></th>`).join('') + '</tr></thead>';
		const body = groups.map(([name, f]) => {
			const list = counties(f), now = summarize(list, 'y26');
			const cols = ORDER.map((k) => {
				const s = summarize(list, k);
				return `<td class="${k === S.base ? 'is-cur' : ''}">${chipCell(diff(margin(now), margin(s)))}<small>then ${lean(margin(s))} · ${fmt(s.total)}</small></td>`;
			}).join('');
			return `<tr class="${name === 'Statewide' ? 'nv-total' : ''}${name === 'CD2' ? ' nv-cd' : ''}"><th scope="row">${name}</th><td>${now.total ? leadN(now.D - now.R) : '–'}<small>${lean(margin(now))} · ${fmt(now.total)}</small></td>${cols}</tr>`;
		}).join('');
		$('nvShift').innerHTML = head + '<tbody>' + body + '</tbody>';
		$('nvShiftTitle').textContent = `Shift since each comparison point · ${methodName()}`;
		$('nvShiftNote').textContent = (mixOn() ? 'D−R margin at each area’s 2024 method mix, by party registration.' : 'Raw D−R margin by party registration.') + ' Shift is 2026’s margin minus the comparison point’s, in points; blue moved toward Democrats, red toward Republicans.';
	}

	// ---------------------------------------------------------------- county table
	function renderCounties() {
		const b = BASES[S.base];
		const cols = [['name', 'County'], ['n26', '2026 ballots'], ['lead', '2026 advantage'], ['nb', b.short + ' ballots'], ['mb', b.short + ' margin'], ['shift', 'Shift'], ['pace', '2026 vs then']];
		const rows = counties(inArea).map((c) => {
			const a = summarize([c], 'y26'), x = summarize([c], S.base);
			return { name: c.n, n26: a.total, lead: a.D - a.R, m26: margin(a), nb: x.total, mb: margin(x), shift: shiftOf(c), pace: x.total ? (100 * a.total) / x.total : null };
		});
		rows.sort((x, y) => {
			const p = x[S.sort], q = y[S.sort];
			if (typeof p === 'string') return S.dir * p.localeCompare(q);
			return S.dir * ((p ?? -1e9) - (q ?? -1e9));
		});
		const th = cols.map(([k, l]) => `<th scope="col"><button type="button" class="nv-sort" data-k="${k}" aria-sort="${S.sort === k ? (S.dir > 0 ? 'ascending' : 'descending') : 'none'}">${l}${S.sort === k ? (S.dir > 0 ? ' ▲' : ' ▼') : ''}</button></th>`).join('');
		const tb = rows.map((r) => `<tr class="${S.county === r.name ? 'is-sel' : ''}" data-n="${esc(r.name)}"><th scope="row"><button type="button" class="nv-link">${esc(r.name)}</button></th>` +
			`<td>${fmt(r.n26)}</td><td>${r.n26 ? leadN(r.lead) + '<small>' + lean(r.m26) + '</small>' : '–'}</td><td>${fmt(r.nb)}</td><td>${lean(r.mb)}</td><td>${chipCell(r.shift)}</td><td>${r.pace == null ? '–' : Math.round(r.pace) + '%'}</td></tr>`).join('');
		const t = $('nvCounties');
		t.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${tb}</tbody>`;
		$('nvCountiesTitle').textContent = S.area === 'st' ? 'All counties' : `${areaName()} counties`;
		$('nvCountiesNote').textContent = `${areaName()}: ${methodName()}, 2026 vs ${b.short}. Click a column to sort.`;
		t.querySelectorAll('.nv-sort').forEach((el) => el.addEventListener('click', () => {
			const k = el.dataset.k;
			S.dir = S.sort === k ? -S.dir : k === 'name' ? 1 : -1;
			S.sort = k;
			renderCounties();
		}));
		t.querySelectorAll('.nv-link').forEach((el) => el.addEventListener('click', () => { select(el.closest('tr').dataset.n); $('nvCounty').scrollIntoView({ block: 'nearest' }); }));
	}

	// ---------------------------------------------------------------- day-by-day in person (2024 vs 2026)
	function renderDaily() {
		const d26 = M.daily['2026'], d24 = M.daily['2024'];
		const n = Math.max(d24.length, d26.length);
		const filt = { st: () => true, clark: (k) => k === 'Clark', washoe: (k) => k === 'Washoe', rural: RURAL, cd2: CD2 }[$('nvDailyArea').value];
		const pts = (arr) => arr.map((e) => {
			const a = Object.entries(e.c).filter(([k]) => filt(k)).reduce((x, [, v]) => add(x, v), [0, 0, 0]);
			return { day: e.day, date: e.date, a, m: a[0] - a[1] };
		});
		const p26 = pts(d26), p24 = pts(d24);
		const max = Math.max(1, ...p26.concat(p24).map((p) => Math.abs(p.m)));
		const W = 640, H = 240, L = 56, B = 26, T = 10, bw = (W - L - 8) / n;
		const y0 = T + (H - T - B) / 2, sc = (H - T - B) / 2 / max;
		const lbl = (v) => (v === 0 ? 'Even' : (v > 0 ? 'D+' : 'R+') + fmt(Math.abs(v)));
		let g = '';
		[-max, -max / 2, 0, max / 2, max].forEach((v) => {
			const y = y0 - v * sc;
			g += `<line x1="${L}" x2="${W - 4}" y1="${y}" y2="${y}" class="${v === 0 ? 'nv-axis0' : 'nv-gridline'}"></line><text class="nv-tick" x="${L - 6}" y="${y + 4}" text-anchor="end">${lbl(v)}</text>`;
		});
		for (let i = 0; i < n; i++) {
			const x = L + i * bw;
			[[p24[i], 0, 'nv-b24'], [p26[i], 1, 'nv-b26']].forEach(([p, k, cls]) => {
				if (!p) return;
				const h = Math.abs(p.m) * sc, w = bw * 0.36;
				const bx = x + bw * 0.12 + k * (w + 2);
				g += `<rect class="${cls} ${p.m >= 0 ? 'is-D' : 'is-R'}" x="${bx}" y="${p.m >= 0 ? y0 - h : y0}" width="${w}" height="${Math.max(h, 1)}" rx="2"><title>${k ? 2026 : 2024} day ${p.day} (${p.date}): ${lbl(p.m)} of ${fmt(sum(p.a))} in-person ballots</title></rect>`;
			});
			g += `<text class="nv-tick" x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${i + 1}</text>`;
		}
		$('nvDaily').innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="In-person D minus R ballots by early-voting day, 2026 and 2024">${g}</svg>`;
		$('nvDailyRows').innerHTML = '<thead><tr><th>Day</th><th>2024</th><th>2026</th></tr></thead><tbody>' + Array.from({ length: n }, (_, i) => {
			const a = p24[i], b = p26[i];
			return `<tr><th scope="row">${i + 1}</th><td>${a ? lbl(a.m) + ' of ' + fmt(sum(a.a)) : '–'}</td><td>${b ? lbl(b.m) + ' of ' + fmt(sum(b.a)) + (i === p26.length - 1 && M.cur.ev.in_progress ? ' (counting)' : '') : '–'}</td></tr>`;
		}).join('') + '</tbody>';
	}

	// ---------------------------------------------------------------- comparison points
	function pointLabel(p, m) {
		if (m === 'ed') return p.doc && p.as_of.endsWith('T19:00') ? dateTxt(p.as_of, false) + ', Election Day, full day' : dateTxt(p.as_of) + ', Election Day';
		const day = p.ev_day >= 1 ? `early-voting day ${p.ev_day}` : `${1 - p.ev_day} day${p.ev_day === 0 ? '' : 's'} before early voting`;
		return `${dateTxt(p.as_of)} (${day}, ${p.days_out} days before Election Day)`;
	}
	function renderPoints() {
		const lines = [];
		['ev', 'mail', 'ed'].filter((m) => M.cur[m]).forEach((m) => {
			const name = { ev: 'In person early', mail: 'Mail', ed: 'Election Day' }[m];
			lines.push(`<li><b>${name}, 2026:</b> ${pointLabel(M.cur[m], m)}, Nevada SoS VIVID.</li>`);
			ORDER.forEach((k) => {
				const p = point(k, m);
				const src = p.docs ? p.docs.map(docLink).join(', ') : docLink(p.doc);
				lines.push(`<li><b>${name}, ${BASES[k].short}:</b> ${pointLabel(p, m)}. ${esc(p.note || '')} (${src}).</li>`);
			});
		});
		$('nvPoints').innerHTML = lines.join('');
	}

	// ---------------------------------------------------------------- controls
	/** When comparison point k was taken, for the selected ballot types. */
	function baseSub(k) {
		const ms = methods();
		if (BASES[k].final) return ms.includes('ed') ? (ms.length === 1 ? 'full Election Day' : 'final count') : 'end of early voting';
		const t = ms.map((m) => {
			const p = point(k, m);
			if (m !== 'ed') return shortDate(p.as_of);
			return p.as_of.endsWith('T19:00') ? 'full Election Day' : new Date(p.as_of).toLocaleTimeString('en-US', { hour: 'numeric' }) + ' Election Day';
		});
		if (t.every((x) => x === t[0])) return ms.includes('ed') ? t[0] : t[0] + ' report';
		return ms.map((m, i) => `${m === 'ed' ? 'ED' : m === 'ev' ? 'in person' : 'mail'} ${t[i].replace(' Election Day', '')}`).join(', ');
	}

	function renderControls() {
		const chip = (id, main, sub, attrs) => `<label class="nv-chip" id="${id}Option"><input ${attrs} id="${id}"><span>${main}</span>${sub ? `<small>${sub}</small>` : ''}</label>`;
		const sub = baseSub;
		$('nvControls').innerHTML =
			'<div class="nv-group"><div class="nv-label">Area</div><div class="nv-seg">' +
			chip('nvAreast', 'Statewide', '17 counties', `type="radio" name="nvArea" value="st"${S.area === 'st' ? ' checked' : ''}`) +
			Object.entries(M.areas).map(([k, a]) => chip('nvArea' + k, a.name, `${a.counties.length} counties`, `type="radio" name="nvArea" value="${k}"${S.area === k ? ' checked' : ''}`)).join('') +
			'</div></div>' +
			'<div class="nv-group"><div class="nv-label">Ballots</div><div class="nv-seg">' +
			chip('nvMail', 'Mail', 'accepted', `type="checkbox"${S.mail ? ' checked' : ''}`) +
			chip('nvEv', 'In person', 'early voting', `type="checkbox"${S.ev ? ' checked' : ''}`) +
			(M.cur.ed ? chip('nvEd', 'Election Day', 'in person', `type="checkbox"${S.ed ? ' checked' : ''}`) : '') +
			`</div><p class="nv-note">${M.cur.ed ? 'Mail + In person = all early ballots; all three = every ballot.' : 'Both checked = all early ballots.'}</p>` +
			'<div class="nv-seg">' + chip('nvMix', '2024 mix', 'reweight methods', `type="checkbox"${S.mix ? ' checked' : ''}${S.mail && S.ev && !S.ed ? '' : ' disabled'}`) + '</div>' +
			'<p class="nv-note">Weights mail and in person to their 2024 shares, so a mail-heavy start doesn’t pass for a shift.</p></div>' +
			'<div class="nv-group"><div class="nv-label">Compare 2026 against</div><div class="nv-seg">' +
			ORDER.map((k) => chip('nvBase' + k, BASES[k].short, sub(k), `type="radio" name="nvBase" value="${k}"${k === S.base ? ' checked' : ''}`)).join('') +
			'</div><p class="nv-note">"Nearest" = the Secretary of State report closest in days before Election Day to where 2026 is now' + (M.cur.ed ? ' (for Election Day, closest in time of day)' : '') + '. "Final" = every early ballot that year' + (M.cur.ed ? ', and the full Election Day' : '') + '.</p></div>';
		const both = () => {
			$('nvMix').disabled = !(S.mail && S.ev && !S.ed);
			document.querySelectorAll('input[name=nvBase]').forEach((r) => { r.nextElementSibling.nextElementSibling.textContent = baseSub(r.value); });
		};
		$('nvMail').addEventListener('change', (e) => { S.mail = e.target.checked; both(); render(); });
		$('nvEv').addEventListener('change', (e) => { S.ev = e.target.checked; both(); render(); });
		if (M.cur.ed) $('nvEd').addEventListener('change', (e) => { S.ed = e.target.checked; both(); render(); });
		$('nvMix').addEventListener('change', (e) => { S.mix = e.target.checked; render(); });
		document.querySelectorAll('input[name=nvArea]').forEach((r) => r.addEventListener('change', (e) => {
			S.area = e.target.value;
			if (S.county && !inArea(S.county)) S.county = null;
			if (S.area !== 'st') { $('nvDailyArea').value = S.area; renderDaily(); }
			render();
		}));
		document.querySelectorAll('input[name=nvBase]').forEach((r) => r.addEventListener('change', (e) => { S.base = e.target.value; render(); }));
	}

	function render() {
		renderResults();
		renderMap();
		renderCounty();
		renderShift();
		renderCounties();
	}

	window.nvInit = function (data) {
		M = data;
		if (M.cur.ed) Object.assign(S, { mail: false, ev: false, ed: true, base: '22f' });
		$('nvMeta').textContent = `2026 in person${M.cur.ed ? ' and Election Day' : ''} as of ${dateTxt(M.cur.ev.as_of)} · mail as of ${dateTxt(M.cur.mail.as_of)} · Nevada SoS VIVID and SoS turnout reports`;
		renderControls();
		$('nvDailyArea').addEventListener('change', renderDaily);
		render();
		renderDaily();
		renderPoints();
	};
})();
