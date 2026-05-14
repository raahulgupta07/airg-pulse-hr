<script>
	import { onMount } from 'svelte';
	import { apiJson, me } from '$lib/api.ts';

	let loading = $state(true);
	let user = $state(null);
	let error = $state('');

	// Display name
	let displayName = $state('');
	let savingName = $state(false);
	let nameMsg = $state('');

	// Change password
	let currentPw = $state('');
	let newPw = $state('');
	let confirmPw = $state('');
	let savingPw = $state(false);
	let pwMsg = $state('');
	let pwErr = $state('');

	onMount(() => {
		if (typeof window === 'undefined') return;
		(async () => {
			try {
				const u = await me();
				user = u;
				displayName = u?.display_name || u?.name || '';
			} catch (e) {
				error = 'Could not load your profile.';
			} finally {
				loading = false;
			}
		})();
	});

	async function saveDisplayName() {
		savingName = true;
		nameMsg = '';
		try {
			await apiJson('/users/me', {
				method: 'PATCH',
				body: JSON.stringify({ display_name: displayName })
			});
			nameMsg = 'Display name saved.';
		} catch (e) {
			// Fallback: localStorage
			try {
				localStorage.setItem('pulse_display_name', displayName);
				nameMsg = 'Saved locally · sync pending';
			} catch {
				nameMsg = 'Could not save.';
			}
		} finally {
			savingName = false;
			setTimeout(() => (nameMsg = ''), 4000);
		}
	}

	async function changePassword() {
		pwErr = '';
		pwMsg = '';
		if (!currentPw || !newPw) {
			pwErr = 'Current and new password required.';
			return;
		}
		if (newPw !== confirmPw) {
			pwErr = 'New passwords do not match.';
			return;
		}
		if (newPw.length < 8) {
			pwErr = 'New password must be at least 8 characters.';
			return;
		}
		savingPw = true;
		try {
			await apiJson('/auth/change-password', {
				method: 'POST',
				body: JSON.stringify({ current_password: currentPw, new_password: newPw })
			});
			pwMsg = 'Password updated.';
			currentPw = ''; newPw = ''; confirmPw = '';
		} catch (e) {
			alert('Contact admin to change password');
		} finally {
			savingPw = false;
			setTimeout(() => (pwMsg = ''), 4000);
		}
	}
</script>

<div class="profile-page">
	<header class="profile-head">
		<h1 class="page-title">Profile</h1>
		<p class="page-sub">Manage your account, password, and display name.</p>
	</header>

	{#if loading}
		<div class="card"><p class="muted">Loading…</p></div>
	{:else if error}
		<div class="card"><p class="err">{error}</p></div>
	{:else}
		<!-- Account -->
		<section class="card">
			<h2 class="section-title">Account</h2>
			<div class="kv-grid">
				<div class="kv">
					<span class="kv-label">Email</span>
					<span class="kv-val">{user?.email || '—'}</span>
				</div>
				<div class="kv">
					<span class="kv-label">Operator ID</span>
					<span class="kv-val mono">{user?.operator_id || '—'}</span>
				</div>
				<div class="kv">
					<span class="kv-label">Role</span>
					<span class="kv-val">
						<span class="role-pill">{user?.role || 'user'}</span>
					</span>
				</div>
			</div>
		</section>

		<!-- Display name -->
		<section class="card">
			<h2 class="section-title">Display name</h2>
			<p class="section-hint">This is the name shown in the app and on notifications.</p>
			<div class="field-row">
				<input
					type="text"
					class="text-input"
					bind:value={displayName}
					placeholder="Your name"
					maxlength="80"
				/>
				<button class="btn-primary" onclick={saveDisplayName} disabled={savingName}>
					{savingName ? 'Saving…' : 'Save'}
				</button>
			</div>
			{#if nameMsg}<p class="hint">{nameMsg}</p>{/if}
		</section>

		<!-- Change password -->
		<section class="card">
			<h2 class="section-title">Change password</h2>
			<p class="section-hint">Use at least 8 characters.</p>
			<div class="form-stack">
				<label class="field-label">
					<span>Current password</span>
					<input type="password" class="text-input" bind:value={currentPw} autocomplete="current-password" />
				</label>
				<label class="field-label">
					<span>New password</span>
					<input type="password" class="text-input" bind:value={newPw} autocomplete="new-password" />
				</label>
				<label class="field-label">
					<span>Confirm new password</span>
					<input type="password" class="text-input" bind:value={confirmPw} autocomplete="new-password" />
				</label>
				<div class="row-end">
					<button class="btn-primary" onclick={changePassword} disabled={savingPw}>
						{savingPw ? 'Saving…' : 'Save'}
					</button>
				</div>
				{#if pwErr}<p class="err">{pwErr}</p>{/if}
				{#if pwMsg}<p class="hint">{pwMsg}</p>{/if}
			</div>
		</section>
	{/if}
</div>

<style>
	.profile-page {
		max-width: 720px;
		margin: 0 auto;
		padding: 32px 24px 64px;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		color: var(--color-ink, #2c2c2c);
		overflow-y: auto;
		height: 100%;
	}
	.profile-head { margin-bottom: 24px; }
	.page-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 26px;
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 4px;
	}
	.page-sub {
		font-size: 13.5px;
		color: var(--color-muted, #6f6e69);
		margin: 0;
	}

	.card {
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		padding: 24px;
		margin-bottom: 16px;
	}
	.section-title {
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		font-size: 17px;
		font-weight: 600;
		margin: 0 0 4px;
	}
	.section-hint {
		font-size: 12.5px;
		color: var(--color-muted, #6f6e69);
		margin: 0 0 16px;
	}

	.kv-grid { display: flex; flex-direction: column; gap: 12px; }
	.kv { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-size: 13.5px; }
	.kv-label { color: var(--color-muted, #6f6e69); }
	.kv-val { color: var(--color-ink, #2c2c2c); font-weight: 500; }
	.mono { font-family: ui-monospace, SFMono-Regular, monospace; font-size: 12.5px; }
	.role-pill {
		display: inline-block;
		padding: 2px 10px;
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		border-radius: 999px;
		font-size: 11.5px;
		font-weight: 600;
		text-transform: capitalize;
	}

	.field-row { display: flex; gap: 8px; align-items: center; }
	.form-stack { display: flex; flex-direction: column; gap: 12px; }
	.field-label { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--color-muted, #6f6e69); }
	.text-input {
		flex: 1;
		padding: 9px 12px;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 8px;
		font-size: 13.5px;
		font-family: inherit;
		background: var(--color-surface, #ffffff);
		color: var(--color-ink, #2c2c2c);
	}
	.text-input:focus {
		outline: none;
		border-color: var(--color-accent, #c96342);
		box-shadow: 0 0 0 3px var(--color-accent-soft, #fdebe1);
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
		transition: filter 0.15s;
	}
	.btn-primary:hover:not(:disabled) { filter: brightness(1.05); }
	.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

	.row-end { display: flex; justify-content: flex-end; }
	.muted { color: var(--color-muted, #6f6e69); font-size: 13px; }
	.hint { color: var(--color-muted, #6f6e69); font-size: 12px; margin: 8px 0 0; }
	.err { color: var(--color-red, #a83232); font-size: 12.5px; margin: 8px 0 0; }
</style>
