import type { LayerSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";
import { Geo } from "@/logic/Geo";
import { atlasLayers, type Look } from "@/logic/map/AtlasLayers";
import { LAYER_ORDER, mapStyle, slotOf } from "@/logic/map/LayerOrder";
import {
	bookmarkLayer,
	ghostLineLayer,
	gotoLayer,
	hitLayers,
	litRouteLayers,
	markLayers,
	outlineLayer,
	previewLayers,
	recentLayer,
	routeLayers,
	savedRouteLayer,
	selectionLayers,
} from "@/logic/map/OverlayLayers";
import { mapInfo, meta, state } from "@/test/Fixtures";

const geo = new Geo(mapInfo);
const look: Look = { settings: state.settings, background: "picture", tilted: false, highlight: null };

/** Every layer the page's components draw from specs, plus the ones made by hand (pictures, the ground, 3D). */
function everyLayer(): string[] {
	const route = routeLayers(geo, true);
	const specs: LayerSpecification[] = [
		...atlasLayers(geo, mapInfo, meta, look),
		...selectionLayers(geo, meta, true),
		...hitLayers(geo, meta),
		gotoLayer(),
		...route.line,
		route.nodes,
		route.here,
		recentLayer(meta, true),
		bookmarkLayer(geo, meta, true),
		savedRouteLayer(meta, true),
		...litRouteLayers(geo, meta),
		...markLayers(true),
		ghostLineLayer(),
		...previewLayers(),
		outlineLayer(0),
	];
	const byHand = ["terrain", "tint-picture", "fog-picture", "ghost-picture", "preview", "lasso"];
	const gl = ["ground-fade-gl", "models-3d-gl", "paths-3d-gl", "icons-3d-gl"];
	return [...specs.map((s) => s.id), ...byHand, ...gl];
}

describe("LAYER_ORDER", () => {
	it("lists every layer once", () => {
		expect(new Set(LAYER_ORDER).size).toBe(LAYER_ORDER.length);
		expect([...everyLayer()].sort()).toEqual([...LAYER_ORDER].sort());
	});

	it("keeps the stack the map has always had", () => {
		const at = (id: string) => LAYER_ORDER.indexOf(id as (typeof LAYER_ORDER)[number]);
		expect(at("terrain")).toBeLessThan(at("tint-picture")); // Colour by over the ground, under the biomes
		expect(at("tint-picture")).toBeLessThan(at("biomes"));
		expect(at("landmarks")).toBeLessThan(at("fog-picture")); // the fog over the map's own layers
		expect(at("fog-picture")).toBeLessThan(at("outline")); // the screenshots coming in over it
		expect(at("ground-fade-gl")).toBeLessThan(at("models-3d-gl"));
		expect(at("models-3d-gl")).toBeLessThan(at("paths-3d-gl")); // (toggled off and on: CodeRabbit)
		expect(at("paths-3d-gl")).toBeLessThan(at("icons-3d-gl"));
		expect(at("icons-3d-gl")).toBeLessThan(at("bookmarks"));
		expect(at("preview")).toBeLessThan(at("selected")); // a question's screenshot under the selection ring
		expect(at("lasso")).toBe(LAYER_ORDER.length - 1);
	});
});

describe("mapStyle", () => {
	it("is black with a hidden slot for every layer, in order", () => {
		const s = mapStyle();
		expect(s.layers[0]).toMatchObject({ id: "background", type: "background" });
		expect(s.layers.slice(1).map((l) => l.id)).toEqual(LAYER_ORDER.map(slotOf));
		for (const l of s.layers.slice(1)) expect(l).toMatchObject({ type: "background", layout: { visibility: "none" } });
		expect(s.sources).toEqual({}); // the components add theirs
	});
});
