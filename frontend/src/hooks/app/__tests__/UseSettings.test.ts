import { describe, expect, it } from "vitest";
import { merge } from "@/hooks/app/UseSettings";
import { state } from "@/test/Fixtures";

describe("merge", () => {
	it("merges layers, style and page settings, and replaces the rest", () => {
		const s = merge(state.settings, { layers: { Removed: true }, style: { path_width: 3 }, ui: { background: "vector" }, near_only: true });
		expect(s.layers).toMatchObject({ Terrain: true, Removed: true });
		expect(s.style.path_width).toBe(3);
		expect(s.style.path_style).toBe("solid");
		expect(s.ui.background).toBe("vector");
		expect(s.near_only).toBe(true);
	});

	it("keeps the style on reset (the app answers with the defaults)", () => {
		const s = merge(state.settings, { style: { reset: true, path_width: 9 } });
		expect(s.style.path_width).toBe(0);
		expect("reset" in s.style).toBe(false);
	});
});
