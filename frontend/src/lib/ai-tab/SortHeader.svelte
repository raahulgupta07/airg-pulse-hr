<script>
	let {
		sortBy = $bindable('score'),
		sortDir = $bindable('desc'),
		allVisibleSelected = false,
		onToggleSelectAll = () => {}
	} = $props();

	function setSort(col) {
		if (sortBy === col) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortBy = col;
			sortDir = col === 'score' ? 'desc' : 'asc';
		}
	}

	function arrow(col) {
		if (sortBy !== col) return '';
		return sortDir === 'desc' ? ' ▼' : ' ▲';
	}
</script>

<div class="ai-sort-row">
	<label class="ai-selectall">
		<input type="checkbox" checked={allVisibleSelected} onchange={onToggleSelectAll} />
		<span>Sel</span>
	</label>
	<button class="ai-sort-btn" class:active={sortBy === 'score'} onclick={() => setSort('score')}>Score{arrow('score')}</button>
	<button class="ai-sort-btn" class:active={sortBy === 'yrs'} onclick={() => setSort('yrs')}>Yrs exp{arrow('yrs')}</button>
	<button class="ai-sort-btn ai-sort-loc" class:active={sortBy === 'location'} onclick={() => setSort('location')}>Location{arrow('location')}</button>
	<button class="ai-sort-btn ai-sort-added" class:active={sortBy === 'added'} onclick={() => setSort('added')}>Added{arrow('added')}</button>
</div>

<style>
	.ai-sort-row {
		display: flex;
		gap: 0;
		background: var(--color-bg, #faf9f5);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		padding: 0;
		align-items: stretch;
		font-family: 'Space Grotesk', sans-serif;
	}
	.ai-selectall {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--color-on-surface-dim, #6f6e69);
		border-right: 1px solid var(--color-border, #e8e6dd);
		cursor: pointer;
	}
	.ai-selectall input {
		width: 14px;
		height: 14px;
		cursor: pointer;
		accent-color: var(--color-accent, #c96342);
	}
	.ai-sort-btn {
		flex: 1;
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		padding: 8px 10px;
		border: none;
		border-right: 1px solid var(--color-border, #e8e6dd);
		background: transparent;
		color: var(--color-on-surface-dim, #6f6e69);
		cursor: pointer;
		text-align: left;
		transition: background 120ms ease, color 120ms ease;
	}
	.ai-sort-btn:last-child { border-right: none; }
	.ai-sort-btn:hover {
		background: rgba(201,99,66,0.06);
		color: var(--color-on-surface, #2c2c2c);
	}
	.ai-sort-btn.active {
		background: rgba(201,99,66,0.10);
		color: var(--color-accent, #c96342);
		font-weight: 700;
	}
	@media (max-width: 600px) {
		.ai-sort-loc, .ai-sort-added { display: none; }
	}
</style>
