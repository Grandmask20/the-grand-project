import { describe, expect, it } from "vitest";
import { pageChanges } from "@/hooks/app/UsePageLog";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo } from "@/test/Fixtures";

describe("pageChanges", () => {
	it("names what changed on the page", () => {
		const before = useAppStore.getState();
		const after = {
			...before,
			tab: "bookmarks",
			mode: { kind: "bookmark" as const },
			selected: nodeInfo,
			error: "no maps inside the lasso",
		};
		// in plain words, no ids (user: the log has to make sense to players)
		expect(pageChanges(after, before)).toEqual([
			"Opened the Bookmarks tab",
			"Add bookmark started",
			"Selected Map #12: Breach",
			"Error shown: no maps inside the lasso",
		]);
		expect(pageChanges({ ...before, mode: { kind: "normal" } }, { ...before, mode: { kind: "lasso" } })).toEqual([
			"Biome select ended",
		]);
		// a file or folder picker too (CodeRabbit: opening one wasn't logged)
		const pick = { title: "Open your screenshot folder", folders: true, onPick: () => {} };
		expect(pageChanges({ ...before, filePick: pick }, before)).toEqual(["Open your screenshot folder: dialog opened"]);
		expect(pageChanges(before, before)).toEqual([]);
	});

	it("says what happened to the route (user: Route here left no line)", () => {
		const st = useAppStore.getState();
		const at = (route: typeof st.route) => ({ ...st, route });
		const tracked = { path: [4, 5, 6], message: "2 maps left", at: 0 };
		expect(pageChanges(at(tracked), at(null))).toEqual(["Tracking a route: map #4 to map #6, 2 maps left"]);
		expect(pageChanges(at({ ...tracked, at: 1, message: "1 map left" }), at(tracked))).toEqual([
			"Next map: on map #5, 1 map left",
		]);
		expect(pageChanges(at(null), at(tracked))).toEqual(["Stopped tracking the route"]);
		expect(pageChanges(at({ ...tracked, saved: 3 }), at(null))[0]).toMatch(/^Tracking a saved route/);
		expect(pageChanges(at({ path: [], message: "No reachable map with Breach." }), at(null))).toEqual([
			"Route: No reachable map with Breach.",
		]);
	});

	it("a map mode refused in the timelapse is said, so it is logged", () => {
		useAppStore.setState({ replay: {} as never });
		useAppStore.getState().setMode({ kind: "player" });
		expect(useAppStore.getState()).toMatchObject({ mode: { kind: "normal" }, errorBrief: true });
		expect(useAppStore.getState().error).toMatch(/timelapse is open/);
		useAppStore.setState({ replay: null, error: null });
	});
});
