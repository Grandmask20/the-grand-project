import type { LayerSpecification } from "maplibre-gl";
import type { Meta } from "@/domain/app/Meta";
import type { Geo } from "@/logic/Geo";
import { findRing, visibility } from "./AtlasLayers";
import { ringRadius, worldSize } from "./Sizes";

/**
 * The layers of what the page draws over the tiles, each over a GeoJSON source of the same name (the source a layer
 * names is the one the component drawing it fills). `on` shows or hides them.
 */
type Spec = LayerSpecification;

const hollow = (colour: string, width: number) => ({
	"circle-color": "rgba(0,0,0,0)",
	"circle-stroke-color": colour,
	"circle-stroke-width": width,
});

/** The selection: a ring on a map node or an icon, or a whole path lit up (as the old window). */
export function selectionLayers(geo: Geo, meta: Meta, ringOn: boolean): Spec[] {
	return [
		{
			id: "selected-path",
			type: "line",
			source: "selected-path",
			layout: { "line-cap": "round", "line-join": "round" },
			paint: { "line-color": meta.colours.select, "line-width": 4, "line-opacity": 0.95 },
		},
		{
			id: "selected",
			type: "circle",
			source: "selected",
			layout: { visibility: visibility(ringOn) },
			paint: {
				"circle-radius": ringRadius(geo, 10),
				...hollow(meta.colours.select, 3),
				"circle-color": "rgba(255,255,255,0.10)",
			},
		},
	];
}

/** A search's results, ringed as Find's highlight is. */
export const hitLayers = (geo: Geo, meta: Meta): Spec[] => findRing("hits", { source: "hits" }, geo, meta);

/** The red mark of a go-to. */
export const gotoLayer = (): Spec => ({
	id: "goto",
	type: "circle",
	source: "goto",
	paint: { "circle-radius": 12, ...hollow("#ff4040", 3) },
});

/** The route: a green line edged in black (`route`) and its maps ringed (`route-nodes`). */
export function routeLayers(geo: Geo, on: boolean): { line: Spec[]; nodes: Spec; here: Spec } {
	const layout = { visibility: visibility(on), "line-cap": "round" as const, "line-join": "round" as const };
	return {
		line: [
			{
				id: "route-casing",
				type: "line",
				source: "route",
				layout,
				paint: { "line-color": "#000000", "line-width": 9, "line-opacity": 0.7 },
			},
			{ id: "route", type: "line", source: "route", layout, paint: { "line-color": "#7cff6b", "line-width": 5 } },
		],
		nodes: {
			id: "route-nodes",
			type: "circle",
			source: "route-nodes",
			layout: { visibility: visibility(on) },
			paint: { "circle-radius": ringRadius(geo, 1), ...hollow("#7cff6b", 3) },
		},
		// the map you are on, on a route tracked: filled, so it stands out from the rings still to run
		here: {
			id: "route-here",
			type: "circle",
			source: "route-here",
			layout: { visibility: visibility(on) },
			paint: {
				"circle-radius": ringRadius(geo, 1),
				"circle-color": "#7cff6b",
				"circle-opacity": 0.55,
				"circle-stroke-color": "#000000",
				"circle-stroke-width": 2,
			},
		},
	};
}

/** The screenshots added last, outlined, the newest brightest. */
export const recentLayer = (meta: Meta, on: boolean): Spec => ({
	id: "recent",
	type: "line",
	source: "recent",
	layout: { visibility: visibility(on) },
	paint: {
		"line-color": ["case", ["get", "picked"], "#ffffff", meta.colours.recent],
		"line-width": ["case", ["==", ["get", "age"], 0], 3, 2],
		"line-opacity": ["get", "opacity"],
	},
});

/** The bookmarks, as dots a little above their spot. */
/** A bookmark pin's radius in screen px: `size` times the pin's atlas units, growing with the zoom as the map's
 * icons do (user: the pins were tiny and didn't scale), from 3 px far out to twice its units close in. */
const pinRadius = (geo: Geo, meta: Meta, size: number) => worldSize(geo, meta.bookmark_pin * size, 3 * size, 2);

export const bookmarkLayer = (geo: Geo, meta: Meta, on: boolean, size = 1): Spec => {
	return {
		id: "bookmarks",
		type: "circle",
		source: "bookmarks",
		// the pin: for a bookmark without an icon, or round its icon (not a symbol's, nor one without a ring)
		filter: ["any", ["==", ["get", "icon"], ""], ["==", ["get", "ring"], true]],
		layout: { visibility: visibility(on) },
		paint: {
			// (a pin with an icon: a ring of its colour round it, the icon inside: bookmarkIconLayer)
			"circle-radius": pinRadius(geo, meta, size),
			// its own colour, else its group's (BookmarkLayer), else the page's
			"circle-color": ["coalesce", ["get", "colour"], meta.colours.bookmark],
			"circle-stroke-color": "#000000",
			"circle-stroke-width": 1.5,
		},
	};
};

/** The icons of bookmarks that have one (their own or their group's: user), on their pins. The pictures are the map
 * icons' (MapSprites loads one when it is first asked for). */
export const bookmarkIconLayer = (geo: Geo, meta: Meta, on: boolean, size = 1): Spec => ({
	id: "bookmark-icons",
	type: "symbol",
	source: "bookmarks",
	filter: ["!=", ["get", "icon"], ""],
	layout: {
		visibility: visibility(on),
		"icon-image": ["get", "icon"],
		// the pictures are 64 px: 0.8 of the pin's width, growing with it
		"icon-size": worldSize(geo, (1.6 * meta.bookmark_pin * size) / 64, (4.8 * size) / 64, 2),
		"icon-allow-overlap": true,
		"icon-ignore-placement": true,
	},
});

/** The saved routes shown (Bookmarks: a route's eye): their lines, dashed in the bookmarks' colour, a branch (a map
 * added off a route's side) in its own colour (user's sketch: the branch apart from the main path), under the route
 * being tracked. */
export const savedRouteLayer = (meta: Meta, on: boolean): Spec => ({
	id: "saved-routes",
	type: "line",
	source: "saved-routes",
	layout: { visibility: visibility(on), "line-cap": "round", "line-join": "round" },
	paint: {
		"line-color": ["case", ["get", "branch"], ROUTE_BRANCH, meta.colours.bookmark],
		"line-width": 3,
		"line-opacity": 0.85,
		"line-dasharray": [2, 1.5],
	},
});

/** A saved route's branches on the map. */
export const ROUTE_BRANCH = "#4dff6a"; // green, as in the user's sketch (a light blue was lost among the paths)

/** The saved route lit up (clicked in Bookmarks, or its maps being changed): its lines in the selection's colour and
 * its maps ringed, as a selection is, whatever the switches and its eye say. */
export function litRouteLayers(geo: Geo, meta: Meta): Spec[] {
	return [
		{
			id: "route-lit",
			type: "line",
			source: "route-lit",
			filter: ["==", ["geometry-type"], "LineString"],
			layout: { "line-cap": "round", "line-join": "round" },
			paint: {
				"line-color": ["case", ["get", "branch"], ROUTE_BRANCH, meta.colours.select],
				"line-width": 4,
				"line-opacity": 0.95,
			},
		},
		{
			id: "route-lit-maps",
			type: "circle",
			source: "route-lit",
			filter: ["==", ["geometry-type"], "Point"],
			paint: { "circle-radius": ringRadius(geo, 7), ...hollow(meta.colours.select, 2) },
		},
	];
}

/** The debug marks: lines between two maps (dashed for a missing path) and rings on the spot. */
export function markLayers(on: boolean): Spec[] {
	const layout = { visibility: visibility(on) };
	const lineOf = ["==", ["geometry-type"], "LineString"];
	return [
		{
			id: "marks-line",
			type: "line",
			source: "marks",
			filter: ["all", lineOf, ["!=", ["get", "kind"], "missing path"]],
			layout,
			paint: { "line-color": "#ff00ff", "line-width": 2 },
		},
		{
			id: "marks-dashed",
			type: "line",
			source: "marks",
			filter: ["all", lineOf, ["==", ["get", "kind"], "missing path"]],
			layout,
			paint: { "line-color": "#ff00ff", "line-width": 2, "line-dasharray": [1, 2] },
		},
		{
			id: "marks-point",
			type: "circle",
			source: "marks",
			filter: ["==", ["geometry-type"], "Point"],
			layout,
			paint: { "circle-radius": 9, ...hollow("#ff00ff", 2) },
		},
	] as Spec[];
}

/** The outline of the screenshot being placed by hand. */
export const ghostLineLayer = (): Spec => ({
	id: "ghost-line",
	type: "line",
	source: "ghost-line",
	paint: { "line-color": "#ffdc00", "line-width": 2 },
});

/** A question's screenshot, outlined (the dialog says so), and the maps it agrees with: what it would join (user:
 * it wasn't visible what it connected to). */
export const previewLayers = (): Spec[] => [
	{
		id: "preview-line",
		type: "line",
		source: "preview-line",
		paint: { "line-color": "#ffdc00", "line-width": 2, "line-dasharray": [3, 2] },
	},
	{
		id: "preview-agree",
		type: "circle",
		source: "preview-agree",
		paint: { "circle-radius": 9, ...hollow("#ffdc00", 2.5) },
	},
];

/** The screenshots coming in while the timelapse plays: only the current step's outline shows (by opacity, at once:
 * setting new outline data on every step was handled in the background and trailed the replay, user). */
export const outlineLayer = (step: number | null): Spec => ({
	id: "outline",
	type: "line",
	source: "outline",
	paint: {
		"line-color": "#ffffff",
		"line-width": 1.2,
		"line-opacity": step === null ? 0 : ["case", ["==", ["get", "step"], step], 0.9, 0],
	},
});
