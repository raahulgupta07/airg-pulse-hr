<script>
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
	import { apiJson, api } from '$lib/api';
	import EmailCompose from '$lib/EmailCompose.svelte';
	import PdfViewer from '$lib/PdfViewer.svelte';
	import Chart from '$lib/Chart.svelte';
	import PipelineStepper from '$lib/PipelineStepper.svelte';
	import DocViewer from '$lib/DocViewer.svelte';
	import SplitPane from '$lib/SplitPane.svelte';
	import QuickActions from '$lib/QuickActions.svelte';
	import CandidateAIMatches from '$lib/CandidateAIMatches.svelte';
	import SchedulePanel from '$lib/SchedulePanel.svelte';
	import Presence from '$lib/Presence.svelte';
	import ActivityFeed from '$lib/ActivityFeed.svelte';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import Eye from '@lucide/svelte/icons/eye';

	// Module-scoped guard: ensure AI summary auto-load runs at most once per candidate id
	// per page session (prevents Svelte 5 effect_update_depth_exceeded loops when the
	// mutation re-triggers reactivity after candidate fetch).
	const aiSummaryLoadAttempted = new Set();

	// --- Route param ---
	const candidateId = $derived(page.params.id);

	// --- State ---
	let candidate = $state(null);
	let loading = $state(true);
	let activeTab = $state('profile');
	let candAiCount = $state(0);
	let notes = $state([]);
	let scorecards = $state([]);
	let activity = $state([]);
	let notesLoading = $state(false);
	let scorecardsLoading = $state(false);
	let activityLoading = $state(false);
	let newNote = $state('');
	let newNoteType = $state('general');
	let submittingNote = $state(false);
	let showEmailCompose = $state(false);
	let showPdfViewer = $state(false);
	let showSchedulePanel = $state(false);

	// --- AI Summary state ---
	let aiSummaryLoading = $state(false);
	let aiSummary = $state(null);
	let showAiSummary = $state(false);
	let aiSummaryCopied = $state(false);

	// --- GitHub Analysis state ---
	let githubUrl = $state('');
	let githubLoading = $state(false);
	let githubResult = $state(null);
	let githubError = $state('');

	// --- @Mentions state ---
	let teamUsers = $state([]);
	let showMentionDropdown = $state(false);
	let mentionFilter = $state('');
	let mentionCursorPos = $state(0);
	let noteTextarea = $state(null);

	// --- Reply / threaded comments state ---
	let replyOpenFor = $state(null);   // parent note id currently being replied to
	let replyText = $state('');
	let submittingReply = $state(false);
	let backendSupportsReplies = $state(true); // flips false if backend rejects parent_id

	// --- Tags state ---
	let tags = $state([]);
	let showTagForm = $state(false);
	let newTagName = $state('');
	let newTagColor = $state('#2c2c2c');
	let submittingTag = $state(false);
	const presetColors = ['#3a8a4f', '#006f7c', '#c4571a', '#c98c2a', '#9d4867', '#2c2c2c'];

	// --- Flags state ---
	let candidateFlags = $state([]);

	// --- Radar chart state ---
	let selectedRadarPosition = $state(0);

	// --- Duplicates state ---
	let duplicates = $state([]);
	let showDuplicates = $state(false);
	let merging = $state(false);

	// --- Referral state ---
	let referral = $state(null);
	let showReferralForm = $state(false);
	let refName = $state('');
	let refEmail = $state('');
	let refNotes = $state('');
	let savingReferral = $state(false);

	// --- Duplicates banner dismissed (per-candidate, localStorage) ---
	let duplicatesDismissed = $state(false);
	let _dbg = (typeof window !== 'undefined') && (window.__hireFx = window.__hireFx || {});
	function _t(label) { if (!_dbg) return; _dbg[label] = (_dbg[label] || 0) + 1; if (_dbg[label] > 50) console.warn('[fx-loop]', label, _dbg[label]); }
	$effect(() => {
		_t('fx_dups');
		if (!candidateId) return;
		try {
			duplicatesDismissed = localStorage.getItem(`hire_dismiss_dup_${candidateId}`) === '1';
		} catch { duplicatesDismissed = false; }
	});
	function dismissDuplicates() {
		duplicatesDismissed = true;
		try { localStorage.setItem(`hire_dismiss_dup_${candidateId}`, '1'); } catch {}
	}

	// --- Prev/next navigation cache ---
	let navIds = $state([]);
	let navIndex = $derived(navIds.indexOf(Number(candidateId)));
	let prevId = $derived(navIndex > 0 ? navIds[navIndex - 1] : null);
	let nextId = $derived(navIndex >= 0 && navIndex < navIds.length - 1 ? navIds[navIndex + 1] : null);

	async function loadNavList() {
		// Try localStorage first (seeded by list page)
		try {
			const cached = JSON.parse(localStorage.getItem('hire_cand_nav_list') || '[]');
			if (Array.isArray(cached) && cached.length > 0) {
				navIds = cached.map(Number).filter(Boolean);
				if (navIds.includes(Number(candidateId))) return;
			}
		} catch {}
		// Fallback: fetch
		try {
			const data = await apiJson('/candidates/?scope=mine&limit=200');
			const items = data.candidates || data.items || (Array.isArray(data) ? data : []);
			navIds = items.map(c => Number(c.id)).filter(Boolean);
			try { localStorage.setItem('hire_cand_nav_list', JSON.stringify(navIds)); } catch {}
		} catch (e) { navIds = []; }
	}

	$effect(() => { _t('fx_nav'); if (candidateId) untrack(() => loadNavList()); });

	function goPrev() { if (prevId) goto(`/candidates/${prevId}`); }
	function goNext() { if (nextId) goto(`/candidates/${nextId}`); }

	// --- Pipeline cost+latency from latest_run ---
	let pipelineCost = $state(0);
	let pipelineLatencyMs = $state(0);
	async function loadPipelineCostLatency() {
		try {
			const d = await apiJson(`/candidates/${candidateId}/pipeline_trace`);
			const runs = d.runs || [];
			const latest = runs[0];
			if (latest) {
				pipelineCost = Number(latest.total_cost_usd || latest.cost_usd || latest.cost || 0);
				pipelineLatencyMs = Number(latest.total_latency_ms || latest.latency_ms || latest.duration_ms || 0);
			}
		} catch (e) { /* silent */ }
	}
	$effect(() => { _t('fx_pcl'); if (candidateId) untrack(() => loadPipelineCostLatency()); });

	// --- Verified count (Opus-verified demographics) ---
	const DEMO_KEYS = ['dob', 'national_id', 'gender', 'marital_status', 'nationality', 'religion', 'height', 'weight', 'father_name'];
	let verifiedCount = $derived.by(() => {
		if (!candidate) return 0;
		return DEMO_KEYS.reduce((acc, k) => acc + (candidate[k] != null && candidate[k] !== '' ? 1 : 0), 0);
	});
	let opusVerified = $derived(verifiedCount > 0);

	// --- Tabs strip horizontal scroll ---
	let tabsStripEl = $state(null);
	let tabsCanScrollLeft = $state(false);
	let tabsCanScrollRight = $state(false);
	let isNarrow = $state(false);
	function updateTabsScroll() {
		if (!tabsStripEl) return;
		tabsCanScrollLeft = tabsStripEl.scrollLeft > 4;
		tabsCanScrollRight = tabsStripEl.scrollLeft + tabsStripEl.clientWidth < tabsStripEl.scrollWidth - 4;
	}
	function scrollTabs(dir) {
		if (!tabsStripEl) return;
		tabsStripEl.scrollBy({ left: dir * 200, behavior: 'smooth' });
		setTimeout(updateTabsScroll, 220);
	}
	$effect(() => {
		_t('fx_resize');
		if (typeof window === 'undefined') return;
		const onResize = () => untrack(() => {
			isNarrow = window.innerWidth < 1100;
			updateTabsScroll();
		});
		onResize();
		window.addEventListener('resize', onResize);
		return () => window.removeEventListener('resize', onResize);
	});

	// --- AI matches count listener (from CandidateAIMatches component) ---
	$effect(() => {
		_t('fx_ai_count');
		if (typeof window === 'undefined') return;
		const onCount = (e) => {
			const d = e?.detail || {};
			if (String(d.candidateId) === String(candidateId)) {
				untrack(() => { candAiCount = Number(d.count) || 0; });
			}
		};
		window.addEventListener('candidate-ai-count', onCount);
		return () => window.removeEventListener('candidate-ai-count', onCount);
	});

	// --- Tab badge counts ---
	function tabBadge(tabId) {
		switch (tabId) {
			case 'notes': return notes?.length || 0;
			case 'scorecards': return scorecards?.length || 0;
			case 'assignments': return assignments?.length || 0;
			case 'competencies': return competencies?.length || 0;
			case 'ai_matches': return candAiCount || 0;
			default: return 0;
		}
	}

	function fmtCost(c) {
		if (!c || c <= 0) return '';
		return '$' + c.toFixed(3);
	}
	function fmtLatency(ms) {
		if (!ms || ms <= 0) return '';
		const s = ms / 1000;
		if (s < 60) return `${s.toFixed(1)}s`;
		const m = Math.floor(s / 60);
		const rem = Math.floor(s % 60);
		return `${m}m ${rem}s`;
	}

	function scrollToSelector(sel) {
		try {
			document.querySelector(sel)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		} catch {}
	}

	// --- Parsed JSONB fields ---
	let experience = $derived(parseJsonField(candidate?.experience));
	let education = $derived(parseJsonField(candidate?.education));
	let certifications = $derived(parseJsonField(candidate?.certifications));
	let projects = $derived(parseJsonField(candidate?.projects));
	let positionMatches = $derived(candidate?.position_matches || candidate?.positions || []);

	// --- Radar chart options ---
	let radarChartOptions = $derived.by(() => {
		if (positionMatches.length === 0) return null;
		const pm = positionMatches[selectedRadarPosition] || positionMatches[0];
		if (!pm) return null;

		const dims = [
			{ key: 'skills', label: 'Technical Skills' },
			{ key: 'experience', label: 'Experience' },
			{ key: 'education', label: 'Education' },
			{ key: 'certifications', label: 'Certifications' },
			{ key: 'industry', label: 'Industry Match' },
			{ key: 'culture', label: 'Culture Fit' },
		];

		const candidateScores = dims.map(d => {
			const val = pm[`match_score_${d.key}`] ?? pm[`score_${d.key}`] ?? pm[d.key] ?? 0;
			return Math.round(Number(val) || 0);
		});

		// If all zeros, try composite score as fallback
		const hasScores = candidateScores.some(v => v > 0);
		if (!hasScores && (pm.composite_score || pm.score)) {
			const base = Math.round(Number(pm.composite_score || pm.score) || 0);
			candidateScores[0] = Math.min(100, base + 5);
			candidateScores[1] = Math.min(100, base - 3);
			candidateScores[2] = Math.min(100, base - 8);
			candidateScores[3] = Math.min(100, base - 15);
			candidateScores[4] = Math.min(100, base);
			candidateScores[5] = Math.min(100, base - 5);
		}

		return {
			tooltip: { trigger: 'item' },
			legend: {
				data: ['Candidate', 'Ideal'],
				bottom: 0,
				textStyle: { fontFamily: 'Space Grotesk', fontSize: 11, fontWeight: 700 },
			},
			radar: {
				indicator: dims.map(d => ({ name: d.label, max: 100 })),
				shape: 'polygon',
				splitNumber: 4,
				axisName: {
					fontFamily: 'Space Grotesk',
					fontSize: 11,
					fontWeight: 700,
					color: '#383832',
				},
				splitLine: { lineStyle: { color: '#e5e5e0' } },
				splitArea: { show: true, areaStyle: { color: ['rgba(254,255,214,0.3)', 'rgba(254,255,214,0.1)'] } },
				axisLine: { lineStyle: { color: '#ccccc4' } },
			},
			series: [{
				type: 'radar',
				data: [
					{
						value: candidateScores,
						name: 'Candidate',
						symbol: 'circle',
						symbolSize: 6,
						lineStyle: { width: 2, color: '#007518' },
						areaStyle: { color: 'rgba(0,117,24,0.25)' },
						itemStyle: { color: '#007518' },
					},
					{
						value: [100, 100, 100, 100, 100, 100],
						name: 'Ideal',
						symbol: 'none',
						lineStyle: { type: 'dashed', width: 2, color: '#383832' },
						areaStyle: { color: 'rgba(56,56,50,0.05)' },
					},
				],
			}],
		};
	});

	// --- Load candidate on mount / id change ---
	$effect(() => {
		_t('fx_main');
		if (candidateId) untrack(() => {
			loadCandidate();
			loadTags();
			loadDuplicates();
			loadReferral();
		});
	});

	// --- Load tab data when tab changes ---
	let notesLoaded = $state(false);
	let scorecardsLoaded = $state(false);
	let activityLoaded = $state(false);
	$effect(() => {
		_t('fx_tabs');
		if (!candidate || !activeTab) return;
		const tab = activeTab;
		queueMicrotask(() => {
			if (tab === 'notes' && !notesLoaded) { notesLoaded = true; loadNotes(); }
			else if (tab === 'scorecards') {
				if (!scorecardsLoaded) { scorecardsLoaded = true; loadScorecards(); }
			}
			else if (tab === 'activity' && !activityLoaded) { activityLoaded = true; loadActivity(); }
			else if (tab === 'assignments' && !assignmentsLoaded) { assignmentsLoaded = true; loadAssignments(); }
			else if (tab === 'competencies' && !competenciesLoaded) { competenciesLoaded = true; loadCompetencies(); }
			else if (tab === 'pipeline') {
				if (!pipelineLoaded) { pipelineLoaded = true; loadPipelineRuns(); }
				if (!artifactsLoaded) { artifactsLoaded = true; loadArtifacts(); }
			}
		});
	});

	// --- Pipeline trace state ---
	let pipelineRuns = $state([]);
	let pipelineRunsLoading = $state(false);
	let pipelineLoaded = $state(false);
	let selectedPipelineRunId = $state(null);
	let pipelineRunBusy = $state(false);

	// --- Processing artifacts state ---
	let artifacts = $state(null);
	let artifactsLoading = $state(false);
	let artifactsError = $state('');
	let artifactsLoaded = $state(false);
	let artifactsExpanded = $state({}); // {row_key: bool}
	let artifactsQaPairs = $state([]);
	let artifactsQaLoaded = $state(false);

	async function loadArtifacts() {
		if (!candidate) return;
		artifactsLoading = true;
		artifactsError = '';
		try {
			const data = await apiJson(`/candidates/${candidate.id}/artifacts`);
			artifacts = data;
			artifactsLoaded = true;
		} catch (e) {
			artifactsError = (e?.message || '').includes('404')
				? 'Artifacts API not yet available — refresh in a moment'
				: 'Failed to load artifacts: ' + (e?.message || '');
			artifacts = null;
		}
		artifactsLoading = false;
	}

	async function toggleArtifactRow(key) {
		artifactsExpanded[key] = !artifactsExpanded[key];
		if (key === 'qa' && artifactsExpanded[key] && !artifactsQaLoaded) {
			try {
				const d = await apiJson(`/candidates/${candidate.id}/qa_pairs`);
				artifactsQaPairs = Array.isArray(d) ? d : (d.items || d.pairs || d.qa_pairs || []);
			} catch (e) {
				// Fall back to sample from artifacts payload
				artifactsQaPairs = (artifacts?.qa_pairs?.sample || []).map(p => ({ question: p.q, answer: p.a }));
			}
			artifactsQaLoaded = true;
		}
	}

	async function loadPipelineRuns() {
		if (!candidate) return;
		pipelineRunsLoading = true;
		try {
			const data = await apiJson(`/candidates/${candidate.id}/pipeline_trace`);
			pipelineRuns = data.runs || [];
			if (pipelineRuns.length > 0 && !selectedPipelineRunId) {
				selectedPipelineRunId = pipelineRuns[0].run_id;
			}
			pipelineLoaded = true;
		} catch (e) {
			pipelineRuns = [];
		}
		pipelineRunsLoading = false;
	}

	async function loadDuplicates() {
		try {
			const data = await apiJson(`/candidates/${candidateId}/duplicates`);
			duplicates = data.duplicates || data || [];
			if (!Array.isArray(duplicates)) duplicates = [];
		} catch (e) { duplicates = []; }
	}

	async function mergeDuplicate(mergeId) {
		merging = true;
		try {
			await apiJson('/duplicates/merge', {
				method: 'POST',
				body: JSON.stringify({ keep_id: parseInt(candidateId), merge_id: mergeId }),
			});
			duplicates = duplicates.filter(d => (d.id || d.candidate_id) !== mergeId);
			await loadCandidate();
		} catch (e) { console.error('Merge failed:', e); }
		merging = false;
	}

	async function loadReferral() {
		try {
			const data = await apiJson(`/candidates/${candidateId}/referral`);
			referral = data.referral || data || null;
			if (referral && !referral.referrer_name) referral = null;
		} catch (e) { referral = null; }
	}

	async function saveReferral() {
		if (!refName.trim()) return;
		savingReferral = true;
		try {
			await apiJson(`/candidates/${candidateId}/referral`, {
				method: 'POST',
				body: JSON.stringify({ referrer_name: refName, referrer_email: refEmail, notes: refNotes }),
			});
			showReferralForm = false;
			refName = ''; refEmail = ''; refNotes = '';
			await loadReferral();
		} catch (e) { console.error('Save referral failed:', e); }
		savingReferral = false;
	}

	function parseJsonField(val) {
		if (!val) return [];
		if (Array.isArray(val)) return val;
		if (typeof val === 'string') {
			try { return JSON.parse(val); } catch { return []; }
		}
		return [];
	}

	async function loadCandidate() {
		loading = true;
		candidate = null;
		// Reset per-candidate state so navigation between profiles is clean
		notes = []; scorecards = []; activity = []; tags = [];
		duplicates = []; pipelineRuns = []; artifacts = null; assignments = [];
		competencies = []; candidateFlags = []; referral = null;
		notesLoaded = false; scorecardsLoaded = false;
		activityLoaded = false; assignmentsLoaded = false; competenciesLoaded = false;
		pipelineLoaded = false; artifactsLoaded = false;
		activeTab = 'profile';
		try {
			candidate = await apiJson(`/candidates/${candidateId}`);
		} catch (e) {
			console.error('Failed to load candidate:', e);
		}
		try {
			const flagsRes = await apiJson(`/evaluation/candidates/${candidateId}/flags`);
			candidateFlags = flagsRes.flags || [];
		} catch (e) { candidateFlags = []; }
		loading = false;

		// Auto-load AI summary in background if not yet generated.
		// Guarded by module-scoped Set + queueMicrotask + untrack so the mutation
		// cannot re-enter the parent $effect (avoids effect_update_depth_exceeded).
		const idKey = String(candidateId);
		if (candidate && !candidate.ai_summary) {
			if (!aiSummaryLoadAttempted.has(idKey)) {
				aiSummaryLoadAttempted.add(idKey);
				queueMicrotask(() => untrack(() => loadAiSummary()));
			}
		} else if (candidate?.ai_summary) {
			aiSummary = { ai_summary: candidate.ai_summary, cached: true };
			aiSummaryLoadAttempted.add(idKey);
		}
	}

	async function loadNotes() {
		notesLoading = true;
		try {
			const data = await apiJson(`/candidates/${candidateId}/notes`);
			notes = Array.isArray(data) ? data : (data.notes || []);
		} catch (e) { console.error(e); }
		notesLoading = false;
	}

	async function loadScorecards() {
		scorecardsLoading = true;
		try {
			const data = await apiJson(`/candidates/${candidateId}/scorecards`);
			scorecards = Array.isArray(data) ? data : (data.scorecards || []);
		} catch (e) { console.error(e); }
		scorecardsLoading = false;
	}

	async function loadActivity() {
		activityLoading = true;
		try {
			const data = await apiJson(`/candidates/${candidateId}/activity`);
			activity = Array.isArray(data) ? data : (data.activity || data.events || []);
		} catch (e) { console.error(e); }
		activityLoading = false;
	}

	async function loadTags() {
		try {
			const data = await apiJson(`/candidates/${candidateId}/tags`);
			tags = Array.isArray(data) ? data : (data.tags || []);
		} catch (e) { console.error('Failed to load tags:', e); }
	}

	async function addTag() {
		if (!newTagName.trim()) return;
		submittingTag = true;
		try {
			await apiJson(`/candidates/${candidateId}/tags`, {
				method: 'POST',
				body: JSON.stringify({ tag: newTagName.trim(), color: newTagColor }),
			});
			newTagName = '';
			newTagColor = '#2c2c2c';
			showTagForm = false;
			await loadTags();
		} catch (e) { console.error('Failed to add tag:', e); }
		submittingTag = false;
	}

	async function removeTag(tagName) {
		try {
			await apiJson(`/candidates/${candidateId}/tags/${encodeURIComponent(tagName)}`, {
				method: 'DELETE',
			});
			await loadTags();
		} catch (e) { console.error('Failed to remove tag:', e); }
	}

	async function submitNote() {
		if (!newNote.trim()) return;
		submittingNote = true;
		try {
			await apiJson(`/candidates/${candidateId}/notes`, {
				method: 'POST',
				body: JSON.stringify({ content: newNote, note_type: newNoteType }),
			});
			newNote = '';
			await loadNotes();
		} catch (e) { console.error(e); }
		submittingNote = false;
	}

	// --- Threaded replies ---
	function openReply(noteId) {
		replyOpenFor = (replyOpenFor === noteId) ? null : noteId;
		replyText = '';
	}

	async function submitReply(parentId) {
		if (!replyText.trim()) return;
		submittingReply = true;
		try {
			// Try backend with parent_id first
			await apiJson(`/candidates/${candidateId}/notes`, {
				method: 'POST',
				body: JSON.stringify({
					content: replyText,
					note_type: 'comment',
					parent_id: parentId,
				}),
			});
		} catch (e) {
			// Backend may reject parent_id (422) — fall back to flat post w/ visual cue
			backendSupportsReplies = false;
			try {
				await apiJson(`/candidates/${candidateId}/notes`, {
					method: 'POST',
					body: JSON.stringify({
						content: `↳ reply: ${replyText}`,
						note_type: 'comment',
					}),
				});
			} catch (err) { console.error('reply fallback failed', err); }
		}
		replyText = '';
		replyOpenFor = null;
		submittingReply = false;
		await loadNotes();
	}

	// Build a parent → children map (works whether or not backend honors parent_id)
	let notesTree = $derived.by(() => {
		const list = Array.isArray(notes) ? notes : [];
		const byParent = new Map();
		const roots = [];
		for (const n of list) {
			const pid = n.parent_id ?? n.parentId ?? null;
			if (pid) {
				if (!byParent.has(pid)) byParent.set(pid, []);
				byParent.get(pid).push(n);
			} else {
				roots.push(n);
			}
		}
		return roots.map(r => ({ note: r, replies: byParent.get(r.id) || [] }));
	});

	function scoreColor(score) {
		if (score >= 70) return 'var(--color-primary)';
		if (score >= 40) return 'var(--color-warning)';
		return 'var(--color-error)';
	}

	function scoreClass(score) {
		if (score >= 70) return 'score-high';
		if (score >= 40) return 'score-mid';
		return 'score-low';
	}

	function formatDate(d) {
		if (!d) return '';
		try {
			return new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
		} catch { return d; }
	}

	function formatDateTime(d) {
		if (!d) return '';
		try {
			return new Date(d).toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
		} catch { return d; }
	}

	function timeAgo(d) {
		if (!d) return '';
		try {
			const now = Date.now();
			const then = new Date(d).getTime();
			const diff = now - then;
			const mins = Math.floor(diff / 60000);
			if (mins < 1) return 'just now';
			if (mins < 60) return `${mins}m ago`;
			const hrs = Math.floor(mins / 60);
			if (hrs < 24) return `${hrs}h ago`;
			const days = Math.floor(hrs / 24);
			if (days < 30) return `${days}d ago`;
			return formatDate(d);
		} catch { return d; }
	}

	function initials(name) {
		if (!name) return '?';
		return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
	}

	function activityIcon(type) {
		const icons = {
			uploaded: 'upload_file',
			scored: 'analytics',
			stage_changed: 'swap_horiz',
			note_added: 'note_add',
			interview_scheduled: 'event',
			interview_completed: 'event_available',
			email_sent: 'mail',
			scorecard_submitted: 'fact_check',
			created: 'person_add',
			updated: 'edit',
		};
		return icons[type] || icons[type?.toLowerCase()] || 'radio_button_checked';
	}

	// --- Activity timeline helpers ---
	function activityColor(type) {
		const colors = {
			uploaded: 'var(--color-on-surface-dim, #6f6e69)',
			stage_changed: '#006f7c',
			stage_change: '#006f7c',
			note_added: 'var(--color-warning, #c98c2a)',
			interview_scheduled: '#006f7c',
			interview_completed: '#006f7c',
			scorecard_submitted: '#3a8a4f',
			email_sent: '#9d4867',
			ai_auto_scan: 'var(--color-accent, #c96342)',
			screening_completed: '#3a8a4f',
			added_to_position: '#006f7c',
			created: 'var(--color-on-surface-dim, #6f6e69)',
			updated: 'var(--color-on-surface, #2c2c2c)',
		};
		return colors[type] || colors[type?.toLowerCase()] || 'var(--color-on-surface, #2c2c2c)';
	}

	function groupActivitiesByDate(items) {
		const groups = [];
		const now = new Date();
		const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
		const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
		const weekAgo = new Date(today); weekAgo.setDate(weekAgo.getDate() - 7);

		let currentGroup = null;

		for (const item of items) {
			const d = new Date(item.created_at || item.timestamp || item.date);
			const itemDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());

			let label;
			if (itemDate >= today) label = 'Today';
			else if (itemDate >= yesterday) label = 'Yesterday';
			else if (itemDate >= weekAgo) label = 'This Week';
			else label = 'Earlier';

			if (!currentGroup || currentGroup.label !== label) {
				currentGroup = { label, items: [] };
				groups.push(currentGroup);
			}
			currentGroup.items.push(item);
		}
		return groups;
	}

	let activityGroups = $derived(groupActivitiesByDate(activity));

	function humanizeEvent(event) {
		const t = (event.action || event.event_type || event.type || 'event').toLowerCase();
		const d = (typeof event.details === 'object' && event.details) || {};
		// stage moves
		if (t.includes('stage') || t === 'event' && d.new_stage) {
			const ns = d.new_stage || d.stage || '?';
			const fs = d.from_stage || d.old_stage;
			return fs ? `Moved from ${fs} → ${ns}` : `Moved to ${ns}`;
		}
		if (t === 'event' && d.added !== undefined && d.scanned !== undefined) {
			return `Added to position (${d.added} of ${d.scanned} matched, threshold ${d.threshold || '—'})`;
		}
		if (t === 'event' && d.rejection_reason) return `Rejected: ${d.rejection_reason}`;
		// known actions
		const map = {
			cv_uploaded: 'CV uploaded',
			cv_processed: 'CV processed',
			candidate_scored: 'Candidate scored',
			scorecard_submitted: 'Scorecard submitted',
			interview_scheduled: 'Interview scheduled',
			interview_completed: 'Interview completed',
			note_added: 'Note added',
			email_sent: 'Email sent',
			tag_added: 'Tag added',
			candidate_uploaded: 'Candidate uploaded',
			user_invite: 'User invited',
		};
		if (map[t]) return map[t];
		return event.description || event.message || event.text || t.replace(/_/g, ' ');
	}

	function humanizeDetails(event) {
		const d = (typeof event.details === 'object' && event.details) || {};
		if (!d || Object.keys(d).length === 0) return '';
		const t = (event.action || event.event_type || event.type || '').toLowerCase();
		// stage move — already covered in title, skip details
		if (d.new_stage && Object.keys(d).every(k => ['bulk','new_stage','old_stage','from_stage','rejection_reason'].includes(k))) {
			return d.rejection_reason ? `Reason: ${d.rejection_reason}` : '';
		}
		if (d.added !== undefined && d.scanned !== undefined) return ''; // in title
		// fallback: pretty key:value
		return Object.entries(d)
			.filter(([_, v]) => v !== null && v !== '' && v !== false)
			.map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
			.join(' · ');
	}

	const tabs = [
		{ id: 'profile', label: 'Profile', icon: 'person' },
		{ id: 'experience', label: 'Experience', icon: 'work' },
		{ id: 'skills', label: 'Skills', icon: 'psychology' },
		{ id: 'competencies', label: 'Comp', icon: 'psychology_alt' },
		{ id: 'assignments', label: 'Assign', icon: 'assignment_ind' },
		{ id: 'notes', label: 'Notes', icon: 'note' },
		{ id: 'scorecards', label: 'Score', icon: 'fact_check' },
		{ id: 'pipeline', label: 'Pipeline', icon: 'graph_3' },
		{ id: 'ai_matches', label: 'AI Matches', icon: 'auto_awesome' },
		{ id: 'activity', label: 'Act', icon: 'timeline' },
	];

	// ── Scorecard submit form (with competency ratings) ──
	let showScorecardForm = $state(false);
	let scorecardPositionSlug = $state('');
	let scorecardOverall = $state(3);
	let scorecardRecommendation = $state('hire');
	let scorecardComments = $state('');
	let scorecardCompetencyRatings = $state({}); // {competency_id: level}
	let positionCompetencies = $state([]);
	let positionCompsLoading = $state(false);
	let submittingScorecard = $state(false);

	async function loadPositionCompetenciesForScorecard() {
		if (!scorecardPositionSlug) { positionCompetencies = []; return; }
		positionCompsLoading = true;
		try {
			const d = await apiJson(`/positions/${scorecardPositionSlug}/competencies`);
			positionCompetencies = (Array.isArray(d) ? d : (d.competencies || d.items || []));
			scorecardCompetencyRatings = {};
		} catch (e) {
			positionCompetencies = [];
		}
		positionCompsLoading = false;
	}

	async function submitScorecard() {
		if (!scorecardPositionSlug) return;
		submittingScorecard = true;
		try {
			const payload = {
				candidate_id: Number(candidateId),
				position_slug: scorecardPositionSlug,
				overall_score: Number(scorecardOverall) * 20,
				recommendation: scorecardRecommendation,
				comments: scorecardComments,
				competency_ratings: scorecardCompetencyRatings,
			};
			await apiJson('/scorecards', { method: 'POST', body: JSON.stringify(payload) });
			window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type: 'success', text: 'Scorecard submitted' } }));
			showScorecardForm = false;
			scorecardComments = '';
			scorecardCompetencyRatings = {};
			scorecards = [];
			loadScorecards();
			competencies = [];
			competenciesLoaded = false;
		} catch (e) {
			window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type: 'error', text: 'Submit failed: ' + (e.message || '') } }));
		}
		submittingScorecard = false;
	}

	// ── Competencies tab state ──
	let competencies = $state([]);
	let competenciesLoaded = $state(false);
	let competenciesLoading = $state(false);
	let extractingComps = $state(false);
	let compExpandedKey = $state(null);
	let compOverrideLevel = $state({});  // {competency_id: level}
	let compOverrideEvidence = $state({});

	async function loadCompetencies() {
		competenciesLoading = true;
		try {
			const d = await apiJson(`/candidates/${candidateId}/competencies`);
			competencies = (Array.isArray(d) ? d : (d.competencies || d.items || []));
		} catch (e) {
			competencies = [];
		}
		competenciesLoaded = true;
		competenciesLoading = false;
	}

	async function autoExtractCompetencies() {
		extractingComps = true;
		try {
			const d = await apiJson(`/candidates/${candidateId}/competencies/auto-extract`, { method: 'POST' });
			const n = d?.extracted?.length ?? d?.created ?? 0;
			window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type: 'success', text: `${n} competencies extracted from CV` } }));
			await loadCompetencies();
		} catch (e) {
			window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type: 'error', text: 'Extract failed: ' + (e.message || '') } }));
		}
		extractingComps = false;
	}

	async function saveCompetencyOverride(comp) {
		const cid = comp.competency_id ?? comp.id;
		const level = compOverrideLevel[cid];
		const evidence = compOverrideEvidence[cid] || '';
		if (level == null) return;
		try {
			await apiJson(`/candidates/${candidateId}/competencies/${cid}`, {
				method: 'PUT',
				body: JSON.stringify({ level: Number(level), evidence, source: 'manual' }),
			});
			window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type: 'success', text: 'Override saved' } }));
			await loadCompetencies();
		} catch (e) {
			window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type: 'error', text: 'Save failed' } }));
		}
	}

	// Aggregate display: competencies might come grouped by competency or as raw signals.
	// If list has duplicates per competency_id, weight-average by source.
	const SOURCE_W = { manual: 1.0, scorecard: 0.9, 'manager-rating': 0.95, manager_rating: 0.95, 'cv-extract': 0.6, cv_extract: 0.6, 'self-report': 0.4, self_report: 0.4 };

	let aggregatedComps = $derived.by(() => {
		if (!Array.isArray(competencies) || competencies.length === 0) return [];
		const byKey = new Map();
		for (const c of competencies) {
			const k = c.competency_id ?? c.id ?? c.key;
			if (!byKey.has(k)) {
				byKey.set(k, { ...c, signals: [] });
			}
			byKey.get(k).signals.push(c);
		}
		const out = [];
		for (const [k, group] of byKey) {
			let sum = 0, wsum = 0;
			let bestSource = '—';
			let bestEvidence = '';
			let bestW = -1;
			for (const s of group.signals) {
				const w = SOURCE_W[s.source] ?? 0.5;
				const lv = Number(s.level ?? 0);
				if (lv > 0) { sum += lv * w; wsum += w; }
				if (w > bestW) { bestW = w; bestSource = s.source || '—'; bestEvidence = s.evidence || ''; }
			}
			const avg = wsum > 0 ? sum / wsum : Number(group.level ?? 0);
			out.push({
				competency_id: group.competency_id ?? group.id,
				key: group.key || group.competency_key || '',
				label: group.label || group.competency_label || group.key || '',
				avgLevel: avg,
				topSource: bestSource,
				topEvidence: bestEvidence,
				signals: group.signals,
			});
		}
		out.sort((a, b) => b.avgLevel - a.avgLevel);
		return out;
	});

	let assignments = $state([]);
	let assignmentsLoaded = $state(false);
	async function loadAssignments() {
		try {
			const d = await apiJson(`/candidates/${candidateId}/assignments?include_dismissed=true`);
			assignments = d.assignments || [];
			assignmentsLoaded = true;
		} catch (e) { assignments = []; assignmentsLoaded = true; }
	}

	const noteTypes = ['general', 'screening', 'feedback', 'internal', 'rejection', 'offer'];

	// --- Load team users for @mentions ---
	$effect(() => { _t('fx_team'); untrack(() => loadTeamUsers()); });

	async function loadTeamUsers() {
		try {
			const data = await apiJson('/auth/users');
			teamUsers = data.users || [];
		} catch (e) { console.error('Failed to load users:', e); }
	}

	let filteredMentionUsers = $derived(
		teamUsers.filter(u =>
			!mentionFilter || u.display_name.toLowerCase().includes(mentionFilter.toLowerCase())
		).slice(0, 6)
	);

	function handleNoteInput(e) {
		const textarea = e.target;
		const val = textarea.value;
		const pos = textarea.selectionStart;
		// Check if we are typing an @mention
		const textBefore = val.substring(0, pos);
		const atMatch = textBefore.match(/@(\w*)$/);
		if (atMatch) {
			mentionFilter = atMatch[1];
			mentionCursorPos = pos;
			showMentionDropdown = true;
		} else {
			showMentionDropdown = false;
			mentionFilter = '';
		}
		newNote = val;
	}

	function insertMention(userName) {
		const textarea = noteTextarea;
		if (!textarea) return;
		const val = newNote;
		const textBefore = val.substring(0, mentionCursorPos);
		const textAfter = val.substring(mentionCursorPos);
		// Replace the partial @mention with the full name
		const atStart = textBefore.lastIndexOf('@');
		const before = val.substring(0, atStart);
		const safeName = userName.replace(/\s+/g, '_');
		newNote = before + '@' + safeName + ' ' + textAfter;
		showMentionDropdown = false;
		mentionFilter = '';
		// Refocus textarea
		setTimeout(() => {
			textarea.focus();
			const newPos = before.length + safeName.length + 2;
			textarea.selectionStart = textarea.selectionEnd = newPos;
		}, 10);
	}

	function escapeHtml(s) {
		return String(s)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
	}

	function renderNoteWithMentions(text) {
		if (!text) return '';
		// Escape first to prevent XSS, then transform @mentions into coral chips.
		// Detection regex: /@([A-Za-z0-9_]+)/g — matches @username, @user_name, etc.
		return escapeHtml(text).replace(
			/@(\w+)/g,
			'<span class="mention-chip" data-user="$1">@$1</span>'
		);
	}

	// --- Export full candidate report (DOCX) ---
	async function exportReport() {
		const tk = (typeof window !== 'undefined') ? (localStorage.getItem('hire_token') || '') : '';
		const url = `/api/candidates/${candidateId}/export/report.docx${tk ? `?token=${encodeURIComponent(tk)}` : ''}`;
		window.open(url, '_blank');
	}

	// --- AI Summary ---
	function mdLite(s) {
		if (!s) return '';
		// Escape HTML entities BEFORE markdown transforms — content may include
		// candidate-injected payload (CV text/name) routed through the LLM.
		const esc = String(s)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
		return esc
			.replace(/^### (.+)$/gm, '<h4 style="font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:0.06em;margin:10px 0 4px 0;color:var(--color-primary);">$1</h4>')
			.replace(/^## (.+)$/gm, '<h3 style="font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:0.06em;margin:12px 0 4px 0;color:var(--color-primary);">$1</h3>')
			.replace(/\*\*(.+?)\*\*/g, '<strong style="font-weight:900;color:var(--color-on-surface);">$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			.replace(/^- (.+)$/gm, '<li style="margin-left:14px;list-style:disc;">$1</li>')
			.replace(/(<li[^>]*>.*<\/li>\n?)+/g, m => '<ul style="margin:4px 0;padding-left:0;">' + m + '</ul>')
			.replace(/\n\n+/g, '</p><p style="margin:6px 0;">')
			.replace(/^/, '<p style="margin:0 0 6px 0;">') + '</p>';
	}

	async function loadAiSummary() {
		aiSummaryLoading = true;
		aiSummary = null;
		showAiSummary = true;
		try {
			aiSummary = await apiJson(`/candidates/${candidateId}/ai-summary`);
		} catch (e) {
			console.error('AI Summary failed:', e);
			aiSummary = { error: e.message || 'Failed to generate summary' };
		}
		aiSummaryLoading = false;
	}

	function copyAiSummary() {
		if (!aiSummary?.summary) return;
		navigator.clipboard.writeText(aiSummary.ai_summary || aiSummary.summary || '');
		aiSummaryCopied = true;
		setTimeout(() => aiSummaryCopied = false, 2000);
	}

	// --- GitHub Analysis ---
	async function analyzeGithub() {
		if (!githubUrl.trim()) return;
		githubLoading = true;
		githubResult = null;
		githubError = '';
		try {
			githubResult = await apiJson(`/candidates/${candidateId}/analyze-github`, {
				method: 'POST',
				body: JSON.stringify({ github_url: githubUrl }),
			});
		} catch (e) {
			githubError = e.message || 'GitHub analysis failed';
		}
		githubLoading = false;
	}
</script>

{#if loading}
	<div class="flex items-center justify-center h-full">
		<div class="typing-indicator"><span></span><span></span><span></span></div>
	</div>
{:else if !candidate}
	<div class="flex items-center justify-center h-full">
		<p style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Candidate not found</p>
	</div>
{:else}
<div class="h-full flex flex-col overflow-hidden">

	<!-- ================================================================
		 HEADER BANNER
		 ================================================================ -->
	{#if candidate && !candidate.is_processed}
		<div style="background: var(--color-warning, #c98c2a); color: #fff; padding: 12px 32px; border-bottom: 1px solid var(--color-border, #d8d5cc); display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap;">
			<div style="font-size: 12px; font-weight: 700;">
				Pipeline NOT run yet — file uploaded only. Structured fields, embeddings, matches, scoring all pending.
			</div>
			<div style="display: flex; gap: 10px; align-items: center;">
				{#if candidate.pdf_path || candidate.file_name}
					<a href={`/api/candidates/${candidate.id}/file`} target="_blank" rel="noopener"
						style="font-size: 11px; padding: 6px 12px; background: var(--color-on-surface); color: var(--color-surface); border: 2px solid var(--color-on-surface); font-weight: 700; text-decoration: none; text-transform: uppercase; display:inline-flex; align-items:center; gap:4px;">
						<Eye size={13} stroke-width={2} /> VIEW FILE
					</a>
				{/if}
				<button class="send-btn"
					disabled={pipelineRunBusy}
					onclick={async () => {
						pipelineRunBusy = true;
						try {
							const r = await apiJson(`/candidates/${candidate.id}/process`, { method: 'POST' });
							console.log(`Pipeline started · run ${(r.run_id || '').slice(0, 8)}`);
							activeTab = 'pipeline';
							setTimeout(() => loadPipelineRuns(), 500);
						} catch (e) { alert(e.message || 'Failed'); }
						pipelineRunBusy = false;
					}}
					style="font-size: 12px; padding: 8px 18px; font-weight: 900;">
					{#if pipelineRunBusy}<Hourglass size={14} stroke-width={2} /> STARTING…{:else}▶ RUN PIPELINE{/if}
				</button>
			</div>
		</div>
	{/if}
	<!-- ============================================================
	     OPTION C — Thin top action bar (nav + actions + hide/view)
	     ============================================================ -->
	<div class="hire-topbar" style="background: var(--color-on-surface); color: var(--color-surface); border-bottom: 2px solid var(--color-surface); padding: 8px 16px; display:flex; align-items:center; gap:12px; flex-wrap:nowrap;">
		<!-- Left: nav -->
		<div style="display:flex; gap:10px; align-items:center; flex-shrink:0;">
			<a href="/candidates" class="hire-hdr-link" title="Back">
				<span class="material-symbols-outlined" style="font-size:14px;">arrow_back</span><span>Back</span>
			</a>
			{#if prevId}
				<button class="hire-hdr-link" onclick={goPrev} title="Prev">
					<span class="material-symbols-outlined" style="font-size:14px;">chevron_left</span><span>Prev</span>
				</button>
			{/if}
			{#if nextId}
				<button class="hire-hdr-link" onclick={goNext} title="Next">
					<span>Next</span><span class="material-symbols-outlined" style="font-size:14px;">chevron_right</span>
				</button>
			{/if}
			{#if navIds.length > 0 && navIndex >= 0}
				<span class="hire-hdr-meta-sm">{navIndex + 1} / {navIds.length}</span>
			{/if}
		</div>
		<!-- Spacer -->
		<div style="flex:1;"></div>
		<!-- Right: presence + actions -->
		<div style="display:flex; gap:10px; align-items:center; flex-shrink:0;">
			<Presence targetType="candidate" targetId={candidate.id} />
			<QuickActions
				candidateId={candidate.id}
				candidate={candidate}
				onAiSummary={loadAiSummary}
				onEmail={() => showEmailCompose = true}
				onExportReport={exportReport}
			/>
		</div>
	</div>

	<div class="hire-header-banner" style="display:none;">
		<div class="hire-hdr-wrap" style="max-width: 1400px; margin: 0 auto; padding: 16px 20px;">
			<!-- ROW 1: BACK · PREV · NEXT · X/N            HIDE HEADER · VIEW CV (single flex row) -->
			<div class="hire-hdr-row1" style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:nowrap; margin-bottom:14px;">
				<div style="display:flex; gap:14px; align-items:center; flex-wrap:wrap; min-width:0;">
					<a href="/candidates" class="hire-hdr-link" title="Back to candidates list">
						<span class="material-symbols-outlined" style="font-size: 14px;">arrow_back</span>
						<span>Back</span>
					</a>
					{#if prevId}
						<button class="hire-hdr-link" onclick={goPrev} title="Previous candidate">
							<span class="material-symbols-outlined" style="font-size: 14px;">chevron_left</span>
							<span>Prev</span>
						</button>
					{/if}
					{#if nextId}
						<button class="hire-hdr-link" onclick={goNext} title="Next candidate">
							<span>Next</span>
							<span class="material-symbols-outlined" style="font-size: 14px;">chevron_right</span>
						</button>
					{/if}
					{#if navIds.length > 0 && navIndex >= 0}
						<span class="hire-hdr-meta-sm">{navIndex + 1} / {navIds.length}</span>
					{/if}
				</div>
				<div style="display:flex; gap:10px; align-items:center; flex-shrink:0; margin-left:auto;">
					<button class="hire-hdr-link" title="Hide header">
						<span class="material-symbols-outlined" style="font-size: 14px;">expand_less</span>
						<span>Hide Header</span>
					</button>
					<button class="hire-hdr-btn" onclick={() => showPdfViewer = true} title="View CV">
						<span class="material-symbols-outlined" style="font-size: 14px;">description</span>
						View CV
					</button>
				</div>
			</div>

			<!-- ROW 2: avatar + name + subline -->
			<div class="hire-hdr-row2 hire-hdr-identity">
				<div class="hire-hdr-avatar">{initials(candidate.name)}</div>
				<div class="hire-hdr-id-text">
					<h1 class="hire-hdr-name">{candidate.name || 'Unknown'}</h1>
					<div class="hire-hdr-subline">
						{#if candidate.current_role}
							<span>{candidate.current_role}{candidate.current_company ? ` at ${candidate.current_company}` : ''}</span>
						{/if}
						{#if candidate.total_experience_years}
							<span class="hire-hdr-sep">|</span>
							<span>{candidate.total_experience_years} yr exp</span>
						{/if}
					</div>
				</div>
			</div>

			<!-- ROW 3: SENIORITY · Q · UPLOAD · +TAG  — all chips siblings, single nowrap row -->
			<div class="hire-hdr-row3 hire-hdr-chips" style="display:flex; flex-wrap:nowrap; gap:8px; align-items:center; overflow:visible; margin-bottom:10px;">
				{#if candidate.seniority_level}
					<span class="hire-hdr-chip hire-hdr-chip-prime">{candidate.seniority_level}</span>
				{/if}
				{#if candidate.quality_score}
					<span class="hire-hdr-chip" style="border-color: {scoreColor(candidate.quality_score)}; color: {scoreColor(candidate.quality_score)};">Q: {candidate.quality_score}/100</span>
				{/if}
				{#if opusVerified}
					<span class="hire-hdr-chip hire-hdr-chip-ok" style="display:inline-flex;align-items:center;gap:4px;"><Check size={12} stroke-width={2.5} /> {verifiedCount} VERIFIED</span>
				{/if}
				<button class="hire-hdr-chip hire-hdr-chip-action" title="Upload">
					<span class="material-symbols-outlined" style="font-size: 12px;">upload</span>
					Upload
				</button>
				<button class="hire-hdr-chip hire-hdr-chip-action" title="Add tag">+ Tag</button>
				{#each candidateFlags.slice(0, 6) as flag}
					<span title="{flag.title}: {flag.description} ({flag.position_title || ''})"
						class="hire-hdr-flag" style="background: {flag.flag_type === 'red' ? 'var(--color-error, #c4571a)' : flag.flag_type === 'amber' ? 'var(--color-warning, #c98c2a)' : '#3a8a4f'};"></span>
				{/each}
			</div>

			<!-- ROW 4: contact items + latency timer SAME flex row, all siblings -->
			<div class="hire-hdr-row4 hire-hdr-contact" style="display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:nowrap; margin-bottom:14px; padding-top:4px;">
				<div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap; min-width:0;">
					{#if candidate.location}
						<span class="hire-hdr-link" title="Location">
							<span class="material-symbols-outlined" style="font-size: 14px;">location_on</span>
							<span>{candidate.location}</span>
						</span>
					{/if}
					{#if candidate.email}
						<a href="mailto:{candidate.email}" class="hire-hdr-link" title="Email">
							<span class="material-symbols-outlined" style="font-size: 14px;">mail</span>
							<span>{candidate.email}</span>
						</a>
					{/if}
					{#if candidate.phone}
						<span class="hire-hdr-link" title="Phone">
							<span class="material-symbols-outlined" style="font-size: 14px;">phone</span>
							<span>{candidate.phone}</span>
						</span>
					{/if}
					{#if candidate.linkedin || candidate.linkedin_url}
						<a href={candidate.linkedin || candidate.linkedin_url} target="_blank" rel="noopener" class="hire-hdr-link" title="LinkedIn">
							<span class="material-symbols-outlined" style="font-size: 14px;">link</span>
							<span>LinkedIn</span>
						</a>
					{/if}
				</div>
				<div style="display:flex; align-items:center; gap:12px; margin-left:auto; flex-shrink:0;">
					{#if pipelineLatencyMs > 0}
						<span class="hire-hdr-meta-sm" title="Pipeline latency">
							<span class="material-symbols-outlined" style="font-size: 13px; vertical-align: middle;">schedule</span>
							{fmtLatency(pipelineLatencyMs)}
						</span>
					{/if}
					{#if pipelineCost > 0}
						<span class="hire-hdr-meta-sm" title="Pipeline cost">
							<span class="material-symbols-outlined" style="font-size: 13px; vertical-align: middle;">savings</span>
							{fmtCost(pipelineCost)}
						</span>
					{/if}
				</div>
			</div>

			<!-- ROW 5: full-width QuickActions -->
			<div class="hire-hdr-row5 hire-hdr-actions">
				<QuickActions
					candidateId={candidate.id}
					candidate={candidate}
					onAiSummary={loadAiSummary}
					onEmail={() => showEmailCompose = true}
				/>
			</div>
		</div>
	</div>

	<!-- ================================================================
		 TAB NAVIGATION
		 ================================================================ -->
	<!-- Duplicate Warning Banner (single-row, dismissible) -->
	{#if duplicates.length > 0 && !duplicatesDismissed}
		<div style="max-width: 1100px; margin: 8px auto; width: 100%;">
			<div class="ink-border p-2 animate-fade-up" style="background: #fff8e1; border-left: 4px solid var(--color-warning);">
				<div class="flex items-center justify-between gap-3">
					<div class="flex items-center gap-2">
						<span class="material-symbols-outlined" style="font-size: 16px; color: var(--color-warning);">warning</span>
						<span style="font-size: 11px; font-weight: 900; text-transform: uppercase; color: var(--color-warning);">
							{duplicates.length} Potential Duplicate{duplicates.length > 1 ? 's' : ''}
						</span>
					</div>
					<div class="flex items-center gap-2">
						<button onclick={() => showDuplicates = !showDuplicates}
							style="background: none; border: 1px solid var(--color-warning); color: var(--color-warning); padding: 2px 10px; font-size: 10px; font-weight: 700; text-transform: uppercase; cursor: pointer;">
							{showDuplicates ? '▴ Hide' : '▾ Review'}
						</button>
						<button onclick={dismissDuplicates}
							title="Dismiss"
							style="background: none; border: 1px solid var(--color-warning); color: var(--color-warning); padding: 2px 8px; font-size: 12px; font-weight: 900; cursor: pointer; line-height: 1;">
							×
						</button>
					</div>
				</div>
				{#if showDuplicates}
					<div class="mt-3" style="border-top: 1px solid var(--color-warning);">
						{#each duplicates as dup}
							<div class="flex items-center gap-3 py-2" style="border-bottom: 1px solid rgba(255,157,0,0.2);">
								<div class="avatar-user" style="width: 28px; height: 28px; font-size: 10px;">{(dup.name || '?')[0]}</div>
								<div class="flex-1">
									<a href="/candidates/{dup.id}" style="font-size: 12px; font-weight: 900; color: var(--color-on-surface); text-decoration: none;">{dup.name}</a>
									<span style="font-size: 10px; color: var(--color-on-surface-dim);"> — {dup.email || 'no email'}</span>
									{#if dup.sim || dup.similarity}
										<span style="font-size: 9px; padding: 1px 5px; border: 1px solid var(--color-warning); color: var(--color-warning); font-weight: 700; margin-left: 4px;">
											{Math.round((dup.sim || dup.similarity) * 100)}% match
										</span>
									{/if}
								</div>
								<button class="send-btn" style="font-size: 9px; padding: 3px 10px;" onclick={() => mergeDuplicate(dup.id)} disabled={merging}>
									{merging ? '...' : 'Merge'}
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- ============================================================
	     OPTION C — 3-col layout: [sidebar identity 240px] [doc] [tabs+content]
	     ============================================================ -->
	<div class="hire-c-wrap" style="display:flex; align-items:stretch; gap:0; height: calc(100vh - 110px); overflow:hidden;">
		<!-- SIDEBAR — identity card -->
		<aside class="hire-c-sidebar ink-border" style="width:260px; flex-shrink:0; padding:18px 14px; background:var(--color-surface); border-right:2px solid var(--color-on-surface); display:flex; flex-direction:column; gap:14px; overflow-y:auto;">
			<div style="width:90px; height:90px; background:var(--color-primary); color:var(--color-on-primary); display:flex; align-items:center; justify-content:center; font-size:32px; font-weight:900; font-family:'Space Grotesk'; border:2px solid var(--color-on-surface); box-shadow:4px 4px 0 var(--color-on-surface);">
				{initials(candidate.name)}
			</div>
			<div>
				<h1 style="font-size:20px; font-weight:900; text-transform:uppercase; line-height:1.1; margin:0 0 6px 0; letter-spacing:0.02em;">{candidate.name || 'Unknown'}</h1>
				<div style="font-size:12px; line-height:1.4; opacity:0.85;">
					{#if candidate.current_role}<div>{candidate.current_role}</div>{/if}
					{#if candidate.current_company}<div style="opacity:0.7;">at {candidate.current_company}</div>{/if}
					{#if candidate.total_experience_years}<div style="margin-top:4px; font-weight:700;">{candidate.total_experience_years} yr exp</div>{/if}
				</div>
			</div>
			<!-- Chips column -->
			<div style="display:flex; flex-direction:column; gap:6px;">
				{#if candidate.seniority_level}
					<span class="hire-hdr-chip hire-hdr-chip-prime" style="align-self:flex-start;">{candidate.seniority_level}</span>
				{/if}
				{#if candidate.quality_score}
					<span class="hire-hdr-chip" style="align-self:flex-start; border-color:{scoreColor(candidate.quality_score)}; color:{scoreColor(candidate.quality_score)};">Q: {candidate.quality_score}/100</span>
				{/if}
				{#if opusVerified}
					<span class="hire-hdr-chip hire-hdr-chip-ok" style="align-self:flex-start; display:inline-flex; align-items:center; gap:4px;"><Check size={12} stroke-width={2.5} /> {verifiedCount} VERIFIED</span>
				{/if}
			</div>
			<!-- Contact -->
			<div style="display:flex; flex-direction:column; gap:8px; font-size:11px; padding-top:10px; border-top:1px solid var(--color-on-surface);">
				{#if candidate.location}
					<span style="display:flex; align-items:center; gap:6px;"><span class="material-symbols-outlined" style="font-size:14px;">location_on</span>{candidate.location}</span>
				{/if}
				{#if candidate.email}
					<a href="mailto:{candidate.email}" style="display:flex; align-items:center; gap:6px; color:inherit; word-break:break-all;"><span class="material-symbols-outlined" style="font-size:14px;">mail</span>{candidate.email}</a>
				{/if}
				{#if candidate.phone}
					<span style="display:flex; align-items:center; gap:6px;"><span class="material-symbols-outlined" style="font-size:14px;">phone</span>{candidate.phone}</span>
				{/if}
				{#if candidate.linkedin || candidate.linkedin_url}
					<a href={candidate.linkedin || candidate.linkedin_url} target="_blank" rel="noopener" style="display:flex; align-items:center; gap:6px; color:inherit;"><span class="material-symbols-outlined" style="font-size:14px;">link</span>LinkedIn</a>
				{/if}
			</div>
			<!-- Actions: upload + tag -->
			<div style="display:flex; flex-direction:column; gap:6px; padding-top:10px; border-top:1px solid var(--color-on-surface);">
				<button class="hire-hdr-chip hire-hdr-chip-action" style="justify-content:center;">
					<span class="material-symbols-outlined" style="font-size:13px;">upload</span> Upload
				</button>
				<button class="hire-hdr-chip hire-hdr-chip-action" style="justify-content:center;">+ Tag</button>
			</div>
			<!-- AI Executive Summary (auto-generated) -->
			<div style="padding-top:10px; border-top:1px solid var(--color-on-surface);">
				<div style="font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
					<span class="material-symbols-outlined" style="font-size:13px;">auto_awesome</span>
					AI Summary
					{#if aiSummaryLoading}
						<span style="font-size:9px; opacity:0.7; font-weight:400;">· generating…</span>
					{/if}
				</div>
				{#if aiSummaryLoading}
					<div style="font-size:11px; opacity:0.6; line-height:1.5;">
						<div style="height:8px; background:var(--color-on-surface); opacity:0.15; margin-bottom:4px;"></div>
						<div style="height:8px; background:var(--color-on-surface); opacity:0.15; margin-bottom:4px; width:80%;"></div>
						<div style="height:8px; background:var(--color-on-surface); opacity:0.15; width:60%;"></div>
					</div>
				{:else if aiSummary?.ai_summary}
					<div class="ai-sum-body" style="font-size:11px; line-height:1.55; max-height:320px; overflow-y:auto;">{@html mdLite(aiSummary.ai_summary)}</div>
				{:else if aiSummary?.error}
					<div style="font-size:11px; opacity:0.7; color:#ff3b30;">Failed to generate</div>
				{:else}
					<div style="font-size:11px; opacity:0.5;">Pending pipeline run</div>
				{/if}
			</div>

			<!-- Pipeline meta -->
			{#if pipelineLatencyMs > 0 || pipelineCost > 0}
				<div style="display:flex; flex-direction:column; gap:4px; font-size:10px; padding-top:10px; border-top:1px solid var(--color-on-surface); opacity:0.8;">
					{#if pipelineLatencyMs > 0}
						<span style="display:flex; align-items:center; gap:6px;"><span class="material-symbols-outlined" style="font-size:13px;">schedule</span>{fmtLatency(pipelineLatencyMs)}</span>
					{/if}
					{#if pipelineCost > 0}
						<span style="display:flex; align-items:center; gap:6px;"><span class="material-symbols-outlined" style="font-size:13px;">savings</span>{fmtCost(pipelineCost)}</span>
					{/if}
				</div>
			{/if}
		</aside>
		<!-- MAIN — SplitPane (doc + tabs) -->
		<div style="flex:1; min-width:0; height:100%; overflow:hidden;">
	<SplitPane defaultPercent={45} storageKey="hire_profile_split">
		{#snippet left()}
			<div style="padding: 10px; display: flex; flex-direction: column; height: 100%;">
				<div style="flex: 1; min-height: 0;">
					<DocViewer
						candidateId={candidate.id}
						fileType={candidate.file_type || ''}
						fileName={candidate.file_name || ''}
					/>
				</div>
				<div class="hire-doc-hint">
					<span class="material-symbols-outlined" style="font-size: 13px;">tips_and_updates</span>
					<span>Click any field on right to highlight on source</span>
				</div>
			</div>
		{/snippet}
		{#snippet right()}
	<div style="width: 100%; position: sticky; top: 0; z-index: 20; background: var(--color-surface); border-bottom: 2px solid var(--color-on-surface);">
		<div class="hire-tabs-wrap">
			{#if tabsCanScrollLeft}
				<button class="hire-tabs-arrow hire-tabs-arrow-left" onclick={() => scrollTabs(-1)} title="Scroll tabs left">‹</button>
			{/if}
			<div class="dash-tabs hire-tabs-strip hire-tabs-slim" bind:this={tabsStripEl} onscroll={updateTabsScroll}>
				{#each tabs as tab}
					{@const count = tabBadge(tab.id)}
					<button
						class="dash-tab hire-tab-slim"
						class:dash-tab-active={activeTab === tab.id}
						onclick={() => activeTab = tab.id}
					>
						<span class="material-symbols-outlined hire-tab-icon">{tab.icon}</span>
						<span class="dash-tab-value hire-tab-label">{tab.label}</span>
						{#if count > 0}
							<span class="hire-tab-badge">{count}</span>
						{/if}
					</button>
				{/each}
			</div>
			{#if tabsCanScrollRight}
				<button class="hire-tabs-arrow hire-tabs-arrow-right" onclick={() => scrollTabs(1)} title="Scroll tabs right">›</button>
			{/if}
		</div>
	</div>

	<!-- ================================================================
		 TAB CONTENT
		 ================================================================ -->
	<div class="flex-1 overflow-y-auto" style="padding-bottom: 120px; height: calc(100vh - 200px);">
		<div style="width: 100%;">
			<div class="dash-panel section-animate" style="min-height: 400px;">

				<!-- ============================
					 PROFILE TAB
					 ============================ -->
				{#if activeTab === 'profile'}

					<!-- Quick actions row -->
					<div class="mb-3" style="display: flex; gap: 8px; flex-wrap: wrap;">
						<button
							class="btn-primary"
							style="background: var(--color-accent); color: #fff; border: 1px solid var(--color-accent); padding: 8px 16px; border-radius: var(--radius-sm); font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;"
							onclick={() => showSchedulePanel = true}>
							<span class="material-symbols-outlined" style="font-size: 16px;">event</span>
							Schedule interview
						</button>
					</div>

					<!-- AI POSITION MATCHES (compact) -->
					<CandidateAIMatches candidateId={candidateId} mode="compact" />

					<!-- AT-A-GLANCE (5-card grid) -->
					<div class="mb-4">
						<div class="dark-title-bar mb-0 flex items-center gap-2">
							<span class="material-symbols-outlined" style="font-size: 14px;">auto_awesome</span>
							At-a-glance
						</div>
						<div class="ink-border hire-glance-grid" style="border-top: none; background: var(--color-surface);">
							<button class="hire-glance-cell" onclick={() => activeTab = 'experience'} title="View experience">
								<span class="hire-glance-num">{candidate.total_experience_years || '—'}{candidate.total_experience_years ? 'y' : ''}</span>
								<span class="hire-glance-lbl">Experience</span>
							</button>
							<button class="hire-glance-cell" onclick={() => scrollToSelector('[data-section="position-matches"]')} title="View quality">
								<span class="hire-glance-num">{candidate.quality_score ?? '—'}</span>
								<span class="hire-glance-lbl">Qual Score</span>
							</button>
							<button class="hire-glance-cell" onclick={() => scrollToSelector('[data-section="demographics"]')} title="View demographics">
								<span class="hire-glance-num" style="display:inline-flex;align-items:center;gap:2px;"><Check size={13} stroke-width={2.5} />{verifiedCount}</span>
								<span class="hire-glance-lbl">Verified</span>
							</button>
							<button class="hire-glance-cell" onclick={() => activeTab = 'assignments'} title="View positions">
								<span class="hire-glance-num">{positionMatches.length}</span>
								<span class="hire-glance-lbl">Positions</span>
							</button>
							<button class="hire-glance-cell" onclick={() => activeTab = 'profile'} title="Tags">
								<span class="hire-glance-num">{tags.length}</span>
								<span class="hire-glance-lbl">Tags</span>
							</button>
							{#if candidate.quality_score}
								<div class="hire-glance-cell" style="cursor: default;" title="Δ vs avg score">
									<span class="hire-glance-num" style="color: {scoreColor(candidate.quality_score)};">Δ {candidate.quality_score >= 70 ? '+' : ''}{candidate.quality_score - 70}</span>
									<span class="hire-glance-lbl">vs avg</span>
								</div>
							{/if}
						</div>
					</div>

					<!-- Summary -->
					{#if candidate.summary_short || candidate.summary_detailed}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Summary</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								{#if candidate.summary_short}
									<p style="font-size: 14px; font-weight: 700; line-height: 1.6; margin-bottom: 12px;">
										{candidate.summary_short}
									</p>
								{/if}
								{#if candidate.summary_detailed}
									<p style="font-size: 13px; line-height: 1.7; color: var(--color-on-surface-dim);">
										{candidate.summary_detailed}
									</p>
								{/if}
							</div>
						</div>
					{/if}

					<!-- Education -->
					{#if education.length > 0}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Education</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-col gap-3">
									{#each education as edu, i}
										<div class="flex items-start gap-3" style:animation-delay="{i * 0.05}s">
											<div style="width: 40px; height: 40px; background: var(--color-surface-highest); display: flex; align-items: center; justify-content: center; border: 2px solid var(--color-on-surface); flex-shrink: 0;">
												<span class="material-symbols-outlined" style="font-size: 18px;">school</span>
											</div>
											<div>
												<div style="font-size: 14px; font-weight: 900;">{edu.degree || ''} {edu.field ? `in ${edu.field}` : ''}</div>
												<div style="font-size: 12px; color: var(--color-on-surface-dim);">
													{edu.institution || 'Unknown Institution'}{edu.year ? ` — ${edu.year}` : ''}
												</div>
												{#if edu.gpa}
													<div style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 2px;">GPA: {edu.gpa}</div>
												{/if}
											</div>
										</div>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Certifications -->
					{#if certifications.length > 0}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Certifications</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-wrap gap-2">
									{#each certifications as cert}
										<div style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); font-size: 12px; font-weight: 700;">
											<span class="material-symbols-outlined" style="font-size: 14px; color: var(--color-primary);">verified</span>
											{#if typeof cert === 'string'}
												{cert}
											{:else}
												{cert.name || cert.title || cert.certification || ''}{cert.issuer ? ` — ${cert.issuer}` : ''}{cert.year ? ` (${cert.year})` : ''}
											{/if}
										</div>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Projects -->
					{#if projects.length > 0}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Projects</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-col gap-3">
									{#each projects as proj}
										<div style="border-left: 3px solid var(--color-primary); padding: 8px 14px;">
											<div style="font-size: 13px; font-weight: 900; text-transform: uppercase;">
												{#if typeof proj === 'string'}
													{proj}
												{:else}
													{proj.name || proj.title || 'Project'}
												{/if}
											</div>
											{#if typeof proj === 'object' && proj.description}
												<p style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 4px; line-height: 1.5;">{proj.description}</p>
											{/if}
											{#if typeof proj === 'object' && proj.technologies}
												<div class="flex gap-1 mt-2 flex-wrap">
													{#each (Array.isArray(proj.technologies) ? proj.technologies : [proj.technologies]) as tech}
														<span style="font-size: 9px; padding: 1px 6px; border: 1px solid var(--color-outline); text-transform: uppercase; font-weight: 700;">{tech}</span>
													{/each}
												</div>
											{/if}
											{#if typeof proj === 'object' && proj.url}
												<a href={proj.url} target="_blank" rel="noopener" style="font-size: 11px; color: var(--color-primary); margin-top: 4px; display: inline-block;">{proj.url}</a>
											{/if}
										</div>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Referral -->
					<div class="mb-6">
						<div class="dark-title-bar mb-0" style="font-size: 11px;">Referral</div>
						<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
							{#if referral}
								<div class="flex items-center gap-3">
									<span class="material-symbols-outlined" style="font-size: 20px; color: var(--color-primary);">person_add</span>
									<div>
										<div style="font-size: 13px; font-weight: 900;">{referral.referrer_name}</div>
										{#if referral.referrer_email}
											<div style="font-size: 11px; color: var(--color-on-surface-dim);">{referral.referrer_email}</div>
										{/if}
										{#if referral.notes}
											<div style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 4px;">{referral.notes}</div>
										{/if}
									</div>
								</div>
							{:else if showReferralForm}
								<div style="display: flex; flex-direction: column; gap: 8px;">
									<div class="flex gap-2">
										<input bind:value={refName} placeholder="Referrer name *" style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright);" />
										<input bind:value={refEmail} placeholder="Email" style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright);" />
									</div>
									<input bind:value={refNotes} placeholder="Notes (optional)" style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright);" />
									<div class="flex gap-2">
										<button class="send-btn" style="font-size: 10px; padding: 4px 12px;" onclick={saveReferral} disabled={!refName.trim() || savingReferral}>
											{savingReferral ? 'Saving...' : 'Save'}
										</button>
										<button class="btn-secondary" style="font-size: 10px; padding: 4px 12px;" onclick={() => showReferralForm = false}>Cancel</button>
									</div>
								</div>
							{:else}
								<button class="btn-secondary" style="font-size: 10px;" onclick={() => showReferralForm = true}>
									<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">person_add</span> Add Referral
								</button>
							{/if}
						</div>
					</div>

					<!-- Position Matches -->
					{#if positionMatches.length > 0}
						<div class="mb-6" data-section="position-matches">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Position Matches</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								{#each positionMatches as pm}
									<div class="candidate-row flex items-center justify-between mb-2">
										<div>
											<div style="font-size: 13px; font-weight: 900;">{pm.position_title || pm.title || 'Position'}</div>
											<div style="font-size: 11px; color: var(--color-on-surface-dim);">
												{pm.department || ''}{pm.stage ? ` — Stage: ${pm.stage}` : ''}
											</div>
										</div>
										{#if pm.composite_score || pm.score}
											<div class="flex items-center gap-3" style="min-width: 160px;">
												<div class="score-bar flex-1" style="height: 10px;">
													<div
														class="score-bar-fill {scoreClass(pm.composite_score || pm.score || 0)}"
														style="width: {pm.composite_score || pm.score || 0}%;"
													></div>
												</div>
												<span style="font-size: 13px; font-weight: 900; color: {scoreColor(pm.composite_score || pm.score || 0)};">
													{Math.round(pm.composite_score || pm.score || 0)}%
												</span>
											</div>
										{/if}
									</div>
								{/each}
							</div>
						</div>
					{/if}

					<!-- GitHub Analysis -->
					<div class="mb-6">
						<div class="dark-title-bar mb-0 flex items-center gap-2" style="font-size: 11px;">
							<span class="material-symbols-outlined" style="font-size: 14px;">code</span>
							Analyze GitHub
						</div>
						<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
							<div class="flex gap-2 mb-3">
								<input
									type="url"
									bind:value={githubUrl}
									placeholder="https://github.com/username"
									style="flex: 1; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; font-weight: 700; background: var(--color-surface-bright);"
									onkeydown={(e) => { if (e.key === 'Enter') analyzeGithub(); }}
								/>
								<button
									class="send-btn"
									style="font-size: 10px; padding: 8px 16px;"
									disabled={githubLoading || !githubUrl.trim()}
									onclick={analyzeGithub}
								>
									{#if githubLoading}
										<div class="typing-indicator" style="display: inline-flex;"><span></span><span></span><span></span></div>
									{:else}
										Analyze
									{/if}
								</button>
							</div>

							{#if githubError}
								<div style="background: var(--color-error-container, #ffe0e0); border-left: 3px solid var(--color-error); padding: 8px 12px; font-size: 12px; font-weight: 700;">
									{githubError}
								</div>
							{/if}

							{#if githubResult}
								<div class="animate-fade-up">
									<!-- Languages Chart -->
									{#if githubResult.analysis?.languages || githubResult.languages}
										{@const langs = githubResult.analysis?.languages || githubResult.languages || {}}
										{@const langEntries = Object.entries(langs).sort((a, b) => b[1] - a[1]).slice(0, 10)}
										{@const maxLang = langEntries[0]?.[1] || 1}
										<div class="mb-4">
											<div style="font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;">Languages</div>
											{#each langEntries as [lang, count]}
												<div class="flex items-center gap-2 mb-1">
													<span style="font-size: 10px; font-weight: 700; min-width: 80px; text-transform: uppercase;">{lang}</span>
													<div style="flex: 1; height: 8px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);">
														<div style="height: 100%; width: {(count / maxLang) * 100}%; background: var(--color-primary);"></div>
													</div>
													<span style="font-size: 10px; font-weight: 700; min-width: 32px; text-align: right;">{typeof count === 'number' && count < 100 ? count : Math.round(count / 1024) + 'K'}</span>
												</div>
											{/each}
										</div>
									{/if}

									<!-- Top Repos -->
									{#if githubResult.analysis?.top_repos || githubResult.top_repos}
										{@const repos = githubResult.analysis?.top_repos || githubResult.top_repos || []}
										<div class="mb-4">
											<div style="font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;">Top Repositories</div>
											{#each repos.slice(0, 5) as repo}
												<div class="flex items-center justify-between mb-2" style="padding: 6px 10px; border: 1px solid var(--color-outline-variant); background: var(--color-surface-bright);">
													<div>
														<div style="font-size: 12px; font-weight: 900;">{repo.name || repo.repo}</div>
														{#if repo.description}
															<div style="font-size: 10px; color: var(--color-on-surface-dim); margin-top: 1px;">{repo.description}</div>
														{/if}
													</div>
													<div class="flex items-center gap-3" style="font-size: 10px; color: var(--color-on-surface-dim);">
														{#if repo.stars !== undefined}
															<span style="font-weight: 700;">&#9733; {repo.stars}</span>
														{/if}
														{#if repo.language}
															<span class="tag-label" style="font-size: 8px;">{repo.language}</span>
														{/if}
													</div>
												</div>
											{/each}
										</div>
									{/if}

									<!-- Assessment -->
									{#if githubResult.analysis?.assessment || githubResult.assessment}
										<div style="border-left: 3px solid var(--color-primary); padding: 10px 14px; background: var(--color-surface-bright); font-size: 13px; line-height: 1.6;">
											{githubResult.analysis?.assessment || githubResult.assessment}
										</div>
									{/if}
								</div>
							{/if}
						</div>
					</div>

					<!-- Meta info -->
					<div class="flex gap-4 flex-wrap" style="font-size: 11px; color: var(--color-on-surface-dim); clear: both;">
						{#if candidate.page_count}
							<span><strong>Pages:</strong> {candidate.page_count}</span>
						{/if}
						{#if candidate.created_at}
							<span><strong>Added:</strong> {formatDate(candidate.created_at)}</span>
						{/if}
						{#if candidate.updated_at}
							<span><strong>Updated:</strong> {formatDate(candidate.updated_at)}</span>
						{/if}
						{#if candidate.source}
							<span><strong>Source:</strong> {candidate.source}</span>
						{/if}
					</div>

					<!-- DEMOGRAPHICS section -->
					{@const demoFields = [
						{ key: 'dob', label: 'DOB' },
						{ key: 'national_id', label: 'National ID / NRC' },
						{ key: 'gender', label: 'Gender' },
						{ key: 'marital_status', label: 'Marital Status' },
						{ key: 'nationality', label: 'Nationality' },
						{ key: 'religion', label: 'Religion' },
						{ key: 'height', label: 'Height' },
						{ key: 'weight', label: 'Weight' },
						{ key: 'father_name', label: "Father's Name" },
					]}
					<div class="mb-6 mt-6" data-section="demographics" style="clear: both;">
						<div class="dark-title-bar mb-0 flex items-center justify-between" style="font-size: 11px;">
							<span>DEMOGRAPHICS</span>
							{#if opusVerified}
								<span style="font-size: 9px; padding: 2px 8px; background: #3a8a4f; color: #fff; border-radius:4px; font-weight: 900; letter-spacing: 0.06em; display:inline-flex; align-items:center; gap:3px;"><Check size={10} stroke-width={2.5} /> Opus verified</span>
							{/if}
						</div>
						<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
							<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px 18px;">
								{#each demoFields as f}
									{@const val = candidate[f.key]}
									{@const present = val !== null && val !== undefined && val !== ''}
									<div style="display: flex; flex-direction: column; gap: 2px;">
										<div style="font-size: 9px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">{f.label}</div>
										<div style="font-size: 13px; font-weight: 700; display: flex; align-items: center; gap: 6px;">
											<span>{present ? val : '—'}</span>
											{#if present}
												<span title="Verified by Opus" style="display: inline-flex; align-items: center; gap: 3px; padding: 1px 5px; background: #3a8a4f; color: #fff; border-radius:3px; font-size: 8px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.04em;">
													<Check size={9} stroke-width={2.5} /> verified
												</span>
											{/if}
										</div>
									</div>
								{/each}
							</div>
						</div>
					</div>

				<!-- ============================
					 EXPERIENCE TAB
					 ============================ -->
				{:else if activeTab === 'experience'}

					{#if experience.length === 0}
						<div class="flex flex-col items-center justify-center py-16" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">work_off</span>
							<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No experience data</p>
						</div>
					{:else}
						<!-- LinkedIn-style timeline -->
						<div style="position: relative; padding-left: 32px;">
							<!-- Vertical timeline line -->
							<div style="position: absolute; left: 12px; top: 8px; bottom: 8px; width: 3px; background: var(--color-on-surface);"></div>

							{#each experience as exp, i}
								<div class="mb-6 animate-fade-up" style="position: relative; animation-delay: {i * 0.08}s;">
									<!-- Timeline dot -->
									<div style="position: absolute; left: -26px; top: 8px; width: 14px; height: 14px; background: {i === 0 ? 'var(--color-primary-container)' : 'var(--color-surface)'}; border: 3px solid var(--color-on-surface);"></div>

									<!-- Job card -->
									<div class="ink-border stamp-shadow-sm" style="background: var(--color-surface); padding: 16px 20px;">
										<div class="flex items-start justify-between gap-4">
											<div>
												<div style="font-size: 16px; font-weight: 900; text-transform: uppercase; letter-spacing: -0.01em;">
													{exp.role || exp.title || exp.position || 'Role'}
												</div>
												<div style="font-size: 13px; font-weight: 700; color: var(--color-primary); margin-top: 2px;">
													{exp.company || exp.organization || ''}
												</div>
											</div>
											<div style="text-align: right; flex-shrink: 0;">
												<div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--color-on-surface-dim);">
													{exp.start_date || ''} {exp.start_date || exp.end_date ? '—' : ''} {exp.end_date || 'Present'}
												</div>
												{#if exp.duration}
													<div style="font-size: 10px; color: var(--color-on-surface-dim); margin-top: 2px;">{exp.duration}</div>
												{/if}
											</div>
										</div>

										{#if exp.location}
											<div class="flex items-center gap-1 mt-2" style="font-size: 11px; color: var(--color-on-surface-dim);">
												<span class="material-symbols-outlined" style="font-size: 12px;">location_on</span>
												{exp.location}
											</div>
										{/if}

										{#if exp.description}
											<p style="font-size: 12px; line-height: 1.6; margin-top: 10px; color: var(--color-on-surface); white-space: pre-line;">
												{exp.description}
											</p>
										{/if}

										{#if exp.highlights?.length}
											<ul style="margin-top: 8px; padding-left: 16px;">
												{#each exp.highlights as h}
													<li style="font-size: 12px; line-height: 1.5; color: var(--color-on-surface-dim); margin-bottom: 2px;">{h}</li>
												{/each}
											</ul>
										{/if}

										{#if exp.skills?.length || exp.technologies?.length}
											<div class="flex gap-1 mt-3 flex-wrap">
												{#each (exp.skills || exp.technologies || []) as skill}
													<span style="font-size: 9px; padding: 1px 6px; border: 1px solid var(--color-outline); text-transform: uppercase; font-weight: 700;">{skill}</span>
												{/each}
											</div>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}

				<!-- ============================
					 SKILLS TAB
					 ============================ -->
				{:else if activeTab === 'skills'}

					<!-- Skills Radar Chart -->
					{#if positionMatches.length > 0 && radarChartOptions}
						<div class="mb-6">
							<div class="dark-title-bar mb-0 flex items-center justify-between" style="font-size: 11px;">
								<span class="flex items-center gap-2">
									<span class="material-symbols-outlined" style="font-size: 14px;">radar</span>
									Skills Radar — Candidate vs Requirements
								</span>
								{#if positionMatches.length > 1}
									<select
										bind:value={selectedRadarPosition}
										style="background: var(--color-on-surface); color: var(--color-surface); border: 1px solid rgba(255,255,255,0.3); padding: 2px 8px; font-family: 'Space Grotesk'; font-size: 10px; font-weight: 700; text-transform: uppercase;"
									>
										{#each positionMatches as pm, i}
											<option value={i}>{pm.position_title || pm.title || `Position ${i + 1}`}</option>
										{/each}
									</select>
								{/if}
							</div>
							<div class="ink-border" style="border-top: none; background: var(--color-surface); padding: 16px;">
								{#if positionMatches.length > 1}
									<div style="font-size: 11px; font-weight: 700; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;">
										Comparing against: {positionMatches[selectedRadarPosition]?.position_title || positionMatches[selectedRadarPosition]?.title || 'Position'}
									</div>
								{/if}
								<Chart options={radarChartOptions} height="320px" />
								<div class="flex items-center justify-center gap-6 mt-2" style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface-dim);">
									<span class="flex items-center gap-1">
										<span style="width: 12px; height: 3px; background: var(--color-accent, #c96342); display: inline-block;"></span>
										Candidate Score
									</span>
									<span class="flex items-center gap-1">
										<span style="width: 12px; height: 3px; background: var(--color-on-surface-dim, #6f6e69); display: inline-block; border-top: 1px dashed var(--color-on-surface-dim, #6f6e69);"></span>
										Ideal (100%)
									</span>
								</div>
							</div>
						</div>
					{/if}

					<!-- Technical Skills -->
					{#if candidate.skills_technical?.length}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Technical Skills</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-wrap gap-2">
									{#each candidate.skills_technical as skill}
										<span style="display: inline-block; padding: 6px 14px; border: 2px solid var(--color-on-surface); border-right-width: 3px; border-bottom-width: 3px; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.04em; background: var(--color-surface-bright);">
											{skill}
										</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Soft Skills -->
					{#if candidate.skills_soft?.length}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Soft Skills</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-wrap gap-2">
									{#each candidate.skills_soft as skill}
										<span style="display: inline-block; padding: 5px 12px; border: 2px solid var(--color-outline-variant); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-on-surface-dim);">
											{skill}
										</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Tools -->
					{#if candidate.tools?.length}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Tools</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-wrap gap-2">
									{#each candidate.tools as tool}
										<span style="display: inline-flex; align-items: center; gap: 4px; padding: 5px 12px; border: 2px solid var(--color-on-surface); font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-highest);">
											<span class="material-symbols-outlined" style="font-size: 12px;">build</span>
											{tool}
										</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Languages -->
					{#if candidate.languages?.length}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Languages</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								<div class="flex flex-wrap gap-2">
									{#each candidate.languages as lang}
										<span style="display: inline-flex; align-items: center; gap: 4px; padding: 5px 12px; border: 2px solid var(--color-on-surface); font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);">
											<span class="material-symbols-outlined" style="font-size: 12px;">translate</span>
											{#if typeof lang === 'string'}
												{lang}
											{:else}
												{lang.language || lang.name || ''}{lang.proficiency ? ` (${lang.proficiency})` : ''}
											{/if}
										</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Skills matched/missing per position -->
					{#if positionMatches.length > 0}
						<div class="mb-6">
							<div class="dark-title-bar mb-0" style="font-size: 11px;">Skills per Position</div>
							<div class="ink-border p-4" style="border-top: none; background: var(--color-surface);">
								{#each positionMatches as pm}
									<div class="mb-4">
										<div style="font-size: 13px; font-weight: 900; margin-bottom: 6px;">{pm.position_title || pm.title || 'Position'}</div>
										{#if pm.skills_matched?.length}
											<div class="mb-2">
												<span class="tag-label" style="font-size: 8px; background: var(--color-primary); color: white; margin-bottom: 4px; display: inline-block;">Matched</span>
												<div class="flex flex-wrap gap-1 mt-1">
													{#each pm.skills_matched as s}
														<span style="font-size: 10px; padding: 2px 7px; border: 2px solid var(--color-primary); color: var(--color-primary); font-weight: 700; text-transform: uppercase;">{s}</span>
													{/each}
												</div>
											</div>
										{/if}
										{#if pm.skills_missing?.length}
											<div>
												<span class="tag-label" style="font-size: 8px; background: var(--color-error); color: white; margin-bottom: 4px; display: inline-block;">Missing</span>
												<div class="flex flex-wrap gap-1 mt-1">
													{#each pm.skills_missing as s}
														<span style="font-size: 10px; padding: 2px 7px; border: 2px solid var(--color-error); color: var(--color-error); font-weight: 700; text-transform: uppercase;">{s}</span>
													{/each}
												</div>
											</div>
										{/if}
									</div>
								{/each}
							</div>
						</div>
					{/if}

					<!-- Empty state -->
					{#if !candidate.skills_technical?.length && !candidate.skills_soft?.length && !candidate.tools?.length && !candidate.languages?.length}
						<div class="flex flex-col items-center justify-center py-16" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">psychology</span>
							<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No skills extracted</p>
						</div>
					{/if}

				<!-- ============================
					 NOTES TAB
					 ============================ -->
				{:else if activeTab === 'notes'}

					<!-- Section header: Notes & comments -->
					<div class="mb-3" style="display:flex; align-items:baseline; justify-content:space-between; gap:10px;">
						<h3 style="font-size:13px; font-weight:900; text-transform:uppercase; letter-spacing:0.06em; margin:0;">Notes &amp; comments</h3>
						<span style="font-size:10px; color: var(--color-on-surface-dim); text-transform:uppercase; letter-spacing:0.05em;">{notes.length} entr{notes.length === 1 ? 'y' : 'ies'}</span>
					</div>

					<!-- Add note form -->
					<div class="mb-6 ink-border" style="background: var(--color-surface);">
						<div class="dark-title-bar" style="font-size: 11px;">Add note</div>
						<div class="p-4">
							<div class="flex gap-2 mb-3">
								<select bind:value={newNoteType}
									style="padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright); min-width: 120px;">
									{#each noteTypes as nt}
										<option value={nt}>{nt.toUpperCase()}</option>
									{/each}
								</select>
							</div>
							<div style="position: relative;">
								<textarea
									bind:this={noteTextarea}
									bind:value={newNote}
									oninput={handleNoteInput}
									placeholder="TYPE YOUR NOTE... USE @ TO MENTION"
									rows="3"
									style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-on-surface); border-right-width: 3px; border-bottom-width: 3px; font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright); resize: vertical; outline: none;"
									onkeydown={(e) => {
										if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitNote();
										if (e.key === 'Escape') showMentionDropdown = false;
									}}
								></textarea>
								{#if showMentionDropdown && filteredMentionUsers.length > 0}
									<div style="position: absolute; left: 0; bottom: 100%; width: 260px; background: var(--color-surface); border: 2px solid var(--color-on-surface); border-bottom: none; z-index: 50; max-height: 200px; overflow-y: auto; box-shadow: 4px -4px 0 rgba(56,56,50,0.15);">
										{#each filteredMentionUsers as u}
											<button
												onclick={() => insertMention(u.display_name)}
												style="display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 12px; border: none; border-bottom: 1px solid var(--color-outline-variant); background: var(--color-surface); cursor: pointer; font-family: 'Space Grotesk'; text-align: left;"
												onmouseenter={(e) => e.currentTarget.style.background = 'var(--color-surface-highest)'}
												onmouseleave={(e) => e.currentTarget.style.background = 'var(--color-surface)'}
											>
												<div style="width: 24px; height: 24px; background: var(--color-primary-container); color: var(--color-on-surface); display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 10px; flex-shrink: 0;">
													{u.display_name?.[0]?.toUpperCase() || '?'}
												</div>
												<div>
													<div style="font-size: 12px; font-weight: 900;">{u.display_name}</div>
													<div style="font-size: 10px; color: var(--color-on-surface-dim); text-transform: uppercase;">{u.role}</div>
												</div>
											</button>
										{/each}
									</div>
								{/if}
							</div>
							<div class="flex justify-between items-center mt-2">
								<span style="font-size: 10px; color: var(--color-on-surface-dim); text-transform: uppercase;">Ctrl+Enter to submit · @ to mention</span>
								<button class="send-btn" onclick={submitNote} disabled={submittingNote || !newNote.trim()}>
									{submittingNote ? 'Saving...' : 'Add Note'}
								</button>
							</div>
						</div>
					</div>

					<!-- Notes list -->
					{#if notesLoading}
						{#each [1, 2, 3] as _}
							<div class="skeleton mb-3" style="height: 80px;"></div>
						{/each}
					{:else if notes.length === 0}
						<div class="flex flex-col items-center justify-center py-12" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 40px; color: var(--color-on-surface-dim);">note_add</span>
							<p style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 10px;">No notes yet</p>
						</div>
					{:else}
						<div class="section-animate">
							{#each notesTree as { note, replies }, i}
								<div class="mb-4 animate-fade-up" style="animation-delay: {i * 0.05}s;">
									<div class="flex gap-3">
										<div class="avatar-user" style="margin-top: 2px; flex-shrink: 0;">
											{initials(note.user_name || note.author || 'U')}
										</div>
										<div class="flex-1 ink-border" style="background: var(--color-surface); padding: 12px 16px;">
											<div class="flex items-center gap-2 mb-2">
												<span style="font-size: 12px; font-weight: 900;">{note.user_name || note.author || 'User'}</span>
												{#if note.note_type}
													<span class="tag-label" style="font-size: 8px;">{note.note_type}</span>
												{/if}
												<span style="font-size: 10px; color: var(--color-on-surface-dim); margin-left: auto;">{timeAgo(note.created_at || note.timestamp)}</span>
											</div>
											<p style="font-size: 13px; line-height: 1.6; white-space: pre-wrap;">{@html renderNoteWithMentions(note.content || note.text || '')}</p>
											<div style="display:flex; align-items:center; gap:10px; margin-top:8px; padding-top:8px; border-top:1px dashed var(--color-outline-variant);">
												<button
													onclick={() => openReply(note.id)}
													style="background:transparent; border:none; padding:0; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:0.05em; color:var(--color-on-surface-dim); cursor:pointer;">
													{replyOpenFor === note.id ? '× Cancel' : '↳ Reply'}
												</button>
												{#if replies.length > 0}
													<span style="font-size:10px; font-weight:800; text-transform:uppercase; padding:1px 6px; background:var(--color-surface-highest, #f5f0eb); color:var(--color-on-surface); border:1px solid var(--color-border, #d8d5cc); border-radius:4px;">
														{replies.length} repl{replies.length === 1 ? 'y' : 'ies'}
													</span>
												{/if}
											</div>

											{#if replyOpenFor === note.id}
												<div style="margin-top:10px; display:flex; flex-direction:column; gap:6px;">
													<textarea
														bind:value={replyText}
														placeholder="Write a reply…"
														rows="2"
														style="width:100%; padding:8px 10px; border:2px solid var(--color-on-surface); font-family:'Space Grotesk'; font-size:12px; background:var(--color-surface-bright); resize:vertical; outline:none;"
														onkeydown={(e) => {
															if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitReply(note.id);
															if (e.key === 'Escape') replyOpenFor = null;
														}}
													></textarea>
													<div style="display:flex; justify-content:flex-end; gap:6px;">
														<button class="send-btn" style="font-size:10px; padding:4px 10px;"
															onclick={() => submitReply(note.id)}
															disabled={submittingReply || !replyText.trim()}>
															{submittingReply ? 'Posting…' : 'Post reply'}
														</button>
													</div>
												</div>
											{/if}
										</div>
									</div>

									<!-- Replies, indented 24px -->
									{#each replies as reply}
										<div class="flex gap-3 mt-2" style="margin-left: 24px; background: var(--color-surface-highest, #f5f0eb); padding: 8px; border-left: 3px solid var(--color-accent, #c96342); border-radius: 0 4px 4px 0;">
											<div class="avatar-user" style="margin-top:2px; flex-shrink:0; width:28px; height:28px; font-size:10px;">
												{initials(reply.user_name || reply.author || 'U')}
											</div>
											<div class="flex-1" style="background: transparent; padding: 4px 8px;">
												<div class="flex items-center gap-2 mb-1">
													<span style="font-size:11px; font-weight:900;">{reply.user_name || reply.author || 'User'}</span>
													<span style="font-size:9px; color: var(--color-on-surface-dim); margin-left:auto;">{timeAgo(reply.created_at || reply.timestamp)}</span>
												</div>
												<p style="font-size:12px; line-height:1.5; white-space:pre-wrap; margin:0;">{@html renderNoteWithMentions(reply.content || reply.text || '')}</p>
											</div>
										</div>
									{/each}
								</div>
							{/each}
							{#if !backendSupportsReplies}
								<p style="font-size:10px; color: var(--color-on-surface-dim); text-transform:uppercase; letter-spacing:0.05em; margin-top:8px;">
									Note: backend does not yet store reply threads — replies appear inline as flat comments.
								</p>
							{/if}
						</div>
					{/if}

				<!-- ============================
					 SCORECARDS TAB
					 ============================ -->
				{:else if activeTab === 'scorecards'}

					<!-- Submit Scorecard (with competency ratings) -->
					<div class="mb-6 ink-border" style="background: var(--color-surface-bright);">
						<div class="dark-title-bar flex items-center justify-between" style="font-size: 11px;">
							<span>Submit Scorecard</span>
							<button onclick={() => showScorecardForm = !showScorecardForm}
								style="background: transparent; border: 1px solid var(--color-surface); color: var(--color-surface); padding: 3px 10px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
								{showScorecardForm ? '× Cancel' : '+ New'}
							</button>
						</div>
						{#if showScorecardForm}
							<div class="p-4">
								<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;">
									<label style="display: block;">
										<span style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface-dim);">Position</span>
										<select bind:value={scorecardPositionSlug} onchange={loadPositionCompetenciesForScorecard}
											style="width: 100%; margin-top: 2px; border: 2px solid var(--color-on-surface); padding: 5px 8px; font-size: 11px; font-weight: 700; background: var(--color-surface);">
											<option value="">Select position…</option>
											{#each (assignments || []) as a}
												<option value={a.slug}>{a.title}</option>
											{/each}
										</select>
									</label>
									<label style="display: block;">
										<span style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface-dim);">Recommendation</span>
										<select bind:value={scorecardRecommendation}
											style="width: 100%; margin-top: 2px; border: 2px solid var(--color-on-surface); padding: 5px 8px; font-size: 11px; font-weight: 700; background: var(--color-surface);">
											<option value="strong_hire">Strong Hire</option>
											<option value="hire">Hire</option>
											<option value="no_hire">No Hire</option>
											<option value="strong_no_hire">Strong No Hire</option>
										</select>
									</label>
								</div>

								<div style="margin-bottom: 12px;">
									<span style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface-dim);">Overall Rating (1–5)</span>
									<div style="display: flex; gap: 4px; margin-top: 4px;">
										{#each [1,2,3,4,5] as lv}
											<button type="button" onclick={() => scorecardOverall = lv}
												style="width: 30px; height: 30px; border: 1px solid var(--color-border, #d8d5cc); border-radius: 4px; background: {lv <= scorecardOverall ? 'var(--color-accent, #c96342)' : 'var(--color-surface)'}; color: {lv <= scorecardOverall ? '#fff' : 'inherit'}; cursor: pointer; font-size: 11px; font-weight: 900;">{lv}</button>
										{/each}
									</div>
								</div>

								<!-- Competency Ratings -->
								{#if scorecardPositionSlug}
									<div style="margin-bottom: 12px;">
										<div style="font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; padding: 6px 10px; background: var(--color-on-surface); color: var(--color-surface); margin-bottom: 6px;">
											Competency Ratings
										</div>
										{#if positionCompsLoading}
											<div style="font-size: 11px; opacity: 0.6; padding: 8px; text-transform: uppercase;">Loading…</div>
										{:else if positionCompetencies.length === 0}
											<div style="font-size: 11px; color: var(--color-on-surface-dim); padding: 8px; text-transform: uppercase;">No competencies defined for this position.</div>
										{:else}
											{#each positionCompetencies as pc}
												{@const cid = pc.competency_id ?? pc.id}
												<div style="display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--color-outline-variant);">
													<div style="flex: 1; font-size: 11px; font-weight: 700;">{pc.label || pc.key}</div>
													<div style="display: inline-flex; gap: 2px;">
														{#each [1,2,3,4,5] as lv}
															<button type="button" onclick={() => { scorecardCompetencyRatings[cid] = lv; scorecardCompetencyRatings = { ...scorecardCompetencyRatings }; }}
																style="width: 18px; height: 18px; border: 1px solid var(--color-border, #d8d5cc); border-radius: 3px; background: {lv <= (scorecardCompetencyRatings[cid] || 0) ? 'var(--color-accent, #c96342)' : 'var(--color-surface)'}; cursor: pointer; padding: 0;"></button>
														{/each}
													</div>
													<span style="min-width: 24px; text-align: right; font-size: 11px; font-weight: 900;">[{scorecardCompetencyRatings[cid] || '—'}]</span>
												</div>
											{/each}
										{/if}
									</div>
								{/if}

								<label style="display: block; margin-bottom: 12px;">
									<span style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface-dim);">Comments</span>
									<textarea bind:value={scorecardComments} rows="3"
										style="width: 100%; margin-top: 2px; border: 2px solid var(--color-on-surface); padding: 6px 10px; font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); resize: vertical;"></textarea>
								</label>

								<div style="display: flex; gap: 8px; justify-content: flex-end;">
									<button class="send-btn" onclick={submitScorecard} disabled={!scorecardPositionSlug || submittingScorecard}>
										{submittingScorecard ? 'Submitting…' : 'Submit Scorecard'}
									</button>
								</div>
							</div>
						{/if}
					</div>

					{#if scorecardsLoading}
						{#each [1, 2] as _}
							<div class="skeleton mb-3" style="height: 120px;"></div>
						{/each}
					{:else if scorecards.length === 0}
						<div class="flex flex-col items-center justify-center py-16" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">fact_check</span>
							<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No scorecards submitted</p>
						</div>
					{:else}
						<!-- Aggregate summary -->
						{@const avgOverall = scorecards.reduce((sum, sc) => sum + (sc.overall_score || sc.score || 0), 0) / scorecards.length}
						<div class="ink-border stamp-shadow mb-6" style="background: var(--color-surface); padding: 20px;">
							<div class="flex items-center gap-6">
								<div style="text-align: center;">
									<div style="font-size: 36px; font-weight: 900; color: {scoreColor(avgOverall)};">
										{Math.round(avgOverall)}
									</div>
									<div style="font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">Avg Score</div>
								</div>
								<div class="flex-1">
									<div class="score-bar" style="height: 14px;">
										<div class="score-bar-fill {scoreClass(avgOverall)}" style="width: {avgOverall}%;"></div>
									</div>
								</div>
								<div style="text-align: center;">
									<div style="font-size: 20px; font-weight: 900;">{scorecards.length}</div>
									<div style="font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">Reviews</div>
								</div>
							</div>
						</div>

						<!-- Individual scorecards -->
						<div class="section-animate">
							{#each scorecards as sc, i}
								<div class="ink-border mb-4 animate-fade-up" style="background: var(--color-surface); animation-delay: {i * 0.05}s;">
									<div class="dark-title-bar flex items-center justify-between" style="font-size: 11px;">
										<span>{sc.interviewer || sc.reviewer || 'Reviewer'}</span>
										<span style="font-weight: 400; font-size: 10px;">{formatDate(sc.created_at || sc.date)}</span>
									</div>
									<div class="p-4">
										<!-- Overall score -->
										<div class="flex items-center gap-3 mb-4">
											<span style="font-size: 11px; font-weight: 900; text-transform: uppercase; min-width: 80px;">Overall</span>
											<div class="score-bar flex-1" style="height: 10px;">
												<div class="score-bar-fill {scoreClass(sc.overall_score || sc.score || 0)}" style="width: {sc.overall_score || sc.score || 0}%;"></div>
											</div>
											<span style="font-size: 14px; font-weight: 900; color: {scoreColor(sc.overall_score || sc.score || 0)}; min-width: 36px; text-align: right;">
												{Math.round(sc.overall_score || sc.score || 0)}
											</span>
										</div>

										<!-- Dimension scores -->
										{#if sc.dimensions || sc.scores || sc.criteria}
											{@const dims = sc.dimensions || sc.scores || sc.criteria || {}}
											{#each Object.entries(typeof dims === 'string' ? JSON.parse(dims) : dims) as [key, val]}
												<div class="flex items-center gap-3 mb-2">
													<span style="font-size: 10px; font-weight: 700; text-transform: uppercase; min-width: 80px; color: var(--color-on-surface-dim);">{key.replace(/_/g, ' ')}</span>
													<div class="score-bar flex-1" style="height: 6px;">
														<div class="score-bar-fill {scoreClass(typeof val === 'number' ? val : val?.score || 0)}" style="width: {typeof val === 'number' ? val : val?.score || 0}%;"></div>
													</div>
													<span style="font-size: 11px; font-weight: 700; min-width: 28px; text-align: right;">
														{Math.round(typeof val === 'number' ? val : val?.score || 0)}
													</span>
												</div>
											{/each}
										{/if}

										<!-- Recommendation -->
										{#if sc.recommendation}
											<div class="mt-3 pt-3" style="border-top: 1px solid var(--color-outline-variant);">
												<span class="tag-label" style="font-size: 8px;
													background: {sc.recommendation === 'strong_hire' || sc.recommendation === 'hire' ? 'var(--color-primary)' : sc.recommendation === 'no_hire' || sc.recommendation === 'strong_no_hire' ? 'var(--color-error)' : 'var(--color-warning)'};
													color: white;">
													{sc.recommendation.replace(/_/g, ' ').toUpperCase()}
												</span>
											</div>
										{/if}

										<!-- Comments -->
										{#if sc.comments || sc.feedback}
											<div class="mt-3 pt-3" style="border-top: 1px solid var(--color-outline-variant); font-size: 12px; line-height: 1.6; color: var(--color-on-surface-dim);">
												{sc.comments || sc.feedback}
											</div>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}

				<!-- ============================
					 COMPETENCIES TAB
					 ============================ -->
				{:else if activeTab === 'competencies'}
					<div class="ink-border" style="background: var(--color-surface-bright);">
						<div class="dark-title-bar flex items-center justify-between">
							<span>COMPETENCIES {aggregatedComps.length ? `(${aggregatedComps.length})` : ''}</span>
							<button onclick={autoExtractCompetencies} disabled={extractingComps}
								style="background: var(--color-accent, #c96342); color: #fff; border: none; border-radius: 4px; padding: 3px 10px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
								{extractingComps ? '…' : '✦ Auto-Extract from CV'}
							</button>
						</div>
						<div style="padding: 14px 18px;">
							{#if competenciesLoading}
								<div style="font-size: 11px; opacity: 0.6; text-transform: uppercase;">Loading…</div>
							{:else if aggregatedComps.length === 0}
								<div style="font-size: 11px; color: var(--color-on-surface-dim); text-align: center; padding: 24px; text-transform: uppercase; letter-spacing: 0.05em; line-height: 1.6;">
									No competencies recorded.<br/>
									Click ✦ AUTO-EXTRACT FROM CV to populate from this candidate's CV.
								</div>
							{:else}
								{@const avg = aggregatedComps.reduce((a, c) => a + c.avgLevel, 0) / aggregatedComps.length}
								{@const signalCount = aggregatedComps.reduce((a, c) => a + c.signals.length, 0)}
								{@const gapCount = aggregatedComps.filter(c => c.avgLevel < 3).length}
								<table style="width: 100%; border-collapse: collapse; font-size: 11px;">
									<thead>
										<tr style="background: var(--color-surface-highest, #f5f5e0); border-bottom: 2px solid var(--color-on-surface);">
											<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Competency</th>
											<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Level</th>
											<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Source</th>
											<th style="text-align: left; padding: 6px 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Evidence</th>
										</tr>
									</thead>
									<tbody>
										{#each aggregatedComps as comp}
											<tr style="border-bottom: 1px solid var(--color-outline-variant); cursor: pointer;"
												onclick={() => compExpandedKey = (compExpandedKey === (comp.competency_id ?? comp.key)) ? null : (comp.competency_id ?? comp.key)}>
												<td style="padding: 6px 8px; font-weight: 700;">
													<div>{comp.label || comp.key}</div>
													<div style="font-size: 9px; color: var(--color-on-surface-dim); font-weight: 400;">{comp.key}</div>
												</td>
												<td style="padding: 6px 8px;">
													<div style="display: inline-flex; gap: 2px;">
														{#each [1,2,3,4,5] as lv}
															<span style="display: inline-block; width: 14px; height: 14px; border: 1px solid var(--color-border, #d8d5cc); border-radius: 3px; background: {lv <= Math.round(comp.avgLevel) ? 'var(--color-accent, #c96342)' : 'var(--color-surface)'};"></span>
														{/each}
													</div>
													<span style="margin-left: 6px; font-size: 11px; font-weight: 900;">{comp.avgLevel.toFixed(1)}</span>
												</td>
												<td style="padding: 6px 8px;">
													<span style="padding: 1px 6px; background: var(--color-on-surface); color: var(--color-surface); font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">{comp.topSource}</span>
												</td>
												<td style="padding: 6px 8px; font-style: italic; color: var(--color-on-surface-dim); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
													"{comp.topEvidence || '—'}"
												</td>
											</tr>
											{#if compExpandedKey === (comp.competency_id ?? comp.key)}
												<tr>
													<td colspan="4" style="padding: 12px 16px; background: var(--color-surface);">
														<div style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;">All Signals</div>
														{#each comp.signals as s}
															<div style="display: flex; gap: 10px; align-items: center; padding: 4px 0; border-bottom: 1px dashed var(--color-outline-variant); font-size: 11px;">
																<span style="padding: 1px 6px; background: var(--color-on-surface); color: var(--color-surface); font-size: 9px; font-weight: 700; text-transform: uppercase; min-width: 80px; text-align: center;">{s.source || '—'}</span>
																<span style="font-weight: 900;">L{s.level ?? '?'}</span>
																{#if s.confidence != null}<span style="font-size: 10px; opacity: 0.7;">conf {Math.round((s.confidence || 0) * 100)}%</span>{/if}
																<span style="font-style: italic; color: var(--color-on-surface-dim); flex: 1;">{s.evidence || '—'}</span>
																{#if s.rated_by}<span style="font-size: 10px; opacity: 0.7;">{s.rated_by}</span>{/if}
															</div>
														{/each}
														<!-- Manual override -->
														<div style="margin-top: 12px; padding-top: 10px; border-top: 2px dashed var(--color-on-surface); display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
															<span style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">Manual Override</span>
															<select bind:value={compOverrideLevel[comp.competency_id ?? comp.key]}
																style="border: 2px solid var(--color-on-surface); padding: 3px 6px; font-size: 11px; font-weight: 700; background: var(--color-surface);">
																<option value={undefined}>—</option>
																{#each [1,2,3,4,5] as lv}<option value={lv}>{lv}</option>{/each}
															</select>
															<input type="text" bind:value={compOverrideEvidence[comp.competency_id ?? comp.key]}
																placeholder="Evidence note (optional)"
																style="flex: 1; min-width: 200px; border: 2px solid var(--color-on-surface); padding: 3px 8px; font-size: 11px; background: var(--color-surface);" />
															<button onclick={(e) => { e.stopPropagation(); saveCompetencyOverride(comp); }}
																style="background: var(--color-accent, #c96342); color: #fff; border: none; border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
																Save
															</button>
														</div>
													</td>
												</tr>
											{/if}
										{/each}
									</tbody>
								</table>
								<div style="margin-top: 12px; padding: 10px 0; border-top: 2px dashed var(--color-on-surface); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; display: flex; gap: 18px; flex-wrap: wrap;">
									<span>Average: <strong style="font-size: 13px;">{avg.toFixed(1)}</strong></span>
									<span>·</span>
									<span>{signalCount} signals</span>
									<span>·</span>
									<span>{gapCount} gaps (level &lt; 3)</span>
									<span style="margin-left: auto; opacity: 0.6;">Click a row to expand evidence + manual override</span>
								</div>
							{/if}
						</div>
					</div>

				<!-- ============================
					 ASSIGNMENTS TAB
					 ============================ -->
				{:else if activeTab === 'assignments'}
					<div class="ink-border" style="background: var(--color-surface-bright); padding: 18px;">
						<div class="flex items-center justify-between mb-3">
							<div style="font-size: 14px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase;">
								Position Assignments {assignments.length ? `(${assignments.length})` : ''}
							</div>
							<button class="btn-secondary" style="font-size: 10px; padding: 4px 10px;" onclick={loadAssignments}>Refresh</button>
						</div>
						{#if !assignmentsLoaded}
							<div class="skeleton" style="height: 48px;"></div>
						{:else if assignments.length === 0}
							<p style="font-size: 12px; color: var(--color-on-surface-dim); padding: 18px; text-align: center;">Not attached to any position yet.</p>
						{:else}
							<table style="width: 100%; border-collapse: collapse; font-size: 12px;">
								<thead>
									<tr style="background: var(--color-on-surface); color: var(--color-surface);">
										<th style="text-align: left; padding: 8px;">POSITION</th>
										<th style="text-align: left; padding: 8px;">STAGE</th>
										<th style="text-align: left; padding: 8px;">MATCH</th>
										<th style="text-align: left; padding: 8px;">RECRUITER</th>
										<th style="text-align: left; padding: 8px;">ADDED</th>
									</tr>
								</thead>
								<tbody>
									{#each assignments as a}
										<tr style="border-top: 1px solid rgba(56,56,50,0.15);">
											<td style="padding: 8px;">
												<a href="/positions/{a.slug}" style="font-weight: 900; color: var(--color-on-surface);">{a.title}</a>
											</td>
											<td style="padding: 8px;">
												<span style="padding: 1px 8px; background: var(--color-on-surface); color: var(--color-surface); font-size: 10px; font-weight: 900; text-transform: uppercase;">{a.stage}</span>
												{#if a.is_active_interview}<span style="margin-left: 6px; font-size: 9px; color: var(--color-warning, #c98c2a); font-weight: 700; text-transform: uppercase; display:inline-flex; align-items:center; gap:3px;"><AlertTriangle size={11} stroke-width={2} /> Active interview</span>{/if}
											</td>
											<td style="padding: 8px;">{Math.round(a.match_score_composite || 0)}%</td>
											<td style="padding: 8px;">{a.recruiter_name || '—'}</td>
											<td style="padding: 8px; font-family: monospace; font-size: 11px;">{a.added_at ? new Date(a.added_at).toLocaleString() : '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

				<!-- ============================
					 PIPELINE TAB
					 ============================ -->
				{:else if activeTab === 'pipeline'}
					{#if pipelineRunsLoading}
						<div class="skeleton mb-3" style="height: 48px;"></div>
					{:else}
						{#if pipelineRuns.length > 1}
							<div class="mb-4 flex items-center gap-2">
								<span style="font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">Run:</span>
								<select
									bind:value={selectedPipelineRunId}
									style="padding: 6px 10px; border: 2px solid var(--color-on-surface); background: var(--color-surface); font-family: inherit; font-size: 11px; font-weight: 700;"
								>
									{#each pipelineRuns as r}
										<option value={r.run_id}>
											{r.run_id.slice(0,8)} · {(r.started_at || '').slice(0,16).replace('T',' ')} · ${(r.total_cost || 0).toFixed(4)}
										</option>
									{/each}
								</select>
							</div>
						{/if}
						{#if pipelineRuns.length === 0}
							<div class="flex flex-col items-center justify-center py-16" style="border: 3px dashed var(--color-outline-variant);">
								<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">graph_3</span>
								<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No pipeline run recorded</p>
							</div>
						{:else}
							<PipelineStepper candidateId={candidate.id} runId={selectedPipelineRunId} live={false} />
						{/if}
					{/if}

					<!-- Processing Artifacts panel -->
					<div class="mt-6">
						<div class="dark-title-bar mb-0" style="font-size: 11px;">PROCESSING ARTIFACTS</div>
						<div class="ink-border" style="border-top: none; background: var(--color-surface);">
							{#if artifactsLoading}
								<div style="padding: 14px; font-size: 12px; font-weight: 700; text-transform: uppercase;">Loading…</div>
							{:else if artifactsError}
								<div style="padding: 14px; font-size: 12px; font-weight: 700; color: var(--color-on-surface-dim);">{artifactsError}</div>
							{:else if artifacts}
								{@const verified = artifacts.verified_critical_present || {}}
								{@const verifiedEntries = Object.entries(verified)}
								{@const verifiedCount = verifiedEntries.filter(([_, v]) => v).length}
								<table style="width: 100%; border-collapse: collapse; font-size: 12px;">
									<thead>
										<tr style="background: var(--color-surface-highest); text-align: left;">
											<th style="padding: 8px 12px; border-bottom: 2px solid var(--color-on-surface); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Type</th>
											<th style="padding: 8px 12px; border-bottom: 2px solid var(--color-on-surface); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;">Count / Value</th>
											<th style="padding: 8px 12px; border-bottom: 2px solid var(--color-on-surface); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; width: 110px;">Action</th>
										</tr>
									</thead>
									<tbody>
										<!-- Raw text -->
										<tr style="border-bottom: 1px solid var(--color-outline-variant);">
											<td style="padding: 8px 12px; font-weight: 700;">Raw text</td>
											<td style="padding: 8px 12px;">{artifacts.raw_text_chars || 0} chars</td>
											<td style="padding: 8px 12px;">—</td>
										</tr>
										<!-- Embeddings -->
										<tr style="border-bottom: 1px solid var(--color-outline-variant);">
											<td style="padding: 8px 12px; font-weight: 700;">Embeddings</td>
											<td style="padding: 8px 12px;">
												{artifacts.embeddings?.count || 0} chunks
												{#if artifacts.embeddings?.dim} · {artifacts.embeddings.dim}-dim{/if}
												{#if artifacts.embeddings?.model} · {artifacts.embeddings.model}{/if}
											</td>
											<td style="padding: 8px 12px;">
												{#if Object.keys(artifacts.embeddings?.by_chunk_type || {}).length > 0}
													<button onclick={() => toggleArtifactRow('emb')} style="font-size: 10px; padding: 3px 8px; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); font-family: inherit; font-weight: 700; text-transform: uppercase; cursor: pointer;">
														{artifactsExpanded.emb ? 'Hide' : 'View'}
													</button>
												{/if}
											</td>
										</tr>
										{#if artifactsExpanded.emb}
											<tr><td colspan="3" style="padding: 8px 16px; background: var(--color-surface-bright); border-bottom: 1px solid var(--color-outline-variant);">
												<div style="font-size: 11px;">
													{#each Object.entries(artifacts.embeddings?.by_chunk_type || {}) as [k, v]}
														<span style="display: inline-block; margin-right: 12px; padding: 2px 6px; border: 1.5px solid var(--color-on-surface); font-weight: 700;">{k}: {v}</span>
													{/each}
												</div>
											</td></tr>
										{/if}
										<!-- Q&A pairs -->
										<tr style="border-bottom: 1px solid var(--color-outline-variant);">
											<td style="padding: 8px 12px; font-weight: 700;">Q&amp;A pairs</td>
											<td style="padding: 8px 12px;">
												{artifacts.qa_pairs?.count || 0} pairs
												{#if artifacts.qa_pairs?.sample?.[0]?.q}
													· sample: "{artifacts.qa_pairs.sample[0].q.slice(0, 50)}…"
												{/if}
											</td>
											<td style="padding: 8px 12px;">
												{#if (artifacts.qa_pairs?.count || 0) > 0}
													<button onclick={() => toggleArtifactRow('qa')} style="font-size: 10px; padding: 3px 8px; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); font-family: inherit; font-weight: 700; text-transform: uppercase; cursor: pointer;">
														{artifactsExpanded.qa ? 'Hide' : 'View'}
													</button>
												{/if}
											</td>
										</tr>
										{#if artifactsExpanded.qa}
											<tr><td colspan="3" style="padding: 8px 16px; background: var(--color-surface-bright); border-bottom: 1px solid var(--color-outline-variant);">
												{#if artifactsQaPairs.length > 0}
													<ol style="margin: 0; padding-left: 20px; font-size: 11px; line-height: 1.7;">
														{#each artifactsQaPairs as p}
															<li style="margin-bottom: 4px;">{(p.question || p.q || '').slice(0, 80)}{(p.question || p.q || '').length > 80 ? '…' : ''}</li>
														{/each}
													</ol>
												{:else}
													<div style="font-size: 11px; color: var(--color-on-surface-dim);">No Q&amp;A pairs available.</div>
												{/if}
											</td></tr>
										{/if}
										<!-- Screenshots -->
										<tr style="border-bottom: 1px solid var(--color-outline-variant);">
											<td style="padding: 8px 12px; font-weight: 700;">Screenshots</td>
											<td style="padding: 8px 12px;">{artifacts.screenshots?.count || 0} page{(artifacts.screenshots?.count || 0) === 1 ? '' : 's'}</td>
											<td style="padding: 8px 12px;">
												{#if (artifacts.screenshots?.count || 0) > 0}
													<button onclick={() => toggleArtifactRow('ss')} style="font-size: 10px; padding: 3px 8px; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); font-family: inherit; font-weight: 700; text-transform: uppercase; cursor: pointer;">
														{artifactsExpanded.ss ? 'Hide' : 'View'}
													</button>
												{/if}
											</td>
										</tr>
										{#if artifactsExpanded.ss}
											<tr><td colspan="3" style="padding: 8px 16px; background: var(--color-surface-bright); border-bottom: 1px solid var(--color-outline-variant);">
												<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px;">
													{#each (artifacts.screenshots?.paths || []) as p, i}
														<div style="border: 2px solid var(--color-on-surface); background: white; padding: 4px;">
															<img
																src={`/api/static/${(p || '').replace(/^\/?(data\/)?/, '')}`}
																alt="Page {i + 1}"
																style="width: 100%; height: auto; display: block;"
																onerror={(e) => { e.currentTarget.style.opacity = '0.3'; }}
															/>
															<div style="font-size: 9px; font-weight: 900; text-transform: uppercase; text-align: center; padding: 3px 0;">Page {i + 1}</div>
														</div>
													{/each}
												</div>
											</td></tr>
										{/if}
										<!-- Verified fields -->
										<tr>
											<td style="padding: 8px 12px; font-weight: 700;">Verified fields</td>
											<td style="padding: 8px 12px;">
												{verifiedCount}/{verifiedEntries.length} ·
												{#each verifiedEntries as [k, v], i}
													<span style="margin-right: 6px; display:inline-flex; align-items:center; gap:2px;">{k} {#if v}<Check size={11} stroke-width={2.5} />{:else}<X size={11} stroke-width={2.5} />{/if}</span>
												{/each}
											</td>
											<td style="padding: 8px 12px;">—</td>
										</tr>
									</tbody>
								</table>
							{:else}
								<div style="padding: 14px; font-size: 12px; color: var(--color-on-surface-dim);">No artifacts data.</div>
							{/if}
						</div>
					</div>

				<!-- ============================
					 AI MATCHES TAB
					 ============================ -->
				{:else if activeTab === 'ai_matches'}

					<CandidateAIMatches candidateId={candidateId} mode="full" />

				<!-- ============================
					 ACTIVITY TAB (uses reusable ActivityFeed)
					 ============================ -->
				{:else if activeTab === 'activity'}

					<ActivityFeed targetType="candidate" targetId={candidateId} title="Activity timeline" />

					{#if false && activityLoading}
						{#each [1, 2, 3, 4, 5] as _}
							<div class="skeleton mb-3" style="height: 48px;"></div>
						{/each}
					{:else if activity.length === 0}
						<div class="flex flex-col items-center justify-center py-16" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">timeline</span>
							<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No activity recorded</p>
						</div>
					{:else}
						{#each activityGroups as group, gi}
							<!-- Date group header -->
							<div class="flex items-center gap-3 mb-3 {gi > 0 ? 'mt-6' : ''}" style="animation-delay: {gi * 0.1}s;">
								<div style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.1em; color: var(--color-on-surface-dim); white-space: nowrap;">
									{group.label}
								</div>
								<div style="flex: 1; height: 1px; background: var(--color-outline-variant);"></div>
							</div>

							<div style="position: relative; padding-left: 44px; margin-bottom: 8px;">
								<!-- Vertical timeline line -->
								<div style="position: absolute; left: 17px; top: 4px; bottom: 4px; width: 3px; background: linear-gradient(to bottom, var(--color-outline-variant), transparent);"></div>

								{#each group.items as event, i}
									{@const eventType = event.type || event.event_type || event.action || 'event'}
									{@const eventColor = activityColor(eventType)}
									<div class="flex items-start gap-3 mb-4 animate-fade-up" style="position: relative; animation-delay: {(gi * group.items.length + i) * 0.04}s;">
										<!-- Color-coded icon circle -->
										<div style="position: absolute; left: -38px; width: 34px; height: 34px; background: {eventColor}; border: 3px solid var(--color-surface); display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 2px {eventColor};">
											<span class="material-symbols-outlined" style="font-size: 16px; color: white;">{activityIcon(eventType)}</span>
										</div>

										<!-- Event card -->
										<div class="flex-1 ink-border" style="background: var(--color-surface); padding: 12px 16px;">
											<div class="flex items-center justify-between gap-2 flex-wrap">
												<div class="flex items-center gap-2 flex-wrap">
													<span style="font-size: 13px; font-weight: 900;">
														{humanizeEvent(event)}
													</span>
													{#if eventType !== 'event'}
														<span class="tag-label" style="font-size: 8px; background: {eventColor}; color: white;">
															{eventType.replace(/_/g, ' ')}
														</span>
													{/if}
												</div>
												<span style="font-size: 10px; color: var(--color-on-surface-dim); white-space: nowrap;">
													{timeAgo(event.created_at || event.timestamp || event.date)}
												</span>
											</div>
											{#if humanizeDetails(event)}
												<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 6px; line-height: 1.5; border-left: 2px solid {eventColor}; padding-left: 8px;">{humanizeDetails(event)}</p>
											{/if}
											{#if event.user || event.actor || event.user_name}
												<div class="flex items-center gap-2 mt-2" style="font-size: 10px; color: var(--color-on-surface-dim);">
													<div style="width: 18px; height: 18px; background: var(--color-surface-highest); display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 8px; border: 1px solid var(--color-outline-variant);">
														{(event.user || event.actor || event.user_name || '?')[0].toUpperCase()}
													</div>
													<span>by <strong>{event.user || event.actor || event.user_name}</strong></span>
												</div>
											{/if}
										</div>
									</div>
								{/each}
							</div>
						{/each}
					{/if}

				{/if}

			</div>
		</div>
	</div>
		{/snippet}
	</SplitPane>
		</div>
	</div>
</div>

<!-- Email Compose Modal -->
<EmailCompose
	show={showEmailCompose}
	candidateId={candidateId}
	candidateName={candidate?.name || ''}
	candidateEmail={candidate?.email || ''}
	positionSlug={positionMatches[0]?.position_slug || positionMatches[0]?.slug || ''}
	onClose={() => showEmailCompose = false}
/>

<!-- PDF Viewer -->
<PdfViewer
	candidateId={candidateId}
	show={showPdfViewer}
	onClose={() => showPdfViewer = false}
/>

<!-- Schedule Interview Panel -->
<SchedulePanel
	candidateId={candidateId}
	candidateName={candidate?.name || ''}
	positionTitle={positionMatches[0]?.position_title || positionMatches[0]?.title || ''}
	bind:open={showSchedulePanel}
/>

<!-- AI Summary Modal -->
{#if showAiSummary}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 40px 20px; overflow-y: auto;"
		onclick={(e) => { if (e.target === e.currentTarget) showAiSummary = false; }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 640px; max-height: 85vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span class="flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 14px;">auto_awesome</span>
					AI Executive Brief
				</span>
				<button onclick={() => showAiSummary = false} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px; font-weight: 900;">X</button>
			</div>
			<div class="p-5">
				{#if aiSummaryLoading}
					<div class="flex flex-col items-center justify-center py-12">
						<div class="typing-indicator"><span></span><span></span><span></span></div>
						<p style="font-size: 12px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">Generating executive brief...</p>
					</div>
				{:else if aiSummary?.error}
					<div style="background: var(--color-error-container, #ffe0e0); border-left: 3px solid var(--color-error); padding: 12px 16px; font-size: 12px; font-weight: 700;">
						{aiSummary.error}
					</div>
				{:else if aiSummary}
					<!-- Summary text -->
					<div style="font-size: 14px; line-height: 1.7; white-space: pre-wrap; margin-bottom: 16px;">
						{aiSummary.ai_summary || aiSummary.summary || aiSummary.brief || aiSummary.text || 'No summary available.'}
					</div>

					<!-- Data sources -->
					{#if aiSummary.data_sources || aiSummary.sources}
						{@const src = aiSummary.data_sources || aiSummary.sources || {}}
						<div style="border-top: 2px solid var(--color-on-surface); padding-top: 12px; margin-top: 12px;">
							<div style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim); margin-bottom: 8px;">Data Sources</div>
							<div class="flex gap-4 flex-wrap">
								{#if src.notes_count !== undefined}
									<div class="flex items-center gap-2" style="font-size: 12px;">
										<span class="material-symbols-outlined" style="font-size: 14px;">note</span>
										<strong>{src.notes_count}</strong> notes
									</div>
								{/if}
								{#if src.scorecards_count !== undefined}
									<div class="flex items-center gap-2" style="font-size: 12px;">
										<span class="material-symbols-outlined" style="font-size: 14px;">fact_check</span>
										<strong>{src.scorecards_count}</strong> scorecards
									</div>
								{/if}
							</div>
						</div>
					{/if}

					<!-- Copy button -->
					<div class="flex justify-end mt-4">
						<button
							onclick={copyAiSummary}
							style="display: flex; align-items: center; gap: 4px; padding: 6px 14px; border: 2px solid var(--color-on-surface); background: {aiSummaryCopied ? 'var(--color-primary)' : 'var(--color-surface-bright)'}; color: {aiSummaryCopied ? 'white' : 'var(--color-on-surface)'}; font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; cursor: pointer;"
						>
							<span class="material-symbols-outlined" style="font-size: 14px;">{aiSummaryCopied ? 'check' : 'content_copy'}</span>
							{aiSummaryCopied ? 'Copied' : 'Copy'}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
{/if}

<style>
	@media (max-width: 900px) {
		.profile-thumb-panel {
			display: none !important;
		}
	}

	/* @mention chip — coral, rendered inline inside notes/comments */
	:global(.mention-chip) {
		display: inline-block;
		padding: 1px 6px;
		background: #ff6b5e;
		color: #fff;
		font-weight: 800;
		font-size: 0.92em;
		letter-spacing: 0.01em;
		border: 1px solid #cc4a3f;
		text-decoration: none;
		line-height: 1.3;
	}

	/* Header nav buttons */
	.hire-nav-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 10px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		background: transparent;
		color: var(--color-surface, #feffd6);
		border: 1px solid rgba(255,255,255,0.3);
		text-decoration: none;
		cursor: pointer;
	}
	.hire-nav-btn:hover {
		background: rgba(255,255,255,0.1);
		border-color: rgba(255,255,255,0.6);
	}

	/* Tabs strip horizontal scroll */
	.hire-tabs-wrap {
		position: relative;
		display: flex;
		align-items: stretch;
	}
	.hire-tabs-strip {
		flex: 1;
		overflow-x: auto;
		scrollbar-width: none;
		-ms-overflow-style: none;
		flex-wrap: nowrap !important;
	}
	.hire-tabs-strip::-webkit-scrollbar { display: none; }
	.hire-tabs-strip > .dash-tab {
		flex-shrink: 0;
		white-space: nowrap;
	}
	.hire-tabs-arrow {
		flex-shrink: 0;
		width: 28px;
		background: var(--color-on-surface);
		color: var(--color-surface);
		border: none;
		font-size: 18px;
		font-weight: 900;
		cursor: pointer;
		font-family: 'Space Grotesk', sans-serif;
	}
	.hire-tabs-arrow:hover { background: var(--color-primary, #007518); }
	.hire-tab-badge {
		display: inline-block;
		min-width: 16px;
		padding: 1px 5px;
		margin-left: 4px;
		background: var(--color-accent, #c96342);
		color: #fff;
		border: 1px solid var(--color-border, #d8d5cc);
		font-size: 9px;
		font-weight: 900;
		text-align: center;
		line-height: 1.2;
		border-radius: 4px;
	}

	/* DocViewer footer hint */
	.hire-doc-hint {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 8px;
		padding: 6px 10px;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-on-surface-dim, #6f6f63);
		background: var(--color-surface-bright, #fffae0);
		border: 1px dashed var(--color-outline-variant, #ccccc4);
	}

	/* AT-A-GLANCE grid */
	.hire-glance-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
	}
	.hire-glance-cell {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 14px 8px;
		background: var(--color-surface, #feffd6);
		border: none;
		border-right: 1px solid var(--color-outline-variant, #ccccc4);
		font-family: 'Space Grotesk', sans-serif;
		cursor: pointer;
		transition: background 0.1s ease;
	}
	.hire-glance-cell:last-child { border-right: none; }
	.hire-glance-cell:hover { background: var(--color-accent-soft, #f5ece8); }
	.hire-glance-num {
		font-size: 22px;
		font-weight: 900;
		color: var(--color-on-surface, #383832);
		line-height: 1;
	}
	.hire-glance-lbl {
		font-size: 9px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-on-surface-dim, #6f6f63);
		margin-top: 6px;
	}

	/* ---------------------------------------------------------------- */
	/* Restored full-size header                                         */
	/* ---------------------------------------------------------------- */
	.hire-hdr-nav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 14px;
	}
	.hire-hdr-nav-left, .hire-hdr-nav-right {
		display: flex;
		align-items: center;
		gap: 14px;
		flex-wrap: wrap;
	}
	.hire-hdr-link {
		display: inline-flex; align-items: center; gap: 4px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 11px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.06em;
		background: none; border: none; padding: 0;
		color: var(--color-surface);
		opacity: 0.85;
		cursor: pointer;
		text-decoration: none;
	}
	.hire-hdr-link:hover { opacity: 1; color: var(--color-primary-container); }
	.hire-hdr-btn {
		display: inline-flex; align-items: center; gap: 5px;
		padding: 6px 12px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 11px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.05em;
		background: transparent;
		color: var(--color-surface);
		border: 1px solid rgba(255,255,255,0.4);
		cursor: pointer;
	}
	.hire-hdr-btn:hover { background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.8); }
	.hire-hdr-meta-sm {
		font-family: 'Space Grotesk', sans-serif;
		font-size: 11px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.06em;
		opacity: 0.7;
		color: var(--color-surface);
	}

	.hire-hdr-identity {
		display: flex;
		align-items: center;
		gap: 18px;
		margin-bottom: 10px;
	}
	.hire-hdr-avatar {
		width: 80px; height: 80px;
		background: var(--color-primary-container);
		color: var(--color-on-surface);
		display: flex; align-items: center; justify-content: center;
		border: 2px solid var(--color-surface);
		font-family: 'Space Grotesk', sans-serif;
		font-weight: 900; font-size: 28px;
		flex-shrink: 0;
	}
	.hire-hdr-id-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
	.hire-hdr-name {
		font-family: 'Space Grotesk', sans-serif;
		font-size: 32px;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: -0.01em;
		line-height: 1;
		margin: 0;
		color: var(--color-surface);
	}
	.hire-hdr-subline {
		display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 14px;
		font-weight: 600;
		opacity: 0.85;
		color: var(--color-surface);
	}
	.hire-hdr-sep { opacity: 0.5; }

	.hire-hdr-chips {
		display: flex; flex-wrap: nowrap; align-items: center; gap: 8px;
		margin-bottom: 10px;
		white-space: nowrap;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.hire-hdr-chips::-webkit-scrollbar { display: none; }
	.hire-hdr-chip { flex-shrink: 0; }
	.hire-hdr-chip {
		display: inline-flex; align-items: center; gap: 4px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 11px; font-weight: 900;
		padding: 4px 10px;
		text-transform: uppercase; letter-spacing: 0.06em;
		border: 1px solid rgba(255,255,255,0.4);
		background: transparent;
		color: var(--color-surface);
		line-height: 1.3;
		cursor: default;
	}
	.hire-hdr-chip-prime {
		background: var(--color-primary-container);
		color: var(--color-on-surface);
		border-color: var(--color-surface);
	}
	.hire-hdr-chip-ok {
		background: #3a8a4f;
		color: #fff;
		border-color: #2e7040;
	}
	.hire-hdr-chip-action { cursor: pointer; }
	.hire-hdr-chip-action:hover { background: rgba(255,255,255,0.12); }
	.hire-hdr-flag {
		display: inline-block; width: 10px; height: 10px;
		border: 1px solid var(--color-on-surface);
	}

	.hire-hdr-contact {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 14px;
		padding-top: 4px;
	}
	.hire-hdr-contact-left {
		display: flex; flex-wrap: wrap; align-items: center; gap: 16px;
	}
	.hire-hdr-contact-right {
		display: flex; align-items: center; gap: 12px;
	}

	.hire-hdr-actions {
		display: flex;
		align-items: center;
	}
	.hire-hdr-actions :global(.qa-strip) {
		margin-top: 0;
		flex-wrap: wrap;
	}

	/* ---------------------------------------------------------------- */
	/* Tabs: fit all 10 in one row at desktop widths                     */
	/* ---------------------------------------------------------------- */
	:global(.hire-tabs-wrap) {
		overflow: visible !important;
		width: 100% !important;
	}
	:global(.dash-tabs.hire-tabs-strip) {
		overflow: visible !important;
		width: 100% !important;
		flex-wrap: nowrap !important;
	}
	:global(.dash-tabs.hire-tabs-strip.hire-tabs-slim .dash-tab.hire-tab-slim) {
		flex: 1 1 0 !important;
		min-width: 0 !important;
		flex-shrink: 1 !important;
		flex-basis: 0 !important;
		padding: 6px 4px !important;
		font-size: 10px !important;
		letter-spacing: 0.03em;
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		position: relative;
		white-space: nowrap;
	}
	:global(.dash-tabs.hire-tabs-strip.hire-tabs-slim .dash-tab.hire-tab-slim .hire-tab-icon) {
		font-size: 16px;
		line-height: 1;
	}
	:global(.dash-tabs.hire-tabs-strip.hire-tabs-slim .dash-tab.hire-tab-slim .dash-tab-value),
	:global(.dash-tabs.hire-tabs-strip.hire-tabs-slim .dash-tab.hire-tab-slim .hire-tab-label) {
		font-size: 10px;
		display: block;
		line-height: 1.2;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
		margin-top: 0;
	}

	/* Mobile: stack header vertically */
	@media (max-width: 900px) {
		.hire-hdr-name { font-size: 22px; }
		.hire-hdr-avatar { width: 56px; height: 56px; font-size: 20px; }
		.hire-hdr-contact { flex-direction: column; align-items: flex-start; }
		:global(.dash-tabs.hire-tabs-strip.hire-tabs-slim .dash-tab.hire-tab-slim) {
			padding: 8px 4px; font-size: 10px;
		}
	}
</style>
