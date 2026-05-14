// White-label branding helpers — single source of truth for app name, logo,
// accent color, and footer text. Persisted to localStorage `pulse_branding`
// and (best-effort) to backend `/api/admin/branding`. Frontend renders out of
// localStorage so reload is instant; backend sync hydrates on mount.

import { writable } from 'svelte/store';

export interface Branding {
  appName: string;
  logoUrl: string;   // data URL or http(s) URL; empty string = no logo (fallback letter)
  accentColor: string;
  footerText: string;
}

export const DEFAULT_BRANDING: Branding = {
  appName: 'City Agent Pulse',
  logoUrl: '',
  accentColor: '#c96342',
  footerText: 'Org Heartbeat',
};

const LS_KEY = 'pulse_branding';

export function getBranding(): Branding {
  if (typeof window === 'undefined') return { ...DEFAULT_BRANDING };
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return { ...DEFAULT_BRANDING };
    const parsed = JSON.parse(raw);
    return {
      appName: typeof parsed.appName === 'string' && parsed.appName.trim() ? parsed.appName : DEFAULT_BRANDING.appName,
      logoUrl: typeof parsed.logoUrl === 'string' ? parsed.logoUrl : DEFAULT_BRANDING.logoUrl,
      accentColor: typeof parsed.accentColor === 'string' && /^#?[0-9a-fA-F]{6}$/.test(parsed.accentColor.replace('#', '')) ? parsed.accentColor : DEFAULT_BRANDING.accentColor,
      footerText: typeof parsed.footerText === 'string' && parsed.footerText.trim() ? parsed.footerText : DEFAULT_BRANDING.footerText,
    };
  } catch {
    return { ...DEFAULT_BRANDING };
  }
}

export function saveBrandingLocal(b: Branding): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(b));
  } catch {
    /* quota or disabled storage — ignore */
  }
}

// Reactive store consumers can subscribe to ($brandingStore in components).
export const brandingStore = writable<Branding>(getBranding());

/** Fetch branding from API and sync local cache. Returns the resolved branding,
 *  falling back to localStorage when the endpoint is missing or fails. */
export async function loadBrandingFromAPI(): Promise<Branding> {
  const local = getBranding();
  if (typeof window === 'undefined') return local;
  try {
    const r = await fetch('/api/admin/branding', { credentials: 'include' });
    if (r.status === 404) {
      // backend not yet implemented — silent fallback
      brandingStore.set(local);
      return local;
    }
    if (r.ok) {
      const data = await r.json();
      const next: Branding = {
        appName: data.app_name || data.appName || local.appName,
        logoUrl: data.logo_data_url || data.logo_url || data.logoUrl || local.logoUrl,
        accentColor: data.accent_color || data.accentColor || local.accentColor,
        footerText: data.footer_text || data.footerText || local.footerText,
      };
      saveBrandingLocal(next);
      brandingStore.set(next);
      return next;
    }
  } catch {
    /* endpoint missing — localStorage-only mode */
  }
  brandingStore.set(local);
  return local;
}

/** Returns true if backend branding endpoint responds (200 or 404 both count as
 *  "no error" — 404 just means endpoint not yet wired but server is alive). */
export async function brandingBackendReachable(): Promise<boolean> {
  if (typeof window === 'undefined') return false;
  try {
    const r = await fetch('/api/admin/branding', { credentials: 'include' });
    return r.ok; // only 200 means backend stores branding
  } catch {
    return false;
  }
}

/** Persist branding to backend (best effort) + always to localStorage.
 *  Returns true when the backend accepted the write, false on fallback. */
export async function saveBrandingToAPI(b: Branding): Promise<boolean> {
  saveBrandingLocal(b);
  brandingStore.set(b);
  if (typeof window === 'undefined') return false;
  try {
    const r = await fetch('/api/admin/branding', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        app_name: b.appName,
        logo_data_url: b.logoUrl,
        accent_color: b.accentColor,
        footer_text: b.footerText,
      }),
    });
    if (r.status === 404) return false; // backend not yet implemented — silent
    return r.ok;
  } catch {
    return false;
  }
}

/** Convert hex → {h,s,l} (0–360 / 0–100 / 0–100). */
function hexToHsl(hex: string): { h: number; s: number; l: number } {
  const m = hex.replace('#', '');
  const r = parseInt(m.slice(0, 2), 16) / 255;
  const g = parseInt(m.slice(2, 4), 16) / 255;
  const b = parseInt(m.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h *= 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

function hslToHex(h: number, s: number, l: number): string {
  s = Math.max(0, Math.min(100, s)) / 100;
  l = Math.max(0, Math.min(100, l)) / 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0;
  let g = 0;
  let b = 0;
  if (h < 60) { r = c; g = x; b = 0; }
  else if (h < 120) { r = x; g = c; b = 0; }
  else if (h < 180) { r = 0; g = c; b = x; }
  else if (h < 240) { r = 0; g = x; b = c; }
  else if (h < 300) { r = x; g = 0; b = c; }
  else { r = c; g = 0; b = x; }
  const toHex = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

/** Derive 4 shades from a base hex via HSL math.
 *  - accent        = base
 *  - accent-ink    = 10% darker (button hover / active text)
 *  - accent-soft   = lighter pastel (active nav background)
 *  - accent-bg     = very light tint (focus rings / dot halo) */
export function deriveAccentShades(hex: string) {
  const { h, s, l } = hexToHsl(hex);
  return {
    accent: hex,
    accentInk: hslToHex(h, s, Math.max(0, l - 10)),
    accentSoft: hslToHex(h, Math.max(20, s - 20), Math.min(95, l + 28)),
    accentBg: hslToHex(h, Math.max(15, s - 30), Math.min(98, l + 38)),
  };
}

/** Apply branding CSS variables on :root so global stylesheet picks up. */
export function applyBranding(b: Branding): void {
  if (typeof document === 'undefined') return;
  const shades = deriveAccentShades(b.accentColor);
  const root = document.documentElement;
  root.style.setProperty('--color-accent', shades.accent);
  root.style.setProperty('--color-accent-ink', shades.accentInk);
  root.style.setProperty('--color-accent-soft', shades.accentSoft);
  root.style.setProperty('--color-accent-bg', shades.accentBg);
}
