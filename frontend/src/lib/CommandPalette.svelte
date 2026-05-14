<script>
	import { goto } from '$app/navigation';
	import { apiJson } from '$lib/api';
	import { logout } from '$lib/auth';

	let open = $state(false);
	let query = $state('');
	let selectedIdx = $state(0);
	let recentPositions = $state([]);
	let recentCandidates = $state([]);
	let inputEl = $state(null);
	let listEl = $state(null);

	const NAV_ITEMS = [
		{ id: 'nav-positions', label: 'Positions', sublabel: 'Open roles', icon: 'work', kind: 'navigate', target: '/' },
		{ id: 'nav-jds', label: 'JD repo', sublabel: 'Job descriptions', icon: 'description', kind: 'navigate', target: '/jds' },
		{ id: 'nav-cvs', label: 'CV repo', sublabel: 'Candidates', icon: 'folder_shared', kind: 'navigate', target: '/candidates' },
		{ id: 'nav-analytics', label: 'Analytics', sublabel: 'Dashboards', icon: 'analytics', kind: 'navigate', target: '/analytics' },
		{ id: 'nav-chat', label: 'Copilot', sublabel: 'Chat with AI', icon: 'smart_toy', kind: 'navigate', target: '/chat' },
		{ id: 'nav-admin', label: 'Admin', sublabel: 'Settings & users', icon: 'admin_panel_settings', kind: 'navigate', target: '/admin' },
		{ id: 'nav-billing', label: 'Billing', sublabel: 'LLM cost ledger', icon: 'receipt_long', kind: 'navigate', target: '/billing' },
	];

	const ACTION_ITEMS = [
		{ id: 'act-upload-cv', label: 'Upload CV', sublabel: 'Add new resume', icon: 'upload_file', kind: 'action', run: () => { goto('/candidates'); setTimeout(() => document.getElementById('cv-upload')?.click(), 200); } },
		{ id: 'act-create-pos', label: 'Create position', sublabel: 'New role workspace', icon: 'add_circle', kind: 'action', run: () => goto('/?new=position') },
		{ id: 'act-new-jd', label: 'New JD', sublabel: 'Paste / save JD', icon: 'note_add', kind: 'action', run: () => goto('/jds?new=paste') },
		{ id: 'act-gen-jd', label: 'Generate JD with AI', sublabel: 'AI-write a JD', icon: 'auto_awesome', kind: 'action', run: () => goto('/jds?new=generate') },
		{ id: 'act-logout', label: 'Logout', sublabel: 'End session', icon: 'logout', kind: 'action', run: () => logout() },
	];

	function score(text, q) {
		if (!q) return 1;
		text = (text || '').toLowerCase();
		q = q.toLowerCase().trim();
		if (!text) return 0;
		if (text.includes(q)) return 100 - text.indexOf(q);
		const toks = q.split(/\s+/).filter(Boolean);
		let s = 0;
		for (const t of toks) {
			if (text.includes(t)) s += 10;
			else return 0;
		}
		return s;
	}

	let groups = $derived.by(() => {
		const q = query.trim();
		const navHits = NAV_ITEMS.map(it => ({ ...it, _s: score(it.label + ' ' + it.sublabel, q) })).filter(it => it._s > 0);
		const actHits = ACTION_ITEMS.map(it => ({ ...it, _s: score(it.label + ' ' + it.sublabel, q) })).filter(it => it._s > 0);
		const posHits = recentPositions.map(p => ({
			id: `pos-${p.slug || p.id}`,
			label: p.title || `Position ${p.id}`,
			sublabel: (p.department || '') + (p.seniority_level ? ' · ' + p.seniority_level : '') || 'Position',
			icon: 'work_outline',
			kind: 'position',
			target: `/positions/${p.slug || p.id}`,
			_s: score((p.title || '') + ' ' + (p.department || ''), q),
		})).filter(it => it._s > 0);
		const cvHits = recentCandidates.map(c => ({
			id: `cv-${c.id}`,
			label: c.name || `Candidate ${c.id}`,
			sublabel: c.current_role || c.email || 'Candidate',
			icon: 'person',
			kind: 'candidate',
			target: `/candidates/${c.id}`,
			_s: score((c.name || '') + ' ' + (c.current_role || '') + ' ' + (c.email || ''), q),
		})).filter(it => it._s > 0);
		const sort = (a, b) => b._s - a._s;
		return [
			{ key: 'navigate', label: 'Navigate', items: navHits.sort(sort) },
			{ key: 'positions', label: 'Positions', items: posHits.sort(sort).slice(0, 5) },
			{ key: 'candidates', label: 'Candidates', items: cvHits.sort(sort).slice(0, 5) },
			{ key: 'actions', label: 'Actions', items: actHits.sort(sort) },
		].filter(g => g.items.length > 0);
	});

	let flatItems = $derived(groups.flatMap(g => g.items));

	async function loadRecent() {
		try {
			const r = await apiJson('/positions?limit=5');
			recentPositions = Array.isArray(r) ? r : (r.positions || r.items || []);
		} catch { recentPositions = []; }
		try {
			const r = await apiJson('/candidates?limit=5');
			recentCandidates = Array.isArray(r) ? r : (r.candidates || r.items || []);
		} catch { recentCandidates = []; }
	}

	export function openPalette() {
		open = true;
		query = '';
		selectedIdx = 0;
		loadRecent();
		queueMicrotask(() => inputEl?.focus());
	}

	function close() {
		open = false;
		query = '';
		selectedIdx = 0;
	}

	function isTypingTarget(el) {
		if (!el) return false;
		const tag = el.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
	}

	function onGlobalKey(e) {
		if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			open ? close() : openPalette();
			return;
		}
		if (open && e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	function invoke(item) {
		close();
		if (item.kind === 'action' && typeof item.run === 'function') {
			setTimeout(() => item.run(), 0);
		} else if (item.target) {
			goto(item.target);
		}
	}

	function onInputKey(e) {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			if (flatItems.length) selectedIdx = (selectedIdx + 1) % flatItems.length;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			if (flatItems.length) selectedIdx = (selectedIdx - 1 + flatItems.length) % flatItems.length;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			const it = flatItems[selectedIdx];
			if (it) invoke(it);
		} else if (e.key === 'Tab') {
			e.preventDefault();
			// cycle to first item of next group
			if (!flatItems.length) return;
			let pos = 0;
			let groupStart = 0;
			for (const g of groups) {
				if (pos + g.items.length > selectedIdx) { break; }
				pos += g.items.length;
				groupStart = pos;
			}
			// next group start
			let acc = 0; let nextStart = 0;
			for (let i = 0; i < groups.length; i++) {
				if (acc > selectedIdx) { nextStart = acc; break; }
				acc += groups[i].items.length;
				if (acc > selectedIdx) {
					nextStart = (i + 1 < groups.length) ? acc : 0;
					break;
				}
			}
			selectedIdx = nextStart % flatItems.length;
		}
	}

	$effect(() => {
		if (typeof window === 'undefined') return;
		window.addEventListener('keydown', onGlobalKey);
		return () => window.removeEventListener('keydown', onGlobalKey);
	});

	// Reset selection on filter change
	$effect(() => {
		query;
		selectedIdx = 0;
	});

	// Scroll selected row into view
	$effect(() => {
		if (!open) return;
		queueMicrotask(() => {
			const el = listEl?.querySelector(`[data-flat-idx="${selectedIdx}"]`);
			el?.scrollIntoView({ block: 'nearest' });
		});
	});

	function isSelected(globalIdx) {
		return globalIdx === selectedIdx;
	}
</script>

{#if open}
	<div class="cp-overlay" onclick={close} role="presentation">
		<div class="cp-card" role="dialog" aria-label="Command palette" onclick={(e) => e.stopPropagation()}>
			<div class="cp-input-wrap">
				<span class="material-symbols-outlined cp-input-icon">search</span>
				<input
					bind:this={inputEl}
					bind:value={query}
					onkeydown={onInputKey}
					placeholder="Type a command or search..."
					class="cp-input"
					autocomplete="off"
					spellcheck="false"
				/>
				<span class="cp-esc">Esc</span>
			</div>
			<div class="cp-list" bind:this={listEl}>
				{#if groups.length === 0}
					<div class="cp-empty">No results</div>
				{:else}
					{#each groups as g, gi}
						{@const offset = groups.slice(0, gi).reduce((a, x) => a + x.items.length, 0)}
						<div class="cp-group-label">{g.label}</div>
						{#each g.items as it, ii}
							{@const gIdx = offset + ii}
							<button
								type="button"
								class="cp-row"
								class:cp-row-sel={isSelected(gIdx)}
								data-flat-idx={gIdx}
								onmouseenter={() => selectedIdx = gIdx}
								onclick={() => invoke(it)}
							>
								<span class="material-symbols-outlined cp-row-icon">{it.icon}</span>
								<span class="cp-row-text">
									<span class="cp-row-label">{it.label}</span>
									{#if it.sublabel}<span class="cp-row-sub">{it.sublabel}</span>{/if}
								</span>
								<span class="cp-row-enter">⏎</span>
							</button>
						{/each}
					{/each}
				{/if}
			</div>
			<div class="cp-foot">
				<span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
				<span><kbd>⏎</kbd> open</span>
				<span><kbd>Tab</kbd> next group</span>
				<span><kbd>Esc</kbd> close</span>
			</div>
		</div>
	</div>
{/if}

<style>
	.cp-overlay {
		position: fixed; inset: 0;
		background: rgba(44, 44, 44, 0.32);
		z-index: 9999;
		display: flex;
		justify-content: center;
		align-items: flex-start;
		padding-top: 12vh;
		backdrop-filter: blur(2px);
	}
	.cp-card {
		width: 600px;
		max-width: calc(100vw - 32px);
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius, 12px);
		box-shadow: var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.12));
		overflow: hidden;
		display: flex;
		flex-direction: column;
		max-height: 70vh;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}
	.cp-input-wrap {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.cp-input-icon { font-size: 18px; color: var(--color-muted, #6f6e69); }
	.cp-input {
		flex: 1;
		border: none;
		outline: none;
		background: transparent;
		font-size: 15px;
		color: var(--color-ink, #2c2c2c);
		font-family: inherit;
	}
	.cp-esc {
		font-size: 10px;
		padding: 2px 6px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 4px;
		color: var(--color-muted, #6f6e69);
		font-family: ui-monospace, SFMono-Regular, monospace;
	}
	.cp-list {
		flex: 1;
		overflow-y: auto;
		padding: 6px 0;
	}
	.cp-empty {
		padding: 24px;
		text-align: center;
		color: var(--color-muted, #6f6e69);
		font-size: 13px;
	}
	.cp-group-label {
		padding: 8px 16px 4px;
		font-size: 10.5px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-dim, #97968f);
	}
	.cp-row {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		padding: 9px 16px;
		background: transparent;
		border: none;
		text-align: left;
		cursor: pointer;
		font-family: inherit;
		color: var(--color-ink, #2c2c2c);
		transition: background 0.1s;
	}
	.cp-row-sel {
		background: var(--color-accent-soft, #fdebe1);
	}
	.cp-row-icon {
		font-size: 18px;
		color: var(--color-muted, #6f6e69);
		flex-shrink: 0;
	}
	.cp-row-sel .cp-row-icon { color: var(--color-accent-ink, #b04f30); }
	.cp-row-text {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.cp-row-label {
		font-size: 13.5px;
		font-weight: 500;
		color: var(--color-ink, #2c2c2c);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-row-sub {
		font-size: 11.5px;
		color: var(--color-muted, #6f6e69);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-row-enter {
		opacity: 0;
		font-size: 12px;
		color: var(--color-accent-ink, #b04f30);
		font-family: ui-monospace, SFMono-Regular, monospace;
	}
	.cp-row-sel .cp-row-enter { opacity: 1; }
	.cp-foot {
		display: flex;
		gap: 14px;
		padding: 8px 16px;
		border-top: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface-warm, #f4f3ee);
		font-size: 11px;
		color: var(--color-muted, #6f6e69);
	}
	.cp-foot kbd {
		display: inline-block;
		padding: 1px 5px;
		margin-right: 4px;
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 3px;
		font-family: ui-monospace, SFMono-Regular, monospace;
		font-size: 10px;
	}
</style>
