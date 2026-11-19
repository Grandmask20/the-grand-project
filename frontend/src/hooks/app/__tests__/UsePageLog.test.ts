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
		expect(pageChanges(after, before)).toEqual([
			"tab bookmarks",
			"mode bookmark",
			"selected node 12: Map #12: Breach",
			"error shown: no maps inside the lasso",
		]);
		expect(pageChanges(before, before)).toEqual([]);
	});
});
