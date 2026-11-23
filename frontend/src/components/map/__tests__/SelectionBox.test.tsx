import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { boxPlace, deleteMapText, SelectionBox } from "@/components/map/SelectionBox";
import { useAppStore } from "@/store/AppStore";
import { fakeMap } from "@/test/FakeMap";
import { nodeInfo } from "@/test/Fixtures";
import { geo, renderOnMap } from "@/test/RenderOnMap";
import { resetStore } from "@/test/RenderWithApp";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const map = {
	...nodeInfo,
	heading: "Map #12",
	icons: [
		{ name: "Breach", label: "Breach" },
		{ name: "Breach", label: "Breach" },
		{ name: "Delirium", label: "Delirium" },
	],
	connected: [11, 13],
	links: [
		[
			[440, 200],
			[400, 180],
		],
	] as [number, number][][],
};

const graph = {
	nodes: [
		{ id: 12, x: 440, y: 200, icons: [], status: "confirmed" },
		{ id: 13, x: 500, y: 200, icons: [], status: "confirmed" },
	],
	edges: [{ a: 12, b: 13 }],
};
const on = (more: Record<string, unknown>) => ({ "GET /api/graph": graph, ...more });

describe("SelectionBox", () => {
	let fm: ReturnType<typeof fakeMap>;
	beforeEach(() => {
		fm = fakeMap();
		// a map of the fake's screen size, centred on map #12 (off the view, the box hides)
		const box = fm.map.getContainer();
		Object.defineProperty(box, "clientWidth", { value: 1000 });
		Object.defineProperty(box, "clientHeight", { value: 800 });
		const [lng, lat] = geo.toLngLat(440, 200);
		fm.map.jumpTo({ center: { lng, lat } } as never);
		useAppStore.getState().setMap(fm.map as never);
	});
	afterEach(resetStore);

	it("shows nothing while nothing is selected", () => {
		renderOnMap(<SelectionBox />, {}, fm);
		expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
	});

	it("a map: its heading, its icons grouped, and its details folded away", async () => {
		const { user } = renderOnMap(<SelectionBox />, on({ "GET /api/info": map }), fm);
		act(() => useAppStore.getState().select(map));
		expect(await screen.findByRole("dialog", { name: "Selected: Map #12" })).toBeInTheDocument();
		expect(screen.getByText("×2")).toBeInTheDocument(); // two Breach icons
		expect(screen.queryByText("How it was found")).not.toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Details" }));
		expect(screen.getByText("How it was found")).toBeInTheDocument();
		expect(screen.getByText("found in 2 of 2 screenshot(s) that show it")).toBeInTheDocument();
		expect(screen.getByText(/Connected to/).textContent).toBe("Connected to map #11 and map #13");
	});

	it("Bookmark, Route here and Screenshots act on it; Delete deletes a plain map after asking (user)", async () => {
		const { user, calls } = renderOnMap(
			<SelectionBox />,
			on({ "GET /api/info": map, "POST /api/map-edit": { ok: true } }),
			fm,
		);
		act(() => useAppStore.getState().select(map));
		await user.click(await screen.findByRole("button", { name: "Bookmark" }));
		expect(useAppStore.getState().bookmarkEdit).toMatchObject({ id: null, x: 440, y: 200, name: "Breach" });
		await user.click(screen.getByRole("button", { name: "Screenshots" }));
		expect(useAppStore.getState().sources).toEqual([440, 200]);
		await user.click(screen.getByRole("button", { name: "Delete" }));
		expect(useAppStore.getState().confirm?.text).toMatch(/^Delete map #12\?/);
		act(() => useAppStore.getState().confirm?.onYes());
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/map-edit")?.body).toEqual({ x: 440, y: 200, op: "remove", kind: "" }),
		);
		await waitFor(() => expect(useAppStore.getState().selected).toBeNull()); // (it's gone)
	});

	it("a bookmarked map edits its bookmark (with its look) and Delete removes it", async () => {
		const marked = {
			...map,
			bookmark: 0,
			bookmark_of: { id: 0, name: "big boss", group: "Boss", note: "daily", colour: "#ff0000", icon: "" },
		};
		const { user, calls } = renderOnMap(
			<SelectionBox />,
			on({ "GET /api/info": marked, "POST /api/bookmarks/delete": { ok: true } }),
			fm,
		);
		act(() => useAppStore.getState().select(marked));
		await user.click(await screen.findByRole("button", { name: "Edit bookmark" }));
		expect(useAppStore.getState().bookmarkEdit).toEqual({
			id: 0,
			x: 440,
			y: 200,
			name: "big boss",
			group: "Boss",
			note: "daily",
			colour: "#ff0000",
			icon: "",
		});
		// two things to delete: the bookmark or the map, from its list
		await user.click(screen.getByRole("button", { name: "Delete" }));
		await user.click(await screen.findByRole("menuitem", { name: "Remove bookmark" }));
		expect(useAppStore.getState().confirm?.text).toBe('Remove the bookmark "big boss"?');
		act(() => useAppStore.getState().confirm?.onYes());
		await waitFor(() => expect(calls.some((c) => c.path === "/api/bookmarks/delete")).toBe(true));
		expect(useAppStore.getState().selected?.id).toBe(12); // the map stays selected
	});

	it("a connected map named in it is selected and gone to", async () => {
		const { user, calls } = renderOnMap(<SelectionBox />, on({ "GET /api/info": map }), fm);
		act(() => useAppStore.getState().select(map));
		await user.click(await screen.findByRole("button", { name: "Details" }));
		await user.click(screen.getByRole("button", { name: "map #13" }));
		await waitFor(() =>
			expect(calls.some((c) => c.path === "/api/info" && (c.params as { id: number }).id === 13)).toBe(true),
		);
	});

	it("stands over the spot, pointing at it; off the view it hides", async () => {
		renderOnMap(<SelectionBox />, on({ "GET /api/info": map }), fm);
		act(() => useAppStore.getState().select(map));
		const box = await screen.findByRole("dialog");
		expect(box.style.transform).toMatch(/^translate\(/);
		const [lng, lat] = geo.toLngLat(440 + 1e6, 200);
		act(() => fm.map.jumpTo({ center: { lng, lat } } as never));
		expect(box.style.visibility).toBe("hidden");
	});

	it("goes above the spot where it fits, else below; fitting neither, on the roomier side, cut short (app check)", () => {
		// (a map 740 px high, a box 300 px high with 26 px of padding and border; GAP 18, EDGE 8)
		expect(boxPlace(500, 740, 300, 26)).toEqual({ top: 182, cut: null }); // above
		expect(boxPlace(200, 740, 300, 26)).toEqual({ top: 218, cut: null }); // no room above: below
		// details open, 600 px: neither side has room; below has more (522 vs 174), cut to it
		expect(boxPlace(200, 740, 600, 26)).toEqual({ top: 218, cut: 488 });
		// above has more: cut to it, its top at the map's edge
		expect(boxPlace(600, 740, 700, 26)).toEqual({ top: 8, cut: 548 });
	});

	it("its x closes it", async () => {
		const { user } = renderOnMap(<SelectionBox />, on({ "GET /api/info": map }), fm);
		act(() => useAppStore.getState().select(map));
		await user.click(await screen.findByRole("button", { name: "Close" }));
		expect(useAppStore.getState().selected).toBeNull();
	});

	it("closes when its map is deleted elsewhere (the right-click menu: app check)", async () => {
		renderOnMap(<SelectionBox />, on({ "GET /api/info": { ...map, removed: true } }), fm);
		act(() => useAppStore.getState().select(map));
		await waitFor(() => expect(useAppStore.getState().selected).toBeNull());
	});

	it("deleting a map you added says it goes for good", () => {
		expect(deleteMapText({ ...map, added: true })).toBe("Delete map #12? You added it: it goes for good.");
		expect(deleteMapText(map)).toMatch(/^Delete map #12\? \(Kept in the atlas/);
	});
});
