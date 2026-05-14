<script>
	/** Job Poolsitory — Create, generate, manage job descriptions */
	import { onMount, untrack } from 'svelte';
	import { apiJson, getToken } from '$lib/api';
	import Pagination from '$lib/Pagination.svelte';
	import { addToast } from '$lib/Toast.svelte';
	import { goto } from '$app/navigation';
	import JdRailFilters from '$lib/JdRailFilters.svelte';
	import { SkeletonRow } from '$lib/Skeleton.svelte';
	import EmptyState from '$lib/EmptyState.svelte';
	import FileText from '@lucide/svelte/icons/file-text';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import ClipboardList from '@lucide/svelte/icons/clipboard-list';
	import Eye from '@lucide/svelte/icons/eye';

	let jds = $state([]);
	let jdTotal = $state(0);

	// ── j/k row navigation ──
	let focusedRowIdx = $state(-1);
	let jdTableRoot = $state(null);
	function isTypingTarget(el) {
		if (!el) return false;
		const tag = el.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
	}
	function focusJdRow(idx) {
		if (!jdTableRoot) return;
		const rows = jdTableRoot.querySelectorAll('[data-row-idx]');
		if (!rows.length) return;
		const c = Math.max(0, Math.min(rows.length - 1, idx));
		focusedRowIdx = c;
		rows[c]?.focus();
		rows[c]?.scrollIntoView({ block: 'nearest' });
	}
	function onJdTableKey(e) {
		if (isTypingTarget(e.target)) return;
		if (!jds.length) return;
		if (e.key === 'j') { e.preventDefault(); focusJdRow(focusedRowIdx < 0 ? 0 : focusedRowIdx + 1); }
		else if (e.key === 'k') { e.preventDefault(); focusJdRow(focusedRowIdx < 0 ? 0 : focusedRowIdx - 1); }
		else if (e.key === 'Enter' && focusedRowIdx >= 0) {
			const jd = jds[focusedRowIdx];
			if (jd) { e.preventDefault(); goto(`/jds/${jd.id}`); }
		} else if ((e.key === 'x' || e.key === 'X') && focusedRowIdx >= 0) {
			const jd = jds[focusedRowIdx];
			if (jd && typeof askDelete === 'function') { e.preventDefault(); askDelete(jd, e); }
		}
	}

	let jdOffset = $state(0);
	const jdLimit = 20;
	let loading = $state(true);
	let searchQuery = $state('');
	let scope = $state(typeof localStorage !== 'undefined' ? (localStorage.getItem('hire_jd_tab') || 'mine') : 'mine');
	let counts = $state({ mine: 0, sector: 0, global: 0 });

	// Create/Generate modal
	let showModal = $state(false);
	let modalMode = $state('generate'); // legacy, kept for refs that still read it
	let showPasteModal = $state(false);
	let pasteAiEnhancing = $state(false);
	let pasteAiResult = $state(null); // { jd_text, extracted } after AI enhance
	let pasteViewMode = $state('rendered');
	let genTitle = $state('');
	let genDept = $state('');
	let genSeniority = $state('');
	let genBullets = $state('');
	let genTone = $state('professional');
	let pasteJd = $state('');
	let generating = $state(false);
	// Preview state — AI-generated JD pending user SAVE
	let genPreview = $state(null); // { jd_text, extracted, scoring_profile, weights } | null
	let savingPreview = $state(false);

	// Corporate template fields (used by both generate + paste)
	let tplJobCode = $state('');
	let tplBusinessSector = $state('');
	let tplGrading = $state('');
	let tplReportingTo = $state('');
	let tplLocation = $state('');
	let tplWorkMode = $state('onsite');
	let tplEmploymentType = $state('full-time');
	let tplJobPurpose = $state('');
	let tplPreferredEducation = $state('');
	let tplTravel = $state('');
	let tplPhysical = $state('');
	let tplDocOwner = $state('');

	// Validation state
	let jdTitleTouched = $state(false);
	let jdTextTouched = $state(false);
	let jdTitleError = $derived(
		jdTitleTouched && genTitle.trim().length < 3 ? (genTitle.trim().length === 0 ? 'Title is required' : 'Title must be at least 3 characters') : ''
	);
	let jdTextError = $derived(
		jdTextTouched && modalMode === 'paste' && pasteJd.trim().length < 50 ? (pasteJd.trim().length === 0 ? 'JD text is required' : `Min 50 chars (${pasteJd.trim().length}/50)`) : ''
	);
	let bulletsWarning = $derived(
		modalMode === 'generate' && genBullets.split('\n').filter(b => b.trim()).length === 0 ? 'At least 1 bullet point recommended for better results' : ''
	);
	let jdTitleValid = $derived(genTitle.trim().length >= 3);
	let jdPasteValid = $derived(modalMode === 'paste' ? pasteJd.trim().length >= 50 : true);

	// View modal
	let selectedJd = $state(null);
	let enhancing = $state(false);
let replacing = $state(false);
let savingDraft = $state(false);
let draft = $state(null);   // editable copy of selectedJd; null when modal closed
let dirty = $state(false);
let _lastJdId = $state(null);
$effect(() => {
	if (selectedJd && selectedJd.id !== _lastJdId) {
		draft = {
			jd_text: selectedJd.jd_text || '',
			title: selectedJd.title || '',
			department: selectedJd.department || '',
			seniority_level: selectedJd.seniority_level || '',
			employment_type: selectedJd.employment_type || 'full_time',
			required_skills: [...(selectedJd.required_skills || [])],
			nice_to_have_skills: [...(selectedJd.nice_to_have_skills || [])],
			min_experience_years: selectedJd.min_experience_years || 0,
			education_level: selectedJd.education_level || '',
			industry_keywords: [...(selectedJd.industry_keywords || [])],
			required_certifications: [...(selectedJd.required_certifications || [])],
			dei_score: selectedJd.dei_score,
			completeness_score: selectedJd.completeness_score,
		};
		dirty = false;
		_lastJdId = selectedJd.id;
	}
	if (!selectedJd) _lastJdId = null;
});

function markDirty() { dirty = true; }

// Rendered docx HTML (mammoth) for left pane preview
let docxHtml = $state('');
let docxLoading = $state(false);
$effect(() => {
	if (!selectedJd) { docxHtml = ''; return; }
	const ext = (selectedJd.source_file_type || '').toLowerCase();
	if (ext !== 'docx' && ext !== 'doc') { docxHtml = ''; return; }
	docxLoading = true;
	(async () => {
		try {
			const r = await fetch(`/api/jds/${selectedJd.id}/file?t=${getToken()}`);
			if (!r.ok) throw new Error(`HTTP ${r.status}`);
			const buf = await r.arrayBuffer();
			const mammoth = await import('mammoth/mammoth.browser.js');
			const result = await mammoth.convertToHtml({ arrayBuffer: buf });
			docxHtml = result.value;
		} catch (e) {
			docxHtml = `<p style="color:#c0392b">Preview failed: ${e.message}</p>`;
		}
		docxLoading = false;
	})();
});

	// ── AI Facet Groups (self-growing JD rail) ──
	// Smart defaults: restore last filters from `pulse_jd_filters`
	const _jdFilterDefaults = (() => {
		if (typeof localStorage === 'undefined') return {};
		try { return JSON.parse(localStorage.getItem('pulse_jd_filters') || '{}'); }
		catch { return {}; }
	})();
	let facetGroups = $state({});
	let facetNewTotal = $state(0);
	let jdSkillSelected = $state(new Set(_jdFilterDefaults.skill || []));
	let jdDeptSelected = $state(new Set(_jdFilterDefaults.dept || []));
	let jdLocationSelected = $state(new Set(_jdFilterDefaults.location || []));
	let jdEmploymentTypeSelected = $state(new Set(_jdFilterDefaults.employmentType || []));
	let jdSenioritySelected = $state(new Set(_jdFilterDefaults.seniority || []));
	let railStateFilter = $state(_jdFilterDefaults.railStateFilter || 'active');

	// Persist on any change
	$effect(() => {
		if (typeof localStorage === 'undefined') return;
		try {
			localStorage.setItem('pulse_jd_filters', JSON.stringify({
				skill: [...jdSkillSelected],
				dept: [...jdDeptSelected],
				location: [...jdLocationSelected],
				employmentType: [...jdEmploymentTypeSelected],
				seniority: [...jdSenioritySelected],
				railStateFilter,
			}));
		} catch {}
	});
	let stateCounts = $state({ active: 0, draft: 0, archived: 0 });
	let facetPollHandle = null;

	async function loadFacetGroups() {
		try {
			const data = await apiJson('/facets/groups?domain=jd');
			facetGroups = data.groups || {};
			facetNewTotal = data.new_total || 0;
		} catch { /* silent */ }
	}
	async function dismissFacetNew(facetId) {
		try { await apiJson(`/facets/dismiss/${facetId}`, { method: 'POST' }); } catch {}
	}
	function clearAllRailFilters() {
		jdSkillSelected = new Set();
		jdDeptSelected = new Set();
		jdLocationSelected = new Set();
		jdEmploymentTypeSelected = new Set();
		jdSenioritySelected = new Set();
		railStateFilter = 'active';
		try { localStorage.removeItem('hire_jd_facets'); } catch {}
		loadJds();
	}

	// Reactive facet-driven reload — re-runs whenever any selected set or state changes
	let _facetSig = $derived(
		[...jdSkillSelected].sort().join(',') + '|' +
		[...jdDeptSelected].sort().join(',') + '|' +
		[...jdLocationSelected].sort().join(',') + '|' +
		[...jdEmploymentTypeSelected].sort().join(',') + '|' +
		[...jdSenioritySelected].sort().join(',') + '|' +
		railStateFilter + '|' + scope
	);
	let _facetMounted = false;
	$effect(() => {
		// Read sig to subscribe
		_facetSig;
		untrack(() => {
			if (!_facetMounted) { _facetMounted = true; return; }
			jdOffset = 0;
			loadJds();
		});
	});

	onMount(() => {
		loadJds();
		loadUserOptions();
		loadFacetGroups();
		facetPollHandle = setInterval(loadFacetGroups, 30000);
		return () => { if (facetPollHandle) clearInterval(facetPollHandle); };
	});

	async function viewJdDetail(jdId) {
		try {
			selectedJd = await apiJson(`/jds/${jdId}`);
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error(e); }
	}

	async function loadJds() {
		loading = true;
		try {
			const p = new URLSearchParams();
			p.set('limit', String(jdLimit)); p.set('offset', String(jdOffset));
			p.set('scope', scope); p.set('sort', sortCol); p.set('dir', sortDir);
			if (searchQuery) p.set('search', searchQuery);
			if (filterDept) p.set('department', filterDept);
			if (filterLevel) p.set('seniority', filterLevel);
			if (filterCreatedBy) p.set('created_by', filterCreatedBy);
			if (filterModifiedBy) p.set('modified_by', filterModifiedBy);
			const ca = rangeBoundary(filterCreated); if (ca) p.set('created_after', ca);
			const ma = rangeBoundary(filterModified); if (ma) p.set('modified_after', ma);
			// Rail-driven STATE filter (active|draft|archived)
			if (railStateFilter && railStateFilter !== 'all') p.set('status', railStateFilter);
			// Rail-driven facet CSVs
			if (jdSkillSelected.size)           p.set('skills',           [...jdSkillSelected].join(','));
			if (jdDeptSelected.size)            p.set('depts',            [...jdDeptSelected].join(','));
			if (jdLocationSelected.size)        p.set('locations',        [...jdLocationSelected].join(','));
			if (jdEmploymentTypeSelected.size)  p.set('employment_types', [...jdEmploymentTypeSelected].join(','));
			if (jdSenioritySelected.size)       p.set('seniorities',      [...jdSenioritySelected].join(','));
			const data = await apiJson(`/jds?${p.toString()}`);
			jds = data.jds || [];
			jdTotal = data.total || jds.length;
			if (data.counts) counts = data.counts;
			// Status counts (rough — based on what's loaded for the current scope)
			try {
				const sc = { active: 0, draft: 0, archived: 0 };
				for (const j of jds) {
					const s = (j.status || 'active');
					if (sc[s] !== undefined) sc[s] += 1;
				}
				stateCounts = sc;
			} catch {}
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error(e); }
		loading = false;
	}

	async function uploadJdFiles(fileList, rawOnly = false) {
		const fd = new FormData();
		for (const f of fileList) fd.append('files', f);
		fd.append('force_type', 'JD');
		if (rawOnly) fd.append('raw_only', 'true');
		try {
			const r = await fetch('/api/ingest/', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${getToken()}` } });
			const d = await r.json();
			const ok = (d.results || []).filter(x => x.status === 'success');
			const err = (d.results || []).filter(x => x.status !== 'success');
			cliEvent('success', `Imported ${ok.length} JD(s), ${err.length} errors`);
			if (ok.length === 1) {
				try { selectedJd = await apiJson(`/jds/${ok[0].target_id}`); } catch {}
			}
			await loadJds();
		} catch (e) {
			cliEvent('error', `Upload failed: ${e.message}`);
		}
	}

	function setScope(s) {
		scope = s;
		jdOffset = 0;
		try { localStorage.setItem('hire_jd_tab', s); } catch {}
		loadJds();
	}

	let shareOpenId = $state(null);
	let sharePos = $state({ top: 0, left: 0 });
	async function shareJdMulti(jdId, payload, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		try {
			await apiJson(`/jds/${jdId}/share`, {
				method: 'POST',
				body: JSON.stringify(payload),
			});
			cliEvent('success', `JD share updated · sector=${payload.shared_sector} global=${payload.shared_global}`);
			await loadJds();
		} catch (e) {
			cliEvent('error', `Share failed: ${e.message}`);
			alert('Share failed: ' + e.message);
		}
	}

	async function shareJd(jdId, vis, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		try {
			await apiJson(`/jds/${jdId}/share`, { method: 'POST', body: JSON.stringify({ visibility: vis }) });
			cliEvent('success', `JD shared → ${vis}`);
			shareOpenId = null;
			await loadJds();
		} catch (e) {
			cliEvent('error', `Share failed: ${e.message}`);
			alert('Share failed: ' + e.message);
		}
	}
	function toggleShare(id, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		if (shareOpenId === id) { shareOpenId = null; return; }
		const r = ev.currentTarget.getBoundingClientRect();
		sharePos = { top: r.bottom + 4, left: Math.max(8, r.right - 220) };
		shareOpenId = id;
	}
	function closeShare() { shareOpenId = null; }

	// --- Hard-delete with double-confirm ---
	let deleteTarget = $state(null); // { id, title }
	let deleteConfirmText = $state('');
	let deleting = $state(false);
	function askDelete(jd, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		deleteTarget = { id: jd.id, title: jd.title };
		deleteConfirmText = '';
	}
	async function confirmDelete() {
		if (!deleteTarget) return;
		const _t = (deleteTarget.title || '').trim().toLowerCase();
		const _v = deleteConfirmText.trim().toLowerCase();
		if (!(_v === _t || _v === 'delete')) {
			addToast('error', `Type JD title "${deleteTarget.title}" or DELETE`);
			return;
		}
		deleting = true;
		try {
			await apiJson(`/jds/${deleteTarget.id}?hard=true`, { method: 'DELETE' });
			addToast('success', `✓ "${deleteTarget.title}" permanently deleted`);
			cliEvent('success', `JD "${deleteTarget.title}" hard-deleted`);
			deleteTarget = null;
			deleteConfirmText = '';
			await loadJds();
		} catch (e) {
			addToast('error', `Delete failed: ${e.message}`);
		}
		deleting = false;
	}

	// ─── Table filters & sort (persisted) ───
	const _persistedJd = (() => {
		try { return JSON.parse(localStorage.getItem('hire_jd_table') || '{}'); }
		catch { return {}; }
	})();
	let filterDept    = $state(_persistedJd.dept || '');
	let filterLevel   = $state(_persistedJd.level || '');
	let filterCreated = $state(_persistedJd.createdRange || 'all');
	let filterModified = $state(_persistedJd.modifiedRange || 'all');
	let filterCreatedBy  = $state(_persistedJd.createdBy || '');
	let filterModifiedBy = $state(_persistedJd.modifiedBy || '');
	let sortCol  = $state(_persistedJd.sortCol || 'updated_at');
	let sortDir  = $state(_persistedJd.sortDir || 'desc');

	function persistJdTable() {
		try {
			localStorage.setItem('hire_jd_table', JSON.stringify({
				dept: filterDept, level: filterLevel,
				createdRange: filterCreated, modifiedRange: filterModified,
				createdBy: filterCreatedBy, modifiedBy: filterModifiedBy,
				sortCol, sortDir,
			}));
		} catch {}
	}

	function rangeBoundary(preset) {
		// Returns ISO start (after) for preset; null = no filter
		if (preset === 'today') {
			const d = new Date(); d.setHours(0,0,0,0);
			return d.toISOString();
		}
		if (preset === '24h')  return new Date(Date.now() - 86400e3).toISOString();
		if (preset === '7d')   return new Date(Date.now() - 7*86400e3).toISOString();
		if (preset === '30d')  return new Date(Date.now() - 30*86400e3).toISOString();
		return null;
	}

	let userOptions = $state([]);
	async function loadUserOptions() {
		try {
			const r = await apiJson('/auth/users/lookup?limit=50');
			userOptions = r.users || [];
		} catch {}
	}

	// Map sortCol to API param
	function sortHeaderClick(col) {
		if (sortCol === col) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortCol = col; sortDir = 'desc';
		}
		persistJdTable(); loadJds();
	}

	function sortIcon(col) {
		if (sortCol !== col) return '';
		return sortDir === 'asc' ? '▲' : '▼';
	}

	function applyFilters() {
		persistJdTable(); loadJds();
	}

	function timeAgo(iso) {
		if (!iso) return '—';
		const d = new Date(iso); const diff = (Date.now() - d.getTime()) / 1000;
		if (diff < 60) return 'just now';
		if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
		if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
		if (diff < 30*86400) return `${Math.floor(diff/86400)}d ago`;
		if (diff < 365*86400) return `${Math.floor(diff/(30*86400))}mo`;
		return d.toLocaleDateString();
	}
	function fmtAbs(iso) {
		if (!iso) return '';
		const d = new Date(iso);
		return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
			+ ' · ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	}

	function onJdPageChange(newOffset) {
		jdOffset = newOffset;
		loadJds();
	}

	async function generateJd() {
		if (!genTitle.trim()) return;
		generating = true;
		try {
			const bullets = genBullets.split('\n').filter(b => b.trim());
			const data = await apiJson('/jds/generate?preview=true', {
				method: 'POST',
				body: JSON.stringify({
					title: genTitle,
					department: genDept,
					seniority_level: genSeniority,
					bullets,
					tone: genTone,
					employment_type: tplEmploymentType,
					job_code: tplJobCode || null,
					business_sector: tplBusinessSector || null,
					grading: tplGrading || null,
					reporting_to: tplReportingTo || null,
					location: tplLocation || null,
					work_mode: tplWorkMode || null,
					travel_requirement: tplTravel || null,
					physical_conditions: tplPhysical || null,
					doc_owner: tplDocOwner || null,
				}),
			});
			genPreview = {
				jd_text: data.jd_text || '',
				extracted: data.extracted || {},
				scoring_profile: data.scoring_profile,
				weights: data.weights || {},
			};
			cliEvent('success', `JD "${genTitle}" generated — preview ready · click SAVE to add to JD pool`);
		} catch (e) {
			cliEvent('error', `Generation failed: ${e.message}`);
		}
		generating = false;
	}

	async function savePreview() {
		if (!genPreview || !genTitle.trim()) return;
		savingPreview = true;
		try {
			const data = await apiJson('/jds/', {
				method: 'POST',
				body: JSON.stringify({
					title: genTitle,
					department: genDept,
					seniority_level: genSeniority,
					employment_type: tplEmploymentType,
					jd_text: genPreview.jd_text,
					required_skills: genPreview.extracted?.required_skills || [],
					nice_to_have_skills: genPreview.extracted?.nice_to_have || [],
					min_experience_years: genPreview.extracted?.min_experience_years || 0,
					education_level: genPreview.extracted?.education_level || '',
					industry_keywords: genPreview.extracted?.industry_keywords || [],
					required_certifications: genPreview.extracted?.certifications || [],
					job_code: tplJobCode || null,
					business_sector: tplBusinessSector || null,
					grading: tplGrading || null,
					reporting_to: tplReportingTo || null,
					location: tplLocation || null,
					work_mode: tplWorkMode || null,
					travel_requirement: tplTravel || null,
					physical_conditions: tplPhysical || null,
					doc_owner: tplDocOwner || null,
				}),
			});
			addToast?.('success', `✓ "${genTitle}" saved to JD pool`);
			cliEvent('success', `JD "${genTitle}" saved to repository`);
			genPreview = null;
			showModal = false;
			resetForm();
			// Switch to MINE scope so newly-saved JD is visible (default visibility = private/mine)
			if (scope !== 'mine') {
				setScope('mine');
			} else {
				await loadJds();
			}
		} catch (e) {
			cliEvent('error', `Save failed: ${e.message}`);
			addToast?.('error', `Save failed: ${e.message}`);
		}
		savingPreview = false;
	}

	function discardPreview() {
		genPreview = null;
	}

	// ── PASTE flow handlers ──
	async function savePasteRaw() {
		if (!genTitle.trim() || pasteJd.trim().length < 50) return;
		pasteAiEnhancing = true;
		try {
			const data = await apiJson('/jds/', {
				method: 'POST',
				body: JSON.stringify({
					title: genTitle,
					department: genDept || '',
					seniority_level: genSeniority || '',
					employment_type: tplEmploymentType || 'full-time',
					jd_text: pasteJd,
				}),
			});
			addToast?.('success', `✓ "${genTitle}" saved to JD pool (${data.extracted?.required_skills?.length || 0} skills extracted)`);
			cliEvent('success', `JD "${genTitle}" saved (raw paste, auto-extracted)`);
			showPasteModal = false;
			pasteAiResult = null;
			resetForm();
			if (scope !== 'mine') setScope('mine'); else await loadJds();
		} catch (e) {
			addToast?.('error', `Save failed: ${e.message}`);
		}
		pasteAiEnhancing = false;
	}

	async function runPasteEnhance() {
		if (!genTitle.trim() || pasteJd.trim().length < 50) return;
		pasteAiEnhancing = true;
		try {
			// Step 1: save raw to get jd_id (private)
			const created = await apiJson('/jds/', {
				method: 'POST',
				body: JSON.stringify({
					title: genTitle,
					department: genDept || '',
					seniority_level: genSeniority || '',
					employment_type: tplEmploymentType || 'full-time',
					jd_text: pasteJd,
				}),
			});
			const jdId = created.jd_id;
			// Step 2: AI-enhance (preview, returns improved text without saving)
			const enhanced = await apiJson(`/jds/${jdId}/enhance?preview=true`, { method: 'POST' });
			const d = enhanced.draft || {};
			pasteAiResult = {
				jd_id: jdId,
				jd_text: d.jd_text || pasteJd,
				extracted: enhanced.extracted || created.extracted || {},
				scoring_profile: created.scoring_profile,
				dei_score: d.dei_score,
				completeness_score: d.completeness_score,
			};
			cliEvent('success', `JD "${genTitle}" enhanced — review preview`);
		} catch (e) {
			addToast?.('error', `AI enhance failed: ${e.message}`);
		}
		pasteAiEnhancing = false;
	}

	async function savePasteEnhanced() {
		if (!pasteAiResult || !pasteAiResult.jd_id) return;
		pasteAiEnhancing = true;
		try {
			// Persist the enhanced text on the already-saved JD
			await apiJson(`/jds/${pasteAiResult.jd_id}/body`, {
				method: 'PATCH',
				body: JSON.stringify({ jd_text: pasteAiResult.jd_text }),
			});
			addToast?.('success', `✓ "${genTitle}" saved + AI-enhanced`);
			cliEvent('success', `JD "${genTitle}" enhanced & saved`);
			showPasteModal = false;
			pasteAiResult = null;
			resetForm();
			if (scope !== 'mine') setScope('mine'); else await loadJds();
		} catch (e) {
			addToast?.('error', `Save failed: ${e.message}`);
		}
		pasteAiEnhancing = false;
	}

	async function createJd() {
		if (!genTitle.trim() || !pasteJd.trim()) return;
		generating = true;
		try {
			const data = await apiJson('/jds/', {
				method: 'POST',
				body: JSON.stringify({
					title: genTitle,
					department: genDept,
					seniority_level: genSeniority,
					jd_text: pasteJd,
					employment_type: tplEmploymentType,
					job_code: tplJobCode || null,
					business_sector: tplBusinessSector || null,
					grading: tplGrading || null,
					reporting_to: tplReportingTo || null,
					location: tplLocation || null,
					work_mode: tplWorkMode || null,
					job_purpose: tplJobPurpose || null,
					preferred_education: tplPreferredEducation || null,
					travel_requirement: tplTravel || null,
					physical_conditions: tplPhysical || null,
					doc_owner: tplDocOwner || null,
				}),
			});
			cliEvent('success', `JD "${genTitle}" saved — ${data.extracted?.required_skills?.length || 0} skills extracted`);
			showModal = false;
			resetForm();
			await loadJds();
		} catch (e) {
			cliEvent('error', `Save failed: ${e.message}`);
		}
		generating = false;
	}

	async function saveDraft() {
		if (!draft || !selectedJd) return;
		savingDraft = true;
		try {
			await apiJson(`/jds/${selectedJd.id}`, { method: 'PATCH', body: JSON.stringify(draft) });
			const savedTitle = draft?.title || selectedJd.title || 'JD';
			cliEvent('success', `✓ "${savedTitle}" saved successfully`);
			await loadJds();
			dirty = false;
			draft = null;
			selectedJd = null;
		} catch (e) {
			cliEvent('error', `Save failed: ${e.message}`);
		}
		savingDraft = false;
	}

	async function replaceJdFromFile(jdId, file) {
		replacing = true;
		try {
			const fd = new FormData();
			fd.append('file', file);
			const r = await fetch(`/api/jds/${jdId}/upload-body`, { method: 'POST', body: fd, headers: { Authorization: `Bearer ${getToken()}` } });
			if (!r.ok) throw new Error(await r.text());
			selectedJd = await apiJson(`/jds/${jdId}`);
			cliEvent('success', `JD body replaced from ${file.name}`);
			await loadJds();
		} catch (e) {
			cliEvent('error', `Upload failed: ${e.message}`);
		}
		replacing = false;
	}

	async function enhanceJd(jdId) {
		enhancing = true;
		try {
			const data = await apiJson(`/jds/${jdId}/enhance?preview=true`, { method: 'POST' });
			if (data?.draft && draft) {
				Object.assign(draft, data.draft);
				dirty = true;
			}
			cliEvent('success', `Enhanced (preview) — DEI ${data.compliance?.dei_score ?? '—'}, Complete ${data.compliance?.completeness ?? '—'}. Click SAVE to commit.`);
		} catch (e) {
			cliEvent('error', `Enhance failed: ${e.message}`);
		}
		enhancing = false;
	}

	async function duplicateJd(jdId) {
		try {
			const data = await apiJson(`/jds/${jdId}/duplicate`, { method: 'POST' });
			cliEvent('success', 'JD duplicated');
			await loadJds();
		} catch (e) { cliEvent('error', `Duplicate failed: ${e.message}`); }
	}

	async function archiveJd(jdId) {
		try {
			await apiJson(`/jds/${jdId}`, { method: 'DELETE' });
			selectedJd = null;
			cliEvent('success', 'JD archived');
			await loadJds();
		} catch (e) { cliEvent('error', `Archive failed: ${e.message}`); }
	}

	function resetForm() {
		genTitle = ''; genDept = ''; genSeniority = ''; genBullets = ''; pasteJd = '';
		tplJobCode = ''; tplBusinessSector = ''; tplGrading = ''; tplReportingTo = '';
		tplLocation = ''; tplWorkMode = 'onsite'; tplEmploymentType = 'full-time';
		tplJobPurpose = ''; tplPreferredEducation = ''; tplTravel = ''; tplPhysical = '';
		tplDocOwner = '';
		jdTitleTouched = false; jdTextTouched = false;
		genPreview = null;
	}

	function cliEvent(type, text) {
		window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type, text } }));
	}

	const seniorityOptions = ['intern', 'junior', 'mid', 'senior', 'staff', 'principal', 'lead', 'manager', 'director', 'vp'];
	const toneOptions = ['professional', 'friendly', 'technical', 'executive', 'startup'];

	// Preview view mode: 'rendered' (formatted JD) | 'edit' (raw markdown textarea)
	let previewViewMode = $state('rendered');

	// Lightweight Markdown → HTML for JD preview (heading/bold/list/table). XSS-safe (escapes first).
	function renderJdMarkdown(s) {
		if (!s) return '';
		const esc = String(s)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
		// Tables: lines like "| a | b |" — collect consecutive pipe lines into a table
		const lines = esc.split('\n');
		const out = [];
		let i = 0;
		while (i < lines.length) {
			const ln = lines[i];
			const isTable = /^\s*\|.+\|\s*$/.test(ln) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1]);
			if (isTable) {
				const header = ln.split('|').slice(1, -1).map(c => c.trim());
				i += 2; // skip header + divider
				const rows = [];
				while (i < lines.length && /^\s*\|.+\|\s*$/.test(lines[i])) {
					rows.push(lines[i].split('|').slice(1, -1).map(c => c.trim()));
					i++;
				}
				out.push(
					'<table style="border-collapse:collapse;margin:8px 0;font-size:12px;"><thead><tr>' +
					header.map(h => `<th style="border:1.5px solid var(--color-on-surface);padding:4px 8px;background:var(--color-surface-bright);font-weight:900;text-transform:uppercase;letter-spacing:0.04em;text-align:left;">${h}</th>`).join('') +
					'</tr></thead><tbody>' +
					rows.map(r => '<tr>' + r.map(c => `<td style="border:1.5px solid var(--color-on-surface);padding:4px 8px;vertical-align:top;">${c}</td>`).join('') + '</tr>').join('') +
					'</tbody></table>'
				);
				continue;
			}
			out.push(ln);
			i++;
		}
		let html = out.join('\n');
		html = html
			.replace(/^### (.+)$/gm, '<h4 style="font-size:13px;font-weight:900;text-transform:uppercase;letter-spacing:0.05em;margin:14px 0 6px 0;color:var(--color-on-surface);">$1</h4>')
			.replace(/^## (.+)$/gm, '<h3 style="font-size:15px;font-weight:900;text-transform:uppercase;letter-spacing:0.05em;margin:18px 0 8px 0;color:var(--color-primary);border-bottom:2px solid var(--color-on-surface);padding-bottom:4px;">$1</h3>')
			.replace(/^# (.+)$/gm, '<h2 style="font-size:18px;font-weight:900;text-transform:uppercase;letter-spacing:0.04em;margin:20px 0 10px 0;">$1</h2>')
			.replace(/\*\*(.+?)\*\*/g, '<strong style="font-weight:900;color:var(--color-on-surface);">$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			.replace(/^\s*[-*] (.+)$/gm, '<li style="margin-left:18px;list-style:disc;line-height:1.55;">$1</li>')
			.replace(/(<li[^>]*>[\s\S]*?<\/li>\n?)+/g, m => '<ul style="margin:6px 0;padding-left:4px;">' + m + '</ul>');
		// Paragraphs: split on blank lines, skip block-level elements
		html = html.split(/\n{2,}/).map(p => {
			const trimmed = p.trim();
			if (!trimmed) return '';
			if (/^<(h\d|ul|ol|li|table|tr|td|th|thead|tbody)/i.test(trimmed)) return trimmed;
			return `<p style="margin:6px 0;line-height:1.55;">${trimmed.replace(/\n/g, '<br/>')}</p>`;
		}).join('\n');
		return html;
	}

	// ─── Recent + Local Saved Searches (localStorage) ───
	const _RECENT_JD_KEY = 'pulse_recent_jd_searches';
	const _LOCAL_SAVED_JD_KEY = 'pulse_saved_jd_searches';
	function _readLs(key, fallback) {
		if (typeof localStorage === 'undefined') return fallback;
		try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
	}
	function _writeLs(key, val) {
		if (typeof localStorage === 'undefined') return;
		try { localStorage.setItem(key, JSON.stringify(val)); } catch {}
	}
	let recentJdSearches = $state(_readLs(_RECENT_JD_KEY, []));
	let savedJdSearches = $state(_readLs(_LOCAL_SAVED_JD_KEY, []));
	let showJdRecentDropdown = $state(false);
	let jdRecentHighlightIdx = $state(-1);

	function pushRecentJdSearch(q) {
		const term = (q || '').trim();
		if (!term) return;
		const next = [term, ...recentJdSearches.filter(s => s !== term)].slice(0, 5);
		recentJdSearches = next;
		_writeLs(_RECENT_JD_KEY, next);
	}
	function applyRecentJdSearch(term) {
		searchQuery = term;
		showJdRecentDropdown = false;
		jdRecentHighlightIdx = -1;
		pushRecentJdSearch(term);
		loadJds();
	}
	function getCurrentJdFilters() {
		return {
			search: searchQuery || '',
			dept: filterDept || '',
			level: filterLevel || '',
			createdBy: filterCreatedBy || '',
			modifiedBy: filterModifiedBy || '',
			createdRange: filterCreated || 'all',
			modifiedRange: filterModified || 'all',
			railStateFilter,
		};
	}
	function saveJdSearch() {
		const name = (prompt('Name this search:') || '').trim();
		if (!name) return;
		const entry = { id: Date.now(), name, filters: getCurrentJdFilters() };
		const next = [entry, ...savedJdSearches.filter(s => s.name !== name)].slice(0, 20);
		savedJdSearches = next;
		_writeLs(_LOCAL_SAVED_JD_KEY, next);
		cliEvent('success', `Search "${name}" saved`);
	}
	function applySavedJdSearch(entry) {
		const f = entry.filters || {};
		searchQuery = f.search || '';
		filterDept = f.dept || '';
		filterLevel = f.level || '';
		filterCreatedBy = f.createdBy || '';
		filterModifiedBy = f.modifiedBy || '';
		filterCreated = f.createdRange || 'all';
		filterModified = f.modifiedRange || 'all';
		if (f.railStateFilter) railStateFilter = f.railStateFilter;
		persistJdTable();
		loadJds();
	}
	function deleteSavedJdSearch(id, ev) {
		ev?.stopPropagation?.();
		const next = savedJdSearches.filter(s => s.id !== id);
		savedJdSearches = next;
		_writeLs(_LOCAL_SAVED_JD_KEY, next);
	}
	function jdSearchKeydown(e) {
		if (!showJdRecentDropdown || recentJdSearches.length === 0) {
			if (e.key === 'Enter') { pushRecentJdSearch(searchQuery); loadJds(); }
			return;
		}
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			jdRecentHighlightIdx = Math.min(jdRecentHighlightIdx + 1, recentJdSearches.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			jdRecentHighlightIdx = Math.max(jdRecentHighlightIdx - 1, -1);
		} else if (e.key === 'Enter') {
			if (jdRecentHighlightIdx >= 0) {
				e.preventDefault();
				applyRecentJdSearch(recentJdSearches[jdRecentHighlightIdx]);
			} else {
				pushRecentJdSearch(searchQuery); loadJds(); showJdRecentDropdown = false;
			}
		} else if (e.key === 'Escape') {
			showJdRecentDropdown = false; jdRecentHighlightIdx = -1;
		}
	}

	// ─── Bulk selection (JD multi-select) ───
	let jdSelectedIds = $state(new Set());
	let bulkConfirmAction = $state(null); // null | 'delete' | 'archive' | 'share'
	function jdToggleSelected(id, ev) {
		ev?.stopPropagation?.();
		const next = new Set(jdSelectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		jdSelectedIds = next;
	}
	function jdSelectAllVisible(checked) {
		if (checked) jdSelectedIds = new Set(jds.map(j => j.id));
		else jdSelectedIds = new Set();
	}
	function jdClearSelection() { jdSelectedIds = new Set(); }
	async function jdBulkArchive() {
		const ids = [...jdSelectedIds];
		try {
			await Promise.all(ids.map(id => apiJson(`/jds/${id}/archive`, { method: 'POST' }).catch(() => null)));
			cliEvent('success', `Archived ${ids.length} JDs`);
			jdClearSelection();
			await loadJds();
		} catch (e) { cliEvent('error', `Archive failed: ${e.message}`); }
	}
	async function jdBulkDelete() {
		const ids = [...jdSelectedIds];
		if (!ids.length) return;
		// Optimistic remove
		jds = jds.filter(j => !jdSelectedIds.has(j.id));
		try {
			const r = await apiJson('/bulk/delete-jds', {
				method: 'POST',
				body: JSON.stringify({ jd_ids: ids }),
			});
			cliEvent('success', `Deleted ${r.deleted ?? ids.length} JD(s)`);
			bulkConfirmAction = null;
			jdClearSelection();
			await loadJds();
		} catch (e) {
			cliEvent('error', `Delete failed: ${e.message}`);
			await loadJds();
		}
	}
	async function jdBulkShare() {
		const ids = [...jdSelectedIds];
		try {
			await Promise.all(ids.map(id => apiJson(`/jds/${id}`, {
				method: 'PATCH', body: JSON.stringify({ shared_global: true })
			}).catch(() => null)));
			cliEvent('success', `Shared ${ids.length} JDs globally`);
			jdClearSelection();
			await loadJds();
		} catch (e) { cliEvent('error', `Share failed: ${e.message}`); }
	}
</script>

<div class="jd-page-wrap">

<div class="jd-split">
<aside class="jd-rail">
	<JdRailFilters
		bind:scope
		scopeCounts={counts}
		onScopeChange={(s) => setScope(s)}
		bind:stateFilter={railStateFilter}
		{stateCounts}
		{facetGroups}
		bind:jdSkillSelected
		bind:jdDeptSelected
		bind:jdLocationSelected
		bind:jdEmploymentTypeSelected
		bind:jdSenioritySelected
		onDismissFacetNew={dismissFacetNew}
		onClearAll={clearAllRailFilters}
	/>
</aside>

<main class="jd-main">
<div style="max-width: 1800px; margin: 0 auto;">
	<!-- Header -->
	<div class="flex items-center justify-between mb-6 section-animate">
		<div>
			<h1 class="jd-page-title">JD library</h1>
			<p class="jd-page-subtitle">
				{jds.length} job description{jds.length !== 1 ? 's' : ''} · create with AI or paste
			</p>
		</div>
		<div class="flex gap-2">
			<button class="jd-btn jd-btn-primary" onclick={() => { modalMode = 'generate'; showModal = true; }}>
				<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">auto_awesome</span>
				Generate with AI
			</button>
			<button class="jd-btn jd-btn-outline" onclick={() => { showPasteModal = true; }}>Paste JD</button>
			<button class="jd-btn jd-btn-outline" onclick={() => document.getElementById('jd-upload-input').click()}>Upload</button>
			<button class="jd-btn jd-btn-outline" onclick={() => { window.location.href = '/api/jds/export.csv'; }} title="Export JDs as CSV">Export CSV</button>
			<input id="jd-upload-input" type="file" multiple accept=".pdf,.docx,.doc,.txt,.md" style="display:none;"
				onchange={(e) => { if (e.target.files?.length) uploadJdFiles(e.target.files, true); e.target.value = ''; }} />
		</div>
	</div>

	<!-- Search -->
	<div class="flex gap-2 mb-2" style="align-items: center;">
		<div style="position: relative; flex: 1; display: flex;">
			<input type="text" bind:value={searchQuery}
				onfocus={() => { showJdRecentDropdown = true; jdRecentHighlightIdx = -1; }}
				onblur={() => { setTimeout(() => { showJdRecentDropdown = false; }, 150); }}
				onkeydown={jdSearchKeydown}
				placeholder="Search by title, skills, department…"
				class="jd-search-input" style="flex: 1; width: 100%;" />
			{#if showJdRecentDropdown && recentJdSearches.length > 0}
				<div class="jd-recent-dropdown">
					<div class="jd-recent-head">Recent searches</div>
					{#each recentJdSearches as term, i}
						<button type="button" class="jd-recent-item" class:active={jdRecentHighlightIdx === i}
							onmousedown={(e) => { e.preventDefault(); applyRecentJdSearch(term); }}
							onmouseenter={() => jdRecentHighlightIdx = i}>
							<span class="material-symbols-outlined" style="font-size: 14px; opacity: 0.55;">history</span>
							<span style="flex: 1; text-align: left;">{term}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>
		<button class="jd-btn jd-btn-outline" onclick={() => { pushRecentJdSearch(searchQuery); loadJds(); }}>Search</button>
		<button class="jd-btn jd-btn-outline" onclick={saveJdSearch} title="Save current search">Save search</button>
	</div>

	{#if savedJdSearches.length > 0}
		<div class="jd-saved-pill-row">
			<span class="jd-saved-pill-label">Saved:</span>
			{#each savedJdSearches as ss (ss.id)}
				<button class="jd-saved-pill" onclick={() => applySavedJdSearch(ss)} title="Apply saved search">
					<span>{ss.name}</span>
					<span class="jd-saved-pill-x" onclick={(e) => deleteSavedJdSearch(ss.id, e)} title="Remove">×</span>
				</button>
			{/each}
		</div>
	{/if}

	<!-- JD List -->
	{#if loading}
		<div class="jd-table-wrap">
			<table class="jd-data-table">
				<tbody>
					<SkeletonRow count={8} />
				</tbody>
			</table>
		</div>
	{:else if jds.length === 0}
		<EmptyState
			icon={FileText}
			title="No job descriptions"
			description="Generate one with AI or paste an existing JD to get started."
			actionLabel="Generate with AI"
			onAction={() => { modalMode = 'generate'; showModal = true; }}
		/>
	{:else}
		<div class="jd-table-wrap" bind:this={jdTableRoot} onkeydown={onJdTableKey} role="grid" tabindex="-1">
		<table class="jd-data-table">
			<thead>
				<tr class="jd-th-labels">
					<th style="width: 36px; padding-left: 8px;">
						<input type="checkbox"
							checked={jds.length > 0 && jdSelectedIds.size === jds.length}
							onchange={(e) => jdSelectAllVisible(e.target.checked)}
							onclick={(e) => e.stopPropagation()} />
					</th>
					<th onclick={() => sortHeaderClick('title')} style="cursor:pointer; min-width: 220px;">Title {sortIcon('title')}</th>
					<th onclick={() => sortHeaderClick('department')} style="cursor:pointer;">Dept {sortIcon('department')}</th>
					<th onclick={() => sortHeaderClick('seniority_level')} style="cursor:pointer;">Level {sortIcon('seniority_level')}</th>
					<th>Skills</th>
					<th>Scope</th>
					<th>Created by</th>
					<th onclick={() => sortHeaderClick('created_at')} style="cursor:pointer;">Created {sortIcon('created_at')}</th>
					<th>Modified by</th>
					<th onclick={() => sortHeaderClick('updated_at')} style="cursor:pointer;">Modified {sortIcon('updated_at')}</th>
					<th>Expires</th>
					<th>Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each jds as jd, i}
					<tr class="jd-row" class:jd-row-focus={focusedRowIdx === i} class:jd-row-selected={jdSelectedIds.has(jd.id)}
						data-row-idx={i} tabindex="0"
						onfocus={() => focusedRowIdx = i}
						onclick={() => goto(`/jds/${jd.id}`)}>
						<td onclick={(e) => e.stopPropagation()} style="padding-left: 8px;">
							<input type="checkbox" checked={jdSelectedIds.has(jd.id)}
								onchange={(e) => jdToggleSelected(jd.id, e)} />
						</td>
						<td>
							<a href="/jds/{jd.id}" class="jd-title-link">{jd.title}</a>
							{#if jd.jd_enhanced}<span class="jd-enhanced-pill">Enhanced</span>{/if}
						</td>
						<td>{jd.department || '—'}</td>
						<td style="text-transform: capitalize;">{jd.seniority_level || '—'}</td>
						<td>{(jd.required_skills || []).length}</td>
						<td>
							<span class="vis-badge vis-{jd.visibility || 'private'}">
								{jd.visibility === 'global' ? 'Global' : jd.visibility === 'sector' ? 'Sector' : 'Mine'}
							</span>
						</td>
						<td>{jd.created_by_name || `#${jd.created_by ?? '—'}`}</td>
						<td class="ts-cell">
							<div class="ts-abs">{fmtAbs(jd.created_at)}</div>
							<div class="ts-rel">{timeAgo(jd.created_at)}</div>
						</td>
						<td>{jd.updated_by_name || `#${jd.updated_by ?? '—'}`}</td>
						<td class="ts-cell">
							<div class="ts-abs">{fmtAbs(jd.updated_at)}</div>
							<div class="ts-rel">{timeAgo(jd.updated_at)}</div>
						</td>
						<td>
							{#if jd.expires_at}
								{#if jd.is_expired}
									<span class="exp-chip exp-chip-red" title={`Expired ${fmtAbs(jd.expires_at)}`}>Expired</span>
								{:else if jd.days_until_expiry != null && jd.days_until_expiry < 14}
									<span class="exp-chip exp-chip-amber" title={`Expires ${fmtAbs(jd.expires_at)}`}>{jd.days_until_expiry}d</span>
								{:else}
									<span class="exp-chip exp-chip-neutral" title={`Expires ${fmtAbs(jd.expires_at)}`}>{jd.days_until_expiry}d</span>
								{/if}
							{:else}
								<span style="font-size: 11px; color: var(--color-on-surface-dim);">—</span>
							{/if}
						</td>
						<td onclick={(e) => e.stopPropagation()}>
							<button class="row-action" onclick={(e) => toggleShare(jd.id, e)}>Share</button>
							<button class="row-action row-action-danger" title="Permanently delete this JD" onclick={(e) => askDelete(jd, e)}>Delete</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		</div>

		<!-- Pagination -->
		<Pagination total={jdTotal} limit={jdLimit} offset={jdOffset} onPageChange={onJdPageChange} />
	{/if}
</div>
</main>
</div><!-- /.jd-split -->

<!-- Status bar (sticky bottom) -->
<div class="jd-status-bar">
	<span class="sb-section">{jdTotal} JD{jdTotal === 1 ? '' : 's'}</span>
	<span class="sb-sep">·</span>
	<span class="sb-section">{stateCounts.active} active</span>
	{#if facetNewTotal > 0}
		<span class="sb-sep">·</span>
		<span class="sb-section sb-accent">AI added {facetNewTotal} new today</span>
	{/if}
</div>

<!-- ═══ HARD-DELETE CONFIRM MODAL ═══ -->
{#if deleteTarget}
	{@const _jt = (deleteTarget?.title || '').trim().toLowerCase()}
	{@const _jv = deleteConfirmText.trim().toLowerCase()}
	{@const _jok = _jv.length > 0 && (_jv === _jt || _jv === 'delete')}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 200; display: flex; align-items: center; justify-content: center; padding: 20px;"
		onclick={(e) => { if (e.target === e.currentTarget && !deleting) { deleteTarget = null; deleteConfirmText = ''; } }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 520px; max-width: 95vw;">
			<div class="dark-title-bar" style="background: var(--color-error); color: white; padding: 8px 14px; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em;">
				⚠ PERMANENT DELETE — JOB DESCRIPTION
			</div>
			<div class="p-5" style="display: flex; flex-direction: column; gap: 14px;">
				<p style="font-size: 13px; line-height: 1.5;">
					You are about to <strong style="color: var(--color-error);">permanently delete</strong> the JD:
				</p>
				<div style="border: 2px solid var(--color-on-surface); padding: 10px 14px; background: var(--color-surface-bright); font-size: 13px; font-weight: 900;">
					{deleteTarget.title}
				</div>
				<p style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.5;">
					⚠ This cannot be undone. Embeddings, facets, position links — all removed. Only the JD creator or a superadmin may proceed.
				</p>
				<div>
					<label class="tag-label mb-1" style="display: block;">Type JD title <strong style="color: var(--color-error);">{deleteTarget?.title}</strong> or word DELETE to confirm</label>
					<input type="text" bind:value={deleteConfirmText}
						placeholder={deleteTarget?.title || 'DELETE'}
						style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-error); font-family: 'Space Grotesk'; font-size: 14px; font-weight: 700; letter-spacing: 0.1em; background: var(--color-surface-bright);" />
				</div>
				<div class="flex gap-2 justify-end pt-2">
					<button class="btn-secondary" disabled={deleting} onclick={() => { deleteTarget = null; deleteConfirmText = ''; }}>Cancel</button>
					<button onclick={confirmDelete} disabled={deleting || !_jok}
						style="background: var(--color-error); color: white; border: 2px solid var(--color-on-surface); padding: 8px 18px; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; cursor: {deleting ? 'wait' : 'pointer'}; opacity: {_jok ? 1 : 0.4};">
						{#if deleting}DELETING…{:else}<Trash2 size={14} /> PERMANENTLY DELETE{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- ═══ PASTE JD MODAL — paste raw text, AI enhances & extracts ═══ -->
{#if showPasteModal}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px;"
		onclick={(e) => { if (e.target === e.currentTarget && !pasteAiEnhancing) { showPasteModal = false; pasteAiResult = null; } }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 720px; max-width: 95vw; max-height: 90vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span><ClipboardList size={14} /> Paste JD — AI will enhance & extract</span>
				<button onclick={() => { showPasteModal = false; pasteAiResult = null; }} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">✕</button>
			</div>

			<div class="p-5" style="display: flex; flex-direction: column; gap: 14px;">
				{#if pasteAiResult}
					<!-- After AI enhance — preview pane -->
					<div style="background: var(--color-primary-container); border: 2px solid var(--color-on-surface); padding: 8px 12px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em;">
						✓ AI-enhanced · review below and click SAVE to add to JD pool
					</div>
					<div>
						<div class="flex items-center justify-between mb-1">
							<label class="tag-label" style="display:block;">Enhanced Job Description</label>
							<div class="flex gap-1">
								<button type="button" onclick={() => pasteViewMode = 'rendered'}
									style="font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:0.05em;padding:3px 10px;border:2px solid var(--color-on-surface);cursor:pointer;background:{pasteViewMode==='rendered'?'var(--color-on-surface)':'var(--color-surface-bright)'};color:{pasteViewMode==='rendered'?'var(--color-primary-container)':'var(--color-on-surface)'};"><Eye size={11} /> Rendered</button>
								<button type="button" onclick={() => pasteViewMode = 'edit'}
									style="font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:0.05em;padding:3px 10px;border:2px solid var(--color-on-surface);cursor:pointer;background:{pasteViewMode==='edit'?'var(--color-on-surface)':'var(--color-surface-bright)'};color:{pasteViewMode==='edit'?'var(--color-primary-container)':'var(--color-on-surface)'};">✎ Edit</button>
							</div>
						</div>
						{#if pasteViewMode === 'rendered'}
							<div style="border:2px solid var(--color-on-surface); background:var(--color-surface-bright); padding:14px 18px; max-height:420px; overflow-y:auto; font-family:'Space Grotesk'; font-size:12px; color:var(--color-on-surface);">
								{@html renderJdMarkdown(pasteAiResult.jd_text)}
							</div>
						{:else}
							<textarea bind:value={pasteAiResult.jd_text} rows="16"
								style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright); resize: vertical; line-height: 1.5;"></textarea>
						{/if}
					</div>
					{#if pasteAiResult.extracted}
						<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px;">
							<div><strong>Skills:</strong> {(pasteAiResult.extracted.required_skills || []).slice(0,10).join(', ') || '—'}</div>
							<div><strong>Min Years:</strong> {pasteAiResult.extracted.min_experience_years || 0}</div>
							<div><strong>Education:</strong> {pasteAiResult.extracted.education_level || '—'}</div>
							<div><strong>Profile:</strong> {pasteAiResult.scoring_profile || '—'}</div>
						</div>
					{/if}
					<div class="flex gap-2 justify-end pt-2">
						<button class="btn-secondary" disabled={pasteAiEnhancing} onclick={() => { pasteAiResult = null; }}>← Back / Re-enhance</button>
						<button class="btn-secondary" disabled={pasteAiEnhancing} onclick={() => { showPasteModal = false; pasteAiResult = null; resetForm(); }}>Cancel</button>
						<button class="send-btn" onclick={savePasteEnhanced} disabled={pasteAiEnhancing}>
							{pasteAiEnhancing ? 'Saving...' : '✓ Save to JD Pool'}
						</button>
					</div>
				{:else}
					<!-- Initial paste form -->
					<div>
						<label class="tag-label mb-1" style="display: block;">Position Title *</label>
						<input bind:value={genTitle} placeholder="e.g. Senior Backend Engineer"
							onfocus={() => jdTitleTouched = true}
							onblur={() => jdTitleTouched = true}
							style="width: 100%; padding: 10px 14px; border: 2px solid {jdTitleError ? 'var(--color-error)' : 'var(--color-on-surface)'}; font-family: 'Space Grotesk'; font-size: 14px; background: var(--color-surface-bright);" />
						{#if jdTitleError}
							<p style="font-size: 10px; color: var(--color-error); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px;">{jdTitleError}</p>
						{/if}
					</div>
					<div>
						<label class="tag-label mb-1" style="display: block;">Paste Full JD Text *</label>
						<textarea bind:value={pasteJd} rows="14"
							onfocus={() => jdTextTouched = true}
							onblur={() => jdTextTouched = true}
							placeholder="Paste the complete job description here. AI will extract skills, experience, education, certifications, and enhance the text for clarity, inclusivity, and structure..."
							style="width: 100%; padding: 12px 14px; border: 2px solid {pasteJd.trim().length > 0 && pasteJd.trim().length < 50 ? 'var(--color-error)' : 'var(--color-on-surface)'}; font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright); resize: vertical; line-height: 1.5;"></textarea>
						<div class="flex items-center justify-between" style="margin-top: 4px;">
							<p style="font-size: 10px; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.04em;">
								AI auto-extracts skills, experience, certifications · auto-enhances structure & language
							</p>
							<span style="font-size: 10px; font-weight: 700; color: {pasteJd.trim().length >= 50 ? 'var(--color-primary)' : 'var(--color-on-surface-dim)'}; text-transform: uppercase; letter-spacing: 0.05em;">
								{pasteJd.trim().length} chars
							</span>
						</div>
					</div>
					<div class="flex gap-2 justify-end pt-2">
						<button class="btn-secondary" disabled={pasteAiEnhancing} onclick={() => { showPasteModal = false; resetForm(); }}>Cancel</button>
						<button class="btn-secondary" disabled={pasteAiEnhancing || !genTitle.trim() || pasteJd.trim().length < 50} onclick={savePasteRaw}>
							{pasteAiEnhancing ? 'Saving...' : 'Save As-Is'}
						</button>
						<button class="send-btn" disabled={pasteAiEnhancing || !genTitle.trim() || pasteJd.trim().length < 50} onclick={runPasteEnhance}>
							{pasteAiEnhancing ? '✨ Enhancing...' : '✨ AI Enhance & Save'}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

</div><!-- /.jd-page-wrap -->

<!-- ═══ CREATE/GENERATE MODAL ═══ -->
{#if showModal}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px;"
		onclick={(e) => { if (e.target === e.currentTarget) showModal = false; }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 640px; max-height: 90vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span>✨ Generate JD with AI</span>
				<button onclick={() => showModal = false} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">✕</button>
			</div>

			<div class="p-5" style="display: flex; flex-direction: column; gap: 14px;">
				{#if genPreview}
					<!-- Preview pane — generated JD pending user SAVE -->
					<div style="display:flex; flex-direction:column; gap:10px;">
						<div style="background: var(--color-primary-container); border: 2px solid var(--color-on-surface); padding: 8px 12px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em;">
							✓ AI-generated · review below and click SAVE to add to JD pool
						</div>
						<div>
							<div class="flex items-center justify-between mb-1">
								<label class="tag-label" style="display:block;">Generated Job Description</label>
								<div class="flex gap-1">
									<button type="button" onclick={() => previewViewMode = 'rendered'}
										style="font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:0.05em;padding:3px 10px;border:2px solid var(--color-on-surface);cursor:pointer;background:{previewViewMode==='rendered'?'var(--color-on-surface)':'var(--color-surface-bright)'};color:{previewViewMode==='rendered'?'var(--color-primary-container)':'var(--color-on-surface)'};"><Eye size={11} /> Rendered</button>
									<button type="button" onclick={() => previewViewMode = 'edit'}
										style="font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:0.05em;padding:3px 10px;border:2px solid var(--color-on-surface);cursor:pointer;background:{previewViewMode==='edit'?'var(--color-on-surface)':'var(--color-surface-bright)'};color:{previewViewMode==='edit'?'var(--color-primary-container)':'var(--color-on-surface)'};">✎ Edit Markdown</button>
								</div>
							</div>
							{#if previewViewMode === 'rendered'}
								<div style="border:2px solid var(--color-on-surface); background:var(--color-surface-bright); padding:14px 18px; max-height:480px; overflow-y:auto; font-family:'Space Grotesk'; font-size:12px; color:var(--color-on-surface);">
									{@html renderJdMarkdown(genPreview.jd_text)}
								</div>
							{:else}
								<textarea bind:value={genPreview.jd_text} rows="20"
									style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; background: var(--color-surface-bright); resize: vertical; line-height: 1.5;"></textarea>
							{/if}
							<p style="font-size: 10px; color: var(--color-on-surface-dim); margin-top: 4px; text-transform: uppercase;">
								{genPreview.jd_text.length} chars · toggle ✎ Edit Markdown to tweak
							</p>
						</div>
						{#if genPreview.extracted}
							<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px;">
								<div><strong>Skills:</strong> {(genPreview.extracted.required_skills || []).join(', ') || '—'}</div>
								<div><strong>Min Years:</strong> {genPreview.extracted.min_experience_years || 0}</div>
								<div><strong>Education:</strong> {genPreview.extracted.education_level || '—'}</div>
								<div><strong>Profile:</strong> {genPreview.scoring_profile || '—'}</div>
							</div>
						{/if}
						<div class="flex gap-2 justify-end pt-2">
							<button class="btn-secondary" onclick={discardPreview} disabled={savingPreview}>← Back / Regenerate</button>
							<button class="btn-secondary" onclick={() => { showModal = false; resetForm(); }} disabled={savingPreview}>Cancel</button>
							<button class="send-btn" onclick={savePreview} disabled={savingPreview}>
								{savingPreview ? 'Saving...' : '✓ Save to JD Pool'}
							</button>
						</div>
					</div>
				{:else}
				<!-- Common fields -->
				<div>
					<label class="tag-label mb-1" style="display: block;">Position Title *</label>
					<input bind:value={genTitle} placeholder="e.g. Senior Backend Engineer"
						onfocus={() => jdTitleTouched = true}
						onblur={() => jdTitleTouched = true}
						style="width: 100%; padding: 10px 14px; border: 2px solid {jdTitleError ? 'var(--color-error)' : 'var(--color-on-surface)'}; font-family: 'Space Grotesk'; font-size: 14px; background: var(--color-surface-bright);" />
					{#if jdTitleError}
						<p style="font-size: 10px; color: var(--color-error); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px;">{jdTitleError}</p>
					{/if}
				</div>
				<div class="flex gap-3">
					<div class="flex-1">
						<label class="tag-label mb-1" style="display: block;">Department</label>
						<input bind:value={genDept} placeholder="Engineering"
							style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright);" />
					</div>
					<div class="flex-1">
						<label class="tag-label mb-1" style="display: block;">Seniority</label>
						<select bind:value={genSeniority}
							style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright);">
							<option value="">Select level</option>
							{#each seniorityOptions as s}
								<option value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
							{/each}
						</select>
					</div>
				</div>

				<!-- ═══ I. ROLE INFORMATION (corporate template) ═══ -->
				<details open style="border: 2px solid var(--color-on-surface); padding: 10px;">
					<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">I. Role Information</summary>
					<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
						<div>
							<label class="tag-label mb-1" style="display: block;">Job Code/ID</label>
							<input bind:value={tplJobCode} placeholder="ENG-SE-001" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Business Sector/Entity</label>
							<input bind:value={tplBusinessSector} placeholder="Technology" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Grading/Ranking</label>
							<input bind:value={tplGrading} placeholder="L5 / Band 4" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Reporting To</label>
							<input bind:value={tplReportingTo} placeholder="VP Engineering" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Location</label>
							<input bind:value={tplLocation} placeholder="Dubai, UAE" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Work Mode</label>
							<select bind:value={tplWorkMode} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
								<option value="onsite">Onsite</option>
								<option value="hybrid">Hybrid</option>
								<option value="remote">Remote</option>
							</select>
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Employment Type</label>
							<select bind:value={tplEmploymentType} style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;">
								<option value="full-time">Full-time</option>
								<option value="part-time">Part-time</option>
								<option value="contract">Contract</option>
								<option value="intern">Intern</option>
								<option value="consultant">Consultant</option>
							</select>
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Document Owner</label>
							<input bind:value={tplDocOwner} placeholder="HR Department" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
					</div>
				</details>

				<!-- ═══ V. WORKING CONDITIONS ═══ -->
				<details style="border: 2px solid var(--color-on-surface); padding: 10px;">
					<summary style="cursor: pointer; font-weight: 900; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;">V. Working Conditions</summary>
					<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
						<div>
							<label class="tag-label mb-1" style="display: block;">Travel Requirement</label>
							<input bind:value={tplTravel} placeholder="<10% / Up to 25%" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
						<div>
							<label class="tag-label mb-1" style="display: block;">Physical/Specific Conditions</label>
							<input bind:value={tplPhysical} placeholder="Standard office / On-call rotation" style="width:100%;padding:8px;border:2px solid var(--color-on-surface);background:var(--color-surface-bright);font-size:12px;" />
						</div>
					</div>
				</details>

				<!-- AI Generation only -->
				<div>
					<label class="tag-label mb-1" style="display: block;">Key Requirements (one per line)</label>
					<textarea bind:value={genBullets} rows="5"
						placeholder="Build distributed payment systems&#10;Go and Kubernetes required&#10;5+ years experience&#10;AWS or GCP cloud experience&#10;Strong system design skills"
						style="width: 100%; padding: 10px 14px; border: 2px solid {bulletsWarning ? 'var(--color-warning)' : 'var(--color-on-surface)'}; font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright); resize: vertical;"></textarea>
					{#if bulletsWarning}
						<p style="font-size: 10px; color: var(--color-warning); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px;">{bulletsWarning}</p>
					{:else}
						<p style="font-size: 9px; color: var(--color-on-surface-dim); margin-top: 4px; text-transform: uppercase;">
							Leave empty to auto-generate based on title · More bullets = more specific JD
						</p>
					{/if}
				</div>
				<div>
					<label class="tag-label mb-1" style="display: block;">Tone</label>
					<div class="flex gap-2 flex-wrap">
						{#each toneOptions as t}
							<button style="padding: 4px 12px; font-size: 10px; font-weight: 700; text-transform: uppercase; border: 2px solid var(--color-on-surface); cursor: pointer;
								background: {genTone === t ? 'var(--color-on-surface)' : 'var(--color-surface-bright)'}; color: {genTone === t ? 'var(--color-primary-container)' : 'var(--color-on-surface)'};"
								onclick={() => genTone = t}>{t}</button>
						{/each}
					</div>
				</div>
				<div class="flex gap-2 justify-end pt-2">
					<button class="btn-secondary" onclick={() => { showModal = false; resetForm(); }}>Cancel</button>
					<button class="send-btn" onclick={generateJd} disabled={!jdTitleValid || generating}>
						{generating ? 'Generating...' : 'Generate JD'}
					</button>
				</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- ═══ JD DETAIL MODAL ═══ -->
{#if selectedJd && draft}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: stretch; justify-content: center; padding: 24px;"
		onclick={(e) => { if (e.target === e.currentTarget) { if (!dirty || confirm('Unsaved changes will be lost. Close anyway?')) selectedJd = null; } }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 95vw; max-width: 1400px; height: 90vh; display:flex; flex-direction:column; overflow:hidden;">
			<!-- Header -->
			<div class="dark-title-bar flex items-center justify-between" style="flex-shrink:0;">
				<div class="flex items-center gap-3">
					<span class="material-symbols-outlined" style="font-size: 18px;">description</span>
					<span style="font-size: 13px;">{draft.title || selectedJd.title}{dirty ? ' · UNSAVED' : ''}</span>
				</div>
				<div class="flex items-center gap-2">
					<button onclick={() => enhanceJd(selectedJd.id)} disabled={enhancing}
						style="background:var(--color-surface-bright, #fff); color:var(--color-on-surface, #2c2c2c); border:1px solid var(--color-border, #d8d5cc); border-radius:6px; padding: 4px 12px; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
						{enhancing ? 'ENHANCING…' : '✨ AI Enhance'}
					</button>
					<button onclick={saveDraft} disabled={savingDraft || !dirty}
						style="background:{dirty ? 'var(--color-accent, #c96342)' : '#999'}; color:#fff; border:none; border-radius:6px; padding: 4px 14px; font-size: 11px; font-weight: 900; cursor:{dirty ? 'pointer' : 'not-allowed'}; text-transform: uppercase;">
						{savingDraft ? 'SAVING…' : (dirty ? '✓ SAVE' : '✓ SAVED')}
					</button>
					<a href={`/api/jds/${selectedJd.id}/export.xlsx`} download
						style="background: var(--color-surface-bright); color: var(--color-on-surface); border: 1px solid var(--color-on-surface); padding: 4px 10px; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase; text-decoration: none;">
						⬇ XLSX
					</a>
					<button onclick={() => { if (!dirty || confirm('Unsaved changes will be lost. Close anyway?')) selectedJd = null; }} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 18px; line-height: 1;">✕</button>
				</div>
			</div>

			<div style="flex:1; display:grid; grid-template-columns: 1fr 6px 1fr; min-height:0;">
				<!-- LEFT: source file viewer -->
				<div style="overflow:auto; background:var(--color-bg, #faf9f5); border-right:1px solid var(--color-border, #d8d5cc);">
					{#if selectedJd.source_file_path}
						{#if (selectedJd.source_file_type || '').toLowerCase() === 'pdf'}
							<iframe src={`/api/jds/${selectedJd.id}/file?t=${getToken()}`} title="JD source"
								style="width:100%; height:100%; border:0; background:var(--color-bg, #faf9f5);"></iframe>
						{:else if ['docx','doc'].includes((selectedJd.source_file_type || '').toLowerCase())}
							<div style="height:100%; display:flex; flex-direction:column;">
								<div style="padding:10px 16px; background:var(--color-on-surface, #2c2c2c); color:var(--color-surface-bright, #fff); display:flex; align-items:center; justify-content:space-between; gap:10px; flex-shrink:0;">
									<span style="font-size:11px; font-weight:900; text-transform:uppercase; letter-spacing:0.06em; display:inline-flex; align-items:center; gap:6px;"><FileText size={12} /> {selectedJd.source_file_name || 'source.docx'}</span>
									<a href={`/api/jds/${selectedJd.id}/file?t=${getToken()}`} target="_blank" rel="noopener"
										style="background:var(--color-accent, #c96342); color:#fff; padding:3px 10px; font-weight:900; text-transform:uppercase; font-size:10px; text-decoration:none; border-radius:4px;">↗ OPEN</a>
								</div>
								<div style="flex:1; overflow:auto; padding:24px 32px; background:#fff;">
									{#if docxLoading}
										<div style="text-align:center; padding:40px; color:#6b6b60; font-size:12px;">Rendering document…</div>
									{:else}
										<div class="docx-render">{@html docxHtml}</div>
									{/if}
								</div>
							</div>
						{:else}
							<div style="padding:20px; font-size:12px;">
								<div style="margin-bottom:12px; font-weight:900; text-transform:uppercase; letter-spacing:0.06em; display:inline-flex; align-items:center; gap:6px;"><FileText size={14} /> {selectedJd.source_file_name || 'source'}</div>
								<a href={`/api/jds/${selectedJd.id}/file?t=${getToken()}`} target="_blank" rel="noopener"
									style="display:inline-block; background:var(--color-accent, #c96342); color:#fff; padding:6px 14px; font-weight:900; text-transform:uppercase; font-size:11px; text-decoration:none; border-radius:6px; margin-bottom:14px;">↗ OPEN IN TAB</a>
							</div>
						{/if}
					{:else}
						<div style="padding:40px; text-align:center;">
							<div style="margin-bottom:12px;"><FileText size={36} /></div>
							<div style="font-size:13px; font-weight:900; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:10px;">No source file</div>
							<div style="font-size:11px; color:#6b6b60; margin-bottom:18px;">Attach the original .pdf / .docx / .txt for reference</div>
							<button onclick={() => document.getElementById('jd-replace-input').click()} disabled={replacing}
								style="background:var(--color-accent, #c96342); color:#fff; padding:8px 18px; border:none; border-radius:6px; font-weight:900; text-transform:uppercase; font-size:11px; cursor:pointer;">
								{replacing ? 'UPLOADING…' : '⬆ ATTACH FILE'}
							</button>
							<input id="jd-replace-input" type="file" accept=".pdf,.docx,.doc,.txt,.md" style="display:none;"
								onchange={(e) => { if (e.target.files?.[0]) replaceJdFromFile(selectedJd.id, e.target.files[0]); e.target.value=''; }} />
						</div>
					{/if}
				</div>

				<!-- DIVIDER -->
				<div style="background:var(--color-border, #d8d5cc);"></div>

				<!-- RIGHT: details + edit -->
				<div style="overflow-y:auto; padding:18px;">
				<!-- ── Meta Info Grid ── -->
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
					<div class="ink-border p-3" style="background: var(--color-surface-bright);">
						<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">Department</div>
						<div style="font-size: 14px; font-weight: 900; margin-top: 2px;">{draft.department || '—'}</div>
					</div>
					<div class="ink-border p-3" style="background: var(--color-surface-bright);">
						<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">Seniority</div>
						<div style="font-size: 14px; font-weight: 900; margin-top: 2px; text-transform: capitalize;">{draft.seniority_level || '—'}</div>
					</div>
					<div class="ink-border p-3" style="background: var(--color-surface-bright);">
						<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">Type</div>
						<div style="font-size: 14px; font-weight: 900; margin-top: 2px;">{draft.employment_type || 'Full-time'}</div>
					</div>
					<div class="ink-border p-3" style="background: var(--color-surface-bright);">
						<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">Min Experience</div>
						<div style="font-size: 14px; font-weight: 900; margin-top: 2px;">{draft.min_experience_years || 0} years</div>
					</div>
				</div>

				<!-- ── Status badges ── -->
				<div class="flex gap-2 mb-5 flex-wrap items-center">
					{#if selectedJd.jd_enhanced}
						<span style="padding: 2px 8px; background: var(--color-primary); color: white; font-weight: 700; font-size: 10px; text-transform: uppercase;">AI Enhanced</span>
					{/if}
					<span style="padding: 2px 8px; border: 1px solid var(--color-outline); font-size: 10px; font-weight: 700; text-transform: uppercase;">{selectedJd.status}</span>
					{#if selectedJd.used_count > 0}
						<span style="padding: 2px 8px; border: 1px solid var(--color-secondary); color: var(--color-secondary); font-size: 10px; font-weight: 700;">Used {selectedJd.used_count}x</span>
					{/if}
					{#if selectedJd.education_level}
						<span style="padding: 2px 8px; border: 1px solid var(--color-outline); font-size: 10px; font-weight: 700; text-transform: uppercase;">Edu: {selectedJd.education_level}</span>
					{/if}
				</div>

				<!-- ── Compliance Scores ── -->
				{#if draft.dei_score || draft.completeness_score || selectedJd.legal_check}
					<div class="mb-5">
						<span class="tag-label mb-3" style="display: block;">Compliance Report</span>
						<div class="grid grid-cols-3 gap-3">
							<div class="ink-border p-3 text-center" style="background: var(--color-surface-bright);">
								<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">DEI Score</div>
								<div style="font-size: 24px; font-weight: 900; color: {(draft.dei_score || 0) >= 80 ? 'var(--color-primary)' : (draft.dei_score || 0) >= 50 ? 'var(--color-warning)' : 'var(--color-error)'};">
									{draft.dei_score ?? '—'}
								</div>
							</div>
							<div class="ink-border p-3 text-center" style="background: var(--color-surface-bright);">
								<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">Legal Check</div>
								<div style="font-size: 18px; font-weight: 900;">
									{selectedJd.legal_check?.pass === true ? '✓ PASS' : selectedJd.legal_check?.pass === false ? '✗ FAIL' : '—'}
								</div>
							</div>
							<div class="ink-border p-3 text-center" style="background: var(--color-surface-bright);">
								<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">Completeness</div>
								<div style="font-size: 24px; font-weight: 900;">
									{draft.completeness_score ?? '—'}<span style="font-size: 12px;">%</span>
								</div>
							</div>
						</div>
					</div>
				{/if}

				<!-- ── Required Skills ── -->
				{#if draft.required_skills?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Required Skills ({draft.required_skills.length})</span>
						<div class="flex gap-1 flex-wrap">
							{#each draft.required_skills as skill}
								<span style="font-size: 11px; padding: 3px 10px; border: 2px solid var(--color-primary); color: var(--color-primary); font-weight: 700; text-transform: uppercase;">{skill}</span>
							{/each}
						</div>
					</div>
				{/if}

				<!-- ── Nice to Have ── -->
				{#if draft.nice_to_have_skills?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Nice to Have ({draft.nice_to_have_skills.length})</span>
						<div class="flex gap-1 flex-wrap">
							{#each draft.nice_to_have_skills as skill}
								<span style="font-size: 11px; padding: 3px 10px; border: 1px dashed var(--color-outline); color: var(--color-on-surface-dim); font-weight: 700; text-transform: uppercase;">{skill}</span>
							{/each}
						</div>
					</div>
				{/if}

				<!-- ── Industry Keywords ── -->
				{#if draft.industry_keywords?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Industry Keywords</span>
						<div class="flex gap-1 flex-wrap">
							{#each draft.industry_keywords as kw}
								<span style="font-size: 10px; padding: 2px 8px; background: var(--color-surface-highest); font-weight: 700; text-transform: uppercase;">{kw}</span>
							{/each}
						</div>
					</div>
				{/if}

				<!-- ── Certifications ── -->
				{#if draft.required_certifications?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Required Certifications</span>
						<div class="flex gap-1 flex-wrap">
							{#each draft.required_certifications as cert}
								<span style="font-size: 10px; padding: 2px 8px; border: 1px solid var(--color-secondary); color: var(--color-secondary); font-weight: 700; text-transform: uppercase;">{cert}</span>
							{/each}
						</div>
					</div>
				{/if}

				<!-- ── Full JD Text (editable) ── -->
				<div class="mb-4">
					<span class="tag-label mb-2" style="display: block;">Full Job Description (editable)</span>
					<textarea bind:value={draft.jd_text} oninput={markDirty}
						style="width:100%; min-height:340px; font-family:'Space Grotesk', monospace; font-size:13px; line-height:1.6; padding:14px; border:2px solid var(--color-on-surface); background:var(--color-surface-bright); resize:vertical; white-space:pre-wrap;"></textarea>
				</div>

				<!-- ── Timestamps ── -->
				<div class="flex gap-4 mb-4" style="font-size: 10px; color: var(--color-on-surface-dim);">
					<span><strong>Created:</strong> {new Date(selectedJd.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</span>
					<span><strong>Updated:</strong> {new Date(selectedJd.updated_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</span>
					{#if selectedJd.tags?.length}
						<span><strong>Tags:</strong> {selectedJd.tags.join(', ')}</span>
					{/if}
				</div>

				<!-- ── Actions ── -->
				<div class="flex gap-2 pt-3" style="border-top: 2px solid var(--color-on-surface);">
					<button class="send-btn" style="font-size: 10px; padding: 6px 14px;" onclick={() => duplicateJd(selectedJd.id)}>Duplicate</button>
					<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px;">Use for Position</button>
					<div class="ml-auto">
						<button class="btn-danger" style="font-size: 10px; padding: 6px 14px;" onclick={() => archiveJd(selectedJd.id)}>Archive</button>
					</div>
				</div>
				</div><!-- /right -->
			</div><!-- /split -->
		</div>
	</div>
{/if}

<!-- Floating share menu — multi-select checkboxes -->
{#if shareOpenId !== null}
	{@const _curJd = jds.find(j => j.id === shareOpenId) || {}}
	<div class="share-overlay" onclick={closeShare}
		role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') closeShare(); }}></div>
	<div class="ink-border stamp-shadow share-menu-floating"
		style="top: {sharePos.top}px; left: {sharePos.left}px; min-width: 240px;">
		<div style="padding: 10px 14px; border-bottom: 2px solid var(--color-on-surface); font-size: 11px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase;">
			Share JD
		</div>
		<label style="display: flex; align-items: center; gap: 8px; padding: 10px 14px; cursor: pointer; border-bottom: 1px solid rgba(56,56,50,0.15);">
			<input type="checkbox" checked={!!_curJd.shared_sector} onchange={(e) => shareJdMulti(shareOpenId, { shared_sector: e.target.checked, shared_global: !!_curJd.shared_global }, e)} />
			<div>
				<div style="font-size: 11px; font-weight: 900;">▣ Share to my Sector</div>
				<div style="font-size: 9px; opacity: 0.7;">visible to sector members</div>
			</div>
		</label>
		<label style="display: flex; align-items: center; gap: 8px; padding: 10px 14px; cursor: pointer; border-bottom: 1px solid rgba(56,56,50,0.15);">
			<input type="checkbox" checked={!!_curJd.shared_global} onchange={(e) => shareJdMulti(shareOpenId, { shared_sector: !!_curJd.shared_sector, shared_global: e.target.checked }, e)} />
			<div>
				<div style="font-size: 11px; font-weight: 900;">◉ Publish to Global</div>
				<div style="font-size: 9px; opacity: 0.7;">org-wide (admin only)</div>
			</div>
		</label>
		<button onclick={(e) => shareJdMulti(shareOpenId, { shared_sector: false, shared_global: false }, e)}
			style="display: block; width: 100%; text-align: left; padding: 10px 14px; border: none; font-size: 11px; font-weight: 700; cursor: pointer; background: transparent;">
			▮ Make private (uncheck both)
		</button>
	</div>
{/if}

<!-- Floating bulk action bar (JDs) -->
{#if jdSelectedIds.size > 0}
	<div class="bulk-bar">
		<span class="bulk-bar-count">{jdSelectedIds.size} selected</span>
		<button class="bulk-bar-pill" onclick={jdBulkArchive}>Archive selected</button>
		<button class="bulk-bar-pill" onclick={jdBulkShare}>Share selected</button>
		<button class="bulk-bar-pill bulk-bar-pill-danger" onclick={() => bulkConfirmAction = 'delete'}>Delete selected</button>
		<button class="bulk-bar-clear" onclick={jdClearSelection} title="Clear selection">×</button>
	</div>
{/if}

<!-- Confirm modal for bulk delete -->
{#if bulkConfirmAction === 'delete'}
	<div class="bulk-modal-backdrop" onclick={(e) => { if (e.target === e.currentTarget) bulkConfirmAction = null; }}>
		<div class="bulk-modal">
			<div class="bulk-modal-head">Delete {jdSelectedIds.size} JD{jdSelectedIds.size === 1 ? '' : 's'}?</div>
			<div class="bulk-modal-body">This cannot be undone.</div>
			<div class="bulk-modal-foot">
				<button class="bulk-modal-btn" onclick={() => bulkConfirmAction = null}>Cancel</button>
				<button class="bulk-modal-btn bulk-modal-btn-danger" onclick={jdBulkDelete}>Delete</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.docx-render { font-family: 'Times New Roman', 'Georgia', serif; color:#222; font-size:13px; line-height:1.55; }
	.docx-render :global(p) { margin: 0 0 0.6em; }
	.docx-render :global(h1),.docx-render :global(h2),.docx-render :global(h3),.docx-render :global(h4) { font-weight:700; margin: 0.8em 0 0.4em; }
	.docx-render :global(table) { border-collapse: collapse; width:100%; margin: 0.6em 0; }
	.docx-render :global(td),.docx-render :global(th) { border:1px solid #999; padding:6px 8px; vertical-align:top; }
	.docx-render :global(ul),.docx-render :global(ol) { padding-left: 1.4em; margin: 0.4em 0; }
	.docx-render :global(strong) { font-weight:700; }
	.docx-render :global(img) { max-width:100%; }
	.jd-page-wrap {
		height: 100vh;
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--color-bg, #faf9f5);
	}
	.jd-split {
		flex: 1 1 auto;
		display: grid;
		grid-template-columns: 280px 1fr;
		min-height: 0;
	}
	.jd-rail {
		overflow-y: auto;
		border-right: 1px solid var(--color-border, #e8e6dd);
		padding: 16px 12px 140px 12px;
		background: var(--color-surface, #ffffff);
	}
	.jd-main {
		min-width: 0;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 20px 24px 140px 24px;
		background: var(--color-bg, #faf9f5);
	}
	@media (max-width: 900px) {
		.jd-split { grid-template-columns: 1fr; grid-auto-flow: row; }
		.jd-rail { border-right: none; border-bottom: 1px solid var(--color-border, #e8e6dd); }
	}
	.jd-page-title {
		font-family: 'Tiempos Text', 'Tiempos', Georgia, 'Times New Roman', serif;
		font-size: 26px;
		font-weight: 500;
		letter-spacing: -0.01em;
		color: var(--color-on-surface, #2c2c2c);
		line-height: 1.2;
	}
	.jd-page-subtitle {
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 13px;
		color: var(--color-on-surface-dim, #6f6e69);
		margin-top: 4px;
	}
	.jd-btn {
		display: inline-flex; align-items: center; gap: 6px;
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 13px; font-weight: 500;
		padding: 7px 14px;
		border-radius: 8px;
		border: 1px solid transparent;
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
		white-space: nowrap;
	}
	.jd-btn-primary {
		background: var(--color-accent, #c96342);
		color: #ffffff;
		border-color: var(--color-accent, #c96342);
	}
	.jd-btn-primary:hover { background: var(--color-accent-ink, #b04f30); border-color: var(--color-accent-ink, #b04f30); }
	.jd-btn-outline {
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface, #2c2c2c);
		border-color: var(--color-border, #e8e6dd);
	}
	.jd-btn-outline:hover { background: var(--color-surface-warm, #f4f3ee); border-color: var(--color-border-strong, #d8d5cb); }
	.jd-search-input {
		flex: 1;
		padding: 9px 14px;
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 13px; font-weight: 400;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 8px;
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface, #2c2c2c);
		outline: none;
		transition: border-color 120ms ease, box-shadow 120ms ease;
	}
	.jd-search-input::placeholder { color: var(--color-on-surface-dim, #6f6e69); }
	.jd-search-input:focus {
		border-color: var(--color-accent, #c96342);
		box-shadow: 0 0 0 3px rgba(201, 99, 66, 0.15);
	}
	.jd-empty-state {
		display: flex; flex-direction: column; align-items: center; justify-content: center;
		padding: 56px 24px;
		background: var(--color-surface, #ffffff);
		border: 1px dashed var(--color-border-strong, #d8d5cb);
		border-radius: 12px;
	}
	.jd-status-bar {
		position: sticky; bottom: 0; left: 0; right: 0;
		z-index: 70;
		height: 32px;
		display: flex; align-items: center; gap: 10px;
		padding: 0 18px;
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface-dim, #6f6e69);
		border-top: 1px solid var(--color-border, #e8e6dd);
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 12px; font-weight: 500;
	}
	.sb-section { font-variant-numeric: tabular-nums; }
	.sb-sep { opacity: 0.4; }
	.sb-accent { color: var(--color-accent, #c96342); font-weight: 600; }

	.scope-tabs {
		display: flex;
		gap: 0;
		margin-bottom: 14px;
		border-bottom: 3px solid var(--color-on-surface);
		overflow-x: auto;
	}
	.scope-tab {
		background: var(--color-surface-bright);
		border: 2px solid var(--color-on-surface);
		border-bottom: none;
		padding: 10px 18px;
		font-family: 'Space Grotesk', sans-serif;
		color: var(--color-on-surface);
		opacity: 0.7;
		cursor: pointer;
		text-align: left;
		margin-right: -2px;
		flex: 1 1 auto;
		max-width: 280px;
	}
	.scope-tab:hover { opacity: 1; }
	.scope-tab.active {
		background: var(--color-accent, #c96342);
		color: #fff;
		opacity: 1;
		font-weight: 900;
	}
	.scope-dot {
		display: inline-block; width: 10px; height: 10px;
		background: transparent; border: 2px solid var(--color-on-surface);
	}
	.scope-dot.dot-active { background: var(--color-on-surface); }
	.scope-count {
		display: inline-block; min-width: 22px; text-align: center;
		background: var(--color-on-surface); color: var(--color-surface);
		padding: 1px 6px; font-size: 10px; font-weight: 900;
		letter-spacing: 0.05em; margin-left: 6px;
	}

	.jd-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		margin-bottom: 16px;
		background: var(--color-surface, #ffffff);
	}
	.jd-data-table {
		width: 100%; border-collapse: collapse;
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 13px;
		color: var(--color-on-surface, #2c2c2c);
	}
	.jd-data-table th, .jd-data-table td { padding: 11px 12px; text-align: left; vertical-align: middle; }
	.jd-th-labels th {
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-on-surface-dim, #6f6e69);
		font-size: 12px; font-weight: 600; letter-spacing: 0;
		text-transform: none; user-select: none; white-space: nowrap;
		position: sticky; top: 0; z-index: 2;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.jd-th-filters td {
		background: var(--color-surface, #ffffff);
		border-top: 1px solid var(--color-border-soft, #efeee6);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		padding: 6px 8px;
	}
	.filt {
		width: 100%; padding: 6px 8px; font-size: 12px;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 6px;
		font-family: 'Inter', system-ui, sans-serif;
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface, #2c2c2c);
	}
	.filt:focus { outline: none; border-color: var(--color-accent, #c96342); box-shadow: 0 0 0 2px rgba(201,99,66,0.12); }
	.jd-row { cursor: pointer; border-top: 1px solid var(--color-border-soft, #efeee6); transition: background 100ms ease; outline: none; }
	.jd-row-focus,
	.jd-row:focus,
	.jd-row:focus-visible {
		box-shadow: inset 0 0 0 2px var(--color-accent, #c96342);
		outline: none;
	}
	.jd-row:hover { background: var(--color-surface-warm, #f4f3ee); }
	.jd-title-link {
		font-weight: 600;
		color: var(--color-on-surface, #2c2c2c);
		text-decoration: none;
	}
	.jd-title-link:hover { color: var(--color-accent, #c96342); }
	.jd-enhanced-pill {
		display: inline-block;
		font-size: 10px; font-weight: 500;
		margin-left: 6px;
		padding: 2px 7px;
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		border-radius: 999px;
	}
	.vis-badge {
		display: inline-block;
		padding: 3px 9px;
		font-size: 11px; font-weight: 500;
		border-radius: 999px;
		border: 1px solid transparent;
	}
	.vis-private {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
	}
	.vis-sector {
		background: var(--color-tertiary-container, #d8e4dd);
		color: var(--color-tertiary, #2d6a4f);
	}
	.vis-global {
		background: var(--color-secondary-container, #f0eee5);
		color: var(--color-on-surface, #2c2c2c);
	}
	.row-action {
		font-family: 'Inter', system-ui, sans-serif;
		font-size: 12px; font-weight: 500;
		padding: 5px 12px;
		border: 1px solid var(--color-border, #e8e6dd);
		background: var(--color-surface, #ffffff);
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 999px;
		cursor: pointer;
		margin-right: 6px;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.row-action:hover { background: var(--color-surface-warm, #f4f3ee); border-color: var(--color-border-strong, #d8d5cb); }
	.row-action-danger {
		border-color: var(--color-border, #e8e6dd);
		color: var(--color-error, #a83232);
	}
	.row-action-danger:hover {
		background: var(--color-error-soft, #f5dada);
		border-color: var(--color-error, #a83232);
		color: var(--color-error, #a83232);
	}
	.share-menu {
		position: absolute; right: 0; top: 100%;
		margin-top: 4px; background: var(--color-surface);
		min-width: 200px; z-index: 50;
	}
	.share-menu button {
		display: block; width: 100%; text-align: left;
		padding: 8px 12px; border: none;
		border-bottom: 1px solid rgba(56,56,50,0.2);
		font-size: 11px; font-weight: 700;
		cursor: pointer; background: transparent;
	}
	.share-menu button:last-child { border-bottom: none; }
	.share-menu button:hover { background: var(--color-surface-bright); }
	.share-overlay { position: fixed; inset: 0; z-index: 999; background: transparent; }
	.share-menu-floating {
		position: fixed; z-index: 1000;
		background: var(--color-surface);
		min-width: 200px;
	}
	.share-menu-floating button {
		display: block; width: 100%; text-align: left;
		padding: 8px 12px; border: none;
		border-bottom: 1px solid rgba(56,56,50,0.2);
		font-size: 11px; font-weight: 700;
		cursor: pointer; background: transparent;
	}
	.share-menu-floating button:last-child { border-bottom: none; }
	.share-menu-floating button:hover { background: var(--color-surface-bright); }
	.ts-cell { white-space: nowrap; }
	.ts-abs { font-size: 12px; font-weight: 500; color: var(--color-on-surface, #2c2c2c); }
	.ts-rel { font-size: 11px; color: var(--color-on-surface-dim, #6f6e69); margin-top: 1px; }

	/* Recent searches dropdown */
	.jd-recent-dropdown {
		position: absolute; top: calc(100% + 4px); left: 0; right: 0;
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0,0,0,0.08);
		z-index: 50; padding: 6px 0;
		max-height: 280px; overflow-y: auto;
	}
	.jd-recent-head {
		font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69);
		padding: 6px 14px 4px; font-weight: 600;
	}
	.jd-recent-item {
		display: flex; align-items: center; gap: 8px;
		width: 100%; padding: 8px 14px;
		background: none; border: none;
		font-size: 13px; color: var(--color-on-surface, #2c2c2c);
		cursor: pointer; font-family: inherit; text-align: left;
	}
	.jd-recent-item.active, .jd-recent-item:hover { background: var(--color-surface-warm, #f4f3ee); }

	/* Saved-search pill row */
	.jd-saved-pill-row {
		display: flex; flex-wrap: wrap; gap: 6px;
		align-items: center; margin: -4px 0 12px;
	}
	.jd-saved-pill-label {
		font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69); font-weight: 600; margin-right: 4px;
	}
	.jd-saved-pill {
		display: inline-flex; align-items: center; gap: 6px;
		padding: 4px 10px 4px 12px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px; font-size: 12px;
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer; font-family: inherit;
		transition: background .15s, border-color .15s;
	}
	.jd-saved-pill:hover {
		background: var(--color-primary-container, #faf2ed);
		border-color: var(--color-primary, #c96342);
	}
	.jd-saved-pill-x {
		display: inline-flex; align-items: center; justify-content: center;
		width: 14px; height: 14px; border-radius: 50%;
		font-size: 14px; line-height: 1;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.jd-saved-pill-x:hover { background: var(--color-error-container, #f5dada); color: var(--color-error, #a83232); }

	/* Selected row tint */
	.jd-row-selected { background: var(--color-primary-container, #faf2ed) !important; }

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
		border-color: var(--color-error, #a83232); color: var(--color-error, #a83232);
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

	/* Confirm modal */
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
	.exp-chip {
		display: inline-block;
		padding: 2px 8px;
		font-size: 11px;
		font-weight: 600;
		border-radius: 999px;
		border: 1px solid transparent;
		line-height: 1.4;
		white-space: nowrap;
	}
	.exp-chip-neutral { background: var(--color-surface-warm, #f4f3ee); color: var(--color-on-surface-dim, #6b6b6b); border-color: var(--color-border, #e8e6dd); }
	.exp-chip-amber   { background: #fef3c7; color: #92400e; border-color: #fcd34d; }
	.exp-chip-red     { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
</style>
