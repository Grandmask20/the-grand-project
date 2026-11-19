import { describe, expect, it } from "vitest";
import { FrameLog } from "@/logic/FrameLog";

describe("FrameLog", () => {
	it("writes one CSV row per frame", () => {
		const log = new FrameLog();
		log.frame(3.5, "moving");
		log.frame(3.6);
		const lines = log.csv().trim().split("\n");
		expect(lines[0]).toBe("time_ms,frame_ms,zoom,note");
		expect(lines).toHaveLength(3);
		expect(lines[1].endsWith(",0,3.5,moving")).toBe(true);
		expect(log.size).toBe(2);
		expect(log.stalls(1e9)).toBe(0);
	});
});
