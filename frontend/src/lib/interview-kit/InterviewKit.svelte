<script>
	import { onMount, untrack } from 'svelte';
	import { api, apiJson, authHeaders } from '$lib/api';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	let { slug, position = null } = $props();

	const AUDIENCES = [
		{ id: 'HR_BP', label: 'HR BP' },
		{ id: 'HIRING_MGR', label: 'Hiring Mgr' },
		{ id: 'PANEL', label: 'Panel' },
		{ id: 'TECH', label: 'Tech' }
	];
	const STAGES = ['SCREEN', 'TECH', 'ONSITE', 'FINAL'];

	let audience = $state('HR_BP');
	let stage = $state('SCREEN');
	let candidateId = $state(null); // null = generic
	let count = $state(8);

	let loading = $state(false);
	let generating = $state(false);
	let error = $state('');
	let questions = $state([]);
	let candidates = $state([]); // top AI matches for candidate dropdown
	let editingId = $state(null);
	let editDraft = $state({ question: '', look_for: '', red_flags: '' });
	let openCats = $state({}); // category -> bool (collapsed state)

	async function loadCandidates() {
		try {
			const data = await apiJson(`/positions/${slug}/ai`);
			const list = (data.matches || []).slice(0, 12).map(m => ({
				id: m.candidate_id,
				name: m.name || `Candidate ${m.candidate_id}`,
				score: Math.round(Number(m.match_score_composite || 0))
			}));
			candidates = list;
		} catch (e) {
			candidates = [];
		}
	}

	async function loadKit() {
		loading = true;
		error = '';
		try {
			const params = new URLSearchParams();
			if (candidateId) params.set('candidate_id', String(candidateId));
			if (audience) params.set('audience', audience);
			if (stage) params.set('stage', stage);
			const data = await apiJson(`/positions/${slug}/interview-kit?${params}`);
			questions = data.questions || [];
		} catch (e) {
			error = e?.message || 'Failed to load';
			questions = [];
		} finally {
			loading = false;
		}
	}

	async function generate() {
		generating = true;
		error = '';
		try {
			const res = await api(`/positions/${slug}/interview-kit/generate`, {
				method: 'POST',
				body: JSON.stringify({ candidate_id: candidateId, audience, stage, count })
			});
			if (!res.ok) {
				const t = await res.text();
				throw new Error(`Generate failed: ${res.status} ${t}`);
			}
			await loadKit();
		} catch (e) {
			error = e?.message || 'Generate failed';
		} finally {
			generating = false;
		}
	}

	async function copyQ(q) {
		const lines = [q.question];
		if (q.look_for?.length) lines.push(`Look for: ${q.look_for.join(' · ')}`);
		if (q.red_flags?.length) lines.push(`Red flags: ${q.red_flags.join(' · ')}`);
		try {
			await navigator.clipboard.writeText(lines.join('\n'));
		} catch (e) {}
	}

	function startEdit(q) {
		editingId = q.id;
		editDraft = {
			question: q.question,
			look_for: (q.look_for || []).join(' · '),
			red_flags: (q.red_flags || []).join(' · ')
		};
	}

	async function saveEdit(q) {
		const body = {
			question: editDraft.question,
			look_for: editDraft.look_for.split('·').map(s => s.trim()).filter(Boolean),
			red_flags: editDraft.red_flags.split('·').map(s => s.trim()).filter(Boolean)
		};
		const res = await api(`/interview-kit/${q.id}`, {
			method: 'PATCH',
			body: JSON.stringify(body)
		});
		if (res.ok) {
			editingId = null;
			await loadKit();
		}
	}

	async function markUsed(q) {
		await api(`/interview-kit/${q.id}/used`, { method: 'POST' });
		await loadKit();
	}

	async function removeQ(q) {
		if (!confirm('Remove this question?')) return;
		await api(`/interview-kit/${q.id}`, { method: 'DELETE' });
		await loadKit();
	}

	function exportMd() {
		const params = new URLSearchParams();
		if (candidateId) params.set('candidate_id', String(candidateId));
		if (audience) params.set('audience', audience);
		if (stage) params.set('stage', stage);
		const url = `/api/positions/${slug}/interview-kit/export.md?${params}`;
		const headers = authHeaders();
		fetch(url, { headers, credentials: 'include' })
			.then(r => r.blob())
			.then(b => {
				const a = document.createElement('a');
				a.href = URL.createObjectURL(b);
				a.download = `interview-kit-${slug}.md`;
				a.click();
			});
	}

	let grouped = $derived.by(() => {
		const by = {};
		for (const q of questions) {
			const c = q.category || 'OTHER';
			(by[c] = by[c] || []).push(q);
		}
		return by;
	});

	let candidateLabel = $derived.by(() => {
		if (!candidateId) return 'Generic';
		const c = candidates.find(x => x.id === candidateId);
		return c ? `${c.name} (${c.score}%)` : `Candidate ${candidateId}`;
	});

	$effect(() => {
		// re-load when slug/audience/stage/candidate changes
		const s = slug;
		audience; stage; candidateId;
		if (s) {
			untrack(() => loadKit());
		}
	});

	onMount(() => {
		loadCandidates();
	});
</script>

<div class="ik-wrap">
	<!-- Toolbar -->
	<div class="ink-border stamp-shadow ik-toolbar">
		<div class="ik-row">
			<div class="ik-field">
				<span class="ik-label">Tailor for</span>
				<select bind:value={candidateId} class="ik-select">
					<option value={null}>— Generic (whole role) —</option>
					{#each candidates as c}
						<option value={c.id}>{c.name} · {c.score}%</option>
					{/each}
				</select>
			</div>

			<div class="ik-field">
				<span class="ik-label">Audience</span>
				<div class="ik-pills">
					{#each AUDIENCES as a}
						<button
							class="ik-pill"
							class:ik-pill-active={audience === a.id}
							onclick={() => (audience = a.id)}>{a.label}</button>
					{/each}
				</div>
			</div>

			<div class="ik-field">
				<span class="ik-label">Stage</span>
				<select bind:value={stage} class="ik-select">
					{#each STAGES as s}<option value={s}>{s}</option>{/each}
				</select>
			</div>

			<div class="ik-field">
				<span class="ik-label">Count</span>
				<input type="number" bind:value={count} min="2" max="20" class="ik-num" />
			</div>

			<div class="ik-actions">
				<button
					class="ik-btn ik-btn-cta"
					onclick={generate}
					disabled={generating}>
					{generating ? '[ ... GENERATING ]' : '[ + GENERATE ]'}
				</button>
				<button class="ik-btn" onclick={exportMd} disabled={!questions.length}>
					[ EXPORT MD ]
				</button>
			</div>
		</div>
		<div class="ik-context">
			<span class="ik-ctx-label">CONTEXT</span>
			<span class="ik-ctx-val">
				{position?.title || slug} · {audience} · {stage} · {candidateLabel}
			</span>
		</div>
	</div>

	{#if error}
		<div class="ink-border ik-error">{error}</div>
	{/if}

	{#if loading}
		<div class="ik-loading">LOADING…</div>
	{:else if !questions.length}
		<div class="ink-border ik-empty">
			<div class="ik-empty-title">NO QUESTIONS YET</div>
			<div class="ik-empty-sub">
				Click <strong>[ + GENERATE ]</strong> to create
				{candidateId ? 'tailored questions using match gaps + strengths' : 'a generic question bank for this role'}.
			</div>
		</div>
	{:else}
		{#each Object.entries(grouped) as [cat, items]}
			<section class="ik-section">
				<div class="ik-section-head">
					<span class="ik-section-title">▸ {cat.replace('_', ' ')}</span>
					<span class="ik-section-count">{items.length} questions</span>
				</div>
				{#each items as q, i}
					<div class="ink-border stamp-shadow ik-card">
						<div class="ik-card-head">
							<span class="ik-qnum">Q{i + 1}</span>
							{#if q.source === 'ai_tailored'}
								<span class="ik-tag ik-tag-tailored" style="display: inline-flex; align-items: center; gap: 3px;"><Sparkles size={9} strokeWidth={1.75} /> TAILORED</span>
							{:else if q.source === 'ai_generic'}
								<span class="ik-tag ik-tag-ai" style="display: inline-flex; align-items: center; gap: 3px;"><Sparkles size={9} strokeWidth={1.75} /> AI</span>
							{:else}
								<span class="ik-tag">MANUAL</span>
							{/if}
							{#if q.used}<span class="ik-tag ik-tag-used" style="display: inline-flex; align-items: center; gap: 3px;"><Check size={9} strokeWidth={1.75} /> USED</span>{/if}
							<span class="ik-tag-mute">{q.audience} · {q.stage}</span>
						</div>

						{#if editingId === q.id}
							<textarea bind:value={editDraft.question} class="ik-edit-q" rows="2"></textarea>
							<label class="ik-edit-label">Look for (· separated)</label>
							<input bind:value={editDraft.look_for} class="ik-edit-line" />
							<label class="ik-edit-label">Red flags (· separated)</label>
							<input bind:value={editDraft.red_flags} class="ik-edit-line" />
							<div class="ik-card-actions">
								<button class="ik-btn ik-btn-cta" onclick={() => saveEdit(q)}>[ SAVE ]</button>
								<button class="ik-btn" onclick={() => (editingId = null)}>[ CANCEL ]</button>
							</div>
						{:else}
							<div class="ik-q">{q.question}</div>
							{#if q.look_for?.length}
								<div class="ik-meta">
									<span class="ik-meta-label">LOOK FOR</span>
									<span>{q.look_for.join(' · ')}</span>
								</div>
							{/if}
							{#if q.red_flags?.length}
								<div class="ik-meta ik-meta-red">
									<span class="ik-meta-label">RED FLAG</span>
									<span>{q.red_flags.join(' · ')}</span>
								</div>
							{/if}
							<div class="ik-card-actions">
								<button class="ik-btn" onclick={() => copyQ(q)}>[ COPY ]</button>
								<button class="ik-btn" onclick={() => startEdit(q)}>[ EDIT ]</button>
								{#if !q.used}
									<button class="ik-btn" onclick={() => markUsed(q)} style="display: inline-flex; align-items: center; gap: 3px;"><Check size={10} strokeWidth={1.75} /> USED</button>
								{/if}
								<button class="ik-btn ik-btn-danger" onclick={() => removeQ(q)} style="display: inline-flex; align-items: center; gap: 3px;"><X size={10} strokeWidth={1.75} /> REMOVE</button>
							</div>
						{/if}
					</div>
				{/each}
			</section>
		{/each}
	{/if}
</div>

<style>
	.ik-wrap {
		display: flex;
		flex-direction: column;
		gap: 16px;
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface, #2c2c2c);
	}
	.ik-toolbar {
		background: var(--color-surface-bright, #feffd6);
		padding: 12px 14px;
	}
	.ik-row {
		display: flex;
		flex-wrap: wrap;
		gap: 16px;
		align-items: flex-end;
	}
	.ik-field { display: flex; flex-direction: column; gap: 4px; min-width: 120px; }
	.ik-label {
		font-size: 9px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.ik-select, .ik-num {
		font-family: inherit;
		font-size: 12px;
		font-weight: 700;
		padding: 6px 8px;
		border: 2px solid var(--color-on-surface, #2c2c2c);
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
	}
	.ik-num { width: 64px; }
	.ik-pills { display: flex; gap: 4px; }
	.ik-pill {
		font-family: inherit;
		font-size: 10px;
		font-weight: 900;
		text-transform: uppercase;
		padding: 6px 12px;
		border: 1px solid var(--color-border, #d8d5cc);
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 6px;
		cursor: pointer;
		transition: background 120ms;
	}
	.ik-pill:hover { background: var(--color-bg, #faf9f5); }
	.ik-pill-active {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.ik-actions { display: flex; gap: 6px; margin-left: auto; }
	.ik-btn {
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 7px 14px;
		border: 1px solid var(--color-border, #d8d5cc);
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 6px;
		cursor: pointer;
		transition: filter 120ms, background 120ms;
	}
	.ik-btn:hover:not([disabled]) { background: var(--color-bg, #faf9f5); }
	.ik-btn[disabled] { opacity: 0.5; cursor: not-allowed; }
	.ik-btn-cta {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.ik-btn-cta:hover:not([disabled]) { filter: brightness(0.94); background: var(--color-accent, #c96342); }
	.ik-btn-danger {
		color: var(--color-error, #c4571a);
		border-color: var(--color-border, #d8d5cc);
		background: transparent;
	}
	.ik-btn-danger:hover { background: rgba(196, 87, 26, 0.08); }

	.ik-context {
		margin-top: 10px;
		padding: 6px 8px;
		border-top: 1px dashed var(--color-on-surface, #2c2c2c);
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.ik-ctx-label {
		font-size: 9px;
		font-weight: 900;
		letter-spacing: 0.06em;
		color: var(--color-primary, #007518);
	}
	.ik-ctx-val { font-size: 11px; font-weight: 700; }

	.ik-error {
		padding: 10px;
		background: #ffe5e0;
		color: #be2d06;
		font-weight: 700;
		font-size: 12px;
	}
	.ik-loading {
		padding: 24px;
		text-align: center;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.1em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.ik-empty {
		padding: 24px;
		text-align: center;
		background: var(--color-surface-bright, #feffd6);
	}
	.ik-empty-title {
		font-size: 14px;
		font-weight: 900;
		letter-spacing: 0.1em;
		margin-bottom: 6px;
	}
	.ik-empty-sub { font-size: 12px; color: var(--color-on-surface-dim, #6f6e69); }

	.ik-section { display: flex; flex-direction: column; gap: 10px; }
	.ik-section-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding-bottom: 4px;
		border-bottom: 2px solid var(--color-on-surface, #2c2c2c);
	}
	.ik-section-title {
		font-size: 12px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.ik-section-count {
		font-size: 10px;
		font-weight: 700;
		color: var(--color-on-surface-dim, #6f6e69);
	}

	.ik-card {
		background: var(--color-surface-bright, #fff);
		padding: 10px 12px;
	}
	.ik-card-head {
		display: flex;
		gap: 6px;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 6px;
	}
	.ik-qnum {
		font-size: 11px;
		font-weight: 900;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.ik-tag {
		font-size: 9px;
		font-weight: 900;
		padding: 1px 6px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border: 1px solid var(--color-on-surface, #2c2c2c);
	}
	.ik-tag-ai {
		background: rgba(201, 99, 66, 0.12);
		color: var(--color-accent, #c96342);
		border-color: rgba(201, 99, 66, 0.3);
	}
	.ik-tag-tailored {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.ik-tag-used { background: #007518; color: white; border-color: #007518; }
	.ik-tag-mute {
		font-size: 9px;
		color: var(--color-on-surface-dim, #6f6e69);
		font-weight: 700;
		margin-left: auto;
	}
	.ik-q {
		font-size: 13px;
		font-weight: 700;
		line-height: 1.4;
		margin: 4px 0 8px;
	}
	.ik-meta {
		display: flex;
		gap: 8px;
		font-size: 11px;
		margin-top: 4px;
	}
	.ik-meta-label {
		font-size: 9px;
		font-weight: 900;
		letter-spacing: 0.06em;
		color: var(--color-primary, #007518);
		min-width: 70px;
	}
	.ik-meta-red .ik-meta-label { color: #be2d06; }
	.ik-card-actions {
		display: flex;
		gap: 4px;
		margin-top: 10px;
		flex-wrap: wrap;
	}
	.ik-edit-q, .ik-edit-line {
		width: 100%;
		font-family: inherit;
		font-size: 12px;
		padding: 6px;
		border: 2px solid var(--color-on-surface, #2c2c2c);
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		margin-bottom: 4px;
	}
	.ik-edit-label {
		font-size: 9px;
		font-weight: 900;
		letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69);
		display: block;
		margin-top: 6px;
	}
</style>
