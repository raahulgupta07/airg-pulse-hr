<script>
	/** WhatsNew — modal shown once per app_version change.
	 *  Tracks acknowledgment in localStorage `pulse_seen_version`.
	 *  Reads version from /api/health (`version` field), fallback "1.1.0".
	 */
	import { onMount } from 'svelte';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import BarChart3 from '@lucide/svelte/icons/bar-chart-3';
	import Bell from '@lucide/svelte/icons/bell';
	import ClipboardList from '@lucide/svelte/icons/clipboard-list';

	let open = $state(false);
	let version = $state('1.1.0');

	const FEATURES = [
		{ icon: Sparkles, text: 'Claude warm theme' },
		{ icon: null, text: '⌘K command palette' },
		{ icon: BarChart3, text: 'New analytics depth: source ROI + predictive time-to-hire' },
		{ icon: Bell, text: 'Unified activity feed' },
		{ icon: ClipboardList, text: 'Per-position interview kit generator' },
	];

	onMount(async () => {
		if (typeof window === 'undefined') return;
		const path = window.location.pathname;
		if (['/login', '/register', '/careers'].some(p => path === p || path.startsWith(p + '/'))) return;

		// Fetch version (graceful)
		try {
			const r = await fetch('/api/health');
			if (r.ok) {
				const d = await r.json();
				if (d?.version) version = String(d.version);
			}
		} catch { /* fallback */ }

		// Compare with seen
		let seen = '';
		try { seen = localStorage.getItem('pulse_seen_version') || ''; } catch {}
		if (seen !== version) {
			// Slight delay so the onboarding tour shows first if both pending
			setTimeout(() => {
				try {
					if (localStorage.getItem('pulse_onboarded') !== '1') return; // wait for tour first run
				} catch {}
				open = true;
			}, 1200);
		}
	});

	function close() {
		open = false;
		try { localStorage.setItem('pulse_seen_version', version); } catch {}
	}

	function onKey(e) {
		if (e.key === 'Escape') close();
	}

	// Display label like "Pulse 1.1"
	let majorMinor = $derived((version || '1.1.0').split('.').slice(0, 2).join('.'));
</script>

<svelte:window onkeydown={onKey} />

{#if open}
	<div class="wn-backdrop" onclick={close} role="presentation">
		<div class="wn-card" role="dialog" aria-modal="true" aria-label="What's new" onclick={(e) => e.stopPropagation()}>
			<button class="wn-close" onclick={close} aria-label="Close">×</button>
			<div class="wn-eyebrow">Release notes</div>
			<h2 class="wn-title">What's new in City Agent Pulse {majorMinor}</h2>
			<ul class="wn-list">
				{#each FEATURES as f}
					<li class="wn-list-item">
						{#if f.icon}<span class="wn-item-icon" aria-hidden="true"><svelte:component this={f.icon} size={16} stroke-width={1.75} /></span>{/if}
						{f.text}
					</li>
				{/each}
			</ul>
			<div class="wn-actions">
				<button class="wn-got-it" onclick={close}>Got it</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.wn-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(20, 18, 14, 0.55);
		display: grid;
		place-items: center;
		z-index: 9998;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		animation: wn-fade 0.2s ease;
	}
	@keyframes wn-fade { from { opacity: 0; } to { opacity: 1; } }
	.wn-card {
		position: relative;
		width: 600px;
		max-width: calc(100vw - 32px);
		background: #ffffff;
		border-radius: 12px;
		box-shadow: 0 24px 64px rgba(0, 0, 0, 0.28);
		padding: 28px 32px 24px;
		color: var(--color-ink, #2c2c2c);
		animation: wn-rise 0.22s ease;
	}
	@keyframes wn-rise {
		from { opacity: 0; transform: translateY(8px) scale(0.98); }
		to   { opacity: 1; transform: translateY(0) scale(1); }
	}
	.wn-close {
		position: absolute;
		top: 10px;
		right: 12px;
		width: 32px;
		height: 32px;
		border: none;
		background: transparent;
		color: var(--color-muted, #6f6e69);
		font-size: 22px;
		line-height: 1;
		border-radius: 8px;
		cursor: pointer;
	}
	.wn-close:hover { background: var(--color-surface-warm, #f4f3ee); color: var(--color-ink, #2c2c2c); }
	.wn-eyebrow {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-accent, #c96342);
		font-weight: 600;
		margin-bottom: 6px;
	}
	.wn-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 28px;
		font-weight: 600;
		letter-spacing: -0.015em;
		margin: 0 0 18px;
		color: var(--color-ink, #2c2c2c);
	}
	.wn-list {
		list-style: none;
		padding: 0;
		margin: 0 0 20px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.wn-list li {
		font-size: 14.5px;
		line-height: 1.55;
		color: var(--color-ink-soft, #4a4a48);
		padding: 10px 12px;
		background: var(--color-surface-warm, #f4f3ee);
		border-radius: 8px;
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.wn-item-icon {
		flex-shrink: 0;
		display: inline-flex;
		color: var(--color-accent, #c96342);
	}
	.wn-actions {
		display: flex;
		justify-content: flex-end;
	}
	.wn-got-it {
		background: var(--color-accent, #c96342);
		color: #fff;
		border: none;
		padding: 10px 22px;
		border-radius: 999px;
		font-family: inherit;
		font-size: 13.5px;
		font-weight: 600;
		cursor: pointer;
		transition: filter 0.15s;
	}
	.wn-got-it:hover { filter: brightness(1.06); }
</style>
