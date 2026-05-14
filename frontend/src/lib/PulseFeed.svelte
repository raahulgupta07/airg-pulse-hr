<script>
	import { onMount, onDestroy, untrack } from 'svelte';
	import { apiJson, getToken } from '$lib/api.ts';
	import Bell from '@lucide/svelte/icons/bell';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Bot from '@lucide/svelte/icons/bot';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import FileText from '@lucide/svelte/icons/file-text';
	import CheckCircle2 from '@lucide/svelte/icons/check-circle-2';
	import XCircle from '@lucide/svelte/icons/x-circle';

	let events = $state([]);
	let unreadCount = $state(0);
	let byType = $state({ notification: 0, jd_agent: 0, ai_scan: 0, ai_match: 0 });
	let open = $state(false);
	let activeTab = $state('all');
	let loading = $state(false);

	let es = null;
	let reconnectHandle = null;
	let containerEl;

	const TABS = [
		{ key: 'all',          label: 'All',     icon: null },
		{ key: 'pipeline',     label: 'Pipe',    icon: Hourglass },
		{ key: 'nudges',       label: 'Nudges',  icon: Sparkles },
		{ key: 'notification', label: 'Notif',   icon: Bell },
		{ key: 'jd_agent',     label: 'JD',      icon: Bot },
		{ key: 'ai',           label: 'AI',      icon: Sparkles }
	];

	// ── Nudges (merged from former AINudges floating panel) ──
	let nudges = $state([]);
	let nudgesLoading = $state(false);
	let nudgesDismissed = $state(new Set());
	let nudgesLastBuilt = 0;
	const NUDGES_TTL_MS = 5 * 60 * 1000;
	const NUDGES_PUBLIC_PREFIXES = ['/login', '/register', '/careers'];

	function nudgesIsPublic() {
		if (typeof window === 'undefined') return true;
		const p = window.location.pathname;
		return NUDGES_PUBLIC_PREFIXES.some(x => p === x || p.startsWith(x + '/'));
	}

	function loadDismissedNudges() {
		try {
			const raw = localStorage.getItem('pulse_dismissed_nudges');
			if (raw) nudgesDismissed = new Set(JSON.parse(raw));
		} catch {}
	}
	function persistDismissedNudges() {
		try {
			localStorage.setItem('pulse_dismissed_nudges', JSON.stringify([...nudgesDismissed]));
		} catch {}
	}

	async function buildNudges(force = false) {
		if (nudgesIsPublic()) return;
		if (!force && nudgesLastBuilt && (Date.now() - nudgesLastBuilt) < NUDGES_TTL_MS) return;
		nudgesLoading = true;
		const out = [];
		try {
			const posRes = await apiJson('/positions').catch(() => ({ positions: [] }));
			const positions = posRes.positions || [];
			const now = Date.now();

			// Nudge 1: stale JD (no view in 7+ days)
			try {
				const stale = positions.find(p => {
					const last = p.last_viewed_at || p.updated_at || p.created_at;
					if (!last) return false;
					const age = (now - new Date(last).getTime()) / 86400000;
					return age >= 7 && (p.status === 'active' || p.status === 'draft');
				});
				if (stale) {
					out.push({
						id: `stale_jd_${stale.slug || stale.id}`,
						icon: FileText,
						text: `JD for ${stale.title} hasn't been viewed in 7 days — archive?`,
						actionLabel: 'Open',
						href: `/positions/${stale.slug}`,
					});
				}
			} catch {}

			// Nudge 2: candidates stuck in screening 5+ days
			try {
				const candRes = await apiJson('/candidates?stage=screened&limit=50').catch(() => ({ candidates: [] }));
				const cands = candRes.candidates || candRes.items || [];
				const stuck = cands.filter(c => {
					const last = c.stage_updated_at || c.updated_at;
					if (!last) return false;
					return (now - new Date(last).getTime()) / 86400000 >= 5;
				});
				if (stuck.length >= 1) {
					out.push({
						id: `stuck_screening_${stuck.length}`,
						icon: Hourglass,
						text: `${stuck.length} CV${stuck.length === 1 ? '' : 's'} in screening for 5+ days — chase or reject?`,
						actionLabel: 'Open',
						href: stuck[0].position_slug ? `/positions/${stuck[0].position_slug}` : '/candidates',
					});
				}
			} catch {}

			// Nudge 3: top AI match per active position
			try {
				const top = positions.find(p => (p.status === 'active') && p.has_jd !== false);
				if (top) {
					const ai = await apiJson(`/positions/${top.slug}/ai`).catch(() => null);
					const matches = ai?.matches || [];
					const best = matches.find(m => (m.match_score_composite ?? 0) >= 65);
					if (best) {
						out.push({
							id: `top_match_${top.slug}_${best.candidate_id || best.id}`,
							icon: Sparkles,
							text: `${best.name || 'Candidate'} scored ${Math.round(best.match_score_composite)}% for ${top.title} — schedule call?`,
							actionLabel: 'Schedule',
							href: `/positions/${top.slug}`,
						});
					}
				}
			} catch {}
		} catch {}
		nudges = out.filter(n => !nudgesDismissed.has(n.id));
		nudgesLastBuilt = Date.now();
		nudgesLoading = false;
	}

	function dismissNudge(id) {
		nudgesDismissed.add(id);
		nudgesDismissed = new Set(nudgesDismissed);
		persistDismissedNudges();
		nudges = nudges.filter(n => n.id !== id);
	}

	function actNudge(n) {
		if (n.href) {
			open = false;
			window.location.href = n.href;
		}
	}

	let pipeStats = $state({ running: 0, queued: 0, queue_depth: 0 });
	let pipeRows = $state([]);
	let pipePollHandle = null;

	async function loadPipeline() {
		try {
			const [qs, pend] = await Promise.all([
				apiJson('/candidates/queue-status').catch(() => ({})),
				apiJson('/candidates/pending?include_recent=true&limit=20').catch(() => ({}))
			]);
			pipeStats = {
				running: qs.running || 0,
				queued: qs.queued || 0,
				queue_depth: qs.queue_depth || 0
			};
			pipeRows = (pend.candidates || pend.pending || []).slice(0, 20);
		} catch { /* ignore */ }
	}

	function openCli(row) {
		window.dispatchEvent(new CustomEvent('hire-cli-open', { detail: { candidateId: row.id, runId: row.run_id || null } }));
		open = false;
	}

	function iconForType(type) {
		const map = {
			notification: Bell,
			jd_agent: Bot,
			ai_scan: Sparkles,
			ai_match: Sparkles
		};
		return map[type] || null;
	}

	function relativeTime(ts) {
		if (!ts) return '';
		const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
		if (diff < 60) return 'just now';
		if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
		if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
		return `${Math.floor(diff / 86400)}d ago`;
	}

	let filteredEvents = $derived.by(() => {
		if (activeTab === 'all') return events;
		if (activeTab === 'ai') return events.filter((e) => e.type === 'ai_scan' || e.type === 'ai_match');
		return events.filter((e) => e.type === activeTab);
	});

	let tabCounts = $derived({
		all: events.length,
		pipeline: pipeStats.running + pipeStats.queued,
		nudges: nudges.length,
		notification: byType.notification || 0,
		jd_agent: byType.jd_agent || 0,
		ai: (byType.ai_scan || 0) + (byType.ai_match || 0)
	});

	async function loadFeed() {
		loading = true;
		try {
			const data = await apiJson('/feed?limit=50');
			events = (data?.events || []).slice(0, 100);
			unreadCount = data?.unread_count || 0;
			byType = data?.by_type || { notification: 0, jd_agent: 0, ai_scan: 0, ai_match: 0 };
		} catch {
			/* non-critical */
		} finally {
			loading = false;
		}
	}

	function pushEvent(ev) {
		if (!ev || !ev.id) return;
		// dedup by id
		if (events.find((e) => e.id === ev.id)) return;
		events = [ev, ...events].slice(0, 100);
		if (!ev.read) {
			unreadCount += 1;
			if (ev.type === 'notification') byType = { ...byType, notification: (byType.notification || 0) + 1 };
			else if (ev.type === 'jd_agent') byType = { ...byType, jd_agent: (byType.jd_agent || 0) + 1 };
			else if (ev.type === 'ai_scan') byType = { ...byType, ai_scan: (byType.ai_scan || 0) + 1 };
			else if (ev.type === 'ai_match') byType = { ...byType, ai_match: (byType.ai_match || 0) + 1 };
		}
	}

	function connectSSE() {
		try {
			const tok = getToken();
			if (!tok) return;
			es = new EventSource(`/api/feed/events?token=${encodeURIComponent(tok)}`);
			es.addEventListener('feed', (e) => {
				try {
					const data = JSON.parse(e.data);
					pushEvent(data);
				} catch { /* ignore parse errors */ }
			});
			es.onerror = () => {
				try { es && es.close(); } catch {}
				es = null;
				if (reconnectHandle) clearTimeout(reconnectHandle);
				reconnectHandle = setTimeout(connectSSE, 5000);
			};
		} catch {
			if (reconnectHandle) clearTimeout(reconnectHandle);
			reconnectHandle = setTimeout(connectSSE, 5000);
		}
	}

	async function markAllRead() {
		try {
			await apiJson('/feed/mark-all-read', { method: 'POST' });
			events = events.map((e) => ({ ...e, read: true }));
			unreadCount = 0;
			byType = { notification: 0, jd_agent: 0, ai_scan: 0, ai_match: 0 };
		} catch { /* ignore */ }
	}

	async function rowClick(ev) {
		if (!ev.read) {
			try {
				await apiJson('/feed/mark-read', { method: 'POST', body: JSON.stringify({ ids: [ev.id] }) });
				ev.read = true;
				events = [...events];
				unreadCount = Math.max(0, unreadCount - 1);
			} catch { /* ignore */ }
		}
		if (ev.action_url) {
			open = false;
			window.location.href = ev.action_url;
		}
	}

	function toggle() {
		open = !open;
		if (open) {
			loadFeed();
			loadPipeline();
			buildNudges();
			if (!pipePollHandle) pipePollHandle = setInterval(loadPipeline, 2000);
		} else {
			if (pipePollHandle) { clearInterval(pipePollHandle); pipePollHandle = null; }
		}
	}

	// React to nudges tab activation — refresh if cache stale
	$effect(() => {
		const t = activeTab;
		const o = open;
		if (t === 'nudges' && o) {
			untrack(() => buildNudges());
		}
	});

	function onFeedRefresh() {
		loadFeed();
		loadPipeline();
	}

	function onDocClick(e) {
		if (!open) return;
		if (containerEl && !containerEl.contains(e.target)) open = false;
	}
	function onKey(e) {
		if (e.key === 'Escape' && open) open = false;
	}

	onMount(() => {
		loadFeed();
		connectSSE();
		loadDismissedNudges();
		buildNudges();
		document.addEventListener('click', onDocClick);
		document.addEventListener('keydown', onKey);
		window.addEventListener('pulse-feed-refresh', onFeedRefresh);
	});
	onDestroy(() => {
		try { es && es.close(); } catch {}
		if (reconnectHandle) clearTimeout(reconnectHandle);
		if (pipePollHandle) clearInterval(pipePollHandle);
		if (typeof document !== 'undefined') {
			document.removeEventListener('click', onDocClick);
			document.removeEventListener('keydown', onKey);
		}
		if (typeof window !== 'undefined') window.removeEventListener('pulse-feed-refresh', onFeedRefresh);
	});
</script>

<div class="pulse-feed-area" bind:this={containerEl}>
	<button class="pulse-trigger" onclick={toggle} aria-label="Pulse Feed">
		{#if unreadCount > 0}
			<span class="pf-dot"></span>
		{/if}
		<span class="pf-bell"><Bell size={13} strokeWidth={1.75} /></span>
		<span class="pf-label">Feed</span>
		<span class="pf-count">· {unreadCount}</span>
	</button>

	{#if open}
		<div class="pf-panel" role="dialog">
			<div class="pf-tabs">
				{#each TABS as t}
					<button
						class="pf-tab"
						class:pf-tab-active={activeTab === t.key}
						onclick={() => (activeTab = t.key)}
					>
						{#if t.icon}<span class="pf-tab-icon"><svelte:component this={t.icon} size={12} strokeWidth={1.75} /></span>{/if}
						<span>{t.label}</span>
						{#if (tabCounts[t.key] ?? 0) > 0}
							<span class="pf-tab-count">{tabCounts[t.key]}</span>
						{/if}
					</button>
				{/each}
			</div>

			<div class="pf-body">
				{#if activeTab === 'pipeline'}
					<div class="pf-pipe-stats">
						<span>{pipeStats.running} running · {pipeStats.queued} queued · depth {pipeStats.queue_depth}</span>
						<button class="pf-pipe-cli" onclick={() => { window.dispatchEvent(new CustomEvent('hire-cli-open', { detail: {} })); open = false; }}>
							Open terminal →
						</button>
					</div>
					{#if pipeRows.length === 0}
						<div class="pf-empty">No active pipeline runs</div>
					{:else}
						{#each pipeRows as r (r.id)}
							<button class="pf-row" onclick={() => openCli(r)}>
								<span class="pf-row-icon">
							{#if r.is_processed}
								<svelte:component this={CheckCircle2} size={14} strokeWidth={1.75} />
							{:else if r.processing_error}
								<svelte:component this={XCircle} size={14} strokeWidth={1.75} />
							{:else}
								<svelte:component this={Hourglass} size={14} strokeWidth={1.75} />
							{/if}
						</span>
								<span class="pf-row-main">
									<span class="pf-row-title">cv_{String(r.id).padStart(3, '0')} · {(r.file_name || r.name || 'unknown').slice(0, 40)}</span>
									<span class="pf-row-sub">
										{#if r.processing_error}error · {r.processing_error.slice(0, 40)}
										{:else if r.is_processed}done · {r.quality_score ?? '-'} qual
										{:else}{r.last_step || 'queued'} · {r.last_status || ''}{/if}
									</span>
								</span>
								<span class="pf-row-ts">Open →</span>
							</button>
						{/each}
					{/if}
				{:else if activeTab === 'nudges'}
					{#if nudgesLoading && nudges.length === 0}
						<div class="pf-empty">Analyzing your pipeline…</div>
					{:else if nudges.length === 0}
						<div class="pf-empty">No nudges right now — all caught up</div>
					{:else}
						{#each nudges as n (n.id)}
							<div class="pf-row pf-nudge-row">
								<span class="pf-row-icon pf-nudge-icon">{#if n.icon}<svelte:component this={n.icon} size={14} strokeWidth={1.75} />{/if}</span>
								<span class="pf-row-main">
									<span class="pf-row-title">{n.text}</span>
								</span>
								<span class="pf-nudge-actions">
									<button class="pf-nudge-act" onclick={() => actNudge(n)}>{n.actionLabel}</button>
									<button class="pf-nudge-dismiss" onclick={() => dismissNudge(n.id)} aria-label="Dismiss">×</button>
								</span>
							</div>
						{/each}
					{/if}
				{:else if loading}
					<div class="pf-empty">Loading…</div>
				{:else if filteredEvents.length === 0}
					<div class="pf-empty">No events</div>
				{:else}
					{#each filteredEvents as ev (ev.id)}
						<button
							class="pf-row"
							class:pf-unread={!ev.read}
							onclick={() => rowClick(ev)}
						>
							<span class="pf-row-icon">{#if iconForType(ev.type)}<svelte:component this={iconForType(ev.type)} size={14} strokeWidth={1.75} />{:else}•{/if}</span>
							<span class="pf-row-main">
								<span class="pf-row-title">{ev.title}</span>
								{#if ev.subtitle}
									<span class="pf-row-sub">{ev.subtitle}</span>
								{/if}
							</span>
							<span class="pf-row-ts">{relativeTime(ev.ts)}</span>
						</button>
					{/each}
				{/if}
			</div>

			<div class="pf-footer">
				<button class="pf-foot-btn" onclick={markAllRead}>Mark all read</button>
				<button class="pf-foot-btn pf-foot-link" onclick={() => loadFeed()}><RefreshCw size={12} strokeWidth={1.75} /> Refresh</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.pulse-feed-area {
		position: relative;
		font-family: var(--font-sans, 'Inter', -apple-system, system-ui, sans-serif);
	}
	.pulse-trigger {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 7px;
		padding: 7px 13px;
		background: var(--color-surface, #ffffff);
		color: var(--color-ink, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-pill, 999px);
		box-shadow: none;
		cursor: pointer;
		font-weight: 500;
		font-size: 12.5px;
		letter-spacing: 0;
		font-family: inherit;
		transition: background .15s, border-color .15s;
	}
	.pulse-trigger:hover { background: var(--color-bg-alt, #f0eee5); }
	.pf-bell { font-size: 13px; }
	.pf-label { font-weight: 500; color: var(--color-ink, #2c2c2c); }
	.pf-count { color: var(--color-muted, #6f6e69); }
	.pf-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--color-accent, #c96342);
		box-shadow: 0 0 0 3px var(--color-accent-soft, #fdebe1);
		flex-shrink: 0;
	}

	.pf-panel {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		width: 380px;
		min-width: 360px;
		max-height: 600px;
		background: var(--color-surface, #ffffff);
		color: var(--color-ink, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius, 12px);
		box-shadow: var(--shadow-md, 0 4px 12px rgba(0,0,0,0.08));
		z-index: 200;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.pf-tabs {
		display: flex;
		gap: 2px;
		padding: 5px;
		background: #f4f3ee;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		overflow-x: auto;
		scrollbar-width: thin;
		scrollbar-color: transparent transparent;
		flex-shrink: 0;
	}
	.pf-tabs:hover {
		scrollbar-color: var(--color-accent, #c96342) transparent;
	}
	.pf-tabs::-webkit-scrollbar {
		height: 4px;
	}
	.pf-tabs::-webkit-scrollbar-track {
		background: transparent;
	}
	.pf-tabs::-webkit-scrollbar-thumb {
		background: transparent;
		border-radius: 2px;
	}
	.pf-tabs:hover::-webkit-scrollbar-thumb {
		background: var(--color-accent, #c96342);
		opacity: 0.5;
	}
	.pf-tab {
		flex: 0 0 auto;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 3px;
		padding: 6px 10px;
		background: transparent;
		color: var(--color-muted, #6f6e69);
		border: none;
		border-radius: var(--radius-pill, 999px);
		font-family: inherit;
		font-weight: 500;
		font-size: 11.5px;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
		white-space: nowrap;
		transition: background .15s, color .15s;
	}
	.pf-tab:hover { color: var(--color-ink, #2c2c2c); }
	.pf-tab-active {
		background: var(--color-surface, #ffffff);
		color: var(--color-accent, #c96342);
		font-weight: 600;
		box-shadow: 0 1px 2px rgba(0,0,0,0.05);
	}
	.pf-tab-icon {
		display: inline-flex;
		align-items: center;
		flex-shrink: 0;
		font-size: 12px;
	}
	.pf-tab-count {
		font-size: 10px;
		opacity: 0.75;
		background: var(--color-border, #e8e6dd);
		border-radius: 999px;
		padding: 0 4px;
		min-width: 14px;
		text-align: center;
		line-height: 1.6;
	}
	.pf-tab-active .pf-tab-count {
		background: color-mix(in srgb, var(--color-accent, #c96342) 15%, transparent);
		color: var(--color-accent, #c96342);
	}
	/* Narrow fallback: wrap to 2 rows below 340px */
	@media (max-width: 340px) {
		.pf-tabs {
			flex-wrap: wrap;
			overflow-x: visible;
		}
	}

	.pf-body {
		overflow-y: auto;
		max-height: 480px;
		flex: 1;
		background: var(--color-surface, #ffffff);
	}
	.pf-empty {
		padding: 32px 12px;
		text-align: center;
		font-size: 12.5px;
		font-weight: 500;
		letter-spacing: 0;
		color: var(--color-muted, #6f6e69);
		text-transform: none;
	}
	.pf-row {
		display: grid;
		grid-template-columns: 22px 1fr auto;
		gap: 10px;
		align-items: flex-start;
		padding: 10px 14px;
		width: 100%;
		background: var(--color-surface, #ffffff);
		border: none;
		border-bottom: 1px solid #f0eee5;
		border-left: 4px solid transparent;
		border-radius: 0;
		text-align: left;
		cursor: pointer;
		font-family: inherit;
		transition: background .12s;
	}
	.pf-row:hover { background: #f4f3ee; }
	.pf-unread {
		background: #fdf6f2;
		border-left-color: var(--color-accent, #c96342);
	}
	.pf-unread:hover { background: #faeee6; }
	.pf-row-icon {
		font-size: 14px;
		line-height: 1.3;
	}
	.pf-row-main {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.pf-row-title {
		font-size: 13px;
		font-weight: 500;
		color: var(--color-ink, #2c2c2c);
		line-height: 1.35;
		text-transform: none;
		letter-spacing: 0;
	}
	.pf-row-sub {
		font-size: 12px;
		color: var(--color-muted, #6f6e69);
		margin-top: 2px;
		line-height: 1.35;
	}
	.pf-row-ts {
		font-size: 11px;
		color: var(--color-muted, #6f6e69);
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		white-space: nowrap;
	}

	.pf-footer {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		padding: 10px 12px;
		border-top: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface, #ffffff);
	}
	.pf-foot-btn {
		flex: 1;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 7px 12px;
		background: var(--color-surface, #ffffff);
		color: var(--color-ink, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-pill, 999px);
		font-family: inherit;
		font-weight: 500;
		font-size: 12px;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
		text-decoration: none;
		text-align: center;
		transition: background .15s, border-color .15s;
	}
	.pf-foot-btn:hover { background: #f4f3ee; }
	.pf-foot-link { color: var(--color-accent, #c96342); }

	.pf-pipe-stats {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		padding: 10px 14px;
		background: #faf2ed;
		color: var(--color-accent, #c96342);
		font-size: 12px;
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.pf-pipe-cli {
		padding: 5px 12px;
		background: var(--color-accent, #c96342);
		color: #ffffff;
		border: 1px solid var(--color-accent, #c96342);
		border-radius: var(--radius-pill, 999px);
		font-family: inherit;
		font-size: 11.5px;
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
		transition: background .15s;
	}
	.pf-pipe-cli:hover { background: #b04f30; border-color: #b04f30; }

	/* ── Nudges (merged from former AINudges floating panel) ── */
	.pf-nudge-row {
		cursor: default;
		grid-template-columns: 22px 1fr auto;
		align-items: center;
	}
	.pf-nudge-row:hover { background: var(--color-surface, #ffffff); }
	.pf-nudge-icon {
		color: var(--color-accent, #c96342);
		font-size: 14px;
	}
	.pf-nudge-actions {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.pf-nudge-act {
		padding: 4px 12px;
		background: var(--color-accent, #c96342);
		color: #ffffff;
		border: 1px solid var(--color-accent, #c96342);
		border-radius: var(--radius-pill, 999px);
		font-family: inherit;
		font-size: 11.5px;
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
		white-space: nowrap;
		transition: background .15s, border-color .15s;
	}
	.pf-nudge-act:hover { background: #b04f30; border-color: #b04f30; }
	.pf-nudge-dismiss {
		background: none;
		border: none;
		color: var(--color-muted, #6f6e69);
		font-size: 16px;
		line-height: 1;
		cursor: pointer;
		padding: 0 4px;
		font-family: inherit;
	}
	.pf-nudge-dismiss:hover { color: var(--color-ink, #2c2c2c); }
</style>
