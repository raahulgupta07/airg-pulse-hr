<script>
	/**
	 * Presence — stub UI showing teammates "currently viewing" this resource.
	 *
	 * Backend wiring is out of scope. We mock 1-2 fake teammates by pulling the
	 * first 2 entries from /api/auth/users (same source the @mention dropdown uses)
	 * plus a synthetic "+N viewing" tail for visual density.
	 *
	 * Props:
	 *   targetType: 'candidate' | 'position' | 'jd' (cosmetic only)
	 *   targetId:   string | number (cosmetic only)
	 */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';

	let { targetType = 'candidate', targetId = null } = $props();

	let viewers = $state([]);
	let extraCount = $state(3); // mock tail — "+N viewing"
	let loaded = $state(false);

	function initials(name) {
		if (!name) return '?';
		return name.split(/\s+/).map(w => w[0]).join('').toUpperCase().slice(0, 2);
	}

	async function loadViewers() {
		try {
			const data = await apiJson('/auth/users?limit=20');
			const all = data.users || data || [];
			// Mock: first 2 teammates are "currently viewing"
			viewers = all.slice(0, 2).map(u => ({
				id: u.id || u.operator_id,
				name: u.display_name || u.operator_id || 'Teammate',
				role: u.role || ''
			}));
			loaded = true;
		} catch (e) {
			viewers = [];
			loaded = true;
		}
	}

	$effect(() => {
		// Re-run when targetId changes
		const _ = targetId;
		untrack(() => loadViewers());
	});

	let totalCount = $derived(viewers.length + extraCount);
	let tooltip = $derived(
		viewers.map(v => v.name).join(' · ') +
		(extraCount > 0 ? ` and ${extraCount} other${extraCount === 1 ? '' : 's'}` : '')
	);
</script>

{#if loaded && viewers.length > 0}
	<div class="presence-wrap" title={tooltip} aria-label="Currently viewing">
		<div class="presence-stack">
			{#each viewers as v, i}
				<div class="presence-bubble" style="z-index: {10 - i}; margin-left: {i === 0 ? 0 : -8}px;" title={v.name}>
					{initials(v.name)}
					<span class="presence-dot"></span>
				</div>
			{/each}
		</div>
		<span class="presence-label">
			{viewers.map(v => initials(v.name)).join(' · ')}
			{#if extraCount > 0}<span class="presence-extra"> · +{extraCount}</span>{/if}
			<span class="presence-verb"> viewing</span>
		</span>
	</div>
{/if}

<style>
	.presence-wrap {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 4px 8px;
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 6px;
		background: var(--color-surface-bright, #fff);
		font-family: 'Space Grotesk', sans-serif;
	}
	.presence-stack {
		display: inline-flex;
		align-items: center;
	}
	.presence-bubble {
		position: relative;
		width: 26px;
		height: 26px;
		background: var(--color-primary, #007518);
		color: var(--color-on-primary, #fff);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-weight: 900;
		font-size: 10px;
		border: 2px solid var(--color-surface-bright, #fff);
		letter-spacing: 0.02em;
	}
	.presence-dot {
		position: absolute;
		bottom: -2px;
		right: -2px;
		width: 8px;
		height: 8px;
		background: #3a8a4f;
		border: 1.5px solid var(--color-surface-bright, #fff);
		border-radius: 50%;
	}
	.presence-label {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-on-surface);
	}
	.presence-extra {
		color: var(--color-on-surface-dim, #6a6a60);
	}
	.presence-verb {
		color: var(--color-on-surface-dim, #6a6a60);
		font-weight: 500;
	}
</style>
