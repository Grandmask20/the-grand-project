/**
 * GET /api/scene3d: the 3D view's icons, paths and models, whole (what the filters show, atlas units). Made from the
 * same features as the vector tiles, once per model / filter / map image version (and timelapse plan).
 */
export interface Scene3D {
	/** [x, y, id, name, slot (place in its row), lift (atlas units: the model top under it), step (-1: always),
	 * node (its map node, -1 for none)] */
	icons: [number, number, number, string, number, number, number, number][];
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

/**
 * The 3D icon that wears the selection ring: a selected icon itself, or for a selected map node (or a landmark, by the
 * map node it marks) the first icon standing on it, the part of a map node seen in 3D (user: clicking a city's
 * citadel lit up nothing of its map; its ring lay on the ground under the model). -1 for none.
 */
export function ringedIcon(
	selected: { kind: string; id: number; node?: number | null } | null,
	scene: Scene3D | undefined,
): number {
	if (!selected) return -1;
	if (selected.kind === "icon") return selected.id;
	const node = selected.kind === "node" ? selected.id : selected.kind === "landmark" ? selected.node : null;
	if (node == null || !scene) return -1;
	return scene.icons.find((ic) => ic[7] === node)?.[2] ?? -1;
}
