import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TypeList } from "@/components/find/TypeList";
import type { ResultRow } from "@/domain/find/SearchResult";
import { useAppStore } from "@/store/AppStore";
import { types } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const found = [{ kind: "node", id: 12, label: "Map #12", x: 440, y: 200, note: "", icons: [] }] as ResultRow[];

describe("TypeList", () => {
	afterEach(resetStore);

	it("lists places and icons with their counts and ticks", async () => {
		renderWithApp(<TypeList onList={vi.fn()} />, { "GET /api/types": types });
		expect(await screen.findByText("Places")).toBeInTheDocument();
		expect(screen.getByRole("checkbox", { name: "Show Breach" })).toBeChecked();
		expect(screen.getByRole("checkbox", { name: "Show Ritual" })).not.toBeChecked(); // hidden in the settings
	});

	it("ticking a type saves it as shown", async () => {
		const { user, calls } = renderWithApp(<TypeList onList={vi.fn()} />, {
			"GET /api/types": types,
			"PATCH /api/settings": (b: unknown) => ({ ...(b as object) }),
		});
		await user.click(await screen.findByRole("checkbox", { name: "Show Ritual" }));
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ hidden_types: [] }));
	});

	it("clicking a name lists that type (icons with their picture's name)", async () => {
		const onList = vi.fn();
		const { user } = renderWithApp(<TypeList onList={onList} />, { "GET /api/types": types });
		await user.click(await screen.findByRole("button", { name: /Breach/ }));
		expect(onList).toHaveBeenCalledWith("Breach", "Breach");
		await user.click(screen.getByRole("button", { name: /City/ }));
		expect(onList).toHaveBeenCalledWith("City", null);
	});

	it("a type listed opens its results within the list, under it; clicked again it folds", async () => {
		const { user } = renderWithApp(<TypeList onList={vi.fn()} />, { "GET /api/types": types });
		await screen.findByText("Places");
		act(() => {
			useAppStore.getState().listType("City", null);
			useAppStore.getState().setResults(found, "1 City");
		});
		const open = screen.getByRole("button", { name: /City/, expanded: true });
		const group = open.closest("div.flex-col") as HTMLElement;
		expect(within(group).getByRole("button", { name: /Map #12/ })).toBeInTheDocument();
		expect(within(group).getByRole("button", { name: "Bookmark all" })).toBeInTheDocument();
		await user.click(open);
		expect(useAppStore.getState().listed).toBeNull(); // folded: its rings off the map too
		expect(screen.queryByRole("button", { name: /Map #12/ })).not.toBeInTheDocument();
	});

	it("a search's results are the list's first group, with its x to clear it", async () => {
		const { user } = renderWithApp(<TypeList onList={vi.fn()} />, { "GET /api/types": types });
		await screen.findByText("Places");
		act(() => {
			useAppStore.getState().setQuery("breach");
			useAppStore.getState().setResults(found, '1 match(es) for "breach"');
		});
		expect(screen.getByText('1 match(es) for "breach"')).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /Map #12/ })).toBeInTheDocument();
		expect(screen.queryByRole("button", { expanded: true })).not.toBeInTheDocument(); // no type open meanwhile
		await user.click(screen.getByRole("button", { name: "Clear the search" }));
		expect(useAppStore.getState().query).toBe("");
	});

	it("no Bookmark all while a search is still coming (it would save the rows before under its name: CodeRabbit)", async () => {
		renderWithApp(<TypeList onList={vi.fn()} />, { "GET /api/types": types });
		await screen.findByText("Places");
		act(() => useAppStore.getState().setQuery("breach"));
		expect(screen.getByText('Finding "breach"…')).toBeInTheDocument();
		expect(screen.queryByRole("button", { name: "Bookmark all" })).not.toBeInTheDocument();
	});

	it("a type opened low in the list rises to its middle at least (user)", async () => {
		renderWithApp(<TypeList onList={vi.fn()} />, { "GET /api/types": types });
		const box = (await screen.findByText("Places")).closest(".overflow-y-auto") as HTMLElement;
		Object.defineProperty(box, "clientHeight", { value: 400 });
		const spy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
			this: HTMLElement,
		) {
			return { top: this === box ? 100 : 450 } as DOMRect; // (the opened row 350 px down a 400 px list)
		});
		act(() => {
			useAppStore.getState().listType("City", null);
			useAppStore.getState().setResults(found, "1 City");
		});
		expect(box.scrollTop).toBe(150); // its row now at the list's middle
		spy.mockRestore();
	});
});
