import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ICE_WAIT_MS, type PeerState, SharePeer, STUN } from "@/logic/share/SharePeer";
import { FRAME } from "@/logic/share/Wire";
import { FakeRtc } from "@/test/FakeRtc";

const flush = () => new Promise((r) => setTimeout(r, 0));

function peer() {
	const got: unknown[] = [];
	const states: PeerState[] = [];
	const p = new SharePeer({ onMessage: (m) => got.push(m), onState: (s) => states.push(s) });
	return { p, got, states };
}

describe("SharePeer", () => {
	beforeEach(() => {
		SharePeer.Rtc = FakeRtc as unknown as typeof RTCPeerConnection;
		FakeRtc.slowIce = false;
	});
	afterEach(() => vi.useRealTimers());

	it("invite, reply, accept: the link opens and messages go both ways, whole however big", async () => {
		const host = peer();
		const friend = peer();
		const invite = await host.p.invite();
		expect(invite).toMatch(/^GPI1\./);
		const reply = await friend.p.answer(invite);
		expect(reply).toMatch(/^GPR1\./);
		await host.p.accept(reply);
		await flush();
		expect(host.states).toEqual(["open"]);
		expect(friend.states).toEqual(["open"]);
		const big = { t: "atlas", s: "y".repeat(FRAME * 3) };
		host.p.send(big);
		friend.p.send({ t: "hello", name: "Nyx" });
		await flush();
		expect(friend.got).toEqual([big]);
		expect(host.got).toEqual([{ t: "hello", name: "Nyx" }]);
	});

	it("asks the STUN server for its public address only", async () => {
		const host = peer();
		await host.p.invite();
		const pc = (host.p as unknown as { pc: FakeRtc }).pc;
		expect(pc.config.iceServers).toBe(STUN);
	});

	it("addresses slow to come: the code is made after ICE_WAIT_MS with those found", async () => {
		vi.useFakeTimers();
		FakeRtc.slowIce = true;
		const host = peer();
		const code = host.p.invite();
		await vi.advanceTimersByTimeAsync(ICE_WAIT_MS);
		await expect(code).resolves.toMatch(/^GPI1\./);
	});

	it("messages sent before the link opens wait for it; once closed, nothing more is sent", async () => {
		const host = peer();
		const friend = peer();
		const reply = await friend.p.answer(await host.p.invite());
		host.p.send({ early: true });
		await host.p.accept(reply);
		await flush();
		expect(friend.got).toEqual([{ early: true }]);
		host.p.close();
		expect(host.states).toEqual(["open", "closed"]);
		await flush();
		expect(friend.states).toEqual(["open", "closed"]);
		host.p.send({ late: true });
		await flush();
		expect(friend.got).toEqual([{ early: true }]);
	});

	it("a connection that fails says closed; a reply with no invite made is an error", async () => {
		const host = peer();
		await host.p.invite();
		(host.p as unknown as { pc: FakeRtc }).pc.fail();
		expect(host.states).toEqual(["closed"]);
		await expect(peer().p.accept("GPR1.zx")).rejects.toThrow("no invite");
	});
});
