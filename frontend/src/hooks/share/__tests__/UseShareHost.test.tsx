import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { ATLAS_GAP_MS, useShareHost } from "@/hooks/share/UseShareHost";
import { relay } from "@/logic/share/RelayConfig";
import { RelayPeer } from "@/logic/share/RelayPeer";
import { SharePeer } from "@/logic/share/SharePeer";
import { useAppStore } from "@/store/AppStore";
import { resetShare, useShareStore } from "@/store/ShareStore";
import { FakeSocket, resetRelay } from "@/test/FakeRelay";
import { FakeRtc } from "@/test/FakeRtc";
import { mapInfo, state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const flush = () => new Promise((r) => setTimeout(r, 0));
const s = () => useShareStore.getState();
const link = (id: number) => s().links.find((l) => l.id === id);

/** A share link and a watch link of this page, linked to each other. */
async function linked() {
	await s().share();
	const share = s().links[0];
	const watch = await s().join(share.code);
	await s().connect(share.id, link(watch)?.code ?? "");
	await flush();
	await flush();
	return watch;
}

function Host() {
	useShareHost();
	return null;
}

const player = { x: 5, y: 6, node: 1, atlas: state.atlas?.path ?? "" };
const opened = { ...state, map: mapInfo, settings: { ...state.settings, ui: { player } } };
const routes = (file = "zATLAS-1") => ({ "GET /api/state": opened, "GET /api/share/atlas": { file } });

describe("useShareHost", () => {
	beforeEach(() => {
		SharePeer.Rtc = FakeRtc as unknown as typeof RTCPeerConnection;
		FakeRtc.slowIce = false;
	});
	afterEach(() => {
		resetShare();
		resetStore();
	});

	it("a link live: it gets this atlas whole (packed by the app), its name, where you are and your route", async () => {
		const watch = await linked();
		useAppStore.getState().setRoute({ path: [1, 2, 4], message: "" });
		renderWithApp(<Host />, routes());
		await waitFor(() => expect(link(watch)?.file).toBe("zATLAS-1"));
		expect(link(watch)).toMatchObject({ atlasName: "default", player: { x: 5, y: 6, node: 1 }, route: [1, 2, 4] });
	});

	it("you move (I'm here), or track another route: they see it", async () => {
		const watch = await linked();
		const { queryClient } = renderWithApp(<Host />, routes());
		await waitFor(() => expect(link(watch)?.player).toEqual({ x: 5, y: 6, node: 1 }));
		const moved = { ...player, x: 100, y: 0, node: 2 };
		act(() =>
			queryClient.setQueryData(AppQueryKeys.state, {
				...opened,
				settings: { ...opened.settings, ui: { player: moved } },
			}),
		);
		act(() => useAppStore.getState().setRoute({ path: [2, 3], message: "" }));
		await waitFor(() => expect(link(watch)).toMatchObject({ player: { x: 100, y: 0, node: 2 }, route: [2, 3] }));
	});

	it("a changed atlas waits out the gap since the last one (an auto-add changes it each screenshot)", async () => {
		const watch = await linked();
		const { queryClient } = renderWithApp(<Host />, routes());
		await waitFor(() => expect(link(watch)?.file).toBe("zATLAS-1"));
		vi.useFakeTimers({ shouldAdvanceTime: true });
		try {
			act(() => queryClient.setQueryData(AppQueryKeys.shareAtlas, { file: "zATLAS-2" }));
			await act(async () => {
				await vi.advanceTimersByTimeAsync(ATLAS_GAP_MS / 3);
			});
			expect(link(watch)?.file).toBe("zATLAS-1");
			await act(async () => {
				await vi.advanceTimersByTimeAsync(ATLAS_GAP_MS);
			});
			await waitFor(() => expect(link(watch)?.file).toBe("zATLAS-2"));
		} finally {
			vi.useRealTimers();
		}
	});

	it("a friend's atlas open here is never passed on", async () => {
		const watch = await linked();
		const theirs = { ...opened, atlas: { ...state.atlas, friend: "Nyx" } };
		const { calls } = renderWithApp(<Host />, { ...routes(), "GET /api/state": theirs });
		await act(flush);
		expect(calls.some((c) => c.path === "/api/share/atlas")).toBe(false);
		expect(link(watch)?.file).toBeNull();
	});

	it("a room: a friend joining later gets the atlas whole too", async () => {
		RelayPeer.Socket = FakeSocket as unknown as typeof WebSocket;
		relay.url = "https://relay.example";
		try {
			await s().shareRoom();
			const code = s().links[0].code;
			const first = await s().join(code);
			renderWithApp(<Host />, routes());
			await waitFor(() => expect(link(first)?.file).toBe("zATLAS-1"));
			const later = await s().join(code);
			await waitFor(() => expect(link(later)?.file).toBe("zATLAS-1"));
			expect(link(later)?.player).toEqual({ x: 5, y: 6, node: 1 });
		} finally {
			resetRelay();
			relay.url = "";
		}
	});

	it("no link live: nothing asked of the app", async () => {
		const { calls } = renderWithApp(<Host />, routes());
		await act(flush);
		expect(calls.some((c) => c.path === "/api/share/atlas")).toBe(false);
	});
});
