<script>
	let open = $state(false);

	const SHORTCUTS = [
		{ keys: ['⌘', 'K'], desc: 'Open command palette' },
		{ keys: ['↑'], desc: 'Navigate rows up' },
		{ keys: ['↓'], desc: 'Navigate rows down' },
		{ keys: ['J'], desc: 'Next row (in table)' },
		{ keys: ['K'], desc: 'Previous row (in table)' },
		{ keys: ['Enter'], desc: 'Open selected' },
		{ keys: ['X'], desc: 'Dismiss / reject' },
		{ keys: ['/'], desc: 'Focus search' },
		{ keys: ['Esc'], desc: 'Close modal or drawer' },
		{ keys: ['?'], desc: 'Show this help' },
	];

	function isTypingTarget(el) {
		if (!el) return false;
		const tag = el.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
	}

	function onGlobalKey(e) {
		if (open && e.key === 'Escape') {
			e.preventDefault();
			open = false;
			return;
		}
		if (e.key === '?' && !isTypingTarget(e.target)) {
			// Some keyboards: '?' may require shift; e.key === '?' is correct shift+/
			e.preventDefault();
			open = !open;
		}
	}

	$effect(() => {
		if (typeof window === 'undefined') return;
		window.addEventListener('keydown', onGlobalKey);
		return () => window.removeEventListener('keydown', onGlobalKey);
	});

	function close() { open = false; }
</script>

{#if open}
	<div class="kh-overlay" onclick={close} role="presentation">
		<div class="kh-card" role="dialog" aria-label="Keyboard shortcuts" onclick={(e) => e.stopPropagation()}>
			<div class="kh-header">
				<h2 class="kh-title">Keyboard shortcuts</h2>
				<button class="kh-close" onclick={close} aria-label="Close">×</button>
			</div>
			<ul class="kh-list">
				{#each SHORTCUTS as s}
					<li class="kh-row">
						<span class="kh-keys">
							{#each s.keys as k}
								<kbd class="kh-kbd">{k}</kbd>
							{/each}
						</span>
						<span class="kh-desc">{s.desc}</span>
					</li>
				{/each}
			</ul>
			<div class="kh-foot">Press <kbd class="kh-kbd">Esc</kbd> to close</div>
		</div>
	</div>
{/if}

<style>
	.kh-overlay {
		position: fixed; inset: 0;
		background: rgba(44, 44, 44, 0.32);
		z-index: 9998;
		display: flex;
		justify-content: center;
		align-items: center;
		backdrop-filter: blur(2px);
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}
	.kh-card {
		width: 460px;
		max-width: calc(100vw - 32px);
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius, 12px);
		box-shadow: var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.12));
		overflow: hidden;
	}
	.kh-header {
		display: flex; align-items: center; justify-content: space-between;
		padding: 14px 18px;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.kh-title {
		margin: 0;
		font-size: 15px;
		font-weight: 600;
		color: var(--color-ink, #2c2c2c);
		font-family: inherit;
		letter-spacing: -0.01em;
	}
	.kh-close {
		background: transparent;
		border: none;
		font-size: 22px;
		line-height: 1;
		color: var(--color-muted, #6f6e69);
		cursor: pointer;
		padding: 0 4px;
	}
	.kh-close:hover { color: var(--color-ink, #2c2c2c); }
	.kh-list {
		list-style: none;
		margin: 0;
		padding: 8px 0;
	}
	.kh-row {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 8px 18px;
		font-size: 13px;
	}
	.kh-row:hover { background: var(--color-surface-warm, #f4f3ee); }
	.kh-keys {
		display: inline-flex;
		gap: 4px;
		min-width: 80px;
		flex-shrink: 0;
	}
	.kh-kbd {
		display: inline-block;
		padding: 2px 7px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 4px;
		font-family: ui-monospace, SFMono-Regular, monospace;
		font-size: 11px;
		color: var(--color-ink, #2c2c2c);
		min-width: 18px;
		text-align: center;
	}
	.kh-desc {
		color: var(--color-ink-soft, #4a4a48);
	}
	.kh-foot {
		padding: 10px 18px;
		font-size: 11px;
		color: var(--color-muted, #6f6e69);
		border-top: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface-warm, #f4f3ee);
	}
</style>
