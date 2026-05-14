<script>
	/** Admin · Integrations — Slack stub + provider catalog.
	 *  Stores webhook URLs in localStorage (no backend required). */
	import { onMount } from 'svelte';
	import MessageCircle from '@lucide/svelte/icons/message-circle';
	import Users from '@lucide/svelte/icons/users';
	import Calendar from '@lucide/svelte/icons/calendar';
	import Mail from '@lucide/svelte/icons/mail';
	import PenLine from '@lucide/svelte/icons/pen-line';
	import Link from '@lucide/svelte/icons/link';

	const INTEGRATIONS = [
		{ key: 'slack',    label: 'Slack',            icon: MessageCircle, supports: 'webhook' },
		{ key: 'teams',    label: 'Microsoft Teams',  icon: Users,         supports: 'webhook' },
		{ key: 'gcal',     label: 'Google Calendar',  icon: Calendar,      supports: 'oauth_stub' },
		{ key: 'outlook',  label: 'Outlook',          icon: Mail,          supports: 'oauth_stub' },
		{ key: 'docusign', label: 'DocuSign',         icon: PenLine,       supports: 'oauth_stub' },
		{ key: 'linkedin', label: 'LinkedIn',         icon: Link,          supports: 'oauth_stub' },
	];

	let saved = $state({});
	let modalKey = $state(null);
	let modalUrl = $state('');
	let testStatus = $state(''); // '', 'sending', 'ok', 'fail'

	function lsKey(k) { return `pulse_integration_${k}_webhook`; }

	function loadAll() {
		const out = {};
		for (const i of INTEGRATIONS) {
			try { out[i.key] = localStorage.getItem(lsKey(i.key)) || ''; }
			catch { out[i.key] = ''; }
		}
		saved = out;
	}

	onMount(() => {
		if (typeof window !== 'undefined') loadAll();
	});

	function openConnect(key) {
		modalKey = key;
		modalUrl = saved[key] || '';
		testStatus = '';
	}
	function closeConnect() {
		modalKey = null;
		modalUrl = '';
		testStatus = '';
	}

	async function saveAndTest() {
		if (!modalKey) return;
		try { localStorage.setItem(lsKey(modalKey), modalUrl.trim()); } catch {}
		saved = { ...saved, [modalKey]: modalUrl.trim() };
		if (!modalUrl.trim()) { closeConnect(); return; }
		testStatus = 'sending';
		const meta = INTEGRATIONS.find(i => i.key === modalKey);
		// Note: ✅ intentionally kept in webhook payload — rendered by Slack/Teams, not our UI.
		const payload = { text: `✅ City Agent Pulse connected to ${meta?.label || modalKey}` };
		try {
			const res = await fetch(modalUrl.trim(), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
				mode: 'cors',
			});
			testStatus = res.ok ? 'ok' : 'fail';
		} catch {
			// CORS / network — webhook may have still arrived
			testStatus = 'fail';
		}
	}

	function disconnect(key) {
		try { localStorage.removeItem(lsKey(key)); } catch {}
		saved = { ...saved, [key]: '' };
	}
</script>

<div class="int-page">
	<header class="int-head">
		<h1 class="int-title">Integrations</h1>
		<p class="int-sub">Connect City Agent Pulse to your team's tools. Webhook URLs are stored in your browser.</p>
	</header>

	<div class="int-grid">
		{#each INTEGRATIONS as i}
			{@const connected = !!saved[i.key]}
			<div class="int-card">
				<div class="int-card-head">
					<div class="int-icon"><svelte:component this={i.icon} size={22} strokeWidth={1.75} /></div>
					<div class="int-name">{i.label}</div>
					<span class="int-pill" class:on={connected}>
						{connected ? 'Connected' : 'Not connected'}
					</span>
				</div>
				<div class="int-card-body">
					<div class="int-supports">
						{i.supports === 'webhook' ? 'Webhook URL' : 'OAuth (coming soon)'}
					</div>
					{#if connected}
						<code class="int-url" title={saved[i.key]}>
							{saved[i.key].length > 38 ? saved[i.key].slice(0, 38) + '…' : saved[i.key]}
						</code>
					{/if}
				</div>
				<div class="int-card-foot">
					<button class="int-btn" onclick={() => openConnect(i.key)}>
						{connected ? 'Reconfigure' : 'Connect'}
					</button>
					{#if connected}
						<button class="int-btn-ghost" onclick={() => disconnect(i.key)}>Disconnect</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>

{#if modalKey}
	{@const meta = INTEGRATIONS.find(i => i.key === modalKey)}
	<div class="int-modal-bg" onclick={(e) => { if (e.target === e.currentTarget) closeConnect(); }} role="presentation">
		<div class="int-modal" role="dialog">
			<div class="int-modal-head">
				<span class="int-icon"><svelte:component this={meta?.icon} size={22} strokeWidth={1.75} /></span>
				<div>
					<h3 style="margin: 0; font-size: 17px; font-weight: 600; color: #2d2a26; font-family: 'Tiempos Headline', Georgia, serif;">Connect {meta?.label}</h3>
					<p style="margin: 2px 0 0; font-size: 12.5px; color: #6b6b66;">Paste your {meta?.label} webhook URL.</p>
				</div>
			</div>
			<div class="int-modal-body">
				<label class="int-label" for="webhook-url">Webhook URL</label>
				<input
					id="webhook-url"
					type="url"
					class="int-input"
					bind:value={modalUrl}
					placeholder="https://hooks.slack.com/services/..."
					autocomplete="off"
				/>
				{#if testStatus === 'sending'}
					<div class="int-test int-test-info">Sending test message…</div>
				{:else if testStatus === 'ok'}
					<div class="int-test int-test-ok">Test sent successfully — check your channel.</div>
				{:else if testStatus === 'fail'}
					<div class="int-test int-test-warn">Test send: check your channel. (Browser CORS may block the response — the webhook may have still delivered.)</div>
				{/if}
			</div>
			<div class="int-modal-foot">
				<button class="int-btn-ghost" onclick={closeConnect}>Cancel</button>
				<button class="int-btn" onclick={saveAndTest} disabled={testStatus === 'sending'}>
					{testStatus === 'sending' ? 'Sending…' : 'Save and test'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.int-page {
		max-width: 1100px;
		margin: 0 auto;
		padding: 28px 24px;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}
	.int-head { margin-bottom: 22px; }
	.int-title {
		font-family: 'Tiempos Headline', Georgia, serif;
		font-size: 28px;
		font-weight: 500;
		color: #2d2a26;
		margin: 0;
	}
	.int-sub {
		font-size: 14px;
		color: #6b6b66;
		margin: 4px 0 0;
	}

	.int-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 14px;
	}
	.int-card {
		background: #ffffff;
		border: 1px solid #e8e6dc;
		border-radius: 12px;
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.int-card-head {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.int-icon {
		display: inline-flex;
		align-items: center;
		line-height: 1;
	}
	.int-name {
		flex: 1;
		font-size: 14px;
		font-weight: 600;
		color: #2d2a26;
	}
	.int-pill {
		font-size: 11px;
		font-weight: 500;
		padding: 3px 8px;
		border-radius: 999px;
		background: #f4f3ee;
		color: #6b6b66;
		border: 1px solid #e8e6dc;
	}
	.int-pill.on {
		background: #eaf3e6;
		color: #4a6b3a;
		border-color: #d2e3c9;
	}
	.int-card-body {
		font-size: 12.5px;
		color: #6b6b66;
		min-height: 28px;
	}
	.int-supports {
		font-size: 11.5px;
		color: #8a8a82;
	}
	.int-url {
		display: inline-block;
		margin-top: 6px;
		padding: 4px 8px;
		background: #faf9f5;
		border: 1px solid #e8e6dc;
		border-radius: 6px;
		font-family: ui-monospace, SFMono-Regular, monospace;
		font-size: 11px;
		color: #2d2a26;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.int-card-foot {
		display: flex;
		gap: 6px;
		justify-content: flex-end;
	}
	.int-btn {
		padding: 7px 14px;
		background: #c96342;
		color: #ffffff;
		border: 1px solid #c96342;
		border-radius: 8px;
		font-size: 12.5px;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
	}
	.int-btn:hover { background: #b35535; }
	.int-btn:disabled { opacity: 0.6; cursor: not-allowed; }
	.int-btn-ghost {
		padding: 7px 14px;
		background: transparent;
		color: #6b6b66;
		border: 1px solid #e8e6dc;
		border-radius: 8px;
		font-size: 12.5px;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
	}
	.int-btn-ghost:hover { background: #faf9f5; color: #2d2a26; }

	/* Modal */
	.int-modal-bg {
		position: fixed;
		inset: 0;
		background: rgba(45, 42, 38, 0.45);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 24px;
		z-index: 9000;
	}
	.int-modal {
		background: #ffffff;
		border-radius: 12px;
		width: 100%;
		max-width: 520px;
		box-shadow: 0 20px 50px rgba(0, 0, 0, 0.18);
		overflow: hidden;
	}
	.int-modal-head {
		padding: 18px 20px;
		border-bottom: 1px solid #e8e6dc;
		display: flex;
		gap: 12px;
		align-items: center;
		background: #faf9f5;
	}
	.int-modal-body { padding: 18px 20px; }
	.int-label {
		display: block;
		font-size: 11px;
		font-weight: 500;
		color: #8a8a82;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin-bottom: 6px;
	}
	.int-input {
		width: 100%;
		padding: 9px 12px;
		border: 1px solid #e8e6dc;
		border-radius: 8px;
		background: #ffffff;
		font-size: 13px;
		font-family: ui-monospace, SFMono-Regular, monospace;
		color: #2d2a26;
		box-sizing: border-box;
	}
	.int-input:focus { outline: none; border-color: #c96342; }
	.int-test {
		margin-top: 12px;
		padding: 9px 12px;
		border-radius: 8px;
		font-size: 12.5px;
	}
	.int-test-info { background: #f4f3ee; color: #6b6b66; }
	.int-test-ok   { background: #eaf3e6; color: #4a6b3a; border: 1px solid #d2e3c9; }
	.int-test-warn { background: #fdf3e6; color: #8a6334; border: 1px solid #f0d9b8; }
	.int-modal-foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px;
		border-top: 1px solid #e8e6dc;
		background: #faf9f5;
	}
</style>
