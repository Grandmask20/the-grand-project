import type { ItemKind } from "@/domain/map/ItemKind";

/** One row of Find's results. */
export interface ResultRow {
	kind: ItemKind;
	id: number;
	label: string;
	x: number;
	y: number;
}

/** GET /api/search: coordinates go there, anything else lists results. */
export type SearchResult = { goto: [number, number] } | { results: ResultRow[] };
