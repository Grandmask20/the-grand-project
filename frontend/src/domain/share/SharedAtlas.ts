import type { GraphEdge, GraphNode } from "@/domain/map/Graph";
import type { MapInfo } from "@/domain/map/MapInfo";

/** A landmark as the map shows it (GET /api/landmarks). */
export interface SharedLandmark {
	id: number;
	x: number;
	y: number;
	/** As the atlas keeps it: "Vaal city", "Tower", "Breach stronghold"... */
	kind: string;
	/** As the page names it. */
	label: string;
	/** The map it stands on (null: none). */
	node: number | null;
}

/** Where the player is on their atlas (I'm here). */
export interface SharedPlayer {
	x: number;
	y: number;
	node: number;
}

/** A friend's atlas as live sharing sends it: enough to draw it read-only, in its own map. */
export interface SharedAtlas {
	/** The atlas's name. */
	name: string;
	/** Its map's frame (the watcher's map is laid out from it, as the sharer's own). */
	info: MapInfo;
	nodes: GraphNode[];
	edges: GraphEdge[];
	landmarks: SharedLandmark[];
}

/** What goes over a live link: the sharer's name, their atlas (whole, each time it changes), their position. */
export type ShareMessage =
	| { t: "hello"; name: string }
	| { t: "atlas"; atlas: SharedAtlas }
	| { t: "pos"; player: SharedPlayer | null };
