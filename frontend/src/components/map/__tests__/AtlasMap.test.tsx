import { act, screen, waitFor } from "@testing-library/react";
import { LngLat } from "maplibre-gl";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasMap, constrainTo } from "@/components/map/AtlasMap";
import { Geo } from "@/logic/Geo";
import { LAYER_ORDER } from "@/logic/map/LayerOrder";
import { useAppStore } from "@/store/AppStore";
import { fakeMap } from "@/test/FakeMap";
import { mapInfo, meta, state } from "@/test/Fixtures";
import { failWith, setMap } from "@/test/ReactMapGlMock";
import { renderWithApp } from "@/test/RenderWithApp";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const part = (s: string, extra = {}) => ({ state: s, quiet: 0, error: null, ...extra });
const app = (parts: Record<string, unknown>) => ({
	"GET /api/parts": { parts },
	"GET /api/state": { ...state, map: mapInfo },
});

function render(parts: Record<string, unknown> = { map_image: part("ready"), model: part("ready") }, fm = fakeMap()) {
	setMap(fm);
	return { fm, ...renderWithApp(<AtlasMap info={mapInfo} meta={meta} />, app(parts)) };
}

describe("AtlasMap", () => {
	afterEach(() => failWith(null));

	it("draws everything over the map once it has loaded, and hands the map to the page", async () => {
		const { fm } = render();
		await waitFor(() => expect(useAppStore.getState().map).toBe(fm.map));
		// its parts, on the map: the tiles' sources, the atlas's layers, the controls
		expect(fm.sources.has("terrain") && fm.sources.has("atlas")).toBe(true);
		expect(fm.layerIds()).toEqual(expect.arrayContaining(["terrain", "paths", "maps", "selected", "bookmarks"]));
		expect(fm.controls.size).toBe(2);
	});

	it("puts every layer in its place in the stack, whenever it comes", async () => {
		const { fm } = render(); // (the fake map has the style's slots, as the real one)
		await waitFor(() => expect(useAppStore.getState().map).toBe(fm.map));
		act(() => useAppStore.setState({ camera: { x: 0, y: 0, px: 1, bearing: 0, pitch: 59 } })); // the 3D layers come later
		const drawn = fm.layerIds();
		expect(drawn).toEqual(LAYER_ORDER.filter((id) => drawn.includes(id)));
		expect(drawn.length).toBeGreaterThan(20);
	});

	it("waits under its cover until every part is ready and the view's tiles are in", async () => {
		render({ map_image: part("ready"), model: part("building", { quiet: 99 }) });
		expect(screen.getByText("Loading atlas…")).toBeInTheDocument();
		expect(await screen.findByText(/no progress for 99 s/)).toBeInTheDocument();
	});

	it("shows itself once ready and the map is idle", async () => {
		const { fm } = render();
		await waitFor(() => expect(useAppStore.getState().map).toBe(fm.map));
		await waitFor(() => expect(screen.queryByText("Loading atlas…")).toBeNull());
	});

	it("can be shown anyway", async () => {
		const { user } = render({ map_image: part("waiting") });
		await user.click(screen.getByRole("button", { name: "Show the map anyway" }));
		expect(screen.queryByText("Loading atlas…")).toBeNull();
	});

	it("says which part failed, and shows what there is", async () => {
		render({ map_image: part("ready"), model: part("failed", { error: "out of memory" }) });
		expect(
			await screen.findByText(/Map nodes, paths, icons and biomes could not be made: out of memory/),
		).toBeInTheDocument();
		expect(screen.queryByText("Loading atlas…")).toBeNull();
	});

	it("says why when the map can't start, with a way to try again", async () => {
		failWith({ error: { message: "Failed to initialize WebGL" } });
		render();
		expect(await screen.findByText("The map could not start: Failed to initialize WebGL")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
		expect(screen.queryByText("Loading atlas…")).toBeNull(); // not waiting for a map that never comes
	});

	it("tells a tile's failure apart, the map still there", async () => {
		failWith({ error: { message: "404" }, sourceId: "terrain" });
		render();
		expect(await screen.findByText("Map tiles could not load: 404")).toBeInTheDocument();
		expect(screen.queryByText(/could not start/)).toBeNull();
	});

	it("gives the page its map back when it goes", async () => {
		const { fm, unmount } = render();
		await waitFor(() => expect(useAppStore.getState().map).toBe(fm.map));
		act(() => unmount());
		expect(useAppStore.getState().map).toBeNull();
	});

	it("keeps the zoom within the map's own limits (user: you could zoom in endlessly)", () => {
		const keep = constrainTo(mapInfo, new Geo(mapInfo));
		const c = new LngLat(0, 0);
		expect(keep(c, 40).zoom).toBe(mapInfo.maxzoom);
		expect(keep(c, -3).zoom).toBe(0);
		expect(keep(c, 4.5).zoom).toBe(4.5);
	});
});
