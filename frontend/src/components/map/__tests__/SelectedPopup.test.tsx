import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SelectedPopup } from "@/components/map/SelectedPopup";
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
const box = () => screen.getByRole("region", { name: "Selected" }).parentElement as HTMLElement;

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
		expect(box().style.left).toBe(`${p.x}px`);
		act(() => fm.map.panBy([100, 0]));
		const q = fm.map.project(geo.toLngLat(nodeInfo.x, nodeInfo.y));
		expect(q.x).not.toBe(p.x);
		expect(box().style.left).toBe(`${q.x}px`);
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
