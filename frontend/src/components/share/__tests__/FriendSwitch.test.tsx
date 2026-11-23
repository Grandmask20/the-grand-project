import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FriendSwitch } from "@/components/share/FriendSwitch";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const OWN = "/atlases/default/atlas.json";
const friends = { friends: [], own: OWN };

describe("FriendSwitch", () => {
	afterEach(resetStore);

	it("your own atlas open: nothing", () => {
		renderWithApp(<FriendSwitch />, { "GET /api/friends": friends });
		expect(screen.queryByText(/read-only/)).toBeNull();
	});

	it("a friend's open: whose, read-only, and back to yours", async () => {
		const theirs = { ...state, atlas: { ...state.atlas, friend: "Nyx" } };
		const { user, calls } = renderWithApp(<FriendSwitch />, {
			"GET /api/state": theirs,
			"GET /api/friends": friends,
			"POST /api/atlas/open": state.atlas,
		});
		expect(screen.getByText("Nyx's atlas")).toBeInTheDocument();
		await user.click(await screen.findByRole("button", { name: "Back to my atlas" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/atlas/open")?.body).toEqual({ path: OWN }));
	});
});
