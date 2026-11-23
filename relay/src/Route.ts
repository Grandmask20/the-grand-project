/** The Worker's own checks before a request reaches a room (src/index.ts). */

/** A room's name in the address: /room/<22 URL-safe base64 characters> (16 random bytes, made by the page). */
const ROOM = /^\/room\/([A-Za-z0-9_-]{22})$/;

/**
 * The room a path asks for.
 *
 * @param path The request's path.
 * @returns The room's name, or null for any other path.
 */
export function roomOf(path: string): string | null {
	return ROOM.exec(path)?.[1] ?? null;
}

/**
 * Whether a page may come in: its origin's scheme and host are in the list (any port: the app takes the first free
 * one from 8765).
 *
 * @param origin The request's Origin header.
 * @param allowed Comma-separated "scheme://host" (wrangler.toml: ALLOWED_ORIGINS).
 * @returns True when allowed.
 */
export function originAllowed(origin: string | null, allowed: string): boolean {
	if (!origin) return false;
	let url: URL;
	try {
		url = new URL(origin);
	} catch {
		return false;
	}
	const here = `${url.protocol}//${url.hostname}`;
	return allowed
		.split(",")
		.map((a) => a.trim().replace(/\/+$/, ""))
		.some((a) => a === here);
}
