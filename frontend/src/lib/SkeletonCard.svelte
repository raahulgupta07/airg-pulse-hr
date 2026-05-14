<!--
  SkeletonCard — card-grid placeholder.
  Layout: title bar + 3 text lines + 2 button stubs at bottom.
  Props:
    count  number  repeat N cards in a CSS grid (default 1)
-->
<script>
  let { count = 1 } = $props();
  let n = $derived(Math.max(1, Number(count) || 1));
</script>

<div class="sk-card-grid">
  {#each Array(n) as _, i (i)}
    <div class="sk-card" aria-hidden="true">
      <span class="sk-block" style="width:62%; height:18px; border-radius:6px;"></span>
      <span class="sk-block" style="width:100%; height:12px; border-radius:6px; margin-top:14px;"></span>
      <span class="sk-block" style="width:88%; height:12px; border-radius:6px; margin-top:8px;"></span>
      <span class="sk-block" style="width:72%; height:12px; border-radius:6px; margin-top:8px;"></span>
      <div class="sk-btn-row">
        <span class="sk-block" style="width:84px; height:28px; border-radius:999px;"></span>
        <span class="sk-block" style="width:84px; height:28px; border-radius:999px;"></span>
      </div>
    </div>
  {/each}
</div>

<style>
  .sk-card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    width: 100%;
  }
  .sk-card {
    background: #ffffff;
    border: 1px solid #e8e6dd;
    border-radius: 12px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    min-height: 200px;
  }
  .sk-btn-row {
    margin-top: auto;
    padding-top: 18px;
    display: flex;
    gap: 8px;
  }
  .sk-block {
    display: block;
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
  }
  @keyframes sk-shimmer {
    0%   { background-position: 100% 0; }
    100% { background-position: -100% 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    .sk-block { animation: none; }
  }
</style>
