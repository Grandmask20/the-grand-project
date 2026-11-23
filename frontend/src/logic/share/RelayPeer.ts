import type { Peer, PeerEvents, PeerState } from "./Peer";
import type { RoomInvite } from "./RoomCodes";
import { seal, sealKey, unseal } from "./Seal";
import { Assembler, toFrames } from "./Wire";

/**
 * A live link through the relay (relay/: a Cloudflare Worker), for networks where browsers can't link directly
 * (user: "no choice to go full cloudflare"). Both sides only open a WebSocket to their room on the relay, which works
 * from any network. Every message is sealed here with the room's key (Seal) before it leaves, so the relay forwards
 * text it can't read; the frames are the direct link's (Wire).
 *
 * The relay says who is in the room ("!room:<sharer>:<watchers>"): the link is open while the other side is there
 * (the sharer: one watcher at least; a watcher: the sharer). A watcher's sharer leaving ends the link.
 */

/** What the relay said is in the room. */
export interface Presence {
	sharer: boolean;
	watchers: number;
}

export interface RelayEvents extends PeerEvents {
	/** Who is in the room, each time someone comes or goes. */
	onPresence?: (p: Presence) => void;
}

/** Characters waiting in the socket above which sending pauses, and how soon it looks again. */
const HIGH = 1 << 20;
const RETRY_MS = 50;

/** The relay's address as a WebSocket one (https -> wss; http for a local `wrangler dev`). */
export const socketUrl = (relay: string, room: string, role: "share" | "watch"): string =>
	`${relay.replace(/^http/, "ws")}/room/${room}?role=${role}`;

export class RelayPeer implements Peer {
	/** The browser's (tests swap in their own). */
	static Socket: typeof WebSocket = globalThis.WebSocket;

	private ws: WebSocket | null = null;
	private key: CryptoKey | null = null;
	private role: "share" | "watch" = "watch";
	private readonly queue: string[] = [];
	private readonly asm = new Assembler();
	private next = 0;
	private state: PeerState = "connecting";
	/** Seals and opens one at a time, so messages keep their order. */
	private outgoing: Promise<void> = Promise.resolve();
	private incoming: Promise<void> = Promise.resolve();
	private timer: ReturnType<typeof setTimeout> | null = null;

	constructor(private readonly events: RelayEvents) {}

	/** Into the room as its sharer or a watcher. */
	async join(relay: string, invite: RoomInvite, role: "share" | "watch"): Promise<void> {
		this.role = role;
		this.key = await sealKey(invite.key);
		if (this.state === "closed") return; // (ended while the key was made)
		const ws = new RelayPeer.Socket(socketUrl(relay, invite.room, role));
		this.ws = ws;
		ws.onmessage = (e) => {
			if (typeof e.data === "string") this.heard(e.data);
		};
		ws.onclose = () => this.set("closed");
		ws.onerror = () => this.set("closed");
	}

	/** A message to the other side, sealed and framed (dropped while nobody is there to hear it). */
	send(msg: unknown): void {
		if (this.state !== "open" || !this.key) return;
		const key = this.key;
		const id = this.next++;
		this.outgoing = this.outgoing
			.then(async () => {
				this.queue.push(...toFrames({ c: await seal(key, JSON.stringify(msg)) }, id));
				this.pump();
			})
			.catch(() => {});
	}

	close(): void {
		if (this.timer) clearTimeout(this.timer);
		this.queue.length = 0;
		try {
			this.ws?.close(1000, "ended");
		} catch {
			// (closed already)
		}
		this.set("closed");
	}

	/** A message from the relay: who is in the room, or a frame from the other side. */
	private heard(text: string): void {
		const room = /^!room:([01]):(\d+)$/.exec(text);
		if (room) {
			const p = { sharer: room[1] === "1", watchers: Number(room[2]) };
			this.events.onPresence?.(p);
			if (this.role === "share") this.set(p.watchers > 0 ? "open" : "connecting");
			else if (p.sharer) this.set("open");
			else if (this.state === "open") this.close(); // (the sharer left)
			if (this.state === "open") this.pump();
			else this.queue.length = 0; // (nobody left to hear what waited)
			return;
		}
		const sealed = this.asm.push(text) as { c?: unknown } | undefined;
		const key = this.key;
		if (typeof sealed?.c !== "string" || !key) return;
		const c = sealed.c;
		this.incoming = this.incoming
			.then(async () => {
				const msg = JSON.parse(await unseal(key, c));
				if (this.state !== "closed") this.events.onMessage(msg);
			})
			.catch(() => {}); // (not sealed with this room's key: dropped)
	}

	private pump(): void {
		if (this.timer) clearTimeout(this.timer);
		this.timer = null;
		const ws = this.ws;
		if (!ws || ws.readyState !== RelayPeer.Socket.OPEN || this.state !== "open") return;
		while (this.queue.length && ws.bufferedAmount < HIGH) ws.send(this.queue.shift() as string);
		if (this.queue.length) this.timer = setTimeout(() => this.pump(), RETRY_MS);
	}

	private set(state: PeerState): void {
		if (this.state === state || this.state === "closed") return;
		this.state = state;
		this.events.onState(state);
	}
}
