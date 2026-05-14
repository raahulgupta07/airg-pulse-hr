<script>
	/**
	 * UndoBar — slim coral-soft toast at bottom for undoable actions.
	 *
	 * Trigger anywhere via:
	 *   window.dispatchEvent(new CustomEvent('pulse-undo', {
	 *     detail: { message: "Position 'X' deleted", onUndo: async () => { ... } }
	 *   }));
	 *
	 * Auto-dismisses after 5s. Click "Undo" to invoke onUndo.
	 */
	import { fade, fly } from 'svelte/transition';
	import { onMount, onDestroy } from 'svelte';

	let visible = $state(false);
	let message = $state('');
	let onUndo = $state(null);
	let secondsLeft = $state(5);
	let countdownTimer = null;
	let dismissTimer = null;

	function clearTimers() {
		if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
		if (dismissTimer)  { clearTimeout(dismissTimer); dismissTimer = null; }
	}
	function show(detail) {
		clearTimers();
		message = String(detail?.message || 'Action completed');
		onUndo = typeof detail?.onUndo === 'function' ? detail.onUndo : null;
		secondsLeft = 5;
		visible = true;
		countdownTimer = setInterval(() => {
			secondsLeft = Math.max(0, secondsLeft - 1);
		}, 1000);
		dismissTimer = setTimeout(() => { dismiss(); }, 5000);
	}
	function dismiss() {
		clearTimers();
		visible = false;
		onUndo = null;
	}
	async function clickUndo() {
		const cb = onUndo;
		dismiss();
		if (cb) {
			try { await cb(); } catch (e) { console.error('[UndoBar] undo callback failed', e); }
		}
	}

	function onEvent(e) { show(e.detail || {}); }

	onMount(() => {
		if (typeof window === 'undefined') return;
		window.addEventListener('pulse-undo', onEvent);
	});
	onDestroy(() => {
		clearTimers();
		if (typeof window !== 'undefined') window.removeEventListener('pulse-undo', onEvent);
	});
</script>

{#if visible}
	<div
		class="undo-bar"
		role="status"
		aria-live="polite"
		in:fly={{ y: 30, duration: 180 }}
		out:fade={{ duration: 120 }}
	>
		<span class="undo-msg">{message}</span>
		<span class="undo-sep">·</span>
		<button type="button" class="undo-btn" aria-label="Undo last action" onclick={clickUndo}>Undo</button>
		<span class="undo-count" aria-hidden="true">{secondsLeft}s</span>
		<button type="button" class="undo-x" aria-label="Dismiss" onclick={dismiss}>×</button>
	</div>
{/if}

<style>
	.undo-bar {
		position: fixed;
		left: 50%;
		bottom: 48px;
		transform: translateX(-50%);
		z-index: 9999;
		display: inline-flex;
		align-items: center;
		gap: 10px;
		padding: 9px 14px 9px 16px;
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		border: 1px solid var(--color-accent, #c96342);
		border-radius: 999px;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		font-size: 13px;
		font-weight: 500;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.10);
		max-width: 92vw;
	}
	.undo-msg {
		max-width: 380px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.undo-sep { opacity: 0.45; }
	.undo-btn {
		background: transparent;
		border: none;
		color: var(--color-accent-ink, #b04f30);
		font-weight: 700;
		font-size: 13px;
		text-decoration: underline;
		cursor: pointer;
		padding: 2px 4px;
		font-family: inherit;
	}
	.undo-btn:hover { color: var(--color-accent, #c96342); }
	.undo-count {
		font-size: 11px;
		opacity: 0.7;
		font-variant-numeric: tabular-nums;
	}
	.undo-x {
		background: transparent;
		border: none;
		color: inherit;
		font-size: 16px;
		line-height: 1;
		padding: 0 2px 0 4px;
		cursor: pointer;
		opacity: 0.55;
	}
	.undo-x:hover { opacity: 1; }
</style>
