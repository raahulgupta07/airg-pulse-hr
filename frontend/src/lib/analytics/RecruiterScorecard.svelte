<script>
	import { apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';

	let rows = $state([]);
	let loading = $state(true);
	let sortKey = $state('hired');
	let sortDir = $state('desc');
	let expandedId = $state(null);

	$effect(() => { load(); });

	async function load() {
		loading = true;
		try { rows = await apiJson('/analytics/v2/recruiter-leaderboard'); }
		catch (e) { console.warn('recruiter leaderboard missing', e); rows = []; }
		loading = false;
	}

	function setSort(k) {
		if (sortKey === k) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else { sortKey = k; sortDir = 'desc'; }
	}

	let sorted = $derived.by(() => {
		const arr = [...(rows || [])];
		arr.sort((a, b) => {
			const av = a[sortKey] ?? 0;
			const bv = b[sortKey] ?? 0;
			if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
			return sortDir === 'asc' ? av - bv : bv - av;
		});
		return arr;
	});

	function sparkOptions(seed) {
		// Mock sparkline since no detail endpoint
		const data = [];
		let v = (seed % 7) + 2;
		for (let i = 0; i < 12; i++) { v = Math.max(0, v + (((seed * (i + 1)) % 5) - 2)); data.push(v); }
		return {
			grid: { left: 0, right: 0, top: 5, bottom: 5 },
			xAxis: { type: 'category', show: false, data: data.map((_, i) => i) },
			yAxis: { type: 'value', show: false },
			series: [{ type: 'line', data, smooth: true, symbol: 'none', lineStyle: { color: '#c96342', width: 2 }, areaStyle: { color: 'rgba(201,99,66,0.12)' } }]
		};
	}

	function hashId(id) {
		const s = String(id || '');
		let h = 0;
		for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
		return Math.abs(h);
	}
</script>

<div class="mb-6" id="recruiter-scorecard">
	<div class="dark-title-bar">RECRUITER SCORECARD</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else if !sorted.length}
			<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase;">No recruiter data</div>
		{:else}
			<div style="overflow-x: auto;">
				<table class="data-table">
					<thead>
						<tr>
							<th style="cursor: pointer;" onclick={() => setSort('name')}>Name</th>
							<th style="cursor: pointer;" onclick={() => setSort('added')}>Added</th>
							<th style="cursor: pointer;" onclick={() => setSort('hired')}>Hired {sortKey === 'hired' ? (sortDir === 'asc' ? '↑' : '↓') : ''}</th>
							<th style="cursor: pointer;" onclick={() => setSort('offers')}>Offers</th>
							<th style="cursor: pointer;" onclick={() => setSort('avg_score_given')}>Avg Score</th>
							<th style="cursor: pointer;" onclick={() => setSort('harshness_index')}>Harshness</th>
							<th style="cursor: pointer;" onclick={() => setSort('avg_turnaround_hrs')}>Turnaround (hrs)</th>
						</tr>
					</thead>
					<tbody>
						{#each sorted as r (r.recruiter_id)}
							<tr style="cursor: pointer;" onclick={() => expandedId = expandedId === r.recruiter_id ? null : r.recruiter_id}>
								<td style="font-weight: 700;">{r.name || '—'}</td>
								<td>{r.added ?? 0}</td>
								<td>{r.hired ?? 0}</td>
								<td>{r.offers ?? 0}</td>
								<td>{(r.avg_score_given ?? 0).toFixed?.(2) ?? r.avg_score_given ?? '—'}</td>
								<td>{(r.harshness_index ?? 0).toFixed?.(2) ?? r.harshness_index ?? '—'}</td>
								<td>{(r.avg_turnaround_hrs ?? 0).toFixed?.(1) ?? r.avg_turnaround_hrs ?? '—'}</td>
							</tr>
							{#if expandedId === r.recruiter_id}
								<tr>
									<td colspan="7" style="background: var(--color-surface-bright); padding: 12px;">
										<div class="tag-label" style="margin-bottom: 4px;">Hires Trend (mock)</div>
										<div style="height: 70px;">
											<Chart options={sparkOptions(hashId(r.recruiter_id))} height="70px" />
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>
