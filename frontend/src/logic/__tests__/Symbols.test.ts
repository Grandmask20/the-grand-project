import { describe, expect, it } from "vitest";
import { isSymbol, SYMBOLS, symbolImage, symbolImageId, symbolPath } from "@/logic/Symbols";

describe("Symbols (a bookmark's plain symbol: sym:<name>)", () => {
	it("knows its own symbols only", () => {
		expect(isSymbol("sym:star")).toBe(true);
		expect(isSymbol("sym:castle")).toBe(false); // no such symbol
		expect(isSymbol("star")).toBe(false); // (a map icon's raw name)
		expect(isSymbol(undefined)).toBe(false);
	});

	it("gives its outline, nothing for anything else", () => {
		expect(symbolPath("sym:diamond")).toBe(SYMBOLS.diamond);
		expect(symbolPath("Abyss")).toBe("");
	});

	it("names its picture by symbol and colour, and draws none for something else", () => {
		expect(symbolImageId("sym:star", "#ff0000")).toBe("sym:star:#ff0000");
		expect(symbolImage("Abyss:#ff0000")).toBeNull();
	});
});
