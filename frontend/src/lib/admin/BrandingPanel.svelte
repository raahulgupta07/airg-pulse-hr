<script lang="ts">
  import { onMount } from 'svelte';
  import {
    DEFAULT_BRANDING,
    getBranding,
    loadBrandingFromAPI,
    saveBrandingToAPI,
    saveBrandingLocal,
    applyBranding,
    deriveAccentShades,
    brandingStore,
    brandingBackendReachable,
    type Branding,
  } from '$lib/branding';
  import { addToast } from '$lib/Toast.svelte';

  const MAX_LOGO_BYTES = 256 * 1024; // 256 KB

  let appName = $state(DEFAULT_BRANDING.appName);
  let logoUrl = $state(DEFAULT_BRANDING.logoUrl);
  let accentColor = $state(DEFAULT_BRANDING.accentColor);
  let footerText = $state(DEFAULT_BRANDING.footerText);

  let saving = $state(false);
  let logoError = $state('');
  let backendKnownGood = $state(false); // becomes true after a successful initial GET; suppresses banner in happy path
  let localOnly = $state(false); // true when backend POST failed → "Saved locally · sync pending"
  let fileInput: HTMLInputElement | null = $state(null);

  let shades = $derived(deriveAccentShades(accentColor));

  function hydrate(b: Branding) {
    appName = b.appName;
    logoUrl = b.logoUrl;
    accentColor = b.accentColor;
    footerText = b.footerText;
  }

  onMount(async () => {
    hydrate(getBranding());
    const remote = await loadBrandingFromAPI();
    hydrate(remote);
    applyBranding(remote);
    // Probe backend so we know whether to show the "saved locally" banner on save.
    backendKnownGood = await brandingBackendReachable();
  });

  // Live-preview accent in nav while user picks a color (revert on reset/save).
  $effect(() => {
    applyBranding({ appName, logoUrl, accentColor, footerText });
  });

  async function onLogoFile(e: Event) {
    logoError = '';
    const target = e.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!file) return;
    if (!/^image\/(png|svg\+xml)$/.test(file.type)) {
      logoError = 'Please upload a PNG or SVG file.';
      target.value = '';
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      logoError = `Logo must be under ${Math.round(MAX_LOGO_BYTES / 1024)} KB (got ${Math.round(file.size / 1024)} KB).`;
      target.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      logoUrl = String(reader.result || '');
    };
    reader.onerror = () => {
      logoError = 'Could not read the file. Please try again.';
    };
    reader.readAsDataURL(file);
  }

  function clearLogo() {
    logoUrl = '';
    if (fileInput) fileInput.value = '';
  }

  async function save() {
    saving = true;
    const next: Branding = { appName: appName.trim() || DEFAULT_BRANDING.appName, logoUrl, accentColor, footerText: footerText.trim() || DEFAULT_BRANDING.footerText };
    const ok = await saveBrandingToAPI(next);
    localOnly = !ok;
    applyBranding(next);
    brandingStore.set(next);
    saving = false;
    addToast(ok ? 'success' : 'info', ok ? 'Branding saved.' : 'Saved locally · sync pending.');
  }

  function resetDefaults() {
    if (!confirm('Reset branding to default values?')) return;
    hydrate({ ...DEFAULT_BRANDING });
    saveBrandingLocal({ ...DEFAULT_BRANDING });
    brandingStore.set({ ...DEFAULT_BRANDING });
    applyBranding({ ...DEFAULT_BRANDING });
    if (fileInput) fileInput.value = '';
    addToast('info', 'Reverted to defaults. Click "Save changes" to persist.');
  }

  let logoPreviewLetter = $derived((appName.trim()[0] || 'P').toUpperCase());
</script>

<div class="page">
  <header class="page-head">
    <h1 class="page-title">Branding & white-label</h1>
    <p class="page-sub">Customize app name, logo, accent color, and footer for your organization.</p>
    {#if localOnly && !backendKnownGood}
      <div class="banner">Saved locally · sync pending. The backend endpoint is unavailable; changes will sync when it returns.</div>
    {/if}
  </header>

  <!-- App name -->
  <section class="card">
    <h2 class="card-title">App name</h2>
    <p class="card-sub">Shown in the top navigation, login screen, and browser tab.</p>
    <input
      type="text"
      class="text-input"
      bind:value={appName}
      placeholder="Your company name"
      maxlength="60"
    />
  </section>

  <!-- Logo -->
  <section class="card">
    <h2 class="card-title">Logo</h2>
    <p class="card-sub">Upload a PNG or SVG (max 256 KB). Replaces the coral letter tile in the nav and login.</p>
    <div class="logo-row">
      <div class="logo-preview" style="background: {logoUrl ? 'transparent' : accentColor};">
        {#if logoUrl}
          <img src={logoUrl} alt="Logo preview" />
        {:else}
          <span class="logo-letter">{logoPreviewLetter}</span>
        {/if}
      </div>
      <div class="logo-actions">
        <label class="btn-outline">
          <input
            bind:this={fileInput}
            type="file"
            accept="image/png,image/svg+xml"
            onchange={onLogoFile}
            hidden
          />
          {logoUrl ? 'Replace logo' : 'Upload logo'}
        </label>
        {#if logoUrl}
          <button type="button" class="btn-ghost" onclick={clearLogo}>Remove</button>
        {/if}
      </div>
    </div>
    {#if logoError}
      <div class="error-line">{logoError}</div>
    {/if}
  </section>

  <!-- Accent color -->
  <section class="card">
    <h2 class="card-title">Accent color</h2>
    <p class="card-sub">Used for primary buttons, active nav items, and accent details. Default coral <code>#c96342</code>.</p>
    <div class="color-row">
      <input type="color" class="color-input" bind:value={accentColor} />
      <input type="text" class="text-input mono" bind:value={accentColor} maxlength="7" />
    </div>
    <div class="preview-pill" aria-hidden="true">
      <span class="prev-btn" style="background: {shades.accent};">Primary button</span>
      <span class="prev-tag" style="background: {shades.accentSoft}; color: {shades.accentInk};">Active tag</span>
      <span class="prev-dot" style="background: {shades.accent}; box-shadow: 0 0 0 4px {shades.accentBg};"></span>
    </div>
    <p class="hint">Derived shades: <code>{shades.accentInk}</code> ink · <code>{shades.accentSoft}</code> soft · <code>{shades.accentBg}</code> bg</p>
  </section>

  <!-- Footer text -->
  <section class="card">
    <h2 class="card-title">Footer text</h2>
    <p class="card-sub">Tagline shown in the footer and login screen copyright line.</p>
    <input
      type="text"
      class="text-input"
      bind:value={footerText}
      placeholder="Your tagline"
      maxlength="80"
    />
  </section>

  <!-- Actions -->
  <div class="actions">
    <button type="button" class="btn-primary" onclick={save} disabled={saving}>
      {saving ? 'Saving…' : 'Save changes'}
    </button>
    <button type="button" class="btn-outline" onclick={resetDefaults} disabled={saving}>
      Reset to defaults
    </button>
  </div>
</div>

<style>
  .page {
    max-width: 760px;
    margin: 0 auto;
    padding: 32px 24px 80px;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    color: var(--color-ink, #2c2c2c);
  }
  .page-head { margin-bottom: 28px; }
  .page-title {
    font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
    font-size: 26px;
    font-weight: 500;
    letter-spacing: -0.015em;
    margin: 0 0 6px;
  }
  .page-sub {
    font-size: 14px;
    color: var(--color-muted, #6f6e69);
    margin: 0;
  }
  .banner {
    margin-top: 14px;
    padding: 10px 14px;
    border-radius: 10px;
    background: var(--color-accent-bg, #faf2ed);
    border: 1px solid var(--color-accent-soft, #fdebe1);
    color: var(--color-accent-ink, #b04f30);
    font-size: 13px;
  }

  .card {
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 16px;
  }
  .card-title {
    font-size: 15px;
    font-weight: 600;
    margin: 0 0 4px;
    color: var(--color-ink, #2c2c2c);
  }
  .card-sub {
    font-size: 13px;
    color: var(--color-muted, #6f6e69);
    margin: 0 0 14px;
  }

  .text-input {
    width: 100%;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border-strong, #d8d5cb);
    border-radius: 10px;
    padding: 10px 12px;
    font-family: inherit;
    font-size: 14px;
    color: var(--color-ink, #2c2c2c);
    outline: none;
    transition: border-color .15s, box-shadow .15s;
  }
  .text-input:focus {
    border-color: var(--color-accent, #c96342);
    box-shadow: 0 0 0 3px var(--color-accent-bg, #faf2ed);
  }
  .text-input.mono { font-family: ui-monospace, SFMono-Regular, monospace; max-width: 140px; text-transform: lowercase; }

  .logo-row { display: flex; align-items: center; gap: 18px; }
  .logo-preview {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    overflow: hidden;
    border: 1px solid var(--color-border, #e8e6dd);
    flex-shrink: 0;
  }
  .logo-preview img { width: 100%; height: 100%; object-fit: cover; }
  .logo-letter {
    color: #fff;
    font-weight: 700;
    font-size: 26px;
    font-family: 'Tiempos Headline', 'Charter', Georgia, serif;
  }
  .logo-actions { display: flex; gap: 10px; align-items: center; }

  .color-row { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
  .color-input {
    width: 56px;
    height: 40px;
    border: 1px solid var(--color-border-strong, #d8d5cb);
    border-radius: 10px;
    padding: 4px;
    background: var(--color-surface, #ffffff);
    cursor: pointer;
  }

  .preview-pill {
    display: inline-flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--color-bg-alt, #f4f3ee);
    border-radius: 999px;
    font-size: 13px;
  }
  .prev-btn {
    color: #fff;
    padding: 7px 14px;
    border-radius: 999px;
    font-weight: 500;
  }
  .prev-tag {
    padding: 5px 12px;
    border-radius: 999px;
    font-weight: 600;
    font-size: 12px;
  }
  .prev-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }

  .hint {
    margin: 10px 0 0;
    font-size: 12px;
    color: var(--color-muted, #6f6e69);
  }
  .hint code, .card-sub code { font-family: ui-monospace, monospace; font-size: 11.5px; padding: 1px 5px; background: var(--color-bg-alt, #f4f3ee); border-radius: 4px; }

  .error-line { margin-top: 10px; font-size: 13px; color: var(--color-red, #a83232); }

  .actions { display: flex; gap: 10px; margin-top: 24px; }

  .btn-primary {
    background: var(--color-accent, #c96342);
    color: #fff;
    border: 1px solid var(--color-accent, #c96342);
    padding: 10px 20px;
    border-radius: 999px;
    font-family: inherit;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: filter .15s;
  }
  .btn-primary:hover:not(:disabled) { filter: brightness(0.95); }
  .btn-primary:disabled { opacity: 0.55; cursor: not-allowed; }

  .btn-outline {
    background: var(--color-surface, #ffffff);
    color: var(--color-ink, #2c2c2c);
    border: 1px solid var(--color-border-strong, #d8d5cb);
    padding: 10px 20px;
    border-radius: 999px;
    font-family: inherit;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    transition: background .15s;
  }
  .btn-outline:hover:not(:disabled) { background: var(--color-bg-alt, #f4f3ee); }
  .btn-outline:disabled { opacity: 0.55; cursor: not-allowed; }

  .btn-ghost {
    background: transparent;
    color: var(--color-muted, #6f6e69);
    border: none;
    padding: 6px 10px;
    font-family: inherit;
    font-size: 13px;
    cursor: pointer;
    border-radius: 6px;
  }
  .btn-ghost:hover { background: var(--color-bg-alt, #f4f3ee); color: var(--color-ink, #2c2c2c); }
</style>
