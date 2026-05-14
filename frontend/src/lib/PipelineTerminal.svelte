<script>
	import { onMount, onDestroy, untrack } from 'svelte';
	import { apiJson } from '$lib/api.ts';

	let lines = $state([]);
	let collapsed = $state(true);   // default: collapsed bar; auto-expands when pipeline runs
	let userToggled = $state(false); // user manually toggled — respect their choice
	let unread = $state(0);
	let scrollEl;
	let pollHandle;
	let lastEventId = 0;
	const seenIds = new Set();
	const MAX_LINES = 800;

	let stats = $state({ running: 0, done: 0, cost: 0 });

	function push(type, text, ts = new Date()) {
		const t = ts.toTimeString().slice(0, 8);
		lines = [...lines.slice(-MAX_LINES + 1), { type, text, t, id: Date.now() + Math.random() }];
		if (collapsed) unread++;
		queueMicrotask(() => { if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight; });
	}

	function handleCli(ev) {
		const { type, text } = ev.detail || {};
		if (!text) return;
		push(type || 'info', text);
	}

	function fmtCid(id) { return `cv_${String(id).padStart(3, '0')}`; }
	function fmtMs(ms) {
		if (ms == null) return '';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms/1000).toFixed(1)}s`;
	}

	const completedAnnounced = new Set();
	async function pollStats() {
		try {
			const data = await apiJson('/candidates/pending?include_recent=true');
			const cands = data.candidates || [];
			let running = 0, done = 0, cost = 0;
			for (const c of cands) {
				const r = c.latest_run || {};
				if (r.has_running) running++;
				else if (r.total_steps && r.done_steps >= r.total_steps) {
					done++;
					// Announce completion once per (cid, run_id) — cyan-highlighted line
					const key = `${c.id}:${r.run_id || ''}`;
					if (r.run_id && !completedAnnounced.has(key)) {
						completedAnnounced.add(key);
						const fname = c.file_name || c.name || '';
						const cost_str = (r.total_cost || 0).toFixed(4);
						const latency_s = ((r.total_latency_ms || 0) / 1000).toFixed(1);
						push('complete', `╔═ PIPELINE COMPLETE · cv_${String(c.id).padStart(3,'0')} (${fname}) · ${r.total_steps}/${r.total_steps} steps · ${latency_s}s · $${cost_str} ═╗`);
					}
				}
				cost += (r.total_cost || r.cost_usd || 0);
			}
			stats = { running, done, cost };
			if (completedAnnounced.size > 1000) {
				const arr = Array.from(completedAnnounced);
				completedAnnounced.clear();
				arr.slice(-500).forEach(k => completedAnnounced.add(k));
			}
		} catch (e) { /* silent */ }
	}

	async function pollEvents() {
		try {
			// Use lower-bound -1 so we re-fetch rows whose status may have transitioned from running→done
			const cursor = Math.max(0, lastEventId - 14);
			const data = await apiJson(`/candidates/pipeline-events?since_id=${cursor}&limit=200`);
			const evs = data.events || [];
			let maxIdSeen = lastEventId;
			for (const e of evs) {
				if (e.id > maxIdSeen) maxIdSeen = e.id;
				// Dedup by (id, status) so running→done transitions both stream
				const key = `${e.id}:${e.status}`;
				if (seenIds.has(key)) continue;
				seenIds.add(key);
				const cid = fmtCid(e.candidate_id);
				const fname = (e.cand_file || e.cand_name || '').slice(0, 36);
				const label = fname ? `${cid} (${fname})` : cid;
				const step = (e.step_name || 'step').toUpperCase().padEnd(14);
				const model = (e.model || '').slice(0, 22).padEnd(22);
				const cost = e.cost_usd ? `$${e.cost_usd.toFixed(4)}` : '';
				const lat = fmtMs(e.latency_ms);
				if (e.status === 'running') {
					push('info', `${label} · ${step} ${model} running…`);
				} else if (e.status === 'done' || e.status === 'skipped') {
					push('success', `${label} · ${step} ${model} ${lat.padStart(7)} ${cost.padStart(9)}`);
				} else if (e.status === 'error') {
					push('error', `${label} · ${step} FAILED · ${e.error_msg || ''}`);
				}
			}
			if (maxIdSeen > lastEventId) lastEventId = maxIdSeen;
			// Bound seenIds memory
			if (seenIds.size > 5000) {
				const arr = Array.from(seenIds);
				seenIds.clear();
				arr.slice(-2500).forEach(k => seenIds.add(k));
			}
		} catch (e) { /* silent */ }
	}

	async function poll() {
		await Promise.allSettled([pollStats(), pollEvents()]);
	}

	function handleCliOpen(e) {
		collapsed = false;
		userToggled = false; // let auto-expand keep working
		unread = 0;
		const d = e?.detail || {};
		if (d.runId || d.candidateId) {
			push('info', `→ JUMP cv_${d.candidateId || '?'}${d.runId ? ` run ${String(d.runId).slice(0,8)}` : ''}`);
		}
	}

	onMount(() => {
		window.addEventListener('hire-cli', handleCli);
		window.addEventListener('hire-cli-open', handleCliOpen);
		push('info', '╔═══ Activity terminal ═════════════════════════╗');
		push('info', '║  Live stream: pipeline_trace events           ║');
		push('info', '╚═══════════════════════════════════════════════╝');
		// Probe DB max_id so we only stream NEW events going forward (skip history)
		apiJson('/candidates/pipeline-events?since_id=999999999&limit=1').then(d => {
			if (typeof d.max_id === 'number') lastEventId = d.max_id;
		}).catch(() => {});
		pollStats();
		pollHandle = setInterval(poll, 1200);
	});
	onDestroy(() => {
		window.removeEventListener('hire-cli', handleCli);
		window.removeEventListener('hire-cli-open', handleCliOpen);
		if (pollHandle) clearInterval(pollHandle);
	});

	function clearLines() { lines = []; unread = 0; }
	function saveLog() {
		const blob = new Blob([lines.map(l => `[${l.t}] ${l.type.toUpperCase().padEnd(8)} ${l.text}`).join('\n')], { type: 'text/plain' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url; a.download = `pulse-terminal-${Date.now()}.log`; a.click();
		URL.revokeObjectURL(url);
	}
	function toggle() { collapsed = !collapsed; userToggled = true; if (!collapsed) unread = 0; }

	// Auto-expand when pipeline starts running (unless user explicitly toggled)
	$effect(() => {
		const running = stats.running;
		const tog = userToggled;
		if (!tog && running > 0) {
			untrack(() => {
				if (collapsed) {
					collapsed = false;
					unread = 0;
				}
			});
		}
	});
</script>

<div class="term-wrap" class:collapsed>
	<div class="term-bar" role="button" tabindex="0" onclick={toggle} onkeydown={(e) => { if (e.key === 'Enter') toggle(); }}>
		<span class="term-title">┌─ Activity terminal</span>
		<span class="term-stats">
			<span class="stat-running">▶ {stats.running} RUNNING</span>
			<span class="stat-sep">·</span>
			<span class="stat-done">✓ {stats.done} DONE</span>
			<span class="stat-sep">·</span>
			<span class="stat-cost">$ {stats.cost.toFixed(4)}</span>
			{#if collapsed && unread > 0}
				<span class="badge">+{unread}</span>
			{/if}
		</span>
		<span class="term-controls">
			<button class="ctl" onclick={(e) => { e.stopPropagation(); clearLines(); }} title="Clear">CLR</button>
			<button class="ctl" onclick={(e) => { e.stopPropagation(); saveLog(); }} title="Save log">SAVE</button>
			<button class="ctl" onclick={(e) => { e.stopPropagation(); toggle(); }} title={collapsed ? 'Expand' : 'Minimize'}>{collapsed ? '▲' : '▼'}</button>
		</span>
	</div>
	{#if !collapsed}
		<div class="term-body" bind:this={scrollEl}>
			{#each lines as line (line.id)}
				<div class="term-line" class:err={line.type==='error'} class:ok={line.type==='success'} class:warn={line.type==='warn'} class:complete={line.type==='complete'}>
					<span class="ts">[{line.t}]</span>
					<span class="sym">{line.type === 'error' ? '✗' : line.type === 'success' ? '✓' : line.type === 'warn' ? '⚠' : line.type === 'complete' ? '★' : '›'}</span>
					<span class="msg">{line.text}</span>
				</div>
			{/each}
			<div class="prompt">› <span class="cursor">_</span></div>
		</div>
		<div class="term-foot">└─[ {lines.length} EVENTS · POLLING 1.2s · {new Date().toLocaleTimeString()} ]──────────────</div>
	{/if}
</div>

<style>
	.term-wrap {
		position: fixed;
		left: 0; right: 0; bottom: 0;
		background: #1a1a1a;
		color: #d6d6c4;
		font-family: ui-monospace, 'SF Mono', Menlo, monospace;
		font-size: 11px;
		line-height: 1.55;
		z-index: 80;
		border-top: 1px solid #c96342;
		box-shadow: 0 -4px 16px rgba(0,0,0,0.25);
		transition: max-height 180ms ease;
		max-height: 180px;
	}
	.term-wrap.collapsed { max-height: 28px; }
	.term-bar {
		display: flex; align-items: center; justify-content: space-between;
		padding: 4px 14px; cursor: pointer; user-select: none;
		background: #222222; border-bottom: 1px solid rgba(201,99,66,0.25);
		height: 28px;
	}
	.term-title { color: #e87d5f; font-weight: 600; letter-spacing: 0.02em; }
	.term-stats { display: flex; align-items: center; gap: 10px; font-weight: 500; }
	.stat-running { color: #d49060; }
	.stat-done { color: #7fb88f; }
	.stat-cost { color: #d6d6c4; opacity: 0.7; }
	.stat-sep { color: rgba(255,255,255,0.2); }
	.badge {
		background: #c96342; color: white;
		padding: 1px 8px; font-size: 10px; font-weight: 600;
		margin-left: 6px; border-radius: 999px;
	}
	.term-controls { display: flex; gap: 6px; }
	.ctl {
		background: transparent; color: #d6d6c4;
		border: 1px solid rgba(255,255,255,0.18);
		padding: 2px 12px; border-radius: 999px;
		font-family: inherit; font-size: 10.5px; font-weight: 500; letter-spacing: 0;
		cursor: pointer;
		transition: background .15s, border-color .15s, color .15s;
	}
	.ctl:hover { background: rgba(201,99,66,0.15); border-color: #c96342; color: #e87d5f; }
	.term-body {
		padding: 6px 14px; overflow-y: auto; max-height: 140px;
		background: #1a1a1a;
	}
	.term-line { white-space: pre; word-break: break-word; padding: 1px 0; font-family: ui-monospace, 'SF Mono', Menlo, monospace; }
	.term-line .ts { color: rgba(214,214,196,0.4); margin-right: 8px; }
	.term-line .sym { display: inline-block; width: 14px; text-align: center; font-weight: 600; color: #e87d5f; }
	.term-line .msg { color: rgba(214,214,196,0.9); }
	.term-line.err .sym { color: #ff7a70; }
	.term-line.err .msg { color: #ffb3ad; }
	.term-line.ok .sym { color: #7fb88f; }
	.term-line.ok .msg { color: #b7d9c3; }
	.term-line.warn .sym { color: #d49060; }
	.term-line.warn .msg { color: #e8c79a; }
	.term-line.complete {
		background: rgba(201, 99, 66, 0.12);
		padding: 4px 8px; margin: 4px 0;
		border-left: 3px solid #c96342;
	}
	.term-line.complete .sym { color: #e87d5f; }
	.term-line.complete .msg { color: #e87d5f; font-weight: 600; letter-spacing: 0.02em; }
	.prompt { color: #e87d5f; padding: 4px 0; }
	.cursor { animation: blink 1s step-end infinite; }
	@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
	.term-foot {
		padding: 2px 14px; background: #222222; color: rgba(214,214,196,0.3);
		font-size: 9.5px; letter-spacing: 0.04em;
		border-top: 1px solid rgba(201,99,66,0.15);
	}
</style>
