import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// (read from disk: the test runner hands CSS imports back empty)
const css = readFileSync(resolve(process.cwd(), "src/theme/Theme.css"), "utf8");

/** The rule for a selector, as written in Theme.css. */
function rule(selector: string): string {
	const at = css.indexOf(`${selector} {`);
	return at < 0 ? "" : css.slice(at, css.indexOf("}", at));
}

describe("Theme.css: the game's controls keep a keyboard focus mark", () => {
	// (their own box-shadow and outline resets took Tailwind's focus ring away: CodeRabbit)
	for (const s of [".poe-btn:focus-visible", ".poe-icon-btn:focus-visible", ".poe-dropbox:focus-visible"])
		it(s, () => expect(rule(s)).toMatch(/outline: 2px solid/));

	it("a tab's focus mark follows its shape (a glow, not a box: user)", () =>
		expect(rule(".poe-tab:focus-visible")).toMatch(/drop-shadow/));
});
