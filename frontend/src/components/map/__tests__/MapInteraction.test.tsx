import { act, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MapInteraction } from "@/components/map/MapInteraction";
import { ModeBar } from "@/components/map/ModeBar";
import type { Point } from "@/logic/Geo";
import { modeCursor, modeHint } from "@/logic/ModeHint";
import { useAppStore } from "@/store/AppStore";
import { fakeMap } from "@/test/FakeMap";
import { nodeInfo } from "@/test/Fixtures";
import { geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));
// the lasso as drawn: handed to the page by the test (Terra Draw itself has its own test)
const lasso = vi.hoisted(() => ({
	drawn: null as null | ((p: Point[], at: { x: number; y: number }) => void),
	start: null as null | (() => void),
}));
vi.mock("@/components/map/draw/LassoDraw", () => ({
	LassoDraw: (p: { onDrawn: typeof lasso.drawn; onStart: typeof lasso.start }) => {
		lasso.drawn = p.onDrawn;
		lasso.start = p.onStart;
		return <div data-testid="lasso-draw" />;
	},
}));

const graph = {
	nodes: [
		{ id: 12, x: 440, y: 200, icons: [], status: "" },
		{ id: 13, x: 0, y: 0, icons: [], status: "" },
	],
	edges: [],
};
const ghost = { picture: 1, box: [0, 0, 10, 10] as [number, number, number, number], name: "g.png", path: "/g.png" };

/** A mouse event on the map at an atlas point. */
const at = (x: number, y: number, button = 0) => {
	const [lng, lat] = geo.toLngLat(x, y);
	return { lngLat: { lng, lat }, point: { x: 30, y: 40 }, originalEvent: { button }, preventDefault: vi.fn() };
};

function setup(routes: Record<string, unknown> = {}) {
	const fm = fakeMap();
	fm.map.addLayer({ id: "maps" }); // (the pointer changes over the layers the map has)
	return renderOnMap(
		<>
			<MapInteraction />
			<ModeBar />
		</>,
		{ "POST /api/pick": nodeInfo, "GET /api/graph": graph, "PATCH /api/settings": (b: unknown) => b, ...routes },
		fm,
	);
}

describe("MapInteraction", () => {
	beforeEach(() => {
		lasso.drawn = null;
	});

	it("a click selects what is there (the panel at the map's side shows it: the tab open stays)", async () => {
		const { fm, calls } = setup();
		act(() => useAppStore.getState().setTab("view"));
		act(() => fm.fire("click", at(440, 200)));
		await waitFor(() => expect(useAppStore.getState().selected?.id).toBe(12));
		expect(useAppStore.getState().tab).toBe("view");
		expect(calls.find((c) => c.path === "/api/pick")?.body).toMatchObject({
			x: expect.closeTo(440, 3),
			y: expect.closeTo(200, 3),
		});
	});

	it("adding a bookmark: on the map clicked, with its suggested name", async () => {
		const { fm } = setup();
		act(() => useAppStore.getState().setMode({ kind: "bookmark" }));
		act(() => fm.fire("click", at(400, 190)));
		await waitFor(() => expect(useAppStore.getState().bookmarkEdit).toMatchObject({ x: 440, y: 200, name: "Breach" }));
		expect(useAppStore.getState().mode.kind).toBe("normal");
	});

	it("adding a bookmark on a bookmarked map opens that bookmark", async () => {
		const marked = { ...nodeInfo, bookmark: 3, bookmark_of: { id: 3, name: "boss", group: "Boss", note: "" } };
		const { fm } = setup({ "POST /api/pick": marked });
		act(() => useAppStore.getState().setMode({ kind: "bookmark" }));
		act(() => fm.fire("click", at(440, 200)));
		await waitFor(() =>
			expect(useAppStore.getState().bookmarkEdit).toMatchObject({ id: 3, name: "boss", group: "Boss" }),
		);
	});

	it("a click answered after its mode ended is dropped", async () => {
		let answer: (v: unknown) => void = () => {};
		const { fm } = setup({ "POST /api/pick": () => new Promise((done) => (answer = done)) });
		act(() => useAppStore.getState().setMode({ kind: "bookmark" }));
		act(() => fm.fire("click", at(440, 200)));
		act(() => useAppStore.getState().setMode({ kind: "normal" })); // Esc, before the answer
		await act(async () => answer(nodeInfo));
		expect(useAppStore.getState().bookmarkEdit).toBeNull();
	});

	it("in a mode: says what a click does over the map, with its pointer", () => {
		const { fm } = setup();
		expect(screen.queryByText(modeHint({ kind: "bookmark" }))).toBeNull();
		act(() => useAppStore.getState().setMode({ kind: "bookmark" }));
		expect(screen.getByText(modeHint({ kind: "bookmark" }))).toBeInTheDocument();
		expect(fm.map.getCanvas().style.cursor).toBe(modeCursor({ kind: "bookmark" }));
		expect(fm.map.getCanvas().style.cursor).toContain("svg"); // the pin
	});

	it("adding a bookmark on empty ground: where clicked, in Other", async () => {
		const { fm } = setup({ "POST /api/pick": null });
		act(() => useAppStore.getState().setMode({ kind: "bookmark" }));
		act(() => fm.fire("click", at(50, 60)));
		await waitFor(() => expect(useAppStore.getState().bookmarkEdit).toMatchObject({ group: "Other", name: "" }));
		expect(useAppStore.getState().bookmarkEdit?.x).toBeCloseTo(50, 3);
	});

	it("setting your position: the map clicked (else the nearest)", async () => {
		const { fm, calls, queryClient } = setup({ "POST /api/pick": null });
		act(() => useAppStore.getState().setMode({ kind: "player" }));
		await waitFor(() =>
			expect(calls.some((c) => c.path === "/api/graph") && queryClient.isFetching() === 0).toBe(true),
		);
		act(() => fm.fire("click", at(5, 5)));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toMatchObject({
				ui: { player: { node: 13, x: 0, y: 0 } },
			}),
		);
	});

	it("a debug link: the second map clicked, or cancelled", async () => {
		const { fm, calls } = setup({ "POST /api/debug": { id: 1 } });
		act(() => useAppStore.getState().setMode({ kind: "debug-link", from: 3, note: "n" }));
		act(() => fm.fire("click", at(440, 200)));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/debug")?.body).toMatchObject({
				kind: "missing path",
				maps: [3, 12],
				note: "n",
			}),
		);
		act(() => useAppStore.getState().setMode({ kind: "debug-link", from: 12, note: "" }));
		act(() => fm.fire("click", at(440, 200))); // the same map: cancelled
		await waitFor(() => expect(String(useAppStore.getState().error)).toContain("link cancelled"));
	});

	it("a double-click zooms in one step; on a screenshot placed by hand, places it", async () => {
		const { fm, calls } = setup({ "POST /api/place": { ok: true } });
		act(() => fm.fire("dblclick", at(0, 0)));
		expect(fm.cam.zoom).toBe(4);
		act(() => useAppStore.getState().setMode({ kind: "ghost", ghost, centre: [7, 8] }));
		act(() => fm.fire("dblclick", at(0, 0)));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/place")?.body).toEqual({ path: "/g.png", x: 7, y: 8 }),
		);
		expect(useAppStore.getState().mode.kind).toBe("normal");
	});

	it("dragging a screenshot placed by hand moves it", () => {
		const { fm } = setup();
		act(() => useAppStore.getState().setMode({ kind: "ghost", ghost, centre: [100, 100] }));
		expect(fm.map.getCanvas().style.cursor).toBe("move");
		act(() => fm.fire("mousedown", at(0, 0)));
		act(() => fm.fire("mousemove", at(30, -20)));
		const mode = useAppStore.getState().mode;
		expect(mode.kind === "ghost" && mode.centre.map((v) => Math.round(v))).toEqual([130, 80]);
		act(() => fm.fire("mouseup", at(30, -20)));
		act(() => fm.fire("mousemove", at(60, -20)));
		const after = useAppStore.getState().mode;
		expect(after.kind === "ghost" && Math.round(after.centre[0])).toBe(130); // let go: it stays
	});

	it("keys: Enter places the screenshot, Esc cancels a mode or empties Find, 0 fits the atlas", async () => {
		const { calls } = setup({ "POST /api/place": { ok: true } });
		act(() => useAppStore.getState().setMode({ kind: "ghost", ghost, centre: [1, 2] }));
		act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" })));
		await waitFor(() => expect(calls.some((c) => c.path === "/api/place")).toBe(true));
		act(() => useAppStore.getState().setMode({ kind: "bookmark" }));
		act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
		expect(useAppStore.getState().mode.kind).toBe("normal");
		act(() => useAppStore.setState({ results: [{ x: 1, y: 1 }] as never }));
		act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
		expect(useAppStore.getState().results).toEqual([]);
		const fit = useAppStore.getState().fitAtlas;
		act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "0" })));
		expect(useAppStore.getState().fitAtlas).not.toBe(fit);
	});

	it("a right-click selects what is there and opens the map menu", async () => {
		const { fm } = setup();
		act(() => fm.fire("contextmenu", at(440, 200)));
		expect(await screen.findByRole("menuitem", { name: "Bookmark this…" })).toBeInTheDocument();
		expect(useAppStore.getState().selected?.id).toBe(12);
	});

	it("the pointer shows what can be clicked", () => {
		const { fm } = setup();
		act(() => fm.fireOn("mouseenter", "maps"));
		expect(fm.map.getCanvas().style.cursor).toBe("pointer");
		act(() => fm.fireOn("mouseleave", "maps"));
		expect(fm.map.getCanvas().style.cursor).toBe("");
	});

	it("the lasso: its maps counted, then their biome picked", async () => {
		const { calls, user } = setup({ "POST /api/lasso": { maps: 3 }, "POST /api/biome": { maps: 3 } });
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		expect(screen.getByTestId("lasso-draw")).toBeInTheDocument();
		const square: Point[] = [
			[0, 0],
			[10, 0],
			[10, 10],
		];
		await act(async () => lasso.drawn?.(square, { x: 5, y: 5 }));
		await user.click(await screen.findByRole("menuitem", { name: "Vaal city" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/biome")?.body).toEqual({ polygon: square, biome: "Vaal city" }),
		);
		expect(useAppStore.getState().mode.kind).toBe("normal");
	});

	it("a biome menu cancelled changes nothing, and says so in the log", async () => {
		const { calls, user } = setup({ "POST /api/lasso": { maps: 3 }, "POST /api/log": { ok: true } });
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		await act(async () =>
			lasso.drawn?.(
				[
					[0, 0],
					[10, 0],
					[10, 10],
				],
				{ x: 5, y: 5 },
			),
		);
		await user.click(await screen.findByRole("menuitem", { name: "Cancel" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/log")?.body).toEqual({
				lines: ["Biome select: cancelled, nothing changed"],
			}),
		);
		expect(calls.some((c) => c.path === "/api/biome")).toBe(false);
	});

	it("a lasso with no maps, or too small, ends it", async () => {
		setup({ "POST /api/lasso": { maps: 0 } });
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		await act(async () =>
			lasso.drawn?.(
				[
					[0, 0],
					[1, 0],
					[1, 1],
				],
				{ x: 0, y: 0 },
			),
		);
		expect(String(useAppStore.getState().error)).toContain("No maps inside the lasso");
		expect(useAppStore.getState().errorBrief).toBe(true); // a brief note: it closes on the next click
		expect(useAppStore.getState().mode.kind).toBe("normal");
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		await act(async () => lasso.drawn?.([[0, 0]], { x: 0, y: 0 }));
		expect(useAppStore.getState().mode.kind).toBe("normal");
	});
});
