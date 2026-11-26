import { describe, expect, it } from "vitest";
import { notesBlocks, notesSpans } from "@/logic/ReleaseNotes";

describe("ReleaseNotes", () => {
	it("makes headings, points and paragraphs of the notes (they showed as typed: user)", () => {
		const notes = "## 1.3.2 Hotfix\r\n\r\n- Fixed deletion of images\r\n- added image foldering\r\n\r\nThanks all.";
		expect(notesBlocks(notes)).toEqual([
			{ kind: "heading", spans: [{ text: "1.3.2 Hotfix" }] },
			{ kind: "list", items: [[{ text: "Fixed deletion of images" }], [{ text: "added image foldering" }]] },
			{ kind: "paragraph", lines: [[{ text: "Thanks all." }]] },
		]);
	});

	it("keeps a point going on an indented line, and leaves dividers out", () => {
		expect(notesBlocks("- one\n  more of it\n---\ntext")).toEqual([
			{ kind: "list", items: [[{ text: "one" }, { text: " more of it" }]] },
			{ kind: "paragraph", lines: [[{ text: "text" }]] },
		]);
	});

	it("reads bold, code and links inside a line; only http(s) addresses become links", () => {
		expect(notesSpans("a **3d view** and `start.sh`, see [the page](https://x.y/z)")).toEqual([
			{ text: "a " },
			{ text: "3d view", bold: true },
			{ text: " and " },
			{ text: "start.sh", code: true },
			{ text: ", see " },
			{ text: "the page", href: "https://x.y/z" },
		]);
		expect(notesSpans("[bad](javascript:alert(1))")).toEqual([{ text: "bad" }, { text: ")" }]);
	});
});
