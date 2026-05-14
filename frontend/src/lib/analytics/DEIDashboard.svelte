<script>
	import { apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';

	let dimension = $state('gender');
	let stagedData = $state(null);
	let dropoff = $state(null);
	let loading = $state(false);

	$effect(() => { load(dimension); });

	async function load(dim) {
		loading = true;
		try { stagedData = await apiJson(`/analytics/v2/diversity?dimension=${dim}`); }
		catch (e) { stagedData = null; }
		try { dropoff = await apiJson(`/analytics/v2/diversity-dropoff?dimension=${dim}`); }
		catch (e) { dropoff = null; }
		loading = false;
	}

	const COLORS = ['#007518', '#006f7c', '#be2d06', '#ff9d00', '#9d4867', '#00fc40', '#383832', '#9d9d91'];

	let stackedOptions = $derived.by(() => {
		const stages = stagedData?.by_stage || [];
		if (!stages.length) return null;
		const groupSet = new Set();
		stages.forEach(s => Object.keys(s.groups || {}).forEach(g => groupSet.add(g)));
		const groups = [...groupSet];
		const series = groups.map((g, i) => ({
			name: g,
			type: 'bar',
			stack: 'total',
			itemStyle: { color: COLORS[i % COLORS.length] },
			data: stages.map(s => {
				const total = s.total || 1;
				return ((s.groups?.[g] || 0) / total) * 100;
			})
		}));
		return {
			grid: { left: 50, right: 20, top: 40, bottom: 30 },
			legend: { textStyle: { fontSize: 10 }, top: 0 },
			xAxis: { type: 'category', data: stages.map(s => s.stage), axisLabel: { fontSize: 10 } },
			yAxis: { type: 'value', name: '%', max: 100, axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis', valueFormatter: v => v.toFixed(1) + '%' },
			series
		};
	});

	let dropoffOptions = $derived.by(() => {
		const stages = dropoff?.by_stage || [];
		if (!stages.length) return null;
		const groupSet = new Set();
		stages.forEach(s => Object.keys(s.groups || {}).forEach(g => groupSet.add(g)));
		const groups = [...groupSet];
		const series = groups.map((g, i) => ({
			name: g,
			type: 'line',
			smooth: true,
			itemStyle: { color: COLORS[i % COLORS.length] },
			lineStyle: { color: COLORS[i % COLORS.length], width: 2 },
			data: stages.map(s => {
				const total = s.total || 1;
				return ((s.groups?.[g] || 0) / total) * 100;
			})
		}));
		return {
			grid: { left: 50, right: 20, top: 40, bottom: 30 },
			legend: { textStyle: { fontSize: 10 }, top: 0 },
			xAxis: { type: 'category', data: stages.map(s => s.stage), axisLabel: { fontSize: 10 } },
			yAxis: { type: 'value', name: 'pass-through %', max: 100, axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis', valueFormatter: v => v.toFixed(1) + '%' },
			series
		};
	});
</script>

<div class="mb-6" id="dei-dashboard">
	<div class="dark-title-bar">DEI DASHBOARD</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		<div class="flex items-center gap-3 mb-3">
			<label class="tag-label">Dimension</label>
			<select
				bind:value={dimension}
				style="padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);"
			>
				<option value="gender">Gender</option>
				<option value="ethnicity">Ethnicity</option>
				<option value="veteran">Veteran</option>
				<option value="disability">Disability</option>
			</select>
			<span style="font-size: 10px; color: var(--color-on-surface-dim); font-style: italic;">self-reported · voluntary</span>
		</div>

		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else}
			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Group Proportions Per Stage</div>
				{#if stackedOptions}
					<Chart options={stackedOptions} height="280px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No diversity data</div>
				{/if}
			</div>
			<div>
				<div class="tag-label" style="margin-bottom: 6px;">Pass-Through Across Stages</div>
				{#if dropoffOptions}
					<Chart options={dropoffOptions} height="260px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No drop-off data</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
