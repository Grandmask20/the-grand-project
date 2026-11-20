import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { PagedTab } from "@/components/layout/PagedTab";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

const pages = (auto: boolean): [string, string, React.ReactNode][] => [
	["atlases", "Saved atlases", <p key="a">the atlases</p>],
	...(auto ? [["auto", "Auto-add", <p key="w">the waiting ones</p>] as [string, string, React.ReactNode]] : []),
];

describe("PagedTab", () => {
	afterEach(resetStore);

	it("shows its first page, and another when picked", async () => {
		render(<PagedTab tab="atlases" label="Atlases pages" pages={pages(true)} />);
		expect(screen.getByText("the atlases")).toBeInTheDocument();
		await userEvent.click(screen.getByRole("tab", { name: "Auto-add" }));
		expect(screen.getByText("the waiting ones")).toBeInTheDocument();
		expect(useAppStore.getState().pages.atlases).toBe("auto");
	});

	it("opens on the page an old tab's id asks for (the app still asks for Auto-add as 'auto')", () => {
		act(() => useAppStore.getState().setTab("auto"));
		expect(useAppStore.getState().tab).toBe("atlases");
		render(<PagedTab tab="atlases" label="Atlases pages" pages={pages(true)} />);
		expect(screen.getByText("the waiting ones")).toBeInTheDocument();
	});

	it("a single page shows no page buttons, and a page no longer offered falls back to the first", () => {
		act(() => useAppStore.getState().setPage("atlases", "auto"));
		render(<PagedTab tab="atlases" label="Atlases pages" pages={pages(false)} />);
		expect(screen.getByText("the atlases")).toBeInTheDocument();
		expect(screen.queryByRole("tab")).not.toBeInTheDocument();
	});

	it("maps every old tab to its new home", () => {
		const home = (id: string) => {
			useAppStore.getState().setTab(id);
			const s = useAppStore.getState();
			return [s.tab, s.pages[s.tab]];
		};
		expect(home("auto")).toEqual(["atlases", "auto"]);
		expect(home("route")).toEqual(["bookmarks", "route"]);
		expect(home("find")).toEqual(["find", undefined]);
	});
});
