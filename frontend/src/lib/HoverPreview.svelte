<script module>
	/**
	 * HoverPreview — floating mini-profile card on candidate name hover.
	 *
	 * Usage:
	 *   <span use:hoverPreview={{ id: c.id, name: c.name, score: c.match_score_composite }}>
	 *     {c.name}
	 *   </span>
	 *
	 * Mounts a <HoverPreview /> at the layout level (it self-mounts via its first instance).
	 *
	 * - Triggers after 600ms hover
	 * - Lazy-fetches /api/candidates/{id} once, caches in module-level Map for session
	 * - Fades in 150ms next to cursor, vanishes on mouseleave
	 */
	import { apiJson } from '$lib/api';

	const cache = new Map(); // id -> profile json (or 'pending' or 'error')
	let activeHost = null;   // singleton host
	let dispatch = null;     // bound by component instance

	function ensureHost() {
		if (activeHost || typeof document === 'undefined') return;
		// Lazy-create a div + Svelte mount. We rely on the layout having mounted us.
		// If no instance is mounted yet, we no-op until one appears.
	}

	export function registerHost(api) {
		dispatch = api;
		activeHost = true;
	}

	export function hoverPreview(node, opts = {}) {
		let timer = null;
		let current = opts;

		function onEnter(ev) {
			if (!current?.id) return;
			const x = ev.clientX, y = ev.clientY;
			timer = setTimeout(async () => {
				let payload = cache.get(current.id);
				if (!payload || payload === 'error') {
					cache.set(current.id, 'pending');
					try {
						const data = await apiJson(`/candidates/${current.id}`);
						cache.set(current.id, data);
						payload = data;
					} catch {
						cache.set(current.id, 'error');
						return;
					}
				}
				if (payload === 'pending') return;
				if (dispatch) dispatch({ x, y, profile: payload, hint: current });
			}, 600);
		}
		function onMove(ev) {
			if (dispatch) dispatch({ move: true, x: ev.clientX, y: ev.clientY });
		}
		function onLeave() {
			if (timer) { clearTimeout(timer); timer = null; }
			if (dispatch) dispatch({ hide: true });
		}

		node.addEventListener('mouseenter', onEnter);
		node.addEventListener('mousemove', onMove);
		node.addEventListener('mouseleave', onLeave);

		return {
			update(next) { current = next || {}; },
			destroy() {
				node.removeEventListener('mouseenter', onEnter);
				node.removeEventListener('mousemove', onMove);
				node.removeEventListener('mouseleave', onLeave);
				if (timer) clearTimeout(timer);
			}
		};
	}
</script>

<script>
	import { fade } from 'svelte/transition';
	import { onMount, onDestroy } from 'svelte';

	let visible = $state(false);
	let pos = $state({ x: 0, y: 0 });
	let profile = $state(null);
	let hint = $state(null);

	function onUpdate(detail) {
		if (detail?.hide) { visible = false; return; }
		if (detail?.move) {
			pos = { x: detail.x, y: detail.y };
			return;
		}
		profile = detail.profile;
		hint = detail.hint;
		pos = { x: detail.x, y: detail.y };
		visible = true;
	}

	onMount(() => { registerHost(onUpdate); });
	onDestroy(() => { /* host stays for module life */ });

	function topSkills(p) {
		const s = p?.skills_technical || p?.skills || [];
		return Array.isArray(s) ? s.slice(0, 3) : [];
	}
	function initials(n) {
		if (!n) return '?';
		const parts = String(n).trim().split(/\s+/).filter(Boolean);
		return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?';
	}
</script>

{#if visible && profile}
	<div
		class="hover-preview"
		style="left: {Math.min(pos.x + 16, (typeof window !== 'undefined' ? window.innerWidth : 1000) - 320)}px; top: {Math.min(pos.y + 16, (typeof window !== 'undefined' ? window.innerHeight : 800) - 200)}px;"
		in:fade={{ duration: 150 }}
		out:fade={{ duration: 100 }}
		role="tooltip"
	>
		<div class="hp-row">
			<div class="hp-avatar">{initials(profile.name)}</div>
			<div class="hp-id">
				<div class="hp-name">{profile.name || 'Unknown'}</div>
				<div class="hp-role">{profile.current_role || profile.role || '—'}</div>
			</div>
			{#if hint?.score != null || profile.composite_score != null}
				<div class="hp-score">{Math.round(hint?.score ?? profile.composite_score ?? 0)}%</div>
			{/if}
		</div>
		<div class="hp-meta">
			{#if profile.total_experience_years != null}
				<span>{profile.total_experience_years}y exp</span>
			{/if}
			{#if profile.current_company}
				<span>· {profile.current_company}</span>
			{/if}
		</div>
		{#if topSkills(profile).length}
			<div class="hp-skills">
				{#each topSkills(profile) as s}
					<span class="hp-skill">{s}</span>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<style>
	.hover-preview {
		position: fixed;
		z-index: 10000;
		min-width: 240px;
		max-width: 300px;
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		padding: 12px 14px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.10);
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		font-size: 12.5px;
		color: var(--color-ink, #2c2c2c);
		pointer-events: none;
	}
	.hp-row {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.hp-avatar {
		width: 32px;
		height: 32px;
		border-radius: 999px;
		background: var(--color-accent, #c96342);
		color: #fff;
		display: grid;
		place-items: center;
		font-weight: 700;
		font-size: 11px;
		flex-shrink: 0;
	}
	.hp-id { flex: 1; min-width: 0; }
	.hp-name {
		font-weight: 600;
		font-size: 13px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.hp-role {
		color: var(--color-muted, #6f6e69);
		font-size: 11.5px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.hp-score {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		padding: 3px 9px;
		border-radius: 999px;
		font-weight: 700;
		font-size: 11px;
	}
	.hp-meta {
		margin-top: 6px;
		color: var(--color-muted, #6f6e69);
		font-size: 11.5px;
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.hp-skills {
		margin-top: 8px;
		display: flex;
		gap: 5px;
		flex-wrap: wrap;
	}
	.hp-skill {
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 10.5px;
		color: var(--color-ink-soft, #4a4a48);
	}
</style>
