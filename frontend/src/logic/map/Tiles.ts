import type { MapInfo } from "@/domain/map/MapInfo";

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

/**
 * The ground version drawn under the map's own (the backdrop): while a job runs (adding, re-checking), the one from
 * before its changes, so the old ground shows wherever the new hasn't come in yet, also where the map wasn't looking
 * (user: "the old terrain should always be viewable until the new terrain is in, even if it was offscreen"); else the
 * current one. Never another atlas's: its tile key differs.
 *
 * @param kept The backdrop's version until now.
 * @param current The ground's version now (terrainVersion).
 * @param busy A job is running.
 */
export function backdropVersion(kept: string, current: string, busy: boolean): string {
	const atlas = (v: string) => v.slice(0, v.lastIndexOf("-")); // (the tile key: this run of the app and atlas)
	return busy && atlas(kept) === atlas(current) ? kept : current;
}

export const PREFETCH_TILES = 340; // the most ground tiles fetched ahead (every level down to where the atlas needs more)
export const PREFETCH_PARALLEL = 3;
export const PREFETCH_DELAY_MS = 1500;

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
