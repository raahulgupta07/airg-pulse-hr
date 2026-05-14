<script>
	/** ToolTrace — collapsible per-tool box for chat v2 SSE agent traces.
	 *  Brutalist style: 2px ink border, 3px stamp shadow, zero radius, mono JSON. */
	import CheckCircle2 from '@lucide/svelte/icons/check-circle-2';
	import XCircle from '@lucide/svelte/icons/x-circle';
	import Hourglass from '@lucide/svelte/icons/hourglass';

	const TOOL_LABELS = {
		query_cvs: 'SEARCH CVS',
		get_candidate_brief: 'LOAD PROFILE',
		score_cv_vs_position: 'SCORE MATCH',
		list_candidate_pipeline: 'LIST PIPELINE',
		query_positions: 'SEARCH POSITIONS',
		get_position_brief: 'LOAD POSITION',
		get_pipeline: 'PIPELINE STATUS',
		query_brain: 'QUERY BRAIN',
		update_brain: 'SAVE LEARNING',
		query_funnel: 'QUERY FUNNEL',
		draft_email: 'DRAFT EMAIL',
	};

	let { tool } = $props();

	let expanded = $state(false);
	let outputExpanded = $state(false);
	let argsExpanded = $state(false);

	let label = $derived(TOOL_LABELS[tool?.name] || (tool?.name || 'TOOL').toUpperCase().replace(/_/g, ' '));
	let status = $derived(tool?.status || 'running');

	function statusIconComponent(s) {
		if (s === 'ok' || s === 'done') return CheckCircle2;
		if (s === 'error' || s === 'fail') return XCircle;
		return Hourglass;
	}

	function fmtMs(ms) {
		if (ms == null) return '—';
		if (ms < 1000) return `${Math.round(ms)}ms`;
		return `${(ms / 1000).toFixed(2)}s`;
	}

	function fmtCost(c) {
		if (c == null || c === 0) return '—';
		return '$' + (c < 0.001 ? c.toFixed(6) : c.toFixed(4));
	}

	function pretty(v) {
		if (v == null) return '';
		if (typeof v === 'string') return v;
		try {
			return JSON.stringify(v, null, 2);
		} catch {
			return String(v);
		}
	}

	const TRUNC = 1000;
	let argsStr = $derived(pretty(tool?.args));
	let outStr = $derived(pretty(tool?.output));
	let argsTruncated = $derived(argsStr.length > TRUNC);
	let outTruncated = $derived(outStr.length > TRUNC);
	let argsView = $derived(argsExpanded || !argsTruncated ? argsStr : argsStr.slice(0, TRUNC) + '…');
	let outView = $derived(outputExpanded || !outTruncated ? outStr : outStr.slice(0, TRUNC) + '…');
</script>

<div class="tt-wrap" class:tt-error={status === 'error' || status === 'fail'}>
	<button
		type="button"
		class="tt-header"
		onclick={() => (expanded = !expanded)}
		aria-expanded={expanded}
	>
		<span class="tt-icon tt-icon-{status}"><svelte:component this={statusIconComponent(status)} size={14} stroke-width={2} /></span>
		<span class="tt-name">{label}</span>
		<span class="tt-raw">{tool?.name || ''}</span>
		<span class="tt-spacer"></span>
		<span class="tt-meta tt-lat">{fmtMs(tool?.latency_ms)}</span>
		<span class="tt-meta tt-cost">{fmtCost(tool?.cost_usd)}</span>
		<span class="tt-chev">{expanded ? '▲' : '▼'}</span>
	</button>

	{#if expanded}
		<div class="tt-body">
			<div class="tt-section">
				<div class="tt-section-label">ARGS</div>
				<pre class="tt-json">{argsView || '—'}</pre>
				{#if argsTruncated}
					<button class="tt-more" type="button" onclick={() => (argsExpanded = !argsExpanded)}>
						{argsExpanded ? '— SHOW LESS' : '+ SHOW MORE'}
					</button>
				{/if}
			</div>
			<div class="tt-section">
				<div class="tt-section-label">OUTPUT</div>
				<pre class="tt-json">{outView || (status === 'running' ? 'WAITING…' : '—')}</pre>
				{#if outTruncated}
					<button class="tt-more" type="button" onclick={() => (outputExpanded = !outputExpanded)}>
						{outputExpanded ? '— SHOW LESS' : '+ SHOW MORE'}
					</button>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.tt-wrap {
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #d8d5cc);
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
		margin-bottom: 8px;
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 8px;
	}
	.tt-error {
		border-color: var(--color-error, #c4571a);
		box-shadow: 0 1px 3px rgba(196,87,26,0.15);
	}
	.tt-header {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 8px 12px;
		background: transparent;
		border: none;
		border-bottom: 1px solid var(--color-border, #d8d5cc);
		cursor: pointer;
		text-align: left;
		font-family: inherit;
		border-radius: 8px 8px 0 0;
	}
	.tt-wrap:not(:has(.tt-body)) .tt-header,
	.tt-wrap > .tt-header:only-child {
		border-bottom: none;
	}
	.tt-header:hover {
		background: var(--color-surface-highest, #f5f0eb);
	}
	.tt-icon {
		font-size: 13px;
		font-weight: 900;
		min-width: 14px;
		text-align: center;
	}
	.tt-icon-ok, .tt-icon-done { color: #3a8a4f; }
	.tt-icon-error, .tt-icon-fail { color: #ff3b30; }
	.tt-icon-running {
		color: #b8a000;
		animation: tt-pulse 1s infinite;
	}
	@keyframes tt-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
	.tt-name {
		font-family: 'JetBrains Mono', 'Space Mono', 'Menlo', monospace;
		font-weight: 900;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.tt-raw {
		font-family: 'JetBrains Mono', 'Space Mono', 'Menlo', monospace;
		font-size: 9px;
		opacity: 0.5;
		font-weight: 700;
	}
	.tt-spacer { flex: 1; }
	.tt-meta {
		font-family: 'JetBrains Mono', 'Space Mono', 'Menlo', monospace;
		font-size: 10px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.tt-lat { color: var(--color-on-surface-dim, #6f6e69); }
	.tt-cost { color: #3a8a4f; font-weight: 900; }
	.tt-chev {
		font-size: 9px;
		font-weight: 900;
		opacity: 0.7;
		min-width: 10px;
		text-align: center;
	}
	.tt-body {
		padding: 8px 12px 10px;
		background: var(--color-surface-highest, #f5f0eb);
		border-radius: 0 0 8px 8px;
	}
	.tt-section { margin-top: 6px; }
	.tt-section:first-child { margin-top: 0; }
	.tt-section-label {
		font-size: 9px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-bottom: 3px;
	}
	.tt-json {
		font-family: 'JetBrains Mono', 'Space Mono', 'Menlo', monospace;
		font-size: 11px;
		line-height: 1.45;
		background: #0d0f0c;
		color: #d6f5d6;
		padding: 8px 10px;
		margin: 0;
		max-height: 320px;
		overflow: auto;
		white-space: pre-wrap;
		word-break: break-word;
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 6px;
	}
	.tt-more {
		margin-top: 4px;
		background: transparent;
		border: 1px solid var(--color-border, #d8d5cc);
		padding: 2px 8px;
		font-family: 'JetBrains Mono', 'Space Mono', 'Menlo', monospace;
		font-size: 9px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		color: var(--color-on-surface-dim, #6f6e69);
		border-radius: 4px;
	}
	.tt-more:hover { background: var(--color-accent-soft, #f5ece8); }
</style>
