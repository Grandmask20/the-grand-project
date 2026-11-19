/** GET /api/bookmarks: bookmarks by group. */
export interface Bookmarks {
	groups: BookmarkGroup[];
}

export interface BookmarkGroup {
	name: string;
	hidden: boolean;
	items: Bookmark[];
}

/** A saved route: its first and last map's numbers when saved, how many maps it runs, and the line along its paths
 * (atlas units), kept so it draws and fits after the atlas is rebuilt. */
export interface SavedRoute {
	from: number;
	to: number;
	maps: number;
	line: [number, number][];
}

export interface Bookmark {
	id: number;
	name: string;
	note: string;
	x: number;
	y: number;
	created: string;
	hidden: boolean;
	shown: boolean;
	/** A saved route (Route in the top bar, Save route): no pin, its line on the map. */
	route?: SavedRoute;
}

export interface BookmarkDraft {
	x: number;
	y: number;
	name: string;
	group: string;
	note: string;
	route?: SavedRoute;
}
