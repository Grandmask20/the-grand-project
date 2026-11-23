import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ago, FriendAtlases } from "@/components/share/FriendAtlases";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const NYX = "/user_data/friends/nyx/atlas.json";
const now = Date.now() / 1000;
const friends = (open = false) => ({
	friends: [{ name: "Nyx", json: NYX, updated: now - 120, open, maps: 412 }],
	own: "/atlases/default/atlas.json",
});

describe("FriendAtlases", () => {
	afterEach(resetStore);

	it("none kept: nothing", async () => {
		renderWithApp(<FriendAtlases />, { "GET /api/friends": { friends: [], own: null } });
		await waitFor(() => expect(screen.queryByRole("region", { name: "Friends' atlases" })).toBeNull());
	});

	it("each friend's atlas: how big, how recent; a click opens it", async () => {
		const { user, calls } = renderWithApp(<FriendAtlases />, {
			"GET /api/friends": friends(),
			"POST /api/atlas/open": state.atlas,
		});
		await user.click(await screen.findByRole("button", { name: /Nyx's atlas/ }));
		expect(screen.getByText("412 maps · came 2 min ago · read-only")).toBeInTheDocument();
		await waitFor(() => expect(calls.find((c) => c.path === "/api/atlas/open")?.body).toEqual({ path: NYX }));
	});

	it("theirs open: marked, and yours a click away", async () => {
		const theirs = { ...state, atlas: { ...state.atlas, path: NYX, friend: "Nyx" } };
		renderWithApp(<FriendAtlases />, { "GET /api/friends": friends(true), "GET /api/state": theirs });
		expect(await screen.findByRole("button", { name: "Back to my atlas" })).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /Nyx's atlas/ })).toBeDisabled();
	});

	it("how long ago, in words", () => {
		expect([ago(null), ago(now - 5, now), ago(now - 300, now), ago(now - 7300, now), ago(now - 200000, now)]).toEqual([
			"",
			"just now",
			"5 min ago",
			"2 h ago",
			"2 days ago",
		]);
	});
});
