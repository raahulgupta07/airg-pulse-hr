import { writable, derived } from 'svelte/store';

const MAX_EVENTS = 500;
const _store = writable([]); // ring buffer

let runStartTs = null;
let _seenKeys = new Set(); // dedup key per (run_id|step_order|status)

function fmtRel(ts) {
	if (runStartTs == null) runStartTs = ts;
	const sec = Math.max(0, (ts - runStartTs) / 1000);
	const m = Math.floor(sec / 60).toString().padStart(2, '0');
	const s = (sec % 60).toFixed(1).padStart(4, '0');
	return `${m}:${s}`;
}

export function pushEvent(ev) {
	// ev = {ts, file, run_id, step, step_order, status, model, latency_ms, cost_usd, detail}
	const key = `${ev.run_id}|${ev.step_order ?? ev.step}|${ev.status}`;
	if (_seenKeys.has(key)) return;
	_seenKeys.add(key);
	const t = ev.ts || Date.now();
	const display = { ...ev, ts: t, rel: fmtRel(t) };
	_store.update((list) => {
		const next = [...list, display];
		return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
	});
}

export function clearEvents() {
	_seenKeys = new Set();
	runStartTs = null;
	_store.set([]);
}

export const events = _store;

export const counters = derived(_store, ($list) => {
	const runs = new Set();
	let done = 0;
	let running = 0;
	let error = 0;
	let cost = 0;
	let lat = 0;
	for (const e of $list) {
		if (e.run_id) runs.add(e.run_id);
		if (e.status === 'done') done++;
		if (e.status === 'running') running++;
		if (e.status === 'error') error++;
		cost += Number(e.cost_usd) || 0;
		lat += Number(e.latency_ms) || 0;
	}
	return { runs: runs.size, done, running, error, cost, latency_ms: lat };
});
