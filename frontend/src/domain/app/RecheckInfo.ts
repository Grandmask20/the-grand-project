/** What the Re-check prompt says about an atlas (GET /api/atlas/recheck-info). */
export interface RecheckInfo {
	/** The last whole-atlas Re-check (time in s since 1970); null: none recorded (before 1.23). */
	last_check: { time: number; version: string } | null;
	shots: number;
	/** Screenshots that will be detected again (their detection is from an older detector, or gone). */
	detect: number;
	/** Screenshots whose file is gone: their old detection is used as it is. */
	missing: number;
	/** About how long the Re-check takes, in s. */
	estimate_s: number;
	/** The screenshots by the version that detected them, newest first (version null: before 1.23). */
	groups: { version: string | null; fresh: boolean; count: number; newest: number; oldest: number }[];
	/** The slim down's tick: the copies of screenshots in dump (owning no spot of the map) there now. */
	slim?: { count: number; mb: number };
}
