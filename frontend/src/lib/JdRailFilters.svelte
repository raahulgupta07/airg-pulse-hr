<script>
	/**
	 * Job Poolsitory — Left rail filters with self-growing AI facets.
	 * Mirrors CandidateRailFilters but scoped to JD facet groups.
	 *
	 * AI facet types (jd_*): jd_skill, jd_dept, jd_location, jd_employment_type, jd_seniority.
	 * Persists selections to localStorage `hire_jd_facets`.
	 * Persists open/closed state to `hire_jd_rail_open`.
	 */
	let {
		// scope (mine/sector/global)
		scope = $bindable('mine'),
		scopeCounts = { mine: 0, sector: 0, global: 0 },
		onScopeChange = () => {},
		// state (active/draft/archived)
		stateFilter = $bindable('active'),
		stateCounts = { active: 0, draft: 0, archived: 0 },
		// AI facet groups payload from /api/facets/groups?domain=jd
		facetGroups = {},
		// per-group selections — Set<canonical>
		jdSkillSelected = $bindable(new Set()),
		jdDeptSelected = $bindable(new Set()),
		jdLocationSelected = $bindable(new Set()),
		jdEmploymentTypeSelected = $bindable(new Set()),
		jdSenioritySelected = $bindable(new Set()),
		// Called with facet id when user clicks a NEW row
		onDismissFacetNew = (_id) => {},
		// clear-all
		onClearAll = () => {},
	} = $props();

	const DEFAULT_OPEN = {
		scope: true, state: true,
		jd_dept: false, jd_location: false, jd_employment_type: false,
		jd_seniority: false, jd_skill: false,
	};
	let openMap = $state({ ...DEFAULT_OPEN });

	const AI_GROUPS = [
		{ key: 'jd_dept',            title: 'Department' },
		{ key: 'jd_location',        title: 'Location' },
		{ key: 'jd_employment_type', title: 'Employment' },
		{ key: 'jd_seniority',       title: 'Seniority' },
		{ key: 'jd_skill',           title: 'Skill' },
	];

	let aiShowAll = $state({ jd_skill: false, jd_dept: false, jd_location: false, jd_employment_type: false, jd_seniority: false });
	let aiQuery = $state({ jd_skill: '', jd_dept: '', jd_location: '', jd_employment_type: '', jd_seniority: '' });

	function aiSelectedSet(key) {
		switch (key) {
			case 'jd_skill':            return jdSkillSelected;
			case 'jd_dept':             return jdDeptSelected;
			case 'jd_location':         return jdLocationSelected;
			case 'jd_employment_type':  return jdEmploymentTypeSelected;
			case 'jd_seniority':        return jdSenioritySelected;
		}
		return new Set();
	}
	function aiSetSelectedSet(key, next) {
		switch (key) {
			case 'jd_skill':            jdSkillSelected = next; break;
			case 'jd_dept':             jdDeptSelected = next; break;
			case 'jd_location':         jdLocationSelected = next; break;
			case 'jd_employment_type':  jdEmploymentTypeSelected = next; break;
			case 'jd_seniority':        jdSenioritySelected = next; break;
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
			const map = JSON.parse(localStorage.getItem('hire_jd_facets') || '{}');
			map[key] = [...next];
			localStorage.setItem('hire_jd_facets', JSON.stringify(map));
		} catch {}
	}
	function aiRowsFor(key) {
		const grp = facetGroups?.[key];
		if (!grp) return [];
		const rowsTop = grp.top || [];
		const rowsNew = grp.new || [];
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
	function aiActive(key) { return aiSelectedSet(key).size > 0; }

	// Hydrate state from localStorage on mount
	$effect(() => {
		try {
			const raw = typeof localStorage !== 'undefined' ? localStorage.getItem('hire_jd_rail_open') : null;
			if (raw) {
				const parsed = JSON.parse(raw);
				if (parsed && typeof parsed === 'object') openMap = { ...DEFAULT_OPEN, ...parsed };
			}
		} catch {}
		try {
			const raw = typeof localStorage !== 'undefined' ? localStorage.getItem('hire_jd_facets') : null;
			if (raw) {
				const parsed = JSON.parse(raw) || {};
				if (Array.isArray(parsed.jd_skill))            jdSkillSelected           = new Set(parsed.jd_skill);
				if (Array.isArray(parsed.jd_dept))             jdDeptSelected            = new Set(parsed.jd_dept);
				if (Array.isArray(parsed.jd_location))         jdLocationSelected        = new Set(parsed.jd_location);
				if (Array.isArray(parsed.jd_employment_type))  jdEmploymentTypeSelected  = new Set(parsed.jd_employment_type);
				if (Array.isArray(parsed.jd_seniority))        jdSenioritySelected       = new Set(parsed.jd_seniority);
			}
		} catch {}
	});

	function toggleGroup(key) {
		openMap = { ...openMap, [key]: !openMap[key] };
		try { localStorage.setItem('hire_jd_rail_open', JSON.stringify(openMap)); } catch {}
	}

	const SCOPE_LABELS = { mine: 'Mine', sector: 'Sector', global: 'All' };
	const STATE_LABELS = { active: 'Active', draft: 'Draft', archived: 'Archived' };

	let scopeActive = $derived(scope !== 'mine');
	let stateActive = $derived(stateFilter !== 'active');

	let aiActiveCount = $derived(
		(jdSkillSelected.size > 0 ? 1 : 0) +
		(jdDeptSelected.size > 0 ? 1 : 0) +
		(jdLocationSelected.size > 0 ? 1 : 0) +
		(jdEmploymentTypeSelected.size > 0 ? 1 : 0) +
		(jdSenioritySelected.size > 0 ? 1 : 0)
	);

	let activeCount = $derived(
		(scopeActive ? 1 : 0) + (stateActive ? 1 : 0) + aiActiveCount
	);
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
					{id:'mine',   label:'Mine',   sub:'created by me'},
					{id:'sector', label:'Sector', sub:'my sector'},
					{id:'global', label:'All',    sub:'org-wide'},
				] as t}
					<label class="rail-radio" class:active={scope === t.id}>
						<input type="radio" name="jd-rail-scope" value={t.id} checked={scope === t.id}
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
					{id:'active',   label:'Active'},
					{id:'draft',    label:'Draft'},
					{id:'archived', label:'Archived'},
				] as s}
					<label class="rail-radio" class:active={stateFilter === s.id}>
						<input type="radio" name="jd-rail-state" value={s.id} checked={stateFilter === s.id}
							onchange={() => (stateFilter = s.id)} />
						<span class="dot dot-spacer"></span>
						<span class="rl">{s.label}</span>
						<span class="ct">{stateCounts[s.id] ?? 0}</span>
					</label>
				{/each}
			</div>
		</div>
	</section>

	<!-- AI FACET GROUPS -->
	{#each AI_GROUPS as g}
		{@const rows = aiRowsFor(g.key)}
		{@const total = facetGroups?.[g.key]?.total || 0}
		{@const visibleRows = aiShowAll[g.key] ? rows : rows.slice(0, 5)}
		<section class="acc" class:acc-active={aiActive(g.key)}>
			<button class="acc-h" type="button" onclick={() => toggleGroup(g.key)} aria-expanded={openMap[g.key]}>
				<span class="acc-title">{g.title} <span class="ai-pill">AI</span></span>
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
						<div class="ai-empty">No options yet — save more JDs.</div>
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
		box-shadow: 0 0 0 2px rgba(201,99,66,0.12);
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
