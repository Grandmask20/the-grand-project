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
	terrain_version: number;
	model_version: number;
	filter_version: number;
	sprite: { size: number; units: number; min_px: number };
}
