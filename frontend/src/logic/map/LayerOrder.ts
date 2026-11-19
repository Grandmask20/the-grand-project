import type { StyleSpecification } from "maplibre-gl";

/**
 * Every layer the map can show, bottom to top. Each has a slot in the map's style (an empty layer of its own), and
 * goes in right under it, so a layer lands in its place whenever it comes and goes: layers made by components that
 * mount at different times (the timelapse's fog, the 3D view, a question's screenshot) stacked in the order they
 * were made before, which needed hand-placed "under that one" for every layer (CodeRabbit: toggling 3D models off
 * and on drew them over the paths and icons).
 */
export const LAYER_ORDER = [
	"land",
	"terrain",
	"tint-picture", // Colour by: under the biomes
	"biomes",
	"biomes-line",
	"recent",
	"paths",
	"removed",
	"route-casing",
	"route",
	"icons",
	"maps",
	"maps-square",
	"maps-icon",
	"landmarks",
	"highlight-edge",
	"highlight",
	"hits-edge",
	"hits",
	"route-nodes",
	"fog-picture", // the timelapse's fog: over the map's own layers, so it hides what isn't revealed yet
	"outline", // the screenshots coming in, over the fog
	"ground-fade-gl", // the 3D view: the ground fading out far off, over the flat layers and under the 3D ones
	"models-3d-gl",
	"paths-3d-gl",
	"icons-3d-gl",
	"bookmarks",
	"marks-line",
	"marks-dashed",
	"marks-point",
	"selected-path",
	"ghost-picture", // the screenshot placed by hand and a question's: under the selection ring
	"preview",
	"selected",
	"goto",
	"ghost-line",
	"preview-line",
	"preview-agree",
	"lasso", // Terra Draw's layers (LassoDraw): on top
] as const;

export type LayerId = (typeof LAYER_ORDER)[number];

/** The id of a layer's slot: the layer goes in right under it. */
export const slotOf = (id: LayerId): string => `slot:${id}`;

/** The style the map starts with: black, the light the 3D models are lit by, and every layer's slot. Sources and
 * layers come with the components that draw them. */
export function mapStyle(): StyleSpecification {
	return {
		version: 8,
		light: { anchor: "map", position: [1.4, 210, 35], intensity: 0.35 },
		sources: {},
		layers: [
			{ id: "background", type: "background", paint: { "background-color": "#000000" } },
			...LAYER_ORDER.map((id) => ({
				id: slotOf(id),
				type: "background" as const,
				layout: { visibility: "none" as const },
			})),
		],
	};
}
