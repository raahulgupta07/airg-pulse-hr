<script>
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { apiJson, api } from '$lib/api.ts';
	import MergeModal from '$lib/MergeModal.svelte';
	import { addToast } from '$lib/Toast.svelte';
	import BrandingPanel from '$lib/admin/BrandingPanel.svelte';
	import EmailTemplatesPanel from '$lib/admin/EmailTemplatesPanel.svelte';
	import OfferTemplatesPanel from '$lib/admin/OfferTemplatesPanel.svelte';
	import IntegrationsPanel from '$lib/admin/IntegrationsPanel.svelte';
	import WorkflowsPanel from '$lib/admin/WorkflowsPanel.svelte';
	import AgentsPanel from '$lib/admin/AgentsPanel.svelte';
	import AgentsConfigPanel from '$lib/admin/AgentsConfigPanel.svelte';
	import RetentionPanel from '$lib/admin/RetentionPanel.svelte';

	const VALID_TABS = new Set([
		'users','roles','sectors','policy','merges','competencies',
		'audit','insights','analytics','system',
		'branding','email-templates','offer-templates','integrations','workflows',
		'agents','agent-config','retention',
	]);

	// Persist current admin tab; honour `#merges` deep link + `?tab=` URL param.
	function _initialTab() {
		if (typeof window === 'undefined') return 'users';
		try {
			const url = new URL(window.location.href);
			const qp = url.searchParams.get('tab');
			if (qp && VALID_TABS.has(qp)) return qp;
		} catch {}
		if (window.location.hash === '#merges') return 'merges';
		try { return localStorage.getItem('hire_admin_tab') || 'users'; } catch { return 'users'; }
	}
	let tab = $state(_initialTab());
	$effect(() => {
		try { localStorage.setItem('hire_admin_tab', tab); } catch {}
		// Mirror to URL ?tab= (replaceState so back-button doesn't accumulate history)
		if (typeof window !== 'undefined') {
			try {
				const url = new URL(window.location.href);
				if (url.searchParams.get('tab') !== tab) {
					url.searchParams.set('tab', tab);
					goto(url.pathname + url.search, { replaceState: true, noScroll: true, keepFocus: true });
				}
			} catch {}
		}
	});

	// --- Merges state ---
	let mergeStatus = $state('pending'); // pending | approved | rejected | reverted
	let mergeEntityType = $state(''); // '' = all
	let merges = $state([]);
	let mergesTotal = $state(0);
	let mergesLoading = $state(false);
	let openMergeId = $state(null);
	let mergeBulkRunning = $state(false);

	async function loadMerges() {
		mergesLoading = true;
		try {
			const params = new URLSearchParams({ status: mergeStatus, limit: '200' });
			if (mergeEntityType) params.set('entity_type', mergeEntityType);
			const d = await apiJson(`/merges/?${params}`);
			merges = d.items || [];
			mergesTotal = d.total ?? merges.length;
		} catch (e) {
			merges = []; mergesTotal = 0;
			addToast('error', e.message || 'Failed to load merges');
		}
		mergesLoading = false;
	}

	async function bulkApproveHighConfidence() {
		const targets = merges.filter(m => (m.confidence || 0) >= 0.95 && m.status === 'pending');
		if (targets.length === 0) { addToast('info', 'No proposals at ≥95% confidence'); return; }
		if (!confirm(`Approve ${targets.length} proposals at ≥95% confidence? Losers will be archived.`)) return;
		mergeBulkRunning = true;
		let ok = 0, fail = 0;
		for (const m of targets) {
			try {
				await apiJson(`/merges/${m.id}/approve`, {
					method: 'POST',
					body: JSON.stringify({ archive: true }),
				});
				ok++;
			} catch { fail++; }
		}
		mergeBulkRunning = false;
		addToast(fail ? 'error' : 'success', `Approved ${ok}${fail ? `, ${fail} failed` : ''}`);
		await loadMerges();
	}

	async function runSweep() {
		mergeBulkRunning = true;
		try {
			await apiJson('/merges/scan/sweep', {
				method: 'POST',
				body: JSON.stringify({ entity_type: mergeEntityType || 'candidate' }),
			});
			addToast('success', 'Sweep started — refreshing in 2s');
			setTimeout(loadMerges, 2000);
		} catch (e) {
			addToast('error', e.message || 'Sweep failed');
		}
		mergeBulkRunning = false;
	}

	function fmtConfidence(c) { return `${Math.round((c || 0) * 100)}%`; }
	function fmtDate(d) { return d ? String(d).replace('T', ' ').slice(0, 16) : '—'; }
	function summaryLabel(item, side) {
		const s = item.summary || {};
		return s[side] || `#${side === 'winner' ? item.winner_id : item.loser_id}`;
	}

	// Users
	let users = $state([]);
	let userTotal = $state(0);
	let userQ = $state('');
	let userRole = $state('');
	let userActive = $state('');
	let inviting = $state(false);
	let invite = $state({ email: '', display_name: '', role: 'recruiter', department: '' });

	// Roles
	let roles = $state([]);
	let permissions = $state([]);
	let creatingRole = $state(false);
	let newRole = $state({ name: '', label: '', perms: new Set() });
	let dirtyRoles = $state(new Set());

	// Audit
	let events = $state([]);
	let auditDays = $state(30);
	let auditAction = $state('');

	// Insights
	let insights = $state(null);

	// System
	let sysConfig = $state(null);

	async function loadUsers() {
		const params = new URLSearchParams();
		if (userQ) params.set('q', userQ);
		if (userRole) params.set('role', userRole);
		if (userActive !== '') params.set('is_active', userActive);
		const d = await apiJson(`/admin/users?${params}`);
		users = d.users; userTotal = d.total;
	}
	async function loadRoles() {
		const d = await apiJson('/admin/roles');
		roles = d.roles; permissions = d.permissions;
		dirtyRoles = new Set();
	}

	function hasPerm(role, key) {
		if (role.permissions?.all) return true;
		return (role.permissions?.keys || []).includes(key);
	}

	function togglePerm(role, key) {
		if (role.permissions?.all) return; // admin all-access locked
		const keys = new Set(role.permissions?.keys || []);
		if (keys.has(key)) keys.delete(key); else keys.add(key);
		role.permissions = { keys: Array.from(keys) };
		dirtyRoles.add(role.name);
		dirtyRoles = new Set(dirtyRoles);
	}

	async function saveRole(role) {
		await apiJson(`/admin/roles/${role.name}`, {
			method: 'PUT',
			body: JSON.stringify({ label: role.label, permissions: role.permissions }),
		});
		dirtyRoles.delete(role.name);
		dirtyRoles = new Set(dirtyRoles);
	}

	async function createRole() {
		if (!newRole.name || !newRole.label) { alert('name + label required'); return; }
		try {
			await apiJson('/admin/roles', {
				method: 'POST',
				body: JSON.stringify({
					name: newRole.name,
					label: newRole.label,
					permissions: { keys: Array.from(newRole.perms) },
				}),
			});
			newRole = { name: '', label: '', perms: new Set() };
			creatingRole = false;
			await loadRoles();
		} catch (e) { alert('Create failed: ' + e.message); }
	}

	async function deleteRole(role) {
		if (!confirm(`Delete role "${role.name}"?`)) return;
		try {
			await apiJson(`/admin/roles/${role.name}`, { method: 'DELETE' });
			await loadRoles();
		} catch (e) { alert('Delete failed: ' + e.message); }
	}

	function togglePermNew(key) {
		if (newRole.perms.has(key)) newRole.perms.delete(key);
		else newRole.perms.add(key);
		newRole = { ...newRole, perms: new Set(newRole.perms) };
	}
	async function loadAudit() {
		const params = new URLSearchParams({ days: String(auditDays) });
		if (auditAction) params.set('action', auditAction);
		const d = await apiJson(`/admin/audit?${params}`);
		events = d.events;
	}
	// ── GDPR helpers (export/delete a user's data) ──────────────────
	async function gdprExport(userId, label) {
		if (!userId) { alert('No user id on this audit row.'); return; }
		let payload = null;
		try {
			payload = await apiJson(`/users/${userId}/gdpr-export`);
		} catch {
			// Fallback: composite call from public endpoints
			const composite = { user: null, candidates: [], notifications: [], _generated_at: new Date().toISOString(), _source: 'composite_fallback' };
			try { composite.user = await apiJson(`/users/${userId}`); } catch {}
			try {
				const c = await apiJson(`/candidates?owner_id=${userId}&limit=500`);
				composite.candidates = c.candidates || c.items || [];
			} catch {}
			try {
				const n = await apiJson(`/notifications?user_id=${userId}&limit=500`);
				composite.notifications = n.notifications || [];
			} catch {}
			payload = composite;
		}
		const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `gdpr_export_${label || userId}.json`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}

	let gdprDeleteTarget = $state(null); // { id, label }
	function openGdprDelete(id, label) { gdprDeleteTarget = { id, label }; }
	function closeGdprDelete() { gdprDeleteTarget = null; }
	async function confirmGdprDelete() {
		const t = gdprDeleteTarget;
		if (!t) return;
		try {
			await apiJson(`/users/${t.id}?gdpr=true`, { method: 'DELETE' });
			alert(`User ${t.label || t.id} GDPR-deleted.`);
			gdprDeleteTarget = null;
			await loadAudit();
		} catch (e) {
			alert('GDPR deletion requires backend support. Endpoint not available.');
			gdprDeleteTarget = null;
		}
	}

	async function loadInsights() { insights = await apiJson('/admin/insights'); }
	async function loadSystem()  { sysConfig = await apiJson('/admin/system/config'); }

	async function doInvite() {
		try {
			await apiJson('/admin/users', { method: 'POST', body: JSON.stringify(invite) });
			invite = { email: '', display_name: '', role: 'recruiter', department: '' };
			inviting = false;
			await loadUsers();
		} catch (e) { alert('Invite failed: ' + e.message); }
	}

	async function toggleUser(u) {
		await apiJson(`/admin/users/${u.id}`, {
			method: 'PATCH',
			body: JSON.stringify({ is_active: !u.is_active }),
		});
		await loadUsers();
	}
	async function revokeTokens(u) {
		if (!confirm(`Revoke all tokens for ${u.email}?`)) return;
		await apiJson(`/admin/users/${u.id}/revoke`, { method: 'POST' });
		alert('Tokens revoked');
	}
	async function setRoleFor(u, role) {
		await apiJson(`/admin/users/${u.id}`, { method: 'PATCH', body: JSON.stringify({ role }) });
		await loadUsers();
	}
	async function toggleFlag(flag) {
		const newVal = !flag.value;
		await apiJson(`/admin/system/config/${flag.key}`, {
			method: 'PATCH',
			body: JSON.stringify({ value: newVal }),
		});
		await loadSystem();
	}

	$effect(() => {
		const t = tab;
		untrack(() => {
			if (t === 'users') { loadUsers(); if (roles.length === 0) loadRoles(); }
			else if (t === 'roles') loadRoles();
			else if (t === 'audit') loadAudit();
			else if (t === 'insights') loadInsights();
			else if (t === 'system') loadSystem();
			else if (t === 'analytics') loadInsights();
			else if (t === 'sectors') loadSectorsAdmin();
			else if (t === 'policy') loadPolicy();
			else if (t === 'merges') loadMerges();
			else if (t === 'competencies') loadCompetenciesAdmin();
		});
	});

	onMount(loadUsers);

	const TABS = [
		{ id: 'users',     label: 'Users' },
		{ id: 'roles',     label: 'Roles' },
		{ id: 'sectors',   label: 'Sectors' },
		{ id: 'policy',    label: 'Policy' },
		{ id: 'merges',    label: 'Merges' },
		{ id: 'competencies', label: 'Competencies' },
		{ id: 'audit',     label: 'Audit log' },
		{ id: 'insights',  label: 'Insights' },
		{ id: 'analytics', label: 'Analytics' },
		{ id: 'system',    label: 'System' },
		{ id: 'branding',         label: 'Branding' },
		{ id: 'email-templates',  label: 'Email templates' },
		{ id: 'offer-templates',  label: 'Offer templates' },
		{ id: 'integrations',     label: 'Integrations' },
		{ id: 'workflows',        label: 'Workflows' },
		{ id: 'agents',           label: 'Agents' },
		{ id: 'agent-config',     label: 'Agent Config' },
		{ id: 'retention',        label: 'Retention' },
	];

	// ── Competencies admin ──
	let compLibrary = $state([]);
	let compFrameworks = $state([]);
	let compFramework = $state('');
	let compSearch = $state('');
	let compCategory = $state('');
	let compEditing = $state(null); // null | 'new' | competency object
	let compForm = $state({ key: '', label: '', category: '', description: '', level_descriptors: '', star_questions: '' });
	let compSaving = $state(false);

	async function loadCompetenciesAdmin() {
		try {
			const d = await apiJson('/competencies');
			compLibrary = d.competencies || d || [];
		} catch (e) { compLibrary = []; }
		try {
			const d = await apiJson('/competencies/frameworks');
			compFrameworks = d.frameworks || [];
		} catch (e) { compFrameworks = []; }
	}

	let filteredCompLibrary = $derived.by(() => {
		const q = (compSearch || '').toLowerCase();
		return compLibrary.filter(c => {
			if (compCategory && c.category !== compCategory) return false;
			if (q && !((c.key || '').toLowerCase().includes(q) || (c.label || '').toLowerCase().includes(q))) return false;
			return true;
		});
	});

	let compCategories = $derived(Array.from(new Set(compLibrary.map(c => c.category).filter(Boolean))));

	function openCompNew() {
		compEditing = 'new';
		compForm = { key: '', label: '', category: '', description: '', level_descriptors: '', star_questions: '' };
	}
	function openCompEdit(c) {
		compEditing = c;
		compForm = {
			key: c.key || '',
			label: c.label || '',
			category: c.category || '',
			description: c.description || '',
			level_descriptors: typeof c.level_descriptors === 'string' ? c.level_descriptors : JSON.stringify(c.level_descriptors || {}, null, 2),
			star_questions: typeof c.star_questions === 'string' ? c.star_questions : JSON.stringify(c.star_questions || [], null, 2),
		};
	}
	function closeCompModal() { compEditing = null; }

	async function saveComp() {
		compSaving = true;
		let levelDesc = {};
		let starQ = [];
		try { if (compForm.level_descriptors.trim()) levelDesc = JSON.parse(compForm.level_descriptors); }
		catch (e) { addToast('error', 'Level descriptors must be valid JSON'); compSaving = false; return; }
		try { if (compForm.star_questions.trim()) starQ = JSON.parse(compForm.star_questions); }
		catch (e) { addToast('error', 'STAR questions must be valid JSON'); compSaving = false; return; }
		const body = {
			key: compForm.key,
			label: compForm.label,
			category: compForm.category,
			description: compForm.description,
			level_descriptors: levelDesc,
			star_questions: starQ,
		};
		try {
			if (compEditing === 'new') {
				await apiJson('/competencies', { method: 'POST', body: JSON.stringify(body) });
				addToast('success', 'Competency created');
			} else {
				await apiJson(`/competencies/${compEditing.id}`, { method: 'PUT', body: JSON.stringify(body) });
				addToast('success', 'Competency updated');
			}
			compEditing = null;
			await loadCompetenciesAdmin();
		} catch (e) {
			addToast('error', e.message || 'Save failed');
		}
		compSaving = false;
	}

	async function deleteComp(c) {
		if (!confirm(`Delete competency "${c.label || c.key}"?`)) return;
		try {
			await apiJson(`/competencies/${c.id}`, { method: 'DELETE' });
			addToast('success', 'Deleted');
			await loadCompetenciesAdmin();
		} catch (e) { addToast('error', e.message || 'Delete failed'); }
	}

	async function toggleCompActive(c) {
		try {
			await apiJson(`/competencies/${c.id}`, {
				method: 'PUT',
				body: JSON.stringify({ ...c, active: !c.active }),
			});
			await loadCompetenciesAdmin();
		} catch (e) { addToast('error', e.message || 'Toggle failed'); }
	}

	let sectors = $state([]);
	let policy = $state([]);
	async function loadSectorsAdmin() {
		try { const d = await apiJson('/admin/sectors'); sectors = d.sectors || []; } catch {}
	}
	async function loadPolicy() {
		try { const d = await apiJson('/admin/scoring-policy'); policy = d.policy || []; } catch {}
	}
	async function saveSector(s) {
		try {
			await apiJson(`/admin/sectors/${s.id}/weights`, {
				method: 'PUT',
				body: JSON.stringify({
					weight_skills: s.weight_skills,
					weight_experience: s.weight_experience,
					weight_industry: s.weight_industry,
					weight_education: s.weight_education,
					weight_certifications: s.weight_certifications,
					weight_culture: s.weight_culture,
					forced_dims: s.forced_dims || [],
				}),
			});
			alert('Sector saved');
			await loadSectorsAdmin();
		} catch (e) { alert('Save failed: ' + e.message); }
	}
	function toggleForced(s, dim) {
		const list = s.forced_dims || [];
		if (Array.isArray(list)) {
			s.forced_dims = list.includes(dim) ? list.filter(d => d !== dim) : [...list, dim];
		} else {
			s.forced_dims = [dim];
		}
		sectors = sectors;
	}
	async function savePolicy() {
		try {
			await apiJson('/admin/scoring-policy', {
				method: 'PUT',
				body: JSON.stringify({ entries: policy }),
			});
			alert('Policy saved');
			await loadPolicy();
		} catch (e) { alert('Save failed: ' + e.message); }
	}

	function categoryClass(cat) {
		const c = (cat || '').toLowerCase();
		if (c.includes('deliver')) return 'pill-cat pill-cat-delivery';
		if (c.includes('lead')) return 'pill-cat pill-cat-leadership';
		if (c.includes('people')) return 'pill-cat pill-cat-people';
		return 'pill-cat pill-cat-default';
	}
	function titleCase(s) {
		if (!s) return '';
		return String(s).charAt(0).toUpperCase() + String(s).slice(1).toLowerCase();
	}
</script>

<div class="admin-shell">
	<div class="admin-fixed">
		<div class="admin-page-header">
			<h1 class="page-title">Admin console</h1>
			<p class="page-sub">System, access, audit, insights</p>
		</div>

		<!-- Tabs -->
		<div class="tab-row">
			{#each TABS as t}
				<button
					onclick={() => (tab = t.id)}
					class:tab-active={tab === t.id}
					class="tab-btn">
					{t.label}
				</button>
			{/each}
		</div>
	</div>

	<div class="admin-scroll">
		{#if tab === 'users'}
			<div class="filter-row">
				<input class="claude-input" bind:value={userQ} placeholder="Search…" oninput={loadUsers} style="flex: 1; min-width: 200px;" />
				<select class="claude-input" bind:value={userRole} onchange={loadUsers}>
					<option value="">All roles</option>
					{#each roles as r}
						<option value={r.name}>{titleCase(r.name)}</option>
					{/each}
				</select>
				<select class="claude-input" bind:value={userActive} onchange={loadUsers}>
					<option value="">All status</option>
					<option value="true">Active</option>
					<option value="false">Disabled</option>
				</select>
				<button class="btn-primary" onclick={() => (inviting = !inviting)}>+ Invite</button>
			</div>

			{#if inviting}
				<div class="claude-card" style="padding: 14px; margin-bottom: 14px;">
					<div class="card-title">Invite user</div>
					<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px;">
						<input class="claude-input" bind:value={invite.email} placeholder="Email" />
						<input class="claude-input" bind:value={invite.display_name} placeholder="Display name" />
						<select class="claude-input" bind:value={invite.role}>
							{#each roles as r}
								<option value={r.name}>{titleCase(r.name)}</option>
							{/each}
						</select>
						<input class="claude-input" bind:value={invite.department} placeholder="Department" />
					</div>
					<div style="margin-top: 10px; display: flex; gap: 8px;">
						<button class="btn-primary" onclick={doInvite}>Create</button>
						<button class="btn-ghost" onclick={() => (inviting = false)}>Cancel</button>
					</div>
				</div>
			{/if}

			<div class="claude-table-wrap">
			<table class="claude-table">
				<thead>
					<tr>
						<th>Name</th>
						<th>Email</th>
						<th>Role</th>
						<th>Status</th>
						<th>Last login</th>
						<th style="text-align: right;">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each users as u}
						<tr>
							<td>{u.display_name}</td>
							<td>{u.email}</td>
							<td>
								<select class="claude-input claude-input-sm" value={u.role} onchange={(e) => setRoleFor(u, e.target.value)}>
									{#each roles as r}
										<option value={r.name}>{titleCase(r.name)}</option>
									{/each}
								</select>
							</td>
							<td>
								<span class="status-dot {u.is_active ? 'on' : 'off'}"></span>
								{u.is_active ? 'Active' : 'Disabled'}
							</td>
							<td style="font-size: 11px; color: var(--color-muted, #6b6b6b);">{u.last_login || '—'}</td>
							<td style="text-align: right;">
								<button class="btn-pill" onclick={() => toggleUser(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>
								<button class="btn-pill" onclick={() => revokeTokens(u)}>Revoke</button>
							</td>
						</tr>
					{/each}
					{#if users.length === 0}
						<tr><td colspan="6" style="padding: 24px; text-align: center; color: var(--color-muted, #6b6b6b);">No users</td></tr>
					{/if}
				</tbody>
			</table>
			</div>
			<div class="meta-line">{userTotal} total</div>

		{:else if tab === 'roles'}
			<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
				<div class="section-title">Roles & permissions <span style="font-weight: 400; color: var(--color-muted, #6b6b6b); font-size: 12px;">— click cells to toggle</span></div>
				<button class="btn-primary" onclick={() => (creatingRole = !creatingRole)}>+ New role</button>
			</div>

			{#if creatingRole}
				<div class="claude-card" style="padding: 14px; margin-bottom: 14px;">
					<div class="card-title">Create role</div>
					<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px;">
						<input class="claude-input" bind:value={newRole.name} placeholder="name (lowercase, no spaces — e.g. sourcer)" />
						<input class="claude-input" bind:value={newRole.label} placeholder="Label (e.g. Sourcer)" />
					</div>
					<div style="font-size: 11px; color: var(--color-muted, #6b6b6b); margin-bottom: 6px;">Pick permissions</div>
					<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px; max-height: 220px; overflow-y: auto; padding: 10px; border: 1px solid var(--color-border, #e7e3d8); border-radius: 8px; background: var(--color-bg-cream, #faf8f3);">
						{#each permissions as p}
							<label style="display: flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer;">
								<input type="checkbox" checked={newRole.perms.has(p.key)} onchange={() => togglePermNew(p.key)} />
								<span><strong style="font-weight: 600;">{p.key}</strong></span>
							</label>
						{/each}
					</div>
					<div style="margin-top: 10px; display: flex; gap: 8px;">
						<button class="btn-primary" onclick={createRole}>Create</button>
						<button class="btn-ghost" onclick={() => (creatingRole = false)}>Cancel</button>
					</div>
				</div>
			{/if}

			<div class="claude-table-wrap">
			<table class="claude-table" style="min-width: 800px;">
				<thead>
					<tr>
						<th style="min-width: 220px;">Permission</th>
						{#each roles as r}
							<th style="min-width: 110px; text-align: center;">
								<div>{titleCase(r.name)}</div>
								<div style="font-size: 10px; color: var(--color-muted, #6b6b6b); font-weight: 400; margin-top: 2px;">{r.is_system ? 'System' : 'Custom'}</div>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each permissions as p}
						<tr>
							<td><strong style="font-weight: 600;">{p.key}</strong><br/><span style="font-size: 11px; color: var(--color-muted, #6b6b6b);">{p.description}</span></td>
							{#each roles as r}
								<td style="text-align: center;">
									<button
										class="perm-toggle"
										class:on={hasPerm(r,p.key)}
										onclick={() => togglePerm(r, p.key)}
										disabled={r.permissions?.all}
										style="cursor: {r.permissions?.all ? 'not-allowed' : 'pointer'}; opacity: {r.permissions?.all ? 0.6 : 1};">
										{hasPerm(r,p.key) ? '✓' : '○'}
									</button>
								</td>
							{/each}
						</tr>
					{/each}
					<tr style="background: var(--color-bg-cream, #f4f3ee);">
						<td style="font-weight: 600;">Actions</td>
						{#each roles as r}
							<td style="text-align: center;">
								{#if dirtyRoles.has(r.name)}
									<button class="btn-primary btn-sm" onclick={() => saveRole(r)}>Save</button>
								{:else if !r.is_system}
									<button class="btn-pill danger" onclick={() => deleteRole(r)}>Delete</button>
								{:else}
									<span style="font-size: 10px; color: var(--color-muted, #6b6b6b);">Locked</span>
								{/if}
							</td>
						{/each}
					</tr>
				</tbody>
			</table>
			</div>
			<div class="meta-line">✓ granted &nbsp;&nbsp; ○ denied &nbsp;&nbsp; Admin role has all-access (cannot edit)</div>

		{:else if tab === 'sectors'}
			<div class="section-title" style="margin-bottom: 12px;">Sector defaults <span style="font-weight: 400; color: var(--color-muted, #6b6b6b); font-size: 12px;">— applied below JD, above tenant baseline</span></div>
			{#each sectors as s}
				<div class="claude-card" style="padding: 14px; margin-bottom: 14px;">
					<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
						<div>
							<strong style="font-weight: 600;">{s.name}</strong> {#if s.email_domain}<span style="font-size: 12px; color: var(--color-muted, #6b6b6b);"> · {s.email_domain}</span>{/if}
							<span style="font-size: 11px; color: var(--color-muted, #6b6b6b);"> · {s.users_count} users</span>
						</div>
						<button class="btn-primary btn-sm" onclick={() => saveSector(s)}>Save</button>
					</div>
					<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px;">
						{#each ['skills','experience','industry','education','certifications','culture'] as dim}
							<div>
								<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
									<span style="font-size: 11px; font-weight: 600; color: var(--color-text, #2a2a2a);">{titleCase(dim)}</span>
									<button onclick={() => toggleForced(s, dim)} title="Force: positions cannot lower"
										class="forced-pill"
										class:active={(s.forced_dims || []).includes(dim)}>
										{(s.forced_dims || []).includes(dim) ? '⊕ Forced' : 'Force?'}
									</button>
								</div>
								<input type="number" min="0" max="100" bind:value={s[`weight_${dim}`]} class="claude-input" style="text-align: center; font-weight: 600;" />
							</div>
						{/each}
					</div>
				</div>
			{/each}
			{#if sectors.length === 0}
				<p style="color: var(--color-muted, #6b6b6b);">Loading sectors…</p>
			{/if}

		{:else if tab === 'policy'}
			<div class="section-title" style="margin-bottom: 12px;">Tenant policy <span style="font-weight: 400; color: var(--color-muted, #6b6b6b); font-size: 12px;">— global floors / caps for all sectors / JDs / positions</span></div>
			<div class="claude-table-wrap">
			<table class="claude-table">
				<thead>
					<tr>
						<th>Key</th>
						<th>Value</th>
						<th>Enforcement</th>
					</tr>
				</thead>
				<tbody>
					{#each policy as p}
						<tr>
							<td style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace;">{p.key}</td>
							<td>
								<input type="number" min="0" max="100" bind:value={p.value} class="claude-input claude-input-sm" style="width: 80px; text-align: center;" />
							</td>
							<td>
								<select class="claude-input claude-input-sm" bind:value={p.enforcement}>
									<option value="clamp">clamp</option>
									<option value="block">block</option>
								</select>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
			</div>
			<div style="margin-top: 14px;">
				<button class="btn-primary" onclick={savePolicy}>Save policy</button>
			</div>

		{:else if tab === 'merges'}
			<div class="filter-row">
				<div style="display: flex; gap: 4px;">
					{#each [
						{ id: 'pending',  label: 'Pending' },
						{ id: 'approved', label: 'Approved' },
						{ id: 'rejected', label: 'Rejected' },
						{ id: 'reverted', label: 'Reverted' },
					] as st}
						<button
							onclick={() => { mergeStatus = st.id; loadMerges(); }}
							class="btn-pill"
							class:btn-pill-active={mergeStatus === st.id}>
							{st.label}
						</button>
					{/each}
				</div>
				<select class="claude-input" bind:value={mergeEntityType} onchange={loadMerges}>
					<option value="">All types</option>
					<option value="candidate">Candidate</option>
					<option value="jd">JD</option>
					<option value="position">Position</option>
				</select>
				<div style="flex: 1;"></div>
				<button class="btn-pill" onclick={loadMerges} disabled={mergesLoading}>↻ Refresh</button>
				<button class="btn-pill" onclick={runSweep} disabled={mergeBulkRunning}>⌕ Run sweep</button>
				{#if mergeStatus === 'pending'}
					<button class="btn-primary" onclick={bulkApproveHighConfidence} disabled={mergeBulkRunning}>▶ Bulk approve ≥95%</button>
				{/if}
			</div>

			<div class="claude-table-wrap">
			<table class="claude-table" style="min-width: 900px;">
				<thead>
					<tr>
						<th>ID</th>
						<th>Type</th>
						<th>Winner</th>
						<th>Loser</th>
						<th>Conf.</th>
						<th>Method</th>
						<th>Status</th>
						<th>Created</th>
						<th style="text-align: right;">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each merges as m}
						<tr style="cursor: pointer;" onclick={() => (openMergeId = m.id)}>
							<td style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace;">#{m.id}</td>
							<td>{titleCase(m.entity_type || '')}</td>
							<td>{summaryLabel(m, 'winner')} <span style="color: var(--color-muted, #6b6b6b);">#{m.winner_id}</span></td>
							<td>{summaryLabel(m, 'loser')} <span style="color: var(--color-muted, #6b6b6b);">#{m.loser_id}</span></td>
							<td style="font-weight: 600; color: {(m.confidence || 0) >= 0.95 ? '#0a7d2c' : (m.confidence || 0) >= 0.8 ? 'var(--color-text, #2a2a2a)' : '#c96342'};">{fmtConfidence(m.confidence)}</td>
							<td style="font-size: 11px;">{m.method || '—'}</td>
							<td><span class="status-pill">{titleCase(m.status || '')}</span></td>
							<td style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;">{fmtDate(m.created_at)}</td>
							<td style="text-align: right;" onclick={(e) => e.stopPropagation()}>
								<button class="btn-primary btn-sm" onclick={() => (openMergeId = m.id)}>Review</button>
							</td>
						</tr>
					{/each}
					{#if merges.length === 0 && !mergesLoading}
						<tr><td colspan="9" style="padding: 24px; text-align: center; color: var(--color-muted, #6b6b6b);">No {mergeStatus} proposals</td></tr>
					{/if}
					{#if mergesLoading}
						<tr><td colspan="9" style="padding: 24px; text-align: center; color: var(--color-muted, #6b6b6b);">Loading…</td></tr>
					{/if}
				</tbody>
			</table>
			</div>
			<div class="meta-line">{mergesTotal} total</div>

		{:else if tab === 'audit'}
			<div class="filter-row">
				<select class="claude-input" bind:value={auditDays} onchange={loadAudit}>
					<option value={1}>24h</option>
					<option value={7}>7d</option>
					<option value={30}>30d</option>
					<option value={365}>1y</option>
				</select>
				<input class="claude-input" bind:value={auditAction} placeholder="Action filter (e.g. user_invite)" oninput={loadAudit} style="flex: 1;" />
			</div>
			<div class="claude-table-wrap">
			<table class="claude-table">
				<thead>
					<tr>
						<th>Time</th>
						<th>User</th>
						<th>Action</th>
						<th>Resource</th>
						<th>IP</th>
						<th style="text-align: right;">GDPR</th>
					</tr>
				</thead>
				<tbody>
					{#each events as e}
						<tr>
							<td style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;">{e.created_at?.replace('T', ' ').slice(0, 19)}</td>
							<td>{e.user_name || `#${e.user_id || '—'}`}</td>
							<td style="font-weight: 600;">{e.action}</td>
							<td>{e.resource_type || ''}{e.resource_id ? `/${e.resource_id}` : ''}</td>
							<td style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;">{e.ip_address || '—'}</td>
							<td style="text-align: right; white-space: nowrap;">
								{#if e.user_id}
									<button class="btn-pill" title="Export user data (GDPR)" onclick={() => gdprExport(e.user_id, e.user_name)}>Export</button>
									<button class="btn-pill" style="color: #a83232; border-color: #f5dada;" title="Delete user data (GDPR)" onclick={() => openGdprDelete(e.user_id, e.user_name)}>Delete</button>
								{:else}
									<span style="color: var(--color-muted, #b8b6ad); font-size: 11px;">—</span>
								{/if}
							</td>
						</tr>
					{/each}
					{#if events.length === 0}
						<tr><td colspan="6" style="padding: 24px; text-align: center; color: var(--color-muted, #6b6b6b);">No events</td></tr>
					{/if}
				</tbody>
			</table>
			</div>

		{:else if tab === 'insights' || tab === 'analytics'}
			{#if insights}
				<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
					{#each Object.entries(insights.totals) as [k, v]}
						<div class="claude-card" style="padding: 14px;">
							<div style="font-size: 11px; color: var(--color-muted, #6b6b6b);">{titleCase(k)}</div>
							<div style="font-size: 28px; font-weight: 600; margin-top: 4px;">{v}</div>
						</div>
					{/each}
				</div>

				<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px;">
					<div class="claude-card" style="padding: 14px;">
						<div class="card-title">Activity (24h)</div>
						<div>Events: <strong style="font-weight: 600;">{insights.activity.audit_24h}</strong></div>
						<div>Login fails (1h): <strong style="font-weight: 600; color: {insights.activity.login_fails_1h > 0 ? '#c96342' : 'inherit'};">{insights.activity.login_fails_1h}</strong></div>
					</div>
					<div class="claude-card" style="padding: 14px;">
						<div class="card-title">AI usage</div>
						<div>7d cost: <strong style="font-weight: 600;">${insights.ai.cost_7d.toFixed(2)}</strong></div>
						<div>Status: <strong style="font-weight: 600;">{insights.ai.available ? 'Active' : 'Disabled'}</strong></div>
						{#each insights.ai.today as m}
							<div style="font-size: 12px; margin-top: 4px;">{m.model}: {m.calls} calls · ${m.cost_usd.toFixed(4)}</div>
						{/each}
					</div>
				</div>

				<div class="claude-card" style="padding: 14px; margin-top: 14px;">
					<div class="card-title">AI insights</div>
					{#if insights.insights.length === 0}
						<div style="color: var(--color-muted, #6b6b6b);">All systems nominal.</div>
					{:else}
						{#each insights.insights as i}
							<div style="padding: 8px 0; border-bottom: 1px solid var(--color-border, #e7e3d8);">
								<span class="level-pill level-{i.level}">{titleCase(i.level)}</span>
								&nbsp; {i.msg}
							</div>
						{/each}
					{/if}
				</div>
			{:else}
				<div style="color: var(--color-muted, #6b6b6b);">Loading…</div>
			{/if}

		{:else if tab === 'competencies'}
			<div class="filter-row">
				<select class="claude-input" bind:value={compFramework}>
					<option value="">All frameworks</option>
					{#each compFrameworks as f}
						<option value={f.id}>{f.name || ''} {f.is_default ? '· Default' : ''} ({f.count ?? 0})</option>
					{/each}
				</select>
				<input class="claude-input" bind:value={compSearch} placeholder="Search…" style="flex: 1; min-width: 200px;" />
				<select class="claude-input" bind:value={compCategory}>
					<option value="">All categories</option>
					{#each compCategories as cat}
						<option value={cat}>{titleCase(cat)}</option>
					{/each}
				</select>
				<button class="btn-primary" onclick={openCompNew}>+ New competency</button>
			</div>

			{#if compLibrary.length === 0}
				<div style="padding: 30px; text-align: center; color: var(--color-muted, #6b6b6b); font-size: 13px;">
					No competencies in library yet. Click "+ New competency" to seed one.
				</div>
			{:else}
				<div class="claude-table-wrap">
				<table class="claude-table">
					<thead>
						<tr>
							<th>Key</th>
							<th>Label</th>
							<th>Category</th>
							<th>Levels</th>
							<th style="text-align: center;">Active</th>
							<th style="text-align: right;">Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredCompLibrary as c}
							<tr>
								<td style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;">{c.key}</td>
								<td style="font-weight: 600;">{c.label}</td>
								<td>
									{#if c.category}
										<span class={categoryClass(c.category)}>{titleCase(c.category)}</span>
									{:else}—{/if}
								</td>
								<td style="font-size: 12px; color: var(--color-muted, #6b6b6b); max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
									{#if c.level_descriptors}
										{@const lvls = typeof c.level_descriptors === 'string' ? (() => { try { return JSON.parse(c.level_descriptors); } catch { return {}; } })() : c.level_descriptors}
										L1–L{Object.keys(lvls || {}).length || 5}: {Object.values(lvls || {}).slice(0, 1)[0] || '—'}
									{:else}—{/if}
								</td>
								<td style="text-align: center;">
									<button class="toggle-switch" class:on={c.active !== false} onclick={() => toggleCompActive(c)} aria-label="Toggle active">
										<span class="toggle-knob"></span>
										<span class="toggle-label">{c.active === false ? 'Off' : 'On'}</span>
									</button>
								</td>
								<td style="text-align: right;">
									<button class="btn-pill" onclick={() => openCompEdit(c)}>Edit</button>
									<button class="btn-pill danger" onclick={() => deleteComp(c)}>Del</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				</div>
			{/if}

		{:else if tab === 'system'}
			{#if sysConfig}
				<div class="section-title" style="margin-bottom: 12px;">Nav features <span style="font-weight: 400; color: var(--color-muted, #6b6b6b); font-size: 12px;">— hide/show top-level tabs</span></div>
				<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin-bottom: 22px;">
					{#each sysConfig.flags.filter(f => f.key.startsWith('feature_')) as f}
						<div class="claude-card" style="padding: 12px; display: flex; align-items: center; justify-content: space-between;">
							<div>
								<div style="font-weight: 600; font-size: 13px;">{titleCase(f.key.replace('feature_',''))}</div>
								<div style="font-size: 11px; color: var(--color-muted, #6b6b6b);">{f.description}</div>
							</div>
							<button class="toggle-switch" class:on={f.value} onclick={() => toggleFlag(f)} aria-label="Toggle">
								<span class="toggle-knob"></span>
								<span class="toggle-label">{f.value ? 'Shown' : 'Hidden'}</span>
							</button>
						</div>
					{/each}
				</div>

				<div class="section-title" style="margin-bottom: 12px;">System flags</div>
				<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">
					{#each sysConfig.flags.filter(f => !f.key.startsWith('feature_')) as f}
						<div class="claude-card" style="padding: 12px; display: flex; align-items: center; justify-content: space-between;">
							<div>
								<div style="font-weight: 600; font-size: 13px;">{f.key}</div>
								<div style="font-size: 11px; color: var(--color-muted, #6b6b6b);">{f.description}</div>
							</div>
							<button class="toggle-switch" class:on={f.value} onclick={() => toggleFlag(f)} aria-label="Toggle">
								<span class="toggle-knob"></span>
								<span class="toggle-label">{f.value ? 'On' : 'Off'}</span>
							</button>
						</div>
					{/each}
				</div>

				<div class="section-title" style="margin: 18px 0 12px;">Secrets</div>
				<div class="claude-card" style="padding: 14px;">
					<div>OPENROUTER_API_KEY: <code style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace;">{sysConfig.secrets.openrouter_masked || '— not set'}</code></div>
					<div>SMTP: <strong style="font-weight: 600;">{sysConfig.secrets.smtp_set ? 'Configured' : 'Not set'}</strong></div>
				</div>

				<div class="section-title" style="margin: 18px 0 12px;">Environment</div>
				<div class="claude-card" style="padding: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;">
					<div>DEV_MODE = {sysConfig.env.dev_mode}</div>
					<div>LOG_FORMAT = {sysConfig.env.log_format}</div>
					<div>WORKERS = {sysConfig.env.workers}</div>
				</div>
			{:else}
				<div style="color: var(--color-muted, #6b6b6b);">Loading…</div>
			{/if}
		{:else if tab === 'branding'}
			<BrandingPanel />
		{:else if tab === 'email-templates'}
			<EmailTemplatesPanel />
		{:else if tab === 'offer-templates'}
			<OfferTemplatesPanel />
		{:else if tab === 'integrations'}
			<IntegrationsPanel />
		{:else if tab === 'workflows'}
			<WorkflowsPanel />
		{:else if tab === 'agents'}
			<AgentsPanel />
		{:else if tab === 'agent-config'}
			<AgentsConfigPanel />
		{:else if tab === 'retention'}
			<RetentionPanel />
		{/if}
	</div>
</div>

{#if openMergeId}
	<MergeModal
		proposalId={openMergeId}
		onClose={() => (openMergeId = null)}
		onResolved={() => { openMergeId = null; loadMerges(); }}
	/>
{/if}

{#if gdprDeleteTarget}
	<div style="position: fixed; inset: 0; background: rgba(42,42,42,0.45); z-index: 9100; display: flex; align-items: center; justify-content: center; padding: 24px;"
		onclick={(e) => { if (e.target === e.currentTarget) closeGdprDelete(); }} role="presentation">
		<div style="background: #ffffff; width: 100%; max-width: 480px; padding: 24px; border-radius: 12px; box-shadow: 0 20px 50px rgba(0,0,0,0.18); font-family: 'Inter', sans-serif;" role="dialog">
			<h3 style="margin: 0 0 8px; font-size: 18px; font-weight: 600; color: #2d2a26; font-family: 'Tiempos Headline', Georgia, serif;">Delete user data (GDPR)</h3>
			<p style="font-size: 13.5px; color: #6b6b66; line-height: 1.5; margin: 0 0 18px;">
				This will permanently erase data for <strong style="color: #2d2a26;">{gdprDeleteTarget.label || `user #${gdprDeleteTarget.id}`}</strong>. This action cannot be undone.
			</p>
			<div style="display: flex; gap: 8px; justify-content: flex-end;">
				<button class="btn-ghost" onclick={closeGdprDelete}>Cancel</button>
				<button class="btn-primary" style="background: #a83232; border-color: #a83232;" onclick={confirmGdprDelete}>Delete data</button>
			</div>
		</div>
	</div>
{/if}

{#if compEditing}
	<div style="position: fixed; inset: 0; background: rgba(42,42,42,0.45); z-index: 9000; display: flex; align-items: center; justify-content: center; padding: 24px;"
		onclick={(e) => { if (e.target === e.currentTarget) closeCompModal(); }} role="presentation">
		<div class="claude-card" style="background: var(--color-surface, #ffffff); width: 100%; max-width: 720px; max-height: 86vh; display: flex; flex-direction: column; padding: 0; border-radius: 12px; box-shadow: 0 20px 50px rgba(0,0,0,0.18);" role="dialog">
			<div style="display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--color-border, #e7e3d8);">
				<span style="font-weight: 600; font-size: 14px;">{compEditing === 'new' ? 'New competency' : `Edit — ${compEditing.key}`}</span>
				<button onclick={closeCompModal} aria-label="Close" style="background: none; border: none; color: var(--color-muted, #6b6b6b); font-size: 18px; cursor: pointer;">✕</button>
			</div>
			<div style="padding: 18px; flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px;">
				<label style="display: block;">
					<span style="font-size: 11px; font-weight: 600; color: var(--color-muted, #6b6b6b);">Key</span>
					<input class="claude-input" bind:value={compForm.key} placeholder="e.g. strategic-thinking" style="margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;" />
				</label>
				<label style="display: block;">
					<span style="font-size: 11px; font-weight: 600; color: var(--color-muted, #6b6b6b);">Label</span>
					<input class="claude-input" bind:value={compForm.label} placeholder="Strategic thinking" style="margin-top: 4px;" />
				</label>
				<label style="display: block;">
					<span style="font-size: 11px; font-weight: 600; color: var(--color-muted, #6b6b6b);">Category</span>
					<input class="claude-input" bind:value={compForm.category} placeholder="leadership / technical / interpersonal" style="margin-top: 4px;" />
				</label>
				<label style="display: block;">
					<span style="font-size: 11px; font-weight: 600; color: var(--color-muted, #6b6b6b);">Description</span>
					<textarea class="claude-input" bind:value={compForm.description} rows="2" style="margin-top: 4px; resize: vertical;"></textarea>
				</label>
				<label style="display: block;">
					<span style="font-size: 11px; font-weight: 600; color: var(--color-muted, #6b6b6b);">Level descriptors (JSON object: {`{"1": "...", "2": "..."}`})</span>
					<textarea class="claude-input" bind:value={compForm.level_descriptors} rows="6" placeholder={'{"1":"basic","2":"developing","3":"competent","4":"strong","5":"expert"}'} style="margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; resize: vertical;"></textarea>
				</label>
				<label style="display: block;">
					<span style="font-size: 11px; font-weight: 600; color: var(--color-muted, #6b6b6b);">STAR questions (JSON array)</span>
					<textarea class="claude-input" bind:value={compForm.star_questions} rows="4" placeholder='["Tell me about a time…", "Describe a situation…"]' style="margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; resize: vertical;"></textarea>
				</label>
			</div>
			<div style="padding: 12px 18px; border-top: 1px solid var(--color-border, #e7e3d8); display: flex; gap: 8px; justify-content: flex-end; background: var(--color-bg-cream, #faf8f3); border-radius: 0 0 12px 12px;">
				<button class="btn-ghost" onclick={closeCompModal} disabled={compSaving}>Cancel</button>
				<button class="btn-primary" onclick={saveComp} disabled={compSaving || !compForm.key || !compForm.label}>
					{compSaving ? 'Saving…' : 'Save'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.admin-shell {
		height: 100%;
		display: flex;
		flex-direction: column;
		padding: 24px 32px;
		max-width: 1800px;
		margin: 0 auto;
		width: 100%;
		box-sizing: border-box;
		overflow: hidden;
		background: var(--color-bg, #faf8f3);
		font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
		color: var(--color-text, #2a2a2a);
	}
	.admin-fixed { flex-shrink: 0; }
	.admin-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		min-height: 0;
		padding-top: 18px;
	}

	/* Header */
	.admin-page-header { margin-bottom: 18px; }
	.page-title {
		font-family: 'Tiempos Text', 'Tiempos', Georgia, 'Times New Roman', serif;
		font-size: 30px;
		font-weight: 500;
		letter-spacing: -0.01em;
		margin: 0;
		color: var(--color-text, #2a2a2a);
	}
	.page-sub {
		font-size: 13px;
		color: var(--color-muted, #6b6b6b);
		margin: 4px 0 0;
	}

	/* Tabs */
	.tab-row {
		display: flex;
		gap: 0;
		border-bottom: 1px solid var(--color-border, #e7e3d8);
		overflow-x: auto;
		margin-bottom: 4px;
	}
	.tab-btn {
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--color-muted, #6b6b6b);
		padding: 10px 16px;
		font-size: 13px;
		font-weight: 500;
		font-family: inherit;
		cursor: pointer;
		flex-shrink: 0;
		margin-bottom: -1px;
		transition: color 0.15s, border-color 0.15s;
	}
	.tab-btn:hover { color: var(--color-text, #2a2a2a); }
	.tab-btn.tab-active {
		color: var(--color-accent, #c96342);
		border-bottom-color: var(--color-accent, #c96342);
	}

	/* Inputs */
	:global(.claude-input) {
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border-strong, #d6d1c4);
		border-radius: 8px;
		padding: 7px 11px;
		font-size: 13px;
		font-family: inherit;
		color: var(--color-text, #2a2a2a);
		outline: none;
		transition: border-color 0.15s, box-shadow 0.15s;
		width: auto;
		box-sizing: border-box;
	}
	:global(.claude-input:focus) {
		border-color: var(--color-accent, #c96342);
		box-shadow: 0 0 0 3px rgba(201, 99, 66, 0.12);
	}
	:global(.claude-input-sm) { padding: 4px 8px; font-size: 12px; }
	textarea.claude-input { width: 100%; }

	.filter-row {
		display: flex;
		gap: 10px;
		align-items: center;
		margin-bottom: 14px;
		flex-wrap: wrap;
	}

	/* Buttons */
	.btn-primary {
		background: var(--color-accent, #c96342);
		color: #fff;
		border: 1px solid var(--color-accent, #c96342);
		border-radius: 999px;
		padding: 7px 16px;
		font-size: 13px;
		font-weight: 500;
		font-family: inherit;
		cursor: pointer;
		transition: background 0.15s, transform 0.05s;
	}
	.btn-primary:hover { background: #b35538; }
	.btn-primary:active { transform: translateY(1px); }
	.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
	.btn-primary.btn-sm { padding: 4px 12px; font-size: 12px; }

	.btn-ghost {
		background: var(--color-surface, #ffffff);
		color: var(--color-text, #2a2a2a);
		border: 1px solid var(--color-border-strong, #d6d1c4);
		border-radius: 999px;
		padding: 7px 16px;
		font-size: 13px;
		font-weight: 500;
		font-family: inherit;
		cursor: pointer;
		transition: background 0.15s;
	}
	.btn-ghost:hover { background: var(--color-bg-cream, #f4f3ee); }

	.btn-pill {
		background: var(--color-surface, #ffffff);
		color: var(--color-text, #2a2a2a);
		border: 1px solid var(--color-border-strong, #d6d1c4);
		border-radius: 999px;
		padding: 4px 12px;
		font-size: 12px;
		font-weight: 500;
		font-family: inherit;
		cursor: pointer;
		margin-left: 4px;
		transition: background 0.15s, border-color 0.15s;
	}
	.btn-pill:first-child { margin-left: 0; }
	.btn-pill:hover { background: var(--color-bg-cream, #f4f3ee); }
	.btn-pill.btn-pill-active {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.btn-pill.danger { color: #b03020; border-color: rgba(176, 48, 32, 0.4); }
	.btn-pill.danger:hover { background: rgba(176, 48, 32, 0.06); }

	/* Cards */
	.claude-card {
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e7e3d8);
		border-radius: 10px;
	}
	.card-title {
		font-weight: 600;
		font-size: 13px;
		margin-bottom: 10px;
		color: var(--color-text, #2a2a2a);
	}
	.section-title {
		font-weight: 600;
		font-size: 14px;
		color: var(--color-text, #2a2a2a);
	}

	/* Tables */
	.claude-table-wrap {
		overflow-x: auto;
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e7e3d8);
		border-radius: 10px;
	}
	.claude-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	.claude-table thead tr {
		background: var(--color-bg-cream, #f4f3ee);
	}
	.claude-table th {
		text-align: left;
		padding: 10px 14px;
		font-weight: 600;
		font-size: 12px;
		color: var(--color-text, #2a2a2a);
		border-bottom: 1px solid var(--color-border, #e7e3d8);
	}
	.claude-table td {
		padding: 10px 14px;
		border-bottom: 1px solid var(--color-border, #e7e3d8);
		vertical-align: middle;
	}
	.claude-table tbody tr:last-child td { border-bottom: none; }
	.claude-table tbody tr:hover { background: var(--color-bg-cream, #faf8f3); }

	.meta-line {
		margin-top: 10px;
		font-size: 11px;
		color: var(--color-muted, #6b6b6b);
	}

	/* Status dot */
	.status-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-right: 6px;
		vertical-align: middle;
	}
	.status-dot.on { background: #2da06b; }
	.status-dot.off { background: #b8b3a3; }

	/* Status pill */
	.status-pill {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 999px;
		background: var(--color-bg-cream, #f4f3ee);
		border: 1px solid var(--color-border, #e7e3d8);
		font-size: 11px;
		font-weight: 500;
	}

	/* Category pills */
	.pill-cat {
		display: inline-block;
		padding: 3px 10px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 500;
	}
	.pill-cat-delivery { background: #e8f0fa; color: #2c5687; }
	.pill-cat-leadership { background: #f7e3dc; color: #a64a2c; }
	.pill-cat-people { background: #e3efe3; color: #2f6b3a; }
	.pill-cat-default { background: var(--color-bg-cream, #f4f3ee); color: var(--color-text, #2a2a2a); }

	/* Modern toggle switch */
	.toggle-switch {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		background: transparent;
		border: none;
		cursor: pointer;
		padding: 0;
		font-family: inherit;
	}
	.toggle-switch::before {
		content: '';
		display: inline-block;
		width: 32px;
		height: 18px;
		background: #d6d1c4;
		border-radius: 999px;
		position: relative;
		transition: background 0.2s;
	}
	.toggle-knob {
		position: absolute;
		width: 14px;
		height: 14px;
		background: #fff;
		border-radius: 50%;
		left: 2px;
		top: 2px;
		transition: transform 0.2s;
		box-shadow: 0 1px 2px rgba(0,0,0,0.15);
	}
	.toggle-switch {
		position: relative;
	}
	.toggle-switch.on::before { background: var(--color-accent, #c96342); }
	.toggle-switch.on .toggle-knob { transform: translateX(14px); }
	.toggle-label {
		font-size: 12px;
		color: var(--color-text, #2a2a2a);
		font-weight: 500;
	}

	/* Permission grid toggle */
	.perm-toggle {
		width: 28px;
		height: 22px;
		border: 1px solid var(--color-border-strong, #d6d1c4);
		background: var(--color-surface, #ffffff);
		border-radius: 6px;
		font-size: 12px;
		color: var(--color-muted, #6b6b6b);
		cursor: pointer;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}
	.perm-toggle.on {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}

	/* Forced pill in sectors */
	.forced-pill {
		border: 1px solid var(--color-border-strong, #d6d1c4);
		background: var(--color-surface, #ffffff);
		color: var(--color-muted, #6b6b6b);
		padding: 2px 8px;
		font-size: 10px;
		border-radius: 999px;
		cursor: pointer;
		font-family: inherit;
	}
	.forced-pill.active {
		background: #fff3d6;
		border-color: #e0b656;
		color: #7a5a18;
	}

	/* Level pill */
	.level-pill {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 500;
	}
	.level-pill.level-error { background: #f7dcdc; color: #8a2828; }
	.level-pill.level-warn { background: #fbeccd; color: #7a5a18; }
	.level-pill.level-info { background: #e7e3d8; color: #2a2a2a; }

	:global(.claude-table th), :global(.claude-table td) {
		border-right: none;
	}
</style>
