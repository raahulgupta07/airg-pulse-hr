<script>
	/** Pagination component — brutalist style */
	let { total = 0, limit = 20, offset = 0, onPageChange = () => {} } = $props();

	let currentPage = $derived(Math.floor(offset / limit) + 1);
	let totalPages = $derived(Math.max(1, Math.ceil(total / limit)));
	let showingFrom = $derived(total === 0 ? 0 : offset + 1);
	let showingTo = $derived(Math.min(offset + limit, total));
	let hasPrev = $derived(offset > 0);
	let hasNext = $derived(offset + limit < total);

	function goPrev() {
		if (hasPrev) onPageChange(Math.max(0, offset - limit));
	}

	function goNext() {
		if (hasNext) onPageChange(offset + limit);
	}
</script>

{#if total > 0}
	<div class="pagination-bar">
		<span class="pagination-info">
			Showing {showingFrom}–{showingTo} of {total}
		</span>

		<div class="pagination-controls">
			<button
				class="pagination-btn"
				disabled={!hasPrev}
				onclick={goPrev}
			>
				Previous
			</button>
			<span class="pagination-page">
				Page {currentPage} of {totalPages}
			</span>
			<button
				class="pagination-btn"
				disabled={!hasNext}
				onclick={goNext}
			>
				Next
			</button>
		</div>
	</div>
{/if}

<style>
	.pagination-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 4px;
		margin-top: 16px;
		border-top: 1px solid var(--color-border, #e8e6dd);
		font-family: 'Inter', system-ui, sans-serif;
	}

	.pagination-info {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-on-surface-dim, #6f6e69);
	}

	.pagination-controls {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.pagination-page {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-on-surface, #2c2c2c);
		min-width: 96px;
		text-align: center;
	}

	.pagination-btn {
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px;
		font-family: 'Inter', system-ui, sans-serif;
		font-weight: 500;
		font-size: 12px;
		cursor: pointer;
		padding: 6px 14px;
		transition: background 120ms ease, border-color 120ms ease;
	}

	.pagination-btn:hover:not(:disabled) {
		background: var(--color-surface-warm, #f4f3ee);
		border-color: var(--color-border-strong, #d8d5cb);
	}

	.pagination-btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
</style>
