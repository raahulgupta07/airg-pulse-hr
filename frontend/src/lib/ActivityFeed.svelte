<script>
	/**
	 * ActivityFeed — reusable timeline.
	 *
	 * Endpoint pattern: /api/{target_type}s/{id}/activity
	 *   target_type='candidate' -> /api/candidates/{id}/activity
	 *   target_type='position'  -> /api/positions/{id}/activity
	 *   target_type='jd'        -> /api/jds/{id}/activity
	 *
	 * Props:
	 *   targetType: string (required) — 'candidate' | 'position' | 'jd'
	 *   targetId:   string|number (required)
	 *   title?:     string (default "Activity")
	 *
	 * Renders a soft-bordered, white-card timeline. Falls back to an
	 * empty state on 404 or other API failure.
	 */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';

	let { targetType, targetId, title = 'Activity' } = $props();

	let events = $state([]);
	let loading = $state(true);
	let errored = $state(false);

	function endpoint(t, id) {
		// Pluralize target_type — caller passes singular (candidate, position, jd)
		const seg = t.endsWith('s') ? t : `${t}s`;
		return `/${seg}/${id}/activity`;
	}

	async function load() {
		loading = true;
		errored = false;
		try {
			const data = await apiJson(endpoint(targetType, targetId));
			events = Array.isArray(data) ? data : (data.activity || data.events || []);
		} catch (e) {
			events = [];
			errored = true;
		}
		loading = false;
	}

	$effect(() => {
		const _ = targetId;
		const __ = targetType;
		if (targetId && targetType) untrack(() => load());
	});

	function initials(name) {
		if (!name) return '?';
		return String(name).split(/\s+/).map(w => w[0]).join('').toUpperCase().slice(0, 2);
	}

	function timeAgo(d) {
		if (!d) return '';
		try {
			const diff = Date.now() - new Date(d).getTime();
			const m = Math.floor(diff / 60000);
			if (m < 1) return 'Just now';
			if (m < 60) return `${m}m ago`;
			const h = Math.floor(m / 60);
			if (h < 24) return `${h}h ago`;
			const days = Math.floor(h / 24);
			if (days < 30) return `${days}d ago`;
			return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
		} catch { return ''; }
	}

	function sentenceCase(s) {
		if (!s) return '';
		const cleaned = String(s).replace(/_/g, ' ').toLowerCase();
		return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
	}

	function actorOf(ev) {
		return ev.actor || ev.user || ev.user_name || ev.author || 'System';
	}

	function verbOf(ev) {
		const t = ev.type || ev.event_type || ev.action || 'event';
		return sentenceCase(t);
	}

	function detailOf(ev) {
		return ev.details || ev.message || ev.description || ev.summary || '';
	}

	function tsOf(ev) {
		return ev.created_at || ev.timestamp || ev.date || '';
	}
</script>

<section class="afeed">
	<header class="afeed-head">
		<h3>{title}</h3>
		<button class="afeed-refresh" onclick={load} title="Refresh"><RefreshCw size={12} strokeWidth={1.75} /></button>
	</header>

	{#if loading}
		<div class="afeed-skeletons">
			{#each [1, 2, 3] as _}
				<div class="afeed-skel"></div>
			{/each}
		</div>
	{:else if events.length === 0}
		<div class="afeed-empty">
			<span class="material-symbols-outlined" aria-hidden="true">timeline</span>
			<p>No activity yet</p>
		</div>
	{:else}
		<ol class="afeed-list">
			{#each events as ev, i}
				<li class="afeed-item">
					<span class="afeed-dot" aria-hidden="true"></span>
					<div class="afeed-card">
						<div class="afeed-row">
							<span class="afeed-avatar" title={actorOf(ev)}>{initials(actorOf(ev))}</span>
							<span class="afeed-actor">{actorOf(ev)}</span>
							<span class="afeed-verb">{verbOf(ev)}</span>
							<span class="afeed-time">{timeAgo(tsOf(ev))}</span>
						</div>
						{#if detailOf(ev)}
							<p class="afeed-detail">{sentenceCase(detailOf(ev))}</p>
						{/if}
					</div>
				</li>
			{/each}
		</ol>
	{/if}
</section>

<style>
	.afeed {
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface);
	}
	.afeed-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
	}
	.afeed-head h3 {
		font-size: 13px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin: 0;
	}
	.afeed-refresh {
		background: transparent;
		border: 1px solid var(--color-outline-variant, #d6d6c8);
		padding: 2px 8px;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
		color: var(--color-on-surface);
	}
	.afeed-refresh:hover {
		background: var(--color-surface-bright, #fff);
	}

	.afeed-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 36px 12px;
		border: 1px dashed var(--color-outline-variant, #d6d6c8);
		background: #fff;
		color: var(--color-on-surface-dim, #6a6a60);
	}
	.afeed-empty p {
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin: 8px 0 0;
	}

	.afeed-skeletons {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.afeed-skel {
		height: 56px;
		background: linear-gradient(90deg, #f4f4ec, #fafaf2, #f4f4ec);
		background-size: 200% 100%;
		animation: shimmer 1.4s linear infinite;
		border: 1px solid var(--color-outline-variant, #e6e6d8);
	}
	@keyframes shimmer {
		from { background-position: 200% 0; }
		to { background-position: -200% 0; }
	}

	.afeed-list {
		list-style: none;
		padding: 0;
		margin: 0;
		position: relative;
	}
	.afeed-list::before {
		content: '';
		position: absolute;
		left: 7px;
		top: 6px;
		bottom: 6px;
		width: 1px;
		background: var(--color-outline-variant, #d6d6c8);
	}
	.afeed-item {
		position: relative;
		padding-left: 26px;
		margin-bottom: 10px;
	}
	.afeed-dot {
		position: absolute;
		left: 3px;
		top: 14px;
		width: 9px;
		height: 9px;
		background: var(--color-accent, #c96342);
		border: 2px solid #fff;
		border-radius: 50%;
		box-shadow: 0 0 0 1px var(--color-outline-variant, #d6d6c8);
	}
	.afeed-card {
		background: #fff;
		border: 1px solid var(--color-outline-variant, #e6e6d8);
		padding: 10px 12px;
	}
	.afeed-row {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.afeed-avatar {
		width: 22px;
		height: 22px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: var(--color-primary-container, #e0f2e6);
		color: var(--color-on-surface);
		font-weight: 900;
		font-size: 9px;
		flex-shrink: 0;
	}
	.afeed-actor {
		font-size: 12px;
		font-weight: 800;
	}
	.afeed-verb {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-on-surface-dim, #6a6a60);
	}
	.afeed-time {
		margin-left: auto;
		font-size: 10px;
		font-weight: 600;
		color: var(--color-on-surface-dim, #6a6a60);
	}
	.afeed-detail {
		font-size: 12px;
		line-height: 1.5;
		margin: 6px 0 0;
		color: var(--color-on-surface);
	}
</style>
