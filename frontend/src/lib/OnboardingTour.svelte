<script>
	/** OnboardingTour — first-run interactive overlay (Claude warm theme).
	 *  Shown when localStorage.pulse_onboarded !== '1'.
	 *  Highlights 4 nav targets with spotlight cutout + tooltip card.
	 */
	import { onMount, tick } from 'svelte';

	let active = $state(false);
	let stepIdx = $state(0);
	let rect = $state(null); // DOMRect of current target
	let tooltipPos = $state({ top: 0, left: 0, placement: 'bottom' });

	const STEPS = [
		{
			selector: 'a.nav-item[href="/"]',
			title: 'Positions',
			body: 'This is where you create hiring roles. Each position is a workspace with its JD, pipeline, and analytics.'
		},
		{
			selector: 'a.nav-item[href="/candidates"]',
			title: 'CV repo',
			body: 'Upload candidate CVs here — bulk drag-drop supported. Everything is parsed, embedded, and searchable.'
		},
		{
			selector: 'a.nav-item[href="/chat"]',
			title: 'Copilot',
			body: 'Ask anything — chat with your candidate database. Natural language, full memory, tool-augmented.'
		},
		{
			selector: '.pulse-feed-btn, [data-tour="pulse-feed"], .nav-right button',
			title: 'Activity feed',
			body: 'Live activity stream from agents and the pipeline. Click the bell-like button in the top-right anytime.'
		}
	];

	let currentStep = $derived(STEPS[stepIdx] || STEPS[0]);
	let totalSteps = STEPS.length;

	onMount(() => {
		if (typeof window === 'undefined') return;
		try {
			if (localStorage.getItem('pulse_onboarded') === '1') return;
		} catch { /* ignore */ }
		// Skip on public routes
		const path = window.location.pathname;
		if (['/login', '/register', '/careers'].some(p => path === p || path.startsWith(p + '/'))) return;
		// Defer briefly so layout is mounted
		setTimeout(() => { active = true; measure(); }, 600);

		const onResize = () => measure();
		window.addEventListener('resize', onResize);
		window.addEventListener('scroll', onResize, true);
		return () => {
			window.removeEventListener('resize', onResize);
			window.removeEventListener('scroll', onResize, true);
		};
	});

	$effect(() => {
		// re-measure when step changes
		if (active) {
			stepIdx; // dep
			tick().then(measure);
		}
	});

	function measure() {
		if (!active) return;
		const sel = currentStep.selector.split(',').map(s => s.trim());
		let el = null;
		for (const s of sel) {
			el = document.querySelector(s);
			if (el) break;
		}
		if (!el) { rect = null; return; }
		const r = el.getBoundingClientRect();
		rect = { top: r.top, left: r.left, width: r.width, height: r.height };
		// Tooltip placement — below by default, above if near bottom
		const tipHeight = 170;
		const tipWidth = 320;
		const margin = 12;
		let placement = 'bottom';
		let top = r.bottom + margin;
		if (top + tipHeight > window.innerHeight) {
			placement = 'top';
			top = r.top - tipHeight - margin;
		}
		let left = r.left + r.width / 2 - tipWidth / 2;
		left = Math.max(12, Math.min(left, window.innerWidth - tipWidth - 12));
		tooltipPos = { top, left, placement };
	}

	function next() {
		if (stepIdx < totalSteps - 1) stepIdx += 1;
		else finish();
	}
	function back() {
		if (stepIdx > 0) stepIdx -= 1;
	}
	function finish() {
		try { localStorage.setItem('pulse_onboarded', '1'); } catch { /* ignore */ }
		active = false;
	}
	function skip() { finish(); }

	// Spotlight padding
	const PAD = 6;
</script>

{#if active}
	<div class="tour-root" role="dialog" aria-label="Onboarding tour">
		{#if rect}
			<!-- 4-piece dim overlay creating spotlight cutout -->
			<div class="dim" style="top:0; left:0; right:0; height:{Math.max(0, rect.top - PAD)}px"></div>
			<div class="dim" style="top:{Math.max(0, rect.top - PAD)}px; left:0; width:{Math.max(0, rect.left - PAD)}px; height:{rect.height + PAD * 2}px"></div>
			<div class="dim" style="top:{Math.max(0, rect.top - PAD)}px; left:{rect.left + rect.width + PAD}px; right:0; height:{rect.height + PAD * 2}px"></div>
			<div class="dim" style="top:{rect.top + rect.height + PAD}px; left:0; right:0; bottom:0"></div>

			<!-- spotlight ring -->
			<div
				class="spotlight"
				style="top:{rect.top - PAD}px; left:{rect.left - PAD}px; width:{rect.width + PAD * 2}px; height:{rect.height + PAD * 2}px"
			></div>
		{:else}
			<div class="dim" style="inset:0"></div>
		{/if}

		<div
			class="tip"
			style="top:{tooltipPos.top}px; left:{tooltipPos.left}px"
		>
			<div class="tip-step">Step {stepIdx + 1} of {totalSteps}</div>
			<div class="tip-title">{currentStep.title}</div>
			<div class="tip-body">{currentStep.body}</div>

			<div class="tip-progress">
				{#each STEPS as _, i}
					<span class="dot" class:active={i === stepIdx} class:done={i < stepIdx}></span>
				{/each}
			</div>

			<div class="tip-actions">
				<button class="t-skip" onclick={skip}>Skip</button>
				<div class="t-spacer"></div>
				{#if stepIdx > 0}
					<button class="t-back" onclick={back}>Back</button>
				{/if}
				<button class="t-next" onclick={next}>
					{stepIdx === totalSteps - 1 ? 'Done' : 'Next'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.tour-root {
		position: fixed;
		inset: 0;
		z-index: 9999;
		pointer-events: none;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}
	.dim {
		position: fixed;
		background: rgba(0, 0, 0, 0.65);
		pointer-events: auto;
		transition: opacity 0.2s ease;
	}
	.spotlight {
		position: fixed;
		border-radius: 12px;
		box-shadow:
			0 0 0 2px var(--color-accent, #c96342),
			0 0 0 6px rgba(201, 99, 66, 0.25),
			0 8px 28px rgba(0, 0, 0, 0.35);
		pointer-events: none;
		transition: top 0.22s ease, left 0.22s ease, width 0.22s ease, height 0.22s ease;
		animation: pulse-ring 1.8s ease-in-out infinite;
	}
	@keyframes pulse-ring {
		0%, 100% { box-shadow: 0 0 0 2px var(--color-accent, #c96342), 0 0 0 6px rgba(201, 99, 66, 0.25), 0 8px 28px rgba(0, 0, 0, 0.35); }
		50%      { box-shadow: 0 0 0 2px var(--color-accent, #c96342), 0 0 0 10px rgba(201, 99, 66, 0.10), 0 8px 28px rgba(0, 0, 0, 0.35); }
	}
	.tip {
		position: fixed;
		width: 320px;
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
		padding: 18px 18px 14px;
		pointer-events: auto;
		color: var(--color-ink, #2c2c2c);
		animation: tip-in 0.22s ease;
	}
	@keyframes tip-in {
		from { opacity: 0; transform: translateY(6px); }
		to   { opacity: 1; transform: translateY(0); }
	}
	.tip-step {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-muted, #6f6e69);
		margin-bottom: 6px;
		font-weight: 600;
	}
	.tip-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.01em;
		margin-bottom: 6px;
		color: var(--color-ink, #2c2c2c);
	}
	.tip-body {
		font-size: 13.5px;
		line-height: 1.5;
		color: var(--color-ink-soft, #4a4a48);
		margin-bottom: 14px;
	}
	.tip-progress {
		display: flex;
		gap: 5px;
		margin-bottom: 14px;
	}
	.dot {
		width: 18px;
		height: 4px;
		border-radius: 2px;
		background: var(--color-border, #e8e6dd);
		transition: background 0.2s;
	}
	.dot.active { background: var(--color-accent, #c96342); }
	.dot.done   { background: var(--color-accent-soft, #fdebe1); }

	.tip-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.t-spacer { flex: 1; }
	.t-skip, .t-back, .t-next {
		font-family: inherit;
		font-size: 13px;
		font-weight: 500;
		padding: 7px 14px;
		border-radius: 999px;
		cursor: pointer;
		border: 1px solid transparent;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}
	.t-skip {
		background: transparent;
		color: var(--color-muted, #6f6e69);
		border-color: transparent;
	}
	.t-skip:hover { color: var(--color-ink, #2c2c2c); background: var(--color-surface-warm, #f4f3ee); }
	.t-back {
		background: transparent;
		color: var(--color-ink-soft, #4a4a48);
		border-color: var(--color-border, #e8e6dd);
	}
	.t-back:hover { background: var(--color-surface-warm, #f4f3ee); }
	.t-next {
		background: var(--color-accent, #c96342);
		color: #fff;
		border-color: var(--color-accent, #c96342);
	}
	.t-next:hover { filter: brightness(1.05); }
</style>
