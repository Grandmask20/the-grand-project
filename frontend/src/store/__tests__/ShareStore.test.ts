import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { relay } from "@/logic/share/RelayConfig";
import { RelayPeer } from "@/logic/share/RelayPeer";
import { SharePeer } from "@/logic/share/SharePeer";
import { resetShare, sendTo, useShareStore } from "@/store/ShareStore";
import { FakeSocket, resetRelay } from "@/test/FakeRelay";
import { FakeRtc } from "@/test/FakeRtc";
import { sharedFile, sharedName } from "@/test/ShareAtlas";

const flush = () => new Promise((r) => setTimeout(r, 0));
const s = () => useShareStore.getState();
const link = (id: number) => s().links.find((l) => l.id === id);

/** A share link and a watch link of this same page, linked to each other through their two codes. */
async function linked() {
	await s().share();
	const share = s().links[0];
	expect(share).toMatchObject({ role: "share", state: "invited" });
	const watch = await s().join(share.code);
	expect(link(watch)).toMatchObject({ role: "watch", state: "replied" });
	await s().connect(share.id, link(watch)?.code ?? "");
	await flush();
	await flush();
	return { share: share.id, watch };
}

describe("ShareStore", () => {
	beforeEach(() => {
		SharePeer.Rtc = FakeRtc as unknown as typeof RTCPeerConnection;
		FakeRtc.slowIce = false;
		localStorage.clear();
	});
	afterEach(resetShare);

	it("invite, reply, connect: both links live, each side told the other's name", async () => {
		s().setName("pl");
		const { share, watch } = await linked();
		expect(link(share)).toMatchObject({ state: "live", friend: "pl" });
		expect(link(watch)).toMatchObject({ state: "live", friend: "pl" });
	});

	it("a watch link keeps what its sharer sends: their atlas, where they are, their route", async () => {
		const { share, watch } = await linked();
		sendTo(share, { t: "atlas", name: sharedName, file: sharedFile });
		sendTo(share, { t: "pos", player: { x: 1, y: 2, node: 1 } });
		sendTo(share, { t: "route", path: [1, 2, 3] });
		await flush();
		expect(link(watch)).toMatchObject({ file: sharedFile, atlasName: sharedName, route: [1, 2, 3] });
		expect(link(watch)?.player).toEqual({ x: 1, y: 2, node: 1 });
		expect(link(share)?.file).toBeNull(); // (a share link keeps nothing of theirs)
		s().kept(watch, "/friends/pl/atlas.json");
		expect(link(watch)?.atlasPath).toBe("/friends/pl/atlas.json");
	});

	it("ending a link closes the other end", async () => {
		const { share, watch } = await linked();
		s().stop(watch);
		await flush();
		expect(link(watch)).toBeUndefined();
		expect(link(share)?.state).toBe("closed");
	});

	it("a bad invite: nothing kept, the reason thrown; a bad reply: said on its link", async () => {
		await expect(s().join("GPR1.zzz")).rejects.toThrow("That's a reply code");
		expect(s().links).toEqual([]);
		await s().share();
		const id = s().links[0].id;
		await s().connect(id, "nonsense");
		expect(link(id)).toMatchObject({ state: "invited", error: "That isn't a reply code." });
	});

	it("the name friends see is kept in this browser", () => {
		s().setName("Nyx");
		expect(localStorage.getItem("gp.share.name")).toBe("Nyx");
	});
});

describe("ShareStore through the relay (rooms)", () => {
	const settle = async () => {
		for (let i = 0; i < 8; i++) await flush();
	};
	beforeEach(() => {
		RelayPeer.Socket = FakeSocket as unknown as typeof WebSocket;
		relay.url = "https://relay.example";
		localStorage.clear();
	});
	afterEach(() => {
		resetShare();
		resetRelay();
		relay.url = "";
	});

	/** A room shared, and one friend in it (this same page plays both). */
	async function room() {
		await s().shareRoom();
		const share = s().links[0];
		expect(share).toMatchObject({ role: "share", via: "room", state: "invited" });
		expect(share.code).toMatch(/^GPS1\./);
		const watch = await s().join(share.code);
		await settle();
		return { share: share.id, watch, code: share.code };
	}

	it("one invite, nothing to paste back: both live once the friend joins, names told", async () => {
		s().setName("pl");
		const { share, watch } = await room();
		expect(link(share)).toMatchObject({ state: "live", watchers: 1, friend: "pl" });
		expect(link(watch)).toMatchObject({ state: "live", via: "room", friend: "pl" });
	});

	it("the atlas and position reach the watcher", async () => {
		const { share, watch } = await room();
		sendTo(share, { t: "atlas", name: sharedName, file: sharedFile });
		sendTo(share, { t: "pos", player: { x: 1, y: 2, node: 1 } });
		await settle();
		expect(link(watch)).toMatchObject({ file: sharedFile, player: { x: 1, y: 2, node: 1 } });
	});

	it("each friend joining counts, and bumps the share link's epoch (they get the atlas whole)", async () => {
		const { share, code } = await room();
		const epoch = link(share)?.epoch ?? 0;
		await s().join(code);
		await settle();
		expect(link(share)).toMatchObject({ watchers: 2, epoch: epoch + 1 });
	});

	it("the sharer stopping: the watcher's link closes, saying so, their atlas kept", async () => {
		const { share, watch } = await room();
		sendTo(share, { t: "atlas", name: sharedName, file: sharedFile });
		await settle();
		s().stop(share);
		await settle();
		expect(link(watch)).toMatchObject({ state: "closed", error: "They stopped sharing.", file: sharedFile });
	});

	it("the last friend leaving: the invite waits for the next", async () => {
		const { share, watch } = await room();
		s().stop(watch);
		await settle();
		expect(link(share)).toMatchObject({ state: "invited", watchers: 0 });
	});

	it("a room invite with no relay set up: said why, nothing kept", async () => {
		await s().shareRoom();
		const code = s().links[0].code;
		resetShare();
		relay.url = "";
		await expect(s().join(code)).rejects.toThrow("has none set up");
		expect(s().links).toEqual([]);
	});

	it("the relay unreachable or refusing: the link closes, saying so", async () => {
		const { code } = await room();
		const again = await s().join(code);
		await settle();
		expect(link(again)?.state).toBe("live"); // (a second friend is fine)
		FakeSocket.made.at(-1)?.drop();
		await settle();
		expect(link(again)).toMatchObject({ state: "closed", error: expect.stringContaining("relay couldn't be reached") });
	});
});
