/** API helper — sends cookies + (legacy) Bearer header on every request. */

import { getToken as _getToken } from './auth';

const API_BASE = '/api';

// Re-export getToken so existing imports `from '$lib/api'` keep working.
export const getToken = _getToken;
export { setToken, clearToken, isAuthed, me, logout } from './auth';

export function authHeaders(): Record<string, string> {
	const token = getToken();
	return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api(path: string, options: RequestInit = {}): Promise<Response> {
	const headers = { ...authHeaders(), ...((options.headers as Record<string, string>) || {}) };
	return fetch(`${API_BASE}${path}`, {
		credentials: 'include',
		...options,
		headers,
	});
}

export async function apiJson<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
	const headers = {
		'Content-Type': 'application/json',
		...authHeaders(),
		...((options.headers as Record<string, string>) || {}),
	};
	const res = await fetch(`${API_BASE}${path}`, {
		credentials: 'include',
		...options,
		headers,
	});
	if (!res.ok) throw new Error(`API error: ${res.status}`);
	return res.json();
}
