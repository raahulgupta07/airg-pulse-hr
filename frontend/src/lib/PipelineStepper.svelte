<script>
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';

	let { candidateId, runId = null, live = false, onComplete = () => {} } = $props();
	let _completedFired = false;

	let runs = $state([]);
	let loading = $state(true);
	let errorMsg = $state('');
	let pollInterval = null;
	let pollStart = 0;
	let collapsed = $state(false);     // E1 — auto-collapse 5s after all terminal
	let collapseTimer = null;

	const ALL_STEPS = [
		{ order: 1,  name: 'CLASSIFY' },
		{ order: 2,  name: 'EXTRACT' },
		{ order: 25, name: 'VERIFY' },
		{ order: 3,  name: 'SCREENSHOTS' },
		{ order: 4,  name: 'STRUCTURE' },
		{ order: 5,  name: 'ENRICH' },
		{ order: 6,  name: 'SAVE' },
		{ order: 7,  name: 'KNOWLEDGE' },
		{ order: 8,  name: 'HYPE_EMBED' },
		{ order: 9,  name: 'CONTEXT_EMBED' },
		{ order: 10, name: 'QUALITY' },
		{ order: 11, name: 'TAG' },
		{ order: 12, name: 'AUTO_MATCH' }
	];

	const TERMINAL = new Set(['done', 'error', 'skipped']);

	async function fetchTrace() {
		try {
			const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
			const data = await apiJson(`/candidates/${candidateId}/pipeline_trace${qs}`);
			runs = data.runs || [];
			errorMsg = '';
		} catch (e) {
			errorMsg = e.message || 'Failed to load trace';
		}
		loading = false;
	}

	function allTerminal(steps) {
		if (!steps || steps.length === 0) return false;
		return steps.every(s => TERMINAL.has(s.status));
	}

	$effect(() => {
		// re-run when candidateId or runId changes
		candidateId; runId;
		untrack(() => {
		loading = true;
		fetchTrace();
		if (live) {
			pollStart = Date.now();
			if (pollInterval) clearInterval(pollInterval);
			pollInterval = setInterval(async () => {
				await fetchTrace();
				const cur = runs[0];
				const elapsed = Date.now() - pollStart;
				if ((cur && allTerminal(cur.steps)) || elapsed > 90000) {
					clearInterval(pollInterval);
					pollInterval = null;
					if (!_completedFired) {
						_completedFired = true;
						try { onComplete(cur || null); } catch {}
					}
					// E1 — auto-collapse 5s after pipeline reaches terminal state
					if (cur && allTerminal(cur.steps) && !collapseTimer) {
						collapseTimer = setTimeout(() => { collapsed = true; }, 5000);
					}
				}
			}, 900);
		} else {
			// non-live (re-opened trace on a finished run): collapse immediately for tidiness
			// but only after first fetch resolves; effect re-runs handle that.
		}
		});
		return () => {
			if (pollInterval) clearInterval(pollInterval);
			pollInterval = null;
			if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = null; }
		};
	});

	function statusIcon(status) {
		switch (status) {
			case 'done':    return { ch: '✓', cls: 'st-done' };
			case 'running': return { ch: '⏳', cls: 'st-running' };
			case 'error':   return { ch: '✗', cls: 'st-error' };
			case 'skipped': return { ch: '⊘', cls: 'st-skipped' };
			default:        return { ch: '☐', cls: 'st-pending' };
		}
	}

	function shortModel(m) {
		if (!m) return '';
		const parts = m.split('/');
		const last = parts[parts.length - 1];
		return last.replace('-preview', '').replace('-latest', '');
	}

	function isVisionModel(m) {
		if (!m) return false;
		return m.includes('opus') || m.includes('claude') || m.includes('gemini-3-flash') || m.includes('vision');
	}

	function fmtCost(c) {
		if (c == null || c === 0) return '';
		return '$' + c.toFixed(c < 0.001 ? 6 : 4);
	}

	function fmtMs(ms) {
		if (ms == null) return '';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms/1000).toFixed(1)}s`;
	}

	// Merge backend steps with skeleton so all 13 always show
	function mergedSteps(backendSteps) {
		const map = new Map();
		for (const s of (backendSteps || [])) map.set(s.step_order, s);
		return ALL_STEPS.map(skel => {
			const found = map.get(skel.order);
			if (found) return found;
			return {
				step_order: skel.order,
				step_name: skel.name,
				status: 'pending',
				model: null,
				latency_ms: null,
				cost_usd: null,
				details: null
			};
		});
	}

	let currentRun = $derived(runs[0] || null);
	let mergedCurrent = $derived(currentRun ? mergedSteps(currentRun.steps) : mergedSteps([]));
	let runStartTs = $derived(
		currentRun?.started_at ? new Date(currentRun.started_at).getTime() :
		(currentRun?.steps?.[0]?.started_at ? new Date(currentRun.steps[0].started_at).getTime() : Date.now())
	);
	function fmtRelTs(iso) {
		if (!iso) return '--:--.-';
		const t = new Date(iso).getTime();
		const sec = Math.max(0, (t - runStartTs) / 1000);
		const m = Math.floor(sec / 60).toString().padStart(2, '0');
		const s = (sec % 60).toFixed(1).padStart(4, '0');
		return `${m}:${s}`;
	}
	function detailSummary(s) {
		const d = s.details || {};
		if (s.step_name === 'CLASSIFY' && d.file_type) return d.file_type;
		if (s.step_name === 'EXTRACT' && d.chars) return `${d.chars} chars`;
		if (s.step_name === 'VERIFY' && Array.isArray(d.fields_overridden)) return d.fields_overridden.join(' ') || 'no overrides';
		if (s.step_name === 'SCREENSHOTS' && d.count != null) return `${d.count} image${d.count===1?'':'s'}`;
		if (s.step_name === 'STRUCTURE' && d.name) return d.name;
		if (s.step_name === 'ENRICH' && d.seniority) return d.seniority;
		if (s.step_name === 'KNOWLEDGE' && d.pairs != null) return `${d.pairs} pairs`;
		if (s.step_name === 'HYPE_EMBED' && d.n_chunks != null) return `${d.n_chunks} chunks`;
		if (s.step_name === 'QUALITY' && d.score != null) return String(d.score);
		if (s.step_name === 'TAG' && Array.isArray(d.tags)) return `[${d.tags.join(', ')}]`;
		if (s.step_name === 'AUTO_MATCH' && (d.n_matched != null || d.n_positions != null)) return `${d.n_matched ?? 0}/${d.n_positions ?? 0} positions`;
		if (s.step_name === 'SAVE') return 'done';
		return s.status === 'done' ? 'done' : '';
	}
	// E2 — compute running totals from the steps themselves so they tick up during run
	let liveCost = $derived(
		mergedCurrent.reduce((acc, s) => acc + (Number(s.cost_usd) || 0), 0)
	);
	let liveLatency = $derived(
		mergedCurrent.reduce((acc, s) => acc + (Number(s.latency_ms) || 0), 0)
	);
	let totalCost = $derived(currentRun?.total_cost ?? liveCost);
	let totalLatency = $derived(currentRun?.total_latency_ms ?? liveLatency);
	let doneCount = $derived(mergedCurrent.filter(s => TERMINAL.has(s.status)).length);
	let totalCount = $derived(mergedCurrent.length);
	let runShort = $derived(currentRun?.run_id ? currentRun.run_id.slice(0, 8) : '—');
	let allDone = $derived(currentRun ? allTerminal(currentRun.steps) : false);

	function expandAgain() { collapsed = false; }
</script>

<div class="pt-wrap ink-border stamp-shadow">
	{#if collapsed && allDone}
		<button class="pt-collapsed-summary" onclick={expandAgain} title="click to expand">
			<span>✓ {doneCount}/{totalCount} done</span>
			<span class="pt-sep">·</span>
			<span>{fmtCost(totalCost) || '$0'}</span>
			<span class="pt-sep">·</span>
			<span>{fmtMs(totalLatency) || '0ms'}</span>
			<span class="pt-sep">·</span>
			<span class="pt-hint">click to expand</span>
		</button>
	{:else}
	<div class="pt-header">
		<span class="pt-title">✦ PIPELINE TRACE — run {runShort}…</span>
		<span class="pt-summary">
			Total so far: <b>{fmtCost(totalCost) || '$0'}</b> · {fmtMs(totalLatency) || '0ms'} · {doneCount}/{totalCount} steps
			{#if allDone}
				<button class="pt-collapse-btn" onclick={() => (collapsed = true)} title="collapse">⌃ COLLAPSE</button>
			{/if}
		</span>
	</div>

	{#if loading && !currentRun}
		<div class="pt-empty">Loading trace…</div>
	{:else if errorMsg}
		<div class="pt-empty pt-error">No trace recorded yet.</div>
	{:else if !currentRun}
		<div class="pt-empty">No trace recorded yet.</div>
	{:else}
		<div class="cli-body">
			{#each mergedCurrent as s}
				{@const ic = statusIcon(s.status)}
				<div class="cli-line cli-{s.status}">
					<span class="cli-ts">[{fmtRelTs(s.started_at || s.finished_at)}]</span>
					<span class="cli-step">{(s.step_name || '').padEnd(13, ' ')}</span>
					<span class="cli-icon {ic.cls}">{ic.ch}</span>
					<span class="cli-model">{s.model ? shortModel(s.model) : (s.status === 'pending' ? '' : '—')}</span>
					<span class="cli-detail">{detailSummary(s)}</span>
					<span class="cli-lat">{fmtMs(s.latency_ms)}</span>
					<span class="cli-cost">{fmtCost(s.cost_usd)}</span>
				</div>
				{#if s.error_msg}
					<div class="cli-line cli-err">                ↳ {s.error_msg}</div>
				{/if}
			{/each}
			{#if allDone && currentRun}
				<div class="cli-summary">
					─────────────────────────────────────────────────────────────────
				</div>
				<div class="cli-line cli-done">
					<span class="cli-icon st-done">✓</span>
					<span class="cli-step">{doneCount}/{totalCount} done</span>
					<span class="cli-detail">{fmtCost(totalCost)} · {fmtMs(totalLatency)}</span>
				</div>
			{/if}
		</div>
	{/if}
	{/if}
</div>

<style>
	.pt-wrap {
		background: var(--color-bg, #faf9f5);
		font-family: 'Space Grotesk', monospace;
		color: var(--color-on-surface, #2c2c2c);
	}
	.pt-header {
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		padding: 8px 12px;
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 900;
	}
	.pt-title { font-weight: 900; }
	.pt-summary { font-weight: 700; opacity: 0.9; }
	.pt-body { padding: 4px 0; }

	/* === Terminal CLI style === */
	.cli-body {
		background: #0d0f0c;
		color: #d6f5d6;
		font-family: 'JetBrains Mono', 'Space Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
		font-size: 12px;
		line-height: 1.6;
		padding: 10px 14px;
		max-height: 480px;
		overflow-y: auto;
	}
	.cli-line {
		display: grid;
		grid-template-columns: 70px 130px 16px 180px 1fr 60px 80px;
		gap: 8px;
		padding: 1px 0;
		white-space: nowrap;
		align-items: baseline;
	}
	.cli-ts     { color: #6da06d; }
	.cli-step   { color: #3a8a4f; font-weight: 700; }
	.cli-icon   { text-align: center; font-weight: 900; }
	.cli-icon.st-done    { color: #3a8a4f; }
	.cli-icon.st-running { color: #ffcc00; animation: cli-pulse 1s infinite; }
	.cli-icon.st-error   { color: #ff5050; }
	.cli-icon.st-skipped { color: #777; }
	.cli-icon.st-pending { color: #444; }
	.cli-model  { color: #80b3ff; overflow: hidden; text-overflow: ellipsis; }
	.cli-detail { color: #d6f5d6; opacity: 0.85; overflow: hidden; text-overflow: ellipsis; }
	.cli-lat    { color: #c0c0c0; text-align: right; }
	.cli-cost   { color: #ffcc00; text-align: right; }
	.cli-line.cli-pending { opacity: 0.45; }
	.cli-line.cli-running { background: rgba(255,204,0,0.08); }
	.cli-line.cli-error   { background: rgba(255,80,80,0.12); }
	.cli-summary { color: #444; padding: 4px 0; font-family: monospace; }
	.cli-line.cli-done .cli-step { color: #3a8a4f; }
	.cli-err { color: #ff8080; padding-left: 80px; }
	@keyframes cli-pulse {
		0%, 100% { opacity: 1; }
		50%      { opacity: 0.4; }
	}
	.pt-row {
		display: grid;
		grid-template-columns: 24px 28px 1fr auto auto auto;
		gap: 10px;
		padding: 6px 12px;
		font-size: 12px;
		font-weight: 700;
		align-items: center;
		border-bottom: 1px dashed rgba(56,56,50,0.15);
	}
	.pt-row:last-child { border-bottom: none; }
	.pt-row-running {
		background: rgba(58,138,79,0.08);
	}
	.pt-icon {
		font-weight: 900;
		text-align: center;
		font-size: 14px;
	}
	.st-done    { color: #3a8a4f; }
	.st-running { color: #3a8a4f; animation: pulse 1s infinite; }
	.st-error   { color: var(--color-error, #c4571a); }
	.st-skipped { color: #888; }
	.st-pending { color: #bbb; }
	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}
	.pt-num {
		font-weight: 900;
		color: var(--color-on-surface, #2c2c2c);
		opacity: 0.6;
		text-align: right;
	}
	.pt-name {
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.pt-model {
		font-size: 10px;
		font-weight: 700;
		padding: 2px 6px;
		border: 1px solid var(--color-border, #d8d5cc);
		background: var(--color-surface-bright, #fff);
		text-transform: lowercase;
		letter-spacing: 0;
		white-space: nowrap;
		border-radius: 4px;
	}
	.pt-model-vision {
		background: var(--color-accent, #c96342);
		color: #fff;
	}
	.pt-model-muted {
		background: transparent;
		opacity: 0.55;
		font-style: italic;
	}
	.pt-model-blank { width: 1px; }
	.pt-lat {
		font-size: 11px;
		color: var(--color-on-surface, #2c2c2c);
		opacity: 0.75;
		min-width: 50px;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.pt-cost {
		font-size: 11px;
		color: #3a8a4f;
		font-weight: 900;
		min-width: 70px;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.pt-empty {
		padding: 24px;
		text-align: center;
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		opacity: 0.6;
	}
	.pt-error { color: var(--color-error, #c4571a); }
	.pt-collapsed-summary {
		width: 100%;
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		border: none;
		padding: 10px 14px;
		font-family: 'Space Grotesk', monospace;
		font-size: 12px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		display: flex;
		gap: 10px;
		align-items: center;
		cursor: pointer;
		text-align: left;
	}
	.pt-collapsed-summary:hover { background: #3a3a34; }
	.pt-sep { opacity: 0.5; }
	.pt-hint { opacity: 0.7; font-weight: 700; margin-left: auto; font-size: 10px; }
	.pt-collapse-btn {
		background: transparent;
		border: 1px solid rgba(255,255,255,0.6);
		color: rgba(255,255,255,0.8);
		padding: 2px 8px;
		font-size: 10px;
		font-weight: 700;
		margin-left: 10px;
		cursor: pointer;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border-radius: 4px;
	}
	.pt-collapse-btn:hover { background: rgba(255,255,255,0.15); }
	.pt-err {
		font-size: 10px;
		color: var(--color-error, #c4571a);
		padding: 0 12px 6px 60px;
		font-style: italic;
	}
</style>
