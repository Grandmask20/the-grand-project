import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SharePeer } from "@/logic/share/SharePeer";
import { resetShare, sendTo, useShareStore } from "@/store/ShareStore";
import { FakeRtc } from "@/test/FakeRtc";
import { sharedAtlas } from "@/test/ShareAtlas";

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

	it("a watch link keeps what its sharer sends: their atlas, then where they are", async () => {
		const { share, watch } = await linked();
		sendTo(share, { t: "atlas", atlas: sharedAtlas });
		sendTo(share, { t: "pos", player: { x: 1, y: 2, node: 1 } });
		await flush();
		expect(link(watch)?.atlas).toEqual(sharedAtlas);
		expect(link(watch)?.player).toEqual({ x: 1, y: 2, node: 1 });
		expect(link(share)?.atlas).toBeNull(); // (a share link shows nothing of theirs)
	});

	it("ending a link closes the other end; the one open over the map is closed too", async () => {
		const { share, watch } = await linked();
		s().view(watch);
		s().stop(watch);
		await flush();
		expect(link(watch)).toBeUndefined();
		expect(s().viewing).toBeNull();
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
