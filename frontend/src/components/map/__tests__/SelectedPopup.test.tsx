import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { placeWindow, SelectedPopup } from "@/components/map/SelectedPopup";
import { Geo } from "@/logic/Geo";
import { useAppStore } from "@/store/AppStore";
import { fakeMap } from "@/test/FakeMap";
import { mapInfo, nodeInfo } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const setup = () => {
	const fm = fakeMap();
	const geo = new Geo(mapInfo);
	Object.defineProperty(fm.container, "clientWidth", { value: 1000 });
	Object.defineProperty(fm.container, "clientHeight", { value: 800 });
	fm.map.jumpTo({ center: geo.toLngLat(nodeInfo.x, nodeInfo.y) }); // (the selection in the middle of the view)
	return {
		fm,
		geo,
		...renderWithApp(<SelectedPopup map={fm.map as never} geo={geo} />, { "GET /api/info": nodeInfo }),
	};
};
const box = () => screen.getByRole("region", { name: "Selected" });
// where the window's point is, across the map
const pointAt = () =>
	Number.parseFloat(box().style.left) + Number.parseFloat(screen.getByTestId("selected-point").style.left);

describe("SelectedPopup", () => {
	afterEach(resetStore);

	it("nothing selected: no window", () => {
		const { container } = setup();
		expect(container).toBeEmptyDOMElement();
	});

	it("opens over the map where the selection is, and follows it as the map moves", async () => {
		const { fm, geo } = setup();
		act(() => useAppStore.getState().select(nodeInfo));
		expect(await screen.findByText("Map #12: Breach")).toBeInTheDocument();
		const p = fm.map.project(geo.toLngLat(nodeInfo.x, nodeInfo.y));
		expect(pointAt()).toBeCloseTo(p.x);
		act(() => fm.map.panBy([100, 0]));
		const q = fm.map.project(geo.toLngLat(nodeInfo.x, nodeInfo.y));
		expect(q.x).not.toBe(p.x);
		expect(pointAt()).toBeCloseTo(q.x);
	});

	it("waits out of sight while its spot is off the view", () => {
		const { fm } = setup();
		act(() => useAppStore.getState().select(nodeInfo));
		act(() => fm.map.panBy([-100000, 0]));
		expect(screen.queryByRole("region", { name: "Selected" })).toBeNull();
	});

	it("its close button lets go of the selection", async () => {
		const { user } = setup();
		act(() => useAppStore.getState().select(nodeInfo));
		await user.click(screen.getByRole("button", { name: "Close" }));
		expect(useAppStore.getState().selected).toBeNull();
	});
});

describe("placeWindow", () => {
	it("above the spot when it fits, centred, its point under it", () => {
		expect(placeWindow(500, 400, 1000, 800, 400, 200)).toEqual({ left: 300, top: 184, side: "bottom", point: 200 });
	});

	it("moved in from the map's edge, its point still on the spot", () => {
		const p = placeWindow(950, 400, 1000, 800, 320, 200);
		expect(p.left + 320).toBe(992); // (8 px in from the right edge)
		expect(p.left + p.point).toBe(950);
		expect(placeWindow(2, 400, 1000, 800, 320, 200)).toMatchObject({ left: 8, point: 20 });
	});

	it("below the spot when it does not fit above", () => {
		expect(placeWindow(500, 100, 1000, 800, 400, 200)).toMatchObject({ top: 116, side: "top" });
	});

	it("too tall for above and below: beside the spot, all of it in view, never scrolling (user)", () => {
		const p = placeWindow(300, 400, 1000, 800, 400, 600);
		expect(p).toMatchObject({ left: 316, side: "left" });
		expect(p.top).toBe(100); // (centred on the spot)
		expect(p.top + p.point).toBe(400);
		expect(placeWindow(800, 100, 1000, 800, 400, 750)).toMatchObject({ left: 384, top: 8, side: "right" });
	});
});
