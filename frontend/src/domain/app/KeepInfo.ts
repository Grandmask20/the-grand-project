/** What the "Keep copies" prompt says about the open atlas (GET /api/atlas/keep-info): its screenshots' 1080p copies
 * in the atlas folder's terrain/, the detected originals moved to used/ (safe to delete then). */
export interface KeepInfo {
	shots: number;
	/** Screenshots with a copy kept already. */
	copied: number;
	/** Screenshots to copy: the file there, no copy yet. */
	todo: number;
	/** Screenshots gone with no copy: their picture is lost. */
	lost: number;
	/** Screenshots in the atlas's own folder: moved to used/ once copied. */
	move: number;
	/** The copies' estimated size (MB) and time (s). */
	mb: number;
	seconds: number;
}
