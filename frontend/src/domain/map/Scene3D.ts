import { pickCode } from "@/logic/Pick";

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
 * What the 3D view lights up for the selection: a selected icon wears its ring (`icon`); a selected map node, or a
 * landmark by the map node it marks, has its model (pillar, city, hall, tower) drawn in gold (`model`, a pick code).
 * Ringing the icon on a selected map node made it look like the icon was selected (user).
 */
export function selection3d(selected: { kind: string; id: number; node?: number | null } | null): {
	icon: number;
	model: number;
} {
	if (!selected) return { icon: -1, model: 0 };
	if (selected.kind === "icon") return { icon: selected.id, model: 0 };
	if (selected.kind === "node") return { icon: -1, model: pickCode("node", selected.id) };
	if (selected.kind === "landmark")
		return {
			icon: -1,
			model: selected.node != null ? pickCode("node", selected.node) : pickCode("landmark", selected.id),
		};
	return { icon: -1, model: 0 };
}
