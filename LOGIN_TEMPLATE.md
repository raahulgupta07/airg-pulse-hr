# Brutalist Terminal Login — Reusable Template

Reusable spec to drop the **PULSE / DASH** style login (dark terminal + animated robot + yellow access card) into any future Svelte / SvelteKit project. Self-contained — no shared CSS dependencies, no design-system assumptions.

---

## What you get

- Dark `#1a1a1e` page (header · main · footer)
- Left pane: mac-style terminal window
  - 3 traffic-light dots
  - Floating robot SVG (antenna pulse + eye blink)
  - Char-by-char typed boot sequence (configurable lines)
  - Big ASCII brand letters
  - Final blinking caret line
- Right pane: yellow `#feffd6` brutalist login card
  - `ACCESS_PORTAL` title
  - Brand block (gradient stripe + acronym row)
  - `OPERATOR_ID` + `ACCESS_KEY` inputs
  - SHOW/HIDE password toggle
  - Green `INITIATE_AUTHENTICATION` button
  - Conditional REGISTER toggle
- Sticky dark header (logo box + brand badge + `SECURE_TERMINAL`)
- Sticky dark footer (copyright · acronym · `SECURE_TERMINAL`)
- Fully responsive (terminal hides under 768px)

---

## Hard requirements

| Item | Why |
|------|-----|
| **SvelteKit 5 (Runes)** — `$state`, `$effect`, `onMount` | Animation state + cursor blink |
| **Google Font: Space Grotesk** | Brand typography (terminal + UI) |
| **Auth endpoint** that accepts `{operator_id, access_key}` (or maps to `{email, password}`) and returns `{token, expires_at?}` | Login submit |
| **Public auth-config endpoint** `GET /api/auth/config` returning `{allow_register: bool}` | Toggle register link |
| **Token store helper** `setToken(token, expMs?)` | Persist after login |
| **Route guard in `+layout.ts`** that bypasses `/login` | Avoid auth loop |
| **`isPublicRoute` flag in root layout** that skips wrapper for `/login` | Login owns its own chrome |

---

## File structure

```
frontend/
├── src/
│   ├── lib/
│   │   └── auth.ts                # setToken/getToken/me/logout
│   ├── routes/
│   │   ├── +layout.svelte         # MUST gate /login behind isPublicRoute
│   │   ├── +layout.ts             # MUST skip /login in route guard
│   │   └── login/
│   │       └── +page.svelte       # ← single self-contained file
│   └── app.html                   # MUST preconnect Google Fonts + load Space Grotesk
└── static/
```

---

## Step 1 — Load Space Grotesk

In `src/app.html` `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700;900&display=swap" rel="stylesheet" />
```

---

## Step 2 — Auth helper (`src/lib/auth.ts`)

Minimal contract the login page calls:

```ts
const TOKEN_KEY = '<app>_token';
const EXP_KEY = '<app>_token_exp';

export function setToken(token: string, expMs: number | null = null) {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
  if (expMs) localStorage.setItem(EXP_KEY, String(expMs));
}
export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  const exp = Number(localStorage.getItem(EXP_KEY) || '0');
  if (exp && Date.now() > exp) { clearToken(); return null; }
  return localStorage.getItem(TOKEN_KEY);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXP_KEY);
}
```

Replace `<app>` with project slug (`pulse_token`, `dash_token`, etc.).

---

## Step 3 — Layout guard (`src/routes/+layout.svelte`)

Must skip wrapper for `/login` so login owns the full viewport:

```svelte
<script lang="ts">
  import { page } from '$app/state';
  let { children } = $props();
  let isPublicRoute = $derived(
    page.url?.pathname?.startsWith('/login') ||
    page.url?.pathname?.startsWith('/careers') ||  // optional public pages
    page.url?.pathname?.startsWith('/register')
  );
</script>

{#if isPublicRoute}
  {@render children()}
{:else}
  <!-- normal app shell with header/footer -->
{/if}
```

And `+layout.ts`:

```ts
import { redirect } from '@sveltejs/kit';
import type { LoadEvent } from '@sveltejs/kit';
export const ssr = false;
export const prerender = false;
export async function load({ url }: LoadEvent) {
  const skip = ['/login', '/register', '/careers'];
  if (skip.some((p) => url.pathname.startsWith(p))) return {};
  // call /api/auth/me — on 401 throw redirect(303, '/login')
  return {};
}
```

---

## Step 4 — Drop in login page

Save as `src/routes/login/+page.svelte`. Search-and-replace tokens before pasting:

| Token | Meaning | Example |
|-------|---------|---------|
| `__BRAND__` | Short uppercase brand | `PULSE` |
| `__BRAND_LONG__` | Brand line under title | `PULSE — ORG HEARTBEAT` |
| `__ACRONYM_PARTS__` | Letter expansion | `People · Updates · Lifecycle · Sourcing · Engagement` |
| `__BOOT_LINES__` | Boot sequence | see template below |
| `__BIG_LETTERS__` | 2–3 ASCII headline words | `PULSE / ORG / AGENT` |
| `__AUTH_LOGIN_URL__` | POST endpoint | `/api/auth/login` |
| `__AUTH_CONFIG_URL__` | Config endpoint | `/api/auth/config` |
| `__AUTH_REGISTER_URL__` | POST endpoint | `/api/auth/register` |
| `__POST_LOGIN_PATH__` | Where to navigate after success | `/` |
| `__SETTOKEN_IMPORT__` | Auth helper import | `$lib/auth` |
| `__TAGLINE__` | Robot intro | `Your org-heartbeat agent.` |
| `__AGENT_LIST__` | Module list | see template |

Full file:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { setToken } from '__SETTOKEN_IMPORT__';

  let operatorId = $state('');
  let accessKey = $state('');
  let showKey = $state(false);
  let error = $state('');
  let loading = $state(false);
  let allowRegister = $state(false);
  let isRegister = $state(false);

  let terminalLines = $state<{ text: string; typed: string; done: boolean; color?: string }[]>([]);
  let cursorVisible = $state(true);
  let bootDone = $state(false);

  const BOOT_SEQUENCE = [
    { text: '[__BRAND__] Waking up...', delay: 70, color: 'dim' },
    { text: '', delay: 200, color: '' },
    { text: '🤖 Hey! I\'m __BRAND__.', delay: 55, color: '' },
    { text: '   __TAGLINE__', delay: 40, color: 'dim' },
    { text: '', delay: 300, color: '' },
    { text: '   Let me get everything ready...', delay: 45, color: 'dim' },
    { text: '', delay: 200, color: '' },
    // __AGENT_LIST__ — pad each label so dots line up. STATUS word at end is auto-greened.
    { text: '   ◆ HR Brain ············· ONLINE', delay: 35, color: 'green' },
    { text: '   ◆ Talent DB ············ CONNECTED', delay: 40, color: 'green' },
    { text: '   ◆ OCR Pool ············· READY', delay: 35, color: 'green' },
    { text: '   ◆ Comms Bus ············ ACTIVE', delay: 40, color: 'green' },
    { text: '   ◆ Ad Broadcaster ······· ARMED', delay: 35, color: 'green' },
    { text: '', delay: 300, color: '' },
    { text: '   All systems go.', delay: 40, color: '' },
    { text: '', delay: 400, color: '' },
    // __BIG_LETTERS__ — one per line
    { text: 'PULSE', delay: 120, color: 'big' },
    { text: 'ORG',   delay: 120, color: 'big' },
    { text: 'AGENT', delay: 120, color: 'big' },
    { text: '', delay: 300, color: '' },
    { text: '   Ready when you are, operator.', delay: 45, color: 'dim' },
    { text: '   Login to start →', delay: 40, color: 'blink' },
  ];

  onMount(() => {
    fetch('__AUTH_CONFIG_URL__')
      .then((r) => (r.ok ? r.json() : { allow_register: false }))
      .then((d) => { allowRegister = !!(d?.allow_register ?? d?.allowRegister); })
      .catch(() => {});
    const cursorInterval = setInterval(() => { cursorVisible = !cursorVisible; }, 530);
    runBootSequence();
    return () => clearInterval(cursorInterval);
  });

  async function runBootSequence() {
    for (const line of BOOT_SEQUENCE) {
      const entry = { text: line.text, typed: '', done: false, color: line.color };
      terminalLines = [...terminalLines, entry];
      for (let i = 0; i < line.text.length; i++) {
        await sleep(line.delay);
        terminalLines = [...terminalLines.slice(0, -1), { ...entry, typed: line.text.slice(0, i + 1) }];
      }
      terminalLines = [...terminalLines.slice(0, -1), { ...entry, typed: line.text, done: true }];
      await sleep(100);
    }
    bootDone = true;
  }
  const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

  async function login() {
    if (!operatorId || !accessKey) { error = 'OPERATOR_ID AND ACCESS_KEY REQUIRED'; return; }
    loading = true; error = '';
    try {
      const res = await fetch('__AUTH_LOGIN_URL__', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          operator_id: operatorId, access_key: accessKey,
          email: operatorId, password: accessKey,  // back-compat
        }),
      });
      if (res.status === 200) {
        const data = await res.json();
        const token = data?.token ?? data?.access_token;
        if (!token) { error = 'NO TOKEN RETURNED'; loading = false; return; }
        const expSec = data?.expires_at ?? data?.exp ?? null;
        const expMs = expSec ? Number(expSec) * (expSec > 1e12 ? 1 : 1000) : null;
        setToken(token, expMs);
        await goto('__POST_LOGIN_PATH__');
        return;
      }
      if (res.status === 401) error = 'INVALID_CREDENTIALS';
      else if (res.status === 429) error = 'ACCOUNT LOCKED — TRY AGAIN LATER';
      else error = `AUTH_ERROR_${res.status}`;
    } catch { error = 'NETWORK_ERROR — RETRY'; }
    loading = false;
  }

  async function register() {
    if (!operatorId || !accessKey) { error = 'ALL FIELDS REQUIRED'; return; }
    if (accessKey.length < 6) { error = 'ACCESS_KEY MUST BE 6+ CHARS'; return; }
    loading = true; error = '';
    try {
      const res = await fetch('__AUTH_REGISTER_URL__', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operator_id: operatorId, access_key: accessKey }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        error = (d?.detail || 'REGISTRATION_FAILED').toString().toUpperCase();
        loading = false; return;
      }
      isRegister = false; await login();
    } catch { error = 'NETWORK_ERROR — RETRY'; loading = false; }
  }

  function handleKey(e: KeyboardEvent) { if (e.key === 'Enter') (isRegister ? register() : login()); }
</script>

<svelte:head><title>ACCESS_PORTAL — __BRAND__</title></svelte:head>

<div class="login-page">
  <header class="login-header">
    <div style="display:flex; align-items:center; gap:10px;">
      <div class="login-logo-box">
        <!-- Robot/lock icon — keep currentColor so the brand-color box paints it -->
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="2" x2="12" y2="6" /><circle cx="12" cy="2" r="1" fill="currentColor" />
          <rect x="3" y="11" width="18" height="10" /><line x1="12" y1="6" x2="12" y2="11" />
          <rect x="7" y="14" width="3" height="2" fill="currentColor" /><rect x="14" y="14" width="3" height="2" fill="currentColor" />
          <line x1="9" y1="18" x2="15" y2="18" />
        </svg>
      </div>
      <div class="login-logo-badge">__BRAND__</div>
    </div>
    <div class="login-header-right">SECURE_TERMINAL</div>
  </header>

  <div class="login-main">
    <div class="login-container">
      <!-- Left: Terminal -->
      <div class="login-branding">
        <div class="terminal-window">
          <div class="terminal-titlebar">
            <span class="terminal-dot" style="background:#ff5f56;"></span>
            <span class="terminal-dot" style="background:#ffbd2e;"></span>
            <span class="terminal-dot" style="background:#27c93f;"></span>
            <span style="margin-left:8px; font-size:10px; opacity:0.5;">__brand__ — thinking...</span>
          </div>
          <div class="terminal-body">
            <div class="robot-icon" style="margin-bottom:12px;">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#00fc40" stroke-width="1.5">
                <line x1="12" y1="2" x2="12" y2="6" class="antenna" />
                <circle cx="12" cy="2" r="1" fill="#00fc40" class="antenna-dot" />
                <rect x="3" y="11" width="18" height="10" />
                <line x1="12" y1="6" x2="12" y2="11" />
                <rect x="7" y="14" width="3" height="2" fill="#00fc40" class="eye-left" />
                <rect x="14" y="14" width="3" height="2" fill="#00fc40" class="eye-right" />
                <line x1="9" y1="18" x2="15" y2="18" />
              </svg>
            </div>
            {#each terminalLines as line}
              {#if line.color === 'big'}
                <div class="terminal-big">{line.typed}</div>
              {:else if line.color === 'blink'}
                <div class="terminal-line terminal-blink">
                  {line.typed}{#if !line.done}<span class="terminal-cursor" class:terminal-cursor-visible={cursorVisible}>_</span>{/if}
                </div>
              {:else if line.color === 'dim'}
                <div class="terminal-line terminal-dim">{line.typed}</div>
              {:else if line.color === 'green'}
                <div class="terminal-line">
                  {#if /(OK|READY|ACTIVE|ONLINE|CONNECTED|ARMED|IDLE|LOADED|SECURED)$/.test(line.typed)}
                    {line.typed.slice(0, -line.typed.split(' ').pop()!.length)}<span class="terminal-ok">{line.typed.split(' ').pop()}</span>
                  {:else}
                    {line.typed}{#if !line.done}<span class="terminal-cursor" class:terminal-cursor-visible={cursorVisible}>_</span>{/if}
                  {/if}
                </div>
              {:else if line.text === ''}
                <div class="terminal-line">&nbsp;</div>
              {:else}
                <div class="terminal-line">{line.typed}{#if !line.done}<span class="terminal-cursor" class:terminal-cursor-visible={cursorVisible}>_</span>{/if}</div>
              {/if}
            {/each}
            {#if !bootDone && terminalLines.length === 0}
              <div class="terminal-line"><span class="terminal-cursor terminal-cursor-visible">_</span></div>
            {/if}
          </div>
        </div>
      </div>

      <!-- Right: Login Form -->
      <div class="login-form-card">
        <div style="padding:32px 28px;">
          <div class="login-title">ACCESS_PORTAL</div>
          <div class="login-subtitle">AUTHORIZED ACCESS ONLY. LOGGING ACTIVE.</div>

          <div class="brand-block">
            <div class="brand-tag">__BRAND_LONG__</div>
            <div class="brand-acro">
              <!-- Replace with literal acronym words separated by sep spans -->
              <span>People</span><span class="sep">·</span>
              <span>Updates</span><span class="sep">·</span>
              <span>Lifecycle</span><span class="sep">·</span>
              <span>Sourcing</span><span class="sep">·</span>
              <span>Engagement</span>
            </div>
          </div>

          <div style="margin-bottom:16px;">
            <div class="tag-label">OPERATOR_ID</div>
            <input type="text" bind:value={operatorId} onkeydown={handleKey} placeholder="Enter credentials" class="login-input" autocomplete="username" />
          </div>

          <div style="margin-bottom:20px;">
            <div class="tag-label">ACCESS_KEY</div>
            <div style="position:relative;">
              <input type={showKey ? 'text' : 'password'} bind:value={accessKey} onkeydown={handleKey} placeholder="Enter passphrase" class="login-input" style="padding-right:60px;" autocomplete={isRegister ? 'new-password' : 'current-password'} />
              <button type="button" onclick={() => (showKey = !showKey)} class="login-show-btn">{showKey ? 'HIDE' : 'SHOW'}</button>
            </div>
          </div>

          {#if error}<div class="login-error">{error}</div>{/if}

          <button onclick={() => (isRegister ? register() : login())} disabled={loading} class="login-btn">
            {loading ? 'PROCESSING...' : isRegister ? 'CREATE_ACCOUNT' : 'INITIATE_AUTHENTICATION'}
          </button>

          {#if allowRegister}
            <div class="login-footer-link">
              <button onclick={() => { isRegister = !isRegister; error = ''; }} class="link-btn">
                {isRegister ? 'ALREADY HAVE ACCESS? LOGIN' : 'NEW USER? REGISTER'}
              </button>
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>

  <footer class="login-footer">
    <span>&copy; 2026 __BRAND__ AI</span>
    <span>__ACRONYM_PARTS__</span>
    <span>SECURE_TERMINAL</span>
  </footer>
</div>

<style>
  /* Beat any global app.css yellow-bg / light-scheme rule */
  :global(html), :global(body) { background:#1a1a1e !important; color-scheme:dark !important; }
  :global(main), :global(main > div) { background:transparent !important; }

  .login-page { min-height:100vh; background:#1a1a1e !important; font-family:'Space Grotesk', monospace, sans-serif; display:flex; flex-direction:column; color:#feffd6; }
  .login-header { display:flex; align-items:center; justify-content:space-between; padding:12px 24px; border-bottom:1px solid rgba(255,255,255,0.08); }
  .login-header-right { color:rgba(255,255,255,0.3); font-size:11px; letter-spacing:0.15em; text-transform:uppercase; font-weight:700; }
  .login-logo-box { background:#00fc40; color:#1a1a1e; padding:6px; border:2px solid #00fc40; display:flex; align-items:center; justify-content:center; }
  .login-logo-badge { background:#00fc40; color:#1a1a1e; padding:4px 14px; font-size:13px; font-weight:900; letter-spacing:0.08em; }
  .login-main { flex:1; display:flex; align-items:center; justify-content:center; padding:24px; }
  .login-container { display:flex; gap:60px; align-items:center; max-width:1050px; width:100%; }
  .login-footer { display:flex; align-items:center; justify-content:space-between; gap:24px; padding:10px 24px; border-top:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.2); font-size:10px; letter-spacing:0.1em; text-transform:uppercase; }

  .login-branding { flex:1; display:none; flex-direction:column; }
  @media (min-width:768px) { .login-branding { display:flex; } }
  .terminal-window { border:1px solid rgba(255,255,255,0.15); background:#0d0d12; overflow:hidden; }
  .terminal-titlebar { display:flex; align-items:center; gap:6px; padding:8px 12px; background:#2a2a30; border-bottom:1px solid rgba(255,255,255,0.08); }
  .terminal-dot { width:10px; height:10px; border-radius:50% !important; display:inline-block; }
  .terminal-body { padding:16px; min-height:320px; font-size:12px; line-height:1.7; font-family:'Space Grotesk', monospace; }
  .terminal-line { color:rgba(255,255,255,0.6); white-space:nowrap; }
  .terminal-ok { color:#00fc40; font-weight:700; }
  .terminal-dim { color:rgba(255,255,255,0.35); font-size:12px; letter-spacing:0.08em; }
  .terminal-big { color:rgba(255,255,255,0.95); font-size:52px; font-weight:900; line-height:0.95; letter-spacing:-0.03em; }
  .terminal-blink { color:#00fc40; animation:termBlink 1s step-end infinite; }
  .terminal-cursor { color:#00fc40; font-weight:400; opacity:0; }
  .terminal-cursor-visible { opacity:1; }
  @keyframes termBlink { 0%,100% { opacity:1; } 50% { opacity:0.3; } }

  .login-form-card { width:420px; max-width:100%; background:#feffd6; border:2px solid #383832; }
  .login-title { font-size:28px; font-weight:900; text-transform:uppercase; letter-spacing:-0.01em; margin-bottom:6px; color:#383832; }
  .login-subtitle { font-size:11px; text-transform:uppercase; letter-spacing:0.1em; color:#6b6b60; margin-bottom:20px; }
  .brand-block { background:#383832; color:#feffd6; padding:10px 12px; margin-bottom:20px; border-left:4px solid #00fc40; }
  .brand-tag { font-size:10px; font-weight:900; letter-spacing:0.12em; }
  .brand-acro { font-size:9px; letter-spacing:0.1em; opacity:0.85; margin-top:4px; display:flex; flex-wrap:wrap; gap:4px; text-transform:uppercase; }
  .brand-acro .sep { opacity:0.4; }
  .tag-label { background:#383832; color:#feffd6; padding:2px 8px; display:inline-block; font-size:9px; font-weight:900; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:6px; }
  .login-input { width:100%; background:#feffd6; border:2px solid #383832; padding:12px 14px; font-family:'Space Grotesk', monospace; font-size:14px; outline:none; color:#383832; }
  .login-input:focus { border-color:#007518; }
  .login-input::placeholder { color:#a0a090; }
  .login-show-btn { position:absolute; right:12px; top:50%; transform:translateY(-50%); background:none; border:none; font-family:'Space Grotesk', monospace; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; cursor:pointer; color:#6b6b60; }
  .login-error { font-size:11px; color:#be2d06; margin-bottom:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; }
  .login-btn { width:100%; background:#00fc40; color:#383832; border:none; padding:14px; font-family:'Space Grotesk', monospace; font-size:13px; font-weight:900; text-transform:uppercase; letter-spacing:0.12em; cursor:pointer; }
  .login-btn:hover { opacity:0.9; }
  .login-btn:disabled { opacity:0.5; cursor:not-allowed; }
  .login-footer-link { border-top:1px solid #383832; margin-top:20px; padding-top:14px; text-align:center; }
  .link-btn { background:none; border:none; cursor:pointer; font-family:'Space Grotesk', monospace; font-size:10px; color:#007518; text-transform:uppercase; letter-spacing:0.08em; font-weight:900; }

  .robot-icon { animation:robotFloat 3s ease-in-out infinite; }
  .robot-icon :global(.antenna-dot) { animation:antennaPulse 1.5s ease-in-out infinite; }
  .robot-icon :global(.eye-left), .robot-icon :global(.eye-right) { animation:eyeBlink 4s ease-in-out infinite; }
  .robot-icon :global(.eye-right) { animation-delay:0.1s; }
  @keyframes robotFloat { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-6px); } }
  @keyframes antennaPulse { 0%,100% { opacity:0.4; } 50% { opacity:1; } }
  @keyframes eyeBlink { 0%,42%,44%,100% { height:2px; } 43% { height:0.5px; } }
</style>
```

---

## Color tokens (one place to change branding)

| Token | Default | Used for |
|-------|---------|----------|
| Page bg | `#1a1a1e` | Page outside terminal/card |
| Terminal bg | `#0d0d12` | Inner terminal body |
| Terminal title bar | `#2a2a30` | Mac chrome strip |
| Brand green | `#00fc40` | Logo box, button, OK status, robot stroke |
| Card surface | `#feffd6` | Login card body |
| Ink | `#383832` | Card text, borders, brand block bg |
| Error red | `#be2d06` | Auth error line |
| Link green | `#007518` | REGISTER toggle |
| Mac dots | `#ff5f56 #ffbd2e #27c93f` | Traffic lights |

To re-skin, swap brand green to your color and re-pick a complementary card surface; everything else can stay.

---

## Cost / time budget

| Aspect | Cost |
|--------|------|
| Boot animation total | ~2.5s (configurable per line) |
| Cursor blink interval | 530ms |
| Robot float cycle | 3s |
| LLM calls | **none** — pure CSS + JS |
| External fetches | 2 (Google Fonts + `/api/auth/config`) |

---

## Backend contract (FastAPI reference)

```python
@router.get('/auth/config')
async def auth_config():
    return {
      'allow_register': os.getenv('ALLOW_REGISTER', 'false').lower() == 'true',
      'app_name': os.getenv('APP_NAME', 'PULSE'),
    }

@router.post('/auth/login')
async def login(body: dict):
    op = body.get('operator_id') or body.get('email')
    pw = body.get('access_key') or body.get('password')
    # ... bcrypt check, lockout, JWT issue
    return {'token': jwt_token, 'expires_at': exp_unix}
```

Lockout response: `429 {"detail": "ACCOUNT_LOCKED", "retry_after": 900}`.

---

## Pre-flight checklist (copy when applying to a new project)

- [ ] Space Grotesk in `app.html`
- [ ] `setToken` helper in `$lib/auth.ts` matches signature
- [ ] `+layout.svelte` skips `/login` via `isPublicRoute`
- [ ] `+layout.ts` whitelists `/login` in route guard
- [ ] Backend `/api/auth/config` returns `{allow_register}`
- [ ] Backend `/api/auth/login` accepts `{operator_id, access_key}` OR `{email, password}` and returns `{token, expires_at?}`
- [ ] Boot sequence agent labels reflect actual project modules
- [ ] `__BRAND__` / `__BRAND_LONG__` / `__ACRONYM_PARTS__` filled
- [ ] `__POST_LOGIN_PATH__` set (usually `/`)
- [ ] Hard reload after deploy (`Cmd+Shift+R`) — Tailwind v4 strips comments and CSS-cache is sticky

---

## Common mistakes

1. **Forgetting `isPublicRoute` gate** — login renders inside main app shell, double header appears.
2. **Forgetting `:global(html), :global(body)` override** — global app yellow-bg leaks through; page looks half-styled.
3. **No `color-scheme:dark`** — Safari/macOS forces input autofill yellow over the dark inputs.
4. **Wrong status-keyword regex** in `green` branch — last word doesn't auto-color. Update regex if your boot lines use different statuses.
5. **Boot sequence too long** — first paint feels slow. Keep total under 3s; pad with empty `delay:300` lines for breathing room instead of long text.
6. **Robot SVG animation classes not picked up** — must use `:global(.antenna-dot)` etc. since SVG children are not Svelte-scoped.
7. **`+layout.ts` not skipping `/login`** — infinite redirect loop on bad creds.

---

## Variants

- **No terminal** (mobile-only, faster ship): drop `.login-branding` entirely, center the card.
- **Different boot vibe**: swap robot SVG for any 24×24 lucide icon; keep classes `antenna-dot`, `eye-left`, `eye-right` on animated elements.
- **OAuth/SSO**: insert SSO button below INITIATE_AUTHENTICATION, gated on `oidcEnabled` from `/api/auth/config`.
- **Single brand color** (no dark page): swap page bg to `#feffd6`, terminal stays dark — yellow-on-dark contrast still works.

---

## License / attribution

Free to copy/modify across projects. Originally derived from City-Dash + PULSE login designs.
