import { act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useFriendSync } from "@/hooks/share/UseFriendSync";
import { useAppStore } from "@/store/AppStore";
import { type Link, resetShare, useShareStore } from "@/store/ShareStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const FRIEND = "/user_data/friends/nyx/atlas.json";

function Sync() {
	useFriendSync();
	return null;
}

const watching = (p: Partial<Link>) =>
	useShareStore.setState({
		links: [
			{
				id: 3,
				role: "watch",
				via: "room",
				state: "live",
				code: "",
				friend: "Nyx",
				file: null,
				atlasName: "",
				player: null,
				route: null,
				atlasPath: "",
				updated: 0,
				watchers: 0,
				epoch: 0,
				error: "",
				...p,
			},
		],
	});
const patchLink = (p: Partial<Link>) =>
	act(() => useShareStore.setState((s) => ({ links: s.links.map((l) => ({ ...l, ...p })) })));

describe("useFriendSync", () => {
	afterEach(() => {
		resetShare();
		resetStore();
	});

	it("their atlas is kept by the app as it comes, with where they are; each new one kept again", async () => {
		watching({ file: "zA1", player: { x: 1, y: 2, node: 3 } });
		const { calls } = renderWithApp(<Sync />, { "POST /api/friends": { json: FRIEND } });
		await waitFor(() => expect(useShareStore.getState().links[0].atlasPath).toBe(FRIEND));
		expect(calls.find((c) => c.path === "/api/friends")?.body).toEqual({
			name: "Nyx",
			file: "zA1",
			player: { x: 1, y: 2, node: 3 },
		});
		patchLink({ file: "zA2" });
		await waitFor(() => expect(calls.filter((c) => c.path === "/api/friends")).toHaveLength(2));
	});

	it("they move: the app is told where they are now", async () => {
		watching({ file: "zA1", atlasPath: FRIEND });
		const { calls } = renderWithApp(<Sync />, {
			"POST /api/friends": { json: FRIEND },
			"POST /api/friends/player": { ok: true },
		});
		await waitFor(() => expect(calls.some((c) => c.path === "/api/friends")).toBe(true));
		patchLink({ player: { x: 9, y: 9, node: 7 } });
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/friends/player")?.body).toEqual({
				name: "Nyx",
				player: { x: 9, y: 9, node: 7 },
			}),
		);
	});

	it("their atlas open: their route is the one shown", async () => {
		watching({ atlasPath: FRIEND, route: [4, 5, 6] });
		const theirs = { ...state, atlas: { ...state.atlas, path: FRIEND, friend: "Nyx" } };
		const { queryClient } = renderWithApp(<Sync />, { "GET /api/state": theirs });
		await waitFor(() => expect(useAppStore.getState().route).toEqual({ path: [4, 5, 6], message: "Nyx's route" }));
		act(() => queryClient.setQueryData(AppQueryKeys.state, state));
		patchLink({ route: [7, 8] });
		await act(async () => {});
		expect(useAppStore.getState().route?.path).toEqual([4, 5, 6]); // (yours open: theirs isn't put on it)
	});
});
