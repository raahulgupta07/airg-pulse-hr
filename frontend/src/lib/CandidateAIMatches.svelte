<script>
	/** CandidateAIMatches — surface AI-generated position matches for a candidate.
	 *
	 * Props:
	 *   candidateId: string|number — candidate id
	 *   mode: 'compact' (top 3, no breakdown bars) | 'full' (all up to 50, full breakdown)
	 */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';

	let { candidateId, mode = 'full' } = $props();

	let recs = $state([]);
	let loading = $state(true);
	let error = $state('');
	let mounted = false;

	const DIMS = [
		{ key: 'match_score_skills', label: 'Skills' },
		{ key: 'match_score_experience', label: 'Experience' },
		{ key: 'match_score_industry', label: 'Industry' },
		{ key: 'match_score_education', label: 'Education' },
		{ key: 'match_score_certifications', label: 'Certs' },
		{ key: 'match_score_culture', label: 'Culture' },
		{ key: 'match_score_competencies', label: 'Comps' },
	];

	function emitCount(n) {
		if (typeof window !== 'undefined') {
			window.dispatchEvent(new CustomEvent('candidate-ai-count', {
				detail: { candidateId, count: n }
			}));
		}
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const data = await apiJson(`/candidates/${candidateId}/ai-recommendations`);
			recs = Array.isArray(data) ? data : (data?.recommendations || data?.items || []);
		} catch (e) {
			error = e?.message || 'Failed to load AI recommendations';
			recs = [];
		}
		loading = false;
		emitCount(recs.length);
	}

	$effect(() => {
		const cid = candidateId;
		if (!cid) return;
		untrack(() => {
			mounted = true;
			load();
		});
	});

	function scoreColor(s) {
		const n = Number(s) || 0;
		if (n >= 70) return '#3a8a4f';
		if (n >= 40) return 'var(--color-warning, #c98c2a)';
		return 'var(--color-error, #c4571a)';
	}
	function fmtScore(s) {
		const n = Number(s) || 0;
		return n.toFixed(0);
	}
	function sourceLabel(src) {
		switch (src) {
			case 'auto_scan_on_create': return 'AUTO · CREATE';
			case 'auto_scan_on_jd_update': return 'AUTO · JD UPDATE';
			case 'auto_scan_rescan': return 'AUTO · RESCAN';
			case 'ai_promoted': return 'AI PROMOTED';
			case 'manual': return 'MANUAL';
			default: return (src || 'AI').toString().toUpperCase();
		}
	}
	function fmtTs(ts) {
		if (!ts) return '';
		try {
			const d = new Date(ts);
			return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' · ' +
				d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
		} catch { return String(ts).slice(0, 16).replace('T', ' '); }
	}

	let visible = $derived(mode === 'compact' ? recs.slice(0, 3) : recs.slice(0, 50));
</script>

<div class="caim-root caim-{mode}">
	<div class="caim-header">
		<span class="material-symbols-outlined caim-hicon">auto_awesome</span>
		<span class="caim-title">AI POSITION MATCHES</span>
		{#if !loading && !error && recs.length > 0}
			<span class="caim-count">{recs.length}</span>
		{/if}
		{#if mode === 'compact' && recs.length > 3}
			<span class="caim-more">+{recs.length - 3} MORE IN AI MATCHES TAB</span>
		{/if}
	</div>

	{#if loading}
		<div class="caim-skel"></div>
		<div class="caim-skel"></div>
		<div class="caim-skel"></div>
	{:else if error}
		<div class="caim-error">
			<span class="material-symbols-outlined">error</span>
			<span>ERROR — {error}</span>
			<button class="caim-retry" onclick={load}>RETRY</button>
		</div>
	{:else if recs.length === 0}
		<div class="caim-empty">
			<span class="material-symbols-outlined caim-empty-icon">search_off</span>
			<div class="caim-empty-title">NO AI RECOMMENDATIONS YET</div>
			<div class="caim-empty-sub">UPLOAD CV TO RUN MATCHING</div>
		</div>
	{:else}
		<div class="caim-list">
			{#each visible as r, i (r.position_slug || r.position_id || i)}
				{@const composite = r.match_score_composite ?? r.match_score ?? 0}
				<div class="caim-row">
					<div class="caim-row-top">
						<span class="caim-rank">#{i + 1}</span>
						<a class="caim-pos-link" href={`/positions/${r.position_slug}#ai`} title={r.position_title}>
							{r.position_title || r.position_slug || 'Untitled position'}
						</a>
						<span class="caim-score-chip" style="background: {scoreColor(composite)};">
							{fmtScore(composite)}
						</span>
						<span class="caim-source-pill">{sourceLabel(r.match_source)}</span>
						{#if r.stage}
							<span class="caim-stage-pill">{String(r.stage).toUpperCase()}</span>
						{/if}
					</div>

					{#if mode === 'full'}
						<div class="caim-bars">
							{#each DIMS as d}
								{@const v = Number(r[d.key]) || 0}
								<div class="caim-bar-row" title={`${d.label}: ${v.toFixed(0)}`}>
									<span class="caim-bar-lbl">{d.label}</span>
									<div class="caim-bar-track">
										<div class="caim-bar-fill" style="width: {Math.min(100, v)}%; background: {scoreColor(v)};"></div>
									</div>
									<span class="caim-bar-val">{v.toFixed(0)}</span>
								</div>
							{/each}
						</div>

						{#if (r.skills_matched && r.skills_matched.length) || (r.skills_missing && r.skills_missing.length)}
							<div class="caim-chips-wrap">
								{#if r.skills_matched && r.skills_matched.length}
									<div class="caim-chips">
										<span class="caim-chips-lbl">STRENGTHS</span>
										{#each r.skills_matched.slice(0, 8) as s}
											<span class="caim-chip caim-chip-good">{s}</span>
										{/each}
										{#if r.skills_matched.length > 8}
											<span class="caim-chip-more">+{r.skills_matched.length - 8}</span>
										{/if}
									</div>
								{/if}
								{#if r.skills_missing && r.skills_missing.length}
									<div class="caim-chips">
										<span class="caim-chips-lbl">GAPS</span>
										{#each r.skills_missing.slice(0, 8) as s}
											<span class="caim-chip caim-chip-bad">{s}</span>
										{/each}
										{#if r.skills_missing.length > 8}
											<span class="caim-chip-more">+{r.skills_missing.length - 8}</span>
										{/if}
									</div>
								{/if}
							</div>
						{/if}

						{#if r.attached_at}
							<div class="caim-ts">ATTACHED {fmtTs(r.attached_at)}</div>
						{/if}
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.caim-root {
		font-family: 'Space Grotesk', system-ui, sans-serif;
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc);
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
		border-radius: 8px;
		padding: 12px 14px;
		margin-bottom: 16px;
	}
	:global(.dark) .caim-root {
		background: #1a1a18;
		color: #f0efd6;
		border-color: #3a3a34;
		box-shadow: 0 1px 3px rgba(0,0,0,0.2);
	}

	.caim-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.caim-hicon { font-size: 16px; color: var(--color-accent, #c96342); }
	.caim-title { font-weight: 900; font-size: 12px; }
	.caim-count {
		background: var(--color-accent, #c96342);
		color: #fff;
		font-weight: 900;
		font-size: 10px;
		padding: 2px 6px;
		border-radius: 4px;
	}
	.caim-more {
		margin-left: auto;
		font-size: 10px;
		font-weight: 700;
		color: var(--color-accent, #c96342);
	}

	.caim-skel {
		height: 38px;
		background: linear-gradient(90deg, #f0ede6 25%, #faf9f5 50%, #f0ede6 75%);
		background-size: 200% 100%;
		animation: caim-sk 1.4s linear infinite;
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 6px;
		margin-bottom: 6px;
	}
	@keyframes caim-sk { 0%{background-position:0 0} 100%{background-position:-200% 0} }

	.caim-error {
		background: rgba(196,87,26,0.08);
		color: var(--color-error, #c4571a);
		padding: 10px 12px;
		border: 1px solid var(--color-error, #c4571a);
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
		border-radius: 6px;
		font-weight: 900;
		font-size: 12px;
		text-transform: uppercase;
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.caim-retry {
		margin-left: auto;
		background: var(--color-surface-bright, #fff);
		color: var(--color-error, #c4571a);
		border: 1px solid var(--color-error, #c4571a);
		padding: 4px 10px;
		font-family: inherit;
		font-weight: 900;
		font-size: 10px;
		cursor: pointer;
		text-transform: uppercase;
		border-radius: 4px;
	}

	.caim-empty {
		text-align: center;
		padding: 18px 12px;
		border: 1px dashed var(--color-border, #d8d5cc);
		border-radius: 6px;
	}
	.caim-empty-icon { font-size: 36px; color: #888; }
	.caim-empty-title { font-weight: 900; font-size: 13px; text-transform: uppercase; margin-top: 6px; }
	.caim-empty-sub { font-size: 11px; color: #666; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }

	.caim-list { display: flex; flex-direction: column; gap: 8px; }
	.caim-row {
		border: 1px solid var(--color-border, #d8d5cc);
		background: var(--color-surface-bright, #fff);
		padding: 8px 10px;
		border-radius: 6px;
		box-shadow: 0 1px 3px rgba(0,0,0,0.04);
	}
	:global(.dark) .caim-row { background: #25251f; border-color: #3a3a34; }

	.caim-row-top {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.caim-rank {
		font-weight: 900;
		font-size: 11px;
		color: var(--color-on-surface-dim, #6f6e69);
		min-width: 24px;
	}
	.caim-pos-link {
		font-weight: 800;
		font-size: 13px;
		color: inherit;
		text-decoration: none;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		flex: 1 1 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.caim-pos-link:hover { color: var(--color-accent, #c96342); text-decoration: underline; }
	.caim-score-chip {
		color: #fff;
		font-weight: 900;
		font-size: 12px;
		padding: 3px 8px;
		border-radius: 4px;
		min-width: 38px;
		text-align: center;
	}
	.caim-source-pill {
		background: transparent;
		border: 1px solid var(--color-border, #d8d5cc);
		font-weight: 800;
		font-size: 9px;
		padding: 2px 6px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		border-radius: 4px;
	}
	.caim-stage-pill {
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		font-weight: 800;
		font-size: 9px;
		padding: 2px 6px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		border-radius: 4px;
	}

	.caim-bars { margin-top: 8px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 12px; }
	.caim-bar-row { display: flex; align-items: center; gap: 6px; font-size: 10px; }
	.caim-bar-lbl { width: 64px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.04em; }
	.caim-bar-track { flex: 1; height: 8px; background: var(--color-surface-highest, #f0ede8); border: 1px solid var(--color-border, #d8d5cc); border-radius: 4px; }
	:global(.dark) .caim-bar-track { background: #15150f; }
	.caim-bar-fill { height: 100%; }
	.caim-bar-val { width: 24px; text-align: right; font-weight: 900; font-size: 10px; }

	.caim-chips-wrap { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
	.caim-chips { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
	.caim-chips-lbl { font-size: 9px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; margin-right: 4px; }
	.caim-chip {
		font-size: 10px;
		padding: 2px 6px;
		border: 1px solid var(--color-border, #d8d5cc);
		font-weight: 700;
		text-transform: uppercase;
		border-radius: 4px;
	}
	.caim-chip-good { background: #d8f5d0; color: #3a8a4f; border-color: #b0d8ba; }
	.caim-chip-bad { background: #fceade; color: var(--color-error, #c4571a); border-color: #f0c0a8; }
	.caim-chip-more { font-size: 10px; font-weight: 900; color: #888; }

	.caim-ts {
		margin-top: 6px;
		font-size: 9px;
		font-weight: 700;
		color: #888;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	@media (max-width: 700px) {
		.caim-bars { grid-template-columns: 1fr; }
	}
</style>
