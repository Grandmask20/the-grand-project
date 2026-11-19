import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { useAppStore } from "@/store/AppStore";
import { bookmarks } from "@/test/Fixtures";
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

	it("deletes the picked bookmarks after asking", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
		await user.click(await screen.findByRole("checkbox", { name: "Pick big boss" }));
		await user.click(screen.getByRole("button", { name: "Delete" }));
		expect(useAppStore.getState().confirm?.text).toBe("Delete 1 bookmark?");
	});

	it("Add bookmark waits for a click on the map", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(screen.getByRole("button", { name: "Add bookmark" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "bookmark" });
		expect(screen.getByText(/Click a map, or a spot, for the new bookmark/)).toBeInTheDocument();
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

	it("leaving the tab ends Add bookmark", () => {
		useAppStore.getState().setMode({ kind: "bookmark" });
		useAppStore.getState().setTab("find");
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("moves the picked bookmarks with a dropdown of the groups", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
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
		await user.click(await screen.findByRole("button", { name: "Select all" }));
		expect(screen.getByRole("checkbox", { name: "Pick group Later" })).toBeChecked();
		expect(screen.getByRole("button", { name: "Select none" })).toBeInTheDocument();
	});

	it("a saved route: a path symbol, its ends in the name, and a click fits it in view", async () => {
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
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": withRoute });
		await user.click(await screen.findByRole("button", { name: "route1 (map #252 -> map #262)" }));
		expect(screen.getByLabelText("Route")).toBeInTheDocument();
		expect(screen.getByLabelText("Routes")).toBeInTheDocument(); // on its group too (user)
		const box = useAppStore.getState().fitTo?.box ?? [];
		expect(box[0]).toBeLessThan(0);
		expect(box[3]).toBeGreaterThan(300);
	});
});
