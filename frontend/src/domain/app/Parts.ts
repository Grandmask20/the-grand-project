/** One part of the map (the map image, the model): how far it is. */
export interface PartState {
	state: "waiting" | "building" | "ready" | "failed";
	/** Why it failed (null otherwise). */
	error: string | null;
	/** Seconds since the part last moved on (it beats while it works). */
	quiet: number;
}

/** GET /api/parts: the map's parts for the open atlas generation (the loading cover waits on these, not a timer). */
export interface Parts {
	generation: number;
	parts: { map_image?: PartState; model?: PartState };
}
