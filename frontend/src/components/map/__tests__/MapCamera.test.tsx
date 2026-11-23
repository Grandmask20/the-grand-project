import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapCamera } from "@/components/map/MapCamera";
import { useAppStore } from "@/store/AppStore";
import { mapInfo } from "@/test/Fixtures";
import { geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("MapCamera", () => {
	it("remembers where the map is after every move", () => {
		const { fm } = renderOnMap(<MapCamera />);
		const [lng, lat] = geo.toLngLat(100, 50);
		act(() => fm.map.jumpTo({ center: [lng, lat], zoom: 5, pitch: 30, bearing: 10 }));
		const cam = useAppStore.getState().camera;
		expect(cam?.x).toBeCloseTo(100, 3);
		expect(cam?.y).toBeCloseTo(50, 3);
		expect(cam).toMatchObject({ px: geo.pxPerUnit(5), pitch: 30, bearing: 10 });
	});

	it("flies to what Find asks for, once each, and never closer than it is", () => {
		const { fm } = renderOnMap(<MapCamera />);
		act(() => useAppStore.getState().flyTo(10, 20, 0.001));
		expect(fm.map.flyTo).toHaveBeenCalledTimes(1);
		expect(fm.map.flyTo.mock.calls[0][0]).toMatchObject({ center: geo.toLngLat(10, 20), zoom: 3 });
		act(() => useAppStore.setState({ highlight: "x" })); // anything else: not again
		expect(fm.map.flyTo).toHaveBeenCalledTimes(1);
		act(() => useAppStore.getState().flyTo(0, 0, 1e6)); // closer than the map goes: its last zoom
		expect(fm.map.flyTo.mock.calls[1][0].zoom).toBe(mapInfo.maxzoom);
	});

	it("puts the spot below a box over the map's top (the Re-check's changes)", () => {
		const { fm } = renderOnMap(<MapCamera />);
		act(() => useAppStore.getState().flyTo(10, 20, 1, 300)); // (the box ends 300 px down; the map starts at 0)
		expect(fm.map.flyTo.mock.calls[0][0]).toMatchObject({ center: geo.toLngLat(10, 20), offset: [0, 150] });
		act(() => useAppStore.getState().flyTo(10, 20, 1));
		expect(fm.map.flyTo.mock.calls[1][0]).not.toHaveProperty("offset");
	});

	it("fits the atlas when asked", () => {
		const { fm } = renderOnMap(<MapCamera />);
		act(() => useAppStore.getState().requestFit());
		expect(fm.map.fitBounds).toHaveBeenCalledWith(mapInfo.bounds, { padding: 30 });
	});

	it("fits a saved route asked for while the map loaded, once it's there, and only once (CodeRabbit)", () => {
		useAppStore.getState().fitArea([0, 0, 100, 100]); // (clicked before the map was made)
		const { fm, unmount } = renderOnMap(<MapCamera />);
		expect(fm.map.fitBounds).toHaveBeenCalledTimes(1);
		expect(useAppStore.getState().fitTo).toBeNull(); // carried out
		unmount();
		const again = renderOnMap(<MapCamera />); // (the map made again: not fitted again)
		expect(again.fm.map.fitBounds).not.toHaveBeenCalled();
	});
});
