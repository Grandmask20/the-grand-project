import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AtlasLayers } from "@/components/map/layers/AtlasLayers";
import { useAppStore } from "@/store/AppStore";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("AtlasLayers", () => {
	it("draws every layer of the vector tiles, each in its slot", () => {
		const { fm } = renderOnMap(<AtlasLayers />);
		expect(fm.layerIds()).toEqual(
			expect.arrayContaining(["land", "biomes", "paths", "icons", "maps", "landmarks", "highlight", "towers"]),
		);
		for (const l of fm.layers) expect(l.before).toBe(`slot:${l.id}`);
	});

	it("follows Find's highlight and the tilt", () => {
		const { fm } = renderOnMap(<AtlasLayers />);
		act(() => useAppStore.setState({ highlight: "Breach" }));
		expect(fm.layers.find((l) => l.id === "highlight")?.spec.filter).toEqual(["in", "|Breach|", ["get", "icons"]]);
		act(() => fm.map.easeTo({ pitch: 50 }));
		expect(fm.layers.find((l) => l.id === "paths")?.layout.visibility).toBe("none"); // the 3D view's paths instead
	});
});
