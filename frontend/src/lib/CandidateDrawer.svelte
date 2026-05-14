<script>
	/**
	 * CandidateDrawer.svelte — slide-in side drawer (~600px) showing
	 * candidate profile + (optional) per-position match score breakdown.
	 *
	 * Props:
	 *   candidateId      — number/string id of candidate to show
	 *   positionContext  — { slug, match } when opened from a position; null when standalone
	 *   isOpen           — boolean controlling visibility
	 *   onClose          — () => void
	 *   onPromote        — (candidateId) => void   (only used when positionContext set)
	 *   onReject         — (candidateId) => void
	 */
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';
	import DocViewer from '$lib/DocViewer.svelte';
	import FileText from '@lucide/svelte/icons/file-text';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';

	// Minimal markdown for AI summaries — escapes HTML first, then renders **bold**, *em*, ## H3,
	// ### H4, - bullets, paragraph breaks. Mirrors `mdLite` in /candidates/[id] page.
	function mdLite(s) {
		if (!s) return '';
		const esc = String(s)
			.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
		return esc
			.replace(/^### (.+)$/gm, '<h4 style="font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:0.06em;margin:10px 0 4px 0;color:#c96342;">$1</h4>')
			.replace(/^## (.+)$/gm, '<h3 style="font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:0.06em;margin:12px 0 4px 0;color:#c96342;">$1</h3>')
			.replace(/\*\*(.+?)\*\*/g, '<strong style="font-weight:900;color:#383832;">$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			.replace(/^- (.+)$/gm, '<li style="margin-left:14px;list-style:disc;">$1</li>')
			.replace(/(<li[^>]*>.*<\/li>\n?)+/g, m => '<ul style="margin:4px 0;padding-left:0;">' + m + '</ul>')
			.replace(/\n\n+/g, '</p><p style="margin:6px 0;">')
			.replace(/^/, '<p style="margin:0 0 6px 0;">') + '</p>';
	}

	let {
		candidateId = null,
		positionContext = null,
		isOpen = false,
		onClose = () => {},
		onPromote = () => {},
		onReject = () => {}
	} = $props();

	let candidate = $state(null);
	let loading = $state(false);
	let loadError = $state('');
	let activeTab = $state('profile');
	let pipeline = $state([]);
	let pipelineLoaded = $state(false);
	let docsActivated = $state(false);
	let signedFileUrl = $state('');
	let docsFileMissing = $state(false);
	let docsFileChecked = $state(false);

	// ─── Load candidate when opened / id changes
	$effect(() => {
		const open = isOpen;
		const cid = candidateId;
		if (!open || !cid) return;
		untrack(() => {
			// reset per-record state
			candidate = null;
			loadError = '';
			activeTab = 'profile';
			pipeline = [];
			pipelineLoaded = false;
			docsActivated = false;
			signedFileUrl = '';
			docsFileMissing = false;
			docsFileChecked = false;
			loading = true;
			(async () => {
				try {
					const data = await apiJson(`/candidates/${cid}`);
					if (cid !== candidateId) return; // stale
					candidate = data?.candidate || data;
				} catch (e) {
					loadError = e?.message || 'Failed to load candidate';
				}
				loading = false;
			})();
		});
	});

	// ─── Body scroll lock + ESC key
	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!isOpen) return;
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		const onKey = (e) => { if (e.key === 'Escape') onClose(); };
		window.addEventListener('keydown', onKey);
		return () => {
			document.body.style.overflow = prev;
			window.removeEventListener('keydown', onKey);
		};
	});

	// ─── Lazy: load pipeline when PIPELINE tab activated
	$effect(() => {
		const open = isOpen;
		const cid = candidateId;
		const tab = activeTab;
		if (!open || !cid) return;
		if (tab !== 'pipeline') return;
		untrack(() => {
			if (pipelineLoaded) return;
			(async () => {
				try {
					const r = await apiJson(`/candidates/${cid}/ai-recommendations`);
					if (cid !== candidateId) return;
					pipeline = r?.recommendations || r?.positions || (Array.isArray(r) ? r : []);
				} catch {
					pipeline = [];
				}
				pipelineLoaded = true;
			})();
		});
	});

	// ─── Probe file availability when DOCS tab activated
	$effect(() => {
		const open = isOpen;
		const cid = candidateId;
		const tab = activeTab;
		const activated = docsActivated;
		if (!open || !cid) return;
		if (tab !== 'docs' || !activated) return;
		untrack(() => {
			if (docsFileChecked) return;
			(async () => {
			try {
				const sig = await apiJson(`/candidates/${cid}/file/sign`);
				let url = sig?.url || '';
				if (url && !url.startsWith('/api/')) url = `/api${url}`;
				if (!url) {
					docsFileMissing = true;
				} else {
					// HEAD probe; many servers don't support HEAD on signed routes, so fall back to GET range
					let resp;
					try {
						resp = await fetch(url, { method: 'HEAD' });
						if (resp.status === 405 || resp.status === 501) {
							resp = await fetch(url, { method: 'GET', headers: { Range: 'bytes=0-0' } });
						}
					} catch {
						resp = await fetch(url, { method: 'GET', headers: { Range: 'bytes=0-0' } });
					}
					if (cid !== candidateId) return;
					docsFileMissing = (resp.status === 404);
				}
			} catch (e) {
				const msg = String(e?.message || '');
				docsFileMissing = msg.includes('404') || msg.includes('file_missing');
			}
			docsFileChecked = true;
		})();
		});
	});

	// ─── Open CV PDF in new tab via signed URL
	async function openCvPdf() {
		if (!candidateId) return;
		try {
			const data = await apiJson(`/candidates/${candidateId}/file/sign`);
			let url = data?.url || '';
			if (url && !url.startsWith('/api/')) url = `/api${url}`;
			if (url) window.open(url, '_blank', 'noopener');
		} catch (e) {
			alert('Could not get signed URL for CV: ' + (e?.message || ''));
		}
	}

	// ─── Tabs
	const tabs = [
		{ id: 'profile', label: 'PROFILE' },
		{ id: 'skills', label: 'SKILLS' },
		{ id: 'experience', label: 'EXPERIENCE' },
		{ id: 'score', label: 'SCORE' },
		{ id: 'docs', label: 'DOCS' },
		{ id: 'pipeline', label: 'PIPELINE' }
	];

	function fmtDate(d) {
		if (!d) return '';
		try {
			const dt = new Date(d);
			if (isNaN(dt.getTime())) return String(d);
			return dt.toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
		} catch { return String(d); }
	}
	function getYrs(c) {
		if (!c) return 0;
		return Number(c.years_experience ?? c.total_experience_years ?? c.experience_years ?? 0) || 0;
	}
	function scoreColor(s) {
		const v = Number(s) || 0;
		if (v >= 70) return '#3a8a4f';
		if (v >= 40) return '#c98c2a';
		return '#c4571a';
	}

	// Source detection (AI vs MANUAL pill)
	let source = $derived.by(() => {
		const m = positionContext?.match || candidate || {};
		const ai = m.auto_added
			|| ['ai_promoted','auto_scan_on_create','auto_scan_on_jd_update','auto_scan_rescan'].includes(m.match_source)
			|| ['ai_scan','auto_match','ai_auto','ai_auto_scan'].includes(m.added_by);
		return ai ? 'AI' : 'MANUAL';
	});

	let match = $derived(positionContext?.match || null);
	let composite = $derived(Number(match?.match_score_composite ?? 0));
	let breakdown = $derived(match ? {
		SKILLS:      match.match_score_skills,
		EXP:         match.match_score_experience,
		EDU:         match.match_score_education,
		CERT:        match.match_score_certifications,
		IND:         match.match_score_industry,
		CULTURE:     match.match_score_culture,
		COMPETENCIES: match.match_score_competencies
	} : {});

	// File ext detection for DocViewer
	let fileExt = $derived.by(() => {
		const fn = candidate?.file_name || candidate?.cv_file || '';
		const m = String(fn).match(/\.([a-zA-Z0-9]+)$/);
		return (m ? m[1] : (candidate?.file_type || 'pdf')).toLowerCase();
	});
	let fileName = $derived(candidate?.file_name || candidate?.cv_file || `candidate_${candidateId}`);
</script>

{#if isOpen}
	<!-- Backdrop -->
	<div class="cdrawer-backdrop"
		onclick={onClose}
		role="button" tabindex="-1"
		aria-label="Close drawer"></div>

	<!-- Drawer -->
	<aside class="cdrawer ink-border stamp-shadow" aria-modal="true" role="dialog">

		<!-- HEADER -->
		<header class="cdrawer-header">
			<button class="cdrawer-x" onclick={onClose} aria-label="Close">[ ✕ ]</button>

			{#if loading && !candidate}
				<div class="cdrawer-loading">LOADING CANDIDATE…</div>
			{:else if loadError}
				<div class="cdrawer-err">{loadError}</div>
			{:else if candidate}
				<div class="cdrawer-name">{candidate.name || `CANDIDATE ${candidateId}`}</div>
				<div class="cdrawer-meta">
					{candidate.current_role || candidate.role || 'N/A'}
					· {getYrs(candidate)}YR
					{#if candidate.current_company}· {candidate.current_company}{/if}
				</div>

				<div class="cdrawer-pillrow">
					<span class="cdrawer-pill" class:cdrawer-pill-ai={source === 'AI'}>{source}</span>
					{#if positionContext}
						<span class="cdrawer-pill cdrawer-pill-ctx">POSITION: {positionContext.slug}</span>
					{/if}
					{#if match}
						<span class="cdrawer-pill cdrawer-pill-score" style="border-color: {scoreColor(composite)}; color: {scoreColor(composite)};">
							{Math.round(composite)}% MATCH
						</span>
					{/if}
				</div>

				<div class="cdrawer-headbtns">
					<button class="cdrawer-btn" onclick={openCvPdf}><FileText size={12} strokeWidth={1.75} /> OPEN CV PDF</button>
					<a class="cdrawer-btn" href={`/candidates/${candidateId}`}>[ VIEW FULL PAGE ]</a>
				</div>
			{/if}
		</header>

		<!-- TAB STRIP -->
		<nav class="cdrawer-tabs">
			{#each tabs as t}
				<button class="cdrawer-tab"
					class:cdrawer-tab-active={activeTab === t.id}
					onclick={() => { activeTab = t.id; if (t.id === 'docs') docsActivated = true; }}>
					{t.label}
				</button>
			{/each}
		</nav>

		<!-- BODY -->
		<div class="cdrawer-body">
			{#if loading && !candidate}
				<div class="cdrawer-loading">LOADING…</div>
			{:else if !candidate}
				<div class="cdrawer-empty">NO CANDIDATE DATA</div>
			{:else if activeTab === 'profile'}
				<section class="cd-section">
					<div class="cd-row"><span class="cd-key">EMAIL</span><span class="cd-val">{candidate.email || '—'}</span></div>
					<div class="cd-row"><span class="cd-key">PHONE</span><span class="cd-val">{candidate.phone || '—'}</span></div>
					<div class="cd-row"><span class="cd-key">LOCATION</span><span class="cd-val">{candidate.location || candidate.city || '—'}</span></div>
					<div class="cd-row"><span class="cd-key">SENIORITY</span><span class="cd-val">{candidate.seniority_level || '—'}</span></div>
					{#if candidate.linkedin_url || candidate.linkedin}
						<div class="cd-row"><span class="cd-key">LINKEDIN</span><a class="cd-link" href={candidate.linkedin_url || candidate.linkedin} target="_blank" rel="noopener">{candidate.linkedin_url || candidate.linkedin}</a></div>
					{/if}
					{#if candidate.github_url || candidate.github}
						<div class="cd-row"><span class="cd-key">GITHUB</span><a class="cd-link" href={candidate.github_url || candidate.github} target="_blank" rel="noopener">{candidate.github_url || candidate.github}</a></div>
					{/if}
					{#if candidate.portfolio_url}
						<div class="cd-row"><span class="cd-key">PORTFOLIO</span><a class="cd-link" href={candidate.portfolio_url} target="_blank" rel="noopener">{candidate.portfolio_url}</a></div>
					{/if}
				</section>

				{#if candidate.dob || candidate.gender || candidate.nationality || candidate.national_id}
					<div class="cd-subhead">DEMOGRAPHICS</div>
					<section class="cd-section">
						{#if candidate.dob}<div class="cd-row"><span class="cd-key">DOB</span><span class="cd-val">{candidate.dob}</span></div>{/if}
						{#if candidate.gender}<div class="cd-row"><span class="cd-key">GENDER</span><span class="cd-val">{candidate.gender}</span></div>{/if}
						{#if candidate.nationality}<div class="cd-row"><span class="cd-key">NATIONALITY</span><span class="cd-val">{candidate.nationality}</span></div>{/if}
						{#if candidate.national_id}<div class="cd-row"><span class="cd-key">NATIONAL ID</span><span class="cd-val">{candidate.national_id}</span></div>{/if}
						{#if candidate.marital_status}<div class="cd-row"><span class="cd-key">MARITAL</span><span class="cd-val">{candidate.marital_status}</span></div>{/if}
					</section>
				{/if}

				{#if candidate.ai_summary || candidate.summary}
					<div class="cd-subhead">SUMMARY</div>
					<div class="cd-summary">{@html mdLite(candidate.ai_summary || candidate.summary)}</div>
				{/if}

			{:else if activeTab === 'skills'}
				{#if Array.isArray(candidate.skills) && candidate.skills.length}
					<div class="cd-subhead">SKILLS</div>
					<div class="cd-chips">
						{#each candidate.skills as s}<span class="cd-chip">{typeof s === 'string' ? s : (s.name || s.skill || '')}</span>{/each}
					</div>
				{/if}
				{#if Array.isArray(candidate.tags) && candidate.tags.length}
					<div class="cd-subhead">TAGS</div>
					<div class="cd-chips">
						{#each candidate.tags as t}<span class="cd-chip">{typeof t === 'string' ? t : (t.name || '')}</span>{/each}
					</div>
				{/if}
				{#if Array.isArray(candidate.competencies) && candidate.competencies.length}
					<div class="cd-subhead">COMPETENCIES</div>
					<div class="cd-chips">
						{#each candidate.competencies as c}<span class="cd-chip">{typeof c === 'string' ? c : (c.label || c.key || '')}</span>{/each}
					</div>
				{/if}
				{#if !(candidate.skills?.length) && !(candidate.tags?.length) && !(candidate.competencies?.length)}
					<div class="cd-empty">NO SKILLS EXTRACTED</div>
				{/if}

			{:else if activeTab === 'experience'}
				{#if Array.isArray(candidate.experience) && candidate.experience.length}
					<ol class="cd-timeline">
						{#each candidate.experience as exp}
							<li class="cd-tl-item">
								<div class="cd-tl-head">
									<span class="cd-tl-role">{exp.title || exp.role || 'ROLE'}</span>
									<span class="cd-tl-dates">{fmtDate(exp.start_date || exp.start)} → {exp.end_date || exp.end ? fmtDate(exp.end_date || exp.end) : 'PRESENT'}</span>
								</div>
								<div class="cd-tl-co">{exp.company || ''}{exp.location ? ` · ${exp.location}` : ''}</div>
								{#if exp.description || exp.summary}
									<div class="cd-tl-desc">{exp.description || exp.summary}</div>
								{/if}
							</li>
						{/each}
					</ol>
				{:else}
					<div class="cd-empty">NO EXPERIENCE EXTRACTED</div>
				{/if}

				{#if Array.isArray(candidate.education) && candidate.education.length}
					<div class="cd-subhead">EDUCATION</div>
					<ol class="cd-timeline">
						{#each candidate.education as ed}
							<li class="cd-tl-item">
								<div class="cd-tl-head">
									<span class="cd-tl-role">{ed.degree || ed.qualification || 'DEGREE'}</span>
									<span class="cd-tl-dates">{fmtDate(ed.start_date)} → {ed.end_date ? fmtDate(ed.end_date) : (ed.year || '')}</span>
								</div>
								<div class="cd-tl-co">{ed.institution || ed.school || ''}</div>
							</li>
						{/each}
					</ol>
				{/if}

			{:else if activeTab === 'score'}
				{#if !match}
					<div class="cd-empty">NO POSITION CONTEXT — OPEN FROM A POSITION TO SEE MATCH SCORE</div>
				{:else}
					<div class="cd-score-head">
						<div class="cd-score-chip" style="border-color: {scoreColor(composite)}; color: {scoreColor(composite)};">
							{Math.round(composite)}%
						</div>
						<div class="cd-score-label">COMPOSITE MATCH SCORE</div>
					</div>

					<div class="cd-bars">
						{#each Object.entries(breakdown) as [dim, val]}
							{#if val != null}
								{@const pct = Math.max(0, Math.min(100, Number(val) || 0))}
								<div class="cd-bar-cell">
									<div class="cd-bar-label">{dim}</div>
									<div class="cd-bar-track">
										<div class="cd-bar-fill" style="width: {pct}%; background: {scoreColor(pct)};"></div>
									</div>
									<div class="cd-bar-val">{Math.round(pct)}%</div>
								</div>
							{/if}
						{/each}
					</div>

					{#if match.skills_matched?.length}
						<div class="cd-subhead">SKILLS MATCHED ({match.skills_matched.length})</div>
						<div class="cd-chips">
							{#each match.skills_matched as s}<span class="cd-chip cd-chip-good"><Check size={10} strokeWidth={2} /> {s}</span>{/each}
						</div>
					{/if}
					{#if match.skills_missing?.length}
						<div class="cd-subhead">SKILLS MISSING ({match.skills_missing.length})</div>
						<div class="cd-chips">
							{#each match.skills_missing as s}<span class="cd-chip cd-chip-bad"><X size={10} strokeWidth={2} /> {s}</span>{/each}
						</div>
					{/if}
					{#if match.match_explanation}
						<div class="cd-subhead">EXPLANATION</div>
						<div class="cd-summary">{match.match_explanation}</div>
					{/if}
				{/if}

			{:else if activeTab === 'docs'}
				{#if docsActivated && candidateId}
					{#if !docsFileChecked}
						<div class="cd-empty">CHECKING FILE…</div>
					{:else if docsFileMissing}
						<div class="cd-empty" style="text-align: left; padding: 24px;">
							<div style="font-weight: 900; font-size: 13px; margin-bottom: 8px;">CV FILE NOT AVAILABLE</div>
							<div style="font-size: 11px; opacity: 0.8; margin-bottom: 12px;">
								The original CV was not stored or has been removed from disk. Extracted data (profile, skills, experience) is still available on other tabs.
							</div>
							<a href="/candidates" style="font-size: 11px; text-decoration: underline;">→ RE-UPLOAD VIA CV REPO</a>
						</div>
					{:else}
						<DocViewer candidateId={candidateId} fileType={fileExt} fileName={fileName} />
					{/if}
				{:else}
					<div class="cd-empty">CLICK [ DOCS ] AGAIN TO LOAD</div>
				{/if}

			{:else if activeTab === 'pipeline'}
				{#if !pipelineLoaded}
					<div class="cd-empty">LOADING PIPELINE…</div>
				{:else if pipeline.length === 0}
					<div class="cd-empty">CANDIDATE NOT ATTACHED TO ANY POSITIONS</div>
				{:else}
					<ul class="cd-pipeline">
						{#each pipeline as p}
							<li class="cd-pl-item">
								<a class="cd-pl-link" href={`/positions/${p.slug || p.position_slug}`}>{p.title || p.position_title || p.slug}</a>
								<span class="cd-pl-stage">{(p.stage || p.status || '').toUpperCase()}</span>
								{#if p.match_score || p.score}
									<span class="cd-pl-score" style="color: {scoreColor(p.match_score || p.score)};">{Math.round(p.match_score || p.score)}%</span>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			{/if}
		</div>

		<!-- FOOTER -->
		<footer class="cdrawer-footer">
			{#if positionContext}
				<button class="cd-foot-btn cd-foot-add" onclick={() => onPromote(candidateId)}>[ ADD TO PIPELINE ]</button>
				<button class="cd-foot-btn cd-foot-rej" onclick={() => onReject(candidateId)}>[ REJECT ]</button>
			{:else}
				<button class="cd-foot-btn" onclick={onClose}>[ CLOSE ]</button>
			{/if}
		</footer>
	</aside>
{/if}

<style>
	/* ── Backdrop ────────────────────────────────────────────── */
	.cdrawer-backdrop {
		position: fixed; inset: 0;
		background: rgba(44,44,44,0.38);
		z-index: 950;
		animation: cd-fade 0.18s ease;
		border: none; padding: 0;
		cursor: pointer;
	}

	/* ── Drawer shell ─────────────────────────────────────────── */
	.cdrawer {
		position: fixed;
		top: 0; right: 0; bottom: 0;
		width: min(600px, 100vw);
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface, #2c2c2c);
		font-family: 'Space Grotesk', sans-serif;
		display: flex; flex-direction: column;
		z-index: 951;
		box-shadow: -4px 0 24px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
		animation: cd-slide 0.2s ease;
		overflow: hidden;
		border-left: 1px solid var(--color-border, #e8e6dd);
	}
	@keyframes cd-fade { from { opacity: 0; } to { opacity: 1; } }
	@keyframes cd-slide { from { transform: translateX(100%); } to { transform: translateX(0); } }

	/* ── HEADER ──────────────────────────────────────────────── */
	.cdrawer-header {
		position: relative;
		padding: 16px 18px 14px;
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}

	/* Close button — soft icon, no harsh border */
	.cdrawer-x {
		position: absolute; top: 10px; right: 12px;
		background: transparent;
		border: 1px solid transparent;
		color: var(--color-on-surface-dim, #6f6e69);
		font-family: inherit; font-weight: 700;
		font-size: 16px; padding: 4px 8px;
		cursor: pointer; border-radius: 6px;
		line-height: 1; transition: background 0.15s, color 0.15s;
	}
	.cdrawer-x:hover {
		background: rgba(201,99,66,0.08);
		color: var(--color-accent, #c96342);
		border-color: var(--color-border, #e8e6dd);
	}

	.cdrawer-name {
		font-size: 17px; font-weight: 700;
		letter-spacing: 0.01em; padding-right: 52px;
		color: var(--color-on-surface, #2c2c2c);
	}
	.cdrawer-meta {
		font-size: 11px; margin-top: 3px;
		text-transform: uppercase; letter-spacing: 0.05em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cdrawer-loading, .cdrawer-err {
		font-size: 12px; font-weight: 700;
		letter-spacing: 0.06em; padding: 6px 0;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cdrawer-err { color: var(--color-error, #c4571a); }

	/* ── Pill row ─────────────────────────────────────────────── */
	.cdrawer-pillrow { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
	.cdrawer-pill {
		font-size: 9px; font-weight: 700; padding: 2px 8px;
		border: 1px solid var(--color-border, #e8e6dd);
		background: transparent;
		color: var(--color-on-surface-dim, #6f6e69);
		text-transform: uppercase; letter-spacing: 0.06em;
		border-radius: 4px;
	}
	/* AI pill — coral tint */
	.cdrawer-pill-ai {
		background: rgba(201,99,66,0.1);
		color: var(--color-accent, #c96342);
		border-color: rgba(201,99,66,0.3);
	}
	/* POSITION pill — subtle warm */
	.cdrawer-pill-ctx {
		background: rgba(232,230,221,0.4);
		color: var(--color-on-surface-dim, #6f6e69);
		border-color: var(--color-border, #e8e6dd);
	}
	/* MATCH score pill — border/text color set inline via scoreColor() */
	.cdrawer-pill-score {
		background: transparent;
		font-weight: 800;
	}

	/* ── Header buttons ───────────────────────────────────────── */
	.cdrawer-headbtns { display: flex; gap: 6px; margin-top: 12px; flex-wrap: wrap; }
	.cdrawer-btn {
		font-family: inherit; font-size: 10px; font-weight: 700;
		padding: 5px 11px; background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer; text-transform: uppercase; letter-spacing: 0.05em;
		text-decoration: none; border-radius: 6px;
		transition: border-color 0.15s, color 0.15s, background 0.15s;
		display: inline-flex; align-items: center; gap: 4px;
	}
	.cdrawer-btn:hover {
		border-color: var(--color-accent, #c96342);
		color: var(--color-accent, #c96342);
		background: rgba(201,99,66,0.05);
	}

	/* ── TAB STRIP ───────────────────────────────────────────── */
	.cdrawer-tabs {
		display: flex; flex-wrap: wrap;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface-bright, #fff);
	}
	.cdrawer-tab {
		flex: 1 1 auto; min-width: 72px;
		font-family: inherit; font-size: 10px; font-weight: 700;
		padding: 9px 6px; cursor: pointer;
		background: transparent;
		color: var(--color-on-surface-dim, #6f6e69);
		border: none;
		border-bottom: 2px solid transparent;
		text-transform: uppercase; letter-spacing: 0.06em;
		transition: color 0.15s, border-color 0.15s;
		margin-bottom: -1px;
	}
	.cdrawer-tab:hover {
		color: var(--color-accent, #c96342);
		background: rgba(201,99,66,0.04);
	}
	/* Active tab — coral underline + coral text, warm bg */
	.cdrawer-tab-active {
		color: var(--color-accent, #c96342);
		border-bottom-color: var(--color-accent, #c96342);
		background: rgba(201,99,66,0.06);
	}

	/* ── BODY ────────────────────────────────────────────────── */
	.cdrawer-body {
		flex: 1 1 auto; min-height: 0;
		overflow-y: auto; overflow-x: hidden;
		padding: 16px 18px 20px;
		background: var(--color-bg, #faf9f5);
	}

	/* Profile rows */
	.cd-section { display: flex; flex-direction: column; gap: 6px; }
	.cd-row {
		display: flex; gap: 10px; font-size: 12px;
		border-bottom: 1px solid rgba(232,230,221,0.7);
		padding: 5px 0;
	}
	.cd-key {
		min-width: 90px; font-size: 10px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cd-val { flex: 1; word-break: break-word; color: var(--color-on-surface, #2c2c2c); }
	.cd-link {
		flex: 1; color: var(--color-accent, #c96342);
		text-decoration: underline; word-break: break-all;
	}

	/* Section subheadings */
	.cd-subhead {
		font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
		text-transform: uppercase; color: var(--color-on-surface-dim, #6f6e69);
		margin: 18px 0 8px; padding-bottom: 5px;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}

	/* Summary / explanation box — white card with hairline */
	.cd-summary {
		font-size: 12px; line-height: 1.6;
		padding: 10px 12px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 6px;
		color: var(--color-on-surface, #2c2c2c);
		box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.04));
	}

	.cd-empty {
		padding: 28px 8px; text-align: center;
		font-size: 11px; font-weight: 700; letter-spacing: 0.07em;
		text-transform: uppercase;
		color: var(--color-on-surface-dim, #6f6e69);
		opacity: 0.7;
	}

	/* Skill/tag chips */
	.cd-chips { display: flex; flex-wrap: wrap; gap: 5px; }
	.cd-chip {
		font-size: 10px; font-weight: 600; padding: 3px 8px;
		border: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface-bright, #fff);
		color: var(--color-on-surface, #2c2c2c);
		text-transform: uppercase; letter-spacing: 0.04em;
		border-radius: 4px;
		display: inline-flex; align-items: center; gap: 3px;
	}
	/* Matched skills — warm green tint */
	.cd-chip-good {
		border-color: rgba(58,138,79,0.3);
		color: #3a8a4f;
		background: rgba(58,138,79,0.06);
	}
	/* Missing skills — muted coral tint */
	.cd-chip-bad {
		border-color: rgba(196,87,26,0.3);
		color: var(--color-error, #c4571a);
		background: rgba(196,87,26,0.05);
	}

	/* ── TIMELINE ────────────────────────────────────────────── */
	.cd-timeline { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
	.cd-tl-item {
		padding: 10px 12px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-left: 3px solid var(--color-accent, #c96342);
		border-radius: 6px;
		box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.04));
	}
	.cd-tl-head { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
	.cd-tl-role { font-size: 12px; font-weight: 700; color: var(--color-on-surface, #2c2c2c); }
	.cd-tl-dates {
		font-size: 10px; text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cd-tl-co {
		font-size: 11px; font-weight: 600; margin-top: 2px;
		color: var(--color-accent, #c96342);
		text-transform: uppercase; letter-spacing: 0.04em;
	}
	.cd-tl-desc { font-size: 11px; line-height: 1.5; margin-top: 5px; color: var(--color-on-surface, #2c2c2c); }

	/* ── SCORE TAB ───────────────────────────────────────────── */
	.cd-score-head { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
	.cd-score-chip {
		width: 64px; height: 64px;
		border: 2px solid;
		background: var(--color-surface-bright, #fff);
		border-radius: 8px;
		display: flex; align-items: center; justify-content: center;
		font-size: 16px; font-weight: 800;
		box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.04));
	}
	.cd-score-label {
		font-size: 11px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.08em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cd-bars { display: flex; flex-direction: column; gap: 6px; }
	.cd-bar-cell { display: grid; grid-template-columns: 100px 1fr 40px; align-items: center; gap: 8px; }
	.cd-bar-label {
		font-size: 9px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.05em;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cd-bar-track {
		height: 6px;
		background: rgba(232,230,221,0.8);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 3px; overflow: hidden;
	}
	.cd-bar-fill { height: 100%; border-radius: 3px; }
	.cd-bar-val {
		font-size: 10px; font-weight: 700;
		text-align: right; color: var(--color-on-surface, #2c2c2c);
	}

	/* ── PIPELINE TAB ────────────────────────────────────────── */
	.cd-pipeline { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
	.cd-pl-item {
		display: flex; align-items: center; gap: 10px;
		padding: 9px 12px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 6px;
		box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.04));
	}
	.cd-pl-link {
		flex: 1; font-weight: 700; font-size: 12px;
		color: var(--color-on-surface, #2c2c2c); text-decoration: none;
	}
	.cd-pl-link:hover { color: var(--color-accent, #c96342); text-decoration: underline; }
	.cd-pl-stage {
		font-size: 9px; font-weight: 700; padding: 2px 7px;
		background: rgba(232,230,221,0.6);
		color: var(--color-on-surface-dim, #6f6e69);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 4px;
		text-transform: uppercase; letter-spacing: 0.05em;
	}
	.cd-pl-score { font-size: 11px; font-weight: 800; }

	/* ── FOOTER ──────────────────────────────────────────────── */
	.cdrawer-footer {
		flex-shrink: 0;
		padding: 10px 16px;
		background: var(--color-surface-bright, #fff);
		display: flex; gap: 8px; justify-content: flex-end;
		border-top: 1px solid var(--color-border, #e8e6dd);
	}
	.cd-foot-btn {
		font-family: inherit;
		font-size: 11px; font-weight: 700;
		padding: 8px 16px;
		background: transparent;
		border: 1px solid var(--color-border, #e8e6dd);
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		text-transform: uppercase; letter-spacing: 0.06em;
		border-radius: 6px;
		transition: background 0.15s, border-color 0.15s, color 0.15s;
	}
	/* ADD TO PIPELINE — coral solid */
	.cd-foot-add {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.cd-foot-add:hover {
		background: #b5573a;
		border-color: #b5573a;
	}
	/* REJECT — warm ghost (coral text + hairline border, fills on hover) */
	.cd-foot-rej {
		border-color: rgba(201,99,66,0.35);
		color: var(--color-accent, #c96342);
		background: transparent;
	}
	.cd-foot-rej:hover {
		background: rgba(201,99,66,0.08);
		border-color: var(--color-accent, #c96342);
	}
	/* Generic close button */
	.cd-foot-btn:hover:not(.cd-foot-add):not(.cd-foot-rej) {
		background: rgba(232,230,221,0.5);
		border-color: var(--color-on-surface-dim, #6f6e69);
	}

	/* ── RESPONSIVE ──────────────────────────────────────────── */
	@media (max-width: 640px) {
		.cdrawer { width: 100vw; }
	}

	@media (max-width: 768px) {
		.cdrawer {
			width: 100vw; max-width: 100vw;
			top: 0; bottom: 0; left: 0; right: 0;
			box-shadow: none;
		}
		.cdrawer-header { padding: 12px 14px; }
		.cdrawer-name { font-size: 15px; padding-right: 48px; }
		.cdrawer-body { padding: 12px 14px 16px; }
		.cdrawer-tab { font-size: 11px; padding: 10px 6px; }
		.cdrawer-x { top: 10px; right: 12px; font-size: 18px; padding: 3px 8px; }
		.cdrawer-headbtns .cdrawer-btn { font-size: 11px; padding: 6px 12px; }
	}
</style>
