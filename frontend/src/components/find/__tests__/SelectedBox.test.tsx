import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SelectedBox } from "@/components/find/SelectedBox";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo, types } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("SelectedBox", () => {
	afterEach(resetStore);

	it("nothing selected: nothing shown (the panel it is in isn't there)", () => {
		const { container } = renderWithApp(<SelectedBox />);
		expect(container).toBeEmptyDOMElement();
	});

	it("shows a map's details and bookmarks it with the suggested name", async () => {
		const { user } = renderWithApp(<SelectedBox />, { "GET /api/info": nodeInfo });
		act(() => useAppStore.getState().select(nodeInfo));
		expect(await screen.findByText("Map #12: Breach")).toBeInTheDocument();
		expect(screen.getByText("position 440, 200")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Bookmark" }));
		expect(useAppStore.getState().bookmarkEdit).toEqual({
			id: null,
			x: 440,
			y: 200,
			name: "Breach",
			group: "Breach",
			note: "",
		});
		await user.click(screen.getByRole("button", { name: "Screenshots" }));
		expect(useAppStore.getState().sources).toEqual([440, 200]);
	});

	it("lists a map's icons by their names, and routes to it", async () => {
		const graph = { nodes: [{ id: 12, x: 440, y: 200, icons: ["Breach"], status: "confirmed" }], edges: [] };
		const { user } = renderWithApp(<SelectedBox />, {
			"GET /api/info": nodeInfo,
			"GET /api/graph": graph,
			"GET /api/types": types,
		});
		act(() => useAppStore.getState().select(nodeInfo));
		expect(await screen.findByText("Map icons")).toBeInTheDocument();
		expect(await screen.findByText("Breach")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Route here" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "player" }); // (no position yet: it asks where you are)
	});

	it("Go to is under ⋯", async () => {
		const { user } = renderWithApp(<SelectedBox />, { "GET /api/info": nodeInfo });
		act(() => useAppStore.getState().select(nodeInfo));
		await user.click(await screen.findByRole("button", { name: "More" }));
		await user.click(await screen.findByRole("menuitem", { name: "Go to" }));
		expect(useAppStore.getState().fly).toMatchObject({ x: 440, y: 200 });
	});

	it("a bookmarked map edits its bookmark and can remove it (no second bookmark)", async () => {
		const marked = { ...nodeInfo, bookmark: 0, bookmark_of: { id: 0, name: "big boss", group: "Boss", note: "daily" } };
		const { user, calls } = renderWithApp(<SelectedBox />, {
			"GET /api/info": marked,
			"POST /api/bookmarks/delete": { ok: true },
		});
		act(() => useAppStore.getState().select(marked));
		await user.click(await screen.findByRole("button", { name: "★ Edit bookmark" }));
		expect(useAppStore.getState().bookmarkEdit).toEqual({
			id: 0,
			x: 440,
			y: 200,
			name: "big boss",
			group: "Boss",
			note: "daily",
		});
		await user.click(screen.getByRole("button", { name: "More" })); // (the rarer actions, under ⋯)
		await user.click(await screen.findByRole("menuitem", { name: "Remove bookmark" }));
		expect(useAppStore.getState().confirm?.text).toBe('Remove the bookmark "big boss"?');
		act(() => useAppStore.getState().confirm?.onYes());
		await waitFor(() => expect(calls.some((c) => c.path === "/api/bookmarks/delete")).toBe(true));
		// the map stays selected (user: removing its bookmark unselected it)
		expect(useAppStore.getState().selected?.id).toBe(12);
	});
});
