import { describe, expect, it } from "vitest";
import { pressAt, pressMove, wasDrag } from "@/logic/map/PanGuard";

describe("PanGuard", () => {
	it("a press that moved is a pan, a wobble is still a click, and each press starts again", () => {
		pressAt(100, 100);
		pressMove(102, 101);
		expect(wasDrag()).toBe(false);
		pressMove(160, 130);
		pressMove(101, 100); // (back where it began: still a pan)
		expect(wasDrag()).toBe(true);
		pressAt(50, 50);
		expect(wasDrag()).toBe(false);
	});
});
