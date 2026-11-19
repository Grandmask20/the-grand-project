import type { LayerSpecification, Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";
import type { MapInfo } from "@/domain/map/MapInfo";
import { Geo } from "@/logic/Geo";
import {
	applyLook,
	baseStyle,
	GEOJSON_SOURCES,
	iconMinZoom,
	iconPx,
	iconSize,
	LAYER_GROUPS,
	type Look,
	nodeRadius,
	setData,
	setImage,
	squareImage,
	worldSize,
} from "@/logic/MapStyle";
import { meta, state } from "@/test/Fixtures";

const info: MapInfo = {
	grid: { x0: -300, y0: -200, scale: 0.5, width: 4000, height: 3000 },
	zmax: 6,
	zdeep: 8,
	world: 16384,
	offset: 4096,
	maxzoom: 9,
	bounds: [
		[-90, -40],
		[0, 60],
	],
	tile_key: "k",
	terrain_version: 1,
	model_version: 1,
	filter_version: 1,
	sprite: { size: 64, units: 30, min_px: 8 },
};
const geo = new Geo(info);
const style = () => baseStyle(info, geo, meta, "/t/{z}/{x}/{y}.jpg", "/v/{z}/{x}/{y}.pbf");

/** A map that keeps what the look sets on it. */
function fakeMap(ids: string[]) {
	const layout: Record<string, Record<string, unknown>> = {};
	const paint: Record<string, Record<string, unknown>> = {};
	const filters: Record<string, unknown> = {};
	const map = {
		getLayer: (id: string) => (ids.includes(id) ? { id } : undefined),
		setLayoutProperty: (id: string, k: string, v: unknown) => {
			layout[id] = { ...layout[id], [k]: v };
		},
		setPaintProperty: (id: string, k: string, v: unknown) => {
			paint[id] = { ...paint[id], [k]: v };
		},
		setFilter: (id: string, f: unknown) => {
			filters[id] = f;
		},
		setLayerZoomRange: vi.fn(),
	};
	return { map: map as unknown as MapLibreMap, layout, paint, filters };
}

const look = (over: Partial<Look> = {}): Look => ({
	settings: structuredClone(state.settings),
	background: "picture",
	tilted: false,
	highlight: null,
	replayPos: null,
	tint: "off",
	...over,
});

describe("baseStyle", () => {
	it("has every source the page fills and the app's tiles within the atlas", () => {
		const s = style();
		for (const id of GEOJSON_SOURCES) expect(s.sources[id]).toMatchObject({ type: "geojson" });
		expect(s.sources.terrain).toMatchObject({ type: "raster", maxzoom: info.zdeep, bounds: [-90, -40, 0, 60] });
		expect(s.sources.atlas).toMatchObject({ type: "vector", maxzoom: info.zmax });
	});

	it("gives every layer its own id and a source that exists", () => {
		const s = style();
		const ids = s.layers.map((l) => l.id);
		expect(new Set(ids).size).toBe(ids.length);
		for (const l of s.layers as (LayerSpecification & { source?: string })[])
			if (l.source) expect(s.sources[l.source], l.id).toBeDefined();
	});

	it("has the layers of every Show on the map toggle", () => {
		const ids = new Set(style().layers.map((l) => l.id));
		for (const [group, layers] of Object.entries(LAYER_GROUPS))
			for (const id of layers) expect(ids.has(id), `${group}: ${id}`).toBe(true);
	});
});

describe("sizes", () => {
	it("worldSize grows with the map from its smallest size, and stops at the cap", () => {
		const grow = worldSize(geo, 2, 1) as unknown[];
		expect(grow[0]).toBe("interpolate");
		expect(grow[4]).toBe(1);
		const capped = worldSize(geo, 2, 1, 1.6) as unknown[];
		expect(capped.at(-1)).toBeCloseTo(3.2);
		expect(worldSize(geo, 2, 10, 1)).toBe(10); // the cap under the smallest size: a fixed size
	});

	it("map nodes are dots zoomed out, then grow with the size setting", () => {
		const r1 = nodeRadius(geo, 1) as unknown[];
		const r2 = nodeRadius(geo, 2) as unknown[];
		expect(r1[4]).toBe(2.2); // the dots
		expect(r2.at(-1)).toBe(26);
		expect(r1.at(-1)).toBe(13);
	});

	it("icons start where they are big enough and scale with the ground", () => {
		const z0 = iconMinZoom(geo, info);
		expect(z0).toBeLessThanOrEqual(info.maxzoom - 0.5);
		expect(iconPx(geo, info, z0, 1)).toBeCloseTo(info.sprite.min_px, 0);
		const size = iconSize(geo, info, 1) as unknown[];
		expect(size[3]).toBe(z0);
		expect(iconPx(geo, info, z0 + 1, 2)).toBeCloseTo(4 * iconPx(geo, info, z0, 1));
	});

	it("squares are hollow, or filled", () => {
		const hollow = squareImage();
		const filled = squareImage(true);
		expect(hollow.width).toBe(32);
		expect(hollow.data.length).toBe(32 * 32 * 4);
		const alphaAt = (img: { data: Uint8Array }, x: number, y: number) => img.data[(y * 32 + x) * 4 + 3];
		expect(alphaAt(hollow, 16, 16)).toBe(0);
		expect(alphaAt(filled, 16, 16)).toBe(255);
		expect(alphaAt(hollow, 4, 16)).toBe(255);
		expect(alphaAt(hollow, 1, 16)).toBe(0); // a clear edge around the ring
	});
});

describe("applyLook", () => {
	const ids = style().layers.map((l) => l.id);

	it("shows the background picked and the layers switched on", () => {
		const { map, layout } = fakeMap(ids);
		applyLook(map, geo, meta, look());
		expect(layout.terrain.visibility).toBe("visible");
		expect(layout.land.visibility).toBe("none");
		expect(layout.paths.visibility).toBe("visible");
		const vector = fakeMap(ids);
		applyLook(vector.map, geo, meta, look({ background: "vector" }));
		expect(vector.layout.terrain.visibility).toBe("none");
		expect(vector.layout.land.visibility).toBe("visible");
	});

	it("hides a switched off group", () => {
		const { map, layout } = fakeMap(ids);
		const l = look();
		l.settings.layers = { ...l.settings.layers, Paths: false, Bookmarks: false };
		applyLook(map, geo, meta, l);
		expect(layout.paths.visibility).toBe("none");
		expect(layout.bookmarks.visibility).toBe("none");
	});

	it("draws paths in the picked style", () => {
		for (const [pathStyle, dash, cap] of [
			["dashed", [3, 2], "butt"],
			["dotted", [0.1, 2], "round"],
			["solid", [1, 0], "butt"],
		] as const) {
			const { map, layout, paint } = fakeMap(ids);
			const l = look();
			l.settings.style = { ...l.settings.style, path_style: pathStyle };
			applyLook(map, geo, meta, l);
			expect(paint.paths["line-dasharray"]).toEqual(dash);
			expect(layout.paths["line-cap"]).toBe(cap);
		}
	});

	it("shows the map style picked", () => {
		const squares = fakeMap(ids);
		const l = look();
		l.settings.style = { ...l.settings.style, map_style: "squares" };
		applyLook(squares.map, geo, meta, l);
		expect(squares.layout["maps-square"].visibility).toBe("visible");
		expect(squares.layout["maps-square"]["icon-image"]).toBe("node-square-solid");
		const hidden = fakeMap(ids);
		l.settings.style = { ...l.settings.style, map_style: "hidden" };
		applyLook(hidden.map, geo, meta, l);
		expect(hidden.layout.maps.visibility).toBe("none");
	});

	it("tilted, the flat paths and icons give way to the 3D ones", () => {
		const { map, layout } = fakeMap(ids);
		const l = look({ tilted: true });
		l.settings.layers = { ...l.settings.layers, "3D models": true };
		applyLook(map, geo, meta, l);
		expect(layout.paths.visibility).toBe("none");
		expect(layout.icons.visibility).toBe("none");
		expect(layout.maps.visibility).toBe("none");
	});

	it("highlights a type found, and hides bookmarks while replaying", () => {
		const { map, filters, layout } = fakeMap(ids);
		applyLook(map, geo, meta, look({ highlight: "Boss", replayPos: 3 }));
		expect(filters.highlight).toEqual(["in", "|Boss|", ["get", "icons"]]);
		expect(layout.bookmarks.visibility).toBe("none");
	});

	it("leaves out layers the map doesn't have", () => {
		const { map, layout } = fakeMap([]);
		applyLook(map, geo, meta, look());
		expect(layout).toEqual({});
	});
});

describe("setData and setImage", () => {
	it("puts data in a source that exists", () => {
		const setDataFn = vi.fn();
		const map = { getSource: (id: string) => (id === "route" ? { setData: setDataFn } : undefined) };
		setData(map as unknown as MapLibreMap, "route", { type: "FeatureCollection", features: [] });
		setData(map as unknown as MapLibreMap, "hits", { type: "FeatureCollection", features: [] }); // missing: nothing
		expect(setDataFn).toHaveBeenCalledOnce();
	});

	it("adds, moves, swaps and removes a picture", () => {
		const corners: [[number, number], [number, number], [number, number], [number, number]] = [
			[0, 1],
			[1, 1],
			[1, 0],
			[0, 0],
		];
		let source:
			| { url: string; setCoordinates: ReturnType<typeof vi.fn>; updateImage: ReturnType<typeof vi.fn> }
			| undefined;
		let layer = false;
		const map = {
			getSource: () => source,
			getLayer: () => (layer ? {} : undefined),
			addSource: (_id: string, s: { url: string }) => {
				source = { url: s.url, setCoordinates: vi.fn(), updateImage: vi.fn() };
			},
			addLayer: vi.fn(() => {
				layer = true;
			}),
			removeLayer: vi.fn(() => {
				layer = false;
			}),
			removeSource: vi.fn(() => {
				source = undefined;
			}),
			setPaintProperty: vi.fn(),
		};
		const m = map as unknown as MapLibreMap;
		setImage(m, "heat", "/a.png", corners, "paths", 0.5);
		expect(map.addLayer).toHaveBeenCalledOnce();
		setImage(m, "heat", "/a.png", corners, "paths", 0.7); // the same picture: only moved
		expect(source?.setCoordinates).toHaveBeenCalledWith(corners);
		expect(map.setPaintProperty).toHaveBeenCalledWith("heat", "raster-opacity", 0.7);
		setImage(m, "heat", "/b.png", corners, "paths");
		expect(source?.updateImage).toHaveBeenCalledWith({ url: "/b.png", coordinates: corners });
		setImage(m, "heat", null, null, "paths");
		expect(map.removeLayer).toHaveBeenCalledWith("heat");
		expect(source).toBeUndefined();
	});
});
