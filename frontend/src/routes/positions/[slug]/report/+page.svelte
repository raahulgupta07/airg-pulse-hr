<script>
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { apiJson } from '$lib/api';

	let loading = $state(true);
	let error = $state('');
	const slug = $derived(page.params.slug);

	/** @type {any} */ let position = $state(null);
	/** @type {any[]} */ let candidates = $state([]);
	/** @type {any} */ let pipeline = $state({});
	/** @type {any[]} */ let interviews = $state([]);
	/** @type {any[]} */ let offers = $state([]);
	/** @type {Record<number, any[]>} */ let notesMap = $state({});

	let evalConsensus = $state({});
	let evalFlags = $state({});
	let evalVotes = $state({});
	let evalStackRank = $state([]);
	let evalCalibration = $state([]);

	const stageColors = {
		uploaded: 'var(--color-on-surface-dim, #6f6e69)', screened: '#006f7c', shortlisted: '#3a8a4f',
		interview_scheduled: 'var(--color-warning, #c98c2a)', interviewed: '#9d4867',
		offered: 'var(--color-accent, #c96342)', hired: '#3a8a4f', rejected: '#666'
	};
	const stageLabels = {
		uploaded: 'Uploaded', screened: 'Screened', shortlisted: 'Shortlisted',
		interview_scheduled: 'Interview Scheduled', interviewed: 'Interviewed',
		offered: 'Offered', hired: 'Hired', rejected: 'Rejected'
	};
	const stageOrder = ['uploaded', 'screened', 'shortlisted', 'interview_scheduled', 'interviewed', 'offered', 'hired'];

	const reportId = $derived('RPT-' + (slug || '').toUpperCase().slice(0, 6) + '-' + Date.now().toString(36).toUpperCase().slice(-4));
	const today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

	const sorted = $derived([...candidates].sort((a, b) => (b.match_score_composite || 0) - (a.match_score_composite || 0)));
	const top3 = $derived(sorted.slice(0, 3));
	const rest = $derived(sorted.slice(3));
	const qualified = $derived(candidates.filter(c => (c.match_score_composite || 0) >= 50));
	const interviewedCandidates = $derived(candidates.filter(c => ['interviewed', 'offered', 'hired'].includes(c.stage)));
	const offeredCandidates = $derived(candidates.filter(c => ['offered', 'hired'].includes(c.stage)));
	const avgMatch = $derived(candidates.length ? Math.round(candidates.reduce((s, c) => s + (c.match_score_composite || 0), 0) / candidates.length) : 0);
	const daysOpen = $derived(position ? Math.floor((Date.now() - new Date(position.created_at).getTime()) / 86400000) : 0);
	const conversionRate = $derived(candidates.length && offeredCandidates.length ? Math.round(offeredCandidates.length / candidates.length * 100) : 0);

	const requiredSkills = $derived(position?.required_skills || []);

	// Risks auto-detected
	const risks = $derived(computeRisks());
	function computeRisks() {
		/** @type {{desc: string, severity: string, status: string}[]} */ const r = [];
		// Skills coverage
		if (requiredSkills.length && top3.length) {
			for (const skill of requiredSkills) {
				const coverage = top3.filter(c => (c.skills_matched || []).map(/** @param {string} s */ s => s.toLowerCase()).includes(skill.toLowerCase())).length;
				if (coverage <= 1) r.push({ desc: `Skill "${skill}" covered by only ${coverage} of top 3 candidates`, severity: 'high', status: 'Open' });
			}
		}
		if (offers.some(o => o.status === 'pending' || o.status === 'sent')) r.push({ desc: 'Pending offer awaiting response', severity: 'medium', status: 'Pending' });
		if (!candidates.some(c => c.stage === 'hired')) r.push({ desc: 'No hire made yet', severity: 'medium', status: 'Open' });
		if (qualified.length < 3) r.push({ desc: `Small qualified pipeline (${qualified.length} candidates)`, severity: 'high', status: 'Open' });
		return r;
	}

	// Action items
	const actions = $derived(computeActions());
	function computeActions() {
		/** @type {{priority: string, text: string}[]} */ const a = [];
		const pendingOffers = offers.filter(o => o.status === 'pending' || o.status === 'sent');
		if (pendingOffers.length) a.push({ priority: 'urgent', text: `Follow up on ${pendingOffers.length} pending offer(s)` });
		const scheduledInts = interviews.filter(i => i.status === 'scheduled');
		if (scheduledInts.length) a.push({ priority: 'high', text: `Complete ${scheduledInts.length} scheduled interview(s)` });
		const shortlisted = candidates.filter(c => c.stage === 'shortlisted');
		if (shortlisted.length) a.push({ priority: 'high', text: `Schedule interviews for ${shortlisted.length} shortlisted candidate(s)` });
		if (top3.length) {
			const gaps = top3.flatMap(c => c.skills_missing || []);
			if (gaps.length) a.push({ priority: 'medium', text: `Plan training for skill gaps: ${[...new Set(gaps)].slice(0, 3).join(', ')}` });
		}
		if (!a.length) a.push({ priority: 'medium', text: 'Pipeline is in good shape — no urgent actions needed' });
		return a;
	}

	$effect(() => {
		const s = slug;
		if (s) untrack(() => loadAll());
	});

	async function loadAll() {
		loading = true;
		error = '';
		try {
			position = await apiJson(`/positions/${slug}`);
			const candData = await apiJson(`/positions/${slug}/candidates`);
			candidates = candData.candidates || [];
			pipeline = candData.pipeline || {};

			// Interviews & offers — may fail
			try { const intData = await apiJson(`/interviews?position_id=${position.id}`); interviews = intData.interviews || intData || []; } catch { interviews = []; }
			try { const offData = await apiJson(`/offers?position_id=${position.id}`); offers = offData.offers || offData || []; } catch { offers = []; }

			// Notes for top 3
			const sortedTemp = [...candidates].sort((a, b) => (b.match_score_composite || 0) - (a.match_score_composite || 0));
			for (const c of sortedTemp.slice(0, 3)) {
				const cid = c.candidate_id || c.id;
				try { const nd = await apiJson(`/candidates/${cid}/notes`); notesMap[cid] = nd.notes || nd || []; } catch { notesMap[cid] = []; }
			}

			// Evaluation data
			const [consensusRes, flagsRes, votesRes, rankRes, calRes] = await Promise.all([
				apiJson(`/evaluation/positions/${slug}/consensus`).catch(() => ({ consensus: {} })),
				apiJson(`/evaluation/positions/${slug}/flags`).catch(() => ({ flags: {} })),
				apiJson(`/evaluation/positions/${slug}/votes`).catch(() => ({ votes: {} })),
				apiJson(`/evaluation/positions/${slug}/stack-rank`).catch(() => ({ rankings: [] })),
				apiJson(`/evaluation/positions/${slug}/calibration`).catch(() => ({ interviewers: [] })),
			]);
			evalConsensus = consensusRes.consensus || {};
			evalFlags = flagsRes.flags || {};
			evalVotes = votesRes.votes || {};
			evalStackRank = rankRes.rankings || [];
			evalCalibration = calRes.interviewers || [];
		} catch (e) {
			error = e.message || 'Failed to load data';
		}
		loading = false;
	}

	/** @param {number} score */
	function scoreColor(score) {
		if (score >= 70) return '#3a8a4f';
		if (score >= 50) return 'var(--color-warning, #c98c2a)';
		return 'var(--color-error, #c4571a)';
	}

	/** @param {number} count @param {number} max */
	function dots(count, max) {
		return '●'.repeat(Math.min(count, max)) + '○'.repeat(Math.max(0, max - count));
	}

	/** @param {any} c @param {string} dim */
	function dimScore(c, dim) {
		const map = { skills: 'match_score_skills', experience: 'match_score_experience', education: 'match_score_education', industry: 'match_score_industry', certs: 'match_score_certifications', culture: 'match_score_culture' };
		return Math.round(c[map[dim]] || 0);
	}

	/** @param {any} c */
	function strengths(c) {
		/** @type {string[]} */ const s = [];
		if ((c.skills_matched || []).length) s.push(`${(c.skills_matched || []).length} required skills matched`);
		if ((c.match_score_composite || 0) >= 70) s.push(`Strong overall match (${Math.round(c.match_score_composite)}%)`);
		if ((c.total_experience_years || 0) >= (position?.min_experience_years || 0) && position?.min_experience_years) s.push(`${c.total_experience_years}+ years experience (meets ${position.min_experience_years}yr minimum)`);
		if (c.current_company) s.push(`Currently at ${c.current_company}`);
		if ((c.match_score_education || 0) >= 80) s.push(`Education score: ${Math.round(c.match_score_education)}%`);
		if (!s.length) s.push('Meets basic qualifications');
		return s;
	}

	/** @param {any} c */
	function concerns(c) {
		/** @type {string[]} */ const s = [];
		if ((c.skills_missing || []).length) s.push(`Missing skills: ${(c.skills_missing || []).join(', ')}`);
		if ((c.match_score_composite || 0) < 70) s.push(`Below 70% threshold (${Math.round(c.match_score_composite || 0)}%)`);
		if ((c.match_score_skills || 0) < 50) s.push(`Low skills match (${Math.round(c.match_score_skills || 0)}%)`);
		if ((c.total_experience_years || 0) < (position?.min_experience_years || 0) && position?.min_experience_years) s.push(`Under minimum experience (${c.total_experience_years || 0} vs ${position.min_experience_years}yr)`);
		return s;
	}

	const pipelineTotal = $derived(candidates.length || 1);
	const dims = ['skills', 'experience', 'education', 'industry', 'certs', 'culture'];
	const dimLabels = { skills: 'Skills', experience: 'Experience', education: 'Education', industry: 'Industry', certs: 'Certifications', culture: 'Culture' };

	function flagColor(type) { return type === 'red' ? 'var(--color-error, #c4571a)' : type === 'amber' ? 'var(--color-warning, #c98c2a)' : '#3a8a4f'; }

	/** @param {any[]} arr @param {string} dim */
	function winnerIdx(arr, dim) {
		if (!arr.length) return -1;
		const scores = arr.map(c => dimScore(c, dim));
		const max = Math.max(...scores);
		return scores.indexOf(max);
	}

	/** @param {any[]} arr */
	function overallWinnerIdx(arr) {
		if (!arr.length) return -1;
		const scores = arr.map(c => c.match_score_composite || 0);
		const max = Math.max(...scores);
		return scores.indexOf(max);
	}
</script>

<div class="report-page">
	<!-- Header bar (hidden in print) -->
	<div class="report-header no-print">
		<div class="header-row">
			<a href="/positions/{slug}" class="back-link">&larr; Back to Position</a>
			<div class="header-actions">
				<button class="print-btn" onclick={() => window.print()}>
					<span class="material-symbols-outlined" style="font-size:14px; vertical-align:middle;">print</span>
					Print Report
				</button>
				<button class="close-btn" onclick={() => history.back()}>Close</button>
			</div>
		</div>
	</div>

	{#if loading}
		<div class="report-loading">
			<div class="loading-spinner"></div>
			<p>Loading hiring data...</p>
		</div>
	{:else if error}
		<div class="report-error">
			<span class="material-symbols-outlined" style="font-size:32px; color:var(--color-error, #c4571a);">error</span>
			<h2>Failed to Load Report</h2>
			<p>{error}</p>
			<a href="/positions/{slug}" class="back-link" style="margin-top:16px; display:inline-block;">&larr; Back to Position</a>
		</div>
	{:else if position}
		<div class="report-body">

			<!-- ====== 1. COVER HEADER ====== -->
			<div class="cover-header">
				<div class="cover-logo">City Agent Pulse</div>
				<div class="cover-subtitle">HIRING INTELLIGENCE REPORT</div>
				<div class="cover-divider"></div>
				<h1 class="cover-title">{position.title}</h1>
				<div class="cover-meta">
					<span>{position.department || 'General'}</span>
					<span class="cover-dot">&bull;</span>
					<span>{position.location || 'Remote'}</span>
					<span class="cover-dot">&bull;</span>
					<span>{position.employment_type || 'Full-time'}</span>
				</div>
				<div class="cover-footer">
					<span>Generated {today}</span>
					<span>{reportId}</span>
				</div>
			</div>

			<!-- ====== 2. EXECUTIVE SNAPSHOT ====== -->
			<section class="section">
				<h2 class="section-title">Executive Snapshot</h2>
				<div class="metrics-row">
					<div class="metric-circle">
						<div class="metric-number">{candidates.length}</div>
						<div class="metric-label">Total</div>
						<div class="metric-dots">{dots(candidates.length, 5)}</div>
					</div>
					<div class="metric-circle">
						<div class="metric-number">{qualified.length}</div>
						<div class="metric-label">Qualified</div>
						<div class="metric-dots">{dots(qualified.length, 5)}</div>
					</div>
					<div class="metric-circle">
						<div class="metric-number">{interviewedCandidates.length}</div>
						<div class="metric-label">Interviewed</div>
						<div class="metric-dots">{dots(interviewedCandidates.length, 5)}</div>
					</div>
					<div class="metric-circle">
						<div class="metric-number">{offeredCandidates.length}</div>
						<div class="metric-label">Offers</div>
						<div class="metric-dots">{dots(offeredCandidates.length, 5)}</div>
					</div>
				</div>

				<div class="snapshot-stats">
					<div class="stat-item"><span class="stat-value">{avgMatch}%</span><span class="stat-label">Avg Match</span></div>
					<div class="stat-item"><span class="stat-value">{daysOpen}</span><span class="stat-label">Days Open</span></div>
					<div class="stat-item"><span class="stat-value">{conversionRate}%</span><span class="stat-label">Conversion</span></div>
				</div>

				{#if sorted.length}
					<div class="verdict-box">
						<div class="verdict-icon">&#10003;</div>
						<div class="verdict-text">
							<strong>Recommended:</strong> {sorted[0].name} — {Math.round(sorted[0].match_score_composite || 0)}% match
							{#if sorted.length > 1}
								<span class="verdict-backup">Backup: {sorted[1].name} ({Math.round(sorted[1].match_score_composite || 0)}%)</span>
							{/if}
						</div>
					</div>
				{/if}
			</section>

			<!-- ====== 3. CANDIDATE SCORECARDS ====== -->
			<section class="section">
				<h2 class="section-title">Candidate Scorecards</h2>

				{#each top3 as c, i}
					{@const cid = c.candidate_id || c.id}
					{@const cNotes = notesMap[cid] || []}
					{@const cInterviews = interviews.filter(iv => iv.candidate_id === cid)}
					<div class="scorecard">
						<div class="scorecard-header">
							<div class="scorecard-rank">#{i + 1}</div>
							<div class="scorecard-info">
								<div class="scorecard-name">
									{c.name}
									{#each (evalFlags[c.candidate_id || c.id] || []) as flag}
										<span style="display: inline-block; width: 10px; height: 10px; background: {flagColor(flag.flag_type)}; border: 1px solid var(--color-border, #d8d5cc); border-radius: 50%; margin-left: 3px;" title="{flag.title}: {flag.description}"></span>
									{/each}
								</div>
								<div class="scorecard-meta">
									{#if c.current_role}{c.current_role}{/if}
									{#if c.current_company} at {c.current_company}{/if}
									{#if c.total_experience_years} &middot; {c.total_experience_years} yrs{/if}
									{#if c.location} &middot; {c.location}{/if}
								</div>
							</div>
							<div class="scorecard-overall" style="color:{scoreColor(c.match_score_composite || 0)}">
								{Math.round(c.match_score_composite || 0)}%
							</div>
						</div>

						<!-- Score bars -->
						<div class="score-bars">
							{#each [
								{ label: 'Skills', key: 'skills', color: '#3a8a4f' },
								{ label: 'Experience', key: 'experience', color: '#006f7c' },
								{ label: 'Education', key: 'education', color: '#7c3aed' },
								{ label: 'Industry', key: 'industry', color: '#0d9488' },
								{ label: 'Certifications', key: 'certs', color: 'var(--color-warning, #c98c2a)' },
								{ label: 'Culture', key: 'culture', color: '#9d4867' }
							] as dim}
								{@const val = dimScore(c, dim.key)}
								<div class="score-bar-row">
									<span class="score-bar-label">{dim.label}</span>
									<div class="score-bar-track">
										<div class="score-bar-fill" style="width:{val}%; background:{dim.color};"></div>
									</div>
									<span class="score-bar-value">{val}%</span>
								</div>
							{/each}
						</div>

						<!-- Votes & Consensus -->
						{#if evalVotes[c.candidate_id || c.id] && ((evalVotes[c.candidate_id || c.id].strong_hire || 0) + (evalVotes[c.candidate_id || c.id].hire || 0) + (evalVotes[c.candidate_id || c.id].no_hire || 0) + (evalVotes[c.candidate_id || c.id].strong_no_hire || 0) > 0)}
							<div style="margin-top: 6px; font-size: 10px; font-weight: 700;">
								VOTES: <span style="color: #3a8a4f;">SH:{evalVotes[c.candidate_id || c.id].strong_hire || 0} H:{evalVotes[c.candidate_id || c.id].hire || 0}</span> · <span style="color: #ff3b30;">NH:{evalVotes[c.candidate_id || c.id].no_hire || 0} SNH:{evalVotes[c.candidate_id || c.id].strong_no_hire || 0}</span>
							</div>
						{/if}
						{#if evalConsensus[c.candidate_id || c.id] && evalConsensus[c.candidate_id || c.id].evaluator_count > 0}
							<div style="margin-top: 4px; font-size: 10px; padding: 3px 8px; border: 1px solid var(--color-border, #d8d5cc); display: inline-block;">
								CONSENSUS: {evalConsensus[c.candidate_id || c.id].avg_overall?.toFixed?.(1) || evalConsensus[c.candidate_id || c.id].avg_overall}/5 · {evalConsensus[c.candidate_id || c.id].evaluator_count} evaluators · {(evalConsensus[c.candidate_id || c.id].agreement_level || '').replace('_', ' ').toUpperCase()}
								{#if evalConsensus[c.candidate_id || c.id].lone_dissent_flag}<span style="color: var(--color-warning, #c98c2a);"> DISSENT</span>{/if}
							</div>
						{/if}

						<!-- Stage badge -->
						<div class="scorecard-badges">
							<span class="stage-badge" style="background:{stageColors[c.stage] || 'var(--color-on-surface-dim, #6f6e69)'}">{stageLabels[c.stage] || c.stage}</span>
							{#if cInterviews.length}
								<span class="interview-badge">{cInterviews.length} interview{cInterviews.length > 1 ? 's' : ''} ({cInterviews[0]?.status || 'scheduled'})</span>
							{/if}
						</div>

						<!-- Strengths & Concerns -->
						<div class="scorecard-columns">
							<div class="scorecard-col">
								<div class="col-header col-green">&#10003; Strengths</div>
								<ul class="col-list">
									{#each strengths(c) as s}
										<li>{s}</li>
									{/each}
								</ul>
							</div>
							<div class="scorecard-col">
								<div class="col-header col-red">&#9888; Concerns</div>
								<ul class="col-list">
									{#if concerns(c).length}
										{#each concerns(c) as s}
											<li>{s}</li>
										{/each}
									{:else}
										<li class="muted">No major concerns</li>
									{/if}
								</ul>
							</div>
						</div>

						<!-- Notes preview -->
						{#if cNotes.length}
							<div class="notes-preview">
								<span class="notes-label">Latest Note:</span>
								{cNotes[0].content?.slice(0, 120) || '—'}{cNotes[0].content?.length > 120 ? '...' : ''}
							</div>
						{/if}
					</div>
				{/each}

				<!-- Compact cards for remaining -->
				{#if rest.length}
					<div class="compact-header">Other Candidates</div>
					{#each rest as c, i}
						<div class="compact-card">
							<span class="compact-rank">#{i + 4}</span>
							<span class="compact-name">{c.name}</span>
							<span class="compact-score" style="color:{scoreColor(c.match_score_composite || 0)}">{Math.round(c.match_score_composite || 0)}%</span>
							<span class="stage-badge compact-badge" style="background:{stageColors[c.stage] || 'var(--color-on-surface-dim, #6f6e69)'}">{stageLabels[c.stage] || c.stage}</span>
							<span class="compact-verdict">Not recommended</span>
						</div>
					{/each}
				{/if}
			</section>

			<!-- ====== 4. HEAD-TO-HEAD COMPARISON ====== -->
			{#if top3.length >= 2}
				<section class="section">
					<h2 class="section-title">Head-to-Head Comparison</h2>
					<table class="comparison-table">
						<thead>
							<tr>
								<th>Dimension</th>
								{#each top3 as c}
									<th>{c.name}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							<!-- Overall row -->
							<tr>
								<td class="row-label">Overall</td>
								{#each top3 as c, i}
									<td class:winner={i === overallWinnerIdx(top3)}>{Math.round(c.match_score_composite || 0)}%</td>
								{/each}
							</tr>
							{#each dims as dim}
								<tr>
									<td class="row-label">{dimLabels[dim]}</td>
									{#each top3 as c, i}
										<td class:winner={i === winnerIdx(top3, dim)}>{dimScore(c, dim)}%</td>
									{/each}
								</tr>
							{/each}
							<!-- Extra info rows -->
							<tr>
								<td class="row-label">Years Exp.</td>
								{#each top3 as c}
									<td>{c.total_experience_years || '—'}</td>
								{/each}
							</tr>
							<tr>
								<td class="row-label">Company</td>
								{#each top3 as c}
									<td>{c.current_company || '—'}</td>
								{/each}
							</tr>
							<tr class="verdict-row">
								<td class="row-label">Verdict</td>
								{#each top3 as c, i}
									<td>
										{#if i === 0}
											<span class="verdict-tag green">Recommended</span>
										{:else if i === 1}
											<span class="verdict-tag orange">Backup</span>
										{:else}
											<span class="verdict-tag gray">Consider</span>
										{/if}
									</td>
								{/each}
							</tr>
						</tbody>
					</table>
				</section>
			{/if}

			<!-- ====== 4b. STACK RANKING ====== -->
			{#if evalStackRank.length > 0}
				<section class="section">
					<h2 class="section-title">Stack Ranking</h2>
					<table class="comparison-table">
						<thead>
							<tr>
								<th>Rank</th>
								<th>Candidate</th>
								<th>Composite</th>
								<th>Consensus</th>
								<th>Flags</th>
								<th>Final</th>
							</tr>
						</thead>
						<tbody>
							{#each evalStackRank.slice(0, 10) as r}
								<tr>
									<td style="font-weight: 900; font-size: 14px;">#{r.rank}</td>
									<td style="font-weight: 700; text-align: left;">{r.name}</td>
									<td>{r.composite}%</td>
									<td>{r.consensus_avg ? r.consensus_avg.toFixed(1) + '/5' : '—'}</td>
									<td>
										{#if r.flag_counts}
											<span style="color: #ff3b30;">{r.flag_counts.red || 0}R</span>
											<span style="color: var(--color-warning, #c98c2a);">{r.flag_counts.amber || 0}A</span>
											<span style="color: #3a8a4f;">{r.flag_counts.green || 0}G</span>
										{/if}
									</td>
									<td style="font-weight: 900; color: {r.final_score >= 70 ? '#3a8a4f' : r.final_score >= 50 ? 'var(--color-warning, #c98c2a)' : 'var(--color-error, #c4571a)'};">{r.final_score}%</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</section>
			{/if}

			<!-- ====== 5. SKILLS HEAT MAP ====== -->
			{#if requiredSkills.length && top3.length}
				<section class="section">
					<h2 class="section-title">Skills Heat Map</h2>
					<table class="heatmap-table">
						<thead>
							<tr>
								<th>Skill</th>
								{#each top3 as c}
									<th>{c.name.split(' ')[0]}</th>
								{/each}
								<th>Coverage</th>
							</tr>
						</thead>
						<tbody>
							{#each requiredSkills as skill}
								{@const coverageCount = top3.filter(c => (c.skills_matched || []).map(/** @param {string} s */ s => s.toLowerCase()).includes(skill.toLowerCase())).length}
								{@const pct = Math.round(coverageCount / top3.length * 100)}
								<tr>
									<td class="skill-name">{skill}</td>
									{#each top3 as c}
										{@const has = (c.skills_matched || []).map(/** @param {string} s */ s => s.toLowerCase()).includes(skill.toLowerCase())}
										<td class="skill-cell">
											{#if has}
												<span class="dot-green">&#9679;</span>
											{:else}
												<span class="dot-red">&#9679;</span>
											{/if}
										</td>
									{/each}
									<td class="coverage-cell">
										<div class="mini-bar-track">
											<div class="mini-bar-fill" style="width:{pct}%; background:{pct >= 66 ? '#3a8a4f' : pct >= 33 ? 'var(--color-warning, #c98c2a)' : 'var(--color-error, #c4571a)'};"></div>
										</div>
										<span class="coverage-label">{coverageCount}/{top3.length}</span>
										{#if coverageCount <= 1}
											<span class="gap-alert">GAP</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</section>
			{/if}

			<!-- ====== 6. PIPELINE FLOW ====== -->
			<section class="section">
				<h2 class="section-title">Pipeline Flow</h2>
				<div class="pipeline-flow">
					{#each stageOrder as stage, i}
						{@const count = pipeline[stage] || 0}
						{@const pct = Math.round(count / pipelineTotal * 100)}
						{@const nextCount = i < stageOrder.length - 1 ? (pipeline[stageOrder[i + 1]] || 0) : 0}
						{@const conversion = count ? Math.round(nextCount / count * 100) : 0}
						<div class="funnel-row">
							<div class="funnel-label">{stageLabels[stage] || stage}</div>
							<div class="funnel-bar-track">
								<div class="funnel-bar-fill" style="width:{pct}%; background:{stageColors[stage]};"></div>
							</div>
							<div class="funnel-stats">
								<span class="funnel-count">{count}</span>
								<span class="funnel-pct">{pct}%</span>
								{#if i < stageOrder.length - 1 && count}
									<span class="funnel-conversion">&rarr; {conversion}%</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</section>

			<!-- ====== 7. COMPENSATION ====== -->
			<section class="section">
				<h2 class="section-title">Compensation</h2>
				{#if offers.length}
					<div class="offers-grid">
						{#each offers as offer}
							<div class="offer-card">
								<div class="offer-name">{offer.candidate_name || `Candidate #${offer.candidate_id}`}</div>
								<div class="offer-detail"><span class="offer-label">Salary</span><span class="offer-value">{offer.salary_currency || 'USD'} {Number(offer.salary_amount || 0).toLocaleString()}/{offer.salary_period || 'year'}</span></div>
								{#if offer.equity}<div class="offer-detail"><span class="offer-label">Equity</span><span class="offer-value">{offer.equity}</span></div>{/if}
								{#if offer.bonus}<div class="offer-detail"><span class="offer-label">Bonus</span><span class="offer-value">{offer.bonus}</span></div>{/if}
								{#if offer.start_date}<div class="offer-detail"><span class="offer-label">Start Date</span><span class="offer-value">{new Date(offer.start_date).toLocaleDateString()}</span></div>{/if}
								<div class="offer-status" style="background:{offer.status === 'accepted' ? '#3a8a4f' : offer.status === 'rejected' ? 'var(--color-error, #c4571a)' : 'var(--color-warning, #c98c2a)'}">{offer.status}</div>
							</div>
						{/each}
					</div>
				{:else}
					<div class="empty-state">No offers extended yet.</div>
				{/if}
			</section>

			<!-- ====== 8. RISK MATRIX ====== -->
			<section class="section">
				<h2 class="section-title">Risk Matrix</h2>
				{#if risks.length}
					<table class="risk-table">
						<thead>
							<tr><th>Risk</th><th>Severity</th><th>Status</th></tr>
						</thead>
						<tbody>
							{#each risks as risk}
								<tr>
									<td>{risk.desc}</td>
									<td class="risk-sev">
										{#if risk.severity === 'high'}
											<span class="sev-dot sev-high">&#9679;</span> HIGH
										{:else if risk.severity === 'medium'}
											<span class="sev-dot sev-medium">&#9679;</span> MEDIUM
										{:else}
											<span class="sev-dot sev-low">&#9679;</span> LOW
										{/if}
									</td>
									<td>{risk.status}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{:else}
					<div class="empty-state">No risks detected.</div>
				{/if}
			</section>

			<!-- ====== 8b. INTERVIEWER CALIBRATION ====== -->
			{#if evalCalibration.length > 0}
				<section class="section">
					<h2 class="section-title">Interviewer Calibration</h2>
					<table class="comparison-table">
						<thead>
							<tr>
								<th>Interviewer</th>
								<th>Avg Score</th>
								<th>Std Dev</th>
								<th>Reviews</th>
								<th>Harshness</th>
							</tr>
						</thead>
						<tbody>
							{#each evalCalibration as cal}
								<tr>
									<td style="font-weight: 700; text-align: left;">{cal.interviewer_name}</td>
									<td>{cal.avg_score?.toFixed?.(1) || '—'}</td>
									<td>{cal.std_dev?.toFixed?.(2) || '—'}</td>
									<td>{cal.scorecard_count}</td>
									<td style="font-weight: 700; color: {cal.harshness_index < 0.9 ? 'var(--color-error, #c4571a)' : cal.harshness_index > 1.1 ? '#3a8a4f' : 'var(--color-on-surface, #2c2c2c)'};">{cal.harshness_index?.toFixed?.(2) || '—'}x</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</section>
			{/if}

			<!-- ====== 9. ACTION ITEMS ====== -->
			<section class="section">
				<h2 class="section-title">Action Items</h2>
				<ol class="action-list">
					{#each actions as action, i}
						<li class="action-item">
							<span class="action-priority" class:priority-urgent={action.priority === 'urgent'} class:priority-high={action.priority === 'high'} class:priority-medium={action.priority === 'medium'}>
								{#if action.priority === 'urgent'}&#9679; URGENT{:else if action.priority === 'high'}&#9679; HIGH{:else}&#9679; MEDIUM{/if}
							</span>
							<span class="action-text">{action.text}</span>
						</li>
					{/each}
				</ol>
			</section>

			<!-- ====== 10. FOOTER ====== -->
			<div class="report-footer">
				Generated by <strong>City Agent Pulse</strong> &middot; {today} &middot; Confidential
			</div>
		</div>
	{/if}
</div>

<style>
	/* ===== BASE ===== */
	.report-page {
		min-height: 100vh;
		height: 100%;
		overflow-y: auto !important;
		background: #ffffff;
		color: #1a1a1a;
		font-family: 'Space Grotesk', sans-serif;
		line-height: 1.5;
	}
	:global(main), :global(.flex-1) {
		overflow: auto !important;
	}

	/* ===== HEADER BAR ===== */
	.report-header { padding: 12px 32px; border-bottom: 1px solid var(--color-border, #e8e6dd); background: var(--color-surface-bright, #fff); }
	.header-row { display: flex; align-items: center; justify-content: space-between; }
	.header-actions { display: flex; gap: 8px; }
	.back-link { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface, #2c2c2c); text-decoration: none; }
	.back-link:hover { text-decoration: underline; }
	.print-btn, .close-btn {
		font-family: 'Space Grotesk', sans-serif; font-size: 11px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.05em; padding: 6px 16px; cursor: pointer; border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px;
	}
	.print-btn { background: #3a8a4f; color: white; }
	.print-btn:hover { background: #2e7040; }
	.close-btn { background: transparent; color: var(--color-on-surface, #2c2c2c); }
	.close-btn:hover { background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff); }

	/* ===== LOADING / ERROR ===== */
	.report-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60vh; gap: 16px; color: var(--color-on-surface, #2c2c2c); }
	.report-loading p { font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
	.loading-spinner { width: 32px; height: 32px; border: 3px solid var(--color-border, #e8e6dd); border-top: 3px solid var(--color-on-surface, #2c2c2c); border-radius: 50%; animation: spin 0.8s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	.report-error { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60vh; gap: 8px; color: var(--color-on-surface, #2c2c2c); text-align: center; }
	.report-error h2 { font-size: 18px; font-weight: 900; text-transform: uppercase; margin: 0; }
	.report-error p { font-size: 13px; color: var(--color-on-surface-dim, #6f6e69); margin: 0; }

	/* ===== REPORT BODY ===== */
	.report-body { max-width: 900px; margin: 0 auto; padding: 0 32px 80px; font-size: 14px; }

	/* ===== 1. COVER HEADER ===== */
	.cover-header {
		background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff); padding: 48px 40px 36px; margin: 0 -32px;
		text-align: center; position: relative;
	}
	.cover-logo { font-size: 14px; font-weight: 900; letter-spacing: 0.3em; text-transform: uppercase; opacity: 0.6; }
	.cover-subtitle { font-size: 11px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; margin-top: 4px; opacity: 0.5; }
	.cover-divider { width: 48px; height: 2px; background: var(--color-surface-bright, #fff); margin: 20px auto; opacity: 0.3; }
	.cover-title { font-size: 32px; font-weight: 900; margin: 0; letter-spacing: -0.01em; line-height: 1.15; }
	.cover-meta { margin-top: 12px; font-size: 13px; font-weight: 500; opacity: 0.7; }
	.cover-dot { margin: 0 8px; }
	.cover-footer { margin-top: 24px; font-size: 11px; opacity: 0.4; display: flex; justify-content: center; gap: 24px; text-transform: uppercase; letter-spacing: 0.05em; }

	/* ===== SECTIONS ===== */
	.section { margin-top: 36px; padding-top: 28px; border-top: 1px solid #e8e8e0; }
	.section-title {
		font-size: 13px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.1em;
		color: var(--color-on-surface, #2c2c2c); margin: 0 0 20px; padding-bottom: 8px; border-bottom: 2px solid var(--color-on-surface, #2c2c2c);
	}

	/* ===== 2. EXECUTIVE SNAPSHOT ===== */
	.metrics-row { display: flex; gap: 24px; justify-content: center; flex-wrap: wrap; margin-bottom: 20px; }
	.metric-circle {
		text-align: center; width: 110px; padding: 16px 8px;
		border: 1px solid #e8e8e0; border-radius: 4px; background: #fafaf4;
	}
	.metric-number { font-size: 32px; font-weight: 900; color: var(--color-on-surface, #2c2c2c); line-height: 1; }
	.metric-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim, #6f6e69); margin-top: 4px; }
	.metric-dots { font-size: 10px; color: #3a8a4f; margin-top: 6px; letter-spacing: 2px; }

	.snapshot-stats { display: flex; gap: 32px; justify-content: center; margin-bottom: 16px; }
	.stat-item { text-align: center; }
	.stat-value { font-size: 20px; font-weight: 900; color: var(--color-on-surface, #2c2c2c); display: block; }
	.stat-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim, #6f6e69); }

	.verdict-box {
		display: flex; align-items: center; gap: 12px; padding: 14px 20px; margin-top: 16px;
		background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 4px;
	}
	.verdict-icon { font-size: 18px; font-weight: 900; color: #3a8a4f; }
	.verdict-text { font-size: 13px; color: #15803d; }
	.verdict-backup { display: block; font-size: 12px; opacity: 0.7; margin-top: 2px; }

	/* ===== 3. SCORECARDS ===== */
	.scorecard {
		border: 1px solid #e8e8e0; border-radius: 4px; padding: 20px 24px; margin-bottom: 16px;
		background: #ffffff;
	}
	.scorecard-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
	.scorecard-rank {
		font-size: 14px; font-weight: 900; color: var(--color-on-surface-dim, #6f6e69); min-width: 32px;
		text-align: center; border: 1px solid #e8e8e0; border-radius: 4px; padding: 4px 8px;
	}
	.scorecard-info { flex: 1; }
	.scorecard-name { font-size: 16px; font-weight: 900; }
	.scorecard-meta { font-size: 12px; color: #6b6b60; margin-top: 2px; }
	.scorecard-overall { font-size: 28px; font-weight: 900; }

	.score-bars { margin-bottom: 14px; }
	.score-bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
	.score-bar-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; width: 100px; color: #6b6b60; }
	.score-bar-track { flex: 1; height: 8px; background: #f0f0e8; border-radius: 4px; overflow: hidden; }
	.score-bar-fill { height: 100%; border-radius: 4px; transition: width 0.5s; }
	.score-bar-value { font-size: 11px; font-weight: 900; width: 36px; text-align: right; }

	.scorecard-badges { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
	.stage-badge {
		font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
		padding: 2px 10px; color: white; border-radius: 2px;
	}
	.interview-badge {
		font-size: 10px; font-weight: 600; padding: 2px 10px; background: #f0f0e8; color: #6b6b60; border-radius: 2px;
	}

	.scorecard-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 10px; }
	.scorecard-col { font-size: 12px; }
	.col-header { font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
	.col-green { color: #3a8a4f; }
	.col-red { color: var(--color-error, #c4571a); }
	.col-list { margin: 0; padding-left: 16px; }
	.col-list li { margin-bottom: 3px; line-height: 1.4; }
	.col-list .muted { color: var(--color-on-surface-dim, #6f6e69); }

	.notes-preview {
		font-size: 11px; color: #6b6b60; padding: 8px 12px; background: #fafaf4;
		border-radius: 3px; margin-top: 6px;
	}
	.notes-label { font-weight: 700; }

	/* Compact cards */
	.compact-header { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim, #6f6e69); margin: 20px 0 8px; }
	.compact-card {
		display: flex; align-items: center; gap: 12px; padding: 8px 12px;
		border: 1px solid #f0f0e8; border-radius: 3px; margin-bottom: 4px; font-size: 13px;
	}
	.compact-rank { font-weight: 900; color: var(--color-on-surface-dim, #6f6e69); min-width: 24px; }
	.compact-name { flex: 1; font-weight: 700; }
	.compact-score { font-weight: 900; min-width: 40px; text-align: right; }
	.compact-badge { font-size: 9px !important; padding: 1px 6px !important; }
	.compact-verdict { font-size: 10px; color: var(--color-on-surface-dim, #6f6e69); font-style: italic; }

	/* ===== 4. COMPARISON TABLE ===== */
	.comparison-table {
		width: 100%; border-collapse: collapse; font-size: 13px;
	}
	.comparison-table th, .comparison-table td {
		padding: 8px 14px; border: 1px solid #e8e8e0; text-align: center;
	}
	.comparison-table th {
		background: #fafaf4; font-size: 11px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; color: #6b6b60;
	}
	.comparison-table .row-label {
		text-align: left; font-weight: 700; font-size: 12px; text-transform: uppercase;
		letter-spacing: 0.03em; color: #6b6b60; background: #fafaf4;
	}
	.comparison-table .winner { font-weight: 900; color: #3a8a4f; background: #f0fdf4; }
	.verdict-row td { padding: 10px 14px; }
	.verdict-tag {
		font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
		padding: 2px 10px; border-radius: 2px; color: white;
	}
	.verdict-tag.green { background: #3a8a4f; }
	.verdict-tag.orange { background: var(--color-warning, #c98c2a); }
	.verdict-tag.gray { background: var(--color-on-surface-dim, #6f6e69); }

	/* ===== 5. SKILLS HEAT MAP ===== */
	.heatmap-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.heatmap-table th, .heatmap-table td { padding: 8px 12px; border: 1px solid #e8e8e0; text-align: center; }
	.heatmap-table th {
		background: #fafaf4; font-size: 11px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; color: #6b6b60;
	}
	.skill-name { text-align: left !important; font-weight: 600; }
	.skill-cell { font-size: 16px; }
	.dot-green { color: #3a8a4f; }
	.dot-red { color: var(--color-error, #c4571a); }
	.coverage-cell { display: flex; align-items: center; gap: 6px; justify-content: center; flex-wrap: nowrap; }
	.mini-bar-track { width: 48px; height: 6px; background: #f0f0e8; border-radius: 3px; overflow: hidden; flex-shrink: 0; }
	.mini-bar-fill { height: 100%; border-radius: 3px; }
	.coverage-label { font-size: 11px; font-weight: 700; color: #6b6b60; }
	.gap-alert {
		font-size: 9px; font-weight: 900; color: var(--color-error, #c4571a); background: #fef2f2;
		padding: 1px 5px; border-radius: 2px; text-transform: uppercase; letter-spacing: 0.05em;
	}

	/* ===== 6. PIPELINE FLOW ===== */
	.pipeline-flow { display: flex; flex-direction: column; gap: 6px; }
	.funnel-row { display: flex; align-items: center; gap: 12px; }
	.funnel-label { width: 130px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: #6b6b60; text-align: right; }
	.funnel-bar-track { flex: 1; height: 22px; background: #f0f0e8; border-radius: 3px; overflow: hidden; }
	.funnel-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; min-width: 2px; }
	.funnel-stats { display: flex; gap: 8px; min-width: 100px; font-size: 12px; }
	.funnel-count { font-weight: 900; }
	.funnel-pct { color: var(--color-on-surface-dim, #6f6e69); }
	.funnel-conversion { color: #006f7c; font-weight: 600; }

	/* ===== 7. COMPENSATION ===== */
	.offers-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
	.offer-card { border: 1px solid #e8e8e0; border-radius: 4px; padding: 16px; }
	.offer-name { font-size: 14px; font-weight: 900; margin-bottom: 10px; }
	.offer-detail { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }
	.offer-label { color: var(--color-on-surface-dim, #6f6e69); font-weight: 600; text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; }
	.offer-value { font-weight: 700; }
	.offer-status {
		display: inline-block; margin-top: 10px; font-size: 10px; font-weight: 700;
		text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 10px; color: white; border-radius: 2px;
	}

	.empty-state { font-size: 13px; color: var(--color-on-surface-dim, #6f6e69); padding: 20px; text-align: center; background: #fafaf4; border-radius: 4px; }

	/* ===== 8. RISK MATRIX ===== */
	.risk-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.risk-table th, .risk-table td { padding: 10px 14px; border: 1px solid #e8e8e0; text-align: left; }
	.risk-table th {
		background: #fafaf4; font-size: 11px; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; color: #6b6b60;
	}
	.risk-sev { font-size: 11px; font-weight: 700; text-transform: uppercase; white-space: nowrap; }
	.sev-dot { font-size: 14px; vertical-align: middle; margin-right: 4px; }
	.sev-high { color: var(--color-error, #c4571a); }
	.sev-medium { color: var(--color-warning, #c98c2a); }
	.sev-low { color: #3a8a4f; }

	/* ===== 9. ACTION ITEMS ===== */
	.action-list { margin: 0; padding-left: 20px; }
	.action-item { margin-bottom: 8px; display: flex; align-items: flex-start; gap: 8px; font-size: 13px; list-style: decimal; }
	.action-priority {
		font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;
		padding: 1px 8px; border-radius: 2px; white-space: nowrap; flex-shrink: 0;
	}
	.priority-urgent { background: #fef2f2; color: var(--color-error, #c4571a); }
	.priority-high { background: #fffbeb; color: #d97706; }
	.priority-medium { background: #f0fdf4; color: #3a8a4f; }
	.action-text { flex: 1; }

	/* ===== 10. FOOTER ===== */
	.report-footer {
		margin-top: 48px; padding: 24px 0; border-top: 1px solid #e8e8e0;
		text-align: center; font-size: 11px; color: var(--color-on-surface-dim, #6f6e69); letter-spacing: 0.03em;
	}

	/* ===== PRINT ===== */
	@media print {
		.no-print { display: none !important; }
		.report-page { background: white; }
		.report-body { max-width: 100%; padding: 0; font-size: 11px; }
		.cover-header { padding: 32px 24px 24px; margin: 0; break-after: avoid; }
		.cover-title { font-size: 24px; }
		.section { margin-top: 20px; padding-top: 16px; break-inside: avoid; }
		.section-title { font-size: 11px; margin-bottom: 12px; }
		.scorecard { break-inside: avoid; padding: 12px 16px; margin-bottom: 10px; }
		.metric-circle { padding: 10px 6px; }
		.metric-number { font-size: 24px; }
		.comparison-table, .heatmap-table, .risk-table { font-size: 10px; }
		.comparison-table th, .comparison-table td,
		.heatmap-table th, .heatmap-table td,
		.risk-table th, .risk-table td { padding: 5px 8px; }
		.funnel-bar-track { height: 16px; }
		.verdict-box { break-inside: avoid; }
		.report-footer { margin-top: 24px; }
	}
</style>
