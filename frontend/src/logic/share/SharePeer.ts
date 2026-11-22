import { type CodeKind, packCode, unpackCode } from "./Codes";
import { Assembler, toFrames } from "./Wire";

/**
 * One live link, browser to browser (WebRTC: no server of our own, no port to open: user). The sharer makes an
 * invite, the friend answers it with a reply, the sharer takes the reply; then a data channel carries messages both
 * ways, encrypted by WebRTC. A public STUN server tells each side its address as the internet sees it (it learns the
 * addresses only, nothing that is sent).
 */

/** Asked only for each side's public address. */
export const STUN: RTCIceServer[] = [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }];
/** The longest wait for the addresses to be found before a code is made with what was found. */
export const ICE_WAIT_MS = 5000;
/** Frames waiting in the channel above which sending pauses (a whole atlas at once overflowed it). */
const HIGH = 1 << 20;
const LOW = 256 << 10;

export type PeerState = "connecting" | "open" | "closed";

export interface PeerEvents {
	onMessage: (msg: unknown) => void;
	onState: (state: PeerState) => void;
}

export class SharePeer {
	/** The browser's (tests swap in their own). */
	static Rtc: typeof RTCPeerConnection = globalThis.RTCPeerConnection;

	private pc: RTCPeerConnection | null = null;
	private ch: RTCDataChannel | null = null;
	private readonly queue: string[] = [];
	private readonly asm = new Assembler();
	private next = 0;
	private state: PeerState = "connecting";

	constructor(private readonly events: PeerEvents) {}

	/** The sharer: a new connection and its invite code. */
	async invite(): Promise<string> {
		const pc = this.make();
		this.wire(pc.createDataChannel("atlas", { ordered: true }));
		await pc.setLocalDescription(await pc.createOffer());
		return this.code(pc, "invite");
	}

	/** The friend: the sharer's invite taken, the reply code to send back. */
	async answer(invite: string): Promise<string> {
		const offer = await unpackCode("invite", invite);
		const pc = this.make();
		pc.ondatachannel = (e) => this.wire(e.channel);
		await pc.setRemoteDescription(offer);
		await pc.setLocalDescription(await pc.createAnswer());
		return this.code(pc, "reply");
	}

	/** The sharer: the friend's reply taken; the link opens by itself from here. */
	async accept(reply: string): Promise<void> {
		if (!this.pc) throw new Error("accept: no invite made");
		await this.pc.setRemoteDescription(await unpackCode("reply", reply));
	}

	/** A message to the other side, framed and sent as the channel takes it. */
	send(msg: unknown): void {
		if (this.state === "closed") return;
		this.queue.push(...toFrames(msg, this.next++));
		this.pump();
	}

	/** Ended from this side. */
	close(): void {
		this.ch?.close();
		this.pc?.close();
		this.queue.length = 0;
		this.set("closed");
	}

	private make(): RTCPeerConnection {
		const pc = new SharePeer.Rtc({ iceServers: STUN });
		pc.onconnectionstatechange = () => {
			if (pc.connectionState === "failed" || pc.connectionState === "closed") this.set("closed");
		};
		this.pc = pc;
		return pc;
	}

	private wire(ch: RTCDataChannel): void {
		this.ch = ch;
		ch.bufferedAmountLowThreshold = LOW;
		ch.onbufferedamountlow = () => this.pump();
		ch.onopen = () => {
			this.set("open");
			this.pump();
		};
		ch.onclose = () => this.set("closed");
		ch.onmessage = (e) => {
			const msg = typeof e.data === "string" ? this.asm.push(e.data) : undefined;
			if (msg !== undefined) this.events.onMessage(msg);
		};
	}

	private pump(): void {
		const ch = this.ch;
		while (ch && ch.readyState === "open" && this.queue.length && ch.bufferedAmount < HIGH) {
			ch.send(this.queue.shift() as string);
		}
	}

	private set(state: PeerState): void {
		if (this.state === state || this.state === "closed") return;
		this.state = state;
		this.events.onState(state);
	}

	/** The code once the addresses are found (or after ICE_WAIT_MS, with those found: a STUN server not answering
	 * still leaves the local ones, enough on one network). */
	private async code(pc: RTCPeerConnection, kind: CodeKind): Promise<string> {
		if (pc.iceGatheringState !== "complete")
			await new Promise<void>((done) => {
				const t = setTimeout(done, ICE_WAIT_MS);
				pc.addEventListener("icegatheringstatechange", () => {
					if (pc.iceGatheringState === "complete") {
						clearTimeout(t);
						done();
					}
				});
			});
		return packCode(kind, pc.localDescription as RTCSessionDescriptionInit);
	}
}
