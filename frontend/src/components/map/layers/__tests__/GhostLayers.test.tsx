import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GhostLayers } from "@/components/map/layers/GhostLayers";
import { useAppStore } from "@/store/AppStore";
import { geo, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const ghost = {
	picture: 7,
	box: [-50, -30, 50, 30] as [number, number, number, number],
	name: "a.png",
	path: "/a.png",
};

describe("GhostLayers", () => {
	it("shows the screenshot placed by hand where it would go, outlined, and follows it when moved", () => {
		const { fm } = renderOnMap(<GhostLayers />);
		expect(fm.sources.has("ghost-picture")).toBe(false);
		act(() => useAppStore.getState().setMode({ kind: "ghost", ghost, centre: [100, 100] }));
		const pic = fm.sources.get("ghost-picture");
		expect(pic).toMatchObject({
			type: "image",
			url: "/api/pictures/7.png",
			coordinates: geo.corners([50, 70, 150, 130]),
		});
		expect(fm.layers.find((l) => l.id === "ghost-picture")?.before).toBe("slot:ghost-picture");
		const outline = fm.sources.get("ghost-line")?.data as GeoJSON.Feature<GeoJSON.LineString>;
		expect(outline.geometry.coordinates[0]).toEqual(geo.toLngLat(50, 70));
		act(() => useAppStore.getState().setMode({ kind: "ghost", ghost, centre: [200, 100] }));
		expect(pic?.setCoordinates).toHaveBeenLastCalledWith(geo.corners([150, 70, 250, 130])); // moved, not loaded again
		act(() => useAppStore.getState().setMode({ kind: "normal" }));
		expect(fm.sources.has("ghost-picture")).toBe(false);
	});
});
