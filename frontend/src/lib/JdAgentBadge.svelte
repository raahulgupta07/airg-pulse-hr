<script>
	import { onMount, onDestroy } from 'svelte';
	import { apiJson } from '$lib/api.ts';
	import Bot from '@lucide/svelte/icons/bot';

	let state = $state({ status: 'idle', current_action: null, last_run_at: null, next_run_at: null, last_cycle_summary: null, total_runs: 0, total_jds_processed: 0 });
	let events = $state([]);
	let intervalS = $state(300);
	let lastEventId = 0;
	let expanded = $state(false);
	let pollHandle;
	let secsTilNext = $state(null);

	async function poll() {
		try {
			const r = await apiJson(`/jd-background/status?since_id=${lastEventId}&event_limit=30`);
			if (r?.state) state = r.state;
			if (r?.interval_s) intervalS = r.interval_s;
			if (Array.isArray(r?.events) && r.events.length) {
				events = [...events, ...r.events].slice(-50);
				lastEventId = r.events[r.events.length - 1].id;
				// Mirror events to global CLI terminal
				for (const e of r.events) {
					window.dispatchEvent(new CustomEvent('hire-cli', {
						detail: { type: e.level || 'info', text: `JD_AGENT · ${e.msg}` }
					}));
				}
			}
		} catch (e) { /* silent */ }
	}

	function tick() {
		if (state.next_run_at) {
			const next = new Date(state.next_run_at).getTime();
			const diff = Math.max(0, Math.round((next - Date.now()) / 1000));
			secsTilNext = diff;
		} else {
			secsTilNext = null;
		}
	}

	onMount(() => {
		poll();
		pollHandle = setInterval(poll, 4000);
		const tickHandle = setInterval(tick, 1000);
		return () => { clearInterval(tickHandle); };
	});
	onDestroy(() => { if (pollHandle) clearInterval(pollHandle); });

	const isActive = $derived(state.status === 'scanning' || state.status === 'starting');
	const statusColor = $derived(
		state.status === 'scanning' ? '#3a8a4f' :
		state.status === 'error' ? 'var(--color-error, #c4571a)' :
		state.status === 'sleeping' ? 'var(--color-warning, #c98c2a)' : '#888'
	);
	function fmtAgo(iso) {
		if (!iso) return '—';
		const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
		if (s < 60) return `${s}s ago`;
		if (s < 3600) return `${Math.round(s/60)}m ago`;
		return `${Math.round(s/3600)}h ago`;
	}
	function fmtCountdown(s) {
		if (s == null) return '—';
		const m = Math.floor(s/60), r = s%60;
		return `${m}m ${String(r).padStart(2,'0')}s`;
	}
</script>

<button class="jd-agent" class:active={isActive} class:expanded onclick={() => expanded = !expanded} title="JD Background Agent — auto-fills missing JD fields every 5 min">
	<span class="robot" class:pulse={isActive}><Bot size={14} strokeWidth={1.75} /></span>
	<span class="label">
		<span class="status-dot" style="background: {statusColor};"></span>
		JD AGENT · {(state.status || 'idle').toUpperCase()}
	</span>
	{#if !expanded}
		<span class="count" title="Total JDs enriched">{state.total_jds_processed || 0}</span>
	{/if}
</button>

{#if expanded}
	<div class="jd-agent-panel">
		<div class="panel-head">
			<span class="robot" class:pulse={isActive}><Bot size={14} strokeWidth={1.75} /></span>
			<span style="font-weight: 900; font-size: 12px; letter-spacing: 0.06em;">JD BACKGROUND AGENT</span>
			<button onclick={(e) => { e.stopPropagation(); expanded = false; }} style="margin-left: auto; background: transparent; border: 1px solid rgba(255,255,255,0.3); color: rgba(255,255,255,0.7); padding: 1px 6px; cursor: pointer; font-size: 10px;">×</button>
		</div>
		<div class="panel-body">
			<div class="row"><span class="k">Status</span><span class="v" style="color: {statusColor}; font-weight: 900;">{(state.status || '—').toUpperCase()}</span></div>
			<div class="row"><span class="k">Current</span><span class="v">{state.current_action || 'idle'}</span></div>
			<div class="row"><span class="k">Last run</span><span class="v">{fmtAgo(state.last_run_at)}</span></div>
			<div class="row"><span class="k">Next scan</span><span class="v">{fmtCountdown(secsTilNext)}</span></div>
			<div class="row"><span class="k">JDs enriched</span><span class="v">{state.total_jds_processed} · {state.total_runs} runs</span></div>
			{#if state.last_cycle_summary}
				<div class="row" style="opacity: 0.7;"><span class="k">Last cycle</span><span class="v">{state.last_cycle_summary.kf4d_done}K · {state.last_cycle_summary.skills_done}S · {state.last_cycle_summary.duration_s}s</span></div>
			{/if}
			<div class="divider"></div>
			<div class="feed-label">RECENT ACTIVITY</div>
			<div class="feed">
				{#each events.slice(-12).reverse() as ev (ev.id)}
					<div class="ev ev-{ev.level || 'info'}">
						<span class="ev-time">{new Date(ev.ts).toTimeString().slice(0,5)}</span>
						<span class="ev-msg">{ev.msg}</span>
					</div>
				{/each}
				{#if events.length === 0}
					<div style="opacity: 0.5; font-size: 10px; padding: 6px;">Waiting for first scan…</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.jd-agent {
		position: relative;
		display: inline-flex; align-items: center; gap: 6px;
		background: rgba(58,138,79,0.1); color: var(--color-on-surface, #2c2c2c);
		border: 1px solid rgba(58,138,79,0.4);
		border-radius: 6px;
		padding: 4px 10px; cursor: pointer;
		font-family: 'Space Grotesk', monospace; font-size: 10px;
		font-weight: 700; letter-spacing: 0.06em;
		transition: all 200ms;
	}
	.jd-agent:hover { border-color: #3a8a4f; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
	.jd-agent.active { border-color: #3a8a4f; box-shadow: 0 0 8px rgba(58,138,79,0.2); }
	.jd-agent.expanded { display: none; }
	.robot { font-size: 14px; display: inline-block; }
	.robot.pulse { animation: bob 1s ease-in-out infinite; }
	@keyframes bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
	.label { display: flex; align-items: center; gap: 4px; }
	.status-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
	.count { background: rgba(58,138,79,0.15); border: 1px solid rgba(58,138,79,0.35); color: #3a8a4f; padding: 0 6px; font-weight: 900; font-size: 9px; border-radius: 4px; }

	.jd-agent-panel {
		position: fixed; top: 56px; right: 200px;
		z-index: 90;
		width: 360px; max-height: 70vh;
		background: #0d0d12; color: #d6d6c4;
		border: 1px solid #3a8a4f;
		border-radius: 8px;
		font-family: 'Space Grotesk', monospace; font-size: 11px;
		box-shadow: 0 4px 24px rgba(0,0,0,0.4);
		display: flex; flex-direction: column;
	}
	.panel-head {
		display: flex; align-items: center; gap: 8px;
		padding: 8px 12px;
		background: #1a1a1e;
		border-bottom: 1px solid rgba(58,138,79,0.2);
		border-radius: 8px 8px 0 0;
	}
	.panel-body { padding: 10px 12px; overflow-y: auto; flex: 1; }
	.row { display: flex; justify-content: space-between; align-items: center; padding: 3px 0; font-size: 11px; }
	.k { color: rgba(214,214,196,0.55); text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px; font-weight: 700; }
	.v { color: #d6d6c4; }
	.divider { height: 1px; background: rgba(255,255,255,0.1); margin: 10px 0; }
	.feed-label { font-size: 10px; font-weight: 900; color: rgba(58,138,79,0.85); letter-spacing: 0.08em; margin-bottom: 4px; }
	.feed { display: flex; flex-direction: column; gap: 2px; max-height: 220px; overflow-y: auto; }
	.ev { display: flex; gap: 6px; padding: 2px 4px; font-size: 10px; line-height: 1.4; }
	.ev-time { color: rgba(214,214,196,0.35); }
	.ev-msg { color: rgba(214,214,196,0.85); }
	.ev-success .ev-msg { color: #b7ffce; }
	.ev-error .ev-msg { color: #ffb3ad; }
</style>
