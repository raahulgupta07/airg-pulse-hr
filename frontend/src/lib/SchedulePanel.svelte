<script>
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api.ts';
	import { addToast } from '$lib/Toast.svelte';

	let { candidateId, candidateName = 'Candidate', positionTitle = '', open = $bindable(false), onclose = () => {} } = $props();

	const TYPES = ['Phone screen', 'Technical', 'Onsite', 'Final', 'Custom'];
	const DURATIONS = [30, 45, 60];

	function defaultDateTime() {
		const d = new Date();
		d.setDate(d.getDate() + 1);
		d.setHours(10, 0, 0, 0);
		// strip TZ for native input - YYYY-MM-DDTHH:MM
		const pad = n => String(n).padStart(2, '0');
		return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
	}

	let form = $state({
		type: 'Phone screen',
		customType: '',
		when: defaultDateTime(),
		duration: 45,
		interviewerIds: [],
		locationKind: 'video', // video | address | tbd
		locationValue: '',
		notes: '',
		sendInvite: true,
	});

	let users = $state([]);
	let usersLoaded = $state(false);
	let backendOk = $state(true);
	let saving = $state(false);
	let weekSlots = $state([]); // existing slots for selected interviewers (visual)

	const STORAGE_KEY = $derived(`pulse_scheduled_interviews_${candidateId}`);

	onMount(async () => {
		try {
			const d = await apiJson('/users');
			users = (d.users || d || []).map(u => ({ id: u.id, name: u.display_name || u.email || `User ${u.id}`, email: u.email }));
			usersLoaded = true;
		} catch {
			// fallback stub interviewers
			users = [
				{ id: 'u1', name: 'Priya Patel', email: 'priya@example.com' },
				{ id: 'u2', name: 'Marcus Lee', email: 'marcus@example.com' },
				{ id: 'u3', name: 'Sarah Chen', email: 'sarah@example.com' },
			];
			usersLoaded = true;
		}
		refreshWeekSlots();
	});

	function refreshWeekSlots() {
		const all = [];
		try {
			// pull all locally-saved interviews across candidates for the selected interviewers
			for (let i = 0; i < localStorage.length; i++) {
				const key = localStorage.key(i);
				if (!key || !key.startsWith('pulse_scheduled_interviews_')) continue;
				const arr = JSON.parse(localStorage.getItem(key) || '[]');
				for (const itv of arr) all.push(itv);
			}
		} catch {}
		weekSlots = all;
	}

	function toggleInterviewer(uid) {
		if (form.interviewerIds.includes(uid)) {
			form.interviewerIds = form.interviewerIds.filter(x => x !== uid);
		} else {
			form.interviewerIds = [...form.interviewerIds, uid];
		}
	}

	function close() {
		open = false;
		onclose();
	}

	function effectiveType() {
		return form.type === 'Custom' ? (form.customType || 'Interview') : form.type;
	}

	function buildPayload() {
		return {
			candidate_id: candidateId,
			interview_type: effectiveType(),
			scheduled_at: new Date(form.when).toISOString(),
			duration_minutes: form.duration,
			interviewer_ids: form.interviewerIds,
			location_kind: form.locationKind,
			location: form.locationValue,
			notes: form.notes,
		};
	}

	function saveLocal(payload) {
		try {
			const list = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
			list.push({ ...payload, id: 'local_' + Date.now(), saved_at: new Date().toISOString() });
			localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
		} catch {}
	}

	async function submit() {
		if (form.interviewerIds.length === 0) {
			addToast('error', 'Pick at least one interviewer');
			return;
		}
		saving = true;
		const payload = buildPayload();
		let savedRemote = false;
		if (backendOk) {
			try {
				await apiJson('/interviews', { method: 'POST', body: JSON.stringify(payload) });
				savedRemote = true;
				addToast('success', 'Interview scheduled');
			} catch {
				backendOk = false;
			}
		}
		if (!savedRemote) {
			saveLocal(payload);
			addToast('info', 'Interview saved locally - backend integration pending');
		}
		if (form.sendInvite) {
			if (savedRemote) {
				// backend would dispatch invite; nothing more here
			} else {
				downloadIcs(payload);
			}
		}
		refreshWeekSlots();
		saving = false;
		close();
	}

	function pad(n, w = 2) { return String(n).padStart(w, '0'); }

	function toIcsDate(iso) {
		const d = new Date(iso);
		return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
	}

	function downloadIcs(payload) {
		const start = new Date(payload.scheduled_at);
		const end = new Date(start.getTime() + payload.duration_minutes * 60_000);
		const uid = `pulse-${candidateId}-${Date.now()}@pulse.local`;
		const summary = `${payload.interview_type} - ${candidateName}${positionTitle ? ' (' + positionTitle + ')' : ''}`;
		const desc = (payload.notes || '').replace(/\n/g, '\\n');
		const loc = payload.location_kind === 'tbd' ? 'TBD' : (payload.location || '');
		const ics = [
			'BEGIN:VCALENDAR',
			'VERSION:2.0',
			'PRODID:-//PULSE//Schedule//EN',
			'CALSCALE:GREGORIAN',
			'METHOD:REQUEST',
			'BEGIN:VEVENT',
			`UID:${uid}`,
			`DTSTAMP:${toIcsDate(new Date().toISOString())}`,
			`DTSTART:${toIcsDate(start.toISOString())}`,
			`DTEND:${toIcsDate(end.toISOString())}`,
			`SUMMARY:${summary}`,
			`DESCRIPTION:${desc}`,
			`LOCATION:${loc}`,
			'END:VEVENT',
			'END:VCALENDAR',
		].join('\r\n');
		const blob = new Blob([ics], { type: 'text/calendar' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `interview-${candidateId}.ics`;
		a.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}

	// week-grid helpers
	function startOfWeek() {
		const d = new Date(form.when || Date.now());
		const day = d.getDay(); // 0..6 (Sun)
		d.setHours(0, 0, 0, 0);
		d.setDate(d.getDate() - day);
		return d;
	}
	let weekDays = $derived.by(() => {
		const start = startOfWeek();
		return Array.from({ length: 7 }, (_, i) => {
			const d = new Date(start);
			d.setDate(start.getDate() + i);
			return d;
		});
	});
	function slotsForDay(day) {
		const dayKey = day.toDateString();
		return weekSlots.filter(s => new Date(s.scheduled_at).toDateString() === dayKey);
	}
	function fmtDay(d) {
		return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
	}
	function fmtTime(iso) {
		return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

{#if open}
	<div class="modal-backdrop" onclick={close} role="presentation">
		<div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
			<header class="modal-head">
				<div>
					<h2>Schedule interview</h2>
					<div class="sub">For <strong>{candidateName}</strong>{positionTitle ? ` - ${positionTitle}` : ''}</div>
				</div>
				<button class="icon-btn" onclick={close} aria-label="Close">&times;</button>
			</header>

			<div class="modal-body">
				<div class="grid-2">
					<div class="left-col">
						<div class="field">
							<span class="label">Interview type</span>
							<div class="pill-row">
								{#each TYPES as t}
									<button type="button" class="pill" class:active={form.type === t} onclick={() => form.type = t}>{t}</button>
								{/each}
							</div>
							{#if form.type === 'Custom'}
								<input class="input" placeholder="Custom type name" bind:value={form.customType} style="margin-top: 8px;" />
							{/if}
						</div>

						<div class="field">
							<span class="label">When</span>
							<input type="datetime-local" class="input" bind:value={form.when} />
						</div>

						<div class="field">
							<span class="label">Duration</span>
							<div class="pill-row">
								{#each DURATIONS as d}
									<button type="button" class="pill" class:active={form.duration === d} onclick={() => form.duration = d}>{d} min</button>
								{/each}
							</div>
						</div>

						<div class="field">
							<span class="label">Interviewers</span>
							{#if !usersLoaded}
								<div class="muted">Loading users...</div>
							{:else}
								<div class="multi">
									{#each users as u}
										<label class="check-row">
											<input type="checkbox" checked={form.interviewerIds.includes(u.id)} onchange={() => toggleInterviewer(u.id)} />
											<span class="who">{u.name}</span>
											{#if u.email}<span class="email">{u.email}</span>{/if}
										</label>
									{/each}
								</div>
							{/if}
						</div>

						<div class="field">
							<span class="label">Location</span>
							<div class="pill-row">
								<button type="button" class="pill" class:active={form.locationKind === 'video'} onclick={() => form.locationKind = 'video'}>Video link</button>
								<button type="button" class="pill" class:active={form.locationKind === 'address'} onclick={() => form.locationKind = 'address'}>Address</button>
								<button type="button" class="pill" class:active={form.locationKind === 'tbd'} onclick={() => form.locationKind = 'tbd'}>TBD</button>
							</div>
							{#if form.locationKind !== 'tbd'}
								<input class="input" placeholder={form.locationKind === 'video' ? 'https://meet...' : 'Office address'} bind:value={form.locationValue} style="margin-top: 8px;" />
							{/if}
						</div>

						<div class="field">
							<span class="label">Notes</span>
							<textarea class="textarea" rows="3" bind:value={form.notes} placeholder="Agenda, links, prep notes..."></textarea>
						</div>

						<label class="check-row">
							<input type="checkbox" bind:checked={form.sendInvite} />
							<span>Send invite (downloads .ics if backend unavailable)</span>
						</label>
					</div>

					<div class="right-col">
						<div class="cal-head">Week view</div>
						<div class="cal-grid">
							{#each weekDays as d}
								<div class="cal-day">
									<div class="cal-day-head">{fmtDay(d)}</div>
									<div class="cal-day-body">
										{#each slotsForDay(d) as s}
											<div class="cal-slot" title={s.notes || ''}>
												<div class="slot-time">{fmtTime(s.scheduled_at)}</div>
												<div class="slot-type">{s.interview_type}</div>
											</div>
										{:else}
											<div class="cal-empty">-</div>
										{/each}
									</div>
								</div>
							{/each}
						</div>
						<div class="cal-foot">Showing locally-saved interviews across all candidates.</div>
					</div>
				</div>
			</div>

			<footer class="modal-foot">
				<button class="btn btn-ghost" onclick={close} disabled={saving}>Cancel</button>
				<button class="btn btn-primary" onclick={submit} disabled={saving}>{saving ? 'Saving...' : 'Schedule'}</button>
			</footer>
		</div>
	</div>
{/if}

<style>
	.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
	.modal { background: var(--color-surface); border-radius: var(--radius); width: 100%; max-width: 1080px; max-height: 92vh; display: flex; flex-direction: column; box-shadow: var(--shadow-lg); }
	.modal-head { display: flex; justify-content: space-between; align-items: flex-start; padding: 18px 20px; border-bottom: 1px solid var(--color-border); }
	.modal-head h2 { font-family: var(--font-headline); font-size: 22px; font-weight: 500; margin: 0; color: var(--color-ink); }
	.sub { font-size: 13px; color: var(--color-muted); margin-top: 2px; }
	.icon-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: var(--color-muted); padding: 4px 8px; border-radius: 6px; }
	.icon-btn:hover { background: var(--color-surface-warm); }

	.modal-body { padding: 20px; overflow-y: auto; }
	.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
	@media (max-width: 880px) { .grid-2 { grid-template-columns: 1fr; } }

	.left-col { display: flex; flex-direction: column; gap: 16px; }
	.right-col { display: flex; flex-direction: column; gap: 8px; }

	.field { display: flex; flex-direction: column; gap: 6px; }
	.label { font-size: 12px; font-weight: 600; color: var(--color-ink-soft); text-transform: uppercase; letter-spacing: 0.04em; }
	.input, .textarea { font-family: var(--font-body); font-size: 14px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-ink); width: 100%; box-sizing: border-box; }
	.input:focus, .textarea:focus { outline: 2px solid var(--color-accent); outline-offset: -1px; border-color: var(--color-accent); }
	.textarea { resize: vertical; line-height: 1.5; }

	.pill-row { display: flex; gap: 6px; flex-wrap: wrap; }
	.pill { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-pill); padding: 6px 14px; font-size: 13px; cursor: pointer; color: var(--color-ink-soft); }
	.pill:hover { background: var(--color-surface-warm); }
	.pill.active { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }

	.multi { display: flex; flex-direction: column; gap: 4px; max-height: 160px; overflow-y: auto; border: 1px solid var(--color-border); border-radius: var(--radius-sm); padding: 8px; background: var(--color-bg); }
	.check-row { display: flex; align-items: center; gap: 8px; padding: 4px 6px; font-size: 13px; cursor: pointer; border-radius: 4px; }
	.check-row:hover { background: var(--color-surface-warm); }
	.who { font-weight: 500; color: var(--color-ink); }
	.email { color: var(--color-muted); font-size: 12px; }
	.muted { color: var(--color-muted); font-size: 13px; }

	.cal-head { font-size: 12px; font-weight: 600; color: var(--color-ink-soft); text-transform: uppercase; letter-spacing: 0.04em; }
	.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; border: 1px solid var(--color-border); border-radius: var(--radius-sm); overflow: hidden; background: var(--color-bg); }
	.cal-day { display: flex; flex-direction: column; background: var(--color-surface); min-height: 240px; }
	.cal-day-head { font-size: 11px; font-weight: 600; padding: 6px 8px; color: var(--color-ink-soft); border-bottom: 1px solid var(--color-border-soft); background: var(--color-surface-warm); text-align: center; }
	.cal-day-body { display: flex; flex-direction: column; gap: 3px; padding: 6px; flex: 1; overflow-y: auto; }
	.cal-slot { background: var(--color-accent-soft); border-left: 2px solid var(--color-accent); border-radius: 4px; padding: 4px 6px; font-size: 11px; }
	.slot-time { font-weight: 700; color: var(--color-accent-ink); }
	.slot-type { color: var(--color-ink-soft); font-size: 10px; }
	.cal-empty { color: var(--color-dim); font-size: 11px; text-align: center; padding-top: 8px; }
	.cal-foot { font-size: 11px; color: var(--color-muted); }

	.modal-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--color-border); }
	.btn { font-family: var(--font-body); font-size: 13px; font-weight: 500; padding: 8px 16px; border-radius: var(--radius-sm); cursor: pointer; border: 1px solid transparent; }
	.btn:disabled { opacity: 0.6; cursor: not-allowed; }
	.btn-primary { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }
	.btn-primary:hover:not(:disabled) { background: var(--color-accent-ink); }
	.btn-ghost { background: transparent; color: var(--color-ink-soft); border-color: var(--color-border); }
	.btn-ghost:hover:not(:disabled) { background: var(--color-surface-warm); }
</style>
