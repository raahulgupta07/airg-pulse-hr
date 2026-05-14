<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { setToken } from '$lib/auth';
  import { getBranding, loadBrandingFromAPI, applyBranding, brandingStore, type Branding } from '$lib/branding';
  import KeyRound from '@lucide/svelte/icons/key-round';
  import Building2 from '@lucide/svelte/icons/building-2';
  import Download from '@lucide/svelte/icons/download';
  import BarChart3 from '@lucide/svelte/icons/bar-chart-3';
  import Newspaper from '@lucide/svelte/icons/newspaper';
  import Image from '@lucide/svelte/icons/image';
  import Mail from '@lucide/svelte/icons/mail';
  import ClipboardList from '@lucide/svelte/icons/clipboard-list';
  import Paperclip from '@lucide/svelte/icons/paperclip';
  import Folder from '@lucide/svelte/icons/folder';

  let branding = $state<Branding>(getBranding());
  const _unsubBranding = brandingStore.subscribe((b) => { branding = b; });

  let operatorId = $state('');
  let accessKey = $state('');
  let showKey = $state(false);
  let error = $state('');
  let loading = $state(false);
  let allowRegister = $state(false);
  let isRegister = $state(false);

  onMount(() => {
    document.body.classList.add('login-active');
    applyBranding(getBranding());
    loadBrandingFromAPI().then((b) => applyBranding(b)).catch(() => {});
    fetch('/api/auth/config')
      .then((r) => (r.ok ? r.json() : { allow_register: false }))
      .then((d) => {
        allowRegister = !!(d?.allow_register ?? d?.allowRegister);
      })
      .catch(() => {});

    return () => {
      document.body.classList.remove('login-active');
      _unsubBranding();
    };
  });

  async function login() {
    if (!operatorId || !accessKey) {
      error = 'Please enter your user ID and password.';
      return;
    }
    loading = true;
    error = '';
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(
          operatorId.includes('@')
            ? { email: operatorId, password: accessKey }
            : { operator_id: operatorId, access_key: accessKey }
        ),
      });
      if (res.status === 200) {
        const data = await res.json().catch(() => ({}));
        const token = data?.token ?? data?.access_token;
        if (token) {
          const expSec = data?.expires_at ?? data?.exp ?? null;
          const expMs = expSec ? Number(expSec) * (expSec > 1e12 ? 1 : 1000) : null;
          setToken(token, expMs);
        }
        await goto('/');
        return;
      }
      if (res.status === 401) error = 'Invalid credentials. Please try again.';
      else if (res.status === 429) error = 'Account locked. Please try again later.';
      else error = `Authentication error (${res.status}).`;
    } catch {
      error = 'Network error. Please retry.';
    }
    loading = false;
  }

  async function register() {
    if (!operatorId || !accessKey) {
      error = 'All fields are required.';
      return;
    }
    if (accessKey.length < 6) {
      error = 'Password must be at least 6 characters.';
      return;
    }
    loading = true;
    error = '';
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ operator_id: operatorId, access_key: accessKey }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        error = (d?.detail || 'Registration failed.').toString();
        loading = false;
        return;
      }
      isRegister = false;
      await login();
    } catch {
      error = 'Network error. Please retry.';
      loading = false;
    }
  }

  function handleKey(e: KeyboardEvent) {
    if (e.key === 'Enter') (isRegister ? register() : login());
  }
</script>

<svelte:head>
  <title>Sign in — {branding.appName}</title>
</svelte:head>

<div class="login-page">

  <!-- Top bar: brand only, no menu -->
  <header class="top-bar">
    <div class="brand">
      {#if branding.logoUrl}
        <div class="brand-logo brand-logo-img"><img src={branding.logoUrl} alt={branding.appName} /></div>
      {:else}
        <div class="brand-logo">{(branding.appName[0] || 'P').toUpperCase()}</div>
      {/if}
      <div class="brand-text">{branding.appName}</div>
    </div>
  </header>

  <main class="split">

    <!-- LEFT: headline + form -->
    <section class="left">
      <h1 class="hero">
        {isRegister ? 'Welcome to' : 'Hire smart,'}<br>
        {isRegister ? branding.appName : 'communicate better'}
      </h1>
      <p class="hero-sub">
        {isRegister ? 'Create your account to get started.' : 'AI co-pilot for hiring, internal comms, broadcasts, and templates.'}
      </p>

      <div class="auth-card">

        <!-- SSO / LDAP buttons -->
        <button class="sso-btn" type="button" onclick={() => alert('SSO not configured. Contact admin.')}>
          <span class="sso-icon"><KeyRound size={16} /></span> Continue with SSO (SAML / OIDC)
        </button>
        <button class="sso-btn" type="button" onclick={() => alert('LDAP not configured. Contact admin.')}>
          <span class="sso-icon"><Building2 size={16} /></span> Continue with LDAP / Active Directory
        </button>
        <div class="divider"><span>or</span></div>

        <div class="field">
          <input
            id="operator-id"
            type="text"
            bind:value={operatorId}
            onkeydown={handleKey}
            placeholder="User ID or email"
            class="field-input"
            autocomplete="username"
          />
        </div>

        <div class="field">
          <div class="field-wrap">
            <input
              id="access-key"
              type={showKey ? 'text' : 'password'}
              bind:value={accessKey}
              onkeydown={handleKey}
              placeholder="Password"
              class="field-input"
              style="padding-right:60px;"
              autocomplete={isRegister ? 'new-password' : 'current-password'}
            />
            <button type="button" onclick={() => (showKey = !showKey)} class="show-btn" aria-label={showKey ? 'Hide password' : 'Show password'}>
              {showKey ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        {#if error}
          <div class="login-error" role="alert">{error}</div>
        {/if}

        <button onclick={() => (isRegister ? register() : login())} disabled={loading} class="login-btn">
          {loading ? 'Please wait…' : isRegister ? 'Create account' : 'Continue with email'}
        </button>

        {#if allowRegister}
          <div class="login-footer-link">
            <button onclick={() => { isRegister = !isRegister; error = ''; }} class="link-btn">
              {isRegister ? 'Already have an account? Sign in' : 'Need an account? Register'}
            </button>
          </div>
        {/if}
      </div>

    </section>

    <!-- RIGHT: animated preview canvas (Claude.ai style) -->
    <aside class="right">
      <div class="canvas">
        <!-- grid bg -->
        <div class="grid-bg"></div>

        <!-- 6 feature tiles — hire + comm mix -->
        <div class="tiles">
          <div class="tile" data-tile="1"><span class="tile-icon"><Download size={20} /></span> Ingest CVs</div>
          <div class="tile" data-tile="2"><span class="tile-icon"><BarChart3 size={20} /></span> Match candidates</div>
          <div class="tile" data-tile="3"><span class="tile-icon"><Newspaper size={20} /></span> Draft article</div>
          <div class="tile" data-tile="4"><span class="tile-icon"><Image size={20} /></span> Generate image</div>
          <div class="tile" data-tile="5"><span class="tile-icon"><Mail size={20} /></span> Broadcast email</div>
          <div class="tile" data-tile="6"><span class="tile-icon"><ClipboardList size={20} /></span> Use template</div>
        </div>

        <!-- animated cursor -->
        <div class="cursor"></div>

        <!-- floating chat bubbles (comm theme) -->
        <div class="bubble bubble-1">"Draft Eid greeting for all staff"</div>
        <div class="bubble bubble-2">✓ Sent to 240 employees · 2s</div>
        <div class="bubble bubble-3"><Paperclip size={12} /> hse_manager_offer.docx</div>

        <!-- bottom dock -->
        <div class="dock">
          <button class="dock-folder" type="button"><Folder size={14} /> Q4 hiring · Dubai office</button>
          <button class="dock-add" type="button">+</button>
          <button class="dock-go" type="button">Let's go →</button>
        </div>
      </div>
    </aside>

  </main>

  <footer class="login-footer">© 2026 {branding.appName} · {branding.footerText}</footer>
</div>

<style>
  :global(body.login-active), :global(html:has(body.login-active)) {
    background: var(--color-bg, #faf9f5) !important;
    color-scheme: light !important;
  }
  :global(body.login-active main), :global(body.login-active main > div) {
    background: transparent !important;
  }

  .login-page {
    min-height: 100vh;
    background: var(--color-bg, #faf9f5);
    color: var(--color-ink, #2c2c2c);
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: 14.5px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    display: flex;
    flex-direction: column;
  }

  .top-bar {
    padding: 22px 36px;
    display: flex;
    align-items: center;
    justify-content: flex-start;
  }
  .brand { display: flex; align-items: center; gap: 11px; }
  .brand-logo {
    width: 32px; height: 32px; border-radius: 9px;
    background: var(--color-accent, #c96342); color: #fff;
    display: grid; place-items: center;
    font-weight: 700; font-size: 15px;
    font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
  }
  .brand-logo.brand-logo-img { background: transparent !important; padding: 0; overflow: hidden; }
  .brand-logo.brand-logo-img img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .brand-text {
    font-weight: 600; font-size: 20px; letter-spacing: -0.01em;
    font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
    color: var(--color-ink, #2c2c2c);
  }

  .split {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
    padding: 24px 48px 40px;
    max-width: 1320px;
    margin: 0 auto;
    width: 100%;
    align-items: center;
  }

  /* LEFT */
  .left {
    display: flex; flex-direction: column;
    max-width: 460px;
    margin-left: auto;
    margin-right: 24px;
    width: 100%;
  }
  .hero {
    font-family: 'Tiempos Headline', 'Charter', 'Source Serif Pro', Georgia, serif;
    font-size: 64px;
    line-height: 1.05;
    font-weight: 500;
    letter-spacing: -0.035em;
    margin: 0 0 16px;
    color: var(--color-ink, #2c2c2c);
  }
  .hero-sub {
    font-size: 16px;
    color: var(--color-muted, #6f6e69);
    margin: 0 0 36px;
    max-width: 380px;
  }

  .auth-card {
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }

  .field { margin-bottom: 12px; }
  .field-wrap { position: relative; }
  .field-input {
    width: 100%;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border-strong, #d8d5cb);
    border-radius: 10px;
    padding: 12px 14px;
    font-family: inherit;
    font-size: 14.5px;
    color: var(--color-ink, #2c2c2c);
    outline: none;
    transition: border-color .15s, box-shadow .15s;
  }
  .field-input::placeholder { color: var(--color-dim, #97968f); }
  .field-input:focus {
    border-color: var(--color-accent, #c96342);
    box-shadow: 0 0 0 3px var(--color-accent-bg, #faf2ed);
  }

  .show-btn {
    position: absolute;
    right: 10px; top: 50%;
    transform: translateY(-50%);
    background: transparent; border: none;
    font-family: inherit; font-size: 12.5px; font-weight: 500;
    color: var(--color-muted, #6f6e69);
    cursor: pointer; padding: 4px 8px; border-radius: 6px;
  }
  .show-btn:hover { background: var(--color-bg-alt, #f4f3ee); color: var(--color-ink, #2c2c2c); }

  .login-error {
    font-size: 13px;
    color: var(--color-red, #a83232);
    background: var(--color-red-soft, #f5dada);
    border: 1px solid #f0c2c2;
    border-radius: 8px;
    padding: 9px 12px;
    margin: 6px 0 12px;
  }

  .login-btn {
    width: 100%;
    background: #1c1c1c;
    color: #fff;
    border: 1px solid #1c1c1c;
    padding: 13px 16px;
    border-radius: 12px;
    font-family: inherit;
    font-size: 14.5px;
    font-weight: 500;
    cursor: pointer;
    margin-top: 4px;
    transition: background .15s, transform .1s;
  }
  .login-btn:hover:not(:disabled) { background: #2c2c2c; }
  .login-btn:active:not(:disabled) { transform: scale(0.99); }
  .login-btn:disabled { opacity: 0.55; cursor: not-allowed; }

  .login-footer-link {
    margin-top: 14px;
    text-align: center;
  }
  .link-btn {
    background: none; border: none; cursor: pointer;
    font-family: inherit; font-size: 13px;
    color: var(--color-accent, #c96342);
    font-weight: 500; padding: 4px 8px; border-radius: 6px;
  }
  .link-btn:hover { text-decoration: underline; }

  /* Floating chat bubbles on right canvas */
  .bubble {
    position: absolute;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 12px;
    color: var(--color-ink, #2c2c2c);
    box-shadow: 0 4px 14px rgba(0,0,0,0.06);
    opacity: 0;
    z-index: 5;
    white-space: nowrap;
    max-width: 240px;
  }
  .bubble-1 {
    top: 12%; left: 6%;
    background: var(--color-accent, #c96342);
    color: #fff; border-color: var(--color-accent, #c96342);
    border-bottom-left-radius: 4px;
    animation: bubble-pop-1 12s ease-in-out infinite;
  }
  .bubble-2 {
    top: 14%; right: 6%;
    color: var(--color-success, #2d6a4f);
    border-color: var(--color-success-soft, #d8e4dd);
    background: var(--color-success-soft, #d8e4dd);
    animation: bubble-pop-2 12s ease-in-out infinite;
  }
  .bubble-3 {
    bottom: 24%; left: 8%;
    color: var(--color-ink-soft, #4a4a48);
    animation: bubble-pop-3 12s ease-in-out infinite;
  }

  @keyframes bubble-pop-1 {
    0%, 4%   { opacity: 0; transform: translateY(8px); }
    8%, 36%  { opacity: 1; transform: translateY(0); }
    44%, 100%{ opacity: 0; transform: translateY(-8px); }
  }
  @keyframes bubble-pop-2 {
    0%, 38%  { opacity: 0; transform: translateY(8px); }
    42%, 70% { opacity: 1; transform: translateY(0); }
    78%, 100%{ opacity: 0; transform: translateY(-8px); }
  }
  @keyframes bubble-pop-3 {
    0%, 70%  { opacity: 0; transform: translateY(8px); }
    74%, 96% { opacity: 1; transform: translateY(0); }
    100%     { opacity: 0; transform: translateY(-8px); }
  }

  /* SSO buttons */
  .sso-btn {
    width: 100%;
    display: flex; align-items: center; justify-content: center;
    gap: 10px;
    background: var(--color-surface, #ffffff);
    color: var(--color-ink, #2c2c2c);
    border: 1px solid var(--color-border-strong, #d8d5cb);
    padding: 11px 16px;
    border-radius: 10px;
    font-family: inherit;
    font-size: 13.5px;
    font-weight: 500;
    cursor: pointer;
    margin-bottom: 8px;
    transition: background .15s, border-color .15s;
  }
  .sso-btn:hover {
    background: var(--color-bg-alt, #f4f3ee);
    border-color: var(--color-dim, #97968f);
  }
  .sso-icon {
    font-size: 14px;
    width: 18px; text-align: center;
    font-weight: 700;
  }
  .sso-btn.google .sso-icon {
    background: linear-gradient(45deg, #4285f4, #ea4335 25%, #fbbc05 50%, #34a853 75%);
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
  }

  .divider {
    display: flex; align-items: center; gap: 12px;
    margin: 14px 0 14px;
    color: var(--color-dim, #97968f);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .divider::before, .divider::after {
    content: ''; flex: 1; height: 1px;
    background: var(--color-border, #e8e6dd);
  }

  /* RIGHT — animated canvas */
  .right {
    display: flex; align-items: center; justify-content: center;
    padding-left: 24px;
    height: 100%;
    min-height: 540px;
  }
  .canvas {
    position: relative;
    width: 100%;
    max-width: 560px;
    height: 540px;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 20px;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }
  .grid-bg {
    position: absolute; inset: 0;
    background-image:
      linear-gradient(to right, rgba(0,0,0,0.04) 1px, transparent 1px),
      linear-gradient(to bottom, rgba(0,0,0,0.04) 1px, transparent 1px);
    background-size: 32px 32px;
    background-position: -1px -1px;
    pointer-events: none;
  }

  /* Tiles grid 3x2 in middle */
  .tiles {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -55%);
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    width: 88%;
    max-width: 480px;
  }
  .tile {
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 12px;
    padding: 16px 14px;
    font-size: 13px;
    font-weight: 500;
    color: var(--color-ink, #2c2c2c);
    display: flex; flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    transition: background .25s, border-color .25s, transform .25s;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
  }
  .tile-icon { font-size: 18px; }

  /* Cursor animation: hops between tiles, highlights each in turn */
  .cursor {
    position: absolute;
    width: 18px; height: 18px;
    pointer-events: none;
    z-index: 10;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%231c1c1c' stroke='white' stroke-width='1.5'><path d='M3 2l6 17 2.5-7 7-2.5L3 2z'/></svg>");
    background-size: contain;
    background-repeat: no-repeat;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.25));
    animation: cursor-tour 12s ease-in-out infinite;
  }

  /* Cursor jumps between 6 tiles */
  @keyframes cursor-tour {
    0%   { top: 28%; left: 22%; }
    14%  { top: 32%; left: 26%; }   /* near tile 1 */
    16%  { top: 32%; left: 26%; }
    30%  { top: 32%; left: 50%; }   /* tile 2 */
    32%  { top: 32%; left: 50%; }
    46%  { top: 32%; left: 74%; }   /* tile 3 */
    48%  { top: 32%; left: 74%; }
    62%  { top: 56%; left: 26%; }   /* tile 4 */
    64%  { top: 56%; left: 26%; }
    78%  { top: 56%; left: 50%; }   /* tile 5 */
    80%  { top: 56%; left: 50%; }
    94%  { top: 56%; left: 74%; }   /* tile 6 */
    96%  { top: 56%; left: 74%; }
    100% { top: 28%; left: 22%; }
  }

  /* Highlight tiles in sync with cursor */
  .tile {
    animation: tile-rest 12s ease-in-out infinite;
  }
  .tile[data-tile="1"] { animation-delay: 0s;     }
  .tile[data-tile="2"] { animation-delay: -10s;   }
  .tile[data-tile="3"] { animation-delay: -8s;    }
  .tile[data-tile="4"] { animation-delay: -6s;    }
  .tile[data-tile="5"] { animation-delay: -4s;    }
  .tile[data-tile="6"] { animation-delay: -2s;    }

  @keyframes tile-rest {
    0%, 12%   { background: var(--color-bg-alt, #f4f3ee); border-color: var(--color-accent, #c96342); transform: scale(1.04); box-shadow: 0 4px 14px rgba(201,99,66,0.15); }
    20%, 100% { background: var(--color-surface, #ffffff); border-color: var(--color-border, #e8e6dd); transform: scale(1); box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
  }

  /* Bottom dock (folder + actions) */
  .dock {
    position: absolute;
    bottom: 24px; left: 24px; right: 24px;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 14px;
    padding: 8px;
    display: flex; align-items: center; gap: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.04);
  }
  .dock-folder {
    flex: 1;
    background: transparent;
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 9px;
    padding: 8px 12px;
    font-family: inherit;
    font-size: 13px;
    color: var(--color-ink-soft, #4a4a48);
    text-align: left;
    cursor: default;
  }
  .dock-add {
    width: 32px; height: 32px; border-radius: 8px;
    background: transparent;
    border: 1px solid var(--color-border, #e8e6dd);
    color: var(--color-muted, #6f6e69);
    font-size: 16px; font-weight: 600;
    cursor: pointer;
  }
  .dock-go {
    background: var(--color-accent-bg, #faf2ed);
    color: var(--color-accent, #c96342);
    border: 1px solid var(--color-accent-soft, #fdebe1);
    border-radius: 9px;
    padding: 8px 16px;
    font-family: inherit;
    font-size: 13px;
    font-weight: 500;
    cursor: default;
  }

  .login-footer {
    font-size: 12px;
    color: var(--color-dim, #97968f);
    text-align: center;
    padding: 16px 0 24px;
  }

  /* Mobile */
  @media (max-width: 900px) {
    .split { grid-template-columns: 1fr; padding: 16px 24px 32px; }
    .left { margin: 0 auto; max-width: 480px; }
    .right { display: none; }
    .hero { font-size: 44px; }
    .top-bar { padding: 18px 24px; }
  }
</style>
