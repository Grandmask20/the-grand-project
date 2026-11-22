import type { ItemKind } from "@/domain/map/ItemKind";

/** A map icon of a result's map: its raw name (its picture) and its name as the page shows it. */
export interface ResultIcon {
	name: string;
	label: string;
}

/** One row of Find's results: named as the page names it, with its picture, the map it is on and that map's icons. */
export interface ResultRow {
	kind: ItemKind;
	id: number;
	label: string;
	x: number;
	y: number;
	/** The raw name of its icon picture (none: the page's own, a map's art or a bookmark's sign). */
	icon?: string | null;
	/** The map it is (a map) or is on. */
	map?: number | null;
	/** That map's icons. */
	icons?: ResultIcon[];
	/** A line under its name: where it is, a bookmark's group, a city's type. */
	note?: string;
	/** A bookmark is on it. */
	bookmarked?: boolean;
	/** The middle of the map it is on, where its picture is cut (none: where it is; a tower, a map itself). */
	at?: [number, number] | null;
}

/** GET /api/search: coordinates go there, anything else lists results. */
export type SearchResult = { goto: [number, number] } | { results: ResultRow[] };
