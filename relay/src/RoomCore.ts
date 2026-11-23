/**
 * What a room does, apart from Cloudflare's runtime (src/index.ts wires it to a Durable Object's WebSockets): who
 * may come in, where each message goes, and telling everyone who is there.
 *
 * A room has one sharer and up to MAX_WATCHERS watchers. The sharer's messages go to every watcher; a watcher's go
 * to the sharer only. The messages are sealed by the pages (AES-GCM, the key is in the invite, never sent here):
 * the relay forwards text it can't read. Its own messages start with "!": a page's never do (they are frames,
 * "ID:I:N:..."), and one that does is dropped, so no page can pass itself off as the relay.
 */

export type Role = "share" | "watch";

/** One page in the room. */
export interface Member {
	role: Role;
	send(text: string): void;
	close(code: number, reason: string): void;
}

/** Watchers in one room at most (one sharer's friends). */
export const MAX_WATCHERS = 8;
/** The largest message forwarded (characters): the pages send 60,000-character frames, sealed a little longer. */
export const MAX_FRAME = 128 * 1024;
/** Closed for a message the relay won't forward (RFC 6455: policy violation). */
export const CLOSE_POLICY = 1008;

/** "share" or "watch", or null for anything else. */
export function roleOf(text: string | null): Role | null {
	return text === "share" || text === "watch" ? text : null;
}

/**
 * Whether one more page may come in with this role.
 *
 * @param members The pages in the room now.
 * @param role The newcomer's.
 * @returns null when it may, else why not (in words for the page's log).
 */
export function admit(members: Member[], role: Role): string | null {
	if (role === "share" && members.some((m) => m.role === "share")) return "This room already has its sharer.";
	if (role === "watch" && members.filter((m) => m.role === "watch").length >= MAX_WATCHERS)
		return `This room is full (${MAX_WATCHERS} watching).`;
	return null;
}

/**
 * A message from one page, forwarded: the sharer's to every watcher, a watcher's to the sharer.
 *
 * @param from Who sent it.
 * @param members Everyone in the room (the sender too).
 * @param data What came (only text is forwarded).
 */
export function forward(from: Member, members: Member[], data: unknown): void {
	if (typeof data !== "string" || data.length > MAX_FRAME || data.startsWith("!")) {
		from.close(CLOSE_POLICY, "not a frame the relay forwards");
		return;
	}
	const to = from.role === "share" ? "watch" : "share";
	for (const m of members) if (m.role === to) safely(() => m.send(data));
}

/**
 * Tell everyone who is in the room: "!room:<sharer there, 0 or 1>:<watchers>".
 *
 * @param members Everyone in the room now (one leaving: without it).
 */
export function announce(members: Member[]): void {
	const sharer = members.some((m) => m.role === "share") ? 1 : 0;
	const watchers = members.filter((m) => m.role === "watch").length;
	const text = `!room:${sharer}:${watchers}`;
	for (const m of members) safely(() => m.send(text));
}

/** A send to a page that is going away throws: the others still get theirs. */
function safely(fn: () => void): void {
	try {
		fn();
	} catch {
		// (it is leaving: its close tells the room)
	}
}
