<script>
	/** Central Talent Poolsitory — Upload, Search, Browse, Compare */
	import { onMount, untrack } from 'svelte';
	import { apiJson, api, getToken } from '$lib/api';
	import { goto } from '$app/navigation';
	import Pagination from '$lib/Pagination.svelte';
	import { addToast } from '$lib/Toast.svelte';
	import MergeModal from '$lib/MergeModal.svelte';
	import UploadProgressModal from '$lib/UploadProgressModal.svelte';
	import PipelineStepper from '$lib/PipelineStepper.svelte';
	// PendingFilesTable retired in favour of unified rows; file kept for revert.
	import UploadTracker from '$lib/UploadTracker.svelte';
	import CandidateRailFilters from '$lib/CandidateRailFilters.svelte';
	import { SkeletonRow } from '$lib/Skeleton.svelte';
	import EmptyState from '$lib/EmptyState.svelte';
	import { hoverPreview } from '$lib/HoverPreview.svelte';
	import Search from '@lucide/svelte/icons/search';
	import Users from '@lucide/svelte/icons/users';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import MapPin from '@lucide/svelte/icons/map-pin';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	// B4 — list of in-flight uploads, fed to <UploadTracker />
	let uploadingFiles = $state.raw([]);

	// Live upload pipeline modals
	let uploadQueue = $state.raw([]);
	function dismissUpload(idx) {
		uploadQueue = uploadQueue.filter((_, i) => i !== idx);
	}

	// --- Merge proposals (duplicate detection chips) ---
	let dupCandidateIds = $state(new Set());
	let dupProposalsByCand = $state(new Map()); // candidate id -> first proposal id
	let openMergeId = $state(null);
	async function loadMergeProposals() {
		try {
			const data = await apiJson('/merges/?entity_type=candidate&status=pending&limit=200');
			const ids = new Set();
			const map = new Map();
			for (const p of (data.items || [])) {
				if (p.winner_id != null) {
					ids.add(p.winner_id);
					if (!map.has(p.winner_id)) map.set(p.winner_id, p.id);
				}
				if (p.loser_id != null) {
					ids.add(p.loser_id);
					if (!map.has(p.loser_id)) map.set(p.loser_id, p.id);
				}
			}
			dupCandidateIds = ids;
			dupProposalsByCand = map;
		} catch { /* non-critical */ }
	}
	function openDupForCandidate(cid, e) {
		e?.stopPropagation();
		const pid = dupProposalsByCand.get(cid);
		if (pid != null) openMergeId = pid;
	}

	// --- Core state ---
	let candidates = $state([]);
	let total = $state(0);
	let loading = $state(true);
	let dragOver = $state(false);
	let candOffset = $state(0);
	const candLimit = 50;
	let uploading = $state(false);
	let uploadResults = $state([]);
	let selectedCvId = $state(null);
	let selectedCandidate = $state(null);
	let dropExpanded = $state(false);
	let showFilters = $state(false);
	let showMore = $state(false);
	let rowActionOpenId = $state(null);
	let rowActionPos = $state({ top: 0, left: 0 });
	let bulkTagInput = $state('');
	let bulkTagOpen = $state(false);

	function initials(name) {
		if (!name) return '?';
		const parts = String(name).trim().split(/\s+/).filter(Boolean);
		if (parts.length === 0) return '?';
		const a = parts[0][0] || '';
		const b = parts.length > 1 ? (parts[1][0] || '') : '';
		return (a + b).toUpperCase();
	}

	function toggleRowAction(id, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		if (rowActionOpenId === id) { rowActionOpenId = null; return; }
		const r = ev.currentTarget.getBoundingClientRect();
		rowActionPos = { top: r.bottom + 4, left: Math.max(8, r.right - 200) };
		rowActionOpenId = id;
	}
	function closeRowAction() { rowActionOpenId = null; }

	async function rowReject(id, ev) {
		ev?.stopPropagation?.();
		rowActionOpenId = null;
		try {
			await apiJson('/bulk/reject', { method: 'POST', body: JSON.stringify({ candidate_ids: [id] }) });
			cliEvent('success', 'Candidate rejected');
			loadCandidates();
		} catch (e) { cliEvent('error', `Reject failed: ${e.message}`); }
	}
	// --- Hard-delete CV with double-confirm modal ---
	let cvDeleteTarget = $state(null); // { id, name }
	let cvDeleteConfirmText = $state('');
	let cvDeleting = $state(false);
	async function rowDelete(id, ev) {
		ev?.stopPropagation?.();
		rowActionOpenId = null;
		const c = candidates.find(x => x.id === id) || pendingRows.find(x => x.id === id);
		const name = c?.name || c?.filename || `CV #${id}`;
		cvDeleteTarget = { id, name };
		cvDeleteConfirmText = '';
	}
	async function confirmCvDelete() {
		if (!cvDeleteTarget) return;
		const _ct = (cvDeleteTarget.name || '').trim().toLowerCase();
		const _cv = cvDeleteConfirmText.trim().toLowerCase();
		if (!(_cv === _ct || _cv === 'delete')) {
			addToast('error', `Type candidate name "${cvDeleteTarget.name}" or DELETE`);
			return;
		}
		cvDeleting = true;
		try {
			await apiJson(`/candidates/${cvDeleteTarget.id}?hard=true`, { method: 'DELETE' });
			addToast('success', `"${cvDeleteTarget.name}" permanently deleted`);
			cliEvent('success', `CV "${cvDeleteTarget.name}" hard-deleted`);
			candidates = candidates.filter(r => r.id !== cvDeleteTarget.id);
			pendingRows = pendingRows.filter(r => r.id !== cvDeleteTarget.id);
			cvDeleteTarget = null;
			cvDeleteConfirmText = '';
			loadCandidates(); loadPendingRows();
		} catch (e) {
			addToast('error', `Delete failed: ${e.message}`);
		}
		cvDeleting = false;
	}

	async function bulkAttachTag() {
		const tag = (bulkTagInput || '').trim();
		if (!tag || selectedIds.size === 0) return;
		bulkLoading = true;
		try {
			const ids = [...selectedIds];
			await Promise.all(ids.map(id => apiJson(`/candidates/${id}/tags`, {
				method: 'POST', body: JSON.stringify({ tag })
			}).catch(() => null)));
			cliEvent('success', `Tagged ${ids.length} with "${tag}"`);
			bulkTagInput = ''; bulkTagOpen = false;
			loadCandidates();
		} catch (e) { cliEvent('error', `Tag failed: ${e.message}`); }
		bulkLoading = false;
	}

	// --- Search & Filters ---
	// Smart defaults: restore last filters from localStorage `pulse_cv_filters`
	const _cvFilterDefaults = (() => {
		if (typeof localStorage === 'undefined') return {};
		try { return JSON.parse(localStorage.getItem('pulse_cv_filters') || '{}'); }
		catch { return {}; }
	})();
	let searchQuery = $state(_cvFilterDefaults.searchQuery || '');
	let filtersOpen = $state(false);
	let mobileFiltersOpen = $state(false); // bottom-sheet rail on <768px
	let skillsChips = $state(_cvFilterDefaults.skillsChips || []);
	let skillsInput = $state('');
	let locationFilter = $state(_cvFilterDefaults.locationFilter || '');
	let companyFilter = $state(_cvFilterDefaults.companyFilter || '');
	let seniorityFilter = $state(_cvFilterDefaults.seniorityFilter || '');
	let minExp = $state(_cvFilterDefaults.minExp || '');
	let maxExp = $state(_cvFilterDefaults.maxExp || '');
	let minQuality = $state(_cvFilterDefaults.minQuality || '');
	let maxQuality = $state(_cvFilterDefaults.maxQuality || '');
	let sourceFilter = $state(_cvFilterDefaults.sourceFilter || '');
	let tagsChips = $state(_cvFilterDefaults.tagsChips || []);
	let tagsInput = $state('');

	// Persist filters whenever they change (smart-defaults polish)
	$effect(() => {
		if (typeof localStorage === 'undefined') return;
		const snap = {
			searchQuery, skillsChips: [...skillsChips], locationFilter, companyFilter,
			seniorityFilter, minExp, maxExp, minQuality, maxQuality,
			sourceFilter, tagsChips: [...tagsChips],
		};
		try { localStorage.setItem('pulse_cv_filters', JSON.stringify(snap)); } catch {}
	});

	// --- Bulk selection ---
	let selectedIds = $state(new Set());
	let bulkStage = $state('');
	let bulkPositionSlug = $state('');
	let bulkLoading = $state(false);

	// --- Compare mode --- (persisted across nav via localStorage)
	const _COMPARE_KEY = 'pulse_compare_ids';
	const _COMPARE_MODE_KEY = 'pulse_compare_mode';
	function _loadCompareIds() {
		if (typeof localStorage === 'undefined') return new Set();
		try { const raw = localStorage.getItem(_COMPARE_KEY); return raw ? new Set(JSON.parse(raw)) : new Set(); }
		catch { return new Set(); }
	}
	let compareMode = $state(typeof localStorage !== 'undefined' && localStorage.getItem(_COMPARE_MODE_KEY) === '1');
	let compareIds = $state(_loadCompareIds());
	let showCompareModal = $state(false);
	let comparisonData = $state(null);
	let compareLoading = $state(false);
	let comparePositionSlug = $state('');
	$effect(() => {
		if (typeof localStorage === 'undefined') return;
		try { localStorage.setItem(_COMPARE_KEY, JSON.stringify([...compareIds])); } catch {}
		try { localStorage.setItem(_COMPARE_MODE_KEY, compareMode ? '1' : '0'); } catch {}
	});

	// --- Positions (for bulk add / compare) ---
	let positions = $state([]);

	// --- Saved Searches ---
	let savedSearches = $state([]);
	let showSavedSearches = $state(false);
	let savingSearch = $state(false);

	// --- Recent + Local Saved Searches (localStorage) ---
	const _RECENT_CV_KEY = 'pulse_recent_cv_searches';
	const _LOCAL_SAVED_CV_KEY = 'pulse_saved_cv_searches';
	function _readLs(key, fallback) {
		if (typeof localStorage === 'undefined') return fallback;
		try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
	}
	function _writeLs(key, val) {
		if (typeof localStorage === 'undefined') return;
		try { localStorage.setItem(key, JSON.stringify(val)); } catch {}
	}
	let recentSearches = $state(_readLs(_RECENT_CV_KEY, []));
	let localSavedSearches = $state(_readLs(_LOCAL_SAVED_CV_KEY, []));
	let showRecentDropdown = $state(false);
	let recentHighlightIdx = $state(-1);

	function pushRecentSearch(q) {
		const term = (q || '').trim();
		if (!term) return;
		const next = [term, ...recentSearches.filter(s => s !== term)].slice(0, 5);
		recentSearches = next;
		_writeLs(_RECENT_CV_KEY, next);
	}
	function applyRecentSearch(term) {
		searchQuery = term;
		showRecentDropdown = false;
		recentHighlightIdx = -1;
		pushRecentSearch(term);
		doSearch();
	}
	function saveLocalSearch() {
		const name = (prompt('Name this search:') || '').trim();
		if (!name) return;
		const entry = { id: Date.now(), name, filters: getCurrentFilters() };
		const next = [entry, ...localSavedSearches.filter(s => s.name !== name)].slice(0, 20);
		localSavedSearches = next;
		_writeLs(_LOCAL_SAVED_CV_KEY, next);
		cliEvent('success', `Search "${name}" saved`);
	}
	function applyLocalSavedSearch(entry) {
		applySavedSearch({ filters: entry.filters || {} });
	}
	function deleteLocalSavedSearch(id, ev) {
		ev?.stopPropagation?.();
		const next = localSavedSearches.filter(s => s.id !== id);
		localSavedSearches = next;
		_writeLs(_LOCAL_SAVED_CV_KEY, next);
	}
	function searchKeydown(e) {
		if (!showRecentDropdown || recentSearches.length === 0) {
			if (e.key === 'Enter') { pushRecentSearch(searchQuery); doSearch(); }
			return;
		}
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			recentHighlightIdx = Math.min(recentHighlightIdx + 1, recentSearches.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			recentHighlightIdx = Math.max(recentHighlightIdx - 1, -1);
		} else if (e.key === 'Enter') {
			if (recentHighlightIdx >= 0 && recentHighlightIdx < recentSearches.length) {
				e.preventDefault();
				applyRecentSearch(recentSearches[recentHighlightIdx]);
			} else {
				pushRecentSearch(searchQuery); doSearch(); showRecentDropdown = false;
			}
		} else if (e.key === 'Escape') {
			showRecentDropdown = false; recentHighlightIdx = -1;
		}
	}

	// --- AI Smart Search ---
	let aiSearchEnabled = $state(false);
	let aiSearchLoading = $state(false);
	let aiSearchInterpretation = $state('');

	// --- Bulk Upload modal ---
	let showBulkUploadModal = $state(false);
	let bulkFiles = $state([]); // Array<{ file: File, status: 'pending'|'uploading'|'done'|'error'|'skipped', error?: string }>
	let bulkDragOver = $state(false);
	let bulkUploading = $state(false);
	let bulkResult = $state(null); // { total, created, skipped_duplicates, errors, skipped }
	const BULK_MAX_FILES = 50;
	const BULK_ALLOWED_EXT = ['.pdf', '.docx', '.doc', '.txt'];

	function bulkResetModal() {
		bulkFiles = [];
		bulkResult = null;
		bulkUploading = false;
		bulkDragOver = false;
	}

	function bulkAddFiles(fileList) {
		if (!fileList) return;
		const arr = Array.from(fileList);
		const existing = new Set(bulkFiles.map(f => `${f.file.name}|${f.file.size}`));
		const next = [...bulkFiles];
		for (const f of arr) {
			const ext = '.' + (f.name.split('.').pop() || '').toLowerCase();
			if (!BULK_ALLOWED_EXT.includes(ext)) continue;
			const key = `${f.name}|${f.size}`;
			if (existing.has(key)) continue;
			existing.add(key);
			next.push({ file: f, status: 'pending' });
			if (next.length >= BULK_MAX_FILES) break;
		}
		bulkFiles = next.slice(0, BULK_MAX_FILES);
	}

	function bulkRemoveFile(idx) {
		bulkFiles = bulkFiles.filter((_, i) => i !== idx);
	}

	function bulkOnDrop(e) {
		e.preventDefault();
		bulkDragOver = false;
		if (e.dataTransfer?.files) bulkAddFiles(e.dataTransfer.files);
	}

	async function bulkDoUpload() {
		if (bulkFiles.length === 0 || bulkUploading) return;
		bulkUploading = true;
		bulkResult = null;
		bulkFiles = bulkFiles.map(f => ({ ...f, status: 'uploading' }));

		try {
			const fd = new FormData();
			for (const f of bulkFiles) fd.append('files', f.file);
			const res = await api('/candidates/bulk-upload', { method: 'POST', body: fd });
			if (!res.ok) {
				let msg = `Upload failed: ${res.status}`;
				try { const j = await res.json(); if (j?.detail) msg = j.detail; } catch {}
				bulkFiles = bulkFiles.map(f => ({ ...f, status: 'error', error: msg }));
				bulkUploading = false;
				return;
			}
			const data = await res.json();
			bulkResult = data;

			// Map per-file status from result
			const createdSet = new Set((data.candidates || []).map(c => (c.email || '').toLowerCase()));
			const skippedByName = new Map((data.skipped || []).map(s => [s.filename, s]));
			const errorByName = new Map((data.errors || []).map(e => [e.filename, e]));
			bulkFiles = bulkFiles.map(f => {
				const nm = f.file.name;
				if (errorByName.has(nm)) return { ...f, status: 'error', error: errorByName.get(nm).error };
				if (skippedByName.has(nm)) return { ...f, status: 'skipped', error: `Duplicate of ${skippedByName.get(nm).existing_name || 'existing candidate'}` };
				return { ...f, status: 'done' };
			});
		} catch (err) {
			bulkFiles = bulkFiles.map(f => ({ ...f, status: 'error', error: String(err) }));
		} finally {
			bulkUploading = false;
		}
	}

	function bulkClose() {
		const hadResult = !!bulkResult;
		showBulkUploadModal = false;
		bulkResetModal();
		if (hadResult) loadCandidates();
	}

	// --- Import modal ---
	let showImportModal = $state(false);
	let importTab = $state('linkedin');
	let importLoading = $state(false);
	let importLinkedinUrl = $state('');
	let importLinkedinText = $state('');
	let importLinkedinPosition = $state('');
	let importGithubUrl = $state('');
	let importGithubCandidateId = $state('');
	let importPasteText = $state('');
	let importPasteSource = $state('text_import');
	let importPastePosition = $state('');
	let importResult = $state(null);
	let importError = $state('');

	async function doLinkedInImport() {
		if (!importLinkedinUrl && !importLinkedinText) { importError = 'Provide a URL or paste profile text'; return; }
		importLoading = true;
		importError = '';
		importResult = null;
		try {
			const payload = {};
			if (importLinkedinUrl) payload.linkedin_url = importLinkedinUrl;
			if (importLinkedinText) payload.linkedin_text = importLinkedinText;
			if (importLinkedinPosition) payload.position_slug = importLinkedinPosition;
			const data = await apiJson('/candidates/import-linkedin', {
				method: 'POST',
				body: JSON.stringify(payload),
			});
			importResult = data;
			cliEvent('success', `Imported ${data.name || 'candidate'} from LinkedIn`);
			setTimeout(() => loadCandidates(), 1000);
		} catch (e) {
			importError = e.message;
			cliEvent('error', `LinkedIn import failed: ${e.message}`);
		}
		importLoading = false;
	}

	async function doGitHubAnalysis() {
		if (!importGithubUrl || !importGithubCandidateId) { importError = 'Provide GitHub URL and select a candidate'; return; }
		importLoading = true;
		importError = '';
		importResult = null;
		try {
			const data = await apiJson(`/candidates/${importGithubCandidateId}/analyze-github`, {
				method: 'POST',
				body: JSON.stringify({ github_url: importGithubUrl }),
			});
			importResult = data;
			cliEvent('success', `GitHub analysis complete: ${data.analysis?.username}`);
		} catch (e) {
			importError = e.message;
			cliEvent('error', `GitHub analysis failed: ${e.message}`);
		}
		importLoading = false;
	}

	async function doTextImport() {
		if (!importPasteText || importPasteText.trim().length < 20) { importError = 'Paste at least 20 characters of text'; return; }
		importLoading = true;
		importError = '';
		importResult = null;
		try {
			const data = await apiJson('/candidates/import-text', {
				method: 'POST',
				body: JSON.stringify({
					text: importPasteText,
					source: importPasteSource,
					position_slug: importPastePosition || undefined,
				}),
			});
			importResult = data;
			cliEvent('success', `Imported ${data.name || 'candidate'} from text`);
			setTimeout(() => loadCandidates(), 1000);
		} catch (e) {
			importError = e.message;
			cliEvent('error', `Text import failed: ${e.message}`);
		}
		importLoading = false;
	}

	function resetImportModal() {
		importLinkedinUrl = '';
		importLinkedinText = '';
		importLinkedinPosition = '';
		importGithubUrl = '';
		importGithubCandidateId = '';
		importPasteText = '';
		importPasteSource = 'text_import';
		importPastePosition = '';
		importResult = null;
		importError = '';
		importLoading = false;
	}

	const seniorityOptions = ['', 'junior', 'mid', 'senior', 'staff', 'principal', 'lead', 'manager', 'director'];
	const sourceOptions = ['', 'upload', 'referral', 'position_upload', 'ai_scan', 'linkedin', 'text_import'];
	const stageOptions = ['uploaded', 'screened', 'shortlisted', 'interview', 'offered', 'hired', 'rejected'];

	// --- Derived ---
	let activeFilterCount = $derived(
		(skillsChips.length > 0 ? 1 : 0) +
		(locationFilter ? 1 : 0) +
		(companyFilter ? 1 : 0) +
		(seniorityFilter ? 1 : 0) +
		(minExp || maxExp ? 1 : 0) +
		(minQuality || maxQuality ? 1 : 0) +
		(sourceFilter ? 1 : 0) +
		(tagsChips.length > 0 ? 1 : 0)
	);

	let allSelected = $derived(
		candidates.length > 0 && candidates.every(c => selectedIds.has(c.id))
	);

	let selectedCount = $derived(selectedIds.size);

	let compareCount = $derived(compareIds.size);

	// --- Load on mount ---
	onMount(() => { loadCandidates(); loadPositions(); loadSavedSearches(); loadCvUserOptions(); loadMergeProposals(); });

	async function loadPositions() {
		try {
			const data = await apiJson('/positions');
			positions = data.positions || [];
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error(e); }
	}

	function onCandPageChange(newOffset) {
		candOffset = newOffset;
		loadCandidates();
	}

	async function loadCandidates() {
		loading = true;
		try {
			let url = `/candidates?limit=${candLimit}&offset=${candOffset}&scope=${cvScope}&with_assignments=1`;
			url += `&sort=${cvSortCol}&dir=${cvSortDir}`;
			if (cvFilterCreatedBy) url += `&created_by=${cvFilterCreatedBy}`;
			if (cvFilterModifiedBy) url += `&modified_by=${cvFilterModifiedBy}`;
			const ca = cvRangeBoundary(cvFilterCreated); if (ca) url += `&created_after=${encodeURIComponent(ca)}`;
			const ma = cvRangeBoundary(cvFilterModified); if (ma) url += `&modified_after=${encodeURIComponent(ma)}`;
			if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;
			if (skillsChips.length) url += `&skills=${encodeURIComponent(skillsChips.join(','))}`;
			if (locationFilter) url += `&location=${encodeURIComponent(locationFilter)}`;
			if (companyFilter) url += `&company=${encodeURIComponent(companyFilter)}`;
			if (seniorityFilter) url += `&seniority=${encodeURIComponent(seniorityFilter)}`;
			if (minExp) url += `&min_exp=${encodeURIComponent(minExp)}`;
			if (maxExp) url += `&max_exp=${encodeURIComponent(maxExp)}`;
			if (minQuality) url += `&min_quality=${encodeURIComponent(minQuality)}`;
			if (maxQuality) url += `&max_quality=${encodeURIComponent(maxQuality)}`;
			if (sourceFilter) url += `&source=${encodeURIComponent(sourceFilter)}`;
			if (tagsChips.length) url += `&tags=${encodeURIComponent(tagsChips.join(','))}`;
			// AI facet selections (canonical csv)
			if (skillSelected.size > 0)     url += `&skills=${encodeURIComponent([...skillSelected].join(','))}`;
			if (companySelected.size > 0)   url += `&companies=${encodeURIComponent([...companySelected].join(','))}`;
			if (locationSelected.size > 0)  url += `&locations=${encodeURIComponent([...locationSelected].join(','))}`;
			if (languageSelected.size > 0)  url += `&languages=${encodeURIComponent([...languageSelected].join(','))}`;
			if (certSelected.size > 0)      url += `&certs=${encodeURIComponent([...certSelected].join(','))}`;
			if (educationSelected.size > 0) url += `&education=${encodeURIComponent([...educationSelected].join(','))}`;
			const data = await apiJson(url);
			candidates = data.candidates || [];
			total = data.total || 0;
			if (data.counts) cvCounts = data.counts;
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error(e); }
		loading = false;
	}

	let cvScope = $state(typeof localStorage !== 'undefined' ? (localStorage.getItem('hire_cv_tab') || 'mine') : 'mine');
	let cvCounts = $state({ mine: 0, sector: 0, pool: 0 });

	// AI facet groups (self-growing filters)
	let facetGroups = $state({});       // { skill: {top, new, total}, ... }
	let facetNewTotal = $state(0);
	let skillSelected = $state(new Set());
	let companySelected = $state(new Set());
	let locationSelected = $state(new Set());
	let languageSelected = $state(new Set());
	let certSelected = $state(new Set());
	let educationSelected = $state(new Set());
	let facetPollHandle = null;
	async function loadFacetGroups() {
		try {
			const data = await apiJson('/facets/groups');
			facetGroups = data.groups || {};
			facetNewTotal = data.new_total || 0;
		} catch { /* silent */ }
	}
	async function dismissFacetNew(facetId) {
		try { await apiJson(`/facets/dismiss/${facetId}`, { method: 'POST' }); } catch {}
	}

	// ─── Unified row state (Option A split pane) ───
	let pendingRows = $state([]);                    // /candidates/pending?include_recent=true rows
	let pendingPollHandle = null;
	let stateFilter = $state('all');                  // all|pending|running|done|error
	let roleSelected = $state(new Set());             // Set<string>
	let attachedSelected = $state(new Set());         // 'senior_pm' | 'driver_pool' | 'unattached'
	let uploadedRange = $state('all');                // today | 7d | 30d | 90d | all
	let qScoreMin = $state(0);                        // 0..100 client-side quality threshold
	let activeTraces = $state({});                    // {cid: run_id}
	let queueRunning = $state(new Set());             // cids actively running
	let queuePositions = $state({});                  // {cid: queueIndex (1-based)}
	let queueDepth = $state(0);
	let queueMaxParallel = $state(4);
	let queuePollHandle;
	async function loadQueueStatus() {
		try {
			const d = await apiJson('/candidates/queue-status');
			queueRunning = new Set(d.running || []);
			const pos = {};
			(d.queued || []).forEach(q => { pos[q.cid] = q.position; });
			queuePositions = pos;
			queueDepth = d.queue_depth || 0;
			queueMaxParallel = d.max_parallel || 4;
		} catch {}
	}
	let dismissedPending = $state(new Set());

	const DISMISS_KEY = 'hire_dismissed_pending';
	function loadDismissedPending() {
		try {
			const raw = (typeof window !== 'undefined') ? localStorage.getItem(DISMISS_KEY) : null;
			if (raw) dismissedPending = new Set(JSON.parse(raw));
		} catch {}
	}
	function persistDismissed() {
		try { localStorage.setItem(DISMISS_KEY, JSON.stringify([...dismissedPending])); } catch {}
	}
	function dismissPendingRow(cid) {
		const s = new Set(dismissedPending);
		s.add(cid);
		dismissedPending = s;
		persistDismissed();
	}

	let _lastRunSig = '';
	async function loadPendingRows() {
		try {
			const data = await apiJson('/candidates/pending?include_recent=true');
			const prev = pendingRows;
			pendingRows = data.candidates || [];
			// Detect state transitions (running→done OR done_steps changed) → reload candidates list
			const sig = pendingRows.map(r => {
				const lr = r.latest_run || {};
				return `${r.id}:${r.is_processed?1:0}:${lr.done_steps||0}:${lr.has_running?'R':''}:${lr.has_error?'E':''}`;
			}).join('|');
			if (sig !== _lastRunSig) {
				_lastRunSig = sig;
				// Any state changed → refresh processed-candidates list so done rows update
				loadCandidates();
			}
			// Clear activeTraces for any cid that finished or errored
			const clear = { ...activeTraces };
			let changed = false;
			for (const r of pendingRows) {
				const lr = r.latest_run || {};
				const finished = (lr.total_steps && lr.done_steps >= lr.total_steps) || lr.has_error || r.is_processed;
				if (finished && clear[r.id]) { delete clear[r.id]; changed = true; }
			}
			if (changed) activeTraces = clear;
			// Drop stale dismissed IDs when the matching row was clearly created AFTER
			// dismissal (heuristic: IDs reused after DB nuke). On first poll, prune any
			// dismissed ID whose pending row created_at is within the last 1 hour
			// (treat as a freshly uploaded file the user didn't intend to dismiss).
			if (!_dismissedPruned && dismissedPending.size > 0) {
				const cutoff = Date.now() - 3600 * 1000;
				const drop = new Set();
				for (const r of pendingRows) {
					if (!dismissedPending.has(r.id)) continue;
					const ts = new Date(r.created_at || 0).getTime();
					if (ts > cutoff) drop.add(r.id);
				}
				if (drop.size > 0) {
					const next = new Set([...dismissedPending].filter(id => !drop.has(id)));
					dismissedPending = next;
					persistDismissed();
				}
				_dismissedPruned = true;
			}
		} catch { /* silent */ }
	}
	let _dismissedPruned = false;

	// Derive state for a row (pending|running|done|error)
	function rowState(c) {
		const r = c.latest_run || {};
		if (r.has_error || c.processing_error) return 'error';
		if (r.has_running) return 'running';
		const isDone = (r.total_steps && r.done_steps >= r.total_steps) || c.is_processed === true;
		if (isDone) return 'done';
		return 'pending';
	}

	function fmtSize(b) {
		if (!b) return '';
		if (b < 1024) return `${b}B`;
		if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)}KB`;
		return `${(b / 1024 / 1024).toFixed(1)}MB`;
	}

	// Merge pending rows + processed candidates → unified list, dedup by id, hide dismissed
	let unifiedRows = $derived.by(() => {
		const map = new Map();
		// Start with processed candidates (full data)
		for (const c of candidates) {
			map.set(c.id, { ...c, _src: 'candidate' });
		}
		// Overlay/insert pending rows
		for (const p of pendingRows) {
			if (dismissedPending.has(p.id)) continue;
			const existing = map.get(p.id);
			if (existing) {
				// Enrich with pipeline_trace info from /pending payload
				map.set(p.id, { ...existing, latest_run: p.latest_run, file_name: p.file_name || existing.file_name, file_type: p.file_type || existing.file_type, file_size: p.file_size, processing_error: p.processing_error, is_processed: p.is_processed });
			} else {
				map.set(p.id, { ...p, _src: 'pending' });
			}
		}
		// Filter: drop dismissed ONLY for pending-only rows (not processed candidates).
		// dismissedPending stores IDs of files user hid from pending queue; processed
		// candidates from /candidates list should always show (covers ID-reuse after DB nuke).
		const arr = [...map.values()].filter(r => {
			if (r._src === 'candidate') return true;
			return !dismissedPending.has(r.id);
		});
		// Sort: queue-running first, then pending, then by updated/created desc
		const order = { running: 0, pending: 1, error: 2, done: 3 };
		arr.sort((a, b) => {
			const ar = queueRunning.has(a.id) ? 0 : order[rowState(a)];
			const br = queueRunning.has(b.id) ? 0 : order[rowState(b)];
			if (ar !== br) return ar - br;
			const ta = new Date(a.updated_at || a.created_at || 0).getTime();
			const tb = new Date(b.updated_at || b.created_at || 0).getTime();
			return tb - ta;
		});
		return arr;
	});

	// State counts (over the full unified list before state filter)
	let stateCounts = $derived.by(() => {
		const out = { all: 0, pending: 0, running: 0, done: 0, error: 0 };
		for (const r of unifiedRows) {
			out.all++;
			out[rowState(r)]++;
		}
		return out;
	});

	// Top-6 role facets
	let roleFacets = $derived.by(() => {
		const m = new Map();
		for (const r of unifiedRows) {
			const role = (r.current_role || '').trim();
			if (!role) continue;
			m.set(role, (m.get(role) || 0) + 1);
		}
		return [...m.entries()]
			.sort((a, b) => b[1] - a[1])
			.slice(0, 6)
			.map(([value, count]) => ({ value, count }));
	});

	// Attached facets
	let attachedFacets = $derived.by(() => {
		// Group by first assignment slug; else 'unattached'
		const m = new Map();
		const labels = new Map();
		let unattached = 0;
		for (const r of unifiedRows) {
			const a = (r.assignments || [])[0];
			if (a && a.slug) {
				m.set(a.slug, (m.get(a.slug) || 0) + 1);
				labels.set(a.slug, a.title || a.slug);
			} else {
				unattached++;
			}
		}
		const out = [...m.entries()]
			.sort((x, y) => y[1] - x[1])
			.slice(0, 5)
			.map(([value, count]) => ({ value, count, label: labels.get(value) || value }));
		out.push({ value: '__unattached', count: unattached, label: 'Unattached' });
		return out;
	});

	// Final visible rows after state + role + attached + uploaded + qScore filters
	let visibleRows = $derived.by(() => {
		const now = Date.now();
		const rangeMs = (() => {
			switch (uploadedRange) {
				case 'today': return 24 * 3600 * 1000;
				case '7d': return 7 * 24 * 3600 * 1000;
				case '30d': return 30 * 24 * 3600 * 1000;
				case '90d': return 90 * 24 * 3600 * 1000;
				default: return null;
			}
		})();
		const minQ = Number(qScoreMin) || 0;
		return unifiedRows.filter(r => {
			if (stateFilter !== 'all' && rowState(r) !== stateFilter) return false;
			if (roleSelected.size > 0) {
				const role = (r.current_role || '').trim();
				if (!roleSelected.has(role)) return false;
			}
			if (attachedSelected.size > 0) {
				const a = (r.assignments || [])[0];
				const key = a?.slug || '__unattached';
				if (!attachedSelected.has(key)) return false;
			}
			if (rangeMs !== null) {
				const ts = new Date(r.created_at || r.updated_at || 0).getTime();
				if (!ts || (now - ts) > rangeMs) return false;
			}
			if (minQ > 0) {
				const q = Number(r.quality_score) || 0;
				if (q < minQ) return false;
			}
			return true;
		});
	});

	function clearAllRailFilters() {
		stateFilter = 'all';
		roleSelected = new Set();
		attachedSelected = new Set();
		uploadedRange = 'all';
		qScoreMin = 0;
		skillSelected = new Set();
		companySelected = new Set();
		locationSelected = new Set();
		languageSelected = new Set();
		certSelected = new Set();
		educationSelected = new Set();
		try { localStorage.removeItem('hire_ai_facets'); } catch {}
		cvScope = 'mine';
		setCvScope('mine');
	}

	// Reload candidates when any AI facet selection changes (debounced via microtask).
	let _aiSig = $derived(
		[...skillSelected].sort().join('|') + '#' +
		[...companySelected].sort().join('|') + '#' +
		[...locationSelected].sort().join('|') + '#' +
		[...languageSelected].sort().join('|') + '#' +
		[...certSelected].sort().join('|') + '#' +
		[...educationSelected].sort().join('|')
	);
	let _aiSigPrev = '';
	$effect(() => {
		const sig = _aiSig;
		untrack(() => {
			if (sig !== _aiSigPrev) {
				_aiSigPrev = sig;
				candOffset = 0;
				loadCandidates();
			}
		});
	});

	// Status bar totals
	let statusTotals = $derived.by(() => {
		let cost = 0, runs = 0, runningCount = 0, doneCount = 0;
		for (const r of unifiedRows) {
			const lr = r.latest_run || {};
			if (lr.total_cost) cost += Number(lr.total_cost) || 0;
			if (lr.run_id) runs++;
			const st = rowState(r);
			if (st === 'running') runningCount++;
			if (st === 'done') doneCount++;
		}
		return { cost, runs, runningCount, doneCount };
	});

	async function cancelOneRow(cid, ev) {
		ev?.stopPropagation?.();
		try {
			const r = await apiJson(`/candidates/${cid}/cancel`, { method: 'POST' });
			if (r.cancelled) {
				addToast('info', `Pipeline cancelled (cid ${cid})`);
			} else {
				addToast('info', `No active task to cancel (cid ${cid})`);
			}
			delete activeTraces[cid];
			activeTraces = { ...activeTraces };
			setTimeout(loadPendingRows, 500);
		} catch (e) { addToast('error', `Cancel failed: ${e.message || e}`); }
	}
	async function cancelAll() {
		if (!confirm('Stop ALL running pipelines? In-flight steps will be aborted.')) return;
		try {
			const r = await apiJson('/candidates/cancel-all', { method: 'POST' });
			addToast('success', `Cancelled ${r.cancelled} pipeline(s)`);
			activeTraces = {};
			setTimeout(loadPendingRows, 500);
		} catch (e) { addToast('error', `Cancel-all failed: ${e.message || e}`); }
	}

	async function runOneRow(cid, ev) {
		ev?.stopPropagation?.();
		// Optimistic: disable button + show "STARTING…" immediately
		activeTraces = { ...activeTraces, [cid]: 'starting' };
		try {
			// /process throws 409 if already processed → fall back to /reprocess
			let r;
			try {
				r = await apiJson(`/candidates/${cid}/process`, { method: 'POST' });
			} catch (e1) {
				if (String(e1.message || '').match(/409|already/i)) {
					r = await apiJson(`/candidates/${cid}/reprocess`, { method: 'POST' });
				} else { throw e1; }
			}
			activeTraces = { ...activeTraces, [cid]: r.run_id || 'running' };
			addToast('success', `Pipeline started · ${(r.run_id || '').slice(0,8)}`);
			cliEvent('success', `Pipeline started — run ${(r.run_id || '').slice(0,8)}`);
			setTimeout(loadPendingRows, 600);
		} catch (e) {
			// Roll back optimistic flag on failure
			const rb = { ...activeTraces };
			if (rb[cid] === 'starting') delete rb[cid];
			activeTraces = rb;
			addToast('error', `Run failed: ${e.message || e}`);
			cliEvent('error', `Run failed: ${e.message || e}`);
		}
	}

	async function retryRow(cid, ev) { return runOneRow(cid, ev); }

	async function deletePendingRow(cid, ev) {
		ev?.stopPropagation?.();
		if (!confirm('Delete this file permanently? Cannot be undone.')) return;
		try {
			await apiJson(`/candidates/${cid}?hard=true`, { method: 'DELETE' });
			pendingRows = pendingRows.filter(r => r.id !== cid);
			candidates = candidates.filter(r => r.id !== cid);
			loadPendingRows(); loadCandidates();
		} catch (e) { console.error(`Delete failed: ${e.message}`); }
	}

	// ── j/k row navigation ──
	let focusedRowIdx = $state(-1);
	let cvTableRoot = $state(null);
	function isTypingTargetCv(el) {
		if (!el) return false;
		const tag = el.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
	}
	function focusCvRow(idx) {
		if (!cvTableRoot) return;
		const rows = cvTableRoot.querySelectorAll('[data-row-idx]');
		if (!rows.length) return;
		const c = Math.max(0, Math.min(rows.length - 1, idx));
		focusedRowIdx = c;
		rows[c]?.focus();
		rows[c]?.scrollIntoView({ block: 'nearest' });
	}
	function onCvTableKey(e) {
		if (isTypingTargetCv(e.target)) return;
		if (!visibleRows.length) return;
		if (e.key === 'j') { e.preventDefault(); focusCvRow(focusedRowIdx < 0 ? 0 : focusedRowIdx + 1); }
		else if (e.key === 'k') { e.preventDefault(); focusCvRow(focusedRowIdx < 0 ? 0 : focusedRowIdx - 1); }
		else if (e.key === 'Enter' && focusedRowIdx >= 0) {
			const r = visibleRows[focusedRowIdx];
			if (r) { e.preventDefault(); handleRowClick(r); }
		} else if ((e.key === 'x' || e.key === 'X') && focusedRowIdx >= 0) {
			const r = visibleRows[focusedRowIdx];
			if (r) { e.preventDefault(); dismissPendingRow(r.id); }
		}
	}

	function handleRowClick(r) {
		const st = rowState(r);
		if (st === 'running') return;
		// Always open candidate profile (record exists even before pipeline completes)
		goto(`/candidates/${r.id}`);
	}

	let previewType = $state('');

	async function runVisibleSelected() {
		if (selectedIds.size === 0) return;
		const ids = [...selectedIds];
		await runIds(ids, 'Selection', true);
		selectedIds = new Set();
	}

	async function runIds(ids, label, force = true) {
		if (!ids.length) {
			addToast('info', `Nothing to run for "${label}"`);
			cliEvent('info', `Nothing to run (${label})`);
			return;
		}
		addToast('info', `${label}: enqueuing ${ids.length}…`);
		try {
			const r = await apiJson('/candidates/bulk_process', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: ids, force }),
			});
			const n = r.count || Object.keys(r.started || {}).length;
			const skip = (r.skipped || []).length;
			addToast('success', `${label}: ${n} enqueued${skip ? `, ${skip} skipped` : ''} · queue depth ${r.queue_depth ?? '?'}`);
			cliEvent('success', `${label}: ${n} enqueued (queue depth ${r.queue_depth ?? '?'})`);
			loadQueueStatus();
			setTimeout(loadPendingRows, 600);
		} catch (e) {
			addToast('error', `${label} failed: ${e.message || e}`);
			cliEvent('error', `${label} failed: ${e.message}`);
		}
	}
	async function runAllVisible() {
		const ids = visibleRows.map(r => r.id);
		await runIds(ids, 'Run all', true);
	}
	async function runOnlyPending() {
		const ids = visibleRows.filter(r => rowState(r) === 'pending' || rowState(r) === 'error').map(r => r.id);
		await runIds(ids, 'Run pending', false);
	}

	onMount(() => {
		loadDismissedPending();
		loadPendingRows();
		loadFacetGroups();
		loadQueueStatus();
		pendingPollHandle = setInterval(loadPendingRows, 3000);
		facetPollHandle = setInterval(loadFacetGroups, 30000);
		queuePollHandle = setInterval(loadQueueStatus, 1500);
		return () => {
			if (pendingPollHandle) clearInterval(pendingPollHandle);
			if (facetPollHandle) clearInterval(facetPollHandle);
			if (queuePollHandle) clearInterval(queuePollHandle);
		};
	});

	function fmtRel(iso) {
		if (!iso) return '—';
		const d = new Date(iso);
		const s = (Date.now() - d.getTime()) / 1000;
		if (s < 60) return `${Math.round(s)}s ago`;
		if (s < 3600) return `${Math.round(s / 60)}m ago`;
		if (s < 86400) return `${Math.round(s / 3600)}h ago`;
		return d.toLocaleDateString();
	}
	function setCvScope(s) {
		cvScope = s; candOffset = 0;
		try { localStorage.setItem('hire_cv_tab', s); } catch {}
		loadCandidates();
	}

	let cvShareOpenId = $state(null);
	let cvSharePos = $state({ top: 0, left: 0 });
	async function shareCvMulti(cid, payload, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		try {
			await apiJson(`/candidates/${cid}/share`, {
				method: 'POST',
				body: JSON.stringify(payload),
			});
			addToast('success', `Share updated · sector=${payload.shared_sector} pool=${payload.shared_global}`);
			await loadCandidates();
		} catch (e) {
			addToast('error', `Share failed: ${e.message}`);
		}
	}

	async function shareCv(cid, vis, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		try {
			await apiJson(`/candidates/${cid}/share`, { method: 'POST', body: JSON.stringify({ visibility: vis }) });
			addToast('success', `Candidate shared → ${vis}`);
			cvShareOpenId = null;
			await loadCandidates();
		} catch (e) {
			addToast('error', `Share failed: ${e.message}`);
		}
	}
	function toggleCvShare(id, ev) {
		ev?.preventDefault?.(); ev?.stopPropagation?.();
		if (cvShareOpenId === id) { cvShareOpenId = null; return; }
		const r = ev.currentTarget.getBoundingClientRect();
		cvSharePos = { top: r.bottom + 4, left: Math.max(8, r.right - 220) };
		cvShareOpenId = id;
	}
	function closeCvShare() { cvShareOpenId = null; }

	// ─── CV Table filters & sort ───
	const _persistedCv = (() => {
		try { return JSON.parse(localStorage.getItem('hire_cv_table') || '{}'); }
		catch { return {}; }
	})();
	let cvSortCol  = $state(_persistedCv.sortCol || 'created_at');
	let cvSortDir  = $state(_persistedCv.sortDir || 'desc');
	let cvFilterCreatedBy  = $state(_persistedCv.createdBy || '');
	let cvFilterModifiedBy = $state(_persistedCv.modifiedBy || '');
	let cvFilterCreated  = $state(_persistedCv.createdRange || 'all');
	let cvFilterModified = $state(_persistedCv.modifiedRange || 'all');

	let cvUserOptions = $state([]);
	async function loadCvUserOptions() {
		try {
			const r = await apiJson('/auth/users/lookup?limit=50');
			cvUserOptions = r.users || [];
		} catch {}
	}

	function cvRangeBoundary(p) {
		if (p === 'today') { const d = new Date(); d.setHours(0,0,0,0); return d.toISOString(); }
		if (p === '24h')  return new Date(Date.now() - 86400e3).toISOString();
		if (p === '7d')   return new Date(Date.now() - 7*86400e3).toISOString();
		if (p === '30d')  return new Date(Date.now() - 30*86400e3).toISOString();
		return null;
	}

	function cvPersist() {
		try {
			localStorage.setItem('hire_cv_table', JSON.stringify({
				sortCol: cvSortCol, sortDir: cvSortDir,
				createdBy: cvFilterCreatedBy, modifiedBy: cvFilterModifiedBy,
				createdRange: cvFilterCreated, modifiedRange: cvFilterModified,
			}));
		} catch {}
	}

	function cvSortClick(col) {
		if (cvSortCol === col) cvSortDir = cvSortDir === 'asc' ? 'desc' : 'asc';
		else { cvSortCol = col; cvSortDir = 'desc'; }
		cvPersist(); loadCandidates();
	}
	function cvSortIcon(col) { return cvSortCol === col ? (cvSortDir === 'asc' ? '▲' : '▼') : ''; }
	function cvApplyFilters() { cvPersist(); loadCandidates(); }

	function cvTimeAgo(iso) {
		if (!iso) return '—';
		const d = new Date(iso); const diff = (Date.now() - d.getTime()) / 1000;
		if (diff < 60) return 'just now';
		if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
		if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
		if (diff < 30*86400) return `${Math.floor(diff/86400)}d ago`;
		return d.toLocaleDateString();
	}
	function cvFmtAbs(iso) {
		if (!iso) return '';
		const d = new Date(iso);
		const sameYear = d.getFullYear() === new Date().getFullYear();
		const dateOpts = sameYear ? { day: '2-digit', month: 'short' } : { day: '2-digit', month: 'short', year: 'numeric' };
		return d.toLocaleDateString(undefined, dateOpts)
			+ ' · ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	}

	function handleDrop(e) {
		e.preventDefault();
		dragOver = false;
		if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
	}

	// Drag-drop polish — document-level overlay; drag any file anywhere → upload
	$effect(() => {
		if (typeof document === 'undefined') return;
		let depth = 0;
		const isFileDrag = (e) => e.dataTransfer?.types?.includes?.('Files');
		const onEnter = (e) => { if (!isFileDrag(e)) return; depth++; dragOver = true; };
		const onOver  = (e) => { if (!isFileDrag(e)) return; e.preventDefault(); };
		const onLeave = (e) => { if (!isFileDrag(e)) return; depth = Math.max(0, depth - 1); if (depth === 0) dragOver = false; };
		const onDrop  = (e) => {
			if (!isFileDrag(e)) return;
			e.preventDefault();
			depth = 0;
			dragOver = false;
			const files = [...(e.dataTransfer?.files || [])].filter(f =>
				/\.(pdf|docx?|png|jpe?g)$/i.test(f.name)
			);
			if (files.length) uploadFiles(files);
		};
		document.addEventListener('dragenter', onEnter);
		document.addEventListener('dragover', onOver);
		document.addEventListener('dragleave', onLeave);
		document.addEventListener('drop', onDrop);
		return () => {
			document.removeEventListener('dragenter', onEnter);
			document.removeEventListener('dragover', onOver);
			document.removeEventListener('dragleave', onLeave);
			document.removeEventListener('drop', onDrop);
		};
	});

	async function uploadFiles(fileList) {
		uploading = true;
		uploadResults = [];
		const items = [...fileList].map(f => ({
			id: (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
			file: f,
			name: f.name,
			size: f.size,
			progress: 0,
			status: 'queued',
		}));
		uploadingFiles = [...uploadingFiles, ...items];

		// Concurrency cap: 4 parallel uploads
		const queue = [...items];
		const workers = Array(Math.min(4, queue.length)).fill(null).map(async () => {
			while (queue.length) {
				const it = queue.shift();
				await uploadOne(it);
			}
		});
		await Promise.all(workers);

		const ok = items.filter(it => it.status === 'done').length;
		const dup = items.filter(it => it.status === 'duplicate').length;
		const err = items.filter(it => it.status === 'error').length;
		const parts = [];
		if (ok)  parts.push(`${ok} new`);
		if (dup) parts.push(`${dup} duplicate (skipped)`);
		if (err) parts.push(`${err} error`);
		cliEvent(dup && !ok ? 'warn' : 'success', `Upload result: ${parts.join(' · ')}`);

		// 3s after all done, drop completed entries from the tracker (component also auto-collapses)
		setTimeout(() => {
			uploadingFiles = uploadingFiles.filter(it => it.status !== 'done' && it.status !== 'duplicate');
		}, 3000);

		uploading = false;
		if (ok > 0 && cvScope !== 'mine') { cvScope = 'mine'; candOffset = 0; }
		loadCandidates();
		loadPendingRows();
	}

	function uploadOne(item) {
		return new Promise(resolve => {
			const xhr = new XMLHttpRequest();
			const fd = new FormData();
			fd.append('files', item.file);
			fd.append('force_type', 'CV');
			fd.append('auto_process', 'false');

			item.status = 'uploading';
			uploadingFiles = [...uploadingFiles];

			xhr.upload.onprogress = (e) => {
				if (e.lengthComputable) {
					item.progress = Math.round(100 * e.loaded / e.total);
					uploadingFiles = [...uploadingFiles];
				}
			};
			xhr.onload = () => {
				item.progress = 100;
				const ok = xhr.status >= 200 && xhr.status < 300;
				item.status = ok ? 'done' : 'error';
				// Parse response → fire dedup toast if backend skipped pipeline
				if (ok) {
					try {
						const d = JSON.parse(xhr.responseText || '{}');
						for (const r of (d.results || [])) {
							if (r.deduped && r.target_id) {
								item.status = 'duplicate';
								window.dispatchEvent(new CustomEvent('pulse-toast', { detail: {
									kind: 'dedup',
									filename: r.filename || item.file?.name || '',
									candidateId: r.target_id,
									text: `already in repo · cv_${r.target_id} · skipped pipeline`,
									ttl: 6000
								}}));
							}
						}
					} catch { /* ignore parse */ }
				}
				uploadingFiles = [...uploadingFiles];
				resolve();
			};
			xhr.onerror = () => {
				item.status = 'error';
				uploadingFiles = [...uploadingFiles];
				resolve();
			};
			xhr.open('POST', '/api/ingest/');
			// Match auth pattern from frontend/src/lib/api.ts (Bearer token from localStorage)
			try {
				const token = (typeof window !== 'undefined') ? localStorage.getItem('hire_token') : null;
				if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
			} catch { /* ignore */ }
			xhr.send(fd);
		});
	}

	let previewCid = $state(null);
	let previewFilename = $state('');
	let runPipelineBusy = $state(false);
	async function runPipelineNow(cid) {
		runPipelineBusy = true;
		try {
			const r = await apiJson(`/candidates/${cid}/process`, { method: 'POST' });
			cliEvent('success', `Pipeline started — run ${(r.run_id || '').slice(0, 8)}`);
			// Open live progress modal + close preview
			uploadQueue = [...uploadQueue, { candidateId: cid, runId: r.run_id, filename: previewFilename || `cv-${cid}` }];
			previewCid = null;
			setTimeout(() => loadCandidates(), 2000);
		} catch (e) {
			cliEvent('error', `Run failed: ${e.message || e}`);
		}
		runPipelineBusy = false;
	}

	async function viewCandidate(id) {
		try {
			selectedCandidate = await apiJson(`/candidates/${id}`);
			selectedCvId = id;
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error(e); }
	}

	function doSearch() {
		if (aiSearchEnabled && searchQuery.trim()) {
			doAiSearch();
		} else {
			aiSearchInterpretation = '';
			loadCandidates();
		}
	}

	async function doAiSearch() {
		aiSearchLoading = true;
		aiSearchInterpretation = '';
		loading = true;
		try {
			const data = await apiJson('/candidates/smart-search', {
				method: 'POST',
				body: JSON.stringify({ query: searchQuery }),
			});
			candidates = data.candidates || [];
			total = data.total || candidates.length;
			if (data.interpretation) {
				aiSearchInterpretation = data.interpretation;
			} else if (data.parsed) {
				const parts = [];
				if (data.parsed.skills?.length) parts.push(`skills=${data.parsed.skills.join(',')}`);
				if (data.parsed.min_exp) parts.push(`min_exp=${data.parsed.min_exp}`);
				if (data.parsed.location) parts.push(`location=${data.parsed.location}`);
				if (data.parsed.seniority) parts.push(`seniority=${data.parsed.seniority}`);
				if (data.parsed.role) parts.push(`role=${data.parsed.role}`);
				aiSearchInterpretation = parts.length > 0 ? `Interpreted: ${parts.join(', ')}` : '';
			}
		} catch (e) {
			console.error('AI search failed:', e);
			cliEvent('error', `AI search failed: ${e.message}`);
		}
		loading = false;
		aiSearchLoading = false;
	}

	function clearAllFilters() {
		skillsChips = [];
		skillsInput = '';
		locationFilter = '';
		companyFilter = '';
		seniorityFilter = '';
		minExp = '';
		maxExp = '';
		minQuality = '';
		maxQuality = '';
		sourceFilter = '';
		tagsChips = [];
		tagsInput = '';
		loadCandidates();
	}

	// --- Chip helpers ---
	function addSkillChip(e) {
		if (e.key === 'Enter' && skillsInput.trim()) {
			const val = skillsInput.trim().toLowerCase();
			if (!skillsChips.includes(val)) skillsChips = [...skillsChips, val];
			skillsInput = '';
		}
	}
	function removeSkillChip(skill) {
		skillsChips = skillsChips.filter(s => s !== skill);
	}
	function addTagChip(e) {
		if (e.key === 'Enter' && tagsInput.trim()) {
			const val = tagsInput.trim().toLowerCase();
			if (!tagsChips.includes(val)) tagsChips = [...tagsChips, val];
			tagsInput = '';
		}
	}
	function removeTagChip(tag) {
		tagsChips = tagsChips.filter(t => t !== tag);
	}

	// --- Bulk selection helpers ---
	function toggleSelect(id) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id); else next.add(id);
		selectedIds = next;
	}
	function toggleSelectAll() {
		if (allSelected) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(candidates.map(c => c.id));
		}
	}
	function clearSelection() { selectedIds = new Set(); }

	async function bulkMoveStage() {
		if (!bulkStage || selectedIds.size === 0) return;
		bulkLoading = true;
		try {
			await apiJson('/bulk/move-stage', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [...selectedIds], stage: bulkStage }),
			});
			cliEvent('success', `Moved ${selectedIds.size} candidate(s) to ${bulkStage}`);
			clearSelection();
			loadCandidates();
		} catch (e) { cliEvent('error', `Bulk move failed: ${e.message}`); }
		bulkLoading = false;
	}

	async function bulkAddToPosition() {
		if (!bulkPositionSlug || selectedIds.size === 0) return;
		bulkLoading = true;
		try {
			await apiJson('/bulk/add-to-position', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [...selectedIds], position_slug: bulkPositionSlug }),
			});
			cliEvent('success', `Added ${selectedIds.size} candidate(s) to position`);
			clearSelection();
		} catch (e) { cliEvent('error', `Bulk add failed: ${e.message}`); }
		bulkLoading = false;
	}

	async function bulkReject() {
		if (selectedIds.size === 0) return;
		bulkLoading = true;
		try {
			await apiJson('/bulk/reject', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: [...selectedIds] }),
			});
			cliEvent('success', `Rejected ${selectedIds.size} candidate(s)`);
			clearSelection();
			loadCandidates();
		} catch (e) { cliEvent('error', `Bulk reject failed: ${e.message}`); }
		bulkLoading = false;
	}

	async function bulkDeleteCandidates() {
		if (selectedIds.size === 0) return;
		const n = selectedIds.size;
		if (!confirm(`Permanently delete ${n} CV${n > 1 ? 's' : ''}? This cannot be undone.`)) return;
		bulkLoading = true;
		try {
			const ids = [...selectedIds];
			// Optimistic remove
			candidates = candidates.filter(c => !selectedIds.has(c.id));
			await apiJson('/bulk/delete-candidates', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: ids }),
			});
			cliEvent('success', `Deleted ${n} CV(s)`);
			clearSelection();
			loadCandidates();
		} catch (e) {
			cliEvent('error', `Bulk delete failed: ${e.message}`);
			loadCandidates();
		}
		bulkLoading = false;
	}

	// --- Compare helpers ---
	function toggleCompare(id) {
		const next = new Set(compareIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			if (next.size >= 5) { cliEvent('error', 'Maximum 5 candidates for comparison'); return; }
			next.add(id);
		}
		compareIds = next;
	}

	async function openComparison() {
		if (compareIds.size < 2) { cliEvent('error', 'Select at least 2 candidates to compare'); return; }
		compareLoading = true;
		showCompareModal = true;
		try {
			const body = { candidate_ids: [...compareIds] };
			if (comparePositionSlug) body.position_slug = comparePositionSlug;
			comparisonData = await apiJson('/matching/compare', {
				method: 'POST',
				body: JSON.stringify(body),
			});
		} catch (e) {
			cliEvent('error', `Comparison failed: ${e.message}`);
			comparisonData = null;
		}
		compareLoading = false;
	}

	function scrollToRow(cid) {
		const el = document.querySelector(`[data-cid="${cid}"]`);
		if (el) {
			el.scrollIntoView({ behavior: 'smooth', block: 'center' });
			el.classList.add('row-flash');
			setTimeout(() => el.classList.remove('row-flash'), 1500);
		}
	}

	function closeComparison() {
		showCompareModal = false;
		comparisonData = null;
	}

	let comparisonAiLoading = $state(false);
	async function regenerateComparisonSummary() {
		if (!comparisonData?.candidates?.length) return;
		comparisonAiLoading = true;
		try {
			const ids = comparisonData.candidates.map(c => c.candidate_id);
			const r = await apiJson('/matching/compare', {
				method: 'POST',
				body: JSON.stringify({ candidate_ids: ids }),
			});
			if (r?.comparison_summary) {
				comparisonData = { ...comparisonData, comparison_summary: r.comparison_summary };
				addToast('success', 'AI summary regenerated');
			} else {
				addToast('error', 'AI summary unavailable');
			}
		} catch (e) {
			addToast('error', `AI failed: ${e.message || e}`);
		}
		comparisonAiLoading = false;
	}

	async function exportComparisonXlsx() {
		if (!comparisonData?.candidates?.length) return;
		try {
			const ids = comparisonData.candidates.map(c => c.candidate_id).join(',');
			const res = await api(`/matching/compare/export.xlsx?ids=${ids}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const blob = await res.blob();
			const u = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = u; a.download = 'pulse-comparison.xlsx'; a.click();
			URL.revokeObjectURL(u);
			addToast('success', 'Excel downloaded');
		} catch (e) {
			addToast('error', `Export failed: ${e.message || e}`);
		}
	}

	// --- Saved search functions ---
	async function loadSavedSearches() {
		try {
			const data = await apiJson('/saved-searches');
			savedSearches = data.searches || [];
		} catch (e) { addToast('error', e.message || 'Something went wrong'); console.error('Failed to load saved searches:', e); }
	}

	function getCurrentFilters() {
		return {
			search: searchQuery || undefined,
			skills: skillsChips.length ? skillsChips.join(',') : undefined,
			location: locationFilter || undefined,
			company: companyFilter || undefined,
			seniority: seniorityFilter || undefined,
			min_exp: minExp || undefined,
			max_exp: maxExp || undefined,
			min_quality: minQuality || undefined,
			max_quality: maxQuality || undefined,
			source: sourceFilter || undefined,
			tags: tagsChips.length ? tagsChips.join(',') : undefined,
		};
	}

	let hasActiveFilters = $derived(searchQuery || activeFilterCount > 0);

	async function saveCurrentSearch() {
		const name = prompt('Name this saved search:');
		if (!name) return;
		savingSearch = true;
		try {
			await apiJson('/saved-searches', {
				method: 'POST',
				body: JSON.stringify({
					name,
					filters: getCurrentFilters(),
					notify_on_match: false,
				}),
			});
			cliEvent('success', `Search "${name}" saved`);
			await loadSavedSearches();
		} catch (e) {
			cliEvent('error', `Save failed: ${e.message}`);
		}
		savingSearch = false;
	}

	async function applySavedSearch(search) {
		const f = search.filters || {};
		searchQuery = f.search || '';
		skillsChips = f.skills ? f.skills.split(',').filter(Boolean) : [];
		locationFilter = f.location || '';
		companyFilter = f.company || '';
		seniorityFilter = f.seniority || '';
		minExp = f.min_exp || '';
		maxExp = f.max_exp || '';
		minQuality = f.min_quality || '';
		maxQuality = f.max_quality || '';
		sourceFilter = f.source || '';
		tagsChips = f.tags ? f.tags.split(',').filter(Boolean) : [];
		showSavedSearches = false;
		await loadCandidates();
	}

	async function deleteSavedSearch(id) {
		try {
			await apiJson(`/saved-searches/${id}`, { method: 'DELETE' });
			cliEvent('success', 'Saved search deleted');
			await loadSavedSearches();
		} catch (e) { cliEvent('error', `Delete failed: ${e.message}`); }
	}

	async function toggleSearchAlert(search) {
		try {
			await apiJson(`/saved-searches/${search.id}`, {
				method: 'PATCH',
				body: JSON.stringify({ notify_on_match: !search.notify_on_match }),
			});
			await loadSavedSearches();
		} catch (e) { cliEvent('error', `Toggle failed: ${e.message}`); }
	}

	function cliEvent(type, text) {
		window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type, text } }));
	}

	function scoreClass(score) {
		if (score >= 70) return 'score-high';
		if (score >= 40) return 'score-mid';
		return 'score-low';
	}
</script>

<div class="cv-page-wrap"
	ondragover={(e) => { if (e.dataTransfer?.types?.includes?.('Files')) { e.preventDefault(); dragOver = true; } }}
	ondragleave={(e) => { if (e.target === e.currentTarget) dragOver = false; }}
	ondrop={handleDrop}
>
	{#if dragOver}
		<div class="cv-drop-overlay pulse-drop-overlay" role="presentation">
			<div class="cv-drop-overlay-inner">
				<div class="cv-drop-overlay-plus">+</div>
				<div class="cv-drop-overlay-text">Drop CVs to upload</div>
				<div class="cv-drop-overlay-sub">PDF · DOCX · PNG · JPG</div>
			</div>
		</div>
	{/if}
	<!-- Split body: rail + main pane (title moved INSIDE main to match JD layout) -->
	<input id="cv-upload" type="file" multiple accept=".pdf,.docx,.doc,.png,.jpg,.jpeg" style="display:none;"
		onchange={(e) => { if (e.target.files?.length) uploadFiles(e.target.files); }} />
	<div class="cv-split">
		<div class="cv-rail">
			<CandidateRailFilters
				bind:scope={cvScope}
				scopeCounts={cvCounts}
				onScopeChange={(s) => setCvScope(s)}
				bind:stateFilter
				{stateCounts}
				{roleFacets}
				bind:roleSelected
				{attachedFacets}
				bind:attachedSelected
				bind:uploadedRange
				bind:qScoreMin
				{facetGroups}
				bind:skillSelected
				bind:companySelected
				bind:locationSelected
				bind:languageSelected
				bind:certSelected
				bind:educationSelected
				onDismissFacetNew={dismissFacetNew}
				onClearAll={clearAllRailFilters}
			/>
		</div>

		<main class="cv-main">
	<div style="max-width: 1800px; margin: 0 auto;">

	<!-- Mobile filters trigger (visible <768px) -->
	<button
		type="button"
		class="cv-mobile-filters-pill"
		onclick={() => mobileFiltersOpen = true}
		aria-label="Open filters"
	>
		<span class="material-symbols-outlined" style="font-size: 16px;">tune</span>
		<span>Filters</span>
	</button>

	<!-- Header (inside body, right of rail — matches JD layout) -->
	<div class="flex items-center justify-between mb-6 section-animate" style="position: relative;">
		<div>
			<h1 class="cv-page-title">CV repository</h1>
			<p class="cv-page-sub">
				{stateCounts.all} candidate{stateCounts.all === 1 ? '' : 's'} · build repo with AI or upload
			</p>
		</div>
		<div class="flex gap-2 items-center" style="position: relative;">
			<button
				class="cv-btn {compareMode ? 'cv-btn-primary' : ''}"
				disabled={compareMode && (selectedIds.size < 2 || selectedIds.size > 5)}
				title="Compare 2–5 selected CVs side-by-side"
				onclick={() => { compareMode = !compareMode; if (!compareMode) compareIds = new Set(); }}
			>
				{compareMode ? 'Exit compare' : '⇄ Compare'}
			</button>
			<button class="cv-btn" onclick={() => { window.location.href = '/api/candidates/export.csv'; }} title="Export candidates as CSV">
				Export CSV
			</button>
			<button class="cv-btn cv-btn-primary" onclick={() => document.getElementById('cv-upload')?.click()} title="Upload 1 or more CVs">
				+ Upload CV(s)
			</button>
			<button class="cv-btn" onclick={() => showMore = !showMore} title="More actions">More</button>
			{#if showMore}
				<div class="cv-popover" style="position: absolute; right: 0; top: 100%; margin-top: 6px; z-index: 60; min-width: 180px;">
					<button onclick={() => { showMore = false; window.open('/api/export/candidates/csv'); }}
						class="cv-popover-item">Export CSV</button>
					<button onclick={() => { showMore = false; showImportModal = true; resetImportModal(); }}
						class="cv-popover-item">Import</button>
				</div>
			{/if}
		</div>
	</div>

	<!-- Live multi-file upload tracker -->
	<UploadTracker files={uploadingFiles} />

	<!-- Upload Results -->
	{#if uploadResults.length > 0}
		<div class="mb-4 ink-border p-3 animate-fade-up" style="background: var(--color-surface-bright);">
			<span class="tag-label mb-2" style="display: inline-block;">Upload Results</span>
			{#each uploadResults as r}
				<div class="flex items-center gap-2 py-1" style="font-size: 12px;">
					{#if r.status === 'uploaded'}
						<span style="color: var(--color-primary); display:inline-flex;"><Check size={14} stroke-width={2} /></span>
					{:else}
						<span style="color: var(--color-error); display:inline-flex;"><X size={14} stroke-width={2} /></span>
					{/if}
					<span style="font-weight: 700;">{r.filename}</span>
					<span style="color: var(--color-on-surface-dim);">{r.status === 'uploaded' ? 'Queued for processing' : r.error}</span>
				</div>
			{/each}
		</div>
	{/if}


	<!-- Search Bar -->
	<div class="flex gap-2 mb-2">
		<button
			title="Smart NLP Search — ask in plain English. Try: 'Senior backend engineer with AWS and 5+ years'"
			onclick={() => { aiSearchEnabled = !aiSearchEnabled; aiSearchInterpretation = ''; }}
			class="cv-btn cv-btn-ai"
			class:on={aiSearchEnabled}
		>
			<span class="material-symbols-outlined" style="font-size: 14px;">auto_awesome</span>
			AI
		</button>
		<div style="position: relative; flex: 1; display: flex;">
			<input
				type="text"
				bind:value={searchQuery}
				onfocus={() => { showRecentDropdown = true; recentHighlightIdx = -1; }}
				onblur={() => { setTimeout(() => { showRecentDropdown = false; }, 150); }}
				onkeydown={searchKeydown}
				placeholder={aiSearchEnabled ? "Describe who you're looking for…" : "Search — name, skills, company… (and or not supported)"}
				class="cv-search-input"
				class:ai={aiSearchEnabled}
				style="flex: 1; width: 100%;"
			/>
			{#if showRecentDropdown && recentSearches.length > 0}
				<div class="recent-dropdown">
					<div class="recent-dropdown-head">Recent searches</div>
					{#each recentSearches as term, i}
						<button
							type="button"
							class="recent-item"
							class:active={recentHighlightIdx === i}
							onmousedown={(e) => { e.preventDefault(); applyRecentSearch(term); }}
							onmouseenter={() => recentHighlightIdx = i}
						>
							<span class="material-symbols-outlined" style="font-size: 14px; opacity: 0.55;">history</span>
							<span style="flex: 1; text-align: left;">{term}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>
		<button class="cv-btn cv-btn-rel" onclick={() => { showFilters = !showFilters; filtersOpen = !filtersOpen; }}>
			Filters
			{#if activeFilterCount > 0}
				<span class="cv-badge-count">{activeFilterCount}</span>
			{/if}
		</button>
		<button class="cv-btn" onclick={() => { pushRecentSearch(searchQuery); doSearch(); }}>Search</button>
		<button class="cv-btn cv-btn-accent" onclick={saveLocalSearch} title="Save current search to this browser">
			Save search
		</button>
		{#if hasActiveFilters}
			<button class="cv-btn cv-btn-accent" onclick={saveCurrentSearch} disabled={savingSearch} title="Save to backend (notify on match)">
				{savingSearch ? '…' : 'Save + alert'}
			</button>
		{/if}
		<button class="cv-btn cv-btn-rel" onclick={() => showSavedSearches = !showSavedSearches}>
			Saved
			{#if savedSearches.length > 0}
				<span class="cv-badge-count">{savedSearches.length}</span>
			{/if}
		</button>
	</div>

	<!-- Saved searches pill row (localStorage) -->
	{#if localSavedSearches.length > 0}
		<div class="saved-pill-row">
			<span class="saved-pill-label">Saved:</span>
			{#each localSavedSearches as ss (ss.id)}
				<button class="saved-pill" onclick={() => applyLocalSavedSearch(ss)} title="Apply saved search">
					<span>{ss.name}</span>
					<span class="saved-pill-x" onclick={(e) => deleteLocalSavedSearch(ss.id, e)} title="Remove">×</span>
				</button>
			{/each}
		</div>
	{/if}

	<!-- Saved Searches Dropdown -->
	{#if showSavedSearches}
		<div class="mb-3 ink-border animate-fade-up" style="background: var(--color-surface-bright); max-height: 300px; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between" style="font-size: 10px;">
				<span>Saved Searches</span>
				<button onclick={() => showSavedSearches = false} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 14px; font-weight: 900;">X</button>
			</div>
			{#if savedSearches.length === 0}
				<div class="p-4" style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase; text-align: center;">
					No saved searches yet
				</div>
			{:else}
				{#each savedSearches as ss}
					<div class="flex items-center gap-2 p-3" style="border-bottom: 1px solid var(--color-outline-variant);">
						<button
							onclick={() => applySavedSearch(ss)}
							style="flex: 1; background: none; border: none; text-align: left; cursor: pointer; font-family: 'Space Grotesk';"
						>
							<div style="font-size: 12px; font-weight: 900; text-transform: uppercase;">{ss.name}</div>
							<div style="font-size: 10px; color: var(--color-on-surface-dim);">
								{ss.last_result_count || 0} results
								{#if ss.last_checked_at}
									· checked {new Date(ss.last_checked_at).toLocaleDateString()}
								{/if}
							</div>
						</button>
						<button
							onclick={() => toggleSearchAlert(ss)}
							style="background: none; border: none; cursor: pointer; padding: 4px;"
							title={ss.notify_on_match ? 'Alerts ON — click to disable' : 'Alerts OFF — click to enable'}
						>
							<span class="material-symbols-outlined" style="font-size: 18px; color: {ss.notify_on_match ? 'var(--color-primary)' : 'var(--color-on-surface-dim)'};">
								{ss.notify_on_match ? 'notifications_active' : 'notifications_off'}
							</span>
						</button>
						<button
							onclick={() => deleteSavedSearch(ss.id)}
							style="background: none; border: none; cursor: pointer; padding: 4px;"
							title="Delete saved search"
						>
							<span class="material-symbols-outlined" style="font-size: 16px; color: var(--color-error);">delete</span>
						</button>
					</div>
				{/each}
			{/if}
		</div>
	{/if}

	{#if aiSearchEnabled}
		<p style="font-size: 9px; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px; margin-top: -4px;">
			AI-powered natural language search · e.g. "Senior Python dev with 5+ years, remote"
		</p>
	{/if}

	<!-- AI Search Interpretation -->
	{#if aiSearchInterpretation}
		<div class="mb-3 animate-fade-up" style="padding: 8px 14px; border: 1px solid var(--color-accent, #c96342); border-left-width: 3px; border-radius: 6px; background: rgba(201,99,66,0.06); font-size: 11px; font-weight: 700; color: var(--color-on-surface);">
			<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle; color: var(--color-accent, #c96342);">auto_awesome</span>
			{aiSearchInterpretation}
		</div>
	{/if}

	<!-- Advanced Filters Panel -->
	{#if filtersOpen}
		<div class="mb-4 ink-border p-4 animate-fade-up" style="background: var(--color-surface-bright);">
			<div class="flex items-center justify-between mb-3">
				<span class="tag-label">Advanced Filters</span>
				<button
					style="background: none; border: none; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-error); cursor: pointer; font-family: 'Space Grotesk';"
					onclick={clearAllFilters}
				>
					Clear All Filters
				</button>
			</div>

			<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
				<!-- Skills -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Skills</label>
					<div class="flex flex-wrap gap-1 mb-1">
						{#each skillsChips as chip}
							<span style="display: inline-flex; align-items: center; gap: 4px; font-size: 10px; padding: 2px 8px; border: 2px solid var(--color-on-surface); font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);">
								{chip}
								<button onclick={() => removeSkillChip(chip)} style="background: none; border: none; cursor: pointer; font-size: 12px; font-weight: 900; color: var(--color-error); padding: 0; line-height: 1;">✕</button>
							</span>
						{/each}
					</div>
					<input
						type="text"
						bind:value={skillsInput}
						onkeydown={addSkillChip}
						placeholder="Type skill, press Enter..."
						style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; background: var(--color-surface);"
					/>
				</div>

				<!-- Location -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Location</label>
					<input
						type="text"
						bind:value={locationFilter}
						placeholder="City, country..."
						style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; background: var(--color-surface);"
					/>
				</div>

				<!-- Company -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Company</label>
					<input
						type="text"
						bind:value={companyFilter}
						placeholder="Current company..."
						style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; background: var(--color-surface);"
					/>
				</div>

				<!-- Seniority -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Seniority</label>
					<select bind:value={seniorityFilter}
						style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface);">
						<option value="">All Levels</option>
						{#each seniorityOptions.filter(s => s) as s}
							<option value={s}>{s.toUpperCase()}</option>
						{/each}
					</select>
				</div>

				<!-- Experience Range -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Experience (Years)</label>
					<div class="flex gap-2 items-center">
						<input
							type="number"
							bind:value={minExp}
							placeholder="Min"
							min="0"
							style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; background: var(--color-surface);"
						/>
						<span style="font-size: 11px; font-weight: 900; color: var(--color-on-surface-dim);">—</span>
						<input
							type="number"
							bind:value={maxExp}
							placeholder="Max"
							min="0"
							style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; background: var(--color-surface);"
						/>
					</div>
				</div>

				<!-- Quality Score Range -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Quality Score</label>
					<div class="flex gap-2 items-center">
						<input
							type="number"
							bind:value={minQuality}
							placeholder="Min"
							min="0"
							max="100"
							style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; background: var(--color-surface);"
						/>
						<span style="font-size: 11px; font-weight: 900; color: var(--color-on-surface-dim);">—</span>
						<input
							type="number"
							bind:value={maxQuality}
							placeholder="Max"
							min="0"
							max="100"
							style="flex: 1; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; background: var(--color-surface);"
						/>
					</div>
				</div>

				<!-- Source -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Source</label>
					<select bind:value={sourceFilter}
						style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface);">
						<option value="">All Sources</option>
						{#each sourceOptions.filter(s => s) as s}
							<option value={s}>{s.toUpperCase().replace('_', ' ')}</option>
						{/each}
					</select>
				</div>

				<!-- Tags -->
				<div>
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Tags</label>
					<div class="flex flex-wrap gap-1 mb-1">
						{#each tagsChips as chip}
							<span style="display: inline-flex; align-items: center; gap: 4px; font-size: 10px; padding: 2px 8px; border: 2px solid var(--color-on-surface); font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);">
								{chip}
								<button onclick={() => removeTagChip(chip)} style="background: none; border: none; cursor: pointer; font-size: 12px; font-weight: 900; color: var(--color-error); padding: 0; line-height: 1;">✕</button>
							</span>
						{/each}
					</div>
					<input
						type="text"
						bind:value={tagsInput}
						onkeydown={addTagChip}
						placeholder="Type tag, press Enter..."
						style="width: 100%; padding: 6px 10px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; background: var(--color-surface);"
					/>
				</div>
			</div>

			<!-- Apply button -->
			<div class="flex justify-end mt-3">
				<button class="send-btn" style="font-size: 10px; padding: 8px 20px;" onclick={doSearch}>Apply Filters</button>
			</div>
		</div>
	{/if}

	<!-- Compare bar (when in compare mode) -->
	{#if compareMode}
		<div class="cv-compare-bar animate-fade-up">
			<span class="cv-compare-label">Compare mode</span>
			<span class="cv-compare-count">{compareCount}/5 selected</span>
			{#if positions.length > 0}
				<select bind:value={comparePositionSlug} class="cv-select" style="margin-left: auto;">
					<option value="">No position context</option>
					{#each positions as p}
						<option value={p.slug}>{p.title}</option>
					{/each}
				</select>
			{/if}
			<button class="cv-btn cv-btn-primary" disabled={compareCount < 2} onclick={openComparison}>
				Compare selected ({compareCount})
			</button>
			<span class="cv-compare-sep"></span>
			<button class="cv-btn cv-btn-primary" onclick={runOnlyPending} title="Run pipeline only on CVs not yet processed">
				Run pending ({visibleRows.filter(r => rowState(r) === 'pending' || rowState(r) === 'error').length})
			</button>
			<button class="cv-btn" onclick={runAllVisible} title="Run pipeline on ALL visible rows">
				Run all ({visibleRows.length})
			</button>
			<button class="cv-btn cv-btn-danger" onclick={cancelAll} title="Stop ALL in-flight pipelines + clear queue">
				Stop all
			</button>
		</div>
	{/if}

	<!-- Unified Candidate List (pending + processed) -->
	{#if loading && unifiedRows.length === 0}
		<div class="cv-table-wrap">
		<table class="cv-data-table">
			<tbody>
				<SkeletonRow count={8} />
			</tbody>
		</table>
		</div>
	{:else if visibleRows.length === 0}
		{#if searchQuery}
			<EmptyState
				icon={Search}
				title="No matching candidates"
				description="Try different search terms or clear filters."
			/>
		{:else if stateFilter !== 'all'}
			<EmptyState
				icon={Users}
				title={`No ${stateFilter} rows`}
				description="Switch the filter to see other candidates."
			/>
		{:else}
			<EmptyState
				icon={Users}
				title="No CVs yet"
				description="Upload PDFs, paste from email, or import from LinkedIn."
				actionLabel="+ Upload CVs"
				onAction={() => document.getElementById('cv-upload')?.click()}
			/>
		{/if}
	{:else}
		<!-- Select All header -->
		{#if !compareMode}
			<div class="flex items-center gap-3 mb-2" style="padding: 0 4px;">
				<input
					type="checkbox"
					checked={visibleRows.length > 0 && visibleRows.every(r => selectedIds.has(r.id))}
					onchange={() => {
						const all = visibleRows.length > 0 && visibleRows.every(r => selectedIds.has(r.id));
						if (all) selectedIds = new Set();
						else selectedIds = new Set(visibleRows.map(r => r.id));
					}}
					style="width: 16px; height: 16px; accent-color: var(--color-primary); cursor: pointer;"
				/>
				<span class="cv-selectall-label">
					Select all ({visibleRows.length})
				</span>
				{#if selectedIds.size > 0}
					<button class="cv-btn cv-btn-primary cv-btn-sm" onclick={runVisibleSelected}>
						Run {selectedIds.size}
					</button>
					<button class="cv-btn cv-btn-danger cv-btn-sm" onclick={bulkDeleteCandidates} disabled={bulkLoading}
						title="Permanently delete selected CVs">
						Delete {selectedIds.size}
					</button>
					<button class="cv-btn cv-btn-sm" onclick={clearSelection} title="Clear selection">
						Clear
					</button>
				{/if}
				<button class="cv-btn cv-btn-primary cv-btn-sm" style="margin-left: auto;" onclick={runOnlyPending} title="Run pipeline only on CVs not yet processed (pending + error)">
					Run pending only ({visibleRows.filter(r => rowState(r) === 'pending' || rowState(r) === 'error').length})
				</button>
				<button class="cv-btn cv-btn-sm" onclick={runAllVisible} title="Run pipeline on ALL visible rows (will re-process done ones)">
					Run all ({visibleRows.length})
				</button>
				<button class="cv-btn cv-btn-danger cv-btn-sm" onclick={cancelAll} title="Stop ALL in-flight pipelines + clear queue">
					Stop all
				</button>
				{#if queueDepth > 0 || queueRunning.size > 0}
					<span class="cv-queue-hint" title="Pipeline queue: running / waiting (max {queueMaxParallel} parallel)">
						{queueRunning.size} running · {queueDepth} queued
					</span>
				{/if}
			</div>
			{#if queueRunning.size > 0}
				{@const runningRows = unifiedRows.filter(r => queueRunning.has(r.id))}
				{#if runningRows.length > 0}
					<div class="cv-running-banner">
						<span class="cv-running-label">Running now:</span>
						{#each runningRows.slice(0, 8) as r (r.id)}
							{@const lr = r.latest_run || {}}
							<button onclick={() => scrollToRow(r.id)} title={r.file_name || r.name || ''} class="cv-running-chip">
								<span>cv_{String(r.id).padStart(3,'0')}</span>
								<span class="cv-running-sep">·</span>
								<span class="cv-running-prog">{lr.done_steps || 0}/{lr.total_steps || 13}</span>
								{#if lr.last_step}<span class="cv-running-step">· {String(lr.last_step).toLowerCase()}</span>{/if}
							</button>
						{/each}
						{#if runningRows.length > 8}
							<span class="cv-running-more">+{runningRows.length - 8} more</span>
						{/if}
					</div>
				{/if}
			{/if}
		{/if}

		<!-- Mobile card list (visible <768px, replaces table) -->
		<div class="cv-card-list">
			{#each visibleRows as r (r.id)}
				{@const st = rowState(r)}
				{@const isPre = st === 'pending' || st === 'running' || st === 'error'}
				<div class="cv-card st-row-{st}" data-cid={r.id} onclick={() => handleRowClick(r)} role="button" tabindex="0" onkeydown={(e) => { if (e.key === 'Enter') handleRowClick(r); }}>
					<div class="cv-card-row1">
						<div class="cv-card-name">
							{#if isPre}
								{r.file_name || r.name || `cv-${r.id}`}
							{:else}
								{r.name || 'Unknown'}
							{/if}
						</div>
						{#if st === 'pending'}<span class="cv-card-pill st-pill-pending">PENDING</span>
						{:else if st === 'running'}<span class="cv-card-pill st-pill-running">RUNNING</span>
						{:else if st === 'done'}<span class="cv-card-pill st-pill-done">DONE</span>
						{:else}<span class="cv-card-pill st-pill-error">ERROR</span>{/if}
					</div>
					{#if !isPre && r.email}
						<div class="cv-card-sub">{r.email}</div>
					{/if}
					<div class="cv-card-meta">
						{#if !isPre && r.current_role}
							<span class="cv-card-meta-item">{r.current_role}</span>
						{/if}
						{#if !isPre}
							<span class="cv-card-meta-item">{r.total_experience_years || 0}y</span>
						{/if}
						{#if !isPre && r.assignments?.length}
							<span class="cv-card-pill st-pill-stage">{r.assignments[0].stage}</span>
						{/if}
					</div>
					<div class="cv-card-actions" onclick={(e) => e.stopPropagation()}>
						{#if st === 'pending'}
							<button class="btn-run" disabled={!!activeTraces[r.id]} onclick={(e) => runOneRow(r.id, e)}>
								{activeTraces[r.id] === 'starting' ? 'Starting…' : 'Run'}
							</button>
						{:else if st === 'error'}
							<button class="btn-retry" disabled={!!activeTraces[r.id]} onclick={(e) => retryRow(r.id, e)}>Retry</button>
						{:else if st === 'running'}
							<button class="cv-mini-stop" onclick={(e) => cancelOneRow(r.id, e)}>Stop</button>
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<div class="cv-table-wrap" bind:this={cvTableRoot} onkeydown={onCvTableKey} role="grid" tabindex="-1">
		<table class="cv-data-table">
			<thead>
				<tr class="cv-th-labels">
					<th style="width: 28px;"><input type="checkbox"
						title={compareMode ? `Select all (max 5 for compare)` : `Select all ${visibleRows.length} visible`}
						checked={visibleRows.length > 0 && visibleRows.every(r => (compareMode ? compareIds : selectedIds).has(r.id))}
						onchange={() => {
							if (compareMode) {
								const all = visibleRows.length > 0 && visibleRows.every(r => compareIds.has(r.id));
								if (all) compareIds = new Set();
								else compareIds = new Set(visibleRows.slice(0, 5).map(r => r.id));
							} else {
								const all = visibleRows.length > 0 && visibleRows.every(r => selectedIds.has(r.id));
								if (all) selectedIds = new Set();
								else selectedIds = new Set(visibleRows.map(r => r.id));
							}
						}} /></th>
					<th style="width: 32px;">St</th>
					<th onclick={() => cvSortClick('name')} style="cursor:pointer;">Identity <span class="sort-ind" class:sort-on={cvSortCol === 'name'}>{cvSortCol === 'name' ? (cvSortDir === 'asc' ? '▲' : '▼') : '▲▼'}</span></th>
					<th>Role</th>
					<th onclick={() => cvSortClick('experience')} style="cursor:pointer;">Exp <span class="sort-ind" class:sort-on={cvSortCol === 'experience'}>{cvSortCol === 'experience' ? (cvSortDir === 'asc' ? '▲' : '▼') : '▲▼'}</span></th>
					<th onclick={() => cvSortClick('quality')} style="cursor:pointer;">Q <span class="sort-ind" class:sort-on={cvSortCol === 'quality'}>{cvSortCol === 'quality' ? (cvSortDir === 'asc' ? '▲' : '▼') : '▲▼'}</span></th>
					<th>Pipeline</th>
					<th>Added by</th>
					<th onclick={() => cvSortClick('updated_at')} style="cursor:pointer;">Updated <span class="sort-ind" class:sort-on={cvSortCol === 'updated_at'}>{cvSortCol === 'updated_at' ? (cvSortDir === 'asc' ? '▲' : '▼') : '▲▼'}</span></th>
					<th>Expires</th>
					<th style="width: 32px;"></th>
				</tr>
			</thead>
			<tbody>
				{#each visibleRows as r, i (r.id)}
					{@const st = rowState(r)}
					{@const lr = r.latest_run || {}}
					{@const isPre = st === 'pending' || st === 'running' || st === 'error'}
					<tr class="cv-row st-row-{st}" class:st-row-running={queueRunning.has(r.id)} class:cv-row-selected={(compareMode ? compareIds.has(r.id) : selectedIds.has(r.id))} class:cv-row-focus={focusedRowIdx === i} data-cid={r.id} data-row-idx={i} tabindex="0" onfocus={() => focusedRowIdx = i} onclick={() => handleRowClick(r)}>
						<td onclick={(e) => e.stopPropagation()}>
							<input type="checkbox"
								checked={compareMode ? compareIds.has(r.id) : selectedIds.has(r.id)}
								onchange={() => compareMode ? toggleCompare(r.id) : toggleSelect(r.id)} />
						</td>
						<td>
							{#if st === 'pending'}<span class="st-dot st-pending" title="Pending" style="display:inline-flex;"><Hourglass size={13} stroke-width={2} /></span>
							{:else if st === 'running'}<span class="st-dot st-running" title="Running" style="display:inline-flex;"><Hourglass size={13} stroke-width={2} /></span>
							{:else if st === 'done'}<span class="st-dot st-done" title="Done" style="display:inline-flex;"><Check size={13} stroke-width={2.5} /></span>
							{:else}<span class="st-dot st-error" title="Error" style="display:inline-flex;"><AlertTriangle size={13} stroke-width={2} /></span>{/if}
						</td>
						<td>
							<div style="display: flex; align-items: center; gap: 8px;">
								{#if !isPre}
									<div class="avatar-user" style="width: 28px; height: 28px; font-size: 11px;">{initials(r.name)}</div>
								{:else}
									<div class="file-icon" title={r.file_type || 'file'}>{(r.file_type || '?').slice(0,3).toUpperCase()}</div>
								{/if}
								<div style="min-width: 0;">
									<div class="row-primary" title={isPre ? r.file_name : r.name}>
										{#if isPre}
											{r.file_name || r.name || `cv-${r.id}`}
										{:else}
											<span use:hoverPreview={{ id: r.id, name: r.name }}>{r.name || 'Unknown'}</span>
										{/if}
										{#if dupCandidateIds.has(r.id) && !isPre}
											<button title="Possible duplicate" aria-label="Possible duplicate"
												onclick={(e) => openDupForCandidate(r.id, e)}
												class="dup-pill"><span aria-hidden="true" style="display:inline-flex;vertical-align:middle;"><Search size={12} stroke-width={2} /></span> DUP?</button>
										{/if}
									</div>
									<div class="row-sub">
										{#if isPre}
											{#if r.name && r.name !== 'Unknown'}{r.name}{:else}{(r.file_type || '').toUpperCase() || 'FILE'} · {fmtSize(r.file_size)}{/if}
											{#if st === 'error' && r.processing_error}<span class="err-msg"> · {r.processing_error}</span>{/if}
										{:else}
											{r.email || `${(r.file_type || '').toUpperCase() || 'CV'} · ${fmtSize(r.file_size) || ''}`}
										{/if}
									</div>
								</div>
							</div>
						</td>
						<td>
							{#if isPre}
								<span style="opacity: 0.5;">—</span>
							{:else}
								{r.current_role || '—'}
								{#if r.current_company}<div style="font-size: 10px; color: var(--color-on-surface-dim);">{r.current_company}</div>{/if}
							{/if}
						</td>
						<td>{isPre ? '—' : `${r.total_experience_years || 0}y`}</td>
						<td>{isPre ? '—' : (r.quality_score ?? '—')}</td>
						<td onclick={(e) => e.stopPropagation()}>
							{#if queueRunning.has(r.id) || st === 'running'}
								<div class="pipe-cell">
									<div class="pipe-bar"><div class="pipe-fill" style="width: {Math.round(((lr.done_steps || 0) / (lr.total_steps || 13)) * 100)}%;"></div></div>
									<span class="pipe-txt">{lr.done_steps || 0}/{lr.total_steps || 13}{lr.last_step ? ` · ${String(lr.last_step).toLowerCase()}` : ''}</span>
									<button onclick={(e) => cancelOneRow(r.id, e)} title="Stop this pipeline" class="cv-mini-stop">Stop</button>
								</div>
							{:else if queuePositions[r.id]}
								<div class="pipe-cell" title="Waiting in queue">
									<span class="cv-queue-pill">Queued #{queuePositions[r.id]}</span>
									<button onclick={(e) => cancelOneRow(r.id, e)} title="Remove from queue" class="cv-mini-stop">×</button>
								</div>
							{:else if st === 'pending'}
								<button class="btn-run" disabled={!!activeTraces[r.id]} onclick={(e) => runOneRow(r.id, e)}>{activeTraces[r.id] === 'starting' ? 'Starting…' : 'Run'}</button>
							{:else if st === 'error'}
								<button class="btn-retry" disabled={!!activeTraces[r.id]} onclick={(e) => retryRow(r.id, e)}>Retry</button>
							{:else if !isPre && r.assignments?.length}
								<a href="/positions/{r.assignments[0].slug}"
									title={`${r.assignments[0].title} · ${r.assignments[0].stage}`}
									class="att-pill">
									<span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px; display: inline-block;">{r.assignments[0].title}</span>
									<span class="att-stage">{r.assignments[0].stage}</span>
								</a>
								{#if r.assignments.length > 1}<span class="att-more">+{r.assignments.length - 1}</span>{/if}
							{:else}
								<span style="font-size: 11px; color: var(--color-on-surface-dim);">—</span>
							{/if}
						</td>
						<td class="ts-cell" title={r.created_by_name || r.owner_name || ''}>
							{#if r.created_by_name || r.owner_name}
								<div class="ts-abs">{r.created_by_name || r.owner_name}</div>
								<div class="ts-rel">{cvTimeAgo(r.created_at)}</div>
							{:else}
								<span style="font-size: 11px; color: var(--color-on-surface-dim);">—</span>
							{/if}
						</td>
						<td class="ts-cell">
							{#if r.updated_by_name}
								<div class="ts-abs">{r.updated_by_name}</div>
								<div class="ts-rel">{cvTimeAgo(r.updated_at || r.created_at)}</div>
							{:else}
								<div class="ts-abs">{cvFmtAbs(r.updated_at || r.created_at)}</div>
								<div class="ts-rel">{cvTimeAgo(r.updated_at || r.created_at)}</div>
							{/if}
						</td>
						<td>
							{#if r.expires_at}
								{@const exp = r.is_expired}
								{@const dleft = r.days_until_expiry}
								{#if exp}
									<span class="exp-chip exp-chip-red" title={`Expired ${cvFmtAbs(r.expires_at)}`}>Expired</span>
								{:else if dleft != null && dleft < 14}
									<span class="exp-chip exp-chip-amber" title={`Expires ${cvFmtAbs(r.expires_at)}`}>{dleft}d</span>
								{:else}
									<span class="exp-chip exp-chip-neutral" title={`Expires ${cvFmtAbs(r.expires_at)}`}>{dleft}d</span>
								{/if}
							{:else}
								<span style="font-size: 11px; color: var(--color-on-surface-dim);">—</span>
							{/if}
						</td>
						<td onclick={(e) => e.stopPropagation()}>
							{#if isPre}
								<button class="row-action" title="Delete permanently"
									onclick={(e) => deletePendingRow(r.id, e)}>✕</button>
							{:else}
								<button class="row-action row-action-more" title="Row actions" onclick={(e) => toggleRowAction(r.id, e)}>⋯</button>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		</div>

		<!-- Pagination -->
		{#if total > candLimit}
			<Pagination total={total} limit={candLimit} offset={candOffset} onPageChange={onCandPageChange} />
		{/if}
	{/if}

		</div><!-- /max-width wrap -->
		</main>
	</div><!-- /.cv-split -->

	<!-- Mobile filters bottom-sheet -->
	{#if mobileFiltersOpen}
		<button
			type="button"
			class="cv-mfilt-overlay"
			aria-label="Close filters"
			onclick={() => mobileFiltersOpen = false}
		></button>
		<aside class="cv-mfilt-sheet" role="dialog" aria-modal="true" aria-label="Filters">
			<div class="cv-mfilt-head">
				<span class="cv-mfilt-title">Filters</span>
				<button type="button" class="cv-mfilt-close" onclick={() => mobileFiltersOpen = false} aria-label="Close">
					<span class="material-symbols-outlined" style="font-size: 20px;">close</span>
				</button>
			</div>
			<div class="cv-mfilt-body">
				<CandidateRailFilters
					bind:scope={cvScope}
					scopeCounts={cvCounts}
					onScopeChange={(s) => setCvScope(s)}
					bind:stateFilter
					{stateCounts}
					{roleFacets}
					bind:roleSelected
					{attachedFacets}
					bind:attachedSelected
					bind:uploadedRange
					bind:qScoreMin
					{facetGroups}
					bind:skillSelected
					bind:companySelected
					bind:locationSelected
					bind:languageSelected
					bind:certSelected
					bind:educationSelected
					onDismissFacetNew={dismissFacetNew}
					onClearAll={clearAllRailFilters}
				/>
			</div>
			<div class="cv-mfilt-foot">
				<button type="button" class="cv-btn cv-btn-primary" onclick={() => mobileFiltersOpen = false}>
					Done
				</button>
			</div>
		</aside>
	{/if}

	<!-- Status Bar (sticky bottom) -->
	<div class="cv-status-bar">
		<span class="sb-section">{stateCounts.all} rows</span>
		<span class="sb-sep">·</span>
		<span class="sb-section sb-running">{statusTotals.runningCount} running</span>
		<span class="sb-sep">·</span>
		<span class="sb-section sb-done">{statusTotals.doneCount} done</span>
		<span class="sb-sep">·</span>
		<span class="sb-section">{statusTotals.runs} runs · ${statusTotals.cost.toFixed(3)} spent</span>
		{#if facetNewTotal > 0}
			<span class="sb-sep">·</span>
			<span class="sb-section sb-ai">✦ AI added {facetNewTotal} new option{facetNewTotal === 1 ? '' : 's'} today</span>
		{/if}
	</div>

<!-- ═══ HARD-DELETE CONFIRM MODAL ═══ -->
{#if cvDeleteTarget}
	{@const _ct2 = (cvDeleteTarget?.name || '').trim().toLowerCase()}
	{@const _cv2 = cvDeleteConfirmText.trim().toLowerCase()}
	{@const _cok = _cv2.length > 0 && (_cv2 === _ct2 || _cv2 === 'delete')}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 200; display: flex; align-items: center; justify-content: center; padding: 20px;"
		onclick={(e) => { if (e.target === e.currentTarget && !cvDeleting) { cvDeleteTarget = null; cvDeleteConfirmText = ''; } }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 520px; max-width: 95vw;">
			<div style="background: var(--color-error); color: white; padding: 8px 14px; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em;">
				PERMANENT DELETE — CV / CANDIDATE
			</div>
			<div class="p-5" style="display: flex; flex-direction: column; gap: 14px;">
				<p style="font-size: 13px; line-height: 1.5;">You are about to <strong style="color: var(--color-error);">permanently delete</strong> the candidate:</p>
				<div style="border: 2px solid var(--color-on-surface); padding: 10px 14px; background: var(--color-surface-bright); font-size: 13px; font-weight: 900;">
					{cvDeleteTarget.name}
				</div>
				<p style="font-size: 11px; color: var(--color-on-surface-dim); text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.5;">
					This cannot be undone. CV file, embeddings, scorecards, position links — all removed. Only the uploader or a superadmin may proceed.
				</p>
				<div>
					<label class="tag-label mb-1" style="display: block;">Type candidate name <strong style="color: var(--color-error);">{cvDeleteTarget?.name}</strong> or word DELETE to confirm</label>
					<input type="text" bind:value={cvDeleteConfirmText}
						placeholder={cvDeleteTarget?.name || 'DELETE'}
						style="width: 100%; padding: 10px 14px; border: 2px solid var(--color-error); font-family: 'Space Grotesk'; font-size: 14px; font-weight: 700; letter-spacing: 0.1em; background: var(--color-surface-bright);" />
				</div>
				<div class="flex gap-2 justify-end pt-2">
					<button class="btn-secondary" disabled={cvDeleting} onclick={() => { cvDeleteTarget = null; cvDeleteConfirmText = ''; }}>Cancel</button>
					<button onclick={confirmCvDelete} disabled={cvDeleting || !_cok}
						style="background: var(--color-error); color: white; border: 2px solid var(--color-on-surface); padding: 8px 18px; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; cursor: {cvDeleting ? 'wait' : 'pointer'}; opacity: {_cok ? 1 : 0.4};">
						{#if !cvDeleting}<Trash2 size={13} stroke-width={2} />{/if} {cvDeleting ? 'DELETING…' : 'PERMANENTLY DELETE'}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

</div><!-- /.cv-page-wrap -->


<!-- Bulk Actions Bar (sticky bottom) -->
{#if selectedCount > 0 && !compareMode}
	<div style="position: fixed; bottom: 0; left: 0; right: 0; z-index: 90; background: var(--color-on-surface); color: var(--color-surface); padding: 10px 24px; display: flex; align-items: center; gap: 16px; font-family: 'Space Grotesk'; border-top: 3px solid var(--color-primary-container);"
		class="animate-fade-up">
		<span style="font-size: 13px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; min-width: 100px;">
			{selectedCount} selected
		</span>

		<!-- Move to Stage -->
		<div class="flex items-center gap-1">
			<select bind:value={bulkStage}
				style="padding: 5px 8px; border: 2px solid var(--color-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 700; text-transform: uppercase; background: transparent; color: var(--color-surface);">
				<option value="">Move to stage...</option>
				{#each stageOptions as s}
					<option value={s}>{s.toUpperCase()}</option>
				{/each}
			</select>
			<button
				style="padding: 5px 10px; border: 2px solid var(--color-primary-container); background: var(--color-primary-container); color: var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; cursor: pointer;"
				disabled={!bulkStage || bulkLoading}
				onclick={bulkMoveStage}
			>Go</button>
		</div>

		<!-- Add to Position -->
		<div class="flex items-center gap-1">
			<select bind:value={bulkPositionSlug}
				style="padding: 5px 8px; border: 2px solid var(--color-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 700; text-transform: uppercase; background: transparent; color: var(--color-surface);">
				<option value="">Add to position...</option>
				{#each positions as p}
					<option value={p.slug}>{p.title}</option>
				{/each}
			</select>
			<button
				style="padding: 5px 10px; border: 2px solid var(--color-primary-container); background: var(--color-primary-container); color: var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; cursor: pointer;"
				disabled={!bulkPositionSlug || bulkLoading}
				onclick={bulkAddToPosition}
			>Go</button>
		</div>

		<!-- Tag -->
		<div class="flex items-center gap-1" style="position: relative;">
			<button
				style="padding: 5px 12px; border: 2px solid var(--color-surface); background: transparent; color: var(--color-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; cursor: pointer;"
				onclick={() => bulkTagOpen = !bulkTagOpen}
			>Tag</button>
			{#if bulkTagOpen}
				<input
					type="text"
					bind:value={bulkTagInput}
					onkeydown={(e) => { if (e.key === 'Enter') bulkAttachTag(); }}
					placeholder="tag…"
					style="padding: 5px 8px; border: 2px solid var(--color-surface); background: var(--color-surface); color: var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 700; width: 110px;"
				/>
				<button onclick={bulkAttachTag} disabled={!bulkTagInput.trim() || bulkLoading}
					style="padding: 5px 8px; border: 2px solid var(--color-primary-container); background: var(--color-primary-container); color: var(--color-on-surface); font-size: 10px; font-weight: 900; text-transform: uppercase; cursor: pointer;">Apply</button>
			{/if}
		</div>

		<!-- Reject All -->
		<button
			style="padding: 5px 14px; border: 2px solid var(--color-error); background: var(--color-error); color: white; font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; cursor: pointer; margin-left: auto;"
			disabled={bulkLoading}
			onclick={bulkReject}
		>Reject All</button>

		<!-- Clear Selection -->
		<button
			style="padding: 5px 14px; border: 2px solid var(--color-surface); background: transparent; color: var(--color-surface); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; cursor: pointer;"
			onclick={clearSelection}
		>Clear</button>
	</div>
{/if}

<!-- CV Detail Modal -->
{#if selectedCandidate}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 40px 20px; overflow-y: auto;"
		onclick={(e) => { if (e.target === e.currentTarget) { selectedCvId = null; selectedCandidate = null; } }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 700px; max-height: 85vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span>{selectedCandidate.name || 'Candidate Detail'}</span>
				<button onclick={() => { selectedCvId = null; selectedCandidate = null; }} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">✕</button>
			</div>
			<div class="p-5">
				<!-- Personal info -->
				<div class="flex gap-4 mb-4">
					<div class="avatar-user" style="width: 56px; height: 56px; font-size: 20px;">{(selectedCandidate.name || '?')[0]}</div>
					<div>
						<h2 style="font-size: 18px; font-weight: 900;">{selectedCandidate.name}</h2>
						<p style="font-size: 13px; color: var(--color-on-surface-dim);">
							{selectedCandidate.current_role || 'N/A'}{selectedCandidate.current_company ? ` at ${selectedCandidate.current_company}` : ''}
						</p>
						<div class="flex gap-3 mt-1" style="font-size: 11px;">
							{#if selectedCandidate.email}<span>✉ {selectedCandidate.email}</span>{/if}
							{#if selectedCandidate.phone}<span>☎ {selectedCandidate.phone}</span>{/if}
							{#if selectedCandidate.location}<span style="display:inline-flex;align-items:center;gap:3px;"><MapPin size={13} stroke-width={1.75} /> {selectedCandidate.location}</span>{/if}
						</div>
					</div>
				</div>

				<!-- Summary -->
				{#if selectedCandidate.summary_short}
					<div class="mb-4 p-3" style="background: var(--color-surface-container); border-left: 3px solid var(--color-primary);">
						<span class="tag-label mb-1" style="display: block; font-size: 8px;">Summary</span>
						<p style="font-size: 13px; line-height: 1.5;">{selectedCandidate.summary_short}</p>
					</div>
				{/if}

				<!-- Skills -->
				{#if selectedCandidate.skills_technical?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Technical Skills</span>
						<div class="flex gap-1 flex-wrap">
							{#each selectedCandidate.skills_technical as skill}
								<span style="font-size: 10px; padding: 2px 8px; border: 2px solid var(--color-on-surface); font-weight: 700; text-transform: uppercase;">{skill}</span>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Experience -->
				{#if selectedCandidate.experience?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Experience ({selectedCandidate.total_experience_years || 0} years)</span>
						{#each (typeof selectedCandidate.experience === 'string' ? JSON.parse(selectedCandidate.experience) : selectedCandidate.experience) as exp}
							<div class="mb-2 p-2" style="border-left: 2px solid var(--color-outline-variant);">
								<div style="font-size: 13px; font-weight: 900;">{exp.role || 'N/A'}</div>
								<div style="font-size: 12px; color: var(--color-on-surface-dim);">
									{exp.company || ''} · {exp.start_date || ''} – {exp.end_date || 'present'}
								</div>
								{#if exp.description}
									<p style="font-size: 12px; margin-top: 2px;">{exp.description}</p>
								{/if}
							</div>
						{/each}
					</div>
				{/if}

				<!-- Education -->
				{#if selectedCandidate.education?.length}
					<div class="mb-4">
						<span class="tag-label mb-2" style="display: block;">Education</span>
						{#each (typeof selectedCandidate.education === 'string' ? JSON.parse(selectedCandidate.education) : selectedCandidate.education) as edu}
							<div class="mb-1" style="font-size: 12px;">
								<span style="font-weight: 700;">{edu.degree || ''} {edu.field || ''}</span>
								— {edu.institution || ''} {edu.year ? `(${edu.year})` : ''}
							</div>
						{/each}
					</div>
				{/if}

				<!-- Quality & Meta -->
				<div class="flex gap-4 pt-3" style="border-top: 2px solid var(--color-on-surface); font-size: 11px;">
					<div><span class="tag-label" style="font-size: 8px;">Quality</span> {selectedCandidate.quality_score || 0}/100</div>
					<div><span class="tag-label" style="font-size: 8px;">Source</span> {selectedCandidate.source || 'upload'}</div>
					<div><span class="tag-label" style="font-size: 8px;">Pages</span> {selectedCandidate.page_count || 0}</div>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- Comparison Modal -->
{#if showCompareModal}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 30px 20px; overflow-y: auto;"
		onclick={(e) => { if (e.target === e.currentTarget) closeComparison(); }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 95vw; max-width: 1100px; max-height: 85vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between" style="gap: 8px;">
				<span>Candidate Comparison ({compareCount})</span>
				<div class="flex items-center" style="gap: 6px;">
					<button onclick={regenerateComparisonSummary} disabled={comparisonAiLoading} title="Regenerate AI executive summary" style="background: var(--color-primary); color: var(--color-on-surface); border: 2px solid var(--color-surface); padding: 4px 10px; font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; cursor: {comparisonAiLoading ? 'wait' : 'pointer'}; display:inline-flex; align-items:center; gap:4px;">{#if !comparisonAiLoading}<Sparkles size={12} stroke-width={1.75} />{:else}<Hourglass size={12} stroke-width={2} />{/if} {comparisonAiLoading ? 'THINKING…' : 'GEN AI'}</button>
					<button onclick={exportComparisonXlsx} title="Download as Excel" style="background: transparent; color: var(--color-surface); border: 2px solid var(--color-surface); padding: 4px 10px; font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; cursor: pointer;">⤓ XLSX</button>
					<button onclick={closeComparison} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">✕</button>
				</div>
			</div>
			<div class="p-5">
				{#if compareLoading}
					<div class="flex items-center justify-center py-12">
						<div class="typing-indicator"><span></span><span></span><span></span></div>
						<span style="font-size: 12px; font-weight: 900; text-transform: uppercase; margin-left: 12px;">Analyzing candidates...</span>
					</div>
				{:else if comparisonData}
					{#if comparisonData.comparison_summary}
						<div style="background: linear-gradient(180deg, rgba(0,252,64,0.12) 0%, rgba(0,252,64,0.02) 100%); border: 2px solid var(--color-primary); padding: 14px 18px; margin-bottom: 16px; position: relative;">
							<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
								<span style="display:inline-flex; color: var(--color-primary);"><Sparkles size={16} stroke-width={1.75} /></span>
								<span style="font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-primary);">AI EXECUTIVE SUMMARY</span>
							</div>
							<p style="font-size: 13px; line-height: 1.6; white-space: pre-wrap; margin: 0;">{comparisonData.comparison_summary}</p>
						</div>
					{/if}
					<!-- Comparison table -->
					<div style="overflow-x: auto;">
						<table class="data-table" style="min-width: 600px;">
							<thead>
								<tr>
									<th style="min-width: 140px;">Dimension</th>
									{#each comparisonData.candidates || [] as cand}
										<th>{cand.name || 'Unknown'}</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Current Role</td>
									{#each comparisonData.candidates || [] as cand}
										<td style="font-size: 12px;">{cand.current_role || 'N/A'}</td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Company</td>
									{#each comparisonData.candidates || [] as cand}
										<td style="font-size: 12px;">{cand.current_company || 'N/A'}</td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Experience</td>
									{#each comparisonData.candidates || [] as cand}
										<td style="font-size: 12px;">{cand.total_experience_years || 0} years</td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Seniority</td>
									{#each comparisonData.candidates || [] as cand}
										<td><span class="tag-label" style="font-size: 8px;">{cand.seniority_level || 'N/A'}</span></td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Location</td>
									{#each comparisonData.candidates || [] as cand}
										<td style="font-size: 12px;">{cand.location || 'N/A'}</td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Skills</td>
									{#each comparisonData.candidates || [] as cand}
										<td>
											<div class="flex flex-wrap gap-1">
												{#each (cand.skills_technical || []).slice(0, 10) as skill}
													<span style="font-size: 8px; padding: 1px 5px; border: 1px solid var(--color-outline); text-transform: uppercase; font-weight: 700;">{skill}</span>
												{/each}
												{#if (cand.skills_technical || []).length > 10}
													<span style="font-size: 8px; color: var(--color-on-surface-dim);">+{cand.skills_technical.length - 10}</span>
												{/if}
											</div>
										</td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Education</td>
									{#each comparisonData.candidates || [] as cand}
										<td style="font-size: 11px;">
											{#each (Array.isArray(cand.education) ? cand.education : []).slice(0, 2) as edu}
												<div>{edu.degree || ''} {edu.field || ''} — {edu.institution || ''}</div>
											{/each}
											{#if !cand.education?.length}
												<span style="color: var(--color-on-surface-dim);">N/A</span>
											{/if}
										</td>
									{/each}
								</tr>
								<tr>
									<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Quality Score</td>
									{#each comparisonData.candidates || [] as cand}
										<td>
											<span style="font-size: 13px; font-weight: 900; padding: 2px 8px; border: 2px solid;
												color: {(cand.quality_score || 0) >= 70 ? 'var(--color-primary)' : (cand.quality_score || 0) >= 40 ? 'var(--color-warning)' : 'var(--color-error)'};">
												{cand.quality_score || 0}
											</span>
										</td>
									{/each}
								</tr>
								{#if comparisonData.scores}
									<tr>
										<td style="font-weight: 900; text-transform: uppercase; font-size: 11px;">Match Score</td>
										{#each comparisonData.candidates || [] as cand}
											<td>
												{#if comparisonData.scores[cand.id]}
													<div style="font-size: 13px; font-weight: 900; color: var(--color-primary);">{comparisonData.scores[cand.id].composite || 'N/A'}</div>
													<div style="font-size: 9px; color: var(--color-on-surface-dim); margin-top: 2px;">
														{#if comparisonData.scores[cand.id].skills}Skills: {comparisonData.scores[cand.id].skills}{/if}
														{#if comparisonData.scores[cand.id].experience} | Exp: {comparisonData.scores[cand.id].experience}{/if}
													</div>
												{:else}
													<span style="color: var(--color-on-surface-dim); font-size: 11px;">No position scored</span>
												{/if}
											</td>
										{/each}
									</tr>
								{/if}
							</tbody>
						</table>
					</div>

					{#if comparisonData.summary}
						<div class="mt-4 p-3" style="background: var(--color-surface-container); border-left: 3px solid var(--color-primary);">
							<span class="tag-label mb-1" style="display: block; font-size: 8px;">AI Summary</span>
							<p style="font-size: 13px; line-height: 1.5;">{comparisonData.summary}</p>
						</div>
					{/if}
				{:else}
					<div class="flex flex-col items-center justify-center py-12">
						<span class="material-symbols-outlined" style="font-size: 36px; color: var(--color-on-surface-dim);">error_outline</span>
						<p style="font-size: 12px; font-weight: 900; text-transform: uppercase; margin-top: 8px;">Comparison data unavailable</p>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- Bulk Upload Modal -->
{#if showBulkUploadModal}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 40px 20px; overflow-y: auto;"
		onclick={(e) => { if (e.target === e.currentTarget) bulkClose(); }}
		role="presentation">
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 680px; max-width: 100%; max-height: 88vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span>Upload CV(s)</span>
				<button onclick={bulkClose} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">X</button>
			</div>

			<div class="p-5">
				<div style="font-size: 11px; font-weight: 700; color: var(--color-on-surface-dim); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em;">
					Up to {BULK_MAX_FILES} files · PDF / DOCX / DOC / TXT · 20MB each · duplicates by email skipped
				</div>

				<!-- Drag-drop zone -->
				<div
					role="button"
					tabindex="0"
					onclick={() => document.getElementById('bulk-cv-input')?.click()}
					onkeydown={(e) => { if (e.key === 'Enter') document.getElementById('bulk-cv-input')?.click(); }}
					ondragover={(e) => { e.preventDefault(); bulkDragOver = true; }}
					ondragleave={() => bulkDragOver = false}
					ondrop={bulkOnDrop}
					style="border: 2px dashed {bulkDragOver ? 'var(--color-primary)' : 'var(--color-on-surface)'}; background: {bulkDragOver ? 'var(--color-primary-container, #e0ffe0)' : 'var(--color-surface-bright)'}; padding: 24px; text-align: center; cursor: pointer; margin-bottom: 12px; transition: all 120ms;"
				>
					<div style="font-size: 13px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px;">
						Drop files here or click to browse
					</div>
					<div style="font-size: 11px; color: var(--color-on-surface-dim); font-weight: 700;">
						{bulkFiles.length} / {BULK_MAX_FILES} selected
					</div>
					<input
						id="bulk-cv-input"
						type="file"
						multiple
						accept=".pdf,.docx,.doc,.txt"
						style="display: none;"
						onchange={(e) => { bulkAddFiles(e.currentTarget.files); e.currentTarget.value = ''; }}
					/>
				</div>

				<!-- File list -->
				{#if bulkFiles.length > 0}
					<div style="max-height: 260px; overflow-y: auto; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); margin-bottom: 12px;">
						{#each bulkFiles as f, idx}
							<div class="flex items-center" style="padding: 6px 10px; border-bottom: 1px solid rgba(56,56,50,0.15); gap: 8px; font-size: 12px;">
								<span style="width: 18px; text-align: center; font-weight: 900;">
									{#if f.status === 'done'}<span style="color: var(--color-primary); display:inline-flex;"><Check size={14} stroke-width={2.5} /></span>
									{:else if f.status === 'error'}<span style="color: var(--color-error); display:inline-flex;"><X size={14} stroke-width={2.5} /></span>
									{:else if f.status === 'skipped'}<span style="color: #b08000;">~</span>
									{:else if f.status === 'uploading'}<span style="color: var(--color-on-surface-dim); display:inline-flex;"><Hourglass size={14} stroke-width={2} /></span>
									{:else}<span style="color: var(--color-on-surface-dim);">☐</span>{/if}
								</span>
								<span style="flex: 1; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title={f.file.name}>
									{f.file.name}
								</span>
								<span style="color: var(--color-on-surface-dim); font-size: 10px; min-width: 60px; text-align: right;">
									{(f.file.size / 1024).toFixed(0)} KB
								</span>
								{#if f.error}
									<span style="color: var(--color-error); font-size: 10px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title={f.error}>{f.error}</span>
								{/if}
								{#if !bulkUploading && f.status !== 'done' && f.status !== 'skipped'}
									<button onclick={() => bulkRemoveFile(idx)} style="background: none; border: 1px solid var(--color-on-surface); padding: 2px 6px; font-size: 10px; font-weight: 900; cursor: pointer;" title="Remove">X</button>
								{/if}
							</div>
						{/each}
					</div>
				{/if}

				<!-- Result summary -->
				{#if bulkResult}
					<div class="ink-border" style="background: var(--color-primary-container, #e8ffe8); padding: 10px; margin-bottom: 12px; font-size: 12px; font-weight: 700;">
						<div style="margin-bottom: 4px;">
							Created: <strong>{bulkResult.created}</strong>
							· Skipped (dupes): <strong>{bulkResult.skipped_duplicates}</strong>
							· Errors: <strong>{(bulkResult.errors || []).length}</strong>
							· Total: <strong>{bulkResult.total}</strong>
						</div>
						{#if (bulkResult.errors || []).length > 0}
							<div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(56,56,50,0.2); font-size: 11px;">
								{#each bulkResult.errors as err}
									<div style="color: var(--color-error);">{err.filename}: {err.error}</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Actions -->
				<div class="flex gap-2" style="justify-content: flex-end;">
					<button class="btn-secondary" style="font-size: 11px; padding: 8px 14px;" onclick={bulkClose} disabled={bulkUploading}>
						{bulkResult ? 'Close' : 'Cancel'}
					</button>
					{#if !bulkResult}
						<button
							class="send-btn"
							style="font-size: 11px; padding: 8px 18px;"
							disabled={bulkUploading || bulkFiles.length === 0}
							onclick={bulkDoUpload}
						>
							{#if bulkUploading}
								<span class="typing-indicator" style="display: inline-flex; justify-content: center;"><span></span><span></span><span></span></span>
							{:else}
								Upload {bulkFiles.length} file{bulkFiles.length === 1 ? '' : 's'}
							{/if}
						</button>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- Import Modal -->
{#if showImportModal}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 40px 20px; overflow-y: auto;"
		onclick={(e) => { if (e.target === e.currentTarget) showImportModal = false; }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 600px; max-height: 85vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span>Import Candidate</span>
				<button onclick={() => showImportModal = false} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px;">X</button>
			</div>

			<!-- Tabs -->
			<div class="flex" style="border-bottom: 2px solid var(--color-on-surface);">
				{#each [['linkedin', 'LinkedIn'], ['github', 'GitHub'], ['text', 'Paste Text']] as [key, label]}
					<button
						onclick={() => { importTab = key; importError = ''; importResult = null; }}
						style="flex: 1; padding: 10px; font-family: 'Space Grotesk'; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; border: none; cursor: pointer;
							background: {importTab === key ? 'var(--color-surface-bright)' : 'var(--color-surface)'};
							color: {importTab === key ? 'var(--color-on-surface)' : 'var(--color-on-surface-dim)'};
							border-bottom: {importTab === key ? '3px solid var(--color-primary)' : '3px solid transparent'};"
					>
						{label}
					</button>
				{/each}
			</div>

			<div class="p-5">
				<!-- Error / Success -->
				{#if importError}
					<div class="mb-3 p-2" style="background: var(--color-error-container, #ffe0e0); border-left: 3px solid var(--color-error); font-size: 12px; font-weight: 700;">
						{importError}
					</div>
				{/if}
				{#if importResult}
					<div class="mb-3 p-2" style="background: var(--color-primary-container); border-left: 3px solid var(--color-primary); font-size: 12px; font-weight: 700;">
						Imported: {importResult.name || importResult.analysis?.username || 'Success'}
						{#if importResult.candidate_id}
							(ID: {importResult.candidate_id})
						{/if}
						{#if importResult.skills_added?.length}
							— Skills added: {importResult.skills_added.join(', ')}
						{/if}
					</div>
				{/if}

				<!-- LinkedIn Tab -->
				{#if importTab === 'linkedin'}
					<div>
						<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">LinkedIn Profile URL</label>
						<input
							type="url"
							bind:value={importLinkedinUrl}
							placeholder="https://linkedin.com/in/username"
							style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; font-weight: 700; background: var(--color-surface-bright); margin-bottom: 12px;"
						/>

						<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Or Paste Profile Text</label>
						<textarea
							bind:value={importLinkedinText}
							placeholder="Paste LinkedIn profile text here if URL doesn't work..."
							rows="5"
							style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface-bright); resize: vertical; margin-bottom: 12px;"
						></textarea>

						<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Link to Position (Optional)</label>
						<select bind:value={importLinkedinPosition}
							style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright); margin-bottom: 16px;">
							<option value="">No position</option>
							{#each positions as p}
								<option value={p.slug}>{p.title}</option>
							{/each}
						</select>

						<button
							class="send-btn"
							style="width: 100%; padding: 10px; font-size: 12px;"
							disabled={importLoading || (!importLinkedinUrl && !importLinkedinText)}
							onclick={doLinkedInImport}
						>
							{#if importLoading}
								<span class="typing-indicator" style="display: inline-flex; justify-content: center;"><span></span><span></span><span></span></span>
							{:else}
								Import from LinkedIn
							{/if}
						</button>
					</div>
				{/if}

				<!-- GitHub Tab -->
				{#if importTab === 'github'}
					<div>
						<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">GitHub Profile URL</label>
						<input
							type="url"
							bind:value={importGithubUrl}
							placeholder="https://github.com/username"
							style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; font-weight: 700; background: var(--color-surface-bright); margin-bottom: 12px;"
						/>

						<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Attach to Candidate</label>
						<select bind:value={importGithubCandidateId}
							style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright); margin-bottom: 16px;">
							<option value="">Select candidate...</option>
							{#each candidates as c}
								<option value={c.id}>{c.name} — {c.current_role || 'No role'}</option>
							{/each}
						</select>

						<button
							class="send-btn"
							style="width: 100%; padding: 10px; font-size: 12px;"
							disabled={importLoading || !importGithubUrl || !importGithubCandidateId}
							onclick={doGitHubAnalysis}
						>
							{#if importLoading}
								<span class="typing-indicator" style="display: inline-flex; justify-content: center;"><span></span><span></span><span></span></span>
							{:else}
								Analyze GitHub Profile
							{/if}
						</button>
					</div>
				{/if}

				<!-- Paste Text Tab -->
				{#if importTab === 'text'}
					<div>
						<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Paste Resume / Profile Text</label>
						<textarea
							bind:value={importPasteText}
							placeholder="Paste candidate info from LinkedIn, email, website, etc..."
							rows="8"
							style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface-bright); resize: vertical; margin-bottom: 12px;"
						></textarea>

						<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
							<div>
								<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Source</label>
								<select bind:value={importPasteSource}
									style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);">
									<option value="text_import">Text Import</option>
									<option value="linkedin">LinkedIn</option>
									<option value="email">Email</option>
									<option value="referral">Referral</option>
									<option value="other">Other</option>
								</select>
							</div>
							<div>
								<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Link to Position (Optional)</label>
								<select bind:value={importPastePosition}
									style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);">
									<option value="">No position</option>
									{#each positions as p}
										<option value={p.slug}>{p.title}</option>
									{/each}
								</select>
							</div>
						</div>

						<button
							class="send-btn"
							style="width: 100%; padding: 10px; font-size: 12px;"
							disabled={importLoading || !importPasteText || importPasteText.trim().length < 20}
							onclick={doTextImport}
						>
							{#if importLoading}
								<span class="typing-indicator" style="display: inline-flex; justify-content: center;"><span></span><span></span><span></span></span>
							{:else}
								Import from Text
							{/if}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- Floating row action menu (portal) -->
{#if rowActionOpenId !== null}
	<div class="cv-share-overlay" onclick={closeRowAction}
		role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') closeRowAction(); }}></div>
	<div class="ink-border stamp-shadow cv-share-menu-floating"
		style="top: {rowActionPos.top}px; left: {rowActionPos.left}px;">
		<button onclick={(e) => { e.stopPropagation(); const id = rowActionOpenId; rowActionOpenId = null; if (id != null) goto(`/candidates/${id}`); }}>Open profile</button>
		<button onclick={(e) => { e.stopPropagation(); const id = rowActionOpenId; rowActionOpenId = null; if (id != null) toggleCvShare(id, e); }}>⇪ Share</button>
		<button onclick={(e) => rowReject(rowActionOpenId, e)}>Reject</button>
		<button onclick={(e) => rowDelete(rowActionOpenId, e)} style="color: var(--color-error);">Delete</button>
	</div>
{/if}

<!-- Floating CV share menu — multi-checkbox -->
{#if cvShareOpenId !== null}
	{@const _curCv = candidates.find(c => c.id === cvShareOpenId) || {}}
	<div class="cv-share-overlay" onclick={closeCvShare}
		role="button" tabindex="-1" onkeydown={(e) => { if (e.key === 'Escape') closeCvShare(); }}></div>
	<div class="ink-border stamp-shadow cv-share-menu-floating"
		style="top: {cvSharePos.top}px; left: {cvSharePos.left}px; min-width: 240px;">
		<div style="padding: 10px 14px; border-bottom: 2px solid var(--color-on-surface); font-size: 11px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase;">
			Share Candidate
		</div>
		<label style="display: flex; align-items: center; gap: 8px; padding: 10px 14px; cursor: pointer; border-bottom: 1px solid rgba(56,56,50,0.15);">
			<input type="checkbox" checked={!!_curCv.shared_sector} onchange={(e) => shareCvMulti(cvShareOpenId, { shared_sector: e.target.checked, shared_global: !!_curCv.shared_global }, e)} />
			<div>
				<div style="font-size: 11px; font-weight: 900;">▣ Share to my Sector</div>
				<div style="font-size: 9px; opacity: 0.7;">visible to sector members</div>
			</div>
		</label>
		<label style="display: flex; align-items: center; gap: 8px; padding: 10px 14px; cursor: pointer; border-bottom: 1px solid rgba(56,56,50,0.15);">
			<input type="checkbox" checked={!!_curCv.shared_global} onchange={(e) => shareCvMulti(cvShareOpenId, { shared_sector: !!_curCv.shared_sector, shared_global: e.target.checked }, e)} />
			<div>
				<div style="font-size: 11px; font-weight: 900;">◉ Add to Talent Pool</div>
				<div style="font-size: 9px; opacity: 0.7;">org-wide (admin only)</div>
			</div>
		</label>
		<button onclick={(e) => shareCvMulti(cvShareOpenId, { shared_sector: false, shared_global: false }, e)}
			style="display: block; width: 100%; text-align: left; padding: 10px 14px; border: none; font-size: 11px; font-weight: 700; cursor: pointer; background: transparent;">
			▮ Make private (uncheck both)
		</button>
	</div>
{/if}

{#if openMergeId}
	<MergeModal
		proposalId={openMergeId}
		onClose={() => (openMergeId = null)}
		onResolved={() => { openMergeId = null; loadMergeProposals(); loadCandidates(); }}
	/>
{/if}

<style>
	/* ── Claude warm theme tokens (scoped fallbacks) ── */
	:root {
		--cv-bg: var(--color-bg, #faf9f5);
		--cv-surface: var(--color-surface, #ffffff);
		--cv-surface-warm: #f4f3ee;
		--cv-bg-alt: #f0eee5;
		--cv-ink: #2c2c2c;
		--cv-ink-soft: #4a4a48;
		--cv-muted: #6f6e69;
		--cv-dim: #97968f;
		--cv-accent: #c96342;
		--cv-accent-ink: #b04f30;
		--cv-accent-soft: #fdebe1;
		--cv-accent-bg: #faf2ed;
		--cv-border: #e8e6dd;
		--cv-border-soft: #efeee6;
		--cv-border-strong: #d8d5cb;
		--cv-green: #2d6a4f;
		--cv-green-soft: #d8e4dd;
		--cv-amber: #a06000;
		--cv-red: #a83232;
		--cv-red-soft: #f5dada;
	}

	/* ── Page header ── */
	.cv-page-title {
		font-size: 26px; font-weight: 500; margin: 0;
		font-family: 'Tiempos Headline', 'Charter', 'Source Serif Pro', Georgia, serif;
		letter-spacing: -0.025em; line-height: 1.15; color: var(--cv-ink);
	}
	.cv-page-sub {
		font-size: 13px; color: var(--cv-muted); margin-top: 6px;
		text-transform: none; letter-spacing: 0;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}

	/* ── Buttons (pill, sentence-case) ── */
	.cv-btn {
		display: inline-flex; align-items: center; gap: 6px;
		padding: 7px 14px; border-radius: 999px;
		background: var(--cv-surface); color: var(--cv-ink);
		border: 1px solid var(--cv-border-strong);
		font-size: 13px; font-weight: 500;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		cursor: pointer; transition: background .15s, border-color .15s;
		white-space: nowrap;
	}
	.cv-btn:hover:not(:disabled) { background: var(--cv-surface-warm); }
	.cv-btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.cv-btn-primary {
		background: var(--cv-accent); color: #fff; border-color: var(--cv-accent);
	}
	.cv-btn-primary:hover:not(:disabled) { background: var(--cv-accent-ink); border-color: var(--cv-accent-ink); }
	.cv-btn-danger {
		background: var(--cv-red-soft); color: var(--cv-red);
		border-color: #f0c2c2;
	}
	.cv-btn-danger:hover:not(:disabled) { background: #f0c2c2; }
	.cv-btn-accent {
		background: var(--cv-accent-bg); color: var(--cv-accent-ink);
		border-color: var(--cv-accent-soft);
	}
	.cv-btn-sm { padding: 5px 12px; font-size: 12.5px; }
	.cv-btn-rel { position: relative; }
	.cv-btn-ai { padding: 6px 12px; }
	.cv-btn-ai.on {
		background: var(--cv-accent); color: #fff; border-color: var(--cv-accent);
	}
	.cv-badge-count {
		margin-left: 4px;
		background: var(--cv-accent-bg); color: var(--cv-accent-ink);
		font-size: 11px; font-weight: 600;
		padding: 1px 7px; border-radius: 999px;
		border: 1px solid var(--cv-accent-soft);
	}

	/* ── Search input ── */
	.cv-search-input {
		flex: 1; padding: 8px 14px;
		border: 1px solid var(--cv-border-strong);
		border-radius: 8px;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		font-size: 13px; font-weight: 400;
		background: var(--cv-surface); color: var(--cv-ink);
		text-transform: none; letter-spacing: 0;
		transition: border-color .15s, box-shadow .15s;
	}
	.cv-search-input::placeholder { color: var(--cv-muted); }
	.cv-search-input:focus {
		outline: none; border-color: var(--cv-accent);
		box-shadow: 0 0 0 3px var(--cv-accent-bg);
	}
	.cv-search-input.ai { border-color: var(--cv-accent); background: var(--cv-accent-bg); }

	/* ── Select ── */
	.cv-select {
		padding: 6px 10px; border-radius: 8px;
		border: 1px solid var(--cv-border-strong);
		background: var(--cv-surface); color: var(--cv-ink);
		font-family: 'Inter', sans-serif; font-size: 12.5px; font-weight: 500;
		cursor: pointer;
	}

	/* ── Popover ── */
	.cv-popover {
		background: var(--cv-surface);
		border: 1px solid var(--cv-border);
		border-radius: 8px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.08);
		overflow: hidden;
	}
	.cv-popover-item {
		display: block; width: 100%; text-align: left;
		padding: 8px 14px; border: none;
		font-family: 'Inter', sans-serif;
		font-size: 13px; font-weight: 500; color: var(--cv-ink);
		cursor: pointer; background: transparent;
		text-transform: none; letter-spacing: 0;
	}
	.cv-popover-item:hover { background: var(--cv-surface-warm); }

	/* ── Compare bar ── */
	.cv-compare-bar {
		display: flex; align-items: center; gap: 10px;
		padding: 10px 14px; margin-bottom: 14px;
		background: var(--cv-surface-warm);
		border: 1px solid var(--cv-border);
		border-radius: 8px;
	}
	.cv-compare-label {
		font-size: 12px; font-weight: 600; color: var(--cv-ink-soft);
		font-family: 'Inter', sans-serif;
	}
	.cv-compare-count {
		font-size: 12px; color: var(--cv-muted);
		padding: 3px 10px; border-radius: 999px;
		background: var(--cv-surface); border: 1px solid var(--cv-border);
	}
	.cv-compare-sep {
		display: inline-block; width: 1px; height: 20px;
		background: var(--cv-border-strong); margin: 0 4px;
	}

	/* ── Select-all bar ── */
	.cv-selectall-label {
		font-size: 12.5px; font-weight: 500; color: var(--cv-muted);
		text-transform: none; letter-spacing: 0;
		font-family: 'Inter', sans-serif;
	}
	.cv-queue-hint {
		margin-left: 8px; font-size: 12px; font-weight: 500;
		color: var(--cv-muted); font-family: 'Inter', sans-serif;
		text-transform: none; letter-spacing: 0;
	}

	/* ── Running banner ── */
	.cv-running-banner {
		display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
		padding: 10px 14px;
		background: var(--cv-accent-bg);
		border: 1px solid var(--cv-accent-soft);
		border-radius: 8px;
		margin-bottom: 10px;
	}
	.cv-running-label {
		font-size: 12px; font-weight: 600;
		color: var(--cv-accent-ink); white-space: nowrap;
		font-family: 'Inter', sans-serif;
	}
	.cv-running-chip {
		background: var(--cv-surface);
		border: 1px solid var(--cv-border);
		border-radius: 999px;
		padding: 4px 10px;
		font-family: 'Inter', sans-serif;
		font-size: 11.5px; font-weight: 500; color: var(--cv-ink);
		cursor: pointer; display: inline-flex; gap: 5px; align-items: center;
	}
	.cv-running-chip:hover { background: var(--cv-surface-warm); }
	.cv-running-sep { color: var(--cv-dim); }
	.cv-running-prog { color: var(--cv-accent-ink); font-weight: 600; }
	.cv-running-step { color: var(--cv-muted); }
	.cv-running-more { font-size: 11.5px; color: var(--cv-muted); }

	/* ── Table ── */
	.cv-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--cv-border);
		border-radius: 8px;
		margin-bottom: 16px;
		background: var(--cv-surface);
	}
	.cv-data-table { width: 100%; border-collapse: collapse; font-size: 13px; font-family: 'Inter', sans-serif; }
	.cv-data-table th, .cv-data-table td { padding: 10px 12px; text-align: left; vertical-align: middle; color: var(--cv-ink); }
	.sort-ind { font-size: 9px; opacity: 0.4; margin-left: 3px; letter-spacing: -1px; color: var(--cv-muted); }
	.sort-ind.sort-on { opacity: 1; color: var(--cv-accent); font-weight: 600; }
	.cv-th-labels th.sort-active { box-shadow: inset 0 -2px var(--cv-accent); }
	.row-action-more { font-size: 14px; padding: 2px 8px; visibility: hidden; line-height: 1; color: var(--cv-muted); }
	.cv-row:hover .row-action-more { visibility: visible; }
	.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
	.drop-zone-compact {
		height: 40px; display: flex; align-items: center; justify-content: center;
		border: 1px dashed var(--cv-border-strong); border-radius: 8px;
		background: var(--cv-surface-warm);
		cursor: pointer; user-select: none;
		color: var(--cv-muted); font-size: 13px;
	}
	.drop-zone-compact:hover { background: var(--cv-accent-bg); border-color: var(--cv-accent); color: var(--cv-accent-ink); }
	.drop-zone-compact.drop-zone-active { background: var(--cv-accent-bg); border-style: solid; border-color: var(--cv-accent); color: var(--cv-accent-ink); }
	.cv-th-labels th {
		background: var(--cv-surface-warm); color: var(--cv-ink-soft);
		font-size: 12px; font-weight: 600; letter-spacing: 0;
		text-transform: none; user-select: none; white-space: nowrap;
		position: sticky; top: 0; z-index: 2;
		border-bottom: 1px solid var(--cv-border);
	}
	.cv-th-filters td {
		background: var(--cv-surface);
		border-top: 1px solid var(--cv-border-soft);
		border-bottom: 1px solid var(--cv-border);
		padding: 6px 8px;
	}
	.cv-row { cursor: pointer; border-top: 1px solid var(--cv-border-soft); transition: background 180ms; outline: none; }
	.cv-row:hover { background: var(--cv-surface-warm); cursor: pointer; }
	.cv-row-focus,
	.cv-row:focus,
	.cv-row:focus-visible {
		box-shadow: inset 0 0 0 2px var(--color-accent, #c96342);
		outline: none;
	}
	/* SELECTED ROW — soft coral tint, coral left-border, readable text */
	.cv-row.st-row-running,
	.cv-row.cv-row-selected { background: var(--cv-accent-bg); border-left: 4px solid var(--cv-accent); color: var(--cv-ink); }
	.cv-row.st-row-running td,
	.cv-row.cv-row-selected td { color: var(--cv-ink); }
	.cv-row.cv-row-selected:hover { background: var(--cv-accent-soft); }
	.cv-row.row-flash { animation: rowFlash 1.5s ease-out; }
	@keyframes rowFlash {
		0% { background: var(--cv-accent-soft); }
		100% { background: transparent; }
	}
	.filt {
		width: 100%; padding: 5px 8px; font-size: 12px;
		border: 1px solid var(--cv-border-strong); border-radius: 6px;
		font-family: 'Inter', sans-serif;
		background: var(--cv-surface); color: var(--cv-ink);
	}
	.vis-badge {
		display: inline-flex; align-items: center;
		padding: 2px 9px; border-radius: 999px;
		font-size: 11px; font-weight: 500; letter-spacing: 0;
		border: 1px solid var(--cv-border);
	}
	.vis-private { background: var(--cv-surface-warm); color: var(--cv-ink-soft); border-color: var(--cv-border); }
	.vis-sector  { background: var(--cv-green-soft); color: var(--cv-green); border-color: var(--cv-green-soft); }
	.vis-global  { background: var(--cv-accent-bg); color: var(--cv-accent-ink); border-color: var(--cv-accent-soft); }
	.row-action {
		font-size: 12px; padding: 4px 10px;
		border: 1px solid var(--cv-border); border-radius: 6px;
		background: transparent; color: var(--cv-muted);
		font-weight: 500; cursor: pointer;
	}
	.row-action:hover { background: var(--cv-surface-warm); color: var(--cv-ink); }
	/* Mini stop button (in-row pipeline) */
	.cv-mini-stop {
		margin-left: 6px; background: var(--cv-red-soft); color: var(--cv-red);
		border: 1px solid #f0c2c2; border-radius: 6px;
		padding: 2px 8px; font-size: 11px; font-weight: 500;
		cursor: pointer; font-family: 'Inter', sans-serif;
	}
	.cv-mini-stop:hover { background: #f0c2c2; }
	.cv-queue-pill {
		display: inline-flex; align-items: center;
		padding: 4px 10px; border-radius: 999px;
		background: var(--cv-surface-warm); color: var(--cv-amber);
		font-size: 11.5px; font-weight: 500;
		border: 1px solid var(--cv-border);
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
	.cv-share-overlay { position: fixed; inset: 0; z-index: 999; background: transparent; }
	.cv-share-menu-floating {
		position: fixed; z-index: 1000;
		background: var(--color-surface);
		min-width: 220px;
	}
	.cv-share-menu-floating button {
		display: block; width: 100%; text-align: left;
		padding: 8px 12px; border: none;
		border-bottom: 1px solid rgba(56,56,50,0.2);
		font-size: 11px; font-weight: 700;
		cursor: pointer; background: transparent;
	}
	.cv-share-menu-floating button:last-child { border-bottom: none; }
	.cv-share-menu-floating button:hover { background: var(--color-surface-bright); }
	.ts-cell { white-space: nowrap; }
	.ts-abs { font-size: 11px; font-weight: 700; }
	.ts-rel { font-size: 9px; color: var(--color-on-surface-dim); margin-top: 1px; letter-spacing: 0.04em; text-transform: uppercase; }

	/* ── LinkedIn-style split-pane layout (independent scroll) ── */
	.cv-page-wrap {
		display: flex; flex-direction: column;
		height: 100vh;
		background: var(--cv-bg);
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		color: var(--cv-ink);
		position: relative;
	}
	.cv-split {
		flex: 1 1 auto;
		display: grid;
		grid-template-columns: 280px 1fr;
		min-height: 0;
	}
	.cv-rail {
		overflow-y: auto;
		border-right: 1px solid var(--cv-border);
		padding: 16px 12px 140px 12px;
		background: var(--color-surface, #ffffff);
	}
	.cv-main {
		padding-bottom: 140px !important;
	}
	.cv-main {
		min-width: 0;
		padding: 16px 20px 24px 20px;
		overflow-y: auto;
		overflow-x: hidden;
	}
	@media (max-width: 900px) {
		.cv-split { grid-template-columns: 1fr; grid-auto-flow: row; }
		.cv-rail { border-right: none; border-bottom: 1px solid var(--cv-border); }
	}

	/* Full-page drop overlay */
	.cv-drop-overlay {
		position: absolute; inset: 0;
		z-index: 200;
		background: rgba(250,242,237,0.94);
		border: 3px dashed var(--cv-accent);
		border-radius: 12px;
		display: flex; align-items: center; justify-content: center;
		pointer-events: none;
	}
	.cv-drop-overlay-inner {
		text-align: center;
		font-family: 'Inter', sans-serif;
		color: var(--cv-ink);
	}
	.cv-drop-overlay-plus { font-size: 64px; font-weight: 500; line-height: 1; color: var(--cv-accent); }
	.cv-drop-overlay-text {
		font-size: 22px; font-weight: 500;
		text-transform: none; letter-spacing: 0;
		margin-top: 10px;
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		color: var(--cv-ink);
	}
	.cv-drop-overlay-sub {
		font-size: 13px; font-weight: 400;
		text-transform: none; letter-spacing: 0;
		color: var(--cv-muted); margin-top: 6px;
	}

	/* Status bar */
	.cv-status-bar {
		position: sticky; bottom: 0; left: 0; right: 0;
		z-index: 70;
		height: 34px;
		display: flex; align-items: center; gap: 10px;
		padding: 0 18px;
		background: var(--cv-surface-warm);
		color: var(--cv-ink-soft);
		border-top: 1px solid var(--cv-border);
		font-size: 12px; font-weight: 500;
		letter-spacing: 0; text-transform: none;
		font-family: 'Inter', sans-serif;
	}
	.sb-section { font-variant-numeric: tabular-nums; }
	.sb-running { color: var(--cv-amber); }
	.sb-done { color: var(--cv-green); }
	.sb-sep { color: var(--cv-dim); }
	.sb-ai { color: var(--cv-accent-ink); font-weight: 600; }
	.sb-cli-btn {
		margin-left: auto;
		background: var(--cv-surface); color: var(--cv-ink-soft);
		border: 1px solid var(--cv-border-strong); border-radius: 999px;
		padding: 3px 12px; font-size: 12px; font-weight: 500;
		letter-spacing: 0; cursor: pointer;
		font-family: 'Inter', sans-serif;
	}
	.sb-cli-btn:hover { background: var(--cv-surface-warm); color: var(--cv-ink); }

	/* Unified row primary/sub lines */
	.row-primary {
		font-weight: 600; font-size: 13.5px;
		display: inline-flex; align-items: center; gap: 6px;
		max-width: 360px;
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
		color: var(--cv-ink); letter-spacing: 0; text-transform: none;
		font-family: 'Inter', sans-serif;
	}
	.row-sub {
		font-size: 12px; color: var(--cv-muted);
		text-transform: none; letter-spacing: 0;
		max-width: 360px;
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
		font-family: 'Inter', sans-serif;
	}
	.err-msg { color: var(--cv-red); text-transform: none; letter-spacing: 0; }
	.dup-pill {
		border: 1px solid var(--cv-red-soft); background: var(--cv-red-soft); color: var(--cv-red);
		font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 999px;
		cursor: pointer; letter-spacing: 0;
	}

	/* Status dot column */
	.st-dot {
		display: inline-flex; align-items: center; justify-content: center;
		width: 22px; height: 22px; border-radius: 50%;
		font-size: 12px; font-weight: 600;
		border: 1px solid var(--cv-border);
	}
	.st-dot.st-pending { background: var(--cv-surface-warm); color: var(--cv-accent); border-color: var(--cv-accent-soft); }
	.st-dot.st-running { background: var(--cv-accent-bg); color: var(--cv-accent); border-color: var(--cv-accent-soft); animation: stp 1.2s ease-in-out infinite; }
	.st-dot.st-done    { background: var(--cv-green-soft); color: var(--cv-green); border-color: var(--cv-green-soft); }
	.st-dot.st-error   { background: var(--cv-red-soft); color: var(--cv-red); border-color: #f0c2c2; }
	@keyframes stp { 0%,100%{opacity:1;} 50%{opacity:.55;} }

	/* File icon (pre-DONE rows) */
	.file-icon {
		width: 28px; height: 28px; border-radius: 7px;
		display: flex; align-items: center; justify-content: center;
		border: 1px solid var(--cv-border);
		background: var(--cv-surface-warm); color: var(--cv-muted);
		font-size: 10px; font-weight: 600; letter-spacing: 0.02em;
	}

	/* Pipeline cell */
	.pipe-cell { display: flex; align-items: center; gap: 8px; min-width: 110px; }
	.pipe-bar {
		flex: 1; height: 6px; border-radius: 999px;
		background: var(--cv-surface-warm);
		overflow: hidden;
	}
	.pipe-fill { height: 100%; background: var(--cv-accent); border-radius: 999px; transition: width 240ms ease; }
	.pipe-txt { font-size: 11.5px; font-weight: 500; font-variant-numeric: tabular-nums; color: var(--cv-muted); font-family: 'Inter', sans-serif; }

	.btn-run, .btn-retry {
		background: var(--cv-accent); color: #fff;
		border: 1px solid var(--cv-accent);
		border-radius: 999px;
		padding: 5px 14px;
		font-size: 12px; font-weight: 500;
		cursor: pointer; font-family: 'Inter', sans-serif;
		letter-spacing: 0;
	}
	.btn-run:hover:not(:disabled), .btn-retry:hover:not(:disabled) { background: var(--cv-accent-ink); border-color: var(--cv-accent-ink); }
	.btn-retry { background: var(--cv-amber); border-color: var(--cv-amber); }
	.btn-retry:hover:not(:disabled) { background: #855000; border-color: #855000; }
	.btn-run:disabled, .btn-retry:disabled { opacity: 0.5; cursor: not-allowed; }

	.att-pill {
		font-size: 12px; padding: 3px 10px; border-radius: 999px;
		border: 1px solid var(--cv-border); background: var(--cv-surface-warm);
		text-decoration: none; color: var(--cv-ink-soft); font-weight: 500;
		letter-spacing: 0;
		display: inline-flex; align-items: center; gap: 6px;
		font-family: 'Inter', sans-serif;
	}
	.att-pill:hover { background: var(--cv-accent-bg); border-color: var(--cv-accent-soft); color: var(--cv-accent-ink); }
	.att-stage {
		background: var(--cv-surface); color: var(--cv-muted);
		padding: 1px 7px; border-radius: 999px;
		font-size: 10.5px; font-weight: 500;
		text-transform: capitalize; letter-spacing: 0;
		border: 1px solid var(--cv-border);
	}
	.att-more { font-size: 11px; color: var(--cv-muted); margin-left: 4px; }

	/* State-tinted row backgrounds — soft warm only, no neon */
	.cv-row.st-row-error   { background: rgba(168,50,50,0.04); }
	.cv-row.st-row-pending { background: transparent; }

	/* Recent searches dropdown */
	.recent-dropdown {
		position: absolute;
		top: calc(100% + 4px);
		left: 0; right: 0;
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0,0,0,0.08);
		z-index: 50;
		padding: 6px 0;
		max-height: 280px;
		overflow-y: auto;
	}
	.recent-dropdown-head {
		font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69);
		padding: 6px 14px 4px; font-weight: 600;
	}
	.recent-item {
		display: flex; align-items: center; gap: 8px;
		width: 100%; padding: 8px 14px;
		background: none; border: none;
		font-size: 13px; color: var(--color-on-surface, #2c2c2c);
		cursor: pointer; font-family: inherit; text-align: left;
	}
	.recent-item.active,
	.recent-item:hover { background: var(--color-surface-warm, #f4f3ee); }

	/* Saved-search pill row */
	.saved-pill-row {
		display: flex; flex-wrap: wrap; gap: 6px;
		align-items: center; margin: -4px 0 12px;
	}
	.saved-pill-label {
		font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
		color: var(--color-on-surface-dim, #6f6e69); font-weight: 600; margin-right: 4px;
	}
	.saved-pill {
		display: inline-flex; align-items: center; gap: 6px;
		padding: 4px 10px 4px 12px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px;
		font-size: 12px; color: var(--color-on-surface, #2c2c2c);
		cursor: pointer; font-family: inherit;
		transition: background .15s, border-color .15s;
	}
	.saved-pill:hover {
		background: var(--color-primary-container, #faf2ed);
		border-color: var(--color-primary, #c96342);
	}
	.saved-pill-x {
		display: inline-flex; align-items: center; justify-content: center;
		width: 14px; height: 14px; border-radius: 50%;
		font-size: 14px; line-height: 1;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.saved-pill-x:hover { background: var(--color-error-container, #f5dada); color: var(--color-error, #a83232); }

	/* ── Mobile responsiveness ── */
	.cv-mobile-filters-pill {
		display: none;
		align-items: center;
		gap: 6px;
		padding: 8px 14px;
		margin: 0 0 10px 0;
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px;
		font-size: 13px;
		font-weight: 500;
		color: var(--color-ink, #2c2c2c);
		cursor: pointer;
		font-family: inherit;
	}
	.cv-mobile-filters-pill:hover { background: var(--color-surface-warm, #f4f3ee); }

	/* Card list — mobile alternative to table */
	.cv-card-list { display: none; flex-direction: column; gap: 8px; }
	.cv-card {
		display: flex; flex-direction: column; gap: 6px;
		padding: 16px;
		background: var(--color-surface, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		cursor: pointer;
	}
	.cv-card:hover { border-color: var(--color-border-strong, #d8d5cb); }
	.cv-card-row1 {
		display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;
	}
	.cv-card-name {
		font-size: 14.5px; font-weight: 600;
		color: var(--color-ink, #2c2c2c);
		line-height: 1.3;
		flex: 1; min-width: 0;
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.cv-card-sub {
		font-size: 12px;
		color: var(--color-on-surface-dim, #6f6e69);
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.cv-card-meta {
		display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
		font-size: 12px;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.cv-card-meta-item {
		display: inline-flex; align-items: center; gap: 4px;
	}
	.cv-card-meta-item + .cv-card-meta-item::before {
		content: '·'; margin-right: 6px; color: var(--color-on-surface-dim, #97968f);
	}
	.cv-card-pill {
		display: inline-flex; align-items: center;
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 10px; font-weight: 700;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		flex-shrink: 0;
	}
	.st-pill-pending { background: var(--color-surface-warm, #f4f3ee); color: var(--color-on-surface-dim, #6f6e69); border: 1px solid var(--color-border, #e8e6dd); }
	.st-pill-running { background: var(--color-accent-bg, #faf2ed); color: var(--color-accent-ink, #b04f30); border: 1px solid var(--color-accent-soft, #fdebe1); }
	.st-pill-done { background: var(--color-success-soft, #d8e4dd); color: var(--color-success, #2d6a4f); border: 1px solid var(--color-success-soft, #d8e4dd); }
	.st-pill-error { background: var(--color-red-soft, #f5dada); color: var(--color-red, #a83232); border: 1px solid var(--color-red-soft, #f5dada); }
	.st-pill-stage { background: var(--color-surface-warm, #f4f3ee); color: var(--color-ink-soft, #4a4a48); border: 1px solid var(--color-border, #e8e6dd); }
	.cv-card-actions { display: flex; gap: 6px; margin-top: 4px; }

	@media (max-width: 768px) {
		.cv-mobile-filters-pill { display: inline-flex; }
		/* Hide left rail on mobile — accessed via bottom-sheet trigger */
		.cv-rail { display: none; }
		.cv-split { grid-template-columns: 1fr; }
		.cv-main { padding: 12px 14px 80px 14px; }
		/* Hide table, show cards */
		.cv-table-wrap { display: none; }
		.cv-card-list { display: flex; }
	}

	/* Mobile filters bottom-sheet */
	.cv-mfilt-overlay {
		position: fixed; inset: 0;
		background: rgba(56,56,50,0.45);
		z-index: 970;
		border: 0; padding: 0; cursor: pointer;
		animation: cvmf-fade 0.18s ease;
	}
	.cv-mfilt-sheet {
		position: fixed;
		left: 0; right: 0; bottom: 0;
		max-height: 85vh;
		background: var(--color-surface, #fff);
		border-top: 1px solid var(--color-border, #e8e6dd);
		border-radius: 16px 16px 0 0;
		z-index: 971;
		display: flex;
		flex-direction: column;
		box-shadow: 0 -8px 24px rgba(0,0,0,0.12);
		animation: cvmf-slide 0.22s ease;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}
	@keyframes cvmf-fade { from { opacity: 0; } to { opacity: 1; } }
	@keyframes cvmf-slide { from { transform: translateY(100%); } to { transform: translateY(0); } }

	.cv-mfilt-head {
		display: flex; align-items: center; justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.cv-mfilt-title { font-size: 15px; font-weight: 600; color: var(--color-ink, #2c2c2c); }
	.cv-mfilt-close {
		background: transparent;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 8px;
		width: 32px; height: 32px;
		display: inline-flex; align-items: center; justify-content: center;
		cursor: pointer;
	}
	.cv-mfilt-close:hover { background: var(--color-surface-warm, #f4f3ee); }
	.cv-mfilt-body { flex: 1; overflow-y: auto; padding: 12px 14px; }
	.cv-mfilt-foot {
		padding: 12px 16px;
		border-top: 1px solid var(--color-border, #e8e6dd);
		display: flex; justify-content: flex-end;
	}
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
