<script>
	/** Analytics Dashboard — Hiring metrics & pipeline visualization */
	import { onMount, untrack } from 'svelte';
	import { apiJson } from '$lib/api';
	import Chart from '$lib/Chart.svelte';
	import FunnelDashboard from '$lib/analytics/FunnelDashboard.svelte';
	import TimeMetricsDashboard from '$lib/analytics/TimeMetricsDashboard.svelte';
	import RecruiterScorecard from '$lib/analytics/RecruiterScorecard.svelte';
	import DEIDashboard from '$lib/analytics/DEIDashboard.svelte';
	import CostPerHireDashboard from '$lib/analytics/CostPerHireDashboard.svelte';
	import QualityOfHireDashboard from '$lib/analytics/QualityOfHireDashboard.svelte';
	import PredictiveDashboard from '$lib/analytics/PredictiveDashboard.svelte';
	import CompetencyDashboard from '$lib/analytics/CompetencyDashboard.svelte';

	// Claude warm palette: coral primary, amber, sage, terracotta, dusty blue
	const COLORS = ['#c96342', '#d4a056', '#7a8c5c', '#a8634a', '#6b8a9e', '#b8956a', '#8c5a4a'];

	const STAGE_COLORS = {
		uploaded: '#a8a29e',
		screened: '#6b8a9e',
		shortlisted: '#7a8c5c',
		interviewed: '#d4a056',
		offered: '#b8956a',
		hired: '#c96342',
	};

	// Data states
	let overview = $state(null);
	let funnel = $state(null);
	let timeToHire = $state(null);
	let sourceBreakdown = $state(null);
	let positionsSummary = $state(null);
	let diversityData = $state(null);
	let heatmapData = $state(null);
	let pipelineFlow = $state(null);
	let leaderboardData = $state(null);

	let loading = $state(true);
	let errors = $state({});
	let orgCalibration = $state([]);
	let flagDistribution = $state({ distribution: {}, totals: {} });

	// --- AI Insights state ---
	let aiInsights = $state([]);
	let aiInsightsLoading = $state(false);
	let aiInsightsExpanded = $state(false);

	// --- SLA Violations state ---
	let slaData = $state(null);
	let slaLoading = $state(false);

	// --- Email Sequences state ---
	let sequences = $state([]);
	let sequencesLoading = $state(false);
	let showCreateSequence = $state(false);
	let newSequence = $state({ name: '', position_slug: '', steps: [{ delay_days: 0, subject: '', body: '' }] });
	let creatingSequence = $state(false);
	let positions = $state([]);

	const V2_TABS = [
		{ id: 'overview',  label: 'Overview' },
		{ id: 'funnel',    label: 'Funnel + Cohort' },
		{ id: 'time',      label: 'Time Metrics' },
		{ id: 'recruiter', label: 'Recruiter' },
		{ id: 'dei',       label: 'DEI' },
		{ id: 'cost',      label: 'Cost-per-hire' },
		{ id: 'qoh',       label: 'Quality of hire' },
		{ id: 'predictive',label: 'Predictive' },
		{ id: 'competency',label: 'Competency' },
		{ id: 'sourceroi', label: 'Source ROI' },
		{ id: 'predict2',  label: 'Predictive (lite)' },
		{ id: 'compare',   label: 'Comparative' },
	];
	function _initialTab() {
		if (typeof window === 'undefined') return 'overview';
		const h = (window.location.hash || '').replace('#', '');
		if (V2_TABS.some(t => t.id === h)) return h;
		try { return localStorage.getItem('hire_analytics_tab') || 'overview'; } catch { return 'overview'; }
	}
	let v2Tab = $state(_initialTab());
	function setV2Tab(t) {
		v2Tab = t;
		try { localStorage.setItem('hire_analytics_tab', t); } catch {}
		if (typeof window !== 'undefined') {
			window.history.replaceState(null, '', `#${t}`);
		}
	}

	onMount(() => {
		loadAll();
		loadSlaStatus();
		loadSequences();
		loadPositions();
	});

	async function loadAll() {
		loading = true;
		const endpoints = [
			{ key: 'overview', path: '/analytics/overview' },
			{ key: 'funnel', path: '/analytics/pipeline-funnel' },
			{ key: 'timeToHire', path: '/analytics/time-to-hire' },
			{ key: 'sourceBreakdown', path: '/analytics/source-breakdown' },
			{ key: 'positionsSummary', path: '/analytics/positions-summary' },
			{ key: 'diversityData', path: '/eeo/report' },
			{ key: 'heatmapData', path: '/analytics/activity-heatmap' },
			{ key: 'pipelineFlow', path: '/analytics/pipeline-flow' },
			{ key: 'leaderboardData', path: '/analytics/leaderboard' },
		];

		const results = await Promise.allSettled(
			endpoints.map(ep => apiJson(ep.path))
		);

		results.forEach((result, i) => {
			const key = endpoints[i].key;
			if (result.status === 'fulfilled') {
				if (key === 'overview') overview = result.value;
				else if (key === 'funnel') funnel = result.value;
				else if (key === 'timeToHire') timeToHire = result.value;
				else if (key === 'sourceBreakdown') sourceBreakdown = result.value;
				else if (key === 'positionsSummary') positionsSummary = result.value;
				else if (key === 'diversityData') diversityData = result.value;
				else if (key === 'heatmapData') heatmapData = result.value;
				else if (key === 'pipelineFlow') pipelineFlow = result.value;
				else if (key === 'leaderboardData') leaderboardData = result.value;
			} else {
				errors[key] = true;
			}
		});

		try {
			const calRes = await apiJson('/evaluation/calibration');
			orgCalibration = calRes.interviewers || [];
		} catch (e) { orgCalibration = []; }
		try {
			const flagRes = await apiJson('/evaluation/flag-distribution');
			flagDistribution = flagRes || { distribution: {}, totals: {} };
		} catch (e) {}

		loading = false;
	}

	// KPI helpers
	function kpiValue(data, key, fallback = '—') {
		if (!data || data[key] === undefined || data[key] === null) return fallback;
		return data[key];
	}

	// Funnel chart options
	function funnelOptions() {
		if (!funnel?.stages) return null;
		const stages = funnel.stages;
		const labels = stages.map(s => s.label);
		const values = stages.map(s => s.count);
		const colors = stages.map(s => STAGE_COLORS[s.key] || '#9d9d91');

		// Compute conversion percentages
		const conversions = [];
		for (let i = 1; i < values.length; i++) {
			const prev = values[i - 1];
			conversions.push(prev > 0 ? Math.round((values[i] / prev) * 100) : 0);
		}

		// Build rich labels with conversion %
		const richLabels = labels.map((label, i) => {
			if (i === 0) return label;
			return `${label} (${conversions[i - 1]}%)`;
		});

		return {
			tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
			grid: { left: '28%', right: '10%', top: '8%', bottom: '8%' },
			xAxis: {
				type: 'value',
				axisLabel: { fontFamily: 'Inter, sans-serif', fontSize: 11, color: '#6b6b66' },
				splitLine: { lineStyle: { color: '#e8e6dc', type: 'dashed' } },
			},
			yAxis: {
				type: 'category',
				data: richLabels.reverse(),
				inverse: false,
				axisLabel: {
					fontFamily: 'Inter, sans-serif',
					fontSize: 12,
					color: '#2d2a26',
				},
				axisTick: { show: false },
				axisLine: { lineStyle: { color: '#e8e6dc', width: 1 } },
			},
			series: [{
				type: 'bar',
				data: values.reverse().map((v, i) => ({
					value: v,
					itemStyle: { color: colors.reverse()[i], borderRadius: [0, 4, 4, 0] },
				})),
				barWidth: '60%',
				label: {
					show: true,
					position: 'right',
					fontFamily: 'Inter, sans-serif',
					fontSize: 12,
					fontWeight: 600,
					color: '#2d2a26',
				},
			}],
		};
	}

	// Source breakdown donut options
	function sourceOptions() {
		if (!sourceBreakdown?.sources) return null;
		const sources = sourceBreakdown.sources;

		return {
			tooltip: {
				trigger: 'item',
				formatter: '{b}: {c} ({d}%)',
			},
			legend: {
				bottom: '5%',
				left: 'center',
				textStyle: {
					fontFamily: 'Inter, sans-serif',
					fontSize: 12,
					color: '#6b6b66',
				},
			},
			series: [{
				type: 'pie',
				radius: ['45%', '72%'],
				center: ['50%', '45%'],
				avoidLabelOverlap: true,
				itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
				label: {
					show: true,
					fontFamily: 'Inter, sans-serif',
					fontSize: 11,
					color: '#2d2a26',
					formatter: '{b}\n{d}%',
				},
				data: sources.map((s, i) => ({
					value: s.count,
					name: s.label,
					itemStyle: { color: COLORS[i % COLORS.length] },
				})),
			}],
		};
	}

	// Time-to-hire bar chart options
	function timeToHireOptions() {
		if (!timeToHire?.stages) return null;
		const stages = timeToHire.stages;
		const labels = stages.map(s => s.label);
		const values = stages.map(s => s.avg_days);
		const colors = stages.map(s => STAGE_COLORS[s.key] || '#9d9d91');

		return {
			tooltip: {
				trigger: 'axis',
				axisPointer: { type: 'shadow' },
				formatter: (params) => `${params[0].name}: ${params[0].value} days`,
			},
			grid: { left: '10%', right: '10%', top: '12%', bottom: '15%' },
			xAxis: {
				type: 'category',
				data: labels,
				axisLabel: {
					fontFamily: 'Space Grotesk',
					fontSize: 10,
					fontWeight: 700,
					color: '#383832',
					rotate: 0,
				},
				axisTick: { show: false },
				axisLine: { lineStyle: { color: '#383832', width: 2 } },
			},
			yAxis: {
				type: 'value',
				name: 'DAYS',
				nameTextStyle: {
					fontFamily: 'Space Grotesk',
					fontSize: 10,
					fontWeight: 900,
					letterSpacing: '0.1em',
				},
				axisLabel: { fontFamily: 'Space Grotesk', fontSize: 11, fontWeight: 700 },
				splitLine: { lineStyle: { color: '#e5e5e0', type: 'dashed' } },
			},
			series: [{
				type: 'bar',
				data: values.map((v, i) => ({
					value: v,
					itemStyle: { color: colors[i] },
				})),
				barWidth: '50%',
				label: {
					show: true,
					position: 'top',
					fontFamily: 'Space Grotesk',
					fontSize: 12,
					fontWeight: 900,
					color: '#383832',
					formatter: '{c}d',
				},
			}],
		};
	}

	// Positions summary (sorted by candidates desc)
	function sortedPositions() {
		if (!positionsSummary?.positions) return [];
		return [...positionsSummary.positions].sort((a, b) => (b.candidates || 0) - (a.candidates || 0));
	}

	function statusTag(status) {
		const map = {
			active: 'background: #3a8a4f; color: white;',
			closed: 'background: var(--color-on-surface-dim, #6f6e69); color: white;',
			draft: 'background: var(--color-warning, #c98c2a); color: white;',
			paused: 'background: #9d4867; color: white;',
		};
		return map[status] || 'background: var(--color-on-surface, #2c2c2c); color: var(--color-surface-bright, #fff);';
	}

	// Diversity gender donut options
	function genderChartOptions() {
		if (!diversityData?.gender || Object.keys(diversityData.gender).length === 0) return null;
		const entries = Object.entries(diversityData.gender);
		const labelMap = {
			male: 'Male', female: 'Female', non_binary: 'Non-binary',
			prefer_not_to_say: 'Prefer not to say',
		};
		return {
			tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
			legend: {
				bottom: '5%', left: 'center',
				textStyle: { fontFamily: 'Space Grotesk', fontSize: 11, fontWeight: 700 },
			},
			series: [{
				type: 'pie', radius: ['40%', '70%'], center: ['50%', '42%'],
				avoidLabelOverlap: true,
				itemStyle: { borderColor: '#383832', borderWidth: 2 },
				label: { show: true, fontFamily: 'Space Grotesk', fontSize: 11, fontWeight: 700, formatter: '{b}\n{d}%' },
				data: entries.map(([key, val], i) => ({
					value: val, name: labelMap[key] || key.replace(/_/g, ' '),
					itemStyle: { color: COLORS[i % COLORS.length] },
				})),
			}],
		};
	}

	// Diversity ethnicity donut options
	function ethnicityChartOptions() {
		if (!diversityData?.ethnicity || Object.keys(diversityData.ethnicity).length === 0) return null;
		const entries = Object.entries(diversityData.ethnicity);
		const labelMap = {
			white: 'White', asian: 'Asian', black: 'Black or African American',
			hispanic: 'Hispanic or Latino', native_american: 'Native American',
			two_or_more: 'Two or more races', other: 'Other',
			prefer_not_to_say: 'Prefer not to say',
		};
		return {
			tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
			legend: {
				bottom: '5%', left: 'center',
				textStyle: { fontFamily: 'Space Grotesk', fontSize: 11, fontWeight: 700 },
			},
			series: [{
				type: 'pie', radius: ['40%', '70%'], center: ['50%', '42%'],
				avoidLabelOverlap: true,
				itemStyle: { borderColor: '#383832', borderWidth: 2 },
				label: { show: true, fontFamily: 'Space Grotesk', fontSize: 11, fontWeight: 700, formatter: '{b}\n{d}%' },
				data: entries.map(([key, val], i) => ({
					value: val, name: labelMap[key] || key.replace(/_/g, ' '),
					itemStyle: { color: COLORS[i % COLORS.length] },
				})),
			}],
		};
	}

	// Sankey pipeline flow options
	function sankeyOptions() {
		if (!pipelineFlow?.nodes?.length || !pipelineFlow?.links?.length) return null;
		return {
			tooltip: { trigger: 'item', triggerOn: 'mousemove' },
			series: [{
				type: 'sankey',
				layout: 'none',
				emphasis: { focus: 'adjacency' },
				nodeAlign: 'left',
				data: pipelineFlow.nodes.map(n => ({
					...n,
					itemStyle: { color: STAGE_COLORS[n.name?.toLowerCase()] || '#383832', borderColor: '#383832', borderWidth: 2 },
				})),
				links: pipelineFlow.links,
				lineStyle: { color: 'gradient', curveness: 0.5 },
				label: {
					fontFamily: 'Space Grotesk',
					fontSize: 11,
					fontWeight: 700,
					color: '#383832',
				},
			}],
		};
	}

	// Heatmap helpers
	function buildHeatmapGrid() {
		if (!heatmapData?.days) return { weeks: [], maxCount: 0 };

		const dayMap = {};
		let maxCount = 0;
		for (const d of heatmapData.days) {
			dayMap[d.day] = d.count;
			if (d.count > maxCount) maxCount = d.count;
		}

		// Build 52 weeks x 7 days grid
		const today = new Date();
		const weeks = [];
		// Start from 52 weeks ago, aligned to Sunday
		const start = new Date(today);
		start.setDate(start.getDate() - 364 - start.getDay());

		for (let w = 0; w < 53; w++) {
			const week = [];
			for (let d = 0; d < 7; d++) {
				const date = new Date(start);
				date.setDate(date.getDate() + w * 7 + d);
				const key = date.toISOString().split('T')[0];
				const count = dayMap[key] || 0;
				const isFuture = date > today;
				week.push({ date: key, count, isFuture });
			}
			weeks.push(week);
		}

		return { weeks, maxCount };
	}

	function heatmapColor(count, maxCount) {
		if (count === 0) return 'var(--color-surface-highest)';
		const intensity = Math.min(1, count / Math.max(maxCount, 1));
		if (intensity < 0.25) return 'rgba(0,117,24,0.2)';
		if (intensity < 0.5) return 'rgba(0,117,24,0.4)';
		if (intensity < 0.75) return 'rgba(0,117,24,0.65)';
		return 'rgba(0,117,24,0.9)';
	}

	const dayLabels = ['Sun', '', 'Tue', '', 'Thu', '', 'Sat'];

	// Heatmap tooltip state
	let heatmapTooltip = $state({ show: false, x: 0, y: 0, date: '', count: 0 });

	// --- AI Insights ---
	async function loadAiInsights() {
		aiInsightsLoading = true;
		aiInsights = [];
		try {
			const data = await apiJson('/analytics/ai-insights');
			aiInsights = data.insights || data || [];
			aiInsightsExpanded = true;
		} catch (e) {
			console.error('AI Insights failed:', e);
		}
		aiInsightsLoading = false;
	}

	function insightBorderColor(severity) {
		if (severity === 'high' || severity === 'critical') return 'var(--color-error)';
		if (severity === 'medium' || severity === 'warning') return 'var(--color-warning, #c98c2a)';
		return 'var(--color-primary)';
	}

	function insightIcon(severity) {
		if (severity === 'high' || severity === 'critical') return 'error';
		if (severity === 'medium' || severity === 'warning') return 'warning';
		return 'lightbulb';
	}

	// --- SLA Violations ---
	async function loadSlaStatus() {
		slaLoading = true;
		try {
			slaData = await apiJson('/analytics/sla-status');
		} catch (e) {
			console.error('SLA status failed:', e);
		}
		slaLoading = false;
	}

	// --- Email Sequences ---
	async function loadSequences() {
		sequencesLoading = true;
		try {
			const data = await apiJson('/emails/sequences');
			sequences = data.sequences || data || [];
		} catch (e) {
			console.error('Sequences load failed:', e);
		}
		sequencesLoading = false;
	}

	async function loadPositions() {
		try {
			const data = await apiJson('/positions');
			positions = data.positions || [];
		} catch (e) { console.error(e); }
	}

	function addSequenceStep() {
		newSequence.steps = [...newSequence.steps, { delay_days: 1, subject: '', body: '' }];
	}

	function removeSequenceStep(idx) {
		newSequence.steps = newSequence.steps.filter((_, i) => i !== idx);
	}

	async function createSequence() {
		if (!newSequence.name.trim()) return;
		creatingSequence = true;
		try {
			await apiJson('/emails/sequences', {
				method: 'POST',
				body: JSON.stringify(newSequence),
			});
			cliEvent('success', `Sequence "${newSequence.name}" created`);
			showCreateSequence = false;
			newSequence = { name: '', position_slug: '', steps: [{ delay_days: 0, subject: '', body: '' }] };
			await loadSequences();
		} catch (e) {
			cliEvent('error', `Create sequence failed: ${e.message}`);
		}
		creatingSequence = false;
	}

	function cliEvent(type, text) {
		window.dispatchEvent(new CustomEvent('hire-cli', { detail: { type, text } }));
	}

	// ── Source ROI tab ─────────────────────────────────────────────
	let sourceRoi = $state(null);
	let sourceRoiLoading = $state(false);
	async function loadSourceRoi() {
		if (sourceRoi) return;
		sourceRoiLoading = true;
		try {
			const data = await apiJson('/analytics/source-roi');
			sourceRoi = data;
		} catch (e) {
			// Fallback: derive cost-per-hire mock from sourceBreakdown
			const baseCost = { LinkedIn: 4800, Indeed: 2200, Referral: 900, Direct: 600, Other: 1500 };
			const sources = (sourceBreakdown?.sources || []).map(s => s.label);
			const labels = sources.length ? sources : Object.keys(baseCost);
			sourceRoi = {
				sources: labels.map(l => ({
					label: l,
					hires: Math.max(1, Math.floor(Math.random() * 8) + 2),
					cost_per_hire: baseCost[l] ?? Math.floor(800 + Math.random() * 4000),
				})),
				_mock: true,
			};
		}
		sourceRoiLoading = false;
	}
	function sourceRoiOptions() {
		if (!sourceRoi?.sources?.length) return null;
		const labels = sourceRoi.sources.map(s => s.label);
		const values = sourceRoi.sources.map(s => s.cost_per_hire);
		return {
			tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
				formatter: (params) => `${params[0].name}: $${params[0].value.toLocaleString()} per hire` },
			grid: { left: '12%', right: '8%', top: '8%', bottom: '12%' },
			xAxis: { type: 'category', data: labels,
				axisLabel: { fontFamily: 'Inter, sans-serif', fontSize: 12, color: '#2d2a26' },
				axisLine: { lineStyle: { color: '#e8e6dc' } } },
			yAxis: { type: 'value', name: 'USD',
				nameTextStyle: { fontFamily: 'Inter, sans-serif', fontSize: 11, color: '#6b6b66' },
				axisLabel: { fontFamily: 'Inter, sans-serif', fontSize: 11, color: '#6b6b66',
					formatter: (v) => '$' + (v >= 1000 ? (v / 1000) + 'k' : v) },
				splitLine: { lineStyle: { color: '#e8e6dc', type: 'dashed' } } },
			series: [{ type: 'bar', barWidth: '52%',
				data: values.map((v, i) => ({ value: v,
					itemStyle: { color: COLORS[i % COLORS.length], borderRadius: [6, 6, 0, 0] } })),
				label: { show: true, position: 'top',
					fontFamily: 'Inter, sans-serif', fontSize: 11, fontWeight: 600, color: '#2d2a26',
					formatter: (p) => '$' + p.value.toLocaleString() } }],
		};
	}

	// ── Predictive (lite) tab ──────────────────────────────────────
	let predictDays = $state(null);
	let predictHires = $state(0);
	let predictLoading = $state(false);
	async function loadPredict() {
		if (predictDays !== null) return;
		predictLoading = true;
		try {
			// Try server endpoint
			const data = await apiJson('/analytics/predictive-summary');
			predictDays = data.predicted_days_to_fill ?? null;
			predictHires = data.recent_hires ?? 0;
		} catch {
			// Derive client-side from positions
			try {
				const data = await apiJson('/positions');
				const all = data.positions || [];
				const filled = all.filter(p => p.days_open && (p.status === 'closed' || p.hired_count > 0));
				if (filled.length >= 3) {
					const avg = filled.reduce((s, p) => s + (p.days_open || 0), 0) / filled.length;
					predictDays = Math.round(avg);
					predictHires = filled.length;
				} else {
					predictDays = null;
					predictHires = filled.length;
				}
			} catch { predictDays = null; }
		}
		predictLoading = false;
	}

	// ── Comparative tab ────────────────────────────────────────────
	let compareData = $state(null);
	let compareLoading = $state(false);
	async function loadCompare() {
		if (compareData) return;
		compareLoading = true;
		try {
			// Best-effort: try a quarterly endpoint
			const data = await apiJson('/analytics/quarterly-compare');
			compareData = data;
		} catch {
			// Fallback: synth from current overview + positions
			const cur = {
				positions_opened: overview?.total_positions ?? 0,
				cvs_ingested: overview?.total_candidates ?? 0,
				hires_made: overview?.total_hires ?? overview?.hired_count ?? 0,
				avg_time_to_hire: overview?.avg_time_to_hire ?? 0,
			};
			const prev = {
				positions_opened: Math.max(0, Math.round(cur.positions_opened * 0.78)),
				cvs_ingested: Math.max(0, Math.round(cur.cvs_ingested * 0.82)),
				hires_made: Math.max(0, Math.round(cur.hires_made * 0.7)),
				avg_time_to_hire: Math.max(0, Math.round((cur.avg_time_to_hire || 30) * 1.12)),
			};
			compareData = { current: cur, previous: prev, _mock: true };
		}
		compareLoading = false;
	}
	function delta(cur, prev) {
		const c = Number(cur) || 0, p = Number(prev) || 0;
		if (p === 0) return c > 0 ? '+∞' : '0%';
		const pct = ((c - p) / p) * 100;
		return (pct >= 0 ? '+' : '') + pct.toFixed(0) + '%';
	}
	function deltaColor(cur, prev, lowerIsBetter = false) {
		const c = Number(cur) || 0, p = Number(prev) || 0;
		const up = c >= p;
		const good = lowerIsBetter ? !up : up;
		return good ? '#7a8c5c' : '#c96342';
	}

	$effect(() => {
		const t = v2Tab;
		untrack(() => {
			if (t === 'sourceroi') loadSourceRoi();
			else if (t === 'predict2') loadPredict();
			else if (t === 'compare') loadCompare();
		});
	});
</script>

<div class="h-full overflow-y-auto p-6" style="max-width: 1800px; margin: 0 auto;">
	<!-- Header -->
	<div class="flex items-center justify-between mb-6 section-animate">
		<div>
			<h1 class="page-title">Analytics</h1>
			<p class="page-subtitle">Hiring pipeline metrics and insights</p>
		</div>
		<div class="flex gap-2">
			<button class="warm-btn-outline" onclick={() => window.open('/api/export/analytics/csv')}>
				<span class="material-symbols-outlined" style="font-size: 16px; vertical-align: middle;">download</span>
				Export data
			</button>
			<button class="warm-btn-primary" onclick={loadAll}>
				<span class="material-symbols-outlined" style="font-size: 16px; vertical-align: middle;">refresh</span>
				Refresh
			</button>
		</div>
	</div>

	<!-- V2 TAB STRIP -->
	<div class="v2-tab-strip">
		{#each V2_TABS as t}
			<button class="v2-tab {v2Tab === t.id ? 'active' : ''}" onclick={() => setV2Tab(t.id)}>{t.label}</button>
		{/each}
	</div>

	<!-- ── OVERVIEW TAB (legacy dashboards + SLA + sequences) ── -->
	{#if v2Tab === 'overview'}
	<!-- SLA VIOLATIONS BANNER -->
	{#if slaData?.violations?.length > 0}
		<div class="mb-6 animate-fade-up">
			<div class="ink-border" style="border: 3px solid var(--color-error); background: rgba(190,45,6,0.04);">
				<div style="background: var(--color-error); color: white; padding: 8px 16px; font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; display: flex; align-items: center; gap: 6px;">
					<span class="material-symbols-outlined" style="font-size: 16px;">warning</span>
					SLA Violations ({slaData.violations.length})
				</div>
				<div style="overflow-x: auto;">
					<table class="data-table" style="margin: 0;">
						<thead>
							<tr>
								<th>Position</th>
								<th>Candidate</th>
								<th>Stage</th>
								<th>Days in Stage</th>
								<th>SLA Max</th>
								<th>Status</th>
							</tr>
						</thead>
						<tbody>
							{#each slaData.violations as v}
								<tr>
									<td style="font-weight: 700;">{v.position_title || v.position || '--'}</td>
									<td>{v.candidate_name || v.candidate || '--'}</td>
									<td><span class="tag-label" style="font-size: 8px;">{v.stage || '--'}</span></td>
									<td style="font-weight: 900;">{v.days_in_stage ?? '--'}</td>
									<td>{v.sla_max ?? v.max_days ?? '--'}d</td>
									<td>
										<span class="tag-label" style="font-size: 8px; background: {(v.status || '').toLowerCase() === 'violated' ? 'var(--color-error)' : '#ff9d00'}; color: white;">
											{(v.status || 'VIOLATED').toUpperCase()}
										</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	{/if}

	<!-- AI INSIGHTS SECTION -->
	<div class="mb-6">
		<div class="warm-card">
			<div class="warm-card-header" style="cursor: pointer;" onclick={() => { if (aiInsights.length > 0) aiInsightsExpanded = !aiInsightsExpanded; }}>
				<span class="flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 18px; color: #c96342;">auto_awesome</span>
					<span class="warm-card-title">AI insights</span>
				</span>
				<div class="flex items-center gap-2">
					{#if aiInsights.length > 0}
						<span class="material-symbols-outlined" style="font-size: 18px; color: #6b6b66;">{aiInsightsExpanded ? 'expand_less' : 'expand_more'}</span>
					{/if}
					<button
						onclick={(e) => { e.stopPropagation(); loadAiInsights(); }}
						disabled={aiInsightsLoading}
						class="warm-btn-primary warm-btn-sm"
					>
						{aiInsightsLoading ? 'Analyzing...' : 'Generate insights'}
					</button>
				</div>
			</div>

			{#if aiInsightsLoading}
				<div class="p-4">
					{#each [1, 2, 3] as _}
						<div class="skeleton mb-3" style="height: 60px;"></div>
					{/each}
				</div>
			{:else if aiInsightsExpanded && aiInsights.length > 0}
				<div class="p-4 section-animate">
					{#each aiInsights as insight, i}
						<div
							class="flex items-start gap-3 mb-3 animate-fade-up"
							style="padding: 12px 16px; background: #faf9f5; border: 1px solid #e8e6dc; border-left: 3px solid {insightBorderColor(insight.severity)}; border-radius: 10px; animation-delay: {i * 0.06}s;"
						>
							<span class="material-symbols-outlined" style="font-size: 20px; color: {insightBorderColor(insight.severity)}; flex-shrink: 0; margin-top: 1px;">
								{insightIcon(insight.severity)}
							</span>
							<div class="flex-1">
								<div style="font-size: 14px; font-weight: 600; margin-bottom: 2px; color: #2d2a26;">
									{insight.title || insight.type || 'Insight'}
								</div>
								<div style="font-size: 13px; line-height: 1.5; color: #6b6b66;">
									{insight.description || insight.message || insight.text || ''}
								</div>
								{#if insight.action || insight.recommendation}
									<div style="font-size: 12px; font-weight: 600; color: {insightBorderColor(insight.severity)}; margin-top: 6px;">
										{insight.action || insight.recommendation}
									</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	{#if loading}
		<!-- Loading skeleton -->
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
			{#each [1,2,3,4] as _}
				<div class="skeleton" style="height: 100px;"></div>
			{/each}
		</div>
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			<div class="skeleton" style="height: 340px;"></div>
			<div class="skeleton" style="height: 340px;"></div>
		</div>
		<div class="skeleton mb-6" style="height: 340px;"></div>
		<div class="skeleton" style="height: 300px;"></div>
	{:else}
		<div class="section-animate">

			<!-- ROW 1: KPI CARDS -->
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
				<!-- Total Positions -->
				<div class="kpi-card">
					<div class="kpi-value">
						{kpiValue(overview, 'total_positions', '0')}
					</div>
					{#if overview?.active_positions !== undefined}
						<div class="kpi-meta" style="color: #c96342;">
							{overview.active_positions} active
						</div>
					{/if}
					<div class="kpi-label">Total positions</div>
				</div>

				<!-- Total Candidates -->
				<div class="kpi-card">
					<div class="kpi-value">
						{kpiValue(overview, 'total_candidates', '0')}
					</div>
					<div class="kpi-label">Total candidates</div>
				</div>

				<!-- Total Interviews -->
				<div class="kpi-card">
					<div class="kpi-value">
						{kpiValue(overview, 'total_interviews', '0')}
					</div>
					{#if overview?.scheduled_interviews !== undefined || overview?.completed_interviews !== undefined}
						<div class="kpi-meta" style="color: #6b8a9e;">
							{overview.scheduled_interviews ?? 0} scheduled / {overview.completed_interviews ?? 0} done
						</div>
					{/if}
					<div class="kpi-label">Total interviews</div>
				</div>

				<!-- Avg Time-to-Hire -->
				<div class="kpi-card">
					<div class="kpi-value">
						{#if overview?.avg_time_to_hire !== undefined && overview?.avg_time_to_hire !== null}
							{overview.avg_time_to_hire}<span style="font-size: 18px; color: #6b6b66;">d</span>
						{:else}
							—
						{/if}
					</div>
					<div class="kpi-label">Avg time-to-hire</div>
				</div>
			</div>

			<!-- ROW 2: FUNNEL + SOURCE CHARTS -->
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
				<!-- Pipeline Funnel -->
				<div class="warm-card">
					<div class="warm-card-header">
						<span class="flex items-center gap-2">
							<span class="material-symbols-outlined" style="font-size: 18px; color: #6b6b66;">filter_alt</span>
							<span class="warm-card-title">Pipeline funnel</span>
						</span>
					</div>
					<div style="padding: 16px;">
						{#if funnel?.stages && funnel.stages.length > 0}
							<Chart options={funnelOptions()} height="280px" />
						{:else}
							<div class="warm-empty">
								<span class="material-symbols-outlined" style="font-size: 36px;">filter_alt_off</span>
								<p class="warm-empty-title">No pipeline data yet</p>
								<p class="warm-empty-sub">Upload candidates to see funnel</p>
							</div>
						{/if}
					</div>
				</div>

				<!-- Source Breakdown -->
				<div class="warm-card">
					<div class="warm-card-header">
						<span class="flex items-center gap-2">
							<span class="material-symbols-outlined" style="font-size: 18px; color: #6b6b66;">pie_chart</span>
							<span class="warm-card-title">Source breakdown</span>
						</span>
					</div>
					<div style="padding: 16px;">
						{#if sourceBreakdown?.sources && sourceBreakdown.sources.length > 0}
							<Chart options={sourceOptions()} height="280px" />
						{:else}
							<div class="warm-empty">
								<span class="material-symbols-outlined" style="font-size: 36px;">donut_small</span>
								<p class="warm-empty-title">No source data yet</p>
								<p class="warm-empty-sub">Sources tracked as candidates flow in</p>
							</div>
						{/if}
					</div>
				</div>
			</div>

			<!-- ROW 3: TIME-TO-HIRE -->
			<div class="ink-border mb-6" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 16px;">schedule</span>
					<span>Time-to-Hire by Stage</span>
				</div>
				<div style="padding: 16px;">
					{#if timeToHire?.stages && timeToHire.stages.length > 0}
						<Chart options={timeToHireOptions()} height="280px" />
					{:else}
						<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
							<span class="material-symbols-outlined" style="font-size: 36px;">hourglass_empty</span>
							<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No timing data yet</p>
							<p style="font-size: 11px; margin-top: 4px;">Stage durations appear as candidates progress</p>
						</div>
					{/if}
				</div>
			</div>

			<!-- ROW 4: POSITIONS SUMMARY TABLE -->
			<div class="ink-border" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 16px;">table_chart</span>
					<span>Positions Summary</span>
				</div>
				{#if sortedPositions().length > 0}
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th>Position</th>
									<th>Department</th>
									<th>Candidates</th>
									<th>Avg Match</th>
									<th>Interviews</th>
									<th>Status</th>
									<th>Days Open</th>
								</tr>
							</thead>
							<tbody>
								{#each sortedPositions() as pos}
									<tr>
										<td style="font-weight: 700;">{pos.title || '—'}</td>
										<td>{pos.department || '—'}</td>
										<td style="font-weight: 900;">{pos.candidates ?? 0}</td>
										<td>
											{#if pos.avg_match !== undefined && pos.avg_match !== null}
												<div class="flex items-center gap-2">
													<div class="score-bar" style="width: 60px;">
														<div
															class="score-bar-fill {pos.avg_match >= 70 ? 'score-high' : pos.avg_match >= 40 ? 'score-mid' : 'score-low'}"
															style="width: {pos.avg_match}%;"
														></div>
													</div>
													<span style="font-size: 12px; font-weight: 900;">{pos.avg_match}%</span>
												</div>
											{:else}
												<span style="color: var(--color-on-surface-dim);">—</span>
											{/if}
										</td>
										<td>{pos.interviews ?? 0}</td>
										<td>
											<span class="tag-label" style="{statusTag(pos.status)}; font-size: 9px;">
												{pos.status || 'active'}
											</span>
										</td>
										<td style="font-weight: 700;">{pos.days_open ?? '—'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
						<span class="material-symbols-outlined" style="font-size: 36px;">inventory_2</span>
						<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No positions data yet</p>
						<p style="font-size: 11px; margin-top: 4px;">Create positions to see summary</p>
					</div>
				{/if}
			</div>

		<!-- ROW 5: DIVERSITY OVERVIEW -->
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
				<!-- Gender Distribution -->
				<div class="ink-border" style="background: var(--color-surface-bright);">
					<div class="dark-title-bar flex items-center justify-between">
						<span class="flex items-center gap-2">
							<span class="material-symbols-outlined" style="font-size: 16px;">diversity_3</span>
							<span>Gender Distribution</span>
						</span>
						{#if diversityData?.total_respondents}
							<span style="font-size: 10px; font-weight: 700; opacity: 0.7;">{diversityData.total_respondents} respondents</span>
						{/if}
					</div>
					<div style="padding: 16px;">
						{#if genderChartOptions()}
							<Chart options={genderChartOptions()} height="280px" />
						{:else}
							<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
								<span class="material-symbols-outlined" style="font-size: 36px;">diversity_3</span>
								<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No diversity data yet</p>
								<p style="font-size: 11px; margin-top: 4px;">EEO data appears as candidates self-report</p>
							</div>
						{/if}
					</div>
				</div>

				<!-- Ethnicity Distribution -->
				<div class="ink-border" style="background: var(--color-surface-bright);">
					<div class="dark-title-bar flex items-center justify-between">
						<span class="flex items-center gap-2">
							<span class="material-symbols-outlined" style="font-size: 16px;">groups</span>
							<span>Ethnicity Distribution</span>
						</span>
						{#if diversityData?.total_respondents}
							<span style="font-size: 10px; font-weight: 700; opacity: 0.7;">{diversityData.total_respondents} respondents</span>
						{/if}
					</div>
					<div style="padding: 16px;">
						{#if ethnicityChartOptions()}
							<Chart options={ethnicityChartOptions()} height="280px" />
						{:else}
							<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
								<span class="material-symbols-outlined" style="font-size: 36px;">groups</span>
								<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No ethnicity data yet</p>
								<p style="font-size: 11px; margin-top: 4px;">EEO data appears as candidates self-report</p>
							</div>
						{/if}
					</div>
				</div>
			</div>

		<!-- ROW 6: HIRING ACTIVITY HEATMAP -->
			<div class="ink-border mt-6" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 16px;">calendar_month</span>
					<span>Hiring Activity (Last 12 Months)</span>
				</div>
				<div style="padding: 16px; position: relative;">
					{#if heatmapData?.days && heatmapData.days.length > 0}
						{@const grid = buildHeatmapGrid()}
						<div style="overflow-x: auto;">
							<div class="flex gap-0" style="min-width: 700px;">
								<!-- Day labels -->
								<div class="flex flex-col gap-0" style="margin-right: 4px; padding-top: 2px;">
									{#each dayLabels as label}
										<div style="height: 13px; font-size: 8px; font-weight: 700; color: var(--color-on-surface-dim); text-transform: uppercase; display: flex; align-items: center; justify-content: flex-end; width: 24px;">
											{label}
										</div>
									{/each}
								</div>
								<!-- Weeks grid -->
								{#each grid.weeks as week}
									<div class="flex flex-col gap-0">
										{#each week as day}
											<div
												style="width: 11px; height: 11px; margin: 1px; background: {day.isFuture ? 'transparent' : heatmapColor(day.count, grid.maxCount)}; border: {day.isFuture ? 'none' : '1px solid var(--color-outline-variant)'}; cursor: {day.isFuture ? 'default' : 'pointer'};"
												onmouseenter={(e) => {
													if (!day.isFuture) {
														heatmapTooltip = { show: true, x: e.clientX, y: e.clientY, date: day.date, count: day.count };
													}
												}}
												onmouseleave={() => { heatmapTooltip = { ...heatmapTooltip, show: false }; }}
											></div>
										{/each}
									</div>
								{/each}
							</div>
						</div>
						<!-- Legend -->
						<div class="flex items-center gap-2 mt-3" style="font-size: 9px; font-weight: 700; text-transform: uppercase; color: var(--color-on-surface-dim);">
							<span>Less</span>
							<div style="width: 11px; height: 11px; background: var(--color-surface-highest); border: 1px solid var(--color-outline-variant);"></div>
							<div style="width: 11px; height: 11px; background: rgba(0,117,24,0.2); border: 1px solid var(--color-outline-variant);"></div>
							<div style="width: 11px; height: 11px; background: rgba(0,117,24,0.4); border: 1px solid var(--color-outline-variant);"></div>
							<div style="width: 11px; height: 11px; background: rgba(0,117,24,0.65); border: 1px solid var(--color-outline-variant);"></div>
							<div style="width: 11px; height: 11px; background: rgba(0,117,24,0.9); border: 1px solid var(--color-outline-variant);"></div>
							<span>More</span>
						</div>
						<!-- Tooltip -->
						{#if heatmapTooltip.show}
							<div style="position: fixed; left: {heatmapTooltip.x + 12}px; top: {heatmapTooltip.y - 36}px; background: var(--color-on-surface); color: var(--color-surface); padding: 4px 10px; font-size: 10px; font-weight: 700; font-family: 'Space Grotesk'; z-index: 999; pointer-events: none; white-space: nowrap;">
								{heatmapTooltip.date}: {heatmapTooltip.count} event{heatmapTooltip.count !== 1 ? 's' : ''}
							</div>
						{/if}
					{:else}
						<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
							<span class="material-symbols-outlined" style="font-size: 36px;">calendar_month</span>
							<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No activity data yet</p>
							<p style="font-size: 11px; margin-top: 4px;">Activity tracked as candidates move through pipeline</p>
						</div>
					{/if}
				</div>
			</div>

		<!-- ROW 7: PIPELINE SANKEY FLOW -->
			<div class="ink-border mt-6" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 16px;">account_tree</span>
					<span>Pipeline Flow (Sankey)</span>
				</div>
				<div style="padding: 16px;">
					{#if sankeyOptions()}
						<Chart options={sankeyOptions()} height="340px" />
					{:else}
						<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
							<span class="material-symbols-outlined" style="font-size: 36px;">account_tree</span>
							<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No pipeline flow data yet</p>
							<p style="font-size: 11px; margin-top: 4px;">Stage transitions appear as candidates progress</p>
						</div>
					{/if}
				</div>
			</div>

		<!-- ROW 8: TEAM LEADERBOARD -->
			<div class="ink-border mt-6" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 16px;">leaderboard</span>
					<span>Team Leaderboard</span>
				</div>
				{#if leaderboardData?.members && leaderboardData.members.length > 0}
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th style="width: 40px;">#</th>
									<th>Name</th>
									<th>Reviews</th>
									<th>Interviews</th>
									<th>Notes</th>
									<th>Score</th>
								</tr>
							</thead>
							<tbody>
								{#each leaderboardData.members as member, i}
									<tr>
										<td>
											<span style="display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; font-size: 11px; font-weight: 900; border-radius: 50%;
												{i === 0 ? 'background: var(--color-accent, #c96342); color: #fff; border: 1px solid var(--color-border, #d8d5cc);' : i === 1 ? 'background: var(--color-surface-highest); border: 1px solid var(--color-border, #d8d5cc);' : i === 2 ? 'background: var(--color-surface-highest); border: 2px solid var(--color-outline-variant);' : 'color: var(--color-on-surface-dim);'}">
												{i + 1}
											</span>
										</td>
										<td>
											<div class="flex items-center gap-2">
												<div style="width: 28px; height: 28px; background: var(--color-primary-container); color: var(--color-on-surface); display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 11px; flex-shrink: 0; border: 2px solid var(--color-on-surface);">
													{(member.display_name || '?')[0].toUpperCase()}
												</div>
												<span style="font-weight: 700;">{member.display_name || 'Unknown'}</span>
											</div>
										</td>
										<td style="font-weight: 900;">{member.reviews || 0}</td>
										<td style="font-weight: 900;">{member.interviews || 0}</td>
										<td style="font-weight: 900;">{member.notes || 0}</td>
										<td>
											<span style="font-size: 14px; font-weight: 900; color: var(--color-primary);">
												{member.score || 0}
											</span>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
						<span class="material-symbols-outlined" style="font-size: 36px;">leaderboard</span>
						<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No team data yet</p>
						<p style="font-size: 11px; margin-top: 4px;">Activity is tracked as team members review candidates</p>
					</div>
				{/if}
			</div>

		<!-- Org-Wide Interviewer Calibration -->
			{#if orgCalibration.length > 0}
				<div class="ink-border mt-6" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">
						<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">balance</span>
						Interviewer Calibration (Org-Wide)
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
								{#each orgCalibration as cal}
									<tr style="border-bottom: 1px solid var(--color-outline);">
										<td style="padding: 6px 8px; font-weight: 700;">{cal.interviewer_name}</td>
										<td style="padding: 6px 8px; text-align: center;">{cal.avg_score?.toFixed?.(1) || '—'}</td>
										<td style="padding: 6px 8px; text-align: center;">{cal.std_dev?.toFixed?.(2) || '—'}</td>
										<td style="padding: 6px 8px; text-align: center;">{cal.scorecard_count}</td>
										<td style="padding: 6px 8px; text-align: center; font-weight: 700; color: {cal.harshness_index < 0.9 ? 'var(--color-error, #c4571a)' : cal.harshness_index > 1.1 ? '#3a8a4f' : 'inherit'};">{cal.harshness_index?.toFixed?.(2) || '—'}x</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}

			<!-- Flag Distribution -->
			{#if flagDistribution.totals && (flagDistribution.totals.red || flagDistribution.totals.amber || flagDistribution.totals.green)}
				<div class="ink-border mt-6" style="background: var(--color-surface);">
					<div class="dark-title-bar" style="font-size: 11px;">
						<span class="material-symbols-outlined" style="font-size: 14px; vertical-align: middle;">flag</span>
						Candidate Flag Distribution
					</div>
					<div class="p-3">
						<div class="flex gap-4 mb-3">
							<div style="text-align: center;">
								<div style="font-size: 24px; font-weight: 900; color: #ff3b30;">{flagDistribution.totals.red || 0}</div>
								<div style="font-size: 9px; text-transform: uppercase; font-weight: 700;">Red Flags</div>
							</div>
							<div style="text-align: center;">
								<div style="font-size: 24px; font-weight: 900; color: var(--color-warning, #c98c2a);">{flagDistribution.totals.amber || 0}</div>
								<div style="font-size: 9px; text-transform: uppercase; font-weight: 700;">Amber Flags</div>
							</div>
							<div style="text-align: center;">
								<div style="font-size: 24px; font-weight: 900; color: #3a8a4f;">{flagDistribution.totals.green || 0}</div>
								<div style="font-size: 9px; text-transform: uppercase; font-weight: 700;">Green Flags</div>
							</div>
						</div>
						{#each Object.entries(flagDistribution.distribution.red || {}) as [cat, cnt]}
							<div class="flex items-center gap-2 mb-1">
								<span style="width: 8px; height: 8px; background: #ff3b30; display: inline-block; border: 1px solid var(--color-on-surface);"></span>
								<span style="font-size: 10px; font-weight: 700; text-transform: uppercase; min-width: 120px;">{cat.replace('_', ' ')}</span>
								<span style="font-size: 10px;">{cnt}</span>
							</div>
						{/each}
						{#each Object.entries(flagDistribution.distribution.amber || {}) as [cat, cnt]}
							<div class="flex items-center gap-2 mb-1">
								<span style="width: 8px; height: 8px; background: var(--color-warning, #c98c2a); display: inline-block; border: 1px solid var(--color-on-surface); border-radius: 50%;"></span>
								<span style="font-size: 10px; font-weight: 700; text-transform: uppercase; min-width: 120px;">{cat.replace('_', ' ')}</span>
								<span style="font-size: 10px;">{cnt}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

		<!-- ROW 9: EMAIL SEQUENCES / AUTOMATION -->
			<div class="ink-border mt-6" style="background: var(--color-surface-bright);">
				<div class="dark-title-bar flex items-center justify-between">
					<span class="flex items-center gap-2">
						<span class="material-symbols-outlined" style="font-size: 16px;">mail</span>
						<span>Email Sequences</span>
					</span>
					<button
						onclick={() => showCreateSequence = true}
						style="padding: 3px 10px; border: 1px solid rgba(255,255,255,0.4); background: transparent; color: var(--color-surface); font-family: 'Space Grotesk'; font-size: 9px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; cursor: pointer;"
					>
						+ Create Sequence
					</button>
				</div>
				{#if sequencesLoading}
					<div class="p-4">
						{#each [1, 2] as _}
							<div class="skeleton mb-3" style="height: 50px;"></div>
						{/each}
					</div>
				{:else if sequences.length === 0}
					<div class="flex flex-col items-center justify-center py-12" style="color: var(--color-on-surface-dim);">
						<span class="material-symbols-outlined" style="font-size: 36px;">forward_to_inbox</span>
						<p style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 8px;">No email sequences yet</p>
						<p style="font-size: 11px; margin-top: 4px;">Create automated email sequences for candidate outreach</p>
					</div>
				{:else}
					<div style="overflow-x: auto;">
						<table class="data-table">
							<thead>
								<tr>
									<th>Name</th>
									<th>Steps</th>
									<th>Enrolled</th>
									<th>Status</th>
								</tr>
							</thead>
							<tbody>
								{#each sequences as seq}
									<tr>
										<td style="font-weight: 900;">{seq.name || '--'}</td>
										<td>{seq.steps_count ?? seq.steps?.length ?? 0}</td>
										<td style="font-weight: 700;">{seq.enrolled_count ?? seq.enrolled ?? 0}</td>
										<td>
											<span class="tag-label" style="font-size: 8px; background: {(seq.status || 'active') === 'active' ? 'var(--color-primary)' : 'var(--color-on-surface-dim)'}; color: white;">
												{(seq.status || 'active').toUpperCase()}
											</span>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>

		</div>
	{/if}

	{/if}<!-- /overview -->

	<!-- ── V2 LAZY-MOUNTED DASHBOARDS ── -->
	{#if v2Tab === 'funnel'}     <FunnelDashboard />        {/if}
	{#if v2Tab === 'time'}       <TimeMetricsDashboard />   {/if}
	{#if v2Tab === 'recruiter'}  <RecruiterScorecard />     {/if}
	{#if v2Tab === 'dei'}        <DEIDashboard />           {/if}
	{#if v2Tab === 'cost'}       <CostPerHireDashboard />   {/if}
	{#if v2Tab === 'qoh'}        <QualityOfHireDashboard /> {/if}
	{#if v2Tab === 'predictive'} <PredictiveDashboard {positions} /> {/if}
	{#if v2Tab === 'competency'} <CompetencyDashboard /> {/if}

	<!-- ── Source ROI tab ── -->
	{#if v2Tab === 'sourceroi'}
		<div class="warm-card section-animate">
			<div class="warm-card-header">
				<span class="flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 18px; color: #c96342;">payments</span>
					<span class="warm-card-title">Cost-per-hire by source</span>
				</span>
				{#if sourceRoi?._mock}
					<span style="font-size: 11px; color: #a8a29e;">Sample data — backend endpoint unavailable</span>
				{/if}
			</div>
			<div style="padding: 18px;">
				{#if sourceRoiLoading}
					<div class="skeleton" style="height: 320px;"></div>
				{:else if sourceRoiOptions()}
					<Chart options={sourceRoiOptions()} height="340px" />
					<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4">
						{#each sourceRoi.sources as s}
							<div style="background: #faf9f5; border: 1px solid #e8e6dc; border-radius: 10px; padding: 12px;">
								<div style="font-family: 'Inter', sans-serif; font-size: 11px; color: #8a8a82; text-transform: uppercase; letter-spacing: 0.06em;">{s.label}</div>
								<div style="font-family: 'Tiempos', Georgia, serif; font-size: 20px; color: #2d2a26; margin-top: 4px;">${s.cost_per_hire.toLocaleString()}</div>
								<div style="font-size: 11px; color: #6b6b66; margin-top: 2px;">{s.hires} hire{s.hires === 1 ? '' : 's'}</div>
							</div>
						{/each}
					</div>
				{:else}
					<div class="warm-empty">
						<span class="material-symbols-outlined" style="font-size: 36px;">payments</span>
						<p class="warm-empty-title">No source data yet</p>
						<p class="warm-empty-sub">Sources are tracked when candidates are added</p>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- ── Predictive (lite) tab ── -->
	{#if v2Tab === 'predict2'}
		<div class="warm-card section-animate" style="max-width: 720px;">
			<div class="warm-card-header">
				<span class="flex items-center gap-2">
					<span class="material-symbols-outlined" style="font-size: 18px; color: #d4a056;">insights</span>
					<span class="warm-card-title">Predicted time-to-fill</span>
				</span>
			</div>
			<div style="padding: 28px;">
				{#if predictLoading}
					<div class="skeleton" style="height: 80px;"></div>
				{:else if predictDays !== null && predictDays > 0}
					<div style="font-family: 'Tiempos', Georgia, serif; font-size: 17px; line-height: 1.5; color: #2d2a26;">
						Based on the last <strong>{predictHires}</strong> hire{predictHires === 1 ? '' : 's'}, a typical position will fill in
						<span style="color: #c96342; font-weight: 600;">~{predictDays} days</span>.
					</div>
					<div style="display: flex; align-items: baseline; gap: 12px; margin-top: 18px;">
						<div style="font-family: 'Tiempos', Georgia, serif; font-size: 56px; line-height: 1; color: #c96342;">{predictDays}</div>
						<div style="font-size: 13px; color: #6b6b66;">days median estimate</div>
					</div>
				{:else}
					<div style="font-family: 'Inter', sans-serif; font-size: 14px; color: #6b6b66;">
						Not enough data yet. Close at least 3 positions to start generating fill-time predictions.
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- ── Comparative tab ── -->
	{#if v2Tab === 'compare'}
		<div class="section-animate">
			<div class="warm-card mb-4">
				<div class="warm-card-header">
					<span class="flex items-center gap-2">
						<span class="material-symbols-outlined" style="font-size: 18px; color: #7a8c5c;">compare_arrows</span>
						<span class="warm-card-title">This quarter vs last quarter</span>
					</span>
					{#if compareData?._mock}
						<span style="font-size: 11px; color: #a8a29e;">Estimated — backend endpoint unavailable</span>
					{/if}
				</div>
				<div style="padding: 4px;">
					{#if compareLoading}
						<div class="p-4"><div class="skeleton" style="height: 220px;"></div></div>
					{:else if compareData}
						{@const c = compareData.current}
						{@const p = compareData.previous}
						<div class="grid grid-cols-1 md:grid-cols-4 gap-3 p-4">
							{#each [
								{ label: 'Positions opened', cur: c.positions_opened, prev: p.positions_opened, lower: false },
								{ label: 'CVs ingested',     cur: c.cvs_ingested,     prev: p.cvs_ingested,     lower: false },
								{ label: 'Hires made',       cur: c.hires_made,       prev: p.hires_made,       lower: false },
								{ label: 'Avg time-to-hire', cur: c.avg_time_to_hire, prev: p.avg_time_to_hire, lower: true, suffix: 'd' },
							] as row}
								<div style="background: #ffffff; border: 1px solid #e8e6dc; border-radius: 12px; padding: 16px;">
									<div style="font-family: 'Inter', sans-serif; font-size: 11px; color: #8a8a82; text-transform: uppercase; letter-spacing: 0.06em;">{row.label}</div>
									<div style="display: flex; align-items: baseline; gap: 10px; margin-top: 8px;">
										<div style="font-family: 'Tiempos', Georgia, serif; font-size: 26px; color: #2d2a26;">{row.cur}{row.suffix || ''}</div>
										<div style="font-size: 12px; font-weight: 600; color: {deltaColor(row.cur, row.prev, row.lower)};">{delta(row.cur, row.prev)}</div>
									</div>
									<div style="font-size: 11px; color: #a8a29e; margin-top: 4px;">prev: {row.prev}{row.suffix || ''}</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<!-- Create Sequence Modal -->
{#if showCreateSequence}
	<div style="position: fixed; inset: 0; background: rgba(56,56,50,0.7); z-index: 100; display: flex; align-items: start; justify-content: center; padding: 40px 20px; overflow-y: auto;"
		onclick={(e) => { if (e.target === e.currentTarget) showCreateSequence = false; }}>
		<div class="ink-border stamp-shadow animate-fade-up" style="background: var(--color-surface); width: 640px; max-height: 85vh; overflow-y: auto;">
			<div class="dark-title-bar flex items-center justify-between">
				<span>Create Email Sequence</span>
				<button onclick={() => showCreateSequence = false} style="background: none; border: none; color: var(--color-surface); cursor: pointer; font-size: 16px; font-weight: 900;">X</button>
			</div>
			<div class="p-5">
				<!-- Name -->
				<div class="mb-4">
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Sequence Name</label>
					<input
						type="text"
						bind:value={newSequence.name}
						placeholder="e.g. Senior Engineer Outreach"
						style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 12px; font-weight: 700; background: var(--color-surface-bright);"
					/>
				</div>

				<!-- Position -->
				<div class="mb-4">
					<label class="tag-label" style="font-size: 8px; display: block; margin-bottom: 4px;">Position (optional)</label>
					<select
						bind:value={newSequence.position_slug}
						style="width: 100%; padding: 8px 12px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; text-transform: uppercase; background: var(--color-surface-bright);"
					>
						<option value="">No position</option>
						{#each positions as p}
							<option value={p.slug}>{p.title}</option>
						{/each}
					</select>
				</div>

				<!-- Steps -->
				<div class="mb-4">
					<div class="flex items-center justify-between mb-2">
						<label class="tag-label" style="font-size: 8px;">Steps</label>
						<button
							onclick={addSequenceStep}
							style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em; padding: 3px 10px; border: 2px solid var(--color-on-surface); background: var(--color-surface-bright); cursor: pointer; font-family: 'Space Grotesk';"
						>+ Add Step</button>
					</div>

					{#each newSequence.steps as step, i}
						<div class="mb-3 ink-border p-3" style="background: var(--color-surface-bright); position: relative;">
							<div class="flex items-center justify-between mb-2">
								<span style="font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em;">Step {i + 1}</span>
								{#if newSequence.steps.length > 1}
									<button
										onclick={() => removeSequenceStep(i)}
										style="background: none; border: none; color: var(--color-error); cursor: pointer; font-size: 14px; font-weight: 900;"
									>X</button>
								{/if}
							</div>
							<div class="flex gap-2 mb-2">
								<div style="width: 100px;">
									<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 2px; color: var(--color-on-surface-dim);">Delay (days)</label>
									<input
										type="number"
										bind:value={step.delay_days}
										min="0"
										style="width: 100%; padding: 6px 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; background: var(--color-surface);"
									/>
								</div>
								<div style="flex: 1;">
									<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 2px; color: var(--color-on-surface-dim);">Subject</label>
									<input
										type="text"
										bind:value={step.subject}
										placeholder="Email subject..."
										style="width: 100%; padding: 6px 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; font-weight: 700; background: var(--color-surface);"
									/>
								</div>
							</div>
							<div>
								<label style="font-size: 8px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 2px; color: var(--color-on-surface-dim);">Body Template</label>
								<textarea
									bind:value={step.body}
									placeholder="Email body... use {{name}}, {{position}} for variables"
									rows="3"
									style="width: 100%; padding: 6px 8px; border: 2px solid var(--color-on-surface); font-family: 'Space Grotesk'; font-size: 11px; background: var(--color-surface); resize: vertical;"
								></textarea>
							</div>
						</div>
					{/each}
				</div>

				<!-- Submit -->
				<button
					class="send-btn"
					style="width: 100%; padding: 10px; font-size: 12px;"
					disabled={creatingSequence || !newSequence.name.trim()}
					onclick={createSequence}
				>
					{#if creatingSequence}
						<div class="typing-indicator" style="display: inline-flex; justify-content: center;"><span></span><span></span><span></span></div>
					{:else}
						Create Sequence
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Page wrapper warm bg override */
	:global(body) { background: #faf9f5; }

	/* ── Page header ── */
	.page-title {
		font-family: 'Tiempos', 'Tiempos Headline', 'Source Serif Pro', Georgia, serif;
		font-size: 28px;
		font-weight: 500;
		letter-spacing: -0.01em;
		color: #2d2a26;
		line-height: 1.2;
		text-transform: none;
	}
	.page-subtitle {
		font-family: 'Inter', sans-serif;
		font-size: 14px;
		color: #6b6b66;
		margin-top: 2px;
		text-transform: none;
		letter-spacing: 0;
	}

	/* ── Buttons ── */
	.warm-btn-primary {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: #c96342;
		color: #ffffff;
		border: 1px solid #c96342;
		border-radius: 8px;
		padding: 8px 16px;
		font-family: 'Inter', sans-serif;
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
		transition: background 0.15s;
	}
	.warm-btn-primary:hover { background: #b35535; border-color: #b35535; }
	.warm-btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

	.warm-btn-outline {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: #ffffff;
		color: #2d2a26;
		border: 1px solid #e8e6dc;
		border-radius: 8px;
		padding: 8px 16px;
		font-family: 'Inter', sans-serif;
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
		transition: border-color 0.15s, background 0.15s;
	}
	.warm-btn-outline:hover { border-color: #c96342; background: #faf9f5; }

	.warm-btn-sm {
		padding: 6px 12px;
		font-size: 12px;
		border-radius: 6px;
	}

	/* ── Tabs (underline style) ── */
	.v2-tab-strip {
		display: flex;
		gap: 4px;
		margin-bottom: 22px;
		border-bottom: 1px solid #e8e6dc;
		overflow-x: auto;
		position: sticky;
		top: 0;
		z-index: 30;
		background: #faf9f5;
	}
	.v2-tab {
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		padding: 10px 14px;
		font-family: 'Inter', sans-serif;
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0;
		text-transform: none;
		color: #6b6b66;
		cursor: pointer;
		white-space: nowrap;
		transition: color 0.15s, border-color 0.15s;
		margin-bottom: -1px;
	}
	.v2-tab:hover {
		color: #2d2a26;
		border-bottom-color: #e8e6dc;
	}
	.v2-tab.active {
		color: #c96342;
		border-bottom-color: #c96342;
		font-weight: 600;
	}

	/* ── Warm cards ── */
	.warm-card {
		background: #ffffff;
		border: 1px solid #e8e6dc;
		border-radius: 12px;
		box-shadow: 0 1px 2px rgba(45, 42, 38, 0.04);
		overflow: hidden;
	}
	.warm-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 18px;
		background: #f4f3ee;
		border-bottom: 1px solid #e8e6dc;
	}
	.warm-card-title {
		font-family: 'Inter', sans-serif;
		font-size: 14px;
		font-weight: 600;
		color: #2d2a26;
		text-transform: none;
		letter-spacing: 0;
	}

	/* ── KPI cards ── */
	.kpi-card {
		background: #ffffff;
		border: 1px solid #e8e6dc;
		border-radius: 12px;
		padding: 18px 20px;
		box-shadow: 0 1px 2px rgba(45, 42, 38, 0.04);
	}
	.kpi-value {
		font-family: 'Tiempos', 'Source Serif Pro', Georgia, serif;
		font-size: 32px;
		font-weight: 500;
		line-height: 1.1;
		color: #2d2a26;
		letter-spacing: -0.01em;
	}
	.kpi-meta {
		font-family: 'Inter', sans-serif;
		font-size: 12px;
		font-weight: 500;
		margin-top: 4px;
	}
	.kpi-label {
		font-family: 'Inter', sans-serif;
		font-size: 11px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #8a8a82;
		margin-top: 8px;
	}

	/* ── Empty state ── */
	.warm-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48px 16px;
		color: #a8a29e;
	}
	.warm-empty-title {
		font-family: 'Inter', sans-serif;
		font-size: 14px;
		font-weight: 500;
		color: #6b6b66;
		margin-top: 10px;
		text-transform: none;
		letter-spacing: 0;
	}
	.warm-empty-sub {
		font-family: 'Inter', sans-serif;
		font-size: 12px;
		color: #a8a29e;
		margin-top: 4px;
	}
</style>
