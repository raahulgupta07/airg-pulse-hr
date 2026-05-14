<script>
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import PauseCircle from '@lucide/svelte/icons/pause-circle';

	let { files = [] } = $props();

	let visible = $state(true);
	let collapseTimer = null;

	function fmtSize(b) {
		if (!b) return '—';
		if (b < 1024) return `${b}B`;
		if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)}KB`;
		return `${(b / 1024 / 1024).toFixed(1)}MB`;
	}

	function statusLabel(s) {
		if (s === 'done') return 'DONE';
		if (s === 'error') return 'ERROR';
		if (s === 'queued') return 'QUEUED';
		if (s === 'uploading') return '';
		return s;
	}
	function statusIconComp(s) {
		if (s === 'done') return Check;
		if (s === 'error') return X;
		if (s === 'queued') return PauseCircle;
		if (s === 'uploading') return Hourglass;
		return null;
	}

	let total = $derived(files.length);
	let doneCount = $derived(files.filter(f => f.status === 'done' || f.status === 'error').length);
	let allDone = $derived(total > 0 && doneCount === total);

	// B3 — auto-collapse 3s after all uploads terminate
	$effect(() => {
		if (allDone) {
			if (collapseTimer) clearTimeout(collapseTimer);
			collapseTimer = setTimeout(() => { visible = false; }, 3000);
		} else {
			visible = true;
			if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = null; }
		}
		return () => { if (collapseTimer) clearTimeout(collapseTimer); };
	});

	function progressBar(p) {
		const filled = Math.round((p || 0) / 100 * 12);
		return '█'.repeat(filled) + '░'.repeat(12 - filled);
	}
</script>

{#if total > 0 && visible}
	<div class="ink-border stamp-shadow mb-4 ut-fade" style="background: var(--color-surface-bright);">
		<div class="dark-title-bar flex items-center justify-between">
			<span>✦ UPLOADING ({doneCount}/{total})</span>
			{#if allDone}
				<button class="ut-close" onclick={() => (visible = false)}>✕ CLOSE</button>
			{/if}
		</div>
		<table style="width: 100%; border-collapse: collapse; font-size: 12px;">
			<thead>
				<tr style="background: var(--color-on-surface); color: var(--color-surface);">
					<th style="padding: 6px 10px; text-align: left;">FILE</th>
					<th style="padding: 6px 10px; text-align: center;">SIZE</th>
					<th style="padding: 6px 10px; text-align: left; width: 40%;">PROGRESS</th>
					<th style="padding: 6px 10px; text-align: right;">STATUS</th>
				</tr>
			</thead>
			<tbody>
				{#each files as f (f.id)}
					<tr style="border-top: 1px solid rgba(56,56,50,0.15); background: var(--color-surface);">
						<td style="padding: 6px 10px; font-weight: 700; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
							{f.name}
						</td>
						<td style="padding: 6px 10px; text-align: center; font-variant-numeric: tabular-nums;">
							{fmtSize(f.size)}
						</td>
						<td style="padding: 6px 10px;">
							<div class="ut-bar-wrap">
								<div class="ut-bar-fill"
									class:ut-bar-error={f.status === 'error'}
									style="width: {f.status === 'error' ? 100 : (f.progress || 0)}%"></div>
								<span class="ut-bar-pct">
									<span class="ut-ascii">{progressBar(f.progress)}</span>
									<span class="ut-pct">{f.progress || 0}%</span>
								</span>
							</div>
						</td>
						<td style="padding: 6px 10px; text-align: right; font-weight: 900; font-size: 11px;"
							class:ut-st-done={f.status === 'done'}
							class:ut-st-error={f.status === 'error'}>
							{#if statusIconComp(f.status)}<svelte:component this={statusIconComp(f.status)} size={12} stroke-width={2} />{/if} {statusLabel(f.status)}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.ut-fade {
		animation: ut-slide-in 200ms ease-out;
	}
	@keyframes ut-slide-in {
		from { opacity: 0; transform: translateY(-6px); }
		to { opacity: 1; transform: translateY(0); }
	}
	.ut-bar-wrap {
		position: relative;
		background: rgba(56,56,50,0.10);
		border: 1.5px solid var(--color-on-surface);
		height: 22px;
		overflow: hidden;
	}
	.ut-bar-fill {
		background: var(--color-primary-container, #00fc40);
		height: 100%;
		transition: width 120ms linear;
	}
	.ut-bar-error { background: var(--color-error, #cc3333); }
	.ut-bar-pct {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 8px;
		font-family: 'Space Grotesk', monospace;
		font-size: 10px;
		font-weight: 900;
		color: var(--color-on-surface);
		mix-blend-mode: difference;
		filter: invert(1) grayscale(1) contrast(99);
	}
	.ut-ascii { letter-spacing: -1px; }
	.ut-pct { font-variant-numeric: tabular-nums; }
	.ut-close {
		background: transparent;
		color: var(--color-surface);
		border: 1px solid var(--color-surface);
		padding: 2px 8px;
		font-size: 10px;
		cursor: pointer;
		font-weight: 700;
	}
	.ut-st-done { color: var(--color-primary, #007518); }
	.ut-st-error { color: var(--color-error, #c40000); }
</style>
