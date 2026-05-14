<script>
  import { onMount, onDestroy } from 'svelte';
  import { apiJson } from '$lib/api';
  import { addToast } from '$lib/Toast.svelte';
  import Settings from '@lucide/svelte/icons/settings';
  import Play from '@lucide/svelte/icons/play';
  import Save from '@lucide/svelte/icons/save';
  import Power from '@lucide/svelte/icons/power';

  let agents = $state([]);          // server-side config + runtime
  let loading = $state(true);
  let error = $state('');
  let timer = null;

  // local edit buffers keyed by agent_id
  let edit = $state({});            // { [id]: { enabled, interval_seconds, thresholds_json } }
  let saving = $state({});          // { [id]: bool }
  let testing = $state({});         // { [id]: bool }

  async function load() {
    try {
      const d = await apiJson('/agents/config');
      const list = d.agents || [];
      agents = list;
      // Initialise edit buffers but don't clobber unsaved edits
      const next = { ...edit };
      for (const a of list) {
        if (!next[a.id]) {
          next[a.id] = {
            enabled: a.config?.enabled ?? true,
            interval_seconds: a.config?.interval_seconds ?? a.default_interval_s ?? 300,
            thresholds_json: JSON.stringify(a.config?.thresholds ?? {}, null, 2),
            dirty: false,
          };
        }
      }
      edit = next;
      error = '';
    } catch (e) { error = e?.message || 'Failed to load agent configs'; }
    finally { loading = false; }
  }

  onMount(() => {
    load();
    timer = setInterval(load, 8000);
  });
  onDestroy(() => { if (timer) clearInterval(timer); });

  function markDirty(id) {
    if (edit[id]) { edit[id].dirty = true; edit = { ...edit }; }
  }

  function statusColor(s) {
    return ({
      idle: '#9c9c8f', running: '#3a8a4f', error: '#c4571a',
      disabled: '#7d7c75', sleeping: '#9c9c8f', scanning: '#3a7bbf', starting: '#c98c2a',
    })[s] || '#9c9c8f';
  }

  function fmtAgo(ts) {
    if (!ts) return '—';
    try {
      const d = new Date(ts);
      const diff = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diff < 0) {
        const a = Math.abs(diff);
        if (a < 60) return `in ${a}s`;
        if (a < 3600) return `in ${Math.floor(a/60)}m`;
        return `in ${Math.floor(a/3600)}h`;
      }
      if (diff < 60) return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
      return `${Math.floor(diff/86400)}d ago`;
    } catch { return ts; }
  }

  async function toggleEnabled(a) {
    const id = a.id;
    const next = !(edit[id]?.enabled);
    edit[id].enabled = next;
    edit = { ...edit };
    saving[id] = true; saving = { ...saving };
    try {
      await apiJson(`/agents/config/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: next }),
      });
      addToast('success', `${a.name}: ${next ? 'enabled' : 'disabled'}`);
      edit[id].dirty = false; edit = { ...edit };
    } catch (e) {
      // revert on failure
      edit[id].enabled = !next; edit = { ...edit };
      addToast('error', e?.message || 'Toggle failed');
    } finally { saving[id] = false; saving = { ...saving }; }
  }

  async function saveCard(a) {
    const id = a.id;
    let thresholds;
    try { thresholds = JSON.parse(edit[id].thresholds_json || '{}'); }
    catch (e) { addToast('error', 'Thresholds must be valid JSON'); return; }
    const interval = Number(edit[id].interval_seconds);
    if (!Number.isFinite(interval) || interval < 60 || interval > 86400) {
      addToast('error', 'Interval must be 60-86400s'); return;
    }
    saving[id] = true; saving = { ...saving };
    try {
      await apiJson(`/agents/config/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          enabled: !!edit[id].enabled,
          interval_seconds: interval,
          thresholds,
        }),
      });
      addToast('success', `${a.name}: saved`);
      edit[id].dirty = false; edit = { ...edit };
      await load();
    } catch (e) { addToast('error', e?.message || 'Save failed'); }
    finally { saving[id] = false; saving = { ...saving }; }
  }

  async function testRun(a) {
    if (!a.supports_test_run) {
      addToast('info', 'Test-run not implemented for this agent yet');
      return;
    }
    const id = a.id;
    testing[id] = true; testing = { ...testing };
    try {
      const r = await apiJson(`/agents/${encodeURIComponent(id)}/test-run`, { method: 'POST' });
      addToast('success', `${a.name}: cycle done ${r?.result ? '· ' + JSON.stringify(r.result) : ''}`);
      await load();
    } catch (e) { addToast('error', e?.message || 'Test-run failed'); }
    finally { testing[id] = false; testing = { ...testing }; }
  }
</script>

<div class="acp-wrap">
  <div class="acp-head">
    <div>
      <h2 class="acp-title">Agent config</h2>
      <p class="acp-sub">Per-agent enable, interval, thresholds. Auto-refreshes every 8s.</p>
    </div>
    <button class="acp-btn-ghost" onclick={load} disabled={loading}>{loading ? '…' : '⟳ Refresh'}</button>
  </div>

  {#if error}<div class="acp-error">{error}</div>{/if}

  <div class="acp-grid">
    {#each agents as a (a.id)}
      {@const e = edit[a.id] || {}}
      {@const rt = a.runtime || {}}
      <div class="acp-card" class:disabled={!e.enabled}>
        <div class="acp-card-head">
          <div class="acp-icon"><Settings size={18} /></div>
          <div class="acp-titles">
            <div class="acp-name">{a.name}</div>
            <div class="acp-id">{a.id} <span class="acp-type">· {a.type}</span></div>
          </div>
          <span class="acp-dot" style="background: {statusColor(rt.status)};" title={rt.status || 'idle'}></span>
        </div>

        {#if a.purpose}
          <p class="acp-purpose">{a.purpose}</p>
        {/if}

        <div class="acp-runtime">
          <div><span>Last run:</span> {fmtAgo(rt.last_run_at)}</div>
          <div><span>Next:</span> {fmtAgo(rt.next_run_at)}</div>
          <div><span>Errors:</span> <strong style="color: {(rt.errors_total || 0) > 0 ? '#c4571a' : 'inherit'};">{rt.errors_total || 0}</strong></div>
        </div>

        <!-- Enable toggle -->
        <div class="acp-row acp-row-toggle">
          <label class="acp-toggle">
            <Power size={14} />
            <span>Enabled</span>
            <button
              type="button"
              class="acp-switch"
              class:on={e.enabled}
              onclick={() => toggleEnabled(a)}
              disabled={saving[a.id]}
              aria-pressed={e.enabled}
            >
              <span class="acp-knob"></span>
            </button>
          </label>
        </div>

        <!-- Interval slider + numeric -->
        <div class="acp-row">
          <label class="acp-lbl">Interval (sec)</label>
          <div class="acp-interval">
            <input
              type="range" min="60" max="86400" step="60"
              bind:value={e.interval_seconds}
              oninput={() => markDirty(a.id)}
              disabled={!e.enabled}
            />
            <input
              type="number" min="60" max="86400"
              bind:value={e.interval_seconds}
              oninput={() => markDirty(a.id)}
              disabled={!e.enabled}
              class="acp-num-input"
            />
          </div>
        </div>

        <!-- Thresholds -->
        <div class="acp-row">
          <label class="acp-lbl">Thresholds (JSON)</label>
          <textarea
            class="acp-textarea"
            rows="3"
            bind:value={e.thresholds_json}
            oninput={() => markDirty(a.id)}
            placeholder={'{}'}
          ></textarea>
        </div>

        <div class="acp-actions">
          <button
            type="button"
            class="acp-btn-test"
            onclick={() => testRun(a)}
            disabled={testing[a.id] || !a.supports_test_run}
            title={a.supports_test_run ? 'Trigger one cycle now' : 'Test-run not implemented'}
          >
            {#if testing[a.id]}<span class="acp-spin"></span>{:else}<Play size={13} />{/if}
            Test run now
          </button>
          <button
            type="button"
            class="acp-btn-save"
            class:dirty={e.dirty}
            onclick={() => saveCard(a)}
            disabled={saving[a.id]}
          >
            <Save size={13} />
            {saving[a.id] ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    {/each}

    {#if agents.length === 0 && !loading}
      <div class="acp-empty">No agents registered.</div>
    {/if}
  </div>
</div>

<style>
  .acp-wrap { padding: 4px 2px 24px; color: var(--color-on-surface, #2c2c2c); }
  .acp-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
  .acp-title { font-family: 'Tiempos Headline', Georgia, serif; font-size: 22px; font-weight: 500; margin: 0 0 4px; }
  .acp-sub { font-size: 12.5px; color: var(--color-on-surface-dim, #6f6e69); margin: 0; }

  .acp-btn-ghost {
    padding: 7px 14px; font-size: 12px; background: transparent;
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 999px; cursor: pointer;
    font-family: inherit;
  }
  .acp-btn-ghost:hover:not(:disabled) { background: var(--color-bg, #faf9f5); }

  .acp-error { background: rgba(196,87,26,0.08); color: #c4571a; padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; font-size: 12.5px; }

  .acp-grid {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  @media (max-width: 1100px) { .acp-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 720px)  { .acp-grid { grid-template-columns: 1fr; } }

  .acp-card {
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd);
    border-radius: 12px;
    padding: 14px 14px 12px;
    display: flex; flex-direction: column; gap: 10px;
    transition: opacity 0.15s, border-color 0.15s;
  }
  .acp-card.disabled { opacity: 0.78; }

  .acp-card-head { display: flex; align-items: center; gap: 10px; }
  .acp-icon { color: var(--color-accent, #c96342); display: inline-flex; }
  .acp-titles { flex: 1; min-width: 0; }
  .acp-name { font-weight: 600; font-size: 13.5px; line-height: 1.2; }
  .acp-id { font-size: 11px; color: var(--color-on-surface-dim, #7d7c75); margin-top: 2px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .acp-type { color: var(--color-on-surface-dim, #9c9c8f); font-family: inherit; }
  .acp-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; box-shadow: 0 0 0 2px rgba(0,0,0,0.04); }

  .acp-purpose {
    margin: 0; font-size: 11.5px; color: var(--color-on-surface-dim, #6f6e69);
    line-height: 1.45;
  }

  .acp-runtime {
    display: grid; grid-template-columns: 1fr 1fr 1fr;
    gap: 6px; font-size: 11px;
    background: var(--color-bg, #faf9f5);
    border: 1px solid var(--color-border, #f0eee6);
    padding: 7px 9px; border-radius: 8px;
  }
  .acp-runtime span { color: var(--color-on-surface-dim, #7d7c75); margin-right: 3px; }

  .acp-row { display: flex; flex-direction: column; gap: 4px; }
  .acp-row-toggle { flex-direction: row; align-items: center; }
  .acp-lbl { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-on-surface-dim, #7d7c75); }

  .acp-toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; cursor: pointer; }
  .acp-toggle :global(svg) { color: var(--color-accent, #c96342); }

  .acp-switch {
    position: relative; width: 34px; height: 18px; border-radius: 999px;
    background: #d6d1c4; border: none; cursor: pointer; padding: 0; margin-left: auto;
    transition: background 0.18s;
  }
  .acp-switch.on { background: var(--color-accent, #c96342); }
  .acp-knob {
    position: absolute; top: 2px; left: 2px;
    width: 14px; height: 14px; border-radius: 50%;
    background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.18);
    transition: transform 0.18s;
  }
  .acp-switch.on .acp-knob { transform: translateX(16px); }

  .acp-interval { display: grid; grid-template-columns: 1fr 90px; gap: 8px; align-items: center; }
  .acp-interval input[type="range"] { width: 100%; accent-color: var(--color-accent, #c96342); }
  .acp-num-input {
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 6px;
    padding: 4px 6px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    text-align: center; background: var(--color-surface-bright, #fff);
  }

  .acp-textarea {
    width: 100%; box-sizing: border-box;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 6px;
    padding: 6px 8px; resize: vertical; background: var(--color-bg, #faf9f5);
    color: var(--color-on-surface, #2c2c2c);
  }
  .acp-textarea:focus { outline: none; border-color: var(--color-accent, #c96342); background: #fff; }

  .acp-actions { display: flex; gap: 8px; margin-top: 4px; }
  .acp-btn-test, .acp-btn-save {
    flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    padding: 7px 10px; font-size: 12px; font-weight: 500; font-family: inherit;
    border-radius: 999px; cursor: pointer; border: 1px solid var(--color-border, #e8e6dd);
    background: var(--color-surface-bright, #fff); color: var(--color-on-surface, #2c2c2c);
    transition: background 0.12s, border-color 0.12s, color 0.12s;
  }
  .acp-btn-test:hover:not(:disabled) { background: var(--color-bg, #faf9f5); }
  .acp-btn-save.dirty {
    background: var(--color-accent, #c96342); color: #fff; border-color: var(--color-accent, #c96342);
  }
  .acp-btn-save.dirty:hover:not(:disabled) { background: #b35538; }
  .acp-btn-test:disabled, .acp-btn-save:disabled { opacity: 0.55; cursor: not-allowed; }

  .acp-spin {
    display: inline-block; width: 12px; height: 12px;
    border: 2px solid rgba(0,0,0,0.15); border-top-color: var(--color-accent, #c96342);
    border-radius: 50%; animation: acp-spin 0.7s linear infinite;
  }
  @keyframes acp-spin { to { transform: rotate(360deg); } }

  .acp-empty { padding: 24px; text-align: center; color: var(--color-on-surface-dim, #6f6e69); font-size: 13px; grid-column: 1 / -1; }
</style>
