<script>
	/** Competency analytics — gap heatmap + interviewer calibration. */
	import { apiJson } from '$lib/api';

	let gaps = $state(null);
	let calibration = $state(null);
	let loading = $state(true);
	let errors = $state({ gaps: false, calibration: false });

	$effect(() => { load(); });

	async function load() {
		loading = true;
		errors = { gaps: false, calibration: false };
		try {
			gaps = await apiJson('/analytics/v2/competency-gaps');
		} catch (e) {
			gaps = null;
			errors.gaps = true;
		}
		try {
			calibration = await apiJson('/analytics/v2/competency-calibration');
		} catch (e) {
			calibration = null;
			errors.calibration = true;
		}
		loading = false;
	}

	// Normalize gaps payload — accept either {matrix:[{position,competency,gap_pct,critical}]}
	// or {positions:[...], competencies:[...], cells:{[pos][comp]: gap_pct}}
	let heatmap = $derived.by(() => {
		if (!gaps) return null;
		// Form A: matrix list
		if (Array.isArray(gaps.matrix)) {
			const positions = Array.from(new Set(gaps.matrix.map(r => r.position || r.position_title || r.slug))).filter(Boolean);
			const competencies = Array.from(new Set(gaps.matrix.map(r => r.competency || r.label || r.key))).filter(Boolean);
			const cells = {};
			for (const r of gaps.matrix) {
				const p = r.position || r.position_title || r.slug;
				const c = r.competency || r.label || r.key;
				if (!cells[p]) cells[p] = {};
				cells[p][c] = {
					gap: Number(r.gap_pct ?? r.gap ?? 0),
					critical: !!r.critical,
				};
			}
			return { positions, competencies, cells };
		}
		// Form B: structured
		if (Array.isArray(gaps.positions) && Array.isArray(gaps.competencies)) {
			return {
				positions: gaps.positions,
				competencies: gaps.competencies,
				cells: gaps.cells || {},
			};
		}
		return null;
	});

	function gapColor(gap) {
		// gap is 0-100 magnitude (0 = no gap, 100 = critical)
		const g = Math.max(0, Math.min(100, Number(gap) || 0));
		if (g === 0) return 'var(--color-surface-bright, #fff)';
		if (g < 15) return '#d4f5dc';
		if (g < 30) return '#fff3c4';
		if (g < 50) return '#ffd6a8';
		if (g < 75) return '#ff9d6d';
		return 'var(--color-error, #c4571a)';
	}

	function gapText(gap) {
		const g = Math.max(0, Math.min(100, Number(gap) || 0));
		return g >= 50 ? '#fff' : 'var(--color-on-surface, #2c2c2c)';
	}

	let calRows = $derived.by(() => {
		if (!calibration) return [];
		if (Array.isArray(calibration)) return calibration;
		return calibration.rows || calibration.items || [];
	});
</script>

<div class="mb-6">
	<div class="dark-title-bar flex items-center justify-between">
		<span>COMPETENCY GAP HEATMAP</span>
		<button onclick={load} style="font-size: 10px; padding: 3px 10px; border: 1px solid var(--color-surface); background: transparent; color: var(--color-surface); font-weight: 700; cursor: pointer; text-transform: uppercase;">Refresh</button>
	</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else if errors.gaps || !heatmap || heatmap.positions.length === 0}
			<div style="font-size: 11px; color: var(--color-on-surface-dim); text-align: center; padding: 24px; text-transform: uppercase; letter-spacing: 0.06em;">
				No competency gap data yet. Tag JDs with competencies and rate candidates to populate.
			</div>
		{:else}
			<div style="overflow-x: auto;">
				<table style="border-collapse: collapse; font-size: 10px; min-width: 100%;">
					<thead>
						<tr>
							<th style="background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff); padding: 6px 8px; text-align: left; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; position: sticky; left: 0; z-index: 2;">Position</th>
							{#each heatmap.competencies as c}
								<th style="background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff); padding: 6px 8px; font-weight: 900; letter-spacing: 0.04em; text-transform: uppercase; writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; min-height: 90px;">{c}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each heatmap.positions as p}
							<tr>
								<td style="background: var(--color-surface-bright); border: 1px solid #383832; padding: 6px 8px; font-weight: 700; position: sticky; left: 0; z-index: 1; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis;">{p}</td>
								{#each heatmap.competencies as c}
									{@const cell = heatmap.cells?.[p]?.[c]}
									{@const gap = typeof cell === 'object' ? (cell?.gap ?? 0) : (cell ?? 0)}
									{@const critical = typeof cell === 'object' ? !!cell?.critical : false}
									<td style="background: {gapColor(gap)}; color: {gapText(gap)}; border: 1px solid #383832; padding: 8px 10px; text-align: center; font-weight: 900; min-width: 44px;">
										{cell == null ? '—' : `${Math.round(gap)}${critical ? '!' : ''}`}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<div style="display: flex; gap: 12px; margin-top: 12px; align-items: center; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;">
				<span style="font-weight: 700;">Gap severity:</span>
				{#each [{l:'0',v:0},{l:'<15',v:10},{l:'<30',v:25},{l:'<50',v:40},{l:'<75',v:60},{l:'≥75',v:80}] as b}
					<span style="display: inline-flex; align-items: center; gap: 4px;">
						<span style="display: inline-block; width: 16px; height: 12px; background: {gapColor(b.v)}; border: 1px solid #383832;"></span>
						{b.l}
					</span>
				{/each}
				<span style="margin-left: auto; opacity: 0.7;">"!" = critical (no signal)</span>
			</div>
		{/if}
	</div>
</div>

<div class="mb-6">
	<div class="dark-title-bar">INTERVIEWER CALIBRATION — COMPETENCY</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else if errors.calibration || calRows.length === 0}
			<div style="font-size: 11px; color: var(--color-on-surface-dim); text-align: center; padding: 24px; text-transform: uppercase; letter-spacing: 0.06em;">
				No calibration data. Submit scorecards with competency ratings to populate.
			</div>
		{:else}
			<div style="overflow-x: auto;">
				<table class="data-table">
					<thead>
						<tr>
							<th>Interviewer</th>
							<th>Competency</th>
							<th>N</th>
							<th>Avg</th>
							<th>Org Avg</th>
							<th>Δ</th>
							<th>Harshness</th>
						</tr>
					</thead>
					<tbody>
						{#each calRows as r}
							{@const delta = (Number(r.avg) || 0) - (Number(r.org_avg) || 0)}
							<tr>
								<td style="font-weight: 700;">{r.interviewer || r.interviewer_name || '—'}</td>
								<td>{r.competency || r.label || r.key || '—'}</td>
								<td>{r.n ?? r.count ?? 0}</td>
								<td>{(Number(r.avg) || 0).toFixed(2)}</td>
								<td>{(Number(r.org_avg) || 0).toFixed(2)}</td>
								<td style="font-weight: 900; color: {delta > 0 ? '#3a8a4f' : delta < 0 ? 'var(--color-error, #c4571a)' : 'var(--color-on-surface, #2c2c2c)'};">
									{delta > 0 ? '+' : ''}{delta.toFixed(2)}
								</td>
								<td>
									{#if r.harshness != null}
										<span style="padding: 1px 8px; border-radius: 4px; background: {Number(r.harshness) > 0.3 ? 'var(--color-error, #c4571a)' : Number(r.harshness) < -0.3 ? '#3a8a4f' : 'var(--color-on-surface, #2c2c2c)'}; color: #fff; font-weight: 900; font-size: 10px;">
											{Number(r.harshness).toFixed(2)}
										</span>
									{:else}
										—
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>
