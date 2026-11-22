import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BookmarkTour, TOUR_MS } from "@/components/map/BookmarkTour";
import type { Bookmarks } from "@/domain/bookmarks/Bookmarks";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const mark = (id: number, name: string, x: number) => ({
	id,
	name,
	note: "",
	x,
	y: 0,
	created: "",
	hidden: false,
	shown: true,
});
const list: Bookmarks = {
	groups: [
		{
			name: "Boss",
			hidden: false,
			items: [
				mark(1, "first", 10),
				{ ...mark(9, "a route", 0), route: { path: [1, 2] } as never }, // (no spot: left out)
				mark(2, "second", 20),
				mark(3, "third", 30),
			],
		},
	],
};
const app = { "GET /api/bookmarks": list, "GET /api/info": { ...nodeInfo, kind: "bookmark" } };
const start = () => act(() => useAppStore.getState().setTour({ group: "Boss", at: 0 }));
const key = (k: string) =>
	act(() => {
		window.dispatchEvent(new KeyboardEvent("keydown", { key: k }));
	});

describe("BookmarkTour", () => {
	afterEach(() => {
		vi.useRealTimers();
		resetStore();
	});

	it("nothing until a tour starts", () => {
		renderWithApp(<BookmarkTour />, app);
		expect(screen.queryByRole("toolbar", { name: "Bookmark tour" })).toBeNull();
	});

	it("flies to each bookmark of the group in turn and selects it (routes left out), Back and Next going round", async () => {
		const { user, calls } = renderWithApp(<BookmarkTour />, app);
		start();
		const bar = await screen.findByRole("toolbar", { name: "Bookmark tour" });
		expect(bar).toHaveTextContent("Boss 1/3 first");
		expect(useAppStore.getState().fly).toMatchObject({ x: 10, y: 0 });
		await waitFor(() => expect(calls.find((c) => c.path === "/api/info")?.params).toEqual({ kind: "bookmark", id: 1 }));
		await user.click(screen.getByRole("button", { name: "Next" }));
		expect(bar).toHaveTextContent("Boss 2/3 second");
		expect(useAppStore.getState().fly).toMatchObject({ x: 20 });
		await user.click(screen.getByRole("button", { name: "Back" }));
		await user.click(screen.getByRole("button", { name: "Back" }));
		expect(bar).toHaveTextContent("Boss 3/3 third"); // (round to the end)
	});

	it("← → step it, Esc or its x ends it", async () => {
		const { user } = renderWithApp(<BookmarkTour />, app);
		start();
		const bar = await screen.findByRole("toolbar", { name: "Bookmark tour" });
		key("ArrowRight");
		expect(bar).toHaveTextContent("2/3");
		key("ArrowLeft");
		expect(bar).toHaveTextContent("1/3");
		key("Escape");
		expect(useAppStore.getState().tour).toBeNull();
		start();
		await user.click(await screen.findByRole("button", { name: "End the tour" }));
		expect(useAppStore.getState().tour).toBeNull();
	});

	it("Play goes on by itself; Pause stops it", async () => {
		renderWithApp(<BookmarkTour />, app);
		start();
		const bar = await screen.findByRole("toolbar", { name: "Bookmark tour" });
		vi.useFakeTimers();
		act(() => screen.getByRole("button", { name: "Play" }).click());
		act(() => vi.advanceTimersByTime(TOUR_MS));
		expect(bar).toHaveTextContent("2/3");
		act(() => screen.getByRole("button", { name: "Pause" }).click());
		act(() => vi.advanceTimersByTime(TOUR_MS * 2));
		expect(bar).toHaveTextContent("2/3");
	});

	it("a group with no bookmark left: the tour ends", async () => {
		renderWithApp(<BookmarkTour />, {
			...app,
			"GET /api/bookmarks": { groups: [{ name: "Boss", hidden: false, items: [] }] },
		});
		start();
		await waitFor(() => expect(useAppStore.getState().tour).toBeNull());
	});
});
