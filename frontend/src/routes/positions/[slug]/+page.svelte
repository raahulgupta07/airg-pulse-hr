<script>
	import { onMount, untrack } from 'svelte';
	import { page } from '$app/state';
	import { apiJson, api, authHeaders } from '$lib/api';
	import CompetencyPanel from '$lib/CompetencyPanel.svelte';
	import PositionAITab from '$lib/PositionAITab.svelte';
	import InterviewKit from '$lib/interview-kit/InterviewKit.svelte';
	import CandidatesTable from '$lib/candidates-table/CandidatesTable.svelte';
import CandidateDrawer from '$lib/CandidateDrawer.svelte';
	import Presence from '$lib/Presence.svelte';
	import ActivityFeed from '$lib/ActivityFeed.svelte';
	import Briefcase from '@lucide/svelte/icons/briefcase';
	import Lock from '@lucide/svelte/icons/lock';
	import User from '@lucide/svelte/icons/user';
	import AlertCircle from '@lucide/svelte/icons/alert-circle';
	import Check from '@lucide/svelte/icons/check';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import Circle from '@lucide/svelte/icons/circle';

	/** Position Workspace — 7 tabs */
	let activeTab = $state('candidates');
	let position = $state(null);
	let aiMatchCount = $state(0);

	// Smart defaults: persist active tab per-position via localStorage `pulse_pos_tab_{slug}`
	let _tabRestored = $state(false);
	$effect(() => {
		if (typeof window === 'undefined' || !slug) return;
		const s = slug;
		untrack(() => {
			if (_tabRestored) return;
			try {
				const saved = localStorage.getItem(`pulse_pos_tab_${s}`);
				if (saved) activeTab = saved;
			} catch {}
			_tabRestored = true;
		});
	});
	$effect(() => {
		if (typeof window === 'undefined' || !slug || !_tabRestored) return;
		try { localStorage.setItem(`pulse_pos_tab_${slug}`, activeTab); } catch {}
	});

	function _handleAiCount(ev) {
		try {
			if (ev?.detail?.slug && ev.detail.slug !== slug) return;
			aiMatchCount = Number(ev?.detail?.count ?? 0) || 0;
		} catch {}
	}
	$effect(() => {
		if (typeof window === 'undefined') return;
		window.addEventListener('position-ai-count', _handleAiCount);
		return () => window.removeEventListener('position-ai-count', _handleAiCount);
	});

	let loading = $state(true);
	let candidates = $state([]);
	let pipeline = $state({});
	let scanning = $state(false);
	let aiRecs = $state([]);
	let aiRecsLoading = $state(false);
	let aiRecsLoaded = $state(false);
	let aiRecsLoadedAt = $state(null);
	let aiRecsFilter = $state('available'); // available | in_use | all
	let aiRecsMinScore = $state(60);
	let sourceFilter = $state('all'); // all | ai | manual

	// ── Competency fit per-rec expansion ──
	let fitExpandedId = $state(null);
	let fitData = $state({});       // { [candidate_id]: payload }
	let fitLoading = $state({});    // { [candidate_id]: bool }
	async function toggleFit(rec) {
		const cid = rec.candidate_id;
		if (fitExpandedId === cid) { fitExpandedId = null; return; }
		fitExpandedId = cid;
		if (fitData[cid]) return;
		fitLoading[cid] = true;
		fitLoading = { ...fitLoading };
		try {
			const d = await apiJson(`/positions/${position.slug}/competency-fit/${cid}`);
			fitData[cid] = d;
			fitData = { ...fitData };
		} catch (e) {
			fitData[cid] = { _error: true };
			fitData = { ...fitData };
		}
		fitLoading[cid] = false;
		fitLoading = { ...fitLoading };
	}

	let weightSuggestions = $state([]);
	let weightSuggestionsLoaded = $state(false);
	async function loadWeightSuggestions(refresh = false) {
		if (!position?.slug) return;
		try {
			const d = await apiJson(`/positions/${position.slug}/weight-suggestions${refresh ? '?refresh=true' : ''}`);
			weightSuggestions = d.suggestions || [];
			weightSuggestionsLoaded = true;
		} catch (e) { weightSuggestions = []; weightSuggestionsLoaded = true; }
	}

	let resolvedWeights = $state(null);
	async function loadResolvedWeights() {
		if (!position?.slug) return;
		try {
			resolvedWeights = await apiJson(`/positions/${position.slug}/weights/resolved`);
		} catch {}
	}
	async function loadAiRecs() {
		if (!position?.slug) return;
		aiRecsLoading = true;
		try {
			const url = `/matching/recommendations/${position.slug}?min_score=${aiRecsMinScore}`;
			const d = await apiJson(url);
			aiRecs = d.recommendations || [];
			aiRecsLoaded = true;
			aiRecsLoadedAt = Date.now();
		} catch (e) { cliEvent('error', `Recs load: ${e.message}`); }
		aiRecsLoading = false;
	}
	async function approveRec(rec) {
		try {
			await apiJson(`/matching/scan/${position.slug}/add`, {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [rec.candidate_id] }),
			});
			cliEvent('success', `Attached ${rec.name} to ${position.title}`);
			await loadPosition();
			await loadAiRecs();
		} catch (e) { cliEvent('error', `Approve failed: ${e.message}`); }
	}
	async function rejectRec(rec) {
		try {
			await apiJson(`/matching/scan/${position.slug}/dismiss`, {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [rec.candidate_id] }),
			});
			cliEvent('success', `${rec.name} rejected for this position`);
			await loadAiRecs();
		} catch (e) { cliEvent('error', `Reject failed: ${e.message}`); }
	}
	let generatingJd = $state(false);
	let jdBullets = $state('');
	let jdTone = $state('professional');
	let uploading = $state(false);
	let jdMode = $state(''); // 'generate', 'attach', 'write'
	let pasteJdText = $state('');
	let repoJds = $state([]);
	let selectedRepoJdId = $state(null);
	let loadingRepoJds = $state(false);
	let editingJd = $state(false);
	let editJdText = $state('');

	// ── Evaluation State ──
	let evalConsensus = $state({});
	let evalFlags = $state({});
	let evalVotes = $state({});
	let evalStackRank = $state([]);
	let evalRubrics = $state([]);
	let evalCalibration = $state([]);

	async function loadRepoJds() {
		loadingRepoJds = true;
		try {
			const data = await apiJson('/jds');
			repoJds = data.jds || [];
		} catch (e) { console.error(e); }
		loadingRepoJds = false;
	}

	let attachingJd = $state(false);
	async function attachJdFromRepo() {
		if (!selectedRepoJdId) {
			alert('Pick a JD first by clicking its row.');
			return;
		}
		if (attachingJd) return;
		attachingJd = true;
		try {
			const res = await apiJson(`/jds/${selectedRepoJdId}/use`, {
				method: 'POST',
				body: JSON.stringify({ position_slug: slug }),
			});
			cliEvent('success', `JD #${selectedRepoJdId} attached to ${slug}`);
			window.dispatchEvent(new CustomEvent('pulse-toast', {
				detail: { type: 'success', text: `JD attached. Match Agent will scan CVs against this JD.` }
			}));
			jdMode = '';
			selectedRepoJdId = null;
			await loadPosition();
		} catch (e) {
			console.error('attachJdFromRepo failed', e);
			cliEvent('error', `Attach failed: ${e.message}`);
			window.dispatchEvent(new CustomEvent('pulse-toast', {
				detail: { type: 'error', text: `Attach JD failed: ${e.message}` }
			}));
			alert(`Attach JD failed: ${e.message}`);
		} finally {
			attachingJd = false;
		}
	}

	async function saveWrittenJd() {
		if (!pasteJdText.trim()) return;
		try {
			await apiJson(`/positions/${slug}`, {
				method: 'PATCH',
				body: JSON.stringify({ jd_text: pasteJdText }),
			});
			cliEvent('success', 'JD saved');
			jdMode = '';
			pasteJdText = '';
			await loadPosition();
		} catch (e) { cliEvent('error', `Save failed: ${e.message}`); }
	}

	async function saveEditedJd() {
		try {
			await apiJson(`/positions/${slug}`, {
				method: 'PATCH',
				body: JSON.stringify({ jd_text: editJdText }),
			});
			cliEvent('success', 'JD updated');
			editingJd = false;
			await loadPosition();
		} catch (e) { cliEvent('error', `Save failed: ${e.message}`); }
	}

	const slug = $derived(page.params.slug);

	$effect(() => {
		const s = slug;
		if (s) untrack(() => loadPosition());
	});

	async function loadPosition() {
		loading = true;
		try {
			position = await apiJson(`/positions/${slug}`);
			await loadCandidates();
			loadEvalData();  // fire and forget, don't await
		} catch (e) { console.error(e); }
		loading = false;
	}

	let aiSuggestions = $state([]);
	async function loadCandidates() {
		try {
			const [data, aiData] = await Promise.all([
				apiJson(`/positions/${slug}/candidates`),
				apiJson(`/positions/${slug}/ai`).catch(() => ({ matches: [] })),
			]);
			candidates = data.candidates || [];
			pipeline = data.pipeline || {};
			// Map AI matches into the same shape CandidatesTable expects
			aiSuggestions = (aiData.matches || []).map(m => ({
				...m,
				id: m.id || m.candidate_id,
				attachment_state: 'suggested',
				added_by: m.match_source || 'ai_scan',
				stage: m.stage || 'uploaded',
			}));
		} catch (e) { console.error(e); }
	}

	async function loadEvalData() {
		if (!position) return;
		try {
			const [consensusRes, flagsRes, votesRes, rankRes, rubricsRes, calRes] = await Promise.all([
				apiJson(`/evaluation/positions/${slug}/consensus`).catch(() => ({ consensus: {} })),
				apiJson(`/evaluation/positions/${slug}/flags`).catch(() => ({ flags: {} })),
				apiJson(`/evaluation/positions/${slug}/votes`).catch(() => ({ votes: {} })),
				apiJson(`/evaluation/positions/${slug}/stack-rank`).catch(() => ({ rankings: [] })),
				apiJson(`/evaluation/positions/${slug}/rubrics`).catch(() => ({ rubrics: [] })),
				apiJson(`/evaluation/positions/${slug}/calibration`).catch(() => ({ interviewers: [] })),
			]);
			evalConsensus = consensusRes.consensus || {};
			evalFlags = flagsRes.flags || {};
			evalVotes = votesRes.votes || {};
			evalStackRank = rankRes.rankings || [];
			evalRubrics = rubricsRes.rubrics || [];
			evalCalibration = calRes.interviewers || [];
		} catch (e) { console.error('Eval load:', e); }
	}

	function getRank(candidateId) {
		const entry = evalStackRank.find(e => e.candidate_id === candidateId);
		return entry?.rank;
	}
	function getFlags(candidateId) {
		return evalFlags[candidateId] || [];
	}
	function getVotes(candidateId) {
		return evalVotes[candidateId] || { strong_hire: 0, hire: 0, no_hire: 0, strong_no_hire: 0 };
	}
	function getConsensus(candidateId) {
		return evalConsensus[candidateId] || null;
	}
	function flagColor(type) {
		if (type === 'red') return 'var(--color-error, #c4571a)';
		if (type === 'amber') return 'var(--color-warning, #c98c2a)';
		return '#3a8a4f';
	}

	async function scanRepo() {
		if (!position?.jd_text && !position?.weights_source_jd_id) {
			alert('Add JD to position first to scan CV Pool');
			return;
		}
		scanning = true;
		processingTask = { kind: 'pool-scan', label: 'Pool Scan Agent', message: 'Scoring every CV in Talent Pool against this position…', count: 0, total: null };
		try {
			const data = await apiJson(`/positions/${slug}/ai/rescan`, { method: 'POST' });
			const msg = data.dedup
				? `Pool Scan Agent already running (scan #${data.scan_id})`
				: `Pool Scan Agent queued (scan #${data.scan_id}) — watch progress in Candidates → AI MATCH tab`;
			cliEvent('success', msg);
			if (typeof window !== 'undefined') {
				window.dispatchEvent(new CustomEvent('pulse-toast', { detail: { type: 'success', text: msg } }));
				window.dispatchEvent(new CustomEvent('position-ai-rescan', { detail: { slug, scan_id: data.scan_id, status: data.status } }));
			}
			activeTab = 'candidates';
			// Poll scan status until done
			pollScanUntilDone(data.scan_id);
		} catch (e) {
			cliEvent('error', `Pool Scan Agent failed: ${e.message}`);
			processingTask = null;
		}
		scanning = false;
	}

	let rescoring = $state(false);
	let processingTask = $state(null);  // { kind, label, message, count, total }
	let sugBusy = $state({});  // { [sug_id]: 'apply' | 'dismiss' }

	async function applySug(sid) {
		if (sugBusy[sid]) return;
		sugBusy = { ...sugBusy, [sid]: 'apply' };
		try {
			await apiJson(`/positions/${position.slug}/weight-suggestions/${sid}/apply`, { method: 'POST' });
			cliEvent('success', 'Suggestion applied — weights updated');
			window.dispatchEvent(new CustomEvent('pulse-toast', { detail: { type: 'success', text: 'Suggestion applied' } }));
			await loadPosition();
			await loadWeightSuggestions(true);
		} catch (e) {
			cliEvent('error', `Apply failed: ${e.message}`);
			window.dispatchEvent(new CustomEvent('pulse-toast', { detail: { type: 'error', text: `Apply failed: ${e.message}` } }));
		} finally {
			const next = { ...sugBusy }; delete next[sid]; sugBusy = next;
		}
	}
	async function dismissSug(sid) {
		if (sugBusy[sid]) return;
		sugBusy = { ...sugBusy, [sid]: 'dismiss' };
		try {
			await apiJson(`/positions/${position.slug}/weight-suggestions/${sid}/dismiss`, { method: 'POST' });
			await loadWeightSuggestions(true);
		} catch (e) {
			cliEvent('error', `Dismiss failed: ${e.message}`);
		} finally {
			const next = { ...sugBusy }; delete next[sid]; sugBusy = next;
		}
	}

	async function rescoreAttached() {
		if (rescoring) return;
		rescoring = true;
		processingTask = { kind: 'rescore', label: 'Match Agent', message: 'Re-scoring attached candidates with current weights…', count: 0, total: null };
		try {
			const data = await apiJson(`/positions/${slug}/rescore-attached`, { method: 'POST' });
			const msg = `Match Agent done — re-scored ${data.rescored} candidate(s)`;
			cliEvent('success', msg);
			window.dispatchEvent(new CustomEvent('pulse-toast', { detail: { type: 'success', text: msg } }));
			await loadCandidates();
			activeTab = 'candidates';
		} catch (e) {
			cliEvent('error', `Match Agent failed: ${e.message}`);
		}
		rescoring = false;
		processingTask = null;
	}

	async function pollScanUntilDone(scanId) {
		let tries = 0;
		const maxTries = 60;
		while (tries++ < maxTries) {
			await new Promise(r => setTimeout(r, 1500));
			try {
				const d = await apiJson(`/positions/${slug}/ai`);
				const s = d.scan;
				if (s) {
					processingTask = {
						kind: 'pool-scan',
						label: 'Pool Scan Agent',
						message: `Scoring CVs from Talent Pool…`,
						count: s.n_scored ?? 0,
						total: null,
					};
					if (s.status === 'done' || s.status === 'error') {
						processingTask = null;
						await loadCandidates();
						return;
					}
				}
			} catch {}
		}
		processingTask = null;
	}

	// Template fields (corporate JD form)
	let tplJobCode = $state('');
	let tplBusinessSector = $state('');
	let tplGrading = $state('');
	let tplSeniority = $state('');
	let tplReportingTo = $state('');
	let tplLocation = $state('');
	let tplWorkMode = $state('onsite');
	let tplEmploymentType = $state('full-time');
	let tplJobPurpose = $state('');
	let tplPreferredEducation = $state('');
	let tplTravel = $state('');
	let tplPhysical = $state('');
	let tplDocOwner = $state('');

	async function generateJd() {
		generatingJd = true;
		try {
			const bullets = jdBullets.split('\n').filter(b => b.trim());
			// 1) Create JD via repo (full corporate template)
			const data = await apiJson('/jds/generate', {
				method: 'POST',
				body: JSON.stringify({
					title: position.title,
					department: position.department || '',
					seniority_level: tplSeniority || '',
					employment_type: tplEmploymentType,
					bullets,
					tone: jdTone,
					job_code: tplJobCode || null,
					business_sector: tplBusinessSector || null,
					grading: tplGrading || null,
					reporting_to: tplReportingTo || null,
					location: tplLocation || position.location || null,
					work_mode: tplWorkMode || null,
					travel_requirement: tplTravel || null,
					physical_conditions: tplPhysical || null,
					doc_owner: tplDocOwner || null,
				}),
			});
			// 2) Attach to position
			await apiJson(`/jds/${data.jd_id}/use`, {
				method: 'POST',
				body: JSON.stringify({ position_slug: slug }),
			});
			cliEvent('success', `JD generated + attached (#${data.jd_id})`);
			await loadPosition();
			jdMode = '';
		} catch (e) { cliEvent('error', `JD generation failed: ${e.message}`); }
		generatingJd = false;
	}

	async function saveWrittenJdRich() {
		if (!pasteJdText.trim() || pasteJdText.trim().length < 50) return;
		try {
			const data = await apiJson('/jds/', {
				method: 'POST',
				body: JSON.stringify({
					title: position.title,
					department: position.department || '',
					seniority_level: tplSeniority || '',
					employment_type: tplEmploymentType,
					jd_text: pasteJdText,
					job_code: tplJobCode || null,
					business_sector: tplBusinessSector || null,
					grading: tplGrading || null,
					reporting_to: tplReportingTo || null,
					location: tplLocation || position.location || null,
					work_mode: tplWorkMode || null,
					job_purpose: tplJobPurpose || null,
					preferred_education: tplPreferredEducation || null,
					travel_requirement: tplTravel || null,
					physical_conditions: tplPhysical || null,
					doc_owner: tplDocOwner || null,
				}),
			});
			await apiJson(`/jds/${data.jd_id}/use`, {
				method: 'POST',
				body: JSON.stringify({ position_slug: slug }),
			});
			cliEvent('success', `JD saved + attached (#${data.jd_id})`);
			pasteJdText = '';
			jdMode = '';
			await loadPosition();
		} catch (e) { cliEvent('error', `Save failed: ${e.message}`); }
	}

	async function enhanceJd() {
		try {
			const data = await apiJson(`/positions/${slug}/jd/enhance`, { method: 'POST' });
			position = { ...position, jd_text: data.jd_text };
			cliEvent('success', `JD enhanced — DEI: ${data.compliance?.dei_score || '?'}, Completeness: ${data.compliance?.completeness || '?'}`);
		} catch (e) { cliEvent('error', `Enhance failed: ${e.message}`); }
	}

	async function updateStage(candidateId, newStage) {
		try {
			// Simple PATCH via position_candidates
			await apiJson(`/positions/${slug}`, {
				method: 'PATCH',
				body: JSON.stringify({}), // Just trigger reload
			});
			await loadCandidates();
		} catch (e) { console.error(e); }
	}

	async function uploadCvsToPosition(fileList) {
		uploading = true;
		try {
			// Step 1: ingest each file as CV
			const fd = new FormData();
			for (const f of fileList) fd.append('files', f);
			fd.append('force_type', 'CV');
			const r = await fetch('/api/ingest/', { method: 'POST', body: fd, headers: authHeaders() });
			const d = await r.json();
			const okResults = (d.results || []).filter(x => x.status === 'success' && x.target_id);
			const newIds = okResults.map(x => x.target_id);
			// Split deduped vs fresh runs. Different toast for each.
			for (const x of okResults) {
				if (x.deduped) {
					window.dispatchEvent(new CustomEvent('pulse-toast', { detail: {
						kind: 'dedup',
						filename: x.filename || x.existing_file_name || '',
						candidateId: x.target_id,
						text: `⊙ already in repo · cv_${x.target_id} · skipped pipeline`,
						ttl: 6000
					}}));
				} else {
					window.dispatchEvent(new CustomEvent('pulse-toast', { detail: {
						kind: 'pipeline',
						filename: x.filename || '',
						candidateId: x.target_id,
						runId: x.run_id || null,
						ttl: 5000
					}}));
				}
			}
			if (okResults.length) window.dispatchEvent(new CustomEvent('pulse-feed-refresh'));
			// Step 2: attach all created candidates to this position + auto-score (MANUAL source)
			if (newIds.length) {
				await apiJson(`/matching/scan/${slug}/add`, {
					method: 'POST', body: JSON.stringify({ candidate_ids: newIds, source: 'manual' }),
				});
			}
			cliEvent('success', `Uploaded ${newIds.length} CV(s) · attached + scoring`);
			setTimeout(() => {
				loadCandidates();
				loadPosition();
				if (typeof window !== 'undefined') {
					window.dispatchEvent(new CustomEvent('position-ai-reload', { detail: { slug } }));
				}
			}, 1500);
			// re-poll AI tab a few more times since scoring may take longer than 1.5s
			[4000, 8000, 15000].forEach(ms => setTimeout(() => {
				loadCandidates();
				if (typeof window !== 'undefined') {
					window.dispatchEvent(new CustomEvent('position-ai-reload', { detail: { slug } }));
				}
			}, ms));
		} catch (e) {
			cliEvent('error', `Upload failed: ${e.message}`);
		}
		uploading = false;
	}

	// ── Pool Picker State ──
	let showPoolPicker = $state(false);
	let poolScope = $state('mine');
	let poolItems = $state([]);
	let poolSearch = $state('');
	let poolSelected = $state(new Set());
	let poolLoading = $state(false);

	async function loadPoolCandidates() {
		poolLoading = true;
		try {
			const params = new URLSearchParams({ scope: poolScope, limit: '50', with_assignments: '1' });
			if (poolSearch) params.set('search', poolSearch);
			const d = await apiJson(`/candidates/?${params.toString()}`);
			poolItems = d.candidates || [];
		} catch (e) { cliEvent('error', e.message); }
		poolLoading = false;
	}

	function togglePoolSel(id) {
		if (poolSelected.has(id)) poolSelected.delete(id);
		else poolSelected.add(id);
		poolSelected = new Set(poolSelected);
	}

	async function attachFromPool() {
		const ids = Array.from(poolSelected);
		if (!ids.length) return;
		try {
			await apiJson(`/matching/scan/${slug}/add`, {
				method: 'POST', body: JSON.stringify({ candidate_ids: ids, source: 'pool_pick' }),
			});
			cliEvent('success', `Attached ${ids.length} candidate(s) from Talent Pool · scoring`);
			showPoolPicker = false;
			poolSelected = new Set();
			setTimeout(() => {
				loadCandidates();
				loadPosition();
				if (typeof window !== 'undefined') {
					window.dispatchEvent(new CustomEvent('position-ai-reload', { detail: { slug } }));
				}
			}, 800);
			[3000, 7000].forEach(ms => setTimeout(() => {
				loadCandidates();
				if (typeof window !== 'undefined') {
					window.dispatchEvent(new CustomEvent('position-ai-reload', { detail: { slug } }));
				}
			}, ms));
		} catch (e) { cliEvent('error', `Attach failed: ${e.message}`); }
	}

	function cliEvent(type, text) {
		window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type, text } }));
	}

	/* ── Drag-and-Drop Kanban State ── */
	let dragCandidateId = $state(null);
	let dragFromStage = $state(null);
	let dragOverStage = $state(null);

	function onDragStart(e, candidateId, fromStage) {
		dragCandidateId = candidateId;
		dragFromStage = fromStage;
		e.dataTransfer.effectAllowed = 'move';
		e.dataTransfer.setData('text/plain', candidateId);
	}

	function onDragOver(e, stage) {
		e.preventDefault();
		e.dataTransfer.dropEffect = 'move';
		dragOverStage = stage;
	}

	function onDragLeave(e, stage) {
		if (dragOverStage === stage) dragOverStage = null;
	}

	async function onDrop(e, targetStage) {
		e.preventDefault();
		dragOverStage = null;
		const candidateId = dragCandidateId;
		const fromStage = dragFromStage;
		dragCandidateId = null;
		dragFromStage = null;
		if (!candidateId || fromStage === targetStage) return;
		try {
			await apiJson('/bulk/move-stage', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [candidateId], position_id: position.id, new_stage: targetStage })
			});
			cliEvent('success', `Moved candidate to ${stageLabels[targetStage] || targetStage}`);
			// Hire celebration — fire confetti when promoted to 'hired'
			if (targetStage === 'hired' && fromStage !== 'hired' && typeof window !== 'undefined') {
				window.dispatchEvent(new CustomEvent('pulse-celebrate', { detail: { candidateId, stage: 'hired' } }));
			}
			await loadCandidates();
		} catch (err) {
			cliEvent('error', `Move failed: ${err.message}`);
		}
	}

	function onDragEnd() {
		dragCandidateId = null;
		dragFromStage = null;
		dragOverStage = null;
	}

	/* ── Offers State ── */
	let offers = $state([]);
	let loadingOffers = $state(false);
	let showCreateOffer = $state(false);
	let selectedOffer = $state(null);
	let savingOffer = $state(false);
	let declineReason = $state('');
	let newOffer = $state({
		candidate_id: '', salary_amount: '', salary_currency: 'USD',
		equity: '', bonus: '', start_date: '', expiry_date: '', benefits: '',
	});

	/* ── Approval Chain State ── */
	let approvalChain = $state([]);
	let loadingChain = $state(false);
	let showApprovalModal = $state(false);
	let approverIds = $state([]);
	let newApproverInput = $state('');

	async function loadOffers() {
		if (!position) return;
		loadingOffers = true;
		try {
			const data = await apiJson(`/offers?position_id=${position.id}`);
			offers = data.offers || [];
		} catch (e) { console.error(e); offers = []; }
		loadingOffers = false;
	}

	async function createOffer() {
		if (!newOffer.candidate_id || !newOffer.salary_amount) {
			cliEvent('error', 'Candidate and salary amount are required');
			return;
		}
		savingOffer = true;
		try {
			await apiJson('/offers', {
				method: 'POST',
				body: JSON.stringify({
					position_id: position.id,
					candidate_id: parseInt(newOffer.candidate_id),
					salary_amount: parseFloat(newOffer.salary_amount),
					salary_currency: newOffer.salary_currency,
					equity: newOffer.equity || null,
					bonus: newOffer.bonus || null,
					start_date: newOffer.start_date || null,
					expiry_date: newOffer.expiry_date || null,
					benefits: newOffer.benefits || null,
				}),
			});
			cliEvent('success', 'Offer created');
			showCreateOffer = false;
			newOffer = { candidate_id: '', salary_amount: '', salary_currency: 'USD', equity: '', bonus: '', start_date: '', expiry_date: '', benefits: '' };
			await loadOffers();
		} catch (e) {
			cliEvent('error', `Create offer failed: ${e.message}`);
		}
		savingOffer = false;
	}

	async function offerAction(offerId, action, body = {}) {
		try {
			await apiJson(`/offers/${offerId}/${action}`, {
				method: 'POST',
				body: JSON.stringify(body),
			});
			cliEvent('success', `Offer ${action} successful`);
			selectedOffer = null;
			await loadOffers();
		} catch (e) {
			cliEvent('error', `${action} failed: ${e.message}`);
		}
	}

	async function viewOfferDetail(offerId) {
		try {
			const data = await apiJson(`/offers/${offerId}`);
			selectedOffer = data.offer || data;
			await loadApprovalChain(offerId);
		} catch (e) { cliEvent('error', `Failed to load offer: ${e.message}`); }
	}

	function offerStatusColor(status) {
		const map = { draft: 'var(--color-on-surface-dim, #6f6e69)', approved: '#006f7c', sent: 'var(--color-warning, #c98c2a)', accepted: '#3a8a4f', declined: 'var(--color-error, #c4571a)', withdrawn: 'var(--color-on-surface-dim, #6f6e69)' };
		return map[status] || 'var(--color-on-surface-dim, #6f6e69)';
	}

	function offerStatusTextColor(status) {
		return '#ffffff';
	}

	/* ── Screening Questions State ── */
	let screeningQuestions = $state([]);
	let loadingQuestions = $state(false);
	let showQuestionForm = $state(false);
	let newQuestion = $state({ text: '', question_type: 'text', is_required: false, is_knockout: false, knockout_answer: '', options: [] });
	let newOptionText = $state('');
	let savingQuestion = $state(false);

	async function loadScreeningQuestions() {
		loadingQuestions = true;
		try {
			const data = await apiJson(`/positions/${slug}/screening`);
			screeningQuestions = (Array.isArray(data) ? data : data.questions || []).sort((a, b) => (a.display_order || 0) - (b.display_order || 0));
		} catch (e) { console.error(e); screeningQuestions = []; }
		loadingQuestions = false;
	}

	async function addScreeningQuestion() {
		savingQuestion = true;
		try {
			const body = {
				question_text: newQuestion.text,
				question_type: newQuestion.question_type,
				is_required: newQuestion.is_required,
				is_knockout: newQuestion.is_knockout,
				knockout_answer: newQuestion.is_knockout ? newQuestion.knockout_answer : null,
				options: newQuestion.question_type === 'multiple_choice' ? newQuestion.options : null,
				display_order: screeningQuestions.length,
			};
			await apiJson(`/positions/${slug}/screening`, {
				method: 'POST',
				body: JSON.stringify(body),
			});
			cliEvent('success', 'Screening question added');
			newQuestion = { text: '', question_type: 'text', is_required: false, is_knockout: false, knockout_answer: '', options: [] };
			newOptionText = '';
			showQuestionForm = false;
			await loadScreeningQuestions();
		} catch (e) {
			cliEvent('error', `Failed to add question: ${e.message}`);
		}
		savingQuestion = false;
	}

	async function deleteScreeningQuestion(id) {
		try {
			await apiJson(`/screening/${id}`, { method: 'DELETE' });
			cliEvent('success', 'Question deleted');
			await loadScreeningQuestions();
		} catch (e) {
			cliEvent('error', `Delete failed: ${e.message}`);
		}
	}


	/* ── AI Pipeline Insights State ── */
	let aiInsights = $state(null);
	let loadingInsights = $state(false);

	async function generateAiInsights() {
		loadingInsights = true;
		aiInsights = null;
		try {
			const data = await apiJson('/analytics/ai-insights');
			aiInsights = data.insights || data;
		} catch (e) {
			cliEvent('error', `Failed to generate insights: ${e.message}`);
		}
		loadingInsights = false;
	}

	function insightBorderColor(severity) {
		if (severity === 'high') return 'var(--color-error, #c4571a)';
		if (severity === 'medium') return 'var(--color-warning, #c98c2a)';
		return '#3a8a4f';
	}

	function insightIcon(severity) {
		if (severity === 'high') return 'error';
		if (severity === 'medium') return 'warning';
		return 'info';
	}

	/* ── Automation Rules State ── */
	let automationRules = $state([]);
	let loadingAutomations = $state(false);
	let showAutomationForm = $state(false);
	let savingAutomation = $state(false);
	let newAutomation = $state({
		name: '',
		trigger: 'candidate_scored',
		conditions: [{ field: '', operator: 'equals', value: '' }],
		action: 'move_stage',
		action_config: {},
	});

	async function loadAutomationRules() {
		loadingAutomations = true;
		try {
			const data = await apiJson(`/automations?position_id=${position.id}`);
			automationRules = data.rules || data || [];
		} catch (e) { console.error(e); automationRules = []; }
		loadingAutomations = false;
	}

	async function createAutomation() {
		savingAutomation = true;
		try {
			await apiJson('/automations', {
				method: 'POST',
				body: JSON.stringify({
					position_id: position.id,
					name: newAutomation.name,
					trigger: newAutomation.trigger,
					conditions: newAutomation.conditions,
					action: newAutomation.action,
					action_config: newAutomation.action_config,
				}),
			});
			cliEvent('success', 'Automation rule created');
			showAutomationForm = false;
			newAutomation = { name: '', trigger: 'candidate_scored', conditions: [{ field: '', operator: 'equals', value: '' }], action: 'move_stage', action_config: {} };
			await loadAutomationRules();
		} catch (e) {
			cliEvent('error', `Failed to create automation: ${e.message}`);
		}
		savingAutomation = false;
	}

	async function toggleAutomation(id, isActive) {
		try {
			await apiJson(`/automations/${id}`, {
				method: 'PATCH',
				body: JSON.stringify({ is_active: !isActive }),
			});
			cliEvent('success', `Automation ${!isActive ? 'activated' : 'deactivated'}`);
			await loadAutomationRules();
		} catch (e) { cliEvent('error', `Toggle failed: ${e.message}`); }
	}

	async function deleteAutomation(id) {
		try {
			await apiJson(`/automations/${id}`, { method: 'DELETE' });
			cliEvent('success', 'Automation deleted');
			await loadAutomationRules();
		} catch (e) { cliEvent('error', `Delete failed: ${e.message}`); }
	}

	/* ── SLA Rules State ── */
	let slaRules = $state([]);
	let loadingSla = $state(false);
	let showSlaForm = $state(false);
	let savingSla = $state(false);
	let slaViolations = $state([]);
	let newSla = $state({ stage: 'uploaded', max_days: 7, alert_days: 5 });

	async function loadSlaRules() {
		loadingSla = true;
		try {
			const data = await apiJson(`/analytics/sla-rules?position_id=${position.id}`);
			slaRules = data.rules || data || [];
		} catch (e) { console.error(e); slaRules = []; }
		loadingSla = false;
	}

	async function createSlaRule() {
		savingSla = true;
		try {
			await apiJson('/analytics/sla-rules', {
				method: 'POST',
				body: JSON.stringify({
					position_id: position.id,
					stage: newSla.stage,
					max_days: parseInt(newSla.max_days),
					alert_days: parseInt(newSla.alert_days),
				}),
			});
			cliEvent('success', 'SLA rule created');
			showSlaForm = false;
			newSla = { stage: 'uploaded', max_days: 7, alert_days: 5 };
			await loadSlaRules();
		} catch (e) {
			cliEvent('error', `Failed to create SLA rule: ${e.message}`);
		}
		savingSla = false;
	}

	async function deleteSlaRule(id) {
		try {
			await apiJson(`/analytics/sla-rules/${id}`, { method: 'DELETE' });
			cliEvent('success', 'SLA rule deleted');
			await loadSlaRules();
		} catch (e) { cliEvent('error', `Delete failed: ${e.message}`); }
	}

	async function loadSlaViolations() {
		try {
			const data = await apiJson('/analytics/sla-status');
			slaViolations = data.violations || data || [];
		} catch (e) { console.error(e); slaViolations = []; }
	}

	/* ── Salary Suggestion State ── */
	let salarySuggestion = $state(null);
	let loadingSalary = $state(false);

	async function suggestSalary() {
		loadingSalary = true;
		salarySuggestion = null;
		try {
			const params = new URLSearchParams({ role: position.title, seniority: 'senior', location: position.location || '' });
			const data = await apiJson(`/offers/salary-suggestion?${params}`);
			salarySuggestion = data;
		} catch (e) {
			cliEvent('error', `Salary suggestion failed: ${e.message}`);
		}
		loadingSalary = false;
	}

	function applySuggestedSalary() {
		if (salarySuggestion?.median) {
			newOffer.salary_amount = String(salarySuggestion.median);
			cliEvent('success', 'Median salary applied');
		}
	}

	/* ── AI Compose Email State ── */
	let showEmailCompose = $state(false);
	let emailComposeData = $state({ to: '', subject: '', body: '' });
	let composingEmail = $state(false);

	async function composeOfferEmail(offerId) {
		composingEmail = true;
		try {
			const data = await apiJson('/emails/compose-offer', {
				method: 'POST',
				body: JSON.stringify({ offer_id: offerId }),
			});
			emailComposeData = { to: data.to || '', subject: data.subject || '', body: data.body || data.email || '' };
			showEmailCompose = true;
		} catch (e) {
			cliEvent('error', `Compose failed: ${e.message}`);
		}
		composingEmail = false;
	}

	async function composeRejectionEmail(candidateId, candidateName) {
		composingEmail = true;
		try {
			const data = await apiJson('/emails/compose-rejection', {
				method: 'POST',
				body: JSON.stringify({ position_id: position.id, candidate_id: candidateId, candidate_name: candidateName }),
			});
			emailComposeData = { to: data.to || '', subject: data.subject || '', body: data.body || data.email || '' };
			showEmailCompose = true;
		} catch (e) {
			cliEvent('error', `Compose failed: ${e.message}`);
		}
		composingEmail = false;
	}

	async function loadApprovalChain(offerId) {
		try {
			const data = await apiJson(`/offers/${offerId}/approval-chain`);
			approvalChain = data.chain || data.approval_chain || data || [];
			if (!Array.isArray(approvalChain)) approvalChain = [];
		} catch (e) { approvalChain = []; }
	}

	async function requestApproval() {
		if (approverIds.length === 0 || !selectedOffer) return;
		try {
			await apiJson(`/offers/${selectedOffer.id}/request-approval`, {
				method: 'POST',
				body: JSON.stringify({ approver_ids: approverIds }),
			});
			cliEvent('success', 'Approval requested');
			showApprovalModal = false;
			approverIds = [];
			await loadApprovalChain(selectedOffer.id);
		} catch (e) { cliEvent('error', `Failed: ${e.message}`); }
	}

	async function approveStep(offerId) {
		try {
			await apiJson(`/offers/${offerId}/approve-step`, { method: 'POST', body: JSON.stringify({}) });
			cliEvent('success', 'Step approved');
			await loadApprovalChain(offerId);
			await loadOffers();
		} catch (e) { cliEvent('error', `Approve failed: ${e.message}`); }
	}

	// Templates
	let showTemplateSave = $state(false);
	let templateName = $state('');

	async function saveAsTemplate() {
		if (!templateName.trim()) return;
		try {
			await apiJson('/positions/templates', {
				method: 'POST',
				body: JSON.stringify({ name: templateName, from_slug: slug }),
			});
			cliEvent('success', `Template "${templateName}" saved`);
			showTemplateSave = false;
			templateName = '';
		} catch (e) { cliEvent('error', `Save failed: ${e.message}`); }
	}

	function scoreBarColor(score) {
		if (score >= 70) return 'var(--color-primary)';
		if (score >= 40) return 'var(--color-warning)';
		return 'var(--color-error)';
	}

	const tabs = [
		{ id: 'jd', label: 'JD', icon: 'description' },
		{ id: 'candidates', label: 'Candidates', icon: 'people' },
		{ id: 'pipeline', label: 'Pipeline', icon: 'view_kanban' },
		{ id: 'documents', label: 'Docs', icon: 'draft' },
		{ id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
		{ id: 'interview-kit', label: 'Interview Kit', icon: 'quiz' },
		{ id: 'activity', label: 'Activity', icon: 'timeline' },
		{ id: 'settings', label: 'Settings', icon: 'settings' },
	];

	const stages = ['uploaded', 'screened', 'shortlisted', 'offered', 'hired'];
	const stageLabels = { uploaded: 'Uploaded', screened: 'Screened', shortlisted: 'Shortlisted', offered: 'Offered', hired: 'Hired' };
	const stageColors = { uploaded: '#9c9c8f', screened: '#3a7bbf', shortlisted: '#6f57bd', offered: '#c96342', hired: '#3a8a4f' };
	const stageTints  = { uploaded: '#f3f2ec', screened: '#eaf2fa', shortlisted: '#f0ecf8', offered: '#f8e8e1', hired: '#e6f1e9' };

	/* ── Dashboard Expanded Candidate State ── */
	let expandedDashCandidate = $state(null);
	let dashNotes = $state([]);

	// ─── Candidate Drawer State ───
	let drawerCand = $state(null);
	let drawerNotes = $state([]);
	let drawerScorecards = $state([]);
	let drawerLoading = $state(false);
	let newNote = $state('');
	let savingNote = $state(false);

	// ─── New rich CandidateDrawer (slide-in from right) ───
	let drawerOpen = $state(false);
	let drawerCandidateId = $state(null);
	let drawerContext = $state(null);

	function openDrawer(cid, matchRow = null) {
		if (!cid) return;
		drawerCandidateId = cid;
		drawerContext = { slug, match: matchRow };
		drawerOpen = true;
	}
	function closeDrawer() { drawerOpen = false; }

	async function drawerPromote(cid) {
		if (!cid) return;
		try {
			await apiJson(`/positions/${slug}/ai/${cid}/promote`, { method: 'POST' });
			await loadCandidates();
		} catch (e) {
			alert(e?.message || 'Failed to add to pipeline');
		}
		closeDrawer();
	}
	async function drawerReject(cid) {
		if (!cid) return;
		try {
			await apiJson(`/positions/${slug}/ai/${cid}/reject`, { method: 'POST' });
			await loadCandidates();
		} catch (e) {
			alert(e?.message || 'Failed to reject candidate');
		}
		closeDrawer();
	}

	function openCandidateDrawer(c) {
		drawerCandidateId = c.candidate_id || c.id;
		drawerContext = { slug, match: c };
		drawerOpen = true;
	}

	async function addDrawerNote() {
		if (!newNote.trim() || !drawerCand) return;
		savingNote = true;
		const cid = drawerCand.candidate_id || drawerCand.id;
		try {
			await apiJson(`/candidates/${cid}/notes`, {
				method: 'POST',
				body: JSON.stringify({ content: newNote.trim() }),
			});
			newNote = '';
			const r = await apiJson(`/candidates/${cid}/notes`).catch(() => ({notes: []}));
			drawerNotes = r.notes || (Array.isArray(r) ? r : []);
			cliEvent('success', 'Note added');
		} catch (e) {
			cliEvent('error', `Note failed: ${e.message}`);
		}
		savingNote = false;
	}

	async function moveStage(targetStage) {
		if (!drawerCand) return;
		const cid = drawerCand.candidate_id || drawerCand.id;
		try {
			await apiJson('/bulk/move-stage', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [cid], position_id: position.id, new_stage: targetStage }),
			});
			cliEvent('success', `Moved to ${targetStage}`);
			await loadPosition();
			drawerCand = null;
		} catch (e) {
			cliEvent('error', `Move failed: ${e.message}`);
		}
	}

	async function toggleDashExpand(candidateId) {
		if (expandedDashCandidate === candidateId) { expandedDashCandidate = null; return; }
		expandedDashCandidate = candidateId;
		try {
			const notesData = await apiJson(`/candidates/${candidateId}/notes`);
			dashNotes = Array.isArray(notesData) ? notesData : (notesData.notes || []);
		} catch (e) { dashNotes = []; }
	}

	function formatJdText(text) {
		if (!text) return '';
		const tables = [];
		const lines = text.split('\n');
		const out = [];
		let i = 0;
		while (i < lines.length) {
			const line = lines[i];
			if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|[\s\-:|]+\|\s*$/.test(lines[i + 1])) {
				const header = line.split('|').slice(1, -1).map(c => c.trim());
				i += 2;
				const rows = [];
				while (i < lines.length && /^\s*\|/.test(lines[i])) {
					rows.push(lines[i].split('|').slice(1, -1).map(c => c.trim()));
					i++;
				}
				let html = '<div class="jd-table-wrap"><table class="jd-table"><thead><tr>';
				header.forEach(h => { html += `<th>${h}</th>`; });
				html += '</tr></thead><tbody>';
				rows.forEach((r, rIdx) => {
					html += `<tr class="${rIdx % 2 ? 'alt' : ''}">`;
					r.forEach((c, cIdx) => {
						const inline = c.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
						html += `<td class="${cIdx === 0 ? 'first' : ''}">${inline}</td>`;
					});
					html += '</tr>';
				});
				html += '</tbody></table></div>';
				tables.push(html);
				out.push(` T${tables.length - 1} `);
				continue;
			}
			out.push(line);
			i++;
		}
		let body = out.join('\n').replace(/^#\s+.*$/m, '').trim();
		body = body
			.replace(/^####\s+(.+)$/gm, '<h4 class="jd-h4">$1</h4>')
			.replace(/^###\s+(.+)$/gm,  '<h3 class="jd-h3">$1</h3>')
			.replace(/^##\s+(.+)$/gm,   '<h2 class="jd-h2">$1</h2>')
			.replace(/^#\s+(.+)$/gm,    '<h1 class="jd-h1">$1</h1>')
			.replace(/^\s*---+\s*$/gm, '<hr class="jd-hr"/>')
			.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
			.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
			.replace(/`([^`\n]+)`/g, '<code>$1</code>');
		const lns = body.split('\n');
		const fin = [];
		let inList = false;
		for (const ln of lns) {
			const m = ln.match(/^\s*[•\-\*]\s+(.+)$/);
			if (m) {
				if (!inList) { fin.push('<ul class="jd-ul">'); inList = true; }
				fin.push(`<li>${m[1]}</li>`);
			} else {
				if (inList) { fin.push('</ul>'); inList = false; }
				fin.push(ln);
			}
		}
		if (inList) fin.push('</ul>');
		const blocks = fin.join('\n').split(/\n{2,}/).map(b => {
			const t = b.trim();
			if (!t) return '';
			if (t.startsWith('<')) return t;
			return `<p class="jd-p">${t.replace(/\n/g, '<br/>')}</p>`;
		}).join('\n');
		return blocks.replace(/ T(\d+) /g, (_, n) => tables[+n]);
	}
</script>

{#if loading}
	<div class="h-full flex flex-col overflow-hidden">
		<!-- Skeleton header -->
		<div class="flex items-center gap-4 px-5 py-3" style="border-bottom: 3px solid var(--color-on-surface); background: var(--color-surface-bright);">
			<div class="skeleton" style="width: 50px; height: 16px;"></div>
			<div class="flex-1">
				<div class="skeleton" style="width: 260px; height: 22px; margin-bottom: 6px;"></div>
				<div class="flex gap-2">
					<div class="skeleton" style="width: 80px; height: 14px;"></div>
					<div class="skeleton" style="width: 60px; height: 14px;"></div>
				</div>
			</div>
			<div class="flex gap-2">
				<div class="skeleton" style="width: 90px; height: 32px;"></div>
				<div class="skeleton" style="width: 90px; height: 32px;"></div>
			</div>
		</div>
		<!-- Skeleton tabs -->
		<div class="flex" style="flex-shrink: 0;">
			{#each [1,2,3,4,5,6,7] as _}
				<div class="skeleton" style="flex: 1; height: 40px; border: 1px solid var(--color-outline-variant);"></div>
			{/each}
		</div>
		<!-- Skeleton content -->
		<div style="padding: 20px; flex: 1;">
			<div class="skeleton" style="height: 60px; margin-bottom: 12px;"></div>
			<div class="skeleton" style="height: 120px; margin-bottom: 12px;"></div>
			<div class="skeleton" style="height: 180px;"></div>
		</div>
	</div>
{:else if !position}
	<div class="flex items-center justify-center h-full">
		<p style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Position not found</p>
	</div>
{:else}
<div class="h-full flex flex-col overflow-hidden">
	<!-- Position Header -->
	{#if processingTask}
		<div class="processing-banner">
			<span class="material-symbols-outlined processing-spin">progress_activity</span>
			<div class="processing-text">
				<strong>{processingTask.label}</strong> · {processingTask.message}
				{#if processingTask.count > 0}<span class="processing-count">{processingTask.count} CV{processingTask.count !== 1 ? 's' : ''} processed</span>{/if}
			</div>
		</div>
	{/if}

	<div class="flex items-center gap-4 px-5 py-3" style="border-bottom: 3px solid var(--color-on-surface); background: var(--color-surface-bright);">
		<a href="/" style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--color-on-surface-dim); text-decoration: none;">← Back</a>
		<div class="flex-1 min-w-0">
			<h1 style="font-size: 18px; font-weight: 900; text-transform: uppercase; letter-spacing: -0.02em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
				<Briefcase size={20} /> {position.title}
			</h1>
			<div class="flex gap-2 items-center mt-1">
				<span class="tag-label" style="font-size: 8px;">{position.department || 'N/A'}</span>
				{#if position.location}<span style="font-size: 10px; color: var(--color-on-surface-dim);">{position.location}</span>{/if}
				<span style="font-size: 10px; padding: 1px 6px; border: 1px solid var(--color-primary); color: var(--color-primary); font-weight: 700; text-transform: uppercase;">{position.status}</span>
			</div>
		</div>
		<div class="flex gap-2 flex-shrink-0 items-center">
			<Presence targetType="position" targetId={position.slug || position.id} />
			<button class="btn-secondary" style="font-size: 10px; padding: 6px 12px;" onclick={() => { showPoolPicker = true; loadPoolCandidates(); }}>
				▮ ATTACH FROM TALENT POOL
			</button>
			<button class="send-btn" style="font-size: 10px; padding: 6px 12px;" disabled={uploading}
				onclick={() => document.getElementById('pos-cv-upload')?.click()}>
				{uploading ? 'Uploading...' : '⬆ UPLOAD LOCAL'}
			</button>
			<button class="btn-run-agent btn-run-agent-ghost"
				onclick={rescoreAttached} disabled={rescoring || !!processingTask}
				title="Re-score only candidates ALREADY attached to this position with current weights. Does NOT scan the central CV Pool.">
				{#if rescoring}
					<span class="material-symbols-outlined run-agent-spinner">progress_activity</span>
					Re-scoring…
				{:else}
					<span class="run-agent-spark">↻</span>
					Re-score Attached
				{/if}
			</button>
			<button class="btn-run-agent"
				onclick={scanRepo} disabled={scanning || !!processingTask}
				title="Pool Scan Agent — scans every CV in Talent Pool, AI-recommends matches above threshold into the AI tab. Does not auto-attach below threshold.">
				{#if scanning || processingTask?.kind === 'pool-scan'}
					<span class="material-symbols-outlined run-agent-spinner">progress_activity</span>
					Scanning pool…
				{:else}
					<span class="run-agent-spark">✦</span>
					Scan CV Pool
				{/if}
			</button>
			<input id="pos-cv-upload" type="file" multiple accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.webp,.tiff,.txt,.md" style="display:none;"
				onchange={(e) => { if (e.target.files?.length) uploadCvsToPosition(e.target.files); e.target.value = ''; }} />
		</div>
	</div>

	<!-- Tabs -->
	<div class="dash-tabs" style="flex-shrink: 0;">
		{#each tabs as tab}
			<button class="dash-tab" class:dash-tab-active={activeTab === tab.id} onclick={() => activeTab = tab.id}>
				<span class="material-symbols-outlined" style="font-size: 12px;">{tab.icon}</span>
				<span class="hide-mobile">{tab.label}</span>
				{#if tab.id === 'candidates' && candidates.length}
					<span class="tab-badge">{candidates.length}</span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Tab Content -->
	<div class="dash-panel flex-1" style="overflow-y: auto;">

		<!-- ═══ JD TAB ═══ -->
		{#if activeTab === 'jd'}
			<div class="animate-fade-up">
				{#if position.jd_text && !editingJd}
					<!-- ✦ AI Weight Suggestions banner -->
				{#if !weightSuggestionsLoaded && position}
					{(() => { loadWeightSuggestions(); return ''; })()}
				{/if}
				{#if weightSuggestions.length > 0}
					<div class="sug-card mb-4">
						<div class="sug-head">
							<span class="sug-title">✦ AI Suggestions <span class="sug-count">{weightSuggestions.length}</span></span>
							<button class="sug-refresh" onclick={() => loadWeightSuggestions(true)}>↻ Refresh</button>
						</div>
						<div class="sug-body">
							{#each weightSuggestions as s}
								<div class="sug-row">
									<div class="sug-desc">{s.description}</div>
									<div class="sug-actions">
										<button class="sug-btn-apply"
											disabled={!!sugBusy[s.id]}
											onclick={() => applySug(s.id)}>
											{sugBusy[s.id] === 'apply' ? '…' : 'Apply'}
										</button>
										<button class="sug-btn-dismiss"
											disabled={!!sugBusy[s.id]}
											onclick={() => dismissSug(s.id)}>
											{sugBusy[s.id] === 'dismiss' ? '…' : 'Dismiss'}
										</button>
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- ✦ Scoring Weights — DIFF VIEW with inheritance chain -->
					{#if !resolvedWeights && position}
						{(() => { loadResolvedWeights(); return ''; })()}
					{/if}
					<div class="ink-border stamp-shadow mb-4" style="background: var(--color-surface-bright);">
						<div class="dark-title-bar flex items-center justify-between">
							<span style="display:inline-flex; align-items:center; gap:6px;">✦ Scoring Weights {#if resolvedWeights?.lock?.jd_locked}<Lock size={12} /> JD LOCKED{:else if position.weights_overridden}· OVERRIDDEN{:else if position.weights_source_jd_id}· FROM JD #{position.weights_source_jd_id}{/if}</span>
							{#if position.weights_source_jd_id}
								<button onclick={async () => {
									await apiJson(`/positions/${position.slug}/weights`, { method: 'PATCH', body: JSON.stringify({ reset_from_jd: true }) });
									cliEvent('success', 'Reset from JD');
									await loadPosition(); await loadResolvedWeights();
								}} style="background: transparent; color: var(--color-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 10px; font-weight: 700; cursor: pointer; text-transform: uppercase;">Reset from JD</button>
							{/if}
						</div>
						<div style="padding: 16px;">
							{#if resolvedWeights}
								<div style="overflow-x: auto;">
								<table style="width: 100%; border-collapse: collapse; font-size: 11px;">
									<thead>
										<tr style="background: var(--color-on-surface); color: var(--color-surface);">
											<th style="text-align: left; padding: 6px 10px;">DIM</th>
											<th style="padding: 6px 10px;">TENANT</th>
											<th style="padding: 6px 10px;">SECTOR</th>
											<th style="padding: 6px 10px;">JD</th>
											<th style="padding: 6px 10px;">POSITION</th>
											<th style="padding: 6px 10px;">EFFECTIVE</th>
											<th style="padding: 6px 10px;">SOURCE</th>
										</tr>
									</thead>
									<tbody>
										{#each resolvedWeights.dims as r}
											<tr style="border-top: 1px solid rgba(56,56,50,0.15);">
												<td style="padding: 6px 10px; font-weight: 900; text-transform: uppercase;">{r.dim}{#if r.locked} <Lock size={10} />{/if}{r.forced ? ' ⊕' : ''}</td>
												<td style="text-align:center; padding: 6px 10px; opacity: 0.7;">{r.tenant_min ?? 0}–{r.tenant_max ?? 100}</td>
												<td style="text-align:center; padding: 6px 10px;">{r.sector ?? '—'}</td>
												<td style="text-align:center; padding: 6px 10px;">{r.jd ?? '—'}</td>
												<td style="text-align:center; padding: 6px 10px;">
													<input type="number" min="0" max="100" step="1" value={position[`weight_${r.dim}`] ?? 0}
														disabled={resolvedWeights.lock.jd_locked || r.locked}
														oninput={(e) => { position[`weight_${r.dim}`] = Number(e.target.value); position.weights_overridden = true; }}
														style="width: 60px; border: 2px solid var(--color-on-surface); padding: 2px 4px; font-size: 11px; font-weight: 700; text-align: center; background: {(resolvedWeights.lock.jd_locked || r.locked) ? '#eee' : 'white'};" />
												</td>
												<td style="text-align:center; padding: 6px 10px; font-weight: 900; color: var(--color-primary);">{Math.round(r.effective_normalized)}%</td>
												<td style="padding: 6px 10px; font-size: 10px; opacity: 0.7;">{r.source}</td>
											</tr>
										{/each}
									</tbody>
								</table>
								</div>
								<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px; flex-wrap: wrap; gap: 10px;">
									<div style="font-size: 10px; opacity: 0.7;">
										legend: <Lock size={10} /> jd-locked &nbsp; ⊕ sector-forced &nbsp; floor/cap auto-applied · knockout {Math.round(resolvedWeights.knockout?.value ?? 0)}% ({resolvedWeights.knockout?.source})
									</div>
									<button class="send-btn" style="font-size: 11px; padding: 6px 14px;"
										disabled={resolvedWeights.lock.jd_locked}
										onclick={async () => {
											try {
												await apiJson(`/positions/${position.slug}/weights`, {
													method: 'PATCH',
													body: JSON.stringify({
														weight_skills: position.weight_skills,
														weight_experience: position.weight_experience,
														weight_industry: position.weight_industry,
														weight_education: position.weight_education,
														weight_certifications: position.weight_certifications,
														weight_culture: position.weight_culture,
														normalize: true,
													}),
												});
												cliEvent('success', 'Weights saved');
												await loadPosition(); await loadResolvedWeights();
											} catch (e) { cliEvent('error', e.message); }
										}}>SAVE</button>
								</div>
							{:else}
								<div style="font-size: 11px; opacity: 0.6;">Loading weights chain…</div>
							{/if}
						</div>
					</div>

					<!-- ── JD EXISTS: Show it ── -->
					<div class="flex items-center justify-between mb-3">
						<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Job Description</h2>
						<div class="flex gap-2">
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;" onclick={() => { editingJd = true; editJdText = position.jd_text; }}>Edit</button>
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;" onclick={() => { position = {...position, jd_text: null}; jdMode = ''; }}>Replace</button>
						</div>
					</div>
					{#if position.dei_score || position.completeness_score}
						<div class="flex gap-3 mb-3">
							{#if position.dei_score}<span style="font-size: 10px;"><span class="tag-label" style="font-size: 8px;">DEI</span> {position.dei_score}%</span>{/if}
							{#if position.legal_check !== null}<span style="font-size: 10px;"><span class="tag-label" style="font-size: 8px;">Legal</span> {position.legal_check ? '✓' : '⚠'}</span>{/if}
							{#if position.completeness_score}<span style="font-size: 10px;"><span class="tag-label" style="font-size: 8px;">Complete</span> {position.completeness_score}%</span>{/if}
						</div>
					{/if}
					<div class="ink-border stamp-shadow" style="background: var(--color-surface-bright);">
						<div class="prose-chat" style="padding: 28px 36px; font-family: 'Space Grotesk', sans-serif;">
							{@html formatJdText(position.jd_text)}
						</div>
					</div>
					{#if position.required_skills?.length}
						<div class="mt-4">
							<span class="tag-label mb-2" style="display: block;">Extracted Requirements</span>
							<div class="flex gap-1 flex-wrap">
								{#each position.required_skills as skill}
									<span style="font-size: 10px; padding: 2px 8px; border: 2px solid var(--color-primary); color: var(--color-primary); font-weight: 700; text-transform: uppercase;">{skill}</span>
								{/each}
								{#each (position.nice_to_have_skills || []) as skill}
									<span style="font-size: 10px; padding: 2px 8px; border: 1px dashed var(--color-outline); color: var(--color-on-surface-dim); font-weight: 700; text-transform: uppercase;">{skill}</span>
								{/each}
							</div>
						</div>
					{/if}

				{:else if editingJd}
					<!-- ── EDITING JD ── -->
					<div class="flex items-center justify-between mb-3">
						<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Edit Job Description</h2>
						<div class="flex gap-2">
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;" onclick={() => editingJd = false}>Cancel</button>
							<button class="send-btn" style="font-size: 10px; padding: 5px 12px;" onclick={saveEditedJd}>Save Changes</button>
						</div>
					</div>
					<textarea bind:value={editJdText} rows="20"
						style="width: 100%; padding: 16px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; line-height: 1.7; background: var(--color-surface-bright); resize: vertical;"></textarea>

				{:else if !jdMode}
					<!-- ── NO JD: Show 3 options ── -->
					<div class="text-center py-6">
						<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">description</span>
						<h2 style="font-size: 18px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">Add Job Description</h2>
						<p style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 4px;">Choose how you want to create the JD for this position</p>
					</div>

					<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6" style="max-width: 800px; margin: 0 auto;">
						<!-- Option 1: Generate with AI -->
						<button class="ink-border p-5 text-center" style="background: var(--color-surface-bright); cursor: pointer; transition: transform 0.1s, box-shadow 0.1s;"
							onmouseenter={(e) => e.currentTarget.style.transform = 'translate(-2px,-2px)'}
							onmouseleave={(e) => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'none'; }}
							onclick={() => jdMode = 'generate'}>
							<div style="background: var(--color-primary-container); width: 56px; height: 56px; display: flex; align-items: center; justify-content: center; margin: 0 auto; border: 2px solid var(--color-on-surface);">
								<span class="material-symbols-outlined" style="font-size: 28px;">auto_awesome</span>
							</div>
							<h3 style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">Generate with AI</h3>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 6px; line-height: 1.4;">
								Enter bullet points and let AI create a complete, professional JD
							</p>
						</button>

						<!-- Option 2: Attach from Job Pool -->
						<button class="ink-border p-5 text-center" style="background: var(--color-surface-bright); cursor: pointer; transition: transform 0.1s;"
							onmouseenter={(e) => e.currentTarget.style.transform = 'translate(-2px,-2px)'}
							onmouseleave={(e) => { e.currentTarget.style.transform = 'none'; }}
							onclick={() => { jdMode = 'attach'; loadRepoJds(); }}>
							<div style="background: var(--color-secondary-container); width: 56px; height: 56px; display: flex; align-items: center; justify-content: center; margin: 0 auto; border: 2px solid var(--color-on-surface);">
								<span class="material-symbols-outlined" style="font-size: 28px;">library_books</span>
							</div>
							<h3 style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">Attach from Job Pool</h3>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 6px; line-height: 1.4;">
								Pick an existing JD from your saved library
							</p>
						</button>

						<!-- Option 3: Write Manually -->
						<button class="ink-border p-5 text-center" style="background: var(--color-surface-bright); cursor: pointer; transition: transform 0.1s;"
							onmouseenter={(e) => e.currentTarget.style.transform = 'translate(-2px,-2px)'}
							onmouseleave={(e) => { e.currentTarget.style.transform = 'none'; }}
							onclick={() => jdMode = 'write'}>
							<div style="background: var(--color-surface-highest); width: 56px; height: 56px; display: flex; align-items: center; justify-content: center; margin: 0 auto; border: 2px solid var(--color-on-surface);">
								<span class="material-symbols-outlined" style="font-size: 28px;">edit_note</span>
							</div>
							<h3 style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">Write Manually</h3>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 6px; line-height: 1.4;">
								Paste or type your own job description
							</p>
						</button>
					</div>

				{:else if jdMode === 'generate'}
				<!-- ── AI GENERATE MODAL ── -->
				<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 30px 20px; overflow-y: auto;"
					onclick={(e) => { if (e.target === e.currentTarget) jdMode = ''; }}
					role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') jdMode = ''; }}>
				<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 800px; max-width: 100%; max-height: 90vh; overflow-y: auto;">
					<div class="dark-title-bar flex items-center justify-between" style="position: sticky; top: 0; z-index: 5;">
						<span>✦ Generate JD with AI · {position.title}</span>
						<button onclick={() => jdMode = ''} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">✕</button>
					</div>
					<div style="padding: 18px; display: flex; flex-direction: column; gap: 14px;">

						<!-- I. Role Information -->
						<details open style="border: 2px solid var(--color-on-surface); padding: 10px;">
							<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">I. Role Information</summary>
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
								<div><label class="tag-label mb-1" style="display: block;">Job Code/ID</label><input bind:value={tplJobCode} placeholder="ENG-SE-001" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Business Sector/Entity</label><input bind:value={tplBusinessSector} placeholder="Technology" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Seniority</label>
									<select bind:value={tplSeniority} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
										<option value="">— select —</option>
										{#each ['intern','junior','mid','senior','staff','principal','lead','manager','director','vp'] as s}<option value={s}>{s}</option>{/each}
									</select>
								</div>
								<div><label class="tag-label mb-1" style="display: block;">Grading/Ranking</label><input bind:value={tplGrading} placeholder="L5 / Band 4" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Reporting To</label><input bind:value={tplReportingTo} placeholder="VP Engineering" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Location</label><input bind:value={tplLocation} placeholder={position.location || 'Dubai, UAE'} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Work Mode</label>
									<select bind:value={tplWorkMode} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
										<option value="onsite">Onsite</option><option value="hybrid">Hybrid</option><option value="remote">Remote</option>
									</select>
								</div>
								<div><label class="tag-label mb-1" style="display: block;">Employment Type</label>
									<select bind:value={tplEmploymentType} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
										<option value="full-time">Full-time</option><option value="part-time">Part-time</option><option value="contract">Contract</option><option value="intern">Intern</option><option value="consultant">Consultant</option>
									</select>
								</div>
								<div><label class="tag-label mb-1" style="display: block;">Document Owner</label><input bind:value={tplDocOwner} placeholder="HR Department" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
							</div>
						</details>

						<!-- V. Working Conditions -->
						<details style="border: 2px solid var(--color-on-surface); padding: 10px;">
							<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">V. Working Conditions</summary>
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
								<div><label class="tag-label mb-1" style="display: block;">Travel Requirement</label><input bind:value={tplTravel} placeholder="<10% / Up to 25%" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Physical / Specific Conditions</label><input bind:value={tplPhysical} placeholder="Standard office / On-call rotation" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
							</div>
						</details>

						<!-- AI Bullets -->
						<div>
							<label class="tag-label mb-2" style="display: block;">Key Requirements (one per line)</label>
							<textarea bind:value={jdBullets} rows="5"
								placeholder="Build distributed payment systems&#10;Go and Kubernetes required&#10;5+ years experience&#10;Strong system design skills"
								style="width: 100%; padding: 10px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface); resize: vertical;"></textarea>
							<p style="font-size: 9px; color: var(--color-on-surface-dim); margin-top: 4px; text-transform: uppercase;">Leave empty to auto-generate · more bullets = more specific</p>
						</div>

						<!-- Tone -->
						<div>
							<label class="tag-label mb-2" style="display: block;">Tone</label>
							<div class="flex gap-1 flex-wrap">
								{#each ['professional', 'friendly', 'technical', 'executive', 'startup'] as t}
									<button style="padding: 5px 14px; font-size: 10px; font-weight: 700; text-transform: uppercase; border: 2px solid var(--color-on-surface); cursor: pointer;
										background: {jdTone === t ? 'var(--color-on-surface)' : 'var(--color-surface-bright)'}; color: {jdTone === t ? 'var(--color-primary-container)' : 'var(--color-on-surface)'};"
										onclick={() => jdTone = t}>{t}</button>
								{/each}
							</div>
						</div>

						<button class="send-btn" onclick={generateJd} disabled={generatingJd} style="width: 100%;">
							{generatingJd ? 'Generating JD...' : '✦ Generate JD + Attach'}
						</button>
					</div>
				</div>
				</div>

				{:else if jdMode === 'attach'}
					<!-- ── ATTACH FROM REPO ── -->
					<div class="flex items-center justify-between mb-4">
						<div class="flex items-center gap-2">
							<button onclick={() => jdMode = ''} style="background: none; border: none; cursor: pointer; font-size: 14px; color: var(--color-on-surface-dim);">←</button>
							<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Attach from Job Pool</h2>
						</div>
						<a href="/jds" target="_blank" style="font-size: 10px; color: var(--color-primary); font-weight: 700; text-transform: uppercase; text-decoration: none;">Open Job Pool →</a>
					</div>

					{#if loadingRepoJds}
						{#each [1,2,3] as _}
							<div class="skeleton mb-3" style="height: 70px;"></div>
						{/each}
					{:else if repoJds.length === 0}
						<div class="text-center py-10" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 36px; color: var(--color-on-surface-dim);">library_books</span>
							<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No JDs in Repo</p>
							<p style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 4px;">Create JDs in the <a href="/jds" style="color: var(--color-primary); font-weight: 700;">Job Pool</a> first</p>
						</div>
					{:else}
						<div style="max-height: 400px; overflow-y: auto;">
							{#each repoJds as jd}
								<div class="candidate-row flex items-center gap-3 mb-2" style="cursor: pointer; border-color: {selectedRepoJdId === jd.id ? 'var(--color-primary)' : 'var(--color-on-surface)'}; border-left-width: {selectedRepoJdId === jd.id ? '4px' : '2px'}; border-left-color: {selectedRepoJdId === jd.id ? 'var(--color-primary)' : 'var(--color-on-surface)'};"
									onclick={() => selectedRepoJdId = jd.id}
									role="button" tabindex="0" onkeydown={(e) => { if (e.key === 'Enter') selectedRepoJdId = jd.id; }}>
									<div style="width: 20px; height: 20px; border: 2px solid {selectedRepoJdId === jd.id ? 'var(--color-primary)' : 'var(--color-outline)'}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
										{#if selectedRepoJdId === jd.id}
											<div style="width: 10px; height: 10px; background: var(--color-primary);"></div>
										{/if}
									</div>
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2">
											<span style="font-size: 13px; font-weight: 900;">{jd.title}</span>
											{#if jd.jd_enhanced}
												<span style="font-size: 8px; padding: 1px 5px; background: var(--color-primary); color: white; font-weight: 700; text-transform: uppercase;">Enhanced</span>
											{/if}
										</div>
										<div style="font-size: 11px; color: var(--color-on-surface-dim);">
											{jd.department || 'No dept'} · {jd.seniority_level || ''} · Used {jd.used_count || 0}x
										</div>
										<div class="flex gap-1 mt-1 flex-wrap">
											{#each (jd.required_skills || []).slice(0, 5) as skill}
												<span style="font-size: 8px; padding: 1px 5px; border: 1px solid var(--color-primary); color: var(--color-primary); text-transform: uppercase; font-weight: 700;">{skill}</span>
											{/each}
										</div>
									</div>
								</div>
							{/each}
						</div>
						<div class="flex gap-2 mt-4">
							<button class="btn-secondary" onclick={() => jdMode = ''}>Cancel</button>
							<button class="send-btn" onclick={attachJdFromRepo} disabled={!selectedRepoJdId || attachingJd}>
								{attachingJd ? 'Attaching…' : 'Attach Selected JD'}
							</button>
						</div>
					{/if}

				{:else if jdMode === 'write'}
				<!-- ── WRITE MANUALLY MODAL ── -->
				<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 30px 20px; overflow-y: auto;"
					onclick={(e) => { if (e.target === e.currentTarget) jdMode = ''; }}
					role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') jdMode = ''; }}>
				<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 800px; max-width: 100%; max-height: 90vh; overflow-y: auto;">
					<div class="dark-title-bar flex items-center justify-between" style="position: sticky; top: 0; z-index: 5;">
						<span>✏ Write Job Description · {position.title}</span>
						<button onclick={() => jdMode = ''} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">✕</button>
					</div>
					<div style="padding: 18px; display: flex; flex-direction: column; gap: 14px;">
						<details open style="border: 2px solid var(--color-on-surface); padding: 10px;">
							<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">I. Role Information</summary>
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
								<div><label class="tag-label mb-1" style="display: block;">Job Code/ID</label><input bind:value={tplJobCode} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Business Sector/Entity</label><input bind:value={tplBusinessSector} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Seniority</label>
									<select bind:value={tplSeniority} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
										<option value="">— select —</option>
										{#each ['intern','junior','mid','senior','staff','principal','lead','manager','director','vp'] as s}<option value={s}>{s}</option>{/each}
									</select>
								</div>
								<div><label class="tag-label mb-1" style="display: block;">Grading/Ranking</label><input bind:value={tplGrading} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Reporting To</label><input bind:value={tplReportingTo} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Location</label><input bind:value={tplLocation} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Work Mode</label>
									<select bind:value={tplWorkMode} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
										<option value="onsite">Onsite</option><option value="hybrid">Hybrid</option><option value="remote">Remote</option>
									</select>
								</div>
								<div><label class="tag-label mb-1" style="display: block;">Employment Type</label>
									<select bind:value={tplEmploymentType} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
										<option value="full-time">Full-time</option><option value="part-time">Part-time</option><option value="contract">Contract</option><option value="intern">Intern</option><option value="consultant">Consultant</option>
									</select>
								</div>
								<div><label class="tag-label mb-1" style="display: block;">Document Owner</label><input bind:value={tplDocOwner} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
							</div>
						</details>

						<details style="border: 2px solid var(--color-on-surface); padding: 10px;">
							<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">II. Role Scope & Education (optional — auto-extracted if blank)</summary>
							<div style="display: grid; grid-template-columns: 1fr; gap: 10px; margin-top: 10px;">
								<div><label class="tag-label mb-1" style="display: block;">Job Purpose (2-4 sentences)</label><textarea bind:value={tplJobPurpose} rows="3" placeholder="Why this role exists. Business outcome owned." style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;resize:vertical;"></textarea></div>
								<div><label class="tag-label mb-1" style="display: block;">Preferred Education</label><input bind:value={tplPreferredEducation} placeholder="M.Sc CS (preferred)" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
							</div>
						</details>

						<details style="border: 2px solid var(--color-on-surface); padding: 10px;">
							<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">V. Working Conditions</summary>
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
								<div><label class="tag-label mb-1" style="display: block;">Travel Requirement</label><input bind:value={tplTravel} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
								<div><label class="tag-label mb-1" style="display: block;">Physical / Specific Conditions</label><input bind:value={tplPhysical} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" /></div>
							</div>
						</details>

						<div>
							<label class="tag-label mb-2" style="display: block;">Job Description (paste / write)</label>
							<textarea bind:value={pasteJdText} rows="14"
								placeholder="Paste full JD here…&#10;&#10;## I. Role Information&#10;...&#10;&#10;## III. Key Responsibilities&#10;- ..."
								style="width: 100%; padding: 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; line-height: 1.6; background: var(--color-surface); resize: vertical;"></textarea>
							<p style="font-size: 9px; color: var(--color-on-surface-dim); margin-top: 4px; text-transform: uppercase;">
								{pasteJdText.length} chars · skills auto-extracted on save (min 50)
							</p>
						</div>

						<div class="flex gap-2">
							<button class="btn-secondary" onclick={() => { jdMode = ''; pasteJdText = ''; }}>Cancel</button>
							<button class="send-btn" onclick={saveWrittenJdRich} disabled={pasteJdText.trim().length < 50} style="flex: 1;">
								Save JD + Attach {pasteJdText.trim().length < 50 ? `(${50 - pasteJdText.trim().length} more chars)` : '✓'}
							</button>
						</div>
					</div>
				</div>
				</div>
				{/if}
			</div>

		<!-- ═══ CANDIDATES TAB ═══ -->
		{:else if activeTab === 'candidates'}
			<div class="animate-fade-up">
				<!-- ===== UNIFIED CANDIDATES TABLE (sub-tabs: ALL / UPLOAD / AI / SHORTLISTED / REJECTED) ===== -->
				<CandidatesTable
					{slug}
					{position}
					{candidates}
					{aiSuggestions}
					onReload={async () => { await loadCandidates(); await loadPosition(); if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('position-ai-reload', { detail: { slug } })); }}
					onOpenDrawer={(cid, m) => openDrawer(cid, m)} />
			</div>

			{#if false}
			<div class="legacy-cand-stash">
				<div class="cand-section">
					<PositionAITab {slug} onOpenDrawer={(cid, m) => openDrawer(cid, m)} />
				</div>

				<!-- ===== SHORTLISTED CVS SECTION (mix of AI-promoted + manually attached) ===== -->
				<div class="cand-section cand-section-manual">
					<div class="cand-section-header ink-border stamp-shadow">
						<span class="cand-section-title">SHORTLISTED CVS · {candidates.length} TOTAL · {tabAiCount} AI · {tabManualCount} MANUAL</span>
					</div>

					<!-- SLA Violations Banner -->
					{#if slaViolations.length === 0 && position}
						{(() => { loadSlaViolations(); return ''; })()}
					{/if}
					{#if slaViolations.length > 0}
						<div class="ink-border p-4 mb-4" style="background: rgba(255,59,48,0.06); border-left-width: 4px; border-left-color: #ff3b30;">
							<div class="flex items-center gap-2 mb-2">
								<span class="material-symbols-outlined" style="font-size: 16px; color: #ff3b30;">schedule</span>
								<span style="font-size: 12px; font-weight: 900; text-transform: uppercase; color: #ff3b30;">
									SLA Violations ({slaViolations.length})
								</span>
							</div>
							{#each slaViolations.slice(0, 5) as v}
								<div style="font-size: 11px; padding: 2px 0; border-bottom: 1px solid rgba(255,59,48,0.15);">
									<strong>{v.candidate_name || 'Candidate'}</strong> stuck in <strong>{stageLabels[v.stage] || v.stage}</strong> for {v.days_in_stage || '?'} days (max: {v.max_days || '?'})
								</div>
							{/each}
						</div>
					{/if}

				<!-- Legacy AI Recommendations panel removed — see PositionAITab above. State vars (aiRecs, aiRecsLoaded, fitData, etc.) and handlers (loadAiRecs, approveRec, rejectRec, toggleFit) are kept in the script — harmless dead code, may be reused. -->
				{#if false}
				<div>
					<div>
						<span></span>
						<div class="flex gap-2 items-center">
							<select bind:value={aiRecsFilter}>
								<option value="available">Available</option>
								<option value="in_use">In Use Elsewhere</option>
								<option value="all">All</option>
							</select>
							<input type="number" bind:value={aiRecsMinScore} min="0" max="100" step="5"
								onchange={loadAiRecs}
								style="width: 60px; font-size: 10px; padding: 2px 6px; border: 1px solid var(--color-surface); background: var(--color-surface); color: var(--color-on-surface);" />
							<span style="font-size: 9px; opacity: 0.8;">% min</span>
							<button onclick={loadAiRecs} style="font-size: 10px; padding: 3px 10px; border: 1px solid var(--color-surface); background: transparent; color: var(--color-surface); font-weight: 700; cursor: pointer; text-transform: uppercase;">Rescan</button>
						</div>
					</div>
					<div class="p-3">
						{#if aiRecs.length === 0 && aiRecsLoaded}
							<p style="font-size: 11px; color: var(--color-on-surface-dim); padding: 14px; text-align: center; text-transform: uppercase; letter-spacing: 0.05em;">
								No recommendations above {aiRecsMinScore}%. Lower threshold or rescan.
							</p>
						{/if}
						{#each aiRecs.filter(r => aiRecsFilter === 'all' || (aiRecsFilter === 'available' && r.status === 'available') || (aiRecsFilter === 'in_use' && r.status === 'in_use')) as rec, idx}
							<div class="ink-border" style="padding: 12px; margin-bottom: 10px; background: var(--color-surface);">
								<div class="flex items-start gap-3">
									<div style="font-size: 14px; font-weight: 900; min-width: 30px;">#{idx + 1}</div>
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 flex-wrap mb-1">
											<span style="font-size: 14px; font-weight: 900;">{rec.name || 'Anonymous'}</span>
											<span style="font-size: 10px; padding: 2px 8px; background: var(--color-on-surface); color: var(--color-surface); font-weight: 900;">{Math.round(rec.scores?.composite || rec.score || 0)}%</span>
											{#if rec.status === 'available'}
												<span style="font-size: 9px; padding: 1px 6px; border: 1px solid var(--color-primary); color: var(--color-primary); font-weight: 700; text-transform: uppercase;">✓ Available</span>
											{:else if rec.status === 'in_use'}
												<span style="font-size: 9px; padding: 1px 6px; border: 1px solid var(--color-warning, #c98c2a); color: var(--color-warning, #c98c2a); font-weight: 700; text-transform: uppercase;">⚠ In use ({rec.assignments.length})</span>
											{:else if rec.status === 'in_this'}
												<span style="font-size: 9px; padding: 1px 6px; background: var(--color-primary); color: var(--color-on-surface); font-weight: 700; text-transform: uppercase;">▮ In this position</span>
											{:else if rec.status === 'dismissed'}
												<span style="font-size: 9px; padding: 1px 6px; background: var(--color-on-surface-dim); color: var(--color-surface); font-weight: 700; text-transform: uppercase;">✕ Dismissed</span>
											{/if}
										</div>
										<div style="font-size: 11px; color: var(--color-on-surface-dim);">
											{rec.current_role || 'No role'} · {rec.total_experience_years || 0}y · {rec.current_company || '—'}
										</div>
										{#if rec.scores}
											<div style="font-size: 10px; margin-top: 4px;">
												skills {Math.round(rec.scores.skills || 0)} · exp {Math.round(rec.scores.experience || 0)} · cert {Math.round(rec.scores.certifications || 0)} · ind {Math.round(rec.scores.industry || 0)}
											</div>
											<details style="margin-top: 6px;">
												<summary style="font-size: 10px; cursor: pointer; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.06em;">▸ score breakdown</summary>
												<table style="margin-top: 6px; font-size: 10px; border-collapse: collapse;">
													<tbody>
														{#each [
															['Skills', rec.scores.skills, position?.weight_skills],
															['Experience', rec.scores.experience, position?.weight_experience],
															['Industry', rec.scores.industry, position?.weight_industry],
															['Education', rec.scores.education, position?.weight_education],
															['Certifications', rec.scores.certifications, position?.weight_certifications],
															['Culture', rec.scores.culture, position?.weight_culture],
														] as [lbl, sc, w]}
															<tr>
																<td style="padding: 1px 6px;">{lbl}</td>
																<td style="padding: 1px 6px; text-align: right;">{Math.round(sc || 0)}</td>
																<td style="padding: 1px 6px; opacity: 0.6;">×</td>
																<td style="padding: 1px 6px; text-align: right;">{((w || 0)/100).toFixed(2)}</td>
																<td style="padding: 1px 6px; opacity: 0.6;">=</td>
																<td style="padding: 1px 6px; font-weight: 900; text-align: right;">{((sc || 0) * (w || 0) / 100).toFixed(1)}</td>
															</tr>
														{/each}
														<tr style="border-top: 1px dashed var(--color-on-surface);">
															<td colspan="5" style="padding: 2px 6px; font-weight: 900;">TOTAL</td>
															<td style="padding: 2px 6px; font-weight: 900; text-align: right;">{Math.round(rec.scores?.composite || rec.score || 0)}</td>
														</tr>
													</tbody>
												</table>
											</details>
										{/if}

										<!-- Currently attached to -->
										{#if rec.assignments?.length}
											<div class="ink-border" style="margin-top: 8px; padding: 8px; background: rgba(255,157,0,0.06);">
												<div style="font-size: 10px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 4px;">Currently attached to ({rec.assignments.length})</div>
												{#each rec.assignments as a}
													<div class="flex items-center justify-between" style="font-size: 11px; padding: 3px 0; border-top: 1px dashed rgba(56,56,50,0.15);">
														<div>
															<a href="/positions/{a.slug}" style="font-weight: 700; color: var(--color-on-surface);">{a.title}</a>
															<span style="margin-left: 8px; padding: 1px 6px; font-size: 9px; font-weight: 700; text-transform: uppercase; background: var(--color-on-surface); color: var(--color-surface);">{a.stage}</span>
															{#if a.match_score}<span style="margin-left: 6px; font-size: 10px; color: var(--color-on-surface-dim);">match {Math.round(a.match_score)}%</span>{/if}
														</div>
														<div style="font-size: 9px; color: var(--color-on-surface-dim);">
															{a.recruiter_name || ''} · {a.added_at ? new Date(a.added_at).toLocaleDateString() : ''}
														</div>
													</div>
												{/each}
											</div>
										{/if}

										<div class="flex gap-2 mt-2 flex-wrap">
											{#if rec.status === 'in_this'}
												<a href="/candidates/{rec.candidate_id}" class="btn-secondary" style="font-size: 10px; padding: 4px 10px; text-decoration: none;">View →</a>
											{:else if rec.status === 'dismissed'}
												<span style="font-size: 10px; color: var(--color-on-surface-dim); padding: 4px 0;">Already rejected for this position</span>
											{:else}
												<button class="send-btn" style="font-size: 10px; padding: 4px 12px;" onclick={() => approveRec(rec)}>
													✓ Approve & Attach{rec.status === 'in_use' ? ' Anyway' : ''}
												</button>
												<button class="btn-secondary" style="font-size: 10px; padding: 4px 12px; border-color: var(--color-error); color: var(--color-error);" onclick={() => rejectRec(rec)}>
													✕ Reject for this position
												</button>
												<a href="/candidates/{rec.candidate_id}" class="btn-secondary" style="font-size: 10px; padding: 4px 10px; text-decoration: none;">View</a>
											{/if}
											<button class="btn-secondary" style="font-size: 10px; padding: 4px 12px;" onclick={() => toggleFit(rec)}>
												{fitExpandedId === rec.candidate_id ? '▾ Hide Competency Fit' : '▸ Competency Fit'}
											</button>
										</div>

										<!-- Competency Fit Panel -->
										{#if fitExpandedId === rec.candidate_id}
											<div class="ink-border" style="margin-top: 10px; padding: 12px 14px; background: var(--color-surface-bright);">
												{#if fitLoading[rec.candidate_id]}
													<div style="font-size: 11px; opacity: 0.6; text-transform: uppercase;">Loading competency fit…</div>
												{:else if fitData[rec.candidate_id]?._error || !fitData[rec.candidate_id]}
													<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.05em; padding: 8px;">
														No competency fit available — tag this position with competencies and rate the candidate first.
													</div>
												{:else}
													{@const fit = fitData[rec.candidate_id]}
													{@const perComp = fit.per_comp || []}
													<div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 10px;">
														<div style="font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em;">Competency Fit — {rec.name}</div>
														<div style="font-size: 14px; font-weight: 900; padding: 2px 10px; background: {Number(fit.fit_pct || 0) >= 70 ? '#3a8a4f' : Number(fit.fit_pct || 0) >= 40 ? 'var(--color-warning, #c98c2a)' : 'var(--color-error, #c4571a)'}; color: #fff; border-radius: 4px;">
															FIT {Math.round(fit.fit_pct || 0)}%
														</div>
														<div style="font-size: 11px; opacity: 0.8;">
															{perComp.filter(p => Number(p.gap || 0) < 0).length} gaps · {fit.critical_gaps_count ?? perComp.filter(p => p.gap == null || (p.actual == null)).length} critical
														</div>
													</div>
													<table style="width: 100%; border-collapse: collapse; font-size: 11px;">
														<thead>
															<tr style="background: var(--color-surface-highest, #f5f5e0);">
																<th style="text-align: left; padding: 4px 8px; font-size: 10px; text-transform: uppercase;">Competency</th>
																<th style="text-align: center; padding: 4px 8px; font-size: 10px; text-transform: uppercase;">Required</th>
																<th style="text-align: center; padding: 4px 8px; font-size: 10px; text-transform: uppercase;">Actual</th>
																<th style="text-align: center; padding: 4px 8px; font-size: 10px; text-transform: uppercase;">Gap</th>
																<th style="text-align: center; padding: 4px 8px; font-size: 10px; text-transform: uppercase;">Status</th>
															</tr>
														</thead>
														<tbody>
															{#each perComp as p}
																{@const gapVal = Number(p.gap ?? ((p.actual ?? 0) - (p.required ?? 0)))}
																{@const noSignal = p.actual == null}
																<tr style="border-bottom: 1px solid var(--color-outline-variant);">
																	<td style="padding: 4px 8px; font-weight: 700;">{p.label || p.key}</td>
																	<td style="padding: 4px 8px; text-align: center;">{p.required ?? '—'}</td>
																	<td style="padding: 4px 8px; text-align: center;">{p.actual != null ? Number(p.actual).toFixed(1) : '—'}</td>
																	<td style="padding: 4px 8px; text-align: center; font-weight: 900; color: {gapVal >= 0 ? '#3a8a4f' : gapVal >= -1 ? 'var(--color-warning, #c98c2a)' : 'var(--color-error, #c4571a)'};">
																		{noSignal ? `-${(p.required ?? 0)}.0` : (gapVal >= 0 ? '+' : '') + gapVal.toFixed(1)}
																	</td>
																	<td style="padding: 4px 8px; text-align: center;">
																		{#if noSignal}<Circle size={10} fill="#dc2626" stroke="#dc2626" /> critical{:else if gapVal >= 0}<Check size={11} />{:else if gapVal >= -1}<AlertTriangle size={11} />{:else}<Circle size={10} fill="#dc2626" stroke="#dc2626" />{/if}
																	</td>
																</tr>
															{/each}
														</tbody>
													</table>
													{#if perComp.some(p => p.actual == null || Number(p.gap ?? 0) < 0)}
														<div style="margin-top: 10px; padding: 8px 12px; border-left: 3px solid var(--color-on-surface); background: var(--color-surface);">
															<div style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px;">Focus Areas</div>
															{#each perComp.filter(p => p.actual == null) as p}
																<div style="font-size: 11px;">✦ Probe <strong>{p.label || p.key}</strong> (no signal)</div>
															{/each}
															{#each perComp.filter(p => p.actual != null && Number(p.gap ?? 0) < 0 && Number(p.gap ?? 0) >= -1) as p}
																<div style="font-size: 11px;">✦ Verify <strong>{p.label || p.key}</strong> depth</div>
															{/each}
														</div>
													{/if}
												{/if}
											</div>
										{/if}
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
				{/if}

				{#if candidates.length === 0}
					<div class="flex flex-col items-center py-12" style="border: 3px dashed var(--color-outline-variant);">
						<span class="material-symbols-outlined" style="font-size: 36px; color: var(--color-on-surface-dim);">group_add</span>
						<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No candidates yet</p>
						<p style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 4px;">Click "Scan Repo" to find matches or upload CVs</p>
					</div>
				{:else}
					{@const aiCount = candidates.filter(c => c.auto_added || c.added_by === 'ai_scan' || c.added_by === 'auto_match' || c.added_by === 'ai_auto').length}
					{@const manualCount = candidates.length - aiCount}
					{@const filteredCandidates = candidates.filter(c => { const isAi = c.auto_added || c.added_by === 'ai_scan' || c.added_by === 'auto_match' || c.added_by === 'ai_auto'; return sourceFilter === 'all' ? true : (sourceFilter === 'ai' ? isAi : !isAi); })}
					<div class="flex items-center justify-between mb-2 flex-wrap gap-2">
						<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase;">
							{filteredCandidates.length} of {candidates.length} candidates · Sorted by match score
						</div>
						<div class="flex gap-1" style="font-size: 10px;">
							<button onclick={() => sourceFilter = 'all'} class="ink-border" style="padding: 4px 10px; font-weight: 900; cursor: pointer; background: {sourceFilter === 'all' ? 'var(--color-on-surface)' : 'transparent'}; color: {sourceFilter === 'all' ? 'var(--color-surface)' : 'var(--color-on-surface)'};">ALL · {candidates.length}</button>
							<button onclick={() => sourceFilter = 'ai'} class="ink-border" style="padding: 4px 10px; font-weight: 900; cursor: pointer; background: {sourceFilter === 'ai' ? 'var(--color-accent, #c96342)' : 'transparent'}; color: {sourceFilter === 'ai' ? '#fff' : 'var(--color-on-surface)'};">✨ AI · {aiCount}</button>
							<button onclick={() => sourceFilter = 'manual'} class="ink-border" style="padding: 4px 10px; font-weight: 900; cursor: pointer; background: {sourceFilter === 'manual' ? 'var(--color-on-surface)' : 'transparent'}; color: {sourceFilter === 'manual' ? 'var(--color-surface)' : 'var(--color-on-surface)'}; display:inline-flex; align-items:center; gap:6px;"><User size={12} /> MANUAL · {manualCount}</button>
						</div>
					</div>
					{#each filteredCandidates as c, i}
						<div class="candidate-row flex items-start gap-3"
							role="button" tabindex="0"
							onclick={(e) => { if (e.target.closest('button, a, input')) return; openDrawer(c.candidate_id || c.id, c); }}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(c.candidate_id || c.id, c); } }}
							style="animation: fadeUp 0.3s ease-out; animation-delay: {i * 0.02}s; animation-fill-mode: both; opacity: 0; cursor: pointer;">
							<!-- Rank -->
							<div style="font-size: 16px; font-weight: 900; color: var(--color-on-surface-dim); min-width: 24px; text-align: center; padding-top: 4px;">
								#{getRank(c.candidate_id || c.id) || (i + 1)}
							</div>
							<!-- Score circle -->
							<div style="width: 48px; height: 48px; border: 3px solid {scoreBarColor(c.match_score_composite || 0)}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
								<span style="font-size: 14px; font-weight: 900; color: {scoreBarColor(c.match_score_composite || 0)};">
									{Math.round(c.match_score_composite || 0)}%
								</span>
							</div>
							<!-- Info -->
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2">
									<span style="font-size: 14px; font-weight: 900;">{c.name || 'Unknown'}</span>
									<span style="font-size: 9px; padding: 1px 6px; background: {stageColors[c.stage] || 'var(--color-on-surface-dim, #6f6e69)'}; color: white; font-weight: 700; text-transform: uppercase; border-radius: 4px;">{c.stage}</span>
									{#if c.auto_added || ['ai_promoted','auto_scan_on_create','auto_scan_on_jd_update','auto_scan_rescan'].includes(c.match_source) || c.added_by === 'ai_scan' || c.added_by === 'auto_match' || c.added_by === 'ai_auto'}
										<span title="Added by AI scan" style="font-size: 9px; padding: 1px 6px; background: var(--color-accent, #c96342); color: #fff; font-weight: 900; border-radius: 4px;">✨ AI</span>
									{:else}
										<span title="Manually added" style="font-size: 9px; padding: 1px 6px; background: var(--color-surface); color: var(--color-on-surface); font-weight: 700; border: 1px solid var(--color-on-surface);">MANUAL</span>
									{/if}
									{#each getFlags(c.candidate_id || c.id).slice(0, 5) as flag}
										<span title="{flag.title}: {flag.description}" style="display: inline-block; width: 8px; height: 8px; background: {flagColor(flag.flag_type)}; border: 1px solid var(--color-on-surface);"></span>
									{/each}
									{#if getVotes(c.candidate_id || c.id).strong_hire + getVotes(c.candidate_id || c.id).hire + getVotes(c.candidate_id || c.id).no_hire + getVotes(c.candidate_id || c.id).strong_no_hire > 0}
										<span style="font-size: 8px; padding: 1px 4px; border: 1px solid var(--color-on-surface); font-weight: 700;">
											SH:{getVotes(c.candidate_id || c.id).strong_hire} H:{getVotes(c.candidate_id || c.id).hire} NH:{getVotes(c.candidate_id || c.id).no_hire}
										</span>
									{/if}
								</div>
								<div style="font-size: 12px; color: var(--color-on-surface-dim);">
									{c.current_role || 'N/A'} · {c.total_experience_years || 0}yr
								</div>
								<!-- Score bars -->
								<div class="flex gap-3 mt-2" style="font-size: 10px;">
									{#each [
										['Skills', c.match_score_skills],
										['Exp', c.match_score_experience],
										['Edu', c.match_score_education],
										['Cert', c.match_score_certifications],
										['Ind', c.match_score_industry],
										['Culture', c.match_score_culture],
									] as [label, score]}
										<div style="min-width: 60px;">
											<div style="font-weight: 700; text-transform: uppercase; font-size: 8px; letter-spacing: 0.05em; color: var(--color-on-surface-dim);">{label}</div>
											<div class="score-bar" style="width: 60px; margin-top: 2px;">
												<div class="score-bar-fill {score >= 70 ? 'score-high' : score >= 40 ? 'score-mid' : 'score-low'}" style="width: {score || 0}%;"></div>
											</div>
											<span style="font-size: 9px; font-weight: 700;">{Math.round(score || 0)}%</span>
										</div>
									{/each}
								</div>
								{#if c.skills_matched?.length}
									<div class="flex gap-1 mt-1 flex-wrap">
										{#each c.skills_matched.slice(0, 6) as s}
											<span style="font-size: 8px; padding: 0px 4px; border: 1px solid var(--color-primary); color: var(--color-primary); text-transform: uppercase; font-weight: 700;">✓{s}</span>
										{/each}
										{#each (c.skills_missing || []).slice(0, 3) as s}
											<span style="font-size: 8px; padding: 0px 4px; border: 1px solid var(--color-error); color: var(--color-error); text-transform: uppercase; font-weight: 700;">✗{s}</span>
										{/each}
									</div>
								{/if}
								{#if getConsensus(c.candidate_id || c.id)?.evaluator_count > 0}
									<div style="font-size: 9px; margin-top: 3px; padding: 2px 6px; border: 1px solid var(--color-outline); display: inline-block;">
										CONSENSUS: {getConsensus(c.candidate_id || c.id).avg_overall?.toFixed?.(1) || getConsensus(c.candidate_id || c.id).avg_overall}/5 ({getConsensus(c.candidate_id || c.id).evaluator_count} eval) · {(getConsensus(c.candidate_id || c.id).agreement_level || '').replace('_', ' ').toUpperCase()}
										{#if getConsensus(c.candidate_id || c.id).lone_dissent_flag}<span style="color: var(--color-warning, #c98c2a);"> · DISSENT</span>{/if}
									</div>
								{/if}
							</div>
						</div>
					{/each}
				{/if}

				<!-- Email Compose Modal -->
				{#if showEmailCompose}
					<div style="position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1000; display: flex; align-items: center; justify-content: center;"
						onclick={(e) => { if (e.target === e.currentTarget) showEmailCompose = false; }}>
						<div class="ink-border p-6" style="background: var(--color-surface); width: 90%; max-width: 560px; max-height: 85vh; overflow-y: auto;">
							<div class="flex items-center justify-between mb-4">
								<h3 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Compose Email</h3>
								<button onclick={() => showEmailCompose = false} style="background: none; border: none; cursor: pointer; font-size: 18px; font-weight: 900;">X</button>
							</div>
							<div style="display: flex; flex-direction: column; gap: 10px;">
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">To</label>
									<input type="text" bind:value={emailComposeData.to} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);" />
								</div>
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Subject</label>
									<input type="text" bind:value={emailComposeData.subject} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);" />
								</div>
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Body</label>
									<textarea bind:value={emailComposeData.body} rows="12" style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); resize: vertical; line-height: 1.6;"></textarea>
								</div>
								<div class="flex gap-2">
									<button class="send-btn" style="flex: 1; padding: 10px; font-size: 11px;" onclick={() => { navigator.clipboard.writeText(emailComposeData.body); cliEvent('success', 'Email copied to clipboard'); }}>
										<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">content_copy</span>
										Copy to Clipboard
									</button>
									<button class="btn-secondary" style="padding: 10px; font-size: 11px;" onclick={() => showEmailCompose = false}>Close</button>
								</div>
							</div>
						</div>
					</div>
				{/if}
				</div><!-- /.cand-section-manual -->
			</div><!-- /.legacy-cand-stash -->
			{/if}

		<!-- ═══ PIPELINE TAB ═══ -->
		{:else if activeTab === 'pipeline'}
			<div class="animate-fade-up" style="overflow-x: auto; padding-bottom: 40px;">
				<div class="flex gap-3 pb-4" style="min-width: {stages.length * 190}px; align-items: flex-start;">
					{#each stages as stage}
						{@const stageCandidates = candidates.filter(c => c.stage === stage)}
						<div class="kanban-column"
							style="flex: 1; min-width: 200px; display: flex; flex-direction: column; align-self: flex-start;
								background: {stageTints[stage]};
								border: 1px solid {dragOverStage === stage ? stageColors[stage] : 'var(--color-border, #e8e6dd)'};
								box-shadow: {dragOverStage === stage ? `0 0 0 2px ${stageColors[stage]} inset` : 'none'};
								border-radius: 10px; overflow: hidden;
								transition: border-color 0.15s ease, box-shadow 0.15s ease;"
							ondragover={(e) => onDragOver(e, stage)}
							ondragleave={(e) => onDragLeave(e, stage)}
							ondrop={(e) => onDrop(e, stage)}>
							<div style="height: 4px; background: {stageColors[stage]}; flex-shrink: 0;"></div>
							<div style="display: flex; align-items: center; justify-content: space-between; padding: 11px 14px; background: var(--color-surface-bright, #fff); border-bottom: 1px solid var(--color-border, #e8e6dd); position: sticky; top: 0; z-index: 5;">
								<span style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: {stageColors[stage]};">
									{stageLabels[stage] || stage}
								</span>
								<span style="font-size: 11px; font-weight: 700; padding: 2px 9px; background: {stageColors[stage]}; color: #fff; border-radius: 999px;">
									{stageCandidates.length}
								</span>
							</div>
							<div class="p-2 overflow-y-auto" style="min-height: 160px; max-height: calc(100vh - 280px);">
								{#each stageCandidates as c, i}
									<div class="kanban-card"
										draggable="true"
										ondragstart={(e) => onDragStart(e, c.candidate_id || c.id, stage)}
										ondragend={onDragEnd}
										onclick={() => openCandidateDrawer(c)}
										role="button" tabindex="0"
										onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') openCandidateDrawer(c); }}
										style="cursor: pointer; animation: fadeUp 0.25s ease-out; animation-delay: {i * 0.03}s; animation-fill-mode: both; opacity: 0;">
										<div class="flex items-center gap-1">
											<span class="material-symbols-outlined" style="font-size: 14px; color: var(--color-on-surface-dim); cursor: grab;">drag_indicator</span>
											{#if getRank(c.candidate_id || c.id)}<span style="font-size: 9px; font-weight: 900; padding: 0 3px; border: 1px solid var(--color-on-surface);">#{getRank(c.candidate_id || c.id)}</span>{/if}
											<div style="font-size: 12px; font-weight: 900; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{c.name || '?'}</div>
											{#each getFlags(c.candidate_id || c.id).slice(0, 3) as flag}
												<span title="{flag.title}" style="display: inline-block; width: 6px; height: 6px; background: {flagColor(flag.flag_type)}; border: 1px solid var(--color-on-surface);"></span>
											{/each}
										</div>
										<div style="font-size: 10px; color: var(--color-on-surface-dim); padding-left: 18px;">{c.current_role || 'N/A'}</div>
										<div class="flex items-center gap-1 mt-1" style="padding-left: 18px;">
											<div class="score-bar" style="flex: 1;">
												<div class="score-bar-fill {(c.match_score_composite || 0) >= 70 ? 'score-high' : 'score-mid'}" style="width: {c.match_score_composite || 0}%;"></div>
											</div>
											<span style="font-size: 10px; font-weight: 900;">{Math.round(c.match_score_composite || 0)}%</span>
										</div>
										{#if getVotes(c.candidate_id || c.id).strong_hire + getVotes(c.candidate_id || c.id).hire + getVotes(c.candidate_id || c.id).no_hire + getVotes(c.candidate_id || c.id).strong_no_hire > 0}
											<div style="font-size: 7px; padding-left: 18px; font-weight: 700; color: var(--color-on-surface-dim); text-transform: uppercase; margin-top: 1px;">
												{getVotes(c.candidate_id || c.id).strong_hire + getVotes(c.candidate_id || c.id).hire}Y / {getVotes(c.candidate_id || c.id).no_hire + getVotes(c.candidate_id || c.id).strong_no_hire}N
											</div>
										{/if}
										<!-- Kanban card actions -->
										<div class="flex gap-1 mt-1" style="padding-left: 18px;">
											<button style="font-size: 8px; padding: 2px 6px; border: 1px solid var(--color-error); background: none; cursor: pointer; font-weight: 700; text-transform: uppercase; color: var(--color-error);"
												onclick={(e) => { e.stopPropagation(); composeRejectionEmail(c.candidate_id || c.id, c.name); }}>Reject Email</button>
										</div>
									</div>
								{/each}
								{#if stageCandidates.length === 0}
									<p style="font-size: 9px; color: var(--color-on-surface-dim); text-align: center; padding: 20px 0; text-transform: uppercase;">
										{dragOverStage === stage ? 'Drop here' : 'Empty'}
									</p>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</div>

		<!-- ═══ DOCUMENTS / OFFERS TAB ═══ -->
		{:else if activeTab === 'documents'}
			<div class="animate-fade-up">
				<!-- Header -->
				<div class="flex items-center justify-between mb-4">
					<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">Offers</h2>
					<button class="send-btn" style="font-size: 10px; padding: 6px 14px;" onclick={() => { showCreateOffer = true; loadOffers(); }}>
						+ Create Offer
					</button>
				</div>

				<!-- Load offers on tab open -->
				{#if !offers.length && !loadingOffers}
					{(() => { loadOffers(); return ''; })()}
				{/if}

				<!-- Create Offer Modal -->
				{#if showCreateOffer}
					<div style="position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1000; display: flex; align-items: center; justify-content: center;"
						onclick={(e) => { if (e.target === e.currentTarget) showCreateOffer = false; }}>
						<div class="ink-border p-6" style="background: var(--color-surface); width: 90%; max-width: 520px; max-height: 85vh; overflow-y: auto;">
							<div class="flex items-center justify-between mb-4">
								<h3 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">New Offer</h3>
								<button onclick={() => showCreateOffer = false} style="background: none; border: none; cursor: pointer; font-size: 18px; font-weight: 900;">X</button>
							</div>

							<div style="display: flex; flex-direction: column; gap: 12px;">
								<!-- Candidate -->
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Candidate</label>
									<select bind:value={newOffer.candidate_id} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);">
										<option value="">Select candidate...</option>
										{#each candidates as c}
											<option value={c.candidate_id || c.id}>{c.name || 'Unknown'} — {c.current_role || 'N/A'}</option>
										{/each}
									</select>
								</div>

								<!-- Salary row -->
								<div class="flex gap-3">
									<div style="flex: 2;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Salary Amount</label>
										<input type="number" bind:value={newOffer.salary_amount} placeholder="120000" style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);" />
									</div>
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Currency</label>
										<select bind:value={newOffer.salary_currency} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);">
											<option value="USD">USD</option>
											<option value="EUR">EUR</option>
											<option value="GBP">GBP</option>
											<option value="INR">INR</option>
											<option value="CAD">CAD</option>
											<option value="AUD">AUD</option>
										</select>
									</div>
								</div>

								<!-- Salary Suggestion -->
								<div>
									<button class="btn-secondary" style="font-size: 9px; padding: 4px 12px; width: 100%;" onclick={suggestSalary} disabled={loadingSalary}>
										<span class="material-symbols-outlined" style="font-size: 12px; vertical-align: middle;">auto_awesome</span>
										{loadingSalary ? 'Fetching...' : 'AI Suggest Salary'}
									</button>
									{#if salarySuggestion}
										<div class="ink-border p-3 mt-2" style="background: var(--color-surface-bright); border-left: 3px solid var(--color-primary);">
											<div class="flex gap-4 items-center justify-center" style="font-size: 12px;">
												<div class="text-center">
													<div style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Min</div>
													<div style="font-weight: 900;">{Number(salarySuggestion.min || 0).toLocaleString()}</div>
												</div>
												<div class="text-center">
													<div style="font-size: 9px; text-transform: uppercase; color: var(--color-primary); font-weight: 700;">Median</div>
													<div style="font-weight: 900; font-size: 16px; color: var(--color-primary);">{Number(salarySuggestion.median || 0).toLocaleString()}</div>
												</div>
												<div class="text-center">
													<div style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Max</div>
													<div style="font-weight: 900;">{Number(salarySuggestion.max || 0).toLocaleString()}</div>
												</div>
											</div>
											{#if salarySuggestion.rationale}
												<p style="font-size: 10px; color: var(--color-on-surface-dim); margin-top: 6px; text-align: center; line-height: 1.4;">{salarySuggestion.rationale}</p>
											{/if}
											<button class="send-btn" style="font-size: 9px; padding: 4px 12px; width: 100%; margin-top: 6px;" onclick={applySuggestedSalary}>
												Apply Median ({Number(salarySuggestion.median || 0).toLocaleString()})
											</button>
										</div>
									{/if}
								</div>

								<!-- Equity + Bonus -->
								<div class="flex gap-3">
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Equity</label>
										<input type="text" bind:value={newOffer.equity} placeholder="0.5% over 4 years" style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);" />
									</div>
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Bonus</label>
										<input type="text" bind:value={newOffer.bonus} placeholder="15% annual target" style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);" />
									</div>
								</div>

								<!-- Dates -->
								<div class="flex gap-3">
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Start Date</label>
										<input type="date" bind:value={newOffer.start_date} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);" />
									</div>
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Expiry Date</label>
										<input type="date" bind:value={newOffer.expiry_date} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface);" />
									</div>
								</div>

								<!-- Benefits -->
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Benefits</label>
									<textarea bind:value={newOffer.benefits} rows="3" placeholder="Health insurance, 401k match, PTO..." style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface); resize: vertical;"></textarea>
								</div>

								<button class="send-btn" style="width: 100%; padding: 10px; font-size: 12px;" onclick={createOffer} disabled={savingOffer}>
									{savingOffer ? 'Creating...' : 'CREATE OFFER'}
								</button>
							</div>
						</div>
					</div>
				{/if}

				<!-- Offer Detail Modal -->
				{#if selectedOffer}
					<div style="position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1000; display: flex; align-items: center; justify-content: center;"
						onclick={(e) => { if (e.target === e.currentTarget) selectedOffer = null; }}>
						<div class="ink-border p-6" style="background: var(--color-surface); width: 90%; max-width: 560px; max-height: 85vh; overflow-y: auto;">
							<div class="flex items-center justify-between mb-4">
								<h3 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Offer Detail</h3>
								<button onclick={() => selectedOffer = null} style="background: none; border: none; cursor: pointer; font-size: 18px; font-weight: 900;">X</button>
							</div>

							<div style="display: flex; flex-direction: column; gap: 10px; font-size: 13px;">
								<div class="flex items-center gap-2">
									<span style="font-size: 18px; font-weight: 900;">{selectedOffer.candidate_name || 'Unknown'}</span>
									<span style="font-size: 10px; padding: 2px 8px; background: {offerStatusColor(selectedOffer.status)}; color: {offerStatusTextColor(selectedOffer.status)}; font-weight: 700; text-transform: uppercase;">
										{selectedOffer.status}
									</span>
								</div>

								<div class="ink-border p-4" style="background: var(--color-surface-bright);">
									<div class="flex gap-4 flex-wrap">
										<div><span style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Salary</span><br/><strong style="font-size: 20px;">{selectedOffer.salary_currency} {Number(selectedOffer.salary_amount).toLocaleString()}</strong><span style="font-size: 10px; color: var(--color-on-surface-dim);">/{selectedOffer.salary_period || 'annual'}</span></div>
										{#if selectedOffer.equity}<div><span style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Equity</span><br/><strong>{selectedOffer.equity}</strong></div>{/if}
										{#if selectedOffer.bonus}<div><span style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Bonus</span><br/><strong>{selectedOffer.bonus}</strong></div>{/if}
									</div>
								</div>

								<div class="flex gap-4">
									{#if selectedOffer.start_date}<div><span style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Start Date</span><br/>{new Date(selectedOffer.start_date).toLocaleDateString()}</div>{/if}
									{#if selectedOffer.expiry_date}<div><span style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Expires</span><br/>{new Date(selectedOffer.expiry_date).toLocaleDateString()}</div>{/if}
								</div>

								{#if selectedOffer.benefits}
									<div><span style="font-size: 9px; text-transform: uppercase; color: var(--color-on-surface-dim); font-weight: 700;">Benefits</span><br/><span style="white-space: pre-wrap;">{selectedOffer.benefits}</span></div>
								{/if}

								{#if selectedOffer.approved_by_name}
									<div style="font-size: 11px; color: var(--color-on-surface-dim);">Approved by: <strong>{selectedOffer.approved_by_name}</strong> {selectedOffer.approved_at ? 'on ' + new Date(selectedOffer.approved_at).toLocaleDateString() : ''}</div>
								{/if}

								{#if selectedOffer.decline_reason}
									<div class="ink-border p-3" style="border-color: var(--color-error); background: rgba(255,59,48,0.05);">
										<span style="font-size: 9px; text-transform: uppercase; color: var(--color-error); font-weight: 700;">Decline Reason</span><br/>
										{selectedOffer.decline_reason}
									</div>
								{/if}

								<!-- Approval Chain -->
								{#if approvalChain.length > 0}
									<div class="mb-3">
										<span style="font-size: 9px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim); letter-spacing: 0.08em;">Approval Chain</span>
										<div class="flex items-center gap-1 mt-2 flex-wrap">
											{#each approvalChain as step, i}
												<div class="ink-border p-2 text-center" style="min-width: 80px;
													background: {step.status === 'approved' ? '#e8f5e9' : step.status === 'rejected' ? '#ffebee' : 'var(--color-surface-bright)'};">
													<div style="font-size: 10px; font-weight: 900;">{step.approver_name || `Step ${step.step_order}`}</div>
													<div style="font-size: 9px; font-weight: 700; text-transform: uppercase; margin-top: 2px;
														color: {step.status === 'approved' ? 'var(--color-primary)' : step.status === 'rejected' ? 'var(--color-error)' : 'var(--color-on-surface-dim)'};">
														{step.status}
													</div>
													{#if step.status === 'pending'}
														<button class="send-btn mt-1" style="font-size: 8px; padding: 2px 8px;" onclick={() => approveStep(selectedOffer.id)}>Approve</button>
													{/if}
												</div>
												{#if i < approvalChain.length - 1}
													<span style="font-size: 14px; color: var(--color-on-surface-dim);">→</span>
												{/if}
											{/each}
										</div>
									</div>
								{:else if selectedOffer.status === 'draft'}
									<button class="btn-secondary mb-3" style="font-size: 10px; width: 100%;" onclick={() => showApprovalModal = true}>
										<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">approval</span> Request Approval Chain
									</button>
									{#if showApprovalModal}
										<div class="ink-border p-3 mb-3" style="background: var(--color-surface);">
											<span class="tag-label mb-2" style="display: block; font-size: 8px;">Add Approvers (in order)</span>
											<div class="flex gap-2 mb-2">
												<input bind:value={newApproverInput} placeholder="User ID" style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright);" />
												<button class="btn-secondary" style="font-size: 10px; padding: 4px 10px;" onclick={() => {
													if (newApproverInput.trim()) {
														approverIds = [...approverIds, parseInt(newApproverInput)];
														newApproverInput = '';
													}
												}}>Add</button>
											</div>
											{#each approverIds as aid, i}
												<div class="flex items-center gap-2 mb-1" style="font-size: 11px;">
													<span style="font-weight: 900;">Step {i+1}:</span> User #{aid}
													<button onclick={() => approverIds = approverIds.filter((_, j) => j !== i)} style="background: none; border: none; color: var(--color-error); cursor: pointer; font-size: 12px;">✕</button>
												</div>
											{/each}
											<div class="flex gap-2 mt-2">
												<button class="send-btn" style="font-size: 10px; padding: 4px 12px;" onclick={requestApproval} disabled={approverIds.length === 0}>Submit</button>
												<button class="btn-secondary" style="font-size: 10px; padding: 4px 12px;" onclick={() => { showApprovalModal = false; approverIds = []; }}>Cancel</button>
											</div>
										</div>
									{/if}
								{/if}

								<!-- Actions -->
								<div class="flex gap-2 mt-2 flex-wrap">
									{#if selectedOffer.status === 'draft'}
										<button class="send-btn" style="font-size: 10px; padding: 6px 14px;" onclick={() => offerAction(selectedOffer.id, 'approve')}>Approve</button>
										<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px; color: var(--color-error); border-color: var(--color-error);" onclick={() => offerAction(selectedOffer.id, 'withdraw')}>Withdraw</button>
									{:else if selectedOffer.status === 'approved'}
										<button class="send-btn" style="font-size: 10px; padding: 6px 14px;" onclick={() => offerAction(selectedOffer.id, 'send')}>Send to Candidate</button>
										<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px; color: var(--color-error); border-color: var(--color-error);" onclick={() => offerAction(selectedOffer.id, 'withdraw')}>Withdraw</button>
									{:else if selectedOffer.status === 'sent'}
										<button class="send-btn" style="font-size: 10px; padding: 6px 14px;" onclick={() => offerAction(selectedOffer.id, 'accept')}>Mark Accepted</button>
										<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px; color: var(--color-error); border-color: var(--color-error);" onclick={() => {
											const reason = prompt('Decline reason:');
											if (reason !== null) offerAction(selectedOffer.id, 'decline', { decline_reason: reason });
										}}>Mark Declined</button>
										<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px;" onclick={() => offerAction(selectedOffer.id, 'withdraw')}>Withdraw</button>
									{/if}
								</div>
								<!-- AI Compose Offer Email -->
								<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px; width: 100%; margin-top: 4px;" onclick={() => composeOfferEmail(selectedOffer.id)} disabled={composingEmail}>
									<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">auto_awesome</span>
									{composingEmail ? 'Composing...' : 'AI Compose Offer Email'}
								</button>
							</div>
						</div>
					</div>
				{/if}

				<!-- Offers List -->
				{#if loadingOffers}
					<div class="flex items-center justify-center py-12">
						<div class="typing-indicator"><span></span><span></span><span></span></div>
					</div>
				{:else if offers.length === 0}
					<div class="flex flex-col items-center py-12" style="border: 3px dashed var(--color-outline-variant);">
						<span class="material-symbols-outlined" style="font-size: 36px; color: var(--color-on-surface-dim);">local_offer</span>
						<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">No offers yet</p>
						<p style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 4px;">Create an offer for a candidate in this position</p>
					</div>
				{:else}
					<div style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase; margin-bottom: 8px;">
						{offers.length} offer{offers.length !== 1 ? 's' : ''}
					</div>
					{#each offers as o, i}
						<div class="ink-border p-4 mb-3" style="background: var(--color-surface); cursor: pointer; animation: fadeUp 0.3s ease-out; animation-delay: {i * 0.04}s; animation-fill-mode: both; opacity: 0;"
							onclick={() => viewOfferDetail(o.id)}>
							<div class="flex items-center gap-3">
								<!-- Candidate name + status -->
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span style="font-size: 14px; font-weight: 900;">{o.candidate_name || 'Unknown'}</span>
										<span style="font-size: 9px; padding: 2px 8px; background: {offerStatusColor(o.status)}; color: {offerStatusTextColor(o.status)}; font-weight: 700; text-transform: uppercase;">
											{o.status}
										</span>
									</div>
									<div style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 2px;">
										{o.salary_currency} {Number(o.salary_amount).toLocaleString()}/{o.salary_period || 'annual'}
										{#if o.equity} · Equity: {o.equity}{/if}
									</div>
								</div>

								<!-- Dates -->
								<div style="text-align: right; flex-shrink: 0;">
									{#if o.start_date}
										<div style="font-size: 10px; color: var(--color-on-surface-dim);">Start: {new Date(o.start_date).toLocaleDateString()}</div>
									{/if}
									<div style="font-size: 9px; color: var(--color-on-surface-dim);">Created: {new Date(o.created_at).toLocaleDateString()}</div>
								</div>

								<!-- Quick Actions -->
								<div class="flex gap-1" style="flex-shrink: 0;" onclick={(e) => e.stopPropagation()}>
									{#if o.status === 'draft'}
										<button class="send-btn" style="font-size: 9px; padding: 4px 10px;" onclick={() => offerAction(o.id, 'approve')}>Approve</button>
									{:else if o.status === 'approved'}
										<button class="send-btn" style="font-size: 9px; padding: 4px 10px;" onclick={() => offerAction(o.id, 'send')}>Send</button>
									{:else if o.status === 'sent'}
										<button class="send-btn" style="font-size: 9px; padding: 4px 10px;" onclick={() => offerAction(o.id, 'accept')}>Accept</button>
										<button class="btn-secondary" style="font-size: 9px; padding: 4px 10px; color: var(--color-error); border-color: var(--color-error);" onclick={() => {
											const reason = prompt('Decline reason:');
											if (reason !== null) offerAction(o.id, 'decline', { decline_reason: reason });
										}}>Decline</button>
									{/if}
								</div>
							</div>
						</div>
					{/each}
				{/if}
			</div>

		<!-- ═══ DASHBOARD TAB — HIRING MANAGER VIEW ═══ -->
		{:else if activeTab === 'dashboard'}
			<div class="animate-fade-up">
				<!-- Header + Export -->
				<div class="flex items-center justify-between mb-4">
					<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase;">Hiring Manager Dashboard</h2>
					<div class="flex gap-2">
						<button class="send-btn" style="font-size: 10px; padding: 5px 14px;" onclick={generateAiInsights} disabled={loadingInsights}>
							<span class="material-symbols-outlined" style="font-size: 12px; vertical-align: middle;">auto_awesome</span>
							{loadingInsights ? '...' : 'AI Insights'}
						</button>
						<button class="btn-secondary" style="font-size: 10px; padding: 6px 12px;" onclick={() => window.open(`/api/export/positions/${slug}/csv`)}>Export CSV</button>
						<button class="btn-secondary" style="font-size: 10px; padding: 6px 12px;" onclick={() => window.open(`/api/export/positions/${slug}/report`)}>Report</button>
						<a href="/positions/{slug}/report" class="send-btn" style="font-size: 10px; padding: 5px 14px; text-decoration: none;" target="_blank">Full Report →</a>
					</div>
				</div>

				<!-- KPI Cards (4) -->
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
					{#each [
						{ label: 'Total', value: candidates.length, icon: 'people' },
						{ label: 'Shortlisted', value: pipeline.shortlisted || 0, icon: 'thumb_up' },
						{ label: 'Offers', value: offers.length, icon: 'mail' },
						{ label: 'Avg Match', value: candidates.length ? Math.round(candidates.reduce((s, c) => s + (c.match_score_composite || 0), 0) / candidates.length) + '%' : '—', icon: 'percent' },
					] as kpi}
						<div class="ink-border p-3 text-center" style="background: var(--color-surface);">
							<span class="material-symbols-outlined" style="font-size: 16px; color: var(--color-on-surface-dim);">{kpi.icon}</span>
							<div style="font-size: 24px; font-weight: 900;">{kpi.value}</div>
							<div style="font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">{kpi.label}</div>
						</div>
					{/each}
				</div>

				<!-- AI Insights -->
				{#if aiInsights && Array.isArray(aiInsights) && aiInsights.length > 0}
					<div class="mb-5">
						{#each aiInsights as insight, i}
							<div class="ink-border p-3 mb-2" style="background: var(--color-surface-bright); border-left: 4px solid {insightBorderColor(insight.severity)};">
								<div class="flex items-center gap-2">
									<span class="material-symbols-outlined" style="font-size: 16px; color: {insightBorderColor(insight.severity)};">{insightIcon(insight.severity)}</span>
									<span style="font-size: 12px; font-weight: 900;">{insight.title || ''}</span>
									<span style="font-size: 11px; color: var(--color-on-surface-dim); flex: 1;">{insight.description || ''}</span>
								</div>
							</div>
						{/each}
					</div>
				{/if}

				<!-- ── CANDIDATE COMPARISON TABLE ── -->
				<div class="ink-border mb-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Candidate Comparison</div>
					<div style="overflow-x: auto;">
						<table class="data-table" style="min-width: 700px;">
							<thead>
								<tr>
									<th style="width: 20px;">#</th>
									<th>Candidate</th>
									<th style="width: 70px;">Match</th>
									<th style="width: 60px;">Skills</th>
									<th style="width: 60px;">Exp</th>
									<th style="width: 60px;">Edu</th>
									<th style="width: 60px;">Ind</th>
									<th style="width: 100px;">Stage</th>
									<th style="width: 60px;">Exp Yrs</th>
								</tr>
							</thead>
							<tbody>
								{#each candidates as c, i}
									<tr onclick={() => toggleDashExpand(c.candidate_id || c.id)} style="cursor: pointer; {expandedDashCandidate === (c.candidate_id || c.id) ? 'background: var(--color-surface-container);' : ''}">
										<td style="font-weight: 900; color: var(--color-on-surface-dim);">{i + 1}</td>
										<td>
											<div style="font-weight: 900; font-size: 12px;">{c.name || 'Unknown'}</div>
											<div style="font-size: 10px; color: var(--color-on-surface-dim);">{c.current_role || ''}</div>
										</td>
										<td>
											<span style="font-weight: 900; font-size: 14px; color: {(c.match_score_composite || 0) >= 70 ? 'var(--color-primary)' : (c.match_score_composite || 0) >= 50 ? 'var(--color-warning)' : 'var(--color-error)'};">
												{Math.round(c.match_score_composite || 0)}%
											</span>
										</td>
										<td style="font-size: 11px; font-weight: 700;">{Math.round(c.match_score_skills || 0)}%</td>
										<td style="font-size: 11px; font-weight: 700;">{Math.round(c.match_score_experience || 0)}%</td>
										<td style="font-size: 11px; font-weight: 700;">{Math.round(c.match_score_education || 0)}%</td>
										<td style="font-size: 11px; font-weight: 700;">{Math.round(c.match_score_industry || 0)}%</td>
										<td>
											<span style="font-size: 9px; padding: 2px 6px; background: {stageColors[c.stage] || 'var(--color-on-surface-dim, #6f6e69)'}; color: white; font-weight: 700; text-transform: uppercase;">
												{c.stage || '?'}
											</span>
										</td>
										<td style="font-size: 11px;">{c.total_experience_years || 0}yr</td>
								</tr>
								{#if expandedDashCandidate === (c.candidate_id || c.id)}
								<tr>
									<td colspan="9" style="padding: 0; background: var(--color-surface-container);">
										<div class="p-4 animate-fade-up" style="border-top: 2px solid var(--color-primary);">
											<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
												<div class="ink-border p-3" style="background: var(--color-surface);">
													<span class="tag-label mb-2" style="display: block; font-size: 8px; background: var(--color-primary);">Strengths</span>
													<ul style="font-size: 11px; padding-left: 16px; margin: 0; line-height: 1.6;">
														{#if (c.skills_matched || []).length}<li>All {(c.skills_matched || []).length} required skills matched</li>{/if}
														{#if (c.total_experience_years || 0) >= (position?.min_experience || 0)}<li>{c.total_experience_years || 0} years experience{position?.min_experience ? ` (exceeds ${position.min_experience} min)` : ''}</li>{/if}
														{#if c.current_role}<li>{c.current_role}{c.current_company ? ` at ${c.current_company}` : ''}</li>{/if}
														{#if (c.match_score_composite || 0) >= 70}<li>Strong overall match ({Math.round(c.match_score_composite)}%)</li>{/if}
														{#if (c.match_score_education || 0) >= 80}<li>Education score {Math.round(c.match_score_education)}%</li>{/if}
													</ul>
												</div>
												<div class="ink-border p-3" style="background: var(--color-surface);">
													<span class="tag-label mb-2" style="display: block; font-size: 8px; background: var(--color-warning);">Concerns</span>
													<ul style="font-size: 11px; padding-left: 16px; margin: 0; line-height: 1.6;">
														{#if (c.skills_missing || []).length}<li>Missing: {(c.skills_missing || []).join(', ')}</li>{/if}
														{#if (c.match_score_composite || 0) < 70}<li>Below 70% threshold ({Math.round(c.match_score_composite || 0)}%)</li>{/if}
														{#if (c.total_experience_years || 0) < (position?.min_experience || 0)}<li>Only {c.total_experience_years || 0}yr experience (min {position?.min_experience})</li>{/if}
														{#if (c.match_score_skills || 0) < 50}<li>Low skills match ({Math.round(c.match_score_skills || 0)}%)</li>{/if}
														{#if !(c.skills_missing || []).length && (c.match_score_composite || 0) >= 70 && (c.total_experience_years || 0) >= (position?.min_experience || 0) && (c.match_score_skills || 0) >= 50}<li style="color: var(--color-on-surface-dim);">No major concerns</li>{/if}
													</ul>
												</div>
												<div class="ink-border p-3" style="background: var(--color-surface);">
													<span class="tag-label mb-2" style="display: block; font-size: 8px;">Activity</span>
													<div style="font-size: 11px;">
														{#if dashNotes.length}
														<div><strong style="font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em;">Notes ({dashNotes.length})</strong>
															{#each dashNotes.slice(0, 3) as note}<div style="padding: 2px 0; color: var(--color-on-surface-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px;">{note.text || note.content || note.note || ''}</div>{/each}
														</div>
														{:else}<div style="color: var(--color-on-surface-dim);">No notes yet</div>{/if}
													</div>
												</div>
											</div>
											<div class="flex gap-2 mt-3">
												<a href="/candidates/{c.candidate_id || c.id}" class="send-btn" style="font-size: 9px; padding: 4px 12px; text-decoration: none;">Full Profile →</a>
												<button class="btn-secondary" style="font-size: 9px; padding: 4px 12px;" onclick={() => expandedDashCandidate = null}>Close</button>
											</div>
										</div>
									</td>
								</tr>
								{/if}
								{/each}
							</tbody>
						</table>
					</div>
				</div>

				<!-- ── SKILLS COVERAGE MATRIX ── -->
				{#if position?.required_skills?.length && candidates.length}
					<div class="ink-border mb-5" style="background: var(--color-surface);">
						<div class="dark-title-bar" style="font-size: 11px;">Skills Coverage Matrix</div>
						<div style="overflow-x: auto;">
							<table class="data-table" style="min-width: 600px;">
								<thead>
									<tr>
										<th>Required Skill</th>
										{#each candidates.filter(c => c.stage !== 'rejected').slice(0, 5) as c}
											<th style="font-size: 9px; max-width: 80px; overflow: hidden; text-overflow: ellipsis;">{(c.name || '').split(' ')[0]}</th>
										{/each}
										<th>Coverage</th>
									</tr>
								</thead>
								<tbody>
									{#each position.required_skills as skill}
										{@const activeCandidates = candidates.filter(c => c.stage !== 'rejected').slice(0, 5)}
										{@const hasSkill = activeCandidates.map(c => (c.skills_matched || []).map(s => s.toLowerCase()).includes(skill.toLowerCase()))}
										{@const coverage = hasSkill.filter(Boolean).length}
										<tr>
											<td style="font-weight: 700; font-size: 11px; text-transform: uppercase;">{skill}</td>
											{#each hasSkill as has}
												<td style="text-align: center;">
													{#if has}
														<span style="color: var(--color-primary); font-weight: 900;">✓</span>
													{:else}
														<span style="color: var(--color-error); opacity: 0.5;">✗</span>
													{/if}
												</td>
											{/each}
											<td>
												<div class="flex items-center gap-2">
													<div style="flex: 1; height: 8px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);">
														<div style="height: 100%; width: {activeCandidates.length > 0 ? (coverage / activeCandidates.length * 100) : 0}%; background: {coverage > 0 ? 'var(--color-primary)' : 'var(--color-error)'};"></div>
													</div>
													<span style="font-size: 10px; font-weight: 900; min-width: 30px;">{coverage}/{activeCandidates.length}</span>
												</div>
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}

				<div class="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
					<!-- ── PIPELINE FUNNEL ── -->
					<div class="ink-border" style="background: var(--color-surface);">
						<div class="dark-title-bar" style="font-size: 11px;">Pipeline Funnel</div>
						<div class="p-4">
							{#each stages as stage}
								{@const count = pipeline[stage] || 0}
								{@const total = candidates.length || 1}
								<div class="flex items-center gap-2 mb-2">
									<span style="font-size: 9px; font-weight: 700; text-transform: uppercase; min-width: 70px; text-align: right;">{stageLabels[stage]}</span>
									<div style="flex: 1; height: 16px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);">
										<div style="height: 100%; width: {(count / total * 100)}%; background: {stageColors[stage]}; transition: width 0.5s;"></div>
									</div>
									<span style="font-size: 11px; font-weight: 900; min-width: 40px;">{count} <span style="font-size: 9px; color: var(--color-on-surface-dim);">{total > 0 ? Math.round(count/total*100) : 0}%</span></span>
								</div>
							{/each}
						</div>
					</div>

					<!-- ── SCORING WEIGHTS ── -->
					<div class="ink-border" style="background: var(--color-surface);">
						<div class="dark-title-bar" style="font-size: 11px;">Scoring Weights</div>
						<div class="p-4">
							{#each [
								['Skills', position?.weight_skills || 40],
								['Experience', position?.weight_experience || 25],
								['Education', position?.weight_education || 10],
								['Certifications', position?.weight_certifications || 10],
								['Industry', position?.weight_industry || 15],
							] as [label, weight]}
								<div class="flex items-center gap-2 mb-2">
									<span style="font-size: 10px; font-weight: 700; text-transform: uppercase; min-width: 90px;">{label}</span>
									<div style="flex: 1; height: 10px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);">
										<div style="height: 100%; width: {weight}%; background: var(--color-primary);"></div>
									</div>
									<span style="font-size: 11px; font-weight: 900; min-width: 30px;">{weight}%</span>
								</div>
							{/each}
						</div>
					</div>
				</div>

				<div class="grid grid-cols-1 gap-5 mb-5">
					<!-- ── OFFERS ── -->
					<div class="ink-border" style="background: var(--color-surface);">
						<div class="dark-title-bar" style="font-size: 11px;">Offers & Decisions</div>
						<div class="p-4">
							{#each offers as o}
								<div class="flex items-center gap-3 py-2" style="border-bottom: 1px solid var(--color-surface-highest);">
									<span class="material-symbols-outlined" style="font-size: 16px; color: {offerStatusColor(o.status)};">
										{o.status === 'accepted' ? 'celebration' : o.status === 'declined' ? 'close' : 'mail'}
									</span>
									<div class="flex-1">
										<span style="font-size: 12px; font-weight: 900;">{o.candidate_name || 'Unknown'}</span>
										<div style="font-size: 10px; color: var(--color-on-surface-dim);">
											{o.salary_currency} {Number(o.salary_amount || 0).toLocaleString()}
										</div>
									</div>
									<span style="font-size: 9px; padding: 2px 6px; background: {offerStatusColor(o.status)}; color: {offerStatusTextColor(o.status)}; font-weight: 700; text-transform: uppercase;">{o.status}</span>
								</div>
							{:else}
								<p style="font-size: 11px; color: var(--color-on-surface-dim); text-align: center; padding: 12px 0;">No offers yet</p>
							{/each}
						</div>
					</div>
				</div>

				<!-- ── NOTES FEED ── -->
				<div class="ink-border mb-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Recent Notes & Feedback</div>
					<div class="p-4">
						{#each candidates.slice(0, 3) as c}
							{#if c.match_explanation}
								<div class="flex items-start gap-3 py-2" style="border-bottom: 1px solid var(--color-surface-highest);">
									<div class="avatar-user" style="width: 24px; height: 24px; font-size: 9px; flex-shrink: 0;">{(c.name || '?')[0]}</div>
									<div class="flex-1">
										<span style="font-size: 11px; font-weight: 700;">{c.name}</span>
										<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 2px; line-height: 1.4;">{c.match_explanation}</p>
									</div>
								</div>
							{/if}
						{/each}
						{#if candidates.every(c => !c.match_explanation)}
							<p style="font-size: 11px; color: var(--color-on-surface-dim); text-align: center; padding: 12px 0;">No notes yet. Add notes from the Candidates tab.</p>
						{/if}
					</div>
				</div>

				<!-- ── AI RECOMMENDATION ── -->
				<div class="ink-border" style="background: #f0fff0; border-left: 4px solid var(--color-primary);">
					<div class="dark-title-bar flex items-center gap-2" style="font-size: 11px; background: var(--color-primary); color: #fff;">
						<span class="material-symbols-outlined" style="font-size: 14px;">auto_awesome</span>
						AI Hiring Recommendation
					</div>
					<div class="p-4">
						{#if candidates.length > 0}
							{@const top = candidates[0]}
							{@const backup = candidates.length > 1 ? candidates[1] : null}
							{@const allSkills = position?.required_skills || []}
							{@const coveredSkills = new Set(candidates.filter(c => c.stage !== 'rejected').flatMap(c => c.skills_matched || []).map(s => s.toLowerCase()))}
							{@const gaps = allSkills.filter(s => !coveredSkills.has(s.toLowerCase()))}
							<div style="font-size: 13px; line-height: 1.6;">
								<p><strong>{top.name}</strong> is the strongest candidate with a <strong>{Math.round(top.match_score_composite || 0)}% match</strong>.
								{#if top.stage === 'offered'}
									Offer has been sent — awaiting response.
								{:else}
									Consider advancing to the next stage.
								{/if}
								</p>
								{#if backup}
									<p style="margin-top: 8px;">Backup: <strong>{backup.name}</strong> ({Math.round(backup.match_score_composite || 0)}%)
									{#if backup.skills_missing?.length}
										— gap in {backup.skills_missing.slice(0, 2).join(', ')} (training recommended).
									{/if}
									</p>
								{/if}
								{#if gaps.length > 0}
									<p style="margin-top: 8px; color: var(--color-warning);">
										<strong>Skill gap alert:</strong> No active candidate has: {gaps.join(', ')}.
									</p>
								{/if}
							</div>
						{:else}
							<p style="font-size: 12px; color: var(--color-on-surface-dim);">Add candidates to get AI recommendations.</p>
						{/if}
					</div>
				</div>

				<!-- VISUAL SCORE CARDS -->
				<div class="mt-5">
					<div class="dark-title-bar" style="font-size: 11px;">Candidate Scorecards</div>
					{#each candidates.filter(c => c.stage !== 'rejected').slice(0, 3) as c, i}
						<div class="ink-border mb-3 animate-fade-up" style="background: var(--color-surface); animation-delay: {i*0.05}s;">
							<div class="flex items-center gap-3 p-4" style="border-bottom: 2px solid var(--color-surface-highest);">
								<div style="width: 48px; height: 48px; border: 3px solid {scoreBarColor(c.match_score_composite || 0)}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
									<span style="font-size: 16px; font-weight: 900; color: {scoreBarColor(c.match_score_composite || 0)};">{Math.round(c.match_score_composite || 0)}%</span>
								</div>
								<div class="flex-1">
									<div class="flex items-center gap-2">
										<span style="font-size: 15px; font-weight: 900;">#{i+1} {c.name}</span>
										<span style="font-size: 9px; padding: 2px 8px; background: {stageColors[c.stage]}; color: white; font-weight: 700; text-transform: uppercase;">{c.stage}</span>
										{#if i === 0}<span style="font-size: 9px; padding: 2px 8px; background: var(--color-primary); color: white; font-weight: 900;">TOP PICK</span>{/if}
										{#if i === 1}<span style="font-size: 9px; padding: 2px 8px; border: 1px solid var(--color-secondary); color: var(--color-secondary); font-weight: 700;">BACKUP</span>{/if}
									</div>
									<div style="font-size: 11px; color: var(--color-on-surface-dim);">{c.current_role || 'N/A'} · {c.total_experience_years || 0}yr</div>
								</div>
							</div>
							<div class="p-4">
								<!-- Score bars with colors -->
								<div class="grid grid-cols-5 gap-3 mb-3">
									{#each [
										{label: 'Skills', score: c.match_score_skills, color: '#3a8a4f'},
										{label: 'Exp', score: c.match_score_experience, color: '#006f7c'},
										{label: 'Edu', score: c.match_score_education, color: '#9d4867'},
										{label: 'Industry', score: c.match_score_industry, color: 'var(--color-warning, #c98c2a)'},
										{label: 'Certs', score: c.match_score_certifications, color: 'var(--color-on-surface, #2c2c2c)'},
									] as dim}
										<div>
											<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">{dim.label}</div>
											<div style="height: 8px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant); margin: 3px 0;">
												<div style="height: 100%; width: {dim.score || 0}%; background: {dim.color};"></div>
											</div>
											<span style="font-size: 11px; font-weight: 900;">{Math.round(dim.score || 0)}%</span>
										</div>
									{/each}
								</div>
								<!-- Strengths / Concerns -->
								<div class="grid grid-cols-2 gap-3">
									<div>
										<span style="font-size: 9px; font-weight: 900; color: var(--color-primary); text-transform: uppercase;">✓ Strengths</span>
										<ul style="font-size: 11px; padding-left: 14px; margin: 4px 0; line-height: 1.5;">
											{#if (c.skills_matched || []).length >= 3}<li>All {c.skills_matched.length} key skills matched</li>{/if}
											{#if (c.total_experience_years || 0) >= (position?.min_experience_years || 0)}<li>{c.total_experience_years}yr exp (exceeds {position?.min_experience_years || 0}yr min)</li>{/if}
											{#if c.current_company}<li>{c.current_role} at {c.current_company}</li>{/if}
											{#if (c.match_score_composite || 0) >= 90}<li>Top-tier match (90%+)</li>{/if}
										</ul>
									</div>
									<div>
										<span style="font-size: 9px; font-weight: 900; color: var(--color-warning); text-transform: uppercase;">⚠ Concerns</span>
										<ul style="font-size: 11px; padding-left: 14px; margin: 4px 0; line-height: 1.5; color: var(--color-on-surface-dim);">
											{#if (c.skills_missing || []).length > 0}<li>Missing: {c.skills_missing.join(', ')}</li>{/if}
											{#if (c.match_score_composite || 0) < 70}<li>Below 70% threshold</li>{/if}
											{#if (c.total_experience_years || 0) < (position?.min_experience_years || 0)}<li>Below min experience</li>{/if}
											{#if !(c.skills_missing || []).length && (c.match_score_composite || 0) >= 70}<li style="color: var(--color-primary);">No major concerns</li>{/if}
										</ul>
									</div>
								</div>
							</div>
						</div>
					{/each}
				</div>

				<!-- PIPELINE VELOCITY -->
				<div class="ink-border mt-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Pipeline Velocity</div>
					<div class="p-4">
						{#each [
							{from: 'Uploaded', to: 'Screened', days: 2.1, speed: 'FAST', color: 'var(--color-primary)'},
							{from: 'Screened', to: 'Shortlisted', days: 3.5, speed: 'NORMAL', color: 'var(--color-secondary)'},
							{from: 'Shortlisted', to: 'Offered', days: 1.0, speed: 'FAST', color: 'var(--color-primary)'},
						] as step}
							<div class="flex items-center gap-3 mb-2">
								<span style="font-size: 10px; font-weight: 700; min-width: 150px; text-transform: uppercase;">{step.from} → {step.to}</span>
								<div style="flex: 1; height: 10px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);">
									<div style="height: 100%; width: {Math.min(step.days * 10, 100)}%; background: {step.color};"></div>
								</div>
								<span style="font-size: 11px; font-weight: 900; min-width: 50px;">{step.days}d</span>
								<span style="font-size: 9px; padding: 1px 6px; border: 1px solid {step.color}; color: {step.color}; font-weight: 700;">{step.speed}</span>
							</div>
						{/each}
					</div>
				</div>

				<!-- TIME IN CURRENT STAGE -->
				<div class="ink-border mt-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Time in Current Stage</div>
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead><tr><th>Candidate</th><th>Stage</th><th>Days</th><th>SLA</th><th>Status</th></tr></thead>
							<tbody>
								{#each candidates.filter(c => c.stage !== 'rejected') as c}
									{@const days = Math.round((Date.now() - new Date(c.stage_changed_at || c.created_at).getTime()) / 86400000)}
									{@const sla = c.stage === 'uploaded' ? 3 : c.stage === 'screened' ? 5 : c.stage === 'shortlisted' ? 5 : 7}
									<tr>
										<td style="font-weight: 700; font-size: 12px;">{c.name}</td>
										<td><span style="font-size: 9px; padding: 2px 6px; background: {stageColors[c.stage]}; color: white; font-weight: 700; text-transform: uppercase;">{c.stage}</span></td>
										<td style="font-weight: 900;">{days}d</td>
										<td>{sla}d</td>
										<td>
											{#if days > sla}
												<span style="color: var(--color-error); font-weight: 900; display:inline-flex; align-items:center; gap:4px;"><Circle size={10} fill="currentColor" /> OVERDUE</span>
											{:else if days > sla * 0.7}
												<span style="color: var(--color-warning); font-weight: 900; display:inline-flex; align-items:center; gap:4px;"><Circle size={10} fill="currentColor" /> WATCH</span>
											{:else}
												<span style="color: var(--color-primary); font-weight: 900; display:inline-flex; align-items:center; gap:4px;"><Circle size={10} fill="currentColor" /> OK</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>

				<!-- DECISION MATRIX -->
				<div class="ink-border mt-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Decision Matrix</div>
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead><tr><th>Criteria</th>
								{#each candidates.filter(c => c.stage !== 'rejected').slice(0, 3) as c}<th>{c.name?.split(' ')[0]}</th>{/each}
								<th>Weight</th>
							</tr></thead>
							<tbody>
								{#each [
									{label: 'Skills Fit', key: 'match_score_skills', weight: position?.weight_skills || 40},
									{label: 'Experience', key: 'match_score_experience', weight: position?.weight_experience || 25},
									{label: 'Education', key: 'match_score_education', weight: position?.weight_education || 10},
									{label: 'Industry', key: 'match_score_industry', weight: position?.weight_industry || 15},
									{label: 'Certifications', key: 'match_score_certifications', weight: position?.weight_certifications || 10},
								] as row}
									<tr>
										<td style="font-weight: 700; font-size: 11px; text-transform: uppercase;">{row.label}</td>
										{#each candidates.filter(c => c.stage !== 'rejected').slice(0, 3) as c}
											{@const score = Math.round(c[row.key] || 0)}
											{@const best = Math.max(...candidates.filter(x => x.stage !== 'rejected').slice(0, 3).map(x => x[row.key] || 0))}
											<td style="font-weight: {score >= best ? '900' : '400'}; color: {score >= best ? 'var(--color-primary)' : 'inherit'}; font-size: 13px;">
												{score}%{score >= best ? ' ✓' : ''}
											</td>
										{/each}
										<td style="font-size: 10px; color: var(--color-on-surface-dim);">{row.weight}%</td>
									</tr>
								{/each}
								<tr style="border-top: 3px solid var(--color-on-surface);">
									<td style="font-weight: 900; text-transform: uppercase;">Total</td>
									{#each candidates.filter(c => c.stage !== 'rejected').slice(0, 3) as c, i}
										<td style="font-weight: 900; font-size: 16px; color: {i === 0 ? 'var(--color-primary)' : 'inherit'};">
											{Math.round(c.match_score_composite || 0)}%
											{#if i === 0}<span style="font-size: 10px;"> HIRE</span>{/if}
											{#if i === 1}<span style="font-size: 10px; color: var(--color-on-surface-dim);"> BACKUP</span>{/if}
										</td>
									{/each}
									<td></td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<!-- SOURCE EFFECTIVENESS -->
				<div class="ink-border mt-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Source Effectiveness</div>
					<div class="p-4">
						{#each ['ai_auto_scan', 'manual', 'ai_auto_match', 'position_upload'] as src}
							{@const srcCandidates = candidates.filter(c => c.added_by === src)}
							{@const qualified = srcCandidates.filter(c => (c.match_score_composite || 0) >= 50)}
							{#if srcCandidates.length > 0}
								<div class="flex items-center gap-3 mb-2">
									<span style="font-size: 10px; font-weight: 700; text-transform: uppercase; min-width: 120px;">{src.replace(/_/g, ' ')}</span>
									<div style="flex: 1; height: 12px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);">
										<div style="height: 100%; width: {srcCandidates.length > 0 ? (qualified.length / srcCandidates.length * 100) : 0}%; background: var(--color-primary);"></div>
									</div>
									<span style="font-size: 11px; font-weight: 900;">{qualified.length}/{srcCandidates.length} qualified</span>
								</div>
							{/if}
						{/each}
					</div>
				</div>

				<!-- PIPELINE DIVERSITY -->
				<div class="ink-border mt-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Pipeline Diversity</div>
					<div class="p-4">
						<div class="flex gap-6">
							<div>
								<span style="font-size: 9px; font-weight: 700; text-transform: uppercase; color: var(--color-on-surface-dim);">Seniority Mix</span>
								<div class="flex gap-1 mt-2 flex-wrap">
									{#each [...new Set(candidates.map(c => c.seniority_level).filter(Boolean))] as level}
										<span style="font-size: 10px; padding: 2px 8px; border: 1px solid var(--color-outline); font-weight: 700; text-transform: uppercase;">{level} ({candidates.filter(c => c.seniority_level === level).length})</span>
									{/each}
								</div>
							</div>
							<div>
								<span style="font-size: 9px; font-weight: 700; text-transform: uppercase; color: var(--color-on-surface-dim);">Sources</span>
								<div class="flex gap-1 mt-2 flex-wrap">
									{#each [...new Set(candidates.map(c => c.added_by).filter(Boolean))] as src}
										<span style="font-size: 10px; padding: 2px 8px; border: 1px solid var(--color-outline); font-weight: 700;">{src.replace(/_/g, ' ')} ({candidates.filter(c => c.added_by === src).length})</span>
									{/each}
								</div>
							</div>
						</div>
						<p style="font-size: 10px; color: var(--color-primary); margin-top: 8px; font-weight: 700;">✓ Pipeline represents {candidates.length} candidates from {new Set(candidates.map(c => c.added_by)).size} sources</p>
					</div>
				</div>

				<!-- CANDIDATE JOURNEY -->
				<div class="ink-border mt-5" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">Candidate Journey</div>
					<div class="p-4">
						{#each candidates.filter(c => c.stage !== 'rejected').slice(0, 4) as c}
							<div class="flex items-center gap-2 mb-2">
								<span style="font-size: 11px; font-weight: 900; min-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{c.name}</span>
								<div class="flex items-center gap-0 flex-1">
									{#each stages.filter(s => s !== 'rejected') as stage, si}
										{@const isReached = stages.indexOf(c.stage) >= si}
										<div style="flex: 1; height: 6px; background: {isReached ? stageColors[stage] : 'var(--color-surface-highest)'}; border-right: 2px solid var(--color-surface);"></div>
									{/each}
								</div>
								<span style="font-size: 9px; padding: 1px 6px; background: {stageColors[c.stage]}; color: white; font-weight: 700; text-transform: uppercase; min-width: 60px; text-align: center;">{c.stage?.replace('_', ' ').split(' ')[0]}</span>
							</div>
						{/each}
					</div>
				</div>

				<!-- NEXT STEPS -->
				<div class="ink-border mt-5 mb-5" style="background: var(--color-surface); border-left: 4px solid var(--color-primary);">
					<div class="dark-title-bar" style="font-size: 11px; background: var(--color-primary); color: #fff;">
						<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">checklist</span>
						Next Steps — Action Required
					</div>
					<div class="p-4">
						{#each candidates.filter(c => c.stage === 'offered') as c}
							<div class="flex items-center gap-3 mb-2">
								<Circle size={14} fill="#dc2626" stroke="#dc2626" />
								<span style="font-size: 12px;"><strong>URGENT:</strong> Follow up with {c.name} on offer response</span>
							</div>
						{/each}
						{#each candidates.filter(c => c.stage === 'shortlisted') as c}
							<div class="flex items-center gap-3 mb-2">
								<Circle size={14} fill="#f59e0b" stroke="#f59e0b" />
								<span style="font-size: 12px;"><strong>HIGH:</strong> Advance {c.name} ({Math.round(c.match_score_composite || 0)}% match)</span>
							</div>
						{/each}
						<div class="flex items-center gap-3 mb-2">
							<Circle size={14} fill="#16a34a" stroke="#16a34a" />
							<span style="font-size: 12px;"><strong>MEDIUM:</strong> Review pipeline health and source effectiveness</span>
						</div>
					</div>
				</div>

				<!-- Interviewer Calibration -->
				{#if evalCalibration.length > 0}
					<div class="ink-border mb-5" style="background: var(--color-surface);">
						<div class="dark-title-bar" style="font-size: 11px;">
							<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">balance</span>
							Interviewer Calibration
						</div>
						<div class="p-3" style="overflow-x: auto;">
							<table style="width: 100%; font-size: 11px; border-collapse: collapse;">
								<thead>
									<tr style="border-bottom: 2px solid var(--color-on-surface);">
										<th style="text-align: left; padding: 4px 8px; font-weight: 900; text-transform: uppercase; font-size: 9px;">Interviewer</th>
										<th style="text-align: center; padding: 4px 8px; font-weight: 900; text-transform: uppercase; font-size: 9px;">Avg Score</th>
										<th style="text-align: center; padding: 4px 8px; font-weight: 900; text-transform: uppercase; font-size: 9px;">Std Dev</th>
										<th style="text-align: center; padding: 4px 8px; font-weight: 900; text-transform: uppercase; font-size: 9px;">Reviews</th>
										<th style="text-align: center; padding: 4px 8px; font-weight: 900; text-transform: uppercase; font-size: 9px;">Harshness</th>
									</tr>
								</thead>
								<tbody>
									{#each evalCalibration as cal}
										<tr style="border-bottom: 1px solid var(--color-outline);">
											<td style="padding: 6px 8px; font-weight: 700;">{cal.interviewer_name}</td>
											<td style="padding: 6px 8px; text-align: center;">{cal.avg_score?.toFixed?.(1) || '—'}</td>
											<td style="padding: 6px 8px; text-align: center;">{cal.std_dev?.toFixed?.(2) || '—'}</td>
											<td style="padding: 6px 8px; text-align: center;">{cal.scorecard_count}</td>
											<td style="padding: 6px 8px; text-align: center; font-weight: 700; color: {cal.harshness_index < 0.9 ? 'var(--color-error, #c4571a)' : cal.harshness_index > 1.1 ? '#3a8a4f' : 'inherit'};">
												{cal.harshness_index?.toFixed?.(2) || '—'}x
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}

			</div>

		<!-- ═══ CHAT TAB ═══ -->
		{:else if activeTab === 'chat'}
			<div class="animate-fade-up" style="height: 100%; display: flex; flex-direction: column;">
				<div class="flex items-center justify-center flex-1">
					<div class="text-center">
						<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">smart_toy</span>
						<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">Position Chat</p>
						<p style="font-size: 12px; color: var(--color-on-surface-dim); margin-top: 4px;">
							Open the <a href="/chat" style="color: var(--color-primary); font-weight: 700;">Copilot</a> to chat about this position
						</p>
					</div>
				</div>
			</div>

		<!-- ═══ SETTINGS TAB ═══ -->
		{:else if activeTab === 'interview-kit'}
			<div class="animate-fade-up">
				<InterviewKit {slug} {position} />
			</div>

		{:else if activeTab === 'activity'}
			<div class="animate-fade-up" style="padding: 16px; max-width: 880px;">
				<ActivityFeed targetType="position" targetId={position.slug || position.id} title="Position activity" />
			</div>

		{:else if activeTab === 'settings'}
			<div class="animate-fade-up">
				<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
					<!-- Position Info -->
					<div class="ink-border p-4" style="background: var(--color-surface);">
						<span class="tag-label mb-3" style="display: block;">Position Info</span>
						<div style="font-size: 12px; display: flex; flex-direction: column; gap: 8px;">
							<div><strong>Title:</strong> {position.title}</div>
							<div><strong>Department:</strong> {position.department || '—'}</div>
							<div><strong>Location:</strong> {position.location || '—'}</div>
							<div><strong>Type:</strong> {position.employment_type || 'full-time'}</div>
							<div><strong>Status:</strong> {position.status}</div>
							<div><strong>Min Experience:</strong> {position.min_experience_years || 0} years</div>
							<div><strong>Min Match Score:</strong> {position.min_match_score || 50}%</div>
						</div>
					</div>

					<!-- Scoring Weights — editable -->
					<div class="ink-border stamp-shadow p-4" style="background: var(--color-surface);">
						<div class="flex items-center justify-between mb-3">
							<span class="tag-label" style="display: block;">Scoring Weights</span>
							<div style="font-size: 10px; opacity: 0.7;">
								{position.weights_overridden ? '◉ overridden' : `▮ from JD${position.weights_source_jd_id ? ' #' + position.weights_source_jd_id : ''}`}
							</div>
						</div>
						{#each [
							{key:'weight_skills',label:'Skills'},
							{key:'weight_experience',label:'Experience'},
							{key:'weight_industry',label:'Industry'},
							{key:'weight_education',label:'Education'},
							{key:'weight_certifications',label:'Certifications'},
							{key:'weight_culture',label:'Culture Fit'},
						] as w}
							<div style="display: grid; grid-template-columns: 110px 60px 1fr; gap: 10px; align-items: center; margin-bottom: 6px;">
								<div style="font-size: 11px; font-weight: 700; text-transform: uppercase;">{w.label}</div>
								<input type="number" min="0" max="100" step="1" value={position[w.key] ?? 0}
									oninput={(e) => { position[w.key] = Number(e.target.value); position.weights_overridden = true; }}
									style="border: 2px solid var(--color-on-surface); padding: 3px 6px; font-size: 11px; font-weight: 700; text-align: center; background: white;" />
								<div style="height: 12px; background: var(--color-surface-highest); border: 1px solid var(--color-on-surface);">
									<div style="height: 100%; width: {Math.min(100, position[w.key] || 0)}%; background: var(--color-primary);"></div>
								</div>
							</div>
						{/each}
						<div style="margin-top: 6px; font-size: 11px; opacity: 0.7;">Total: <strong>{Math.round((position.weight_skills||0)+(position.weight_experience||0)+(position.weight_industry||0)+(position.weight_education||0)+(position.weight_certifications||0)+(position.weight_culture||0))}%</strong> · auto-normalized on save</div>
						<div style="display: flex; gap: 8px; margin-top: 12px;">
							<button class="send-btn" style="font-size: 10px; padding: 5px 12px;"
								onclick={async () => {
									await apiJson(`/positions/${position.slug}/weights`, {
										method: 'PATCH',
										body: JSON.stringify({
											weight_skills: position.weight_skills,
											weight_experience: position.weight_experience,
											weight_industry: position.weight_industry,
											weight_education: position.weight_education,
											weight_certifications: position.weight_certifications,
											weight_culture: position.weight_culture,
											normalize: true,
										}),
									});
									cliEvent('success', 'Weights saved');
									await loadPosition();
								}}>SAVE</button>
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;"
								onclick={async () => {
									if (!position.weights_source_jd_id) { cliEvent('error','No source JD'); return; }
									await apiJson(`/positions/${position.slug}/weights`, {
										method: 'PATCH', body: JSON.stringify({ reset_from_jd: true })
									});
									cliEvent('success','Reset from JD');
									await loadPosition();
								}}>RESET FROM JD</button>
						</div>
					</div>

					<!-- Required Skills -->
					<div class="ink-border p-4" style="background: var(--color-surface);">
						<span class="tag-label mb-3" style="display: block;">Required Skills</span>
						<div class="flex gap-1 flex-wrap">
							{#each (position.required_skills || []) as skill}
								<span style="font-size: 10px; padding: 2px 8px; border: 2px solid var(--color-on-surface); font-weight: 700; text-transform: uppercase;">{skill}</span>
							{/each}
							{#if !position.required_skills?.length}
								<span style="font-size: 11px; color: var(--color-on-surface-dim);">None extracted yet — add a JD first</span>
							{/if}
						</div>
					</div>

					<!-- Save as Template -->
					<div class="ink-border p-4" style="background: var(--color-surface);">
						<span class="tag-label mb-3" style="display: block;">Save as Template</span>
						<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-bottom: 8px;">Save this position's settings as a reusable template for future hiring.</p>
						{#if showTemplateSave}
							<div class="flex gap-2">
								<input bind:value={templateName} placeholder="Template name" style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright);" />
								<button class="send-btn" style="font-size: 10px; padding: 6px 12px;" onclick={saveAsTemplate} disabled={!templateName.trim()}>Save</button>
								<button class="btn-secondary" style="font-size: 10px; padding: 6px 12px;" onclick={() => showTemplateSave = false}>Cancel</button>
							</div>
						{:else}
							<button class="send-btn" style="font-size: 10px;" onclick={() => showTemplateSave = true}>Save as Template</button>
						{/if}
					</div>

					<!-- Danger Zone -->
					<div class="ink-border p-4" style="background: var(--color-surface); border-color: var(--color-error);">
						<span class="tag-label mb-3" style="display: block; background: var(--color-error);">Danger Zone</span>
						<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-bottom: 8px;">Close this position or delete it permanently.</p>
						<button class="btn-danger" style="font-size: 10px;">Close Position</button>
					</div>
				</div>

				<!-- ── Screening Questions Section ── -->
				<div class="mt-6">
					<div class="flex items-center justify-between mb-3">
						<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">Screening Questions</h2>
						<div class="flex gap-2">
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;" onclick={loadScreeningQuestions} disabled={loadingQuestions}>
								{loadingQuestions ? 'Loading...' : 'Refresh'}
							</button>
							<button class="send-btn" style="font-size: 10px; padding: 5px 12px;" onclick={() => { showQuestionForm = !showQuestionForm; if (!screeningQuestions.length) loadScreeningQuestions(); }}>
								{showQuestionForm ? 'Cancel' : '+ Add Question'}
							</button>
						</div>
					</div>

					<!-- Add Question Form -->
					{#if showQuestionForm}
						<div class="ink-border p-4 mb-4" style="background: var(--color-surface); border-left: 4px solid var(--color-primary);">
							<span class="tag-label mb-3" style="display: block;">New Question</span>
							<div style="display: flex; flex-direction: column; gap: 10px;">
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 4px;">Question Text</label>
									<textarea bind:value={newQuestion.text} rows="2" placeholder="Enter the screening question..."
										style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); resize: vertical;"></textarea>
								</div>
								<div class="flex gap-3 flex-wrap">
									<div>
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 4px;">Type</label>
										<select bind:value={newQuestion.question_type}
											style="padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; font-weight: 700; background: var(--color-surface); text-transform: uppercase;">
											<option value="text">Text</option>
											<option value="yes_no">Yes / No</option>
											<option value="multiple_choice">Multiple Choice</option>
											<option value="number">Number</option>
										</select>
									</div>
									<div class="flex items-end gap-4">
										<label style="font-size: 11px; font-weight: 700; display: flex; align-items: center; gap: 4px; cursor: pointer;">
											<input type="checkbox" bind:checked={newQuestion.is_required} style="accent-color: var(--color-primary);"> Required
										</label>
										<label style="font-size: 11px; font-weight: 700; display: flex; align-items: center; gap: 4px; cursor: pointer;">
											<input type="checkbox" bind:checked={newQuestion.is_knockout} style="accent-color: var(--color-error);"> Knockout
										</label>
									</div>
								</div>

								<!-- Knockout Answer -->
								{#if newQuestion.is_knockout}
									<div>
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 4px; color: var(--color-error);">Knockout Answer (expected answer to pass)</label>
										<input type="text" bind:value={newQuestion.knockout_answer} placeholder="e.g. Yes, or a minimum value..."
											style="width: 100%; padding: 8px; border: 2px solid var(--color-error); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);">
									</div>
								{/if}

								<!-- Multiple Choice Options -->
								{#if newQuestion.question_type === 'multiple_choice'}
									<div>
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 4px;">Options</label>
										<div class="flex gap-1 flex-wrap mb-2">
											{#each newQuestion.options as opt, idx}
												<span style="font-size: 11px; padding: 3px 8px; border: 2px solid var(--color-on-surface); font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
													{opt}
													<button onclick={() => { newQuestion.options = newQuestion.options.filter((_, i) => i !== idx); }}
														style="background: none; border: none; cursor: pointer; font-size: 12px; color: var(--color-error); font-weight: 900; padding: 0; line-height: 1;">x</button>
												</span>
											{/each}
											{#if newQuestion.options.length === 0}
												<span style="font-size: 11px; color: var(--color-on-surface-dim);">No options added yet</span>
											{/if}
										</div>
										<div class="flex gap-2">
											<input type="text" bind:value={newOptionText} placeholder="Add an option..."
												style="flex: 1; padding: 6px 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);"
												onkeydown={(e) => { if (e.key === 'Enter' && newOptionText.trim()) { newQuestion.options = [...newQuestion.options, newOptionText.trim()]; newOptionText = ''; } }}>
											<button class="btn-secondary" style="font-size: 10px; padding: 5px 10px;"
												onclick={() => { if (newOptionText.trim()) { newQuestion.options = [...newQuestion.options, newOptionText.trim()]; newOptionText = ''; } }}>
												Add
											</button>
										</div>
									</div>
								{/if}

								<div class="flex gap-2 mt-1">
									<button class="send-btn" style="font-size: 11px; padding: 6px 16px;" onclick={addScreeningQuestion}
										disabled={savingQuestion || !newQuestion.text.trim()}>
										{savingQuestion ? 'Saving...' : 'Save Question'}
									</button>
									<button class="btn-secondary" style="font-size: 11px; padding: 6px 16px;" onclick={() => showQuestionForm = false}>Cancel</button>
								</div>
							</div>
						</div>
					{/if}

					<!-- Existing Questions List -->
					{#if loadingQuestions}
						<div class="flex items-center justify-center py-8">
							<div class="typing-indicator"><span></span><span></span><span></span></div>
						</div>
					{:else if screeningQuestions.length === 0}
						<div class="flex flex-col items-center py-8" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 32px; color: var(--color-on-surface-dim);">quiz</span>
							<p style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 10px;">No screening questions</p>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 4px;">Add questions to screen candidates</p>
						</div>
					{:else}
						<div class="flex flex-col gap-3">
							{#each screeningQuestions as q, i}
								<div class="ink-border p-4" style="background: var(--color-surface); animation: fadeUp 0.25s ease-out; animation-delay: {i * 0.04}s; animation-fill-mode: both; opacity: 0;">
									<div class="flex items-start justify-between gap-3">
										<div class="flex-1">
											<div class="flex items-center gap-2 mb-1">
												<span style="font-size: 11px; font-weight: 900; color: var(--color-on-surface-dim);">Q{i + 1}.</span>
												<span style="font-size: 13px; font-weight: 700;">{q.question_text}</span>
											</div>
											<div class="flex gap-2 flex-wrap mt-2">
												<span class="tag-label" style="font-size: 8px;">{q.question_type?.replace('_', ' ') || 'text'}</span>
												{#if q.is_required}
													<span class="tag-label" style="font-size: 8px; background: var(--color-primary);">Required</span>
												{/if}
												{#if q.is_knockout}
													<span class="tag-label" style="font-size: 8px; background: var(--color-error);">Knockout</span>
												{/if}
												{#if q.knockout_answer}
													<span style="font-size: 10px; color: var(--color-on-surface-dim);">Expected: <strong>{q.knockout_answer}</strong></span>
												{/if}
											</div>
											{#if q.options?.length}
												<div class="flex gap-1 flex-wrap mt-2">
													{#each q.options as opt}
														<span style="font-size: 10px; padding: 1px 6px; border: 1px solid var(--color-outline); font-weight: 700;">{opt}</span>
													{/each}
												</div>
											{/if}
										</div>
										<button onclick={() => deleteScreeningQuestion(q.id)}
											style="background: none; border: none; cursor: pointer; padding: 4px; flex-shrink: 0;"
											title="Delete question">
											<span class="material-symbols-outlined" style="font-size: 16px; color: var(--color-error);">delete</span>
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- ── Automation Rules Section ── -->
				<div class="mt-6">
					<div class="flex items-center justify-between mb-3">
						<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">Automation Rules</h2>
						<div class="flex gap-2">
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;" onclick={loadAutomationRules} disabled={loadingAutomations}>
								{loadingAutomations ? 'Loading...' : 'Refresh'}
							</button>
							<button class="send-btn" style="font-size: 10px; padding: 5px 12px;" onclick={() => { showAutomationForm = !showAutomationForm; if (!automationRules.length) loadAutomationRules(); }}>
								{showAutomationForm ? 'Cancel' : '+ Add Rule'}
							</button>
						</div>
					</div>

					{#if showAutomationForm}
						<div class="ink-border p-4 mb-4" style="background: var(--color-surface); border-left: 4px solid var(--color-primary);">
							<span class="tag-label mb-3" style="display: block;">New Automation Rule</span>
							<div style="display: flex; flex-direction: column; gap: 10px;">
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Rule Name</label>
									<input type="text" bind:value={newAutomation.name} placeholder="e.g. Auto-shortlist high scorers"
										style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);" />
								</div>
								<div class="flex gap-3">
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Trigger</label>
										<select bind:value={newAutomation.trigger} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); text-transform: uppercase;">
											<option value="candidate_scored">Candidate Scored</option>
											<option value="stage_changed">Stage Changed</option>
											<option value="cv_uploaded">CV Uploaded</option>
										</select>
									</div>
									<div style="flex: 1;">
										<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Action</label>
										<select bind:value={newAutomation.action} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); text-transform: uppercase;">
											<option value="move_stage">Move Stage</option>
											<option value="send_email">Send Email</option>
											<option value="add_tag">Add Tag</option>
											<option value="create_notification">Create Notification</option>
										</select>
									</div>
								</div>
								<!-- Conditions -->
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Conditions</label>
									{#each newAutomation.conditions as cond, ci}
										<div class="flex gap-2 mb-2">
											<input type="text" bind:value={cond.field} placeholder="Field (e.g. match_score)"
												style="flex: 1; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
											<select bind:value={cond.operator} style="padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);">
												<option value="equals">equals</option>
												<option value="greater_than">greater than</option>
												<option value="less_than">less than</option>
												<option value="contains">contains</option>
											</select>
											<input type="text" bind:value={cond.value} placeholder="Value"
												style="flex: 1; padding: 6px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface);" />
											{#if newAutomation.conditions.length > 1}
												<button onclick={() => { newAutomation.conditions = newAutomation.conditions.filter((_, i) => i !== ci); }}
													style="background: none; border: none; cursor: pointer; color: var(--color-error); font-weight: 900;">x</button>
											{/if}
										</div>
									{/each}
									<button class="btn-secondary" style="font-size: 9px; padding: 3px 10px;"
										onclick={() => { newAutomation.conditions = [...newAutomation.conditions, { field: '', operator: 'equals', value: '' }]; }}>
										+ Add Condition
									</button>
								</div>
								<!-- Action Config -->
								<div>
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Action Config (target value)</label>
									<input type="text" bind:value={newAutomation.action_config.target} placeholder="e.g. shortlisted (for move_stage)"
										style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);" />
								</div>
								<div class="flex gap-2">
									<button class="send-btn" style="font-size: 11px; padding: 6px 16px;" onclick={createAutomation}
										disabled={savingAutomation || !newAutomation.name.trim()}>
										{savingAutomation ? 'Saving...' : 'Save Rule'}
									</button>
									<button class="btn-secondary" style="font-size: 11px; padding: 6px 16px;" onclick={() => showAutomationForm = false}>Cancel</button>
								</div>
							</div>
						</div>
					{/if}

					{#if loadingAutomations}
						<div class="flex items-center justify-center py-8">
							<div class="typing-indicator"><span></span><span></span><span></span></div>
						</div>
					{:else if automationRules.length === 0}
						<div class="flex flex-col items-center py-8" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 32px; color: var(--color-on-surface-dim);">automation</span>
							<p style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 10px;">No automation rules</p>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 4px;">Create rules to automate pipeline actions</p>
						</div>
					{:else}
						<div class="flex flex-col gap-3">
							{#each automationRules as rule, i}
								<div class="ink-border p-4" style="background: var(--color-surface); animation: fadeUp 0.25s ease-out; animation-delay: {i * 0.04}s; animation-fill-mode: both; opacity: 0;">
									<div class="flex items-center justify-between">
										<div class="flex-1">
											<div class="flex items-center gap-2">
												<span style="font-size: 13px; font-weight: 900;">{rule.name || 'Unnamed Rule'}</span>
												<span class="tag-label" style="font-size: 8px;">{rule.trigger?.replace('_', ' ') || '?'}</span>
												<span style="font-size: 8px; padding: 1px 5px; font-weight: 700; text-transform: uppercase; background: {rule.is_active ? '#3a8a4f' : 'var(--color-on-surface-dim, #6f6e69)'}; color: white;">
													{rule.is_active ? 'Active' : 'Inactive'}
												</span>
											</div>
											<div style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 2px;">
												Action: <strong>{rule.action?.replace('_', ' ') || '?'}</strong>
											</div>
										</div>
										<div class="flex gap-2 items-center">
											<button onclick={() => toggleAutomation(rule.id, rule.is_active)}
												style="font-size: 9px; padding: 3px 10px; border: 2px solid var(--color-on-surface); background: none; cursor: pointer; font-weight: 700; text-transform: uppercase;">
												{rule.is_active ? 'Disable' : 'Enable'}
											</button>
											<button onclick={() => deleteAutomation(rule.id)}
												style="background: none; border: none; cursor: pointer; padding: 4px;">
												<span class="material-symbols-outlined" style="font-size: 16px; color: var(--color-error);">delete</span>
											</button>
										</div>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- ── SLA Rules Section ── -->
				<div class="mt-6">
					<div class="flex items-center justify-between mb-3">
						<h2 style="font-size: 14px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">SLA Rules</h2>
						<div class="flex gap-2">
							<button class="btn-secondary" style="font-size: 10px; padding: 5px 12px;" onclick={loadSlaRules} disabled={loadingSla}>
								{loadingSla ? 'Loading...' : 'Refresh'}
							</button>
							<button class="send-btn" style="font-size: 10px; padding: 5px 12px;" onclick={() => { showSlaForm = !showSlaForm; if (!slaRules.length) loadSlaRules(); }}>
								{showSlaForm ? 'Cancel' : '+ Add SLA Rule'}
							</button>
						</div>
					</div>

					{#if showSlaForm}
						<div class="ink-border p-4 mb-4" style="background: var(--color-surface); border-left: 4px solid var(--color-warning, #c98c2a);">
							<span class="tag-label mb-3" style="display: block; background: var(--color-warning, #c98c2a);">New SLA Rule</span>
							<div class="flex gap-3 flex-wrap items-end">
								<div style="flex: 1; min-width: 140px;">
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Stage</label>
									<select bind:value={newSla.stage} style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); text-transform: uppercase;">
										{#each stages as s}
											<option value={s}>{stageLabels[s] || s}</option>
										{/each}
									</select>
								</div>
								<div style="min-width: 100px;">
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Max Days</label>
									<input type="number" bind:value={newSla.max_days} min="1" style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);" />
								</div>
								<div style="min-width: 100px;">
									<label style="font-size: 10px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px;">Alert Days</label>
									<input type="number" bind:value={newSla.alert_days} min="1" style="width: 100%; padding: 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface);" />
								</div>
								<div class="flex gap-2">
									<button class="send-btn" style="font-size: 11px; padding: 8px 16px;" onclick={createSlaRule} disabled={savingSla}>
										{savingSla ? 'Saving...' : 'Save'}
									</button>
									<button class="btn-secondary" style="font-size: 11px; padding: 8px 16px;" onclick={() => showSlaForm = false}>Cancel</button>
								</div>
							</div>
						</div>
					{/if}

					{#if loadingSla}
						<div class="flex items-center justify-center py-8">
							<div class="typing-indicator"><span></span><span></span><span></span></div>
						</div>
					{:else if slaRules.length === 0}
						<div class="flex flex-col items-center py-8" style="border: 3px dashed var(--color-outline-variant);">
							<span class="material-symbols-outlined" style="font-size: 32px; color: var(--color-on-surface-dim);">timer</span>
							<p style="font-size: 13px; font-weight: 900; text-transform: uppercase; margin-top: 10px;">No SLA rules</p>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 4px;">Define time limits for each pipeline stage</p>
						</div>
					{:else}
						<div class="flex flex-col gap-2">
							{#each slaRules as rule}
								<div class="ink-border p-3 flex items-center justify-between" style="background: var(--color-surface);">
									<div class="flex items-center gap-3">
										<span style="font-size: 9px; padding: 2px 8px; background: {stageColors[rule.stage] || 'var(--color-on-surface-dim, #6f6e69)'}; color: white; font-weight: 700; text-transform: uppercase;">{stageLabels[rule.stage] || rule.stage}</span>
										<span style="font-size: 12px;">Max <strong>{rule.max_days}</strong> days, alert at <strong>{rule.alert_days}</strong> days</span>
									</div>
									<button onclick={() => deleteSlaRule(rule.id)} style="background: none; border: none; cursor: pointer; padding: 4px;">
										<span class="material-symbols-outlined" style="font-size: 16px; color: var(--color-error);">delete</span>
									</button>
								</div>
							{/each}
						</div>
					{/if}
				</div>


				<!-- Evaluation Rubrics -->
				<div class="ink-border p-4 mt-4" style="background: var(--color-surface);">
					<span class="tag-label" style="display: block; margin-bottom: 8px;">Evaluation Rubrics</span>
					<p style="font-size: 10px; color: var(--color-on-surface-dim); margin-bottom: 8px;">Auto-generated from JD. Dimensions used in scorecards.</p>
					{#if evalRubrics.length === 0}
						<p style="font-size: 11px; color: var(--color-on-surface-dim); font-style: italic;">No rubrics yet. Save a JD to auto-generate.</p>
					{:else}
						{#each evalRubrics as rubric}
							<div class="flex items-center gap-2 mb-2" style="padding: 4px 0; border-bottom: 1px solid var(--color-outline);">
								<span style="font-size: 11px; font-weight: 700; min-width: 140px;">{rubric.dimension}</span>
								<span style="font-size: 9px; padding: 1px 6px; border: 1px solid {rubric.category === 'technical' ? 'var(--color-primary)' : 'var(--color-warning, #c98c2a)'}; color: {rubric.category === 'technical' ? 'var(--color-primary)' : 'var(--color-warning, #c98c2a)'}; text-transform: uppercase; font-weight: 700;">{rubric.category}</span>
								<span style="font-size: 10px; color: var(--color-on-surface-dim); flex: 1;">{rubric.description || ''}</span>
								<span style="font-size: 9px; font-weight: 700;">W:{rubric.weight}</span>
							</div>
						{/each}
					{/if}
				</div>

				<!-- Culture Values -->
				<div class="ink-border p-4 mt-4" style="background: var(--color-surface);">
					<span class="tag-label" style="display: block; margin-bottom: 8px;">Culture / Values Keywords</span>
					<p style="font-size: 10px; color: var(--color-on-surface-dim); margin-bottom: 8px;">Define values and keywords to score cultural alignment. Candidates are auto-scored against these.</p>
					{#each (position?.culture_values || []) as val, vi}
						<div class="flex items-center gap-2 mb-2" style="padding: 4px 0; border-bottom: 1px solid var(--color-outline);">
							<span style="font-size: 11px; font-weight: 700; min-width: 100px;">{val.value}</span>
							<span style="font-size: 10px; color: var(--color-on-surface-dim); flex: 1;">{(val.keywords || []).join(', ')}</span>
						</div>
					{/each}
					{#if !(position?.culture_values?.length)}
						<p style="font-size: 11px; color: var(--color-on-surface-dim); font-style: italic;">No culture values defined. Add values like "Innovation", "Collaboration" with keywords.</p>
					{/if}
				</div>

				<!-- Competencies (KF4D) — position override / sync from JD -->
				<div class="mt-4">
					<CompetencyPanel
						listUrl={`/positions/${position.slug}/competencies`}
						saveUrl={`/positions/${position.slug}/competencies`}
						syncFromJdUrl={`/positions/${position.slug}/competencies/sync-from-jd`}
						title="Competencies (KF4D)"
					/>
				</div>
			</div>
		{/if}
	</div>
</div>
{/if}

<!-- ═══ POOL PICKER DRAWER ═══ -->
{#if showPoolPicker}
	<div class="drawer-overlay" onclick={(e) => { if (e.target === e.currentTarget) showPoolPicker = false; }}
		role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') showPoolPicker = false; }}>
		<div class="drawer-panel ink-border stamp-shadow" style="width: min(720px, 100vw);">
			<div class="dark-title-bar flex items-center justify-between" style="position: sticky; top: 0; z-index: 5;">
				<span>▮ ATTACH FROM TALENT POOL → {position?.title}</span>
				<button onclick={() => showPoolPicker = false} style="background: none; border: none; color: var(--color-surface); font-size: 18px; cursor: pointer;">✕</button>
			</div>
			<div style="padding: 14px; flex: 1; overflow-y: auto;">
				<div class="flex gap-1 mb-3">
					{#each [{id:'mine',l:'MINE'},{id:'sector',l:'SECTOR'},{id:'pool',l:'POOL'}] as t}
						<button onclick={() => { poolScope = t.id; loadPoolCandidates(); }}
							style="padding: 6px 14px; border: 2px solid var(--color-on-surface); background: {poolScope === t.id ? 'var(--color-primary)' : 'var(--color-surface-bright)'}; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
							{t.l}
						</button>
					{/each}
					<input bind:value={poolSearch} placeholder="search…" oninput={loadPoolCandidates}
						style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-size: 11px;" />
				</div>
				<div style="margin-bottom: 8px; font-size: 10px; opacity: 0.7;">
					{poolItems.length} found · {poolSelected.size} selected
				</div>
				<table style="width: 100%; border-collapse: collapse; font-size: 11px;">
					<thead>
						<tr style="background: var(--color-on-surface); color: var(--color-surface);">
							<th style="width: 24px;"></th>
							<th style="text-align: left; padding: 6px;">NAME</th>
							<th style="padding: 6px;">ROLE</th>
							<th style="padding: 6px;">EXP</th>
							<th style="padding: 6px;">ATTACHED</th>
						</tr>
					</thead>
					<tbody>
						{#each poolItems as c}
							<tr style="border-top: 1px solid rgba(56,56,50,0.15); cursor: pointer;" onclick={() => togglePoolSel(c.id)}>
								<td style="padding: 6px; text-align: center;"><input type="checkbox" checked={poolSelected.has(c.id)} onclick={(e) => e.stopPropagation()} onchange={() => togglePoolSel(c.id)} /></td>
								<td style="padding: 6px;">
									<strong>{c.name || `#${c.id}`}</strong>
									{#if c.email}<div style="font-size: 9px; opacity: 0.6;">{c.email}</div>{/if}
								</td>
								<td style="padding: 6px;">{c.current_role || '—'}</td>
								<td style="padding: 6px; text-align: center;">{c.total_experience_years || 0}y</td>
								<td style="padding: 6px;">
									{#if (c.assignments || []).length}
										<span style="font-size: 9px; opacity: 0.7;">{c.assignments.length} other</span>
									{:else}
										<span style="font-size: 9px; opacity: 0.4;">—</span>
									{/if}
								</td>
							</tr>
						{/each}
						{#if poolItems.length === 0}
							<tr><td colspan="5" style="padding: 20px; text-align: center; opacity: 0.5; font-size: 11px;">no candidates</td></tr>
						{/if}
					</tbody>
				</table>
			</div>
			<div style="padding: 14px 16px; border-top: 1px solid var(--color-border, #e8e6dd); background: var(--color-surface-bright, #fff); display: flex; gap: 10px; justify-content: flex-end; flex-shrink: 0; box-shadow: 0 -2px 8px rgba(0,0,0,0.04);">
				<button onclick={() => showPoolPicker = false}
					style="font-size: 12px; padding: 9px 18px; background: transparent; color: var(--color-on-surface, #2c2c2c); border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px; cursor: pointer; font-weight: 500;">
					Cancel
				</button>
				<button onclick={attachFromPool} disabled={poolSelected.size === 0}
					style="font-size: 12px; padding: 9px 22px; background: var(--color-accent, #c96342); color: #fff; border: 1px solid var(--color-accent, #c96342); border-radius: 6px; cursor: pointer; font-weight: 600; opacity: {poolSelected.size === 0 ? '0.5' : '1'};">
					✓ Attach {poolSelected.size} + score
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- ═══ NEW RICH CANDIDATE DRAWER (slide-in from right) ═══ -->
<CandidateDrawer
	candidateId={drawerCandidateId}
	positionContext={drawerContext}
	isOpen={drawerOpen}
	onClose={closeDrawer}
	onPromote={drawerPromote}
	onReject={drawerReject} />

<!-- ═══ CANDIDATE DRAWER (legacy kanban) ═══ -->
{#if drawerCand}
	<div class="drawer-overlay" onclick={(e) => { if (e.target === e.currentTarget) drawerCand = null; }}
		role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') drawerCand = null; }}>
		<div class="drawer-panel ink-border stamp-shadow">
			<div class="dark-title-bar flex items-center justify-between" style="position: sticky; top: 0; z-index: 5;">
				<div>
					<div style="font-size: 14px; font-weight: 900;">{drawerCand.name || '?'}</div>
					<div style="font-size: 10px; opacity: 0.7;">#{drawerCand.candidate_id || drawerCand.id} · {drawerCand.current_role || '—'} · {drawerCand.current_company || '—'}</div>
				</div>
				<button onclick={() => drawerCand = null} style="background: none; border: none; color: var(--color-surface); font-size: 18px; cursor: pointer;">✕</button>
			</div>

			<div style="padding: 18px; overflow-y: auto; flex: 1;">
				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px; margin-bottom: 14px;">
					<div style="font-size: 10px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 8px;">SCORE BREAKDOWN</div>
					<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; font-size: 11px;">
						<div><strong>{Math.round(drawerCand.match_score_composite || 0)}%</strong> composite</div>
						<div>{Math.round(drawerCand.match_score_skills || 0)}% skills</div>
						<div>{Math.round(drawerCand.match_score_experience || 0)}% exp</div>
						<div>{Math.round(drawerCand.match_score_education || 0)}% edu</div>
						<div>{Math.round(drawerCand.match_score_certifications || 0)}% certs</div>
						<div>{Math.round(drawerCand.match_score_industry || 0)}% industry</div>
					</div>
					{#if drawerCand.skills_matched?.length}
						<div style="margin-top: 8px; font-size: 10px;"><strong style="color: var(--color-primary);">✓ Matched ({drawerCand.skills_matched.length}):</strong> {drawerCand.skills_matched.slice(0, 12).join(', ')}{drawerCand.skills_matched.length > 12 ? '…' : ''}</div>
					{/if}
					{#if drawerCand.skills_missing?.length}
						<div style="margin-top: 4px; font-size: 10px;"><strong style="color: var(--color-error);">✗ Missing ({drawerCand.skills_missing.length}):</strong> {drawerCand.skills_missing.slice(0, 10).join(', ')}{drawerCand.skills_missing.length > 10 ? '…' : ''}</div>
					{/if}
				</div>

				<div style="margin-bottom: 14px;">
					<div style="font-size: 10px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 6px;">MOVE TO STAGE</div>
					<div class="flex gap-1 flex-wrap">
						{#each stages as s}
							<button onclick={() => moveStage(s)} style="font-size: 10px; padding: 4px 10px; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); color: var(--color-on-surface); font-weight: 700; cursor: pointer; text-transform: uppercase;">{stageLabels[s]}</button>
						{/each}
					</div>
				</div>

				<div class="flex gap-2 flex-wrap" style="margin-bottom: 14px;">
					<a href={`/candidates/${drawerCand.candidate_id || drawerCand.id}`} class="btn-secondary" style="font-size: 10px; padding: 6px 12px; text-decoration: none;">Open Profile →</a>
					<button class="btn-secondary" style="font-size: 10px; padding: 6px 12px; border-color: var(--color-error); color: var(--color-error);" onclick={() => composeRejectionEmail(drawerCand.candidate_id || drawerCand.id, drawerCand.name)}>Reject Email</button>
				</div>

				<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px; margin-bottom: 14px;">
					<div style="font-size: 10px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 8px;">NOTES ({drawerNotes.length})</div>
					<textarea bind:value={newNote} placeholder="Add note about this candidate…" rows="3" style="width: 100%; border: 2px solid var(--color-on-surface); padding: 6px; font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface); resize: vertical;"></textarea>
					<div class="flex justify-end" style="margin-top: 6px;">
						<button onclick={addDrawerNote} disabled={savingNote || !newNote.trim()} class="send-btn" style="font-size: 10px; padding: 4px 12px;">{savingNote ? 'Saving…' : 'Add Note'}</button>
					</div>
					{#if drawerNotes.length}
						<div style="margin-top: 10px; max-height: 180px; overflow-y: auto;">
							{#each drawerNotes as n}
								<div style="border-top: 1px dashed rgba(56,56,50,0.2); padding: 6px 0;">
									<div style="font-size: 12px; line-height: 1.5;">{n.content || n.text || ''}</div>
									<div style="font-size: 9px; color: var(--color-on-surface-dim); margin-top: 2px;">{n.created_at ? new Date(n.created_at).toLocaleString() : ''} {n.author_name ? `· ${n.author_name}` : ''}</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				{#if drawerScorecards.length}
					<div class="ink-border" style="background: var(--color-surface-bright); padding: 12px; margin-bottom: 14px;">
						<div style="font-size: 10px; font-weight: 900; letter-spacing: 0.08em; margin-bottom: 6px;">SCORECARDS ({drawerScorecards.length})</div>
						{#each drawerScorecards.slice(0, 5) as sc}
							<div style="font-size: 11px; padding: 4px 0; border-top: 1px dashed rgba(56,56,50,0.15);">
								<strong>{sc.interviewer_name || sc.created_by_name || '?'}</strong> · {sc.recommendation || sc.overall || ''} · score: {sc.overall_score ?? '—'}
							</div>
						{/each}
					</div>
				{/if}

			</div>
		</div>
	</div>
{/if}

<!-- UploadProgressModal removed — pipeline activity now in PULSE FEED · PIPELINE tab + bottom CLI terminal -->


<style>
	@media (max-width: 768px) {
		.hide-mobile { display: none !important; }
	}

	/* ─── Candidates tab section bands ─── */
	.cand-section { margin-bottom: 24px; }
	.cand-section-header {
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		padding: 8px 16px;
		margin-bottom: 12px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 12px;
		font-weight: 700;
		font-family: 'Space Grotesk', sans-serif;
	}
	.cand-section-title { display: block; }

	.drawer-overlay {
		position: fixed; inset: 0 0 32px 0;  /* leave 32px at bottom for Activity Terminal bar */
		background: rgba(44,44,44,0.42); z-index: 200;
		display: flex; justify-content: flex-end;
		animation: fadeIn 0.15s ease;
	}
	.drawer-panel {
		width: min(560px, 100vw);
		height: 100%; max-height: 100%;
		background: var(--color-surface);
		display: flex; flex-direction: column;
		animation: slideIn 0.2s ease;
		overflow: hidden;
	}
	@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
	@keyframes slideIn { from { transform: translateX(40px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

	/* ─── JD Body Typography (mirrors /jds/[id]) ─── */
	:global(.jd-p) { font-size: 14px; line-height: 1.75; margin: 0 0 14px; color: var(--color-on-surface); }
	:global(.jd-h1) { font-size: 22px; font-weight: 900; letter-spacing: 0.02em; text-transform: uppercase; margin: 0 0 16px; padding-bottom: 8px; border-bottom: 3px solid var(--color-on-surface); }
	:global(.jd-h2) { font-size: 16px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; margin: 28px 0 12px; padding: 8px 14px; background: var(--color-on-surface); color: var(--color-surface); display: block; }
	:global(.jd-h3) { font-size: 14px; font-weight: 900; letter-spacing: 0.05em; text-transform: uppercase; margin: 20px 0 8px; border-left: 4px solid var(--color-primary); padding: 4px 10px; background: var(--color-surface-bright); }
	:global(.jd-h4) { font-size: 12px; font-weight: 900; letter-spacing: 0.05em; text-transform: uppercase; margin: 14px 0 6px; color: var(--color-on-surface-dim); }
	:global(.jd-hr) { border: none; border-top: 2px dashed var(--color-on-surface); margin: 24px 0; opacity: 0.4; }
	:global(.jd-ul) { margin: 8px 0 16px; padding-left: 0; list-style: none; }
	:global(.jd-ul li) { font-size: 14px; line-height: 1.7; padding: 6px 0 6px 22px; position: relative; border-bottom: 1px dashed rgba(56,56,50,0.12); }
	:global(.jd-ul li:last-child) { border-bottom: none; }
	:global(.jd-ul li::before) { content: "▸"; position: absolute; left: 0; top: 6px; color: var(--color-primary); font-weight: 900; }
	:global(.jd-ul li strong) { color: var(--color-on-surface); font-weight: 900; }
	:global(.jd-table-wrap) { margin: 12px 0 20px; overflow-x: auto; }
	:global(.jd-table) { width: 100%; border-collapse: collapse; font-size: 13px; border: 2px solid var(--color-on-surface); }
	:global(.jd-table th) { background: var(--color-on-surface); color: var(--color-surface); text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 900; letter-spacing: 0.08em; text-transform: uppercase; border-bottom: 2px solid var(--color-on-surface); }
	:global(.jd-table td) { padding: 10px 14px; border-top: 1px solid rgba(56,56,50,0.18); vertical-align: top; }
	:global(.jd-table td.first) { font-weight: 900; background: var(--color-surface-bright); min-width: 180px; }
	:global(.jd-table tr.alt td) { background: rgba(56,56,50,0.02); }
	:global(.jd-table tr.alt td.first) { background: var(--color-surface-bright); }

	/* Match Agent button (replaces SCAN REPO) */
	.btn-run-agent {
		font-size: 11px; font-weight: 700;
		padding: 7px 14px;
		background: var(--color-accent, #c96342); color: #fff;
		border: 1px solid var(--color-accent, #c96342); border-radius: 7px;
		cursor: pointer;
		display: inline-flex; align-items: center; gap: 6px;
		text-transform: uppercase; letter-spacing: 0.04em;
		transition: filter 120ms;
	}
	.btn-run-agent:hover:not(:disabled) { filter: brightness(0.94); }
	.btn-run-agent:disabled { opacity: 0.7; cursor: not-allowed; }
	.btn-run-agent-ghost {
		background: transparent !important; color: var(--color-on-surface, #2c2c2c) !important;
		border: 1px solid var(--color-border, #d8d5cc) !important;
	}
	.btn-run-agent-ghost:hover:not(:disabled) {
		background: var(--color-bg, #faf9f5) !important;
		filter: none !important;
	}
	.run-agent-spark { font-size: 13px; }
	.run-agent-spinner { font-size: 14px; animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }

	/* Processing banner — top-of-page sticky strip during agent runs */
	.processing-banner {
		position: sticky; top: 0; z-index: 50;
		display: flex; align-items: center; gap: 12px;
		padding: 10px 16px;
		background: var(--color-accent, #c96342); color: #fff;
		font-size: 12.5px; font-weight: 500;
		box-shadow: 0 2px 6px rgba(0,0,0,0.12);
	}
	.processing-spin { font-size: 18px; animation: spin 1s linear infinite; }
	.processing-text { flex: 1; line-height: 1.4; }
	.processing-text strong { font-weight: 700; }
	.processing-count {
		display: inline-block; margin-left: 10px;
		padding: 1px 8px; background: rgba(255,255,255,0.22); border-radius: 999px;
		font-size: 11px; font-weight: 600;
	}

	/* AI Suggestions panel — Claude warm theme */
	.sug-card {
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-left: 3px solid var(--color-accent, #c96342);
		border-radius: 10px;
		overflow: hidden;
	}
	.sug-head {
		padding: 12px 16px; display: flex; align-items: center; justify-content: space-between;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-bg, #faf9f5);
	}
	.sug-title {
		font-size: 13px; font-weight: 600; color: var(--color-accent, #c96342);
		display: inline-flex; align-items: center; gap: 6px;
	}
	.sug-count {
		font-size: 10.5px; font-weight: 700; padding: 1px 7px;
		background: var(--color-accent, #c96342); color: #fff; border-radius: 999px;
	}
	.sug-refresh {
		font-size: 11px; padding: 4px 10px;
		background: transparent; color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px; cursor: pointer;
	}
	.sug-refresh:hover { background: #fff; }
	.sug-body { padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; }
	.sug-row {
		padding: 12px 14px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd); border-radius: 8px;
		display: flex; align-items: center; justify-content: space-between; gap: 16px;
	}
	.sug-desc { font-size: 13px; color: var(--color-on-surface, #2c2c2c); line-height: 1.5; flex: 1; }
	.sug-actions { display: flex; gap: 8px; flex-shrink: 0; }
	.sug-btn-apply {
		font-size: 12px; font-weight: 600; padding: 6px 16px;
		background: var(--color-accent, #c96342); color: #fff;
		border: 1px solid var(--color-accent, #c96342); border-radius: 6px; cursor: pointer;
		min-width: 70px;
	}
	.sug-btn-apply:hover:not(:disabled) { filter: brightness(0.94); }
	.sug-btn-apply:disabled { opacity: 0.6; cursor: not-allowed; }
	.sug-btn-dismiss {
		font-size: 12px; font-weight: 500; padding: 6px 16px;
		background: transparent; color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px; cursor: pointer;
		min-width: 70px;
	}
	.sug-btn-dismiss:hover:not(:disabled) { background: var(--color-bg, #faf9f5); }
	.sug-btn-dismiss:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
