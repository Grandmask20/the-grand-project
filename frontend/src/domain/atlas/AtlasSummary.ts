/** The open atlas and its counts. */
export interface AtlasSummary {
	name: string;
	path: string;
	maps: number;
	icons: number;
	shots: number;
	landmarks: number;
	bookmarks: number;
	/** A friend's atlas from live sharing (their name): read-only, shown with their view. */
	friend?: string | null;
}
