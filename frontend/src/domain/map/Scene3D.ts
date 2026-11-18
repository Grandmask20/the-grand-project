/**
 * GET /api/scene3d: the 3D view's icons, paths and models, whole (what the filters show, atlas units). Made from the
 * same features as the vector tiles, once per model / filter / map image version (and timelapse plan).
 */
export interface Scene3D {
	/** [x, y, id, name, slot (place in its row), lift (atlas units: the model top under it), step (-1: always)] */
	icons: [number, number, number, string, number, number, number][];
	paths: { id: number; strong: boolean; abyss: boolean; step: number; pts: [number, number][] }[];
	models: {
		rings: [number, number][][];
		colour: string;
		/** metres (MapLibre's 3D units) */
		base: number;
		height: number;
		ax: number;
		ay: number;
		step: number;
		/** what a click on it selects: "node:<i>", "landmark:<i>" or "" */
		pick: string;
	}[];
}
