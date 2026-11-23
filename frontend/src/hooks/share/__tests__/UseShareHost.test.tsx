import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useShareHost } from "@/hooks/share/UseShareHost";
import { relay } from "@/logic/share/RelayConfig";
import { RelayPeer } from "@/logic/share/RelayPeer";
import { SharePeer } from "@/logic/share/SharePeer";
import { resetShare, useShareStore } from "@/store/ShareStore";
import { FakeSocket, resetRelay } from "@/test/FakeRelay";
import { FakeRtc } from "@/test/FakeRtc";
import { mapInfo, state } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";
import { sharedAtlas } from "@/test/ShareAtlas";

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

const graph = { nodes: sharedAtlas.nodes, edges: sharedAtlas.edges };
const player = { x: 5, y: 6, node: 1, atlas: state.atlas?.path ?? "" };
const opened = { ...state, map: mapInfo, settings: { ...state.settings, ui: { player } } };

describe("useShareHost", () => {
	beforeEach(() => {
		SharePeer.Rtc = FakeRtc as unknown as typeof RTCPeerConnection;
		FakeRtc.slowIce = false;
	});
	afterEach(resetShare);

	it("a link live: it gets this atlas (maps, paths, landmarks, its frame and name) and where you are", async () => {
		const watch = await linked();
		renderWithApp(<Host />, {
			"GET /api/state": opened,
			"GET /api/graph": graph,
			"GET /api/landmarks": sharedAtlas.landmarks,
		});
		await waitFor(() => expect(link(watch)?.atlas).toBeTruthy());
		expect(link(watch)?.atlas).toEqual({
			name: "default",
			info: mapInfo,
			nodes: graph.nodes,
			edges: graph.edges,
			landmarks: sharedAtlas.landmarks,
		});
		expect(link(watch)?.player).toEqual({ x: 5, y: 6, node: 1 });
	});

	it("you move (I'm here): they see it move", async () => {
		const watch = await linked();
		const { queryClient } = renderWithApp(<Host />, {
			"GET /api/state": opened,
			"GET /api/graph": graph,
			"GET /api/landmarks": sharedAtlas.landmarks,
		});
		await waitFor(() => expect(link(watch)?.player).toEqual({ x: 5, y: 6, node: 1 }));
		const moved = { ...player, x: 100, y: 0, node: 2 };
		act(() =>
			queryClient.setQueryData(AppQueryKeys.state, {
				...opened,
				settings: { ...opened.settings, ui: { player: moved } },
			}),
		);
		await waitFor(() => expect(link(watch)?.player).toEqual({ x: 100, y: 0, node: 2 }));
	});

	it("a room: a friend joining later gets the atlas whole too", async () => {
		RelayPeer.Socket = FakeSocket as unknown as typeof WebSocket;
		relay.url = "https://relay.example";
		try {
			await s().shareRoom();
			const code = s().links[0].code;
			const first = await s().join(code);
			renderWithApp(<Host />, {
				"GET /api/state": opened,
				"GET /api/graph": graph,
				"GET /api/landmarks": sharedAtlas.landmarks,
			});
			await waitFor(() => expect(link(first)?.atlas?.nodes).toEqual(graph.nodes));
			const later = await s().join(code);
			await waitFor(() => expect(link(later)?.atlas?.nodes).toEqual(graph.nodes));
			expect(link(later)?.player).toEqual({ x: 5, y: 6, node: 1 });
		} finally {
			resetShare();
			resetRelay();
			relay.url = "";
		}
	});

	it("no link live: nothing asked of the app", async () => {
		const { calls } = renderWithApp(<Host />, { "GET /api/state": opened, "GET /api/graph": graph });
		await act(flush);
		expect(calls.some((c) => c.path === "/api/graph" || c.path === "/api/landmarks")).toBe(false);
	});
});
