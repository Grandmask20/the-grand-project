import type { RecheckInfo } from "@/domain/app/RecheckInfo";

/** How long ago a time (s since 1970) was, in words: "just now", "5 minutes ago", "3 days ago". */
export function ago(t: number, now: number = Date.now() / 1000): string {
	const s = Math.max(0, now - t);
	const say = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;
	if (s < 60) return "just now";
	if (s < 3600) return say(Math.floor(s / 60), "minute");
	if (s < 86400) return say(Math.floor(s / 3600), "hour");
	if (s < 86400 * 60) return say(Math.floor(s / 86400), "day");
	return say(Math.floor(s / (86400 * 30)), "month");
}

/** A duration in words: "under a minute", "about 4 minutes", "about 1 h 25 min". */
export function duration(s: number): string {
	if (s < 60) return "under a minute";
	const m = Math.round(s / 60);
	if (m < 60) return `about ${m} minute${m === 1 ? "" : "s"}`;
	return `about ${Math.floor(m / 60)} h ${m % 60} min`;
}

const version = (v: string | null) => (v ? `v${v}` : "an unrecorded version (before 1.23)");

/** The Re-check prompt's lines (user: since when the atlas was checked, its screenshots in groups by when and on
 * which version they were detected, how many will be detected again and how long it may take). */
export function recheckLines(info: RecheckInfo, now: number = Date.now() / 1000) {
	const last = info.last_check
		? `${ago(info.last_check.time, now)} (v${info.last_check.version})`
		: "not recorded (re-checks before 1.23 weren't kept)";
	const groups = info.groups.map((g) => {
		const when =
			ago(g.newest, now) === ago(g.oldest, now) ? ago(g.newest, now) : `${ago(g.oldest, now)} to ${ago(g.newest, now)}`;
		return {
			text: `${g.count} detected ${when} on ${version(g.version)}`,
			again: !g.fresh,
		};
	});
	const work =
		info.detect > 0
			? `${info.detect} of ${info.shots} screenshots will be detected again, then the whole atlas is cleaned up.`
			: `No screenshot needs detecting again: only the whole-atlas clean-up runs (${info.shots} screenshots).`;
	return { last, groups, work, time: duration(info.estimate_s) };
}
