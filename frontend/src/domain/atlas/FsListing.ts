/** A folder listed for the file and folder pickers. */
export interface FsListing {
	path: string;
	parent: string | null;
	entries: FsEntry[];
	truncated: boolean;
}

export interface FsEntry {
	name: string;
	path: string;
	dir: boolean;
	size: number;
}
