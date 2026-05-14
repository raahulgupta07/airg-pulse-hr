<script>
	/** Field-level merge review modal. */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';
	import { addToast } from '$lib/Toast.svelte';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	let { proposalId, onClose, onResolved } = $props();

	let loading = $state(true);
	let submitting = $state(false);
	let error = $state('');
	let proposal = $state(null);
	let fieldChoices = $state({}); // {field: 'winner'|'loser'|'merged'|customValue}
	let archive = $state(true);
	let rejectNotes = $state('');
	let showReject = $state(false);

	$effect(() => {
		const pid = proposalId;
		if (pid) untrack(() => loadProposal());
	});

	async function loadProposal() {
		loading = true;
		error = '';
		try {
			const data = await apiJson(`/merges/${proposalId}`);
			proposal = data;
			// initialise field choices
			const init = {};
			const diff = data.diff || {};
			for (const [field, info] of Object.entries(diff)) {
				if (Array.isArray(info?.winner) || Array.isArray(info?.loser)) {
					init[field] = 'merged';
				} else {
					init[field] = 'winner';
				}
			}
			fieldChoices = init;
		} catch (e) {
			error = e.message || 'Failed to load merge proposal';
		}
		loading = false;
	}

	function isArrayField(field) {
		const info = proposal?.diff?.[field];
		return Array.isArray(info?.winner) || Array.isArray(info?.loser);
	}

	function fieldsToShow() {
		if (!proposal?.diff) return [];
		return Object.keys(proposal.diff);
	}

	function rowFields() {
		// preferred header rows for the 3-col grid
		const preferred = ['name', 'full_name', 'email', 'phone', 'role', 'current_role', 'current_company', 'location', 'skills', 'title', 'company'];
		const have = fieldsToShow();
		const ordered = preferred.filter(p => have.includes(p));
		const rest = have.filter(p => !preferred.includes(p));
		return [...ordered, ...rest];
	}

	function fmtVal(v) {
		if (v == null) return '—';
		if (Array.isArray(v)) {
			const head = v.slice(0, 5).join(', ');
			return v.length > 5 ? `${head}, +${v.length - 5}` : head || '—';
		}
		if (typeof v === 'object') return JSON.stringify(v).slice(0, 60);
		const s = String(v);
		return s.length > 60 ? s.slice(0, 60) + '…' : s;
	}

	function resultVal(field) {
		const info = proposal?.diff?.[field];
		if (!info) return '—';
		const choice = fieldChoices[field];
		if (choice === 'winner') return info.winner;
		if (choice === 'loser') return info.loser;
		if (choice === 'merged') {
			if (Array.isArray(info.winner) || Array.isArray(info.loser)) {
				const w = Array.isArray(info.winner) ? info.winner : [];
				const l = Array.isArray(info.loser) ? info.loser : [];
				return Array.from(new Set([...w, ...l]));
			}
			return info.suggested ?? info.winner;
		}
		return choice;
	}

	function fieldsDiffer(info) {
		try { return JSON.stringify(info?.winner) !== JSON.stringify(info?.loser); }
		catch { return true; }
	}

	async function approve() {
		submitting = true;
		try {
			await apiJson(`/merges/${proposalId}/approve`, {
				method: 'POST',
				body: JSON.stringify({ field_choices: fieldChoices, archive }),
			});
			addToast('success', 'Merge approved');
			onResolved?.();
			onClose?.();
		} catch (e) {
			addToast('error', e.message || 'Approve failed');
		}
		submitting = false;
	}

	async function reject() {
		submitting = true;
		try {
			await apiJson(`/merges/${proposalId}/reject`, {
				method: 'POST',
				body: JSON.stringify({ notes: rejectNotes || undefined }),
			});
			addToast('success', 'Marked as not a duplicate');
			onResolved?.();
			onClose?.();
		} catch (e) {
			addToast('error', e.message || 'Reject failed');
		}
		submitting = false;
	}

	function recordLabel(rec, fallback) {
		if (!rec) return fallback;
		return rec.full_name || rec.name || rec.title || rec.email || `#${rec.id}`;
	}
</script>

<div class="merge-overlay" onclick={onClose} role="presentation">
	<div class="merge-modal ink-border stamp-shadow" onclick={(e) => e.stopPropagation()} role="dialog">
		<div class="dark-title-bar" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 18px;">
			<div>
				<div style="font-size: 14px; font-weight: 900; letter-spacing: 0.05em;">
					MERGE REVIEW
					{#if proposal}
						— {recordLabel(proposal.winner, `#${proposal.winner_id}`)} (#{proposal.winner_id})
						↔ {recordLabel(proposal.loser, `#${proposal.loser_id}`)} (#{proposal.loser_id})
					{/if}
				</div>
				{#if proposal}
					<div style="font-size: 10px; opacity: 0.7; letter-spacing: 0.08em; margin-top: 2px;">
						confidence {Math.round((proposal.confidence || 0) * 100)}% · method: {proposal.method || '—'} · entity: {proposal.entity_type || '—'}
					</div>
				{/if}
			</div>
			<button onclick={onClose} aria-label="Close" style="background: none; border: none; color: var(--color-surface-bright, #fff); font-size: 22px; cursor: pointer; line-height: 1;"><X size={18} strokeWidth={2} /></button>
		</div>

		<div class="merge-body">
			{#if loading}
				<div style="padding: 40px; text-align: center; opacity: 0.6;">Loading proposal…</div>
			{:else if error}
				<div style="padding: 20px; color: #c00;">{error}</div>
			{:else if proposal}
				<!-- 3-column comparison -->
				<div class="merge-grid">
					<div class="grid-head">FIELD</div>
					<div class="grid-head" style="background: #3a8a4f; color: #fff;">#{proposal.winner_id} (KEEP)</div>
					<div class="grid-head" style="background: #ffd6d6;">#{proposal.loser_id} (DISCARD)</div>
					<div class="grid-head" style="background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff);">RESULT</div>

					{#each rowFields() as f}
						{@const info = proposal.diff[f]}
						{@const differs = fieldsDiffer(info)}
						<div class="grid-cell label-cell">{f}{isArrayField(f) ? ` (${(info.winner || []).length}/${(info.loser || []).length})` : ''}</div>
						<div class="grid-cell" style="background: {differs ? '#fff' : '#f5f5e0'};">{fmtVal(info.winner)}</div>
						<div class="grid-cell" style="background: {differs ? '#ffeaea' : '#f5f5e0'};">{fmtVal(info.loser)}</div>
						<div class="grid-cell" style="background: #f0fff0; font-weight: 700;">
							{#if isArrayField(f) && fieldChoices[f] === 'merged'}
								MERGED ({(resultVal(f) || []).length}) · {fmtVal(resultVal(f))}
							{:else}
								{fmtVal(resultVal(f))}
							{/if}
						</div>
					{/each}
				</div>

				<!-- Field-level toggles -->
				<div style="margin-top: 18px;">
					<div style="font-size: 11px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 8px;">FIELD-LEVEL TOGGLES</div>
					<div class="toggles">
						{#each rowFields() as f}
							{@const info = proposal.diff[f]}
							{#if fieldsDiffer(info)}
								<div class="toggle-row">
									<div class="toggle-label">{f}:</div>
									<div class="toggle-options">
										{#if isArrayField(f)}
											<label class="toggle-opt" class:active={fieldChoices[f] === 'merged'}>
												<input type="radio" bind:group={fieldChoices[f]} value="merged" /> MERGED
											</label>
										{/if}
										<label class="toggle-opt" class:active={fieldChoices[f] === 'winner'}>
											<input type="radio" bind:group={fieldChoices[f]} value="winner" /> #{proposal.winner_id}
										</label>
										<label class="toggle-opt" class:active={fieldChoices[f] === 'loser'}>
											<input type="radio" bind:group={fieldChoices[f]} value="loser" /> #{proposal.loser_id}
										</label>
									</div>
								</div>
							{/if}
						{/each}
					</div>
				</div>

				<!-- Loser handling -->
				<div style="margin-top: 18px;">
					<div style="font-size: 11px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 8px;">LOSER HANDLING</div>
					<label style="display: block; font-size: 12px; margin-bottom: 4px; cursor: pointer;">
						<input type="radio" bind:group={archive} value={true} /> ARCHIVE (soft-delete, can revert)
					</label>
					<label style="display: block; font-size: 12px; cursor: pointer;">
						<input type="radio" bind:group={archive} value={false} /> HARD DELETE (irreversible)
					</label>
				</div>

				{#if showReject}
					<div style="margin-top: 14px;">
						<div style="font-size: 11px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 6px;">REJECT — REASON (optional)</div>
						<textarea bind:value={rejectNotes} placeholder="Why are these not duplicates?"
							style="width: 100%; border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px; padding: 8px; font-family: inherit; min-height: 60px;"></textarea>
					</div>
				{/if}
			{/if}
		</div>

		<div class="merge-footer">
			<button class="btn-secondary" onclick={onClose} disabled={submitting}>CANCEL</button>
			<div style="flex: 1;"></div>
			{#if showReject}
				<button class="btn-secondary" onclick={() => (showReject = false)} disabled={submitting}>BACK</button>
				<button class="send-btn" style="background: #c00; color: #fff;" onclick={reject} disabled={submitting}><X size={14} strokeWidth={2} /> CONFIRM REJECT</button>
			{:else}
				<button class="btn-secondary" onclick={() => (showReject = true)} disabled={submitting || loading}><X size={14} strokeWidth={2} /> REJECT — NOT DUP</button>
				<button class="send-btn" onclick={approve} disabled={submitting || loading}><Check size={14} strokeWidth={2} /> APPROVE MERGE</button>
			{/if}
		</div>
	</div>
</div>

<style>
	.merge-overlay {
		position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 9000;
		display: flex; align-items: center; justify-content: center; padding: 20px;
	}
	.merge-modal {
		background: var(--color-bg, #faf9f5); max-width: 1100px; width: 100%; max-height: 90vh;
		display: flex; flex-direction: column; font-family: 'Space Grotesk', sans-serif;
		border-radius: 8px;
	}
	.merge-body { overflow-y: auto; padding: 18px; flex: 1; }
	.merge-footer {
		display: flex; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--color-border, #d8d5cc);
		background: var(--color-surface-bright, #fff); align-items: center;
		border-radius: 0 0 8px 8px;
	}
	.merge-grid {
		display: grid; grid-template-columns: 140px 1fr 1fr 1fr;
		border: 1px solid var(--color-border, #d8d5cc); font-size: 12px;
		border-radius: 6px; overflow: hidden;
	}
	.grid-head {
		padding: 8px 10px; font-weight: 900; letter-spacing: 0.05em;
		font-size: 11px; background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff);
		border-right: 1px solid rgba(255,255,255,0.15);
	}
	.grid-cell {
		padding: 6px 10px; border-top: 1px solid #ddd; border-right: 1px solid #eee;
		word-break: break-word; overflow-wrap: anywhere;
	}
	.label-cell { background: #f5f5e0; font-weight: 700; text-transform: uppercase; font-size: 10px; }
	.toggles { display: flex; flex-direction: column; gap: 4px; }
	.toggle-row {
		display: flex; align-items: center; gap: 10px;
		padding: 4px 0; border-bottom: 1px dashed #ccc;
	}
	.toggle-label { font-size: 11px; font-weight: 700; min-width: 100px; text-transform: uppercase; }
	.toggle-options { display: flex; gap: 6px; }
	.toggle-opt {
		display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
		border: 1px solid var(--color-border, #d8d5cc); font-size: 10px; font-weight: 700; cursor: pointer;
		background: var(--color-surface-bright, #fff); letter-spacing: 0.04em;
		border-radius: 4px;
	}
	.toggle-opt.active { background: #3a8a4f; color: #fff; border-color: #3a8a4f; }
	.toggle-opt input { margin: 0; }
</style>
