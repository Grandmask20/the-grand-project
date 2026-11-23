import { create } from "zustand";
import type { SharedAtlas, SharedPlayer, ShareMessage } from "@/domain/share/SharedAtlas";
import { ShareCodeError } from "@/logic/share/Codes";
import type { Peer } from "@/logic/share/Peer";
import { relay, relayOn } from "@/logic/share/RelayConfig";
import { type Presence, RelayPeer } from "@/logic/share/RelayPeer";
import { isRoomCode, newRoom, parseRoom } from "@/logic/share/RoomCodes";
import { SharePeer } from "@/logic/share/SharePeer";

/**
 * Live sharing (Share dialog): the links to friends. A "share" link sends this atlas; a "watch" link shows a
 * friend's. A link goes one of two ways:
 *
 * Through the relay (a room: RelayPeer), when one is set up. One invite, any number of friends (user: "no choice to
 * go full cloudflare": direct links fail on some networks):
 *
 *   share:  room made -> "invited" (send the invite) -> a friend joins -> "live" (none left watching: "invited")
 *   watch:  the invite pasted -> "connecting" (until the sharer is there) -> "live"
 *
 * Direct, browser to browser (SharePeer): two codes pasted by hand, one friend per invite, no third party:
 *
 *   share:  invite made -> "invited" (send it) -> their reply pasted -> "connecting" -> "live"
 *   watch:  their invite pasted -> reply made -> "replied" (send it back) -> "live"
 *
 * A link that drops is "closed": a new invite starts it again.
 */

export type LinkRole = "share" | "watch";
/** Through the relay (a room), or browser to browser. */
export type LinkVia = "room" | "direct";
export type LinkState = "making" | "invited" | "replied" | "connecting" | "live" | "closed";

export interface Link {
	id: number;
	role: LinkRole;
	via: LinkVia;
	state: LinkState;
	/** The code to send the friend (an invite or a reply). */
	code: string;
	/** Their name, once they said it. */
	friend: string;
	/** A watch link: their atlas and where they are, as last sent. */
	atlas: SharedAtlas | null;
	player: SharedPlayer | null;
	/** When their atlas or position last came (ms). */
	updated: number;
	/** A room's share link: how many friends watch now. */
	watchers: number;
	/** Bumped each time a friend joins a room's share link: they are sent the atlas whole (useShareHost). */
	epoch: number;
	error: string;
}

export interface ShareStoreState {
	/** The name friends see (kept in this browser). */
	name: string;
	setName: (name: string) => void;
	open: boolean;
	setOpen: (open: boolean) => void;
	links: Link[];
	/** The watch link whose atlas is open over the map (null: none). */
	viewing: number | null;
	view: (id: number | null) => void;
	/** Share this atlas through the relay: a new room and its invite (relayOn only). */
	shareRoom: () => Promise<void>;
	/** Share this atlas browser to browser: a new direct invite. */
	share: () => Promise<void>;
	/** A share link: the friend's reply pasted. */
	connect: (id: number, reply: string) => Promise<void>;
	/** Watch a friend's atlas: their invite pasted (a room's, or a direct one: its reply made). */
	join: (invite: string) => Promise<number>;
	/** A link ended (and forgotten). */
	stop: (id: number) => void;
}

const NAME_KEY = "gp.share.name";
const readName = () => {
	try {
		return localStorage.getItem(NAME_KEY) ?? "";
	} catch {
		return "";
	}
};

/** The links' peers (not in the store: no React state). */
const peers = new Map<number, Peer>();
let ids = 0;

/** A message to one link (a share link's atlas and position: useShareHost). */
export function sendTo(id: number, msg: ShareMessage): void {
	peers.get(id)?.send(msg);
}

const blank = (id: number, role: LinkRole, via: LinkVia): Link => ({
	id,
	role,
	via,
	state: "making",
	code: "",
	friend: "",
	atlas: null,
	player: null,
	updated: 0,
	watchers: 0,
	epoch: 0,
	error: "",
});

const why = (e: unknown) => (e instanceof ShareCodeError ? e.message : "The link couldn't be made in this browser.");
const RELAY_GONE = "The relay couldn't be reached, or dropped the link: make a new invite.";

export const useShareStore = create<ShareStoreState>()((set, get) => {
	const patch = (id: number, p: Partial<Link>) =>
		set((s) => ({ links: s.links.map((l) => (l.id === id ? { ...l, ...p } : l)) }));
	const add = (l: Link) => set((s) => ({ links: [...s.links, l] }));
	const say = (id: number) => peers.get(id)?.send({ t: "hello", name: get().name || "A friend" } as ShareMessage);

	// what the other side sends: a share link hears their name only; a watch link their atlas and position too
	const heard = (id: number) => (msg: unknown) => {
		const m = msg as ShareMessage;
		if (m?.t === "hello" && typeof m.name === "string") patch(id, { friend: m.name.slice(0, 40) });
		const link = get().links.find((l) => l.id === id);
		if (link?.role !== "watch") return;
		if (m?.t === "atlas" && m.atlas) patch(id, { atlas: m.atlas, updated: Date.now() });
		if (m?.t === "pos") patch(id, { player: m.player ?? null, updated: Date.now() });
	};
	const peerFor = (id: number) => {
		const p = new SharePeer({
			onMessage: heard(id),
			onState: (st) => {
				if (st === "open") {
					patch(id, { state: "live", error: "" });
					say(id);
				} else if (st === "closed") patch(id, { state: "closed" });
			},
		});
		peers.set(id, p);
		return p;
	};

	/** A room's peer: its link follows who is in the room. */
	const roomPeer = (id: number, role: LinkRole) => {
		const link = () => get().links.find((l) => l.id === id);
		const p = new RelayPeer({
			onMessage: heard(id),
			onState: (st) => {
				if (st === "open") {
					patch(id, { state: "live", error: "" });
					say(id);
				} else if (st === "connecting") patch(id, { state: role === "share" ? "invited" : "connecting" });
				else patch(id, { state: "closed", error: link()?.error || RELAY_GONE }); // (the relay refused or dropped)
			},
			onPresence: (pr: Presence) => {
				const was = link();
				if (!was) return;
				if (role === "watch") {
					// (the link closes right after: said why)
					if (!pr.sharer && was.state === "live") patch(id, { error: "They stopped sharing." });
					return;
				}
				const joined = pr.watchers > was.watchers;
				patch(id, { watchers: pr.watchers, epoch: was.epoch + (joined ? 1 : 0) });
				if (joined && was.state === "live") say(id); // (the newcomer is told the sharer's name)
			},
		});
		peers.set(id, p);
		return p;
	};

	return {
		name: readName(),
		setName: (name) => {
			try {
				localStorage.setItem(NAME_KEY, name);
			} catch {
				// (a browser that keeps nothing: the name lasts this visit)
			}
			set({ name });
		},
		open: false,
		setOpen: (open) => set({ open }),
		links: [],
		viewing: null,
		view: (viewing) => set({ viewing }),
		shareRoom: async () => {
			const id = ++ids;
			const invite = newRoom();
			add({ ...blank(id, "share", "room"), state: "invited", code: invite.code });
			try {
				await roomPeer(id, "share").join(relay.url, invite, "share");
			} catch (e) {
				patch(id, { state: "closed", error: why(e) });
			}
		},
		share: async () => {
			const id = ++ids;
			add(blank(id, "share", "direct"));
			try {
				const code = await peerFor(id).invite();
				patch(id, { state: "invited", code });
			} catch (e) {
				patch(id, { state: "closed", error: why(e) });
			}
		},
		connect: async (id, reply) => {
			const p = peers.get(id);
			if (!(p instanceof SharePeer)) return;
			try {
				await p.accept(reply);
				if (get().links.find((l) => l.id === id)?.state === "invited") patch(id, { state: "connecting", error: "" });
			} catch (e) {
				patch(id, { error: why(e) });
			}
		},
		join: async (invite) => {
			const id = ++ids;
			if (isRoomCode(invite)) {
				const room = parseRoom(invite); // (throws why, before any link is made)
				if (!relayOn())
					throw new ShareCodeError("That invite goes through the relay, and this copy of the app has none set up.");
				add({ ...blank(id, "watch", "room"), state: "connecting" });
				try {
					await roomPeer(id, "watch").join(relay.url, room, "watch");
				} catch (e) {
					patch(id, { state: "closed", error: why(e) });
				}
				return id;
			}
			add(blank(id, "watch", "direct"));
			try {
				const code = await peerFor(id).answer(invite);
				// (the link may have opened already while the reply was made: stays live)
				if (get().links.find((l) => l.id === id)?.state === "making") patch(id, { state: "replied", code });
				else patch(id, { code });
			} catch (e) {
				peers.get(id)?.close();
				peers.delete(id);
				set((s) => ({ links: s.links.filter((l) => l.id !== id) }));
				throw new ShareCodeError(why(e));
			}
			return id;
		},
		stop: (id) => {
			peers.get(id)?.close();
			peers.delete(id);
			set((s) => ({ links: s.links.filter((l) => l.id !== id), viewing: s.viewing === id ? null : s.viewing }));
		},
	};
});

/** Every link ended (tests; a page closing ends them anyway). */
export function resetShare(): void {
	for (const p of peers.values()) p.close();
	peers.clear();
	useShareStore.setState({ links: [], viewing: null, open: false });
}
