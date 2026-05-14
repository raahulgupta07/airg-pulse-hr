<script>
	import { onMount } from 'svelte';
	let positions = $state([]);
	let loading = $state(true);
	let error = $state('');
	let filterDept = $state('all');
	let expandedSlug = $state(null);
	let showApplyModal = $state(false);
	let applyPosition = $state(null);
	let submitting = $state(false);
	let submitResult = $state(null);

	// Form fields
	let formName = $state('');
	let formEmail = $state('');
	let formPhone = $state('');
	let formCoverLetter = $state('');
	let formFile = $state(null);

	// EEO fields (voluntary self-identification)
	let eeoGender = $state('prefer_not_to_say');
	let eeoEthnicity = $state('prefer_not_to_say');
	let eeoVeteran = $state('prefer_not_to_say');
	let eeoDisability = $state('prefer_not_to_say');

	onMount(() => {
		fetchPositions();
	});

	async function fetchPositions() {
		try {
			const res = await fetch('/api/careers/positions');
			if (!res.ok) throw new Error('Failed to load positions');
			const data = await res.json();
			positions = data.positions || [];
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function getDepartments() {
		const depts = new Set(positions.map(p => p.department).filter(Boolean));
		return ['all', ...Array.from(depts).sort()];
	}

	function filteredPositions() {
		if (filterDept === 'all') return positions;
		return positions.filter(p => p.department === filterDept);
	}

	function toggleExpand(slug) {
		expandedSlug = expandedSlug === slug ? null : slug;
	}

	function openApply(pos) {
		applyPosition = pos;
		showApplyModal = true;
		submitResult = null;
		formName = '';
		formEmail = '';
		formPhone = '';
		formCoverLetter = '';
		formFile = null;
		eeoGender = 'prefer_not_to_say';
		eeoEthnicity = 'prefer_not_to_say';
		eeoVeteran = 'prefer_not_to_say';
		eeoDisability = 'prefer_not_to_say';
	}

	function closeModal() {
		showApplyModal = false;
		applyPosition = null;
	}

	function handleFileChange(e) {
		const file = e.target.files?.[0];
		if (file) {
			const ext = file.name.split('.').pop()?.toLowerCase();
			if (!['pdf', 'docx'].includes(ext)) {
				alert('Only PDF and DOCX files are accepted.');
				e.target.value = '';
				return;
			}
			formFile = file;
		}
	}

	async function submitApplication() {
		if (!formName || !formEmail || !formFile || !applyPosition) return;
		submitting = true;
		submitResult = null;

		try {
			const fd = new FormData();
			fd.append('name', formName);
			fd.append('email', formEmail);
			fd.append('phone', formPhone);
			fd.append('cover_letter', formCoverLetter);
			fd.append('position_slug', applyPosition.slug);
			fd.append('file', formFile);

			const res = await fetch('/api/careers/apply', { method: 'POST', body: fd });
			const data = await res.json();

			if (!res.ok) throw new Error(data.detail || 'Submission failed');

			// Submit EEO data separately (voluntary, best-effort)
			if (data.candidate_id) {
				try {
					await fetch(`/api/eeo/${data.candidate_id}`, {
						method: 'POST',
						headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify({
							gender: eeoGender,
							ethnicity: eeoEthnicity,
							veteran_status: eeoVeteran,
							disability_status: eeoDisability,
						}),
					});
				} catch (_) {
					// EEO submission is voluntary — do not block on failure
				}
			}

			submitResult = { success: true, message: data.message };
		} catch (e) {
			submitResult = { success: false, message: e.message };
		} finally {
			submitting = false;
		}
	}

	function formatDate(d) {
		if (!d) return '';
		return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
	}

	function formatType(t) {
		if (!t) return '';
		return t.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
	}

	// ── Application status lookup ──────────────────────────────────
	let statusEmail = $state('');
	let statusLoading = $state(false);
	let statusResult = $state(null); // { stage, last_update, next_steps } | { error }
	async function lookupStatus() {
		if (!statusEmail || !statusEmail.includes('@')) {
			statusResult = { error: 'Please enter a valid email address.' };
			return;
		}
		statusLoading = true;
		statusResult = null;
		try {
			const res = await fetch(`/api/careers/status?email=${encodeURIComponent(statusEmail)}`);
			if (!res.ok) throw new Error('not_found');
			const data = await res.json();
			statusResult = data;
		} catch {
			statusResult = {
				stub: true,
				message: 'Status tracking coming soon. Email recruiter@example.com for updates on your application.',
			};
		} finally {
			statusLoading = false;
		}
	}
</script>

<svelte:head>
	<title>Careers — City Agent Pulse</title>
</svelte:head>

<div class="careers-page">
	<!-- Hero -->
	<section class="hero">
		<div class="hero-inner">
			<div class="hero-badge">NOW HIRING</div>
			<h1 class="hero-title">Join Our Team</h1>
			<p class="hero-sub">
				We are building the future of talent intelligence. Find your next role and help us
				transform how organizations discover and develop exceptional people.
			</p>
		</div>
	</section>

	<!-- Filters + Count -->
	<section class="controls">
		<div class="controls-inner">
			<div class="position-count">
				<span class="count-num">{filteredPositions().length}</span>
				<span class="count-label">Open {filteredPositions().length === 1 ? 'Position' : 'Positions'}</span>
			</div>
			<div class="filter-wrap">
				<label for="dept-filter" class="filter-label">Department</label>
				<select id="dept-filter" bind:value={filterDept} class="filter-select">
					{#each getDepartments() as dept}
						<option value={dept}>{dept === 'all' ? 'All Departments' : dept}</option>
					{/each}
				</select>
			</div>
		</div>
	</section>

	<!-- Application Status Lookup (Claude warm tokens) -->
	<section class="status-lookup">
		<div class="status-inner">
			<div class="status-head">
				<h3 class="status-title">Application status</h3>
				<p class="status-sub">Already applied? Check where you are in the pipeline.</p>
			</div>
			<form class="status-form" onsubmit={(e) => { e.preventDefault(); lookupStatus(); }}>
				<input
					type="email"
					bind:value={statusEmail}
					placeholder="you@email.com"
					class="status-input"
					required
				/>
				<button type="submit" class="status-btn" disabled={statusLoading}>
					{statusLoading ? 'Looking up…' : 'Check status'}
				</button>
			</form>
			{#if statusResult}
				<div class="status-result">
					{#if statusResult.error}
						<div class="status-line status-err">{statusResult.error}</div>
					{:else if statusResult.stub}
						<div class="status-line status-stub">
							<span class="material-symbols-outlined" style="font-size: 16px;">info</span>
							{statusResult.message}
						</div>
					{:else}
						<div class="status-grid">
							<div>
								<div class="status-k">Stage</div>
								<div class="status-v">{statusResult.stage || '—'}</div>
							</div>
							<div>
								<div class="status-k">Last update</div>
								<div class="status-v">{statusResult.last_update || '—'}</div>
							</div>
							<div>
								<div class="status-k">Next steps</div>
								<div class="status-v">{statusResult.next_steps || 'We will reach out soon.'}</div>
							</div>
						</div>
						<div class="status-actions">
							<a href={statusResult.scheduler_url || '#'} class="status-resched">Reschedule interview</a>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</section>

	<!-- Positions List -->
	<section class="positions-section">
		{#if loading}
			<div class="loading-state">
				<div class="loading-bar"></div>
				<p>Loading open positions...</p>
			</div>
		{:else if error}
			<div class="error-state">
				<span class="material-symbols-outlined" style="font-size: 32px;">error</span>
				<p>{error}</p>
			</div>
		{:else if filteredPositions().length === 0}
			<div class="empty-state">
				<span class="material-symbols-outlined" style="font-size: 40px; opacity: 0.3;">work_off</span>
				<p>No open positions {filterDept !== 'all' ? `in ${filterDept}` : 'right now'}.</p>
				<p class="empty-sub">Check back soon — we are always growing.</p>
			</div>
		{:else}
			<div class="positions-list">
				{#each filteredPositions() as pos}
					<div class="position-card" class:expanded={expandedSlug === pos.slug}>
						<div class="card-header" onclick={() => toggleExpand(pos.slug)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && toggleExpand(pos.slug)}>
							<div class="card-left">
								<h2 class="card-title">{pos.title}</h2>
								<div class="card-meta">
									{#if pos.department}
										<span class="meta-tag dept-tag">{pos.department}</span>
									{/if}
									{#if pos.location}
										<span class="meta-item">
											<span class="material-symbols-outlined" style="font-size: 14px;">location_on</span>
											{pos.location}
										</span>
									{/if}
									{#if pos.employment_type}
										<span class="meta-item">
											<span class="material-symbols-outlined" style="font-size: 14px;">schedule</span>
											{formatType(pos.employment_type)}
										</span>
									{/if}
									<span class="meta-item meta-date">Posted {formatDate(pos.created_at)}</span>
								</div>
								{#if pos.required_skills?.length}
									<div class="card-skills">
										{#each pos.required_skills.slice(0, 6) as skill}
											<span class="skill-tag">{skill}</span>
										{/each}
										{#if pos.required_skills.length > 6}
											<span class="skill-more">+{pos.required_skills.length - 6}</span>
										{/if}
									</div>
								{/if}
							</div>
							<div class="card-right">
								<button class="apply-btn" onclick={(e) => { e.stopPropagation(); openApply(pos); }}>
									Apply Now
								</button>
								<span class="expand-icon material-symbols-outlined">
									{expandedSlug === pos.slug ? 'expand_less' : 'expand_more'}
								</span>
							</div>
						</div>

						{#if expandedSlug === pos.slug}
							<div class="card-body">
								{#if pos.nice_to_have_skills?.length}
									<div class="nice-skills">
										<span class="nice-label">Nice to have:</span>
										{#each pos.nice_to_have_skills as skill}
											<span class="nice-tag">{skill}</span>
										{/each}
									</div>
								{/if}
								{#if pos.jd_text}
									<div class="jd-text">{@html pos.jd_text.replace(/\n/g, '<br>')}</div>
								{:else}
									<p class="no-jd">Full job description coming soon. Apply now and we will share more details.</p>
								{/if}
								<div class="card-body-actions">
									<button class="apply-btn apply-btn-lg" onclick={() => openApply(pos)}>
										Apply for this Position
									</button>
								</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</section>
</div>

<!-- Apply Modal -->
{#if showApplyModal && applyPosition}
	<div class="modal-overlay" onclick={closeModal} role="dialog" aria-modal="true">
		<div class="modal-box" onclick={(e) => e.stopPropagation()} role="document">
			{#if submitResult?.success}
				<div class="success-screen">
					<div class="success-icon">
						<span class="material-symbols-outlined" style="font-size: 48px; color: #3a8a4f;">check_circle</span>
					</div>
					<h2>Application Submitted</h2>
					<p>{submitResult.message}</p>
					<button class="modal-close-btn" onclick={closeModal}>Close</button>
				</div>
			{:else}
				<div class="modal-header">
					<div>
						<h2 class="modal-title">Apply for Position</h2>
						<p class="modal-pos-name">{applyPosition.title}</p>
					</div>
					<button class="modal-x" onclick={closeModal}>
						<span class="material-symbols-outlined">close</span>
					</button>
				</div>

				{#if submitResult && !submitResult.success}
					<div class="form-error">{submitResult.message}</div>
				{/if}

				<form class="apply-form" onsubmit={(e) => { e.preventDefault(); submitApplication(); }}>
					<div class="form-row">
						<label class="form-label">
							Full Name <span class="req">*</span>
							<input type="text" bind:value={formName} required class="form-input" placeholder="Your full name" />
						</label>
					</div>
					<div class="form-row form-row-2">
						<label class="form-label">
							Email <span class="req">*</span>
							<input type="email" bind:value={formEmail} required class="form-input" placeholder="you@email.com" />
						</label>
						<label class="form-label">
							Phone
							<input type="tel" bind:value={formPhone} class="form-input" placeholder="+1 (555) 000-0000" />
						</label>
					</div>
					<div class="form-row">
						<label class="form-label">
							Cover Letter
							<textarea bind:value={formCoverLetter} class="form-textarea" rows="4" placeholder="Tell us why you are interested in this role..."></textarea>
						</label>
					</div>
					<div class="form-row">
						<label class="form-label">
							Resume / CV <span class="req">*</span>
							<div class="file-upload">
								<input type="file" accept=".pdf,.docx" onchange={handleFileChange} required class="file-input" />
								<div class="file-label">
									<span class="material-symbols-outlined" style="font-size: 20px;">upload_file</span>
									{#if formFile}
										<span>{formFile.name}</span>
									{:else}
										<span>Upload PDF or DOCX</span>
									{/if}
								</div>
							</div>
						</label>
					</div>
					<!-- Voluntary Self-Identification (EEO) -->
					<div class="eeo-section">
						<div class="eeo-header">
							<span class="eeo-title">Voluntary Self-Identification</span>
							<span class="eeo-subtitle">This information is collected for compliance purposes only. It will not be used in hiring decisions.</span>
						</div>
						<div class="form-row form-row-2">
							<label class="form-label">
								Gender
								<select bind:value={eeoGender} class="form-input">
									<option value="prefer_not_to_say">Prefer not to say</option>
									<option value="male">Male</option>
									<option value="female">Female</option>
									<option value="non_binary">Non-binary</option>
								</select>
							</label>
							<label class="form-label">
								Ethnicity
								<select bind:value={eeoEthnicity} class="form-input">
									<option value="prefer_not_to_say">Prefer not to say</option>
									<option value="white">White</option>
									<option value="asian">Asian</option>
									<option value="black">Black or African American</option>
									<option value="hispanic">Hispanic or Latino</option>
									<option value="native_american">Native American</option>
									<option value="two_or_more">Two or more races</option>
								</select>
							</label>
						</div>
						<div class="form-row form-row-2">
							<label class="form-label">
								Veteran Status
								<select bind:value={eeoVeteran} class="form-input">
									<option value="prefer_not_to_say">Prefer not to say</option>
									<option value="yes">Yes</option>
									<option value="no">No</option>
								</select>
							</label>
							<label class="form-label">
								Disability
								<select bind:value={eeoDisability} class="form-input">
									<option value="prefer_not_to_say">Prefer not to say</option>
									<option value="yes">Yes</option>
									<option value="no">No</option>
								</select>
							</label>
						</div>
					</div>

					<div class="form-actions">
						<button type="button" class="cancel-btn" onclick={closeModal}>Cancel</button>
						<button type="submit" class="submit-btn" disabled={submitting || !formName || !formEmail || !formFile}>
							{#if submitting}
								Submitting...
							{:else}
								Submit Application
							{/if}
						</button>
					</div>
				</form>
			{/if}
		</div>
	</div>
{/if}

<style>
	/* Page */
	.careers-page {
		font-family: 'Space Grotesk', sans-serif;
	}

	/* Hero */
	.hero {
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		padding: 4rem 2rem;
		text-align: center;
	}
	.hero-inner {
		max-width: 680px;
		margin: 0 auto;
	}
	.hero-badge {
		display: inline-block;
		background: var(--color-accent, #c96342);
		color: #fff;
		font-size: 11px;
		font-weight: 900;
		letter-spacing: 0.12em;
		padding: 4px 14px;
		border-radius: 4px;
		margin-bottom: 1.5rem;
	}
	.hero-title {
		font-size: 3rem;
		font-weight: 900;
		letter-spacing: -0.04em;
		line-height: 1.1;
		margin: 0 0 1rem 0;
	}
	.hero-sub {
		font-size: 1.1rem;
		line-height: 1.6;
		opacity: 0.7;
		margin: 0;
		font-weight: 400;
	}

	/* Controls */
	.controls {
		background: white;
		border-bottom: 1px solid var(--color-border, #d8d5cc);
		padding: 1rem 2rem;
		position: sticky;
		top: 0;
		z-index: 10;
	}
	.controls-inner {
		max-width: 900px;
		margin: 0 auto;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}
	.position-count {
		display: flex;
		align-items: baseline;
		gap: 8px;
	}
	.count-num {
		font-size: 2rem;
		font-weight: 900;
		color: var(--color-on-surface, #2c2c2c);
		line-height: 1;
	}
	.count-label {
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #888;
	}
	.filter-wrap {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.filter-label {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: #888;
	}
	.filter-select {
		font-family: 'Space Grotesk', sans-serif;
		font-size: 13px;
		font-weight: 600;
		padding: 6px 12px;
		border: 1px solid var(--color-border, #d8d5cc);
		background: white;
		color: var(--color-on-surface, #2c2c2c);
		cursor: pointer;
		border-radius: 6px;
	}

	/* Positions */
	.positions-section {
		max-width: 900px;
		margin: 2rem auto;
		padding: 0 2rem;
	}
	.positions-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.position-card {
		background: white;
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 8px;
		transition: box-shadow 0.15s;
	}
	.position-card:hover {
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
	}
	.card-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: 1.25rem 1.5rem;
		cursor: pointer;
		gap: 1rem;
	}
	.card-left {
		flex: 1;
		min-width: 0;
	}
	.card-title {
		font-size: 1.25rem;
		font-weight: 800;
		margin: 0 0 8px 0;
		color: var(--color-on-surface, #2c2c2c);
		letter-spacing: -0.02em;
	}
	.card-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
		margin-bottom: 8px;
	}
	.dept-tag {
		background: var(--color-accent, #c96342);
		color: white;
		padding: 2px 10px;
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		border-radius: 4px;
	}
	.meta-item {
		display: flex;
		align-items: center;
		gap: 3px;
		font-size: 13px;
		color: #666;
		font-weight: 500;
	}
	.meta-date {
		opacity: 0.6;
		font-size: 12px;
	}
	.card-skills {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 6px;
	}
	.skill-tag {
		background: var(--color-surface-highest, #f5f0eb);
		color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc);
		padding: 2px 8px;
		font-size: 11px;
		font-weight: 600;
		border-radius: 4px;
	}
	.skill-more {
		font-size: 11px;
		color: #888;
		font-weight: 700;
		padding: 2px 4px;
	}
	.card-right {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 8px;
		flex-shrink: 0;
	}
	.apply-btn {
		background: var(--color-accent, #c96342);
		color: #fff;
		border: none;
		padding: 8px 20px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 12px;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		cursor: pointer;
		border-radius: 6px;
		transition: background 0.15s;
	}
	.apply-btn:hover {
		background: #b5593b;
	}
	.apply-btn-lg {
		padding: 12px 32px;
		font-size: 13px;
	}
	.expand-icon {
		color: #aaa;
		font-size: 20px;
	}

	/* Expanded card body */
	.card-body {
		border-top: 1px solid #eee;
		padding: 1.5rem;
		background: #fafaf5;
	}
	.nice-skills {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin-bottom: 1rem;
	}
	.nice-label {
		font-size: 11px;
		font-weight: 700;
		color: #888;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.nice-tag {
		background: white;
		border: 1px dashed #bbb;
		padding: 2px 8px;
		font-size: 11px;
		color: #666;
	}
	.jd-text {
		font-size: 14px;
		line-height: 1.7;
		color: #444;
		max-width: 700px;
	}
	.no-jd {
		color: #888;
		font-style: italic;
	}
	.card-body-actions {
		margin-top: 1.5rem;
		padding-top: 1rem;
		border-top: 1px solid #ddd;
	}

	/* States */
	.loading-state, .error-state, .empty-state {
		text-align: center;
		padding: 4rem 2rem;
		color: #888;
	}
	.loading-bar {
		width: 60px;
		height: 4px;
		background: var(--color-accent, #c96342);
		border-radius: 2px;
		margin: 0 auto 1rem;
		animation: loadPulse 1s infinite;
	}
	@keyframes loadPulse {
		0%, 100% { opacity: 0.3; }
		50% { opacity: 1; }
	}
	.empty-sub {
		font-size: 13px;
		opacity: 0.6;
	}

	/* Modal */
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(56, 56, 50, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: 1rem;
	}
	.modal-box {
		background: white;
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 12px;
		width: 100%;
		max-width: 560px;
		max-height: 90vh;
		overflow-y: auto;
		padding: 2rem;
		box-shadow: 0 1px 3px rgba(0,0,0,0.08);
	}
	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 1.5rem;
	}
	.modal-title {
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: #888;
		margin: 0 0 4px 0;
	}
	.modal-pos-name {
		font-size: 1.25rem;
		font-weight: 800;
		color: var(--color-on-surface, #2c2c2c);
		margin: 0;
	}
	.modal-x {
		background: none;
		border: none;
		cursor: pointer;
		color: #888;
		padding: 4px;
	}
	.modal-x:hover {
		color: var(--color-on-surface, #2c2c2c);
	}

	/* Form */
	.apply-form {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.form-row-2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}
	.form-label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: #555;
	}
	.req {
		color: #ff4444;
	}
	.form-input, .form-textarea {
		font-family: 'Space Grotesk', sans-serif;
		font-size: 14px;
		padding: 10px 12px;
		border: 1px solid var(--color-border, #d8d5cc);
		background: var(--color-bg, #faf9f5);
		color: var(--color-on-surface, #2c2c2c);
		border-radius: 6px;
		transition: border-color 0.15s;
	}
	.form-input:focus, .form-textarea:focus {
		outline: none;
		border-color: var(--color-accent, #c96342);
	}
	.form-textarea {
		resize: vertical;
		min-height: 80px;
	}
	.file-upload {
		position: relative;
	}
	.file-input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
		z-index: 2;
	}
	.file-label {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px;
		border: 2px dashed #ccc;
		background: #fafaf5;
		color: #888;
		font-size: 13px;
		font-weight: 500;
		text-transform: none;
		letter-spacing: 0;
	}
	.form-actions {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
		margin-top: 0.5rem;
	}
	.cancel-btn {
		background: none;
		border: 2px solid #ddd;
		padding: 10px 20px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		color: #666;
	}
	.submit-btn {
		background: var(--color-accent, #c96342);
		color: #fff;
		border: none;
		padding: 10px 24px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 12px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		border-radius: 6px;
	}
	.submit-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.form-error {
		background: #fff0f0;
		border: 1px solid #ff4444;
		color: #cc0000;
		padding: 10px 14px;
		font-size: 13px;
		margin-bottom: 0.5rem;
	}

	/* EEO Section */
	.eeo-section {
		border-top: 2px dashed #ccc;
		margin-top: 0.5rem;
		padding-top: 1rem;
	}
	.eeo-header {
		margin-bottom: 0.75rem;
	}
	.eeo-title {
		display: block;
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--color-on-surface, #2c2c2c);
		margin-bottom: 4px;
	}
	.eeo-subtitle {
		display: block;
		font-size: 11px;
		font-weight: 400;
		color: #888;
		line-height: 1.4;
	}

	/* Success */
	.success-screen {
		text-align: center;
		padding: 2rem 0;
	}
	.success-icon {
		margin-bottom: 1rem;
	}
	.success-screen h2 {
		font-size: 1.25rem;
		font-weight: 800;
		margin: 0 0 0.5rem 0;
	}
	.success-screen p {
		color: #666;
		font-size: 14px;
		line-height: 1.6;
		margin: 0 0 1.5rem 0;
	}
	.modal-close-btn {
		background: var(--color-accent, #c96342);
		color: #fff;
		border: none;
		padding: 10px 28px;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		border-radius: 6px;
	}

	@media (max-width: 640px) {
		.hero-title { font-size: 2rem; }
		.hero { padding: 2.5rem 1.5rem; }
		.controls-inner { flex-direction: column; align-items: flex-start; }
		.card-header { flex-direction: column; }
		.card-right { flex-direction: row; align-items: center; width: 100%; }
		.form-row-2 { grid-template-columns: 1fr; }
	}

	/* ── Application status lookup (Claude warm tokens) ── */
	.status-lookup {
		background: #faf9f5;
		border-top: 1px solid #e8e6dc;
		border-bottom: 1px solid #e8e6dc;
		padding: 32px 24px;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}
	.status-inner {
		max-width: 720px;
		margin: 0 auto;
	}
	.status-head { margin-bottom: 16px; }
	.status-title {
		font-family: 'Tiempos Headline', Georgia, serif;
		font-size: 22px;
		font-weight: 500;
		color: #2d2a26;
		margin: 0;
	}
	.status-sub {
		font-size: 13.5px;
		color: #6b6b66;
		margin: 4px 0 0;
	}
	.status-form {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.status-input {
		flex: 1;
		min-width: 240px;
		padding: 10px 14px;
		border: 1px solid #e8e6dc;
		border-radius: 8px;
		background: #ffffff;
		font-size: 13.5px;
		font-family: inherit;
		color: #2d2a26;
	}
	.status-input:focus {
		outline: none;
		border-color: #c96342;
	}
	.status-btn {
		padding: 10px 18px;
		background: #c96342;
		color: #ffffff;
		border: none;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
	}
	.status-btn:hover { background: #b35535; }
	.status-btn:disabled { opacity: 0.6; cursor: not-allowed; }
	.status-result {
		margin-top: 16px;
		background: #ffffff;
		border: 1px solid #e8e6dc;
		border-radius: 12px;
		padding: 16px;
	}
	.status-line { font-size: 13.5px; color: #2d2a26; display: flex; align-items: center; gap: 8px; }
	.status-err { color: #a83232; }
	.status-stub { color: #6b6b66; }
	.status-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 16px;
	}
	.status-k {
		font-size: 11px;
		font-weight: 500;
		color: #8a8a82;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.status-v {
		font-size: 14px;
		color: #2d2a26;
		margin-top: 4px;
	}
	.status-actions { margin-top: 14px; }
	.status-resched {
		display: inline-block;
		padding: 7px 14px;
		background: transparent;
		color: #c96342;
		border: 1px solid #c96342;
		border-radius: 8px;
		font-size: 12.5px;
		font-weight: 500;
		text-decoration: none;
	}
	.status-resched:hover { background: #fdebe1; }
	@media (max-width: 720px) {
		.status-grid { grid-template-columns: 1fr; }
	}
</style>
