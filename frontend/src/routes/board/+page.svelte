<script>
  import { onMount } from 'svelte';
  import { apiJson } from '$lib/api';

  const STAGES = [
    { key: 'draft',      label: 'Draft',      hint: 'Position drafted, JD not finalised', accent: '#9c9c8f', tint: '#f3f2ec' },
    { key: 'sourcing',   label: 'Sourcing',   hint: 'Open + accepting applications',      accent: '#3a7bbf', tint: '#eaf2fa' },
    { key: 'screening',  label: 'Screening',  hint: 'Reviewing CVs / phone screens',      accent: '#6f57bd', tint: '#f0ecf8' },
    { key: 'interview',  label: 'Interview',  hint: 'Loops in progress',                  accent: '#c98c2a', tint: '#faf2e1' },
    { key: 'offer',      label: 'Offer',      hint: 'Offer extended',                     accent: '#c96342', tint: '#f8e8e1' },
    { key: 'filled',     label: 'Filled',     hint: 'Hire accepted, role closed',         accent: '#3a8a4f', tint: '#e6f1e9' },
    { key: 'archived',   label: 'Archived',   hint: 'Hidden / cancelled',                 accent: '#7d7c75', tint: '#ecebe6' },
  ];

  let kpis = $state({
    open_positions: 0, active_cvs: 0, avg_tth_days: null, stale_count: 0, filled_mtd: 0,
    new_today: 0, interviews_week: 0, offers_out: 0, avg_match_score: null, hired_qtd: 0,
  });
  let stages = $state({});
  let departments = $state([]);
  let loading = $state(true);
  let deptFilter = $state('all');
  let search = $state('');
  let dragOver = $state(null);
  let dragging = $state(null);

  async function load() {
    loading = true;
    try {
      const d = await apiJson('/board/summary');
      kpis = d.kpis || kpis;
      stages = d.stages || {};
      departments = d.departments || [];
    } catch (e) { console.error('board load failed', e); }
    finally { loading = false; }
  }
  onMount(load);

  function filterCards(cards) {
    const q = search.trim().toLowerCase();
    return (cards || []).filter(c => {
      if (deptFilter !== 'all' && c.department !== deptFilter) return false;
      if (q) {
        const hay = [c.title, c.department, c.location].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function dragStart(e, slug, fromStage) {
    dragging = { slug, fromStage };
    try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', slug); } catch {}
  }
  function dragEnd() { dragging = null; dragOver = null; }
  function dragOverCol(e, stage) { e.preventDefault(); dragOver = stage; }
  function dragLeaveCol(stage) { if (dragOver === stage) dragOver = null; }
  async function dropOnCol(e, toStage) {
    e.preventDefault();
    const slug = dragging?.slug || e.dataTransfer.getData('text/plain');
    const from = dragging?.fromStage;
    dragOver = null; dragging = null;
    if (!slug || from === toStage) return;
    // Optimistic UI
    const fromList = stages[from] || [];
    const idx = fromList.findIndex(c => c.slug === slug);
    if (idx === -1) return;
    const card = fromList[idx];
    stages = {
      ...stages,
      [from]: fromList.filter(c => c.slug !== slug),
      [toStage]: [{ ...card, stage: toStage }, ...(stages[toStage] || [])],
    };
    try {
      await apiJson(`/board/positions/${slug}/lifecycle`, {
        method: 'PATCH', body: JSON.stringify({ stage: toStage }),
      });
    } catch (err) {
      alert('Move failed: ' + err.message);
      load();  // rollback by re-fetch
    }
  }

  function tthLabel() {
    if (kpis.avg_tth_days === null) return '—';
    return `${kpis.avg_tth_days}d`;
  }
</script>

<svelte:head><title>Hiring Board · City Agent Pulse</title></svelte:head>

<div class="board-wrap">
  <!-- FROZEN HEADER + KPI bundle -->
  <div class="board-sticky">
    <header class="board-head">
      <div>
        <h1 class="page-title">Hiring board</h1>
        <p class="page-sub">Drag positions across stages to update lifecycle. Live view across the org.</p>
      </div>
      <div class="board-actions">
        <button class="btn-ghost" onclick={load} disabled={loading}>{loading ? '…' : '⟳ Refresh'}</button>
      </div>
    </header>

    <!-- KPI ROW -->
    <div class="kpi-row">
    <div class="kpi-tile">
      <div class="kpi-label">Open</div>
      <div class="kpi-value">{kpis.open_positions}</div>
      <div class="kpi-sub">positions</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Active CVs</div>
      <div class="kpi-value">{kpis.active_cvs}</div>
      <div class="kpi-sub">pipeline</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">New today</div>
      <div class="kpi-value">{kpis.new_today}</div>
      <div class="kpi-sub">positions</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Interviews</div>
      <div class="kpi-value">{kpis.interviews_week}</div>
      <div class="kpi-sub">this week</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Offers out</div>
      <div class="kpi-value">{kpis.offers_out}</div>
      <div class="kpi-sub">awaiting</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Avg score</div>
      <div class="kpi-value">{kpis.avg_match_score !== null ? kpis.avg_match_score + '%' : '—'}</div>
      <div class="kpi-sub">match</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Avg TTH</div>
      <div class="kpi-value">{tthLabel()}</div>
      <div class="kpi-sub">days</div>
    </div>
    <div class="kpi-tile {kpis.stale_count > 0 ? 'kpi-warn' : ''}">
      <div class="kpi-label">Stale</div>
      <div class="kpi-value">{kpis.stale_count}</div>
      <div class="kpi-sub">&gt;30d SLA</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Filled MTD</div>
      <div class="kpi-value">{kpis.filled_mtd}</div>
      <div class="kpi-sub">this month</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">Hired QTD</div>
      <div class="kpi-value">{kpis.hired_qtd}</div>
      <div class="kpi-sub">this quarter</div>
    </div>
    </div>
  </div>
  <!-- /board-sticky -->

  <!-- FILTER BAR -->
  <div class="filter-bar">
    <div class="search-wrap">
      <span class="material-symbols-outlined search-icon">search</span>
      <input type="text" bind:value={search} placeholder="Filter board…" />
    </div>
    <div class="dept-chips">
      <button class="chip {deptFilter === 'all' ? 'on' : ''}" onclick={() => deptFilter = 'all'}>All</button>
      {#each departments as d}
        <button class="chip {deptFilter === d ? 'on' : ''}" onclick={() => deptFilter = d}>{d}</button>
      {/each}
    </div>
  </div>

  <!-- BOARD -->
  {#if loading}
    <div class="board-loading">Loading board…</div>
  {:else}
    <div class="board-cols">
      {#each STAGES as st}
        {@const cards = filterCards(stages[st.key])}
        <div class="col {dragOver === st.key ? 'col-over' : ''}"
             style="--col-accent: {st.accent}; --col-tint: {st.tint};"
             ondragover={(e) => dragOverCol(e, st.key)}
             ondragleave={() => dragLeaveCol(st.key)}
             ondrop={(e) => dropOnCol(e, st.key)}
             role="region" aria-label={st.label}>
          <div class="col-stripe"></div>
          <div class="col-head">
            <span class="col-name">{st.label}</span>
            <span class="col-count">{cards.length}</span>
          </div>
          <div class="col-body">
            {#each cards as c (c.slug)}
              <div class="card"
                   draggable="true"
                   ondragstart={(e) => dragStart(e, c.slug, st.key)}
                   ondragend={dragEnd}
                   onclick={() => window.location.href = `/positions/${c.slug}`}
                   role="button" tabindex="0"
                   onkeydown={(e) => { if (e.key === 'Enter') window.location.href = `/positions/${c.slug}`; }}>
                <div class="card-title">{c.title}</div>
                <div class="card-meta">{c.department || '—'}{c.location ? ' · ' + c.location : ''}</div>
                <div class="card-kpis">
                  <span class="kpi-chip">{c.cv_count} CV{c.cv_count !== 1 ? 's' : ''}</span>
                  {#if c.avg_match !== null}
                    <span class="kpi-chip kpi-chip-match">{c.avg_match}%</span>
                  {/if}
                </div>
              </div>
            {/each}
            {#if cards.length === 0}
              <div class="col-empty">empty</div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .board-wrap {
    padding: 0 28px 64px; max-width: 100%;
    height: 100%; overflow-y: auto;
  }
  .board-sticky {
    position: sticky; top: 0; z-index: 30;
    background: #faf9f5;  /* solid, opaque */
    padding: 18px 0 12px;
    margin: 0 -28px;       /* bleed full width */
    padding-left: 28px; padding-right: 28px;
    border-bottom: 1px solid var(--color-border, #e8e6dd);
    box-shadow: 0 4px 8px -4px rgba(0, 0, 0, 0.06);
  }
  .board-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
  .page-title {
    font-family: 'Tiempos Headline', Georgia, serif; font-size: 28px; font-weight: 500;
    margin: 0 0 4px; letter-spacing: -0.02em; color: var(--color-on-surface, #2c2c2c);
  }
  .page-sub { font-size: 13px; color: var(--color-on-surface-dim, #6f6e69); margin: 0; }
  .board-actions { display: flex; gap: 8px; }
  .btn-ghost {
    padding: 7px 14px; font-size: 12.5px; font-weight: 500;
    background: transparent; color: var(--color-on-surface, #2c2c2c);
    border: 1px solid var(--color-border, #d8d5cc); border-radius: 7px; cursor: pointer;
  }
  .btn-ghost:hover:not(:disabled) { background: var(--color-bg, #faf9f5); }

  /* KPI tiles — compact (sticky handled by .board-sticky parent) */
  .kpi-row {
    display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px;
  }
  @media (max-width: 1400px) { .kpi-row { grid-template-columns: repeat(5, 1fr); } }
  @media (max-width: 900px)  { .kpi-row { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 600px)  { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
  .kpi-tile {
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 8px;
    padding: 8px 10px;
  }
  .kpi-label {
    font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--color-on-surface-dim, #6f6e69); margin-bottom: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .kpi-value {
    font-family: 'Tiempos Headline', Georgia, serif;
    font-size: 20px; font-weight: 500; line-height: 1.1;
    color: var(--color-on-surface, #2c2c2c);
  }
  .kpi-sub {
    font-size: 10px; color: var(--color-on-surface-dim, #6f6e69); margin-top: 1px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .kpi-warn .kpi-value { color: var(--color-error, #c4571a); }

  /* Filter bar */
  .filter-bar {
    display: flex; align-items: center; gap: 14px;
    margin: 16px 0;
    flex-wrap: wrap;
  }
  .search-wrap { position: relative; min-width: 240px; }
  .search-icon {
    position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
    font-size: 16px; color: var(--color-on-surface-dim, #6f6e69); pointer-events: none;
  }
  .search-wrap input {
    width: 100%; padding: 8px 12px 8px 32px; font-size: 13px; font-family: inherit;
    background: var(--color-surface, #fff); color: var(--color-on-surface, #2c2c2c);
    border: 1px solid var(--color-border, #d8d5cc); border-radius: 8px; outline: none;
  }
  .search-wrap input:focus { border-color: var(--color-accent, #c96342); box-shadow: 0 0 0 2px rgba(201, 99, 66, 0.12); }
  .dept-chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip {
    padding: 5px 12px; font-size: 11.5px; font-weight: 500;
    background: transparent; color: var(--color-on-surface, #2c2c2c);
    border: 1px solid var(--color-border, #d8d5cc); border-radius: 999px; cursor: pointer;
  }
  .chip:hover { background: var(--color-bg, #faf9f5); }
  .chip.on { background: var(--color-accent, #c96342); color: #fff; border-color: var(--color-accent, #c96342); }

  /* Board */
  .board-cols {
    display: grid; grid-template-columns: repeat(7, minmax(220px, 1fr));
    gap: 10px; overflow-x: auto;
    padding-bottom: 12px;
  }
  @media (max-width: 1400px) { .board-cols { grid-template-columns: repeat(7, 220px); } }
  .col {
    background: var(--col-tint, #f3f2ec);
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 10px;
    display: flex; flex-direction: column; min-height: 280px;
    position: relative; overflow: hidden;
    transition: background 120ms, border-color 120ms;
  }
  .col-stripe {
    height: 4px; background: var(--col-accent, #c96342);
    flex-shrink: 0;
  }
  .col-over {
    background: var(--col-tint, #f3f2ec);
    border-color: var(--col-accent, #c96342);
    box-shadow: 0 0 0 2px var(--col-accent, #c96342) inset;
  }
  .col-head {
    padding: 11px 14px; display: flex; align-items: center; justify-content: space-between;
    background: var(--color-surface-bright, #fff);
    border-bottom: 1px solid var(--color-border, #e8e6dd);
  }
  .col-name {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--col-accent, #2c2c2c);
  }
  .col-count {
    font-size: 11px; font-weight: 700; padding: 2px 9px;
    background: var(--col-accent, #c96342); color: #fff;
    border-radius: 999px;
  }
  .col-body { padding: 8px; flex: 1; display: flex; flex-direction: column; gap: 8px; }
  .card {
    background: var(--color-surface-bright, #fff);
    border: 1px solid var(--color-border, #e8e6dd); border-radius: 8px;
    padding: 10px 12px; cursor: grab; transition: box-shadow 120ms, transform 120ms;
  }
  .card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); transform: translateY(-1px); }
  .card:active { cursor: grabbing; }
  .card-title {
    font-size: 13px; font-weight: 600; color: var(--color-on-surface, #2c2c2c);
    line-height: 1.3; margin-bottom: 4px;
  }
  .card-meta { font-size: 11px; color: var(--color-on-surface-dim, #6f6e69); margin-bottom: 8px; }
  .card-kpis { display: flex; gap: 6px; flex-wrap: wrap; }
  .kpi-chip {
    font-size: 10.5px; font-weight: 600; padding: 2px 8px;
    background: var(--color-bg, #faf9f5); border-radius: 4px;
    color: var(--color-on-surface, #2c2c2c);
  }
  .kpi-chip-match { background: rgba(201, 99, 66, 0.12); color: var(--color-accent, #c96342); }
  .col-empty {
    text-align: center; padding: 20px 0; font-size: 11px; color: var(--color-on-surface-dim, #6f6e69);
    font-style: italic;
  }
  .board-loading { padding: 40px; text-align: center; color: var(--color-on-surface-dim, #6f6e69); }
</style>
