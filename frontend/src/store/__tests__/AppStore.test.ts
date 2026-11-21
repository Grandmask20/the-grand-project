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

	it("a saved route lit up and a selection put each other out; leaving Bookmarks ends changing a route", () => {
		const s = useAppStore.getState();
		s.select({ kind: "node", id: 1, x: 0, y: 0 } as never);
		s.lightRoute(5);
		expect(useAppStore.getState()).toMatchObject({ routeLit: 5, selected: null });
		s.select(null);
		expect(useAppStore.getState().routeLit).toBeNull();
		s.setTab("bookmarks");
		s.setMode({ kind: "route-edit", id: 5 });
		s.setTab("find");
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("a saved route deleted ends tracking it, lighting it up and adjusting it; other routes stay", () => {
		const s = useAppStore.getState();
		s.setRoute({ path: [1, 2], message: "", at: 0, saved: 5 });
		s.lightRoute(5);
		s.setMode({ kind: "route-edit", id: 5 });
		s.bookmarksAre(new Set([5, 6]));
		expect(useAppStore.getState()).toMatchObject({ routeLit: 5, mode: { kind: "route-edit" } });
		s.bookmarksAre(new Set([6]));
		expect(useAppStore.getState()).toMatchObject({ route: null, routeLit: null, mode: { kind: "normal" } });
		s.setRoute({ path: [1, 2], message: "", at: 0 }); // (Track now: not a saved route)
		s.bookmarksAre(new Set());
		expect(useAppStore.getState().route).not.toBeNull();
	});

	it("lighting another route ends adjusting the first; another atlas lets go of held settings (review)", () => {
		const s = useAppStore.getState();
		s.setMode({ kind: "route-edit", id: 5 });
		s.lightRoute(5);
		expect(useAppStore.getState().mode).toEqual({ kind: "route-edit", id: 5 });
		s.lightRoute(6);
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		s.hold("Paths");
		s.resetAtlas();
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("another atlas closes the Re-check prompt asked about the one before (self review)", () => {
		const s = useAppStore.getState();
		s.askRecheck("/atlases/a/atlas.json");
		s.resetAtlas();
		expect(useAppStore.getState().recheckAtlas).toBeNull();
	});

	it("tracking another route ends adjusting one; tracking the same one doesn't (CodeRabbit)", () => {
		const s = useAppStore.getState();
		s.setMode({ kind: "route-edit", id: 5 });
		s.setRoute({ path: [1, 2], message: "", at: 0, saved: 5 });
		expect(useAppStore.getState().mode).toEqual({ kind: "route-edit", id: 5 });
		s.setRoute({ path: [3, 4], message: "", at: 0, saved: 6 });
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
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

	it("drops a click's selection when something newer was selected meanwhile (CodeRabbit)", async () => {
		const s = useAppStore.getState();
		let answerA: (v: never) => void = () => undefined;
		const a = s.selectLoaded(new Promise((r) => (answerA = r)));
		await s.selectLoaded(Promise.resolve({ kind: "node", id: 2 } as never)); // B, clicked after A, comes first
		answerA({ kind: "node", id: 1 } as never);
		await a;
		expect(useAppStore.getState().selected).toMatchObject({ id: 2 });
	});

	it("drops a click's selection still loading when another atlas opens (CodeRabbit)", async () => {
		const s = useAppStore.getState();
		let answer: (v: never) => void = () => undefined;
		const loading = s.selectLoaded(new Promise((r) => (answer = r)));
		s.resetAtlas();
		answer({ kind: "node", id: 1 } as never);
		await loading;
		expect(useAppStore.getState().selected).toBeNull();
	});
});
