<script>
	/**
	 * Reusable competency panel — used by JD detail and Position settings.
	 * Backend can be either JD or Position; URLs are passed in.
	 *
	 * Props:
	 *   listUrl       — GET endpoint returning array
	 *   saveUrl       — PUT endpoint accepting array body
	 *   autoExtractUrl — POST endpoint (optional)
	 *   syncFromJdUrl — POST endpoint (optional, position only)
	 *   title         — header text
	 */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';
	import { addToast } from '$lib/Toast.svelte';

	let { listUrl, saveUrl, autoExtractUrl = '', syncFromJdUrl = '', title = 'Competencies (KF4D)' } = $props();

	let library = $state([]);          // full library
	let libraryLoaded = $state(false);
	let rows = $state([]);             // competencies tagged on this entity
	let loading = $state(true);
	let saving = $state(false);
	let extracting = $state(false);
	let dirty = $state(false);
	let error = $state('');
	let showAdd = $state(false);
	let pickSelected = $state(new Set());

	$effect(() => {
		const u = listUrl;
		if (u) untrack(() => load());
	});

	async function loadLibrary() {
		if (libraryLoaded) return;
		try {
			const d = await apiJson('/competencies');
			library = d.competencies || d || [];
			libraryLoaded = true;
		} catch (e) {
			library = [];
			libraryLoaded = true;
		}
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const d = await apiJson(listUrl);
			rows = (Array.isArray(d) ? d : (d.competencies || d.items || [])).map(normalize);
			dirty = false;
			if (!libraryLoaded) loadLibrary();
		} catch (e) {
			rows = [];
			error = '';  // empty state, not error
		}
		loading = false;
	}

	function normalize(r) {
		return {
			competency_id: r.competency_id ?? r.id,
			key: r.key || r.competency_key || '',
			label: r.label || r.competency_label || r.key || '',
			required_level: Number(r.required_level ?? 3),
			importance: r.importance || 'required',
			weight: Number(r.weight ?? 1.0),
			notes: r.notes || '',
		};
	}

	function setLevel(idx, v) {
		rows[idx].required_level = v;
		dirty = true;
	}

	function removeRow(idx) {
		rows = rows.filter((_, i) => i !== idx);
		dirty = true;
	}

	async function save() {
		saving = true;
		try {
			const body = rows.map(r => ({
				competency_id: r.competency_id,
				required_level: r.required_level,
				importance: r.importance,
				weight: Number(r.weight) || 1.0,
				notes: r.notes || '',
			}));
			await apiJson(saveUrl, { method: 'PUT', body: JSON.stringify(body) });
			addToast('success', 'Competencies saved');
			dirty = false;
			await load();
		} catch (e) {
			addToast('error', e.message || 'Save failed');
		}
		saving = false;
	}

	async function autoExtract() {
		if (!autoExtractUrl) return;
		extracting = true;
		try {
			const d = await apiJson(autoExtractUrl, { method: 'POST' });
			const n = (d.extracted?.length ?? d.created ?? 0);
			addToast('success', `${n} competencies extracted`);
			await load();
		} catch (e) {
			addToast('error', e.message || 'Extract failed');
		}
		extracting = false;
	}

	async function syncFromJd() {
		if (!syncFromJdUrl) return;
		try {
			await apiJson(syncFromJdUrl, { method: 'POST' });
			addToast('success', 'Synced from JD');
			await load();
		} catch (e) {
			addToast('error', e.message || 'Sync failed');
		}
	}

	async function openAdd() {
		showAdd = true;
		pickSelected = new Set();
		await loadLibrary();
	}

	function togglePick(id) {
		if (pickSelected.has(id)) pickSelected.delete(id);
		else pickSelected.add(id);
		pickSelected = new Set(pickSelected);
	}

	function commitAdd() {
		const existing = new Set(rows.map(r => r.competency_id));
		const toAdd = library.filter(c => pickSelected.has(c.id) && !existing.has(c.id));
		for (const c of toAdd) {
			rows.push({
				competency_id: c.id,
				key: c.key,
				label: c.label,
				required_level: 3,
				importance: 'required',
				weight: 1.0,
				notes: '',
			});
		}
		rows = rows;
		dirty = true;
		showAdd = false;
	}

	let availableForAdd = $derived.by(() => {
		const existing = new Set(rows.map(r => r.competency_id));
		return library.filter(c => !existing.has(c.id));
	});
</script>

<div class="ink-border stamp-shadow mb-4" style="background: var(--color-surface-bright);">
	<div class="dark-title-bar flex items-center justify-between">
		<span>✦ {title}</span>
		<div class="flex gap-2 items-center">
			<button onclick={openAdd}
				style="background: transparent; color: var(--color-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
				+ Add
			</button>
			{#if autoExtractUrl}
				<button onclick={autoExtract} disabled={extracting}
					style="background: var(--color-primary-container, #00fc40); color: var(--color-on-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
					{extracting ? '…' : '✦ Auto-Extract'}
				</button>
			{/if}
			{#if syncFromJdUrl}
				<button onclick={syncFromJd}
					style="background: transparent; color: var(--color-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
					Sync from JD
				</button>
			{/if}
		</div>
	</div>
	<div style="padding: 14px 18px;">
		{#if loading}
			<div style="font-size: 11px; text-transform: uppercase; opacity: 0.7;">Loading…</div>
		{:else if rows.length === 0}
			<div style="font-size: 11px; color: var(--color-on-surface-dim); text-align: center; padding: 18px; text-transform: uppercase; letter-spacing: 0.05em; line-height: 1.6;">
				No competencies tagged.<br/>
				{autoExtractUrl ? 'Click ✦ AUTO-EXTRACT to let AI fill from JD text, or + Add to pick from library.' : 'Click + Add to pick from library.'}
			</div>
		{:else}
			<table style="width: 100%; border-collapse: collapse; font-size: 11px;">
				<thead>
					<tr style="background: var(--color-surface-highest, #f5f5e0); border-bottom: 2px solid var(--color-on-surface);">
						<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Competency</th>
						<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Required</th>
						<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Importance</th>
						<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Weight</th>
						<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Notes</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each rows as r, idx}
						<tr style="border-bottom: 1px solid var(--color-outline-variant);">
							<td style="padding: 6px 8px; font-weight: 700;">
								<div>{r.label || r.key}</div>
								<div style="font-size: 9px; color: var(--color-on-surface-dim); font-weight: 400;">{r.key}</div>
							</td>
							<td style="padding: 6px 8px;">
								<div style="display: inline-flex; gap: 2px;">
									{#each [1,2,3,4,5] as lv}
										<button type="button" onclick={() => setLevel(idx, lv)} title="Level {lv}"
											style="width: 18px; height: 18px; border: 1.5px solid var(--color-on-surface); background: {lv <= r.required_level ? 'var(--color-primary, #00fc40)' : 'var(--color-surface)'}; cursor: pointer; padding: 0;">
										</button>
									{/each}
								</div>
								<span style="margin-left: 6px; font-size: 10px; font-weight: 900;">{r.required_level}</span>
							</td>
							<td style="padding: 6px 8px;">
								<select bind:value={r.importance} onchange={() => dirty = true}
									style="border: 1.5px solid var(--color-on-surface); padding: 2px 6px; font-size: 11px; font-weight: 700; background: var(--color-surface);">
									<option value="required">required</option>
									<option value="preferred">preferred</option>
									<option value="nice">nice</option>
								</select>
							</td>
							<td style="padding: 6px 8px;">
								<input type="number" min="0" max="5" step="0.1" bind:value={r.weight}
									oninput={() => dirty = true}
									style="width: 60px; border: 1.5px solid var(--color-on-surface); padding: 2px 4px; font-size: 11px; font-weight: 700; background: var(--color-surface);" />
							</td>
							<td style="padding: 6px 8px;">
								<input type="text" bind:value={r.notes}
									oninput={() => dirty = true}
									placeholder="—"
									style="width: 100%; min-width: 120px; border: 1.5px solid var(--color-outline-variant); padding: 2px 6px; font-size: 11px; background: var(--color-surface);" />
							</td>
							<td style="padding: 6px 8px;">
								<button type="button" onclick={() => removeRow(idx)} title="Remove"
									style="background: transparent; border: 1px solid var(--color-error, #be2d06); color: var(--color-error, #be2d06); padding: 1px 6px; font-size: 11px; font-weight: 900; cursor: pointer;">✕</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>

			<div style="display: flex; gap: 8px; margin-top: 12px; justify-content: flex-end;">
				<button type="button" onclick={load} disabled={!dirty || saving}
					style="background: transparent; color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 5px 14px; font-size: 11px; font-weight: 700; cursor: pointer; text-transform: uppercase;">
					Reset
				</button>
				<button type="button" onclick={save} disabled={!dirty || saving}
					style="background: var(--color-primary, #00fc40); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 5px 14px; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
					{saving ? 'Saving…' : 'Save'}
				</button>
			</div>
		{/if}
	</div>
</div>

{#if showAdd}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.55); z-index: 9000; display: flex; align-items: center; justify-content: center; padding: 24px;"
		onclick={(e) => { if (e.target === e.currentTarget) showAdd = false; }} role="presentation">
		<div class="ink-border stamp-shadow" style="background: var(--color-surface-bright); width: 100%; max-width: 720px; max-height: 80vh; display: flex; flex-direction: column;" role="dialog">
			<div class="dark-title-bar flex items-center justify-between">
				<span>+ Add Competencies</span>
				<button onclick={() => showAdd = false} aria-label="Close" style="background: none; border: none; color: var(--color-surface); font-size: 18px; cursor: pointer;">✕</button>
			</div>
			<div style="padding: 14px 18px; flex: 1; overflow-y: auto;">
				{#if !libraryLoaded}
					<div style="font-size: 11px; text-transform: uppercase; opacity: 0.7;">Loading library…</div>
				{:else if availableForAdd.length === 0}
					<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase; padding: 18px; text-align: center;">
						All library competencies are already tagged.
					</div>
				{:else}
					<div style="font-size: 11px; opacity: 0.7; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;">{availableForAdd.length} available · {pickSelected.size} selected</div>
					<div style="display: flex; flex-direction: column; gap: 6px;">
						{#each availableForAdd as c}
							<label style="display: flex; align-items: flex-start; gap: 8px; padding: 8px 10px; border: 1.5px solid var(--color-outline-variant); cursor: pointer; background: {pickSelected.has(c.id) ? 'rgba(0,252,64,0.15)' : 'var(--color-surface)'};">
								<input type="checkbox" checked={pickSelected.has(c.id)} onchange={() => togglePick(c.id)} style="margin-top: 2px;" />
								<div style="flex: 1;">
									<div style="font-size: 12px; font-weight: 900;">{c.label || c.key}</div>
									<div style="font-size: 10px; color: var(--color-on-surface-dim); font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">{c.key}{c.category ? ` · ${c.category}` : ''}</div>
									{#if c.description}
										<div style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 2px; line-height: 1.4;">{c.description}</div>
									{/if}
								</div>
							</label>
						{/each}
					</div>
				{/if}
			</div>
			<div style="padding: 12px 18px; border-top: 2px solid var(--color-on-surface); display: flex; gap: 8px; justify-content: flex-end; background: var(--color-surface-highest, #f5f5e0);">
				<button onclick={() => showAdd = false}
					style="background: transparent; border: 2px solid var(--color-on-surface); padding: 5px 14px; font-size: 11px; font-weight: 700; cursor: pointer; text-transform: uppercase;">
					Cancel
				</button>
				<button onclick={commitAdd} disabled={pickSelected.size === 0}
					style="background: var(--color-primary, #00fc40); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 5px 14px; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
					Add {pickSelected.size}
				</button>
			</div>
		</div>
	</div>
{/if}
