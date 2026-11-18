/** An error answered by the app ({"error": message}); status 0 when the app could not be reached. */
export class ApiError extends Error {
	readonly status: number;

	constructor(message: string, status: number) {
		super(message);
		this.name = "ApiError";
		this.status = status;
	}
}

/**
 * An answer (or a refused change) that belonged to the atlas open before: another atlas was opened meanwhile. Not an
 * error to show: the page drops it and draws the new atlas (the atlas owner rework: user, CodeRabbit).
 */
export class StaleError extends ApiError {
	constructor() {
		super("the atlas changed", 409);
		this.name = "StaleError";
	}
}

export const isStale = (e: unknown) => e instanceof StaleError;

/** The open atlas's generation as the page last saw it (from /api/state); null until then. */
let atlasGen: number | null = null;

/** Set the generation the page draws (useAppState, from each state it gets). */
export function setAtlasGen(gen: number | null | undefined): void {
	atlasGen = gen ?? null;
}

export const getAtlasGen = () => atlasGen;

/**
 * A check that the atlas open now is still the open one: work on the page that spans an atlas switch (an export, a
 * question asked after a load) stops on it. The same generation every answer is checked against, so there is one
 * notion of "the atlas changed" on the page.
 */
export function sameAtlas(): () => boolean {
	const gen = atlasGen;
	return () => atlasGen === gen;
}

/**
 * Calls that don't belong to one atlas: their answers are kept whichever atlas is open (switching atlas itself, the
 * state that tells the page about it, settings, the atlas list, folders, answering a question, quitting).
 */
const GEN_FREE = [
	"/api/state",
	"/api/meta",
	"/api/settings",
	"/api/quit",
	"/api/questions/",
	"/api/atlases",
	"/api/atlas/open",
	"/api/atlas/new",
	"/api/atlas/folder",
	"/api/fs",
	"/api/replay/close",
];
const genFree = (path: string) => GEN_FREE.some((p) => path === p || path.startsWith(p.endsWith("/") ? p : `${p}/`));

export interface Http {
	get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T>;
	send<T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T>;
	upload<T>(path: string, file: Blob, name: string): Promise<T>;
	url(path: string, params?: Record<string, string | number | boolean | undefined>): string;
}

/**
 * The app's HTTP calls: JSON both ways, the X-Grand header on every change (the app refuses changes without it).
 * Changes carry the atlas generation the page draws (X-Atlas-Gen): the app refuses one meant for an atlas no longer
 * open (409, stale), so a bookmark id, a lasso or a placement made in one atlas never lands in another. An answer
 * that comes back after the page learned of another atlas, or that the app gave for another atlas than the page
 * draws, is a StaleError too.
 */
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
		if (res.status === 409 && data?.stale) throw new StaleError();
		if (!res.ok) throw new ApiError(data?.error ?? `${res.status} ${res.statusText}`, res.status);
		return data as T;
	}

	async function call<T>(path: string, input: string, init: RequestInit, sent: number | null): Promise<T> {
		let res: Response;
		try {
			res = await fetcher(input, init);
		} catch {
			throw new ApiError("The app isn't running (start it again, then reload this page).", 0);
		}
		if (sent !== null && !genFree(path)) {
			const got = res.headers?.get?.("X-Atlas-Gen");
			if (atlasGen !== sent || (got != null && got !== String(sent))) {
				void res.text().catch(() => undefined);
				throw new StaleError();
			}
		}
		const data = await read<T>(res);
		// checked again once the body is in: another atlas can come into the page while it is read (CodeRabbit)
		if (sent !== null && !genFree(path) && atlasGen !== sent) throw new StaleError();
		return data;
	}

	const genHeader = (sent: number | null): Record<string, string> =>
		sent === null ? {} : { "X-Atlas-Gen": String(sent) };

	return {
		url,
		get: (path, params) => call(path, url(path, params), { method: "GET" }, atlasGen),
		send: (method, path, body) => {
			const sent = atlasGen;
			return call(
				path,
				url(path),
				{
					method,
					headers: { "Content-Type": "application/json", "X-Grand": "1", ...genHeader(sent) },
					body: body === undefined ? undefined : JSON.stringify(body),
				},
				sent,
			);
		},
		upload: (path, file, name) => {
			const sent = atlasGen;
			return call(
				path,
				url(path),
				{
					method: "POST",
					headers: {
						"Content-Type": "application/octet-stream",
						"X-Grand": "1",
						"X-Filename": encodeURIComponent(name),
						...genHeader(sent),
					},
					body: file,
				},
				sent,
			);
		},
	};
}
