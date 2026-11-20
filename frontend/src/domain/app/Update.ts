/** GET /api/update: the in-app update (app/updater.py). */
export interface UpdateStatus {
	/** "release" (the player build), "develop", "internal". */
	channel: string;
	/** This copy's release ("1.3"), or null for a development copy. */
	release: string | null;
	/** The program version ("1.21"). */
	program: string;
	/** It can update itself in the app; else why not (a development copy: git). */
	can: boolean;
	why: string;
	/** Check once a day when the app starts. */
	auto: boolean;
	/** When GitHub was last asked (s since 1970), or null. */
	checked: number | null;
	/** Seconds before GitHub is asked again (it's asked at most once a minute: its limit). */
	wait: number;
	state: "idle" | "checking" | "downloading" | "restarting" | "error";
	latest: { release: string; name: string; notes: string; url: string; published: string } | null;
	/** The latest release is newer than this one. */
	available: boolean;
	error: string | null;
	/** Bytes downloaded, and of how many (0: not known). */
	got: number;
	size: number;
	/** What the last update did, when the app started after one. */
	just: { ok: boolean; from?: string; to?: string; error?: string } | null;
}
