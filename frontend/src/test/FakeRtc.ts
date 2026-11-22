/**
 * A stand-in for the browser's RTCPeerConnection (jsdom has none): an offer and an answer whose descriptions name
 * the connection, and, once the offerer takes the answer, the two data channels joined and opened. Addresses are
 * "found" at once (`slowIce`: never, the code waits for its time out).
 */
const made = new Map<string, FakeRtc>();
let n = 0;

class FakeChannel extends EventTarget {
	readyState: RTCDataChannelState = "connecting";
	bufferedAmount = 0;
	bufferedAmountLowThreshold = 0;
	other: FakeChannel | null = null;
	sent: string[] = [];
	onopen: (() => void) | null = null;
	onclose: (() => void) | null = null;
	onmessage: ((e: { data: unknown }) => void) | null = null;
	onbufferedamountlow: (() => void) | null = null;
	constructor(readonly label: string) {
		super();
	}
	send(data: string) {
		this.sent.push(data);
		const o = this.other;
		queueMicrotask(() => o?.onmessage?.({ data }));
	}
	open() {
		this.readyState = "open";
		this.onopen?.();
	}
	close() {
		if (this.readyState === "closed") return;
		this.readyState = "closed";
		this.onclose?.();
		this.other?.close();
	}
}

export class FakeRtc extends EventTarget {
	static slowIce = false;
	readonly name = `pc${++n}`;
	iceGatheringState: RTCIceGatheringState = "new";
	connectionState: RTCPeerConnectionState = "new";
	localDescription: RTCSessionDescriptionInit | null = null;
	remote: RTCSessionDescriptionInit | null = null;
	channel: FakeChannel | null = null;
	onconnectionstatechange: (() => void) | null = null;
	ondatachannel: ((e: { channel: FakeChannel }) => void) | null = null;
	constructor(readonly config: RTCConfiguration) {
		super();
		made.set(this.name, this);
	}
	createDataChannel(label: string) {
		this.channel = new FakeChannel(label);
		return this.channel;
	}
	async createOffer() {
		return { type: "offer" as RTCSdpType, sdp: `v=0 offer from ${this.name}` };
	}
	async createAnswer() {
		return { type: "answer" as RTCSdpType, sdp: `v=0 answer from ${this.name}` };
	}
	async setLocalDescription(d: RTCSessionDescriptionInit) {
		this.localDescription = d;
		if (FakeRtc.slowIce) return;
		this.iceGatheringState = "complete";
	}
	async setRemoteDescription(d: RTCSessionDescriptionInit) {
		this.remote = d;
		if (d.type !== "answer") return;
		// the offerer took the answer: the two ends joined
		const other = made.get(String(d.sdp).split(" ").pop() as string);
		if (!other || !this.channel) return;
		const theirs = new FakeChannel(this.channel.label);
		this.channel.other = theirs;
		theirs.other = this.channel;
		other.ondatachannel?.({ channel: theirs });
		queueMicrotask(() => {
			this.channel?.open();
			theirs.open();
		});
	}
	/** The connection failing (the routers let nothing through). */
	fail() {
		this.connectionState = "failed";
		this.onconnectionstatechange?.();
	}
	close() {
		this.connectionState = "closed";
		this.channel?.close();
	}
}
