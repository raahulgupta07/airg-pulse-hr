<script>
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api';
	import Eye from '@lucide/svelte/icons/eye';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import Play from '@lucide/svelte/icons/play';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import Pause from '@lucide/svelte/icons/pause';
	import FileText from '@lucide/svelte/icons/file-text';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';

	let { onProcessComplete = () => {} } = $props();

	let pending = $state([]);
	let loading = $state(true);
	let selectedIds = $state(new Set());
	let activeTraces = $state({});      // { [cid]: run_id }
	let previewCid = $state(null);
	let previewType = $state('');

	// Track previous run states so we can fire onProcessComplete when a run finishes
	const prevRunState = new Map();

	// A5 — locally-dismissed DONE rows, persisted to localStorage
	const DISMISS_KEY = 'hire_dismissed_pending';
	let dismissed = $state(new Set());
	function loadDismissed() {
		if (typeof window === 'undefined') return;
		try {
			const raw = localStorage.getItem(DISMISS_KEY);
			if (raw) dismissed = new Set(JSON.parse(raw));
		} catch { /* ignore */ }
	}
	function saveDismissed() {
		if (typeof window === 'undefined') return;
		try { localStorage.setItem(DISMISS_KEY, JSON.stringify([...dismissed])); } catch { /* ignore */ }
	}
	function dismissRow(cid) {
		const s = new Set(dismissed);
		s.add(cid);
		dismissed = s;
		saveDismissed();
	}

	// A1 — status filter chips
	const FILTERS = ['ALL', 'PENDING', 'RUNNING', 'DONE', 'ERROR'];
	let activeFilter = $state('ALL');

	let pollInterval = null;

	async function load() {
		try {
			const data = await apiJson('/candidates/pending?include_recent=true');
			const next = data.candidates || [];
			// Detect transition: had running -> now done -> bubble up
			for (const c of next) {
				const r = c.latest_run || {};
				const prev = prevRunState.get(c.id);
				const wasRunning = !!prev?.has_running;
				const isDone =
					(r.total_steps && r.done_steps >= r.total_steps && !r.has_running) ||
					c.is_processed === true;
				if ((wasRunning || activeTraces[c.id]) && isDone) {
					try { onProcessComplete(c.id); } catch {}
					if (activeTraces[c.id]) {
						const t = { ...activeTraces };
						delete t[c.id];
						activeTraces = t;
					}
				}
				prevRunState.set(c.id, { has_running: !!r.has_running, done: isDone });
			}
			pending = next;
		} catch (e) { /* swallow */ }
		loading = false;
	}

	onMount(() => {
		loadDismissed();
		load();
		pollInterval = setInterval(load, 3000);
		return () => { if (pollInterval) clearInterval(pollInterval); };
	});

	function fmtSize(b) {
		if (!b) return '—';
		if (b < 1024) return `${b}B`;
		if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)}KB`;
		return `${(b / 1024 / 1024).toFixed(1)}MB`;
	}

	function fmtRel(iso) {
		if (!iso) return '—';
		const d = new Date(iso);
		const s = (Date.now() - d.getTime()) / 1000;
		if (s < 60) return `${Math.round(s)}s ago`;
		if (s < 3600) return `${Math.round(s / 60)}m ago`;
		if (s < 86400) return `${Math.round(s / 3600)}h ago`;
		return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function fmtMs(ms) {
		if (ms == null || ms === 0) return '';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(0)}s`;
	}
	function fmtCost(c) {
		if (c == null || c === 0) return '';
		return '$' + Number(c).toFixed(Number(c) < 0.001 ? 6 : 3);
	}

	function statusOf(c) {
		const r = c.latest_run || {};
		if (r.has_error) return { label: 'ERROR', cls: 'st-error', kind: 'ERROR' };
		if (r.has_running) return { label: `${r.done_steps}/13`, cls: 'st-running', kind: 'RUNNING' };
		const isDone = (r.total_steps && r.done_steps >= r.total_steps) || c.is_processed === true;
		if (isDone) {
			const dur = fmtMs(r.total_latency_ms);
			const cost = fmtCost(r.total_cost);
			const tail = [cost, dur].filter(Boolean).join(' ');
			const label = tail ? `done ${tail}` : 'done';
			return { label, cls: 'st-done', kind: 'DONE' };
		}
		return { label: 'PENDING', cls: 'st-pending', kind: 'PENDING' };
	}

	// Filtered/visible rows = pending minus dismissed, then by activeFilter chip
	let visible = $derived(
		pending
			.filter(c => !dismissed.has(c.id))
			.filter(c => activeFilter === 'ALL' || statusOf(c).kind === activeFilter)
	);

	async function runOne(cid) {
		try {
			const r = await apiJson(`/candidates/${cid}/process`, { method: 'POST' });
			activeTraces = { ...activeTraces, [cid]: r.run_id };
			setTimeout(load, 800);
		} catch (e) {
			alert(e.message || 'Run failed');
		}
	}

	async function retryOne(cid) {
		// A3 — error rows still have is_processed=false, so /process re-runs them
		try {
			const r = await apiJson(`/candidates/${cid}/process`, { method: 'POST' });
			activeTraces = { ...activeTraces, [cid]: r.run_id };
			setTimeout(load, 800);
		} catch (e) {
			alert(e.message || 'Retry failed');
		}
	}

	async function runSelected() {
		if (selectedIds.size === 0) return;
		try {
			const r = await apiJson('/candidates/bulk_process', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [...selectedIds] }),
			});
			activeTraces = { ...activeTraces, ...r.started };
			selectedIds = new Set();
			setTimeout(load, 800);
		} catch (e) { alert(e.message || 'Bulk run failed'); }
	}

	async function deleteOne(cid) {
		if (!confirm('Delete this uploaded file?')) return;
		try {
			await apiJson(`/candidates/${cid}`, { method: 'DELETE' });
			load();
		} catch (e) { alert(e.message || 'Delete failed'); }
	}

	function viewFile(c) {
		previewCid = c.id;
		previewType = (c.file_type || '').toLowerCase();
	}

	function toggleSel(cid) {
		const s = new Set(selectedIds);
		s.has(cid) ? s.delete(cid) : s.add(cid);
		selectedIds = s;
	}

	function toggleAll() {
		const ids = visible.map(c => c.id);
		if (selectedIds.size === ids.length) selectedIds = new Set();
		else selectedIds = new Set(ids);
	}
</script>

{#if visible.length > 0 || loading}
	<div class="ink-border stamp-shadow mb-4" style="background: var(--color-surface-bright);">
		<div class="dark-title-bar flex items-center justify-between">
			<span>PENDING FILES ({visible.length}) — uploaded &amp; recently processed</span>
			<div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
				{#each FILTERS as f}
					<button class="filter-chip" class:active={activeFilter === f}
						onclick={() => (activeFilter = f)}>{f}</button>
				{/each}
				{#if selectedIds.size > 0}
					<button onclick={runSelected}
						style="background: var(--color-primary-container); color: var(--color-on-surface); border: none; padding: 4px 12px; font-size: 11px; cursor: pointer; font-weight: 900; display: inline-flex; align-items: center; gap: 4px;">
						<Play size={12} strokeWidth={1.75} /> RUN {selectedIds.size}
					</button>
				{/if}
				<button onclick={() => document.getElementById('cv-upload')?.click()}
					style="background: transparent; color: var(--color-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 10px; cursor: pointer; font-weight: 700;">
					+ Upload more
				</button>
			</div>
		</div>
		<div style="padding: 0;">
			<table style="width: 100%; border-collapse: collapse; font-size: 12px;">
				<thead>
					<tr style="background: var(--color-on-surface); color: var(--color-surface);">
						<th style="padding: 8px 10px; width: 28px;">
							<input type="checkbox" checked={selectedIds.size === visible.length && visible.length > 0}
								onchange={toggleAll} aria-label="select all" />
						</th>
						<th style="padding: 8px 10px; text-align: left;">FILE</th>
						<th style="padding: 8px 10px; text-align: center;">TYPE</th>
						<th style="padding: 8px 10px; text-align: center;">SIZE</th>
						<th style="padding: 8px 10px; text-align: center;">UPLOADED</th>
						<th style="padding: 8px 10px; text-align: center;">STATUS</th>
						<th style="padding: 8px 10px; text-align: right;">ACTIONS</th>
					</tr>
				</thead>
				<tbody>
					{#each visible as c (c.id)}
						{@const st = statusOf(c)}
						<tr style="border-top: 1px solid rgba(56,56,50,0.15); background: var(--color-surface);">
							<td style="padding: 8px 10px;">
								<input type="checkbox" checked={selectedIds.has(c.id)} onchange={() => toggleSel(c.id)} />
							</td>
							<td style="padding: 8px 10px;">
								<div style="font-weight: 700; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
									{c.file_name || c.name || `cv-${c.id}`}
								</div>
								{#if c.processing_error}
									<div style="font-size: 10px; color: var(--color-error); margin-top: 2px;">{c.processing_error}</div>
								{/if}
							</td>
							<td style="padding: 8px 10px; text-align: center;">
								<span class="ink-border" style="display: inline-block; padding: 2px 8px; font-size: 10px; font-weight: 700; background: var(--color-surface-bright); text-transform: uppercase;">
									{(c.file_type || '?').toUpperCase()}
								</span>
							</td>
							<td style="padding: 8px 10px; text-align: center; font-variant-numeric: tabular-nums;">{fmtSize(c.file_size)}</td>
							<td style="padding: 8px 10px; text-align: center; font-size: 11px;">{fmtRel(c.created_at)}</td>
							<td style="padding: 8px 10px; text-align: center;">
								<span class="status-pill {st.cls}" style="display: inline-flex; align-items: center; gap: 4px;">
									{#if st.kind === 'ERROR'}<AlertTriangle size={11} strokeWidth={1.75} />{:else if st.kind === 'RUNNING'}<Hourglass size={11} strokeWidth={1.75} />{:else if st.kind === 'DONE'}<Check size={11} strokeWidth={1.75} />{:else}<Pause size={11} strokeWidth={1.75} />{/if}
									{st.label}
								</span>
							</td>
							<td style="padding: 8px 10px; text-align: right; white-space: nowrap;">
								<button onclick={() => viewFile(c)} title="Preview file"
									style="background: var(--color-surface-bright); border: 2px solid var(--color-on-surface); padding: 3px 8px; font-size: 11px; cursor: pointer; margin-right: 4px; display: inline-flex; align-items: center; gap: 4px;"><Eye size={12} strokeWidth={1.75} /> VIEW</button>

								{#if st.kind === 'DONE'}
									<a href={`/candidates/${c.id}`}
										style="background: var(--color-primary-container); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 4px 12px; font-size: 11px; font-weight: 900; cursor: pointer; margin-right: 4px; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;">
										PROFILE
									</a>
									<button onclick={() => dismissRow(c.id)} title="Dismiss row"
										style="background: transparent; border: 2px solid var(--color-on-surface); color: var(--color-on-surface); padding: 3px 8px; font-size: 11px; cursor: pointer; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;"><X size={11} strokeWidth={1.75} /> DISMISS</button>
								{:else if st.kind === 'ERROR'}
									<button onclick={() => retryOne(c.id)}
										style="background: var(--color-primary-container); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 4px 12px; font-size: 11px; font-weight: 900; cursor: pointer; margin-right: 4px; display: inline-flex; align-items: center; gap: 4px;">
										<RefreshCw size={11} strokeWidth={1.75} /> RETRY
									</button>
									<button onclick={() => deleteOne(c.id)} title="Delete"
										style="background: transparent; border: 2px solid var(--color-error); color: var(--color-error); padding: 3px 8px; font-size: 11px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;"><X size={11} strokeWidth={1.75} /> DISMISS</button>
								{:else if st.kind === 'RUNNING'}
									<button onclick={() => deleteOne(c.id)} title="Delete"
										style="background: transparent; border: 2px solid var(--color-error); color: var(--color-error); padding: 3px 8px; font-size: 11px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;"><X size={11} strokeWidth={1.75} /> DISMISS</button>
								{:else}
									<button onclick={() => runOne(c.id)}
										style="background: var(--color-primary-container); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 4px 12px; font-size: 11px; font-weight: 900; cursor: pointer; margin-right: 4px; display: inline-flex; align-items: center; gap: 4px;">
										<Play size={11} strokeWidth={1.75} /> RUN
									</button>
									<button onclick={() => deleteOne(c.id)} title="Delete"
										style="background: transparent; border: 2px solid var(--color-error); color: var(--color-error); padding: 3px 8px; font-size: 11px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;"><X size={11} strokeWidth={1.75} /> DISMISS</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{/if}

{#if previewCid}
	<div role="dialog" aria-modal="true"
		style="position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 10000; display: flex; align-items: center; justify-content: center; padding: 24px;"
		onclick={(e) => { if (e.target === e.currentTarget) previewCid = null; }}
		onkeydown={(e) => { if (e.key === 'Escape') previewCid = null; }}>
		<div class="ink-border stamp-shadow" style="background: var(--color-surface); width: min(900px, 95vw); height: min(85vh, 800px); display: flex; flex-direction: column;">
			<div class="dark-title-bar flex items-center justify-between" style="flex-shrink: 0;">
				<span>FILE PREVIEW · candidate #{previewCid}</span>
				<button onclick={() => (previewCid = null)} style="background: transparent; color: var(--color-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 11px; cursor: pointer; font-weight: 700; display: inline-flex; align-items: center;"><X size={12} strokeWidth={1.75} /></button>
			</div>
			<div style="flex: 1; overflow: auto; background: #fafafa; display: flex; align-items: center; justify-content: center;">
				{#if ['png','jpg','jpeg','webp'].includes(previewType)}
					<img src={`/api/candidates/${previewCid}/file`} alt="preview" style="max-width: 100%; max-height: 100%; object-fit: contain;" />
				{:else if previewType === 'pdf'}
					<iframe src={`/api/candidates/${previewCid}/file`} title="pdf" style="width: 100%; height: 100%; border: none;"></iframe>
				{:else}
					<div style="padding: 40px; text-align: center; opacity: 0.6; display: flex; align-items: center; justify-content: center; gap: 6px;"><FileText size={20} strokeWidth={1.75} /> No preview for {previewType}</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.status-pill {
		display: inline-block;
		padding: 3px 10px;
		font-size: 10px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border: 2px solid var(--color-on-surface);
	}
	.st-pending  { background: var(--color-surface-bright); color: var(--color-on-surface); }
	.st-running  { background: #ffcc00; color: var(--color-on-surface); border-color: var(--color-on-surface); }
	.st-done     { background: var(--color-on-surface); color: var(--color-surface); }
	.st-error    { background: var(--color-error, #cc3333); color: white; border-color: var(--color-error, #cc3333); }
	.st-skipped  { background: #ddd; color: var(--color-on-surface); }
	tr:hover { background: rgba(0,117,24,0.05) !important; }

	.filter-chip {
		background: transparent;
		color: var(--color-surface);
		border: 1px solid var(--color-surface);
		padding: 3px 8px;
		font-size: 10px;
		font-weight: 700;
		cursor: pointer;
		letter-spacing: 0.05em;
	}
	.filter-chip.active {
		background: var(--color-surface);
		color: var(--color-on-surface);
	}
</style>
