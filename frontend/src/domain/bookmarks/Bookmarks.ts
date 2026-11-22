/** GET /api/bookmarks: bookmarks by group. */
export interface Bookmarks {
	groups: BookmarkGroup[];
}

export interface BookmarkGroup {
	name: string;
	hidden: boolean;
	/** Folded shut in the Bookmarks tab (kept per atlas). */
	folded?: boolean;
	/** Its own look: a colour ("#rrggbb") and an icon (a map icon's or place's raw name); its bookmarks without one of
	 * their own take it. */
	colour?: string;
	icon?: string;
	/** Its icon without a ring of its colour. */
	plain?: boolean;
	items: Bookmark[];
}

/** A leg of a saved route: its maps' spots and the line along its paths (atlas units). */
export interface RouteLeg {
	maps: [number, number][];
	line: [number, number][];
}

/** A saved route: its first and last map's numbers, how many maps it runs, and its legs (the main one, then a branch
 * for each map added off its side), kept by spot so it draws, fits and is tracked after the atlas is rebuilt. One
 * saved before branches has its one `line` instead. */
export interface SavedRoute {
	from: number;
	to: number;
	maps: number;
	legs?: RouteLeg[];
	line?: [number, number][];
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
	/** Its own look (none: its group's, then the page's); `plain`: its icon without a ring. */
	colour?: string;
	icon?: string;
	plain?: boolean;
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
	/** Its own look ("": none); left out, an edit keeps it as it is. */
	colour?: string;
	icon?: string;
	plain?: boolean;
}
