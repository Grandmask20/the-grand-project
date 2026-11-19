import type { LayerSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import { ATLAS, atlasLayers, type Look, layerOn, NONE, visibility } from "@/logic/map/AtlasLayers";
import { mapInfo, meta, state } from "@/test/Fixtures";

const geo = new Geo(mapInfo);

const look = (over: Partial<Look> = {}, settings: Partial<Look["settings"]> = {}): Look => ({
	settings: { ...structuredClone(state.settings), ...settings },
	background: "picture",
	tilted: false,
	highlight: null,
	...over,
});

type Any = LayerSpecification & {
	layout?: Record<string, unknown>;
	paint?: Record<string, unknown>;
	filter?: unknown;
	minzoom?: number;
	maxzoom?: number;
	source?: string;
};

/** The layers by id. */
function layers(l: Look): Record<string, Any> {
	return Object.fromEntries(atlasLayers(geo, mapInfo, meta, l).map((s) => [s.id, s as Any]));
}

const withStyle = (style: Record<string, string | number | boolean>) =>
	look({}, { style: { ...state.settings.style, ...style } });

describe("AtlasLayers", () => {
	it("draws every layer from the app's vector tiles", () => {
		const all = atlasLayers(geo, mapInfo, meta, look());
		expect(new Set(all.map((s) => s.id)).size).toBe(all.length);
		for (const s of all as Any[]) expect(s.source, s.id).toBe(ATLAS);
	});

	it("shows the shapes ground only as the background picked", () => {
		expect(layers(look()).land.layout?.visibility).toBe("none");
		const vector = layers(look({ background: "vector" }));
		expect(vector.land.layout?.visibility).toBe("visible");
		expect(vector.biomes.paint?.["fill-opacity"]).toBe(0.8); // the biomes over it, stronger
	});

	it("hides a switched off group", () => {
		const off = layers(look({}, { layers: { ...state.settings.layers, Paths: false, Landmarks: false } }));
		expect(off.paths.layout?.visibility).toBe("none");
		expect(off.landmarks.layout?.visibility).toBe("none");
		expect(off.towers.layout?.visibility).toBe("none");
		expect(off.icons.layout?.visibility).toBe("visible");
	});

	it("draws paths in the picked style", () => {
		for (const [path_style, dash, cap] of [
			["dashed", [3, 2], "butt"],
			["dotted", [0.1, 2], "round"],
			["solid", [1, 0], "butt"],
		] as const) {
			const { paths } = layers(withStyle({ path_style }));
			expect(paths.paint?.["line-dasharray"]).toEqual(dash);
			expect(paths.layout?.["line-cap"]).toBe(cap);
		}
	});

	it("shows the map style picked, dots zoomed out", () => {
		const squares = layers(withStyle({ map_style: "squares" }));
		expect(squares["maps-square"].layout?.visibility).toBe("visible");
		expect(squares["maps-square"].layout?.["icon-image"]).toBe("node-square-solid");
		expect(squares.maps.maxzoom).toBe(squares["maps-square"].minzoom); // the dots up to where the squares start
		expect(squares["maps-icon"].layout?.visibility).toBe("none");
		const bordered = layers(withStyle({ map_style: "squares", map_fill: "bordered" }));
		expect(bordered["maps-square"].layout?.["icon-image"]).toBe("node-square");
		const circles = layers(look());
		expect(circles.maps.maxzoom).toBe(24);
		expect(layers(withStyle({ map_style: "hidden" })).maps.layout?.visibility).toBe("none");
	});

	it("tilted, the flat paths, icons and dots give way to the 3D ones", () => {
		const tilted = layers(look({ tilted: true }, { layers: { ...state.settings.layers, "3D models": true } }));
		expect(tilted.paths.layout?.visibility).toBe("none");
		expect(tilted.icons.layout?.visibility).toBe("none");
		expect(tilted.maps.layout?.visibility).toBe("none");
		// without the models, the dots stay
		const flatDots = layers(look({ tilted: true }, { layers: { ...state.settings.layers, "3D models": false } }));
		expect(flatDots.maps.layout?.visibility).toBe("visible");
	});

	it("rings a type found, and nothing without one", () => {
		const found = layers(look({ highlight: "Boss" }));
		expect(found.highlight.filter).toEqual(["in", "|Boss|", ["get", "icons"]]);
		expect(found["highlight-edge"].filter).toEqual(found.highlight.filter);
		expect(layers(look()).highlight.filter).toEqual(NONE);
	});

	it("puts the tower picture over towers when asked, twice an icon", () => {
		const towers = layers(withStyle({ ov_towers: true, icon_size: 1.5 }));
		expect(towers.towers.layout?.visibility).toBe("visible");
		const size = towers.towers.layout?.["icon-size"] as number[];
		const icon = towers.icons.layout?.["icon-size"] as number[];
		expect(size.at(-1)).toBeCloseTo(2 * Number(icon.at(-1)));
	});

	it("reads a toggle as on unless switched off", () => {
		expect(layerOn({ ...state.settings, layers: {} }, "Paths")).toBe(true);
		expect(layerOn({ ...state.settings, layers: { Paths: false } }, "Paths")).toBe(false);
		expect(visibility(true)).toBe("visible");
	});
});
