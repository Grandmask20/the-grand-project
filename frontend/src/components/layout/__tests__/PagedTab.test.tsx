import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { PagedTab } from "@/components/layout/PagedTab";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

const pages = (debug: boolean): [string, string, React.ReactNode][] => [
	["log", "Log", <p key="l">the log</p>],
	...(debug ? [["debug", "Debug", <p key="d">the marks</p>] as [string, string, React.ReactNode]] : []),
];

describe("PagedTab", () => {
	afterEach(resetStore);

	it("shows its first page, and another when picked", async () => {
		render(<PagedTab tab="log" label="Log pages" pages={pages(true)} />);
		expect(screen.getByText("the log")).toBeInTheDocument();
		await userEvent.click(screen.getByRole("tab", { name: "Debug" }));
		expect(screen.getByText("the marks")).toBeInTheDocument();
		expect(useAppStore.getState().pages.log).toBe("debug");
	});

	it("opens on the page an old tab's id asks for (the app still asks for Auto-add as 'auto')", () => {
		act(() => useAppStore.getState().setTab("debug"));
		expect(useAppStore.getState().tab).toBe("log");
		render(<PagedTab tab="log" label="Log pages" pages={pages(true)} />);
		expect(screen.getByText("the marks")).toBeInTheDocument();
	});

	it("a single page shows no page buttons, and a page no longer offered falls back to the first", () => {
		act(() => useAppStore.getState().setPage("log", "debug"));
		render(<PagedTab tab="log" label="Log pages" pages={pages(false)} />); // (debug mode off)
		expect(screen.getByText("the log")).toBeInTheDocument();
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
		expect(home("experimental")).toEqual(["log", "experimental"]);
		expect(home("find")).toEqual(["find", undefined]);
	});
});
