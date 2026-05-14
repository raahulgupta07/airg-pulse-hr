/**
 * auth.ts — session helpers.
 *
 * Cookie-based session is the canonical flow (HttpOnly `pulse_token` set by
 * POST /api/auth/login). Legacy localStorage Bearer token is retained for
 * backwards compatibility with any older callers.
 */

const TOKEN_KEY = 'hire_token';
const EXP_KEY = 'hire_token_exp';

export interface User {
	id?: number | string;
	email?: string;
	name?: string;
	display_name?: string;
	role?: string;
	operator_id?: string;
	[k: string]: unknown;
}

export function getToken(): string | null {
	if (typeof window === 'undefined') return null;
	return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, expEpochMs?: number | null): void {
	if (typeof window === 'undefined') return;
	localStorage.setItem(TOKEN_KEY, token);
	if (expEpochMs && Number.isFinite(expEpochMs)) {
		localStorage.setItem(EXP_KEY, String(expEpochMs));
	} else {
		localStorage.removeItem(EXP_KEY);
	}
}

export function clearToken(): void {
	if (typeof window === 'undefined') return;
	localStorage.removeItem(TOKEN_KEY);
	localStorage.removeItem(EXP_KEY);
}

export function isAuthed(): boolean {
	// With cookie auth, the only authoritative check is /auth/me. This is kept
	// for back-compat with code that gated UI on a synchronous flag.
	const tok = getToken();
	if (!tok) return false;
	if (typeof window === 'undefined') return false;
	const expRaw = localStorage.getItem(EXP_KEY);
	if (!expRaw) return true;
	const exp = Number(expRaw);
	if (!Number.isFinite(exp)) return true;
	return Date.now() < exp;
}

export async function me(): Promise<User | null> {
	try {
		const headers: Record<string, string> = {};
		const tok = getToken();
		if (tok) headers.Authorization = `Bearer ${tok}`;
		const res = await fetch('/api/auth/me', {
			headers,
			credentials: 'include',
		});
		if (res.status === 401) {
			clearToken();
			return null;
		}
		if (!res.ok) return null;
		const body = (await res.json()) as { user?: User } & User;
		return (body.user as User) || (body as User);
	} catch {
		return null;
	}
}

export async function logout(): Promise<void> {
	try {
		await fetch('/api/auth/logout', {
			method: 'POST',
			credentials: 'include',
		});
	} catch {
		/* ignore */
	}
	clearToken();
	if (typeof window !== 'undefined') {
		window.location.href = '/login';
	}
}
