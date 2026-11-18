import type {
	ExpressionSpecification,
	FilterSpecification,
	GeoJSONSource,
	ImageSource,
	Map as MapLibreMap,
	StyleSpecification,
} from "maplibre-gl";
import type { Meta } from "@/domain/app/Meta";
import type { Background, UiSettings } from "@/domain/app/UiSettings";
import type { MapInfo } from "@/domain/map/MapInfo";
import { cityColours, landmarkColours, styleColour } from "./Colours";
import type { Geo } from "./Geo";

export const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

/** GeoJSON sources the page fills (everything else comes from the app's tiles). */
export const GEOJSON_SOURCES = [
	"frames",
	"fog",
	"recent",
	"route",
	"route-nodes",
	"hits",
	"selected",
	"goto",
	"marks",
	"lasso",
	"outline",
	"ghost-line",
] as const;
export type GeoJsonSourceId = (typeof GEOJSON_SOURCES)[number];

/** Map layers each "Show on the map" toggle switches. */
export const LAYER_GROUPS: Record<string, string[]> = {
	Terrain: ["terrain"],
	Paths: ["paths"],
	Nodes: ["maps", "maps-square", "maps-icon"],
	Icons: ["icons"],
	Landmarks: ["landmarks"],
	Bookmarks: ["bookmarks"],
	"City & stronghold biomes": ["biomes", "biomes-line"],
	"Recent additions": ["recent"],
	Removed: ["removed"],
	Route: ["route", "route-casing", "route-nodes"],
	"Debug marks": ["marks-line", "marks-dashed", "marks-point"],
};

/** Layers whose features carry the replay's "step" (hidden until the replay reaches them). */
export const STEPPED = ["maps", "maps-square", "maps-icon", "paths", "icons", "landmarks", "towers", "solids"] as const;

const NONE: FilterSpecification = ["==", ["get", "id"], -1];

/** The map zoom where a size in atlas units is `px` screen px. */
const zoomAt = (geo: Geo, px: number) => geo.zoomFor(px);

/** The style the map starts with: sources and every layer (looks are set by applyLook). */
export function baseStyle(
	info: MapInfo,
	geo: Geo,
	meta: Meta,
	terrainUrl: string,
	vectorUrl: string,
): StyleSpecification {
	const bounds = [...info.bounds[0], ...info.bounds[1]] as [number, number, number, number];
	const ring = (extra: number): ExpressionSpecification => [
		"interpolate",
		["exponential", 2],
		["zoom"],
		zoomAt(geo, 0.25),
		4 + extra,
		zoomAt(geo, 1.6),
		16 + extra,
	];
	const sources: StyleSpecification["sources"] = {
		terrain: { type: "raster", tiles: [terrainUrl], tileSize: 256, minzoom: 0, maxzoom: info.zdeep, bounds },
		atlas: { type: "vector", tiles: [vectorUrl], minzoom: 0, maxzoom: info.zmax, bounds },
	};
	for (const id of GEOJSON_SOURCES) sources[id] = { type: "geojson", data: EMPTY };
	return {
		version: 8,
		light: { anchor: "map", position: [1.4, 210, 35], intensity: 0.35 },
		sources,
		layers: [
			{ id: "background", type: "background", paint: { "background-color": "#000000" } },
			{ id: "land", type: "fill", source: "atlas", "source-layer": "land", paint: { "fill-color": meta.colours.land } },
			{ id: "terrain", type: "raster", source: "terrain", paint: { "raster-fade-duration": 100 } },
			{
				id: "tint",
				type: "fill",
				source: "frames",
				layout: { visibility: "none" },
				paint: { "fill-color": ["get", "colour"], "fill-opacity": meta.tint_alpha },
			},
			{ id: "biomes", type: "fill", source: "atlas", "source-layer": "biomes", paint: { "fill-opacity": 0.28 } },
			{
				id: "biomes-line",
				type: "line",
				source: "atlas",
				"source-layer": "biomes",
				paint: { "line-width": 1.5, "line-opacity": 0.8 },
			},
			{
				id: "fog-full",
				type: "fill",
				source: "fog",
				filter: NONE,
				paint: { "fill-color": "#000000", "fill-opacity": 1, "fill-antialias": false },
			},
			{
				id: "fog-fading",
				type: "fill",
				source: "fog",
				filter: NONE,
				paint: { "fill-color": "#000000", "fill-opacity": 1, "fill-antialias": false },
			},
			{
				id: "outline",
				type: "line",
				source: "outline",
				paint: { "line-color": "#ffffff", "line-width": 1.2, "line-opacity": 0.9 },
			},
			{
				id: "recent",
				type: "line",
				source: "recent",
				paint: {
					"line-color": ["case", ["get", "picked"], "#ffffff", meta.colours.recent],
					"line-width": ["case", ["==", ["get", "age"], 0], 3, 2],
					"line-opacity": ["get", "opacity"],
				},
			},
			{
				id: "paths",
				type: "line",
				source: "atlas",
				"source-layer": "paths",
				layout: { "line-cap": "round", "line-join": "round" },
				// the starting sizes are the scaled ones too: a fixed default drew everything big for a moment (user)
				paint: { "line-opacity": 0.9, "line-width": worldSize(geo, 2.5, 0.6, 1.6) },
			},
			{
				id: "removed",
				type: "circle",
				source: "atlas",
				"source-layer": "removed",
				paint: {
					"circle-radius": worldSize(geo, 7, 1.5),
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-color": meta.colours.removed,
					"circle-stroke-width": 2,
				},
			},
			{
				id: "route-casing",
				type: "line",
				source: "route",
				layout: { "line-cap": "round", "line-join": "round" },
				paint: { "line-color": "#000000", "line-width": 9, "line-opacity": 0.7 },
			},
			{
				id: "route",
				type: "line",
				source: "route",
				layout: { "line-cap": "round", "line-join": "round" },
				paint: { "line-color": "#7cff6b", "line-width": 5 },
			},
			{
				id: "maps",
				type: "circle",
				source: "atlas",
				"source-layer": "maps",
				paint: { "circle-radius": nodeRadius(geo, 1), "circle-stroke-width": 0.6 },
			},
			{
				id: "maps-square",
				type: "symbol",
				source: "atlas",
				"source-layer": "maps",
				layout: {
					visibility: "none",
					"icon-image": "node-square",
					"icon-allow-overlap": true,
					"icon-ignore-placement": true,
				},
			},
			{
				// the "map icons" style: the game's map node picture (references/map_node_icon.webp), as the old window
				id: "maps-icon",
				type: "symbol",
				source: "atlas",
				"source-layer": "maps",
				layout: {
					visibility: "none",
					"icon-image": "node-picture",
					"icon-allow-overlap": true,
					"icon-ignore-placement": true,
				},
			},
			{
				id: "landmarks",
				type: "circle",
				source: "atlas",
				"source-layer": "landmarks",
				paint: {
					"circle-radius": worldSize(geo, 14, 4),
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-width": worldSize(geo, 2.2, 1),
				},
			},
			{
				id: "highlight",
				type: "circle",
				source: "atlas",
				"source-layer": "maps",
				filter: NONE,
				paint: {
					"circle-radius": ring(3),
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-color": meta.colours.hit,
					"circle-stroke-width": 3,
				},
			},
			{
				id: "hits",
				type: "circle",
				source: "hits",
				paint: {
					"circle-radius": ring(6),
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-color": meta.colours.hit,
					"circle-stroke-width": 2,
				},
			},
			{
				id: "route-nodes",
				type: "circle",
				source: "route-nodes",
				paint: {
					"circle-radius": ring(1),
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-color": "#7cff6b",
					"circle-stroke-width": 3,
				},
			},
			{
				id: "solids",
				type: "fill-extrusion",
				source: "atlas",
				"source-layer": "solids",
				layout: { visibility: "none" },
				paint: {
					"fill-extrusion-color": ["get", "colour"],
					"fill-extrusion-base": ["get", "base"],
					"fill-extrusion-height": ["get", "height"],
					"fill-extrusion-opacity": 0.95,
					"fill-extrusion-vertical-gradient": true,
				},
			},
			{
				id: "bookmarks",
				type: "circle",
				source: "atlas",
				"source-layer": "bookmarks",
				paint: {
					"circle-radius": ["interpolate", ["linear"], ["zoom"], zoomAt(geo, 0.05), 3, zoomAt(geo, 2), 9],
					"circle-color": meta.colours.bookmark,
					"circle-stroke-color": "#000000",
					"circle-stroke-width": 1.5,
					"circle-translate": [0, -10],
				},
			},
			{
				id: "marks-line",
				type: "line",
				source: "marks",
				filter: ["all", ["==", ["geometry-type"], "LineString"], ["!=", ["get", "kind"], "missing path"]],
				paint: { "line-color": "#ff00ff", "line-width": 2 },
			},
			{
				id: "marks-dashed",
				type: "line",
				source: "marks",
				filter: ["all", ["==", ["geometry-type"], "LineString"], ["==", ["get", "kind"], "missing path"]],
				paint: { "line-color": "#ff00ff", "line-width": 2, "line-dasharray": [1, 2] },
			},
			{
				id: "marks-point",
				type: "circle",
				source: "marks",
				filter: ["==", ["geometry-type"], "Point"],
				paint: {
					"circle-radius": 9,
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-color": "#ff00ff",
					"circle-stroke-width": 2,
				},
			},
			{
				id: "selected",
				type: "circle",
				source: "selected",
				paint: {
					"circle-radius": ring(10),
					"circle-color": "rgba(255,255,255,0.10)",
					"circle-stroke-color": meta.colours.select,
					"circle-stroke-width": 3,
				},
			},
			{
				id: "goto",
				type: "circle",
				source: "goto",
				paint: {
					"circle-radius": 12,
					"circle-color": "rgba(0,0,0,0)",
					"circle-stroke-color": "#ff4040",
					"circle-stroke-width": 3,
				},
			},
			{
				id: "ghost-line",
				type: "line",
				source: "ghost-line",
				paint: { "line-color": "#ffdc00", "line-width": 2 },
			},
			{
				id: "lasso-fill",
				type: "fill",
				source: "lasso",
				paint: { "fill-color": "#c8a45c", "fill-opacity": 0.12 },
			},
			{
				id: "lasso",
				type: "line",
				source: "lasso",
				paint: { "line-color": "#c8a45c", "line-width": 2, "line-dasharray": [2, 1] },
			},
		],
	};
}

/** Everything that decides how the map looks besides its tiles. */
export interface Look {
	settings: UiSettings;
	background: Background;
	tilted: boolean;
	highlight: string | null;
	replayPos: number | null;
	tint: "off" | "frames" | "heat";
}

/**
 * A size that grows and shrinks with the map like the thing it draws (`units` atlas units), but never below
 * `minPx` screen px, and from `capPx` per unit on stays put. Fixed screen sizes made the zoomed out atlas one cyan
 * blob (2 px rings on map nodes 3 px apart) and changed how paths looked from zoom to zoom (user).
 */
export function worldSize(geo: Geo, units: number, minPx: number, capPx = 0): ExpressionSpecification {
	const z0 = zoomAt(geo, minPx / units);
	if (capPx > 0) {
		const z1 = zoomAt(geo, capPx);
		if (z1 > z0) return ["interpolate", ["exponential", 2], ["zoom"], z0, minPx, z1, units * capPx];
		return minPx as unknown as ExpressionSpecification;
	}
	return ["interpolate", ["exponential", 2], ["zoom"], z0, minPx, z0 + 12, minPx * 4096];
}

function visible(map: MapLibreMap, id: string, on: boolean) {
	if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
}

function setPaint(map: MapLibreMap, id: string, name: string, value: unknown) {
	if (map.getLayer(id)) map.setPaintProperty(id, name, value);
}

function setFilter(map: MapLibreMap, id: string, filter: FilterSpecification | null) {
	if (map.getLayer(id)) map.setFilter(id, filter);
}

/**
 * A map node's radius as the old window drew it: zoomed out (under 0.45 px per unit) small dots whatever the size
 * setting (a big size made the far view one blob: user), then 8 px per screen px per unit times the size, up to 13.
 */
export function nodeRadius(geo: Geo, size: number): ExpressionSpecification {
	const z = zoomAt(geo, 0.45);
	const r = Math.max(2, 0.45 * 8) * size;
	const zCap = zoomAt(geo, 13 / 8);
	// the dots: 2.2 px radius (1.5 with soft edges looked like 1 px and vanished into the ground: user)
	if (zCap <= z + 0.02) return ["step", ["zoom"], 2.2, z, 13 * size];
	return ["interpolate", ["exponential", 2], ["zoom"], z, 2.2, z + 0.01, Math.max(r, 2.2), zCap, 13 * size];
}

/** Icons in a row: their place (-2 .. 2 in halves). Model heights: 0 .. 440 atlas units in steps of 10. */
const ICON_SLOTS = ["-2", "-1.5", "-1", "-0.5", "0", "0.5", "1", "1.5", "2"];
const ICON_LIFTS = Array.from({ length: 45 }, (_, k) => k * 10);
/** How tall a height looks next to the same length across the screen, at the game's camera angle (sin 59 deg). */
const UPRIGHT = 0.857;

/**
 * Where a 3D view icon is drawn, in its picture's px (64 px = 26 units): its place in the row (36 units apart) and
 * its bottom 11 units above the map node, on top of the 3D model under it while models are shown (user: city icons
 * sat inside the city).
 */
function iconOffset(geo: Geo, models: boolean): ExpressionSpecification {
	void geo;
	const px = 64 / 26;
	const at = (slot: string, lift: number) => ["literal", [Number(slot) * 36 * px, -(11 + lift * UPRIGHT) * px]];
	if (!models)
		return [
			"match",
			["get", "slot"],
			...ICON_SLOTS.flatMap((k) => [k, at(k, 0)]),
			at("0", 0),
		] as unknown as ExpressionSpecification;
	return [
		"match",
		["concat", ["get", "slot"], "|", ["to-string", ["get", "lift"]]],
		...ICON_SLOTS.flatMap((k) => ICON_LIFTS.flatMap((l) => [`${k}|${l}`, at(k, l)])),
		at("0", 0),
	] as unknown as ExpressionSpecification;
}

/** Apply the settings to the map's layers (visibility, colours, sizes, filters). */
export function applyLook(map: MapLibreMap, geo: Geo, meta: Meta, look: Look): void {
	const { settings: s } = look;
	const L = s.layers;
	const st = s.style;
	const on = (k: string) => L[k] !== false;

	// background: the picture, the vector ground (land and biome areas), or nothing
	visible(map, "terrain", look.background === "picture" && on("Terrain"));
	visible(map, "land", look.background === "vector");
	setPaint(map, "biomes", "fill-opacity", look.background === "vector" ? 0.8 : 0.28);
	for (const [group, ids] of Object.entries(LAYER_GROUPS)) {
		if (group === "Terrain" || group === "Nodes") continue;
		for (const id of ids) visible(map, id, on(group));
	}
	visible(map, "removed", on("Removed"));
	visible(map, "tint", false); // Colour by is drawn as one picture (MapTint)

	// biome colours: the city tints of the View tab, the ground kinds' own
	const cities = cityColours(meta, st);
	const biomeColour: ExpressionSpecification = [
		"match",
		["get", "kind"],
		...Object.entries({ ...meta.colours.biome, ...cities }).flat(),
		"#888888",
	] as unknown as ExpressionSpecification;
	setPaint(map, "biomes", "fill-color", biomeColour);
	setPaint(map, "biomes-line", "line-color", biomeColour);

	// paths
	const strong = styleColour(st, "path_col", meta.colours.path_multi);
	const weak = styleColour(st, "path_col1", meta.colours.path_single);
	setPaint(map, "paths", "line-color", [
		"case",
		["get", "abyss"],
		meta.colours.path_abyss,
		["get", "strong"],
		strong,
		weak,
	]);
	// the width is the px at 1 px per atlas unit; it scales with the map (up to 1.6 px per unit), so dashes keep
	// their place along the path as you zoom
	const w = Number(st.path_width) || 2.5;
	// at least 1 px, like the old window's (thinner paths were hard to see zoomed out: user)
	setPaint(map, "paths", "line-width", worldSize(geo, st.path_style === "dotted" ? 1.6 * w : w, 1, 1.6));
	setPaint(
		map,
		"paths",
		"line-dasharray",
		st.path_style === "dashed" ? [3, 2] : st.path_style === "dotted" ? [0.1, 2] : [1, 0],
	);
	if (map.getLayer("paths")) map.setLayoutProperty("paths", "line-cap", st.path_style === "dotted" ? "round" : "butt");

	// maps: circles, squares or hidden; the ring by status (or the View tab's colour), filled with the icon's
	const size = Number(st.map_size) || 1;
	const statusColour: ExpressionSpecification = [
		"match",
		["get", "status"],
		...Object.entries(meta.colours.node).flat(),
		"#ffffff",
	] as unknown as ExpressionSpecification;
	const mapColour = typeof st.map_col === "string" && st.map_col ? st.map_col : statusColour;
	// solid: filled with the map's colour (the old window's dots; user: the black inside hid the colour); bordered:
	// the icon's colour inside a border of its own colour (or the map's colour)
	const solid = st.map_fill !== "bordered";
	const iconFill: ExpressionSpecification = [
		"case",
		["==", ["get", "fill"], ""],
		meta.colours.no_icon,
		["get", "fill"],
	];
	const fill = solid ? mapColour : iconFill;
	const ringColour = solid
		? "rgba(0,0,0,0.55)"
		: typeof st.map_border === "string" && st.map_border
			? st.map_border
			: mapColour;
	const nodes = on("Nodes") && st.map_style !== "hidden";
	// as the old window: zoomed out (under 0.45 px per unit) every style is a dot in the map's colour; above that the
	// style's own look (circles / squares / the map picture) takes over and grows with the zoom (user: the map pictures
	// stayed on zoomed out, and the dots never turned into the style)
	const zDots = zoomAt(geo, 0.45);
	const z07 = zoomAt(geo, 0.7);
	const circles = st.map_style !== "squares" && st.map_style !== "map icons";
	visible(map, "maps", nodes);
	visible(map, "maps-square", nodes && st.map_style === "squares");
	visible(map, "maps-icon", nodes && st.map_style === "map icons");
	if (map.getLayer("maps")) map.setLayerZoomRange("maps", 0, circles ? 24 : zDots);
	if (map.getLayer("maps-square")) map.setLayerZoomRange("maps-square", zDots, 24);
	if (map.getLayer("maps-icon")) map.setLayerZoomRange("maps-icon", zDots, 24);
	// the picture is 49 px, drawn 2.8 map node radii wide (the old window's size), up to the 13 px radius
	if (map.getLayer("maps-icon"))
		map.setLayoutProperty("maps-icon", "icon-size", worldSize(geo, (22.4 * size) / 49, (10 * size) / 49, 13 / 8));
	setPaint(map, "maps", "circle-radius", nodeRadius(geo, size));
	setPaint(map, "maps", "circle-color", ["step", ["zoom"], mapColour, zDots, fill]);
	setPaint(map, "maps", "circle-stroke-width", ["step", ["zoom"], 0, zDots, solid ? 0.6 : 1, z07, solid ? 0.6 : 2]);
	setPaint(map, "maps", "circle-stroke-color", ringColour);
	setPaint(map, "maps-square", "icon-color", solid ? mapColour : ringColour);
	if (map.getLayer("maps-square")) {
		map.setLayoutProperty("maps-square", "icon-image", solid ? "node-square-solid" : "node-square");
		// a 32 px picture: half of it is the 8 units of a map node's radius, up to 13 px
		map.setLayoutProperty("maps-square", "icon-size", worldSize(geo, (16 * size) / 32, (7 * size) / 32, 13 / 8));
	}

	// landmarks by kind (locked strongholds and removed ones in their own colours)
	const lm = landmarkColours(meta, st);
	setPaint(map, "landmarks", "circle-stroke-color", [
		"case",
		["get", "removed"],
		meta.colours.removed,
		["get", "locked"],
		lm["Locked stronghold"] ?? "#966496",
		["match", ["get", "kind"], ...Object.entries(lm).flat(), "#c8c8c8"],
	] as unknown as ExpressionSpecification);

	visible(map, "towers", !!st.ov_towers && on("Landmarks"));

	// 3D models while tilted; icons above them then
	visible(map, "solids", look.tilted && on("3D models"));
	// icons: on the ground when flat, standing in rows above their map nodes when tilted
	visible(map, "icons", on("Icons") && !look.tilted);
	visible(map, "icons-3d", false); // the 3D view's icons are drawn by IconLayer3D
	const models = look.tilted && on("3D models");
	if (map.getLayer("icons-3d")) map.setLayoutProperty("icons-3d", "icon-offset", iconOffset(geo, models));
	// the flat map node dots would show through the bottom of the 3D pillars (user)
	if (models) for (const id of ["maps", "maps-square", "maps-icon"]) visible(map, id, false);
	// paths tilted: drawn by PathLayer3D (raised, one width on screen)
	if (look.tilted) visible(map, "paths", false);

	// Find: a type highlighted
	setFilter(map, "highlight", look.highlight ? ["in", `|${look.highlight}|`, ["get", "icons"]] : NONE);

	// the replay: what isn't revealed yet lies under the fog, which is drawn over the map's layers while replaying
	// (ReplayLayers). Per-item opacity or filters by step made MapLibre redo every feature (13k paths) each frame:
	// the page fell seconds behind and kept going after a pause (user). The 3D models stand above the fog, so they
	// keep a filter by step (only while tilted).
	const pos = look.replayPos;
	setFilter(map, "solids", pos === null || !look.tilted ? null : ["<", ["coalesce", ["get", "step"], 0], pos]);
	// the tower pictures only on Towers, always (CodeRabbit: the replay filter replaced it)
	setFilter(map, "towers", ["==", ["get", "kind"], "Tower"]);
	// bookmarks are not part of how the atlas was made: hidden while replaying (user: they showed from the start)
	if (look.replayPos !== null) visible(map, "bookmarks", false);
}

/** Put a GeoJSON source's data. */
export function setData(map: MapLibreMap, id: GeoJsonSourceId, data: GeoJSON.GeoJSON): void {
	(map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
}

/** Show (or update, or remove with url null) a picture over 4 corners, under the layer `before`. */
export function setImage(
	map: MapLibreMap,
	id: string,
	url: string | null,
	coordinates: [[number, number], [number, number], [number, number], [number, number]] | null,
	before: string,
	opacity = 1,
): void {
	const src = map.getSource(id) as ImageSource | undefined;
	if (!url || !coordinates) {
		if (map.getLayer(id)) map.removeLayer(id);
		if (src) map.removeSource(id);
		return;
	}
	if (src) src.updateImage({ url, coordinates });
	else map.addSource(id, { type: "image", url, coordinates });
	if (!map.getLayer(id))
		map.addLayer(
			{ id, type: "raster", source: id, paint: { "raster-fade-duration": 0, "raster-opacity": opacity } },
			before,
		);
	else map.setPaintProperty(id, "raster-opacity", opacity);
}

/** A white square for the "squares" map style, tinted by icon-color (an SDF image): hollow, or filled. */
export function squareImage(filled = false): { width: number; height: number; data: Uint8Array } {
	const n = 32;
	const data = new Uint8Array(n * n * 4);
	for (let y = 0; y < n; y++)
		for (let x = 0; x < n; x++) {
			const d = Math.min(x, y, n - 1 - x, n - 1 - y);
			const v = d >= 3 && (filled || d <= 7) ? 255 : 0; // the ring, or the whole square
			const i = (y * n + x) * 4;
			data[i] = 255;
			data[i + 1] = 255;
			data[i + 2] = 255;
			data[i + 3] = v;
		}
	return { width: n, height: n, data };
}
