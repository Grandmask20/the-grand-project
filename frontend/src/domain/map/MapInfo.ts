/** The map image's grid: atlas (x, y) is image px ((x - x0) * scale, (y - y0) * scale). */
export interface GridInfo {
	x0: number;
	y0: number;
	scale: number;
	width: number;
	height: number;
}

/** GET /api/map (also in the state): the grid, zoom range and versions of the map's tiles. */
export interface MapInfo {
	grid: GridInfo;
	zmax: number;
	zdeep: number;
	world: number;
	offset: number;
	maxzoom: number;
	bounds: [[number, number], [number, number]];
	/** This run of the app and the open atlas: in every tile URL, so tiles of another run or atlas never come back from the browser's cache. */
	tile_key: string;
	terrain_version: number;
	model_version: number;
	filter_version: number;
	sprite: { size: number; units: number; min_px: number };
}
