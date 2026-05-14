<script>
	import PipelineStepper from '$lib/PipelineStepper.svelte';
	import { apiJson } from '$lib/api';

	let { candidateId, runId = null, filename = '', onClose = () => {} } = $props();

	let allTerminal = $state(false);
	let autoCloseTimer = null;
	let pollInterval = null;

	const TERMINAL = new Set(['done', 'error', 'skipped']);

	async function checkTerminal() {
		try {
			const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
			const data = await apiJson(`/candidates/${candidateId}/pipeline_trace${qs}`);
			const run = (data.runs || [])[0];
			if (run && run.steps && run.steps.length > 0) {
				const done = run.steps.every(s => TERMINAL.has(s.status));
				if (done) {
					allTerminal = true;
					if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
					autoCloseTimer = setTimeout(() => onClose(), 6000);
				}
			}
		} catch (_) {}
	}

	$effect(() => {
		pollInterval = setInterval(checkTerminal, 1200);
		return () => {
			if (pollInterval) clearInterval(pollInterval);
			if (autoCloseTimer) clearTimeout(autoCloseTimer);
		};
	});

	function handleClose() {
		if (autoCloseTimer) clearTimeout(autoCloseTimer);
		if (pollInterval) clearInterval(pollInterval);
		onClose();
	}
</script>

<div class="upm-overlay">
	<div class="upm-modal ink-border stamp-shadow">
		<div class="upm-titlebar">
			<span class="upm-title">CV INGEST · {filename || `Candidate #${candidateId}`}</span>
			<button
				class="upm-close"
				disabled={!allTerminal}
				onclick={handleClose}
				title={allTerminal ? 'Close' : 'Wait for pipeline to finish'}
			>✕</button>
		</div>
		<div class="upm-body">
			<PipelineStepper {candidateId} {runId} live={true} />
		</div>
		{#if allTerminal}
			<div class="upm-footer">Pipeline complete. Auto-closing…</div>
		{/if}
	</div>
</div>

<style>
	.upm-overlay {
		position: fixed;
		inset: 0;
		background: rgba(56,56,50,0.35);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 60px 20px;
		z-index: 9999;
		font-family: 'Space Grotesk', monospace;
	}
	.upm-modal {
		background: var(--color-bg, #faf9f5);
		max-width: 720px;
		width: 100%;
		max-height: 85vh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		border-radius: 8px;
	}
	.upm-titlebar {
		background: var(--color-accent, #c96342);
		color: #fff;
		padding: 10px 14px;
		display: flex;
		justify-content: space-between;
		align-items: center;
		border-bottom: 1px solid var(--color-border, #d8d5cc);
		border-radius: 8px 8px 0 0;
	}
	.upm-title {
		font-weight: 900;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.upm-close {
		background: rgba(255,255,255,0.15);
		color: #fff;
		border: none;
		width: 24px;
		height: 24px;
		font-weight: 900;
		cursor: pointer;
		font-size: 12px;
		border-radius: 4px;
	}
	.upm-close:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.upm-body {
		overflow-y: auto;
		flex: 1;
		padding: 12px;
	}
	.upm-footer {
		background: #3a8a4f;
		color: #fff;
		padding: 6px 14px;
		font-size: 10px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		text-align: center;
		border-radius: 0 0 8px 8px;
	}
</style>
