import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AtlasLayers } from "@/components/map/layers/AtlasLayers";
import { pathShareFilter } from "@/logic/map/AtlasLayers";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("AtlasLayers", () => {
	it("draws every layer of the vector tiles, each in its slot", () => {
		const { fm } = renderOnMap(<AtlasLayers />);
		expect(fm.layerIds()).toEqual(
			expect.arrayContaining(["land", "biomes", "paths", "icons", "maps", "landmarks", "highlight"]),
		);
		for (const l of fm.layers) expect(l.before).toBe(`slot:${l.id}`);
		expect(fm.layerIds()).not.toContain("towers"); // (the tower picture went with its View switch)
	});

	it('hides the paths drawn by fewer screenshots than "drawn by at least", on the tiles it has', async () => {
		const { fm, queryClient } = renderOnMap(<AtlasLayers />);
		expect(fm.layers.find((l) => l.id === "paths")?.spec.filter).toEqual(pathShareFilter(0));
		act(() =>
			queryClient.setQueryData(["state"], {
				...state,
				settings: { ...state.settings, style: { ...state.settings.style, path_freq: 0.5 } },
			}),
		);
		await waitFor(() => expect(fm.layers.find((l) => l.id === "paths")?.spec.filter).toEqual(pathShareFilter(0.5)));
		expect(fm.sources.size).toBe(0); // no new tiles asked for: the layer's filter only
	});

	it("follows Find's highlight and the tilt", () => {
		const { fm } = renderOnMap(<AtlasLayers />);
		act(() => useAppStore.setState({ highlight: "Breach" }));
		expect(fm.layers.find((l) => l.id === "highlight")?.spec.filter).toEqual(["in", "|Breach|", ["get", "icons"]]);
		act(() => fm.map.easeTo({ pitch: 50 }));
		expect(fm.layers.find((l) => l.id === "paths")?.layout.visibility).toBe("none"); // the 3D view's paths instead
	});
});
