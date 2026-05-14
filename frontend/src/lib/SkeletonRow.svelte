<!--
  SkeletonRow — table-row skeleton (5 cells of 12px height).
  Renders <tr><td>×5 with shimmer blocks. Must be used inside <tbody>.
  Props:
    count  number  repeat N rows (default 1)
-->
<script>
  let { count = 1 } = $props();
  let n = $derived(Math.max(1, Number(count) || 1));
  const widths = ['28%', '18%', '22%', '16%', '12%'];
</script>

{#each Array(n) as _, i (i)}
  <tr class="sk-row">
    {#each widths as w}
      <td>
        <span class="sk-cell" style="width:{w};" aria-hidden="true"></span>
      </td>
    {/each}
  </tr>
{/each}

<style>
  .sk-row td {
    padding: 10px 12px;
    border-bottom: 1px solid #efeee6;
  }
  .sk-cell {
    display: block;
    height: 12px;
    border-radius: 6px;
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
    .sk-cell { animation: none; }
  }
</style>
