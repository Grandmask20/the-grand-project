import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { BookmarkAll, iconGroups, ResultRows, rowTitle } from "@/components/find/ResultRows";
import type { ResultRow } from "@/domain/find/SearchResult";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo, state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const rows = [
	{
		kind: "node",
		id: 12,
		label: "Map #12",
		x: 440,
		y: 200,
		note: "",
		icons: [
			{ name: "Breach", label: "Breach" },
			{ name: "Breach", label: "Breach" },
			{ name: "Delirium", label: "Delirium" },
		],
	},
	{ kind: "landmark", id: 3, label: "Ezomyte city", x: 10, y: 20, note: "on map #234", icon: "City", icons: [] },
	{ kind: "bookmark", id: 0, label: "farm", x: 5, y: 5, note: "Farm", icons: [] },
] as ResultRow[];

describe("ResultRows", () => {
	afterEach(resetStore);

	it("groups a map's icons with their counts", () => {
		expect(iconGroups(rows[0].icons ?? []).map((g) => [g.name, g.count])).toEqual([
			["Breach", 2],
			["Delirium", 1],
		]);
		expect(rowTitle(rows[0])).toBe("Map #12 · map icons: Breach, Delirium");
		expect(rowTitle(rows[1])).toBe("Ezomyte city · on map #234");
	});

	it("each row: the ground there, its name, where it is, its icons", () => {
		renderWithApp(<ResultRows rows={rows} />, { "GET /api/state": { ...state, generation: 3, terrain_version: 7 } });
		const first = screen.getByRole("button", { name: /Map #12/ });
		expect(first.querySelector("img")?.getAttribute("src")).toContain("/api/crop?x=440&y=200&g=3&v=7");
		expect(first.textContent).toContain("×2");
		expect(screen.getByText("on map #234")).toBeInTheDocument();
	});

	it("a picture that failed is asked for again once the map image is new (it stayed blank: CodeRabbit)", async () => {
		const { queryClient } = renderWithApp(<ResultRows rows={[rows[0]]} />, {
			"GET /api/state": { ...state, generation: 3, terrain_version: 7 },
		});
		const row = screen.getByRole("button", { name: /Map #12/ });
		const crop = () => row.querySelector('img[width="36"]');
		crop()?.dispatchEvent(new Event("error"));
		await waitFor(() => expect(crop()).toBeNull()); // the blank one meanwhile
		queryClient.setQueryData(["state"], { ...state, generation: 3, terrain_version: 8 });
		await waitFor(() => expect(crop()?.getAttribute("src")).toContain("v=8"));
	});

	it("goes to a result and selects it", async () => {
		const { user, calls } = renderWithApp(<ResultRows rows={rows} />, { "GET /api/info": nodeInfo });
		await user.click(screen.getByRole("button", { name: /Map #12/ }));
		expect(useAppStore.getState().fly).toMatchObject({ x: 440, y: 200, px: 1 });
		await waitFor(() => expect(useAppStore.getState().selected?.id).toBe(12));
		expect(calls.find((c) => c.path === "/api/info")?.params).toEqual({ kind: "node", id: 12 });
	});

	it("says when there are too many to show", () => {
		const many = Array.from({ length: 503 }, (_, i) => ({ kind: "node", id: i, label: `Map #${i}`, x: i, y: 0 }));
		renderWithApp(<ResultRows rows={many as ResultRow[]} />);
		expect(screen.getByText("3 more: narrow the search")).toBeInTheDocument();
	});

	it("Bookmark all puts all but bookmarks into a group", async () => {
		const { user, calls } = renderWithApp(<BookmarkAll rows={rows} name="breach" />, {
			"POST /api/bookmarks/all": { added: 2, skipped: 0 },
		});
		await user.click(screen.getByRole("button", { name: "Bookmark all" }));
		const prompt = useAppStore.getState().prompt;
		expect(prompt?.label).toBe("Bookmark all 2 results into group:");
		expect(prompt?.value).toBe("breach");
		prompt?.onOk("");
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/bookmarks/all")?.body).toEqual({
				items: [
					{ kind: "node", id: 12 },
					{ kind: "landmark", id: 3 },
				],
				group: "Other",
			}),
		);
	});
});
