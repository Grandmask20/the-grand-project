import { describe, expect, it } from "vitest";
import { Assembler, FRAME, toFrames } from "@/logic/share/Wire";

describe("Wire", () => {
	it("a small message is one frame", () => {
		const f = toFrames({ t: "pos", player: null }, 7);
		expect(f).toEqual(['7:0:1:{"t":"pos","player":null}']);
		expect(new Assembler().push(f[0])).toEqual({ t: "pos", player: null });
	});

	it("a big one is cut into frames, put back whole once all are in, in any order", () => {
		const big = { t: "atlas", data: "x".repeat(FRAME * 2 + 5) };
		const f = toFrames(big, 3);
		expect(f).toHaveLength(3);
		const a = new Assembler();
		expect(a.push(f[2])).toBeUndefined();
		expect(a.push(f[0])).toBeUndefined();
		expect(a.push(f[1])).toEqual(big);
	});

	it("two messages' frames mixed come out each whole; what isn't a frame is ignored", () => {
		const a = new Assembler();
		const one = toFrames({ n: 1, s: "a".repeat(FRAME) }, 1);
		const two = toFrames({ n: 2 }, 2);
		expect(a.push(one[0])).toBeUndefined();
		expect(a.push(two[0])).toEqual({ n: 2 });
		expect(a.push(one[1])).toMatchObject({ n: 1 });
		expect(a.push("hello")).toBeUndefined();
		expect(a.push("1:5:2:x")).toBeUndefined();
	});
});
