<script>
	import { apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';

	let ttf = $state(null);
	let perStage = $state([]);
	let interviewers = $state([]);
	let loading = $state(true);
	let sortKey = $state('avg_hrs_to_scorecard');
	let sortDir = $state('asc');

	$effect(() => { load(); });

	async function load() {
		loading = true;
		try { ttf = await apiJson('/analytics/v2/time-to-fill'); } catch (e) { ttf = null; }
		try { perStage = await apiJson('/analytics/v2/time-per-stage'); } catch (e) { perStage = []; }
		try { interviewers = await apiJson('/analytics/v2/interviewer-turnaround'); } catch (e) { interviewers = []; }
		loading = false;
	}

	function setSort(k) {
		if (sortKey === k) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else { sortKey = k; sortDir = 'asc'; }
	}

	let sortedInterviewers = $derived.by(() => {
		const arr = [...(interviewers || [])];
		arr.sort((a, b) => {
			const av = a[sortKey] ?? 0;
			const bv = b[sortKey] ?? 0;
			if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
			return sortDir === 'asc' ? av - bv : bv - av;
		});
		return arr;
	});

	let perStageOptions = $derived.by(() => {
		if (!perStage?.length) return null;
		return {
			grid: { left: 60, right: 20, top: 30, bottom: 50 },
			legend: { textStyle: { fontSize: 10 }, top: 0 },
			xAxis: { type: 'category', data: perStage.map(s => s.stage), axisLabel: { fontSize: 10, rotate: 20 } },
			yAxis: { type: 'value', name: 'days', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis' },
			series: [
				{ name: 'avg', type: 'bar', data: perStage.map(s => s.avg_days || 0), itemStyle: { color: '#007518' } },
				{ name: 'median', type: 'bar', data: perStage.map(s => s.median || 0), itemStyle: { color: '#006f7c' } },
				{ name: 'p90', type: 'bar', data: perStage.map(s => s.p90 || 0), itemStyle: { color: '#be2d06' } }
			]
		};
	});

	let byDeptOptions = $derived.by(() => {
		const rows = ttf?.by_department || [];
		if (!rows.length) return null;
		return {
			grid: { left: 100, right: 20, top: 20, bottom: 30 },
			xAxis: { type: 'value', name: 'days', axisLabel: { fontSize: 10 } },
			yAxis: { type: 'category', data: rows.map(r => r.department || r.name || '—'), axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis' },
			series: [{ type: 'bar', data: rows.map(r => r.avg_days || r.days || 0), itemStyle: { color: '#9d4867' }, label: { show: true, position: 'right', fontSize: 10 } }]
		};
	});
</script>

<div class="mb-6" id="time-metrics">
	<div class="dark-title-bar">TIME METRICS</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else}
			<div class="grid grid-cols-3 gap-3 mb-4">
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Avg Time-to-Fill</div>
					<div style="font-size: 32px; font-weight: 900;">{ttf?.avg_days ?? '—'}<span style="font-size: 12px; font-weight: 700; margin-left: 4px;">days</span></div>
				</div>
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Median Time-to-Fill</div>
					<div style="font-size: 32px; font-weight: 900;">{ttf?.median_days ?? '—'}<span style="font-size: 12px; font-weight: 700; margin-left: 4px;">days</span></div>
				</div>
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">P90 Time-to-Fill</div>
					<div style="font-size: 32px; font-weight: 900;">{ttf?.p90_days ?? '—'}<span style="font-size: 12px; font-weight: 700; margin-left: 4px;">days</span></div>
				</div>
			</div>

			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Time Per Stage</div>
				{#if perStageOptions}
					<Chart options={perStageOptions} height="280px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No stage data</div>
				{/if}
			</div>

			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Time-to-Fill by Department</div>
				{#if byDeptOptions}
					<Chart options={byDeptOptions} height="260px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No department data</div>
				{/if}
			</div>

			<div>
				<div class="tag-label" style="margin-bottom: 6px;">Interviewer Turnaround</div>
				{#if sortedInterviewers.length === 0}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No interviewer data</div>
				{:else}
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th style="cursor: pointer;" onclick={() => setSort('name')}>Name {sortKey === 'name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}</th>
									<th style="cursor: pointer;" onclick={() => setSort('avg_hrs_to_scorecard')}>Avg Hrs To Scorecard</th>
									<th style="cursor: pointer;" onclick={() => setSort('completion_rate')}>Completion %</th>
									<th style="cursor: pointer;" onclick={() => setSort('n_interviews')}>Interviews</th>
								</tr>
							</thead>
							<tbody>
								{#each sortedInterviewers as r}
									<tr>
										<td>{r.name || '—'}</td>
										<td>{(r.avg_hrs_to_scorecard ?? 0).toFixed?.(1) ?? r.avg_hrs_to_scorecard ?? '—'}</td>
										<td>{((r.completion_rate ?? 0) * 100).toFixed(0)}%</td>
										<td>{r.n_interviews ?? 0}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
