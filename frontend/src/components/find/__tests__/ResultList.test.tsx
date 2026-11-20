import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultList } from "@/components/find/ResultList";
import type { ResultRow } from "@/domain/find/SearchResult";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const rows = [
	{ kind: "node", id: 12, label: "Map #12: Breach", x: 440, y: 200 },
	{ kind: "landmark", id: 3, label: "Tower (seen 2x)", x: 10, y: 20 },
	{ kind: "bookmark", id: 0, label: "[bookmark] farm (Farm)", x: 5, y: 5 },
] as ResultRow[];

describe("ResultList", () => {
	afterEach(resetStore);

	it("shows nothing before a search", () => {
		renderWithApp(<ResultList />);
		expect(screen.queryByText("Results")).not.toBeInTheDocument();
	});

	it("lists the results under their title", () => {
		useAppStore.getState().setResults(rows, "3 found for “bre”");
		renderWithApp(<ResultList />);
		expect(screen.getByText("3 found for “bre”")).toBeInTheDocument();
		expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(rows.map((r) => r.label));
	});

	it("shows only the kinds Find's pills leave on, and says how many more there are", () => {
		useAppStore.getState().setResults(rows, "3 found");
		useAppStore.getState().toggleFindKind("landmark");
		renderWithApp(<ResultList />);
		expect(screen.queryByRole("button", { name: "Tower (seen 2x)" })).toBeNull();
		expect(screen.getByText("1 more of the kinds switched off under the search")).toBeInTheDocument();
	});

	it("drops down as a list over the panel, named Results", () => {
		useAppStore.getState().setResults(rows, "found");
		renderWithApp(<ResultList />);
		expect(screen.getByRole("region", { name: "Results" })).toHaveClass("absolute");
	});

	it("↑ and ↓ move between the results", async () => {
		useAppStore.getState().setResults(rows, "found");
		const { user } = renderWithApp(<ResultList />);
		screen.getByRole("button", { name: "Map #12: Breach" }).focus();
		await user.keyboard("{ArrowDown}");
		expect(screen.getByRole("button", { name: "Tower (seen 2x)" })).toHaveFocus();
		await user.keyboard("{ArrowUp}{ArrowUp}");
		expect(screen.getByRole("button", { name: "Map #12: Breach" })).toHaveFocus();
	});

	it("goes to a result, selects it and says it was picked", async () => {
		useAppStore.getState().setResults(rows, "found");
		const picked = vi.fn();
		const { user, calls } = renderWithApp(<ResultList onPick={picked} />, { "GET /api/info": nodeInfo });
		await user.click(screen.getByRole("button", { name: "Map #12: Breach" }));
		expect(picked).toHaveBeenCalledOnce();
		expect(useAppStore.getState().fly).toMatchObject({ x: 440, y: 200, px: 1 });
		await waitFor(() => expect(useAppStore.getState().selected?.id).toBe(12));
		expect(calls.find((c) => c.path === "/api/info")?.params).toEqual({ kind: "node", id: 12 });
	});

	it("bookmarks all results but bookmarks into a group", async () => {
		useAppStore.getState().setQuery("breach");
		useAppStore.getState().setResults(rows, "found");
		const { user, calls } = renderWithApp(<ResultList />, { "POST /api/bookmarks/all": { added: 2, skipped: 0 } });
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

	it("says when there are too many to show", () => {
		const many = Array.from({ length: 503 }, (_, i) => ({
			kind: "node",
			id: i,
			label: `Map #${i}`,
			x: i,
			y: 0,
		})) as ResultRow[];
		useAppStore.getState().setResults(many, "503 found");
		renderWithApp(<ResultList />);
		expect(screen.getByText("3 more: narrow the search")).toBeInTheDocument();
	});
});
