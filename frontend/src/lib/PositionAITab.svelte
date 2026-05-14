<script>
	/** Position AI Tab — auto-matched CVs from JD scan (orchestrator) */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';
	import { getToken } from '$lib/auth';
	import MatchRow from '$lib/ai-tab/MatchRow.svelte';
	import FilterChips from '$lib/ai-tab/FilterChips.svelte';
	import SortHeader from '$lib/ai-tab/SortHeader.svelte';
	import BulkActionBar from '$lib/ai-tab/BulkActionBar.svelte';

	let { slug, onOpenDrawer = () => {} } = $props();

	let scan = $state(null);
	let matches = $state([]);
	let position = $state(null);
	let loading = $state(true);
	let rescanning = $state(false);
	let pendingAction = $state({});
	let pollTimer = null;
	let sse = null;
	let mounted = false;

	let activeFilter = $state('all');
	let sortBy = $state('score');
	let sortDir = $state('desc');
	let selectedIds = $state(new Set());
	let focusedRow = $state(0);

	function emitCount(n) {
		if (typeof window !== 'undefined') {
			window.dispatchEvent(new CustomEvent('position-ai-count', { detail: { slug, count: n } }));
		}
	}

	let topScored = $state(null);  // { threshold, total_scored, n_above_threshold, top, suggested_threshold }
	let loadingTop = $state(false);
	let loweringThreshold = $state(false);

	async function loadTopScored() {
		loadingTop = true;
		try {
			topScored = await apiJson(`/positions/${slug}/ai/top-scored?limit=5`);
		} catch (e) { topScored = null; }
		finally { loadingTop = false; }
	}

	async function lowerThresholdAndRescan(newThreshold) {
		if (!confirm(`Lower match threshold from ${position?.min_match_score ?? 50}% to ${newThreshold}% and rescan?`)) return;
		loweringThreshold = true;
		try {
			await apiJson(`/positions/${slug}/weights`, {
				method: 'PUT',
				body: JSON.stringify({
					weight_skills: position.weight_skills ?? 40,
					weight_experience: position.weight_experience ?? 25,
					weight_education: position.weight_education ?? 10,
					weight_certifications: position.weight_certifications ?? 10,
					weight_industry: position.weight_industry ?? 15,
					min_match_score: newThreshold,
				}),
			});
			await rescan();
			topScored = null;
		} catch (e) { alert('Failed: ' + e.message); }
		finally { loweringThreshold = false; }
	}

	async function load() {
		try {
			const data = await apiJson(`/positions/${slug}/ai`);
			scan = data.scan || null;
			matches = data.matches || [];
			position = data.position || null;
		} catch (e) {
			scan = { status: 'error', error: e?.message || 'Failed to load AI matches' };
			matches = [];
		}
		loading = false;
		emitCount(matches.length);
		startStreamIfActive();
		// Auto-fetch top-scored explanation when we have a finished scan with no matches
		if (scan?.status === 'done' && (scan?.n_scored ?? 0) > 0 && matches.length === 0 && !topScored) {
			loadTopScored();
		}
	}

	function closeSse() {
		if (sse) { try { sse.close(); } catch {} sse = null; }
		if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
	}

	function startStreamIfActive() {
		closeSse();
		if (!mounted) return;
		const st = scan?.status;
		if (st !== 'running' && st !== 'queued') return;

		try {
			const token = getToken?.();
			const qs = token ? `?token=${encodeURIComponent(token)}` : '';
			const url = `/api/positions/${slug}/ai/events${qs}`;
			sse = new EventSource(url, { withCredentials: false });
			sse.addEventListener('scan', (ev) => {
				try {
					const data = JSON.parse(ev.data);
					scan = { ...(scan || {}), ...data };
					if (data.status === 'done') {
						closeSse();
						load();
					} else if (data.status === 'error') {
						closeSse();
					}
				} catch {}
			});
			sse.addEventListener('end', () => closeSse());
			sse.addEventListener('error', () => {
				closeSse();
				pollTimer = setTimeout(load, 2000);
			});
		} catch {
			pollTimer = setTimeout(load, 2000);
		}
	}

	async function rescan() {
		if (rescanning) return;
		rescanning = true;
		try {
			await apiJson(`/positions/${slug}/ai/rescan`, { method: 'POST' });
			scan = { ...(scan || {}), status: 'queued', n_scored: 0, n_matched: 0, error: null };
			await load();
		} catch (e) {
			scan = { ...(scan || {}), status: 'error', error: e?.message || 'Rescan failed' };
		}
		rescanning = false;
	}

	function emit(name, payload) {
		if (typeof window !== 'undefined') {
			window.dispatchEvent(new CustomEvent(name, { detail: payload }));
		}
	}

	async function addToPipeline(m) {
		const cid = m.candidate_id;
		if (pendingAction[cid]) return;
		pendingAction = { ...pendingAction, [cid]: 'adding' };
		try {
			await apiJson(`/positions/${slug}/ai/${cid}/promote`, { method: 'POST' });
			matches = matches.filter((x) => x.candidate_id !== cid);
			emit('position-ai-add', { slug, candidate_id: cid });
			emitCount(matches.length);
			await load();
		} catch (e) {
			alert(e?.message || 'Failed to add to pipeline');
		} finally {
			const next = { ...pendingAction };
			delete next[cid];
			pendingAction = next;
		}
	}

	async function rejectMatch(m) {
		const cid = m.candidate_id;
		if (pendingAction[cid]) return;
		pendingAction = { ...pendingAction, [cid]: 'rejecting' };
		try {
			await apiJson(`/positions/${slug}/ai/${cid}/reject`, { method: 'POST' });
			matches = matches.filter((x) => x.candidate_id !== cid);
			emit('position-ai-reject', { slug, candidate_id: cid });
			emitCount(matches.length);
			await load();
		} catch (e) {
			alert(e?.message || 'Failed to reject candidate');
		} finally {
			const next = { ...pendingAction };
			delete next[cid];
			pendingAction = next;
		}
	}

	async function bulkAddSelected() {
		const ids = Array.from(selectedIds);
		if (ids.length === 0) return;
		try {
			await apiJson(`/positions/${slug}/ai/bulk-promote`, {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: ids })
			});
			const idSet = new Set(ids);
			matches = matches.filter((m) => !idSet.has(m.candidate_id));
			ids.forEach((cid) => emit('position-ai-add', { slug, candidate_id: cid }));
		} catch (e) {
			console.warn('bulk promote failed', e);
			alert(e?.message || 'Bulk promote failed');
		}
		selectedIds = new Set();
		emitCount(matches.length);
		await load();
	}

	function toggleSelect(cid) {
		const next = new Set(selectedIds);
		if (next.has(cid)) next.delete(cid); else next.add(cid);
		selectedIds = next;
	}

	function toggleSelectAll() {
		const visIds = sortedFilteredMatches.map((m) => m.candidate_id);
		const allSel = visIds.length > 0 && visIds.every((id) => selectedIds.has(id));
		const next = new Set(selectedIds);
		if (allSel) {
			visIds.forEach((id) => next.delete(id));
		} else {
			visIds.forEach((id) => next.add(id));
		}
		selectedIds = next;
	}

	function clearSelection() { selectedIds = new Set(); }

	function fmtTs(ts) {
		if (!ts) return '—';
		try {
			const d = new Date(ts);
			const pad = (n) => String(n).padStart(2, '0');
			return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
		} catch { return ts; }
	}

	function getYrs(m) { return Number(m.years_experience ?? m.yrs_exp ?? m.experience_years ?? m.total_experience_years ?? 0) || 0; }
	function getLocation(m) { return (m.location || m.city || '').toString(); }
	function getAttachedAt(m) { return m.attached_at || m.created_at || null; }

	// Keyboard nav handler
	function handleKey(e) {
		// Skip when typing in inputs/textareas/contenteditable
		const t = e.target;
		if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
		if (e.metaKey || e.ctrlKey || e.altKey) return;

		const list = sortedFilteredMatches;
		if (!list.length) return;

		const k = e.key;
		if (k === 'j') {
			e.preventDefault();
			focusedRow = Math.min(focusedRow + 1, list.length - 1);
		} else if (k === 'k') {
			e.preventDefault();
			focusedRow = Math.max(focusedRow - 1, 0);
		} else if (k === 'Enter') {
			const m = list[focusedRow];
			if (m) {
				e.preventDefault();
				window.location.href = `/candidates/${m.candidate_id}`;
			}
		} else if (k === 'a') {
			const m = list[focusedRow];
			if (m) { e.preventDefault(); addToPipeline(m); }
		} else if (k === 'r') {
			const m = list[focusedRow];
			if (m) { e.preventDefault(); rejectMatch(m); }
		}
	}

	function handleReloadEvent(e) {
		const detail = e?.detail;
		if (detail && detail.slug && detail.slug !== slug) return;
		load();
	}

	$effect(() => {
		untrack(() => {
			mounted = true;
			load();
		});
		if (typeof window !== 'undefined') {
			window.addEventListener('keydown', handleKey);
			window.addEventListener('position-ai-reload', handleReloadEvent);
		}
		return () => {
			mounted = false;
			closeSse();
			if (typeof window !== 'undefined') {
				window.removeEventListener('keydown', handleKey);
				window.removeEventListener('position-ai-reload', handleReloadEvent);
			}
		};
	});

	let isScanning = $derived(scan?.status === 'running' || scan?.status === 'queued');
	let isError = $derived(scan?.status === 'error' || !!scan?.error);
	let isEmptyJd = $derived(!loading && !isError && !scan);

	let filteredMatches = $derived.by(() => {
		const arr = matches.slice();
		if (activeFilter === 'top10') return arr.slice(0, 10);
		if (activeFilter === 'above80') return arr.filter((m) => Number(m.score ?? 0) >= 80);
		if (activeFilter === 'newweek') {
			const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
			return arr.filter((m) => {
				const t = getAttachedAt(m);
				if (!t) return false;
				const ts = new Date(t).getTime();
				return !isNaN(ts) && ts >= cutoff;
			});
		}
		return arr;
	});

	let sortedFilteredMatches = $derived.by(() => {
		const arr = filteredMatches.slice();
		const dir = sortDir === 'asc' ? 1 : -1;
		arr.sort((a, b) => {
			let av, bv;
			if (sortBy === 'score') { av = Number(a.score ?? 0); bv = Number(b.score ?? 0); }
			else if (sortBy === 'yrs') { av = getYrs(a); bv = getYrs(b); }
			else if (sortBy === 'location') { av = getLocation(a).toLowerCase(); bv = getLocation(b).toLowerCase(); }
			else if (sortBy === 'added') {
				av = new Date(getAttachedAt(a) || 0).getTime();
				bv = new Date(getAttachedAt(b) || 0).getTime();
			} else { av = 0; bv = 0; }
			if (av < bv) return -1 * dir;
			if (av > bv) return 1 * dir;
			return 0;
		});
		return arr;
	});

	let selectedCount = $derived(selectedIds.size);
	let allVisibleSelected = $derived.by(() => {
		const ids = sortedFilteredMatches.map((m) => m.candidate_id);
		return ids.length > 0 && ids.every((id) => selectedIds.has(id));
	});

	let counts = $derived.by(() => {
		const all = matches.length;
		const top10 = Math.min(10, all);
		const above80 = matches.filter((m) => Number(m.score ?? 0) >= 80).length;
		const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
		const newThisWeek = matches.filter((m) => {
			const t = getAttachedAt(m);
			if (!t) return false;
			const ts = new Date(t).getTime();
			return !isNaN(ts) && ts >= cutoff;
		}).length;
		return { all, top10, above80, newThisWeek };
	});

	// Clamp focused row when list shrinks
	$effect(() => {
		const len = sortedFilteredMatches.length;
		untrack(() => {
			if (focusedRow >= len) focusedRow = Math.max(0, len - 1);
		});
	});
</script>

<div class="ai-tab animate-fade-up">

	{#if loading && !scan}
		<div class="ink-border stamp-shadow ai-loading">
			<div class="dark-title-bar">LOADING…</div>
			<div class="ai-loading-body">
				<div class="ai-spinner"></div>
				<div class="ai-loading-text">FETCHING AI SUGGESTIONS</div>
			</div>
		</div>

	{:else if isEmptyJd}
		<div class="ink-border stamp-shadow ai-empty">
			<div class="dark-title-bar">AI SUGGESTIONS</div>
			<div class="ai-empty-body">
				NO JD ON POSITION — ADD JD TO RUN MATCH AGENT
			</div>
		</div>

	{:else}
		<div class="ink-border stamp-shadow ai-header">
			<div class="ai-header-row">
				<div class="ai-summary">
					{#if isError}
						AI SCAN ERROR
					{:else if isScanning}
						SCANNING… {scan?.n_scored ?? 0} CVS PROCESSED
					{:else}
						SCANNED {scan?.n_scored ?? 0} CVS · {scan?.n_matched ?? matches.length} MATCHES · {fmtTs(scan?.finished_at || scan?.started_at)}
					{/if}
				</div>
				<button class="ai-rescan-btn" onclick={rescan} disabled={rescanning || isScanning}>
					{rescanning ? '[ … ]' : '[ RESCAN ]'}
				</button>
			</div>

			{#if isScanning}
				<div class="ai-progress-wrap">
					<div class="ai-progress-bar"></div>
				</div>
			{/if}
		</div>

		{#if isError}
			<div class="ink-border ai-alert">
				<div class="dark-title-bar ai-alert-bar">SCAN ERROR</div>
				<div class="ai-alert-body">
					{scan?.error || 'Unknown error'}
				</div>
			</div>
		{/if}

		{#if matches.length === 0 && !isScanning && !isError}
			<div class="ink-border ai-empty-list ai-empty-rich">
				{#if (scan?.n_scored ?? 0) === 0}
					<div class="ai-empty-title">CV repo is empty</div>
					<div class="ai-empty-sub">Upload CVs to start matching against this position.</div>
					<a href="/candidates" class="ai-empty-cta">Go to Talent Pool →</a>
				{:else}
					<div class="ai-empty-title">No CVs passed the {position?.min_match_score ?? 50}% match threshold</div>
					<div class="ai-empty-sub">
						Scanned {scan?.n_scored ?? 0} CV{(scan?.n_scored ?? 0) !== 1 ? 's' : ''}. None scored above {position?.min_match_score ?? 50}%.
						{#if topScored?.top?.length}
							 Highest match: <strong>{topScored.top[0].name}</strong> at <strong>{topScored.top[0].composite}%</strong>.
						{/if}
					</div>

					{#if loadingTop}
						<div style="margin-top: 12px; font-size: 11px; opacity: 0.7;">Computing top-scored CVs…</div>
					{:else if topScored?.top?.length}
						<div class="ai-top-scored">
							<div class="ai-top-scored-label">Top {topScored.top.length} CVs (below threshold)</div>
							{#each topScored.top as t}
								<div class="ai-top-row">
									<div class="ai-top-bar-wrap">
										<div class="ai-top-bar" style="width: {t.composite}%;"></div>
									</div>
									<div class="ai-top-score">{t.composite}%</div>
									<div class="ai-top-name">{t.name}</div>
									<div class="ai-top-role">{t.current_role || '—'}</div>
									<div class="ai-top-exp">{t.years_experience}y</div>
								</div>
							{/each}
						</div>

						{#if topScored.suggested_threshold}
							<div class="ai-empty-actions">
								<button class="ai-empty-cta" disabled={loweringThreshold}
									onclick={() => lowerThresholdAndRescan(topScored.suggested_threshold)}>
									{loweringThreshold ? 'Updating…' : `Lower threshold to ${topScored.suggested_threshold}% and rescan`}
								</button>
								<button class="ai-empty-cta-ghost" onclick={() => loadTopScored()}>Refresh scores</button>
							</div>
							<div class="ai-empty-hint">
								Why no matches? These CVs likely come from a different domain (skills, industry, or experience don't align with this JD). Lowering the threshold lets weaker matches through; alternatively, upload more relevant CVs or refine the JD.
							</div>
						{/if}
					{:else}
						<div style="margin-top: 12px;">
							<button class="ai-empty-cta-ghost" onclick={() => loadTopScored()}>Show top-scored CVs</button>
						</div>
					{/if}
				{/if}
			</div>
		{:else}
			<FilterChips
				bind:activeFilter
				{counts}
				visibleCount={sortedFilteredMatches.length}
				totalCount={matches.length} />

			<SortHeader
				bind:sortBy
				bind:sortDir
				{allVisibleSelected}
				onToggleSelectAll={toggleSelectAll} />

			<div class="ai-kbd-hint">KBD: J/K NAV · ENTER OPEN · A ADD · R REJECT</div>

			<div class="ai-match-list">
				{#each sortedFilteredMatches as m, i (m.candidate_id)}
					<MatchRow
						match={m}
						index={i}
						isPending={pendingAction[m.candidate_id] || null}
						isFocused={i === focusedRow}
						isSelected={selectedIds.has(m.candidate_id)}
						{position}
						onPromote={addToPipeline}
						onReject={rejectMatch}
						onToggleSelect={toggleSelect}
						onOpenDrawer={onOpenDrawer} />
				{/each}
			</div>
		{/if}
	{/if}
</div>

<BulkActionBar
	{selectedCount}
	onAddAll={bulkAddSelected}
	onClear={clearSelection} />

<style>
	.ai-tab {
		display: flex;
		flex-direction: column;
		gap: 16px;
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface, #383832);
	}

	.dark-title-bar {
		background: var(--color-on-surface, #383832);
		color: var(--color-surface, #feffd6);
		padding: 6px 12px;
		font-size: 11px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.ai-header { background: var(--color-surface-bright, #feffd6); }
	.ai-header-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 12px 16px;
		gap: 16px;
		flex-wrap: wrap;
	}
	.ai-summary {
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}
	.ai-rescan-btn {
		background: transparent;
		border: 2px solid var(--color-on-surface, #383832);
		border-right-width: 4px;
		border-bottom-width: 4px;
		padding: 6px 14px;
		font-family: inherit;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--color-on-surface, #383832);
		cursor: pointer;
		box-shadow: 4px 4px 0 0 rgba(0,0,0,0.15);
	}
	.ai-rescan-btn:hover:not(:disabled) { background: var(--color-accent, #c96342); color: #fff; }
	.ai-rescan-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.ai-progress-wrap {
		height: 6px;
		background: rgba(56,56,50,0.1);
		border-top: 2px solid var(--color-on-surface, #383832);
		overflow: hidden;
		position: relative;
	}
	.ai-progress-bar {
		position: absolute;
		left: 0; top: 0; bottom: 0;
		width: 30%;
		background: var(--color-accent, #c96342);
		animation: ai-slide 1.2s linear infinite;
	}
	@keyframes ai-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }

	.ai-loading-body {
		padding: 28px 20px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 14px;
		background: var(--color-surface-bright, #feffd6);
	}
	.ai-spinner {
		width: 28px;
		height: 28px;
		border: 4px solid var(--color-on-surface, #383832);
		border-top-color: var(--color-accent, #c96342);
		animation: ai-spin 0.9s linear infinite;
	}
	@keyframes ai-spin { to { transform: rotate(360deg); } }
	.ai-loading-text {
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.ai-empty-body, .ai-empty-list {
		padding: 28px 20px;
		text-align: center;
		font-size: 12px;
		font-weight: 900;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		background: var(--color-surface-bright, #feffd6);
	}
	.ai-empty-list { padding: 18px; opacity: 0.7; }

	.ai-alert {
		background: rgba(196,87,26,0.06);
		border-color: var(--color-error, #c4571a) !important;
	}
	.ai-alert-bar { background: var(--color-error, #c4571a); color: #fff; }
	.ai-alert-body { padding: 14px 16px; font-size: 12px; color: var(--color-error, #c4571a); font-weight: 700; }

	.ai-match-list { display: flex; flex-direction: column; gap: 12px; }

	.ai-kbd-hint {
		font-size: 9px;
		font-weight: 900;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		opacity: 0.55;
		padding: 2px 4px;
	}

	@media (max-width: 600px) {
		.ai-kbd-hint { display: none; }
	}

	/* ---- Rich empty state (no matches found) ---- */
	.ai-empty-rich {
		padding: 28px 32px !important;
		text-align: left !important;
		background: var(--color-surface-bright, #fff);
		border-radius: 10px;
	}
	.ai-empty-title {
		font-size: 16px; font-weight: 600; color: var(--color-on-surface, #2c2c2c);
		margin-bottom: 6px; letter-spacing: -0.01em;
	}
	.ai-empty-sub {
		font-size: 13px; color: var(--color-on-surface-dim, #6f6e69);
		line-height: 1.55;
	}
	.ai-top-scored {
		margin-top: 18px; padding-top: 16px;
		border-top: 1px solid var(--color-border, #e8e6dd);
	}
	.ai-top-scored-label {
		font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
		color: var(--color-on-surface-dim, #6f6e69); margin-bottom: 10px;
	}
	.ai-top-row {
		display: grid;
		grid-template-columns: 100px 44px 1.4fr 1.6fr 50px;
		gap: 12px; align-items: center;
		padding: 8px 0; font-size: 12.5px;
		border-bottom: 1px solid var(--color-border, #f0eee6);
	}
	.ai-top-row:last-child { border-bottom: none; }
	.ai-top-bar-wrap {
		height: 6px; background: var(--color-bg, #faf9f5);
		border-radius: 3px; overflow: hidden;
	}
	.ai-top-bar {
		height: 100%; background: var(--color-accent, #c96342);
		border-radius: 3px; transition: width 0.3s ease;
	}
	.ai-top-score { font-weight: 700; color: var(--color-accent, #c96342); }
	.ai-top-name { font-weight: 600; color: var(--color-on-surface, #2c2c2c); }
	.ai-top-role { color: var(--color-on-surface-dim, #6f6e69); font-size: 12px; }
	.ai-top-exp { color: var(--color-on-surface-dim, #6f6e69); font-size: 11px; text-align: right; }

	.ai-empty-actions {
		display: flex; gap: 10px; margin-top: 18px; flex-wrap: wrap;
	}
	.ai-empty-cta {
		padding: 9px 16px; font-size: 12.5px; font-weight: 600;
		background: var(--color-accent, #c96342); color: #fff;
		border: 1px solid var(--color-accent, #c96342); border-radius: 6px;
		cursor: pointer; text-decoration: none; display: inline-block;
	}
	.ai-empty-cta:hover:not(:disabled) { filter: brightness(0.95); }
	.ai-empty-cta:disabled { opacity: 0.6; cursor: not-allowed; }
	.ai-empty-cta-ghost {
		padding: 9px 16px; font-size: 12.5px; font-weight: 500;
		background: transparent; color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px;
		cursor: pointer;
	}
	.ai-empty-cta-ghost:hover { background: var(--color-bg, #faf9f5); }
	.ai-empty-hint {
		margin-top: 14px; font-size: 11.5px; color: var(--color-on-surface-dim, #6f6e69);
		line-height: 1.55; padding: 10px 12px;
		background: var(--color-bg, #faf9f5); border-radius: 6px;
	}

	@media (max-width: 700px) {
		.ai-top-row { grid-template-columns: 1fr 50px; gap: 6px; }
		.ai-top-bar-wrap, .ai-top-role, .ai-top-exp { display: none; }
	}
</style>
