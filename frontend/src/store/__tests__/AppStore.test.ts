import { describe, expect, it } from "vitest";
import { StaleError } from "@/api/Http";
import { useAppStore } from "@/store/AppStore";

describe("useAppStore", () => {
	it("counts fly and fit requests so the same spot can be asked twice", () => {
		const s = useAppStore.getState();
		s.flyTo(1, 2);
		s.flyTo(1, 2);
		expect(useAppStore.getState().fly).toEqual({ x: 1, y: 2, px: undefined, n: 2 });
		s.requestFit();
		expect(useAppStore.getState().fitAtlas).toBe(1);
	});

	it("patches the replay only while one is open", () => {
		const s = useAppStore.getState();
		s.patchReplay({ pos: 3 });
		expect(useAppStore.getState().replay).toBeNull();
	});

	it("shows an error's message", () => {
		useAppStore.getState().showError(new Error("boom"));
		expect(useAppStore.getState().error).toBe("boom");
		useAppStore.getState().showError(null);
		expect(useAppStore.getState().error).toBeNull();
	});

	it("doesn't show an answer for the atlas open before as an error", () => {
		useAppStore.getState().showError(new StaleError());
		expect(useAppStore.getState().error).toBeNull();
	});

	it("forgets what belonged to the atlas open before", () => {
		const s = useAppStore.getState();
		s.select({ kind: "node", id: 3 } as never);
		s.setResults([{ id: 1 } as never], "Breach");
		s.setQuery("Breach");
		s.setHighlight("Breach");
		s.setMode({ kind: "lasso" });
		s.setRoute({ path: [1, 2], message: "1 map to run" });
		s.setTab("bookmarks");
		s.resetAtlas();
		const t = useAppStore.getState();
		expect([t.selected, t.results, t.query, t.highlight, t.mode, t.route]).toEqual([
			null,
			[],
			"",
			null,
			{ kind: "normal" },
			null,
		]);
		expect(t.tab).toBe("bookmarks"); // the tab stays
	});
});
