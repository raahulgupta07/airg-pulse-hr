<script>
	/** Positions Grid — Home page (Claude warm theme) */
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api';
	import { addToast } from '$lib/Toast.svelte';
	import { SkeletonCard } from '$lib/Skeleton.svelte';
	import EmptyState from '$lib/EmptyState.svelte';
	import ClipboardList from '@lucide/svelte/icons/clipboard-list';
	import Briefcase from '@lucide/svelte/icons/briefcase';
	import Package from '@lucide/svelte/icons/package';
	import X from '@lucide/svelte/icons/x';

	let positions = $state([]);
	let loading = $state(true);
	let showCreate = $state(false);

	// Status filter: 'active' | 'all' | 'closed'
	let statusFilter = $state('active');
	let searchQuery = $state('');
	let filteredPositions = $derived.by(() => {
		const q = searchQuery.trim().toLowerCase();
		if (!q) return positions;
		return positions.filter(p => {
			const hay = [p.title, p.department, p.location, p.slug, ...(p.required_skills || []), ...(p.tags || [])]
				.filter(Boolean).join(' ').toLowerCase();
			return hay.includes(q);
		});
	});

	// Create form
	let newTitle = $state('');
	let newDept = $state('');
	let newLocation = $state('');
	let newType = $state('full-time');
	let creating = $state(false);

	// Templates
	let templates = $state([]);
	let createMode = $state('blank'); // 'blank' | 'template'
	let selectedTemplateId = $state(null);
	let selectedTemplate = $derived(templates.find(t => t.id === selectedTemplateId));

	// Validation
	let titleTouched = $state(false);
	let deptTouched = $state(false);
	let titleError = $derived(
		titleTouched && newTitle.trim().length < 3 ? (newTitle.trim().length === 0 ? 'Title is required' : 'Title must be at least 3 characters') : ''
	);
	let deptWarning = $derived(deptTouched && !newDept.trim() ? 'Department recommended' : '');
	let titleValid = $derived(newTitle.trim().length >= 3);

	let headerSubtitle = $derived(
		statusFilter === 'active' ? `${positions.length} active · last sync just now`
		: statusFilter === 'closed' ? `${positions.length} closed · last sync just now`
		: statusFilter === 'archived' ? `${positions.length} archived · soft-deleted, restore anytime`
		: `${positions.length} total · last sync just now`
	);

	onMount(() => {
		loadPositions();
		loadTemplates();
	});

	async function loadTemplates() {
		try {
			const data = await apiJson('/positions/templates');
			templates = data.templates || [];
		} catch (e) { /* templates table may not exist yet */ }
	}

	function applyTemplate(tpl) {
		selectedTemplateId = tpl.id;
		newTitle = tpl.title || '';
		newDept = tpl.department || '';
		newType = tpl.employment_type || 'full-time';
	}

	async function loadPositions() {
		loading = true;
		try {
			let url = '/positions';
			if (statusFilter === 'active') url += '?status=active';
			else if (statusFilter === 'closed') url += '?status=closed';
			else if (statusFilter === 'archived') url += '?status=archived';
			const data = await apiJson(url);
			positions = data.positions || [];
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error(e); }
		loading = false;
	}

	async function restorePosition(slug, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		try {
			await apiJson(`/board/positions/${slug}/unarchive`, { method: 'POST' });
			addToast('success', 'Position restored');
			await loadPositions();
		} catch (e) { addToast('error', `Restore failed: ${e.message}`); }
	}

	async function posBulkRestore() {
		const slugs = [...posSelectedSlugs];
		try {
			await Promise.all(slugs.map(s => apiJson(`/board/positions/${s}/unarchive`, { method: 'POST' }).catch(() => null)));
			addToast('success', `Restored ${slugs.length} position${slugs.length === 1 ? '' : 's'}`);
			posClearSelection();
			await loadPositions();
		} catch (e) { addToast('error', `Restore failed: ${e.message}`); }
	}

	function setFilter(f) {
		statusFilter = f;
		loadPositions();
	}

	async function archivePosition(e, slug) {
		e.preventDefault();
		e.stopPropagation();
		try {
			await apiJson(`/positions/${slug}/archive`, { method: 'POST' });
			cliEvent('success', `Position archived`);
			await loadPositions();
		} catch (err) {
			cliEvent('error', `Archive failed: ${err.message}`);
		}
	}

	// --- Hard-delete position with double-confirm ---
	let posDeleteTarget = $state(null); // { slug, title }
	let posDeleteConfirmText = $state('');
	let posDeleting = $state(false);

	// --- Smart title-casing + common HR-domain typo corrections ---
	const HR_TYPO_MAP = {
		// Engineer/engineering misspellings
		'eginner': 'engineer', 'enginner': 'engineer', 'enginer': 'engineer', 'enginer.': 'engineer.',
		'enginerring': 'engineering', 'engneer': 'engineer', 'engneering': 'engineering',
		'developement': 'development', 'developmnet': 'development', 'developent': 'development',
		'managment': 'management', 'mangment': 'management', 'managemnet': 'management',
		'analist': 'analyst', 'anaylst': 'analyst', 'analyist': 'analyst',
		'desinger': 'designer', 'desginer': 'designer',
		'recruitement': 'recruitment', 'recruitement.': 'recruitment.',
		'specalist': 'specialist', 'speciallist': 'specialist',
		'reseacher': 'researcher', 'reasearch': 'research',
		'softwear': 'software', 'sotware': 'software',
		'frontent': 'frontend', 'backed': 'backend',
		'archtect': 'architect', 'arcitect': 'architect',
		'concultant': 'consultant', 'consultent': 'consultant',
		'directer': 'director',
		// Words that should stay lowercase even in title-case
	};
	const KEEP_LOWER = new Set(['a','an','and','at','by','for','in','of','on','or','the','to','vs','via','with']);
	const KEEP_UPPER = new Set(['ai','ml','it','hr','hse','ehs','ux','ui','sre','seo','ceo','cto','cfo','vp','sr','jr','qa','os','db','iot','api','sdk','sql','aws','gcp','llm','rag','dei']);

	function smartTitleCase(input) {
		if (!input) return input;
		const original = String(input).trim().replace(/\s+/g, ' ');
		if (!original) return original;
		// Step 1: lowercase + apply typo map word-by-word
		const words = original.split(' ');
		const fixed = words.map((w, i) => {
			const stripped = w.toLowerCase().replace(/[^a-z0-9'-]/g, '');
			const punct = w.slice(stripped.length);
			let corrected = HR_TYPO_MAP[stripped] || stripped;
			// Step 2: casing
			if (KEEP_UPPER.has(corrected)) {
				return corrected.toUpperCase() + punct;
			}
			if (i > 0 && KEEP_LOWER.has(corrected)) {
				return corrected + punct;
			}
			return corrected.charAt(0).toUpperCase() + corrected.slice(1) + punct;
		});
		return fixed.join(' ');
	}
	function askDeletePosition(e, pos) {
		e?.preventDefault?.(); e?.stopPropagation?.();
		posDeleteTarget = { slug: pos.slug, title: pos.title };
		posDeleteConfirmText = '';
	}
	async function confirmDeletePosition() {
		if (!posDeleteTarget) return;
		const ok = posDeleteConfirmText.trim().toLowerCase() === (posDeleteTarget.title || '').trim().toLowerCase()
			|| posDeleteConfirmText.trim().toUpperCase() === 'DELETE';
		if (!ok) {
			cliEvent('error', `Type position name "${posDeleteTarget.title}" or DELETE`);
			return;
		}
		posDeleting = true;
		try {
			const deletedSlug = posDeleteTarget.slug;
			const deletedTitle = posDeleteTarget.title;
			// Snapshot for undo (re-POST /api/positions if user clicks Undo)
			const snapshot = positions.find(p => p.slug === deletedSlug) || { title: deletedTitle, slug: deletedSlug };
			await apiJson(`/positions/${deletedSlug}?hard=true`, { method: 'DELETE' });
			cliEvent('success', `Position "${deletedTitle}" permanently deleted`);
			addToast('success', `Deleted "${deletedTitle}"`);
			posDeleteTarget = null;
			posDeleteConfirmText = '';
			// Optimistic remove — fresh array reference triggers Svelte 5 reactivity
			positions = [...positions.filter(p => p.slug !== deletedSlug)];
			posSelectedSlugs = new Set([...posSelectedSlugs].filter(s => s !== deletedSlug));
			// Belt + suspenders: re-fetch from DB to confirm
			loadPositions();
			// Fire pulse-undo event — re-POST to restore on click
			if (typeof window !== 'undefined') {
				window.dispatchEvent(new CustomEvent('pulse-undo', {
					detail: {
						message: `Position "${deletedTitle}" deleted`,
						onUndo: async () => {
							try {
								await apiJson('/positions/', {
									method: 'POST',
									body: JSON.stringify({
										title: snapshot.title,
										department: snapshot.department || '',
										location: snapshot.location || '',
										employment_type: snapshot.employment_type || 'full-time',
									}),
								});
								cliEvent('success', `Position "${deletedTitle}" restored`);
								await loadPositions();
							} catch (err) {
								cliEvent('error', `Restore failed: ${err.message}`);
							}
						},
					},
				}));
			}
			await loadPositions();
		} catch (e) {
			cliEvent('error', `Delete failed: ${e.message}`);
		}
		posDeleting = false;
	}

	async function createPosition() {
		if (!newTitle.trim()) return;
		creating = true;
		try {
			let res;
			if (createMode === 'template' && selectedTemplateId) {
				res = await apiJson(`/positions/from-template/${selectedTemplateId}`, {
					method: 'POST',
					body: JSON.stringify({ title: newTitle, department: newDept, location: newLocation }),
				});
			} else {
				res = await apiJson('/positions/', {
					method: 'POST',
					body: JSON.stringify({ title: newTitle, department: newDept, location: newLocation, employment_type: newType }),
				});
			}
			const createdSlug = res.slug;
			showCreate = false;
			cliEvent('success', `Position "${newTitle}" created`);
			newTitle = ''; newDept = ''; newLocation = ''; newType = 'full-time';
			createMode = 'blank'; selectedTemplateId = null;
			await loadPositions();
			// Navigate to the new position
			if (createdSlug) window.location.href = `/positions/${createdSlug}`;
		} catch (e) {
			cliEvent('error', `Failed: ${e.message}`);
		}
		creating = false;
	}

	function cliEvent(type, text) {
		window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type, text } }));
	}

	// --- Position Health Score (client-side calculation) ---
	function computeHealth(pos) {
		const cvCount = pos.cv_count || 0;
		const avgMatch = pos.avg_match || 0;
		const pipeline = pos.pipeline || {};
		const daysOpen = pos.days_open || 0;

		const activePipeline = Object.entries(pipeline)
			.filter(([stage]) => stage !== 'uploaded' && stage !== 'rejected')
			.reduce((sum, [, count]) => sum + count, 0);

		const pipelineScore = cvCount > 0 ? Math.min(100, activePipeline * 20) : 0;
		const cvScore = Math.min(100, cvCount * 10);
		const matchScore = avgMatch;
		const freshness = daysOpen <= 60 ? Math.max(0, 100 - (daysOpen * 100 / 60)) : 0;

		return Math.round(
			pipelineScore * 0.25 +
			cvScore * 0.25 +
			matchScore * 0.30 +
			freshness * 0.20
		);
	}

	function healthLabel(score) {
		if (score >= 70) return 'On track';
		if (score >= 40) return 'Needs attention';
		return 'At risk';
	}

	function timeAgo(pos) {
		const d = pos.days_open;
		if (d == null) return 'recently';
		if (d === 0) return 'today';
		if (d === 1) return '1d ago';
		if (d < 30) return `${d}d ago`;
		const m = Math.floor(d / 30);
		return m === 1 ? '1mo ago' : `${m}mo ago`;
	}

	// ─── Bulk selection ───
	let posSelectedSlugs = $state(new Set());
	let posBulkConfirmAction = $state(null); // null | 'delete'
	function posToggleSelected(slug, ev) {
		ev?.preventDefault?.();
		ev?.stopPropagation?.();
		const next = new Set(posSelectedSlugs);
		if (next.has(slug)) next.delete(slug); else next.add(slug);
		posSelectedSlugs = next;
	}
	function posClearSelection() { posSelectedSlugs = new Set(); }

	async function posBulkArchive() {
		const slugs = [...posSelectedSlugs];
		try {
			await Promise.all(slugs.map(s => apiJson(`/positions/${s}/archive`, { method: 'POST' }).catch(() => null)));
			cliEvent('success', `Archived ${slugs.length} positions`);
			posClearSelection();
			await loadPositions();
		} catch (e) { cliEvent('error', `Archive failed: ${e.message}`); }
	}
	async function posBulkClose() {
		const slugs = [...posSelectedSlugs];
		try {
			await Promise.all(slugs.map(s => apiJson(`/positions/${s}`, {
				method: 'PATCH', body: JSON.stringify({ status: 'closed' })
			}).catch(() => null)));
			cliEvent('success', `Closed ${slugs.length} positions`);
			posClearSelection();
			await loadPositions();
		} catch (e) { cliEvent('error', `Close failed: ${e.message}`); }
	}
	async function posBulkDelete() {
		const slugs = [...posSelectedSlugs];
		const slugSet = new Set(slugs);
		try {
			await Promise.all(slugs.map(s => apiJson(`/positions/${s}?hard=true`, { method: 'DELETE' }).catch(() => null)));
			cliEvent('success', `Deleted ${slugs.length} positions`);
			addToast('success', `Deleted ${slugs.length} position${slugs.length === 1 ? '' : 's'}`);
			posBulkConfirmAction = null;
			// Optimistic remove with fresh array
			positions = [...positions.filter(p => !slugSet.has(p.slug))];
			posClearSelection();
			loadPositions();
		} catch (e) { cliEvent('error', `Delete failed: ${e.message}`); }
	}
	async function posBulkExport() {
		const slugs = [...posSelectedSlugs];
		const out = [];
		for (const slug of slugs) {
			try {
				const pos = await apiJson(`/positions/${slug}`);
				let candidates = [];
				try {
					const cd = await apiJson(`/positions/${slug}/candidates`);
					candidates = cd.candidates || cd.items || [];
				} catch {}
				out.push({ position: pos, candidates });
			} catch { /* skip */ }
		}
		const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), positions: out }, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url; a.download = `positions-export-${Date.now()}.json`;
		document.body.appendChild(a); a.click();
		setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
		cliEvent('success', `Exported ${out.length} positions`);
	}

	// ── Demo data seed (first-run helper) ──
	let isOnboarded = $state(false);
	let seedingDemo = $state(false);
	$effect(() => {
		if (typeof window === 'undefined') return;
		try { isOnboarded = localStorage.getItem('pulse_onboarded') === '1'; } catch {}
	});
	async function tryDemoData() {
		seedingDemo = true;
		try {
			const r = await fetch('/api/demo/seed', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: '{}'
			});
			if (r.status === 404) {
				alert('Demo data: ask admin to enable. Skipping for now.');
				return;
			}
			if (!r.ok) {
				alert('Demo data: ask admin to enable. Skipping for now.');
				return;
			}
			addToast('success', 'Demo data loaded');
			await loadPositions();
		} catch (e) {
			alert('Demo data: ask admin to enable. Skipping for now.');
		} finally {
			seedingDemo = false;
		}
	}
</script>

<div class="pulse-page">
	<!-- Page header -->
	<div class="page-head section-animate">
		<div>
			<h1 class="page-title">Open positions</h1>
			<div class="page-sub">
				<span class="live-dot"></span>
				{headerSubtitle}
			</div>
		</div>
		<div class="actions">
			<div class="pos-search-wrap">
				<span class="material-symbols-outlined pos-search-icon">search</span>
				<input
					type="text"
					class="pos-search"
					bind:value={searchQuery}
					placeholder="Search positions by title, dept, location, skill…"
					aria-label="Search positions"
				/>
				{#if searchQuery}
					<button class="pos-search-clear" onclick={() => searchQuery = ''} aria-label="Clear search">×</button>
				{/if}
			</div>
			<div class="seg">
				{#each [['active','Active'],['closed','Closed'],['archived','Archived'],['all','All']] as [val, label]}
					<button class="seg-item {statusFilter === val ? 'on' : ''}" onclick={() => setFilter(val)}>{label}</button>
				{/each}
			</div>
			<button class="btn btn-ghost btn-sm" onclick={() => { window.location.href = '/api/positions/export.csv'; }} title="Export positions as CSV">↓ Export</button>
			<button class="btn btn-primary" onclick={() => showCreate = true}>+ New position</button>
		</div>
	</div>

	<!-- Create Modal (warm restyle) -->
	{#if showCreate}
		<div class="warm-modal-backdrop" onclick={(e) => { if (e.target === e.currentTarget) showCreate = false; }}>
			<div class="warm-modal animate-fade-up" style="width: 560px; max-height: 90vh; overflow-y: auto;">
				<div class="warm-modal-head">
					<span class="serif" style="font-size: 18px;">Create position</span>
					<button class="warm-modal-close" onclick={() => showCreate = false}>✕</button>
				</div>
				<div style="padding: 22px; display: flex; flex-direction: column; gap: 16px;">
					<!-- Template / Blank toggle -->
					<div class="seg" style="align-self: flex-start;">
						<button class="seg-item {createMode === 'blank' ? 'on' : ''}" onclick={() => { createMode = 'blank'; selectedTemplateId = null; }}>
							+ Blank
						</button>
						<button class="seg-item {createMode === 'template' ? 'on' : ''}" onclick={() => createMode = 'template'}>
							From template
						</button>
					</div>

					<!-- Template selector -->
					{#if createMode === 'template'}
						{#if templates.length === 0}
							<div class="warm-info" style="border-left-color: var(--color-warning, #a06000);">
								<p style="font-size: 12.5px; color: var(--color-on-surface-dim);">No templates saved yet. Create a position and save it as a template from the Settings tab.</p>
							</div>
						{:else}
							<div>
								<label class="warm-label">Select template</label>
								<div class="warm-template-list">
									{#each templates as tpl}
										<button class="warm-template-item {selectedTemplateId === tpl.id ? 'on' : ''}" onclick={() => applyTemplate(tpl)}>
											<span style="font-weight: 600;">{tpl.name}</span>
											<span style="opacity: 0.65;"> — {tpl.title} · {tpl.department || 'No dept'}</span>
										</button>
									{/each}
								</div>
							</div>
						{/if}
					{/if}

					<div>
						<label class="warm-label">Position title *</label>
						<input bind:value={newTitle} placeholder="e.g. Senior Backend Engineer"
							class="warm-input"
							class:warm-input-error={titleError}
							spellcheck="true" autocorrect="on" autocapitalize="words" autocomplete="off"
							onfocus={() => titleTouched = true}
							onblur={(e) => { titleTouched = true; newTitle = smartTitleCase(newTitle); }} />
						{#if titleError}
							<p class="warm-hint warm-hint-error">{titleError}</p>
						{/if}
					</div>
					<div style="display: flex; gap: 12px;">
						<div style="flex: 1;">
							<label class="warm-label">Department</label>
							<input bind:value={newDept} placeholder="Engineering"
								class="warm-input"
								class:warm-input-warn={deptWarning}
								spellcheck="true" autocorrect="on" autocapitalize="words" autocomplete="off"
								onfocus={() => deptTouched = true}
								onblur={() => { deptTouched = true; newDept = smartTitleCase(newDept); }} />
							{#if deptWarning}
								<p class="warm-hint warm-hint-warn">{deptWarning}</p>
							{/if}
						</div>
						<div style="flex: 1;">
							<label class="warm-label">Location</label>
							<input bind:value={newLocation} placeholder="Remote / San Francisco" class="warm-input"
								spellcheck="true" autocorrect="on" autocapitalize="words" autocomplete="off"
								onblur={() => newLocation = smartTitleCase(newLocation)} />
						</div>
					</div>
					<div>
						<label class="warm-label">Employment type</label>
						<div class="seg" style="display: flex;">
							{#each [['full-time','Full-time'],['part-time','Part-time'],['contract','Contract'],['intern','Intern']] as [v, lbl]}
								<button class="seg-item {newType === v ? 'on' : ''}" onclick={() => newType = v} style="flex: 1;">{lbl}</button>
							{/each}
						</div>
					</div>
					<div class="warm-info">
						<p style="font-size: 12.5px; color: var(--color-on-surface-dim); line-height: 1.55; margin: 0;">
							You can add the job description inside the position — generate with AI, attach from JD repo, or write manually.
						</p>
					</div>
					<div style="display: flex; gap: 8px; justify-content: flex-end;">
						<button class="btn" onclick={() => { showCreate = false; titleTouched = false; deptTouched = false; }}>Cancel</button>
						<button class="btn btn-primary" onclick={createPosition} disabled={!titleValid || creating}>
							{creating ? 'Creating…' : 'Create & open'}
						</button>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Grid -->
	{#if loading}
		<div class="section-animate">
			<SkeletonCard count={4} />
		</div>
	{:else if positions.length === 0}
		<EmptyState
			icon={ClipboardList}
			title="No positions yet"
			description="Create your first hiring role to start matching CVs."
			actionLabel="+ New position"
			onAction={() => showCreate = true}
		/>
	{:else if filteredPositions.length === 0}
		<EmptyState
			icon={ClipboardList}
			title="No positions match your search"
			description="Try a different keyword, or clear the search to see all positions."
			actionLabel="Clear search"
			onAction={() => searchQuery = ''}
		/>
	{:else}
		<div class="warm-grid section-animate">
			{#each filteredPositions as pos (pos.slug)}
				{@const health = computeHealth(pos)}
				{@const matchPct = pos.avg_match ? Math.round(pos.avg_match) : null}
				{@const dept = pos.department || 'No department'}
				{@const loc = pos.location || ''}
				{@const ago = timeAgo(pos)}
				{@const meta = [dept, loc, ago].filter(Boolean).join(' · ')}
				<a href="/positions/{pos.slug}" class="warm-card" class:warm-card-selected={posSelectedSlugs.has(pos.slug)} style="position: relative; text-decoration: none; color: inherit; display: flex; flex-direction: column; gap: 12px; {pos.status === 'closed' ? 'opacity: 0.65;' : ''}">
					<input type="checkbox"
						class="warm-card-check"
						checked={posSelectedSlugs.has(pos.slug)}
						onclick={(e) => posToggleSelected(pos.slug, e)} />
					<div class="warm-card-head">
						<div class="warm-card-icon"><Briefcase size={16} stroke-width={1.75} /></div>
						<div style="flex: 1; min-width: 0;">
							<div class="warm-card-title serif">{pos.title}</div>
							<div class="warm-card-meta">{meta}</div>
						</div>
						<span class="warm-badge warm-badge-{pos.status === 'archived' ? 'archived' : pos.status === 'closed' ? 'closed' : 'active'}">
							{pos.status === 'archived' ? 'Archived' : pos.status === 'closed' ? 'Closed' : 'Active'}
						</span>
					</div>

					<!-- Stats -->
					<div class="warm-stats">
						<div>
							<div class="warm-stat-label">CVs</div>
							<div class="warm-stat-val serif">{pos.cv_count || 0}</div>
						</div>
						<div>
							<div class="warm-stat-label">Shortlist</div>
							<div class="warm-stat-val serif">{pos.shortlisted || 0}</div>
						</div>
						<div>
							<div class="warm-stat-label">Match</div>
							<div class="warm-stat-val serif warm-stat-accent">{matchPct !== null ? `${matchPct}%` : '—'}</div>
						</div>
					</div>

					<!-- Pipeline / health progress -->
					<div class="warm-progress-row">
						<div class="warm-progress-meta">
							<span>Pipeline progress</span>
							<strong class="warm-progress-status">{health}% {healthLabel(health)}</strong>
						</div>
						<div class="warm-progress-bar"><div class="warm-progress-fill" style="width: {Math.max(4, health)}%"></div></div>
					</div>

					<!-- Footer actions -->
					<div class="warm-card-foot">
						{#if pos.status === 'archived'}
							<button class="btn btn-primary btn-sm warm-foot-open"
								onclick={(e) => restorePosition(pos.slug, e)} title="Restore to active">
								↻ Restore
							</button>
							<button class="btn btn-sm btn-danger warm-icon-btn" onclick={(e) => askDeletePosition(e, pos)} title="Permanently delete (cannot undo)" aria-label="Delete forever"><X size={14} stroke-width={1.75} /></button>
						{:else}
							<span class="btn btn-primary btn-sm warm-foot-open">Open</span>
							{#if pos.status === 'active'}
								<button class="btn btn-sm warm-icon-btn" onclick={(e) => archivePosition(e, pos.slug)} title="Archive (recoverable)" aria-label="Archive"><Package size={14} stroke-width={1.75} /></button>
							{/if}
							<button class="btn btn-sm btn-danger warm-icon-btn" onclick={(e) => askDeletePosition(e, pos)} title="Permanently delete" aria-label="Delete"><X size={14} stroke-width={1.75} /></button>
						{/if}
					</div>
				</a>
			{/each}
		</div>
	{/if}
</div>

<!-- Floating bulk action bar (Positions) -->
{#if posSelectedSlugs.size > 0}
	<div class="bulk-bar">
		<span class="bulk-bar-count">{posSelectedSlugs.size} selected</span>
		{#if statusFilter === 'archived'}
			<button class="bulk-bar-pill" onclick={posBulkRestore}>↻ Restore selected</button>
		{:else}
			<button class="bulk-bar-pill" onclick={posBulkArchive}>Archive selected</button>
			<button class="bulk-bar-pill" onclick={posBulkClose}>Close selected</button>
		{/if}
		<button class="bulk-bar-pill" onclick={posBulkExport}>Export selected</button>
		<button class="bulk-bar-pill bulk-bar-pill-danger" onclick={() => posBulkConfirmAction = 'delete'}>Delete selected</button>
		<button class="bulk-bar-clear" onclick={posClearSelection} title="Clear selection">×</button>
	</div>
{/if}

<!-- Bulk delete confirm modal -->
{#if posBulkConfirmAction === 'delete'}
	<div class="bulk-modal-backdrop" onclick={(e) => { if (e.target === e.currentTarget) posBulkConfirmAction = null; }}>
		<div class="bulk-modal">
			<div class="bulk-modal-head">Delete {posSelectedSlugs.size} position{posSelectedSlugs.size === 1 ? '' : 's'}?</div>
			<div class="bulk-modal-body">This cannot be undone.</div>
			<div class="bulk-modal-foot">
				<button class="bulk-modal-btn" onclick={() => posBulkConfirmAction = null}>Cancel</button>
				<button class="bulk-modal-btn bulk-modal-btn-danger" onclick={posBulkDelete}>Delete</button>
			</div>
		</div>
	</div>
{/if}

<!-- ═══ POSITION HARD-DELETE CONFIRM MODAL (warm restyle) ═══ -->
{#if posDeleteTarget}
	{@const _pt = (posDeleteTarget?.title || '').trim().toLowerCase()}
	{@const _pv = posDeleteConfirmText.trim().toLowerCase()}
	{@const _ok = _pv.length > 0 && (_pv === _pt || _pv === 'delete')}
	<div class="warm-modal-backdrop" style="z-index: 200;"
		onclick={(e) => { if (e.target === e.currentTarget && !posDeleting) { posDeleteTarget = null; posDeleteConfirmText = ''; } }}>
		<div class="warm-modal animate-fade-up" style="width: 520px; max-width: 95vw;">
			<div class="warm-modal-head warm-modal-head-danger">
				<span class="serif" style="font-size: 16px;">Permanent delete — position</span>
				<button class="warm-modal-close" style="color: #fff;" disabled={posDeleting} onclick={() => { posDeleteTarget = null; posDeleteConfirmText = ''; }}>✕</button>
			</div>
			<div style="padding: 22px; display: flex; flex-direction: column; gap: 14px;">
				<p style="font-size: 13.5px; line-height: 1.55; margin: 0;">You are about to <strong style="color: var(--color-error, #a83232);">permanently delete</strong> the position:</p>
				<div class="warm-info" style="background: var(--color-surface-warm, #f4f3ee); border-left-color: var(--color-error, #a83232);">
					<span class="serif" style="font-size: 16px;">{posDeleteTarget.title}</span>
				</div>
				<p style="font-size: 12.5px; color: var(--color-on-surface-dim); line-height: 1.55; margin: 0;">
					This cannot be undone. Candidates, scorecards, evaluations, JD link — all references removed. Only the creator or a superadmin may proceed.
				</p>
				<div>
					<label class="warm-label">Type position name <strong style="color: var(--color-error, #a83232);">{posDeleteTarget?.title}</strong> or word DELETE to confirm</label>
					<input type="text" bind:value={posDeleteConfirmText} placeholder={posDeleteTarget?.title || 'DELETE'} class="warm-input warm-input-error" />
				</div>
				<div style="display: flex; gap: 8px; justify-content: flex-end; padding-top: 4px;">
					<button class="btn" disabled={posDeleting} onclick={() => { posDeleteTarget = null; posDeleteConfirmText = ''; }}>Cancel</button>
					<button class="btn btn-danger-solid" onclick={confirmDeletePosition} disabled={posDeleting || !_ok}>
						{posDeleting ? 'Deleting…' : 'Permanently delete'}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

<style>
	/* ── Page shell ── */
	.pulse-page {
		max-width: 1280px;
		margin: 0 auto;
		padding: 40px 32px 80px;
		height: 100%;
		overflow-y: auto;
	}

	/* ── Page head ── */
	.page-head {
		margin-bottom: 32px;
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 18px;
	}
	.page-title {
		font-size: 26px;
		font-weight: 500;
		margin: 0;
		font-family: 'Tiempos Headline', 'Charter', 'Source Serif Pro', Georgia, serif;
		letter-spacing: -0.025em;
		line-height: 1.15;
		color: var(--color-on-surface, #2c2c2c);
	}
	.page-sub {
		font-size: 14px;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-top: 8px;
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.live-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--color-primary, #c96342);
		box-shadow: 0 0 0 3px var(--color-primary-container, #faf2ed);
		animation: warm-pulse 2s ease-in-out infinite;
	}
	@keyframes warm-pulse {
		0%, 100% { box-shadow: 0 0 0 3px var(--color-primary-container, #faf2ed); }
		50% { box-shadow: 0 0 0 5px var(--color-primary-container, #faf2ed); }
	}
	.actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

	/* ── Segmented control ── */
	.seg {
		display: inline-flex;
		padding: 3px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-pill, 999px);
		gap: 0;
	}
	.seg-item {
		padding: 5px 14px;
		border-radius: var(--radius-pill, 999px);
		font-size: 12.5px;
		color: var(--color-on-surface-dim, #6f6e69);
		cursor: pointer;
		font-weight: 500;
		font-family: inherit;
		background: transparent;
		border: none;
		transition: background .15s, color .15s;
	}
	.seg-item:hover { color: var(--color-on-surface, #2c2c2c); }
	.seg-item.on {
		background: var(--color-surface, #fff);
		color: var(--color-on-surface, #2c2c2c);
		box-shadow: 0 1px 2px rgba(0,0,0,0.03);
	}

	/* ── Buttons ── */
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		border-radius: var(--radius-pill, 999px);
		background: var(--color-surface, #fff);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border-strong, #d8d5cb);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
		transition: background .15s, transform .1s, border-color .15s;
		text-decoration: none;
		line-height: 1.2;
	}
	.btn:hover:not(:disabled) { background: var(--color-surface-warm, #f4f3ee); }
	.btn:active:not(:disabled) { transform: scale(0.98); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn-primary {
		background: var(--color-primary, #c96342);
		color: #fff;
		border-color: var(--color-primary, #c96342);
	}
	.btn-primary:hover:not(:disabled) {
		background: var(--color-primary-strong, #b04f30);
		border-color: var(--color-primary-strong, #b04f30);
	}
	.btn-ghost { background: transparent; border-color: transparent; }
	.btn-ghost:hover:not(:disabled) { background: var(--color-surface-warm, #f4f3ee); }
	.btn-sm { padding: 7px 14px; font-size: 12.5px; }
	.btn-danger {
		color: var(--color-error, #a83232);
		background: transparent;
		border-color: var(--color-border-strong, #d8d5cb);
	}
	.btn-danger:hover:not(:disabled) {
		background: var(--color-error-soft, #f5dada);
		border-color: #f0c2c2;
	}
	.btn-danger-solid {
		background: var(--color-error, #a83232);
		color: #fff;
		border-color: var(--color-error, #a83232);
		padding: 8px 18px;
	}
	.btn-danger-solid:hover:not(:disabled) { background: #8e2828; border-color: #8e2828; }

	/* ── Position search bar ── */
	.pos-search-wrap {
		position: relative;
		display: flex; align-items: center;
		min-width: 280px;
	}
	.pos-search-icon {
		position: absolute; left: 10px;
		font-size: 16px; color: var(--color-on-surface-dim, #6f6e69);
		pointer-events: none;
	}
	.pos-search {
		width: 100%; padding: 8px 32px 8px 32px;
		font-size: 13px; font-family: inherit;
		background: var(--color-surface, #fff); color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc); border-radius: 8px;
		outline: none; transition: border-color 120ms;
	}
	.pos-search::placeholder { color: var(--color-on-surface-dim, #9c9b95); }
	.pos-search:focus {
		border-color: var(--color-accent, #c96342);
		box-shadow: 0 0 0 2px rgba(201, 99, 66, 0.12);
	}
	.pos-search-clear {
		position: absolute; right: 6px;
		width: 22px; height: 22px; border-radius: 50%;
		background: transparent; border: none;
		color: var(--color-on-surface-dim, #6f6e69);
		font-size: 18px; line-height: 1; cursor: pointer;
	}
	.pos-search-clear:hover { background: rgba(0,0,0,0.06); color: var(--color-accent, #c96342); }
	@media (max-width: 720px) {
		.pos-search-wrap { min-width: 0; flex: 1; }
	}

	/* ── Card grid — fixed 3-col on desktop ── */
	.warm-grid {
		display: grid;
		gap: 16px;
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}
	@media (max-width: 1100px) {
		.warm-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
	}
	@media (max-width: 720px) {
		.warm-grid { grid-template-columns: 1fr; gap: 10px; }
	}

	.warm-card {
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-md, 12px);
		padding: 16px;
		cursor: pointer;
		transition: border-color .2s, box-shadow .2s, transform .15s;
		position: relative;
	}
	.warm-card:hover {
		border-color: var(--color-border-strong, #d8d5cb);
		box-shadow: 0 4px 12px rgba(0,0,0,0.05);
		transform: translateY(-1px);
	}

	.warm-card-head { display: flex; align-items: flex-start; gap: 12px; }
	.warm-card-icon {
		width: 32px;
		height: 32px;
		border-radius: 9px;
		background: var(--color-primary-container, #faf2ed);
		color: var(--color-primary, #c96342);
		display: grid;
		place-items: center;
		font-size: 15px;
		flex-shrink: 0;
		border: 1px solid var(--color-primary-soft, #fdebe1);
	}
	.warm-card-title {
		font-size: 15px;
		font-weight: 500;
		line-height: 1.3;
		color: var(--color-on-surface, #2c2c2c);
		letter-spacing: -0.015em;
		font-family: 'Tiempos Headline', 'Charter', 'Source Serif Pro', Georgia, serif;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.warm-card-meta {
		font-size: 12px;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-top: 4px;
	}

	.warm-badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 10px;
		border-radius: var(--radius-pill, 999px);
		font-size: 11.5px;
		font-weight: 500;
		flex-shrink: 0;
	}
	.warm-badge::before {
		content: '';
		width: 5px;
		height: 5px;
		border-radius: 50%;
	}
	.warm-badge-active {
		background: var(--color-success-soft, #d8e4dd);
		color: var(--color-success, #2d6a4f);
	}
	.warm-badge-active::before { background: var(--color-success, #2d6a4f); }
	.warm-badge-closed {
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.warm-badge-closed::before { background: var(--color-on-surface-dim, #97968f); }
	.warm-badge-archived {
		background: rgba(125, 124, 117, 0.12);
		color: var(--color-on-surface-dim, #6f6e69);
		font-style: italic;
	}
	.warm-badge-archived::before { background: var(--color-on-surface-dim, #97968f); }

	.warm-stats {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 12px;
		padding: 12px 0;
		border-top: 1px solid var(--color-border-soft, #efeee6);
		border-bottom: 1px solid var(--color-border-soft, #efeee6);
	}
	.warm-stat-label {
		font-size: 10px;
		color: var(--color-on-surface-dim, #6f6e69);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		font-weight: 600;
	}
	.warm-stat-val {
		font-size: 20px;
		font-weight: 500;
		margin-top: 4px;
		letter-spacing: -0.025em;
		line-height: 1.1;
		color: var(--color-on-surface, #2c2c2c);
	}
	.warm-stat-accent { color: var(--color-primary, #c96342); }

	.warm-progress-row { display: flex; flex-direction: column; gap: 7px; }
	.warm-progress-meta {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		font-size: 12.5px;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.warm-progress-status { color: var(--color-warning, #a06000); font-weight: 600; }
	.warm-progress-bar {
		height: 4px;
		border-radius: 999px;
		background: var(--color-surface-warm, #f4f3ee);
		overflow: hidden;
	}
	.warm-progress-fill {
		height: 100%;
		border-radius: 999px;
		background: linear-gradient(90deg, var(--color-warning, #a06000) 0%, #d97706 100%);
		transition: width .3s ease;
	}

	.warm-card-foot { display: flex; gap: 4px; align-items: center; }
	.warm-foot-open { flex: 1; justify-content: center; }
	.warm-card-foot .btn { padding: 5px 10px; font-size: 11px; }
	.warm-icon-btn {
		padding: 5px 8px !important;
		min-width: 28px;
		justify-content: center;
		font-size: 12px !important;
		line-height: 1;
	}

	/* ── Empty state ── */
	.warm-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 80px 20px;
		background: var(--color-surface, #fff);
		border: 1px dashed var(--color-border-strong, #d8d5cb);
		border-radius: var(--radius-md, 12px);
	}

	/* ── Modal (warm) ── */
	.warm-modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(44, 44, 44, 0.45);
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 20px;
		backdrop-filter: blur(2px);
	}
	.warm-modal {
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-md, 12px);
		box-shadow: 0 20px 60px rgba(0,0,0,0.18);
		overflow: hidden;
	}
	.warm-modal-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 22px;
		border-bottom: 1px solid var(--color-border-soft, #efeee6);
		background: var(--color-surface, #fff);
	}
	.warm-modal-head-danger {
		background: var(--color-error, #a83232);
		color: #fff;
		border-bottom: none;
	}
	.warm-modal-close {
		background: none;
		border: none;
		font-size: 16px;
		cursor: pointer;
		color: var(--color-on-surface-dim, #6f6e69);
		padding: 4px 8px;
		border-radius: 6px;
	}
	.warm-modal-close:hover:not(:disabled) { background: rgba(0,0,0,0.05); }

	.warm-label {
		display: block;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-bottom: 6px;
	}
	.warm-input {
		width: 100%;
		padding: 10px 14px;
		border: 1px solid var(--color-border-strong, #d8d5cb);
		border-radius: var(--radius-sm, 8px);
		font-family: inherit;
		font-size: 14px;
		background: var(--color-surface, #fff);
		color: var(--color-on-surface, #2c2c2c);
		transition: border-color .15s, box-shadow .15s;
	}
	.warm-input:focus {
		outline: none;
		border-color: var(--color-primary, #c96342);
		box-shadow: 0 0 0 3px var(--color-primary-container, #faf2ed);
	}
	.warm-input-error { border-color: var(--color-error, #a83232); }
	.warm-input-error:focus { box-shadow: 0 0 0 3px var(--color-error-soft, #f5dada); }
	.warm-input-warn { border-color: var(--color-warning, #a06000); }

	.warm-hint {
		font-size: 11.5px;
		margin-top: 4px;
	}
	.warm-hint-error { color: var(--color-error, #a83232); }
	.warm-hint-warn { color: var(--color-warning, #a06000); }

	.warm-info {
		background: var(--color-primary-container, #faf2ed);
		padding: 12px 14px;
		border-left: 3px solid var(--color-primary, #c96342);
		border-radius: var(--radius-sm, 8px);
	}

	.warm-template-list {
		max-height: 180px;
		overflow-y: auto;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-sm, 8px);
	}
	.warm-template-item {
		display: block;
		width: 100%;
		text-align: left;
		padding: 10px 14px;
		border: none;
		border-bottom: 1px solid var(--color-border-soft, #efeee6);
		background: var(--color-surface, #fff);
		color: var(--color-on-surface, #2c2c2c);
		font-family: inherit;
		font-size: 13px;
		cursor: pointer;
		transition: background .12s;
	}
	.warm-template-item:last-child { border-bottom: none; }
	.warm-template-item:hover { background: var(--color-surface-warm, #f4f3ee); }
	.warm-template-item.on {
		background: var(--color-primary-container, #faf2ed);
		color: var(--color-primary-strong, #b04f30);
	}

	/* Card checkbox + selected state — SVG-tick approach */
	.warm-card-check {
		position: absolute; top: 12px; left: 12px;
		width: 24px; height: 24px;
		appearance: none; -webkit-appearance: none; -moz-appearance: none;
		background-color: #fff;
		border: 2px solid var(--color-border, #d8d5cc);
		border-radius: 6px;
		opacity: 0;
		transition: opacity .15s, background-color .12s, border-color .12s;
		z-index: 4;
		cursor: pointer;
		background-repeat: no-repeat;
		background-position: 50% 50%;
		background-size: 18px 18px;
		margin: 0; padding: 0;
		box-sizing: border-box;
	}
	.warm-card:hover .warm-card-check,
	.warm-card-check:checked,
	.warm-card-selected .warm-card-check { opacity: 1; }
	.warm-card-check:checked,
	.warm-card-selected .warm-card-check {
		background-color: #fff;
		border-color: var(--color-accent, #c96342);
		border-width: 2px;
		background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23c96342' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'/></svg>");
	}
	.warm-card-selected {
		outline: 2px solid var(--color-accent, #c96342);
		outline-offset: -2px;
	}

	/* Floating bulk action bar */
	.bulk-bar {
		position: fixed; left: 50%; bottom: 24px;
		transform: translateX(-50%);
		display: flex; align-items: center; gap: 10px;
		background: #fff;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		box-shadow: 0 12px 32px rgba(0,0,0,0.12);
		padding: 10px 14px;
		z-index: 100;
	}
	.bulk-bar-count {
		font-size: 12.5px; font-weight: 600;
		color: var(--color-on-surface, #2c2c2c);
		padding-right: 6px;
		border-right: 1px solid var(--color-border, #e8e6dd);
		margin-right: 4px;
	}
	.bulk-bar-pill {
		padding: 6px 14px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px;
		font-size: 12.5px; font-weight: 500;
		font-family: inherit; cursor: pointer;
		color: var(--color-on-surface, #2c2c2c);
		transition: background .15s, color .15s;
	}
	.bulk-bar-pill:hover {
		background: var(--color-primary-container, #faf2ed);
		border-color: var(--color-primary, #c96342);
	}
	.bulk-bar-pill-danger { color: var(--color-error, #a83232); }
	.bulk-bar-pill-danger:hover {
		background: var(--color-error-container, #f5dada);
		border-color: var(--color-error, #a83232);
	}
	.bulk-bar-clear {
		width: 26px; height: 26px;
		display: inline-flex; align-items: center; justify-content: center;
		border: none; background: transparent;
		font-size: 18px; line-height: 1; cursor: pointer;
		color: var(--color-on-surface-dim, #6f6e69);
		border-radius: 50%;
	}
	.bulk-bar-clear:hover { background: var(--color-surface-warm, #f4f3ee); color: var(--color-on-surface, #2c2c2c); }

	.bulk-modal-backdrop {
		position: fixed; inset: 0; z-index: 200;
		background: rgba(0,0,0,0.4);
		display: flex; align-items: center; justify-content: center;
	}
	.bulk-modal {
		background: #fff; border-radius: 12px;
		width: 420px; max-width: 92vw;
		box-shadow: 0 24px 48px rgba(0,0,0,0.2);
		overflow: hidden;
	}
	.bulk-modal-head {
		padding: 18px 22px 8px;
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 18px; font-weight: 500;
		color: var(--color-on-surface, #2c2c2c);
	}
	.bulk-modal-body {
		padding: 4px 22px 18px;
		font-size: 13.5px; color: var(--color-on-surface-dim, #6f6e69);
	}
	.bulk-modal-foot {
		display: flex; justify-content: flex-end; gap: 8px;
		padding: 12px 22px 18px;
	}
	.bulk-modal-btn {
		padding: 8px 18px; border-radius: 8px;
		font-size: 13px; font-weight: 500; font-family: inherit;
		border: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
	}
	.bulk-modal-btn:hover { background: var(--color-surface, #fff); }
	.bulk-modal-btn-danger {
		background: var(--color-error, #a83232); color: #fff; border-color: var(--color-error, #a83232);
	}
	.bulk-modal-btn-danger:hover { background: #8e2828; }
</style>
