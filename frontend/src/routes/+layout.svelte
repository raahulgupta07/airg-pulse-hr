<script>
	import '../app.css';
	import Toast from '$lib/Toast.svelte';
	import PipelineTerminal from '$lib/PipelineTerminal.svelte';
	import PulseFeed from '$lib/PulseFeed.svelte';
	import AgentLiveIndicator from '$lib/AgentLiveIndicator.svelte';
	import PulseToast from '$lib/PulseToast.svelte';
	import CommandPalette from '$lib/CommandPalette.svelte';
	import KeyboardHelp from '$lib/KeyboardHelp.svelte';
	// OnboardingTour disabled — was overlaying spotlight ring across the whole app
	// import OnboardingTour from '$lib/OnboardingTour.svelte';
	import WhatsNew from '$lib/WhatsNew.svelte';
	import Confetti from '$lib/Confetti.svelte';
	import { apiJson } from '$lib/api.ts';
	import { logout } from '$lib/auth';
	import { page } from '$app/state';
	import { fade } from 'svelte/transition';
	import UndoBar from '$lib/UndoBar.svelte';
	import HoverPreview from '$lib/HoverPreview.svelte';
	import { brandingStore, getBranding, loadBrandingFromAPI, applyBranding } from '$lib/branding';

	let { data, children } = $props();
	let branding = $state(getBranding());
	const _unsubBranding = brandingStore.subscribe((b) => { branding = b; });
	let commandPaletteRef = $state(null);
	let currentUser = $derived(data?.user ?? null);
	let operatorLabel = $derived(
		currentUser?.operator_id || currentUser?.email || currentUser?.display_name || ''
	);

	let currentPath = $derived(page.url?.pathname || '/');
	let systemStatus = $state('active');

	// Notifications
	let notifCount = $state(0);
	let notifications = $state([]);
	let showNotifPanel = $state(false);
	let notifLoading = $state(false);

	// User dropdown menu
	let showUserMenu = $state(false);
	function toggleUserMenu() { showUserMenu = !showUserMenu; }
	function goTo(path) {
		showUserMenu = false;
		if (typeof window !== 'undefined') window.location.href = path;
	}

	// Merge proposals (pending count)
	let mergePendingCount = $state(0);
	async function fetchMergeCount() {
		try {
			const data = await apiJson('/merges/pending-count');
			mergePendingCount = data.total || 0;
		} catch { /* non-critical */ }
	}

	// Apply branding ASAP (from cache) + sync from API in background.
	$effect(() => {
		if (typeof window === 'undefined') return;
		applyBranding(getBranding());
		loadBrandingFromAPI().then((b) => applyBranding(b)).catch(() => {});
		return () => { _unsubBranding(); };
	});

	$effect(() => {
		if (typeof window === 'undefined') return;

		// Skip heavy chrome work on public/auth routes (no token yet)
		const path = window.location.pathname;
		if (['/login', '/register', '/careers'].some((p) => path === p || path.startsWith(p + '/'))) {
			return;
		}

		const onClick = (e) => {
			if (showNotifPanel && !e.target.closest('.notif-area')) {
				showNotifPanel = false;
			}
			if (showUserMenu && !e.target.closest('.user-menu-area')) {
				showUserMenu = false;
			}
		};
		const onKey = (e) => {
			if (e.key === 'Escape') {
				showUserMenu = false;
				showNotifPanel = false;
			}
		};
		document.addEventListener('click', onClick);
		document.addEventListener('keydown', onKey);

		loadFeatures();
		fetchNotifCount();
		fetchMergeCount();
		const interval = setInterval(() => { fetchNotifCount(); fetchMergeCount(); }, 30000);
		return () => {
			clearInterval(interval);
			document.removeEventListener('click', onClick);
			document.removeEventListener('keydown', onKey);
		};
	});

	async function fetchNotifCount() {
		try {
			const data = await apiJson('/notifications/count');
			notifCount = data.count || 0;
		} catch { /* non-critical */ }
	}

	async function fetchNotifications() {
		notifLoading = true;
		try {
			const data = await apiJson('/notifications');
			notifications = data.notifications || [];
		} catch {
			notifications = [];
		} finally {
			notifLoading = false;
		}
	}

	function toggleNotifPanel() {
		showNotifPanel = !showNotifPanel;
		if (showNotifPanel) fetchNotifications();
	}

	async function markRead(notif) {
		try {
			await apiJson(`/notifications/read/${notif.id}`, { method: 'POST' });
			notif.is_read = true;
			notifications = [...notifications];
			notifCount = Math.max(0, notifCount - 1);
		} catch { /* ignore */ }
		if (notif.link) {
			showNotifPanel = false;
			window.location.href = notif.link;
		}
	}

	async function markAllRead() {
		try {
			await apiJson('/notifications/read-all', { method: 'POST' });
			notifications = notifications.map(n => ({ ...n, is_read: true }));
			notifCount = 0;
		} catch { /* ignore */ }
	}

	function timeAgo(dateStr) {
		if (!dateStr) return '';
		const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
		if (diff < 60) return 'just now';
		if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
		if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
		return `${Math.floor(diff / 86400)}d ago`;
	}

	const NAV_ALL = [
		{ path: '/', label: 'Positions', icon: 'work', flag: 'feature_positions' },
		{
			path: '/jds', label: 'Pools', icon: 'inventory_2', flag: null,
			children: [
				{ path: '/jds', label: 'Job Pool', desc: 'Job descriptions library — paste, generate, attach to positions', icon: 'description' },
				{ path: '/candidates', label: 'Talent Pool', desc: 'CV repository — upload, search, attach to positions', icon: 'folder_shared' },
			],
		},
		{ path: '/board', label: 'Board', icon: 'view_kanban', flag: null },
		{
			path: '/communicate/announcements', label: 'Communicate', icon: 'campaign', flag: null,
			badge: 'NEW',
			children: [
				{ path: '/communicate/announcements', label: 'Announcements', desc: 'Org movement, promotion, leadership letters', soon: true },
				{ path: '/communicate/invitations', label: 'Invitations', desc: 'Webinars + events, AI body + image', soon: true },
				{ path: '/communicate/articles', label: 'Articles', desc: "Holiday + culture posts (Women's Day, Thadingyut, etc)", soon: true },
			],
		},
		{ path: '/chat', label: 'Copilot', icon: 'auto_awesome', flag: 'feature_chat' },
		{
			path: '/admin', label: 'Admin', icon: 'admin_panel_settings', flag: null,
			children: [
				{ path: '/admin', label: 'Settings', desc: 'Users, branding, templates, workflows, integrations', icon: 'admin_panel_settings' },
				{ path: '/analytics', label: 'Analytics', desc: 'Funnel, time-to-hire, source ROI, predictive', icon: 'analytics' },
				{ path: '/billing', label: 'Billing', desc: 'LLM cost ledger, daily cap, model breakdown', icon: 'receipt_long' },
				{ path: '/agents', label: 'Agents', desc: 'Live status of background + on-demand agents', icon: 'smart_toy' },
			],
		},
	];
	let features = $state(null);
	let navItems = $derived(features === null ? [] : NAV_ALL.filter(n => !n.flag || features[n.flag] !== false));

	async function loadFeatures() {
		try {
			const r = await fetch('/api/system/features');
			features = await r.json();
		} catch { features = {}; }
	}

	$effect(() => {
		if (!isPublicRoute && features === null) loadFeatures();
	});

	function isActive(path) {
		if (path === '/') return currentPath === '/' || currentPath === '';
		return currentPath.startsWith(path);
	}

	const PUBLIC_PREFIXES = ['/login', '/register', '/careers'];
	let isPublicRoute = $derived(
		PUBLIC_PREFIXES.some((p) => currentPath === p || currentPath.startsWith(p + '/'))
	);

	// ── Mobile nav drawer ──
	let mobileNavOpen = $state(false);
	function openMobileNav() { mobileNavOpen = true; }
	function closeMobileNav() { mobileNavOpen = false; }

	$effect(() => {
		if (typeof window === 'undefined') return;
		const onKey = (e) => { if (e.key === 'Escape' && mobileNavOpen) closeMobileNav(); };
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	});

	// Close mobile nav on route change
	$effect(() => {
		currentPath;
		if (mobileNavOpen) mobileNavOpen = false;
	});
</script>

{#if isPublicRoute}
	{@render children()}
{:else}
<div class="flex flex-col h-screen app-shell">
	<!-- Skip to content (visible on focus only, a11y) -->
	<a href="#pulse-main" class="skip-to-content">Skip to content</a>

	<!-- Header -->
	<header class="claude-nav">
		<button
			type="button"
			class="hamburger show-mobile"
			aria-label="Open menu"
			aria-expanded={mobileNavOpen}
			onclick={openMobileNav}
		>
			<span class="material-symbols-outlined" style="font-size: 22px;">menu</span>
		</button>

		<a href="/" class="brand">
			{#if branding.logoUrl}
				<div class="brand-logo brand-logo-img"><img src={branding.logoUrl} alt={branding.appName} /></div>
			{:else}
				<div class="brand-logo">{(branding.appName[0] || 'P').toUpperCase()}</div>
			{/if}
			<span class="brand-text">{branding.appName}</span>
		</a>

		<nav class="nav-items nav-items-desktop">
			{#each navItems as item}
				{#if item.children}
					{@const parentActive = item.children.some(c => isActive(c.path))}
					<div class="nav-dropdown">
						<a href={item.path}
							class="nav-item nav-item-with-children"
							class:active={parentActive}>
							<span class="hide-mobile">{item.label}</span>
							{#if item.badge}<span class="nav-badge">{item.badge}</span>{/if}
							<span class="nav-caret">▾</span>
							<span class="material-symbols-outlined nav-item-icon-mobile">{item.icon}</span>
						</a>
						<div class="nav-dropdown-menu">
							{#each item.children as child}
								<a href={child.path} class="nav-dropdown-item" class:active={isActive(child.path)}>
									<div class="nav-dd-row">
										{#if child.icon}<span class="material-symbols-outlined nav-dd-icon">{child.icon}</span>{/if}
										<span class="nav-dd-label">{child.label}</span>
										{#if child.soon}<span class="nav-dd-soon">SOON</span>{/if}
									</div>
									{#if child.desc}<div class="nav-dd-desc">{child.desc}</div>{/if}
								</a>
							{/each}
						</div>
					</div>
				{:else}
					<a
						href={item.path}
						class="nav-item"
						class:active={isActive(item.path)}
					>
						<span class="hide-mobile">{item.label}</span>
						<span class="material-symbols-outlined nav-item-icon-mobile">{item.icon}</span>
					</a>
				{/if}
			{/each}
		</nav>

		<div class="nav-spacer"></div>

		<div class="nav-right">
			{#if mergePendingCount > 0}
				<a href="/admin#merges" class="merge-pill" title="{mergePendingCount} pending merge proposals">
					<span class="material-symbols-outlined" style="font-size: 13px;">merge_type</span>
					Merges · {mergePendingCount}
				</a>
			{/if}

			<!-- Live agent activity indicator -->
			<AgentLiveIndicator />

			<!-- Unified Pulse Feed (replaces bell + JD agent badge) -->
			<PulseFeed />

			{#if operatorLabel}
				<div class="user-menu-area">
					<button
						type="button"
						class="user-pill hide-mobile"
						aria-haspopup="menu"
						aria-expanded={showUserMenu}
						title="Account menu"
						onclick={(e) => { e.stopPropagation(); toggleUserMenu(); }}
					>
						<div class="avatar">{operatorLabel.slice(0, 2).toUpperCase()}</div>
						<span class="user-name">{operatorLabel}</span>
						<span class="material-symbols-outlined caret" aria-hidden="true">expand_more</span>
					</button>

					{#if showUserMenu}
						<div class="user-menu" role="menu">
							<button class="user-menu-item" role="menuitem" onclick={() => goTo('/profile')}>
								<span class="material-symbols-outlined mi-icon">person</span>
								<span>Profile</span>
							</button>
							<button class="user-menu-item" role="menuitem" onclick={() => goTo('/profile/notifications')}>
								<span class="material-symbols-outlined mi-icon">notifications</span>
								<span>Notification preferences</span>
							</button>
							<button class="user-menu-item" role="menuitem" onclick={() => goTo('/profile/api-keys')}>
								<span class="material-symbols-outlined mi-icon">key</span>
								<span>API keys</span>
							</button>
							<button class="user-menu-item" role="menuitem" onclick={() => goTo('/profile/help')}>
								<span class="material-symbols-outlined mi-icon">help</span>
								<span>Help &amp; shortcuts</span>
							</button>
							<div class="user-menu-divider"></div>
							<button class="user-menu-item user-menu-danger" role="menuitem" onclick={() => { showUserMenu = false; logout(); }}>
								<span class="material-symbols-outlined mi-icon">logout</span>
								<span>Logout</span>
							</button>
						</div>
					{/if}
				</div>
			{:else if currentUser}
				<button class="logout-btn" onclick={logout} aria-label="Logout">Logout</button>
			{/if}
		</div>
	</header>

	<!-- Main Content -->
	<main id="pulse-main" class="flex-1 overflow-hidden flex flex-col">
		<div class="flex-1 overflow-hidden">
			{#key currentPath}
				<div class="route-fade" in:fade={{ duration: 120 }} style="height:100%;">
					{@render children()}
				</div>
			{/key}
		</div>
	</main>

	<!-- Mobile nav drawer -->
	{#if mobileNavOpen}
		<button
			type="button"
			class="mobile-nav-overlay"
			aria-label="Close menu"
			onclick={closeMobileNav}
		></button>
		<aside class="mobile-nav-drawer" role="dialog" aria-modal="true" aria-label="Main navigation">
			<div class="mobile-nav-head">
				<a href="/" class="brand" onclick={closeMobileNav}>
					{#if branding.logoUrl}
						<div class="brand-logo brand-logo-img"><img src={branding.logoUrl} alt={branding.appName} /></div>
					{:else}
						<div class="brand-logo">{(branding.appName[0] || 'P').toUpperCase()}</div>
					{/if}
					<span class="brand-text">{branding.appName}</span>
				</a>
				<button type="button" class="mobile-nav-close" aria-label="Close menu" onclick={closeMobileNav}>
					<span class="material-symbols-outlined" style="font-size: 20px;">close</span>
				</button>
			</div>
			<nav class="mobile-nav-list">
				{#each navItems as item}
					<a
						href={item.path}
						class="mobile-nav-link"
						class:active={isActive(item.path)}
						onclick={closeMobileNav}
					>
						<span class="material-symbols-outlined" style="font-size: 20px;">{item.icon}</span>
						<span>{item.label}</span>
					</a>
				{/each}
			</nav>
			{#if operatorLabel}
				<div class="mobile-nav-foot">
					<div class="mobile-nav-user">
						<div class="avatar">{operatorLabel.slice(0, 2).toUpperCase()}</div>
						<span class="user-name">{operatorLabel}</span>
					</div>
					{#if currentUser}
						<button class="logout-btn" onclick={() => { closeMobileNav(); logout(); }}>Logout</button>
					{/if}
				</div>
			{/if}
		</aside>
	{/if}

	<!-- Footer -->
	<footer class="claude-foot">
		<div class="foot-status">
			<div class="foot-dot"></div>
			<span>{systemStatus === 'active' ? 'System active' : 'Processing'}</span>
		</div>
		<span class="hide-mobile foot-version">
			{branding.appName} v1.0 · {branding.footerText}
		</span>
	</footer>

	<Toast />
	<PulseToast />
	<PipelineTerminal />
	<!-- <OnboardingTour /> — removed: spotlight ring overlay was breaking all pages -->
	<WhatsNew />
	<Confetti />
	<CommandPalette bind:this={commandPaletteRef} />
	<KeyboardHelp />
	<UndoBar />
	<HoverPreview />
</div>
{/if}

<style>
	@media (max-width: 768px) {
		.hide-mobile { display: none !important; }
	}

	/* Mobile-only utility */
	.show-mobile { display: none; }
	@media (max-width: 900px) {
		.show-mobile { display: inline-flex; }
		.nav-items-desktop { display: none !important; }
	}

	/* Hamburger button */
	.hamburger {
		background: transparent;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 8px;
		width: 36px;
		height: 36px;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		color: var(--color-ink, #2c2c2c);
		margin-right: 8px;
		padding: 0;
	}
	.hamburger:hover { background: var(--color-surface-warm, #f4f3ee); }

	/* Mobile drawer */
	.mobile-nav-overlay {
		position: fixed; inset: 0;
		background: rgba(56,56,50,0.45);
		z-index: 980;
		border: 0; padding: 0; cursor: pointer;
		animation: mn-fade 0.18s ease;
	}
	.mobile-nav-drawer {
		position: fixed;
		top: 0; left: 0; bottom: 0;
		width: 280px;
		max-width: 85vw;
		background: var(--color-bg-alt, #f0eee5);
		border-right: 1px solid var(--color-border, #e8e6dd);
		z-index: 981;
		display: flex;
		flex-direction: column;
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		animation: mn-slide 0.22s ease;
		box-shadow: 4px 0 24px rgba(0,0,0,0.08);
	}
	@keyframes mn-fade { from { opacity: 0; } to { opacity: 1; } }
	@keyframes mn-slide { from { transform: translateX(-100%); } to { transform: translateX(0); } }

	.mobile-nav-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--color-border, #e8e6dd);
	}
	.mobile-nav-close {
		background: transparent;
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 8px;
		width: 32px; height: 32px;
		display: inline-flex; align-items: center; justify-content: center;
		cursor: pointer;
		color: var(--color-ink-soft, #4a4a48);
	}
	.mobile-nav-close:hover { background: var(--color-surface-warm, #f4f3ee); }

	.mobile-nav-list {
		flex: 1;
		padding: 12px 8px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.mobile-nav-link {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 11px 14px;
		border-radius: 10px;
		text-decoration: none;
		color: var(--color-ink-soft, #4a4a48);
		font-size: 14px;
		font-weight: 500;
		font-family: inherit;
	}
	.mobile-nav-link:hover {
		background: rgba(0,0,0,0.04);
		color: var(--color-ink, #2c2c2c);
	}
	.mobile-nav-link.active {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		font-weight: 600;
	}

	.mobile-nav-foot {
		border-top: 1px solid var(--color-border, #e8e6dd);
		padding: 12px 16px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.mobile-nav-user {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.mobile-nav-user .user-name {
		font-size: 13px;
		color: var(--color-ink-soft, #4a4a48);
		font-weight: 500;
	}

	/* Hide PipelineTerminal on small viewports — too dense for mobile */
	@media (max-width: 900px) {
		:global(.term-wrap),
		:global(.pipeline-terminal),
		:global(#pipeline-terminal),
		:global([data-pipeline-terminal]) {
			display: none !important;
		}
	}

	/* Tighten nav padding on mobile so brand + hamburger fit */
	@media (max-width: 600px) {
		.claude-nav { padding: 0 12px; }
		.brand { margin-right: 12px; }
		.brand-text { font-size: 16px; }
	}

	/* Skip-to-content (a11y) — visible only when focused */
	.skip-to-content {
		position: absolute;
		top: -40px;
		left: 12px;
		z-index: 9999;
		background: var(--color-accent, #c96342);
		color: #fff;
		padding: 8px 14px;
		border-radius: 999px;
		font-size: 13px;
		font-weight: 600;
		text-decoration: none;
		transition: top 120ms ease-out;
	}
	.skip-to-content:focus,
	.skip-to-content:focus-visible {
		top: 12px;
		outline: 2px solid var(--color-accent, #c96342);
		outline-offset: 2px;
	}
	.route-fade { will-change: opacity; }

	/* ── Claude warm top nav ── */
	.claude-nav {
		height: 60px;
		display: flex;
		align-items: center;
		padding: 0 24px;
		gap: 4px;
		flex-shrink: 0;
		background: var(--color-bg-alt, #f0eee5);
		border-bottom: 1px solid var(--color-border, #e8e6dd);
		color: var(--color-ink, #2c2c2c);
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 11px;
		margin-right: 28px;
		text-decoration: none;
		color: inherit;
	}
	.brand-logo {
		width: 32px;
		height: 32px;
		border-radius: 9px;
		background: var(--color-accent, #c96342);
		color: #fff;
		display: grid;
		place-items: center;
		font-weight: 700;
		font-size: 15px;
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
	}
	.brand-logo-img { background: transparent !important; padding: 0; overflow: hidden; }
	.brand-logo-img img { width: 100%; height: 100%; object-fit: cover; display: block; }
	.brand-text {
		font-weight: 600;
		font-size: 17px;
		letter-spacing: -0.01em;
		font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
		color: var(--color-ink, #2c2c2c);
	}

	.nav-items {
		display: flex;
		gap: 2px;
		align-items: center;
	}
	.nav-item {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 8px 14px;
		color: var(--color-ink-soft, #4a4a48);
		text-decoration: none;
		font-size: 13.5px;
		font-weight: 500;
		border-radius: var(--radius-sm, 8px);
		transition: background 0.15s, color 0.15s;
		font-family: inherit;
	}
	.nav-item:hover {
		background: rgba(0, 0, 0, 0.04);
		color: var(--color-ink, #2c2c2c);
	}
	.nav-item.active {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
		font-weight: 600;
	}
	.nav-item-icon-mobile { display: none; font-size: 16px; }

	/* ---- Dropdown nav (Communicate ▾) ---- */
	.nav-dropdown { position: relative; }
	.nav-item-with-children { display: inline-flex; align-items: center; gap: 4px; }
	.nav-caret { font-size: 9px; opacity: 0.7; }
	.nav-badge {
		font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
		padding: 1px 6px; border-radius: 999px; margin-left: 4px;
		background: var(--color-accent, #c96342); color: #fff;
		animation: navBadgePulse 2s infinite;
	}
	@keyframes navBadgePulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.65; }
	}
	.nav-dropdown-menu {
		position: absolute; top: calc(100% + 6px); left: 0;
		min-width: 280px; padding: 8px;
		background: var(--color-surface-bright, #fff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08), 0 2px 6px rgba(0, 0, 0, 0.04);
		opacity: 0; visibility: hidden; transform: translateY(-4px);
		transition: opacity 140ms, transform 140ms, visibility 140ms;
		z-index: 200;
	}
	.nav-dropdown:hover .nav-dropdown-menu,
	.nav-dropdown:focus-within .nav-dropdown-menu {
		opacity: 1; visibility: visible; transform: translateY(0);
	}
	.nav-dropdown-item {
		display: block; padding: 10px 12px; border-radius: 7px;
		color: var(--color-on-surface, #2c2c2c); text-decoration: none;
		transition: background 120ms;
	}
	.nav-dropdown-item:hover { background: var(--color-bg, #faf9f5); }
	.nav-dropdown-item.active { background: rgba(201, 99, 66, 0.08); }
	.nav-dd-row { display: flex; align-items: center; gap: 8px; }
	.nav-dd-icon {
		font-size: 17px; color: var(--color-on-surface-dim, #6f6e69);
		flex-shrink: 0;
	}
	.nav-dropdown-item.active .nav-dd-icon { color: var(--color-accent, #c96342); }
	.nav-dd-label { font-size: 13.5px; font-weight: 600; }
	.nav-dd-soon {
		font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
		padding: 1px 6px; border-radius: 4px;
		background: rgba(201, 99, 66, 0.10); color: var(--color-accent, #c96342);
	}
	.nav-dd-desc { font-size: 11.5px; color: var(--color-on-surface-dim, #6f6e69); margin-top: 2px; }
	@media (max-width: 768px) {
		.nav-item-icon-mobile { display: inline-flex; }
		.nav-item { padding: 8px 10px; }
	}

	.nav-spacer { flex: 1; }
	.nav-right { display: flex; align-items: center; gap: 8px; }

	.merge-pill {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 5px 11px;
		background: var(--color-red-soft, #f5dada);
		color: var(--color-red, #a83232);
		border: 1px solid var(--color-red-soft, #f5dada);
		border-radius: var(--radius-pill, 999px);
		font-size: 12px;
		font-weight: 500;
		text-decoration: none;
		font-family: inherit;
	}
	.merge-pill:hover { filter: brightness(0.97); }

	.cmdk {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 7px 12px;
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: var(--radius-pill, 999px);
		font-size: 12.5px;
		color: var(--color-muted, #6f6e69);
		cursor: pointer;
		min-width: 220px;
		font-family: inherit;
	}
	.cmdk:hover { background: var(--color-surface-warm, #f4f3ee); }
	.cmdk .kbd {
		margin-left: auto;
		padding: 1px 6px;
		background: var(--color-surface-warm, #f4f3ee);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 4px;
		font-size: 10px;
		font-family: ui-monospace, SFMono-Regular, monospace;
		color: var(--color-muted, #6f6e69);
	}

	.user-menu-area {
		position: relative;
		display: inline-block;
	}
	.user-pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 4px 10px 4px 4px;
		border-radius: var(--radius-pill, 999px);
		background: transparent;
		border: 1px solid transparent;
		cursor: pointer;
		font-family: inherit;
		transition: background 0.15s, border-color 0.15s;
	}
	.user-pill:hover {
		background: var(--color-surface-warm, #f4f3ee);
		border-color: var(--color-border, #e8e6dd);
	}
	.user-pill:focus-visible {
		outline: 2px solid var(--color-accent, #c96342);
		outline-offset: 2px;
	}
	.user-pill .caret {
		font-size: 16px;
		color: var(--color-muted, #6f6e69);
	}

	.user-menu {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		min-width: 240px;
		background: var(--color-surface, #ffffff);
		border: 1px solid var(--color-border, #e8e6dd);
		border-radius: 12px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
		padding: 6px;
		z-index: 200;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.user-menu-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 12px;
		background: transparent;
		border: none;
		border-radius: 8px;
		font-size: 13px;
		color: var(--color-ink, #2c2c2c);
		text-align: left;
		cursor: pointer;
		font-family: inherit;
		transition: background 0.12s;
	}
	.user-menu-item:hover {
		background: var(--color-accent-soft, #fdebe1);
		color: var(--color-accent-ink, #b04f30);
	}
	.user-menu-item .mi-icon {
		font-size: 18px;
		color: var(--color-muted, #6f6e69);
	}
	.user-menu-item:hover .mi-icon {
		color: var(--color-accent-ink, #b04f30);
	}
	.user-menu-divider {
		height: 1px;
		background: var(--color-border, #e8e6dd);
		margin: 4px 2px;
	}
	.user-menu-danger {
		color: var(--color-red, #a83232);
	}
	.user-menu-danger .mi-icon {
		color: var(--color-red, #a83232);
	}
	.user-menu-danger:hover {
		background: var(--color-red-soft, #f5dada);
		color: var(--color-red, #a83232);
	}
	.user-menu-danger:hover .mi-icon {
		color: var(--color-red, #a83232);
	}
	.avatar {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--color-accent, #c96342);
		color: #fff;
		display: grid;
		place-items: center;
		font-size: 11px;
		font-weight: 700;
		font-family: inherit;
	}
	.user-name {
		font-size: 12.5px;
		color: var(--color-ink-soft, #4a4a48);
		font-weight: 500;
		max-width: 160px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.logout-btn {
		padding: 7px 13px;
		border-radius: var(--radius-pill, 999px);
		background: transparent;
		color: var(--color-muted, #6f6e69);
		border: 1px solid var(--color-border, #e8e6dd);
		font-size: 12.5px;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}
	.logout-btn:hover {
		background: var(--color-surface-warm, #f4f3ee);
		color: var(--color-ink, #2c2c2c);
		border-color: var(--color-border-strong, #d8d5cb);
	}
	.logout-btn:focus-visible {
		outline: 2px solid var(--color-accent, #c96342);
		outline-offset: 2px;
	}

	/* ── Footer ── */
	.claude-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 24px;
		height: 32px;
		flex-shrink: 0;
		background: var(--color-bg-alt, #f0eee5);
		border-top: 1px solid var(--color-border, #e8e6dd);
		color: var(--color-muted, #6f6e69);
		font-family: 'Inter', -apple-system, system-ui, sans-serif;
		font-size: 11.5px;
	}
	.foot-status { display: flex; align-items: center; gap: 8px; }
	.foot-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-accent, #c96342);
		box-shadow: 0 0 0 3px var(--color-accent-bg, #faf2ed);
	}
	.foot-version {
		color: var(--color-dim, #97968f);
		letter-spacing: 0.02em;
	}

	/* Notification Bell */
	.notif-badge {
		position: absolute;
		top: 0;
		right: -2px;
		background: #ff4444;
		color: white;
		font-size: 9px;
		font-weight: 900;
		min-width: 16px;
		height: 16px;
		border-radius: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
		padding: 0 3px;
	}

	/* Notification Panel */
	.notif-panel {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		width: 340px;
		max-height: 420px;
		background: white;
		border: 1px solid var(--color-border, #d8d5cc);
		border-radius: 8px;
		box-shadow: 0 1px 3px rgba(0,0,0,0.06);
		z-index: 100;
		display: flex;
		flex-direction: column;
	}
	.notif-panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		border-bottom: 1px solid #eee;
		color: var(--color-on-surface, #2c2c2c);
	}
	.notif-mark-all {
		background: none;
		border: none;
		color: var(--color-accent, #c96342);
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		font-family: 'Space Grotesk', sans-serif;
	}
	.notif-mark-all:hover {
		text-decoration: underline;
	}
	.notif-panel-body {
		overflow-y: auto;
		flex: 1;
	}
	.notif-empty {
		padding: 2rem;
		text-align: center;
		color: #aaa;
		font-size: 12px;
	}
	.notif-item {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 10px 14px;
		border-bottom: 1px solid #f5f5f0;
		cursor: pointer;
		width: 100%;
		background: none;
		border-left: none;
		border-right: none;
		border-top: none;
		text-align: left;
		font-family: 'Space Grotesk', sans-serif;
		transition: background 0.1s;
	}
	.notif-item:hover {
		background: #fafaf5;
	}
	.notif-unread {
		background: #f8fff0;
	}
	.notif-dot-wrap {
		width: 8px;
		flex-shrink: 0;
		padding-top: 5px;
	}
	.notif-dot {
		width: 8px;
		height: 8px;
		background: var(--color-accent, #c96342);
		border: 1px solid rgba(201,99,66,0.5);
		border-radius: 50%;
	}
	.notif-content {
		flex: 1;
		min-width: 0;
	}
	.notif-title {
		font-size: 12px;
		font-weight: 700;
		color: var(--color-on-surface, #2c2c2c);
		line-height: 1.3;
	}
	.notif-msg {
		font-size: 11px;
		color: #888;
		margin-top: 2px;
		line-height: 1.3;
	}
	.notif-time {
		font-size: 10px;
		color: #bbb;
		margin-top: 3px;
	}
</style>
