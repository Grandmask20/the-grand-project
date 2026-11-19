import { describe, expect, it } from "vitest";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import { nodeInfo } from "@/test/Fixtures";

const onMap = { id: 0, name: "big boss", group: "Boss", note: "daily" };

describe("bookmarkOf", () => {
	it("is the bookmark that came with a bookmarked map's details", () => {
		expect(bookmarkOf({ ...nodeInfo, bookmark: 0, bookmark_of: onMap })).toEqual({
			id: 0,
			x: 440,
			y: 200,
			name: "big boss",
			group: "Boss",
			note: "daily",
		});
	});

	it("is null for a map without one, a path, or nothing (no guess from an id alone: CodeRabbit)", () => {
		expect(bookmarkOf(nodeInfo)).toBeNull();
		expect(bookmarkOf({ ...nodeInfo, kind: "path", bookmark_of: onMap })).toBeNull();
		expect(bookmarkOf(null)).toBeNull();
		expect(bookmarkOf({ ...nodeInfo, bookmark: 3 })).toBeNull();
	});

	it("is the bookmark itself for a bookmark pin", () => {
		const pin = { ...nodeInfo, kind: "bookmark" as const, id: 0, name: "big boss", group: "Boss", note: "daily" };
		expect(bookmarkOf(pin)).toMatchObject({ id: 0, name: "big boss", group: "Boss", note: "daily" });
	});
});

describe("newBookmark", () => {
	it("goes on the map with its suggested name, or on the spot when nothing is there", () => {
		expect(newBookmark(nodeInfo, [0, 0])).toMatchObject({ id: null, x: 440, y: 200, name: "Breach", group: "Breach" });
		expect(newBookmark(null, [5, 6])).toEqual({ id: null, x: 5, y: 6, name: "", group: "Other", note: "" });
	});
});
