<script>
	import { apiJson } from '$lib/api';

	let { positions = [] } = $props();

	let selectedSlug = $state('');
	let forecast = $state(null);
	let loading = $state(false);
	let error = $state('');

	async function loadForecast() {
		if (!selectedSlug) { forecast = null; return; }
		loading = true;
		error = '';
		try {
			forecast = await apiJson(`/analytics/v2/forecast/${selectedSlug}`);
		} catch (e) {
			console.warn('forecast missing', e);
			forecast = null;
			error = 'Forecast unavailable for this position';
		}
		loading = false;
	}

	$effect(() => { loadForecast(); });

	function confidenceColor(c) {
		const v = (c || '').toLowerCase();
		if (v === 'high') return '#3a8a4f';
		if (v === 'medium' || v === 'med') return 'var(--color-warning, #c98c2a)';
		if (v === 'low') return 'var(--color-error, #c4571a)';
		return 'var(--color-on-surface-dim, #6f6e69)';
	}
</script>

<div class="mb-6" id="predictive">
	<div class="dark-title-bar">PREDICTIVE</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		<div class="flex items-center gap-2 mb-3">
			<label class="tag-label">Position</label>
			<select
				bind:value={selectedSlug}
				style="padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright); min-width: 280px;"
			>
				<option value="">Select a position…</option>
				{#each positions as p}
					<option value={p.slug}>{p.title}</option>
				{/each}
			</select>
		</div>

		{#if !selectedSlug}
			<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase;">Select a position to see forecast</div>
		{:else if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else if error}
			<div style="font-size: 11px; color: var(--color-on-surface-dim);">{error}</div>
		{:else if forecast}
			<div class="grid grid-cols-2 gap-3 mb-4">
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Days To Fill (forecast)</div>
					<div style="font-size: 36px; font-weight: 900;">{forecast.days_to_fill ?? '—'}<span style="font-size: 12px; font-weight: 700; margin-left: 4px;">days</span></div>
				</div>
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Confidence</div>
					<div style="display: inline-block; padding: 6px 16px; background: {confidenceColor(forecast.confidence)}; color: white; font-size: 16px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 4px;">
						{forecast.confidence || '—'}
					</div>
				</div>
			</div>

			<div>
				<div class="tag-label" style="margin-bottom: 6px;">Comparable Positions</div>
				{#if !forecast.comparable_positions?.length}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No comparable positions</div>
				{:else}
					<div style="font-size: 10px; color: var(--color-on-surface-dim); margin-bottom: 6px;">based on {forecast.comparable_positions.length} similar past hires</div>
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th>Title</th>
									<th>Days To Fill</th>
									<th>Hired</th>
								</tr>
							</thead>
							<tbody>
								{#each forecast.comparable_positions as cp}
									<tr>
										<td style="font-weight: 700;">{cp.title || cp.slug || '—'}</td>
										<td>{cp.days_to_fill ?? '—'}</td>
										<td>{cp.hired_at || cp.closed_at || '—'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		{:else}
			<div style="font-size: 11px; color: var(--color-on-surface-dim);">No forecast data</div>
		{/if}
	</div>
</div>
