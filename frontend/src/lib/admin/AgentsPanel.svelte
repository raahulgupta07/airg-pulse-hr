<script>
  import { onMount, onDestroy } from 'svelte';
  import { apiJson } from '$lib/api';

  let agents = $state([]);
  let loading = $state(true);
  let error = $state('');
  let timer = null;

  async function load() {
    try {
      const d = await apiJson('/agents/');
      agents = d.agents || [];
      error = '';
    } catch (e) { error = e.message || 'Failed to load agents'; }
    finally { loading = false; }
  }

  onMount(() => {
    load();
    timer = setInterval(load, 5000);
  });
  onDestroy(() => { if (timer) clearInterval(timer); });

  function fmt(ts) {
    if (!ts) return '—';
    try {
      const d = new Date(ts);
      const diff = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diff < 0) {
        const ahead = Math.abs(diff);
        if (ahead < 60) return `in ${ahead}s`;
        return `in ${Math.floor(ahead / 60)}m`;
      }
      if (diff < 60) return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    } catch { return ts; }
  }

  function statusColor(s) {
    return {
      idle: '#9c9c8f',
      running: '#3a8a4f',
      error: '#c4571a',
      disabled: '#7d7c75',
    }[s] || '#9c9c8f';
  }

  function statusDot(s) {
    return s === 'running' ? '●' : '○';
  }

  function typeBadge(t) {
    return {
      'continuous': { label: '∞ continuous', color: '#3a7bbf' },
      'event-driven': { label: '⚡ event', color: '#6f57bd' },
      'event+poll': { label: '⚡ event + poll', color: '#6f57bd' },
      'scheduled': { label: '⏱ scheduled', color: '#c98c2a' },
      'triggered': { label: '↻ triggered', color: '#c96342' },
    }[t] || { label: t, color: '#9c9c8f' };
  }
</script>

<div class="ap-wrap">
  <div class="ap-head">
    <div>
      <h2 class="ap-title">Agents</h2>
      <p class="ap-sub">All background workers + on-demand agents. Auto-refreshes every 5s.</p>
    </div>
    <button class="btn-ghost" onclick={load} disabled={loading}>{loading ? '…' : '⟳ Refresh'}</button>
  </div>

  {#if error}<div class="ap-error">{error}</div>{/if}

  <div class="ap-table">
    <div class="ap-row ap-row-head">
      <div>Status</div>
      <div>Agent</div>
      <div>Type</div>
      <div>Last run</div>
      <div>Next run</div>
      <div>Events</div>
      <div>Errors</div>
    </div>
    {#each agents as a}
      {@const tb = typeBadge(a.type)}
      <div class="ap-row">
        <div>
          <span class="ap-dot" style="color: {statusColor(a.status)}; font-size: 14px;">{statusDot(a.status)}</span>
          <span class="ap-status" style="color: {statusColor(a.status)};">{a.status}</span>
        </div>
        <div>
          <div class="ap-name">{a.name}</div>
          <div class="ap-purpose">{a.purpose}</div>
          {#if a.current_action}
            <div class="ap-action">→ {a.current_action}</div>
          {/if}
        </div>
        <div><span class="ap-type-badge" style="color: {tb.color}; border-color: {tb.color};">{tb.label}</span></div>
        <div>{fmt(a.last_run_at)}</div>
        <div>{fmt(a.next_run_at)}</div>
        <div class="ap-num">{a.events_total ?? 0}</div>
        <div class="ap-num" style="color: {a.errors_total > 0 ? '#c4571a' : 'inherit'};">{a.errors_total ?? 0}</div>
      </div>
      {#if a.last_error}
        <div class="ap-error-row">⚠ {a.last_error}</div>
      {/if}
    {/each}
    {#if agents.length === 0 && !loading}
      <div class="ap-empty">No agents registered.</div>
    {/if}
  </div>
</div>

<style>
  .ap-wrap { padding: 8px 4px 24px; }
  .ap-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
  .ap-title { font-family: 'Tiempos Headline', Georgia, serif; font-size: 22px; font-weight: 500; margin: 0 0 4px; color: var(--color-on-surface, #2c2c2c); }
  .ap-sub { font-size: 12.5px; color: var(--color-on-surface-dim, #6f6e69); margin: 0; }
  .btn-ghost { padding: 7px 14px; font-size: 12px; background: transparent; border: 1px solid var(--color-border, #d8d5cc); border-radius: 7px; cursor: pointer; }
  .btn-ghost:hover:not(:disabled) { background: var(--color-bg, #faf9f5); }

  .ap-table { background: var(--color-surface-bright, #fff); border: 1px solid var(--color-border, #e8e6dd); border-radius: 10px; overflow: hidden; }
  .ap-row {
    display: grid;
    grid-template-columns: 100px 2.4fr 1.4fr 1fr 1fr 0.7fr 0.7fr;
    gap: 14px; padding: 12px 16px; align-items: start;
    border-bottom: 1px solid var(--color-border, #f0eee6); font-size: 12.5px;
  }
  .ap-row:last-child { border-bottom: none; }
  .ap-row-head {
    background: var(--color-bg, #faf9f5);
    font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--color-on-surface-dim, #6f6e69);
  }
  .ap-status { font-weight: 600; text-transform: capitalize; }
  .ap-name { font-weight: 600; color: var(--color-on-surface, #2c2c2c); margin-bottom: 2px; }
  .ap-purpose { font-size: 11px; color: var(--color-on-surface-dim, #6f6e69); line-height: 1.4; }
  .ap-action { font-size: 11px; font-style: italic; color: var(--color-accent, #c96342); margin-top: 4px; }
  .ap-type-badge {
    display: inline-block; padding: 2px 8px; font-size: 10px; font-weight: 600;
    border: 1px solid; border-radius: 4px; white-space: nowrap;
  }
  .ap-num { font-variant-numeric: tabular-nums; font-weight: 600; }
  .ap-error { background: rgba(196, 87, 26, 0.08); color: #c4571a; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; font-size: 12.5px; }
  .ap-error-row { padding: 6px 16px; font-size: 11px; color: #c4571a; background: rgba(196, 87, 26, 0.04); border-bottom: 1px solid var(--color-border, #f0eee6); }
  .ap-empty { padding: 24px; text-align: center; color: var(--color-on-surface-dim, #6f6e69); font-size: 13px; }
</style>
