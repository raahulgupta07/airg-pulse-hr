<!--
  Skeleton.svelte — warm-tone shimmer placeholder
  Props:
    width   string | number   width (CSS) — default '100%'
    height  string | number   height (CSS) — default '14px'
    radius  string | number   border-radius — default 6px
    count   number            repeats stacked w/ 8px gap — default 1

  Sub-components exposed via context-module exports:
    <SkeletonRow />   — 5 cells of 12px height for table rows
    <SkeletonCard />  — card placeholder: title + 3 lines + 2 buttons
-->
<script module>
  // Re-export sub-components from a sibling helper so consumers can
  // `import Skeleton, { SkeletonRow, SkeletonCard } from '$lib/Skeleton.svelte'`.
  export { default as SkeletonRow } from './SkeletonRow.svelte';
  export { default as SkeletonCard } from './SkeletonCard.svelte';
</script>

<script>
  let {
    width = '100%',
    height = '14px',
    radius = '6px',
    count = 1
  } = $props();

  const cssLen = (v) => (typeof v === 'number' ? `${v}px` : v);

  let w = $derived(cssLen(width));
  let h = $derived(cssLen(height));
  let r = $derived(cssLen(radius));
  let n = $derived(Math.max(1, Number(count) || 1));
</script>

{#if n === 1}
  <span class="sk" style="width:{w}; height:{h}; border-radius:{r};" aria-hidden="true"></span>
{:else}
  <span class="sk-stack" aria-hidden="true">
    {#each Array(n) as _, i (i)}
      <span class="sk" style="width:{w}; height:{h}; border-radius:{r};"></span>
    {/each}
  </span>
{/if}

<style>
  .sk {
    display: inline-block;
    background: linear-gradient(
      90deg,
      #e8e6dd 0%,
      #e8e6dd 35%,
      #f4f3ee 50%,
      #e8e6dd 65%,
      #e8e6dd 100%
    );
    background-size: 200% 100%;
    animation: sk-shimmer 1.4s ease-in-out infinite;
    vertical-align: middle;
  }

  .sk-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }

  @keyframes sk-shimmer {
    0%   { background-position: 100% 0; }
    100% { background-position: -100% 0; }
  }

  @media (prefers-reduced-motion: reduce) {
    .sk { animation: none; }
  }
</style>
