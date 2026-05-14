<script>
	import { onMount, onDestroy } from 'svelte';
	import Hourglass from '@lucide/svelte/icons/hourglass';

	let toasts = $state([]);
	let nextId = 0;

	function onToast(e) {
		const d = e.detail || {};
		const id = ++nextId;
		const ttl = d.ttl || 5000;
		toasts = [...toasts, {
			id,
			kind: d.kind || 'info',
			filename: d.filename || '',
			candidateId: d.candidateId || null,
			runId: d.runId || null,
			text: d.text || ''
		}];
		setTimeout(() => dismiss(id), ttl);
	}

	function dismiss(id) {
		toasts = toasts.filter(t => t.id !== id);
	}

	function openCli(t) {
		if (t.kind === 'dedup' && t.candidateId) {
			window.location.href = `/candidates/${t.candidateId}`;
		} else {
			window.dispatchEvent(new CustomEvent('hire-cli-open', { detail: { runId: t.runId, candidateId: t.candidateId } }));
		}
		dismiss(t.id);
	}

	onMount(() => {
		window.addEventListener('pulse-toast', onToast);
	});
	onDestroy(() => {
		if (typeof window !== 'undefined') window.removeEventListener('pulse-toast', onToast);
	});
</script>

<div class="pt-stack">
	{#each toasts as t (t.id)}
		<div class="pt-toast" class:pt-pipeline={t.kind === 'pipeline'} class:pt-dedup={t.kind === 'dedup'}>
			<button class="pt-body" onclick={() => openCli(t)} title={t.kind === 'dedup' ? 'View existing CV' : 'Open pipeline terminal'}>
				<span class="pt-icon">{#if t.kind === 'pipeline'}<Hourglass size={14} strokeWidth={1.75} />{:else if t.kind === 'dedup'}⊙{:else}•{/if}</span>
				<span class="pt-main">
					<span class="pt-title">
						{#if t.kind === 'pipeline'}CV ingest · queued
						{:else if t.kind === 'dedup'}Duplicate · skipped
						{:else}Event{/if}
					</span>
					<span class="pt-sub">{t.filename || ''}{t.text ? ' · ' + t.text : ''}</span>
				</span>
				<span class="pt-arrow">{t.kind === 'dedup' ? 'View profile →' : 'Open terminal →'}</span>
			</button>
			<button class="pt-x" onclick={() => dismiss(t.id)} aria-label="dismiss">×</button>
		</div>
	{/each}
</div>

<style>
	.pt-stack {
		position: fixed;
		top: 72px;
		right: 16px;
		z-index: 5000;
		display: flex;
		flex-direction: column;
		gap: 10px;
		font-family: var(--font-sans, 'Inter', -apple-system, system-ui, sans-serif);
		pointer-events: none;
	}
	.pt-toast {
		display: flex;
		align-items: stretch;
		min-width: 320px;
		max-width: 400px;
		background: var(--color-surface, #ffffff);
		color: var(--color-ink, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-left: 4px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius, 12px);
		box-shadow: var(--shadow-md, 0 4px 12px rgba(0,0,0,0.08));
		pointer-events: auto;
		animation: pt-in 180ms ease-out;
		overflow: hidden;
	}
	.pt-pipeline { border-left-color: var(--color-accent, #c96342); }
	.pt-pipeline .pt-title { color: var(--color-accent, #c96342); }
	.pt-dedup    { border-left-color: #d97706; }
	.pt-dedup .pt-title { color: #a06000; }
	.pt-body {
		flex: 1;
		display: grid;
		grid-template-columns: 22px 1fr auto;
		gap: 10px;
		align-items: center;
		padding: 11px 14px;
		background: transparent;
		color: inherit;
		border: none;
		text-align: left;
		cursor: pointer;
		font-family: inherit;
		min-width: 0;
	}
	.pt-body:hover { background: #faf9f5; }
	.pt-icon { font-size: 14px; }
	.pt-main { display: flex; flex-direction: column; min-width: 0; }
	.pt-title {
		font-size: 12.5px;
		font-weight: 600;
		letter-spacing: 0;
		text-transform: none;
		color: var(--color-ink, #2c2c2c);
	}
	.pt-sub {
		font-size: 12px;
		color: var(--color-muted, #6f6e69);
		margin-top: 3px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pt-arrow {
		font-size: 11.5px;
		font-weight: 500;
		letter-spacing: 0;
		color: var(--color-accent, #c96342);
		text-transform: none;
		white-space: nowrap;
	}
	.pt-x {
		padding: 0 12px;
		background: transparent;
		color: var(--color-muted, #6f6e69);
		border: none;
		border-left: 1px solid var(--color-border, #e8e6dd);
		font-size: 18px;
		font-weight: 400;
		cursor: pointer;
		transition: background .12s, color .12s;
	}
	.pt-x:hover { background: #f4f3ee; color: var(--color-ink, #2c2c2c); }

	@keyframes pt-in {
		from { transform: translateX(20px); opacity: 0; }
		to { transform: translateX(0); opacity: 1; }
	}
</style>
