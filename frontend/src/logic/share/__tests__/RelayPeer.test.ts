import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PeerState } from "@/logic/share/Peer";
import { type Presence, RelayPeer, socketUrl } from "@/logic/share/RelayPeer";
import { newRoom } from "@/logic/share/RoomCodes";
import { FRAME } from "@/logic/share/Wire";
import { FakeSocket, resetRelay } from "@/test/FakeRelay";

const flush = async () => {
	for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
};

/** A page's end of a room: what it heard, its states and who it was told is there. */
function end() {
	const heard: unknown[] = [];
	const states: PeerState[] = [];
	const presence: Presence[] = [];
	const peer = new RelayPeer({
		onMessage: (m) => heard.push(m),
		onState: (s) => states.push(s),
		onPresence: (p) => presence.push(p),
	});
	return { peer, heard, states, presence };
}

const RELAY = "https://relay.example";

describe("RelayPeer", () => {
	beforeEach(() => {
		RelayPeer.Socket = FakeSocket as unknown as typeof WebSocket;
	});
	afterEach(resetRelay);

	it("the relay's address: wss, the room, the role", () => {
		expect(socketUrl(RELAY, "r", "share")).toBe("wss://relay.example/room/r?role=share");
		expect(socketUrl("http://localhost:8787", "r", "watch")).toBe("ws://localhost:8787/room/r?role=watch");
	});

	it("open once the other side is in the room; messages both ways, sealed on the relay", async () => {
		const room = newRoom();
		const [s, w] = [end(), end()];
		await s.peer.join(RELAY, room, "share");
		await flush();
		expect(s.states).toEqual([]); // (nobody watching yet)
		await w.peer.join(RELAY, room, "watch");
		await flush();
		expect(s.states).toEqual(["open"]);
		expect(w.states).toEqual(["open"]);
		expect(s.presence.at(-1)).toEqual({ sharer: true, watchers: 1 });

		s.peer.send({ t: "atlas", atlas: { name: "Nyx's" } });
		w.peer.send({ t: "hello", name: "pl" });
		await flush();
		expect(w.heard).toEqual([{ t: "atlas", atlas: { name: "Nyx's" } }]);
		expect(s.heard).toEqual([{ t: "hello", name: "pl" }]);
		const relayed = FakeSocket.made.flatMap((k) => k.sent).join("");
		expect(relayed).not.toContain("Nyx");
		expect(relayed).not.toContain("hello");
	});

	it("a whole atlas: many frames, in order, put back whole", async () => {
		const room = newRoom();
		const [s, w] = [end(), end()];
		await s.peer.join(RELAY, room, "share");
		await w.peer.join(RELAY, room, "watch");
		await flush();
		const big = { t: "atlas", data: "x".repeat(FRAME * 3) };
		s.peer.send({ t: "pos", player: 1 });
		s.peer.send(big);
		s.peer.send({ t: "pos", player: 2 });
		await vi.waitFor(() => expect(w.heard).toEqual([{ t: "pos", player: 1 }, big, { t: "pos", player: 2 }]));
	});

	it("the sharer to every watcher; a watcher's message to the sharer only", async () => {
		const room = newRoom();
		const [s, a, b] = [end(), end(), end()];
		await s.peer.join(RELAY, room, "share");
		await a.peer.join(RELAY, room, "watch");
		await b.peer.join(RELAY, room, "watch");
		await flush();
		s.peer.send({ t: "pos", player: null });
		a.peer.send({ t: "hello", name: "a" });
		await flush();
		expect(a.heard).toEqual([{ t: "pos", player: null }]);
		expect(b.heard).toEqual([{ t: "pos", player: null }]);
		expect(s.heard).toEqual([{ t: "hello", name: "a" }]);
	});

	it("another room's key opens nothing", async () => {
		const room = newRoom();
		const [s, w] = [end(), end()];
		await s.peer.join(RELAY, room, "share");
		await w.peer.join(RELAY, { ...room, key: newRoom().key }, "watch");
		await flush();
		s.peer.send({ t: "hello", name: "x" });
		await flush();
		expect(w.heard).toEqual([]);
	});

	it("the sharer leaving ends a watcher's link; the last watcher leaving puts the sharer back to waiting", async () => {
		const room = newRoom();
		const [s, w] = [end(), end()];
		await s.peer.join(RELAY, room, "share");
		await w.peer.join(RELAY, room, "watch");
		await flush();
		w.peer.close();
		await flush();
		expect(s.states).toEqual(["open", "connecting"]);
		const w2 = end();
		await w2.peer.join(RELAY, room, "watch");
		await flush();
		s.peer.close();
		await flush();
		expect(w2.states).toEqual(["open", "closed"]);
	});

	it("nothing sent while nobody is there to hear it", async () => {
		const room = newRoom();
		const s = end();
		await s.peer.join(RELAY, room, "share");
		await flush();
		s.peer.send({ t: "pos", player: null });
		await flush();
		expect(FakeSocket.made[0].sent).toEqual([]);
	});

	it("a second sharer for the same room is refused", async () => {
		const room = newRoom();
		const [a, b] = [end(), end()];
		await a.peer.join(RELAY, room, "share");
		await flush();
		await b.peer.join(RELAY, room, "share");
		await flush();
		expect(b.states).toEqual(["closed"]);
	});
});
