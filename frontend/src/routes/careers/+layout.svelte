<script>
	import '../../app.css';
	let { children } = $props();
</script>

<div class="careers-layout">
	<!-- Minimal Header -->
	<header class="careers-header">
		<a href="/careers" class="careers-logo">
			<div class="logo-icon">
				<span class="material-symbols-outlined" style="font-size: 20px; color: var(--color-accent, #c96342);">work</span>
			</div>
			<span class="logo-text">City Agent Pulse</span>
			<span class="logo-divider"></span>
			<span class="logo-sub">Careers</span>
		</a>
	</header>

	<main class="careers-main">
		{@render children()}
	</main>

	<footer class="careers-footer">
		<span>City Agent Pulse — People · Updates · Lifecycle · Sourcing · Engagement</span>
		<span class="careers-footer-dot"></span>
		<span>Equal Opportunity Employer</span>
	</footer>
</div>

<style>
	.careers-layout {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		background: #fafaf5;
	}

	.careers-header {
		display: flex;
		align-items: center;
		padding: 0 2rem;
		height: 56px;
		background: var(--color-on-surface, #2c2c2c);
		color: var(--color-surface-bright, #fff);
		flex-shrink: 0;
	}

	.careers-logo {
		display: flex;
		align-items: center;
		gap: 10px;
		text-decoration: none;
		color: inherit;
	}

	.logo-icon {
		background: var(--color-accent, #c96342);
		padding: 4px 8px;
		border: 1px solid rgba(255,255,255,0.3);
		border-radius: 6px;
		display: flex;
		align-items: center;
	}

	.logo-text {
		font-size: 20px;
		font-weight: 900;
		letter-spacing: -0.03em;
		font-family: 'Space Grotesk', sans-serif;
	}

	.logo-divider {
		width: 1px;
		height: 20px;
		background: rgba(254, 255, 214, 0.3);
	}

	.logo-sub {
		font-size: 14px;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		opacity: 0.7;
	}

	.careers-main {
		flex: 1;
	}

	.careers-footer {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 16px 2rem;
		background: var(--color-on-surface, #2c2c2c);
		color: rgba(255,255,255,0.45);
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.careers-footer-dot {
		width: 4px;
		height: 4px;
		background: var(--color-accent, #c96342);
		border-radius: 50%;
	}
</style>
