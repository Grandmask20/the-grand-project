import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/Http";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { useAppStore } from "@/store/AppStore";
import { bookmarks, state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("BookmarksTab", () => {
	afterEach(resetStore);

	it("lists the bookmarks by group", async () => {
		renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		expect(await screen.findByText("big boss")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Show Farm" })).toBeInTheDocument(); // a hidden group
	});

	it("hides a bookmark with its eye", async () => {
		const { user, calls } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": bookmarks,
			"POST /api/bookmarks/toggle": { ok: true },
		});
		await user.click(await screen.findByRole("button", { name: "Hide big boss" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/bookmarks/toggle")?.body).toEqual({ id: 0 }));
	});

	it("picking is Select's: the tick boxes show only then, and Done puts them away", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await screen.findByText("big boss");
		expect(screen.queryByRole("checkbox")).toBeNull();
		await user.click(screen.getByRole("button", { name: "Select" }));
		await user.click(screen.getByRole("checkbox", { name: "Pick big boss" }));
		expect(screen.getByText("1 picked")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Done" }));
		expect(screen.queryByRole("checkbox")).toBeNull();
	});

	it("deletes the picked bookmarks after asking", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(await screen.findByRole("button", { name: "Select" }));
		expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
		await user.click(await screen.findByRole("checkbox", { name: "Pick big boss" }));
		await user.click(screen.getByRole("button", { name: "Delete" }));
		expect(useAppStore.getState().confirm?.text).toBe("Delete 1 bookmark?");
	});

	it("Add bookmark waits for a click on the map", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(screen.getByRole("button", { name: "Add bookmark" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "bookmark" }); // (the line above the map says what to do)
		// pressed again, it cancels
		await user.click(screen.getByRole("button", { name: "Cancel adding" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("anything else done in the tab ends Add bookmark", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(screen.getByRole("button", { name: "Add bookmark" }));
		await user.click(await screen.findByRole("button", { name: "Delete big boss" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		expect(useAppStore.getState().confirm?.text).toBe('Delete "big boss"?');
	});

	it("leaving the tab ends Adjust route; Add bookmark stays on (a map tool of the top bar now)", () => {
		useAppStore.getState().setMode({ kind: "route-edit", id: 5 });
		useAppStore.getState().setTab("find");
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		useAppStore.getState().setMode({ kind: "bookmark" });
		useAppStore.getState().setTab("view");
		expect(useAppStore.getState().mode).toEqual({ kind: "bookmark" });
	});

	it("moves the picked bookmarks with a dropdown of the groups", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(await screen.findByRole("button", { name: "Select" }));
		await user.click(await screen.findByRole("checkbox", { name: "Pick big boss" }));
		await user.click(screen.getByRole("button", { name: "Move to…" }));
		expect(useAppStore.getState().prompt?.choices).toEqual(bookmarks.groups.map((g) => g.name));
	});

	it("a group's tick box picks all of it, and Delete takes an empty ticked group too", async () => {
		const { user, calls } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": bookmarks,
			"POST /api/bookmarks/delete": { deleted: ["big boss"] },
			"POST /api/groups/delete": { deleted: 1 },
		});
		await user.click(await screen.findByRole("button", { name: "Select" }));
		await user.click(await screen.findByRole("checkbox", { name: "Pick group Boss" }));
		expect(screen.getByRole("checkbox", { name: "Pick big boss" })).toBeChecked();
		await user.click(screen.getByRole("checkbox", { name: "Pick group Farm" })); // empty
		await user.click(screen.getByRole("button", { name: "Delete" }));
		expect(useAppStore.getState().confirm?.text).toBe("Delete 1 bookmark and 1 empty group?");
		act(() => useAppStore.getState().confirm?.onYes());
		await waitFor(() => expect(calls.find((c) => c.path === "/api/groups/delete")?.body).toEqual({ names: ["Farm"] }));
		expect(calls.find((c) => c.path === "/api/bookmarks/delete")?.body).toEqual({ ids: [0] });
	});

	it("Select all picks every bookmark, and then picks none", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(await screen.findByRole("button", { name: "Select" }));
		await user.click(await screen.findByRole("button", { name: "Select all" }));
		expect(screen.getByRole("checkbox", { name: "Pick big boss" })).toBeChecked();
		await user.click(screen.getByRole("button", { name: "Select none" }));
		expect(screen.getByRole("checkbox", { name: "Pick big boss" })).not.toBeChecked();
	});

	it("Select all counts empty groups too", async () => {
		// (with only empty groups it never turned into Select none: CodeRabbit)
		const { user } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": { groups: [{ name: "Later", hidden: false, items: [] }] },
		});
		await user.click(await screen.findByRole("button", { name: "Select" }));
		await user.click(await screen.findByRole("button", { name: "Select all" }));
		expect(screen.getByRole("checkbox", { name: "Pick group Later" })).toBeChecked();
		expect(screen.getByRole("button", { name: "Select none" })).toBeInTheDocument();
	});

	it("Fold all folds every group at once and the app keeps it (user: it was forgotten after a reload)", async () => {
		const { user, calls } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": bookmarks,
			"POST /api/groups/fold": { ok: true },
		});
		await user.click(await screen.findByRole("button", { name: "Fold all" }));
		const names = bookmarks.groups.map((g) => g.name);
		for (const n of names) expect(screen.getByRole("button", { name: `Open ${n}` })).toBeInTheDocument();
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/groups/fold")?.body).toEqual({ names, folded: true }),
		);
	});

	it("a fold the app couldn't keep is shown as the app has it again (CodeRabbit)", async () => {
		const { user, calls } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": bookmarks,
			"POST /api/groups/fold": new ApiError("the settings couldn't be saved", 500),
		});
		await user.click(await screen.findByRole("button", { name: "Fold all" }));
		await waitFor(() => expect(calls.filter((c) => c.path === "/api/bookmarks").length).toBeGreaterThan(1));
		const first = bookmarks.groups[0].name;
		expect(await screen.findByRole("button", { name: `Fold ${first}` })).toBeInTheDocument();
	});

	it("a saved route: a path symbol, its ends in the name, and a click lights it up and fits it in view", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": withRoute });
		await user.click(await screen.findByRole("button", { name: "route1 (map #252 -> map #262)" }));
		expect(screen.getByLabelText("Route")).toBeInTheDocument();
		expect(screen.getByLabelText("Routes")).toBeInTheDocument(); // on its group too (user)
		const box = useAppStore.getState().fitTo?.box ?? [];
		expect(box[0]).toBeLessThan(0);
		expect(box[3]).toBeGreaterThan(300);
		// lit up as a selected bookmark is (user)
		expect(useAppStore.getState().routeLit).toBe(5);
	});

	it("a saved route shows its ends and length, and its ⋯ opens its menu", async () => {
		const { user } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": withRoute,
			"GET /api/graph": routeGraph,
		});
		expect(await screen.findByText(/map #252 → map #262/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Route menu: route1" }));
		expect(await screen.findByRole("menuitem", { name: "Adjust route" })).toBeInTheDocument();
	});

	it("a tracked saved route shows the maps left", async () => {
		useAppStore.getState().setRoute({ path: [252, 253, 262], message: "", at: 1, saved: 5 });
		renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": withRoute });
		expect(await screen.findByText(/· 1 left/)).toBeInTheDocument();
	});

	it("a saved route's right-click menu: track it now, adjust it", async () => {
		const { user, calls } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": withRoute,
			"GET /api/graph": routeGraph,
			"PATCH /api/settings": state.settings,
		});
		const row = await screen.findByRole("button", { name: "route1 (map #252 -> map #262)" });
		fireEvent.contextMenu(row);
		await user.click(await screen.findByRole("menuitem", { name: "Adjust route" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "route-edit", id: 5 });
		expect(useAppStore.getState().routeLit).toBe(5);

		fireEvent.contextMenu(row);
		const track = await screen.findByRole("menuitem", { name: "Start tracking now" });
		await waitFor(() => expect(track).not.toHaveAttribute("data-disabled")); // (once the map's paths are in)
		await user.click(track);
		// a route saved before routes kept their maps: found again from its line's ends; tracked as this bookmark
		expect(useAppStore.getState().route).toMatchObject({ path: [252, 253, 262], at: 0, saved: 5 });
		// your position stays as it is (user: deleting a tracked route left a stray "I'm here")
		expect(calls.some((c) => c.path === "/api/settings")).toBe(false);
	});
});

// a route saved before routes kept their maps (its one line), on the atlas 252 - 253 - 262
const withRoute = {
	groups: [
		{
			name: "Routes",
			hidden: false,
			items: [
				{
					id: 5,
					name: "route1",
					note: "",
					x: 0,
					y: 0,
					created: "",
					hidden: false,
					shown: true,
					route: {
						from: 252,
						to: 262,
						maps: 2,
						line: [
							[0, 0],
							[100, 0],
							[100, 300],
						] as [number, number][],
					},
				},
			],
		},
	],
};
const routeGraph = {
	nodes: [
		{ id: 252, x: 0, y: 0, icons: [], status: "confirmed" },
		{ id: 253, x: 100, y: 0, icons: [], status: "confirmed" },
		{ id: 262, x: 100, y: 300, icons: [], status: "confirmed" },
	],
	edges: [
		{ a: 252, b: 253 },
		{ a: 253, b: 262 },
	],
};
