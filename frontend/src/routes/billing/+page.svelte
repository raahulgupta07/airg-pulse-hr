<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { apiJson } from '$lib/api.ts';

  type Summary = {
    total_cost: number; cap_usd: number; cap_used_pct: number;
    in_tokens: number; out_tokens: number; total_tokens: number;
    calls: number; avg_latency_ms: number; p95_latency_ms: number;
    timeouts: number; fails: number; jobs: number; fail_rate_pct: number;
  };
  type ModelRow = { model: string; calls: number; tokens: number; cost_usd: number };
  type StepRow = { step: string; calls: number; avg_cost: number; total_cost: number };
  type HourRow = { hour: string; cost_usd: number };
  type JobRow = {
    run_id: string; candidate_id: number | null; candidate_name: string;
    started: string; steps: number; total_cost: number; tokens: number;
    duration_s: number; status: string;
  };
  type TopRow = {
    ts: string; model: string; step: string | null; candidate_id: number | null;
    in_tokens: number; out_tokens: number; cost_usd: number; status: string;
  };

  let range = $state<'today' | '7d' | '30d' | 'mtd'>('today');
  let summary = $state<Summary | null>(null);
  let byModel = $state<ModelRow[]>([]);
  let byStep = $state<StepRow[]>([]);
  let hourly = $state<HourRow[]>([]);
  let jobs = $state<JobRow[]>([]);
  let jobsTotal = $state(0);
  let page = $state(1);
  let topCalls = $state<TopRow[]>([]);
  let loading = $state(true);
  let error = $state('');
  let openJob = $state<string | null>(null);
  let jobDetail = $state<any>(null);

  async function loadAll() {
    loading = true; error = '';
    try {
      const [s, m, st, h, j, t] = await Promise.all([
        apiJson(`/billing/summary?range=${range}`),
        apiJson(`/billing/by-model?range=${range}`),
        apiJson(`/billing/by-step?range=${range}`),
        apiJson(`/billing/hourly?range=${range}`),
        apiJson(`/billing/jobs?range=${range}&page=${page}&per_page=25`),
        apiJson(`/billing/top?range=${range}&limit=5`),
      ]);
      summary = s; byModel = m; byStep = st; hourly = h;
      jobs = j.rows; jobsTotal = j.total; topCalls = t;
    } catch (e: any) {
      error = e?.message || 'Load failed';
    } finally { loading = false; }
  }

  async function openJobDetail(run_id: string) {
    openJob = run_id;
    jobDetail = null;
    try { jobDetail = await apiJson(`/billing/job/${run_id}`); } catch {}
  }

  onMount(() => {
    loadAll();
    const t = setInterval(loadAll, 30000);
    return () => clearInterval(t);
  });

  // refilter when range changes
  $effect(() => { range; untrack(() => { page = 1; loadAll(); }); });

  function fmtUsd(n: number) { return `$${(n ?? 0).toFixed(4)}`; }
  function fmtUsdShort(n: number) { return `$${(n ?? 0).toFixed(2)}`; }
  function fmtTok(n: number) { return (n ?? 0).toLocaleString(); }
  function fmtDur(s: number) {
    if (!s) return '—';
    if (s < 60) return `${s}s`;
    return `${Math.floor(s/60)}m ${s%60}s`;
  }
  function statusBadge(s: string): string {
    if (!s || s.startsWith('ok')) return 'ok';
    if (s.startsWith('timeout')) return 'timeout';
    if (s.startsWith('cap_')) return 'cap';
    return 'fail';
  }

  function exportCsv() {
    window.location.href = `/api/billing/export.csv?range=${range}`;
  }

  let maxHourly = $derived(Math.max(0.01, ...hourly.map(h => h.cost_usd)));

  // cost color based on cap %
  function costColor(pct: number): string {
    if (pct > 80) return 'var(--color-danger, #b54a3a)';
    if (pct > 50) return 'var(--color-accent, #c96342)';
    return 'var(--color-success, #3a7d4f)';
  }
  function capFillColor(pct: number): string {
    if (pct > 80) return 'var(--color-danger, #b54a3a)';
    if (pct > 50) return 'var(--color-accent, #c96342)';
    return 'var(--color-success, #3a7d4f)';
  }
</script>

<svelte:head><title>Billing — City Agent Pulse</title></svelte:head>

<div class="page">
  <header class="hdr">
    <div>
      <div class="h1">Billing</div>
      <div class="h2">LLM cost ledger — per-job, per-model, per-step</div>
    </div>
    <div class="actions">
      <button class="btn-primary" onclick={loadAll}>↻ Refresh</button>
      <button class="btn-outline" onclick={exportCsv}>↓ Export CSV</button>
    </div>
  </header>

  <!-- Filters -->
  <section class="filters">
    <div class="seg">
      {#each [['today','Today'],['7d','7 days'],['30d','30 days'],['mtd','MTD']] as [v, l]}
        <button class="seg-item" class:active={range === v} onclick={() => range = v as any}>{l}</button>
      {/each}
    </div>
  </section>

  {#if error}
    <div class="err">{error}</div>
  {/if}

  <!-- Totals -->
  {#if summary}
    <section class="totals">
      <div class="card tot-main">
        <div class="kpi-l">Total spend</div>
        <div class="tot-amount" style="color: {costColor(summary.cap_used_pct)};">
          {fmtUsdShort(summary.total_cost)}<span class="tot-cap"> / {fmtUsdShort(summary.cap_usd)} cap</span>
        </div>
        <div class="tot-bar"><div class="tot-bar-fill" style="width: {Math.min(100, summary.cap_used_pct)}%; background: {capFillColor(summary.cap_used_pct)};"></div></div>
        <div class="tot-pct">{summary.cap_used_pct.toFixed(1)}% used</div>
      </div>
      <div class="card kpi"><div class="kpi-v">{fmtTok(summary.total_tokens)}</div><div class="kpi-l">Total tokens</div><div class="kpi-sub">in: {fmtTok(summary.in_tokens)} · out: {fmtTok(summary.out_tokens)}</div></div>
      <div class="card kpi"><div class="kpi-v">{summary.calls}</div><div class="kpi-l">LLM calls</div><div class="kpi-sub">avg {summary.avg_latency_ms}ms · p95 {summary.p95_latency_ms}ms</div></div>
      <div class="card kpi"><div class="kpi-v">{summary.jobs}</div><div class="kpi-l">CV jobs</div><div class="kpi-sub">fails: {summary.fails} · timeouts: {summary.timeouts}</div></div>
      <div class="card kpi"><div class="kpi-v">{summary.fail_rate_pct.toFixed(2)}%</div><div class="kpi-l">Fail rate</div><div class="kpi-sub">{summary.timeouts} timeouts</div></div>
    </section>
  {/if}

  <!-- By Model + By Step side by side -->
  <section class="two-col">
    <div class="card">
      <div class="card-h">Cost by model</div>
      <table class="tbl">
        <thead><tr><th>Model</th><th class="r">Calls</th><th class="r">Tokens</th><th class="r">$</th></tr></thead>
        <tbody>
          {#each byModel as r}
            <tr>
              <td class="mono">{r.model}</td>
              <td class="r">{r.calls}</td>
              <td class="r">{fmtTok(r.tokens)}</td>
              <td class="r b">{fmtUsd(r.cost_usd)}</td>
            </tr>
          {/each}
          {#if byModel.length === 0}
            <tr><td colspan="4" class="empty">No data</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-h">Cost by pipeline step</div>
      <table class="tbl">
        <thead><tr><th>Step</th><th class="r">Calls</th><th class="r">Avg $</th><th class="r">Total $</th></tr></thead>
        <tbody>
          {#each byStep as r}
            <tr>
              <td class="mono">{r.step}</td>
              <td class="r">{r.calls}</td>
              <td class="r">{fmtUsd(r.avg_cost)}</td>
              <td class="r b">{fmtUsd(r.total_cost)}</td>
            </tr>
          {/each}
          {#if byStep.length === 0}
            <tr><td colspan="4" class="empty">No data</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </section>

  <!-- Hourly burn chart (ASCII bars) -->
  <section class="card">
    <div class="card-h">Hourly burn ({range === 'today' ? 'today' : range === 'mtd' ? 'month-to-date' : range})</div>
    <div class="bars">
      {#each hourly as h}
        <div class="bar-col" title="{h.hour} · {fmtUsd(h.cost_usd)}">
          <div class="bar" style="height: {(h.cost_usd / maxHourly * 100).toFixed(1)}%;"></div>
          <div class="bar-lab">{new Date(h.hour).getHours()}</div>
        </div>
      {/each}
      {#if hourly.length === 0}
        <div class="empty">No data</div>
      {/if}
    </div>
  </section>

  <!-- Jobs table -->
  <section class="card">
    <div class="card-h">CV jobs · {jobsTotal} total</div>
    <table class="tbl">
      <thead><tr><th>#</th><th>Candidate</th><th>Started</th><th class="r">Steps</th><th class="r">Total $</th><th class="r">Tokens</th><th class="r">Duration</th><th>Status</th></tr></thead>
      <tbody>
        {#each jobs as j}
          <tr class="clickable" onclick={() => openJobDetail(j.run_id)}>
            <td>{j.candidate_id ?? '—'}</td>
            <td>{j.candidate_name}</td>
            <td class="mono">{j.started ? new Date(j.started).toLocaleTimeString() : '—'}</td>
            <td class="r">{j.steps}</td>
            <td class="r b">{fmtUsd(j.total_cost)}</td>
            <td class="r">{fmtTok(j.tokens)}</td>
            <td class="r">{fmtDur(j.duration_s)}</td>
            <td><span class="badge {statusBadge(j.status)}">{j.status}</span></td>
          </tr>
        {/each}
        {#if jobs.length === 0}
          <tr><td colspan="8" class="empty">No jobs in range</td></tr>
        {/if}
      </tbody>
    </table>
    {#if jobsTotal > 25}
      <div class="pag">
        <button class="btn-outline" disabled={page <= 1} onclick={() => { page--; loadAll(); }}>◀ Prev</button>
        <span>Page {page} / {Math.ceil(jobsTotal / 25)}</span>
        <button class="btn-outline" disabled={page * 25 >= jobsTotal} onclick={() => { page++; loadAll(); }}>Next ▶</button>
      </div>
    {/if}
  </section>

  <!-- Top expensive calls -->
  <section class="card">
    <div class="card-h">Top expensive calls</div>
    <table class="tbl">
      <thead><tr><th>Time</th><th>Model</th><th>Step</th><th class="r">Cand</th><th class="r">In tok</th><th class="r">Out tok</th><th class="r">$</th><th>Status</th></tr></thead>
      <tbody>
        {#each topCalls as t}
          <tr>
            <td class="mono">{new Date(t.ts).toLocaleTimeString()}</td>
            <td class="mono">{t.model}</td>
            <td class="mono">{t.step ?? '—'}</td>
            <td class="r">{t.candidate_id ?? '—'}</td>
            <td class="r">{fmtTok(t.in_tokens)}</td>
            <td class="r">{fmtTok(t.out_tokens)}</td>
            <td class="r b">{fmtUsd(t.cost_usd)}</td>
            <td><span class="badge {statusBadge(t.status)}">{t.status}</span></td>
          </tr>
        {/each}
        {#if topCalls.length === 0}
          <tr><td colspan="8" class="empty">No calls</td></tr>
        {/if}
      </tbody>
    </table>
  </section>

  {#if openJob}
    <div class="modal-bg" onclick={() => { openJob = null; jobDetail = null; }}>
      <div class="modal" onclick={(e) => e.stopPropagation()}>
        <div class="modal-h">Job · {openJob}</div>
        {#if !jobDetail}
          <div class="empty">Loading…</div>
        {:else}
          <table class="tbl">
            <thead><tr><th>Step</th><th>Model</th><th class="r">In</th><th class="r">Out</th><th class="r">$</th><th class="r">Latency</th><th>Status</th></tr></thead>
            <tbody>
              {#each jobDetail.steps as s}
                <tr>
                  <td class="mono">{s.step ?? '—'}</td>
                  <td class="mono">{s.model}</td>
                  <td class="r">{fmtTok(s.in_tokens)}</td>
                  <td class="r">{fmtTok(s.out_tokens)}</td>
                  <td class="r b">{fmtUsd(s.cost_usd)}</td>
                  <td class="r">{s.latency_ms}ms</td>
                  <td><span class="badge {statusBadge(s.status)}">{s.status}</span></td>
                </tr>
              {/each}
              <tr class="totals-row">
                <td colspan="2" class="b">Total</td>
                <td class="r b">{fmtTok(jobDetail.totals.in_tokens)}</td>
                <td class="r b">{fmtTok(jobDetail.totals.out_tokens)}</td>
                <td class="r b">{fmtUsd(jobDetail.totals.cost_usd)}</td>
                <td class="r b">{jobDetail.totals.latency_ms}ms</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        {/if}
        <div style="margin-top:14px; text-align:right;">
          <button class="btn-primary" onclick={() => { openJob = null; jobDetail = null; }}>Close</button>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  /* Claude warm theme tokens (with fallbacks) */
  .page {
    --c-bg: var(--color-bg, #faf9f5);
    --c-bg-alt: var(--color-bg-alt, #f4f3ee);
    --c-surface: var(--color-surface, #ffffff);
    --c-ink: var(--color-ink, #2b2a27);
    --c-muted: var(--color-muted, #6b6a64);
    --c-subtle: var(--color-subtle, #8a8980);
    --c-border: var(--color-border, #e7e5dc);
    --c-accent: var(--color-accent, #c96342);
    --c-accent-hover: var(--color-accent-hover, #b5563a);
    --c-success: var(--color-success, #3a7d4f);
    --c-warning: var(--color-warning, #c08a3e);
    --c-danger: var(--color-danger, #b54a3a);
    --serif: var(--font-serif, 'Tiempos', 'Tiempos Headline', Georgia, 'Times New Roman', serif);
    --sans: var(--font-sans, 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
    --mono: var(--font-mono, 'JetBrains Mono', 'SF Mono', Menlo, monospace);
    --shadow-sm: 0 1px 2px rgba(40, 38, 33, 0.04);
    --shadow-md: 0 1px 3px rgba(40, 38, 33, 0.06), 0 1px 2px rgba(40, 38, 33, 0.04);

    padding: 28px 32px;
    max-width: 1400px;
    margin: 0 auto;
    color: var(--c-ink);
    height: 100%;
    overflow-y: auto;
    box-sizing: border-box;
    background: var(--c-bg);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.5;
  }

  .hdr { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom: 24px; }
  .h1 {
    font-family: var(--serif);
    font-size: 28px;
    font-weight: 500;
    letter-spacing: -0.015em;
    line-height: 1.15;
    color: var(--c-ink);
  }
  .h2 {
    font-size: 13px;
    font-weight: 400;
    color: var(--c-muted);
    margin-top: 4px;
  }
  .actions { display:flex; gap: 8px; }

  .btn-primary {
    background: var(--c-accent);
    color: #fff;
    border: 1px solid var(--c-accent);
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 500;
    border-radius: 8px;
    cursor: pointer;
    font-family: var(--sans);
    transition: background .15s ease;
  }
  .btn-primary:hover { background: var(--c-accent-hover); border-color: var(--c-accent-hover); }

  .btn-outline {
    background: var(--c-surface);
    color: var(--c-ink);
    border: 1px solid var(--c-border);
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 500;
    border-radius: 8px;
    cursor: pointer;
    font-family: var(--sans);
    transition: background .15s ease, border-color .15s ease;
  }
  .btn-outline:hover { background: var(--c-bg-alt); border-color: #d8d6cc; }
  .btn-outline:disabled { opacity: 0.4; cursor: not-allowed; }

  /* Segmented range control */
  .filters { margin-bottom: 20px; }
  .seg {
    display: inline-flex;
    gap: 2px;
    background: var(--c-bg-alt);
    border-radius: 999px;
    padding: 3px;
  }
  .seg-item {
    background: transparent;
    border: none;
    color: var(--c-muted);
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 500;
    border-radius: 999px;
    cursor: pointer;
    font-family: var(--sans);
    transition: background .15s ease, color .15s ease;
  }
  .seg-item:hover { color: var(--c-ink); }
  .seg-item.active {
    background: var(--c-surface);
    color: var(--c-ink);
    box-shadow: var(--shadow-sm);
  }

  .err {
    background: #fbeae5;
    color: var(--c-danger);
    padding: 10px 14px;
    margin-bottom: 14px;
    font-weight: 500;
    font-size: 13px;
    border-radius: 8px;
    border: 1px solid #f0d4cc;
  }

  /* Card base */
  .card {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: 12px;
    padding: 18px;
    box-shadow: var(--shadow-sm);
    margin-bottom: 18px;
  }
  .card-h {
    font-family: var(--serif);
    font-size: 16px;
    font-weight: 500;
    color: var(--c-ink);
    margin-bottom: 14px;
    letter-spacing: -0.005em;
  }

  /* Totals */
  .totals {
    display: grid;
    grid-template-columns: 1.4fr repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 18px;
  }
  .tot-main { padding: 18px; }
  .tot-amount {
    font-family: var(--serif);
    font-size: 32px;
    font-weight: 500;
    line-height: 1.1;
    margin-top: 4px;
    letter-spacing: -0.015em;
  }
  .tot-cap { font-size: 14px; color: var(--c-muted); font-weight: 400; font-family: var(--sans); }
  .tot-bar {
    height: 4px;
    background: var(--c-bg-alt);
    border-radius: 999px;
    margin-top: 14px;
    overflow: hidden;
  }
  .tot-bar-fill { height: 100%; border-radius: 999px; transition: width .4s ease; }
  .tot-pct { font-size: 12px; margin-top: 8px; color: var(--c-muted); font-weight: 500; }

  .kpi { padding: 16px 18px; }
  .kpi-v {
    font-family: var(--serif);
    font-size: 28px;
    font-weight: 500;
    color: var(--c-ink);
    line-height: 1.1;
    letter-spacing: -0.015em;
    font-variant-numeric: tabular-nums;
  }
  .kpi-l {
    font-size: 12px;
    font-weight: 500;
    color: var(--c-muted);
    margin-top: 6px;
  }
  .kpi-sub {
    font-size: 11px;
    color: var(--c-subtle);
    margin-top: 6px;
  }

  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 18px; }
  @media (max-width: 1100px) {
    .totals { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 900px) {
    .two-col { grid-template-columns: 1fr; }
    .totals { grid-template-columns: 1fr; }
  }

  /* Tables */
  .tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .tbl thead th {
    text-align: left;
    padding: 9px 12px;
    font-size: 12px;
    font-weight: 500;
    color: var(--c-muted);
    background: var(--c-bg-alt);
    border-bottom: 1px solid var(--c-border);
  }
  .tbl thead th:first-child { border-top-left-radius: 8px; }
  .tbl thead th:last-child { border-top-right-radius: 8px; }
  .tbl td {
    padding: 9px 12px;
    border-bottom: 1px solid var(--c-border);
    color: var(--c-ink);
  }
  .tbl tbody tr:last-child td { border-bottom: none; }
  .tbl tbody tr:hover td { background: #faf8f3; }
  .tbl .r { text-align: right; font-variant-numeric: tabular-nums; }
  .tbl .b { font-weight: 600; }
  .mono { font-family: var(--mono); font-size: 12px; color: var(--c-ink); }
  .empty { text-align: center; color: var(--c-subtle); font-style: italic; padding: 22px; font-size: 13px; }
  .clickable { cursor: pointer; }
  .totals-row td { background: var(--c-bg-alt); border-top: 1px solid var(--c-border); }

  /* Badges */
  .badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid transparent;
  }
  .badge.ok { background: #e7f1ea; color: var(--c-success); border-color: #cfe3d6; }
  .badge.timeout { background: #faecd2; color: var(--c-warning); border-color: #f0dab2; }
  .badge.cap { background: #fbeae5; color: var(--c-accent); border-color: #f0d4cc; }
  .badge.fail { background: #fbeae5; color: var(--c-danger); border-color: #f0d4cc; }

  /* Hourly bars — coral on light track */
  .bars {
    display: flex;
    align-items: flex-end;
    gap: 6px;
    height: 160px;
    padding: 8px 4px 0;
    border-bottom: 1px solid var(--c-border);
  }
  .bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; min-width: 18px; }
  .bar {
    width: 100%;
    background: var(--c-accent);
    border-radius: 4px 4px 0 0;
    opacity: 0.85;
    transition: opacity .15s ease;
  }
  .bar-col:hover .bar { opacity: 1; }
  .bar-lab { font-size: 11px; margin-top: 6px; color: var(--c-muted); font-weight: 400; }

  .pag { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; font-size: 13px; color: var(--c-muted); }

  /* Modal */
  .modal-bg { position: fixed; inset: 0; background: rgba(40, 38, 33, 0.45); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px; }
  .modal {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: 12px;
    box-shadow: 0 20px 50px rgba(40, 38, 33, 0.18);
    max-width: 1000px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    padding: 24px;
  }
  .modal-h {
    font-family: var(--serif);
    font-size: 18px;
    font-weight: 500;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--c-border);
    margin-bottom: 16px;
    letter-spacing: -0.01em;
  }
</style>
