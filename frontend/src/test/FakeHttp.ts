import { ApiError, type Http } from "@/api/Http";

type Handler = unknown | ((body: unknown, params?: Record<string, unknown>) => unknown);

export interface Call {
	method: string;
	path: string;
	body?: unknown;
	params?: Record<string, unknown>;
}

/** An Http that answers from a table ("GET /api/state": value, or function giving a value or a promise of one);
 * every call is recorded. */
export function fakeHttp(routes: Record<string, Handler>) {
	const calls: Call[] = [];
	const answer = async (method: string, path: string, body?: unknown, params?: Record<string, unknown>) => {
		calls.push({ method, path, body, params });
		const key = `${method} ${path}`;
		if (!(key in routes)) throw new ApiError(`no route for ${key}`, 404);
		const h = routes[key];
		// a function may answer later (a promise): a test then decides when each answer comes
		const value = await (typeof h === "function"
			? (h as (b: unknown, p?: Record<string, unknown>) => unknown)(body, params)
			: h);
		if (value instanceof Error) throw value;
		return structuredClone(value);
	};
	const http: Http = {
		url: (path, params) => {
			const q = new URLSearchParams();
			for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) q.set(k, String(v));
			const s = q.toString();
			return `${path}${s ? `?${s}` : ""}`;
		},
		get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
			answer("GET", path, undefined, params) as Promise<T>,
		send: <T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown) =>
			answer(method, path, body) as Promise<T>,
		upload: <T>(path: string, _file: Blob, name: string) => answer("POST", path, { name }) as Promise<T>,
	};
	return { http, calls };
}
