import { describe, expect, it } from "vitest";
import { notesBlocks, notesSpans, notesWithSkipped } from "@/logic/ReleaseNotes";

describe("ReleaseNotes", () => {
	it("makes headings, points and paragraphs of the notes (they showed as typed: user)", () => {
		const notes = "## 1.3.2 Hotfix\r\n\r\n- Fixed deletion of images\r\n- added image foldering\r\n\r\nThanks all.";
		expect(notesBlocks(notes)).toEqual([
			{ kind: "heading", spans: [{ text: "1.3.2 Hotfix" }] },
			{ kind: "list", items: [[{ text: "Fixed deletion of images" }], [{ text: "added image foldering" }]] },
			{ kind: "paragraph", lines: [[{ text: "Thanks all." }]] },
		]);
	});

	it("formats a point's indented next line too", () => {
		// (it showed as typed - CodeRabbit)
		expect(notesBlocks("- Fix\n  See [guide](https://x.y) and **details**")).toEqual([
			{
				kind: "list",
				items: [
					[
						{ text: "Fix" },
						{ text: " See " },
						{ text: "guide", href: "https://x.y" },
						{ text: " and " },
						{ text: "details", bold: true },
					],
				],
			},
		]);
	});

	it("adds the notes of releases skipped since this copy's, each under its own header", () => {
		const since = [
			{ name: "The Grand Project 1.3.1", notes: "## 1.3.1 Hotfix\n\n- safe deletion" },
			{ name: "The Grand Project 1.3.0b", notes: "- a point without a header" },
			{ name: "empty", notes: "  " },
		];
		expect(notesWithSkipped({ notes: "## 1.3.2\n\n- newest", since })).toBe(
			"## 1.3.2\n\n- newest\n\n## 1.3.1 Hotfix\n\n- safe deletion\n\n## The Grand Project 1.3.0b\n\n- a point without a header",
		);
		expect(notesWithSkipped({ notes: "only" })).toBe("only");
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
		expect(notesSpans("[bad](javascript:alert(1))")).toEqual([{ text: "bad" }]);
		// (one level of brackets in an address: it was cut at the first ")" - CodeRabbit)
		expect(notesSpans("[docs](https://example.com/a(b)) end")).toEqual([
			{ text: "docs", href: "https://example.com/a(b)" },
			{ text: " end" },
		]);
	});
});
