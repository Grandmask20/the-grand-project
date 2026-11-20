import type { ItemKind } from "@/domain/map/ItemKind";

/** An item's details (GET /api/info, POST /api/pick). */
export interface ItemInfo {
	kind: ItemKind;
	id: number;
	title: string;
	lines: string[];
	x: number;
	y: number;
	node?: number | null;
	/** A path's points (atlas units). */
	line?: [number, number][];
	icon?: string;
	landmark_kind?: string;
	removed?: boolean;
	city_type?: string | null;
	city_types?: string[];
	name?: string;
	group?: string;
	note?: string;
	/** The id of the bookmark on this spot (a map, icon or landmark), and the bookmark itself. */
	bookmark?: number | null;
	bookmark_of?: { id: number; name: string; group: string; note: string } | null;
	suggest?: { name: string; group: string } | null;
}
