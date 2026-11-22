import { createExpression, featureFilter } from "@maplibre/maplibre-gl-style-spec";
import type { LayerSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import { ATLAS, atlasLayers, type Look, layerOn, NONE, pathShareFilter, visibility } from "@/logic/map/AtlasLayers";
import { mapInfo, meta, nodeStates, state } from "@/test/Fixtures";

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

/** A paint or layout value as MapLibre works it out for a map node (zoomed in past the dots), as "#rrggbb". */
function colourOf(value: unknown, props: Record<string, unknown>, zoom = 22): string {
	const parsed = createExpression(value, {
		type: "color",
		"property-type": "data-driven",
		expression: { interpolated: false, parameters: ["zoom", "feature"] },
	} as never);
	if (parsed.result !== "success") throw new Error(JSON.stringify(parsed.value));
	const c = parsed.value.evaluate({ zoom }, { type: 1, properties: props, geometry: [] } as never) as {
		r: number;
		g: number;
		b: number;
	};
	const hex = (v: number) =>
		Math.round(v * 255)
			.toString(16)
			.padStart(2, "0");
	return `#${hex(c.r)}${hex(c.g)}${hex(c.b)}`;
}

const node = (props: Record<string, unknown>) => ({ status: "confirmed", fill: "", icons: "", ...props });

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

	it("hides paths drawn by too few screenshots on the page, without new tiles", () => {
		expect(layers(look()).paths.filter).toEqual(pathShareFilter(0));
		expect(layers(withStyle({ path_freq: 0.35 })).paths.filter).toEqual(pathShareFilter(0.35));
	});

	it("the share filter keeps paths at or above the share, Abyss chains, and tiles from before shares", () => {
		// run by MapLibre's own filter evaluator, not compared with the helper that made it (CodeRabbit)
		const keeps = (freq: number, props: Record<string, unknown>) =>
			featureFilter(pathShareFilter(freq)).filter({ zoom: 10 }, { type: 2, properties: props, geometry: [] });
		expect(keeps(0.35, { share: 0.2, abyss: false })).toBe(false);
		expect(keeps(0.35, { share: 0.35, abyss: false })).toBe(true); // at the share: kept
		expect(keeps(0.35, { share: 0.9, abyss: false })).toBe(true);
		expect(keeps(1, { share: 0.2, abyss: true })).toBe(true); // an Abyss chain always
		expect(keeps(0.35, { abyss: false })).toBe(true); // a tile from before paths carried their share
		expect(keeps(0, { share: 0, abyss: false })).toBe(true); // 0%: every path
	});

	it("hides a switched off group", () => {
		const off = layers(look({}, { layers: { ...state.settings.layers, Paths: false, Landmarks: false } }));
		expect(off.paths.layout?.visibility).toBe("none");
		expect(off.landmarks.layout?.visibility).toBe("none");
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

	it("colours a map node by its state, by its status while no screenshot named it", () => {
		const { maps } = layers(look());
		for (const [st, colour] of Object.entries(nodeStates)) {
			expect(colourOf(maps.paint?.["circle-color"], node({ state: st }))).toBe(colour);
			expect(colourOf(maps.paint?.["circle-color"], node({ state: st }), 0)).toBe(colour); // zoomed out dots too
		}
		expect(colourOf(maps.paint?.["circle-color"], node({ state: "" }))).toBe(meta.colours.node.confirmed);
		expect(colourOf(maps.paint?.["circle-color"], node({ status: "single", state: "" }))).toBe(
			meta.colours.node.single,
		);
		expect(colourOf(maps.paint?.["circle-color"], node({ state: "purple" }))).toBe(meta.colours.node.confirmed);
		// a state wins over the status
		expect(colourOf(maps.paint?.["circle-color"], node({ status: "single", state: "green" }))).toBe("#50c850");
	});

	it("a state wins over the View tab's map colour, which colours the maps without one", () => {
		const { maps } = layers(withStyle({ map_col: "#123456" }));
		expect(colourOf(maps.paint?.["circle-color"], node({ state: "red" }))).toBe(nodeStates.red);
		expect(colourOf(maps.paint?.["circle-color"], node({ state: "" }))).toBe("#123456");
	});

	it("bordered, the ring and the squares take the state's colour (the icon's colour inside)", () => {
		const bordered = layers(withStyle({ map_style: "squares", map_fill: "bordered" }));
		const blue = node({ state: "blue", fill: "#aabbcc" });
		expect(colourOf(bordered.maps.paint?.["circle-stroke-color"], blue)).toBe(nodeStates.blue);
		expect(colourOf(bordered["maps-square"].paint?.["icon-color"], blue)).toBe(nodeStates.blue);
		expect(colourOf(bordered.maps.paint?.["circle-color"], blue)).toBe("#aabbcc");
		const solid = layers(withStyle({ map_style: "squares" }));
		expect(colourOf(solid["maps-square"].paint?.["icon-color"], blue)).toBe(nodeStates.blue);
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

	it("reads a toggle as on unless switched off", () => {
		expect(layerOn({ ...state.settings, layers: {} }, "Paths")).toBe(true);
		expect(layerOn({ ...state.settings, layers: { Paths: false } }, "Paths")).toBe(false);
		expect(visibility(true)).toBe("visible");
	});
});
