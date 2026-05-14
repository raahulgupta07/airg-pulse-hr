<script>
	let {
		match,
		index,
		isPending = null,
		isFocused = false,
		isSelected = false,
		position = null,
		onPromote = () => {},
		onReject = () => {},
		onToggleSelect = () => {},
		onOpenDrawer = () => {}
	} = $props();

	function handleRowClick(e) {
		// Skip if click originated on a control (button/link/input/checkbox/score chip)
		const t = e.target;
		if (!t) return;
		if (t.closest('button, a, input, .ai-score-wrap')) return;
		onOpenDrawer(match.candidate_id, match);
	}
	function handleRowKey(e) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			onOpenDrawer(match.candidate_id, match);
		}
	}

	let hoverTooltip = $state(false);

	function getYrs(m) { return Number(m.years_experience ?? m.yrs_exp ?? m.experience_years ?? m.total_experience_years ?? 0) || 0; }
	function getRole(m) { return (m.current_role || m.role || 'N/A').toString(); }

	/** Semantic score color — green / amber / muted-red */
	function scoreColor(s) {
		if (s >= 70) return '#3a8a4f';
		if (s >= 40) return '#c98c2a';
		return '#c4571a';
	}
	/** 10%-opacity tint backgrounds for score pill */
	function scoreBg(s) {
		if (s >= 70) return 'rgba(58,138,79,0.10)';
		if (s >= 40) return 'rgba(201,140,42,0.10)';
		return 'rgba(196,87,26,0.10)';
	}

	function getStrengths(m) {
		if (Array.isArray(m.top_strengths) && m.top_strengths.length) return m.top_strengths;
		if (Array.isArray(m.skills_matched)) return m.skills_matched.slice(0, 3);
		return [];
	}
	function getGaps(m) {
		if (Array.isArray(m.gaps) && m.gaps.length) return m.gaps;
		if (Array.isArray(m.skills_missing)) return m.skills_missing.slice(0, 2);
		return [];
	}

	let composite = $derived(Number(match.match_score_composite ?? 0));
	let breakdown = $derived({
		SKILLS: match.match_score_skills,
		EXP: match.match_score_experience,
		EDU: match.match_score_education,
		CERT: match.match_score_certifications,
		IND: match.match_score_industry,
		CULTURE: match.match_score_culture
	});
	let strengths = $derived(getStrengths(match));
	let gaps = $derived(getGaps(match));
	let yrs = $derived(getYrs(match));
	let role = $derived(getRole(match));
	let status = $derived((match.stage && String(match.stage).toUpperCase() === 'SCREENED') ? 'SCREENED' : 'UPLOADED');
	let source = $derived((
		match.auto_added
		|| ['ai_promoted','auto_scan_on_create','auto_scan_on_jd_update','auto_scan_rescan'].includes(match.match_source)
		|| ['ai_scan','auto_match','ai_auto','ai_auto_scan'].includes(match.added_by)
	) ? 'AI' : 'MANUAL');
</script>

<div class="ai-match-row"
	class:ai-match-selected={isSelected}
	class:ai-match-focused={isFocused}
	role="button"
	tabindex="0"
	onclick={handleRowClick}
	onkeydown={handleRowKey}
	style="cursor: pointer;">
	<div class="ai-match-check">
		<input type="checkbox" checked={isSelected}
			onclick={(e) => e.stopPropagation()}
			onchange={(e) => { e.stopPropagation(); onToggleSelect(match.candidate_id); }} />
	</div>

	<div class="ai-match-rank">#{index + 1}</div>

	<!-- Score chip -->
	<div class="ai-score-wrap"
		onmouseover={() => hoverTooltip = true}
		onmouseout={() => hoverTooltip = false}
		onfocus={() => hoverTooltip = true}
		onblur={() => hoverTooltip = false}
		role="button"
		tabindex="0">
		<div class="ai-score-chip"
			style="background: {scoreBg(composite)}; color: {scoreColor(composite)};">
			{Math.round(composite)}%
		</div>
		{#if hoverTooltip && (match.match_explanation || strengths.length || gaps.length)}
			<div class="ai-tooltip">
				<div class="ai-tooltip-title">Why {Math.round(composite)}%</div>
				{#if match.match_explanation}
					<div class="ai-tooltip-body">{match.match_explanation}</div>
				{/if}
				{#if strengths.length}
					<div class="ai-tooltip-section">
						<div class="ai-tooltip-label">Strengths</div>
						<div>{strengths.join(' · ')}</div>
					</div>
				{/if}
				{#if gaps.length}
					<div class="ai-tooltip-section">
						<div class="ai-tooltip-label">Gaps</div>
						<div>{gaps.join(' · ')}</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Middle info -->
	<div class="ai-match-info">
		<div class="ai-info-head">
			<span class="ai-name">{match.name || `Candidate ${match.candidate_id}`}</span>
			<span class="ai-pill ai-pill-status">{status}</span>
			<span class="ai-pill" class:ai-pill-ai={source === 'AI'} class:ai-pill-manual={source === 'MANUAL'}>{source === 'AI' ? '✦ AI' : 'MANUAL'}</span>
		</div>
		<div class="ai-sub">{role} · {yrs}yr</div>

		<div class="ai-bars">
			{#each Object.entries(breakdown) as [dim, val]}
				{@const pct = Math.max(0, Math.min(100, Number(val) || 0))}
				<div class="ai-bar-cell">
					<div class="ai-bar-label">{dim}</div>
					<div class="ai-bar-track">
						<div class="ai-bar-fill" style="width: {pct}%;"></div>
					</div>
					<div class="ai-bar-val">{Math.round(pct)}%</div>
				</div>
			{/each}
		</div>
	</div>

	<!-- Right action stack -->
	<div class="ai-actions">
		<a class="ai-action ai-action-link" href={`/candidates/${match.candidate_id}`} onclick={(e) => e.stopPropagation()}>View CV</a>
		<button class="ai-action ai-action-add"
			onclick={(e) => { e.stopPropagation(); onPromote(match); }}
			disabled={!!isPending}>
			{isPending === 'adding' ? '…' : '+ Add'}
		</button>
		<button class="ai-action ai-action-reject"
			onclick={(e) => { e.stopPropagation(); onReject(match); }}
			disabled={!!isPending}>
			{isPending === 'rejecting' ? '…' : 'Reject'}
		</button>
	</div>
</div>

<style>
	.ai-match-row {
		display: grid;
		grid-template-columns: 28px 32px 56px 1fr 140px;
		gap: 12px;
		align-items: center;
		padding: 12px;
		min-height: 120px;
		background: var(--color-surface-bright, #fff);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface, #2c2c2c);
		transition: background 150ms ease;
	}
	.ai-match-row:hover {
		background: rgba(250, 249, 245, 0.85);
	}
	.ai-match-selected {
		background: rgba(201, 99, 66, 0.06);
	}
	.ai-match-focused {
		outline: 2px solid var(--color-accent, #c96342);
		outline-offset: -2px;
	}

	.ai-match-check { display: flex; align-items: center; }
	.ai-match-check input {
		width: 16px;
		height: 16px;
		cursor: pointer;
		accent-color: var(--color-accent, #c96342);
	}

	.ai-match-rank {
		font-size: 13px;
		font-weight: 700;
		color: var(--color-on-surface-dim, #6f6e69);
		text-align: center;
	}

	/* Score chip — soft pill, semantic color */
	.ai-score-wrap { position: relative; }
	.ai-score-chip {
		width: 48px;
		height: 36px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 13px;
		font-weight: 700;
		border-radius: 4px;
		cursor: help;
	}

	.ai-match-info { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
	.ai-info-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
	.ai-name { font-size: 14px; font-weight: 700; color: var(--color-on-surface, #2c2c2c); }

	/* Source + status pills */
	.ai-pill {
		font-size: 10px;
		padding: 2px 7px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-radius: 4px;
		border: none;
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.ai-pill-status {
		background: rgba(111,110,105,0.12);
		color: var(--color-on-surface-dim, #6f6e69);
	}
	/* AI = coral accent on cream */
	.ai-pill-ai {
		background: rgba(201,99,66,0.10);
		color: var(--color-accent, #c96342);
	}
	/* MANUAL = neutral grey on warm beige */
	.ai-pill-manual {
		background: rgba(111,110,105,0.10);
		color: var(--color-on-surface-dim, #6f6e69);
	}

	.ai-sub { font-size: 12px; color: var(--color-on-surface-dim, #6f6e69); }

	/* Breakdown bars */
	.ai-bars { display: flex; gap: 12px; margin-top: 4px; flex-wrap: wrap; }
	.ai-bar-cell { display: flex; flex-direction: column; gap: 2px; min-width: 80px; }
	.ai-bar-label {
		font-size: 8px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.ai-bar-track {
		width: 80px;
		height: 5px;
		background: var(--color-bg, #f3f2ec);
		border-radius: 2px;
		overflow: hidden;
	}
	.ai-bar-fill {
		height: 100%;
		background: var(--color-accent, #c96342);
		border-radius: 2px;
	}
	.ai-bar-val { font-size: 9px; font-weight: 600; color: var(--color-on-surface-dim, #6f6e69); }

	/* Tooltip */
	.ai-tooltip {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		width: 260px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 6px;
		box-shadow: 0 4px 16px rgba(0,0,0,0.10);
		padding: 10px 12px;
		z-index: 50;
	}
	.ai-tooltip-title {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--color-accent, #c96342);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		padding-bottom: 4px;
		margin-bottom: 6px;
	}
	.ai-tooltip-body { font-size: 11px; line-height: 1.4; margin-bottom: 6px; color: var(--color-on-surface, #2c2c2c); }
	.ai-tooltip-section { margin-top: 6px; font-size: 10px; color: var(--color-on-surface, #2c2c2c); }
	.ai-tooltip-label {
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-bottom: 2px;
	}

	/* Action buttons */
	.ai-actions { display: flex; flex-direction: column; gap: 4px; }
	.ai-action {
		display: block;
		text-align: center;
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		padding: 6px 10px;
		border-radius: 6px;
		border: 1px solid var(--color-border, #e8e6dd);
		background: transparent;
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		text-decoration: none;
		transition: background 120ms ease, color 120ms ease;
	}
	.ai-action[disabled] { opacity: 0.45; cursor: not-allowed; }

	/* View CV — ghost */
	.ai-action-link:hover {
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface, #2c2c2c);
	}

	/* Add — solid coral fill */
	.ai-action-add {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.ai-action-add:hover:not([disabled]) {
		background: #b35538;
		border-color: #b35538;
	}

	/* Reject — warm ghost */
	.ai-action-reject {
		color: var(--color-on-surface-dim, #6f6e69);
		border-color: var(--color-border, #e8e6dd);
		background: transparent;
	}
	.ai-action-reject:hover:not([disabled]) {
		background: rgba(196,87,26,0.08);
		color: #c4571a;
		border-color: rgba(196,87,26,0.30);
	}

	@media (max-width: 720px) {
		.ai-match-row { grid-template-columns: 28px 32px 56px 1fr; }
		.ai-actions { grid-column: 1 / -1; flex-direction: row; flex-wrap: wrap; }
		.ai-action { flex: 1; min-width: 90px; }
	}
</style>
