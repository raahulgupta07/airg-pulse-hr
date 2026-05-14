<script>
	import { api, apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';

	let groupBy = $state('channel');
	let cphData = $state(null);
	let cphByDept = $state(null);
	let costRows = $state([]);
	let loading = $state(true);
	let saving = $state(false);
	let formError = $state('');

	let form = $state({
		period_start: '',
		period_end: '',
		category: '',
		channel: '',
		amount: '',
		currency: 'USD',
		notes: ''
	});

	$effect(() => { load(); });
	$effect(() => { loadCph(groupBy); });

	async function load() {
		loading = true;
		try { costRows = await apiJson('/analytics/v2/costs'); } catch (e) { costRows = []; }
		try { cphByDept = await apiJson('/analytics/v2/cost-per-hire?group_by=department'); } catch (e) { cphByDept = null; }
		loading = false;
	}
	async function loadCph(g) {
		try { cphData = await apiJson(`/analytics/v2/cost-per-hire?group_by=${g}`); } catch (e) { cphData = null; }
	}

	async function submitCost() {
		formError = '';
		if (!form.period_start || !form.period_end || !form.amount) {
			formError = 'period_start, period_end, amount required';
			return;
		}
		saving = true;
		try {
			const body = {
				period_start: form.period_start,
				period_end: form.period_end,
				category: form.category || null,
				channel: form.channel || null,
				amount: parseFloat(form.amount),
				currency: form.currency || 'USD',
				notes: form.notes || null
			};
			const res = await api('/analytics/v2/costs', { method: 'POST', body: JSON.stringify(body) });
			if (!res.ok) throw new Error(`status ${res.status}`);
			form = { period_start: '', period_end: '', category: '', channel: '', amount: '', currency: 'USD', notes: '' };
			await load();
		} catch (e) {
			formError = e.message;
		}
		saving = false;
	}

	let channelTable = $derived.by(() => {
		const rows = cphData?.by || [];
		return [...rows].sort((a, b) => {
			const aRatio = (a.hires || 0) / Math.max(a.spend || 1, 1);
			const bRatio = (b.hires || 0) / Math.max(b.spend || 1, 1);
			return bRatio - aRatio;
		});
	});

	let deptBarOptions = $derived.by(() => {
		const rows = cphByDept?.by || [];
		if (!rows.length) return null;
		return {
			grid: { left: 100, right: 20, top: 20, bottom: 30 },
			xAxis: { type: 'value', axisLabel: { fontSize: 10, formatter: v => '$' + v } },
			yAxis: { type: 'category', data: rows.map(r => r.label || r.department || '—'), axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis', valueFormatter: v => '$' + v.toLocaleString() },
			series: [{ type: 'bar', data: rows.map(r => r.cost_per_hire || 0), itemStyle: { color: '#be2d06' }, label: { show: true, position: 'right', fontSize: 10, formatter: p => '$' + Math.round(p.value) } }]
		};
	});
</script>

<div class="mb-6" id="cost-per-hire">
	<div class="dark-title-bar">COST PER HIRE</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else}
			<div class="grid grid-cols-3 gap-3 mb-4">
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Total Spend</div>
					<div style="font-size: 24px; font-weight: 900;">${(cphData?.total_spend ?? 0).toLocaleString?.() ?? cphData?.total_spend ?? '0'}</div>
				</div>
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Hires</div>
					<div style="font-size: 24px; font-weight: 900;">{cphData?.hires ?? 0}</div>
				</div>
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Cost Per Hire</div>
					<div style="font-size: 24px; font-weight: 900;">${(cphData?.cost_per_hire ?? 0).toLocaleString?.() ?? cphData?.cost_per_hire ?? '0'}</div>
				</div>
			</div>

			<div class="flex items-center gap-2 mb-2">
				<label class="tag-label">Group By</label>
				<select
					bind:value={groupBy}
					style="padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);"
				>
					<option value="channel">Channel</option>
					<option value="department">Department</option>
				</select>
			</div>

			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Channel ROI (sorted by hires per $)</div>
				{#if !channelTable.length}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No channel data</div>
				{:else}
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th>{groupBy === 'channel' ? 'Channel' : 'Department'}</th>
									<th>Spend</th>
									<th>Hires</th>
									<th>Cost / Hire</th>
									<th>Hires / $1k</th>
								</tr>
							</thead>
							<tbody>
								{#each channelTable as r}
									<tr>
										<td>{r.label || r.channel || r.department || '—'}</td>
										<td>${(r.spend ?? 0).toLocaleString?.() ?? r.spend ?? 0}</td>
										<td>{r.hires ?? 0}</td>
										<td>${(r.cost_per_hire ?? 0).toLocaleString?.() ?? r.cost_per_hire ?? 0}</td>
										<td>{((r.hires || 0) / Math.max((r.spend || 1) / 1000, 0.001)).toFixed(2)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>

			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Cost Per Hire By Department</div>
				{#if deptBarOptions}
					<Chart options={deptBarOptions} height="260px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No department data</div>
				{/if}
			</div>

			<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
				<div class="tag-label" style="margin-bottom: 8px;">Add Cost Row</div>
				<div class="grid grid-cols-3 gap-2 mb-2">
					<div>
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Period Start</label>
						<input type="date" bind:value={form.period_start} style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
					</div>
					<div>
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Period End</label>
						<input type="date" bind:value={form.period_end} style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
					</div>
					<div>
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Amount</label>
						<input type="number" bind:value={form.amount} placeholder="0.00" style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
					</div>
					<div>
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Category</label>
						<input type="text" bind:value={form.category} placeholder="job_board / agency / referral" style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
					</div>
					<div>
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Channel</label>
						<input type="text" bind:value={form.channel} placeholder="linkedin, indeed..." style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
					</div>
					<div>
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Currency</label>
						<input type="text" bind:value={form.currency} style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
					</div>
				</div>
				<div class="mb-2">
					<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Notes</label>
					<input type="text" bind:value={form.notes} style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
				</div>
				{#if formError}
					<div style="font-size: 10px; color: var(--color-error); margin-bottom: 4px;">{formError}</div>
				{/if}
				<button class="send-btn" disabled={saving} onclick={submitCost}>
					{saving ? 'Saving…' : 'Add Cost'}
				</button>
				{#if costRows?.length}
					<div style="font-size: 10px; margin-top: 8px; color: var(--color-on-surface-dim);">{costRows.length} cost rows tracked</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
