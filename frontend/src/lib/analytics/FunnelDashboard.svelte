<script>
	import { apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';

	let funnel = $state(null);
	let cohort = $state([]);
	let loading = $state(true);

	$effect(() => { load(); });

	async function load() {
		loading = true;
		try { funnel = await apiJson('/analytics/v2/funnel'); }
		catch (e) { console.warn('funnel v2 missing', e); funnel = null; }
		try { cohort = await apiJson('/analytics/v2/cohort?metric=offer_rate'); }
		catch (e) { console.warn('cohort v2 missing', e); cohort = []; }
		loading = false;
	}

	let stageBarOptions = $derived.by(() => {
		const stages = funnel?.stages || [];
		if (!stages.length) return null;
		return {
			grid: { left: 110, right: 30, top: 20, bottom: 30 },
			xAxis: { type: 'value', axisLabel: { fontSize: 10 } },
			yAxis: { type: 'category', data: stages.map(s => s.stage), axisLabel: { fontSize: 11, fontWeight: 700 } },
			tooltip: { trigger: 'axis' },
			series: [{
				type: 'bar',
				data: stages.map(s => s.count || 0),
				itemStyle: { color: '#007518' },
				label: { show: true, position: 'right', fontSize: 10, fontWeight: 700 }
			}]
		};
	});

	let stackedSourceOptions = $derived.by(() => {
		const rows = funnel?.by_source || [];
		if (!rows.length) return null;
		const sources = [...new Set(rows.map(r => r.source))];
		const stages = [...new Set(rows.map(r => r.stage))];
		const colors = ['#007518', '#006f7c', '#be2d06', '#ff9d00', '#9d4867', '#00fc40', '#383832'];
		const series = stages.map((st, i) => ({
			name: st,
			type: 'bar',
			stack: 'total',
			itemStyle: { color: colors[i % colors.length] },
			data: sources.map(src => {
				const m = rows.find(r => r.source === src && r.stage === st);
				return m?.count || 0;
			})
		}));
		return {
			grid: { left: 50, right: 20, top: 40, bottom: 40 },
			legend: { textStyle: { fontSize: 10 }, top: 5 },
			xAxis: { type: 'category', data: sources, axisLabel: { fontSize: 10 } },
			yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis' },
			series
		};
	});

	let cohortHeatmapOptions = $derived.by(() => {
		if (!cohort?.length) return null;
		const months = cohort.map(c => c.cohort_month);
		const stageSet = new Set();
		cohort.forEach(c => Object.keys(c.stages || {}).forEach(s => stageSet.add(s)));
		const stages = [...stageSet];
		const data = [];
		let maxV = 0;
		cohort.forEach((c, yi) => {
			stages.forEach((st, xi) => {
				const v = c.stages?.[st] || 0;
				if (v > maxV) maxV = v;
				data.push([xi, yi, v]);
			});
		});
		return {
			tooltip: { position: 'top' },
			grid: { left: 90, right: 30, top: 40, bottom: 40 },
			xAxis: { type: 'category', data: stages, axisLabel: { fontSize: 10 }, splitArea: { show: true } },
			yAxis: { type: 'category', data: months, axisLabel: { fontSize: 10 }, splitArea: { show: true } },
			visualMap: { min: 0, max: maxV || 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 5, textStyle: { fontSize: 9 }, inRange: { color: ['#feffd6', '#007518'] } },
			series: [{ type: 'heatmap', data, label: { show: true, fontSize: 10, fontWeight: 700 } }]
		};
	});
</script>

<div class="mb-6" id="funnel-cohort">
	<div class="dark-title-bar">FUNNEL + COHORT</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else if !funnel && !cohort?.length}
			<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase;">No funnel data available</div>
		{:else}
			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Stages × Count</div>
				{#if stageBarOptions}
					<Chart options={stageBarOptions} height="280px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No stage data</div>
				{/if}
			</div>

			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Stage Breakdown By Source</div>
				{#if stackedSourceOptions}
					<Chart options={stackedSourceOptions} height="300px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No source data</div>
				{/if}
			</div>

			<div>
				<div class="tag-label" style="margin-bottom: 6px;">Cohort Heatmap (rows=cohort month)</div>
				{#if cohortHeatmapOptions}
					<Chart options={cohortHeatmapOptions} height="340px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No cohort data</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
