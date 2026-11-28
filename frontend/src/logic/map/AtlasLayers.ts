import type { ExpressionSpecification, FilterSpecification, LayerSpecification } from "maplibre-gl";
import type { Meta } from "@/domain/app/Meta";
import type { Background, UiSettings } from "@/domain/app/UiSettings";
import type { MapInfo } from "@/domain/map/MapInfo";
import { cityColours, landmarkColours, styleColour } from "@/logic/Colours";
import type { Geo } from "@/logic/Geo";
import { iconMinZoom, iconSize, nodeRadius, ringRadius, worldSize, zoomAt } from "./Sizes";

/** Everything that decides how the atlas's own layers look besides their tiles. */
export interface Look {
	settings: UiSettings;
	background: Background;
	/** The map tilted: the 3D layers draw paths, icons and models instead. */
	tilted: boolean;
	/** Find: the type whose maps are ringed. */
	highlight: string | null;
}

/** The source the app's vector tiles are in. */
export const ATLAS = "atlas";

/** Size of Find's ring past the selection ring's (ring(10) plus its stroke), so it lies outside it. */
export const FIND_RING = 15;

export const NONE: FilterSpecification = ["==", ["get", "id"], -1];

/** A "Show on the map" toggle: on unless switched off (settings without their layers yet: all on). */
export const layerOn = (settings: UiSettings, group: string): boolean => settings.layers?.[group] !== false;

export const visibility = (on: boolean) => (on ? ("visible" as const) : ("none" as const));

type Spec<T extends LayerSpecification["type"]> = Extract<LayerSpecification, { type: T }>;

/**
 * Find's ring as two circle layers: `<id>-edge`, a wide black stroke, then `<id>`, a narrower white one on the same
 * circle, which leaves a black edge on both sides of the white ring. Outside the yellow selection ring, so a result
 * and the selection never look alike (user's mock-up: the two were both yellow in 3D).
 */
export function findRing(
	id: "highlight" | "hits",
	from: { source: string; "source-layer"?: string; filter?: FilterSpecification },
	geo: Geo,
	meta: Meta,
): [Spec<"circle">, Spec<"circle">] {
	const radius = ringRadius(geo, FIND_RING);
	const ring = (layer: string, colour: string, width: number): Spec<"circle"> => ({
		id: layer,
		type: "circle",
		...from,
		paint: {
			"circle-radius": radius,
			"circle-color": "rgba(0,0,0,0)",
			"circle-stroke-color": colour,
			"circle-stroke-width": width,
		},
	});
	return [ring(`${id}-edge`, "#000000", 6), ring(id, meta.colours.hit, 2.5)];
}

/** The ground drawn from the tiles' shapes (Background: shapes) and the city and stronghold biomes. */
export function groundLayers(meta: Meta, look: Look): LayerSpecification[] {
	const st = look.settings.style;
	const biomeColour = [
		"match",
		["get", "kind"],
		...Object.entries({ ...meta.colours.biome, ...cityColours(meta, st) }).flat(),
		"#888888",
	] as unknown as ExpressionSpecification;
	const biomes = visibility(layerOn(look.settings, "City & stronghold biomes"));
	return [
		{
			id: "land",
			type: "fill",
			source: ATLAS,
			"source-layer": "land",
			layout: { visibility: visibility(look.background === "vector") },
			paint: { "fill-color": meta.colours.land },
		},
		{
			id: "biomes",
			type: "fill",
			source: ATLAS,
			"source-layer": "biomes",
			layout: { visibility: biomes },
			paint: { "fill-color": biomeColour, "fill-opacity": look.background === "vector" ? 0.8 : 0.28 },
		},
		{
			id: "biomes-line",
			type: "line",
			source: ATLAS,
			"source-layer": "biomes",
			layout: { visibility: biomes },
			paint: { "line-color": biomeColour, "line-width": 1.5, "line-opacity": 0.8 },
		},
	];
}

/** The paths drawn by at least `freq` of the screenshots that show both their map nodes (Abyss chains always; tiles
 * from before paths carried their share show every path). */
export function pathShareFilter(freq: number): FilterSpecification {
	return ["any", ["get", "abyss"], [">=", ["coalesce", ["get", "share"], 1], freq - 1e-9]] as FilterSpecification;
}

/** The paths between map nodes in the View tab's colours and style (flat only: tilted, PathLayer3D draws them). */
export function pathLayer(geo: Geo, meta: Meta, look: Look): Spec<"line"> {
	const st = look.settings.style;
	// the width is the px at 1 px per atlas unit; it scales with the map (up to 1.6 px per unit), so dashes keep
	// their place along the path as you zoom. At least 1 px, like the old window's (thinner paths were hard to see
	// zoomed out: user)
	const w = Number(st.path_width) || 2.5;
	return {
		id: "paths",
		type: "line",
		source: ATLAS,
		"source-layer": "paths",
		// "drawn by at least": hidden here by each path's share, not in new tiles, so the slider is live while dragged
		// (user: each step remade every tile)
		filter: pathShareFilter(Number(st.path_freq) || 0),
		layout: {
			visibility: visibility(layerOn(look.settings, "Paths") && !look.tilted),
			"line-cap": st.path_style === "dotted" ? "round" : "butt",
			"line-join": "round",
		},
		paint: {
			"line-color": [
				"case",
				["get", "abyss"],
				meta.colours.path_abyss,
				["get", "strong"],
				styleColour(st, "path_col", meta.colours.path_multi),
				styleColour(st, "path_col1", meta.colours.path_single),
			],
			"line-opacity": 0.9,
			"line-width": worldSize(geo, st.path_style === "dotted" ? 1.6 * w : w, 1, 1.6),
			"line-dasharray": st.path_style === "dashed" ? [3, 2] : st.path_style === "dotted" ? [0.1, 2] : [1, 0],
		},
	};
}

/**
 * A map node's colour: its state's (grey / blue / green / red, named by finalize.states) whatever its status or the
 * View tab's map colour, else `fallback` (no screenshot named its state).
 */
function stateColour(meta: Meta, fallback: ExpressionSpecification | string): ExpressionSpecification {
	const states = Object.entries(meta.colours.node_state).flat();
	return ["match", ["get", "state"], ...states, fallback] as unknown as ExpressionSpecification;
}

/**
 * The map nodes in the View tab's style: circles, squares, the game's map node picture, or hidden. As the old window,
 * zoomed out (under 0.45 px per unit) every style is a dot in the map's colour; above that the style's own look takes
 * over and grows with the zoom (user: the map pictures stayed on zoomed out, and the dots never turned into the style).
 */
export function nodeLayers(geo: Geo, meta: Meta, look: Look): LayerSpecification[] {
	const st = look.settings.style;
	const size = Number(st.map_size) || 1;
	const statusColour = [
		"match",
		["get", "status"],
		...Object.entries(meta.colours.node).flat(),
		"#ffffff",
	] as unknown as ExpressionSpecification;
	const mapColour = stateColour(meta, typeof st.map_col === "string" && st.map_col ? st.map_col : statusColour);
	// solid: filled with the map's colour (the old window's dots; user: the black inside hid the colour); bordered:
	// the icon's colour inside a border of its own colour (or the map's colour)
	const solid = st.map_fill !== "bordered";
	const iconFill: ExpressionSpecification = [
		"case",
		["==", ["get", "fill"], ""],
		meta.colours.no_icon,
		["get", "fill"],
	];
	const ringColour = solid
		? "rgba(0,0,0,0.55)"
		: typeof st.map_border === "string" && st.map_border
			? st.map_border
			: mapColour;
	// tilted with the 3D models on, the flat map node dots would show through the bottom of their pillars (user)
	const shown =
		layerOn(look.settings, "Nodes") &&
		st.map_style !== "hidden" &&
		!(look.tilted && layerOn(look.settings, "3D models"));
	const zDots = zoomAt(geo, 0.45);
	const z07 = zoomAt(geo, 0.7);
	const circles = st.map_style !== "squares" && st.map_style !== "map icons";
	const from = { source: ATLAS, "source-layer": "maps" };
	return [
		{
			id: "maps",
			type: "circle",
			...from,
			minzoom: 0,
			maxzoom: circles ? 24 : zDots,
			layout: { visibility: visibility(shown) },
			paint: {
				"circle-radius": nodeRadius(geo, size),
				"circle-color": ["step", ["zoom"], mapColour, zDots, solid ? mapColour : iconFill],
				"circle-stroke-width": ["step", ["zoom"], 0, zDots, solid ? 0.6 : 1, z07, solid ? 0.6 : 2],
				"circle-stroke-color": ringColour,
			},
		},
		{
			id: "maps-square",
			type: "symbol",
			...from,
			minzoom: zDots,
			maxzoom: 24,
			layout: {
				visibility: visibility(shown && st.map_style === "squares"),
				"icon-image": solid ? "node-square-solid" : "node-square",
				// a 32 px picture: half of it is the 8 units of a map node's radius, up to 13 px
				"icon-size": worldSize(geo, (16 * size) / 32, (7 * size) / 32, 13 / 8),
				"icon-allow-overlap": true,
				"icon-ignore-placement": true,
			},
			paint: { "icon-color": solid ? mapColour : ringColour },
		},
		{
			// the "map icons" style: the game's map node picture (references/map_node_icon.webp), as the old window. The
			// picture is 49 px, drawn 2.8 map node radii wide (the old window's size), up to the 13 px radius
			id: "maps-icon",
			type: "symbol",
			...from,
			minzoom: zDots,
			maxzoom: 24,
			layout: {
				visibility: visibility(shown && st.map_style === "map icons"),
				"icon-image": "node-picture",
				"icon-size": worldSize(geo, (22.4 * size) / 49, (10 * size) / 49, 13 / 8),
				"icon-allow-overlap": true,
				"icon-ignore-placement": true,
			},
		},
	];
}

/** The map content icons: the game's pictures on the ground (flat only: tilted, IconLayer3D stands them up). */
export function iconLayer(geo: Geo, info: MapInfo, look: Look): Spec<"symbol"> {
	return {
		id: "icons",
		type: "symbol",
		source: ATLAS,
		"source-layer": "icons",
		minzoom: iconMinZoom(geo, info),
		layout: {
			visibility: visibility(layerOn(look.settings, "Icons") && !look.tilted),
			"icon-image": ["get", "name"],
			"icon-size": iconSize(geo, info, Number(look.settings.style.icon_size) || 1),
			"icon-allow-overlap": true,
			"icon-ignore-placement": true,
		},
	};
}

/** Landmarks ringed by kind (locked strongholds and removed ones in their own colours). */
export function landmarkLayers(geo: Geo, meta: Meta, look: Look): LayerSpecification[] {
	const st = look.settings.style;
	const on = layerOn(look.settings, "Landmarks");
	const lm = landmarkColours(meta, st);
	return [
		{
			id: "landmarks",
			type: "circle",
			source: ATLAS,
			"source-layer": "landmarks",
			layout: { visibility: visibility(on) },
			paint: {
				"circle-radius": worldSize(geo, 14, 4),
				"circle-color": "rgba(0,0,0,0)",
				"circle-stroke-width": worldSize(geo, 2.2, 1),
				"circle-stroke-color": [
					"case",
					["get", "removed"],
					meta.colours.removed,
					["get", "locked"],
					lm["Locked stronghold"] ?? "#966496",
					["match", ["get", "kind"], ...Object.entries(lm).flat(), "#c8c8c8"],
				] as unknown as ExpressionSpecification,
			},
		},
	];
}

/** The maps taken out of the atlas, ringed where they were. */
export function removedLayer(geo: Geo, meta: Meta, look: Look): Spec<"circle"> {
	return {
		id: "removed",
		type: "circle",
		source: ATLAS,
		"source-layer": "removed",
		layout: { visibility: visibility(layerOn(look.settings, "Removed")) },
		paint: {
			"circle-radius": worldSize(geo, 7, 1.5),
			"circle-color": "rgba(0,0,0,0)",
			"circle-stroke-color": meta.colours.removed,
			"circle-stroke-width": 2,
		},
	};
}

/** Find: the maps of the type listed, ringed. */
export function highlightLayers(geo: Geo, meta: Meta, look: Look): LayerSpecification[] {
	const filter: FilterSpecification = look.highlight ? ["in", `|${look.highlight}|`, ["get", "icons"]] : NONE;
	return findRing("highlight", { source: ATLAS, "source-layer": "maps", filter }, geo, meta);
}

/** Every layer drawn from the app's vector tiles. */
export function atlasLayers(geo: Geo, info: MapInfo, meta: Meta, look: Look): LayerSpecification[] {
	return [
		...groundLayers(meta, look),
		pathLayer(geo, meta, look),
		removedLayer(geo, meta, look),
		iconLayer(geo, info, look),
		...nodeLayers(geo, meta, look),
		...landmarkLayers(geo, meta, look),
		...highlightLayers(geo, meta, look),
	];
}
