/** An error answered by the app ({"error": message}); status 0 when the app could not be reached. */
export class ApiError extends Error {
	readonly status: number;

	constructor(message: string, status: number) {
		super(message);
		this.name = "ApiError";
		this.status = status;
	}
}

export interface Http {
	get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T>;
	send<T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T>;
	upload<T>(path: string, file: Blob, name: string): Promise<T>;
	url(path: string, params?: Record<string, string | number | boolean | undefined>): string;
}

/** The app's HTTP calls: JSON both ways, the X-Grand header on every change (the app refuses changes without it). */
export function createHttp(base = "", fetcher: typeof fetch = (...args) => fetch(...args)): Http {
	const url = (path: string, params?: Record<string, string | number | boolean | undefined>) => {
		const q = new URLSearchParams();
		for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) q.set(k, String(v));
		const s = q.toString();
		return `${base}${path}${s ? `?${s}` : ""}`;
	};

	async function read<T>(res: Response): Promise<T> {
		const text = await res.text();
		const data = text ? JSON.parse(text) : null;
		if (!res.ok) throw new ApiError(data?.error ?? `${res.status} ${res.statusText}`, res.status);
		return data as T;
	}

	async function call<T>(input: string, init: RequestInit): Promise<T> {
		let res: Response;
		try {
			res = await fetcher(input, init);
		} catch {
			throw new ApiError("The app isn't running (start it again, then reload this page).", 0);
		}
		return read<T>(res);
	}

	return {
		url,
		get: (path, params) => call(url(path, params), { method: "GET" }),
		send: (method, path, body) =>
			call(url(path), {
				method,
				headers: { "Content-Type": "application/json", "X-Grand": "1" },
				body: body === undefined ? undefined : JSON.stringify(body),
			}),
		upload: (path, file, name) =>
			call(url(path), {
				method: "POST",
				headers: { "Content-Type": "application/octet-stream", "X-Grand": "1", "X-Filename": encodeURIComponent(name) },
				body: file,
			}),
	};
}
