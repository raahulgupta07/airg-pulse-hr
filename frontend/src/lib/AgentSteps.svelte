<script>
	/** AgentSteps — vertical timeline for chat v2 agent run.
	 *  Renders each reasoning step + child ToolTrace boxes for tools invoked. */
	import ToolTrace from './ToolTrace.svelte';

	let { steps = [], active = false } = $props();

	function isStepRunning(step, idx, total) {
		if (!active) return false;
		if (idx !== total - 1) return false;
		// last step is "running" if it has any running tool, or no tools yet
		if (!step.tools || step.tools.length === 0) return true;
		return step.tools.some((t) => (t.status || 'running') === 'running');
	}
</script>

<div class="as-wrap">
	<div class="as-header">
		<span class="as-title">AGENT TRACE</span>
		<span class="as-meta">{steps.length} STEP{steps.length === 1 ? '' : 'S'}</span>
	</div>

	<div class="as-timeline">
		{#each steps as step, i}
			{@const running = isStepRunning(step, i, steps.length)}
			<div class="as-step" class:as-step-running={running}>
				<div class="as-rail">
					<div class="as-num" class:as-num-running={running}>
						{#if running}
							<span class="as-spinner"></span>
						{:else}
							{step.idx ?? i + 1}
						{/if}
					</div>
					{#if i < steps.length - 1}
						<div class="as-line"></div>
					{/if}
				</div>
				<div class="as-content">
					{#if step.reasoning}
						<div class="as-reasoning">{step.reasoning}</div>
					{:else if running}
						<div class="as-reasoning as-reasoning-dim">THINKING…</div>
					{/if}
					{#if step.tools && step.tools.length > 0}
						<div class="as-tools">
							{#each step.tools as t}
								<ToolTrace tool={t} />
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/each}

		{#if steps.length === 0 && active}
			<div class="as-empty">
				<span class="as-spinner as-spinner-lg"></span>
				<span>PLANNING…</span>
			</div>
		{/if}
	</div>
</div>

<style>
	.as-wrap {
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #d8d5cc);
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
		margin-bottom: 12px;
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 8px;
	}
	.as-header {
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		padding: 8px 12px;
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-weight: 900;
	}
	.as-title { font-weight: 900; }
	.as-meta { font-weight: 700; opacity: 0.9; font-family: 'JetBrains Mono', monospace; }
	.as-timeline {
		padding: 12px;
	}
	.as-step {
		display: grid;
		grid-template-columns: 28px 1fr;
		gap: 10px;
		margin-bottom: 8px;
	}
	.as-step:last-child { margin-bottom: 0; }
	.as-rail {
		display: flex;
		flex-direction: column;
		align-items: center;
	}
	.as-num {
		width: 24px;
		height: 24px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #d8d5cc);
		display: flex;
		align-items: center;
		justify-content: center;
		font-family: 'JetBrains Mono', monospace;
		font-size: 11px;
		font-weight: 900;
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 50%;
		flex-shrink: 0;
	}
	.as-num-running {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.as-line {
		flex: 1;
		width: 1px;
		background: var(--color-border, #d8d5cc);
		min-height: 12px;
		margin-top: 2px;
	}
	.as-content {
		padding-bottom: 6px;
	}
	.as-reasoning {
		font-size: 12px;
		font-weight: 700;
		line-height: 1.45;
		margin-bottom: 8px;
		padding: 6px 8px;
		background: var(--color-surface-highest, #f5f0eb);
		border-left: 3px solid var(--color-accent, #c96342);
		border-radius: 0 4px 4px 0;
	}
	.as-reasoning-dim {
		opacity: 0.6;
		font-style: italic;
		border-left-color: #b8a000;
	}
	.as-tools {
		margin-top: 4px;
	}
	.as-empty {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px;
		font-size: 11px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		opacity: 0.7;
	}
	.as-spinner {
		display: inline-block;
		width: 10px;
		height: 10px;
		border: 2px solid var(--color-border, #d8d5cc);
		border-top-color: var(--color-accent, #c96342);
		border-radius: 50%;
		animation: as-spin 0.8s linear infinite;
	}
	.as-spinner-lg {
		width: 14px;
		height: 14px;
	}
	@keyframes as-spin {
		to { transform: rotate(360deg); }
	}
</style>
