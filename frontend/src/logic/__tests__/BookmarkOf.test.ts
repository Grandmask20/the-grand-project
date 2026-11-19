import { describe, expect, it } from "vitest";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import { bookmarks, nodeInfo } from "@/test/Fixtures";

describe("bookmarkOf", () => {
	it("finds the bookmark on a bookmarked map", () => {
		expect(bookmarkOf({ ...nodeInfo, bookmark: 0 }, bookmarks)).toEqual({
			id: 0,
			x: 10,
			y: 20,
			name: "big boss",
			group: "Boss",
			note: "daily",
		});
	});

	it("is null for a map without one, a path, nothing, or a bookmark just removed", () => {
		expect(bookmarkOf(nodeInfo, bookmarks)).toBeNull();
		expect(bookmarkOf({ ...nodeInfo, kind: "path" }, bookmarks)).toBeNull();
		expect(bookmarkOf(null, bookmarks)).toBeNull();
		expect(bookmarkOf({ ...nodeInfo, bookmark: 7 }, bookmarks)).toBeNull();
	});

	it("is the bookmark itself for a bookmark pin, and keeps the id before the list loads", () => {
		const pin = { ...nodeInfo, kind: "bookmark" as const, id: 0, name: "big boss", group: "Boss", note: "daily" };
		expect(bookmarkOf(pin, undefined)?.id).toBe(0);
		expect(bookmarkOf({ ...nodeInfo, bookmark: 3 }, undefined)?.id).toBe(3);
	});
});

describe("newBookmark", () => {
	it("goes on the map with its suggested name, or on the spot when nothing is there", () => {
		expect(newBookmark(nodeInfo, [0, 0])).toMatchObject({ id: null, x: 440, y: 200, name: "Breach", group: "Breach" });
		expect(newBookmark(null, [5, 6])).toEqual({ id: null, x: 5, y: 6, name: "", group: "Other", note: "" });
	});
});
