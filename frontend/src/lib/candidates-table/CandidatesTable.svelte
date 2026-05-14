<script>
	import { untrack } from 'svelte';
	import { apiJson, api } from '$lib/api';
	import { hoverPreview } from '$lib/HoverPreview.svelte';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import User from '@lucide/svelte/icons/user';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import Plus from '@lucide/svelte/icons/plus';
	import Star from '@lucide/svelte/icons/star';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Layers from '@lucide/svelte/icons/layers';
	import Award from '@lucide/svelte/icons/award';
	import CheckCircle from '@lucide/svelte/icons/check-circle';

	let { slug, position = null, candidates = [], aiSuggestions = [], onReload = () => {}, onOpenDrawer = () => {} } = $props();

	const AI_SOURCES = ['ai_promoted','auto_scan_on_create','auto_scan_on_jd_update','auto_scan_rescan'];
	const AI_ADDED_BY = ['ai_scan','auto_match','ai_auto','ai_auto_scan'];
	const POOL_ADDED_BY = ['pool_pick','manual_pool','talent_pool'];
	const UPLOAD_ADDED_BY = ['position_upload','manual_upload','direct_upload'];

	function isAi(c) {
		return c.auto_added
			|| AI_SOURCES.includes(c.match_source)
			|| AI_ADDED_BY.includes(c.added_by);
	}

	// Distinguish source: AI vs POOL (manual pick from talent pool) vs UPL (direct upload to position)
	function srcKind(c) {
		if (isAi(c)) return 'ai';
		const ab = c.added_by || '';
		if (POOL_ADDED_BY.includes(ab)) return 'pool';
		if (UPLOAD_ADDED_BY.includes(ab)) return 'upl';
		return 'man';
	}
	function srcMeta(c) {
		const k = srcKind(c);
		return {
			ai:   { label: '✦ AI',          color: '#c96342', bg: 'rgba(201,99,66,0.10)', tip: 'Auto-matched by AI Scan Agent' },
			pool: { label: '▮ POOL',        color: '#6f57bd', bg: 'rgba(111,87,189,0.10)', tip: 'Picked from Talent Pool' },
			upl:  { label: '↑ UPLOAD',      color: '#3a7bbf', bg: 'rgba(58,123,191,0.10)', tip: 'Uploaded directly to position' },
			man:  { label: '👤 MANUAL',     color: '#6f6e69', bg: 'rgba(111,110,105,0.10)', tip: 'Manually attached' },
		}[k];
	}
	function addedByLabel(c) {
		// Show who attached: prefer user display_name fields if backend joins them, else added_by string
		return c.added_by_name || c.added_by || 'system';
	}

	let activeTab = $state('all');
	let selected = $state(new Set());
	let expanded = $state(new Set());
	let sortKey = $state('score');
	let sortDir = $state('desc');
	let pendingRowAction = $state({});

	// ── stage classifiers — pipeline-aligned (UPLOADED · SCREENED · SHORTLISTED · OFFERED · HIRED · REJECTED) ──
	const SHORT_STAGES = ['shortlisted','screened','offered','hired'];
	function isRejected(c) { return c.stage === 'rejected' || c.dismissed; }
	function isStage(c, s) { return !isRejected(c) && (c.stage || 'uploaded') === s; }
	function isShortlistedAny(c) { return !isRejected(c) && SHORT_STAGES.includes(c.stage); }
	function isInbox(c) { return !isRejected(c) && (!c.stage || c.stage === 'uploaded'); }
	function isAiInbox(c) { return isInbox(c) && isAi(c); }
	function isUploadedInbox(c) { return isInbox(c) && !isAi(c); }

	// ── derived counts ──
	let countAll = $derived(candidates.length);
	let countAI = $derived((aiSuggestions || []).length);
	let countUploaded = $derived(candidates.filter(isUploadedInbox).length);
	let countScreened = $derived(candidates.filter(c => isStage(c, 'screened')).length);
	let countShortlisted = $derived(candidates.filter(c => isStage(c, 'shortlisted')).length);
	let countOffered = $derived(candidates.filter(c => isStage(c, 'offered')).length);
	let countHired = $derived(candidates.filter(c => isStage(c, 'hired')).length);
	let countRej = $derived(candidates.filter(isRejected).length);

	// ── filter by tab ──
	// AI tab uses separate `aiSuggestions` array (state='suggested', from /ai endpoint)
	// All other tabs filter the `candidates` array (state='attached')
	let filtered = $derived.by(() => {
		let base;
		if (activeTab === 'ai') base = aiSuggestions || [];
		else if (activeTab === 'uploaded') base = candidates.filter(isUploadedInbox);
		else if (activeTab === 'screened') base = candidates.filter(c => isStage(c, 'screened'));
		else if (activeTab === 'shortlisted') base = candidates.filter(c => isStage(c, 'shortlisted'));
		else if (activeTab === 'offered') base = candidates.filter(c => isStage(c, 'offered'));
		else if (activeTab === 'hired') base = candidates.filter(c => isStage(c, 'hired'));
		else if (activeTab === 'rejected') base = candidates.filter(isRejected);
		else base = candidates;

		const dir = sortDir === 'asc' ? 1 : -1;
		const arr = base.slice();
		arr.sort((a, b) => {
			let va, vb;
			if (sortKey === 'score') { va = Number(a.match_score_composite || 0); vb = Number(b.match_score_composite || 0); }
			else if (sortKey === 'name') { va = (a.name || '').toLowerCase(); vb = (b.name || '').toLowerCase(); }
			else if (sortKey === 'exp') { va = Number(a.total_experience_years || a.years_experience || 0); vb = Number(b.total_experience_years || b.years_experience || 0); }
			else if (sortKey === 'stage') { va = a.stage || ''; vb = b.stage || ''; }
			else va = vb = 0;
			if (va < vb) return -1 * dir;
			if (va > vb) return 1 * dir;
			return 0;
		});
		return arr;
	});

	function toggleSort(key) {
		if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else { sortKey = key; sortDir = 'desc'; }
	}

	function toggleSelect(cid) {
		const next = new Set(selected);
		if (next.has(cid)) next.delete(cid); else next.add(cid);
		selected = next;
	}

	function toggleSelectAll() {
		const visIds = filtered.map(c => c.candidate_id || c.id);
		const allSel = visIds.length > 0 && visIds.every(id => selected.has(id));
		const next = new Set(selected);
		if (allSel) visIds.forEach(id => next.delete(id));
		else visIds.forEach(id => next.add(id));
		selected = next;
	}

	function clearSelection() { selected = new Set(); }

	// ── j/k row navigation ──
	let focusedIdx = $state(-1);
	let tableRoot = $state(null);

	function focusRow(idx) {
		if (!tableRoot) return;
		const rows = tableRoot.querySelectorAll('[data-row-idx]');
		if (!rows.length) return;
		const clamped = Math.max(0, Math.min(rows.length - 1, idx));
		focusedIdx = clamped;
		const el = rows[clamped];
		el?.focus();
		el?.scrollIntoView({ block: 'nearest' });
	}

	function isTypingTarget(el) {
		if (!el) return false;
		const tag = el.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
	}

	function onTableKey(e) {
		if (isTypingTarget(e.target)) return;
		if (!filtered.length) return;
		if (e.key === 'j') {
			e.preventDefault();
			focusRow((focusedIdx < 0 ? 0 : focusedIdx + 1));
		} else if (e.key === 'k') {
			e.preventDefault();
			focusRow((focusedIdx < 0 ? 0 : focusedIdx - 1));
		} else if (e.key === 'Enter' && focusedIdx >= 0) {
			const c = filtered[focusedIdx];
			if (c) {
				e.preventDefault();
				const cid = c.candidate_id || c.id;
				onOpenDrawer(cid, c);
			}
		} else if ((e.key === 'x' || e.key === 'X') && focusedIdx >= 0) {
			const c = filtered[focusedIdx];
			if (c) {
				e.preventDefault();
				reject(c);
			}
		}
	}

	function toggleExpand(cid) {
		const next = new Set(expanded);
		if (next.has(cid)) next.delete(cid); else next.add(cid);
		expanded = next;
	}

	function scoreColor(s) {
		const min = Number(position?.min_match_score ?? 50);
		if (!s && s !== 0) return '#9c9c8f';
		if (s >= 70) return '#3a8a4f';
		if (s >= 40) return '#a06000';
		return '#a83232';
	}

	function stageStyle(stage) {
		const map = {
			uploaded:    { color: '#9c9c8f', bg: '#f3f2ec' },
			screened:    { color: '#3a7bbf', bg: '#eaf2fa' },
			shortlisted: { color: '#6f57bd', bg: '#f0ecf8' },
			offered:     { color: '#c96342', bg: '#f8e8e1' },
			hired:       { color: '#3a8a4f', bg: '#e6f1e9' },
			rejected:    { color: '#c4571a', bg: '#faecdf' },
		};
		return map[stage] || map.uploaded;
	}

	function srcLabel(c) { return isAi(c) ? 'AI' : 'MAN'; }
	function isAiSrc(c) { return isAi(c); }
	function stageLabel(s) {
		const map = { uploaded: 'UPL', screened: 'SCR', shortlisted: 'SHO', offered: 'OFF', hired: 'HIR', rejected: 'REJ' };
		return map[s] || (s || 'UPL').toUpperCase().slice(0,3);
	}

	// ── row actions ──
	async function promote(c) {
		const cid = c.candidate_id || c.id;
		if (pendingRowAction[cid]) return;
		pendingRowAction = { ...pendingRowAction, [cid]: 'add' };
		try {
			await apiJson(`/positions/${slug}/ai/${cid}/promote`, { method: 'POST' });
			await onReload();
		} catch (e) {
			alert(e?.message || 'Promote failed');
		} finally {
			const n = { ...pendingRowAction }; delete n[cid]; pendingRowAction = n;
		}
	}

	async function reject(c) {
		const cid = c.candidate_id || c.id;
		if (pendingRowAction[cid]) return;
		pendingRowAction = { ...pendingRowAction, [cid]: 'reject' };
		try {
			await apiJson(`/positions/${slug}/ai/${cid}/reject`, { method: 'POST' });
			await onReload();
		} catch (e) {
			alert(e?.message || 'Reject failed');
		} finally {
			const n = { ...pendingRowAction }; delete n[cid]; pendingRowAction = n;
		}
	}

	async function setStage(c, newStage) {
		const cid = c.candidate_id || c.id;
		if (!position?.id || !newStage || newStage === (c.stage || 'uploaded')) return;
		if (pendingRowAction[cid]) return;
		pendingRowAction = { ...pendingRowAction, [cid]: 'stage' };
		try {
			if (newStage === 'rejected') {
				await apiJson(`/positions/${slug}/ai/${cid}/reject`, { method: 'POST' });
			} else {
				await apiJson('/bulk/move-stage', {
					method: 'POST',
					body: JSON.stringify({
						candidate_ids: [cid],
						position_id: position.id,
						new_stage: newStage,
					})
				});
			}
			showToast('success', `Moved to ${newStage.toUpperCase()}`);
			await onReload();
		} catch (e) {
			showToast('error', e?.message || 'Stage change failed');
		} finally {
			const n = { ...pendingRowAction }; delete n[cid]; pendingRowAction = n;
		}
	}

	// ── bulk actions ──
	let bulkBusy = $state(false);
	async function bulkShortlist() {
		if (!selected.size || !position?.id) return;
		const n = selected.size;
		bulkBusy = true;
		try {
			await apiJson('/bulk/move-stage', {
				method: 'POST',
				body: JSON.stringify({
					candidate_ids: Array.from(selected),
					position_id: position.id,
					new_stage: 'shortlisted'
				})
			});
			clearSelection();
			await onReload();
			showToast('success', `Shortlisted ${n} candidate(s)`);
		} catch (e) { showToast('error', e?.message || 'Bulk shortlist failed'); }
		bulkBusy = false;
	}

	async function bulkReject() {
		if (!selected.size || !position?.id) return;
		if (!confirm(`Reject ${selected.size} candidate(s)?`)) return;
		const n = selected.size;
		bulkBusy = true;
		try {
			await apiJson('/bulk/reject', {
				method: 'POST',
				body: JSON.stringify({
					candidate_ids: Array.from(selected),
					position_id: position.id,
					rejection_reason: ''
				})
			});
			clearSelection();
			await onReload();
			showToast('success', `Rejected ${n} candidate(s)`);
		} catch (e) { showToast('error', e?.message || 'Bulk reject failed'); }
		bulkBusy = false;
	}

	function bulkOpenKit() {
		if (typeof window !== 'undefined') {
			window.dispatchEvent(new CustomEvent('open-interview-kit-tab', {
				detail: { slug, candidate_ids: Array.from(selected) }
			}));
		}
	}

	// Talent Pool tab removed — accessed via [▮ ATTACH FROM TALENT POOL] button at top-right
	// (opens dedicated browse modal). Inline tab was redundant + auto-loaded unwanted.
	// Tab order mirrors PIPELINE kanban columns so candidates flow l→r between views.
	const TABS = [
		{ id: 'all',         label: 'ALL',          countKey: 'all',  icon: null },
		{ id: 'ai',          label: 'AI',           countKey: 'ai',   icon: Sparkles },
		{ id: 'uploaded',    label: 'UPLOADED',     countKey: 'up',   icon: ArrowUp },
		{ id: 'screened',    label: 'SCREENED',     countKey: 'scr',  icon: Layers },
		{ id: 'shortlisted', label: 'SHORTLISTED',  countKey: 'sh',   icon: Star },
		{ id: 'offered',     label: 'OFFERED',      countKey: 'off',  icon: Award },
		{ id: 'hired',       label: 'HIRED',        countKey: 'hir',  icon: CheckCircle },
		{ id: 'rejected',    label: 'REJECTED',     countKey: 'rj',   icon: X },
	];

	// ── POOL state ──
	let poolItems = $state([]);
	let poolLoading = $state(false);
	let poolSearch = $state('');
	let poolScope = $state('all'); // all | mine
	let poolSelected = $state(new Set());
	let poolAttaching = $state(false);

	let attachedIds = $derived(new Set(candidates.map(c => c.candidate_id || c.id)));

	let poolSearched = $derived.by(() => {
		const q = poolSearch.trim().toLowerCase();
		return poolItems.filter(p => {
			if (!q) return true;
			return (p.name || '').toLowerCase().includes(q)
				|| (p.current_role || '').toLowerCase().includes(q)
				|| (p.email || '').toLowerCase().includes(q)
				|| (Array.isArray(p.skills_technical) && p.skills_technical.some(s => String(s).toLowerCase().includes(q)));
		});
	});

	// Hide attached CVs from pool list — strict no-dupe across tabs
	let poolFiltered = $derived(poolSearched.filter(p => !attachedIds.has(p.id)));
	let poolAvailable = $derived(poolFiltered.length);
	let poolAttachedCount = $derived(poolSearched.filter(p => attachedIds.has(p.id)).length);

	async function loadPool() {
		poolLoading = true;
		try {
			const params = new URLSearchParams({ scope: poolScope, limit: '100' });
			if (poolSearch) params.set('search', poolSearch);
			const data = await apiJson(`/candidates/?${params}`);
			poolItems = data.candidates || [];
		} catch (e) {
			poolItems = [];
		}
		poolLoading = false;
	}

	function poolToggle(cid) {
		const next = new Set(poolSelected);
		if (next.has(cid)) next.delete(cid); else next.add(cid);
		poolSelected = next;
	}

	function poolToggleAll() {
		const visIds = poolFiltered.map(p => p.id);
		const allSel = visIds.length > 0 && visIds.every(id => poolSelected.has(id));
		const next = new Set(poolSelected);
		if (allSel) visIds.forEach(id => next.delete(id));
		else visIds.forEach(id => next.add(id));
		poolSelected = next;
	}

	let dupeModal = $state(null); // { added, skipped: [...] }
	let toast = $state(null); // { kind: 'success'|'error', text }
	let toastTimer = null;

	function showToast(kind, text) {
		toast = { kind, text };
		if (toastTimer) clearTimeout(toastTimer);
		toastTimer = setTimeout(() => { toast = null; }, 4500);
	}

	async function poolAttachIds(ids) {
		if (!ids || !ids.length) return;
		poolAttaching = true;
		try {
			const res = await apiJson(`/matching/scan/${slug}/add`, {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: ids, source: 'manual' })
			});
			poolSelected = new Set();
			if (res && Array.isArray(res.skipped) && res.skipped.length > 0) {
				dupeModal = res;
			} else if (res && res.added > 0) {
				const names = res.added === 1
					? (poolItems.find(p => ids.includes(p.id))?.name || 'Candidate')
					: `${res.added} candidates`;
				showToast('success', `Attached ${names} · score computing in background`);
			}
			await onReload();
			await loadPool();
		} catch (e) {
			showToast('error', e?.message || 'Attach failed');
		}
		poolAttaching = false;
	}

	async function poolAttachSelected() {
		await poolAttachIds(Array.from(poolSelected));
	}

	function closeDupeModal() { dupeModal = null; }

	let poolBrowsed = $state(false);
	function browseTalentPool() {
		poolBrowsed = true;
		loadPool();
	}

	function countFor(key) {
		switch (key) {
			case 'all': return countAll;
			case 'up': return countUploaded;
			case 'ai': return countAI;
			case 'scr': return countScreened;
			case 'sh': return countShortlisted;
			case 'off': return countOffered;
			case 'hir': return countHired;
			case 'rj': return countRej;
			case 'pool': return poolLoading ? '…' : (poolAvailable + ' new');
		}
		return 0;
	}

	const TAB_HELP = {
		all: {
			title: 'ALL CANDIDATES',
			desc: 'Every candidate attached to this position — AI-recommended, manually uploaded, attached from pool, shortlisted, rejected. Sortable + bulk-actionable.',
			how: 'Add more: [⬆ UPLOAD LOCAL] (top-right) for fresh CVs from your computer · [▮ ATTACH FROM TALENT POOL] to pick existing CVs from the central repo · [⟳ SCAN REPO] to re-run AI matching across the whole repo.'
		},
		uploaded: {
			title: 'MANUALLY UPLOADED CVS',
			desc: 'CVs you (or another recruiter) added directly via the UPLOAD LOCAL button. These bypass the AI auto-match — you decided to put them in this position.',
			how: 'Add more: click [⬆ UPLOAD LOCAL] at the top-right of the page → multi-select files (PDF/DOCX/TXT/PNG/JPG) → pipeline auto-runs → CVs land here within ~15s. Score is computed against this position\'s JD.'
		},
		ai: {
			title: 'AI RECOMMENDED MATCHES',
			desc: 'CVs the AI found in the central repo and auto-matched to this position\'s JD. Sources: position-create scan, JD-update scan, or manual rescan. Score = composite of skills/exp/edu/cert/ind/culture.',
			how: 'Refresh AI list: click [⟳ SCAN REPO] (top-right) → re-runs AI scan over the entire CV repo. Add a stronger match: [▮ ATTACH FROM TALENT POOL] lets you hand-pick from the repo even if AI didn\'t auto-flag them.'
		},
		screened: {
			title: 'SCREENED CANDIDATES',
			desc: 'Candidates that passed initial CV review. Recruiter has confirmed fit on paper — next step is a screening call or technical filter before formal shortlist.',
			how: 'Move a candidate here: change STAGE column dropdown → SCREENED, OR drag the card on the PIPELINE tab into the SCREENED column. Reverts via the same dropdown.'
		},
		shortlisted: {
			title: 'SHORTLISTED CANDIDATES',
			desc: 'Top-tier candidates being actively pursued. Typically moved here after a positive screening call — these are your prioritised interview pool.',
			how: 'Move a candidate here: change STAGE column dropdown → SHORTLISTED, OR multi-select rows → [SHORTLIST ALL] in the bulk toolbar. Mirrors the SHORTLISTED column on the PIPELINE tab.'
		},
		offered: {
			title: 'OFFERED CANDIDATES',
			desc: 'Candidates who have received a formal offer. Awaiting acceptance, negotiation, or rejection. Use Offer Templates in admin for consistent terms.',
			how: 'Move a candidate here: change STAGE column dropdown → OFFERED. Mirrors the OFFERED column on the PIPELINE tab.'
		},
		hired: {
			title: 'HIRED CANDIDATES',
			desc: 'Candidates who have signed and accepted the offer. Position closes automatically when this column is non-empty + has at least one HIRED.',
			how: 'Move a candidate here: change STAGE column dropdown → HIRED. Triggers hire celebration confetti.'
		},
		rejected: {
			title: 'REJECTED CANDIDATES',
			desc: 'Candidates marked rejected (or AI-matches you dismissed). They stay attached for audit + future re-consideration but are excluded from active pipeline.',
			how: 'Reject from anywhere: [REJECT] action on a row, OR multi-select → [REJECT ALL] in bulk toolbar. To un-reject, open candidate drawer and move them back via PIPELINE tab.'
		},
	};
</script>

<div class="ct-wrap">

	<!-- TAB STRIP -->
	<div class="ct-tabs">
		{#each TABS as t}
			<button
				class="ct-tab"
				class:ct-tab-active={activeTab === t.id}
				onclick={() => { activeTab = t.id; clearSelection(); expanded = new Set(); }}
				style="display: inline-flex; align-items: center; gap: 4px;">
				{#if t.icon}<svelte:component this={t.icon} size={11} strokeWidth={1.75} />{/if}
				{t.label} · {countFor(t.countKey)}
			</button>
		{/each}
	</div>

	<!-- TAB EXPLANATION BANNER -->
	{#if TAB_HELP[activeTab]}
		<div class="ink-border ct-help">
			<div class="ct-help-head">
				<span class="ct-help-title">▸ {TAB_HELP[activeTab].title}</span>
			</div>
			<div class="ct-help-body">
				<p class="ct-help-desc"><span class="ct-help-label">WHAT</span> {TAB_HELP[activeTab].desc}</p>
				<p class="ct-help-how"><span class="ct-help-label ct-help-label-green">HOW</span> {TAB_HELP[activeTab].how}</p>
			</div>
		</div>
	{/if}

	<!-- BULK TOOLBAR (sticky, appears on multi-select) -->
	{#if selected.size > 0}
		<div class="ink-border stamp-shadow ct-bulk-bar">
			<span class="ct-bulk-count" style="display: inline-flex; align-items: center; gap: 4px;">{selected.size} SELECTED</span>
			<button class="ct-bulk-btn ct-bulk-cta" disabled={bulkBusy} onclick={bulkShortlist} style="display: inline-flex; align-items: center; gap: 4px;">
				<Check size={11} strokeWidth={1.75} /> SHORTLIST ALL
			</button>
			<button class="ct-bulk-btn ct-bulk-danger" disabled={bulkBusy} onclick={bulkReject} style="display: inline-flex; align-items: center; gap: 4px;">
				<X size={11} strokeWidth={1.75} /> REJECT ALL
			</button>
			<button class="ct-bulk-btn" onclick={bulkOpenKit}>[ + INTERVIEW KIT ]</button>
			<button class="ct-bulk-btn ct-bulk-mute" onclick={clearSelection}>[ CLEAR ]</button>
		</div>
	{/if}

	<!-- TABLE -->
	<div class="ink-border ct-table" bind:this={tableRoot} onkeydown={onTableKey} role="grid" tabindex="-1">
		<div class="ct-thead">
			<div class="ct-cell ct-c-check">
				<input type="checkbox"
					checked={filtered.length > 0 && filtered.every(c => selected.has(c.candidate_id || c.id))}
					onchange={toggleSelectAll} />
			</div>
			<div class="ct-cell ct-c-rank">#</div>
			<button class="ct-cell ct-c-name ct-sort" onclick={() => toggleSort('name')}>
				NAME {sortKey === 'name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
			</button>
			<div class="ct-cell ct-c-role">ROLE</div>
			<button class="ct-cell ct-c-exp ct-sort" onclick={() => toggleSort('exp')}>
				EXP {sortKey === 'exp' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
			</button>
			<button class="ct-cell ct-c-score ct-sort" onclick={() => toggleSort('score')}>
				SCORE 0% ─────── 100% {sortKey === 'score' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
			</button>
			<div class="ct-cell ct-c-src">SRC</div>
			<div class="ct-cell ct-c-act">STAGE / ACTIONS</div>
		</div>

		{#if filtered.length === 0}
			<div class="ct-empty">
				NO CANDIDATES IN <strong>{TABS.find(t => t.id === activeTab)?.label}</strong>
			</div>
		{:else}
			{#each filtered as c, i (c.candidate_id || c.id)}
				{@const cid = c.candidate_id || c.id}
				{@const score = Number(c.match_score_composite || 0)}
				{@const yrs = Number(c.total_experience_years || c.years_experience || 0)}
				{@const role = c.current_role || c.role || 'N/A'}
				{@const isExp = expanded.has(cid)}
				{@const isSel = selected.has(cid)}
				<div class="ct-row" class:ct-row-sel={isSel} class:ct-row-focus={focusedIdx === i}
					data-row-idx={i} tabindex="0"
					onfocus={() => focusedIdx = i}>
					<!-- main row -->
					<div class="ct-cell ct-c-check">
						<input type="checkbox" checked={isSel} onclick={(e) => e.stopPropagation()}
							onchange={() => toggleSelect(cid)} />
					</div>
					<button class="ct-cell ct-c-rank ct-expand-btn" onclick={() => toggleExpand(cid)}
						title="expand details">
						{isExp ? '▾' : '▸'} {i + 1}
					</button>
					<button
						class="ct-cell ct-c-name ct-name-link"
						use:hoverPreview={{ id: cid, name: c.name, score: score }}
						onclick={() => onOpenDrawer(cid, c)}
					>
						{c.name || `Candidate ${cid}`}
					</button>
					<div class="ct-cell ct-c-role">{role}</div>
					<div class="ct-cell ct-c-exp">{yrs}yr</div>
					<div class="ct-cell ct-c-score">
						<div class="ct-score-bar">
							<div class="ct-score-fill" style="width: {Math.min(100, Math.max(0, score))}%; background: {scoreColor(score)};"></div>
						</div>
						<span class="ct-score-num" style="color: {scoreColor(score)};">{Math.round(score)}%</span>
					</div>
					<div class="ct-cell ct-c-src">
						<span class="ct-pill"
							style="display: inline-flex; align-items: center; gap: 3px; color: {srcMeta(c).color}; background: {srcMeta(c).bg}; border-color: {srcMeta(c).color}33;"
							title="{srcMeta(c).tip} · added by {addedByLabel(c)}">
							{srcMeta(c).label}
						</span>
					</div>
					<div class="ct-cell ct-c-act">
						{#if c.attachment_state === 'suggested'}
							<button class="ct-act ct-act-cta" disabled={!!pendingRowAction[cid]}
								title="Promote to pipeline"
								onclick={() => promote(c)} style="display: inline-flex; align-items: center; justify-content: center;">{pendingRowAction[cid] === 'add' ? '...' : '+'}</button>
							<button class="ct-act ct-act-danger" disabled={!!pendingRowAction[cid]}
								title="Dismiss suggestion"
								onclick={() => reject(c)} style="display: inline-flex; align-items: center; justify-content: center;">{#if pendingRowAction[cid] === 'reject'}...{:else}<X size={11} strokeWidth={1.75} />{/if}</button>
						{:else}
							{#key (c.stage || 'uploaded') + ':' + cid}
								<select class="ct-stage-select"
									disabled={!!pendingRowAction[cid]}
									title="Change stage"
									onclick={(e) => e.stopPropagation()}
									onchange={(e) => setStage(c, e.currentTarget.value)}
									style="color:{stageStyle(c.stage).color};background-color:{stageStyle(c.stage).bg};border-color:{stageStyle(c.stage).color}55;">
									<option value="uploaded" selected={(c.stage || 'uploaded') === 'uploaded'}>UPLOADED</option>
									<option value="screened" selected={c.stage === 'screened'}>SCREENED</option>
									<option value="shortlisted" selected={c.stage === 'shortlisted'}>SHORTLISTED</option>
									<option value="offered" selected={c.stage === 'offered'}>OFFERED</option>
									<option value="hired" selected={c.stage === 'hired'}>HIRED</option>
									<option value="rejected" selected={c.stage === 'rejected'}>REJECTED</option>
								</select>
							{/key}
						{/if}
						<a class="ct-act" href={`/candidates/${cid}`} title="Open profile" onclick={(e) => e.stopPropagation()}>↗</a>
					</div>

					<!-- expanded panel (H3) -->
					{#if isExp}
						<div class="ct-exp-panel">
							{#if c.match_explanation}
								<div class="ct-exp-row">
									<span class="ct-exp-label">WHY {Math.round(score)}%</span>
									<span>{c.match_explanation}</span>
								</div>
							{/if}
							{#if Array.isArray(c.skills_matched) && c.skills_matched.length}
								<div class="ct-exp-row">
									<span class="ct-exp-label ct-exp-green">STRENGTHS</span>
									<span>{c.skills_matched.slice(0, 8).join(' · ')}</span>
								</div>
							{/if}
							{#if Array.isArray(c.skills_missing) && c.skills_missing.length}
								<div class="ct-exp-row">
									<span class="ct-exp-label ct-exp-red">GAPS</span>
									<span>{c.skills_missing.slice(0, 6).join(' · ')}</span>
								</div>
							{/if}
							<!-- 6-dim mini bars -->
							<div class="ct-exp-bars">
								{#each [['SKL', c.match_score_skills],['EXP', c.match_score_experience],['EDU', c.match_score_education],['CRT', c.match_score_certifications],['IND', c.match_score_industry],['CULT', c.match_score_culture]] as [k, v]}
									{@const pv = Math.max(0, Math.min(100, Number(v) || 0))}
									<div class="ct-exp-bar-cell">
										<span class="ct-exp-bar-label">{k}</span>
										<div class="ct-exp-bar-track"><div class="ct-exp-bar-fill" style="width: {pv}%; background: {scoreColor(pv)};"></div></div>
										<span class="ct-exp-bar-val">{Math.round(pv)}%</span>
									</div>
								{/each}
							</div>
							<div class="ct-exp-actions">
								<button class="ct-act ct-act-cta" onclick={() => promote(c)} style="display: inline-flex; align-items: center; gap: 3px;"><Plus size={11} strokeWidth={1.75} /> ADD TO PIPELINE</button>
								<button class="ct-act ct-act-danger" onclick={() => reject(c)} style="display: inline-flex; align-items: center; gap: 3px;"><X size={11} strokeWidth={1.75} /> REJECT</button>
								<button class="ct-act" onclick={() => onOpenDrawer(cid, c)}>DRAWER</button>
								<a class="ct-act" href={`/candidates/${cid}`}>FULL CV</a>
							</div>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>

	{#if toast}
		<div class="ct-toast" class:ct-toast-error={toast.kind === 'error'}>
			<span class="ct-toast-text">{toast.text}</span>
			<button class="ct-toast-x" onclick={() => toast = null} style="display: inline-flex; align-items: center; justify-content: center;"><X size={12} strokeWidth={1.75} /></button>
		</div>
	{/if}

	{#if dupeModal}
		<div class="ct-modal-bg" onclick={closeDupeModal} role="presentation">
			<div class="ink-border stamp-shadow ct-modal" onclick={(e) => e.stopPropagation()} role="dialog">
				<div class="ct-modal-head">
					<span class="ct-modal-title" style="display: inline-flex; align-items: center; gap: 4px;"><AlertTriangle size={13} strokeWidth={1.75} /> ALREADY ATTACHED</span>
					<button class="ct-modal-x" onclick={closeDupeModal} style="display: inline-flex; align-items: center; justify-content: center;"><X size={12} strokeWidth={1.75} /></button>
				</div>
				<div class="ct-modal-body">
					<p class="ct-modal-line">
						<strong>{dupeModal.added}</strong> attached ·
						<strong>{dupeModal.skipped_count}</strong> skipped (already on this position) ·
						<strong>{dupeModal.requested}</strong> requested
					</p>
					<p class="ct-modal-sub">CV cannot be added twice to same position. Skipped:</p>
					<ul class="ct-modal-list">
						{#each dupeModal.skipped as s}
							<li>
								<strong>{s.name || `Candidate ${s.candidate_id}`}</strong>
								— stage: <span class="ct-modal-pill">{(s.stage || 'uploaded').toUpperCase()}</span>
								{s.reason === 'already_rejected' ? ' · was REJECTED' : ''}
							</li>
						{/each}
					</ul>
				</div>
				<div class="ct-modal-foot">
					<button class="ct-bulk-btn ct-bulk-cta" onclick={closeDupeModal}>[ OK ]</button>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	/* ── Wrap ──────────────────────────────────────────────────── */
	.ct-wrap {
		display: flex;
		flex-direction: column;
		gap: 12px;
		font-family: var(--font-body, 'Inter', sans-serif);
	}

	/* ── Row focus ─────────────────────────────────────────────── */
	.ct-row { outline: none; }
	.ct-row-focus,
	.ct-row:focus,
	.ct-row:focus-visible {
		box-shadow: inset 0 0 0 2px var(--color-accent, #c96342);
		outline: none;
	}

	/* ── Tab strip ─────────────────────────────────────────────── */
	.ct-tabs {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.ct-tab {
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 6px 12px;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 7px;
		background: var(--color-surface, #fff);
		color: var(--color-on-surface-dim, #6f6e69);
		cursor: pointer;
		transition: background 0.12s, color 0.12s, border-color 0.12s;
	}
	.ct-tab:hover {
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface, #2c2c2c);
		border-color: var(--color-border-strong, #d8d5cb);
	}
	.ct-tab-active {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.ct-tab-active:hover {
		background: var(--color-accent-ink, #b04f30);
		border-color: var(--color-accent-ink, #b04f30);
		color: #fff;
	}

	/* ── Tab help banner ───────────────────────────────────────── */
	.ct-help {
		padding: 10px 14px;
		background: var(--color-bg, #faf9f5);
		border: 1px solid var(--color-border, #e8e6dd);
		border-left: 3px solid var(--color-accent, #c96342);
		border-radius: 8px;
	}
	.ct-help-head { margin-bottom: 6px; }
	.ct-help-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-accent, #c96342);
	}
	.ct-help-body { display: flex; flex-direction: column; gap: 4px; }
	.ct-help-desc, .ct-help-how {
		margin: 0;
		font-size: 11px;
		line-height: 1.5;
		color: var(--color-on-surface, #2c2c2c);
	}
	.ct-help-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.07em;
		padding: 1px 6px;
		margin-right: 6px;
		background: var(--color-on-surface, #2c2c2c);
		color: #fff;
		border-radius: 4px;
		text-transform: uppercase;
	}
	.ct-help-label-green {
		background: var(--color-success, #2d6a4f);
		color: #fff;
	}

	/* ── Bulk toolbar ──────────────────────────────────────────── */
	.ct-bulk-bar {
		position: sticky;
		top: 0;
		z-index: 10;
		display: flex;
		gap: 6px;
		align-items: center;
		padding: 8px 12px;
		background: var(--color-accent, #c96342);
		color: white;
		border-radius: 8px;
		box-shadow: var(--shadow-md, 0 4px 12px rgba(0,0,0,0.05));
	}
	.ct-bulk-count {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.04em;
		margin-right: auto;
	}
	.ct-bulk-btn {
		font-family: inherit;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		padding: 5px 10px;
		border: 1px solid rgba(255,255,255,0.5);
		border-radius: 6px;
		background: transparent;
		color: white;
		cursor: pointer;
		transition: background 0.12s;
	}
	.ct-bulk-btn:hover { background: rgba(255,255,255,0.15); }
	.ct-bulk-btn[disabled] { opacity: 0.5; cursor: not-allowed; }
	.ct-bulk-cta { background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.7); }
	.ct-bulk-danger { border-color: rgba(255,255,255,0.4); }
	.ct-bulk-danger:hover { background: rgba(168,50,50,0.4); }
	.ct-bulk-mute { opacity: 0.6; }

	/* ── Main table ────────────────────────────────────────────── */
	.ct-table {
		display: flex;
		flex-direction: column;
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		overflow: hidden;
	}
	.ct-thead, .ct-row {
		display: grid;
		grid-template-columns: 28px 36px minmax(140px,1.4fr) minmax(120px,1.2fr) 50px minmax(140px,1.3fr) 64px 220px;
		gap: 8px;
		align-items: center;
		padding: 8px 10px;
	}
	/* Table header — warm beige, dark sentence-case text, 1px hairline bottom */
	.ct-thead {
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface-dim, #6f6e69);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		position: sticky;
		top: 0;
		z-index: 5;
	}
	.ct-thead .ct-cell { color: var(--color-on-surface-dim, #6f6e69); }
	.ct-sort {
		font-family: inherit;
		font-size: inherit;
		font-weight: inherit;
		letter-spacing: inherit;
		text-transform: inherit;
		text-align: left;
		background: transparent;
		color: inherit;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.ct-sort:hover { color: var(--color-on-surface, #2c2c2c); }
	.ct-row {
		border-top: 1px solid var(--color-border-soft, #efeee6);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-on-surface, #2c2c2c);
	}
	.ct-row:hover { background: var(--color-bg, #faf9f5); }
	.ct-row-sel { background: var(--color-accent-bg, #faf2ed); }
	.ct-cell { display: flex; align-items: center; gap: 4px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
	.ct-c-check input { width: 14px; height: 14px; cursor: pointer; accent-color: var(--color-accent, #c96342); }
	.ct-c-rank { color: var(--color-on-surface-dim, #6f6e69); font-weight: 600; }
	.ct-expand-btn {
		font-family: inherit; font-size: inherit; font-weight: inherit;
		background: transparent; border: none; color: inherit; cursor: pointer; padding: 0;
	}
	.ct-name-link {
		font-family: inherit; font-size: inherit; font-weight: 600;
		background: transparent; border: none; color: inherit; cursor: pointer; padding: 0;
		text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
	}
	.ct-name-link:hover { color: var(--color-accent, #c96342); text-decoration: underline; }

	/* ── Score bar ─────────────────────────────────────────────── */
	.ct-score-bar {
		flex: 1;
		min-width: 100px;
		height: 8px;
		background: var(--color-border, #e8e6dd);
		border-radius: 999px;
		overflow: hidden;
	}
	.ct-score-fill { height: 100%; border-radius: 999px; }
	.ct-score-num { font-size: 11px; font-weight: 700; min-width: 38px; text-align: right; }

	/* ── Source + Stage pills ──────────────────────────────────── */
	.ct-pill {
		font-size: 9px;
		font-weight: 600;
		padding: 2px 7px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 6px;
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface-dim, #6f6e69);
	}
	/* AI source pill — coral accent */
	.ct-pill-ai {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		border-color: var(--color-accent-soft, #fdebe1);
	}
	/* Stage pill colors set via inline style from stageStyle() */
	.ct-pill-stage { font-weight: 600; }

	.ct-stage-select {
		font-family: inherit;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		min-width: 150px;
		padding: 5px 22px 5px 10px;
		border-radius: 6px;
		border: 1px solid var(--color-border, #e8e6dd);
		appearance: none;
		-webkit-appearance: none;
		background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'><path d='M2 4l3 3 3-3' stroke='%23383832' stroke-width='1.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
		background-repeat: no-repeat;
		background-position: right 5px center;
		cursor: pointer;
		transition: filter 0.12s;
	}
	.ct-stage-select:hover:not(:disabled) { filter: brightness(0.96); }
	.ct-stage-select:disabled { opacity: 0.5; cursor: wait; }

	/* ── Action buttons ────────────────────────────────────────── */
	/* Soft icon buttons: 28px square, transparent bg, hover warm */
	.ct-act {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		min-width: 28px;
		height: 28px;
		padding: 0 6px;
		border: 1px solid transparent;
		border-radius: 7px;
		background: transparent;
		color: var(--color-on-surface-dim, #6f6e69);
		cursor: pointer;
		text-decoration: none;
		transition: background 0.12s, color 0.12s, border-color 0.12s;
	}
	.ct-act:hover {
		background: var(--color-bg, #faf9f5);
		border-color: var(--color-border, #e8e6dd);
		color: var(--color-on-surface, #2c2c2c);
	}
	.ct-act[disabled] { opacity: 0.4; cursor: not-allowed; }
	/* Plus / promote — coral on hover */
	.ct-act-cta { color: var(--color-on-surface-dim, #6f6e69); }
	.ct-act-cta:hover {
		background: var(--color-accent-soft, #fdebe1);
		border-color: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent, #c96342);
	}
	/* X / reject — muted error red on hover */
	.ct-act-danger { color: var(--color-on-surface-dim, #6f6e69); }
	.ct-act-danger:hover {
		background: var(--color-error-soft, #f5dada);
		border-color: var(--color-error-soft, #f5dada);
		color: var(--color-error, #a83232);
	}

	/* ── Empty state ───────────────────────────────────────────── */
	.ct-empty {
		padding: 32px;
		text-align: center;
		font-size: 12px;
		font-weight: 600;
		color: var(--color-on-surface-dim, #6f6e69);
		letter-spacing: 0.04em;
		border-top: 1px solid var(--color-border-soft, #efeee6);
	}

	/* ── Expanded detail panel ─────────────────────────────────── */
	.ct-exp-panel {
		grid-column: 1 / -1;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px 14px;
		background: var(--color-bg, #faf9f5);
		border-top: 1px dashed var(--color-border, #e8e6dd);
	}
	.ct-exp-row { display: flex; gap: 8px; align-items: baseline; font-size: 11px; }
	.ct-exp-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.06em;
		min-width: 80px;
		color: var(--color-accent, #c96342);
	}
	.ct-exp-green { color: var(--color-success, #2d6a4f); }
	.ct-exp-red { color: var(--color-error, #a83232); }
	.ct-exp-bars { display: flex; flex-wrap: wrap; gap: 12px; }
	.ct-exp-bar-cell { display: flex; flex-direction: column; gap: 2px; min-width: 80px; }
	.ct-exp-bar-label { font-size: 8px; font-weight: 700; letter-spacing: 0.06em; color: var(--color-on-surface-dim, #6f6e69); }
	.ct-exp-bar-track {
		width: 80px; height: 6px;
		background: var(--color-border, #e8e6dd);
		border-radius: 999px;
		overflow: hidden;
	}
	.ct-exp-bar-fill { height: 100%; border-radius: 999px; }
	.ct-exp-bar-val { font-size: 9px; font-weight: 600; }
	.ct-exp-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }

	/* ── Pool picker ───────────────────────────────────────────── */
	/* Talent Pool — explicit opt-in empty state */
	.ct-pool-empty {
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		padding: 56px 32px;
		text-align: center;
		max-width: 600px;
		margin: 24px auto;
	}
	.ct-pool-empty-icon {
		font-size: 38px;
		color: var(--color-accent, #c96342);
		margin-bottom: 14px;
	}
	.ct-pool-empty-title {
		font-family: 'Tiempos Headline', Georgia, serif;
		font-size: 22px; font-weight: 500;
		color: var(--color-on-surface, #2c2c2c);
		margin-bottom: 8px;
	}
	.ct-pool-empty-sub {
		font-size: 13px; line-height: 1.55;
		color: var(--color-on-surface-dim, #6f6e69);
		max-width: 420px; margin: 0 auto 24px;
	}
	.ct-pool-empty-cta {
		padding: 11px 24px;
		font-size: 13.5px; font-weight: 600;
		background: var(--color-accent, #c96342); color: #fff;
		border: 1px solid var(--color-accent, #c96342); border-radius: 8px;
		cursor: pointer; transition: filter 120ms;
	}
	.ct-pool-empty-cta:hover { filter: brightness(0.94); }
	.ct-pool-empty-hint {
		margin-top: 18px; font-size: 11.5px;
		color: var(--color-on-surface-dim, #6f6e69);
	}

	.ct-pool {
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}
	.ct-pool-bar {
		display: flex;
		gap: 8px;
		align-items: center;
		padding: 10px 12px;
		flex-wrap: wrap;
		background: var(--color-bg, #faf9f5);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		color: var(--color-on-surface, #2c2c2c);
	}
	.ct-pool-search {
		flex: 1;
		min-width: 220px;
		font-family: inherit;
		font-size: 12px;
		font-weight: 500;
		padding: 6px 10px;
		border: 1px solid var(--color-border-strong, #d8d5cb);
		border-radius: 7px;
		background: var(--color-surface, #fff);
		color: var(--color-on-surface, #2c2c2c);
		outline: none;
		transition: border-color 0.12s;
	}
	.ct-pool-search:focus { border-color: var(--color-accent, #c96342); }
	.ct-pool-scope, .ct-pool-refresh {
		font-family: inherit;
		font-size: 10px;
		font-weight: 600;
		padding: 6px 10px;
		border: 1px solid var(--color-border-strong, #d8d5cb);
		border-radius: 7px;
		background: var(--color-surface, #fff);
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		text-transform: uppercase;
		transition: background 0.12s;
	}
	.ct-pool-scope:hover, .ct-pool-refresh:hover { background: var(--color-border, #e8e6dd); }
	.ct-pool-count {
		font-size: 10px;
		font-weight: 500;
		color: var(--color-on-surface-dim, #6f6e69);
		letter-spacing: 0.03em;
		margin-left: auto;
	}
	.ct-pool-attach {
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		padding: 7px 14px;
		border: 1px solid var(--color-accent, #c96342);
		border-radius: 7px;
		background: var(--color-accent, #c96342);
		color: #fff;
		cursor: pointer;
		text-transform: uppercase;
		transition: background 0.12s;
	}
	.ct-pool-attach:hover { background: var(--color-accent-ink, #b04f30); border-color: var(--color-accent-ink, #b04f30); }
	.ct-pool-attach[disabled] { opacity: 0.5; cursor: not-allowed; }
	.ct-pool-thead, .ct-pool-row {
		display: grid;
		grid-template-columns: 28px minmax(140px,1.4fr) minmax(120px,1fr) 60px minmax(180px,2fr) 80px;
		gap: 8px;
		align-items: center;
		padding: 8px 10px;
	}
	.ct-pool-thead {
		background: var(--color-bg, #faf9f5);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--color-on-surface-dim, #6f6e69);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.ct-pool-row {
		font-size: 12px;
		font-weight: 500;
		border-top: 1px solid var(--color-border-soft, #efeee6);
		color: var(--color-on-surface, #2c2c2c);
	}
	.ct-pool-row:hover { background: var(--color-bg, #faf9f5); }
	.ct-pool-skills { font-size: 10px; color: var(--color-on-surface-dim, #6f6e69); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.ct-pool-mute { opacity: 0.4; }

	.ct-pool-row-attached { opacity: 0.5; background: var(--color-bg, #faf9f5); }
	.ct-pool-row-attached:hover { background: var(--color-border-soft, #efeee6); }
	.ct-pill-attached {
		background: var(--color-success-soft, #d8e4dd);
		color: var(--color-success, #2d6a4f);
		border-color: var(--color-success-soft, #d8e4dd);
		font-size: 9px;
		font-weight: 600;
		padding: 2px 8px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-radius: 6px;
	}

	/* ── Toast ─────────────────────────────────────────────────── */
	.ct-toast {
		position: fixed;
		bottom: 30px;
		left: 50%;
		transform: translateX(-50%);
		background: var(--color-on-surface, #2c2c2c);
		color: white;
		padding: 12px 18px;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		box-shadow: var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.08));
		font-size: 13px;
		font-weight: 500;
		z-index: 2000;
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 280px;
		max-width: 600px;
	}
	.ct-toast-error { background: var(--color-error, #a83232); }
	.ct-toast-text { flex: 1; }
	.ct-toast-x {
		background: transparent;
		border: 1px solid rgba(255,255,255,0.4);
		border-radius: 5px;
		color: white;
		cursor: pointer;
		width: 22px;
		height: 22px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	/* ── Dupe modal ────────────────────────────────────────────── */
	.ct-modal-bg {
		position: fixed;
		inset: 0;
		background: rgba(0,0,0,0.35);
		z-index: 1000;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.ct-modal {
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		min-width: 480px;
		max-width: 640px;
		max-height: 80vh;
		overflow: auto;
		box-shadow: var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.08));
	}
	.ct-modal-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 12px 16px;
		background: var(--color-error-soft, #f5dada);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px 12px 0 0;
		color: var(--color-error, #a83232);
	}
	.ct-modal-title {
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.ct-modal-x {
		background: transparent;
		border: 1px solid var(--color-border-strong, #d8d5cb);
		border-radius: 6px;
		color: var(--color-on-surface-dim, #6f6e69);
		width: 24px;
		height: 24px;
		font-weight: 600;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}
	.ct-modal-body { padding: 16px; }
	.ct-modal-line { font-size: 13px; margin: 0 0 10px; color: var(--color-on-surface, #2c2c2c); }
	.ct-modal-sub { font-size: 11px; color: var(--color-on-surface-dim, #6f6e69); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.05em; }
	.ct-modal-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
	.ct-modal-list li {
		font-size: 12px;
		padding: 6px 10px;
		border-left: 3px solid var(--color-error, #a83232);
		background: var(--color-error-soft, #f5dada);
		border-radius: 0 6px 6px 0;
	}
	.ct-modal-pill {
		font-size: 9px;
		font-weight: 600;
		padding: 1px 6px;
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 4px;
		text-transform: uppercase;
	}
	.ct-modal-foot {
		padding: 12px 16px;
		border-top: 1px solid var(--color-border, #e8e6dd);
		display: flex;
		justify-content: flex-end;
	}

	@media (max-width: 900px) {
		.ct-thead, .ct-row {
			grid-template-columns: 24px 28px 1fr 60px 1fr 50px 50px;
		}
		.ct-c-role, .ct-c-stage { display: none; }
	}
</style>
