<script>
	/** Confetti — celebration particle burst.
	 *  Trigger: window.dispatchEvent(new CustomEvent('pulse-celebrate'))
	 *  Renders 60 colored particles falling for 3s with rotation, then fades.
	 *  Pure CSS animation, no canvas, no deps.
	 */
	import { onMount } from 'svelte';

	const PALETTE = [
		'#c96342', // coral / Claude accent
		'#e07a5c', // light coral
		'#3a8a4f', // green
		'#3aa75a', // lighter green
		'#d99a3a', // amber
		'#f0c674', // light amber
		'#f5efe1', // warm cream
		'#faf2ed'  // pale cream
	];

	let bursts = $state([]); // each = {id, particles:[]}
	let nextId = 0;

	onMount(() => {
		if (typeof window === 'undefined') return;
		const handler = () => fire();
		window.addEventListener('pulse-celebrate', handler);
		return () => window.removeEventListener('pulse-celebrate', handler);
	});

	function fire() {
		const id = ++nextId;
		const particles = [];
		for (let i = 0; i < 60; i++) {
			particles.push({
				i,
				color: PALETTE[i % PALETTE.length],
				left: Math.random() * 100, // vw %
				delay: Math.random() * 0.4, // s
				dur: 2.4 + Math.random() * 0.9, // s
				drift: (Math.random() - 0.5) * 200, // px sway
				rot: Math.random() * 720 - 360, // deg
				size: 7 + Math.random() * 7, // px
				shape: Math.random() < 0.5 ? 'rect' : 'circle'
			});
		}
		bursts = [...bursts, { id, particles }];
		// Clean up after 3.6s
		setTimeout(() => {
			bursts = bursts.filter(b => b.id !== id);
		}, 3600);
	}
</script>

{#if bursts.length > 0}
	<div class="confetti-root" aria-hidden="true">
		{#each bursts as b (b.id)}
			<div class="burst">
				{#each b.particles as p (p.i)}
					<span
						class="p {p.shape}"
						style="
							--c: {p.color};
							--left: {p.left}vw;
							--delay: {p.delay}s;
							--dur: {p.dur}s;
							--drift: {p.drift}px;
							--rot: {p.rot}deg;
							--size: {p.size}px;
						"
					></span>
				{/each}
			</div>
		{/each}
	</div>
{/if}

<style>
	.confetti-root {
		position: fixed;
		inset: 0;
		pointer-events: none;
		z-index: 10000;
		overflow: hidden;
	}
	.burst { position: absolute; inset: 0; }
	.p {
		position: absolute;
		top: -20px;
		left: var(--left);
		width: var(--size);
		height: var(--size);
		background: var(--c);
		opacity: 0;
		transform: translate3d(0, 0, 0) rotate(0deg);
		animation: fall var(--dur) cubic-bezier(0.25, 0.7, 0.5, 1) var(--delay) forwards;
		will-change: transform, opacity;
	}
	.p.circle { border-radius: 50%; }
	.p.rect   { border-radius: 1px; }
	@keyframes fall {
		0%   { opacity: 0; transform: translate3d(0, -20px, 0) rotate(0deg); }
		8%   { opacity: 1; }
		80%  { opacity: 1; }
		100% {
			opacity: 0;
			transform: translate3d(var(--drift), 100vh, 0) rotate(var(--rot));
		}
	}
</style>
