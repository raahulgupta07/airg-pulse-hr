<script>
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api.ts';
	import { addToast } from '$lib/Toast.svelte';
	import { getBranding } from '$lib/branding';

	const STORAGE_KEY = 'pulse_offer_templates';
	const MERGE_TAGS = [
		'{{candidate.name}}',
		'{{position.title}}',
		'{{salary.amount}}',
		'{{salary.currency}}',
		'{{start.date}}',
		'{{benefits}}',
		'{{org}}',
	];

	const SAMPLE = {
		'{{candidate.name}}': 'Aisha Zaw',
		'{{position.title}}': 'Senior AI Engineer',
		'{{salary.amount}}': '120,000',
		'{{salary.currency}}': 'USD',
		'{{start.date}}': 'June 1, 2026',
		'{{benefits}}': 'Health, dental, 25 PTO days, hybrid work',
		'{{org}}': (typeof window !== 'undefined' ? getBranding().appName : 'City Agent Pulse'),
	};

	const SEED = [
		{
			id: 'offer_standard',
			title: 'Standard offer letter',
			body: '# Offer of employment\n\nDear {{candidate.name}},\n\nWe are pleased to offer you the position of **{{position.title}}** at {{org}}.\n\n## Compensation\n- Base salary: {{salary.amount}} {{salary.currency}} per year\n- Start date: {{start.date}}\n\n## Benefits\n{{benefits}}\n\n## Standard clauses\n- 90-day probationary period\n- At-will employment\n- Confidentiality and IP assignment apply\n\nPlease sign and return this letter to confirm acceptance.\n\nWarm regards,\n{{org}} People Team',
		},
		{
			id: 'offer_executive',
			title: 'Executive offer letter',
			body: '# Executive offer\n\nDear {{candidate.name}},\n\nOn behalf of {{org}}, I am delighted to offer you the role of **{{position.title}}**.\n\n## Package\n- Base: {{salary.amount}} {{salary.currency}}\n- Equity: to be detailed in side letter\n- Start: {{start.date}}\n\n## Benefits\n{{benefits}}\n\n## Clauses\n- 6-month notice period\n- Non-compete and non-solicit clauses\n- Severance terms per executive policy\n\nWelcome to the team.\n\n{{org}} CEO',
		},
	];

	let templates = $state([]);
	let loading = $state(true);
	let backendOk = $state(false);

	let editing = $state(null);
	let form = $state({ title: '', body: '' });
	let preview = $state(false);
	let bodyEl;

	onMount(load);

	async function load() {
		loading = true;
		try {
			const d = await apiJson('/offer-templates');
			templates = d.templates || d || [];
			backendOk = true;
		} catch {
			backendOk = false;
			templates = readLocal();
			if (templates.length === 0) {
				templates = SEED.map(t => ({ ...t }));
				writeLocal(templates);
			}
		}
		loading = false;
	}

	function readLocal() {
		try {
			const raw = localStorage.getItem(STORAGE_KEY);
			return raw ? JSON.parse(raw) : [];
		} catch { return []; }
	}
	function writeLocal(list) {
		try { localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); } catch {}
	}

	function openNew() {
		editing = { id: null };
		form = { title: '', body: '' };
		preview = false;
	}
	function openEdit(t) {
		editing = t;
		form = { title: t.title, body: t.body };
		preview = false;
	}
	function close() { editing = null; }

	async function save() {
		if (!form.title.trim()) { addToast('error', 'Title is required'); return; }
		const payload = { ...form };
		if (backendOk) {
			try {
				if (editing.id) {
					await apiJson(`/offer-templates/${editing.id}`, { method: 'PUT', body: JSON.stringify(payload) });
				} else {
					await apiJson('/offer-templates', { method: 'POST', body: JSON.stringify(payload) });
				}
				addToast('success', 'Saved');
				await load();
				close();
				return;
			} catch {
				backendOk = false;
				addToast('info', 'Saved locally - backend integration pending');
			}
		}
		let next = readLocal();
		if (next.length === 0) next = templates.slice();
		if (editing.id) {
			next = next.map(t => (t.id === editing.id ? { ...t, ...payload } : t));
		} else {
			next = [...next, { id: 'offer_' + Date.now(), ...payload }];
		}
		writeLocal(next);
		templates = next;
		addToast('success', 'Saved');
		close();
	}

	async function duplicate(t) {
		const copy = { title: t.title + ' (copy)', body: t.body };
		if (backendOk) {
			try {
				await apiJson('/offer-templates', { method: 'POST', body: JSON.stringify(copy) });
				addToast('success', 'Duplicated');
				await load();
				return;
			} catch { backendOk = false; }
		}
		const next = [...templates, { id: 'offer_' + Date.now(), ...copy }];
		writeLocal(next);
		templates = next;
		addToast('success', 'Duplicated locally');
	}

	async function remove(t) {
		if (!confirm(`Delete offer "${t.title}"?`)) return;
		if (backendOk) {
			try {
				await apiJson(`/offer-templates/${t.id}`, { method: 'DELETE' });
				addToast('success', 'Deleted');
				await load();
				return;
			} catch { backendOk = false; }
		}
		const next = templates.filter(x => x.id !== t.id);
		writeLocal(next);
		templates = next;
		addToast('success', 'Deleted locally');
	}

	function insertTag(tag) {
		const el = bodyEl;
		if (!el) { form.body = (form.body || '') + tag; return; }
		const start = el.selectionStart ?? form.body.length;
		const end = el.selectionEnd ?? form.body.length;
		form.body = form.body.slice(0, start) + tag + form.body.slice(end);
		setTimeout(() => { el.focus(); el.selectionStart = el.selectionEnd = start + tag.length; }, 0);
	}

	function wrapMd(syntax) {
		const el = bodyEl;
		if (!el) return;
		const start = el.selectionStart;
		const end = el.selectionEnd;
		const sel = form.body.slice(start, end) || 'text';
		const wrapped = syntax === 'link' ? `[${sel}](https://example.com)` : `${syntax}${sel}${syntax}`;
		form.body = form.body.slice(0, start) + wrapped + form.body.slice(end);
		setTimeout(() => el.focus(), 0);
	}

	function renderPreview(text) {
		let out = text || '';
		for (const tag of MERGE_TAGS) out = out.split(tag).join(SAMPLE[tag] || tag);
		out = out
			.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
			.replace(/^# (.+)$/gm, '<h2>$1</h2>')
			.replace(/^## (.+)$/gm, '<h3>$1</h3>')
			.replace(/^- (.+)$/gm, '<li>$1</li>')
			.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
			.replace(/\n\n/g, '</p><p>')
			.replace(/\n/g, '<br>');
		return '<p>' + out + '</p>';
	}

	function bodyPreviewSnippet(b) {
		const flat = (b || '').replace(/[#*_`>-]/g, '').replace(/\n+/g, ' ').trim();
		return flat.length > 160 ? flat.slice(0, 160) + '...' : flat;
	}

	function generatePdf() {
		alert('PDF export coming soon');
	}
</script>

<div class="page-wrap">
	<header class="page-header">
		<div>
			<h1 class="page-title">Offer letter builder</h1>
			<p class="page-sub">Build offer templates with merge tags and standard clauses.</p>
		</div>
		<div class="actions">
			<button class="btn btn-primary" onclick={openNew}>+ New offer template</button>
		</div>
	</header>

	{#if !backendOk && !loading}
		<div class="banner">
			Backend endpoint not available - using local storage fallback (<code>{STORAGE_KEY}</code>).
		</div>
	{/if}

	{#if loading}
		<div class="empty">Loading offer templates...</div>
	{:else if templates.length === 0}
		<div class="empty">No offer templates yet. Create your first one.</div>
	{:else}
		<div class="grid">
			{#each templates as t (t.id)}
				<article class="card">
					<header class="card-head">
						<h3 class="card-title">{t.title}</h3>
					</header>
					<p class="card-body">{bodyPreviewSnippet(t.body)}</p>
					<div class="tags-inline">
						{#each MERGE_TAGS.filter(tag => (t.body || '').includes(tag)) as tag}
							<span class="mini-chip">{tag}</span>
						{/each}
					</div>
					<footer class="card-foot">
						<button class="btn btn-ghost" onclick={() => openEdit(t)}>Edit</button>
						<button class="btn btn-ghost" onclick={() => duplicate(t)}>Duplicate</button>
						<button class="btn btn-ghost danger" onclick={() => remove(t)}>Delete</button>
					</footer>
				</article>
			{/each}
		</div>
	{/if}
</div>

{#if editing !== null}
	<div class="modal-backdrop" onclick={close} role="presentation">
		<div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
			<header class="modal-head">
				<h2>{editing.id ? 'Edit offer template' : 'New offer template'}</h2>
				<button class="icon-btn" onclick={close} aria-label="Close">&times;</button>
			</header>

			<div class="modal-body">
				<label class="field">
					<span>Title</span>
					<input class="input" bind:value={form.title} placeholder="Standard offer letter" />
				</label>

				<div class="field">
					<div class="field-head">
						<span>Body (markdown)</span>
						<div class="md-bar">
							<button type="button" class="md-btn" onclick={() => wrapMd('**')}><strong>B</strong></button>
							<button type="button" class="md-btn" onclick={() => wrapMd('*')}><em>I</em></button>
							<button type="button" class="md-btn" onclick={() => wrapMd('link')}>link</button>
						</div>
					</div>
					<textarea class="textarea" bind:value={form.body} bind:this={bodyEl} rows="16" placeholder="# Offer of employment..."></textarea>
				</div>

				<div class="tags-help">
					<div class="tags-label">Variables - click to insert</div>
					<div class="tags-row">
						{#each MERGE_TAGS as tag}
							<button type="button" class="chip" onclick={() => insertTag(tag)}>{tag}</button>
						{/each}
					</div>
				</div>

				<label class="toggle">
					<input type="checkbox" bind:checked={preview} />
					<span>Preview with sample data</span>
				</label>

				{#if preview}
					<div class="preview-pane">{@html renderPreview(form.body)}</div>
				{/if}
			</div>

			<footer class="modal-foot">
				<button class="btn btn-ghost" onclick={generatePdf}>Generate sample PDF</button>
				<div style="flex: 1;"></div>
				<button class="btn btn-ghost" onclick={close}>Cancel</button>
				<button class="btn btn-primary" onclick={save}>Save</button>
			</footer>
		</div>
	</div>
{/if}

<style>
	.page-wrap { padding: 32px 40px; max-width: 1200px; margin: 0 auto; }
	.page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
	.page-title { font-family: var(--font-headline); font-size: 36px; font-weight: 500; letter-spacing: -0.02em; margin: 0; color: var(--color-ink); }
	.page-sub { color: var(--color-muted); margin: 6px 0 0; font-size: 14px; }
	.actions { display: flex; gap: 8px; }

	.banner { background: var(--color-accent-soft); color: var(--color-accent-ink); padding: 12px 16px; border-radius: var(--radius-sm); margin-bottom: 16px; font-size: 13px; }
	.banner code { background: rgba(0,0,0,0.06); padding: 2px 6px; border-radius: 4px; font-size: 12px; }

	.empty { padding: 48px; text-align: center; color: var(--color-muted); border: 1px dashed var(--color-border); border-radius: var(--radius); background: var(--color-surface); }

	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
	.card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius); padding: 18px; display: flex; flex-direction: column; gap: 10px; box-shadow: var(--shadow-sm); transition: box-shadow .15s; }
	.card:hover { box-shadow: var(--shadow-md); }
	.card-title { font-family: var(--font-headline); font-size: 18px; font-weight: 500; margin: 0; }
	.card-body { font-size: 13px; color: var(--color-muted); line-height: 1.5; margin: 0; flex: 1; }
	.tags-inline { display: flex; flex-wrap: wrap; gap: 4px; }
	.mini-chip { background: var(--color-surface-warm); color: var(--color-ink-soft); border-radius: 4px; padding: 2px 6px; font-size: 11px; font-family: ui-monospace, monospace; }
	.card-foot { display: flex; gap: 6px; padding-top: 8px; border-top: 1px solid var(--color-border-soft); }

	.btn { font-family: var(--font-body); font-size: 13px; font-weight: 500; padding: 8px 14px; border-radius: var(--radius-sm); cursor: pointer; border: 1px solid transparent; transition: all .15s; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
	.btn-primary { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }
	.btn-primary:hover { background: var(--color-accent-ink); }
	.btn-ghost { background: transparent; color: var(--color-ink-soft); border-color: var(--color-border); }
	.btn-ghost:hover { background: var(--color-surface-warm); }
	.btn-ghost.danger { color: var(--color-error); }

	.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
	.modal { background: var(--color-surface); border-radius: var(--radius); width: 100%; max-width: 760px; max-height: 90vh; display: flex; flex-direction: column; box-shadow: var(--shadow-lg); }
	.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 18px 20px; border-bottom: 1px solid var(--color-border); }
	.modal-head h2 { font-family: var(--font-headline); font-size: 22px; font-weight: 500; margin: 0; }
	.icon-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: var(--color-muted); padding: 4px 8px; border-radius: 6px; }
	.modal-body { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
	.modal-foot { display: flex; align-items: center; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--color-border); }

	.field { display: flex; flex-direction: column; gap: 6px; }
	.field > span, .field-head > span { font-size: 12px; font-weight: 600; color: var(--color-ink-soft); text-transform: uppercase; letter-spacing: 0.04em; }
	.field-head { display: flex; justify-content: space-between; align-items: center; }
	.input, .textarea { font-family: var(--font-body); font-size: 14px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-ink); width: 100%; box-sizing: border-box; }
	.textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; line-height: 1.5; resize: vertical; }
	.input:focus, .textarea:focus { outline: 2px solid var(--color-accent); outline-offset: -1px; border-color: var(--color-accent); }

	.md-bar { display: flex; gap: 4px; }
	.md-btn { background: var(--color-surface-warm); border: 1px solid var(--color-border); border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; color: var(--color-ink-soft); }

	.tags-help { background: var(--color-surface-warm); border-radius: var(--radius-sm); padding: 12px; }
	.tags-label { font-size: 11px; font-weight: 600; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px; }
	.tags-row { display: flex; gap: 6px; flex-wrap: wrap; }
	.chip { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-pill); padding: 4px 10px; font-size: 12px; font-family: ui-monospace, monospace; cursor: pointer; color: var(--color-ink-soft); }
	.chip:hover { background: var(--color-accent-soft); color: var(--color-accent-ink); border-color: var(--color-accent); }

	.toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--color-ink-soft); cursor: pointer; }
	.preview-pane { background: var(--color-bg); border: 1px solid var(--color-border); border-radius: var(--radius-sm); padding: 20px; font-size: 14px; line-height: 1.7; color: var(--color-ink); }
	.preview-pane :global(h2) { font-family: var(--font-headline); font-size: 22px; margin: 0 0 12px; }
	.preview-pane :global(h3) { font-family: var(--font-headline); font-size: 17px; margin: 16px 0 8px; }
	.preview-pane :global(ul) { padding-left: 20px; margin: 8px 0; }
	.preview-pane :global(a) { color: var(--color-accent); }
</style>
