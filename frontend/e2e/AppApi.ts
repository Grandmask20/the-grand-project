import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page } from "@playwright/test";

/** What the browser tests share: the app's API (as the page calls it), waiting for its jobs, the test material. */

/** Where tests/e2e_atlas.py put the atlas and the screenshots to add. */
export const RUN = process.env.E2E_RUN ?? "";
export const E2E_ATLAS = join(RUN, "e2e", "atlas.json");

/** The screenshots of one made-up set (tests/e2e_atlas.py: SHOT_SETS), or the real crawl ones ("crawl"). */
export function shots(set: string): string[] {
	const dir = set === "crawl" ? join(RUN, "crawl") : join(RUN, "shots", set);
	if (!existsSync(dir)) return [];
	return readdirSync(dir)
		.filter((n) => n.endsWith(".png"))
		.sort()
		.map((n) => join(dir, n));
}

export const name = (path: string) => path.split(/[\\/]/).at(-1) ?? path;

export interface State {
	busy: boolean;
	progress: string | null;
	atlas: { name: string; path: string; maps: number; shots: number } | null;
	waiting: { name: string }[];
	questions: { id: number }[];
	undo: string[][];
	log: string[];
	watch: { on: boolean; folder: string };
}

export async function get<T>(page: Page, path: string): Promise<T> {
	const r = await page.request.get(path);
	expect(r.ok(), `GET ${path}: ${r.status()}`).toBe(true);
	return (await r.json()) as T;
}

/** A change, as the page sends it (the X-Grand header). Returns the status and the answer. */
export async function post(page: Page, path: string, body: unknown = {}) {
	const r = await page.request.post(path, { data: body, headers: { "X-Grand": "1" } });
	return { status: r.status(), body: (await r.json().catch(() => null)) as Record<string, unknown> | null };
}

export const state = (page: Page) => get<State>(page, "/api/state");

/**
 * Wait until the app has no job queued or running. A question it asks meanwhile (a weak match) is answered Yes in
 * the page, as a player would.
 */
export async function waitIdle(page: Page, timeoutMs = 150_000): Promise<State> {
	const end = Date.now() + timeoutMs;
	for (;;) {
		const s = await state(page);
		if (!s.busy && !s.questions.length) return s;
		if (s.questions.length) {
			const yes = page.getByRole("dialog").getByRole("button", { name: "Yes" });
			if (await yes.isVisible().catch(() => false)) await yes.click();
		}
		if (Date.now() > end) throw new Error(`still busy after ${timeoutMs / 1000} s: ${s.progress}`);
		await page.waitForTimeout(500);
	}
}

/** Open an atlas (a new one when `fresh`) and load the page on it. */
export async function useAtlas(page: Page, path: string, fresh = false) {
	await waitIdle(page);
	const r = await post(page, fresh ? "/api/atlas/new" : "/api/atlas/open", { path });
	expect(r.status, JSON.stringify(r.body)).toBe(200);
	await page.goto("/");
	await expect(page.getByRole("button", { name: /^Atlas: / })).toBeVisible();
}

/** Lines of the log that mention a screenshot. */
export const linesOf = (log: string[], file: string) => log.filter((l) => l.includes(name(file)));
