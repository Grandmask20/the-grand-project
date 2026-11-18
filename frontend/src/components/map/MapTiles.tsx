import type { Map as MapLibreMap, RasterTileSource, VectorTileSource } from "maplibre-gl";
import { useEffect } from "react";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";

/** The vector tiles' version: they change with the model, the filters and the map image (its ground shapes). */
export function vectorVersion(
	info: Pick<MapInfo, "tile_key" | "model_version" | "filter_version" | "terrain_version">,
): string {
	return `${info.tile_key}-${info.model_version}-${info.filter_version}-${info.terrain_version}`;
}

/** The ground tiles' version: the app run and atlas (tile_key) and the map image's version. */
export function terrainVersion(info: Pick<MapInfo, "tile_key" | "terrain_version">): string {
	return `${info.tile_key}-${info.terrain_version}`;
}

/** Points the map's tile sources at the current versions (a changed atlas, map image or filter is fetched again). */
export function MapTiles({ map }: { map: MapLibreMap }) {
	const app = useAppClient();
	const info = useAppState().data?.map;
	const terrain = info ? terrainVersion(info) : undefined;
	const vector = info ? vectorVersion(info) : null;
	// the timelapse's tiles only in the tab playing it (other tabs, and this one after a reload, get the plain ones)
	const replay = useAppStore((s) => s.replay?.plan.token);

	useEffect(() => {
		if (terrain === undefined) return;
		(map.getSource("terrain") as RasterTileSource | undefined)?.setTiles([app.terrainTiles(terrain)]);
	}, [map, app, terrain]);

	// the zoomed-out ground fetched ahead (few tiles): zooming far out from close in, the map nodes and paths were
	// there long before the ground (user: blobs over black)
	const bounds = info ? JSON.stringify(info.bounds) : null; // (a new array with every state)
	useEffect(() => {
		if (terrain === undefined || !bounds) return;
		const urls = groundAhead(app.terrainTiles(terrain), JSON.parse(bounds));
		let stop = false;
		const next = async () => {
			for (let url = urls.shift(); url && !stop; url = urls.shift())
				await fetch(url).then(
					(r) => r.arrayBuffer(),
					() => undefined,
				);
		};
		// after the first view has loaded, a few at a time (the view's own tiles first)
		const start = setTimeout(() => {
			for (let k = 0; k < PREFETCH_PARALLEL; k++) void next();
		}, PREFETCH_DELAY_MS);
		return () => {
			stop = true;
			clearTimeout(start);
		};
	}, [app, terrain, bounds]);

	useEffect(() => {
		if (vector === null) return;
		(map.getSource("atlas") as VectorTileSource | undefined)?.setTiles([app.vectorTiles(vector, replay)]);
	}, [map, app, vector, replay]);

	return null;
}

const PREFETCH_TILES = 340; // the most ground tiles fetched ahead (every level down to where the atlas needs more)
const PREFETCH_PARALLEL = 3;
const PREFETCH_DELAY_MS = 1500;

/**
 * The ground tile URLs of the zoomed-out levels, coarsest first, as long as they stay within PREFETCH_TILES.
 *
 * @param template The ground tile URL with {z}/{x}/{y}.
 * @param bounds The atlas's [[west, south], [east, north]].
 */
export function groundAhead(template: string, bounds: [[number, number], [number, number]]): string[] {
	const [[w, s], [e, n]] = bounds;
	const tx = (lng: number, z: number) => Math.floor(((lng + 180) / 360) * 2 ** z);
	const ty = (lat: number, z: number) => {
		const r = (Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180;
		return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
	};
	const out: string[] = [];
	for (let z = 0; z <= 24; z++) {
		const x0 = Math.max(0, tx(w, z));
		const x1 = Math.min(2 ** z - 1, tx(e, z));
		const y0 = Math.max(0, ty(n, z));
		const y1 = Math.min(2 ** z - 1, ty(s, z));
		const count = (x1 - x0 + 1) * (y1 - y0 + 1);
		if (out.length + count > PREFETCH_TILES) break;
		for (let y = y0; y <= y1; y++)
			for (let x = x0; x <= x1; x++)
				out.push(template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y)));
	}
	return out;
}
