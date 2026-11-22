import { create } from "zustand";
import type { SharedAtlas, SharedPlayer, ShareMessage } from "@/domain/share/SharedAtlas";
import { ShareCodeError } from "@/logic/share/Codes";
import { SharePeer } from "@/logic/share/SharePeer";

/**
 * Live sharing (Share dialog): the links to friends, each a SharePeer. A "share" link sends this atlas to a friend;
 * a "watch" link shows theirs. Two codes pasted by hand set one up (user: no server of our own):
 *
 *   share:  invite made -> "invited" (send it) -> their reply pasted -> "connecting" -> "live"
 *   watch:  their invite pasted -> reply made -> "replied" (send it back) -> "live"
 *
 * A link that drops is "closed": a new pair of codes starts it again.
 */

export type LinkRole = "share" | "watch";
export type LinkState = "making" | "invited" | "replied" | "connecting" | "live" | "closed";

export interface Link {
	id: number;
	role: LinkRole;
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
	/** Share this atlas: a new invite. */
	share: () => Promise<void>;
	/** A share link: the friend's reply pasted. */
	connect: (id: number, reply: string) => Promise<void>;
	/** Watch a friend's atlas: their invite pasted, the reply made. */
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
const peers = new Map<number, SharePeer>();
let ids = 0;

/** A message to one link (a share link's atlas and position: useShareHost). */
export function sendTo(id: number, msg: ShareMessage): void {
	peers.get(id)?.send(msg);
}

const blank = (id: number, role: LinkRole): Link => ({
	id,
	role,
	state: "making",
	code: "",
	friend: "",
	atlas: null,
	player: null,
	updated: 0,
	error: "",
});

const why = (e: unknown) => (e instanceof ShareCodeError ? e.message : "The link couldn't be made in this browser.");

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
		share: async () => {
			const id = ++ids;
			add(blank(id, "share"));
			try {
				const code = await peerFor(id).invite();
				patch(id, { state: "invited", code });
			} catch (e) {
				patch(id, { state: "closed", error: why(e) });
			}
		},
		connect: async (id, reply) => {
			const p = peers.get(id);
			if (!p) return;
			try {
				await p.accept(reply);
				if (get().links.find((l) => l.id === id)?.state === "invited") patch(id, { state: "connecting", error: "" });
			} catch (e) {
				patch(id, { error: why(e) });
			}
		},
		join: async (invite) => {
			const id = ++ids;
			add(blank(id, "watch"));
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
