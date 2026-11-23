/** One live link to a friend, whichever way it goes: browser to browser (SharePeer) or through the relay (RelayPeer). */

/** connecting: not yet (or, a room's sharer, nobody watching now); open: messages go; closed: ended for good. */
export type PeerState = "connecting" | "open" | "closed";

export interface PeerEvents {
	onMessage: (msg: unknown) => void;
	onState: (state: PeerState) => void;
}

export interface Peer {
	/** A message to the other side (dropped once closed). */
	send(msg: unknown): void;
	/** Ended from this side. */
	close(): void;
}
