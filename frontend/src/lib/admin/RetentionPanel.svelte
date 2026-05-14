<script lang="ts">
  /** Admin · Retention — sets default expires_at window (in days) for newly
   *  created CVs and JDs. Existing rows are NOT mutated. Affects rows
   *  created AFTER save. Pure visual chip in repos — does NOT block
   *  edits or exclude from AI scan. */
  import { onMount } from 'svelte';
  import { apiJson } from '$lib/api.ts';
  import { addToast } from '$lib/Toast.svelte';

  let cvDays = $state(90);
  let jdDays = $state(90);
  let loaded = $state(false);
  let saving = $state(false);

  onMount(async () => {
    try {
      const d = await apiJson('/admin/retention');
      cvDays = Number(d?.cv_days) || 90;
      jdDays = Number(d?.jd_days) || 90;
    } catch (e: any) {
      addToast('error', e?.message || 'Could not load retention settings');
    } finally {
      loaded = true;
    }
  });

  function clamp(n: number): number {
    n = Number(n);
    if (!Number.isFinite(n) || n < 1) return 1;
    if (n > 3650) return 3650;
    return Math.round(n);
  }

  async function save() {
    saving = true;
    try {
      const payload = { cv_days: clamp(cvDays), jd_days: clamp(jdDays) };
      const out = await apiJson('/admin/retention', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      cvDays = out.cv_days;
      jdDays = out.jd_days;
      addToast('success', 'Retention defaults saved. Applies to newly created records.');
    } catch (e: any) {
      addToast('error', e?.message || 'Save failed');
    } finally {
      saving = false;
    }
  }
</script>

<div class="claude-card" style="padding: 18px; max-width: 640px;">
  <div class="card-title">Retention defaults</div>
  <p style="font-size: 12.5px; color: var(--color-on-surface-dim, #6b6b6b); margin: 4px 0 16px;">
    New candidate CVs and JDs get an <code>expires_at</code> stamp of <em>today + N days</em>.
    Repos show a chip warning when a row is within 14 days of expiry (amber) or already
    expired (red). This is a visual signal only — expired rows remain editable and continue
    to surface in AI scans.
  </p>

  {#if !loaded}
    <div style="font-size: 12px; color: var(--color-on-surface-dim, #888);">Loading…</div>
  {:else}
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px;">
      <label style="display: flex; flex-direction: column; gap: 6px;">
        <span style="font-size: 12px; font-weight: 600;">CV retention (days)</span>
        <input
          class="claude-input"
          type="number"
          min="1"
          max="3650"
          bind:value={cvDays}
        />
      </label>
      <label style="display: flex; flex-direction: column; gap: 6px;">
        <span style="font-size: 12px; font-weight: 600;">JD retention (days)</span>
        <input
          class="claude-input"
          type="number"
          min="1"
          max="3650"
          bind:value={jdDays}
        />
      </label>
    </div>

    <div style="display: flex; gap: 8px; align-items: center;">
      <button class="btn-primary" onclick={save} disabled={saving}>
        {saving ? 'Saving…' : 'Save'}
      </button>
      <span style="font-size: 11.5px; color: var(--color-on-surface-dim, #888);">
        Applies to records created after save.
      </span>
    </div>
  {/if}
</div>
