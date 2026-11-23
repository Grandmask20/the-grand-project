import { describe, expect, it } from "vitest";
import { ago, duration, recheckLines } from "@/logic/Recheck";

describe("Recheck", () => {
	it("says how long ago, in words", () => {
		expect(ago(1000, 1030)).toBe("just now");
		expect(ago(0, 60)).toBe("1 minute ago");
		expect(ago(0, 7200)).toBe("2 hours ago");
		expect(ago(0, 86400 * 3)).toBe("3 days ago");
		expect(ago(0, 86400 * 90)).toBe("3 months ago");
	});

	it("says a duration, in words", () => {
		expect(duration(20)).toBe("under a minute");
		expect(duration(65)).toBe("about 1 minute");
		expect(duration(1525)).toBe("about 25 minutes");
		expect(duration(5100)).toBe("about 1 h 25 min");
	});

	it("says when nothing needs detecting again, and when no Re-check was recorded", () => {
		const lines = recheckLines({ last_check: null, shots: 5, detect: 0, missing: 0, estimate_s: 2, groups: [] }, 1000);
		expect(lines.last).toMatch(/not recorded/);
		expect(lines.work).toMatch(/only the whole-atlas clean-up runs/);
	});
});
