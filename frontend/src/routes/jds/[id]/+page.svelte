<script>
	/** JD Detail — Full page view */
	import { page } from '$app/state';
	import { apiJson, getToken } from '$lib/api';
	import CompetencyPanel from '$lib/CompetencyPanel.svelte';
	import Lock from '@lucide/svelte/icons/lock';
	import Unlock from '@lucide/svelte/icons/unlock';

	let jd = $state(null);
	let loading = $state(true);
	let enhancing = $state(false);
	let editing = $state(false);
	let editText = $state('');
	// Structured form state
	let editForm = $state({
		title: '', department: '', seniority_level: '', employment_type: '',
		location: '', work_mode: '', job_code: '', business_sector: '',
		grading: '', reporting_to: '', travel_requirement: '',
		min_experience_years: 0, education_level: '',
		jd_text: '',
		required_skills: '', nice_to_have_skills: '',
		industry_keywords: '', required_certifications: '', tags: ''
	});
	const SENIORITY_OPTS = ['', 'intern', 'junior', 'mid', 'senior', 'lead', 'principal', 'manager', 'director', 'vp', 'c-level'];
	const EMPLOYMENT_OPTS = ['full-time', 'part-time', 'contract', 'temporary', 'internship'];
	const WORKMODE_OPTS = ['', 'on-site', 'hybrid', 'remote'];
	const EDUCATION_OPTS = ['', 'high-school', 'diploma', 'bachelor', 'master', 'phd'];

	function openEdit() {
		if (!jd) return;
		const arrToCsv = (a) => Array.isArray(a) ? a.join(', ') : (a || '');
		editForm = {
			title: jd.title || '',
			department: jd.department || '',
			seniority_level: jd.seniority_level || '',
			employment_type: jd.employment_type || 'full-time',
			location: jd.location || '',
			work_mode: jd.work_mode || '',
			job_code: jd.job_code || '',
			business_sector: jd.business_sector || '',
			grading: jd.grading || '',
			reporting_to: jd.reporting_to || '',
			travel_requirement: jd.travel_requirement || '',
			min_experience_years: jd.min_experience_years ?? 0,
			education_level: jd.education_level || '',
			jd_text: jd.jd_text || '',
			required_skills: arrToCsv(jd.required_skills),
			nice_to_have_skills: arrToCsv(jd.nice_to_have_skills),
			industry_keywords: arrToCsv(jd.industry_keywords),
			required_certifications: arrToCsv(jd.required_certifications),
			tags: arrToCsv(jd.tags)
		};
		editText = jd.jd_text || '';
		editing = true;
	}
	let positions = $state([]);
	let aiAvailable = $state(null);
	let enhanceError = $state('');

	// Weights state
	let weights = $state({ skills: 40, experience: 25, industry: 15, education: 10, certifications: 10, culture: 0 });
	let scoringProfile = $state('engineering');
	let knockoutThreshold = $state(0);
	let weightsDirty = $state(false);
	let presets = $state({});

	async function loadPresets() {
		try {
			const d = await apiJson('/jds/meta/presets');
			presets = d.presets || {};
		} catch {}
	}
	function syncWeightsFromJd() {
		if (!jd) return;
		weights = {
			skills: Number(jd.weight_skills ?? 40),
			experience: Number(jd.weight_experience ?? 25),
			industry: Number(jd.weight_industry ?? 15),
			education: Number(jd.weight_education ?? 10),
			certifications: Number(jd.weight_certifications ?? 10),
			culture: Number(jd.weight_culture ?? 0),
		};
		scoringProfile = jd.scoring_profile || 'engineering';
		knockoutThreshold = Number(jd.knockout_threshold ?? 0);
		weightsDirty = false;
	}
	function totalWeight() {
		return Math.round(weights.skills + weights.experience + weights.industry + weights.education + weights.certifications + weights.culture);
	}
	function applyPreset(name) {
		const p = presets[name];
		if (!p) return;
		weights = {
			skills: p.weight_skills, experience: p.weight_experience,
			industry: p.weight_industry, education: p.weight_education,
			certifications: p.weight_certifications, culture: p.weight_culture,
		};
		scoringProfile = name;
		weightsDirty = true;
	}
	async function toggleJdLock() {
		try {
			await apiJson(`/jds/${jdId}/lock`, {
				method: 'PATCH',
				body: JSON.stringify({ weights_locked: !jd.weights_locked }),
			});
			cliEvent('success', jd.weights_locked ? 'Unlocked' : 'Locked');
			await loadJd();
		} catch (e) { cliEvent('error', `Lock failed: ${e.message}`); }
	}
	async function toggleDimLock(dim) {
		const current = jd.weights_locked_dims || [];
		const next = current.includes(dim) ? current.filter(d => d !== dim) : [...current, dim];
		try {
			await apiJson(`/jds/${jdId}/lock`, {
				method: 'PATCH',
				body: JSON.stringify({ weights_locked_dims: next }),
			});
			await loadJd();
		} catch (e) { cliEvent('error', e.message); }
	}
	async function saveWeights(applyToOpen = false) {
		try {
			const body = {
				weight_skills: weights.skills,
				weight_experience: weights.experience,
				weight_industry: weights.industry,
				weight_education: weights.education,
				weight_certifications: weights.certifications,
				weight_culture: weights.culture,
				knockout_threshold: knockoutThreshold,
				scoring_profile: scoringProfile,
				normalize: true,
				apply_to_open_positions: applyToOpen,
			};
			await apiJson(`/jds/${jdId}/weights`, { method: 'PATCH', body: JSON.stringify(body) });
			cliEvent('success', applyToOpen ? 'Weights saved + synced to open positions' : 'Weights saved');
			await loadJd();
			syncWeightsFromJd();
		} catch (e) {
			cliEvent('error', `Weights save failed: ${e.message}`);
		}
	}

	const jdId = $derived(page.params.id);

	$effect(() => {
		if (jdId) { loadJd(); loadPositions(); checkAiStatus(); }
	});

	async function checkAiStatus() {
		try {
			const data = await apiJson('/ai-status');
			aiAvailable = data.available;
		} catch (e) { aiAvailable = false; }
	}

	async function loadJd() {
		loading = true;
		try {
			jd = await apiJson(`/jds/${jdId}`);
			syncWeightsFromJd();
			if (Object.keys(presets).length === 0) loadPresets();
		} catch (e) { console.error(e); }
		loading = false;
	}

	async function loadPositions() {
		try {
			const data = await apiJson('/positions');
			positions = (data.positions || []).filter(p => p.jd_text && p.status === 'active');
		} catch (e) { console.error(e); }
	}

	let enriching = $state(false);
	async function enrichFields() {
		enriching = true;
		try {
			const r = await apiJson(`/jds/${jdId}/enrich`, { method: 'POST' });
			cliEvent('success', `Enriched: ${(r.updated || []).join(', ') || 'no changes'}`);
			await loadJd();
		} catch (e) {
			cliEvent('error', e?.message || 'Enrich failed');
			alert(e?.message || 'Enrich failed');
		} finally {
			enriching = false;
		}
	}

	async function enhanceJd() {
		enhanceError = '';
		if (aiAvailable === false) {
			enhanceError = 'AI features require OPENROUTER_API_KEY. Set it in your environment and restart the backend.';
			cliEvent('error', enhanceError);
			return;
		}
		enhancing = true;
		try {
			const res = await fetch(`/api/jds/${jdId}/enhance`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', ...(await import('$lib/api')).authHeaders() },
			});
			const data = await res.json();
			if (!res.ok) {
				enhanceError = data.detail || 'Enhancement failed';
				cliEvent('error', enhanceError);
				enhancing = false;
				return;
			}
			jd = await apiJson(`/jds/${jdId}`);
			enhanceError = '';
			cliEvent('success', `Enhanced — DEI: ${data.compliance?.dei_score || '?'}/100, Complete: ${data.compliance?.completeness || '?'}%`);
		} catch (e) {
			enhanceError = e.message;
			cliEvent('error', `Enhance failed: ${e.message}`);
		}
		enhancing = false;
	}

	async function saveEdit() {
		try {
			const csvToArr = (s) => (s || '').split(',').map(x => x.trim()).filter(Boolean);
			const payload = {
				title: editForm.title,
				department: editForm.department,
				seniority_level: editForm.seniority_level,
				employment_type: editForm.employment_type,
				location: editForm.location,
				work_mode: editForm.work_mode,
				job_code: editForm.job_code,
				business_sector: editForm.business_sector,
				grading: editForm.grading,
				reporting_to: editForm.reporting_to,
				travel_requirement: editForm.travel_requirement,
				min_experience_years: Number(editForm.min_experience_years) || 0,
				education_level: editForm.education_level,
				jd_text: editForm.jd_text,
				required_skills: csvToArr(editForm.required_skills),
				nice_to_have_skills: csvToArr(editForm.nice_to_have_skills),
				industry_keywords: csvToArr(editForm.industry_keywords),
				required_certifications: csvToArr(editForm.required_certifications),
				tags: csvToArr(editForm.tags)
			};
			await apiJson(`/jds/${jdId}`, { method: 'PATCH', body: JSON.stringify(payload) });
			editing = false;
			await loadJd();
			cliEvent('success', 'JD updated');
		} catch (e) { cliEvent('error', `Save failed: ${e.message}`); }
	}

	function removeChip(field, idx) {
		const arr = (editForm[field] || '').split(',').map(x => x.trim()).filter(Boolean);
		arr.splice(idx, 1);
		editForm[field] = arr.join(', ');
	}

	let reformatting = $state(false);
	let showRaw = $state(false);
	async function reformatNow(force = false) {
		reformatting = true;
		try {
			const r = await apiJson(`/jds/${jdId}/reformat${force ? '?force=true' : ''}`, { method: 'POST' });
			if (r.skipped) { cliEvent('info', `Reformat skipped: ${r.reason}`); }
			else { cliEvent('success', `JD reformatted (score ${(r.score ?? 0).toFixed(2)})`); }
			await loadJd();
		} catch (e) { cliEvent('error', `Reformat failed: ${e.message}`); }
		finally { reformatting = false; }
	}
	async function downloadAuth(path, filename) {
		try {
			const r = await fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } });
			if (!r.ok) throw new Error(`HTTP ${r.status}`);
			const blob = await r.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url; a.download = filename; document.body.appendChild(a); a.click();
			a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
		} catch (e) { cliEvent('error', `Download failed: ${e.message}`); }
	}

	async function revertRaw() {
		if (!confirm('Restore original (pre-reformat) text? Current AI-formatted version will be lost.')) return;
		try {
			await apiJson(`/jds/${jdId}/revert-raw`, { method: 'POST' });
			cliEvent('success', 'JD reverted to raw original');
			showRaw = false;
			await loadJd();
		} catch (e) { cliEvent('error', `Revert failed: ${e.message}`); }
	}

	async function duplicateJd() {
		try {
			const data = await apiJson(`/jds/${jdId}/duplicate`, { method: 'POST' });
			cliEvent('success', 'JD duplicated');
			window.location.href = `/jds/${data.jd_id}`;
		} catch (e) { cliEvent('error', `Duplicate failed: ${e.message}`); }
	}

	async function useForPosition(slug) {
		try {
			await apiJson(`/jds/${jdId}/use`, {
				method: 'POST',
				body: JSON.stringify({ position_slug: slug }),
			});
			cliEvent('success', `JD applied to ${slug}`);
			await loadJd();
		} catch (e) { cliEvent('error', `Failed: ${e.message}`); }
	}

	async function archiveJd() {
		try {
			await apiJson(`/jds/${jdId}`, { method: 'DELETE' });
			cliEvent('success', 'JD archived');
			window.location.href = '/jds';
		} catch (e) { cliEvent('error', `Archive failed: ${e.message}`); }
	}

	function cliEvent(type, text) {
		window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type, text } }));
	}

	function formatJdText(text) {
		if (!text) return '';
		const TABLE_PLACEHOLDER = (idx) => ` T${idx} `;
		const tables = [];
		const lines = text.split('\n');
		const out = [];
		let i = 0;
		// Pad lines containing pipes but missing leading/trailing pipes (legacy malformed tables)
		const padPipes = (ln) => {
			if (!/\|/.test(ln)) return ln;
			let s = ln.trim();
			if (!s.startsWith('|')) s = '| ' + s;
			if (!s.endsWith('|')) s = s + ' |';
			return s;
		};
		const isSeparator = (ln) => /^\s*\|?[\s\-:|]+\|?\s*$/.test(ln) && /-/.test(ln) && /\|/.test(ln);

		while (i < lines.length) {
			const rawLine = lines[i];
			const line = padPipes(rawLine);
			// Markdown table: header row + |---| separator (tolerate missing edge pipes)
			if (/\|/.test(line) && i + 1 < lines.length && isSeparator(lines[i + 1])) {
				const header = line.split('|').slice(1, -1).map(c => c.trim());
				i += 2;
				const rows = [];
				while (i < lines.length && /\|/.test(lines[i]) && !isSeparator(lines[i])) {
					rows.push(padPipes(lines[i]).split('|').slice(1, -1).map(c => c.trim()));
					i++;
				}
				let html = '<div class="jd-table-wrap"><table class="jd-table">';
				html += '<thead><tr>';
				header.forEach(h => { html += `<th>${h}</th>`; });
				html += '</tr></thead><tbody>';
				rows.forEach((r, rIdx) => {
					html += `<tr class="${rIdx % 2 ? 'alt' : ''}">`;
					r.forEach((c, cIdx) => {
						const inline = c
							.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
							.replace(/`([^`]+)`/g, '<code>$1</code>');
						html += `<td class="${cIdx === 0 ? 'first' : ''}">${inline}</td>`;
					});
					html += '</tr>';
				});
				html += '</tbody></table></div>';
				tables.push(html);
				out.push(TABLE_PLACEHOLDER(tables.length - 1));
				continue;
			}
			out.push(line);
			i++;
		}
		let body = out.join('\n');

		// Strip leading H1 if present (already shown in header)
		body = body.replace(/^#\s+.*$/m, '').trim();

		// Block: headings
		body = body
			.replace(/^####\s+(.+)$/gm, '<h4 class="jd-h4">$1</h4>')
			.replace(/^###\s+(.+)$/gm,  '<h3 class="jd-h3">$1</h3>')
			.replace(/^##\s+(.+)$/gm,   '<h2 class="jd-h2">$1</h2>')
			.replace(/^#\s+(.+)$/gm,    '<h1 class="jd-h1">$1</h1>');

		// Horizontal rule
		body = body.replace(/^\s*---+\s*$/gm, '<hr class="jd-hr"/>');

		// Inline: bold, italic, code
		body = body
			.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
			.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
			.replace(/`([^`\n]+)`/g, '<code>$1</code>');

		// Lists — group consecutive bullet lines into <ul>
		const blockLines = body.split('\n');
		const finalLines = [];
		let inList = false;
		for (const ln of blockLines) {
			const m = ln.match(/^\s*[•\-\*]\s+(.+)$/);
			if (m) {
				if (!inList) { finalLines.push('<ul class="jd-ul">'); inList = true; }
				finalLines.push(`<li>${m[1]}</li>`);
			} else {
				if (inList) { finalLines.push('</ul>'); inList = false; }
				finalLines.push(ln);
			}
		}
		if (inList) finalLines.push('</ul>');

		// Wrap plain paragraphs separated by blank lines
		const joined = finalLines.join('\n');
		const blocks = joined.split(/\n{2,}/).map(b => {
			const t = b.trim();
			if (!t) return '';
			if (t.startsWith('<')) return t;
			return `<p class="jd-p">${t.replace(/\n/g, '<br/>')}</p>`;
		}).join('\n');

		// Restore tables
		return blocks.replace(/ T(\d+) /g, (_, n) => tables[+n]);
	}

	let showUseDropdown = $state(false);

	function complianceColor(score) {
		if (!score && score !== 0) return 'var(--color-on-surface-dim)';
		if (score >= 80) return 'var(--color-primary)';
		if (score >= 50) return 'var(--color-warning)';
		return 'var(--color-error)';
	}
</script>

{#if loading}
	<div class="h-full overflow-y-auto p-6" style="max-width: 1100px; margin: 0 auto;">
		<div class="skeleton" style="height: 24px; width: 120px; margin-bottom: 20px;"></div>
		<div class="skeleton" style="height: 140px; margin-bottom: 20px;"></div>
		<div class="skeleton" style="height: 60px; margin-bottom: 20px;"></div>
		<div class="flex gap-4">
			<div class="skeleton" style="flex: 6; height: 400px;"></div>
			<div class="skeleton" style="flex: 4; height: 400px;"></div>
		</div>
	</div>
{:else if !jd}
	<div class="flex items-center justify-center h-full">
		<div class="text-center">
			<span class="material-symbols-outlined" style="font-size: 48px; color: var(--color-on-surface-dim);">error</span>
			<p style="font-size: 14px; font-weight: 900; text-transform: uppercase; margin-top: 12px;">JD Not Found</p>
			<a href="/jds" class="send-btn mt-4" style="display: inline-block; text-decoration: none;">← Back to Job Pool</a>
		</div>
	</div>
{:else}
	<div class="h-full overflow-y-auto">
		<div style="max-width: 1600px; margin: 0 auto; padding: 24px;">

			<!-- Back -->
			<a href="/jds" style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-on-surface-dim); text-decoration: none; display: inline-flex; align-items: center; gap: 4px; margin-bottom: 16px;">
				<span class="material-symbols-outlined" style="font-size: 16px;">arrow_back</span> Back to Job Pool
			</a>

			<!-- Hero Header -->
			<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-on-surface); color: var(--color-surface); padding: 24px 28px; margin-bottom: 20px;">
				<div class="flex items-start justify-between">
					<div>
						<div class="flex items-center gap-3 mb-2">
							<span class="material-symbols-outlined" style="font-size: 28px;">description</span>
							<h1 style="font-size: 24px; font-weight: 900; text-transform: uppercase; letter-spacing: -0.02em;">{jd.title}</h1>
						</div>
						<div class="flex items-center gap-2 flex-wrap" style="font-size: 12px; opacity: 0.8;">
							<span>{jd.department || 'No department'}</span>
							<span>·</span>
							<span style="text-transform: capitalize;">{jd.seniority_level || 'Any level'}</span>
							<span>·</span>
							<span>{jd.employment_type || 'Full-time'}</span>
						</div>
					</div>
					<div class="flex gap-2 flex-shrink-0 flex-wrap">
						<button onclick={enrichFields} disabled={enriching}
							style="background: #00fc40; color: #383832; border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;">
							{enriching ? 'Enriching...' : '✦ Enrich Fields'}
						</button>
						<button onclick={enhanceJd} disabled={enhancing}
							style="background: var(--color-primary-container); color: var(--color-on-surface); border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;">
							{enhancing ? 'Enhancing...' : '✦ AI Enhance'}
						</button>
						<button onclick={() => downloadAuth(`/api/jds/${jdId}/export.docx`, `jd-${jdId}.docx`)}
							style="background: transparent; color: var(--color-surface); border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em; display: inline-flex; align-items: center; gap: 4px;">
							⬇ WORD
						</button>
						<button onclick={() => downloadAuth(`/api/jds/${jdId}/export.xlsx`, `jd-${jdId}.xlsx`)}
							style="background: transparent; color: var(--color-surface); border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em; display: inline-flex; align-items: center; gap: 4px;">
							⬇ EXCEL
						</button>
						<button onclick={() => reformatNow(false)} disabled={reformatting}
							title="Restructure layout with AI (preserves wording)"
							style="background: transparent; color: var(--color-surface); border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;">
							{reformatting ? '...' : '✦ Reformat'}
						</button>
						{#if jd.jd_text_raw}
							<button onclick={revertRaw}
								title="Restore original pre-reformat text"
								style="background: transparent; color: var(--color-surface); border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;">
								↶ Revert raw
							</button>
						{/if}
						<button onclick={openEdit}
							style="background: transparent; color: var(--color-surface); border: 2px solid var(--color-surface); padding: 6px 14px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;">
							Edit
						</button>
					</div>
				</div>

				<!-- Status badges + stats -->
				<div class="flex gap-2 mt-3 flex-wrap items-center">
					<span style="padding: 2px 10px; border: 1px solid rgba(254,255,214,0.4); font-size: 10px; font-weight: 700; text-transform: uppercase;">{jd.status || 'active'}</span>
					{#if jd.jd_enhanced}
						<span style="padding: 2px 10px; background: var(--color-primary); color: white; font-size: 10px; font-weight: 700; text-transform: uppercase;">AI Enhanced</span>
					{/if}
					{#if jd.jd_text_source === 'ai_reformatted'}
						<span title={jd.reformat_quality_score ? `Score ${jd.reformat_quality_score.toFixed(2)}` : ''}
							style="padding: 2px 10px; background: var(--color-accent, #c96342); color: white; font-size: 10px; font-weight: 700; text-transform: uppercase;">✦ Auto-formatted</span>
					{/if}
					{#if jd.jd_text}
						<span style="padding: 2px 10px; border: 1px solid rgba(254,255,214,0.3); font-size: 9px; font-weight: 700; opacity: 0.7;">
							{jd.jd_text.split(/\s+/).length} words · {jd.jd_text.length} chars · {jd.jd_text.split('\n').filter(l => l.trim()).length} lines
						</span>
					{/if}
					{#if jd.used_count > 0}
						<span style="padding: 2px 10px; border: 1px solid rgba(254,255,214,0.4); font-size: 10px; font-weight: 700;">Used {jd.used_count}x</span>
					{/if}
				</div>
			</div>

			<!-- KPI Row -->
			<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5 section-animate">
				{#each [
					{ label: 'Department', value: jd.department || '—', icon: 'business' },
					{ label: 'Seniority', value: (jd.seniority_level || '—'), icon: 'trending_up' },
					{ label: 'Type', value: jd.employment_type || 'Full-time', icon: 'schedule' },
					{ label: 'Min Experience', value: `${jd.min_experience_years || 0} years`, icon: 'work_history' },
					{ label: 'Used In', value: `${jd.used_count || 0} position${(jd.used_count || 0) !== 1 ? 's' : ''}`, icon: 'link' },
				] as kpi}
					<div class="ink-border p-3" style="background: var(--color-surface-bright);">
						<div class="flex items-center gap-2 mb-1">
							<span class="material-symbols-outlined" style="font-size: 14px; color: var(--color-on-surface-dim);">{kpi.icon}</span>
							<span style="font-size: 8px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-on-surface-dim);">{kpi.label}</span>
						</div>
						<div style="font-size: 15px; font-weight: 900; text-transform: capitalize;">{kpi.value}</div>
					</div>
				{/each}
			</div>

			<!-- ✦ SCORING WEIGHTS — top placement -->
			<div class="ink-border stamp-shadow mb-4" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center justify-between">
					<span style="display:inline-flex; align-items:center; gap:6px;">✦ Scoring Weights {#if jd?.weights_locked}<Lock size={12} /> LOCKED{/if}</span>
					<div style="display: flex; gap: 8px; align-items: center;">
					<button onclick={toggleJdLock}
						style="background: {jd?.weights_locked ? 'var(--color-warning, #ff9d00)' : 'transparent'}; color: var(--color-surface); border: 1px solid var(--color-surface); padding: 3px 10px; font-size: 10px; font-weight: 900; cursor: pointer; text-transform: uppercase;">
						{#if jd?.weights_locked}<Lock size={11} /> Unlock{:else}<Unlock size={11} /> Lock to Positions{/if}
					</button>
					<select bind:value={scoringProfile} onchange={() => applyPreset(scoringProfile)}
						style="font-size: 11px; padding: 3px 8px; border: 1px solid var(--color-surface); background: var(--color-surface); color: var(--color-on-surface); font-weight: 700; text-transform: uppercase;">
						<option value="engineering">engineering</option>
						<option value="sales">sales</option>
						<option value="design">design</option>
						<option value="product">product</option>
						<option value="marketing">marketing</option>
						<option value="compliance">compliance</option>
						<option value="healthcare">healthcare</option>
						<option value="finance">finance</option>
						<option value="custom">custom</option>
					</select>
					</div>
				</div>
				<div style="padding: 16px 24px;">
					<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
						{#each [
							{key:'skills',label:'Skills'},
							{key:'experience',label:'Experience'},
							{key:'industry',label:'Industry'},
							{key:'education',label:'Education'},
							{key:'certifications',label:'Certifications'},
							{key:'culture',label:'Culture Fit'},
						] as w}
							<div>
								<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
									<span style="font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em;">{w.label}</span>
									<input type="number" min="0" max="100" step="1"
										bind:value={weights[w.key]}
										oninput={() => { weightsDirty = true; scoringProfile = 'custom'; }}
										style="width: 60px; border: 2px solid var(--color-on-surface); padding: 3px 6px; font-size: 12px; font-weight: 900; text-align: center; background: white;" />
								</div>
								<div style="height: 12px; background: var(--color-surface-highest); border: 1px solid var(--color-on-surface);">
									<div style="height: 100%; width: {Math.min(100, weights[w.key])}%; background: var(--color-primary); transition: width 0.15s ease;"></div>
								</div>
							</div>
						{/each}
					</div>
					<div style="border-top: 2px dashed var(--color-on-surface); margin-top: 14px; padding-top: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
						<div style="display: flex; align-items: center; gap: 12px;">
							<span style="font-size: 12px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase;">Total</span>
							<span style="font-size: 14px; font-weight: 900; color: {totalWeight() === 100 ? 'var(--color-primary)' : 'var(--color-warning, #ff9d00)'};">
								{totalWeight()}% {totalWeight() === 100 ? '✓' : '— normalize on save'}
							</span>
							<span style="margin-left: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase;">Knockout</span>
							<input type="number" min="0" max="100" bind:value={knockoutThreshold}
								oninput={() => weightsDirty = true}
								style="width: 60px; border: 2px solid var(--color-on-surface); padding: 3px 6px; font-size: 11px; text-align: center;" />
							<span style="font-size: 10px; opacity: 0.7;">% min</span>
						</div>
						<div style="display: flex; gap: 8px;">
							<button onclick={() => saveWeights(false)}
								style="background: var(--color-primary); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 6px 16px; font-size: 11px; font-weight: 900; cursor: pointer; text-transform: uppercase;"
								disabled={!weightsDirty}>SAVE</button>
							<button onclick={() => saveWeights(true)}
								style="background: var(--color-surface-bright); color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 6px 16px; font-size: 11px; font-weight: 700; cursor: pointer; text-transform: uppercase;"
								disabled={!weightsDirty}>Apply to Open Positions</button>
							<button onclick={syncWeightsFromJd}
								style="background: transparent; color: var(--color-on-surface); border: 2px solid var(--color-on-surface); padding: 6px 16px; font-size: 11px; font-weight: 700; cursor: pointer; text-transform: uppercase;"
								disabled={!weightsDirty}>Reset</button>
						</div>
					</div>
				</div>
			</div>

			<!-- ✦ COMPETENCIES (KF4D) -->
			<CompetencyPanel
				listUrl={`/jds/${jdId}/competencies`}
				saveUrl={`/jds/${jdId}/competencies`}
				autoExtractUrl={`/jds/${jdId}/competencies/auto-extract`}
				title="Competencies (KF4D)"
			/>

			<!-- Full-width JD body, sidebar moves below -->
			<div style="display: block;">
				<!-- JD Content full width -->
				<div style="width: 100%; min-width: 0;">

					{#if editing}
						<!-- Edit Mode — structured form -->
						<div class="ink-border animate-fade-up" style="background: var(--color-surface-bright); border-radius: 0;">
							<div class="dark-title-bar flex items-center justify-between" style="border-radius: 0;">
								<span>Edit Job Description</span>
								<div class="flex gap-2">
									<button onclick={() => editing = false} class="jd-btn-cancel">Cancel</button>
									<button onclick={saveEdit} class="jd-btn-save">Save changes</button>
								</div>
							</div>

							<div class="jd-edit-form">
								<!-- Basics -->
								<div class="jd-form-section">
									<div class="jd-form-section-title">Basics</div>
									<div class="jd-grid-2">
										<label class="jd-field jd-field-full"><span>Job title</span>
											<input type="text" bind:value={editForm.title} placeholder="e.g. Senior Backend Engineer" /></label>
										<label class="jd-field"><span>Department</span>
											<input type="text" bind:value={editForm.department} placeholder="Engineering" /></label>
										<label class="jd-field"><span>Seniority</span>
											<select bind:value={editForm.seniority_level}>
												{#each SENIORITY_OPTS as opt}<option value={opt}>{opt || '—'}</option>{/each}
											</select></label>
										<label class="jd-field"><span>Employment type</span>
											<select bind:value={editForm.employment_type}>
												{#each EMPLOYMENT_OPTS as opt}<option value={opt}>{opt}</option>{/each}
											</select></label>
										<label class="jd-field"><span>Work mode</span>
											<select bind:value={editForm.work_mode}>
												{#each WORKMODE_OPTS as opt}<option value={opt}>{opt || '—'}</option>{/each}
											</select></label>
										<label class="jd-field"><span>Location</span>
											<input type="text" bind:value={editForm.location} placeholder="Yangon, Myanmar" /></label>
										<label class="jd-field"><span>Min experience (yrs)</span>
											<input type="number" min="0" bind:value={editForm.min_experience_years} /></label>
										<label class="jd-field"><span>Education level</span>
											<select bind:value={editForm.education_level}>
												{#each EDUCATION_OPTS as opt}<option value={opt}>{opt || '—'}</option>{/each}
											</select></label>
										<label class="jd-field"><span>Reporting to</span>
											<input type="text" bind:value={editForm.reporting_to} placeholder="Engineering Manager" /></label>
										<label class="jd-field"><span>Travel</span>
											<input type="text" bind:value={editForm.travel_requirement} placeholder="None / 10% / Frequent" /></label>
									</div>
								</div>

								<!-- Corporate template -->
								<div class="jd-form-section">
									<div class="jd-form-section-title">Corporate fields</div>
									<div class="jd-grid-2">
										<label class="jd-field"><span>Job code</span>
											<input type="text" bind:value={editForm.job_code} placeholder="ENG-BE-002" /></label>
										<label class="jd-field"><span>Business sector</span>
											<input type="text" bind:value={editForm.business_sector} placeholder="Technology" /></label>
										<label class="jd-field"><span>Grading</span>
											<input type="text" bind:value={editForm.grading} placeholder="L5 / Band 4" /></label>
									</div>
								</div>

								<!-- Skills + tags -->
								<div class="jd-form-section">
									<div class="jd-form-section-title">Skills, certs, tags</div>
									{#each [
										{f:'required_skills', label:'Required skills', help:'Comma-separated. Press Enter or type comma to add.'},
										{f:'nice_to_have_skills', label:'Nice to have', help:''},
										{f:'industry_keywords', label:'Industry keywords', help:''},
										{f:'required_certifications', label:'Certifications', help:''},
										{f:'tags', label:'Tags', help:''}
									] as fld}
										<label class="jd-field jd-field-full">
											<span>{fld.label}</span>
											<input type="text" bind:value={editForm[fld.f]} placeholder="python, postgres, fastapi" />
											{#if editForm[fld.f]}
												<div class="jd-chips">
													{#each editForm[fld.f].split(',').map(x => x.trim()).filter(Boolean) as chip, idx}
														<span class="jd-chip">{chip}<button type="button" onclick={() => removeChip(fld.f, idx)} aria-label="Remove">×</button></span>
													{/each}
												</div>
											{/if}
											{#if fld.help}<small class="jd-help">{fld.help}</small>{/if}
										</label>
									{/each}
								</div>

								<!-- Body markdown -->
								<div class="jd-form-section">
									<div class="jd-form-section-title">Job description body (markdown)</div>
									<textarea bind:value={editForm.jd_text} rows="20" class="jd-body-textarea"
										placeholder="## About the role&#10;&#10;### Responsibilities&#10;- ..."></textarea>
									<small class="jd-help">Supports markdown: # headings, **bold**, - bullets, | tables |. Renders on save.</small>
								</div>

								<div class="jd-form-actions">
									<button onclick={() => editing = false} class="jd-btn-cancel">Cancel</button>
									<button onclick={saveEdit} class="jd-btn-save">Save changes</button>
								</div>
							</div>
						</div>
					{:else}
						<!-- View Mode -->
						<div class="ink-border stamp-shadow" style="background: var(--color-surface-bright);">
							<div class="dark-title-bar flex items-center justify-between">
								<span>{showRaw ? 'Original (raw)' : 'Full Job Description'}</span>
								<div style="display: flex; gap: 10px; align-items: center;">
									{#if jd.jd_text_raw && jd.jd_text_source === 'ai_reformatted'}
										<button onclick={() => showRaw = !showRaw}
											style="background: transparent; border: 1px solid var(--color-surface); color: var(--color-surface); padding: 2px 8px; font-size: 9px; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;">
											{showRaw ? 'Show formatted' : 'Show original'}
										</button>
									{/if}
									<span style="font-size: 9px; opacity: 0.7; letter-spacing: 0.1em;">v{jd.doc_version || '1.0'} · {jd.doc_last_review || ''}</span>
								</div>
							</div>
							<div class="prose-chat" style="padding: 32px 40px; min-height: 300px; font-family: 'Space Grotesk', sans-serif;">
								{#if showRaw && jd.jd_text_raw}
									<pre style="white-space: pre-wrap; font-family: ui-monospace, Menlo, monospace; font-size: 12px; line-height: 1.5; color: var(--color-on-surface-dim);">{jd.jd_text_raw}</pre>
								{:else if jd.jd_text}
									{@html formatJdText(jd.jd_text)}
								{:else}
									<p style="color: var(--color-on-surface-dim); font-style: italic;">No JD content yet. Click "Edit" to add or "AI Enhance" to generate.</p>
								{/if}
							</div>
						</div>
					{/if}

					<!-- Positions Using This JD -->
					<div class="mt-5">
						<div class="dark-title-bar" style="font-size: 11px;">Positions Using This JD</div>
						<div class="ink-border p-4" style="border-top: none; background: var(--color-surface-bright);">
							{#if jd.used_count > 0}
								<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-bottom: 8px;">This JD is linked to {jd.used_count} position(s). Check the Positions page for details.</p>
								<a href="/" class="send-btn" style="font-size: 10px; padding: 5px 12px; text-decoration: none; display: inline-block;">View Positions →</a>
							{:else}
								<div class="flex items-center gap-3">
									<span class="material-symbols-outlined" style="font-size: 20px; color: var(--color-on-surface-dim);">link_off</span>
									<span style="font-size: 12px; color: var(--color-on-surface-dim);">Not linked to any position yet</span>
									<div class="relative" style="position: relative;">
										<button class="send-btn" style="font-size: 10px; padding: 5px 12px;" onclick={() => showUseDropdown = !showUseDropdown}>
											Use for Position ▾
										</button>
										{#if showUseDropdown}
											<div class="ink-border stamp-shadow" style="position: absolute; top: 100%; left: 0; margin-top: 4px; background: var(--color-surface-bright); z-index: 50; min-width: 220px; max-height: 200px; overflow-y: auto;">
												{#each positions as pos}
													<button style="display: block; width: 100%; text-align: left; padding: 8px 12px; border: none; border-bottom: 1px solid var(--color-surface-highest); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; cursor: pointer; background: transparent;"
														onclick={() => { useForPosition(pos.slug); showUseDropdown = false; }}>
														{pos.title} <span style="font-weight: 400; color: var(--color-on-surface-dim);">— {pos.department || ''}</span>
													</button>
												{/each}
												{#if positions.length === 0}
													<p style="padding: 12px; font-size: 11px; color: var(--color-on-surface-dim);">No active positions</p>
												{/if}
											</div>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					</div>
				</div>

				<!-- BOTTOM GRID: Compliance + Skills + Tags etc -->
				<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-top: 20px;">

					<!-- Compliance Report -->
					<div class="ink-border mb-4" style="background: var(--color-surface-bright);">
						<div class="dark-title-bar" style="font-size: 11px;">Compliance Report</div>
						<div class="p-4">
							{#if jd.dei_score || jd.completeness_score || jd.legal_check !== null}
								<div class="grid grid-cols-3 gap-2">
									<div class="text-center p-2" style="border: 2px solid {complianceColor(jd.dei_score)};">
										<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">DEI</div>
										<div style="font-size: 22px; font-weight: 900; color: {complianceColor(jd.dei_score)};">{jd.dei_score ?? '—'}</div>
									</div>
									<div class="text-center p-2" style="border: 2px solid {jd.legal_check ? 'var(--color-primary)' : jd.legal_check === false ? 'var(--color-error)' : 'var(--color-outline)'};">
										<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">Legal</div>
										<div style="font-size: 16px; font-weight: 900; color: {jd.legal_check ? 'var(--color-primary)' : jd.legal_check === false ? 'var(--color-error)' : 'var(--color-on-surface-dim)'};">
											{jd.legal_check === true ? '✓ PASS' : jd.legal_check === false ? '✗ FAIL' : '—'}
										</div>
									</div>
									<div class="text-center p-2" style="border: 2px solid {complianceColor(jd.completeness_score)};">
										<div style="font-size: 8px; font-weight: 900; text-transform: uppercase; color: var(--color-on-surface-dim);">Complete</div>
										<div style="font-size: 22px; font-weight: 900; color: {complianceColor(jd.completeness_score)};">{jd.completeness_score ?? '—'}<span style="font-size: 10px;">%</span></div>
									</div>
								</div>
							{:else}
								<div class="text-center py-3" style="border: 2px dashed var(--color-outline-variant);">
									<span class="material-symbols-outlined" style="font-size: 24px; color: var(--color-on-surface-dim);">verified</span>
									<p style="font-size: 10px; color: var(--color-on-surface-dim); text-transform: uppercase; margin-top: 4px;">Click "AI Enhance" to run compliance checks</p>
								</div>
							{/if}
						</div>
					</div>

					<!-- Required Skills -->
					<div class="ink-border mb-4" style="background: var(--color-surface-bright);">
						<div class="dark-title-bar flex items-center justify-between" style="font-size: 11px;">
							<span>Required Skills</span>
							<span style="opacity: 0.6;">{jd.required_skills?.length || 0}</span>
						</div>
						<div class="p-4">
							{#if jd.required_skills?.length}
								<div class="flex gap-1 flex-wrap">
									{#each jd.required_skills as skill}
										<span style="font-size: 11px; padding: 3px 10px; border: 2px solid var(--color-primary); color: var(--color-primary); font-weight: 700; text-transform: uppercase; margin-bottom: 2px;">{skill}</span>
									{/each}
								</div>
							{:else}
								<p style="font-size: 10px; color: var(--color-on-surface-dim); text-transform: uppercase;">AI Enhance to extract skills</p>
							{/if}
						</div>
					</div>

					<!-- Nice to Have -->
					<div class="ink-border mb-4" style="background: var(--color-surface-bright);">
						<div class="dark-title-bar flex items-center justify-between" style="font-size: 11px;">
							<span>Nice to Have</span>
							<span style="opacity: 0.6;">{jd.nice_to_have_skills?.length || 0}</span>
						</div>
						<div class="p-4">
							{#if jd.nice_to_have_skills?.length}
								<div class="flex gap-1 flex-wrap">
									{#each jd.nice_to_have_skills as skill}
										<span style="font-size: 11px; padding: 3px 10px; border: 1px dashed var(--color-outline); color: var(--color-on-surface-dim); font-weight: 700; text-transform: uppercase;">{skill}</span>
									{/each}
								</div>
							{:else}
								<p style="font-size: 10px; color: var(--color-on-surface-dim); text-transform: uppercase;">—</p>
							{/if}
						</div>
					</div>

					<!-- Industry Keywords -->
					{#if jd.industry_keywords?.length}
						<div class="ink-border mb-4" style="background: var(--color-surface-bright);">
							<div class="dark-title-bar" style="font-size: 11px;">Industry Keywords</div>
							<div class="p-4">
								<div class="flex gap-1 flex-wrap">
									{#each jd.industry_keywords as kw}
										<span style="font-size: 10px; padding: 2px 8px; background: var(--color-surface-highest); font-weight: 700; text-transform: uppercase;">{kw}</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Certifications -->
					{#if jd.required_certifications?.length}
						<div class="ink-border mb-4" style="background: var(--color-surface-bright);">
							<div class="dark-title-bar" style="font-size: 11px;">Certifications Required</div>
							<div class="p-4">
								<div class="flex gap-1 flex-wrap">
									{#each jd.required_certifications as cert}
										<span style="font-size: 10px; padding: 2px 8px; border: 1px solid var(--color-secondary); color: var(--color-secondary); font-weight: 700; text-transform: uppercase;">{cert}</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}

					<!-- Education -->
					{#if jd.education_level}
						<div class="ink-border mb-4" style="background: var(--color-surface-bright);">
							<div class="dark-title-bar" style="font-size: 11px;">Education</div>
							<div class="p-4">
								<span style="font-size: 13px; font-weight: 700; text-transform: capitalize;">{jd.education_level}</span>
							</div>
						</div>
					{/if}

					<!-- Tags -->
					{#if jd.tags?.length}
						<div class="ink-border" style="background: var(--color-surface-bright);">
							<div class="dark-title-bar" style="font-size: 11px;">Tags</div>
							<div class="p-4">
								<div class="flex gap-1 flex-wrap">
									{#each jd.tags as tag}
										<span style="font-size: 10px; padding: 2px 8px; background: var(--color-on-surface); color: var(--color-surface); font-weight: 700; text-transform: uppercase;">{tag}</span>
									{/each}
								</div>
							</div>
						</div>
					{/if}
				</div>
			</div>

			<!-- Footer Actions -->
			<div class="ink-border mt-5 p-4 animate-fade-up" style="background: var(--color-surface-bright);">
				<div class="flex items-center justify-between flex-wrap gap-3">
					<div style="font-size: 10px; color: var(--color-on-surface-dim);">
						Created: {new Date(jd.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}
						· Updated: {new Date(jd.updated_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}
					</div>
					<div class="flex gap-2">
						<button class="send-btn" style="font-size: 10px; padding: 6px 14px;" onclick={duplicateJd}>Duplicate</button>
						<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px;" onclick={() => showUseDropdown = !showUseDropdown}>Use for Position</button>
						<button class="btn-secondary" style="font-size: 10px; padding: 6px 14px;" onclick={enhanceJd} disabled={enhancing}>
							{enhancing ? '...' : '✦ AI Enhance'}
						</button>
						<button class="btn-danger" style="font-size: 10px; padding: 6px 14px;" onclick={archiveJd}>Archive</button>
					</div>
				</div>
			</div>

			<!-- Enhance Error -->
			{#if enhanceError}
				<div class="mt-4 ink-border p-4 animate-fade-up" style="background: #ffebee; border-left: 4px solid var(--color-error);">
					<div class="flex items-start gap-3">
						<span class="material-symbols-outlined" style="font-size: 24px; color: var(--color-error);">error</span>
						<div>
							<p style="font-size: 13px; font-weight: 900; color: var(--color-error); text-transform: uppercase; margin-bottom: 4px;">AI Enhancement Failed</p>
							<p style="font-size: 12px; color: var(--color-on-surface); line-height: 1.5;">{enhanceError}</p>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 8px;">
								To fix: Run <code style="background: #1a1a1a; color: #00fc40; padding: 2px 8px; font-size: 11px;">export OPENROUTER_API_KEY=sk-or-v1-your-key</code> then restart the backend.
								Get a key at <strong>openrouter.ai/keys</strong>
							</p>
						</div>
					</div>
				</div>
			{/if}

			<!-- AI Status Banner -->
			{#if aiAvailable === false}
				<div class="mt-4 ink-border p-4" style="background: #fff8e1; border-left: 4px solid var(--color-warning);">
					<div class="flex items-start gap-3">
						<span class="material-symbols-outlined" style="font-size: 24px; color: var(--color-warning);">key_off</span>
						<div>
							<p style="font-size: 13px; font-weight: 900; color: var(--color-warning); text-transform: uppercase; margin-bottom: 4px;">AI Features Disabled</p>
							<p style="font-size: 12px; color: var(--color-on-surface); line-height: 1.5;">
								OPENROUTER_API_KEY is not set. AI features (Generate JD, Enhance, Extract Skills, Compliance Checks) are disabled.
							</p>
							<p style="font-size: 11px; color: var(--color-on-surface-dim); margin-top: 6px;">
								1. Get a free API key from <strong>openrouter.ai/keys</strong><br/>
								2. Run: <code style="background: #1a1a1a; color: #00fc40; padding: 2px 8px; font-size: 11px;">export OPENROUTER_API_KEY=sk-or-v1-your-key</code><br/>
								3. Restart the backend
							</p>
						</div>
					</div>
				</div>
			{:else if !jd.dei_score && !jd.required_skills?.length && aiAvailable}
				<div class="mt-4 p-3" style="background: var(--color-surface-container); border-left: 4px solid var(--color-primary); font-size: 11px;">
					<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle; color: var(--color-primary);">auto_awesome</span>
					<strong>Tip:</strong> Click "AI Enhance" to automatically extract skills, run compliance checks, and improve this JD.
				</div>
			{/if}

		</div>
	</div>
{/if}

<style>
	@media (max-width: 768px) {
		.flex { flex-wrap: wrap; }
	}

	/* ─── JD Body Typography (world-class HR style) ─── */
	:global(.jd-p) {
		font-size: 14px;
		line-height: 1.75;
		margin: 0 0 14px;
		color: var(--color-on-surface);
	}
	:global(.jd-h1) {
		font-size: 22px; font-weight: 900; letter-spacing: 0.02em;
		text-transform: uppercase; margin: 0 0 16px;
		padding-bottom: 8px; border-bottom: 3px solid var(--color-on-surface);
	}
	:global(.jd-h2) {
		font-size: 16px; font-weight: 900; letter-spacing: 0.06em;
		text-transform: uppercase; margin: 28px 0 12px;
		padding: 8px 14px; background: var(--color-on-surface); color: var(--color-surface);
		display: block;
	}
	:global(.jd-h3) {
		font-size: 14px; font-weight: 900; letter-spacing: 0.05em;
		text-transform: uppercase; margin: 20px 0 8px;
		border-left: 4px solid var(--color-primary); padding: 4px 10px;
		background: var(--color-surface-bright);
	}
	:global(.jd-h4) {
		font-size: 12px; font-weight: 900; letter-spacing: 0.05em;
		text-transform: uppercase; margin: 14px 0 6px;
		color: var(--color-on-surface-dim);
	}
	:global(.jd-hr) {
		border: none; border-top: 2px dashed var(--color-on-surface);
		margin: 24px 0; opacity: 0.4;
	}
	:global(.jd-ul) {
		margin: 8px 0 16px; padding-left: 0; list-style: none;
	}
	:global(.jd-ul li) {
		font-size: 14px; line-height: 1.7;
		padding: 6px 0 6px 22px; position: relative;
		border-bottom: 1px dashed rgba(56,56,50,0.12);
	}
	:global(.jd-ul li:last-child) { border-bottom: none; }
	:global(.jd-ul li::before) {
		content: "▸"; position: absolute; left: 0; top: 6px;
		color: var(--color-primary); font-weight: 900;
	}
	:global(.jd-ul li strong) { color: var(--color-on-surface); font-weight: 900; }
	:global(.jd-table-wrap) { margin: 12px 0 20px; overflow-x: auto; }
	:global(.jd-table) {
		width: 100%; border-collapse: collapse; font-size: 13px;
		border: 2px solid var(--color-on-surface);
	}
	:global(.jd-table th) {
		background: var(--color-on-surface); color: var(--color-surface);
		text-align: left; padding: 10px 14px;
		font-size: 11px; font-weight: 900; letter-spacing: 0.08em;
		text-transform: uppercase;
		border-bottom: 2px solid var(--color-on-surface);
	}
	:global(.jd-table td) {
		padding: 10px 14px; border-top: 1px solid rgba(56,56,50,0.18);
		vertical-align: top;
	}
	:global(.jd-table td.first) {
		font-weight: 900; background: var(--color-surface-bright);
		min-width: 180px;
	}
	:global(.jd-table tr.alt td) { background: rgba(56,56,50,0.02); }
	:global(.jd-table tr.alt td.first) { background: var(--color-surface-bright); }
	:global(.jd-table code) {
		background: var(--color-surface-bright); padding: 1px 5px;
		font-family: ui-monospace, monospace; font-size: 12px;
		border: 1px solid rgba(56,56,50,0.2);
	}
	:global(.prose-chat code) {
		background: var(--color-surface-bright); padding: 1px 5px;
		font-family: ui-monospace, monospace; font-size: 12px;
	}
	:global(.prose-chat strong) { font-weight: 900; }

	/* tag chips */
	.chip-skill {
		font-size: 11px; padding: 4px 10px;
		border: 2px solid var(--color-primary); color: var(--color-primary);
		font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
	}

	/* ---------- JD Edit Form ---------- */
	.jd-edit-form { padding: 24px 28px; background: var(--color-surface, #fff); }
	.jd-form-section { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--color-border, #e8e6dd); }
	.jd-form-section:last-of-type { border-bottom: none; padding-bottom: 0; }
	.jd-form-section-title {
		font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
		color: var(--color-on-surface-dim, #6f6e69); margin-bottom: 14px;
	}
	.jd-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 18px; }
	.jd-field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
	.jd-field-full { grid-column: 1 / -1; }
	.jd-field > span {
		font-size: 11px; font-weight: 600; color: var(--color-on-surface, #2c2c2c);
		letter-spacing: 0.01em;
	}
	.jd-field input[type="text"], .jd-field input[type="number"], .jd-field select, .jd-body-textarea {
		width: 100%; padding: 9px 12px; font-family: inherit; font-size: 13px;
		background: #fff; color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px;
		outline: none; transition: border-color 120ms;
		box-sizing: border-box;
	}
	.jd-field input:focus, .jd-field select:focus, .jd-body-textarea:focus {
		border-color: var(--color-accent, #c96342); box-shadow: 0 0 0 2px rgba(201, 99, 66, 0.15);
	}
	.jd-body-textarea {
		font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
		font-size: 12.5px; line-height: 1.6; padding: 14px 16px; resize: vertical;
		min-height: 320px; border-radius: 8px;
	}
	.jd-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
	.jd-chip {
		display: inline-flex; align-items: center; gap: 6px;
		font-size: 11px; padding: 3px 4px 3px 10px;
		background: var(--color-bg, #faf9f5); color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #e8e6dd); border-radius: 999px;
	}
	.jd-chip button {
		width: 18px; height: 18px; padding: 0; line-height: 1;
		border: none; background: transparent; color: var(--color-on-surface-dim, #6f6e69);
		font-size: 16px; cursor: pointer; border-radius: 50%;
	}
	.jd-chip button:hover { background: rgba(0,0,0,0.06); color: var(--color-accent, #c96342); }
	.jd-help { font-size: 11px; color: var(--color-on-surface-dim, #6f6e69); margin-top: 4px; }
	.jd-form-actions {
		display: flex; gap: 10px; justify-content: flex-end;
		padding-top: 16px; border-top: 1px solid var(--color-border, #e8e6dd);
	}
	.jd-btn-cancel {
		padding: 8px 18px; font-size: 12px; font-weight: 500;
		background: transparent; color: var(--color-on-surface, #2c2c2c);
		border: 1px solid var(--color-border, #d8d5cc); border-radius: 6px; cursor: pointer;
	}
	.jd-btn-cancel:hover { background: var(--color-bg, #faf9f5); }
	.jd-btn-save {
		padding: 8px 18px; font-size: 12px; font-weight: 600;
		background: var(--color-accent, #c96342); color: #fff;
		border: 1px solid var(--color-accent, #c96342); border-radius: 6px; cursor: pointer;
	}
	.jd-btn-save:hover { filter: brightness(0.95); }
	@media (max-width: 800px) { .jd-grid-2 { grid-template-columns: 1fr; } }
</style>
