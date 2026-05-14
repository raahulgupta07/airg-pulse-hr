<script>
	import { api, apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';

	let qoh = $state(null);
	let pending = $state([]);
	let period = $state('90d');
	let loading = $state(true);
	let saving = $state(false);
	let activeReview = $state(null); // {candidate_id, name, period}
	let form = $state({ rating: 3, retained: true, notes: '' });

	$effect(() => { load(); });

	async function load() {
		loading = true;
		try { qoh = await apiJson(`/analytics/v2/quality-of-hire?period=${period}`); } catch (e) { qoh = null; }
		try {
			const r = await apiJson('/analytics/v2/qoh/pending');
			pending = r?.items || [];
		} catch (e) { pending = []; }
		loading = false;
	}

	function openReview(item, p) {
		activeReview = { candidate_id: item.candidate_id, name: item.name, period: p };
		form = { rating: 3, retained: true, notes: '' };
	}

	async function submitReview() {
		if (!activeReview) return;
		saving = true;
		try {
			const body = { period: activeReview.period, rating: form.rating, retained: form.retained, notes: form.notes };
			const res = await api(`/analytics/v2/qoh/${activeReview.candidate_id}`, { method: 'POST', body: JSON.stringify(body) });
			if (!res.ok) throw new Error(`status ${res.status}`);
			activeReview = null;
			await load();
		} catch (e) {
			console.warn('qoh submit failed', e);
		}
		saving = false;
	}

	let bySourceOptions = $derived.by(() => {
		const rows = qoh?.by_source || [];
		if (!rows.length) return null;
		return {
			grid: { left: 100, right: 20, top: 20, bottom: 30 },
			xAxis: { type: 'value', max: 5, axisLabel: { fontSize: 10 } },
			yAxis: { type: 'category', data: rows.map(r => r.source || r.label || '—'), axisLabel: { fontSize: 10 } },
			tooltip: { trigger: 'axis' },
			series: [{ type: 'bar', data: rows.map(r => r.avg_rating || 0), itemStyle: { color: '#007518' }, label: { show: true, position: 'right', fontSize: 10, formatter: p => p.value.toFixed(2) } }]
		};
	});
</script>

<div class="mb-6" id="quality-of-hire">
	<div class="dark-title-bar">QUALITY OF HIRE</div>
	<div class="ink-border stamp-shadow" style="background: var(--color-surface); padding: 16px;">
		<div class="flex items-center gap-2 mb-3">
			<label class="tag-label">Period</label>
			<select
				bind:value={period}
				onchange={load}
				style="padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);"
			>
				<option value="90d">90 Days</option>
				<option value="180d">180 Days</option>
				<option value="360d">360 Days</option>
			</select>
		</div>

		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase;">Loading…</div>
		{:else}
			<div class="grid grid-cols-2 gap-3 mb-4">
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Avg Rating</div>
					<div style="font-size: 32px; font-weight: 900;">{(qoh?.avg_rating ?? 0).toFixed?.(2) ?? qoh?.avg_rating ?? '—'}<span style="font-size: 12px; font-weight: 700;">/5</span></div>
				</div>
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="font-size: 9px;">Retention</div>
					<div style="font-size: 32px; font-weight: 900;">{(qoh?.retention_pct ?? 0).toFixed?.(1) ?? qoh?.retention_pct ?? 0}%</div>
				</div>
			</div>

			<div class="mb-4">
				<div class="tag-label" style="margin-bottom: 6px;">Avg Rating By Source</div>
				{#if bySourceOptions}
					<Chart options={bySourceOptions} height="240px" />
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No source data</div>
				{/if}
			</div>

			<div>
				<div class="tag-label" style="margin-bottom: 6px;">Pending Reviews</div>
				{#if !pending.length}
					<div style="font-size: 11px; color: var(--color-on-surface-dim);">No pending reviews</div>
				{:else}
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th>Name</th>
									<th>Hired At</th>
									<th>Period Due</th>
									<th>Submit Review</th>
								</tr>
							</thead>
							<tbody>
								{#each pending as it}
									<tr>
										<td style="font-weight: 700;">{it.name || '—'}</td>
										<td>{it.hired_at || '—'}</td>
										<td>{it.period_due || '—'}</td>
										<td>
											<div class="flex gap-1">
												<button class="btn-secondary" style="font-size: 9px; padding: 4px 8px;" onclick={() => openReview(it, '90d')}>90d</button>
												<button class="btn-secondary" style="font-size: 9px; padding: 4px 8px;" onclick={() => openReview(it, '180d')}>180d</button>
												<button class="btn-secondary" style="font-size: 9px; padding: 4px 8px;" onclick={() => openReview(it, '360d')}>360d</button>
											</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>

			{#if activeReview}
				<div class="ink-border mt-4" style="background: var(--color-surface-bright); padding: 12px;">
					<div class="tag-label" style="margin-bottom: 6px;">Review {activeReview.name} · {activeReview.period}</div>
					<div class="mb-2">
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Rating</label>
						<div class="flex gap-1">
							{#each [1, 2, 3, 4, 5] as n}
								<button
									onclick={() => form.rating = n}
									style="background: {n <= form.rating ? '#ff9d00' : 'var(--color-surface)'}; border: 2px solid var(--color-on-surface); width: 30px; height: 30px; cursor: pointer; font-weight: 900; font-family: 'Space Grotesk';"
								>{n}</button>
							{/each}
						</div>
					</div>
					<div class="mb-2">
						<label style="font-size: 10px; font-weight: 700; text-transform: uppercase;">
							<input type="checkbox" bind:checked={form.retained} /> Retained
						</label>
					</div>
					<div class="mb-2">
						<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block;">Notes</label>
						<textarea bind:value={form.notes} rows="3" style="width: 100%; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);"></textarea>
					</div>
					<div class="flex gap-2">
						<button class="send-btn" disabled={saving} onclick={submitReview}>
							{saving ? 'Saving…' : 'Submit Review'}
						</button>
						<button class="btn-secondary" onclick={() => activeReview = null}>Cancel</button>
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>
