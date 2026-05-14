<script>
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api.ts';
	import { addToast } from '$lib/Toast.svelte';
	import { getBranding } from '$lib/branding';

	const STORAGE_KEY = 'pulse_email_templates';
	const MERGE_TAGS = [
		'{{candidate.name}}',
		'{{candidate.email}}',
		'{{position.title}}',
		'{{interviewer}}',
		'{{date}}',
		'{{org}}',
	];

	const SEED = [
		{
			id: 'tmpl_invite',
			name: 'Interview invite',
			subject: 'Interview with {{org}} for {{position.title}}',
			body: 'Hi {{candidate.name}},\n\nThanks for applying to the {{position.title}} role at {{org}}. We would like to invite you to an interview with {{interviewer}} on {{date}}.\n\nPlease confirm your availability.\n\nBest,\n{{org}} Talent Team',
		},
		{
			id: 'tmpl_reject_polite',
			name: 'Rejection - polite',
			subject: 'Update on your application to {{org}}',
			body: 'Hi {{candidate.name}},\n\nThank you for your interest in the {{position.title}} role at {{org}}. After careful review we have decided to move forward with other candidates.\n\nWe wish you the best in your search and will keep your profile on file.\n\nBest,\n{{org}} Talent Team',
		},
		{
			id: 'tmpl_offer_generic',
			name: 'Offer - generic',
			subject: 'Offer of employment - {{position.title}}',
			body: 'Hi {{candidate.name}},\n\nWe are delighted to extend an offer for the {{position.title}} role at {{org}}, with a start date of {{date}}.\n\nFull details are attached. Please reply to confirm.\n\nBest,\n{{org}} Talent Team',
		},
		{
			id: 'tmpl_followup',
			name: 'Follow-up nudge',
			subject: 'Quick follow-up on {{position.title}}',
			body: 'Hi {{candidate.name}},\n\nJust circling back on our conversation about the {{position.title}} role. Let me know if you have any questions or would like to discuss next steps.\n\nThanks,\n{{interviewer}}',
		},
	];

	const SAMPLE = {
		'{{candidate.name}}': 'Aisha Zaw',
		'{{candidate.email}}': 'aisha.zaw@example.com',
		'{{position.title}}': 'Senior AI Engineer',
		'{{interviewer}}': 'Priya Patel',
		'{{date}}': 'Wed, May 21 at 10:00 AM',
		'{{org}}': (typeof window !== 'undefined' ? getBranding().appName : 'City Agent Pulse'),
	};

	let templates = $state([]);
	let loading = $state(true);
	let backendOk = $state(false);

	let editing = $state(null); // null | template object
	let form = $state({ name: '', subject: '', body: '' });
	let preview = $state(false);
	let bodyEl;

	onMount(load);

	async function load() {
		loading = true;
		try {
			const d = await apiJson('/email-templates');
			templates = d.templates || d || [];
			backendOk = true;
		} catch (e) {
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
		form = { name: '', subject: '', body: '' };
		preview = false;
	}
	function openEdit(t) {
		editing = t;
		form = { name: t.name, subject: t.subject, body: t.body };
		preview = false;
	}
	function close() { editing = null; }

	async function save() {
		if (!form.name.trim() || !form.subject.trim()) {
			addToast('error', 'Name and subject are required');
			return;
		}
		const payload = { ...form };
		if (backendOk) {
			try {
				if (editing.id) {
					await apiJson(`/email-templates/${editing.id}`, { method: 'PUT', body: JSON.stringify(payload) });
				} else {
					await apiJson('/email-templates', { method: 'POST', body: JSON.stringify(payload) });
				}
				addToast('success', 'Template saved');
				await load();
				close();
				return;
			} catch (e) {
				backendOk = false;
				addToast('info', 'Saved locally - backend integration pending');
			}
		}
		// localStorage fallback
		let next = readLocal();
		if (next.length === 0) next = templates.slice();
		if (editing.id) {
			next = next.map(t => (t.id === editing.id ? { ...t, ...payload } : t));
		} else {
			next = [...next, { id: 'tmpl_' + Date.now(), ...payload }];
		}
		writeLocal(next);
		templates = next;
		if (backendOk) addToast('success', 'Template saved');
		else addToast('success', 'Saved locally');
		close();
	}

	async function duplicate(t) {
		const copy = { name: t.name + ' (copy)', subject: t.subject, body: t.body };
		if (backendOk) {
			try {
				await apiJson('/email-templates', { method: 'POST', body: JSON.stringify(copy) });
				addToast('success', 'Duplicated');
				await load();
				return;
			} catch { backendOk = false; }
		}
		const next = [...readLocal().concat(templates.length === 0 ? [] : templates), { id: 'tmpl_' + Date.now(), ...copy }];
		// dedupe by id
		const seen = new Set();
		const dedup = next.filter(x => (seen.has(x.id) ? false : (seen.add(x.id), true)));
		writeLocal(dedup);
		templates = dedup;
		addToast('success', 'Duplicated locally');
	}

	async function remove(t) {
		if (!confirm(`Delete template "${t.name}"?`)) return;
		if (backendOk) {
			try {
				await apiJson(`/email-templates/${t.id}`, { method: 'DELETE' });
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
		if (!el) {
			form.body = (form.body || '') + tag;
			return;
		}
		const start = el.selectionStart ?? form.body.length;
		const end = el.selectionEnd ?? form.body.length;
		form.body = form.body.slice(0, start) + tag + form.body.slice(end);
		setTimeout(() => {
			el.focus();
			el.selectionStart = el.selectionEnd = start + tag.length;
		}, 0);
	}

	function wrapMd(syntax) {
		const el = bodyEl;
		if (!el) return;
		const start = el.selectionStart;
		const end = el.selectionEnd;
		const sel = form.body.slice(start, end) || 'text';
		const wrapped = syntax === 'link'
			? `[${sel}](https://example.com)`
			: `${syntax}${sel}${syntax}`;
		form.body = form.body.slice(0, start) + wrapped + form.body.slice(end);
		setTimeout(() => el.focus(), 0);
	}

	function renderPreview(text) {
		let out = text || '';
		for (const tag of MERGE_TAGS) {
			out = out.split(tag).join(SAMPLE[tag] || tag);
		}
		// minimal markdown
		out = out
			.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
			.replace(/\n/g, '<br>');
		return out;
	}

	function bodyPreviewSnippet(b) {
		const flat = (b || '').replace(/\n+/g, ' ');
		return flat.length > 140 ? flat.slice(0, 140) + '...' : flat;
	}
</script>

<div class="page-wrap">
	<header class="page-header">
		<div>
			<h1 class="page-title">Email templates</h1>
			<p class="page-sub">Reusable messages for invites, offers, follow-ups and rejections.</p>
		</div>
		<div class="actions">
			<button class="btn btn-primary" onclick={openNew}>+ New template</button>
		</div>
	</header>

	{#if !backendOk && !loading}
		<div class="banner">
			Backend endpoint not available - using local storage fallback (<code>{STORAGE_KEY}</code>).
		</div>
	{/if}

	{#if loading}
		<div class="empty">Loading templates...</div>
	{:else if templates.length === 0}
		<div class="empty">No templates yet. Create your first one.</div>
	{:else}
		<div class="grid">
			{#each templates as t (t.id)}
				<article class="card">
					<header class="card-head">
						<h3 class="card-title">{t.name}</h3>
					</header>
					<div class="card-subject">{t.subject}</div>
					<p class="card-body">{bodyPreviewSnippet(t.body)}</p>
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
				<h2>{editing.id ? 'Edit template' : 'New template'}</h2>
				<button class="icon-btn" onclick={close} aria-label="Close">&times;</button>
			</header>

			<div class="modal-body">
				<label class="field">
					<span>Name</span>
					<input class="input" bind:value={form.name} placeholder="Interview invite" />
				</label>

				<label class="field">
					<span>Subject</span>
					<input class="input" bind:value={form.subject} placeholder="Interview with {'{{org}}'} for {'{{position.title}}'}" />
				</label>

				<div class="field">
					<div class="field-head">
						<span>Body</span>
						<div class="md-bar">
							<button type="button" class="md-btn" onclick={() => wrapMd('**')} title="Bold"><strong>B</strong></button>
							<button type="button" class="md-btn" onclick={() => wrapMd('*')} title="Italic"><em>I</em></button>
							<button type="button" class="md-btn" onclick={() => wrapMd('link')} title="Link">link</button>
						</div>
					</div>
					<textarea
						class="textarea"
						bind:value={form.body}
						bind:this={bodyEl}
						rows="12"
						placeholder="Hi {'{{candidate.name}}'}, ..."
					></textarea>
				</div>

				<div class="tags-help">
					<div class="tags-label">Available merge tags</div>
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
					<div class="preview-pane">
						<div class="preview-subject"><strong>Subject:</strong> {renderPreview(form.subject)}</div>
						<div class="preview-body">{@html renderPreview(form.body)}</div>
					</div>
				{/if}
			</div>

			<footer class="modal-foot">
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

	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
	.card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius); padding: 18px; display: flex; flex-direction: column; gap: 8px; box-shadow: var(--shadow-sm); transition: box-shadow .15s; }
	.card:hover { box-shadow: var(--shadow-md); }
	.card-head { display: flex; justify-content: space-between; align-items: center; }
	.card-title { font-family: var(--font-headline); font-size: 18px; font-weight: 500; margin: 0; color: var(--color-ink); }
	.card-subject { font-size: 13px; color: var(--color-ink-soft); font-weight: 600; }
	.card-body { font-size: 13px; color: var(--color-muted); line-height: 1.5; margin: 0; flex: 1; }
	.card-foot { display: flex; gap: 6px; padding-top: 8px; border-top: 1px solid var(--color-border-soft); }

	.btn { font-family: var(--font-body); font-size: 13px; font-weight: 500; padding: 8px 14px; border-radius: var(--radius-sm); cursor: pointer; border: 1px solid transparent; transition: all .15s; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
	.btn-primary { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }
	.btn-primary:hover { background: var(--color-accent-ink); }
	.btn-ghost { background: transparent; color: var(--color-ink-soft); border-color: var(--color-border); }
	.btn-ghost:hover { background: var(--color-surface-warm); }
	.btn-ghost.danger { color: var(--color-error); }
	.btn-ghost.danger:hover { background: var(--color-error-soft); }

	.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
	.modal { background: var(--color-surface); border-radius: var(--radius); width: 100%; max-width: 720px; max-height: 90vh; display: flex; flex-direction: column; box-shadow: var(--shadow-lg); }
	.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 18px 20px; border-bottom: 1px solid var(--color-border); }
	.modal-head h2 { font-family: var(--font-headline); font-size: 22px; font-weight: 500; margin: 0; }
	.icon-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: var(--color-muted); padding: 4px 8px; border-radius: 6px; }
	.icon-btn:hover { background: var(--color-surface-warm); }
	.modal-body { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
	.modal-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--color-border); }

	.field { display: flex; flex-direction: column; gap: 6px; }
	.field > span, .field-head > span { font-size: 12px; font-weight: 600; color: var(--color-ink-soft); text-transform: uppercase; letter-spacing: 0.04em; }
	.field-head { display: flex; justify-content: space-between; align-items: center; }
	.input, .textarea { font-family: var(--font-body); font-size: 14px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-ink); width: 100%; box-sizing: border-box; }
	.textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; line-height: 1.5; resize: vertical; }
	.input:focus, .textarea:focus { outline: 2px solid var(--color-accent); outline-offset: -1px; border-color: var(--color-accent); }

	.md-bar { display: flex; gap: 4px; }
	.md-btn { background: var(--color-surface-warm); border: 1px solid var(--color-border); border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; color: var(--color-ink-soft); }
	.md-btn:hover { background: var(--color-bg-alt); }

	.tags-help { background: var(--color-surface-warm); border-radius: var(--radius-sm); padding: 12px; }
	.tags-label { font-size: 11px; font-weight: 600; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px; }
	.tags-row { display: flex; gap: 6px; flex-wrap: wrap; }
	.chip { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-pill); padding: 4px 10px; font-size: 12px; font-family: ui-monospace, monospace; cursor: pointer; color: var(--color-ink-soft); }
	.chip:hover { background: var(--color-accent-soft); color: var(--color-accent-ink); border-color: var(--color-accent); }

	.toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--color-ink-soft); cursor: pointer; }
	.preview-pane { background: var(--color-bg); border: 1px solid var(--color-border); border-radius: var(--radius-sm); padding: 16px; font-size: 14px; line-height: 1.6; color: var(--color-ink); }
	.preview-subject { padding-bottom: 10px; margin-bottom: 12px; border-bottom: 1px solid var(--color-border); font-size: 13px; }
	.preview-body :global(a) { color: var(--color-accent); }
</style>
