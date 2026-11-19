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
		expect(pageChanges(before, before)).toEqual([]);
	});
});
