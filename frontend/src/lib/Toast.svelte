<script module>
	/** Global toast notification store + addToast function */
	import { writable } from 'svelte/store';

	/** @typedef {{ id: number, type: string, message: string }} ToastItem */

	let toastId = 0;
	/** @type {import('svelte/store').Writable<ToastItem[]>} */
	export const toasts = writable([]);

	/**
	 * Add a toast notification
	 * @param {string} type
	 * @param {string} message
	 * @param {number} [duration]
	 */
	export function addToast(type, message, duration = 4000) {
		const id = ++toastId;
		toasts.update(t => [...t, { id, type, message }]);
		setTimeout(() => removeToast(id), duration);
	}

	/** @param {number} id */
	export function removeToast(id) {
		toasts.update(t => t.filter(toast => toast.id !== id));
	}
</script>

<script>
	/** @type {Array<{id: number, type: string, message: string}>} */
	let items = $state([]);

	$effect(() => {
		const unsub = toasts.subscribe(v => { items = v; });
		return unsub;
	});

	/** @type {Record<string, string>} */
	const borderColors = {
		success: '#3a8a4f',
		error: 'var(--color-error, #c4571a)',
		warning: 'var(--color-warning, #c98c2a)',
		info: '#006f7c',
	};

	/** @type {Record<string, string>} */
	const icons = {
		success: 'check_circle',
		error: 'error',
		warning: 'warning',
		info: 'info',
	};
</script>

{#if items.length > 0}
	<div class="toast-container">
		{#each items as toast (toast.id)}
			<div
				class="toast-item animate-slide-in"
				style="border-left: 4px solid {borderColors[toast.type] || borderColors.info};"
			>
				<span
					class="material-symbols-outlined"
					style="font-size: 18px; color: {borderColors[toast.type]}; flex-shrink: 0;"
				>{icons[toast.type] || 'info'}</span>
				<span class="toast-message">{toast.message}</span>
				<button class="toast-close" onclick={() => removeToast(toast.id)}>&#10005;</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	.toast-container {
		position: fixed;
		bottom: 48px;
		right: 16px;
		z-index: 200;
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: 380px;
	}

	.toast-item {
		display: flex;
		align-items: center;
		gap: 10px;
		background: var(--color-surface-bright);
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 8px;
		padding: 10px 14px;
		font-family: 'Space Grotesk', sans-serif;
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
		animation: toast-slide-in 0.3s ease-out;
	}

	.toast-message {
		flex: 1;
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-on-surface);
	}

	.toast-close {
		background: none;
		border: none;
		color: var(--color-on-surface-dim);
		font-size: 14px;
		cursor: pointer;
		padding: 0 2px;
		flex-shrink: 0;
		font-family: 'Space Grotesk', sans-serif;
		font-weight: 900;
	}

	.toast-close:hover {
		color: var(--color-on-surface);
	}

	@keyframes toast-slide-in {
		from { transform: translateX(100%); opacity: 0; }
		to { transform: translateX(0); opacity: 1; }
	}
</style>
