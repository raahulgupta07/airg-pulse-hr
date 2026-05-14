<script>
	import { untrack } from 'svelte';
	import { apiJson } from '$lib/api';

	let {
		show = false,
		candidateId = '',
		candidateName = '',
		candidateEmail = '',
		positionSlug = '',
		onClose = () => {},
	} = $props();

	// --- State ---
	let subject = $state('');
	let body = $state('');
	let selectedTemplate = $state('');
	let sending = $state(false);
	let sendResult = $state(null);
	let showPreview = $state(false);
	let bodyEl = $state(null);

	const templates = [
		{ id: 'screening', label: 'Screening Invitation', subject: 'Invitation: Initial Screening Call', body: 'Dear {candidate_name},\n\nThank you for your interest in the {role} position at {company}. We were impressed by your profile and would like to invite you for an initial screening call.\n\nPlease let us know your availability for the coming week.\n\nBest regards,\n{sender_name}' },
		{ id: 'interview', label: 'Interview Invitation', subject: 'Interview Invitation: {role}', body: 'Dear {candidate_name},\n\nWe are pleased to invite you for an interview for the {role} position at {company}.\n\nPlease find the details below and confirm your availability:\n\n- Date: [DATE]\n- Time: [TIME]\n- Location: [LOCATION/LINK]\n\nLooking forward to meeting you.\n\nBest regards,\n{sender_name}' },
		{ id: 'rejection', label: 'Rejection Notice', subject: 'Update on Your Application - {role}', body: 'Dear {candidate_name},\n\nThank you for taking the time to apply for the {role} position at {company} and for your interest in joining our team.\n\nAfter careful consideration, we have decided to move forward with other candidates whose qualifications more closely align with our current needs.\n\nWe encourage you to apply for future openings that match your skills and experience.\n\nWe wish you the best in your career.\n\nBest regards,\n{sender_name}' },
		{ id: 'offer', label: 'Offer Letter', subject: 'Offer of Employment: {role} at {company}', body: 'Dear {candidate_name},\n\nWe are thrilled to extend an offer for the {role} position at {company}!\n\nPlease find the offer details attached. We would appreciate your response by [DEADLINE].\n\nIf you have any questions, please do not hesitate to reach out.\n\nWelcome aboard!\n\nBest regards,\n{sender_name}' },
		{ id: 'followup', label: 'Follow-up', subject: 'Following Up - {role} at {company}', body: 'Dear {candidate_name},\n\nI wanted to follow up regarding the {role} position at {company}.\n\nPlease let us know if you have any questions or need additional information.\n\nBest regards,\n{sender_name}' },
	];

	const variables = [
		{ key: '{candidate_name}', label: 'Candidate Name' },
		{ key: '{role}', label: 'Role' },
		{ key: '{company}', label: 'Company' },
		{ key: '{sender_name}', label: 'Sender Name' },
	];

	function applyTemplate() {
		const tpl = templates.find(t => t.id === selectedTemplate);
		if (tpl) {
			subject = tpl.subject;
			body = tpl.body;
		}
	}

	function insertVariable(varKey) {
		if (bodyEl) {
			const start = bodyEl.selectionStart;
			const end = bodyEl.selectionEnd;
			body = body.substring(0, start) + varKey + body.substring(end);
			// Restore cursor after the inserted variable
			setTimeout(() => {
				bodyEl.focus();
				bodyEl.selectionStart = bodyEl.selectionEnd = start + varKey.length;
			}, 0);
		} else {
			body += varKey;
		}
	}

	function renderPreview(text) {
		return text
			.replace(/\{candidate_name\}/g, candidateName || 'Candidate')
			.replace(/\{role\}/g, positionSlug ? positionSlug.replace(/-/g, ' ') : 'Position')
			.replace(/\{company\}/g, 'Our Company')
			.replace(/\{sender_name\}/g, 'HR Team');
	}

	async function sendEmail() {
		if (!subject.trim() || !body.trim()) return;
		sending = true;
		sendResult = null;
		try {
			await apiJson('/emails/send', {
				method: 'POST',
				body: JSON.stringify({
					candidate_id: candidateId,
					subject: renderPreview(subject),
					body: renderPreview(body),
					recipient_email: candidateEmail,
				}),
			});
			sendResult = { type: 'success', text: 'Email sent successfully' };
			setTimeout(() => {
				resetAndClose();
			}, 1500);
		} catch (e) {
			sendResult = { type: 'error', text: `Failed to send: ${e.message}` };
		}
		sending = false;
	}

	function resetAndClose() {
		subject = '';
		body = '';
		selectedTemplate = '';
		sendResult = null;
		showPreview = false;
		onClose();
	}

	$effect(() => {
		const t = selectedTemplate;
		if (t) untrack(() => applyTemplate());
	});
</script>

{#if show}
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="modal-overlay"
	onclick={(e) => { if (e.target === e.currentTarget) resetAndClose(); }}
>
	<div class="modal-container ink-border stamp-shadow animate-fade-up">
		<!-- Header -->
		<div class="dark-title-bar flex items-center justify-between" style="font-size: 11px;">
			<span class="flex items-center gap-2">
				<span class="material-symbols-outlined" style="font-size: 16px;">mail</span>
				Compose Email to {candidateName || 'Candidate'}
			</span>
			<button onclick={resetAndClose} style="background: none; border: none; color: var(--color-surface); cursor: pointer; padding: 2px;">
				<span class="material-symbols-outlined" style="font-size: 18px;">close</span>
			</button>
		</div>

		<div style="padding: 20px; max-height: 70vh; overflow-y: auto;">
			<!-- Recipient -->
			<div class="mb-4">
				<label style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">To</label>
				<div style="padding: 8px 12px; background: var(--color-surface-highest); border: 2px solid var(--color-on-surface); font-size: 13px; font-weight: 700;">
					{candidateEmail || 'No email on file'}
				</div>
			</div>

			<!-- Template Selector -->
			<div class="mb-4">
				<label style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Template</label>
				<select
					bind:value={selectedTemplate}
					style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);"
				>
					<option value="">-- Select Template --</option>
					{#each templates as tpl}
						<option value={tpl.id}>{tpl.label}</option>
					{/each}
				</select>
			</div>

			<!-- Subject -->
			<div class="mb-4">
				<label style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Subject</label>
				<input
					type="text"
					bind:value={subject}
					placeholder="EMAIL SUBJECT..."
					style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); border-right-width: 3px; border-bottom-width: 3px; font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright); outline: none; box-sizing: border-box;"
				/>
			</div>

			<!-- Variable Chips -->
			<div class="mb-3">
				<label style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 6px;">Insert Variable</label>
				<div class="flex flex-wrap gap-2">
					{#each variables as v}
						<button
							onclick={() => insertVariable(v.key)}
							style="padding: 4px 10px; border: 2px solid var(--color-primary); background: var(--color-surface-bright); font-family: 'Space Grotesk'; font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--color-primary); cursor: pointer; transition: background 0.1s;"
							onmouseenter={(e) => e.target.style.background = 'var(--color-primary-container)'}
							onmouseleave={(e) => e.target.style.background = 'var(--color-surface-bright)'}
						>
							{v.label}
						</button>
					{/each}
				</div>
			</div>

			<!-- Body -->
			<div class="mb-4">
				<label style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 4px;">Body</label>
				<textarea
					bind:this={bodyEl}
					bind:value={body}
					placeholder="TYPE YOUR EMAIL..."
					rows="10"
					style="width: 100%; padding: 12px 14px; border: 2px solid var(--color-on-surface); border-right-width: 3px; border-bottom-width: 3px; font-family: 'Space Grotesk'; font-size: 13px; background: var(--color-surface-bright); resize: vertical; outline: none; line-height: 1.6; box-sizing: border-box;"
				></textarea>
			</div>

			<!-- Preview -->
			{#if showPreview}
				<div class="mb-4">
					<div class="dark-title-bar mb-0" style="font-size: 10px;">Preview</div>
					<div class="ink-border" style="border-top: none; padding: 16px; background: white;">
						<div style="font-size: 12px; font-weight: 700; margin-bottom: 8px; color: var(--color-on-surface-dim);">
							Subject: {renderPreview(subject)}
						</div>
						<div style="font-size: 13px; line-height: 1.7; white-space: pre-wrap;">
							{renderPreview(body)}
						</div>
					</div>
				</div>
			{/if}

			<!-- Send Result -->
			{#if sendResult}
				<div class="mb-4" style="padding: 10px 14px; border: 2px solid {sendResult.type === 'success' ? 'var(--color-primary)' : 'var(--color-error)'}; background: {sendResult.type === 'success' ? '#e8ffe8' : '#ffe8e8'}; font-size: 12px; font-weight: 700;">
					<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle; margin-right: 4px;">{sendResult.type === 'success' ? 'check_circle' : 'error'}</span>
					{sendResult.text}
				</div>
			{/if}

			<!-- Action Buttons -->
			<div class="flex items-center justify-between gap-3">
				<button
					onclick={() => showPreview = !showPreview}
					class="btn-secondary"
					style="font-size: 10px; padding: 8px 14px;"
				>
					<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">preview</span>
					{showPreview ? 'Hide Preview' : 'Preview'}
				</button>

				<div class="flex gap-2">
					<button onclick={resetAndClose} style="background: none; border: 2px solid var(--color-on-surface); padding: 8px 14px; font-family: 'Space Grotesk'; font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; cursor: pointer;">
						Cancel
					</button>
					<button
						class="send-btn"
						onclick={sendEmail}
						disabled={sending || !subject.trim() || !body.trim()}
						style="font-size: 10px; padding: 8px 16px;"
					>
						{#if sending}
							<span class="typing-indicator" style="display: inline-flex; gap: 2px; vertical-align: middle; margin-right: 4px;"><span></span><span></span><span></span></span>
							Sending...
						{:else}
							<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">send</span>
							Send Email
						{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
</div>
{/if}

<style>
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(56, 56, 50, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		padding: 20px;
	}

	.modal-container {
		background: var(--color-surface);
		width: 100%;
		max-width: 640px;
		max-height: 90vh;
		overflow: hidden;
	}
</style>
