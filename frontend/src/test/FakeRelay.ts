/**
 * The live-sharing relay for the page's tests: a WebSocket (FakeSocket, RelayPeer.Socket = FakeSocket) whose rooms
 * act as relay/src/RoomCore.ts does: one sharer, its messages to every watcher, a watcher's to the sharer, and
 * "!room:<sharer>:<watchers>" to everyone as they come and go. Everything arrives on a later microtask, as on a network.
 */

type Role = "share" | "watch";

const rooms = new Map<string, Set<FakeSocket>>();

export class FakeSocket {
	static readonly CONNECTING = 0;
	static readonly OPEN = 1;
	static readonly CLOSING = 2;
	static readonly CLOSED = 3;
	/** Every socket made (a test reaches the ones a page opened). */
	static made: FakeSocket[] = [];

	readyState = FakeSocket.CONNECTING;
	bufferedAmount = 0;
	readonly room: string;
	readonly role: Role;
	/** Every frame this page sent (as the relay got it: sealed). */
	readonly sent: string[] = [];
	onopen: (() => void) | null = null;
	onmessage: ((e: { data: unknown }) => void) | null = null;
	onclose: ((e: { code: number }) => void) | null = null;
	onerror: (() => void) | null = null;

	constructor(readonly url: string) {
		FakeSocket.made.push(this);
		const u = new URL(url);
		this.room = u.pathname.replace("/room/", "");
		this.role = u.searchParams.get("role") as Role;
		queueMicrotask(() => {
			const room = rooms.get(this.room) ?? new Set();
			if (this.role === "share" && [...room].some((s) => s.role === "share")) {
				this.readyState = FakeSocket.CLOSED;
				this.onclose?.({ code: 1006 }); // (refused: the browser sees a failed connection)
				return;
			}
			room.add(this);
			rooms.set(this.room, room);
			this.readyState = FakeSocket.OPEN;
			this.onopen?.();
			announce(room);
		});
	}

	send(text: string): void {
		if (this.readyState !== FakeSocket.OPEN) throw new Error("send on a socket not open");
		this.sent.push(text);
		const to: Role = this.role === "share" ? "watch" : "share";
		for (const s of rooms.get(this.room) ?? []) if (s.role === to) deliver(s, text);
	}

	close(): void {
		if (this.readyState === FakeSocket.CLOSED) return;
		this.readyState = FakeSocket.CLOSED;
		const room = rooms.get(this.room);
		room?.delete(this);
		queueMicrotask(() => {
			this.onclose?.({ code: 1000 });
			if (room) announce(room);
		});
	}

	/** The relay dropped this page (its network went away). */
	drop(): void {
		this.close();
	}
}

function deliver(s: FakeSocket, data: string): void {
	queueMicrotask(() => {
		if (s.readyState === FakeSocket.OPEN) s.onmessage?.({ data });
	});
}

function announce(room: Set<FakeSocket>): void {
	const sharer = [...room].some((s) => s.role === "share") ? 1 : 0;
	const watchers = [...room].filter((s) => s.role === "watch").length;
	for (const s of room) deliver(s, `!room:${sharer}:${watchers}`);
}

/** Every room emptied (after each test). */
export function resetRelay(): void {
	rooms.clear();
	FakeSocket.made = [];
}
