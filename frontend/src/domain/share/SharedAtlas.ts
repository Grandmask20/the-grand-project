/** Where the player is on their atlas (I'm here). */
export interface SharedPlayer {
	x: number;
	y: number;
	node: number;
}

/**
 * What goes over a live link: the sharer's name; their atlas, whole, each time it changes (the atlas file, their
 * map image's frame and their view, packed by their app: GET /api/share/atlas); where they are; their route.
 */
export type ShareMessage =
	| { t: "hello"; name: string }
	| { t: "atlas"; name: string; file: string }
	| { t: "pos"; player: SharedPlayer | null }
	| { t: "route"; path: number[] | null };

/** A friend's atlas kept by this app (GET /api/friends). */
export interface FriendAtlasCard {
	name: string;
	/** Its atlas file here (open it as any). */
	json: string;
	/** When it last came (s). */
	updated: number | null;
	open: boolean;
	maps: number | null;
}

/** The Atlases tab's friends' atlases, and your own atlas to go back to (null: none). */
export interface FriendAtlases {
	friends: FriendAtlasCard[];
	own: string | null;
}
