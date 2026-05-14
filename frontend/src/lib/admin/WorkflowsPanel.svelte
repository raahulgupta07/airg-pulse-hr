<script>
	/** Automation rules — visual workflow builder
	 * Backend: GET/POST /api/automations (graceful fallback to localStorage)
	 */
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api';
	import { addToast } from '$lib/Toast.svelte';
	import Zap from '@lucide/svelte/icons/zap';

	const LS_KEY = 'pulse_workflow_rules';
	let rules = $state([]);
	let loading = $state(true);
	let backendAvailable = $state(true);

	// Builder modal
	let showBuilder = $state(false);
	let stage = $state(1); // 1 trigger, 2 condition, 3 action
	let saving = $state(false);

	// Builder fields
	let ruleName = $state('');
	let triggerType = $state('cv_uploaded');
	let conditionField = $state(''); // empty = no condition
	let conditionOp = $state('gt');
	let conditionValue = $state('');
	let actionType = $state('move_stage');
	let actionPayload = $state(''); // free-form value (stage name, template id, tag, user, pool name)

	const TRIGGERS = [
		{ id: 'cv_uploaded',      label: 'CV uploaded' },
		{ id: 'stage_changed',    label: 'Stage changed' },
		{ id: 'sla_breach',       label: 'SLA breach' },
		{ id: 'match_threshold',  label: 'Match score threshold' },
		{ id: 'daily_digest',     label: 'Daily digest time' },
	];

	const CONDITION_FIELDS = [
		{ id: '',             label: 'No condition' },
		{ id: 'match_score',  label: 'Match score' },
		{ id: 'position',     label: 'Position' },
		{ id: 'source',       label: 'Source' },
	];

	const CONDITION_OPS = [
		{ id: 'gt',  label: '>' },
		{ id: 'lt',  label: '<' },
		{ id: 'eq',  label: '=' },
		{ id: 'neq', label: '≠' },
	];

	const ACTIONS = [
		{ id: 'move_stage',     label: 'Move to stage',     placeholder: 'e.g. screened' },
		{ id: 'send_email',     label: 'Send email template', placeholder: 'e.g. welcome_v2' },
		{ id: 'add_tag',        label: 'Add tag',            placeholder: 'e.g. high-priority' },
		{ id: 'notify_user',    label: 'Notify user',        placeholder: 'e.g. recruiter@org.com' },
		{ id: 'add_to_pool',    label: 'Add to pool',        placeholder: 'e.g. senior-eng-pool' },
	];

	function triggerLabel(id) { return (TRIGGERS.find(t => t.id === id) || {}).label || id; }
	function actionLabel(id)  { return (ACTIONS.find(a => a.id === id) || {}).label || id; }
	function actionPlaceholder() { return (ACTIONS.find(a => a.id === actionType) || {}).placeholder || ''; }

	onMount(() => { loadRules(); });

	function _readLocal() {
		if (typeof localStorage === 'undefined') return [];
		try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch { return []; }
	}
	function _writeLocal(arr) {
		if (typeof localStorage === 'undefined') return;
		try { localStorage.setItem(LS_KEY, JSON.stringify(arr)); } catch {}
	}

	async function loadRules() {
		loading = true;
		try {
			const data = await apiJson('/automations');
			rules = data.rules || data.items || data || [];
			backendAvailable = true;
		} catch (e) {
			// Backend not available — fall back to localStorage
			backendAvailable = false;
			rules = _readLocal();
		}
		loading = false;
	}

	function openBuilder() {
		ruleName = '';
		triggerType = 'cv_uploaded';
		conditionField = '';
		conditionOp = 'gt';
		conditionValue = '';
		actionType = 'move_stage';
		actionPayload = '';
		stage = 1;
		showBuilder = true;
	}

	function closeBuilder() { showBuilder = false; }

	function nextStage() {
		if (stage === 1 && !triggerType) { addToast('error', 'Pick a trigger'); return; }
		if (stage === 3) return;
		stage = stage + 1;
	}
	function prevStage() {
		if (stage > 1) stage = stage - 1;
	}

	async function saveRule() {
		if (!actionType) { addToast('error', 'Pick an action'); return; }
		const rule = {
			id: Date.now(),
			name: ruleName.trim() || `${triggerLabel(triggerType)} → ${actionLabel(actionType)}`,
			trigger: triggerType,
			condition: conditionField ? { field: conditionField, op: conditionOp, value: conditionValue } : null,
			action: { type: actionType, payload: actionPayload },
			enabled: true,
			created_at: new Date().toISOString(),
		};
		saving = true;
		try {
			if (backendAvailable) {
				await apiJson('/automations', { method: 'POST', body: JSON.stringify(rule) });
				addToast('success', 'Rule saved');
			} else {
				const next = [..._readLocal(), rule];
				_writeLocal(next);
				addToast('success', 'Rule saved (local)');
			}
			showBuilder = false;
			await loadRules();
		} catch (e) {
			// Endpoint missing — fall back to localStorage so user doesn't lose work
			alert(`Backend save failed (${e.message}). Saving locally.`);
			const next = [..._readLocal(), rule];
			_writeLocal(next);
			backendAvailable = false;
			rules = next;
			showBuilder = false;
		}
		saving = false;
	}

	async function deleteRule(rule) {
		if (!confirm(`Delete rule "${rule.name}"?`)) return;
		try {
			if (backendAvailable && rule.id) {
				await apiJson(`/automations/${rule.id}`, { method: 'DELETE' });
			}
		} catch { /* ignore */ }
		const next = _readLocal().filter(r => r.id !== rule.id);
		_writeLocal(next);
		await loadRules();
	}

	function conditionPillText(rule) {
		if (!rule.condition) return 'Always';
		const c = rule.condition;
		const op = (CONDITION_OPS.find(o => o.id === c.op) || {}).label || c.op;
		const field = (CONDITION_FIELDS.find(f => f.id === c.field) || {}).label || c.field;
		return `${field} ${op} ${c.value}`;
	}
	function actionPillText(rule) {
		const a = rule.action || {};
		const lbl = actionLabel(a.type);
		return a.payload ? `${lbl}: ${a.payload}` : lbl;
	}
</script>

<div class="wf-page">
	<header class="wf-head">
		<div>
			<h1 class="wf-title">Automation rules</h1>
			<p class="wf-sub">
				When trigger fires and condition matches, run action.
				{#if !backendAvailable}<span class="wf-local-badge">Local only — backend not connected</span>{/if}
			</p>
		</div>
		<button class="wf-primary" onclick={openBuilder}>+ New rule</button>
	</header>

	{#if loading}
		<div class="wf-skeleton"></div>
		<div class="wf-skeleton"></div>
	{:else if rules.length === 0}
		<div class="wf-empty">
			<span style="display: flex; justify-content: center; opacity: 0.4;"><Zap size={44} strokeWidth={1.25} /></span>
			<p class="wf-empty-title">No rules yet</p>
			<p class="wf-empty-sub">Create a rule to automate stage changes, emails, tags and more.</p>
			<button class="wf-primary" style="margin-top: 14px;" onclick={openBuilder}>+ New rule</button>
		</div>
	{:else}
		<div class="wf-list">
			{#each rules as rule (rule.id)}
				<div class="wf-card">
					<div class="wf-card-head">
						<span class="wf-card-name">{rule.name}</span>
						<button class="wf-card-del" onclick={() => deleteRule(rule)} title="Delete rule">×</button>
					</div>
					<div class="wf-flow">
						<span class="wf-pill wf-pill-when">
							<span class="wf-pill-label">When</span>
							{triggerLabel(rule.trigger)}
						</span>
						<span class="wf-arrow">→</span>
						<span class="wf-pill wf-pill-if">
							<span class="wf-pill-label">If</span>
							{conditionPillText(rule)}
						</span>
						<span class="wf-arrow">→</span>
						<span class="wf-pill wf-pill-then">
							<span class="wf-pill-label">Then</span>
							{actionPillText(rule)}
						</span>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

{#if showBuilder}
	<div class="wf-modal-backdrop" onclick={(e) => { if (e.target === e.currentTarget && !saving) closeBuilder(); }}>
		<div class="wf-modal">
			<div class="wf-modal-head">
				<span class="wf-modal-title">New automation rule</span>
				<button class="wf-modal-close" onclick={closeBuilder} disabled={saving}>×</button>
			</div>

			<!-- Stage indicator -->
			<div class="wf-stages">
				<div class="wf-stage" class:wf-stage-active={stage >= 1}><span>1</span> Trigger</div>
				<div class="wf-stage-line"></div>
				<div class="wf-stage" class:wf-stage-active={stage >= 2}><span>2</span> Condition</div>
				<div class="wf-stage-line"></div>
				<div class="wf-stage" class:wf-stage-active={stage >= 3}><span>3</span> Action</div>
			</div>

			<div class="wf-modal-body">
				<label class="wf-label">Rule name (optional)</label>
				<input class="wf-input" bind:value={ruleName} placeholder="Auto-screen high-match seniors" />

				{#if stage === 1}
					<div class="wf-section-title">When this happens</div>
					<select class="wf-input" bind:value={triggerType}>
						{#each TRIGGERS as t}
							<option value={t.id}>{t.label}</option>
						{/each}
					</select>
					<p class="wf-help">Pick the event that starts this rule.</p>
				{:else if stage === 2}
					<div class="wf-section-title">If this is true (optional)</div>
					<div class="wf-row">
						<select class="wf-input" bind:value={conditionField}>
							{#each CONDITION_FIELDS as f}
								<option value={f.id}>{f.label}</option>
							{/each}
						</select>
						{#if conditionField}
							<select class="wf-input" bind:value={conditionOp} style="max-width: 90px;">
								{#each CONDITION_OPS as op}
									<option value={op.id}>{op.label}</option>
								{/each}
							</select>
							<input class="wf-input" bind:value={conditionValue} placeholder="Value" />
						{/if}
					</div>
					<p class="wf-help">Leave as no condition to always run when the trigger fires.</p>
				{:else if stage === 3}
					<div class="wf-section-title">Then do this</div>
					<select class="wf-input" bind:value={actionType}>
						{#each ACTIONS as a}
							<option value={a.id}>{a.label}</option>
						{/each}
					</select>
					<input class="wf-input" bind:value={actionPayload} placeholder={actionPlaceholder()} style="margin-top: 10px;" />
					<p class="wf-help">{actionPlaceholder()}</p>
				{/if}
			</div>

			<div class="wf-modal-foot">
				{#if stage > 1}
					<button class="wf-btn" onclick={prevStage} disabled={saving}>Back</button>
				{:else}
					<span style="flex: 1;"></span>
				{/if}
				<span style="flex: 1;"></span>
				{#if stage < 3}
					<button class="wf-btn" onclick={closeBuilder} disabled={saving}>Cancel</button>
					<button class="wf-primary" onclick={nextStage} disabled={saving}>Next</button>
				{:else}
					<button class="wf-btn" onclick={closeBuilder} disabled={saving}>Cancel</button>
					<button class="wf-primary" onclick={saveRule} disabled={saving}>{saving ? 'Saving…' : 'Save rule'}</button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.wf-page {
		max-width: 1100px; margin: 0 auto; padding: 32px 28px 80px;
		font-family: 'Inter', system-ui, sans-serif;
		color: var(--color-on-surface, #2c2c2c);
	}
	.wf-head {
		display: flex; justify-content: space-between; align-items: flex-end;
		margin-bottom: 28px; gap: 16px; flex-wrap: wrap;
	}
	.wf-title {
		font-family: 'Tiempos Headline', 'Charter', 'Source Serif Pro', Georgia, serif;
		font-size: 28px; font-weight: 500;
		letter-spacing: -0.025em; line-height: 1.15;
		margin: 0; color: var(--color-on-surface, #2c2c2c);
	}
	.wf-sub {
		font-size: 13.5px; color: var(--color-on-surface-dim, #6f6e69);
		margin: 6px 0 0;
	}
	.wf-local-badge {
		display: inline-block; margin-left: 8px;
		padding: 2px 8px; border-radius: 999px;
		font-size: 11px; font-weight: 600;
		background: #fff3e6; color: #a06000;
		border: 1px solid #ffd9a8;
	}

	.wf-primary {
		padding: 9px 18px; border-radius: 8px;
		font-size: 13.5px; font-weight: 500;
		font-family: inherit; cursor: pointer;
		background: var(--color-primary, #c96342); color: #fff;
		border: 1px solid var(--color-primary, #c96342);
		transition: background .15s;
	}
	.wf-primary:hover { background: #b04f30; }
	.wf-primary:disabled { opacity: 0.6; cursor: not-allowed; }

	.wf-btn {
		padding: 9px 18px; border-radius: 8px;
		font-size: 13.5px; font-weight: 500;
		font-family: inherit; cursor: pointer;
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd);
	}
	.wf-btn:hover { background: #fff; }
	.wf-btn:disabled { opacity: 0.6; cursor: not-allowed; }

	.wf-skeleton {
		height: 90px; margin-bottom: 12px;
		border-radius: 12px;
		background: linear-gradient(90deg, #f4f3ee, #faf8f3, #f4f3ee);
		background-size: 200% 100%;
		animation: wf-skel 1.4s ease-in-out infinite;
	}
	@keyframes wf-skel { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

	.wf-empty {
		text-align: center; padding: 72px 24px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px dashed var(--color-border, #e8e6dd);
		border-radius: 12px;
	}
	.wf-empty-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 20px; font-weight: 500;
		margin: 8px 0 4px; color: var(--color-on-surface, #2c2c2c);
	}
	.wf-empty-sub { font-size: 13px; color: var(--color-on-surface-dim, #6f6e69); margin: 0; }

	.wf-list { display: flex; flex-direction: column; gap: 12px; }
	.wf-card {
		background: #fff;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		padding: 16px 18px;
		transition: box-shadow .15s;
	}
	.wf-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.05); }

	.wf-card-head {
		display: flex; justify-content: space-between; align-items: center;
		margin-bottom: 12px;
	}
	.wf-card-name {
		font-size: 14.5px; font-weight: 600;
		color: var(--color-on-surface, #2c2c2c);
	}
	.wf-card-del {
		width: 26px; height: 26px;
		display: inline-flex; align-items: center; justify-content: center;
		border: none; background: transparent;
		font-size: 18px; line-height: 1; cursor: pointer;
		color: var(--color-on-surface-dim, #6f6e69);
		border-radius: 50%;
	}
	.wf-card-del:hover {
		background: var(--color-error-container, #f5dada);
		color: var(--color-error, #a83232);
	}

	.wf-flow { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
	.wf-pill {
		display: inline-flex; align-items: center; gap: 6px;
		padding: 6px 12px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 999px;
		font-size: 12.5px; color: var(--color-on-surface, #2c2c2c);
	}
	.wf-pill-label {
		font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
		font-weight: 600; color: var(--color-on-surface-dim, #6f6e69);
	}
	.wf-pill-when { background: #f0f6ff; border-color: #d4e2f5; }
	.wf-pill-if   { background: #fff8e6; border-color: #ffe6b3; }
	.wf-pill-then { background: #f0fdf4; border-color: #bbe5c8; }
	.wf-arrow { color: var(--color-on-surface-dim, #6f6e69); font-size: 16px; }

	/* Modal */
	.wf-modal-backdrop {
		position: fixed; inset: 0; z-index: 200;
		background: rgba(0,0,0,0.4);
		display: flex; align-items: center; justify-content: center;
		padding: 20px;
	}
	.wf-modal {
		background: #fff; border-radius: 14px;
		width: 560px; max-width: 100%; max-height: 92vh;
		overflow-y: auto;
		box-shadow: 0 24px 48px rgba(0,0,0,0.2);
	}
	.wf-modal-head {
		display: flex; justify-content: space-between; align-items: center;
		padding: 18px 22px 6px;
	}
	.wf-modal-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 20px; font-weight: 500;
		color: var(--color-on-surface, #2c2c2c);
	}
	.wf-modal-close {
		width: 32px; height: 32px;
		display: inline-flex; align-items: center; justify-content: center;
		border: none; background: transparent;
		font-size: 22px; cursor: pointer;
		color: var(--color-on-surface-dim, #6f6e69);
		border-radius: 50%;
	}
	.wf-modal-close:hover { background: var(--color-surface-warm, #f4f3ee); }

	.wf-stages {
		display: flex; align-items: center; gap: 8px;
		padding: 10px 22px 6px;
		font-size: 12px;
	}
	.wf-stage {
		display: inline-flex; align-items: center; gap: 6px;
		color: var(--color-on-surface-dim, #6f6e69);
	}
	.wf-stage span {
		display: inline-flex; align-items: center; justify-content: center;
		width: 22px; height: 22px; border-radius: 50%;
		background: var(--color-surface-warm, #f4f3ee);
		font-size: 11px; font-weight: 600;
	}
	.wf-stage-active { color: var(--color-on-surface, #2c2c2c); }
	.wf-stage-active span { background: var(--color-primary, #c96342); color: #fff; }
	.wf-stage-line { flex: 1; height: 1px; background: var(--color-border, #e8e6dd); }

	.wf-modal-body { padding: 14px 22px 18px; }
	.wf-label {
		display: block;
		font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
		font-weight: 600; color: var(--color-on-surface-dim, #6f6e69);
		margin-bottom: 6px;
	}
	.wf-input {
		width: 100%; padding: 9px 12px;
		border-radius: 8px;
		border: 1px solid var(--color-border, #e8e6dd);
		font-size: 13.5px; font-family: inherit;
		color: var(--color-on-surface, #2c2c2c);
		background: #fff;
		margin-bottom: 14px;
	}
	.wf-input:focus { outline: 2px solid var(--color-primary, #c96342); outline-offset: -2px; }
	.wf-section-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 16px; font-weight: 500;
		margin: 6px 0 10px;
		color: var(--color-on-surface, #2c2c2c);
	}
	.wf-row { display: flex; gap: 8px; align-items: stretch; }
	.wf-row .wf-input { flex: 1; }
	.wf-help {
		font-size: 12px; color: var(--color-on-surface-dim, #6f6e69);
		margin: 4px 0 0;
	}

	.wf-modal-foot {
		display: flex; gap: 8px; align-items: center;
		padding: 12px 22px 18px;
		border-top: 1px solid var(--color-border, #e8e6dd);
	}
</style>
