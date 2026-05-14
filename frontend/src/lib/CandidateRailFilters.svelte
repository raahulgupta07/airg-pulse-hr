<script>
	/**
	 * Left-rail filters — LinkedIn-style accordion.
	 * Each facet is a collapsible card with a clickable header showing
	 * a summary of the current state. Active filters get a 4px primary
	 * left border.
	 *
	 * Open-state persistence: localStorage key `hire_rail_open`, an
	 * object map { scope, state, role, attached, uploaded, qscore }.
	 */
	let {
		// scope
		scope = $bindable('mine'),
		scopeCounts = { mine: 0, sector: 0, pool: 0 },
		onScopeChange = () => {},
		// state filter (pipeline state)
		stateFilter = $bindable('all'),
		stateCounts = { all: 0, pending: 0, running: 0, done: 0, error: 0 },
		// role filter
		roleFacets = [],          // [{value, count}]
		roleSelected = $bindable(new Set()),
		// attached filter
		attachedFacets = [],      // [{value, count, label}]
		attachedSelected = $bindable(new Set()),
		// uploaded date range (today | 7d | 30d | 90d | all)
		uploadedRange = $bindable('all'),
		// quality score (slider 0..100)
		qScoreMin = $bindable(0),
		// AI facet groups — { skill: {top, new, total}, company: {...}, ... }
		facetGroups = {},
		// AI facet selections per type (Set<string canonical>)
		skillSelected = $bindable(new Set()),
		companySelected = $bindable(new Set()),
		locationSelected = $bindable(new Set()),
		languageSelected = $bindable(new Set()),
		certSelected = $bindable(new Set()),
		educationSelected = $bindable(new Set()),
		// Called with facet id when user clicks a NEW row
		onDismissFacetNew = (_id) => {},
		// clear-all
		onClearAll = () => {},
	} = $props();

	const DEFAULT_OPEN = {
		scope: true, state: true, role: false, attached: false, uploaded: false, qscore: false,
		skill: false, company: false, location: false, language: false, cert: false, education: false,
	};

	let openMap = $state({ ...DEFAULT_OPEN });
	let showAllRoles = $state(false);
	// Per-AI-group "show all" + search-text state
	let aiShowAll = $state({ skill: false, company: false, location: false, language: false, cert: false, education: false });
	let aiQuery = $state({ skill: '', company: '', location: '', language: '', cert: '', education: '' });

	const AI_GROUPS = [
		{ key: 'skill',     title: 'Skill'     },
		{ key: 'company',   title: 'Company'   },
		{ key: 'location',  title: 'Location'  },
		{ key: 'language',  title: 'Language'  },
		{ key: 'cert',      title: 'Cert'      },
		{ key: 'education', title: 'Education' },
	];

	function aiSelectedSet(key) {
		switch (key) {
			case 'skill':     return skillSelected;
			case 'company':   return companySelected;
			case 'location':  return locationSelected;
			case 'language':  return languageSelected;
			case 'cert':      return certSelected;
			case 'education': return educationSelected;
		}
		return new Set();
	}
	function aiSetSelectedSet(key, next) {
		switch (key) {
			case 'skill':     skillSelected = next; break;
			case 'company':   companySelected = next; break;
			case 'location':  locationSelected = next; break;
			case 'language':  languageSelected = next; break;
			case 'cert':      certSelected = next; break;
			case 'education': educationSelected = next; break;
		}
	}
	function aiToggle(key, canonical, facetId, isNew) {
		const cur = aiSelectedSet(key);
		const next = new Set(cur);
		if (next.has(canonical)) next.delete(canonical); else next.add(canonical);
		aiSetSelectedSet(key, next);
		if (isNew && facetId) {
			try { onDismissFacetNew(facetId); } catch {}
		}
		try {
			const map = JSON.parse(localStorage.getItem('hire_ai_facets') || '{}');
			map[key] = [...next];
			localStorage.setItem('hire_ai_facets', JSON.stringify(map));
		} catch {}
	}
	function aiRowsFor(key) {
		const grp = facetGroups?.[key];
		if (!grp) return [];
		const rowsTop = grp.top || [];
		const rowsNew = grp.new || [];
		// Merge: new rows first (deduped by id), then top by count
		const seen = new Set();
		const out = [];
		for (const r of rowsNew) {
			if (seen.has(r.id)) continue;
			seen.add(r.id);
			out.push({ ...r, _new: true });
		}
		for (const r of rowsTop) {
			if (seen.has(r.id)) continue;
			seen.add(r.id);
			out.push({ ...r, _new: !!r.is_new });
		}
		const q = (aiQuery[key] || '').trim().toLowerCase();
		if (q) {
			return out.filter(r => (r.canonical || '').toLowerCase().includes(q) || (r.value || '').toLowerCase().includes(q));
		}
		return out;
	}
	function aiActive(key) {
		return aiSelectedSet(key).size > 0;
	}

	// Hydrate open-state from localStorage (effect runs once after mount).
	$effect(() => {
		try {
			const raw = typeof localStorage !== 'undefined' ? localStorage.getItem('hire_rail_open') : null;
			if (raw) {
				const parsed = JSON.parse(raw);
				if (parsed && typeof parsed === 'object') openMap = { ...DEFAULT_OPEN, ...parsed };
			}
		} catch {}
		try {
			const raw = typeof localStorage !== 'undefined' ? localStorage.getItem('hire_ai_facets') : null;
			if (raw) {
				const parsed = JSON.parse(raw) || {};
				if (Array.isArray(parsed.skill))     skillSelected     = new Set(parsed.skill);
				if (Array.isArray(parsed.company))   companySelected   = new Set(parsed.company);
				if (Array.isArray(parsed.location))  locationSelected  = new Set(parsed.location);
				if (Array.isArray(parsed.language))  languageSelected  = new Set(parsed.language);
				if (Array.isArray(parsed.cert))      certSelected      = new Set(parsed.cert);
				if (Array.isArray(parsed.education)) educationSelected = new Set(parsed.education);
			}
		} catch {}
	});

	function toggleGroup(key) {
		openMap = { ...openMap, [key]: !openMap[key] };
		try { localStorage.setItem('hire_rail_open', JSON.stringify(openMap)); } catch {}
	}

	function toggleSet(set, val, setter) {
		const next = new Set(set);
		if (next.has(val)) next.delete(val); else next.add(val);
		setter(next);
	}

	// Summaries shown in collapsed header rows.
	const SCOPE_LABELS = { mine: 'Mine', sector: 'Sector', pool: 'Pool' };
	const STATE_LABELS = { all: 'Any', pending: 'Pending', running: 'Running', done: 'Done', error: 'Error' };
	const RANGE_LABELS = { today: 'Today', '7d': 'Last 7 days', '30d': 'Last 30 days', '90d': 'Last 90 days', all: 'Any' };

	let scopeActive = $derived(scope !== 'mine');
	let stateActive = $derived(stateFilter !== 'all');
	let roleActive = $derived(roleSelected.size > 0);
	let attachedActive = $derived(attachedSelected.size > 0);
	let uploadedActive = $derived(uploadedRange !== 'all');
	let qScoreActive = $derived(Number(qScoreMin) > 0);

	let aiActiveCount = $derived(
		(skillSelected.size > 0 ? 1 : 0) +
		(companySelected.size > 0 ? 1 : 0) +
		(locationSelected.size > 0 ? 1 : 0) +
		(languageSelected.size > 0 ? 1 : 0) +
		(certSelected.size > 0 ? 1 : 0) +
		(educationSelected.size > 0 ? 1 : 0)
	);

	let activeCount = $derived(
		(scopeActive ? 1 : 0) + (stateActive ? 1 : 0) + (roleActive ? 1 : 0) +
		(attachedActive ? 1 : 0) + (uploadedActive ? 1 : 0) + (qScoreActive ? 1 : 0) +
		aiActiveCount
	);

	function roleSummary() {
		if (roleSelected.size === 0) return 'Any';
		if (roleSelected.size === 1) return [...roleSelected][0];
		return `${roleSelected.size} selected`;
	}
	function attachedSummary() {
		if (attachedSelected.size === 0) return 'Any';
		if (attachedSelected.size === 1) {
			const v = [...attachedSelected][0];
			const f = attachedFacets.find(a => a.value === v);
			return f?.label || v;
		}
		return `${attachedSelected.size} selected`;
	}
</script>

<aside class="rail">
	<!-- SCOPE -->
	<section class="acc" class:acc-active={scopeActive}>
		<button class="acc-h" type="button" onclick={() => toggleGroup('scope')} aria-expanded={openMap.scope}>
			<span class="acc-title">Scope</span>
			<span class="acc-sum">{SCOPE_LABELS[scope] || 'Any'}</span>
			<span class="acc-chev">{openMap.scope ? '⌄' : '›'}</span>
		</button>
		<div class="acc-body" class:open={openMap.scope}>
			<div class="acc-inner">
				{#each [
					{id:'mine', label:'Mine', sub:'uploaded by me'},
					{id:'sector', label:'Sector', sub:'my sector'},
					{id:'pool', label:'Pool', sub:'org-wide'},
				] as t}
					<label class="rail-radio" class:active={scope === t.id}>
						<input type="radio" name="rail-scope" value={t.id} checked={scope === t.id}
							onchange={() => { scope = t.id; onScopeChange(t.id); }} />
						<span class="rl">{t.label}</span>
						<span class="ct">{scopeCounts[t.id] ?? 0}</span>
						<div class="sb">{t.sub}</div>
					</label>
				{/each}
			</div>
		</div>
	</section>

	<!-- STATE -->
	<section class="acc" class:acc-active={stateActive}>
		<button class="acc-h" type="button" onclick={() => toggleGroup('state')} aria-expanded={openMap.state}>
			<span class="acc-title">State</span>
			<span class="acc-sum">{STATE_LABELS[stateFilter] || 'Any'}</span>
			<span class="acc-chev">{openMap.state ? '⌄' : '›'}</span>
		</button>
		<div class="acc-body" class:open={openMap.state}>
			<div class="acc-inner">
				{#each [
					{id:'all', label:'All', dot:''},
					{id:'pending', label:'Pending', dot:'dot-pending'},
					{id:'running', label:'Running', dot:'dot-running'},
					{id:'done', label:'Done', dot:'dot-done'},
					{id:'error', label:'Error', dot:'dot-error'},
				] as s}
					<label class="rail-radio" class:active={stateFilter === s.id}>
						<input type="radio" name="rail-state" value={s.id} checked={stateFilter === s.id}
							onchange={() => (stateFilter = s.id)} />
						{#if s.dot}<span class={'dot ' + s.dot}></span>{:else}<span class="dot dot-spacer"></span>{/if}
						<span class="rl">{s.label}</span>
						<span class="ct">{stateCounts[s.id] ?? 0}</span>
					</label>
				{/each}
			</div>
		</div>
	</section>

	<!-- ROLE -->
	{#if roleFacets.length > 0}
		<section class="acc" class:acc-active={roleActive}>
			<button class="acc-h" type="button" onclick={() => toggleGroup('role')} aria-expanded={openMap.role}>
				<span class="acc-title">Role</span>
				<span class="acc-sum">{roleSummary()}</span>
				<span class="acc-chev">{openMap.role ? '⌄' : '›'}</span>
			</button>
			<div class="acc-body" class:open={openMap.role}>
				<div class="acc-inner">
					{#each (showAllRoles ? roleFacets : roleFacets.slice(0, 5)) as r}
						<label class="rail-check">
							<input type="checkbox" checked={roleSelected.has(r.value)}
								onchange={() => toggleSet(roleSelected, r.value, (v) => roleSelected = v)} />
							<span class="rl" title={r.value}>{r.value}</span>
							<span class="ct">{r.count}</span>
						</label>
					{/each}
					{#if roleFacets.length > 5}
						<button class="show-all" type="button" onclick={() => showAllRoles = !showAllRoles}>
							{showAllRoles ? '− show less' : `+ show all (${roleFacets.length})`}
						</button>
					{/if}
				</div>
			</div>
		</section>
	{/if}

	<!-- AI FACET GROUPS (skill / company / location / language / cert / education) -->
	{#each AI_GROUPS as g}
		{@const rows = aiRowsFor(g.key)}
		{@const total = facetGroups?.[g.key]?.total || 0}
		{@const visibleRows = aiShowAll[g.key] ? rows : rows.slice(0, 5)}
		<section class="acc" class:acc-active={aiActive(g.key)}>
			<button class="acc-h" type="button" onclick={() => toggleGroup(g.key)} aria-expanded={openMap[g.key]}>
				<span class="acc-title">{g.title} <span class="ai-pill" title="AI-generated facets">AI</span></span>
				<span class="acc-sum">{aiSelectedSet(g.key).size > 0 ? `${aiSelectedSet(g.key).size} selected` : (total ? `${total}` : 'Empty')}</span>
				<span class="acc-chev">{openMap[g.key] ? '⌄' : '›'}</span>
			</button>
			<div class="acc-body" class:open={openMap[g.key]}>
				<div class="acc-inner">
					<input
						type="text"
						class="ai-search"
						placeholder="Filter…"
						value={aiQuery[g.key]}
						oninput={(e) => aiQuery = { ...aiQuery, [g.key]: e.currentTarget.value }}
					/>
					{#if rows.length === 0}
						<div class="ai-empty">No options yet — process more CVs.</div>
					{:else}
						{#each visibleRows as r (r.id)}
							{@const selected = aiSelectedSet(g.key).has(r.canonical)}
							<label class="rail-check ai-row" class:row-new={r._new} class:active={selected}>
								<input
									type="checkbox"
									checked={selected}
									onchange={() => aiToggle(g.key, r.canonical, r.id, r._new)}
								/>
								<span class="rl" title={r.value}>
									{#if r._new}<span class="new-tag">New</span>{/if}
									{r.value || r.canonical}
								</span>
								<span class="ct">{r.count}</span>
							</label>
						{/each}
						{#if rows.length > 5}
							<button class="show-all" type="button" onclick={() => aiShowAll = { ...aiShowAll, [g.key]: !aiShowAll[g.key] }}>
								{aiShowAll[g.key] ? '− show less' : `+ show all (${rows.length - 5} more)`}
							</button>
						{/if}
					{/if}
				</div>
			</div>
		</section>
	{/each}

	<!-- ATTACHED -->
	{#if attachedFacets.length > 0}
		<section class="acc" class:acc-active={attachedActive}>
			<button class="acc-h" type="button" onclick={() => toggleGroup('attached')} aria-expanded={openMap.attached}>
				<span class="acc-title">Attached</span>
				<span class="acc-sum">{attachedSummary()}</span>
				<span class="acc-chev">{openMap.attached ? '⌄' : '›'}</span>
			</button>
			<div class="acc-body" class:open={openMap.attached}>
				<div class="acc-inner">
					{#each attachedFacets as a}
						<label class="rail-check">
							<input type="checkbox" checked={attachedSelected.has(a.value)}
								onchange={() => toggleSet(attachedSelected, a.value, (v) => attachedSelected = v)} />
							<span class="rl" title={a.label || a.value}>{a.label || a.value}</span>
							<span class="ct">{a.count}</span>
						</label>
					{/each}
				</div>
			</div>
		</section>
	{/if}

	<!-- UPLOADED -->
	<section class="acc" class:acc-active={uploadedActive}>
		<button class="acc-h" type="button" onclick={() => toggleGroup('uploaded')} aria-expanded={openMap.uploaded}>
			<span class="acc-title">Uploaded</span>
			<span class="acc-sum">{RANGE_LABELS[uploadedRange] || 'Any'}</span>
			<span class="acc-chev">{openMap.uploaded ? '⌄' : '›'}</span>
		</button>
		<div class="acc-body" class:open={openMap.uploaded}>
			<div class="acc-inner">
				{#each [
					{id:'today', label:'Today'},
					{id:'7d', label:'Last 7 days'},
					{id:'30d', label:'Last 30 days'},
					{id:'90d', label:'Last 90 days'},
					{id:'all', label:'Any time'},
				] as o}
					<label class="rail-radio" class:active={uploadedRange === o.id}>
						<input type="radio" name="rail-uploaded" value={o.id} checked={uploadedRange === o.id}
							onchange={() => (uploadedRange = o.id)} />
						<span class="dot dot-spacer"></span>
						<span class="rl">{o.label}</span>
					</label>
				{/each}
			</div>
		</div>
	</section>

	<!-- Q SCORE -->
	<section class="acc" class:acc-active={qScoreActive}>
		<button class="acc-h" type="button" onclick={() => toggleGroup('qscore')} aria-expanded={openMap.qscore}>
			<span class="acc-title">Q score</span>
			<span class="acc-sum">{qScoreActive ? `≥ ${qScoreMin}` : 'Any'}</span>
			<span class="acc-chev">{openMap.qscore ? '⌄' : '›'}</span>
		</button>
		<div class="acc-body" class:open={openMap.qscore}>
			<div class="acc-inner">
				<div class="qs-row">
					<input type="range" min="0" max="100" step="5"
						value={qScoreMin}
						oninput={(e) => qScoreMin = Number(e.currentTarget.value)} />
					<span class="qs-val">{qScoreMin}</span>
				</div>
				<div class="qs-hint">Show CVs with quality ≥ {qScoreMin}</div>
			</div>
		</div>
	</section>

	<button class="clear-all" type="button" onclick={onClearAll} disabled={activeCount === 0}>
		Clear all{activeCount > 0 ? ` · ${activeCount} active` : ''}
	</button>
</aside>

<style>
	.rail {
		background: var(--color-surface, #ffffff);
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-family: 'Inter', system-ui, sans-serif;
	}
	.acc {
		border: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface, #ffffff);
		border-radius: 10px;
		position: relative;
		overflow: hidden;
	}
	.acc.acc-active {
		border-left: 3px solid var(--color-accent, #c96342);
	}
	.acc-h {
		display: grid;
		grid-template-columns: auto 1fr auto;
		align-items: center;
		column-gap: 8px;
		width: 100%;
		padding: 10px 12px;
		background: transparent;
		border: none;
		font-family: 'Inter', system-ui, sans-serif;
		cursor: pointer;
		text-align: left;
	}
	.acc-h:hover { background: var(--color-surface-warm, #f4f3ee); }
	.acc-title {
		font-size: 13px; font-weight: 600;
		color: var(--color-on-surface, #2c2c2c);
	}
	.acc-sum {
		font-size: 12px; font-weight: 400;
		color: var(--color-on-surface-dim, #6f6e69);
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
		text-align: right;
	}
	.acc-chev {
		font-size: 14px; font-weight: 500;
		color: var(--color-on-surface-dim, #6f6e69);
		min-width: 12px; text-align: center;
	}
	.acc-body {
		max-height: 0;
		opacity: 0;
		overflow: hidden;
		transition: max-height 180ms ease, opacity 180ms ease;
	}
	.acc-body.open { max-height: 600px; opacity: 1; }
	.acc-inner {
		padding: 6px 10px 12px 10px;
		border-top: 1px solid var(--color-border-soft, #efeee6);
		display: flex; flex-direction: column; gap: 2px;
	}
	.rail-radio, .rail-check {
		display: grid;
		grid-template-columns: 14px 1fr auto;
		align-items: center;
		column-gap: 8px;
		padding: 6px 8px;
		font-size: 13px;
		font-weight: 400;
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		border-radius: 8px;
		border: 1px solid transparent;
	}
	.rail-radio:hover, .rail-check:hover { background: var(--color-surface-warm, #f4f3ee); }
	.rail-radio.active, .rail-check.active {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
	}
	.rail-radio input, .rail-check input { accent-color: var(--color-accent, #c96342); margin: 0; }
	.rl {
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.ct {
		font-variant-numeric: tabular-nums;
		font-size: 11px; font-weight: 500;
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-on-surface-dim, #6f6e69);
		padding: 1px 8px;
		border-radius: 999px;
		min-width: 22px; text-align: center;
	}
	.rail-radio.active .ct, .rail-check.active .ct {
		background: var(--color-accent, #c96342);
		color: #ffffff;
	}
	.sb {
		grid-column: 2 / -1;
		font-size: 11px;
		font-weight: 400;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-top: -1px;
	}
	.dot {
		width: 8px; height: 8px; display: inline-block;
		border: 1px solid var(--color-border-strong, #d8d5cb);
		border-radius: 50%;
		grid-column: 1;
	}
	.dot-spacer { border-color: transparent; }
	.dot-pending { background: var(--color-surface, #ffffff); }
	.dot-running { background: #d4912a; border-color: #d4912a; animation: pulse 1.2s ease-in-out infinite; }
	.dot-done    { background: #5a8a3a; border-color: #5a8a3a; }
	.dot-error   { background: var(--color-error, #a83232); border-color: var(--color-error, #a83232); }
	@keyframes pulse {
		0%,100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.5; transform: scale(0.85); }
	}
	.show-all {
		margin-top: 4px;
		background: transparent;
		border: none;
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 12px; font-weight: 500;
		color: var(--color-accent, #c96342);
		cursor: pointer;
		text-align: left;
		padding: 4px 8px;
	}
	.show-all:hover { color: var(--color-accent-ink, #b04f30); }
	.qs-row {
		display: grid;
		grid-template-columns: 1fr auto;
		align-items: center;
		column-gap: 8px;
		padding: 4px 4px 0 4px;
	}
	.qs-row input[type="range"] { accent-color: var(--color-accent, #c96342); width: 100%; }
	.qs-val {
		font-variant-numeric: tabular-nums;
		font-size: 12px; font-weight: 600;
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-on-surface, #2c2c2c);
		padding: 2px 8px;
		border-radius: 999px;
		min-width: 28px; text-align: center;
	}
	.qs-hint {
		font-size: 11px; font-weight: 400;
		color: var(--color-on-surface-dim, #6f6e69);
		padding: 4px 6px 0 6px;
	}
	.ai-pill {
		display: inline-block;
		font-size: 10px;
		font-weight: 500;
		padding: 1px 7px;
		margin-left: 4px;
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		border-radius: 999px;
		vertical-align: middle;
	}
	.ai-search {
		width: 100%;
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 12px;
		font-weight: 400;
		padding: 6px 10px;
		margin-bottom: 6px;
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 8px;
		outline: none;
	}
	.ai-search:focus {
		border-color: var(--color-accent, #c96342);
		box-shadow: 0 0 0 3px var(--color-accent-bg, rgba(201,99,66,0.12));
	}
	.ai-empty {
		font-size: 12px;
		font-weight: 400;
		color: var(--color-on-surface-dim, #6f6e69);
		padding: 8px;
	}
	.ai-row.row-new {
		background: var(--color-accent-bg, #faf2ed);
	}
	.new-tag {
		display: inline-block;
		font-size: 10px;
		font-weight: 500;
		padding: 0 6px;
		margin-right: 4px;
		background: var(--color-accent, #c96342);
		color: #ffffff;
		border-radius: 999px;
	}
	.clear-all {
		margin-top: 8px;
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px;
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 12px; font-weight: 500;
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		padding: 8px 14px;
		text-align: center;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.clear-all:hover:not(:disabled) {
		background: var(--color-error-soft, #f5dada);
		border-color: var(--color-error, #a83232);
		color: var(--color-error, #a83232);
	}
	.clear-all:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
