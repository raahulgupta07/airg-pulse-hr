<script>
	import { onMount } from 'svelte';
	import { apiJson } from '$lib/api.ts';

	const STORAGE_KEY = 'pulse_notif_prefs';

	const PREF_DEFS = [
		{ key: 'email_cv_uploaded',    label: 'Email me when CV is uploaded to my position', def: true },
		{ key: 'email_ai_match',       label: 'Email me when AI matches new candidates',     def: true },
		{ key: 'email_stage_change',   label: 'Email me when candidate moves stage',         def: false },
		{ key: 'email_daily_digest',   label: 'Email me daily pipeline digest (8am)',        def: false },
		{ key: 'inapp_pulse_feed',     label: 'In-app: pulse feed updates',                  def: true }
	];

	let prefs = $state({});
	let loading = $state(true);
	let saving = $state(false);
	let savedHint = $state('');
	let degraded = $state(false);

	onMount(() => {
		if (typeof window === 'undefined') return;
		(async () => {
			// Initialize from defaults
			const init = {};
			for (const p of PREF_DEFS) init[p.key] = p.def;
			prefs = init;

			// Try server first
			try {
				const data = await apiJson('/users/me/notifications');
				if (data && typeof data === 'object') {
					prefs = { ...init, ...(data.preferences || data) };
				}
			} catch {
				// Fallback to localStorage
				try {
					const raw = localStorage.getItem(STORAGE_KEY);
					if (raw) prefs = { ...init, ...JSON.parse(raw) };
				} catch { /* ignore */ }
				degraded = true;
			} finally {
				loading = false;
			}
		})();
	});

	function toggle(key) {
		prefs = { ...prefs, [key]: !prefs[key] };
	}

	async function save() {
		saving = true;
		savedHint = '';
		// Always mirror to localStorage as cache
		try { localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs)); } catch { /* ignore */ }
		try {
			await apiJson('/users/me/notifications', {
				method: 'POST',
				body: JSON.stringify({ preferences: prefs })
			});
			savedHint = 'Preferences saved.';
			degraded = false;
		} catch {
			savedHint = 'Saved locally · sync pending';
			degraded = true;
		} finally {
			saving = false;
			setTimeout(() => (savedHint = ''), 4000);
		}
	}
</script>

<div class="prefs-page">
	<header class="prefs-head">
		<a href="/profile" class="back-link">
			<span class="material-symbols-outlined" style="font-size: 16px;">arrow_back</span>
			Profile
		</a>
		<h1 class="page-title">Notification preferences</h1>
		<p class="page-sub">Choose what you'd like to be notified about and how.</p>
	</header>

	<section class="card">
		{#if loading}
			<p class="muted">Loading…</p>
		{:else}
			<ul class="pref-list">
				{#each PREF_DEFS as p}
					<li class="pref-row">
						<span class="pref-label">{p.label}</span>
						<button
							type="button"
							class="toggle-switch"
							class:on={prefs[p.key]}
							role="switch"
							aria-checked={!!prefs[p.key]}
							aria-label={p.label}
							onclick={() => toggle(p.key)}
						>
							<span class="toggle-knob"></span>
						</button>
					</li>
				{/each}
			</ul>

			<div class="actions">
				{#if savedHint}
					<span class="hint" class:hint-warn={degraded}>{savedHint}</span>
				{:else if degraded}
					<span class="hint hint-warn">Backend unavailable · using local cache</span>
				{/if}
				<button class="btn-primary" onclick={save} disabled={saving}>
					{saving ? 'Saving…' : 'Save'}
				</button>
			</div>
		{/if}
	</section>
</div>

<style>
	.prefs-page {
		max-width: 720px;
		margin: 0 auto;
		padding: 32px 24px 64px;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		color: var(--color-ink, #2c2c2c);
		overflow-y: auto;
		height: 100%;
	}
	.prefs-head { margin-bottom: 24px; }
	.back-link {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 12.5px;
		color: var(--color-muted, #6f6e69);
		text-decoration: none;
		margin-bottom: 8px;
	}
	.back-link:hover { color: var(--color-accent, #c96342); }
	.page-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 26px;
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 4px;
	}
	.page-sub { font-size: 13.5px; color: var(--color-muted, #6f6e69); margin: 0; }

	.card {
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		padding: 24px;
	}

	.pref-list { list-style: none; margin: 0; padding: 0; }
	.pref-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 14px 0;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.pref-row:last-child { border-bottom: none; }
	.pref-label { font-size: 13.5px; color: var(--color-ink, #2c2c2c); }

	/* Toggle switch (mirrors admin) */
	.toggle-switch {
		position: relative;
		display: inline-block;
		width: 36px;
		height: 20px;
		background: #d6d1c4;
		border: none;
		border-radius: 999px;
		cursor: pointer;
		padding: 0;
		flex-shrink: 0;
		transition: background 0.2s;
	}
	.toggle-knob {
		position: absolute;
		width: 16px;
		height: 16px;
		background: #fff;
		border-radius: 50%;
		left: 2px;
		top: 2px;
		transition: transform 0.2s;
		box-shadow: 0 1px 2px rgba(0,0,0,0.15);
	}
	.toggle-switch.on { background: var(--color-accent, #c96342); }
	.toggle-switch.on .toggle-knob { transform: translateX(16px); }
	.toggle-switch:focus-visible {
		outline: 2px solid var(--color-accent, #c96342);
		outline-offset: 2px;
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: 12px;
		margin-top: 18px;
	}
	.btn-primary {
		padding: 9px 18px;
		background: var(--color-accent, #c96342);
		color: #fff;
		border: none;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
		font-family: inherit;
	}
	.btn-primary:hover:not(:disabled) { filter: brightness(1.05); }
	.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
	.muted { color: var(--color-muted, #6f6e69); font-size: 13px; }
	.hint { font-size: 12px; color: var(--color-muted, #6f6e69); }
	.hint-warn { color: var(--color-accent-ink, #b04f30); }
</style>
