import type { ExpressionSpecification } from "maplibre-gl";
import type { MapInfo } from "@/domain/map/MapInfo";
import type { Geo } from "@/logic/Geo";

/** The map zoom where a size in atlas units is `px` screen px. */
export const zoomAt = (geo: Geo, px: number): number => geo.zoomFor(px);

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

/** A ring around a map node (selection, Find, route): `extra` px past the node, growing with it. */
export function ringRadius(geo: Geo, extra: number): ExpressionSpecification {
	return ["interpolate", ["exponential", 2], ["zoom"], zoomAt(geo, 0.25), 4 + extra, zoomAt(geo, 1.6), 16 + extra];
}

/** The zoom from which icons are drawn: from where one is sprite.min_px across. */
export const iconMinZoom = (geo: Geo, info: MapInfo): number =>
	Math.min(info.maxzoom - 0.5, geo.zoomFor(info.sprite.min_px / info.sprite.units));

/** An icon's size: the game's pictures at their own size on the ground (sprite.units atlas units), times `scale`. */
export function iconSize(geo: Geo, info: MapInfo, scale: number): ExpressionSpecification {
	const sp = info.sprite;
	const at = (z: number) => (scale * sp.units * geo.pxPerUnit(z)) / sp.size;
	const z0 = iconMinZoom(geo, info);
	return ["interpolate", ["exponential", 2], ["zoom"], z0, at(z0), info.maxzoom, at(info.maxzoom)];
}

/** How many screen px an icon spans at this zoom (MapLabels: their names show once they are big enough). */
export const iconPx = (geo: Geo, info: MapInfo, zoom: number, scale: number): number =>
	scale * info.sprite.units * geo.pxPerUnit(zoom);
