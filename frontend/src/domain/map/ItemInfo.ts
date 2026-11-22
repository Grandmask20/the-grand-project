import type { ResultIcon } from "@/domain/find/SearchResult";
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
	bookmark_of?: {
		id: number;
		name: string;
		group: string;
		note: string;
		colour?: string;
		icon?: string;
		plain?: boolean;
	} | null;
	/** A bookmark's own look ("": none). */
	colour?: string;
	plain?: boolean;
	suggest?: { name: string; group: string } | null;
	/** A map's heading without its icons ("Map #233", "Ezomyte city (map #233)"), its icons, the maps its paths lead
	 * to and those paths' lines (the selection's box over the map; they light up with it). */
	heading?: string;
	/** A map added by hand (deleting it takes it away for good). */
	added?: boolean;
	icons?: ResultIcon[];
	connected?: number[];
	links?: [number, number][][];
	/** A map's landmark (a City on it...), changed from the map's menu: a click on a landmark selects its map. */
	on_landmark?: OnLandmark;
}

/** A landmark as its map shows it: what its edits need. */
export interface OnLandmark {
	id: number;
	title: string;
	x: number;
	y: number;
	landmark_kind: string;
	city_type: string | null;
}
