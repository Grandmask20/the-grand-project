import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useRevealedLayers } from "@/hooks/app/UseShownSettings";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

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
		act(() => useAppStore.getState().setMode({ kind: "normal" }));
		expect(result.current).toEqual([]);
	});

	it("shows a layer while its setting is held, not after, and never as a notice; the tab change lets go", () => {
		const { result } = renderHook(() => useRevealedLayers());
		let release = () => {};
		act(() => {
			useAppStore.getState().setTab("view");
			release = useAppStore.getState().hold("Icons");
			useAppStore.getState().hold("view:3d");
		});
		expect(result.current).toEqual(["Icons"]); // (the notice isn't a layer)
		act(() => {
			release();
			release(); // (let go twice: counted once)
		});
		expect(result.current).toEqual([]);
		act(() => {
			useAppStore.getState().hold("Paths");
			useAppStore.getState().setTab("find");
		});
		expect(result.current).toEqual([]);
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("a route found or tracked follows the Routes switch; Route while picking shows it", () => {
		const { result } = renderHook(() => useRevealedLayers());
		act(() => useAppStore.getState().setRoute({ path: [1, 2], message: "", at: 0 }));
		expect(result.current).toEqual([]);
		act(() => useAppStore.getState().setRouteDraft([3]));
		expect(result.current).toEqual(["Route"]);
	});
});
