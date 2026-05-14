<script>
  import { onMount } from 'svelte';
  import { apiJson } from '$lib/api';

  let {
    feature,
    title,
    tagline,
    steps = [],
    samplePreview = ''
  } = $props();

  let joined = $state(false);
  let loading = $state(false);
  let count = $state(null);

  onMount(async () => {
    try {
      const me = await apiJson('/communicate/me/waitlist');
      joined = (me?.joined || []).includes(feature);
    } catch {}
    try {
      const c = await apiJson('/communicate/waitlist/counts');
      count = c?.counts?.[feature] ?? null;
    } catch {}
  });

  async function notifyMe() {
    loading = true;
    try {
      await apiJson('/communicate/waitlist', {
        method: 'POST',
        body: JSON.stringify({ feature })
      });
      joined = true;
      if (typeof count === 'number') count += 1;
    } catch (e) { alert('Failed: ' + e.message); }
    finally { loading = false; }
  }
</script>

<div class="cs-scroll">
<div class="cs-wrap">
  <div class="cs-hero">
    <div class="cs-eta">✦ Coming soon</div>
    <h1 class="cs-title">{title}</h1>
    <p class="cs-tag">{tagline}</p>

    {#if joined}
      <div class="cs-joined">✓ You're on the waitlist. We'll notify you when it launches.</div>
    {:else}
      <button class="cs-cta" onclick={notifyMe} disabled={loading}>
        {loading ? 'Adding…' : 'Notify me when ready'}
      </button>
    {/if}

    {#if count !== null}
      <div class="cs-count">{count} {count === 1 ? 'person is' : 'people are'} waiting for this</div>
    {/if}
  </div>

  {#if steps.length}
    <div class="cs-section">
      <div class="cs-section-title">How it will work</div>
      <div class="cs-step-row">
        {#each steps as s, i}
          <div class="cs-step">
            <div class="cs-step-num">{i + 1}</div>
            <div class="cs-step-text">{s}</div>
          </div>
          {#if i < steps.length - 1}<div class="cs-step-arrow">→</div>{/if}
        {/each}
      </div>
    </div>
  {/if}

  {#if samplePreview}
    <div class="cs-section">
      <div class="cs-section-title">Sample output</div>
      <div class="cs-sample">{@html samplePreview}</div>
    </div>
  {/if}
</div>
</div>

<style>
  .cs-scroll {
    height: 100%; overflow-y: auto;
  }
  .cs-wrap {
    max-width: 920px; margin: 0 auto; padding: 32px 24px 64px;
    box-sizing: border-box;
  }
  .cs-hero {
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 14px; padding: 56px 40px; text-align: center;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  }
  .cs-eta {
    display: inline-block; padding: 5px 14px; border-radius: 999px;
    background: rgba(201, 99, 66, 0.10); color: var(--color-accent, #c96342);
    font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    margin-bottom: 18px;
  }
  .cs-title {
    font-family: 'Tiempos Headline', Georgia, serif;
    font-size: 38px; font-weight: 500; margin: 0 0 12px;
    letter-spacing: -0.02em; color: var(--color-on-surface, #2c2c2c);
  }
  .cs-tag {
    font-size: 15px; line-height: 1.55; color: var(--color-on-surface-dim, #6f6e69);
    max-width: 580px; margin: 0 auto 28px;
  }
  .cs-cta {
    padding: 11px 26px; font-size: 14px; font-weight: 600;
    background: var(--color-accent, #c96342); color: #fff;
    border: 1px solid var(--color-accent, #c96342); border-radius: 8px;
    cursor: pointer; transition: filter 120ms;
  }
  .cs-cta:hover:not(:disabled) { filter: brightness(0.94); }
  .cs-cta:disabled { opacity: 0.6; cursor: not-allowed; }
  .cs-joined {
    display: inline-block; padding: 10px 20px;
    background: rgba(46, 125, 50, 0.10); color: #2e7d32;
    border-radius: 8px; font-size: 13px; font-weight: 500;
  }
  .cs-count {
    margin-top: 14px; font-size: 11.5px; color: var(--color-on-surface-dim, #6f6e69);
  }

  .cs-section { margin-top: 40px; }
  .cs-section-title {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--color-on-surface-dim, #6f6e69); margin-bottom: 18px;
    text-align: center;
  }
  .cs-step-row {
    display: flex; align-items: stretch; gap: 6px; flex-wrap: wrap;
    justify-content: center;
  }
  .cs-step {
    flex: 1 1 140px; max-width: 170px; min-width: 130px;
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 10px;
    padding: 16px 14px; text-align: center;
  }
  .cs-step-num {
    width: 26px; height: 26px; border-radius: 50%;
    background: var(--color-accent, #c96342); color: #fff;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; margin-bottom: 10px;
  }
  .cs-step-text { font-size: 12.5px; line-height: 1.4; color: var(--color-on-surface, #2c2c2c); }
  .cs-step-arrow {
    display: flex; align-items: center; color: var(--color-on-surface-dim, #6f6e69);
    font-size: 18px;
  }

  .cs-sample {
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 10px;
    padding: 28px 32px; font-size: 13.5px; line-height: 1.7;
    color: var(--color-on-surface, #2c2c2c);
    max-width: 760px; margin: 0 auto;
  }

  @media (max-width: 700px) {
    .cs-step-row { flex-direction: column; align-items: stretch; }
    .cs-step { max-width: none; }
    .cs-step-arrow { transform: rotate(90deg); justify-content: center; }
    .cs-title { font-size: 28px; }
    .cs-hero { padding: 36px 24px; }
  }
</style>
