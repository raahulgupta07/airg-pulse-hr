<script>
	let { selectedCount = 0, onAddAll = () => {}, onClear = () => {}, children } = $props();
</script>

{#if selectedCount > 0}
	<div class="ai-bulk-bar">
		<span class="ai-bulk-count">{selectedCount} selected</span>
		<button class="ai-bulk-btn ai-bulk-add" onclick={onAddAll}>Add all to shortlist</button>
		<button class="ai-bulk-btn ai-bulk-clear" onclick={onClear}>Clear</button>
		{#if children}{@render children()}{/if}
	</div>
{/if}

<style>
	.ai-bulk-bar {
		position: fixed;
		bottom: 16px;
		left: 16px;
		display: flex;
		gap: 8px;
		align-items: center;
		padding: 10px 16px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		box-shadow: 0 4px 20px rgba(0,0,0,0.12);
		z-index: 50;
		font-family: 'Space Grotesk', sans-serif;
		flex-wrap: wrap;
		max-width: calc(100vw - 32px);
	}
	.ai-bulk-count {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-on-surface, #2c2c2c);
	}
	.ai-bulk-btn {
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		padding: 6px 14px;
		border-radius: 6px;
		border: 1px solid var(--color-border, #e8e6dd);
		background: transparent;
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
	}
	.ai-bulk-btn:hover {
		background: var(--color-bg, #faf9f5);
	}

	/* Add all — solid coral */
	.ai-bulk-add {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.ai-bulk-add:hover {
		background: #b35538;
		border-color: #b35538;
	}

	/* Clear — muted ghost */
	.ai-bulk-clear {
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.ai-bulk-clear:hover {
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface, #2c2c2c);
	}
</style>
