<script>
	import { onMount } from 'svelte';
	import { apiJson, api } from '$lib/api.ts';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import X from '@lucide/svelte/icons/x';

	let dragOver = $state(false);
	let uploading = $state(false);
	let results = $state([]);
	let log = $state([]);
	let logFilter = $state('');

	async function uploadFiles(fileList) {
		const fd = new FormData();
		for (const f of fileList) fd.append('files', f);
		uploading = true;
		try {
			const r = await fetch('/api/ingest/', { method: 'POST', body: fd });
			const d = await r.json();
			results = [...d.results, ...results];
			await loadLog();
		} catch (e) {
			alert('Upload failed: ' + e.message);
		}
		uploading = false;
	}

	function onDrop(e) {
		e.preventDefault(); dragOver = false;
		if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
	}

	async function loadLog() {
		const url = '/ingest/log' + (logFilter ? `?status=${logFilter}` : '');
		try {
			const d = await apiJson(url);
			log = d.items || [];
		} catch {}
	}

	async function resolvePending(id, type) {
		try {
			await apiJson(`/ingest/log/${id}/resolve`, {
				method: 'POST', body: JSON.stringify({ classified_as: type }),
			});
			await loadLog();
		} catch (e) { alert(e.message); }
	}

	async function dismissPending(id) {
		try {
			await apiJson(`/ingest/log/${id}`, { method: 'DELETE' });
			await loadLog();
		} catch (e) { alert(e.message); }
	}

	function targetUrl(r) {
		if (r.target_type === 'candidate') return `/candidates/${r.target_id}`;
		if (r.target_type === 'jd') return `/jds/${r.target_id}`;
		return '#';
	}

	onMount(loadLog);
</script>

<div style="max-width: 1400px; margin: 0 auto; padding: 24px;">
	<div class="ink-border stamp-shadow" style="background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff); padding: 16px 22px; margin-bottom: 18px;">
		<div style="font-size: 22px; font-weight: 900; letter-spacing: 0.05em;">✦ INGEST AGENT</div>
		<div style="font-size: 11px; opacity: 0.7; letter-spacing: 0.08em; margin-top: 3px;">Drop ANY HR file · agent classifies + routes</div>
	</div>

	<!-- Drop zone -->
	<div role="button" tabindex="0"
		ondrop={onDrop}
		ondragover={(e) => { e.preventDefault(); dragOver = true; }}
		ondragleave={() => dragOver = false}
		class="ink-border stamp-shadow"
		style="background: {dragOver ? 'var(--color-accent-soft, #f5ece8)' : 'var(--color-surface-bright)'}; padding: 48px; text-align: center; cursor: pointer; transition: background 0.15s ease;"
		onclick={() => document.getElementById('ingest-input').click()}
		onkeydown={(e) => { if (e.key === 'Enter') document.getElementById('ingest-input').click(); }}>
		<div style="font-size: 32px; font-weight: 900;">▼ DROP FILES ▼</div>
		<div style="font-size: 12px; margin-top: 8px; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.06em;">
			pdf · docx · png · jpg · jpeg · webp · tiff · xlsx · txt
		</div>
		<div style="font-size: 11px; margin-top: 6px; opacity: 0.6;">
			AI auto-classifies as: CV · JD · OFFER · CERTIFICATE · OTHER
		</div>
		<input type="file" id="ingest-input" multiple
			accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.webp,.tiff,.bmp,.xlsx,.txt,.md"
			style="display: none;"
			onchange={(e) => { if (e.target.files?.length) uploadFiles(e.target.files); e.target.value = ''; }} />
	</div>

	{#if uploading}
		<div style="margin-top: 14px; font-size: 12px; color: var(--color-on-surface-dim); text-transform: uppercase; display: flex; align-items: center; gap: 6px;"><Hourglass size={14} strokeWidth={1.75} /> uploading + classifying…</div>
	{/if}

	<!-- Recent results -->
	{#if results.length}
		<div class="ink-border" style="margin-top: 18px; background: var(--color-surface-bright);">
			<div class="dark-title-bar">RECENT INGESTS</div>
			<div style="padding: 8px;">
				{#each results as r}
					<div class="ink-border" style="padding: 10px 14px; margin: 6px 0; background: var(--color-surface);">
						<div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;">
							<div>
								<strong>{r.filename}</strong>
								{#if r.classified_as}
									<span style="margin-left: 8px; padding: 2px 8px; background: var(--color-on-surface); color: var(--color-surface); font-size: 10px; font-weight: 900;">{r.classified_as}</span>
								{/if}
								{#if r.confidence !== undefined && r.confidence !== null}
									<span style="margin-left: 6px; font-size: 11px; opacity: 0.7;">{Math.round(r.confidence * 100)}%</span>
								{/if}
							</div>
							<div style="font-size: 10px; opacity: 0.7;">
								{r.elapsed_ms || 0}ms · {r.pipeline || '—'}
							</div>
						</div>
						<div style="font-size: 11px; opacity: 0.7; margin-top: 4px;">{r.reason || ''}</div>
						<div style="margin-top: 6px;">
							{#if r.status === 'success' && r.target_id}
								<a href={targetUrl(r)} class="send-btn" style="font-size: 10px; padding: 4px 10px; text-decoration: none;">OPEN →</a>
							{:else if r.status === 'pending_review'}
								<span style="font-size: 10px; color: var(--color-warning, #c98c2a); font-weight: 700; display: inline-flex; align-items: center; gap: 4px;"><AlertTriangle size={12} strokeWidth={1.75} /> PENDING REVIEW — see Admin</span>
							{:else if r.status === 'error'}
								<span style="font-size: 10px; color: var(--color-error); display: inline-flex; align-items: center; gap: 4px;"><X size={12} strokeWidth={1.75} /> {r.error_msg || 'error'}</span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Pending review queue -->
	<div class="ink-border" style="margin-top: 18px; background: var(--color-surface-bright);">
		<div class="dark-title-bar flex items-center justify-between">
			<span>INGEST LOG</span>
			<select bind:value={logFilter} onchange={loadLog} style="font-size: 10px; padding: 2px 6px; border: 1px solid var(--color-surface); background: var(--color-surface); color: var(--color-on-surface);">
				<option value="">all</option>
				<option value="success">success</option>
				<option value="pending_review">pending review</option>
				<option value="error">error</option>
				<option value="resolved">resolved</option>
				<option value="dismissed">dismissed</option>
			</select>
		</div>
		<div style="padding: 10px; max-height: 400px; overflow-y: auto;">
			{#if log.length === 0}
				<p style="opacity: 0.5; text-align: center; padding: 20px; font-size: 11px;">No items</p>
			{:else}
				<table style="width: 100%; border-collapse: collapse; font-size: 11px;">
					<thead>
						<tr style="background: var(--color-on-surface); color: var(--color-surface);">
							<th style="text-align: left; padding: 6px;">FILE</th>
							<th style="padding: 6px;">TYPE</th>
							<th style="padding: 6px;">CLASS</th>
							<th style="padding: 6px;">CONF</th>
							<th style="padding: 6px;">PIPELINE</th>
							<th style="padding: 6px;">STATUS</th>
							<th style="padding: 6px;">ACTIONS</th>
						</tr>
					</thead>
					<tbody>
						{#each log as item}
							<tr style="border-top: 1px solid rgba(56,56,50,0.15);">
								<td style="padding: 6px;">{item.filename}</td>
								<td style="text-align: center; padding: 6px;">{item.file_type}</td>
								<td style="text-align: center; padding: 6px;">{item.classified_as || '—'}</td>
								<td style="text-align: center; padding: 6px;">{item.confidence != null ? Math.round(item.confidence*100)+'%' : '—'}</td>
								<td style="text-align: center; padding: 6px;">{item.pipeline || '—'}</td>
								<td style="text-align: center; padding: 6px; font-weight: 700;">{item.status}</td>
								<td style="padding: 6px; text-align: center;">
									{#if item.status === 'pending_review'}
										<select onchange={(e) => resolvePending(item.id, e.target.value)} style="font-size: 10px; padding: 2px;">
											<option value="">classify…</option>
											<option value="CV">CV</option>
											<option value="JD">JD</option>
											<option value="OFFER">Offer</option>
											<option value="CERTIFICATE">Cert</option>
											<option value="OTHER">Other</option>
										</select>
										<button onclick={() => dismissPending(item.id)} style="margin-left: 4px; font-size: 10px; padding: 2px 6px; border: 1px solid #c00; background: transparent; color: #c00; cursor: pointer; display: inline-flex; align-items: center;"><X size={10} strokeWidth={1.75} /></button>
									{:else if item.target_id}
										<a href={item.target_type === 'candidate' ? `/candidates/${item.target_id}` : item.target_type === 'jd' ? `/jds/${item.target_id}` : '#'}
											style="font-size: 10px; color: var(--color-primary); font-weight: 700;">OPEN →</a>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	</div>
</div>
