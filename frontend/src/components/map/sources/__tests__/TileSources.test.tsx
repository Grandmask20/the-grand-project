import { act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TileSources } from "@/components/map/sources/TileSources";
import { PREFETCH_DELAY_MS } from "@/logic/map/Tiles";
import { useAppStore } from "@/store/AppStore";
import { mapInfo, state } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

/** The tile address a source asks for. */
const tiles = (fm: ReturnType<typeof renderOnMap>["fm"], id: string) =>
	String((fm.sources.get(id)?.tiles as string[] | undefined)?.[0]);

const withMap = (over: Record<string, unknown> = {}, settings = state.settings) => ({
	"GET /api/state": { ...state, map: { ...mapInfo, ...over }, settings },
});

describe("TileSources", () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it("points the map at the app's ground and vector tiles, at their versions", () => {
		const { fm } = renderOnMap(<TileSources />, withMap());
		const terrain = fm.sources.get("terrain");
		expect(terrain).toMatchObject({ type: "raster", maxzoom: mapInfo.zdeep, bounds: [-90, -40, 0, 60] });
		expect(tiles(fm, "terrain")).toMatch(/\/api\/tiles\/terrain\/\{z\}\/\{x\}\/\{y\}\.jpg\?v=k-1$/);
		expect(tiles(fm, "atlas")).toMatch(/\/api\/tiles\/vector\/.*\.pbf\?v=k-1-1-1$/);
		expect(fm.layers.find((l) => l.id === "terrain")).toMatchObject({
			before: "slot:terrain",
			layout: { visibility: "visible" },
		});
	});

	it("asks for new tiles when the model changes, and the timelapse's in the tab playing it", async () => {
		const { fm, queryClient } = renderOnMap(<TileSources />, withMap());
		act(() => queryClient.setQueryData(["state"], { ...state, map: { ...mapInfo, model_version: 7 } }));
		// (the query's news reaches the page a tick later)
		await waitFor(() => expect(tiles(fm, "atlas")).toMatch(/v=k-7-1-1/));
		act(() => useAppStore.setState({ replay: { pos: 0, plan: { token: 4 } } as never }));
		expect(tiles(fm, "atlas")).toMatch(/&r=4$/);
	});

	it("hides the ground picture with Ground off or another background", () => {
		const settings = { ...state.settings, layers: { ...state.settings.layers, Terrain: false } };
		const { fm } = renderOnMap(<TileSources />, withMap({}, settings));
		expect(fm.layers.find((l) => l.id === "terrain")?.layout.visibility).toBe("none");
		expect(fm.layers.find((l) => l.id === "terrain-before")?.layout.visibility).toBe("none");
	});

	it("draws a backdrop of the map image's own levels under the ground", () => {
		const { fm } = renderOnMap(<TileSources />, withMap());
		// (never the sharp ground past zmax: slow to make, and the backdrop is there to show something at once)
		expect(fm.sources.get("terrain-before")).toMatchObject({ type: "raster", maxzoom: mapInfo.zmax });
		expect(tiles(fm, "terrain-before")).toBe(tiles(fm, "terrain"));
		expect(fm.layers.find((l) => l.id === "terrain-before")).toMatchObject({ before: "slot:terrain-before" });
	});

	it("keeps the backdrop on the ground from before a job's changes until the job ends (user)", async () => {
		const { fm, queryClient } = renderOnMap(<TileSources />, withMap());
		const set = (over: Record<string, unknown>, busy: boolean) =>
			act(() => queryClient.setQueryData(["state"], { ...state, busy, map: { ...mapInfo, ...over } }));
		set({ terrain_version: 2 }, true); // new screenshots pasted in while adding
		await waitFor(() => expect(tiles(fm, "terrain")).toMatch(/v=k-2$/));
		expect(tiles(fm, "terrain-before")).toMatch(/v=k-1$/); // the old ground under it, wherever the new isn't in
		set({ terrain_version: 3 }, true);
		await waitFor(() => expect(tiles(fm, "terrain")).toMatch(/v=k-3$/));
		expect(tiles(fm, "terrain-before")).toMatch(/v=k-1$/);
		set({ terrain_version: 3 }, false); // the job ended
		await waitFor(() => expect(tiles(fm, "terrain-before")).toMatch(/v=k-3$/));
	});

	it("never keeps another atlas's ground as the backdrop, even mid-job", async () => {
		const { fm, queryClient } = renderOnMap(<TileSources />, withMap());
		act(() =>
			queryClient.setQueryData(["state"], {
				...state,
				busy: true,
				map: { ...mapInfo, tile_key: "other", terrain_version: 1 },
			}),
		);
		await waitFor(() => expect(tiles(fm, "terrain-before")).toMatch(/v=other-1$/));
	});

	it("fetches the zoomed-out ground ahead after a while, past tiles that fail", async () => {
		vi.useFakeTimers();
		const fetch = vi.fn(async (url: string) => {
			if (url.includes("/0/0/0")) throw new Error("gone");
			return { arrayBuffer: async () => new ArrayBuffer(1) };
		});
		vi.stubGlobal("fetch", fetch);
		renderOnMap(<TileSources />, withMap());
		expect(fetch).not.toHaveBeenCalled();
		await act(async () => {
			await vi.advanceTimersByTimeAsync(PREFETCH_DELAY_MS + 10);
		});
		expect(fetch.mock.calls.length).toBeGreaterThan(5);
		expect(String(fetch.mock.calls[0][0])).toContain("/0/0/0.jpg");
	});
});
