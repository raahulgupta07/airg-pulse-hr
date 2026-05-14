/**
 * Root layout load — client-side auth guard for the SPA.
 * Static adapter ⇒ runs on the client only.
 */
import { redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { me } from '$lib/auth';
import type { LoadEvent } from '@sveltejs/kit';

export const ssr = false;
export const prerender = false;

const PUBLIC_PREFIXES = ['/login', '/register', '/careers'];

export async function load({ url }: LoadEvent) {
	if (!browser) return { user: null };

	const path = url.pathname;
	if (PUBLIC_PREFIXES.some((p) => path === p || path.startsWith(p + '/'))) {
		return { user: null };
	}

	const user = await me();
	if (!user) {
		throw redirect(307, '/login');
	}
	return { user };
}
