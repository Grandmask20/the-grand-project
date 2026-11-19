import { describe, expect, it } from "vitest";
import { duration } from "@/utils/Format";

describe("duration", () => {
	it("carries rounded seconds into the minutes (CodeRabbit)", () => {
		expect(duration(119.6)).toBe("2:00");
		expect(duration(59.6)).toBe("1:00");
		expect(duration(65)).toBe("1:05");
		expect(duration(12.2)).toBe("12 s");
	});
});
