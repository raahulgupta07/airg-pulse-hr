<script>
	let { left, right, defaultPercent = 45, storageKey = 'hire_split_percent' } = $props();
	let pct = $state(defaultPercent);

	if (typeof window !== 'undefined') {
		const stored = parseFloat(localStorage.getItem(storageKey) || '');
		if (!isNaN(stored) && stored > 15 && stored < 85) pct = stored;
	}

	let dragging = $state(false);
	let containerEl = $state(null);

	function onMouseDown(e) {
		dragging = true;
		e.preventDefault();
		window.addEventListener('mousemove', onMouseMove);
		window.addEventListener('mouseup', onMouseUp);
	}
	function onMouseMove(e) {
		if (!dragging || !containerEl) return;
		const r = containerEl.getBoundingClientRect();
		const newPct = ((e.clientX - r.left) / r.width) * 100;
		pct = Math.max(20, Math.min(80, newPct));
	}
	function onMouseUp() {
		dragging = false;
		window.removeEventListener('mousemove', onMouseMove);
		window.removeEventListener('mouseup', onMouseUp);
		try { localStorage.setItem(storageKey, String(pct)); } catch {}
	}

	let isMobile = $state(false);
	$effect(() => {
		if (typeof window === 'undefined') return;
		const mq = window.matchMedia('(max-width: 900px)');
		isMobile = mq.matches;
		const h = (e) => (isMobile = e.matches);
		mq.addEventListener('change', h);
		return () => mq.removeEventListener('change', h);
	});

	let docCollapsed = $state(false); // mobile only
</script>

{#if isMobile}
	<div class="sp-mobile">
		<button class="sp-toggle" onclick={() => (docCollapsed = !docCollapsed)}>
			{docCollapsed ? 'Show source document' : 'Hide source document'}
		</button>
		{#if !docCollapsed}<div class="sp-mobile-doc">{@render left()}</div>{/if}
		<div class="sp-mobile-data">{@render right()}</div>
	</div>
{:else}
	<div class="sp-wrap" bind:this={containerEl}>
		<div class="sp-left" style:flex-basis="{pct}%">{@render left()}</div>
		<div class="sp-divider" class:dragging onmousedown={onMouseDown} role="separator" aria-orientation="vertical">
			<span class="sp-grip">|</span>
		</div>
		<div class="sp-right" style:flex-basis="{100 - pct}%">{@render right()}</div>
	</div>
{/if}

<style>
	.sp-wrap { display: flex; align-items: stretch; min-height: 70vh; flex: 1; width: 100%; }
	.sp-left, .sp-right { min-width: 240px; overflow: auto; }
	.sp-divider {
		width: 8px; cursor: col-resize; background: var(--color-on-surface);
		display: flex; align-items: center; justify-content: center;
		user-select: none;
		flex-shrink: 0;
	}
	.sp-divider:hover, .sp-divider.dragging { background: var(--color-primary-container); }
	.sp-grip { color: var(--color-surface); font-weight: 900; font-size: 14px; }
	.sp-mobile { display: flex; flex-direction: column; gap: 8px; padding: 8px; }
	.sp-toggle {
		background: var(--color-on-surface); color: var(--color-surface);
		border: 2px solid var(--color-on-surface); padding: 6px 12px;
		font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;
		font-family: 'Space Grotesk';
		letter-spacing: 0.06em;
	}
	.sp-mobile-doc { max-height: 60vh; overflow: auto; border: 2px solid var(--color-on-surface); }
</style>
