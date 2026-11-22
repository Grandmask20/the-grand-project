import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BoxSelect, mapsInBox } from "@/components/map/BoxSelect";
import { useAppStore } from "@/store/AppStore";
import { features, renderOnMap } from "@/test/RenderOnMap";
import { resetStore } from "@/test/RenderWithApp";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const graph = {
	nodes: [
		{ id: 1, x: 0, y: 0, icons: [], status: "" },
		{ id: 2, x: 0, y: 0, icons: [], status: "" },
		{ id: 3, x: 0, y: 0, icons: [], status: "" },
	],
	edges: [],
};

const mouse = (target: EventTarget, type: string, x: number, y: number, extra: MouseEventInit = {}) =>
	act(() => {
		target.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, ...extra }));
	});

describe("BoxSelect", () => {
	afterEach(resetStore);

	it("the maps whose spot is in the box, drawn either way", () => {
		const at: [number, number][] = [
			[10, 10],
			[50, 60],
			[200, 10],
		];
		expect(mapsInBox(at, [1, 2, 3], { x0: 0, y0: 0, x1: 100, y1: 100 })).toEqual([1, 2]);
		expect(mapsInBox(at, [1, 2, 3], { x0: 100, y0: 100, x1: 0, y1: 0 })).toEqual([1, 2]);
	});

	it("Shift-drag draws a box and picks the maps in it: ringed, a bar to bookmark them, Esc lets go", async () => {
		const { fm } = renderOnMap(<BoxSelect />, { "GET /api/graph": graph });
		const el = fm.map.getCanvasContainer();
		// every map at the screen's middle (500, 400): a box round it picks the three
		(fm.map as unknown as { project: () => { x: number; y: number } }).project = () => ({ x: 500, y: 400 });
		await new Promise((r) => setTimeout(r, 50)); // (the graph comes)
		mouse(el, "mousedown", 450, 350, { button: 0, shiftKey: true });
		mouse(window, "mousemove", 560, 470);
		expect(screen.getByTestId("box-select")).toBeInTheDocument();
		mouse(window, "mouseup", 560, 470);
		expect(screen.queryByTestId("box-select")).toBeNull();
		await waitFor(() => expect(useAppStore.getState().boxPicked).toHaveLength(3));
		expect(screen.getByRole("toolbar", { name: "Maps picked" })).toHaveTextContent("3 maps picked");
		expect(screen.getByRole("button", { name: "Bookmark all" })).toBeInTheDocument();
		await waitFor(() => expect(features(fm, "box-picked")).toHaveLength(3));
		act(() => {
			window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
		});
		expect(useAppStore.getState().boxPicked).toEqual([]);
	});

	it("without Shift, or barely moved (a click), nothing is picked", async () => {
		const { fm } = renderOnMap(<BoxSelect />, { "GET /api/graph": graph });
		const el = fm.map.getCanvasContainer();
		await new Promise((r) => setTimeout(r, 50));
		mouse(el, "mousedown", 450, 350, { button: 0 });
		mouse(window, "mouseup", 560, 470);
		mouse(el, "mousedown", 498, 398, { button: 0, shiftKey: true });
		mouse(window, "mouseup", 501, 401);
		expect(useAppStore.getState().boxPicked).toEqual([]);
	});

	it("its x lets the picked maps go", async () => {
		renderOnMap(<BoxSelect />, { "GET /api/graph": graph });
		act(() => useAppStore.getState().setBoxPicked([1, 2]));
		await screen.findByRole("toolbar", { name: "Maps picked" });
		act(() => screen.getByRole("button", { name: "Let the picked maps go" }).click());
		expect(useAppStore.getState().boxPicked).toEqual([]);
	});
});
