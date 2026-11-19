import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { layerOfStyle, useRevealedLayers } from "@/hooks/app/UseShownSettings";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

describe("layerOfStyle", () => {
	it("knows the layer each View setting shapes", () => {
		expect(layerOfStyle("icon_size")).toBe("Icons");
		expect(layerOfStyle("d3_icon_scale")).toBe("Icons");
		expect(layerOfStyle("path_width")).toBe("Paths");
		expect(layerOfStyle("d3_solid_px")).toBe("Paths");
		expect(layerOfStyle("map_style")).toBe("Nodes");
		expect(layerOfStyle("d3_beams")).toBe("3D models");
		expect(layerOfStyle("theme")).toBeNull();
	});
});

describe("useRevealedLayers", () => {
	afterEach(resetStore);

	it("shows the debug marks while the Debug page is open", () => {
		const { result } = renderHook(() => useRevealedLayers());
		expect(result.current).toEqual([]);
		act(() => {
			useAppStore.getState().setTab("log");
			useAppStore.getState().setPage("log", "debug");
		});
		expect(result.current).toEqual(["Debug marks"]);
	});

	it("shows the route in Route mode and while one is shown, the biomes in Biome select", () => {
		const { result } = renderHook(() => useRevealedLayers());
		act(() => useAppStore.getState().setMode({ kind: "route", from: null }));
		expect(result.current).toEqual(["Route"]);
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		expect(result.current).toEqual(["City & stronghold biomes"]);
		act(() => {
			useAppStore.getState().setMode({ kind: "normal" });
			useAppStore.getState().setRoute({ path: [3], message: "Route from map #3" });
		});
		expect(result.current).toEqual(["Route"]);
	});

	it("keeps a layer you restyled shown until you leave the tab", () => {
		const { result } = renderHook(() => useRevealedLayers());
		act(() => {
			useAppStore.getState().setTab("view");
			useAppStore.getState().reveal("Icons");
			useAppStore.getState().reveal("Icons");
		});
		expect(result.current).toEqual(["Icons"]);
		act(() => useAppStore.getState().setTab("find"));
		expect(result.current).toEqual([]);
	});
});
