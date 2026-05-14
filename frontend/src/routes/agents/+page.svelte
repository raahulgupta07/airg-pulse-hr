<script>
  import AgentsPanel from '$lib/admin/AgentsPanel.svelte';
</script>

<svelte:head><title>Agents · City Agent Pulse</title></svelte:head>

<div class="agents-wrap">
  <header class="agents-head">
    <h1 class="page-title">Agents</h1>
    <p class="page-sub">Live status of every background + on-demand agent. Auto-refreshes every 5s.</p>
  </header>
  <AgentsPanel />
</div>

<style>
  .agents-wrap {
    padding: 24px 28px 64px; max-width: 1400px; margin: 0 auto;
    height: 100%; overflow-y: auto; box-sizing: border-box;
  }
  .agents-head { margin-bottom: 18px; }
  .page-title {
    font-family: 'Tiempos Headline', Georgia, serif;
    font-size: 28px; font-weight: 500; margin: 0 0 4px;
    letter-spacing: -0.02em; color: var(--color-on-surface, #2c2c2c);
  }
  .page-sub { font-size: 13px; color: var(--color-on-surface-dim, #6f6e69); margin: 0; }
</style>
