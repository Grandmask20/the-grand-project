import { describe, expect, it } from "vitest";
import { bookmarkLook } from "@/logic/BookmarkLook";

describe("bookmarkLook (a bookmark's look as drawn)", () => {
	const group = { colour: "#112233", icon: "Breach", plain: true };

	it("takes its group's look where it has none of its own", () => {
		expect(bookmarkLook({}, group)).toEqual({ colour: "#112233", icon: "Breach", plain: true });
		expect(bookmarkLook({}, {})).toEqual({ colour: "", icon: "", plain: false });
	});

	it("a colour of its own brings its ring back on its group's ringless icon (CodeRabbit)", () => {
		expect(bookmarkLook({ colour: "#ff0000" }, group)).toEqual({ colour: "#ff0000", icon: "Breach", plain: false });
	});

	it("\"none\" of its own takes the ring off its group's icon (it wasn't kept: CodeRabbit)", () => {
		expect(bookmarkLook({ plain: true }, { icon: "Breach" })).toEqual({ colour: "", icon: "Breach", plain: true });
	});

	it("an icon of its own without a colour choice keeps its group's ring choice", () => {
		expect(bookmarkLook({ icon: "sym:star" }, group).plain).toBe(true);
	});
});
