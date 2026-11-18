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
	icon?: string;
	landmark_kind?: string;
	removed?: boolean;
	city_type?: string | null;
	city_types?: string[];
	name?: string;
	group?: string;
	note?: string;
	bookmark?: number | null;
	suggest?: { name: string; group: string } | null;
}
