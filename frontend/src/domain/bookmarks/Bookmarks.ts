/** GET /api/bookmarks: bookmarks by group. */
export interface Bookmarks {
	groups: BookmarkGroup[];
}

export interface BookmarkGroup {
	name: string;
	hidden: boolean;
	items: Bookmark[];
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
}

export interface BookmarkDraft {
	x: number;
	y: number;
	name: string;
	group: string;
	note: string;
}
