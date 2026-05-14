<script>
	let { activeFilter = $bindable('all'), counts = null, visibleCount = 0, totalCount = 0 } = $props();
</script>

<div class="ai-filter-row">
	<span class="ai-filter-label">Filter:</span>
	<button class="ai-filter-chip" class:active={activeFilter === 'all'} onclick={() => activeFilter = 'all'}>
		All{counts?.all != null ? ` (${counts.all})` : ''}
	</button>
	<button class="ai-filter-chip" class:active={activeFilter === 'top10'} onclick={() => activeFilter = 'top10'}>
		Top 10{counts?.top10 != null ? ` (${counts.top10})` : ''}
	</button>
	<button class="ai-filter-chip" class:active={activeFilter === 'above80'} onclick={() => activeFilter = 'above80'}>
		Above 80%{counts?.above80 != null ? ` (${counts.above80})` : ''}
	</button>
	<button class="ai-filter-chip" class:active={activeFilter === 'newweek'} onclick={() => activeFilter = 'newweek'}>
		New this week{counts?.newThisWeek != null ? ` (${counts.newThisWeek})` : ''}
	</button>
	<span class="ai-filter-count">{visibleCount} / {totalCount}</span>
</div>

<style>
	.ai-filter-row {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		padding: 6px 0;
		font-family: 'Space Grotesk', sans-serif;
	}
	.ai-filter-label {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-right: 4px;
	}
	.ai-filter-chip {
		font-family: inherit;
		font-size: 12px;
		font-weight: 500;
		padding: 5px 12px;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 20px;
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.ai-filter-chip:hover {
		background: var(--color-bg, #faf9f5);
		border-color: var(--color-accent, #c96342);
	}
	.ai-filter-chip.active {
		background: rgba(201,99,66,0.10);
		border-color: var(--color-accent, #c96342);
		color: var(--color-accent, #c96342);
		font-weight: 600;
	}
	.ai-filter-count {
		margin-left: auto;
		font-size: 11px;
		font-weight: 500;
		color: var(--color-on-surface-dim, #6f6e69);
	}
</style>
