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
	/** When GitHub may be asked again (s since 1970; 0: now): at most once a minute, its limit. */
	next: number;
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
	/** Goes up with each change, within one run of the app (`run`: when it started): the newest status, by (run,
	 * seq), wins over one that comes later but is older. */
	seq: number;
	run: number;
}
