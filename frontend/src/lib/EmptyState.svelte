<!--
  EmptyState.svelte — friendly zero-data placeholder.
  Props:
    icon          import('svelte').Component | null   Lucide icon component (48-64px)
    title         string                Tiempos serif headline (18px)
    description   string                muted body copy
    actionLabel   string?               CTA pill label
    actionHref    string?               link target (renders <a>)
    onAction      () => void?           callback (renders <button>)

  Layout: centered white card, 12px radius, soft border, 48px padding,
  max-width 480px, margin auto. Coral pill CTA.
-->
<script>
  // TODO: update call-sites to pass Lucide icon components instead of emoji strings:
  //   src/routes/+page.svelte
  //   src/routes/candidates/+page.svelte
  //   src/routes/jds/+page.svelte
  // The template already falls back to rendering string icons for compatibility.
  /** @type {import('svelte').Component | null} */
  let {
    icon = null,
    title = '',
    description = '',
    actionLabel = '',
    actionHref = '',
    onAction = null
  } = $props();

  let hasAction = $derived(!!actionLabel && (!!actionHref || typeof onAction === 'function'));
</script>

<div class="empty-card">
  {#if icon}
    <div class="empty-icon" aria-hidden="true">
      {#if typeof icon === 'string'}
        {icon}
      {:else}
        <svelte:component this={icon} size={64} stroke-width={1.5} />
      {/if}
    </div>
  {/if}
  {#if title}
    <h3 class="empty-title">{title}</h3>
  {/if}
  {#if description}
    <p class="empty-desc">{description}</p>
  {/if}
  {#if hasAction}
    {#if actionHref}
      <a class="empty-cta" href={actionHref}>{actionLabel}</a>
    {:else}
      <button type="button" class="empty-cta" onclick={onAction}>{actionLabel}</button>
    {/if}
  {/if}
</div>

<style>
  .empty-card {
    max-width: 480px;
    margin: 32px auto;
    padding: 48px;
    background: #ffffff;
    border: 1px solid #e8e6dd;
    border-radius: 12px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .empty-icon {
    line-height: 1;
    margin-bottom: 20px;
  }
  .empty-title {
    font-family: 'Tiempos Headline', 'Charter', 'Source Serif Pro', Georgia, serif;
    font-size: 18px;
    font-weight: 500;
    color: #2c2c2c;
    margin: 0 0 8px;
    letter-spacing: -0.01em;
  }
  .empty-desc {
    font-size: 13.5px;
    color: #6f6e69;
    line-height: 1.5;
    margin: 0 0 20px;
    max-width: 380px;
  }
  .empty-cta {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 9px 18px;
    background: #c96342;
    color: #ffffff;
    border: 1px solid #c96342;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 500;
    text-decoration: none;
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease;
    font-family: inherit;
  }
  .empty-cta:hover {
    background: #b04f30;
    border-color: #b04f30;
  }
  .empty-cta:focus-visible {
    outline: 2px solid #fdebe1;
    outline-offset: 2px;
  }
</style>
