<script>
  import { onMount, onDestroy } from 'svelte';
  import { apiJson } from '$lib/api';

  let agents = $state([]);
  let timer = null;
  let openTip = $state(false);

  async function load() {
    try {
      const d = await apiJson('/agents/');
      agents = d.agents || [];
    } catch {}
  }

  // tick state for re-evaluating "recently active" window every 1s
  let nowTs = $state(Date.now());
  let tickHandle = null;

  onMount(() => {
    load();
    timer = setInterval(load, 1500);
    tickHandle = setInterval(() => { nowTs = Date.now(); }, 1000);
  });
  onDestroy(() => {
    if (timer) clearInterval(timer);
    if (tickHandle) clearInterval(tickHandle);
  });

  // "Recently active" if last_activity_at within last 8s — keeps dot pulsing for fast bursts
  function recentlyActive(a) {
    if (!a.last_activity_at) return false;
    try {
      const t = new Date(a.last_activity_at).getTime();
      return (nowTs - t) < 8000;
    } catch { return false; }
  }

  function effectiveStatus(a) {
    if (a.status === 'error') return 'error';
    if (a.status === 'running') return 'running';
    if (recentlyActive(a)) return 'running';
    return 'idle';
  }

  let runningAgents = $derived(agents.filter(a => effectiveStatus(a) === 'running'));
  let errorAgents = $derived(agents.filter(a => a.status === 'error'));
  let nRunning = $derived(runningAgents.length);
  let nErrors = $derived(errorAgents.length);
  let nTotal = $derived(agents.length);

  let label = $derived.by(() => {
    if (nErrors > 0) return `${nErrors} agent${nErrors !== 1 ? 's' : ''} error`;
    if (nRunning > 0) return `${nRunning} agent${nRunning !== 1 ? 's' : ''} running`;
    if (nTotal > 0) return `${nTotal} agents idle`;
    return 'agents';
  });

  function dotColor(status) {
    if (status === 'running') return 'var(--color-accent, #c96342)';
    if (status === 'error') return 'var(--color-error, #c4571a)';
    return 'var(--color-border, #d8d5cc)';
  }
</script>

<a href="/agents"
  class="ali-wrap"
  class:ali-active={nRunning > 0}
  class:ali-err={nErrors > 0}
  onmouseenter={() => openTip = true}
  onmouseleave={() => openTip = false}
  title="Agent live indicator — click to open Agents dashboard">
  <div class="ali-dots">
    {#each agents as a (a.id)}
      {@const eff = effectiveStatus(a)}
      <span class="ali-dot"
        class:ali-dot-running={eff === 'running'}
        class:ali-dot-error={eff === 'error'}
        style="background: {dotColor(eff)};"></span>
    {/each}
  </div>
  <span class="ali-label">{label}</span>

  {#if openTip && agents.length > 0}
    <div class="ali-tip">
      <div class="ali-tip-head">Agents · {nRunning}/{nTotal} running</div>
      {#each agents as a (a.id)}
        {@const eff = effectiveStatus(a)}
        <div class="ali-tip-row">
          <span class="ali-tip-dot" style="background: {dotColor(eff)};"
            class:ali-dot-running={eff === 'running'}></span>
          <span class="ali-tip-name">{a.name}</span>
          <span class="ali-tip-status">{eff}</span>
        </div>
      {/each}
      <div class="ali-tip-foot">Click → open Agents page</div>
    </div>
  {/if}
</a>

<style>
  .ali-wrap {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 5px 10px;
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 999px;
    text-decoration: none;
    color: var(--color-on-surface, #2c2c2c);
    font-size: 11.5px;
    cursor: pointer;
    transition: border-color 120ms, background 120ms;
    position: relative;
  }
  .ali-wrap:hover {
    background: var(--color-bg, #faf9f5);
    border-color: var(--color-accent, #c96342);
  }
  .ali-wrap.ali-active {
    border-color: rgba(201, 99, 66, 0.4);
    background: rgba(201, 99, 66, 0.05);
  }
  .ali-wrap.ali-err {
    border-color: rgba(196, 87, 26, 0.5);
    background: rgba(196, 87, 26, 0.06);
  }
  .ali-dots { display: inline-flex; gap: 3px; }
  .ali-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--color-border, #d8d5cc);
    transition: transform 120ms;
  }
  .ali-dot-running {
    animation: aliPulse 1.2s ease-in-out infinite;
  }
  .ali-dot-error {
    animation: aliBlink 0.8s ease-in-out infinite;
  }
  @keyframes aliPulse {
    0%, 100% { opacity: 0.45; transform: scale(1); }
    50%      { opacity: 1; transform: scale(1.35); }
  }
  @keyframes aliBlink {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.35; }
  }
  .ali-label {
    font-weight: 500;
    color: var(--color-on-surface-dim, #6f6e69);
    white-space: nowrap;
  }
  .ali-active .ali-label { color: var(--color-accent, #c96342); font-weight: 600; }
  .ali-err .ali-label { color: var(--color-error, #c4571a); font-weight: 600; }

  /* Tooltip popover */
  .ali-tip {
    position: absolute; top: calc(100% + 8px); right: 0;
    min-width: 280px; max-width: 360px;
    padding: 10px 12px;
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.10), 0 2px 6px rgba(0,0,0,0.04);
    z-index: 200;
    font-size: 12px;
  }
  .ali-tip-head {
    font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--color-on-surface-dim, #6f6e69);
    padding-bottom: 6px;
    border-bottom: 1px solid var(--color-border, #f0eee6);
    margin-bottom: 6px;
  }
  .ali-tip-row {
    display: grid;
    grid-template-columns: 12px 1fr auto;
    gap: 8px; align-items: center;
    padding: 4px 0;
    font-size: 11.5px;
  }
  .ali-tip-dot { width: 7px; height: 7px; border-radius: 50%; }
  .ali-tip-name { color: var(--color-on-surface, #2c2c2c); font-weight: 500; }
  .ali-tip-status {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--color-on-surface-dim, #6f6e69);
  }
  .ali-tip-foot {
    margin-top: 8px; padding-top: 6px;
    border-top: 1px solid var(--color-border, #f0eee6);
    font-size: 10.5px; color: var(--color-on-surface-dim, #6f6e69);
    text-align: center;
  }

  @media (max-width: 900px) {
    .ali-label { display: none; }
  }
</style>
